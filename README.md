# ServeEase Recommendation Service

A production-ready, scalable recommendation system for service marketplaces built with modern data science and engineering practices.

## 🎯 Overview

ServeEase is an intelligent recommendation engine that helps users discover service providers in their area. The system combines multiple recommendation approaches:

- **Content-Based Filtering**: Recommends providers based on location proximity, service categories, and quality metrics
- **Collaborative Filtering**: Learns from user interactions and provider ratings using advanced machine learning
- **Hybrid Approach**: Combines both methods for optimal recommendations

## 🏗️ Architecture

### Core Components

- **API Layer**: FastAPI-based REST API with async support
- **Database**: PostgreSQL with PostGIS for geospatial queries
- **Cache**: Redis for high-performance caching
- **Background Tasks**: Celery for asynchronous processing
- **Monitoring**: Prometheus metrics with Grafana dashboards
- **Machine Learning**: LightFM for collaborative filtering, scikit-learn for feature engineering

### System Flow

```
User Request → API Gateway → Cache Check → Recommendation Engine → Database Query → ML Scoring → Response
```

## 🚀 Features

### Recommendation Engine
- **Geospatial Recommendations**: Haversine distance calculations for accurate location-based matching
- **Category Matching**: Hierarchical service categorization with similarity scoring
- **Quality Scoring**: Multi-factor quality assessment (ratings, certifications, experience)
- **Personalized Recommendations**: User interaction history analysis
- **Real-time Updates**: Continuous model retraining with new data

### Performance & Scalability
- **Async Processing**: Non-blocking I/O with asyncpg and aiohttp
- **Intelligent Caching**: Multi-level caching strategy (Redis + in-memory)
- **Load Balancing**: Horizontal scaling support
- **Background Processing**: Celery workers for heavy computations

### Monitoring & Observability
- **Metrics Collection**: Prometheus integration with custom business metrics
- **Structured Logging**: JSON logging with correlation IDs
- **Health Checks**: Comprehensive system health monitoring
- **Performance Tracking**: Request latency and throughput monitoring

### Developer Experience
- **Auto Documentation**: OpenAPI/Swagger UI
- **Type Safety**: Full Pydantic model validation
- **Testing**: Comprehensive test suite with pytest
- **Code Quality**: Linting and formatting standards

## 📊 Data Science Implementation

### Recommendation Algorithm

The system uses a weighted scoring approach combining three factors:

```
Final Score = (0.60 × Distance Score) + (0.30 × Category Score) + (0.10 × Quality Score)
```

#### Distance Scoring
- Uses haversine formula for accurate great-circle distance
- Normalized score: `max(0, 1 - (distance / search_radius))`
- Optimized with PostGIS spatial indexes

#### Category Scoring
- Hierarchical category matching with parent/child relationships
- Exact match: 1.0, Child category: 0.8, Parent category: 0.7, Sibling: 0.6
- Configurable category weights

#### Quality Scoring
- Multi-dimensional quality assessment:
  - Provider approval status (20% weight)
  - Certificate validation (20% weight)
  - Employee count and experience (20% weight)
  - Service portfolio size (20% weight)
  - Average user ratings (20% weight)
  - Interaction volume and engagement

### Machine Learning Pipeline

#### Collaborative Filtering (Phase 2)
- **Framework**: LightFM (Bayesian Personalized Ranking)
- **Features**: User-item interaction matrix with content features
- **Training Data**: Service request history, ratings, and implicit feedback
- **Model Updates**: Automated retraining with MLflow tracking

#### Feature Engineering
- **Text Processing**: TF-IDF for service descriptions and certificate analysis
- **Geospatial Features**: Distance bands and location clusters
- **Temporal Features**: Time-based patterns and seasonality
- **Interaction Features**: User engagement metrics and conversion rates

## 🛠️ Technology Stack

### Backend
- **Framework**: FastAPI (Python async web framework)
- **Database**: PostgreSQL 15 with PostGIS 3.4
- **Cache**: Redis 7 with persistence
- **Task Queue**: Celery with Redis broker
- **ORM**: SQLAlchemy with async support

### Data Science & ML
- **Core ML**: scikit-learn, LightFM, implicit
- **Data Processing**: pandas, NumPy
- **Experiment Tracking**: MLflow
- **Model Serialization**: joblib

### Infrastructure & DevOps
- **Containerization**: Docker & Docker Compose
- **Monitoring**: Prometheus, Grafana
- **Logging**: structlog with JSON formatting
- **Configuration**: Pydantic settings with environment validation

### Quality Assurance
- **Testing**: pytest with async support
- **Code Quality**: Black, isort, flake8
- **API Testing**: HTTPX for integration tests
- **Performance Testing**: Locust (planned)

## 📁 Project Structure

