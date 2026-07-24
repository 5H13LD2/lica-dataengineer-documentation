#standardSQL
CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_booking_summary` AS
WITH replied_moderates AS (
  SELECT
    report_date AS moderate_report_date,
    silver_session_id,
    manychat_id,
    first_cs_reply_at
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE reply_status = 'Has CS Reply'
    AND manychat_id IS NOT NULL
),
followups AS (
  SELECT
    report_date AS followup_date,
    manychat_id,
    followup_at,
    followup_type,
    agent_name AS followup_agent_name
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail`
),
matched_followups AS (
  SELECT * EXCEPT(match_rank)
  FROM (
    SELECT
      m.moderate_report_date,
      m.silver_session_id,
      m.manychat_id,
      f.followup_date,
      f.followup_at,
      f.followup_type,
      f.followup_agent_name,
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
first_booking AS (
  SELECT * EXCEPT(booking_rank)
  FROM (
    SELECT
      mf.silver_session_id,
      mf.followup_at,
      b.order_id,
      b.booking_day,
      ROW_NUMBER() OVER (
        PARTITION BY mf.silver_session_id, mf.followup_at
        ORDER BY b.booking_at ASC, b.order_id ASC
      ) AS booking_rank
    FROM matched_followups mf
    LEFT JOIN `gulong-chatbot-459723.gulong_core.orders_booked` b
      ON b.manychat_user_id = mf.manychat_id
     AND b.booking_at >= mf.followup_at
     AND b.booking_day <= DATE_ADD(mf.followup_date, INTERVAL 14 DAY)
  )
  WHERE booking_rank = 1
     OR order_id IS NULL
),
base AS (
  SELECT
    mf.moderate_report_date,
    mf.followup_date,
    mf.followup_type,
    mf.followup_agent_name,
    mf.days_from_moderate_to_followup,
    mf.days_from_reply_to_followup,
    CAST(mf.days_from_moderate_to_followup = 1 AS INT64) AS is_next_day_followup,
    CAST(1 AS INT64) AS followups_from_moderate,
    CAST(fb.order_id IS NOT NULL AS INT64) AS bookings_from_followups
  FROM matched_followups mf
  LEFT JOIN first_booking fb
    ON fb.silver_session_id = mf.silver_session_id
   AND fb.followup_at = mf.followup_at
)
SELECT
  moderate_report_date,
  followup_date,
  followup_agent_name,
  followup_type,
  days_from_moderate_to_followup,
  days_from_reply_to_followup,
  is_next_day_followup,
  SUM(followups_from_moderate) AS followups_from_moderate,
  SUM(bookings_from_followups) AS bookings_from_followups,
  SAFE_DIVIDE(SUM(bookings_from_followups), SUM(followups_from_moderate)) AS booking_rate
FROM base
GROUP BY
  moderate_report_date,
  followup_date,
  followup_agent_name,
  followup_type,
  days_from_moderate_to_followup,
  days_from_reply_to_followup,
  is_next_day_followup;
