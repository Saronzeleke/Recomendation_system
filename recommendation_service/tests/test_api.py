import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import json

from main import app
from core.config import settings

client = TestClient(app)

def test_health_check():
    """Test health check endpoint"""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "database" in data
    assert "redis" in data

def test_recommendations_endpoint():
    """Test recommendations endpoint"""
    with patch('api.endpoints.content_based_recommender.get_recommendations') as mock_recommend:
        # Mock successful response
        mock_recommend.return_value = {
            "items": [
                {
                    "provider_id": 1,
                    "distance_km": 2.5,
                    "distance_score": 0.85,
                    "category_score": 1.0,
                    "quality_score": 0.9,
                    "final_score": 0.89,
                    "reason_for_recommendation": "Close to your location",
                    "all_reasons": ["Close to your location"],
                    "metadata": {}
                }
            ],
            "total": 1,
            "metadata": {
                "lat": 40.7128,
                "lng": -74.0060,
                "radius": 10,
                "category": "Plumbing",
                "processing_time_ms": 45.2,
                "weights": settings.dict()
            }
        }
        
        response = client.get(
            "/api/v1/recommendations",
            params={
                "lat": 40.7128,
                "lng": -74.0060,
                "category": "Plumbing",
                "radius": 10,
                "limit": 20
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "metadata" in data

def test_recommendations_validation():
    """Test input validation"""
    # Test invalid latitude
    response = client.get(
        "/api/v1/recommendations",
        params={"lat": 100, "lng": -74.0060}
    )
    assert response.status_code == 422  # Validation error
    
    # Test invalid longitude
    response = client.get(
        "/api/v1/recommendations",
        params={"lat": 40.7128, "lng": 200}
    )
    assert response.status_code == 422
    
    # Test invalid radius
    response = client.get(
        "/api/v1/recommendations",
        params={"lat": 40.7128, "lng": -74.0060, "radius": 200}
    )
    assert response.status_code == 422

def test_geocode_endpoint():
    """Test geocoding endpoint"""
    with patch('api.endpoints.geocoding_service.geocode_address') as mock_geocode:
        mock_geocode.return_value = (40.7128, -74.0060)
        
        response = client.get(
            "/api/v1/recommendations/geocode",
            params={"address": "New York, NY"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["latitude"] == 40.7128
        assert data["longitude"] == -74.0060

def test_reverse_geocode_endpoint():
    """Test reverse geocoding endpoint"""
    with patch('api.endpoints.geocoding_service.reverse_geocode') as mock_reverse:
        mock_reverse.return_value = {
            "address": "New York, NY",
            "latitude": 40.7128,
            "longitude": -74.0060
        }
        
        response = client.get(
            "/api/v1/recommendations/reverse-geocode",
            params={"lat": 40.7128, "lng": -74.0060}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "address" in data

def test_provider_detail_endpoint():
    """Test provider detail endpoint"""
    with patch('api.endpoints.db_manager.get_session') as mock_session:
        mock_conn = AsyncMock()
        mock_session.return_value.__aenter__.return_value = mock_conn
        
        # Mock provider query
        mock_result = AsyncMock()
        mock_result.fetchone.return_value = {
            "id": 1,
            "category": "Plumbing",
            "employee_count": 5,
            "is_approved": True,
            "certificates": {},
            "latitude": 40.7128,
            "longitude": -74.0060
        }
        mock_conn.execute.return_value = mock_result
        
        response = client.get("/api/v1/providers/1")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["category"] == "Plumbing"

def test_rate_limiting():
    """Test rate limiting (if configured)"""
    # Make multiple requests quickly
    responses = []
    for _ in range(10):
        response = client.get(
            "/api/v1/recommendations",
            params={"lat": 40.7128, "lng": -74.0060, "limit": 1}
        )
        responses.append(response.status_code)
    
    # Should all succeed or rate limit appropriately
    assert all(code in [200, 429] for code in responses)

def test_cache_headers():
    """Test cache control headers"""
    with patch('api.endpoints.content_based_recommender.get_recommendations') as mock_recommend:
        mock_recommend.return_value = {
            "items": [],
            "total": 0,
            "metadata": {
                "lat": 40.7128,
                "lng": -74.0060,
                "radius": 10,
                "processing_time_ms": 10
            }
        }
        
        response = client.get(
            "/api/v1/recommendations",
            params={"lat": 40.7128, "lng": -74.0060}
        )
        
        assert "cache-control" in response.headers
        # Should have cache headers for CDN/proxy caching