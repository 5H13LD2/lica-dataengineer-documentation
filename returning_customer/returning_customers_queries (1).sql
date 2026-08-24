-- ============================================================
-- Returning Customers - August 2026 (Aug 1-19, partial)
-- BigQuery queries used. Project: gulong-chatbot-459723
-- Source: gulong_core.orders_booked (canonical reportable-booked view)
-- Note: walang email/contact sa BigQuery mirror; galing sila sa raw
--       Redash temp_orders CSV. Dito, BQ ang nagbibigay ng exact
--       "valid order" scope (order IDs); ang email/contact join ay
--       ginagawa sa Python gamit ang CSV.
-- ============================================================


-- ------------------------------------------------------------
-- 0) (Optional) Kumpirmahin na walang contact/email sa order data.
--    Ang identity fields lang: customer_name, customer_name_key, many_chat_id
-- ------------------------------------------------------------
SELECT column_name, data_type
FROM `gulong-chatbot-459723.gulong_core.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'orders_raw_deduped'
ORDER BY ordinal_position;


-- ------------------------------------------------------------
-- 1) NAME-BASED returning (reference number = 18).
--    "Returning" = name_key na may booked order sa August AT may
--    booked order bago mag-Aug 1 (kahit kailan back to 2024).
--    Ito ang na-validate na tumugma sa Python name-approx.
-- ------------------------------------------------------------
WITH booked AS (
  SELECT order_id, order_day, customer_name_key, net_sales_amount
  FROM `gulong-chatbot-459723.gulong_core.orders_booked`
  WHERE customer_name_key IS NOT NULL AND TRIM(customer_name_key) != ''
),
prior_customers AS (
  SELECT DISTINCT customer_name_key
  FROM booked
  WHERE order_day < DATE '2026-08-01'
),
aug_orders AS (
  SELECT * FROM booked
  WHERE order_day >= DATE '2026-08-01' AND order_day < DATE '2026-09-01'
),
aug_classified AS (
  SELECT a.*, (p.customer_name_key IS NOT NULL) AS is_returning
  FROM aug_orders a
  LEFT JOIN prior_customers p USING (customer_name_key)
),
customer_level AS (
  SELECT customer_name_key, MAX(is_returning) AS is_returning
  FROM aug_classified
  GROUP BY customer_name_key
)
SELECT
  (SELECT COUNT(*)            FROM customer_level) AS total_aug_customers,
  (SELECT COUNTIF(is_returning) FROM customer_level) AS returning_customers,
  (SELECT COUNTIF(NOT is_returning) FROM customer_level) AS new_customers,
  ROUND(100*(SELECT COUNTIF(is_returning) FROM customer_level)
           /(SELECT COUNT(*) FROM customer_level),2) AS returning_rate_pct,
  ROUND((SELECT SUM(net_sales_amount) FROM aug_classified WHERE is_returning),2)     AS returning_net_sales,
  ROUND((SELECT SUM(net_sales_amount) FROM aug_classified WHERE NOT is_returning),2) AS new_net_sales,
  ROUND((SELECT SAFE_DIVIDE(SUM(net_sales_amount),COUNT(*)) FROM aug_classified WHERE is_returning),2)     AS returning_aov,
  ROUND((SELECT SAFE_DIVIDE(SUM(net_sales_amount),COUNT(*)) FROM aug_classified WHERE NOT is_returning),2) AS new_aov;


-- ------------------------------------------------------------
-- 2) Kunin ang PRIOR (pre-August) booked order IDs -> isang string.
--    Isasave sa file (prior_booked_ids.txt) para i-join sa CSV sa Python.
--    Ito ang nagbibigay ng exact canonical scope kahit name/email/contact
--    ang gamiting identifier.
-- ------------------------------------------------------------
SELECT
  COUNT(*)                    AS prior_booked_ct,
  STRING_AGG(order_id, ',')   AS prior_booked_ids
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE order_day < DATE '2026-08-01';


-- ------------------------------------------------------------
-- 3) Kunin ang AUGUST booked orders (302) + net sales -> isang string
--    na "order_id~net_sales|..." (isasave sa aug_booked.txt).
-- ------------------------------------------------------------
SELECT
  COUNT(*) AS aug_ct,
  STRING_AGG(FORMAT('%s~%.2f', order_id, net_sales_amount), '|') AS aug_rows
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE order_day >= DATE '2026-08-01' AND order_day < DATE '2026-09-01';
