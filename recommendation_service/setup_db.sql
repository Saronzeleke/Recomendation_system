-- Create tables if they don't exist
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    role VARCHAR(50),
    is_active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS service_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE,
    parent_id INTEGER REFERENCES service_categories(id),
    hierarchy TEXT
);

CREATE TABLE IF NOT EXISTS provider_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    category VARCHAR(255),
    business_name VARCHAR(255),
    location TEXT,
    latitude FLOAT,
    longitude FLOAT,
    status VARCHAR(50) DEFAULT 'active',
    is_approved BOOLEAN DEFAULT false,
    certificates JSONB,
    employee_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    provider_id INTEGER REFERENCES provider_profiles(id),
    category_id INTEGER REFERENCES service_categories(id),
    title VARCHAR(255),
    description TEXT,
    is_active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS service_requests (
    id SERIAL PRIMARY KEY,
    seeker_id INTEGER REFERENCES users(id),
    provider_id INTEGER REFERENCES provider_profiles(id),
    service_id INTEGER REFERENCES services(id),
    status VARCHAR(50),
    seeker_rating FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES provider_profiles(id),
    skills TEXT[],
    is_active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id SERIAL PRIMARY KEY,
    type VARCHAR(50),
    user_id INTEGER REFERENCES users(id),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    sender_id INTEGER REFERENCES users(id),
    receiver_id INTEGER REFERENCES provider_profiles(id),
    content TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Add PostGIS geometry column
ALTER TABLE provider_profiles ADD COLUMN IF NOT EXISTS location_geom geography(POINT, 4326);

-- Insert sample data
INSERT INTO users (role, is_active) VALUES 
('provider', true),
('provider', true),
('seeker', true)
ON CONFLICT DO NOTHING;

INSERT INTO service_categories (name) VALUES 
('Plumbing'),
('Electrical'),
('Carpentry'),
('Cleaning'),
('Moving')
ON CONFLICT (name) DO NOTHING;

-- Get category IDs
DO \$\$
DECLARE
    plumbing_id INTEGER;
    electrical_id INTEGER;
    carpentry_id INTEGER;
    cleaning_id INTEGER;
BEGIN
    SELECT id INTO plumbing_id FROM service_categories WHERE name = 'Plumbing';
    SELECT id INTO electrical_id FROM service_categories WHERE name = 'Electrical';
    SELECT id INTO carpentry_id FROM service_categories WHERE name = 'Carpentry';
    SELECT id INTO cleaning_id FROM service_categories WHERE name = 'Cleaning';
    
    -- Insert providers
    INSERT INTO provider_profiles (user_id, category, business_name, latitude, longitude, is_approved, employee_count, status, is_active)
    VALUES 
    (1, 'Plumbing', 'NYC Plumbing Pros', 40.7128, -74.0060, true, 5, 'active', true),
    (2, 'Electrical', 'Spark Electric NYC', 40.7282, -73.9942, true, 3, 'active', true),
    (1, 'Carpentry', 'Wood Masters NYC', 40.7580, -73.9855, true, 4, 'active', true),
    (2, 'Cleaning', 'Clean Sweep NYC', 40.7614, -73.9776, true, 6, 'active', true)
    ON CONFLICT DO NOTHING;
    
    -- Insert services
    INSERT INTO services (provider_id, category_id, title, description, is_active)
    VALUES 
    (1, plumbing_id, 'Emergency Plumbing', '24/7 emergency plumbing services', true),
    (1, plumbing_id, 'Pipe Installation', 'Professional pipe installation', true),
    (2, electrical_id, 'Electrical Repair', 'Home electrical repair services', true),
    (3, carpentry_id, 'Custom Furniture', 'Handcrafted custom furniture', true),
    (4, cleaning_id, 'Deep Cleaning', 'Professional deep cleaning services', true)
    ON CONFLICT DO NOTHING;
END \$\$;

-- Update geometry for PostGIS
UPDATE provider_profiles 
SET location_geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND location_geom IS NULL;

-- Create spatial index
CREATE INDEX IF NOT EXISTS idx_provider_profiles_location ON provider_profiles USING GIST (location_geom);

-- Show counts
SELECT 'Users: ' || COUNT(*) FROM users;
SELECT 'Categories: ' || COUNT(*) FROM service_categories;
SELECT 'Providers: ' || COUNT(*) FROM provider_profiles;
SELECT 'Services: ' || COUNT(*) FROM services;
