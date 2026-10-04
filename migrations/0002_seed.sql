-- Demo data for development, tests and a first look at the deployed app.
--
-- Three branches and three users, deliberately including a second chef at a
-- different branch so branch isolation can be tested for real rather than
-- assumed.
--
-- All demo accounts use the password: didi1234
-- Hashes are pbkdf2_sha256 at the cost set in api/src/security.py.
-- Rotate these before any real deployment.

INSERT INTO branches (name, location) VALUES
    ('Legon Outlet',   'Legon, Accra'),
    ('Osu Outlet',     'Osu, Accra'),
    ('Airport Outlet', 'Airport Residential, Accra');

INSERT INTO users (name, email, password_hash, role) VALUES
    ('Mr Fred',    'chef@didijollof.com',
     'pbkdf2_sha256$100000$5ANoBXogB88fAYSxeZ7ydg$vDsmRzBaIuua3hL1Z-mcgFeGOrH6-9ZR1FZBKhKG2hc',
     'chef'),
    ('Ama Serwaa', 'chef.osu@didijollof.com',
     'pbkdf2_sha256$100000$zw6sk_WyjSzla8U1KWVENA$_QtfBr-70qYZWNjLwJor-jVcRWYavIRUgaePPAAPaXs',
     'chef'),
    ('Mr Owner',   'owner@didijollof.com',
     'pbkdf2_sha256$100000$EYIOGQhq9LtnDpBcrXe3zQ$uATVTEDT2q8TJdHnVOV9uEut5I2W4P70YeM_hhEploE',
     'owner');

-- The location mapping: each chef sees one branch, the owner sees all three.
INSERT INTO user_branches (user_id, branch_id)
SELECT u.id, b.id
  FROM users u
  JOIN branches b ON b.name = 'Legon Outlet'
 WHERE u.email = 'chef@didijollof.com';

INSERT INTO user_branches (user_id, branch_id)
SELECT u.id, b.id
  FROM users u
  JOIN branches b ON b.name = 'Osu Outlet'
 WHERE u.email = 'chef.osu@didijollof.com';

INSERT INTO user_branches (user_id, branch_id)
SELECT u.id, b.id
  FROM users u
  CROSS JOIN branches b
 WHERE u.email = 'owner@didijollof.com';

-- Price is per unit, and unit is the thing the kitchen actually counts.
INSERT INTO items (name, price, category, unit) VALUES
    ('Chicken',           45.00, 'protein',   'pc'),
    ('Beef',              25.00, 'protein',   'kg'),
    ('Goat meat',         38.00, 'protein',   'kg'),
    ('Tilapia',           30.00, 'protein',   'pc'),
    ('Tomatoes',          60.00, 'produce',   'carton'),
    ('Carrot',            40.00, 'produce',   'carton'),
    ('Onions',            55.00, 'produce',   'sack'),
    ('Green pepper',      18.00, 'produce',   'kg'),
    ('Garden eggs',       22.00, 'produce',   'kg'),
    ('Curry powder',      12.00, 'spices',    'tin'),
    ('Shito pepper',      35.00, 'spices',    'jar'),
    ('Ginger',            15.00, 'spices',    'kg'),
    ('Salt',               8.00, 'spices',    'bag'),
    ('Takeaway packs',     9.00, 'packaging', 'pack'),
    ('Carrier bags',       6.00, 'packaging', 'roll'),
    ('Foil containers',   14.00, 'packaging', 'sleeve'),
    ('Serviettes',         7.00, 'packaging', 'pack');

-- Every branch stocks every item. Par levels are identical here for simplicity;
-- in production they differ per branch, which is exactly why they live on
-- branch_items rather than items.
INSERT INTO branch_items (branch_id, item_id, current_stock, min_level, par_level)
SELECT b.id,
       i.id,
       0,
       GREATEST(1, (i.id * 3) % 7),
       GREATEST(4, (i.id * 5) % 23 + 6)
  FROM branches b
  CROSS JOIN items i;

-- Legon is the demo branch, so give it counts that exercise every status the
-- UI renders: out, critical (below min), low (below par) and full.
UPDATE branch_items bi
   SET current_stock = v.stock,
       min_level = v.min_level,
       par_level = v.par_level,
       counted_at = NOW() - INTERVAL '3 hours',
       counted_by = (SELECT id FROM users WHERE email = 'chef@didijollof.com')
  FROM (VALUES
        ('Chicken',          2,  6, 24),   -- critical
        ('Beef',             1,  4, 12),   -- critical
        ('Goat meat',        5,  4, 10),   -- low
        ('Tilapia',          0,  5, 20),   -- out
        ('Tomatoes',         2,  4, 11),   -- critical
        ('Carrot',           2,  3,  8),   -- critical
        ('Onions',           6,  2,  9),   -- low
        ('Green pepper',    14,  4, 14),   -- full
        ('Garden eggs',      3,  5, 12),   -- critical
        ('Curry powder',     9,  3, 10),   -- low
        ('Shito pepper',     2,  3,  8),   -- critical
        ('Ginger',           7,  2,  7),   -- full
        ('Salt',             4,  2,  6),   -- low
        ('Takeaway packs',  12, 20, 60),   -- critical
        ('Carrier bags',     8,  5, 15),   -- low
        ('Foil containers',  0,  4, 12),   -- out
        ('Serviettes',      10,  4, 10)    -- full
       ) AS v(name, stock, min_level, par_level)
 WHERE bi.item_id = (SELECT id FROM items WHERE items.name = v.name)
   AND bi.branch_id = (SELECT id FROM branches WHERE branches.name = 'Legon Outlet');
