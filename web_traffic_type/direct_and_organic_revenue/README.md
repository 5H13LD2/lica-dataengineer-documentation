# Revenue match

Source: direct_and_organic.csv. URL-decode requestid, then Base64-decode to backend order ID. 168 of 171 unique IDs matched; 3 unmatched orders have unknown revenue and are excluded from totals. 282 ecommerce purchase events are not revenue multipliers.

Source table: gulong-chatbot-459723.gulong_backend.orders_raw, accessed through gulong_core.orders_raw_deduped. The requested gulong_backend.raw table does not exist. The view chooses the latest row per order and defines net_sales_amount as ROUND(total_amount_due / 1.12, 2). This is the existing reporting model's VAT-exclusive order value, not a cash-receipts amount.

All-order net sales include cancelled, unpaid, pending and return orders. Fulfilled net revenue uses the view's is_fulfillment_success_order flag (fulfilled/partially fulfilled and fully paid/partial payment) and excludes test orders. Partial payments use full order value; actual cash collected is unavailable in this extract. Campaigns come from the supplied CSV. Order dates are backend dates and may differ from analytics dates. Latest raw ingestion: 2026-09-25 02:00:22.

Files: decoded_orders_with_revenue.csv (row-level match), revenue_by_campaign.csv, revenue_by_status.csv, summary.json, backend_orders.json (query result), match_orders.sql, build_report.py.
