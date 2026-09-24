SELECT order_id, order_date, date_updated, order_status_raw, payment_status_raw,
 gross_sales_amount, net_sales_amount, is_excluded_test_order, is_non_cancelled_order,
 is_fulfilled_order, is_fulfillment_success_order, quantity_int, sku, brand,
 customer_source_raw, _ingest_loaded_at
FROM `gulong-chatbot-459723.gulong_core.orders_raw_deduped`
WHERE order_id_int IN (39773,39143,39395,39497,39507,39542,39568,39570,39581,39583,39586,39603,39608,39623,39665,39677,39691,39692,39705,39736,39738,39816,39835,39862,39870,39877,39878,39895,39898,39017,39032,39034,39035,39065,38959,39158,39164,39166,39169,39193,39204,39260,39265,39301,39372,38981,38969,38985,39468,39471,39589,39594,39601,39602,39656,39813,39023,39121,39132,39133,39146,39171,39172,39213,39219,39368,39396,39397)
ORDER BY order_id