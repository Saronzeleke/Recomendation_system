import pytest
import pytest_asyncio
from unittest.mock import Mock, patch, AsyncMock
import numpy as np
from datetime import datetime

from services.content_based import ContentBasedRecommender
from services.feature_extractor import FeatureExtractor
from core.config import settings

@pytest.fixture
def recommender():
    return ContentBasedRecommender()

@pytest.mark.asyncio
async def test_distance_score_calculation(recommender):
    """Test distance score calculation"""
    # New York to Boston (~306 km)
    score, distance = await recommender.calculate_distance_score(
        40.7128, -74.0060,  # NYC
        42.3601, -71.0589,  # Boston
        500  # max distance
    )
    
    assert distance > 300 and distance < 310
    assert score > 0 and score < 1
    assert score == pytest.approx(1 - (distance/500), rel=0.01)

@pytest.mark.asyncio
async def test_distance_score_out_of_range(recommender):
    """Test distance score when provider is outside radius"""
    score, distance = await recommender.calculate_distance_score(
        40.7128, -74.0060,  # NYC
        34.0522, -118.2437,  # LA (~3936 km)
        100  # max distance
    )
    
    assert score == 0
    assert distance > 3900

@pytest.mark.asyncio
async def test_category_score_exact_match(recommender):
    """Test exact category match"""
    hierarchy = {
        "Home Services": ["Plumbing", "Electrical", "Carpentry"]
    }
    
    score = await recommender.calculate_category_score(
        "Plumbing",
        "Plumbing",
        hierarchy
    )
    
    assert score == 1.0

@pytest.mark.asyncio
async def test_category_score_child_match(recommender):
    """Test child category match"""
    hierarchy = {
        "Home Services": ["Plumbing", "Electrical", "Carpentry"]
    }
    
    score = await recommender.calculate_category_score(
        "Plumbing",
        "Home Services",
        hierarchy
    )
    
    assert score == 0.8

@pytest.mark.asyncio
async def test_quality_score_calculation(recommender):
    """Test quality score calculation"""
    provider_data = {
        'employee_count': 5,
        'is_approved': True,
        'has_certificates': True,
        'service_count': 10,
        'request_count': 50,
        'avg_rating': 4.5,
        'certificate_skills': ['plumbing', 'electrical'],
        'employee_skills': ['plumbing']
    }
    
    score = await recommender.calculate_quality_score(provider_data)
    
    assert score > 0
    assert score <= 1
    assert score > 0.5  # Should be decent quality

@pytest.mark.asyncio
async def test_quality_score_minimal_data(recommender):
    """Test quality score with minimal provider data"""
    provider_data = {
        'employee_count': 0,
        'is_approved': False,
        'has_certificates': False,
        'service_count': 0,
        'request_count': 0,
        'avg_rating': 0
    }
    
    score = await recommender.calculate_quality_score(provider_data)
    
    assert score == pytest.approx(0.3, rel=0.01)  # Default base score

class TestFeatureExtractor:
    @pytest.fixture
    def extractor(self):
        return FeatureExtractor()
    
    def test_extract_skills_from_certificates(self, extractor):
        """Test skill extraction from certificates"""
        certificates = {
            "certificates": [
                {
                    "name": "Certified Plumbing Professional",
                    "skills": ["pipe installation", "leak repair"]
                },
                {
                    "name": "Electrical Safety Certification",
                    "description": "Certified in electrical wiring and safety"
                }
            ]
        }
        
        skills = extractor.extract_skills_from_certificates(certificates)
        
        assert isinstance(skills, list)
        assert "plumbing" in skills or "pipe installation" in skills
        assert "electrical" in skills or "wiring" in skills

    def test_parse_skills_from_text(self, extractor):
        """Test skill parsing from text"""
        text = "Professional plumber with 10 years experience in pipe fitting"
        
        skills = extractor._parse_skills_from_text(text)
        
        assert "plumbing" in skills
        assert "professional" in skills

@pytest.mark.asyncio
async def test_recommendation_pipeline_integration(recommender):
    """Integration test for full recommendation pipeline"""
    # Mock database responses
    with patch('services.content_based.db_manager.get_session') as mock_session:
        mock_conn = AsyncMock()
        mock_session.return_value.__aenter__.return_value = mock_conn
        
        # Mock category hierarchy query
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Home Services", ["Plumbing", "Electrical"])
        ]
        
        # Mock providers query
        mock_providers = [
            Mock(
                id=1,
                category="Plumbing",
                employee_count=5,
                is_approved=True,
                certificates={"certificates": []},
                latitude=40.7129,
                longitude=-74.0059,
                distance_km=0.5,
                service_count=10,
                request_count=50,
                avg_rating=4.5
            )
        ]
        mock_conn.execute.return_value.fetchall.return_value = mock_providers
        
        # Test recommendation
        result = await recommender.get_recommendations(
            lat=40.7128,
            lng=-74.0060,
            category="Plumbing",
            radius=10,
            limit=20
        )
        
        assert result['total'] > 0
        assert len(result['items']) > 0
        assert result['items'][0]['final_score'] > 0
        assert result['metadata']['processing_time_ms'] > 0