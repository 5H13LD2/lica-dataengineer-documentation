#standardSQL
CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_booking_detail` AS
WITH replied_moderates AS (
  SELECT
    report_date AS moderate_report_date,
    report_week AS moderate_report_week,
    report_month AS moderate_report_month,
    silver_session_id,
    manychat_id,
    user_name,
    contact_number,
    first_customer_message_at,
    first_moderate_at,
    moderate_tagged_at,
    first_cs_reply_at,
    first_cs_reply_sender,
    reply_agent_name
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE reply_status = 'Has CS Reply'
    AND manychat_id IS NOT NULL
),
followups AS (
  SELECT
    report_date AS followup_date,
    report_week AS followup_week,
    report_month AS followup_month,
    manychat_id,
    user_name AS followup_user_name,
    agent_name AS followup_agent_name,
    followup_at,
    followup_type,
    followup_text
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail`
),
matched_followups AS (
  SELECT * EXCEPT(match_rank)
  FROM (
    SELECT
      m.moderate_report_date,
      m.moderate_report_week,
      m.moderate_report_month,
      f.followup_date,
      f.followup_week,
      f.followup_month,
      m.silver_session_id,
      m.manychat_id,
      m.user_name,
      m.contact_number,
      m.first_customer_message_at,
      m.first_moderate_at,
      m.moderate_tagged_at,
      m.first_cs_reply_at,
      m.first_cs_reply_sender,
      m.reply_agent_name,
      f.followup_user_name,
      f.followup_agent_name,
      f.followup_at,
      f.followup_type,
      f.followup_text,
      DATE_DIFF(f.followup_date, m.moderate_report_date, DAY) AS days_from_moderate_to_followup,
      DATE_DIFF(f.followup_date, DATE(m.first_cs_reply_at), DAY) AS days_from_reply_to_followup,
      ROW_NUMBER() OVER (
        PARTITION BY f.manychat_id, f.followup_at
        ORDER BY m.first_cs_reply_at DESC, m.silver_session_id DESC
      ) AS match_rank
    FROM replied_moderates m
    JOIN followups f
      ON f.manychat_id = m.manychat_id
     AND f.followup_at >= m.first_cs_reply_at
     AND f.followup_date <= DATE_ADD(m.moderate_report_date, INTERVAL 7 DAY)
  )
  WHERE match_rank = 1
),
booking_candidates AS (
  SELECT
    mf.silver_session_id,
    mf.followup_at,
    b.order_id,
    b.booking_at,
    b.booking_day,
    b.customer_name AS booking_customer_name,
    b.net_sales_amount,
    b.gross_sales_amount,
    b.total_cost_amount,
    b.gross_profit_amount,
    b.quantity_int,
    b.canonical_order_brand,
    b.canonical_order_tire_size,
    b.installation_partner_name,
    b.appointment_at,
    b.appointment_day,
    b.booked_inclusion_reason,
    ROW_NUMBER() OVER (
      PARTITION BY mf.silver_session_id, mf.followup_at
      ORDER BY b.booking_at ASC, b.order_id ASC
    ) AS booking_rank,
    COUNT(b.order_id) OVER (
      PARTITION BY mf.silver_session_id, mf.followup_at
    ) AS booking_count_within_14d
  FROM matched_followups mf
  LEFT JOIN `gulong-chatbot-459723.gulong_core.orders_booked` b
    ON b.manychat_user_id = mf.manychat_id
   AND b.booking_at >= mf.followup_at
   AND b.booking_day <= DATE_ADD(mf.followup_date, INTERVAL 14 DAY)
),
first_booking AS (
  SELECT * EXCEPT(booking_rank)
  FROM booking_candidates
  WHERE booking_rank = 1
     OR order_id IS NULL
)
SELECT
  mf.moderate_report_date,
  mf.moderate_report_week,
  mf.moderate_report_month,
  mf.followup_date,
  mf.followup_week,
  mf.followup_month,
  mf.silver_session_id,
  mf.manychat_id,
  mf.user_name,
  mf.contact_number,
  mf.first_customer_message_at,
  mf.first_moderate_at,
  mf.moderate_tagged_at,
  mf.first_cs_reply_at,
  mf.first_cs_reply_sender,
  mf.reply_agent_name,
  mf.followup_user_name,
  mf.followup_agent_name,
  mf.followup_at,
  mf.followup_type,
  mf.followup_text,
  mf.days_from_moderate_to_followup,
  mf.days_from_reply_to_followup,
  CAST(mf.days_from_moderate_to_followup = 1 AS INT64) AS is_next_day_followup,
  fb.order_id,
  fb.booking_at,
  fb.booking_day,
  fb.booking_customer_name,
  fb.net_sales_amount,
  fb.gross_sales_amount,
  fb.total_cost_amount,
  fb.gross_profit_amount,
  fb.quantity_int,
  fb.canonical_order_brand,
  fb.canonical_order_tire_size,
  fb.installation_partner_name,
  fb.appointment_at,
  fb.appointment_day,
  fb.booked_inclusion_reason,
  IF(fb.order_id IS NOT NULL, 'Yes', 'No') AS is_booked,
  CAST(fb.order_id IS NOT NULL AS INT64) AS is_booked_flag,
  COALESCE(fb.booking_count_within_14d, 0) AS booking_count_within_14d,
  DATE_DIFF(fb.booking_day, mf.followup_date, DAY) AS days_from_followup_to_booking,
  CAST(1 AS INT64) AS followed_up_moderate_count
FROM matched_followups mf
LEFT JOIN first_booking fb
  ON fb.silver_session_id = mf.silver_session_id
 AND fb.followup_at = mf.followup_at;
