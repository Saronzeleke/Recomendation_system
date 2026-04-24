from typing import List, Dict, Any, Optional, Tuple
import math
from datetime import datetime
import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
from asyncpg import Connection

from core.config import settings
from core.database import db_manager
from core.cache import cache_manager, cached_result
from services.feature_extractor import feature_extractor

logger = structlog.get_logger()

class ContentBasedRecommender:
    """Phase 1: Content-based recommendation system"""
    
    def __init__(self):
        self.weights = {
            'distance': settings.weight_distance,
            'category': settings.weight_category,
            'quality': settings.weight_quality
        }
    
    async def calculate_distance_score(
        self,
        provider_lat: float,
        provider_lng: float,
        user_lat: float,
        user_lng: float,
        max_distance: float
    ) -> Tuple[float, float]:
        """
        Calculate distance score using haversine formula
        Returns (score, distance_km)
        """
        # Haversine formula for accurate distance calculation
        R = 6371  # Earth's radius in kilometers
        
        lat1, lon1 = math.radians(provider_lat), math.radians(provider_lng)
        lat2, lon2 = math.radians(user_lat), math.radians(user_lng)
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        distance = R * c
        
        # Score: inverse of distance (closer = higher score)
        if distance <= max_distance:
            # Linear decay: 1.0 at 0km, 0.0 at max_distance
            score = max(0, 1 - (distance / max_distance))
        else:
            score = 0
        
        return score, distance
    
    async def calculate_category_score(
        self,
        provider_category: str,
        user_category: Optional[str],
        category_hierarchy: Dict[str, List[str]]
    ) -> float:
        """
        Calculate category match score with hierarchy fallback
        """
        if not user_category:
            return 0.5  # Default score when no category specified
        
        # Exact match
        if provider_category == user_category:
            return 1.0
        
        # Check hierarchy (parent/child relationship)
        if user_category in category_hierarchy:
            if provider_category in category_hierarchy[user_category]:
                return 0.8  # Child category match
        
        # Check if provider category is parent of user category
        for parent, children in category_hierarchy.items():
            if user_category in children and provider_category == parent:
                return 0.7  # Parent category match
        
        # Check sibling categories (same parent)
        for parent, children in category_hierarchy.items():
            if user_category in children:
                if provider_category in children:
                    return 0.6  # Sibling category match
        
        return 0.0
    
    async def calculate_quality_score(
        self,
        provider_data: Dict[str, Any]
    ) -> float:
        """
        Calculate provider quality score based on multiple signals
        """
        score = 0.0
        signals = 0
        
        # Employee count (normalized)
        if provider_data.get('employee_count', 0) > 0:
            emp_score = min(provider_data['employee_count'] / 10, 1.0)  # Cap at 10+ employees
            score += emp_score
            signals += 1
        
        # Approval status
        if provider_data.get('is_approved', False):
            score += 1.0
            signals += 1
        
        # Certificates presence
        if provider_data.get('has_certificates', False):
            score += 0.8
            signals += 1
        
        # Service count (normalized)
        service_count = provider_data.get('service_count', 0)
        if service_count > 0:
            service_score = min(service_count / 5, 1.0)  # Cap at 5+ services
            score += service_score
            signals += 1
        
        # Request count and ratings
        request_count = provider_data.get('request_count', 0)
        avg_rating = provider_data.get('avg_rating', 0)
        
        if request_count > 0:
            # Weight by number of requests and average rating
            request_score = min(request_count / 20, 1.0)  # Cap at 20+ requests
            rating_score = avg_rating / 5.0  # Normalize to 0-1
            
            score += (request_score * 0.5 + rating_score * 0.5)
            signals += 1
        
        # Skills diversity
        skills = set()
        skills.update(provider_data.get('certificate_skills', []))
        skills.update(provider_data.get('employee_skills', []))
        
        if skills:
            skill_score = min(len(skills) / 10, 1.0)  # Cap at 10+ unique skills
            score += skill_score
            signals += 1
        
        # Calculate average if we have signals
        if signals > 0:
            return score / signals
        else:
            return 0.3  # Default base quality score
    
    async def get_category_hierarchy(self, session: AsyncSession) -> Dict[str, List[str]]:
        """Build category hierarchy from database - FIXED with type casting"""
        query = text("""
            WITH RECURSIVE category_tree AS (
                SELECT id, name, parent_id, name::varchar as path
                FROM service_categories
                WHERE parent_id IS NULL
                
                UNION ALL
                
                SELECT sc.id, sc.name, sc.parent_id, 
                       (ct.path || ' > ' || sc.name)::varchar as path
                FROM service_categories sc
                INNER JOIN category_tree ct ON sc.parent_id = ct.id
            )
            SELECT 
                c1.name as parent_name,
                array_agg(c2.name) as children
            FROM service_categories c1
            LEFT JOIN service_categories c2 ON c1.id = c2.parent_id
            WHERE c2.id IS NOT NULL
            GROUP BY c1.name
        """)
        
        result = await session.execute(query)
        hierarchy = {}
        
        for row in result:
            if row.children:
                hierarchy[row.parent_name] = list(row.children)
        
        return hierarchy
    
    @cached_result(ttl=300, key_prefix="provider_features")
    async def get_provider_features_batch(
        self,
        provider_ids: List[int]
    ) -> Dict[int, Dict[str, Any]]:
        """Get features for multiple providers efficiently"""
        async with db_manager.get_session() as session:
            query = text("""
                SELECT 
                    pp.id,
                    pp.business_name,
                    pp.category,
                    pp.employee_count,
                    pp.is_approved,
                    pp.certificates,
                    pp.latitude,
                    pp.longitude,
                    COUNT(DISTINCT s.id) as service_count,
                    COUNT(DISTINCT sr.id) as request_count,
                    COALESCE(AVG(sr.seeker_rating), 0) as avg_rating,
                    array_agg(DISTINCT e.skill) as employee_skills
                FROM provider_profiles pp
                LEFT JOIN services s ON pp.id = s.provider_id AND s.is_active = true
                LEFT JOIN service_requests sr ON s.id = sr.service_id
                LEFT JOIN employees e ON pp.id = e.organization_id AND e.is_active = true
                WHERE pp.id = ANY(:provider_ids)
                GROUP BY pp.id, pp.business_name
            """)
            
            result = await session.execute(
                query,
                {"provider_ids": provider_ids}
            )
            
            features = {}
            for row in result:
                provider_features = {
                    'provider_id': row.id,
                    'business_name': row.business_name,
                    'category': row.category,
                    'employee_count': row.employee_count or 0,
                    'is_approved': row.is_approved,
                    'has_certificates': bool(row.certificates),
                    'service_count': row.service_count or 0,
                    'request_count': row.request_count or 0,
                    'avg_rating': float(row.avg_rating or 0),
                    'location': (row.latitude, row.longitude) if row.latitude else None
                }
                
                # Extract skills from certificates
                if row.certificates:
                    cert_skills = await feature_extractor.extract_skills_from_certificates(
                        row.certificates
                    )
                    provider_features['certificate_skills'] = cert_skills
                
                features[row.id] = provider_features
            
            return features
    
    async def get_recommendations(
        self,
        lat: float,
        lng: float,
        category: Optional[str] = None,
        radius: int = 10,
        limit: int = 20,
        offset: int = 0,
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get ranked provider recommendations based on content-based scoring
        """
        start_time = datetime.now()
        if user_id:
            logger.debug("content_based_recommendations", user_id=user_id)
            
        try:
            # Get category hierarchy
            async with db_manager.get_session() as session:
                category_hierarchy = await self.get_category_hierarchy(session)
            
            # Query nearby providers using haversine formula
            async with db_manager.get_session() as session:
                query = text("""
                    WITH provider_distances AS (
                        SELECT 
                            pp.id,
                            pp.business_name,
                            pp.category,
                            pp.employee_count,
                            pp.is_approved,
                            pp.certificates,
                            pp.latitude,
                            pp.longitude,
                            -- Calculate distance using haversine formula
                            6371 * acos(
                                LEAST(1.0, 
                                    cos(radians(:lat)) * 
                                    cos(radians(pp.latitude)) * 
                                    cos(radians(pp.longitude) - radians(:lng)) + 
                                    sin(radians(:lat)) * 
                                    sin(radians(pp.latitude))
                                )
                            ) as distance_km
                        FROM provider_profiles pp
                        WHERE 
                            pp.is_active = true 
                            AND pp.status = 'active'
                            AND pp.latitude IS NOT NULL 
                            AND pp.longitude IS NOT NULL
                    )
                    SELECT 
                        pd.*,
                        COUNT(DISTINCT s.id) as service_count,
                        COUNT(DISTINCT sr.id) as request_count,
                        COALESCE(AVG(sr.seeker_rating), 0) as avg_rating
                    FROM provider_distances pd
                    LEFT JOIN services s ON pd.id = s.provider_id AND s.is_active = true
                    LEFT JOIN service_requests sr ON s.id = sr.service_id
                    WHERE pd.distance_km <= :radius
                    GROUP BY 
                        pd.id, pd.business_name, pd.category, pd.employee_count, 
                        pd.is_approved, pd.certificates, 
                        pd.latitude, pd.longitude, pd.distance_km
                    ORDER BY pd.distance_km
                """)
                
                result = await session.execute(
                    query,
                    {
                        "lat": lat,
                        "lng": lng,
                        "radius": radius
                    }
                )
                
                providers = result.fetchall()
            
            if not providers:
                logger.info("no_providers_found_within_radius", 
                           lat=lat, lng=lng, radius=radius)
                return {
                    "items": [],
                    "total": 0,
                    "metadata": {
                        "lat": lat,
                        "lng": lng,
                        "radius": radius,
                        "category": category,
                        "processing_time_ms": (datetime.now() - start_time).total_seconds() * 1000
                    }
                }
            
            # Calculate scores for each provider
            recommendations = []
            
            for provider in providers:
                # Distance score
                distance_km = provider.distance_km
                distance_score = max(0, 1 - (distance_km / radius))
                
                # Category score
                category_score = await self.calculate_category_score(
                    provider.category,
                    category,
                    category_hierarchy
                )
                
                # Quality score
                provider_features = {
                    'employee_count': provider.employee_count,
                    'is_approved': provider.is_approved,
                    'has_certificates': bool(provider.certificates),
                    'service_count': provider.service_count or 0,
                    'request_count': provider.request_count or 0,
                    'avg_rating': float(provider.avg_rating or 0)
                }
                
                quality_score = await self.calculate_quality_score(provider_features)
                
                # Calculate weighted final score
                final_score = (
                    self.weights['distance'] * distance_score +
                    self.weights['category'] * category_score +
                    self.weights['quality'] * quality_score
                )
                
                # Determine reason for recommendation
                reasons = []
                if distance_score > 0.7:
                    reasons.append("Very close to your location")
                elif distance_score > 0.3:
                    reasons.append("Within your search radius")
                
                if category_score > 0.8:
                    if category:
                        reasons.append(f"Specializes in {category}")
                    else:
                        reasons.append("Specializes in this category")
                elif category_score > 0.5:
                    reasons.append("Related service category")
                
                if quality_score > 0.7:
                    reasons.append("High-quality provider with good ratings")
                elif provider_features['is_approved']:
                    reasons.append("Verified provider")
                
                if not reasons:
                    reasons.append("Available in your area")
                
                recommendations.append({
                    "provider_id": provider.id,
                    "business_name": provider.business_name,
                    "distance_km": round(distance_km, 2),
                    "distance_score": round(distance_score, 3),
                    "category_score": round(category_score, 3),
                    "quality_score": round(quality_score, 3),
                    "final_score": round(final_score, 3),
                    "reason_for_recommendation": reasons[0] if reasons else "Recommended provider",
                    "all_reasons": reasons,
                    "metadata": {
                        "category": provider.category,
                        "business_name": provider.business_name,
                        "service_count": provider.service_count,
                        "request_count": provider.request_count,
                        "avg_rating": round(float(provider.avg_rating), 2) if provider.avg_rating else None
                    }
                })
            
            # Sort by final score
            recommendations.sort(key=lambda x: x['final_score'], reverse=True)
            
            # Apply pagination
            total = len(recommendations)
            paginated = recommendations[offset:offset + limit]
            
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            
            logger.info(
                "recommendations_generated",
                total_found=total,
                returned=len(paginated),
                processing_time_ms=round(processing_time, 2),
                lat=lat,
                lng=lng,
                radius=radius
            )
            
            return {
                "items": paginated,
                "total": total,
                "metadata": {
                    "lat": lat,
                    "lng": lng,
                    "radius": radius,
                    "category": category,
                    "processing_time_ms": round(processing_time, 2),
                    "weights": self.weights
                }
            }
            
        except Exception as e:
            logger.error(
                "recommendation_generation_failed",
                error=str(e),
                exc_info=True,
                lat=lat,
                lng=lng
            )
            
            # Return empty result with error metadata
            return {
                "items": [],
                "total": 0,
                "metadata": {
                    "lat": lat,
                    "lng": lng,
                    "radius": radius,
                    "category": category,
                    "error": str(e),
                    "processing_time_ms": (datetime.now() - start_time).total_seconds() * 1000
                }
            }

# Global recommender instance
content_based_recommender = ContentBasedRecommender()