CREATE INDEX IF NOT EXISTS orders_date_status_idx ON business.orders(ordered_at,status);
CREATE INDEX IF NOT EXISTS orders_customer_idx ON business.orders(customer_id);
CREATE INDEX IF NOT EXISTS items_order_idx ON business.order_items(order_id);
CREATE INDEX IF NOT EXISTS items_product_idx ON business.order_items(product_id);
CREATE INDEX IF NOT EXISTS refunds_order_status_idx ON business.refunds(order_id,status);
CREATE INDEX IF NOT EXISTS customers_region_idx ON business.customers(region);
