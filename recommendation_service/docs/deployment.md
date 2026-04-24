# 🚢 ServeEase - Production Deployment Guide

## 🏭 Production Architecture
Load Balancer (Nginx/HAProxy)
├── App Instance 1 (Port 8000)
├── App Instance 2 (Port 8000)
└── App Instance 3 (Port 8000)
│
PostgreSQL Primary ←── PostgreSQL Replica
│
Redis Cluster (3 nodes)

## 📦 Production docker-compose.yml

```yaml
version: '3.8'

services:
  postgres:
    image: postgis/postgis:15-3.4
    container_name: serveease-prod-db
    environment:
      POSTGRES_DB: serveease
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - /data/postgres:/var/lib/postgresql/data
    deploy:
      resources:
        limits:
          memory: 4G
    restart: always
    command: >
      postgres -c max_connections=200
               -c shared_buffers=1GB
               -c effective_cache_size=3GB
               -c maintenance_work_mem=512MB
               -c checkpoint_completion_target=0.9
               -c wal_buffers=16MB
               -c default_statistics_target=100

  redis:
    image: redis:7-alpine
    container_name: serveease-prod-redis
    command: redis-server --requirepass ${REDIS_PASSWORD} --maxmemory 2gb --maxmemory-policy allkeys-lru
    ports:
      - "6379:6379"
    volumes:
      - /data/redis:/data
    deploy:
      resources:
        limits:
          memory: 2G
    restart: always

  app:
    build: .
    container_name: serveease-prod-app
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/serveease
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      ENVIRONMENT: production
      WORKERS: 4
    depends_on:
      - postgres
      - redis
    deploy:
      replicas: 3
      resources:
        limits:
          memory: 1G
          cpus: '1'
    restart: always
    command: gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

  nginx:
    image: nginx:alpine
    container_name: serveease-prod-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - /etc/letsencrypt:/etc/letsencrypt
    depends_on:
      - app
    restart: always

  prometheus:
    image: prom/prometheus
    container_name: serveease-prod-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    restart: always

  grafana:
    image: grafana/grafana
    container_name: serveease-prod-grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
    volumes:
      - grafana_data:/var/lib/grafana
    depends_on:
      - prometheus
    restart: always
🔧 Production .env
# Database
DB_USER=serveease_prod
DB_PASSWORD=Strong!Random@Password123
REDIS_PASSWORD=Strong!Redis@Password123

# App
WORKERS=4
LOG_LEVEL=INFO

# Security
SECRET_KEY=your-256-bit-secret-key-here
API_KEYS=key1,key2,key3

# Monitoring
GRAFANA_PASSWORD=admin123

# SSL
DOMAIN=api.serveease.com
EMAIL=admin@serveease.com
📊 Nginx Configuration
# nginx.conf
upstream app_servers {
    server app:8000;
    server app:8001;
    server app:8002;
}

server {
    listen 80;
    server_name api.serveease.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.serveease.com;

    ssl_certificate /etc/letsencrypt/live/api.serveease.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.serveease.com/privkey.pem;
    
    location / {
        proxy_pass http://app_servers;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Rate limiting
        limit_req zone=api burst=20 nodelay;
        limit_req_status 429;
    }

    location /metrics {
        proxy_pass http://prometheus:9090;
    }
}

📈 Prometheus Configuration
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'app'
    static_configs:
      - targets: ['app:8000']
    metrics_path: /metrics

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']
🚀 Deployment Steps
1. Server Preparation
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Setup firewall
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
2. SSL Certificate
# Install certbot
sudo apt install certbot python3-certbot-nginx -y

# Get certificate
sudo certbot --nginx -d api.serveease.com
3. Deploy Application
# Clone repository
git clone https://github.com/TigistAshenafi/ServeEase.git
cd ServeEase/serveease-recommendation

# Create production env
cp .env.production .env

# Pull latest images
docker-compose -f docker-compose.prod.yml pull

# Start services
docker-compose -f docker-compose.prod.yml up -d

# Check logs
docker-compose -f docker-compose.prod.yml logs -f
4. Database Migration
# Run migrations
docker-compose -f docker-compose.prod.yml exec app python migrate.py

# Create backup
docker-compose -f docker-compose.prod.yml exec postgres pg_dump -U serveease_prod serveease > backup_$(date +%Y%m%d).sql
📊 Monitoring Setup
Grafana Dashboards
# Access Grafana
open http://your-server:3000

# Default login
Username: admin
Password: ${GRAFANA_PASSWORD}

# Import dashboards
# - Node Exporter Full (ID: 1860)
# - PostgreSQL (ID: 9628)
# - Redis (ID: 11835)
Alert Rules
# alerts.yml
groups:
  - name: serveease_alerts
    rules:
      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(recommendation_latency_seconds_bucket[5m])) > 0.5
        for: 5m
        annotations:
          summary: "High latency detected"

      - alert: HighErrorRate
        expr: rate(recommendation_requests_total{status="error"}[5m]) / rate(recommendation_requests_total[5m]) > 0.05
        for: 5m
        annotations:
          summary: "Error rate above 5%"

      - alert: DatabaseDown
        expr: pg_up == 0
        for: 1m
        annotations:
          summary: "PostgreSQL is down"
🔄 Backup Strategy
Automated Backups
bash
#!/bin/bash
# /usr/local/bin/backup.sh

BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Database backup
docker-compose -f /opt/serveease/docker-compose.prod.yml exec -T postgres \
  pg_dump -U serveease_prod serveease | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Upload to S3
aws s3 cp $BACKUP_DIR/db_$DATE.sql.gz s3://serveease-backups/

# Keep last 30 days
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete
Cron Job
bash
# Add to crontab
0 2 * * * /usr/local/bin/backup.sh
🚨 Disaster Recovery
bash
# 1. Stop all services
docker-compose -f docker-compose.prod.yml down

# 2. Restore database
gunzip -c latest_backup.sql.gz | docker-compose -f docker-compose.prod.yml exec -T postgres psql -U serveease_prod -d serveease

# 3. Start services
docker-compose -f docker-compose.prod.yml up -d

# 4. Verify
curl https://api.serveease.com/api/v1/health
📈 Performance Tuning
PostgreSQL
sql
-- Tune for your hardware
ALTER SYSTEM SET max_connections = '200';
ALTER SYSTEM SET shared_buffers = '1GB';
ALTER SYSTEM SET effective_cache_size = '3GB';
ALTER SYSTEM SET maintenance_work_mem = '512MB';
ALTER SYSTEM SET checkpoint_completion_target = '0.9';
ALTER SYSTEM SET wal_buffers = '16MB';
ALTER SYSTEM SET default_statistics_target = '100';
Redis
bash
# redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
App
python
# Gunicorn with multiple workers
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
✅ Production Checklist
SSL certificates installed

Firewall configured

Database backups automated

Monitoring alerts set up

Rate limiting enabled

API keys generated

Load testing completed

Documentation updated

Team access configured

Incident response plan ready

🆘 Support
Emergency: +1-xxx-xxx-xxxx

Email: oncall@serveease.com

Slack: #prod-alerts

Runbook: docs/runbook.md

text

---

## 📁 Final Structure
serveease-recommendation/
├── 📄 README.md # Quick start (1 page)
├── 📁 docs/
│ ├── 📄 setup.md # Detailed installation
│ ├── 📄 database.md # Schema & queries
│ └── 📄 deployment.md # Production guide
├── 📄 docker-compose.yml
├── 📄 Dockerfile
├── 📄 requirements.txt
├── 📄 .env.example
└── 📁 core/ services/ api/ etc.

text

**This structure gives users:**
- **README.md** → 5-minute quick start
- **docs/setup.md** → Complete installation
- **docs/database.md** → Schema reference
- **docs/deployment.md** → Production ops

**Clean, professional, and easy to navigate!** 🚀