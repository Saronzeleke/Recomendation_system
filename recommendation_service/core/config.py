from typing import Optional, List
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, PostgresDsn, field_validator
import structlog
import os

logger = structlog.get_logger()

class Settings(BaseSettings):
    # Application
    app_name: str = "ServeEase Recommendation Service"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    
    # Database
    database_url: PostgresDsn
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_pool_pre_ping: bool = True
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 20
    redis_socket_timeout: int = 5
    redis_socket_connect_timeout: int = 5
    
    # Cache TTLs (seconds)
    cache_ttl_provider_features: int = 3600  # 1 hour
    cache_ttl_recommendations: int = 300  # 5 minutes
    cache_ttl_geocoding: int = 86400  # 24 hours
    
    # Recommendation weights
    weight_distance: float = 0.60
    weight_category: float = 0.30
    weight_quality: float = 0.10
    
    # Default search radius (km)
    default_radius: int = 10
    max_radius: int = 100
    max_recommendations: int = 100
    
    # Geocoding
    geocoding_provider: str = "google"  # or "osm"
    google_maps_api_key: Optional[str] = None
    geocoding_timeout: int = 5
    geocoding_retries: int = 3
    
    # ML Model paths
    model_path: str = "/app/ml/models"
    model_registry_uri: Optional[str] = None
    
    # Monitoring
    metrics_port: int = 9090
    enable_prometheus: bool = True
    log_level: str = "INFO"
    
    # Feature flags
    enable_hybrid_recommendations: bool = False
    min_interactions_for_ml: int = 1000
    ab_testing_enabled: bool = True
    
    # Docker environment flag
    in_docker: bool = False
    
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @field_validator("environment", mode="before")
    @classmethod
    def detect_docker(cls, v: str) -> str:
        """Auto-detect if running in Docker"""
        # Check for Docker environment
        if os.path.exists('/.dockerenv') or os.path.exists('/run/.containerenv'):
            cls.in_docker = True
            logger.info("detected_docker_environment")
        return v
    
    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if isinstance(v, str):
            # Ensure asyncpg is used
            if v.startswith("postgresql://") and "+asyncpg" not in v:
                v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
            
            # For Docker, ensure we use the service name
            if cls.in_docker and "localhost" in v:
                v = v.replace("localhost", "postgres")
                logger.info("using_docker_db_host", host="postgres")
                
        return v
    
    @field_validator("redis_url", mode="before")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        if isinstance(v, str):
            # For Docker, ensure we use the service name
            if cls.in_docker and "localhost" in v:
                v = v.replace("localhost", "redis")
                logger.info("using_docker_redis_host", host="redis")
        return v

settings = Settings()