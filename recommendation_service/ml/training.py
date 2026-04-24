from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score, ndcg_score
import lightfm
from lightfm import LightFM
from lightfm.data import Dataset
import joblib
import mlflow
import structlog
from datetime import datetime, timedelta
import asyncio

from core.database import db_manager
from core.config import settings

logger = structlog.get_logger()

class MLTrainingPipeline:
    """Machine learning training pipeline for Phase 2 hybrid recommendations"""
    
    def __init__(self):
        self.dataset = Dataset()
        self.model = None
        self.item_features = None
        self.user_features = None
        
    async def collect_training_data(self, days: int = 30) -> pd.DataFrame:
        """Collect user interaction data for training"""
        async with db_manager.get_session() as session:
            from sqlalchemy import text
            
            query = text("""
                SELECT 
                    sr.seeker_id as user_id,
                    sr.provider_id as item_id,
                    sr.status,
                    sr.seeker_rating,
                    sr.created_at,
                    al.metadata as activity_metadata
                FROM service_requests sr
                LEFT JOIN activity_logs al ON 
                    al.user_id = sr.seeker_id 
                    AND al.metadata->>'provider_id' = sr.provider_id::text
                WHERE sr.created_at > NOW() - :days * INTERVAL '1 day'
                
                UNION ALL
                
                SELECT 
                    al.user_id,
                    (al.metadata->>'provider_id')::int as provider_id,
                    'view' as status,
                    NULL as rating,
                    al.created_at,
                    al.metadata
                FROM activity_logs al
                WHERE 
                    al.type = 'provider_view'
                    AND al.created_at > NOW() - :days * INTERVAL '1 day'
            """)
            
            result = await session.execute(query, {"days": days})
            rows = result.fetchall()
            
            df = pd.DataFrame(rows, columns=[
                'user_id', 'item_id', 'interaction_type', 
                'rating', 'timestamp', 'metadata'
            ])
            
            logger.info(
                "training_data_collected",
                rows=len(df),
                days=days
            )
            
            return df
    
    def prepare_features(
        self,
        df: pd.DataFrame
    ) -> Tuple[lightfm.data.Dataset, np.ndarray, np.ndarray]:
        """Prepare features for LightFM model"""
        
        # Get unique users and items
        users = df['user_id'].unique().tolist()
        items = df['item_id'].unique().tolist()
        
        # Fit dataset
        self.dataset.fit(
            users,
            items,
            item_features=['category', 'has_certificates', 'is_approved']
        )
        
        # Create interactions matrix
        interactions, weights = self.dataset.build_interactions(
            [(row.user_id, row.item_id, 1.0) for _, row in df.iterrows()]
        )
        
        # Create item features
        item_features = self._build_item_features(items)
        
        return interactions, weights, item_features
    
    def _build_item_features(self, items: List[int]) -> np.ndarray:
        """Build item features matrix"""
        async def _get_features():
            async with db_manager.get_session() as session:
                from sqlalchemy import text
                
                query = text("""
                    SELECT 
                        id,
                        category,
                        CASE WHEN certificates IS NOT NULL AND jsonb_array_length(certificates) > 0 
                             THEN 1 ELSE 0 END as has_certificates,
                        CASE WHEN is_approved THEN 1 ELSE 0 END as is_approved
                    FROM provider_profiles
                    WHERE id = ANY(:items)
                """)
                
                result = await session.execute(query, {"items": items})
                features_data = result.fetchall()
                
                # Create feature matrix
                feature_list = []
                for item in items:
                    item_data = next((f for f in features_data if f.id == item), None)
                    if item_data:
                        features = [
                            f"category:{item_data.category}",
                            f"has_certificates:{item_data.has_certificates}",
                            f"is_approved:{item_data.is_approved}"
                        ]
                    else:
                        features = []
                    feature_list.append(features)
                
                return self.dataset.build_item_features(
                    [(item_id, features) for item_id, features in zip(items, feature_list)]
                )
        
        return asyncio.run(_get_features())
    
    @mlflow.start_run
    async def train_model(
        self,
        epochs: int = 30,
        learning_rate: float = 0.05,
        loss: str = 'warp'
    ):
        """Train LightFM model with MLflow tracking"""
        
        # Log parameters
        mlflow.log_param("epochs", epochs)
        mlflow.log_param("learning_rate", learning_rate)
        mlflow.log_param("loss", loss)
        
        # Collect data
        df = await self.collect_training_data()
        
        if len(df) < settings.min_interactions_for_ml:
            logger.warning(
                "insufficient_training_data",
                current=len(df),
                required=settings.min_interactions_for_ml
            )
            return None
        
        # Prepare features
        interactions, weights, item_features = self.prepare_features(df)
        
        # Split data
        train, test = train_test_split(
            np.arange(interactions.shape[0]),
            test_size=0.2,
            random_state=42
        )
        
        # Initialize model
        model = LightFM(
            no_components=64,
            learning_rate=learning_rate,
            loss=loss,
            random_state=42
        )
        
        # Train model
        for epoch in range(epochs):
            model.fit_partial(
                interactions[train],
                item_features=item_features,
                epochs=1,
                num_threads=4
            )
            
            # Evaluate
            train_precision = self._evaluate_model(
                model,
                interactions[train],
                item_features,
                k=10
            )
            
            test_precision = self._evaluate_model(
                model,
                interactions[test],
                item_features,
                k=10
            )
            
            mlflow.log_metric("train_precision", train_precision, step=epoch)
            mlflow.log_metric("test_precision", test_precision, step=epoch)
            
            logger.info(
                "training_epoch",
                epoch=epoch,
                train_precision=train_precision,
                test_precision=test_precision
            )
        
        # Save model
        self.model = model
        self.item_features = item_features
        
        # Save model artifact
        model_path = f"{settings.model_path}/lightfm_model_{datetime.now().strftime('%Y%m%d_%H%M%S')}.joblib"
        joblib.dump(model, model_path)
        mlflow.log_artifact(model_path)
        
        logger.info(
            "model_training_completed",
            final_train_precision=train_precision,
            final_test_precision=test_precision,
            model_path=model_path
        )
        
        return model
    
    def _evaluate_model(
        self,
        model,
        interactions,
        item_features,
        k: int = 10
    ) -> float:
        """Evaluate model precision at k"""
        n_users, n_items = interactions.shape
        
        # Get scores for all items
        scores = model.predict(
            np.repeat(np.arange(n_users), n_items),
            np.tile(np.arange(n_items), n_users),
            item_features=item_features
        ).reshape(n_users, n_items)
        
        # Calculate precision@k
        precisions = []
        for user_id in range(n_users):
            # Get known positive items
            known_positives = interactions[user_id].indices
            
            if len(known_positives) == 0:
                continue
            
            # Get top k recommendations
            top_k = np.argsort(-scores[user_id])[:k]
            
            # Calculate precision
            precision = len(set(top_k) & set(known_positives)) / k
            precisions.append(precision)
        
        return np.mean(precisions) if precisions else 0.0

training_pipeline = MLTrainingPipeline()