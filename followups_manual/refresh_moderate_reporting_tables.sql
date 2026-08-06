-- =====================================================================
-- GULONG.PH — MODERATE REPORTING PHYSICAL TABLE REFRESH
-- Project: gulong-chatbot-459723
-- Dataset: gulong_reporting
--
-- Purpose:
--   Refresh the physical reporting tables that can go stale after the
--   upstream views advance.
--
-- When to run:
--   - after changes to `v_looker_first_reply_detail`
--   - after changes to follow-up matching logic
--   - when Looker Studio is pointed at the `t_` tables and new rows are
--     missing from the dashboard
--
-- Rolling-window behavior:
--   This script keeps historical rows outside the refresh window and only
--   rebuilds the recent slice from the live views, using the current
--   Manila date as the moving anchor.
--
--   Adjust `refresh_window_days` if you want a wider or narrower window.
--
-- Safe order:
--   1. t_moderate_followup_detail
--   2. t_moderate_followup_coverage
--   3. t_moderate_booking_reconstruction
-- =====================================================================

DECLARE refresh_window_days INT64 DEFAULT 30;
DECLARE refresh_start_date DATE DEFAULT DATE_SUB(
  CURRENT_DATE('Asia/Manila'),
  INTERVAL refresh_window_days DAY
);

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
CLUSTER BY followup_date AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
WHERE followup_date < refresh_start_date

UNION ALL

SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_detail`
WHERE followup_date >= refresh_start_date;


CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
CLUSTER BY moderate_report_date AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE moderate_report_date < refresh_start_date

UNION ALL

SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`
WHERE moderate_report_date >= refresh_start_date;


CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day AS
WITH historical_rows AS (
  SELECT *
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
  WHERE booking_day < refresh_start_date
),
moderates AS (
  SELECT
    report_date AS moderate_report_date,
    DATE_TRUNC(report_date, WEEK(MONDAY)) AS moderate_week,
    DATE_TRUNC(report_date, MONTH) AS moderate_month,
    silver_session_id,
    manychat_id,
    user_name,
    contact_number,
    reply_status,
    reply_agent_name,
    LOWER(TRIM(reply_agent_name)) AS reply_agent_name_norm,
    first_customer_message_at,
    next_customer_message_at,
    first_cs_reply_at,
    minutes_to_first_reply
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE manychat_id IS NOT NULL
),
recent_official_bookings AS (
  SELECT
    order_id,
    booking_at,
    booking_day,
    manychat_user_id AS manychat_id,
    customer_name AS booking_customer_name,
    sales_reporting_agent_name,
    inquiry_silver_session_id,
    inquiry_day,
    order_status_norm
  FROM `gulong-chatbot-459723.gulong_core.orders_booked`
  WHERE sales_reporting_agent_name = 'Chatbot/JCo'
    AND is_reportable_booked_order = TRUE
    AND manychat_user_id IS NOT NULL
    AND booking_day >= refresh_start_date
),
followup_booking_flags AS (
  SELECT
    attributed_order_id AS order_id,
    MIN(followup_date) AS first_followup_date,
    MIN(followup_at) AS first_followup_at
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
  WHERE attributed_order_id IS NOT NULL
  GROUP BY 1
),
matched_orders AS (
  SELECT
    b.order_id,
    b.booking_at,
    b.booking_day,
    b.manychat_id,
    b.booking_customer_name,
    b.sales_reporting_agent_name,
    b.inquiry_silver_session_id,
    b.inquiry_day,
    b.order_status_norm,
    m.moderate_report_date,
    m.moderate_week,
    m.moderate_month,
    m.silver_session_id,
    m.user_name,
    m.contact_number,
    m.reply_status,
    m.reply_agent_name,
    m.reply_agent_name_norm,
    m.first_customer_message_at,
    m.next_customer_message_at,
    m.first_cs_reply_at,
    m.minutes_to_first_reply,
    CASE
      WHEN b.inquiry_silver_session_id = m.silver_session_id THEN 'EXACT INQUIRY SESSION'
      ELSE 'LATEST PRIOR MODERATE'
    END AS booking_match_rule,
    ROW_NUMBER() OVER (
      PARTITION BY b.order_id
      ORDER BY
        CASE WHEN b.inquiry_silver_session_id = m.silver_session_id THEN 0 ELSE 1 END,
        m.first_customer_message_at DESC,
        m.moderate_report_date DESC,
        m.silver_session_id DESC
    ) AS booking_match_rn
  FROM recent_official_bookings b
  JOIN moderates m
    ON m.manychat_id = b.manychat_id
   AND (
     b.inquiry_silver_session_id = m.silver_session_id
     OR m.first_customer_message_at <= b.booking_at
   )
),
recent_rows AS (
  SELECT
    mo.booking_day,
    DATE_TRUNC(mo.booking_day, WEEK(MONDAY)) AS booking_week,
    DATE_TRUNC(mo.booking_day, MONTH) AS booking_month,
    mo.order_id,
    mo.booking_at,
    mo.manychat_id,
    mo.booking_customer_name,
    mo.sales_reporting_agent_name,
    mo.order_status_norm,
    mo.inquiry_silver_session_id,
    mo.inquiry_day,
    mo.moderate_report_date,
    mo.moderate_week,
    mo.moderate_month,
    mo.silver_session_id,
    mo.user_name,
    mo.contact_number,
    mo.reply_status,
    mo.reply_agent_name,
    mo.reply_agent_name_norm,
    mo.first_customer_message_at,
    mo.next_customer_message_at,
    mo.first_cs_reply_at,
    mo.minutes_to_first_reply,
    mo.booking_match_rule,
    fb.first_followup_date,
    fb.first_followup_at,
    CASE
      WHEN fb.order_id IS NOT NULL THEN 'CS Assisted'
      ELSE 'Chatbot Only'
    END AS booking_owner_bucket,
    CASE
      WHEN fb.order_id IS NOT NULL THEN 'CS-ASSISTED BOOKING'
      ELSE 'CHATBOT-ONLY BOOKING'
    END AS booking_ownership_status,
    DATETIME_DIFF(mo.booking_at, mo.first_customer_message_at, MINUTE) AS minutes_from_first_customer_to_booking,
    DATE_DIFF(mo.booking_day, mo.moderate_report_date, DAY) AS days_from_moderate_to_booking,
    CAST(fb.order_id IS NOT NULL AS INT64) AS cs_assisted_booking_count,
    CAST(fb.order_id IS NULL AS INT64) AS chatbot_only_booking_count,
    CAST(0 AS INT64) AS unmatched_official_booking_count,
    CAST(1 AS INT64) AS booked_order_count
  FROM matched_orders mo
  LEFT JOIN followup_booking_flags fb
    USING (order_id)
  WHERE mo.booking_match_rn = 1
)
SELECT *
FROM historical_rows

UNION ALL

SELECT *
FROM recent_rows;


-- Optional QA
SELECT
  't_moderate_followup_detail' AS table_name,
  CAST(refresh_start_date AS STRING) AS refresh_start_date,
  MAX(followup_date) AS max_date,
  COUNT(*) AS row_count
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`

UNION ALL

SELECT
  't_moderate_followup_coverage' AS table_name,
  CAST(refresh_start_date AS STRING) AS refresh_start_date,
  MAX(moderate_report_date) AS max_date,
  COUNT(*) AS row_count
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`

UNION ALL

SELECT
  't_moderate_booking_reconstruction' AS table_name,
  CAST(refresh_start_date AS STRING) AS refresh_start_date,
  MAX(booking_day) AS max_date,
  COUNT(*) AS row_count
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`;
