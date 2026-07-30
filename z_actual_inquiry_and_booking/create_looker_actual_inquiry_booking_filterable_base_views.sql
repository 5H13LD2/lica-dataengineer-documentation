#standardSQL

-- Flexible Looker base layer for inquiry and booking analysis.
-- Use these views when dashboard users need to toggle booking-scope filters
-- such as "non-call only" or "original-owner only" inside Looker.
--
-- Important:
-- The workbook flags `is_call_order`, `inquiry_in_july_scope`, and
-- `in_scope_original_owner` are not persisted as-is in `gulong_core.orders_all`.
-- This file therefore exposes warehouse-safe approximation flags so Looker can
-- switch between the locked KPI universe and broader exploratory slices.

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_actual_inquiry_base`
OPTIONS (
  description = "Inquiry-grain Looker base view for actual inquiry analysis. One row per deduplicated inquiry assignment. Use for denominator metrics, inquiry counts, reporting-lane filtering, and conversion joins to booking attribution base views."
) AS
WITH inquiry_cohorts AS (
  SELECT
    assignment_date AS report_date,
    DATE_TRUNC(assignment_date, WEEK(MONDAY)) AS report_week,
    DATE_TRUNC(assignment_date, MONTH) AS report_month,
    business_unit,
    user_id AS manychat_id,
    user_name,
    assigned_agent_key,
    assigned_agent_name,
    agent_reporting_group,
    agent_reporting_name,
    is_chatbot_jeanel,
    raw_channel_value,
    messaging_channel,
    channel_subtype,
    silver_session_id,
    session_seq,
    session_start_at,
    session_end_at,
    first_user_message_at,
    latest_user_message_at,
    user_message_count,
    assignment_at,
    assignment_event_id,
    COALESCE(
      NULLIF(TRIM(silver_session_id), ''),
      CONCAT('event:', NULLIF(TRIM(assignment_event_id), '')),
      CONCAT('user:', user_id, ':', CAST(assignment_at AS STRING))
    ) AS inquiry_key,
    CASE
      WHEN is_chatbot_jeanel THEN 'Taira (Chatbot/JCo)'
      WHEN LOWER(TRIM(COALESCE(agent_reporting_name, assigned_agent_name, ''))) IN ('rem reyes') THEN 'Rem Reyes'
      WHEN LOWER(TRIM(COALESCE(agent_reporting_name, assigned_agent_name, ''))) IN ('aira l. garcia', 'aira') THEN 'Aira L. Garcia'
      WHEN LOWER(TRIM(COALESCE(agent_reporting_name, assigned_agent_name, ''))) IN ('rolyn ang') THEN 'Rolyn Ang'
      WHEN LOWER(TRIM(COALESCE(agent_reporting_name, assigned_agent_name, ''))) IN ('sarah gulongph', 'sarah mae manansala', 'sarah') THEN 'Sarah'
      ELSE COALESCE(agent_reporting_name, assigned_agent_name, 'Unassigned')
    END AS reporting_lane
  FROM `gulong-chatbot-459723.gulong_core.inquiry_assignments`
  WHERE business_unit = 'gulong'
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY COALESCE(
      NULLIF(TRIM(silver_session_id), ''),
      CONCAT('event:', NULLIF(TRIM(assignment_event_id), '')),
      CONCAT('user:', user_id, ':', CAST(assignment_at AS STRING))
    )
    ORDER BY assignment_at ASC, loaded_at DESC, assignment_event_id
  ) = 1
),
moderate_flags AS (
  SELECT
    silver_session_id,
    TRUE AS validated_moderate,
    ARRAY_AGG(first_moderate_source IGNORE NULLS ORDER BY first_moderate_at LIMIT 1)[SAFE_OFFSET(0)] AS first_moderate_source,
    MIN(first_moderate_at) AS first_moderate_at,
    ARRAY_AGG(chat_analysis_top_intent IGNORE NULLS ORDER BY first_moderate_at LIMIT 1)[SAFE_OFFSET(0)] AS chat_analysis_top_intent,
    STRING_AGG(DISTINCT src, ', ' ORDER BY src) AS moderate_evidence_sources
  FROM `gulong-chatbot-459723.gulong_core.moderate_intent_sessions`
  LEFT JOIN UNNEST(IFNULL(JSON_VALUE_ARRAY(evidence_sources_json), CAST([] AS ARRAY<STRING>))) AS src
  WHERE business_unit = 'gulong'
    AND validated_moderate = TRUE
  GROUP BY silver_session_id
)
SELECT
  c.report_date,
  c.report_week,
  c.report_month,
  c.business_unit,
  c.inquiry_key,
  c.manychat_id,
  c.user_name,
  c.assigned_agent_key,
  c.assigned_agent_name,
  c.agent_reporting_group,
  c.agent_reporting_name,
  c.reporting_lane,
  c.is_chatbot_jeanel,
  c.raw_channel_value,
  c.messaging_channel,
  c.channel_subtype,
  c.silver_session_id,
  c.session_seq,
  c.session_start_at,
  c.session_end_at,
  c.first_user_message_at,
  c.latest_user_message_at,
  c.user_message_count,
  c.assignment_at,
  c.assignment_event_id,
  COALESCE(m.validated_moderate, FALSE) AS validated_moderate,
  IF(COALESCE(m.validated_moderate, FALSE), 'Yes', 'No') AS is_moderate,
  CAST(COALESCE(m.validated_moderate, FALSE) AS INT64) AS validated_moderate_count,
  m.first_moderate_at,
  DATE(m.first_moderate_at) AS first_moderate_day,
  m.first_moderate_source,
  m.chat_analysis_top_intent,
  m.moderate_evidence_sources,
  CAST(1 AS INT64) AS actual_inquiry_count,
  c.reporting_lane IN (
    'Rem Reyes',
    'Aira L. Garcia',
    'Rolyn Ang',
    'Sarah',
    'Taira (Chatbot/JCo)'
  ) AS is_primary_reporting_lane,
  CURRENT_DATETIME('Asia/Manila') AS loaded_at
FROM inquiry_cohorts c
LEFT JOIN moderate_flags m
  ON m.silver_session_id = c.silver_session_id;


CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_actual_inquiry_booking_attribution_base`
OPTIONS (
  description = "Booking-grain Looker base view for inquiry-date attribution analysis. One row per reportable booked order linked to an inquiry key. Includes approximation flags that let Looker users toggle between the locked KPI booking universe and broader exploratory slices."
) AS
SELECT
  COALESCE(
    NULLIF(TRIM(inquiry_silver_session_id), ''),
    CONCAT('event:', NULLIF(TRIM(inquiry_assignment_event_id), '')),
    CONCAT('user:', manychat_user_id, ':', CAST(inquiry_assignment_at AS STRING))
  ) AS inquiry_key,
  order_id,
  manychat_user_id AS manychat_id,
  booking_at,
  booking_day,
  inquiry_assignment_at,
  inquiry_assignment_date,
  sales_channel,
  quantity_int,
  gross_sales_amount,
  net_sales_amount,
  total_cost_amount,
  gross_profit_amount,
  is_reportable_booked_order,
  COALESCE(original_assigned_is_chatbot_jeanel, FALSE) AS original_assigned_is_chatbot_jeanel,
  original_assigned_agent_name,
  inquiry_agent_reporting_name,
  inquiry_assigned_agent_name,
  CASE
    WHEN COALESCE(original_assigned_is_chatbot_jeanel, FALSE) THEN 'Taira (Chatbot/JCo)'
    WHEN LOWER(TRIM(COALESCE(
      original_assigned_agent_name,
      inquiry_agent_reporting_name,
      inquiry_assigned_agent_name,
      ''
    ))) IN ('rem reyes') THEN 'Rem Reyes'
    WHEN LOWER(TRIM(COALESCE(
      original_assigned_agent_name,
      inquiry_agent_reporting_name,
      inquiry_assigned_agent_name,
      ''
    ))) IN ('aira l. garcia', 'aira') THEN 'Aira L. Garcia'
    WHEN LOWER(TRIM(COALESCE(
      original_assigned_agent_name,
      inquiry_agent_reporting_name,
      inquiry_assigned_agent_name,
      ''
    ))) IN ('rolyn ang') THEN 'Rolyn Ang'
    WHEN LOWER(TRIM(COALESCE(
      original_assigned_agent_name,
      inquiry_agent_reporting_name,
      inquiry_assigned_agent_name,
      ''
    ))) IN ('sarah', 'sarah gulongph', 'sarah mae manansala') THEN 'Sarah'
    ELSE COALESCE(
      original_assigned_agent_name,
      inquiry_agent_reporting_name,
      inquiry_assigned_agent_name,
      'Unassigned'
    )
  END AS original_owner_lane_approx,
  sales_channel IN ('fb', 'chatbot') AS approx_is_non_call_order,
  inquiry_assignment_date IS NOT NULL AS approx_inquiry_in_scope,
  (
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
  ) AS approx_in_scope_original_owner,
  (
    is_reportable_booked_order = TRUE
    AND sales_channel IN ('fb', 'chatbot')
    AND inquiry_assignment_date IS NOT NULL
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
  ) AS approx_matches_locked_booking_scope,
  CURRENT_DATETIME('Asia/Manila') AS loaded_at
FROM `gulong-chatbot-459723.gulong_core.orders_all`
WHERE is_reportable_booked_order = TRUE
  AND booking_day IS NOT NULL
  AND COALESCE(
    NULLIF(TRIM(inquiry_silver_session_id), ''),
    NULLIF(TRIM(inquiry_assignment_event_id), ''),
    CAST(manychat_user_id AS STRING)
  ) IS NOT NULL;
