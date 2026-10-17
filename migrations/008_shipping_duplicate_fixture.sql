-- Add duplicate delivered observations; aggregate by order_id before joining.
INSERT INTO business.shipping_events SELECT 1000+id,id,'delivered',ordered_at+interval '3 days' FROM business.orders WHERE id%12=0 ON CONFLICT DO NOTHING;
