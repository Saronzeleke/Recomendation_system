from typing import Optional, Annotated
from fastapi import Query, Depends, HTTPException, status
import structlog

from core.config import settings
from services.content_based import content_based_recommender
from services.hybrid import hybrid_recommender  # Now this exists!
from core.database import get_db_session, db_manager
from core.cache import cache_manager
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
class RecommendationParams:
    """Dependency for recommendation query parameters with validation"""
    
    def __init__(
        self,
        lat: float = Query(..., ge=-90, le=90, description="User latitude"),
        lng: float = Query(..., ge=-180, le=180, description="User longitude"),
        category: Optional[str] = Query(None, description="Filter by category"),
        radius: int = Query(settings.default_radius, ge=1, le=settings.max_radius),
        limit: int = Query(20, ge=1, le=settings.max_recommendations),
        offset: int = Query(0, ge=0),
        user_id: Optional[int] = Query(None, description="User ID for personalized recommendations")
    ):
        self.lat = lat
        self.lng = lng
        self.category = category
        self.radius = radius
        self.limit = limit
        self.offset = offset
        self.user_id = user_id
        
        logger.debug(
            "recommendation_params",
            lat=lat,
            lng=lng,
            category=category,
            radius=radius,
            limit=limit,
            offset=offset,
            user_id=user_id
        )

async def get_recommender():
    """Dependency to get appropriate recommender based on phase"""
    # Check if we have enough interactions for hybrid model
    if settings.enable_hybrid_recommendations:
        try:
            async with db_manager.get_session() as session:
                from sqlalchemy import text
                result = await session.execute(
                    text("SELECT COUNT(*) FROM service_requests WHERE created_at > NOW() - INTERVAL '7 days'")
                )
                interaction_count = result.scalar()
                
                if interaction_count >= settings.min_interactions_for_ml:
                    logger.info("using_hybrid_recommender", interactions=interaction_count)
                    return hybrid_recommender
        except Exception as e:
            logger.warning("failed_to_check_interactions", error=str(e))
    
    # Default to content-based
    logger.debug("using_content_based_recommender")
    return content_based_recommender

async def verify_location(lat: float, lng: float):
    """Verify that location coordinates are valid"""
    try:
        if lat < -90 or lat > 90 or lng < -180 or lng > 180:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid coordinates"
            )
        return {"lat": lat, "lng": lng}
    except Exception as e:
        logger.error("location_validation_failed", lat=lat, lng=lng, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid location coordinates"
        )

# Type aliases for dependencies
RecommendationParamsDep = Annotated[RecommendationParams, Depends()]
RecommenderDep = Annotated[any, Depends(get_recommender)]
LocationDep = Annotated[dict, Depends(verify_location)]
DatabaseSessionDep = Annotated[any, Depends(get_db_session)]