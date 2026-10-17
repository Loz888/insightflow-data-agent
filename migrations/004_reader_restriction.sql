REVOKE ALL ON ALL TABLES IN SCHEMA business FROM insightflow_reader;
GRANT SELECT ON business.customers,business.products,business.orders,business.order_items,business.refunds TO insightflow_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA business REVOKE SELECT ON TABLES FROM insightflow_reader;
