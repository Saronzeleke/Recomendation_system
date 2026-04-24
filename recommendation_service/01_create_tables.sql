-- Create tables first
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    role VARCHAR(50),
    is_active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS service_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    parent_id INTEGER REFERENCES service_categories(id),
    hierarchy TEXT
);

CREATE TABLE IF NOT EXISTS provider_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    category VARCHAR(255),
    location TEXT,
    latitude FLOAT,
    longitude FLOAT,
    status VARCHAR(50) DEFAULT 'active',
    is_approved BOOLEAN DEFAULT false,
    certificates JSONB,
    employee_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    business_name VARCHAR(255)
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