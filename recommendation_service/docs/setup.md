🔧 ServeEase – Complete Setup Guide

📋 Prerequisites

# Docker
```
docker --version        # 24.0+
docker compose version  # 2.20+
```
# Git

git --version
```
Minimum requirement:
  .4GB RAM allocated to Docker
  ```
🏗️ Step 1 – Clone the Repository

```git clone https://github.com/TigistAshenafi/ServeEase.git```

```cd ServeEase/serveease-recommendation```

Verify structure:
 ```ls -la```
Expected files:
```
docker-compose.yml
requirements.txt
core/
services/
api/
```
🐳 Step 2 – Docker Compose Setup

Create docker-compose.yml
```
services:
  postgres:
    image: postgis/postgis:15-3.4
    environment:
      POSTGRES_DB: serveease
      POSTGRES_USER: serveease_user
      POSTGRES_PASSWORD: secure_password_123
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U serveease_user"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru

  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://serveease_user:secure_password_123@postgres:5432/serveease
      REDIS_URL: redis://redis:6379/0
      ENVIRONMENT: development
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - ./:/app
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

  celery-worker:
    build: .
    command: celery -A tasks.celery_app worker --loglevel=info
    environment:
      DATABASE_URL: postgresql://serveease_user:secure_password_123@postgres:5432/serveease
      REDIS_URL: redis://redis:6379/0
    depends_on:
      - redis
      - postgres
    volumes:
      - ./:/app

volumes:
  postgres_data:
  redis_data:
```
🐍 Step 3 – Dockerfile

Create Dockerfile
```
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
```
# Copy requirements and install Python dependencies

COPY requirements.txt .

```RUN pip install --no-cache-dir -r requirements.txt```

# Copy application code

COPY . .

# Create non-root user

```
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
📦 Step 4 – Python Requirements


Create requirements.txt

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
asyncpg==0.29.0
sqlalchemy==2.0.23
pydantic==2.5.0
redis==5.0.1
celery==5.3.4
numpy==1.26.2
pandas==2.1.3
scikit-learn==1.3.2
lightfm==1.17
python-dotenv==1.0.0
```
⚙️ Step 5 – Environment Variables

Create .env

```APP_NAME=ServeEase Recommendation Service
ENVIRONMENT=development
API_PREFIX=/api/v1

DATABASE_URL=postgresql://serveease_user:secure_password_123@postgres:5432/serveease
REDIS_URL=redis://redis:6379/0

WEIGHT_DISTANCE=0.60
WEIGHT_CATEGORY=0.30
WEIGHT_QUALITY=0.10

DEFAULT_RADIUS=10
MAX_RADIUS=100
```

🚀 Step 6 – Build and Run

# Start containers

```docker compose up -d --build```

# Wait for services

```sleep 30```

# Check containers

```docker compose ps```

# View logs

```docker compose logs -f app```

✅ Step 7 – Verify the System

# Health check

```curl http://localhost:8000/api/v1/health```

Example request:

```curl "http://localhost:8000/api/v1/recommendations?lat=40.7128&lng=-74.0060&radius=10"```

Swagger UI:

```http://localhost:8000/api/docs```

🎯 Quick Commands

# Stop containers

```docker compose down```

# Restart API

```docker compose restart app```

# Rebuild containers

```docker compose up -d --build```

# Reset environment

```docker compose down -v```

🚨 Troubleshooting

| Issue                       | Fix                                 |
| --------------------------- | ----------------------------------- |
| Database connection refused | `docker compose restart postgres`   |
| Port 8000 already in use    | Change port in `docker-compose.yml` |
| No providers returned       | Run database seed script            |
| Module errors               | `docker compose up -d --build`      |
