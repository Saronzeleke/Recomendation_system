from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict, field_validator
from datetime import datetime

class Location(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude (-90 to 90)")
    lng: float = Field(..., ge=-180, le=180, description="Longitude (-180 to 180)")
    
    @field_validator('lat')
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if v < -90 or v > 90:
            raise ValueError('Latitude must be between -90 and 90')
        return round(v, 6)
    
    @field_validator('lng')
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if v < -180 or v > 180:
            raise ValueError('Longitude must be between -180 and 180')
        return round(v, 6)

class RecommendationRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    category: Optional[str] = Field(None, description="Filter by service category")
    radius: int = Field(10, ge=1, le=100, description="Search radius in kilometers")
    limit: int = Field(20, ge=1, le=100, description="Number of results to return")
    offset: int = Field(0, ge=0, description="Pagination offset")
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "lat": 40.7128,
                "lng": -74.0060,
                "category": "Plumbing",
                "radius": 10,
                "limit": 20,
                "offset": 0
            }
        }
    )

class RecommendationItem(BaseModel):
    provider_id: int
    distance_km: float = Field(..., description="Distance in kilometers")
    distance_score: float = Field(..., ge=0, le=1)
    category_score: float = Field(..., ge=0, le=1)
    quality_score: float = Field(..., ge=0, le=1)
    final_score: float = Field(..., ge=0, le=1)
    reason_for_recommendation: str
    all_reasons: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RecommendationMetadata(BaseModel):
    lat: float
    lng: float
    radius: int
    category: Optional[str] = None
    processing_time_ms: float
    weights: Optional[Dict[str, float]] = None
    error: Optional[str] = None

class RecommendationResponse(BaseModel):
    items: List[RecommendationItem]
    total: int
    metadata: RecommendationMetadata
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "provider_id": 123,
                        "distance_km": 2.5,
                        "distance_score": 0.85,
                        "category_score": 1.0,
                        "quality_score": 0.9,
                        "final_score": 0.89,
                        "reason_for_recommendation": "Very close to your location",
                        "all_reasons": ["Very close to your location", "Specializes in Plumbing"],
                        "metadata": {
                            "category": "Plumbing",
                            "service_count": 5,
                            "avg_rating": 4.8
                        }
                    }
                ],
                "total": 1,
                "metadata": {
                    "lat": 40.7128,
                    "lng": -74.0060,
                    "radius": 10,
                    "category": "Plumbing",
                    "processing_time_ms": 45.2,
                    "weights": {
                        "distance": 0.6,
                        "category": 0.3,
                        "quality": 0.1
                    }
                }
            }
        }
    )

class ProviderDetail(BaseModel):
    id: int
    business_name: Optional[str] = None
    category: str
    latitude: float
    longitude: float
    distance_km: Optional[float] = None
    is_approved: bool
    employee_count: int
    has_certificates: bool
    
    model_config = ConfigDict(from_attributes=True)

class HealthCheck(BaseModel):
    status: str
    version: str = "1.0.0"
    database: str
    redis: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)