#standardSQL
CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail` AS
WITH followup_messages AS (
  SELECT
    DATE(TIMESTAMP(m.datetime, 'Asia/Manila'), 'Asia/Manila') AS report_date,
    DATE_TRUNC(DATE(TIMESTAMP(m.datetime, 'Asia/Manila'), 'Asia/Manila'), WEEK(MONDAY)) AS report_week,
    DATE_TRUNC(DATE(TIMESTAMP(m.datetime, 'Asia/Manila'), 'Asia/Manila'), MONTH) AS report_month,
    m.user_id AS manychat_id,
    COALESCE(NULLIF(u.user_name, ''), NULLIF(m.user_name, ''), CONCAT('manychat:', m.user_id)) AS user_name,
    m.sender AS agent_name,
    m.datetime AS followup_at,
    m.text_content AS followup_text,
    CASE
      WHEN REGEXP_CONTAINS(LOWER(m.text_content), r'\bproceed\b')
        OR REGEXP_CONTAINS(LOWER(m.text_content), r'would you like to proceed')
      THEN 'proceed_nudge'
      WHEN REGEXP_CONTAINS(LOWER(m.text_content), r'still interested')
      THEN 'still_interested'
      WHEN REGEXP_CONTAINS(LOWER(m.text_content), r'do you still need help with your inquiry')
        OR REGEXP_CONTAINS(LOWER(m.text_content), r'just checking')
        OR REGEXP_CONTAINS(LOWER(m.text_content), r'may napili na po kayong')
      THEN 'checking_in'
      ELSE NULL
    END AS followup_type,
    ROW_NUMBER() OVER (
      PARTITION BY
        m.user_id,
        DATE(TIMESTAMP(m.datetime, 'Asia/Manila'), 'Asia/Manila')
      ORDER BY m.datetime, m.message_id
    ) AS user_day_followup_rank
  FROM `gulong-chatbot-459723.manychat_data.messages` m
  LEFT JOIN `gulong-chatbot-459723.manychat_data.users_current` u
    ON u.business_unit = m.business_unit
   AND u.user_id = m.user_id
  WHERE m.business_unit = 'gulong'
    AND m.role = 'agent'
    AND m.type = 'msgout_lc'
    AND m.datetime >= DATETIME '2026-06-01 00:00:00'
    AND m.text_content IS NOT NULL
    AND m.sender IN (
      'sarah gulongph',
      'Aira L. Garcia',
      'Rem Reyes',
      'Becca Armstrng',
      'Atossa Saremi',
      'Rolyn Ang'
    )
    AND (
      REGEXP_CONTAINS(LOWER(m.text_content), r'still interested')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'do you still need help with your inquiry')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'just checking')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'may napili na po kayong')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'\bproceed\b')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'would you like to proceed')
    )
)
SELECT
  report_date,
  report_week,
  report_month,
  manychat_id,
  user_name,
  agent_name,
  followup_at,
  followup_type,
  followup_text,
  CAST(1 AS INT64) AS followup_count
FROM followup_messages
WHERE followup_type IS NOT NULL
  AND user_day_followup_rank = 1;
