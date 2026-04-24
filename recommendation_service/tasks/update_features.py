from celery import shared_task
import structlog
import asyncio

from core.database import db_manager
from services.feature_extractor import feature_extractor
from core.cache import cache_manager

logger = structlog.get_logger()

@shared_task(name="tasks.update_features.refresh_materialized_view")
def refresh_materialized_view():
    """Refresh the materialized view for provider features"""
    async def _refresh():
        async with db_manager.get_session() as session:
            from sqlalchemy import text
            await session.execute(
                text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_provider_features")
            )
            await session.commit()
            logger.info("materialized_view_refreshed")
    
    asyncio.run(_refresh())

@shared_task(name="tasks.update_features.update_service_vectors")
def update_service_vectors():
    """Update TF-IDF service vectors"""
    async def _update():
        async with db_manager.get_session() as session:
            await feature_extractor.build_service_vectors(session)
            
            # Clear related cache
            await cache_manager.clear_pattern("service_vectors*")
            logger.info("service_vectors_updated")
    
    asyncio.run(_update())

@shared_task(name="tasks.update_features.update_provider_features")
def update_provider_features(provider_id: int = None):
    """Update features for specific provider or all providers"""
    async def _update():
        async with db_manager.get_session() as session:
            from sqlalchemy import text
            
            if provider_id:
                # Update specific provider
                await cache_manager.delete(f"provider_features:{provider_id}")
                logger.info("provider_features_updated", provider_id=provider_id)
            else:
                # Clear all provider feature cache
                await cache_manager.clear_pattern("provider_features:*")
                logger.info("all_provider_features_cleared")
    
    asyncio.run(_update())