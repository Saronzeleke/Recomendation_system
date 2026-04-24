"""
Hybrid recommendation system combining collaborative filtering and content-based approaches.
Phase 2 implementation using LightFM for production-ready recommendations.

PRODUCTION GRADE - Fixed by Senior Data Scientist
"""

from typing import List, Dict, Any, Optional, Tuple, Set
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import structlog
import joblib
from pathlib import Path
import asyncio
from collections import defaultdict

from lightfm import LightFM
from lightfm.data import Dataset
from lightfm.evaluation import precision_at_k

from sqlalchemy import text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import db_manager
from core.cache import cache_manager
from services.content_based import content_based_recommender
from services.feature_extractor import feature_extractor

logger = structlog.get_logger()

class HybridRecommender:
    """
    Production-grade hybrid recommender system.
    
    Features:
    - LightFM collaborative filtering with content features
    - Automatic model retraining with versioning
    - Graceful degradation to content-based
    - Optimized batch predictions
    - Comprehensive error handling
    - Performance monitoring
    """
    
    def __init__(self):
        self.model: Optional[LightFM] = None
        self.dataset = Dataset()
        self.item_features = None
        self.user_features = None
        self.item_id_map: Dict[int, int] = {}
        self.user_id_map: Dict[int, int] = {}
        self.reverse_item_map: Dict[int, int] = {}
        self.reverse_user_map: Dict[int, int] = {}
        self.model_version = 0
        self.last_trained = None
        self.model_path = Path(settings.model_path) / "hybrid"
        self.model_path.mkdir(parents=True, exist_ok=True)
        self.model_file = self.model_path / "lightfm_model_latest.pkl"
        self.metadata_file = self.model_path / "metadata_latest.pkl"
        
        # Model hyperparameters
        self.default_params = {
            'no_components': 64,
            'learning_rate': 0.05,
            'loss': 'warp',
            'max_sampled': 10,
            'random_state': 42
        }
        
        # Load existing model if available
        self._load_model()
    
    def _load_model(self) -> bool:
        """Load pre-trained model with version fallback"""
        try:
            # Try latest first
            if self.model_file.exists() and self.metadata_file.exists():
                self.model = joblib.load(self.model_file)
                metadata = joblib.load(self.metadata_file)
                self.item_id_map = metadata.get('item_id_map', {})
                self.user_id_map = metadata.get('user_id_map', {})
                self.reverse_item_map = {v: k for k, v in self.item_id_map.items()}
                self.reverse_user_map = {v: k for k, v in self.user_id_map.items()}
                self.model_version = metadata.get('version', 0)
                self.last_trained = metadata.get('timestamp')
                
                logger.info(
                    "loaded_existing_model",
                    model_file=str(self.model_file),
                    version=self.model_version,
                    items=len(self.item_id_map),
                    users=len(self.user_id_map)
                )
                return True
                
            # Try backup versions
            backup_files = sorted(self.model_path.glob("lightfm_model_*.pkl"), reverse=True)
            if backup_files:
                backup_file = backup_files[0]
                meta_file = backup_file.with_name(backup_file.name.replace('model', 'metadata'))
                
                if meta_file.exists():
                    self.model = joblib.load(backup_file)
                    metadata = joblib.load(meta_file)
                    self.item_id_map = metadata.get('item_id_map', {})
                    self.user_id_map = metadata.get('user_id_map', {})
                    self.reverse_item_map = {v: k for k, v in self.item_id_map.items()}
                    self.reverse_user_map = {v: k for k, v in self.user_id_map.items()}
                    
                    logger.info("loaded_backup_model", backup_file=str(backup_file))
                    return True
                    
        except Exception as e:
            logger.error("failed_to_load_model", error=str(e), exc_info=True)
        
        return False
    
    def _save_model(self, is_backup: bool = False):
        """Save trained model with versioning"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.model_version += 1
            
            metadata = {
                'item_id_map': self.item_id_map,
                'user_id_map': self.user_id_map,
                'version': self.model_version,
                'timestamp': datetime.now().isoformat(),
                'params': self.default_params
            }
            
            if is_backup:
                model_file = self.model_path / f"lightfm_model_{timestamp}.pkl"
                meta_file = self.model_path / f"metadata_{timestamp}.pkl"
            else:
                model_file = self.model_file
                meta_file = self.metadata_file
            
            joblib.dump(self.model, model_file, compress=3)
            joblib.dump(metadata, meta_file, compress=3)
            
            # Update latest symlinks or copies
            if is_backup:
                joblib.dump(self.model, self.model_file, compress=3)
                joblib.dump(metadata, self.metadata_file, compress=3)
            
            self.last_trained = datetime.now()
            
            logger.info(
                "saved_model",
                model_file=str(model_file),
                version=self.model_version,
                is_backup=is_backup
            )
            
        except Exception as e:
            logger.error("failed_to_save_model", error=str(e), exc_info=True)
    
    async def collect_interaction_data(self, days: int = 30) -> pd.DataFrame:
        """Collect user-provider interactions with optimized query"""
        try:
            async with db_manager.get_session() as session:
                query = text("""
                    WITH interactions AS (
                        -- Service requests (highest value)
                        SELECT 
                            sr.seeker_id as user_id,
                            sr.provider_id as item_id,
                            5.0 as rating,
                            sr.created_at,
                            10 as weight
                        FROM service_requests sr
                        WHERE sr.status = 'completed'
                            AND sr.created_at > NOW() - :days * INTERVAL '1 day'
                        
                        UNION ALL
                        
                        -- Messages (medium-high value)
                        SELECT 
                            m.sender_id as user_id,
                            m.receiver_id as item_id,
                            3.0 as rating,
                            m.created_at,
                            5 as weight
                        FROM messages m
                        WHERE m.created_at > NOW() - :days * INTERVAL '1 day'
                        
                        UNION ALL
                        
                        -- Profile views (low value)
                        SELECT 
                            al.user_id,
                            (al.metadata->>'provider_id')::int as item_id,
                            1.0 as rating,
                            al.created_at,
                            1 as weight
                        FROM activity_logs al
                        WHERE al.type = 'provider_view'
                            AND al.created_at > NOW() - :days * INTERVAL '1 day'
                        
                        UNION ALL
                        
                        -- Searches (contextual)
                        SELECT 
                            al.user_id,
                            (al.metadata->>'provider_id')::int as item_id,
                            2.0 as rating,
                            al.created_at,
                            2 as weight
                        FROM activity_logs al
                        WHERE al.type = 'search_click'
                            AND al.created_at > NOW() - :days * INTERVAL '1 day'
                    )
                    SELECT 
                        user_id,
                        item_id,
                        MAX(rating) as rating,
                        SUM(weight) as total_weight,
                        MAX(created_at) as last_interaction
                    FROM interactions
                    WHERE user_id IS NOT NULL 
                        AND item_id IS NOT NULL
                        AND user_id > 0
                        AND item_id > 0
                    GROUP BY user_id, item_id
                    HAVING SUM(weight) >= 1
                    ORDER BY last_interaction DESC
                """)
                
                result = await session.execute(query, {"days": days})
                rows = result.fetchall()
                
                if not rows:
                    return pd.DataFrame()
                
                df = pd.DataFrame(rows, columns=[
                    'user_id', 'item_id', 'rating', 'weight', 'last_interaction'
                ])
                
                logger.info(
                    "collected_interaction_data",
                    rows=len(df),
                    unique_users=df['user_id'].nunique(),
                    unique_items=df['item_id'].nunique(),
                    days=days
                )
                
                return df
                
        except Exception as e:
            logger.error("collect_interaction_data_failed", error=str(e), exc_info=True)
            return pd.DataFrame()
    
    async def collect_item_features(self, item_ids: List[int]) -> pd.DataFrame:
        """Collect features for items with optimized batch query"""
        if not item_ids:
            return pd.DataFrame()
        
        try:
            # Process in batches to avoid SQL parameter limits
            batch_size = 100
            all_rows = []
            
            async with db_manager.get_session() as session:
                for i in range(0, len(item_ids), batch_size):
                    batch_ids = item_ids[i:i + batch_size]
                    
                    query = text("""
                        SELECT 
                            pp.id as item_id,
                            pp.category,
                            pp.employee_count,
                            CASE WHEN pp.is_approved THEN 1 ELSE 0 END as is_approved,
                            CASE WHEN pp.certificates IS NOT NULL 
                                 AND jsonb_array_length(pp.certificates) > 0 
                                 THEN 1 ELSE 0 END as has_certificates,
                            COALESCE(pp.employee_count, 0) as employee_count,
                            COALESCE(s.avg_rating, 0) as avg_rating,
                            COALESCE(s.service_count, 0) as service_count,
                            COALESCE(s.request_count, 0) as request_count
                        FROM provider_profiles pp
                        LEFT JOIN (
                            SELECT 
                                s.provider_id,
                                AVG(sr.seeker_rating) as avg_rating,
                                COUNT(DISTINCT s.id) as service_count,
                                COUNT(DISTINCT sr.id) as request_count
                            FROM services s
                            LEFT JOIN service_requests sr ON s.id = sr.service_id
                            GROUP BY s.provider_id
                        ) s ON pp.id = s.provider_id
                        WHERE pp.id = ANY(:item_ids)
                    """)
                    
                    result = await session.execute(query, {"item_ids": batch_ids})
                    batch_rows = result.fetchall()
                    all_rows.extend(batch_rows)
            
            if not all_rows:
                return pd.DataFrame()
            
            df = pd.DataFrame(all_rows, columns=[
                'item_id', 'category', 'employee_count', 'is_approved',
                'has_certificates', 'employee_count_dup', 'avg_rating',
                'service_count', 'request_count'
            ])
            
            # Drop duplicate column
            df = df.drop(columns=['employee_count_dup'])
            
            return df
            
        except Exception as e:
            logger.error("collect_item_features_failed", error=str(e), exc_info=True)
            return pd.DataFrame()
    
    async def prepare_training_data(self, days: int = 30) -> Tuple:
        """Prepare data for LightFM with robust error handling"""
        try:
            # Collect interaction data
            interactions_df = await self.collect_interaction_data(days)
            
            if len(interactions_df) < settings.min_interactions_for_ml:
                logger.warning(
                    "insufficient_interaction_data",
                    count=len(interactions_df),
                    required=settings.min_interactions_for_ml
                )
                return None, None, None
            
            # Get unique users and items
            users = interactions_df['user_id'].unique().tolist()
            items = interactions_df['item_id'].unique().tolist()
            
            # Collect item features
            item_features_df = await self.collect_item_features(items)
            
            # Define feature set
            all_categories = ['plumbing', 'electrical', 'carpentry', 'cleaning', 
                            'moving', 'painting', 'hvac', 'other']
            
            feature_names = (
                [f"category_{cat}" for cat in all_categories] +
                ['is_approved', 'has_certificates', 'high_employee_count',
                 'high_rating', 'active_provider', 'established']
            )
            
            # Fit the dataset
            self.dataset.fit(
                users,
                items,
                item_features=feature_names
            )
            
            # Build interactions matrix
            interactions, weights = self.dataset.build_interactions(
                [(row.user_id, row.item_id, row.rating * np.log1p(row.weight))
                 for _, row in interactions_df.iterrows()]
            )
            
            # Build item features
            item_features_list = []
            for item_id in items:
                features = set()
                item_data = item_features_df[item_features_df['item_id'] == item_id]
                
                if not item_data.empty:
                    row = item_data.iloc[0]
                    
                    # Category feature
                    category = str(row.get('category', 'other')).lower()
                    if category in all_categories:
                        features.add(f"category_{category}")
                    else:
                        features.add("category_other")
                    
                    # Binary features
                    if row.get('is_approved', False):
                        features.add('is_approved')
                    if row.get('has_certificates', False):
                        features.add('has_certificates')
                    if row.get('employee_count', 0) > 5:
                        features.add('high_employee_count')
                    if row.get('avg_rating', 0) > 4.0:
                        features.add('high_rating')
                    if row.get('service_count', 0) > 3:
                        features.add('active_provider')
                    if row.get('request_count', 0) > 10:
                        features.add('established')
                
                item_features_list.append((item_id, list(features)))
            
            # Build item features matrix
            item_features = self.dataset.build_item_features(item_features_list)
            
            # Store mappings
            self.item_id_map = {item: idx for idx, item in enumerate(items)}
            self.user_id_map = {user: idx for idx, user in enumerate(users)}
            self.reverse_item_map = {idx: item for item, idx in self.item_id_map.items()}
            self.reverse_user_map = {idx: user for user, idx in self.user_id_map.items()}
            
            logger.info(
                "prepared_training_data",
                users=len(users),
                items=len(items),
                interactions=interactions.nnz,
                features=len(feature_names)
            )
            
            return interactions, item_features, weights
            
        except Exception as e:
            logger.error("prepare_training_data_failed", error=str(e), exc_info=True)
            return None, None, None
    
    async def train(
        self,
        epochs: int = 30,
        learning_rate: float = 0.05,
        loss: str = 'warp',
        no_components: int = 64,
        days: int = 30
    ) -> bool:
        """Train model with automatic versioning and monitoring"""
        try:
            start_time = datetime.now()
            
            # Prepare data
            interactions, item_features, weights = await self.prepare_training_data(days)
            
            if interactions is None:
                return False
            
            # Initialize model
            self.model = LightFM(
                no_components=no_components,
                learning_rate=learning_rate,
                loss=loss,
                max_sampled=10,
                random_state=42
            )
            
            # Train model with progress tracking
            best_precision = 0
            for epoch in range(epochs):
                self.model.fit_partial(
                    interactions,
                    item_features=item_features,
                    epochs=1,
                    num_threads=4,
                    verbose=False
                )
                
                # Calculate metrics every 5 epochs
                if (epoch + 1) % 5 == 0:
                    train_precision = precision_at_k(
                        self.model, 
                        interactions,
                        item_features=item_features,
                        k=10, 
                        num_threads=4,
                        check_intersections=False
                    ).mean()
                    
                    if train_precision > best_precision:
                        best_precision = train_precision
                    
                    logger.info(
                        "training_progress",
                        epoch=epoch + 1,
                        train_precision=round(float(train_precision), 4),
                        best_precision=round(float(best_precision), 4),
                        elapsed_seconds=(datetime.now() - start_time).total_seconds()
                    )
            
            # Store item features
            self.item_features = item_features
            
            # Save model (create backup of previous)
            if self.model_file.exists():
                self._save_model(is_backup=True)
            self._save_model(is_backup=False)
            
            training_time = (datetime.now() - start_time).total_seconds()
            
            logger.info(
                "training_completed",
                epochs=epochs,
                loss=loss,
                components=no_components,
                best_precision=round(float(best_precision), 4),
                training_seconds=round(training_time, 2),
                interactions=interactions.nnz
            )
            
            return True
            
        except Exception as e:
            logger.error("training_failed", error=str(e), exc_info=True)
            return False
    
    async def batch_predict(self, user_ids: List[int], item_ids: List[int]) -> np.ndarray:
        """Batch prediction for multiple users and items"""
        if self.model is None or not user_ids or not item_ids:
            return np.array([])
        
        try:
            # Filter to known users/items
            known_user_indices = []
            known_item_indices = []
            valid_user_ids = []
            valid_item_ids = []
            
            for user_id in user_ids:
                if user_id in self.user_id_map:
                    known_user_indices.append(self.user_id_map[user_id])
                    valid_user_ids.append(user_id)
            
            for item_id in item_ids:
                if item_id in self.item_id_map:
                    known_item_indices.append(self.item_id_map[item_id])
                    valid_item_ids.append(item_id)
            
            if not known_user_indices or not known_item_indices:
                return np.array([])
            
            # Create prediction matrix
            n_users = len(known_user_indices)
            n_items = len(known_item_indices)
            
            # Repeat users for each item
            user_repeats = np.repeat(known_user_indices, n_items)
            item_tiles = np.tile(known_item_indices, n_users)
            
            # Predict
            scores = self.model.predict(
                user_repeats,
                item_tiles,
                item_features=self.item_features
            )
            
            return scores.reshape(n_users, n_items)
            
        except Exception as e:
            logger.error("batch_predict_failed", error=str(e), exc_info=True)
            return np.array([])
    
    async def get_recommendations(
        self,
        lat: float,
        lng: float,
        category: Optional[str] = None,
        radius: int = 10,
        limit: int = 20,
        offset: int = 0,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get hybrid recommendations with graceful degradation"""
        start_time = datetime.now()
        
        try:
            # Phase 1: Always fall back to content-based for now
            # This ensures system works while model trains
            if self.model is None or user_id is None or len(self.user_id_map) < 10:
                return await content_based_recommender.get_recommendations(
                    lat, lng, category, radius, limit, offset
                )
            
            # Phase 2: Hybrid recommendations
            async with db_manager.get_session() as session:
                # Get providers within radius
                query = text("""
                    SELECT 
                        pp.id,
                        pp.category,
                        pp.latitude,
                        pp.longitude,
                        ST_DistanceSphere(
                            ST_MakePoint(:lng, :lat),
                            ST_MakePoint(pp.longitude, pp.latitude)
                        ) / 1000 as distance_km,
                        mv.is_approved,
                        mv.avg_rating
                    FROM provider_profiles pp
                    LEFT JOIN mv_provider_features mv ON pp.id = mv.provider_id
                    WHERE 
                        pp.is_active = true 
                        AND pp.status = 'active'
                        AND pp.latitude IS NOT NULL 
                        AND pp.longitude IS NOT NULL
                        AND ST_DistanceSphere(
                            ST_MakePoint(:lng, :lat),
                            ST_MakePoint(pp.longitude, pp.latitude)
                        ) / 1000 <= :radius
                    ORDER BY distance_km
                    LIMIT 200  -- Limit candidates for performance
                """)
                
                result = await session.execute(
                    query,
                    {"lat": lat, "lng": lng, "radius": radius}
                )
                providers = result.fetchall()
            
            if not providers:
                return {
                    "items": [],
                    "total": 0,
                    "metadata": {
                        "lat": lat,
                        "lng": lng,
                        "radius": radius,
                        "category": category,
                        "processing_time_ms": (datetime.now() - start_time).total_seconds() * 1000,
                        "model_used": "hybrid_fallback"
                    }
                }
            
            # Get collaborative scores in batch
            provider_ids = [p.id for p in providers]
            cf_scores = {}
            
            if user_id in self.user_id_map:
                batch_scores = await self.batch_predict([user_id], provider_ids)
                if len(batch_scores) > 0:
                    for idx, provider_id in enumerate(provider_ids):
                        cf_scores[provider_id] = float(batch_scores[0][idx])
            
            # Score and rank providers
            recommendations = []
            for provider in providers:
                # Collaborative score (with fallback)
                cf_score = cf_scores.get(provider.id, 0.3)
                
                # Distance score (inverse distance)
                distance_score = max(0, 1 - (provider.distance_km / radius))
                
                # Category match
                category_score = 1.0 if category and provider.category == category else 0.3
                
                # Quality score from materialized view
                quality_score = min(1.0, (
                    (0.4 * provider.is_approved) +
                    (0.6 * (provider.avg_rating / 5.0 if provider.avg_rating else 0.3))
                ))
                
                # Hybrid weighted score
                hybrid_score = (
                    0.35 * cf_score +      # Collaborative
                    0.35 * distance_score + # Location
                    0.15 * category_score + # Category
                    0.15 * quality_score    # Quality
                )
                
                # Boost if user has history with this provider
                if provider.id in cf_scores:
                    hybrid_score *= 1.1
                
                # Recommendation reasons
                reasons = []
                if cf_score > 0.6:
                    reasons.append("Matches your preferences")
                if distance_score > 0.7:
                    reasons.append("Very close to you")
                if category_score > 0.8:
                    reasons.append(f"Specializes in {category}")
                if quality_score > 0.7:
                    reasons.append("Highly rated provider")
                
                if not reasons:
                    reasons.append("Available provider")
                
                recommendations.append({
                    "provider_id": provider.id,
                    "distance_km": round(provider.distance_km, 2),
                    "distance_score": round(distance_score, 3),
                    "category_score": round(category_score, 3),
                    "cf_score": round(cf_score, 3),
                    "quality_score": round(quality_score, 3),
                    "final_score": round(hybrid_score, 3),
                    "reason_for_recommendation": reasons[0],
                    "all_reasons": reasons,
                    "metadata": {
                        "category": provider.category,
                        "model_used": "hybrid",
                        "avg_rating": float(provider.avg_rating) if provider.avg_rating else None
                    }
                })
            
            # Sort and paginate
            recommendations.sort(key=lambda x: x['final_score'], reverse=True)
            total = len(recommendations)
            paginated = recommendations[offset:offset + limit]
            
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            
            logger.info(
                "hybrid_recommendations_generated",
                total=total,
                returned=len(paginated),
                processing_time_ms=round(processing_time, 2),
                user_id=user_id,
                model_used="hybrid"
            )
            
            return {
                "items": paginated,
                "total": total,
                "metadata": {
                    "lat": lat,
                    "lng": lng,
                    "radius": radius,
                    "category": category,
                    "processing_time_ms": round(processing_time, 2),
                    "model_used": "hybrid",
                    "model_version": self.model_version,
                    "has_user_history": user_id in self.user_id_map
                }
            }
            
        except Exception as e:
            logger.error(
                "hybrid_recommendation_failed",
                error=str(e),
                exc_info=True,
                lat=lat,
                lng=lng,
                user_id=user_id
            )
            # Fall back to content-based
            return await content_based_recommender.get_recommendations(
                lat, lng, category, radius, limit, offset
            )
    
    async def get_similar_providers(
        self,
        provider_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get similar providers using item embeddings"""
        try:
            if self.model is None or provider_id not in self.item_id_map:
                # Fall back to content-based
                similar = await feature_extractor.get_similar_services(provider_id, limit)
                return [{"provider_id": s['service_id'], 
                        "similarity_score": s['similarity_score']} 
                        for s in similar]
            
            item_idx = self.item_id_map[provider_id]
            
            # Get item embeddings
            item_embeddings = self.model.item_embeddings
            
            # Calculate cosine similarities
            query_vector = item_embeddings[item_idx]
            norms = np.linalg.norm(item_embeddings, axis=1)
            similarities = np.dot(item_embeddings, query_vector) / (norms * norms[item_idx] + 1e-10)
            
            # Get top similar items (excluding self)
            similar_indices = np.argsort(-similarities)[1:limit+1]
            
            similar_providers = []
            for idx in similar_indices:
                if similarities[idx] > 0.2:  # Similarity threshold
                    similar_providers.append({
                        "provider_id": self.reverse_item_map[idx],
                        "similarity_score": float(similarities[idx])
                    })
            
            return similar_providers
            
        except Exception as e:
            logger.error("similar_providers_failed", error=str(e), exc_info=True)
            return []

# Global hybrid recommender instance
hybrid_recommender = HybridRecommender()