-- Didi Jollof — initial schema.
--
-- This is the original schema.sql (kept in the repo root as the authored record)
-- extended with what the DIDI screens actually need. Every addition is marked
-- [+] with the reason, so the diff against the original reads cleanly.
--
-- Target: PostgreSQL 16 (Neon in production, Docker locally).

-- [+] chef counts and orders for one branch; an owner reviews several.
CREATE TYPE user_role AS ENUM (
    'chef',
    'owner'
);

CREATE TABLE users (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash TEXT NOT NULL,
    role user_role NOT NULL DEFAULT 'chef',             -- [+]
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),      -- [+]

    CONSTRAINT users_name_not_blank
        CHECK (btrim(name) <> ''),

    CONSTRAINT users_email_not_blank
        CHECK (btrim(email) <> '')
);

-- [+] Categories back the circular filters on the home screen.
CREATE TYPE item_category AS ENUM (
    'produce',
    'protein',
    'spices',
    'packaging',
    'other'
);

CREATE TABLE items (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    category item_category NOT NULL DEFAULT 'other',    -- [+]
    unit VARCHAR(24) NOT NULL DEFAULT 'pc',             -- [+] pc, box, carton, pack, kg
    image_url TEXT,                                     -- [+] category/item thumbnails
    is_active BOOLEAN NOT NULL DEFAULT TRUE,            -- [+] retire without deleting history

    CONSTRAINT items_name_not_blank
        CHECK (btrim(name) <> ''),

    CONSTRAINT items_price_non_negative
        CHECK (price >= 0),

    CONSTRAINT items_unit_not_blank                     -- [+]
        CHECK (btrim(unit) <> '')
);

CREATE TABLE branches (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    location TEXT NOT NULL,

    CONSTRAINT branches_name_not_blank
        CHECK (btrim(name) <> ''),

    CONSTRAINT branches_location_not_blank
        CHECK (btrim(location) <> ''),

    CONSTRAINT branches_name_unique
        UNIQUE (name)
);

-- [+] The location mapping. This table is the security boundary: every
-- branch-scoped query is gated on a row existing here for the caller.
-- A chef maps to exactly one branch; an owner maps to many.
CREATE TABLE user_branches (
    user_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (user_id, branch_id),

    CONSTRAINT user_branches_user_fk
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT user_branches_branch_fk
        FOREIGN KEY (branch_id)
        REFERENCES branches(id)
        ON DELETE CASCADE
);

-- [+] Stock levels are per branch, not per item: Legon and Osu hold different
-- amounts of the same thing and carry different par levels.
--   current_stock → the chef's count, what the UI shows as "2 boxes left"
--   min_level     → reorder point; below it the item reads critical
--   par_level     → what "full" means; the bar is current_stock / par_level
CREATE TABLE branch_items (
    branch_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    current_stock INTEGER NOT NULL DEFAULT 0,
    min_level INTEGER NOT NULL DEFAULT 0,
    par_level INTEGER NOT NULL,
    counted_at TIMESTAMPTZ,
    counted_by INTEGER,

    PRIMARY KEY (branch_id, item_id),

    CONSTRAINT branch_items_branch_fk
        FOREIGN KEY (branch_id)
        REFERENCES branches(id)
        ON DELETE CASCADE,

    CONSTRAINT branch_items_item_fk
        FOREIGN KEY (item_id)
        REFERENCES items(id)
        ON DELETE CASCADE,

    CONSTRAINT branch_items_counted_by_fk
        FOREIGN KEY (counted_by)
        REFERENCES users(id)
        ON DELETE SET NULL,

    CONSTRAINT branch_items_stock_non_negative
        CHECK (current_stock >= 0),

    CONSTRAINT branch_items_min_non_negative
        CHECK (min_level >= 0),

    CONSTRAINT branch_items_par_positive
        CHECK (par_level > 0),

    CONSTRAINT branch_items_min_within_par
        CHECK (min_level <= par_level)
);

-- 'approved' is declared up front rather than added later: ALTER TYPE ... ADD VALUE
-- cannot run in the same transaction that uses the new value.           -- [+]
CREATE TYPE order_status AS ENUM (
    'active',       -- submitted by the chef, awaiting the owner (UI: "pending")
    'approved',     -- [+] owner approved, not yet purchased
    'completed',    -- purchased and received
    'rejected'
);

CREATE TABLE orders (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status order_status NOT NULL DEFAULT 'active',
    deleted_at TIMESTAMPTZ,
    reviewed_by INTEGER,                                -- [+] which owner acted
    reviewed_at TIMESTAMPTZ,                            -- [+]
    review_note TEXT,                                   -- [+] rejection reason

    CONSTRAINT orders_user_fk
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT,

    CONSTRAINT orders_branch_fk
        FOREIGN KEY (branch_id)
        REFERENCES branches(id)
        ON DELETE RESTRICT,

    CONSTRAINT orders_reviewed_by_fk                    -- [+]
        FOREIGN KEY (reviewed_by)
        REFERENCES users(id)
        ON DELETE SET NULL,

    -- [+] A reviewed order must say who and when; an unreviewed one must not.
    CONSTRAINT orders_review_consistent
        CHECK (
            (status IN ('active') AND reviewed_by IS NULL AND reviewed_at IS NULL)
            OR (status IN ('approved', 'completed', 'rejected'))
        )
);

CREATE TABLE order_items (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    existing_stock INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,                 -- [+] see note below

    CONSTRAINT order_items_order_fk
        FOREIGN KEY (order_id)
        REFERENCES orders(id)
        ON DELETE CASCADE,

    CONSTRAINT order_items_item_fk
        FOREIGN KEY (item_id)
        REFERENCES items(id)
        ON DELETE RESTRICT,

    CONSTRAINT order_items_quantity_positive
        CHECK (quantity > 0),

    CONSTRAINT order_items_stock_non_negative
        CHECK (existing_stock >= 0),

    CONSTRAINT order_items_unit_price_non_negative      -- [+]
        CHECK (unit_price >= 0),

    CONSTRAINT order_items_unique_item
        UNIQUE (order_id, item_id)
);

-- [+] unit_price is a snapshot of items.price at the moment the request was
-- submitted. Without it, a supplier price change would silently rewrite what
-- every past request cost, and the history screen's totals would drift.
COMMENT ON COLUMN order_items.unit_price IS
    'Price per unit at submission time. Immutable snapshot; never read live from items.price.';

CREATE UNIQUE INDEX users_email_lower_idx
    ON users (LOWER(email));

CREATE INDEX orders_user_id_idx
    ON orders (user_id);

CREATE INDEX orders_branch_id_idx
    ON orders (branch_id);

CREATE INDEX orders_created_at_idx
    ON orders (created_at DESC);

CREATE INDEX order_items_item_id_idx
    ON order_items (item_id);

-- [+] The history screen lists a branch's requests newest-first, filtered by
-- status, and always excludes soft-deleted rows.
CREATE INDEX orders_branch_created_idx
    ON orders (branch_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- [+] The inventory screen pulls every item for one branch.
CREATE INDEX branch_items_branch_idx
    ON branch_items (branch_id);
