-- Insert sample data for testing
INSERT INTO users (role, is_active) VALUES 
('provider', true),
('seeker', true),
('provider', true),
('seeker', true),
('provider', true);

INSERT INTO service_categories (name) VALUES 
('Plumbing'),
('Electrical'),
('Carpentry'),
('Cleaning'),
('Moving'),
('Painting'),
('HVAC');

INSERT INTO provider_profiles (user_id, category, business_name, latitude, longitude, is_approved, employee_count, certificates, status, is_active)
VALUES 
(1, 'Plumbing', 'NYC Plumbing Pros', 40.7128, -74.0060, true, 5, '[{"name": "Master Plumber License", "skills": ["pipe fitting", "leak repair", "water heater"]}]'::jsonb, 'active', true),
(3, 'Electrical', 'Spark Electric NYC', 40.7282, -73.9942, true, 3, '[{"name": "Licensed Electrician", "skills": ["wiring", "circuit breakers", "lighting"]}]'::jsonb, 'active', true),
(5, 'Carpentry', 'Wood Masters', 40.7580, -73.9855, true, 4, '[{"name": "Master Carpenter", "skills": ["furniture", "cabinetry", "woodworking"]}]'::jsonb, 'active', true);

INSERT INTO services (provider_id, category_id, title, description, is_active)
VALUES 
(1, 1, 'Emergency Plumbing', '24/7 emergency plumbing services for your home or business', true),
(1, 1, 'Pipe Installation', 'Professional pipe installation and replacement services', true),
(2, 2, 'Electrical Repair', 'Complete home electrical repair and installation services', true),
(3, 3, 'Custom Furniture', 'Handcrafted custom furniture pieces', true);