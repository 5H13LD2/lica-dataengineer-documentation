#standardSQL

-- Fairness analysis layer for Taira vs CS performance.
--
-- Purpose:
-- - preserve the current broad/general KPI from p_looker_agent_daily_conversion
-- - expose a stricter filtered inquiry->booking view using the workbook-style booking rules
-- - let reporting compare both logic families side by side without replacing the current dashboard

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_taira_cs_fairness_logic_daily`
OPTIONS (
  description = "Daily Taira vs CS comparison layer with two logic families: general_official_kpi from p_looker_agent_daily_conversion and strict_filtered_live rebuilt from inquiry/date attribution with reportable, non-call, in-scope original-owner booking rules."
) AS
WITH official_general AS (
  SELECT
    report_date,
    CASE
      WHEN agent_name = 'Chatbot/JCo' THEN 'Taira (Chatbot/JCo)'
      WHEN LOWER(TRIM(agent_name)) IN ('sarah gulongph', 'sarah mae manansala', 'sarah') THEN 'Sarah'
      WHEN LOWER(TRIM(agent_name)) IN ('aira l. garcia', 'aira') THEN 'Aira L. Garcia'
      WHEN LOWER(TRIM(agent_name)) = 'rem reyes' THEN 'Rem Reyes'
      WHEN LOWER(TRIM(agent_name)) = 'rolyn ang' THEN 'Rolyn Ang'
      ELSE agent_name
    END AS agent_name,
    CASE
      WHEN agent_name = 'Chatbot/JCo' THEN 'Taira'
      ELSE 'Four-CS'
    END AS comparison_group,
    'general_official_kpi' AS logic_family,
    total_inquiries AS actual_inquiries,
    total_bookings AS booking_count,
    total_moderate_intents AS validated_moderate_inquiries,
    booking_inquiry_rate AS conversion_rate,
    moderate_intent_inquiry_rate AS moderate_rate,
    booking_moderate_intent_rate AS booking_per_moderate_rate
  FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
  WHERE agent_name IN (
    'Chatbot/JCo',
    'Aira L. Garcia',
    'Rem Reyes',
    'Rolyn Ang',
    'sarah gulongph'
  )
),
strict_inquiry_cohorts AS (
  SELECT
    assignment_date AS report_date,
    DATE_TRUNC(assignment_date, MONTH) AS report_month,
    user_id,
    silver_session_id,
    assignment_event_id,
    assignment_at,
    CASE
      WHEN is_chatbot_jeanel THEN 'Taira (Chatbot/JCo)'
      WHEN LOWER(TRIM(COALESCE(agent_reporting_name, assigned_agent_name, ''))) = 'rem reyes' THEN 'Rem Reyes'
      WHEN LOWER(TRIM(COALESCE(agent_reporting_name, assigned_agent_name, ''))) IN ('aira l. garcia', 'aira') THEN 'Aira L. Garcia'
      WHEN LOWER(TRIM(COALESCE(agent_reporting_name, assigned_agent_name, ''))) = 'rolyn ang' THEN 'Rolyn Ang'
      WHEN LOWER(TRIM(COALESCE(agent_reporting_name, assigned_agent_name, ''))) IN ('sarah gulongph', 'sarah mae manansala', 'sarah') THEN 'Sarah'
      ELSE NULL
    END AS agent_name,
    COALESCE(
      NULLIF(TRIM(silver_session_id), ''),
      CONCAT('event:', NULLIF(TRIM(assignment_event_id), '')),
      CONCAT('user:', CAST(user_id AS STRING), ':', CAST(assignment_at AS STRING))
    ) AS inquiry_key,
    COALESCE(
      CONCAT('evt:', NULLIF(TRIM(assignment_event_id), '')),
      CONCAT('sess:', NULLIF(TRIM(silver_session_id), '')),
      CONCAT('usr:', CAST(user_id AS STRING), ':', CAST(assignment_at AS STRING))
    ) AS booking_join_key
  FROM `gulong-chatbot-459723.gulong_core.inquiry_assignments`
  WHERE business_unit = 'gulong'
    AND (
      is_chatbot_jeanel
      OR LOWER(TRIM(agent_reporting_name)) IN (
        'rem reyes',
        'aira l. garcia',
        'aira',
        'rolyn ang',
        'sarah gulongph',
        'sarah mae manansala',
        'sarah'
      )
    )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY
      DATE_TRUNC(assignment_date, MONTH),
      COALESCE(
        NULLIF(TRIM(silver_session_id), ''),
        CONCAT('event:', NULLIF(TRIM(assignment_event_id), '')),
        CONCAT('user:', CAST(user_id AS STRING), ':', CAST(assignment_at AS STRING))
      )
    ORDER BY assignment_at ASC, loaded_at DESC, assignment_event_id
  ) = 1
),
strict_moderate_flags AS (
  SELECT
    silver_session_id,
    DATE_TRUNC(first_moderate_day, MONTH) AS moderate_month,
    TRUE AS validated_moderate
  FROM `gulong-chatbot-459723.gulong_core.moderate_intent_sessions`
  WHERE business_unit = 'gulong'
    AND validated_moderate = TRUE
  GROUP BY silver_session_id, moderate_month
),
strict_booking_flags AS (
  SELECT
    COALESCE(
      CONCAT('evt:', NULLIF(TRIM(inquiry_assignment_event_id), '')),
      CONCAT('sess:', NULLIF(TRIM(inquiry_silver_session_id), '')),
      CONCAT('usr:', CAST(manychat_user_id AS STRING), ':', CAST(inquiry_assignment_at AS STRING))
    ) AS booking_join_key,
    COUNT(DISTINCT order_id) AS booking_count
  FROM `gulong-chatbot-459723.gulong_core.orders_all`
  WHERE is_reportable_booked_order = TRUE
    AND LOWER(TRIM(COALESCE(customer_source_norm, ''))) <> 'call'
    AND inquiry_assignment_date IS NOT NULL
    AND booking_day IS NOT NULL
    AND (
      COALESCE(original_assigned_is_chatbot_jeanel, FALSE)
      OR LOWER(TRIM(COALESCE(
        original_assigned_agent_name,
        inquiry_agent_reporting_name,
        inquiry_assigned_agent_name,
        ''
      ))) IN (
        'rem reyes',
        'aira l. garcia',
        'aira',
        'rolyn ang',
        'sarah',
        'sarah gulongph',
        'sarah mae manansala'
      )
    )
  GROUP BY booking_join_key
),
strict_filtered_live AS (
  SELECT
    c.report_date,
    c.agent_name,
    CASE
      WHEN c.agent_name = 'Taira (Chatbot/JCo)' THEN 'Taira'
      ELSE 'Four-CS'
    END AS comparison_group,
    'strict_filtered_live' AS logic_family,
    COUNT(*) AS actual_inquiries,
    COALESCE(SUM(b.booking_count), 0) AS booking_count,
    COUNTIF(m.validated_moderate) AS validated_moderate_inquiries,
    SAFE_DIVIDE(COALESCE(SUM(b.booking_count), 0), COUNT(*)) AS conversion_rate,
    SAFE_DIVIDE(COUNTIF(m.validated_moderate), COUNT(*)) AS moderate_rate,
    SAFE_DIVIDE(COALESCE(SUM(b.booking_count), 0), COUNTIF(m.validated_moderate)) AS booking_per_moderate_rate
  FROM strict_inquiry_cohorts c
  LEFT JOIN strict_moderate_flags m
    ON m.silver_session_id = c.silver_session_id
   AND m.moderate_month = c.report_month
  LEFT JOIN strict_booking_flags b
    ON b.booking_join_key = c.booking_join_key
  WHERE c.agent_name IS NOT NULL
  GROUP BY c.report_date, c.agent_name
)
SELECT * FROM official_general
UNION ALL
SELECT * FROM strict_filtered_live;


CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_taira_cs_fairness_logic_period`
OPTIONS (
  description = "Period rollup of the fairness logic daily layer for Taira vs CS. Supports side-by-side comparison of general_official_kpi vs strict_filtered_live."
) AS
SELECT
  report_date,
  agent_name,
  comparison_group,
  logic_family,
  actual_inquiries,
  booking_count,
  validated_moderate_inquiries,
  conversion_rate,
  moderate_rate,
  booking_per_moderate_rate
FROM `gulong-chatbot-459723.gulong_reporting.v_taira_cs_fairness_logic_daily`;
