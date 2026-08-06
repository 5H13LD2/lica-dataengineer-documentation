-- Latest operational SQL for `t_moderate_booking_reconstruction`.
-- Use these statements in order:
-- 1. Rebuild the physical table from the live reconstruction view.
-- 2. Backfill `first_cs_reply_at`, `reply_status`, and `reply_agent_name`
--    from raw ManyChat agent messages for rows that still have null reply fields.

DECLARE rebuild_start_date DATE DEFAULT DATE '2025-01-01';

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day AS
WITH moderates AS (
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
official_bookings AS (
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
    AND booking_day >= rebuild_start_date
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
  FROM official_bookings b
  JOIN moderates m
    ON m.manychat_id = b.manychat_id
   AND (
     b.inquiry_silver_session_id = m.silver_session_id
     OR m.first_customer_message_at <= b.booking_at
   )
)
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
WHERE mo.booking_match_rn = 1;

UPDATE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction` AS t
SET
  first_cs_reply_at = c.backfilled_first_cs_reply_at,
  reply_status = 'Has CS Reply',
  reply_agent_name = c.backfilled_reply_agent_name,
  reply_agent_name_norm = LOWER(TRIM(c.backfilled_reply_agent_name)),
  minutes_to_first_reply = DATETIME_DIFF(c.backfilled_first_cs_reply_at, t.first_customer_message_at, MINUTE)
FROM (
  SELECT
    order_id,
    candidate_first_cs_reply_at AS backfilled_first_cs_reply_at,
    candidate_reply_agent_name AS backfilled_reply_agent_name
  FROM (
    SELECT
      t.order_id,
      m.datetime AS candidate_first_cs_reply_at,
      m.sender AS candidate_reply_agent_name,
      ROW_NUMBER() OVER (
        PARTITION BY t.order_id
        ORDER BY
          CASE WHEN m.datetime <= t.booking_at THEN 0 ELSE 1 END,
          m.datetime,
          m.message_id
      ) AS rn
    FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction` t
    JOIN `gulong-chatbot-459723.manychat_data.messages` m
      ON m.datetime >= DATETIME '2025-01-01 00:00:00'
     AND m.datetime < DATETIME '2030-01-01 00:00:00'
     AND m.user_id = t.manychat_id
     AND m.business_unit = 'gulong'
     AND m.role = 'agent'
     AND m.type = 'msgout_lc'
     AND m.datetime >= t.first_customer_message_at
    WHERE t.first_cs_reply_at IS NULL
      AND t.manychat_id IS NOT NULL
      AND t.first_customer_message_at IS NOT NULL
  )
  WHERE rn = 1
) AS c
WHERE t.order_id = c.order_id;
