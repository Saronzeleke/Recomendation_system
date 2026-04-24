from typing import Optional, Any, Callable
import json
import pickle
from datetime import timedelta
import aiocache
from aiocache import Cache, cached
from aiocache.serializers import JsonSerializer, PickleSerializer
from redis.asyncio import Redis, ConnectionPool
import structlog

from .config import settings

logger = structlog.get_logger()

class CacheManager:
    """Manages Redis caching with multiple backends and serialization"""
    
    def __init__(self):
        self.redis_pool: Optional[ConnectionPool] = None
        self.redis_client: Optional[Redis] = None
        self.aiocache_redis: Optional[Cache] = None
        
    async def initialize(self):
        """Initialize Redis connection pool"""
        try:
            self.redis_pool = ConnectionPool.from_url(
                settings.redis_url,
                max_connections=settings.redis_max_connections,
                socket_timeout=settings.redis_socket_timeout,
                socket_connect_timeout=settings.redis_socket_connect_timeout,
                decode_responses=False  # Keep as bytes for pickling
            )
            
            self.redis_client = Redis(connection_pool=self.redis_pool)
            
            # Test connection
            await self.redis_client.ping()
            
            # Initialize aiocache with Redis
            self.aiocache_redis = Cache(
                Cache.REDIS,
                endpoint=settings.redis_url.split("://")[1].split(":")[0],
                port=int(settings.redis_url.split(":")[-1].split("/")[0]),
                namespace="serveease",
                serializer=PickleSerializer(),
                pool_min_size=5,
                pool_max_size=settings.redis_max_connections
            )
            
            logger.info(
                "cache_initialized",
                redis_url=settings.redis_url,
                max_connections=settings.redis_max_connections
            )
            
        except Exception as e:
            logger.error("cache_initialization_failed", error=str(e))
            # Don't raise - allow graceful degradation without Redis
            self.redis_client = None
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache"""
        if not self.redis_client:
            return default
        
        try:
            value = await self.redis_client.get(key)
            if value:
                return pickle.loads(value)
            return default
        except Exception as e:
            logger.warning("cache_get_failed", key=key, error=str(e))
            return default
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int = 300,
        nx: bool = False
    ) -> bool:
        """Set value in cache with TTL"""
        if not self.redis_client:
            return False
        
        try:
            pickled = pickle.dumps(value)
            if nx:
                return await self.redis_client.setnx(key, pickled)
            else:
                return await self.redis_client.setex(key, ttl, pickled)
        except Exception as e:
            logger.warning("cache_set_failed", key=key, error=str(e))
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if not self.redis_client:
            return False
        
        try:
            return await self.redis_client.delete(key) > 0
        except Exception as e:
            logger.warning("cache_delete_failed", key=key, error=str(e))
            return False
    
    async def clear_pattern(self, pattern: str):
        """Clear all keys matching pattern"""
        if not self.redis_client:
            return
        
        try:
            keys = await self.redis_client.keys(pattern)
            if keys:
                await self.redis_client.delete(*keys)
                logger.info("cache_cleared_pattern", pattern=pattern, count=len(keys))
        except Exception as e:
            logger.warning("cache_clear_pattern_failed", pattern=pattern, error=str(e))
    
    async def close(self):
        """Close Redis connections"""
        if self.redis_pool:
            await self.redis_pool.disconnect()
        if self.aiocache_redis:
            await self.aiocache_redis.close()
        logger.info("cache_connections_closed")

# Global cache manager instance
cache_manager = CacheManager()

# Decorator for caching function results
def cached_result(ttl: int = 300, key_prefix: str = ""):
    """Decorator to cache function results in Redis"""
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Try to get from cache
            cached_value = await cache_manager.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            await cache_manager.set(cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator