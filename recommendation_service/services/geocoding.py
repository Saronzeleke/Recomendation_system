from typing import Optional, Tuple, Dict, Any
import asyncio
from geopy.geocoders import GoogleV3, Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import settings
from core.cache import cache_manager

logger = structlog.get_logger()

class GeocodingService:
    """Handles geocoding with multiple providers and caching"""
    
    def __init__(self):
        self.geocoder = self._initialize_geocoder()
        self.reverse_geocoder = self._initialize_reverse_geocoder()
        
    def _initialize_geocoder(self):
        """Initialize geocoder based on settings"""
        if settings.geocoding_provider == "google" and settings.google_maps_api_key:
            return GoogleV3(api_key=settings.google_maps_api_key)
        else:
            # Fallback to OpenStreetMap Nominatim
            return Nominatim(user_agent="serveease-recommendation-service")
    
    def _initialize_reverse_geocoder(self):
        """Initialize reverse geocoder with rate limiting"""
        if settings.geocoding_provider == "google":
            return RateLimiter(
                self.geocoder.reverse,
                min_delay_seconds=0.1,  # 10 requests per second max
                max_retries=2
            )
        else:
            # OSM Nominatim has stricter limits (1 req/sec)
            return RateLimiter(
                self.geocoder.reverse,
                min_delay_seconds=1.0,
                max_retries=2
            )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry_error_callback=lambda retry_state: None
    )
    async def geocode_address(
        self,
        address: str,
        country: Optional[str] = None
    ) -> Optional[Tuple[float, float]]:
        """
        Convert address to coordinates (lat, lng)
        Uses caching to avoid repeated API calls
        """
        cache_key = f"geocode:{address}:{country or 'global'}"
        
        # Check cache
        cached = await cache_manager.get(cache_key)
        if cached:
            logger.debug("geocode_cache_hit", address=address)
            return cached
        
        try:
            # Run geocoding in thread pool to avoid blocking
            full_address = f"{address}, {country}" if country else address
            
            loop = asyncio.get_event_loop()
            location = await loop.run_in_executor(
                None,
                lambda: self.geocoder.geocode(
                    full_address,
                    timeout=settings.geocoding_timeout
                )
            )
            
            if location:
                coordinates = (location.latitude, location.longitude)
                # Cache for 24 hours (addresses don't change often)
                await cache_manager.set(cache_key, coordinates, settings.cache_ttl_geocoding)
                
                logger.info(
                    "geocode_success",
                    address=address,
                    coordinates=coordinates
                )
                return coordinates
            else:
                logger.warning("geocode_not_found", address=address)
                return None
                
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.error(
                "geocode_failed",
                address=address,
                error=str(e),
                provider=settings.geocoding_provider
            )
            return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def reverse_geocode(
        self,
        lat: float,
        lng: float
    ) -> Optional[Dict[str, Any]]:
        """
        Convert coordinates to address
        Returns structured address data
        """
        cache_key = f"reverse_geocode:{lat:.4f}:{lng:.4f}"
        
        # Check cache
        cached = await cache_manager.get(cache_key)
        if cached:
            return cached
        
        try:
            loop = asyncio.get_event_loop()
            location = await loop.run_in_executor(
                None,
                lambda: self.reverse_geocoder((lat, lng))
            )
            
            if location:
                address_data = {
                    "address": location.address,
                    "raw": location.raw,
                    "latitude": lat,
                    "longitude": lng
                }
                
                # Cache reverse geocoding results
                await cache_manager.set(
                    cache_key,
                    address_data,
                    settings.cache_ttl_geocoding
                )
                
                return address_data
            else:
                return None
                
        except Exception as e:
            logger.error("reverse_geocode_failed", lat=lat, lng=lng, error=str(e))
            return None
    
    async def batch_geocode(
        self,
        addresses: list[Tuple[str, Optional[str]]]
    ) -> list[Optional[Tuple[float, float]]]:
        """Batch geocode multiple addresses with rate limiting"""
        # Process with delays to respect rate limits
        results = []
        for address, country in addresses:
            result = await self.geocode_address(address, country)
            results.append(result)
            # Add delay between requests
            await asyncio.sleep(0.2)  # 200ms between requests
        
        return results

# Global geocoding service instance
geocoding_service = GeocodingService()