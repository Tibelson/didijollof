CREATE TABLE users (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash TEXT NOT NULL,

    CONSTRAINT users_name_not_blank
        CHECK (btrim(name) <> ''),

    CONSTRAINT users_email_not_blank
        CHECK (btrim(email) <> '')
);

CREATE TABLE items (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,

    CONSTRAINT items_name_not_blank
        CHECK (btrim(name) <> ''),

    CONSTRAINT items_price_non_negative
        CHECK (price >= 0)
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

CREATE TYPE order_status AS ENUM (
    'active',
    'completed',
    'rejected'
);

CREATE TABLE orders (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status order_status NOT NULL DEFAULT 'active',
    deleted_at TIMESTAMPTZ,

    CONSTRAINT orders_user_fk
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE RESTRICT,

    CONSTRAINT orders_branch_fk
        FOREIGN KEY (branch_id)
        REFERENCES branches(id)
        ON DELETE RESTRICT
);

CREATE TABLE order_items (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    existing_stock INTEGER NOT NULL,

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

    CONSTRAINT order_items_unique_item
        UNIQUE (order_id, item_id)
);

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


