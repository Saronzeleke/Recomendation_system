# 🗄️ ServeEase - Database Schema Guide

## 📊 Core Tables

### 👤 users
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    role VARCHAR(50),
    is_active BOOLEAN DEFAULT true
);
```
📁 service_categories
CREATE TABLE service_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE,
    parent_id INTEGER REFERENCES service_categories(id),
    hierarchy TEXT
);
🏢 provider_profiles
CREATE TABLE provider_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    category VARCHAR(255),
    business_name VARCHAR(255),
    latitude FLOAT,
    longitude FLOAT,
    location_geom geography(POINT, 4326),
    status VARCHAR(50) DEFAULT 'active',
    is_approved BOOLEAN DEFAULT false,
    certificates JSONB,
    employee_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true
);
🔧 services
CREATE TABLE services (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES provider_profiles(id),
    category_id INTEGER REFERENCES service_categories(id),
    title VARCHAR(255),
    description TEXT,
    is_active BOOLEAN DEFAULT true
);
📝 service_requests
CREATE TABLE service_requests (
    id SERIAL PRIMARY KEY,
    seeker_id INTEGER REFERENCES users(id),
    provider_id INTEGER REFERENCES provider_profiles(id),
    service_id INTEGER REFERENCES services(id),
    status VARCHAR(50),
    seeker_rating FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);
👥 employees
CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES provider_profiles(id),
    skills TEXT[],
    is_active BOOLEAN DEFAULT true
);
📊 activity_logs
CREATE TABLE activity_logs (
    id SERIAL PRIMARY KEY,
    type VARCHAR(50),
    user_id INTEGER REFERENCES users(id),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
🗺️ PostGIS Setup
-- Enable extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Add geometry column
ALTER TABLE provider_profiles ADD COLUMN IF NOT EXISTS location_geom geography(POINT, 4326);

-- Update from lat/lng
UPDATE provider_profiles 
SET location_geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Create spatial index
CREATE INDEX idx_provider_profiles_location ON provider_profiles USING GIST (location_geom);

⚡ Performance Views
📊 Materialized View
CREATE MATERIALIZED VIEW mv_provider_features AS
SELECT 
    pp.id as provider_id,
    pp.user_id,
    pp.category,
    pp.business_name,
    pp.location_geom,
    pp.employee_count,
    pp.is_approved,
    CASE WHEN pp.certificates IS NOT NULL THEN 1 ELSE 0 END as has_certificates,
    COALESCE(s.avg_rating, 0) as avg_rating,
    COALESCE(s.total_services, 0) as total_services
FROM provider_profiles pp
LEFT JOIN (
    SELECT provider_id, AVG(seeker_rating) as avg_rating, COUNT(*) as total_services
    FROM services s
    LEFT JOIN service_requests sr ON s.id = sr.service_id
    GROUP BY provider_id
) s ON pp.id = s.provider_id;

🔄 Auto-Refresh Trigger
CREATE OR REPLACE FUNCTION refresh_provider_features()
RETURNS TRIGGER AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_provider_features;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER refresh_provider_features_on_provider
    AFTER INSERT OR UPDATE OR DELETE ON provider_profiles
    FOR EACH STATEMENT EXECUTE FUNCTION refresh_provider_features();
📏 Distance Functions
-- Calculate distance between two points (km)
CREATE OR REPLACE FUNCTION calculate_distance(
    lat1 float, lng1 float, lat2 float, lng2 float
) RETURNS float AS $$
BEGIN
    RETURN ST_DistanceSphere(
        ST_MakePoint(lng1, lat1),
        ST_MakePoint(lng2, lat2)
    ) / 1000;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Usage
SELECT *, calculate_distance(40.7128, -74.0060, latitude, longitude) as distance_km
FROM provider_profiles
WHERE calculate_distance(40.7128, -74.0060, latitude, longitude) <= 10;
🎯 Sample Data
-- Insert providers
INSERT INTO provider_profiles (user_id, category, business_name, latitude, longitude, is_approved, employee_count)
VALUES 
(1, 'Plumbing', 'NYC Plumbing Pros', 40.7128, -74.0060, true, 5),
(2, 'Electrical', 'Spark Electric NYC', 40.7282, -73.9942, true, 3);

-- Insert services
INSERT INTO services (provider_id, category_id, title, description)
SELECT 
    p.id, c.id, 'Emergency Plumbing', '24/7 emergency service'
FROM provider_profiles p, service_categories c
WHERE p.business_name = 'NYC Plumbing Pros' AND c.name = 'Plumbing';
📊 Useful Queries
-- Find nearby providers (10km)
SELECT *, ST_Distance(location_geom, ST_SetSRID(ST_MakePoint(-74.0060, 40.7128), 4326)::geography)/1000 as distance_km
FROM provider_profiles
WHERE ST_DWithin(location_geom, ST_SetSRID(ST_MakePoint(-74.0060, 40.7128), 4326)::geography, 10000)
ORDER BY distance_km;

-- Provider stats
SELECT p.business_name, p.category, COUNT(s.id) as service_count, AVG(r.seeker_rating) as avg_rating
FROM provider_profiles p
LEFT JOIN services s ON p.id = s.provider_id
LEFT JOIN service_requests r ON s.id = r.service_id
GROUP BY p.id;

-- Active providers by category
SELECT category, COUNT(*) as count
FROM provider_profiles
WHERE is_active = true AND status = 'active'
GROUP BY category;
🔧 Maintenance
# Backup
docker-compose exec postgres pg_dump -U serveease_user serveease > backup.sql

# Restore
cat backup.sql | docker-compose exec -T postgres psql -U serveease_user -d serveease

# Analyze
docker-compose exec postgres psql -U serveease_user -d serveease -c "ANALYZE;"

# Vacuum
docker-compose exec postgres psql -U serveease_user -d serveease -c "VACUUM ANALYZE;"
📈 Indexes
-- Spatial index
CREATE INDEX idx_provider_profiles_location ON provider_profiles USING GIST (location_geom);

-- Foreign key indexes
CREATE INDEX idx_services_provider_id ON services(provider_id);
CREATE INDEX idx_service_requests_provider_id ON service_requests(provider_id);
CREATE INDEX idx_service_requests_seeker_id ON service_requests(seeker_id);

-- Status indexes
CREATE INDEX idx_provider_profiles_status ON provider_profiles(status, is_active);
CREATE INDEX idx_services_is_active ON services(is_active);
🚨 Troubleshooting
-- Check table sizes
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- Find missing indexes
SELECT schemaname, tablename, attname, n_distinct, correlation
FROM pg_stats
WHERE correlation < 1 AND correlation > -1
ORDER BY correlation;

-- Check connection count
SELECT count(*) FROM pg_stat_activity;