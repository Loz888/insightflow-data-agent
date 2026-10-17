CREATE SCHEMA IF NOT EXISTS business;
CREATE TABLE IF NOT EXISTS business.customers (
 id integer PRIMARY KEY, name text NOT NULL, region text NOT NULL
 CHECK (region IN ('华东','华南','华北','西部')), created_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS business.products (
 id integer PRIMARY KEY, name text NOT NULL, category text NOT NULL,
 price numeric(12,2) NOT NULL CHECK(price>0));
CREATE TABLE IF NOT EXISTS business.orders (
 id integer PRIMARY KEY, customer_id integer NOT NULL REFERENCES business.customers(id),
 ordered_at timestamptz NOT NULL, status text NOT NULL CHECK(status IN ('paid','pending','cancelled')));
CREATE TABLE IF NOT EXISTS business.order_items (
 id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES business.orders(id),
 product_id integer NOT NULL REFERENCES business.products(id),
 quantity integer NOT NULL CHECK(quantity>0),
 unit_price numeric(12,2) NOT NULL CHECK(unit_price>0));
CREATE TABLE IF NOT EXISTS business.refunds (
 id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES business.orders(id),
 refund_amount numeric(12,2) NOT NULL CHECK(refund_amount>0),
 refunded_at timestamptz NOT NULL, status text NOT NULL CHECK(status IN ('succeeded','pending','failed')));
