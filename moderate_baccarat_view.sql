CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_baccarat`
OPTIONS (
  description = "One row per moderate session from v_looker_moderate_followup_coverage. Combines the moderate/session denominator with the first matched official booking and the first true CS follow-up so Looker can analyze the moderate-to-booking funnel in one place. GRAIN: silver_session_id."
)
AS
WITH first_reply AS (
  SELECT
    silver_session_id,
    moderate_tagged_at,
    first_cs_reply_at
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
),
moderates AS (
  SELECT
    moderate_report_date,
    silver_session_id,
    manychat_id,
    user_name,
    contact_number,
    reply_agent_name,
    fr.moderate_tagged_at,
    fr.first_cs_reply_at,
    first_followup_date AS followup_date,
    first_followup_text AS cs_followup_text
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`
  LEFT JOIN first_reply fr
    USING (silver_session_id)
),
first_booking AS (
  SELECT
    silver_session_id,
    order_id,
    booking_day,
    order_status_norm AS order_status,
    days_from_moderate_to_booking,
    ROW_NUMBER() OVER (
      PARTITION BY silver_session_id
      ORDER BY booking_at, order_id
    ) AS rn
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`
  WHERE moderate_report_date IS NOT NULL
)
SELECT
  m.moderate_report_date,
  m.moderate_tagged_at,
  m.first_cs_reply_at,
  fb.booking_day,
  m.user_name,
  fb.order_status,
  m.contact_number,
  m.manychat_id,
  fb.order_id,
  fb.days_from_moderate_to_booking AS days_to_moderate_conversion,
  m.followup_date,
  m.reply_agent_name,
  m.cs_followup_text,
  COALESCE(fb.order_id, 'No') AS isbooked
FROM moderates m
LEFT JOIN first_booking fb
  ON fb.silver_session_id = m.silver_session_id
 AND fb.rn = 1;
