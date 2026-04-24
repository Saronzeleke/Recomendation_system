from contextlib import asynccontextmanager
from typing import AsyncGenerator
import asyncio
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
import time

from core.config import settings
from core.database import db_manager
from core.cache import cache_manager
from api.endpoints import router
from tasks.celery_app import celery_app

# Structured logging setup
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Lifespan context manager for startup and shutdown events
    """
    # Startup
    logger.info("starting_up", environment=settings.environment)
    
    # Initialize database connection pool
    await db_manager.initialize()
    
    # Initialize Redis cache
    await cache_manager.initialize()
    
    # Warm up cache if needed
    if settings.environment == "production":
        asyncio.create_task(warm_up_cache())
    
    logger.info("startup_complete")
    
    yield
    
    # Shutdown
    logger.info("shutting_down")
    
    # Close database connections
    await db_manager.close()
    
    # Close Redis connections
    await cache_manager.close()
    
    logger.info("shutdown_complete")

async def warm_up_cache():
    """Warm up cache with common recommendations"""
    try:
        logger.info("warming_up_cache")
        
        # Common locations (can be loaded from config)
        common_locations = [
            (40.7128, -74.0060),  # NYC
            (34.0522, -118.2437),  # LA
            (41.8781, -87.6298),   # Chicago
            (29.7604, -95.3698),   # Houston
            (33.4484, -112.0740),  # Phoenix
        ]
        
        from services.content_based import content_based_recommender
        
        for lat, lng in common_locations:
            await content_based_recommender.get_recommendations(
                lat=lat,
                lng=lng,
                radius=10,
                limit=20
            )
            await asyncio.sleep(1)  # Rate limiting
        
        logger.info("cache_warm_up_complete")
        
    except Exception as e:
        logger.error("cache_warm_up_failed", error=str(e))

# Create FastAPI app
app = FastAPI(
    title="ServeEase Recommendation Service",
    description="Production-ready recommendation system for service marketplace",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url="/api/redoc" if settings.environment != "production" else None,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Include routers
app.include_router(router)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time header and log requests"""
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    
    # Log request
    logger.info(
        "request_processed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        process_time_ms=round(process_time * 1000, 2),
        client_host=request.client.host if request.client else None
    )
    
    return response

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        method=request.method
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred",
            "error_code": "INTERNAL_SERVER_ERROR",
            "timestamp": time.time()
        }
    )

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "ServeEase Recommendation Service",
        "version": "1.0.0",
        "status": "operational",
        "documentation": "/api/docs"
    }