```
recommendation_service/
├── api/                    # API layer
│   ├── endpoints.py       # REST endpoints with Prometheus metrics
│   ├── models.py          # Pydantic request/response models
│   └── dependencies.py    # FastAPI dependencies and validation
├── core/                  # Core functionality
│   ├── config.py          # Application configuration with Pydantic
│   ├── database.py        # Async PostgreSQL connection management
│   └── cache.py           # Redis caching with aiocache
├── services/              # Business logic
│   ├── content_based.py   # Content-based recommender (Phase 1)
│   ├── hybrid.py          # Hybrid recommender with LightFM (Phase 2)
│   ├── geocoding.py       # Address geocoding with geopy
│   └── feature_extractor.py # ML feature engineering with sklearn
├── ml/                    # Machine learning pipeline
│   ├── training.py        # Model training with LightFM
│   └── models/            # Saved models and artifacts
├── tasks/                 # Background tasks
│   └── celery_app.py      # Celery configuration and tasks
├── monitoring/            # Observability
│   ├── prometheus.yml     # Metrics collection configuration
│   └── grafana-dashboard.json # Dashboard definition
├── tests/                 # Test suite
│   ├── test_api.py        # API endpoint tests
│   ├── test_scoring.py    # Recommendation algorithm tests
│   └── ...
└── docs/                  # Documentation
    ├── database.md        # Database schema and relationships
    ├── deployment.md      # Deployment guide
    └── setup.md           # Setup instructions
```

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+
- PostgreSQL 15+ (with PostGIS)
- Redis 7+

### Development Setup

1. **Clone and navigate**:
   ```bash
   git clone <repository-url>
   cd recommendation_service
   ```

2. **Environment setup**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start services**:
   ```bash
   docker-compose up -d postgres redis
   ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Initialize database**:
   ```bash
   # Run database migrations
   alembic upgrade head

   # Load sample data
   python -m scripts.load_sample_data
   ```

6. **Start the application**:
   ```bash
   uvicorn main:app --reload
   ```

7. **Access the API**:
   - API Documentation: http://localhost:8000/api/docs
   - Health Check: http://localhost:8000/api/v1/health
   - Metrics: http://localhost:8000/metrics

### Production Deployment

```bash
# Build and deploy
docker-compose -f docker-compose.prod.yml up -d

# Scale workers
docker-compose up -d --scale celery-worker=3
```

## 📡 API Usage

### Get Recommendations

```bash
curl "http://localhost:8000/api/v1/recommendations?lat=40.7128&lng=-74.0060&category=plumbing&radius=10&limit=20"
```

**Response**:
```json
{
  "items": [
    {
      "id": 123,
      "business_name": "ABC Plumbing",
      "category": "plumbing",
      "distance_km": 2.5,
      "score": 0.85,
      "reasons": ["Very close to your location", "Specializes in plumbing"],
      "rating": 4.8,
      "services_count": 15
    }
  ],
  "total": 1,
  "metadata": {
    "processing_time_ms": 45.2,
    "algorithm": "content_based"
  }
}
```

### Geocoding

```bash
curl "http://localhost:8000/api/v1/recommendations/geocode?address=123%20Main%20St%2C%20New%20York%2C%20NY"
```

## 🔧 Configuration

Key configuration options in `.env`:

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5433/serveease

# Redis
REDIS_URL=redis://localhost:6379/0

# Recommendation Weights
WEIGHT_DISTANCE=0.60
WEIGHT_CATEGORY=0.30
WEIGHT_QUALITY=0.10

# ML Features
ENABLE_HYBRID_RECOMMENDATIONS=true
MIN_INTERACTIONS_FOR_ML=1000

# Monitoring
PROMETHEUS_PORT=9090
```

## 📈 Monitoring & Metrics

### Key Metrics
- `recommendation_latency_seconds`: Request processing time
- `recommendation_requests_total`: Request count by status
- `cache_hit_ratio`: Cache effectiveness
- `model_accuracy`: ML model performance

### Grafana Dashboard
Pre-configured dashboard available at `/monitoring/grafana-dashboard.json`

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=recommendation_service --cov-report=html

# Run specific tests
pytest tests/test_api.py -v
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

### Code Standards
- **Formatting**: Black with 88 character line length
- **Imports**: isort with standard library separation
- **Linting**: flake8 with custom configuration
- **Types**: Full type hints required

## 📚 Documentation

- [Database Schema](./docs/database.md)
- [Deployment Guide](./docs/deployment.md)
- [Setup Instructions](./docs/setup.md)
- [API Reference](http://localhost:8000/api/docs) (when running)

## 🔄 CI/CD Pipeline

- **Automated Testing**: GitHub Actions with pytest
- **Code Quality**: Automated linting and formatting checks
- **Security Scanning**: Dependency vulnerability checks
- **Performance Testing**: Load testing on staging environment

## 🚨 Troubleshooting

### Common Issues

1. **Database Connection Failed**
   - Ensure PostgreSQL is running with PostGIS
   - Check DATABASE_URL configuration

2. **Redis Connection Error**
   - Verify Redis service is running
   - Check REDIS_URL configuration

3. **ML Model Not Loading**
   - Run model training pipeline
   - Check model file permissions

### Logs
```bash
# View application logs
docker-compose logs app

# View Celery worker logs
docker-compose logs celery-worker
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👥 Acknowledgments

- LightFM library for collaborative filtering
- PostGIS for geospatial capabilities
- FastAPI community for excellent documentation
- Open source contributors

---

Built with ❤️ for scalable recommendation systems