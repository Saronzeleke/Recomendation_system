from typing import List, Dict, Any, Optional, Set, Tuple
import json
import re
from collections import Counter
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import db_manager
from core.cache import cache_manager

logger = structlog.get_logger()

class FeatureExtractor:
    """Extracts and processes features from provider data"""
    
    def __init__(self):
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=1000,
            stop_words='english',
            ngram_range=(1, 2),
            min_df=2,
            max_df=0.9
        )
        self._service_vectors = None
        self._service_ids = None
        
    async def extract_skills_from_certificates(
        self,
        certificates_json: Dict[str, Any]
    ) -> List[str]:
        """
        Extract skills from JSONB certificates data
        Expected format: {"certificates": [{"name": "...", "skills": [...]}]}
        """
        skills = set()
        
        try:
            # Handle different certificate formats
            if isinstance(certificates_json, dict):
                # Direct certificates array
                if "certificates" in certificates_json:
                    certs = certificates_json["certificates"]
                else:
                    certs = [certificates_json]
            elif isinstance(certificates_json, list):
                certs = certificates_json
            else:
                return []
            
            for cert in certs:
                # Extract from certificate name
                if isinstance(cert, dict):
                    if "name" in cert:
                        # Parse skills from certificate name
                        name_skills = self._parse_skills_from_text(cert["name"])
                        skills.update(name_skills)
                    
                    if "skills" in cert and isinstance(cert["skills"], list):
                        skills.update(cert["skills"])
                    
                    if "description" in cert:
                        desc_skills = self._parse_skills_from_text(cert["description"])
                        skills.update(desc_skills)
                elif isinstance(cert, str):
                    # If certificate is just a string
                    skills.update(self._parse_skills_from_text(cert))
            
        except Exception as e:
            logger.error("certificate_parsing_failed", error=str(e))
        
        return list(skills)
    
    def _parse_skills_from_text(self, text: str) -> Set[str]:
        """Parse skills from text using pattern matching"""
        text = text.lower()
        skills = set()
        
        # Common skill patterns
        patterns = {
            r'\b(plumbing|plumber|pipe|piping)\b': 'plumbing',
            r'\b(electrical|electrician|wiring|circuit)\b': 'electrical',
            r'\b(carpentry|carpenter|wood|furniture)\b': 'carpentry',
            r'\b(painting|painter|paint)\b': 'painting',
            r'\b(hvac|heating|cooling|air condition)\b': 'hvac',
            r'\b(cleaning|cleaner|janitorial)\b': 'cleaning',
            r'\b(landscaping|gardening|lawn)\b': 'landscaping',
            r'\b(moving|mover|relocation)\b': 'moving',
            r'\b(photography|photographer|camera)\b': 'photography',
            r'\b(tutoring|tutor|teaching|education)\b': 'tutoring',
            r'\b(web\s*development|programming|coding|software)\b': 'web_development',
            r'\b(graphic\s*design|designer|illustration)\b': 'graphic_design',
            r'\b(writing|content|copywriting|editor)\b': 'writing',
            r'\b(marketing|seo|social\s*media)\b': 'marketing',
            r'\b(consulting|consultant|advisory)\b': 'consulting'
        }
        
        for pattern, skill in patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                skills.add(skill)
        
        # Also add individual words that might be skills
        words = re.findall(r'\b[a-z]{3,}\b', text)
        common_skill_words = {
            'expert', 'professional', 'certified', 'licensed',
            'technician', 'specialist', 'master', 'skilled'
        }
        for word in words:
            if word in common_skill_words or len(word) > 5:
                skills.add(word)
        
        return skills
    
    async def build_service_vectors(self, session: AsyncSession) -> Tuple[np.ndarray, List[int]]:
        """
        Build TF-IDF vectors for all service titles and descriptions
        Returns vectors and corresponding service IDs
        """
        cache_key = "service_vectors"
        
        # Try cache first
        cached = await cache_manager.get(cache_key)
        if cached:
            self._service_vectors = cached['vectors']
            self._service_ids = cached['service_ids']
            return self._service_vectors, self._service_ids
        
        # Query all active services
        query = text("""
            SELECT 
                s.id,
                s.title,
                s.description,
                sc.name as category_name
            FROM services s
            LEFT JOIN service_categories sc ON s.category_id = sc.id
            WHERE s.is_active = true
        """)
        
        result = await session.execute(query)
        services = result.fetchall()
        
        if not services:
            return np.array([]), []
        
        # Combine title, description, and category for text corpus
        texts = []
        service_ids = []
        
        for service in services:
            text_parts = [
                service.title or '',
                service.description or '',
                service.category_name or ''
            ]
            combined_text = ' '.join(text_parts)
            texts.append(combined_text)
            service_ids.append(service.id)
        
        # Fit and transform
        self._service_vectors = self.tfidf_vectorizer.fit_transform(texts).toarray()
        self._service_ids = service_ids
        
        # Cache the vectors
        await cache_manager.set(
            cache_key,
            {
                'vectors': self._service_vectors,
                'service_ids': self._service_ids
            },
            ttl=3600  # 1 hour
        )
        
        logger.info(
            "service_vectors_built",
            num_services=len(service_ids),
            vector_shape=self._service_vectors.shape
        )
        
        return self._service_vectors, self._service_ids
    
    async def get_similar_services(
        self,
        service_id: int,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Find similar services using cosine similarity"""
        if self._service_vectors is None or self._service_ids is None:
            async with db_manager.get_session() as session:
                await self.build_service_vectors(session)
        
        try:
            idx = self._service_ids.index(service_id)
            vector = self._service_vectors[idx].reshape(1, -1)
            
            # Calculate similarities
            similarities = cosine_similarity(vector, self._service_vectors)[0]
            
            # Get top k similar services (excluding itself)
            similar_indices = np.argsort(similarities)[::-1][1:top_k+1]
            
            results = []
            for i in similar_indices:
                if similarities[i] > 0.1:  # Minimum similarity threshold
                    results.append({
                        'service_id': self._service_ids[i],
                        'similarity_score': float(similarities[i])
                    })
            
            return results
            
        except ValueError:
            logger.error("service_id_not_found", service_id=service_id)
            return []
    
    async def extract_provider_features(
        self,
        provider_id: int
    ) -> Dict[str, Any]:
        """Extract all features for a single provider"""
        async with db_manager.get_session() as session:
            query = text("""
                SELECT 
                    pp.*,
                    array_agg(DISTINCT e.skill) as employee_skills,
                    COUNT(DISTINCT s.id) as service_count,
                    COUNT(DISTINCT sr.id) as request_count,
                    AVG(sr.seeker_rating) as avg_rating
                FROM provider_profiles pp
                LEFT JOIN employees e ON pp.id = e.organization_id
                LEFT JOIN services s ON pp.id = s.provider_id
                LEFT JOIN service_requests sr ON s.id = sr.service_id
                WHERE pp.id = :provider_id
                GROUP BY pp.id
            """)
            
            result = await session.execute(query, {"provider_id": provider_id})
            provider = result.fetchone()
            
            if not provider:
                return {}
            
            features = {
                'provider_id': provider_id,
                'category': provider.category,
                'employee_count': provider.employee_count or 0,
                'is_approved': provider.is_approved,
                'has_certificates': bool(provider.certificates),
                'service_count': provider.service_count or 0,
                'request_count': provider.request_count or 0,
                'avg_rating': float(provider.avg_rating or 0),
                'location': (provider.latitude, provider.longitude) if provider.latitude else None
            }
            
            # Extract skills from certificates
            if provider.certificates:
                cert_skills = await self.extract_skills_from_certificates(provider.certificates)
                features['certificate_skills'] = cert_skills
            
            # Combine employee skills
            if provider.employee_skills:
                # Handle PostgreSQL array format
                skills = [s for s in provider.employee_skills if s]
                features['employee_skills'] = skills
            
            return features

feature_extractor = FeatureExtractor()