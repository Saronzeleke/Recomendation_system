-- First, add geometry column and update existing data
ALTER TABLE provider_profiles ADD COLUMN IF NOT EXISTS location_geom geography(POINT, 4326);
UPDATE provider_profiles 
SET location_geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_provider_profiles_location ON provider_profiles USING GIST (location_geom);

-- Create the materialized view directly
DROP MATERIALIZED VIEW IF EXISTS mv_provider_features;
CREATE MATERIALIZED VIEW mv_provider_features AS
SELECT 
    pp.id as provider_id,
    pp.user_id,
    pp.category,
    pp.location_geom,
    COALESCE(pp.employee_count, 0) as employee_count,
    CASE WHEN pp.is_approved THEN 1 ELSE 0 END as is_approved,
    CASE WHEN pp.certificates IS NOT NULL AND jsonb_array_length(pp.certificates) > 0 THEN 1 ELSE 0 END as has_certificates,
    COALESCE(s.avg_rating, 0) as avg_rating,
    COALESCE(s.total_services, 0) as total_services,
    COALESCE(s.total_completed_requests, 0) as total_completed_requests
FROM provider_profiles pp
LEFT JOIN (
    SELECT 
        s.provider_id,
        COUNT(DISTINCT s.id) as total_services,
        AVG(sr.seeker_rating) as avg_rating,
        COUNT(DISTINCT CASE WHEN sr.status = 'completed' THEN sr.id END) as total_completed_requests
    FROM services s
    LEFT JOIN service_requests sr ON s.id = sr.service_id
    GROUP BY s.provider_id
) s ON pp.id = s.provider_id
WHERE pp.is_active = true AND pp.status = 'active';

CREATE UNIQUE INDEX idx_mv_provider_features_id ON mv_provider_features (provider_id);
CREATE INDEX idx_mv_provider_features_location ON mv_provider_features USING GIST (location_geom);

-- Now recreate the function without the problematic refresh
CREATE OR REPLACE FUNCTION create_spatial_indexes() RETURNS void AS \$\$
BEGIN
    -- Add geometry column to provider_profiles if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'provider_profiles' AND column_name = 'location_geom'
    ) THEN
        ALTER TABLE provider_profiles ADD COLUMN location_geom geography(POINT, 4326);
    END IF;
    
    -- Update geometry from lat/lng
    UPDATE provider_profiles 
    SET location_geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND location_geom IS NULL;
    
    -- Create spatial index if not exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_provider_profiles_location'
    ) THEN
        CREATE INDEX idx_provider_profiles_location ON provider_profiles USING GIST (location_geom);
    END IF;
END;
\$\$ LANGUAGE plpgsql;

-- Drop and recreate the refresh function
CREATE OR REPLACE FUNCTION refresh_provider_features()
RETURNS TRIGGER AS \$\$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_provider_features;
    RETURN NULL;
END;
\$\$ LANGUAGE plpgsql;

-- Recreate triggers
DROP TRIGGER IF EXISTS refresh_provider_features_on_provider ON provider_profiles;
CREATE TRIGGER refresh_provider_features_on_provider
    AFTER INSERT OR UPDATE OR DELETE ON provider_profiles
    FOR EACH STATEMENT
    EXECUTE FUNCTION refresh_provider_features();

DROP TRIGGER IF EXISTS refresh_provider_features_on_services ON services;
CREATE TRIGGER refresh_provider_features_on_services
    AFTER INSERT OR UPDATE OR DELETE ON services
    FOR EACH STATEMENT
    EXECUTE FUNCTION refresh_provider_features();

-- Run the spatial indexes function
SELECT create_spatial_indexes();

-- Verify the materialized view has data
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_provider_features;
