from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse
import structlog
from prometheus_client import Histogram, Counter, generate_latest
from sqlalchemy import text  # ADD THIS IMPORT

from api.models import (
    RecommendationResponse,
    RecommendationRequest,
    HealthCheck,
    ErrorResponse,
    ProviderDetail
)
from api.dependencies import (
    RecommendationParamsDep,
    RecommenderDep,
    LocationDep,
    DatabaseSessionDep,
    get_db_session
)
from services.content_based import content_based_recommender
from services.geocoding import geocoding_service
from core.config import settings
from core.cache import cache_manager

logger = structlog.get_logger()

# Metrics
recommendation_latency = Histogram(
    'recommendation_latency_seconds',
    'Recommendation generation latency',
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
)

recommendation_counter = Counter(
    'recommendation_requests_total',
    'Total recommendation requests',
    ['status']
)

# Create router
router = APIRouter(prefix=settings.api_prefix, tags=["recommendations"])

@router.get(
    "/recommendations",
    response_model=RecommendationResponse,
    responses={
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    }
)
async def get_recommendations(
    params: RecommendationParamsDep,
    recommender: RecommenderDep,
    location: LocationDep
):
    """
    Get ranked provider recommendations based on location and preferences
    """
    with recommendation_latency.time():
        try:
            # Check cache first
            cache_key = f"recommendations:{params.lat:.4f}:{params.lng:.4f}:{params.category}:{params.radius}:{params.limit}:{params.offset}"
            
            cached_result = await cache_manager.get(cache_key)
            if cached_result:
                logger.debug("recommendation_cache_hit", cache_key=cache_key)
                recommendation_counter.labels(status='cached').inc()
                return RecommendationResponse(**cached_result)
            
            # Generate recommendations
            result = await recommender.get_recommendations(
                lat=params.lat,
                lng=params.lng,
                category=params.category,
                radius=params.radius,
                limit=params.limit,
                offset=params.offset,
                user_id=None
            )
            
            # Cache successful results
            if result["items"]:
                await cache_manager.set(
                    cache_key,
                    result,
                    ttl=settings.cache_ttl_recommendations
                )
            
            recommendation_counter.labels(status='success').inc()
            
            return RecommendationResponse(**result)
            
        except Exception as e:
            # FIXED: Create a dictionary manually instead of using .model_dump()
            error_params = {
                "lat": params.lat,
                "lng": params.lng,
                "category": params.category,
                "radius": params.radius,
                "limit": params.limit,
                "offset": params.offset,
                "user_id": params.user_id if hasattr(params, 'user_id') else None
            }
            
            logger.error(
                "recommendation_endpoint_error",
                error=str(e),
                params=error_params  # Using manually created dict
            )
            recommendation_counter.labels(status='error').inc()
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate recommendations: {str(e)}"
            )

@router.get("/recommendations/geocode")
async def geocode_address(
    address: str,
    country: Optional[str] = None
):
    """
    Convert address to coordinates for use in recommendations
    """
    try:
        coordinates = await geocoding_service.geocode_address(address, country)
        
        if coordinates:
            return {
                "address": address,
                "latitude": coordinates[0],
                "longitude": coordinates[1],
                "success": True
            }
        else:
            return {
                "address": address,
                "success": False,
                "error": "Address not found"
            }
    except Exception as e:
        logger.error("geocode_endpoint_error", address=address, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Geocoding failed: {str(e)}"
        )

@router.get("/recommendations/reverse-geocode")
async def reverse_geocode(
    lat: float,
    lng: float
):
    """
    Convert coordinates to address
    """
    try:
        address_data = await geocoding_service.reverse_geocode(lat, lng)
        
        if address_data:
            return {
                **address_data,
                "success": True
            }
        else:
            return {
                "latitude": lat,
                "longitude": lng,
                "success": False,
                "error": "Address not found"
            }
    except Exception as e:
        logger.error("reverse_geocode_endpoint_error", lat=lat, lng=lng, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reverse geocoding failed: {str(e)}"
        )

@router.get("/health", response_model=HealthCheck)
async def health_check(db_session: DatabaseSessionDep):
    """
    Health check endpoint for monitoring
    """
    try:
        # Check database
        await db_session.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        logger.error("health_check_db_failed", error=str(e))
        db_status = "unhealthy"
    
    try:
        # Check Redis
        await cache_manager.redis_client.ping()
        redis_status = "healthy"
    except Exception as e:
        logger.error("health_check_redis_failed", error=str(e))
        redis_status = "unhealthy"
    
    return HealthCheck(
        status="healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded",
        database=db_status,
        redis=redis_status
    )

@router.get("/metrics")
async def get_metrics():
    """
    Prometheus metrics endpoint
    """
    return generate_latest()

@router.post("/recommendations/refresh-cache")
async def refresh_recommendation_cache():
    """
    Admin endpoint to clear recommendation cache
    """
    try:
        await cache_manager.clear_pattern("recommendations:*")
        await cache_manager.clear_pattern("provider_features:*")
        
        return {"status": "success", "message": "Cache cleared"}
    except Exception as e:
        logger.error("cache_refresh_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {str(e)}"
        )

@router.get("/providers/{provider_id}", response_model=ProviderDetail)
async def get_provider_detail(
    provider_id: int,
    db_session: DatabaseSessionDep,
    lat: Optional[float] = None,
    lng: Optional[float] = None
):
    """
    Get detailed information about a specific provider
    """
    try:
        from sqlalchemy import text
        
        if lat and lng:
            # Include distance if location provided
            query = text("""
                SELECT 
                    pp.*,
                    ST_DistanceSphere(
                        ST_MakePoint(:lng, :lat),
                        ST_MakePoint(pp.longitude, pp.latitude)
                    ) / 1000 as distance_km
                FROM provider_profiles pp
                WHERE pp.id = :provider_id AND pp.is_active = true
            """)
            
            result = await db_session.execute(
                query,
                {
                    "provider_id": provider_id,
                    "lat": lat,
                    "lng": lng
                }
            )
        else:
            query = text("""
                SELECT *
                FROM provider_profiles
                WHERE id = :provider_id AND is_active = true
            """)
            
            result = await db_session.execute(
                query,
                {"provider_id": provider_id}
            )
        
        provider = result.fetchone()
        
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Provider not found"
            )
        
        return ProviderDetail.model_validate(provider)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("provider_detail_error", provider_id=provider_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch provider: {str(e)}"
        )