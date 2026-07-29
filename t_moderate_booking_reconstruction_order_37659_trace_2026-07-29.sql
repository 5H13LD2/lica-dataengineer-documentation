-- Trace for order_id = 37659
-- Date: 2026-07-29
--
-- Purpose:
-- 1. Confirm official booking existence
-- 2. Confirm matching replied session in v_looker_first_reply_detail
-- 3. Replay reconstruction match logic directly
-- 4. Compare downstream reporting tables


-- =====================================================================
-- A. Current downstream counts for 2026-07-28
-- =====================================================================

SELECT
  report_date,
  agent_name,
  total_bookings,
  total_moderate_sessions
FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
WHERE report_date BETWEEN DATE '2026-07-27' AND DATE '2026-07-29'
  AND agent_name = 'Chatbot/JCo'
ORDER BY report_date;

SELECT
  booking_day,
  COUNT(*) AS booked_rows,
  COUNT(DISTINCT order_id) AS distinct_orders,
  COUNTIF(booked_order_count = 1) AS booked_order_rows,
  COUNTIF(booking_owner_bucket = 'CS Assisted') AS cs_assisted_rows,
  COUNTIF(booking_owner_bucket = 'Chatbot Only') AS chatbot_only_rows
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE booking_day = DATE '2026-07-28'
GROUP BY 1;

SELECT
  COUNT(*) AS orders_booked_count,
  COUNT(DISTINCT order_id) AS distinct_orders
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE booking_day = DATE '2026-07-28'
  AND sales_reporting_agent_name = 'Chatbot/JCo'
  AND is_reportable_booked_order = TRUE;


-- =====================================================================
-- B. Raw official booking rows
-- =====================================================================

SELECT
  order_id,
  booking_day,
  booking_at,
  manychat_user_id AS manychat_id,
  customer_name,
  inquiry_silver_session_id,
  sales_reporting_agent_name,
  is_reportable_booked_order
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE booking_day = DATE '2026-07-28'
  AND sales_reporting_agent_name = 'Chatbot/JCo'
  AND is_reportable_booked_order = TRUE
ORDER BY booking_at, order_id;

SELECT
  order_id,
  booking_day,
  booking_at,
  manychat_user_id AS manychat_id,
  inquiry_silver_session_id,
  customer_name
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE order_id = '37659';


-- =====================================================================
-- C. v_looker_first_reply_detail candidate rows
-- =====================================================================

SELECT
  report_date,
  silver_session_id,
  manychat_id,
  user_name,
  reply_status,
  reply_agent_name,
  first_customer_message_at,
  first_cs_reply_at,
  minutes_to_first_reply
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
WHERE silver_session_id = '31698e21bbffe3bc05784586c258d032'
   OR manychat_id = '2845998122184220'
ORDER BY report_date DESC, first_customer_message_at DESC;


-- =====================================================================
-- D. Replay deployed reconstruction match logic for 37659
-- =====================================================================

WITH moderates AS (
  SELECT
    report_date AS moderate_report_date,
    silver_session_id,
    manychat_id,
    user_name,
    reply_status,
    first_customer_message_at,
    first_cs_reply_at
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE manychat_id IS NOT NULL
),
official_booking AS (
  SELECT
    order_id,
    booking_at,
    booking_day,
    manychat_user_id AS manychat_id,
    customer_name,
    inquiry_silver_session_id
  FROM `gulong-chatbot-459723.gulong_core.orders_booked`
  WHERE order_id = '37659'
)
SELECT
  b.order_id,
  b.booking_day,
  b.booking_at,
  b.inquiry_silver_session_id,
  m.moderate_report_date,
  m.silver_session_id,
  m.user_name,
  m.reply_status,
  m.first_customer_message_at,
  m.first_cs_reply_at,
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
FROM official_booking b
JOIN moderates m
  ON m.manychat_id = b.manychat_id
 AND (
   b.inquiry_silver_session_id = m.silver_session_id
   OR m.first_customer_message_at <= b.booking_at
 )
ORDER BY booking_match_rn;


-- =====================================================================
-- E. Current physical reconstruction rows
-- =====================================================================

SELECT
  order_id,
  booking_day,
  moderate_report_date,
  silver_session_id,
  booking_match_rule,
  booking_owner_bucket,
  reply_status
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE booking_day = DATE '2026-07-28'
ORDER BY order_id;

SELECT
  order_id,
  booking_day,
  moderate_report_date,
  silver_session_id,
  booking_match_rule,
  booking_owner_bucket,
  reply_status
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE order_id = '37659'
LIMIT 1;


-- =====================================================================
-- F. Raw ManyChat conversation trace for the matched session
-- =====================================================================

SELECT
  datetime,
  role,
  sender,
  type,
  text_content
FROM `gulong-chatbot-459723.manychat_data.messages`
WHERE user_id = '2845998122184220'
  AND datetime >= DATETIME '2026-07-27 00:00:00'
  AND datetime < DATETIME '2026-07-29 00:00:00'
ORDER BY datetime
LIMIT 100;
