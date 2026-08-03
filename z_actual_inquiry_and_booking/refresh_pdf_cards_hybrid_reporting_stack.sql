#standardSQL

-- Daily refresh bundle for the hybrid PDF-cards + live continuation reporting stack.
--
-- Run order:
-- 1. rebuild the live continuation tables
-- 2. redeploy the live Looker views
-- 3. ensure the hybrid view is still present
--
-- Intended schedule:
-- - daily, after upstream `gulong_core` loads are complete
-- - timezone: Asia/Manila

-- 1) Live continuation tables
--    Source file: build_medallion_inquiry_booking_tables.sql
CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_detail`
PARTITION BY report_date
CLUSTER BY reporting_lane, inquiry_key
AS
SELECT * FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_detail`;

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_daily`
PARTITION BY report_date
CLUSTER BY reporting_lane
AS
SELECT * FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_daily`;

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_monthly`
AS
SELECT * FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_monthly`;

-- 2) Fixed live Looker views
CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_actual_inquiry_booking_conversion_daily`
OPTIONS (
  description = "Looker-facing daily actual inquiry booking conversion summary by reporting lane. Source of truth is t_actual_inquiry_booking_conversion_daily."
) AS
SELECT
  report_date,
  report_week,
  report_month,
  reporting_lane AS agent_name,
  actual_inquiries,
  validated_moderate_inquiries,
  moderate_rate,
  traceable_qualifying_bookings AS booking_count,
  distinct_converted_inquiries,
  booking_per_inquiry_rate AS conversion_rate,
  unique_inquiry_conversion_rate,
  booking_per_moderate_rate,
  qualifying_tire_quantity,
  qualifying_gross_sales_amount AS booking_revenue,
  qualifying_net_sales_amount,
  qualifying_total_cost_amount,
  qualifying_gross_profit_amount,
  loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_daily`;

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_actual_inquiry_booking_conversion_monthly`
OPTIONS (
  description = "Looker-facing monthly actual inquiry booking conversion summary by reporting lane. Source of truth is t_actual_inquiry_booking_conversion_monthly."
) AS
SELECT
  report_month,
  reporting_lane AS agent_name,
  actual_inquiries,
  validated_moderate_inquiries,
  moderate_rate,
  traceable_qualifying_bookings AS booking_count,
  distinct_converted_inquiries,
  booking_per_inquiry_rate AS conversion_rate,
  unique_inquiry_conversion_rate,
  booking_per_moderate_rate,
  qualifying_tire_quantity,
  qualifying_gross_sales_amount AS booking_revenue,
  qualifying_net_sales_amount,
  qualifying_total_cost_amount,
  qualifying_gross_profit_amount,
  loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_monthly`;

-- 3) Hybrid view stays on top of:
--    - v_looker_pdf_cards_agent_daily_2026_07_29
--    - t_actual_inquiry_booking_conversion_daily
SELECT 'refresh bundle definition updated' AS status;
