-- Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Create spatial index function
CREATE OR REPLACE FUNCTION create_spatial_indexes() RETURNS void AS $$
BEGIN
    -- Add geometry column to provider_profiles if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'provider_profiles' AND column_name = 'location_geom'
    ) THEN
        ALTER TABLE provider_profiles ADD COLUMN location_geom geography(POINT, 4326);
        
        -- Update geometry from lat/lng
        UPDATE provider_profiles 
        SET location_geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
        
        -- Create spatial index
        CREATE INDEX idx_provider_profiles_location ON provider_profiles USING GIST (location_geom);
    END IF;
    
    -- Create materialized view for provider features
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
            provider_id,
            COUNT(*) as total_services,
            AVG(seeker_rating) as avg_rating,
            COUNT(CASE WHEN status = 'completed' THEN 1 END) as total_completed_requests
        FROM services s
        LEFT JOIN service_requests sr ON s.id = sr.service_id
        GROUP BY provider_id
    ) s ON pp.id = s.provider_id
    WHERE pp.is_active = true AND pp.status = 'active';
    
    CREATE UNIQUE INDEX idx_mv_provider_features_id ON mv_provider_features (provider_id);
    CREATE INDEX idx_mv_provider_features_location ON mv_provider_features USING GIST (location_geom);
END;
$$ LANGUAGE plpgsql;

-- Create function to update materialized view
CREATE OR REPLACE FUNCTION refresh_provider_features()
RETURNS TRIGGER AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_provider_features;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Create triggers to refresh materialized view
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

-- Create geocoding helper function
CREATE OR REPLACE FUNCTION calculate_distance(
    lat1 float,
    lng1 float,
    lat2 float,
    lng2 float
) RETURNS float AS $$
BEGIN
    RETURN ST_DistanceSphere(
        ST_MakePoint(lng1, lat1),
        ST_MakePoint(lng2, lat2)
    ) / 1000; -- Convert to kilometers
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Initialize indexes
SELECT create_spatial_indexes();