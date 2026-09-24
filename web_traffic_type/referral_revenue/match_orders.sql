SELECT order_id, order_date, date_updated, order_status_raw, payment_status_raw,
 gross_sales_amount, net_sales_amount, is_excluded_test_order, is_non_cancelled_order,
 is_fulfilled_order, is_fulfillment_success_order, quantity_int, sku, brand,
 customer_source_raw, _ingest_loaded_at
FROM `gulong-chatbot-459723.gulong_core.orders_raw_deduped`
WHERE order_id_int IN (39006,39011,39075,39101,39125,39248,39280,39293,39314,39325,39341,39364,39369,39392,39448,39460,39485,39490,39528,39551,39655,39684,39686,39723,39751,39758,39795,39840)
ORDER BY order_id