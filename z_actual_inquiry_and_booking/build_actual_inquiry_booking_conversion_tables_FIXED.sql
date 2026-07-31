#standardSQL
-- =====================================================================
-- FIXED report-level build for actual inquiry -> booking conversion.
-- Goal: reproduce the audit workbook exactly (July: 12,429 inquiries,
-- 111 traceable bookings; per-lane Taira 32 / Aira 26 / Rem 22 /
-- Sarah 18 / Rolyn 13).
--
-- Changes vs the original build_actual_inquiry_booking_conversion_tables.sql,
-- each marked [FIX n] inline:
--   [FIX 1] Booking<->inquiry JOIN key is now EVENT-first, symmetric on
--           both sides. inquiry_assignment_event_id is the workbook's
--           canonical link (100% populated on qualifying bookings);
--           silver_session_id is only ~75% populated on the order side,
--           so a silver-first key silently drops bookings.
--   [FIX 2] CALL orders are excluded via is_call_order (customer_source_norm
--           = 'call'), NOT via sales_channel. All call orders are fb, so the
--           old channel filter did not remove them.
--   [FIX 3] Added the bare 'aira' alias to the booking owner list for
--           symmetry with the cohort/denominator logic.
--   [FIX 4] Cohort dedup is now partitioned BY MONTH, so a session that
--           spans months is not pulled out of the month you are reporting.
--           This matches the workbook's within-window dedup.
--
-- NOTE on grain: dedup key stays SESSION-first (one inquiry row per
-- silver_session_id per month) so the denominator matches the workbook.
-- The JOIN key is separate and EVENT-first. Do not conflate the two.
-- =====================================================================

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_detail`
PARTITION BY report_date
CLUSTER BY reporting_lane, inquiry_key
AS
WITH inquiry_cohorts AS (
  SELECT
    assignment_date AS report_date,
    DATE_TRUNC(assignment_date, WEEK(MONDAY)) AS report_week,
    DATE_TRUNC(assignment_date, MONTH) AS report_month,
    business_unit,
    user_id,
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
    assignment_event_id,
    session_seq,
    session_start_at,
    session_end_at,
    first_user_message_at,
    latest_user_message_at,
    user_message_count,
    assignment_at,

    -- Denominator grain key: SESSION-first (one inquiry per session/month).
    COALESCE(
      NULLIF(TRIM(silver_session_id), ''),
      CONCAT('event:', NULLIF(TRIM(assignment_event_id), '')),
      CONCAT('user:', CAST(user_id AS STRING), ':', CAST(assignment_at AS STRING))
    ) AS inquiry_key,

    -- [FIX 1] Booking JOIN key: EVENT-first, symmetric with the order side.
    COALESCE(
      CONCAT('evt:',  NULLIF(TRIM(assignment_event_id), '')),
      CONCAT('sess:', NULLIF(TRIM(silver_session_id), '')),
      CONCAT('usr:',  CAST(user_id AS STRING), ':', CAST(assignment_at AS STRING))
    ) AS booking_join_key,

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
  -- [FIX 4] Dedup within month, session-grain, earliest assignment wins.
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

moderate_flags AS (
  SELECT
    silver_session_id,
    DATE_TRUNC(first_moderate_day, MONTH) AS moderate_month,
    TRUE AS validated_moderate,
    ARRAY_AGG(first_moderate_source IGNORE NULLS ORDER BY first_moderate_at LIMIT 1)[SAFE_OFFSET(0)] AS first_moderate_source,
    MIN(first_moderate_at) AS first_moderate_at,
    ARRAY_AGG(chat_analysis_top_intent IGNORE NULLS ORDER BY first_moderate_at LIMIT 1)[SAFE_OFFSET(0)] AS chat_analysis_top_intent,
    STRING_AGG(DISTINCT src, ', ' ORDER BY src) AS moderate_evidence_sources
  FROM `gulong-chatbot-459723.gulong_core.moderate_intent_sessions`
  LEFT JOIN UNNEST(IFNULL(JSON_VALUE_ARRAY(evidence_sources_json), CAST([] AS ARRAY<STRING>))) AS src
  WHERE business_unit = 'gulong'
    AND validated_moderate = TRUE
  GROUP BY silver_session_id, moderate_month
),

booking_flags AS (
  SELECT
    -- [FIX 1] Order-side JOIN key: EVENT-first, identical shape to cohort.
    COALESCE(
      CONCAT('evt:',  NULLIF(TRIM(inquiry_assignment_event_id), '')),
      CONCAT('sess:', NULLIF(TRIM(inquiry_silver_session_id), '')),
      CONCAT('usr:',  CAST(manychat_user_id AS STRING), ':', CAST(inquiry_assignment_at AS STRING))
    ) AS booking_join_key,
    COUNT(DISTINCT order_id) AS linked_order_count_all,
    COUNT(DISTINCT order_id) AS qualifying_booking_count,
    COUNT(DISTINCT order_id) > 0 AS converted_inquiry,
    MIN(booking_at) AS first_qualifying_booking_at,
    MIN(booking_day) AS first_qualifying_booking_day,
    MAX(booking_at) AS latest_qualifying_booking_at,
    MAX(booking_day) AS latest_qualifying_booking_day,
    SUM(quantity_int) AS qualifying_tire_quantity,
    SUM(gross_sales_amount) AS qualifying_gross_sales_amount,
    SUM(net_sales_amount) AS qualifying_net_sales_amount,
    SUM(total_cost_amount) AS qualifying_total_cost_amount,
    SUM(gross_profit_amount) AS qualifying_gross_profit_amount,
    STRING_AGG(DISTINCT order_id, ', ' ORDER BY order_id) AS linked_order_ids,
    STRING_AGG(DISTINCT order_id, ', ' ORDER BY order_id) AS qualifying_order_ids
  FROM `gulong-chatbot-459723.gulong_core.orders_all`
  WHERE is_reportable_booked_order = TRUE
    -- [FIX 2] Exclude CALL orders properly via customer_source_norm.
    -- `gulong_core.orders_all` in this environment does not expose the
    -- workbook's `is_call_order` flag directly.
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
        'aira',                    -- [FIX 3] added for symmetry
        'rolyn ang',
        'sarah',
        'sarah gulongph',
        'sarah mae manansala'
      )
    )
  GROUP BY booking_join_key
)

SELECT
  c.report_date,
  c.report_week,
  c.report_month,
  c.business_unit,
  c.inquiry_key,
  c.user_id,
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
  c.assignment_event_id,
  c.session_seq,
  c.session_start_at,
  c.session_end_at,
  c.first_user_message_at,
  c.latest_user_message_at,
  c.user_message_count,
  c.assignment_at,
  COALESCE(m.validated_moderate, FALSE) AS validated_moderate,
  m.first_moderate_at,
  DATE(m.first_moderate_at) AS first_moderate_day,
  m.first_moderate_source,
  m.chat_analysis_top_intent,
  m.moderate_evidence_sources,
  COALESCE(b.linked_order_count_all, 0) AS linked_order_count_all,
  COALESCE(b.qualifying_booking_count, 0) AS qualifying_booking_count,
  COALESCE(b.converted_inquiry, FALSE) AS converted_inquiry,
  CAST(COALESCE(b.converted_inquiry, FALSE) AS INT64) AS converted_inquiry_flag,
  b.first_qualifying_booking_at,
  b.first_qualifying_booking_day,
  b.latest_qualifying_booking_at,
  b.latest_qualifying_booking_day,
  COALESCE(b.qualifying_tire_quantity, 0) AS qualifying_tire_quantity,
  COALESCE(b.qualifying_gross_sales_amount, 0) AS qualifying_gross_sales_amount,
  COALESCE(b.qualifying_net_sales_amount, 0) AS qualifying_net_sales_amount,
  COALESCE(b.qualifying_total_cost_amount, 0) AS qualifying_total_cost_amount,
  COALESCE(b.qualifying_gross_profit_amount, 0) AS qualifying_gross_profit_amount,
  b.linked_order_ids,
  b.qualifying_order_ids,
  CURRENT_DATETIME('Asia/Manila') AS loaded_at
FROM inquiry_cohorts c
LEFT JOIN moderate_flags m
  ON m.silver_session_id = c.silver_session_id
 AND m.moderate_month = c.report_month
-- [FIX 1] Join on the EVENT-first key, not the session-first denominator key.
LEFT JOIN booking_flags b
  ON b.booking_join_key = c.booking_join_key;


CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_daily`
PARTITION BY report_date
CLUSTER BY reporting_lane
AS
SELECT
  report_date,
  report_week,
  report_month,
  reporting_lane,
  COUNT(*) AS actual_inquiries,
  COUNTIF(validated_moderate) AS validated_moderate_inquiries,
  SAFE_DIVIDE(COUNTIF(validated_moderate), COUNT(*)) AS moderate_rate,
  SUM(qualifying_booking_count) AS traceable_qualifying_bookings,
  COUNTIF(converted_inquiry) AS distinct_converted_inquiries,
  SAFE_DIVIDE(SUM(qualifying_booking_count), COUNT(*)) AS booking_per_inquiry_rate,
  SAFE_DIVIDE(COUNTIF(converted_inquiry), COUNT(*)) AS unique_inquiry_conversion_rate,
  SAFE_DIVIDE(SUM(qualifying_booking_count), COUNTIF(validated_moderate)) AS booking_per_moderate_rate,
  CONCAT(
    CAST(SUM(qualifying_booking_count) AS STRING), '/',
    CAST(COUNT(*) AS STRING), ' (',
    CAST(ROUND(SAFE_DIVIDE(SUM(qualifying_booking_count), COUNT(*)) * 100, 2) AS STRING), '%)'
  ) AS conversion_display,
  SUM(qualifying_tire_quantity) AS qualifying_tire_quantity,
  SUM(qualifying_gross_sales_amount) AS qualifying_gross_sales_amount,
  SUM(qualifying_net_sales_amount) AS qualifying_net_sales_amount,
  SUM(qualifying_total_cost_amount) AS qualifying_total_cost_amount,
  SUM(qualifying_gross_profit_amount) AS qualifying_gross_profit_amount,
  MAX(loaded_at) AS loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_detail`
GROUP BY report_date, report_week, report_month, reporting_lane;


CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_monthly`
PARTITION BY report_month
CLUSTER BY reporting_lane
AS
SELECT
  report_month,
  reporting_lane,
  COUNT(*) AS actual_inquiries,
  COUNTIF(validated_moderate) AS validated_moderate_inquiries,
  SAFE_DIVIDE(COUNTIF(validated_moderate), COUNT(*)) AS moderate_rate,
  SUM(qualifying_booking_count) AS traceable_qualifying_bookings,
  COUNTIF(converted_inquiry) AS distinct_converted_inquiries,
  SAFE_DIVIDE(SUM(qualifying_booking_count), COUNT(*)) AS booking_per_inquiry_rate,
  SAFE_DIVIDE(COUNTIF(converted_inquiry), COUNT(*)) AS unique_inquiry_conversion_rate,
  SAFE_DIVIDE(SUM(qualifying_booking_count), COUNTIF(validated_moderate)) AS booking_per_moderate_rate,
  CONCAT(
    CAST(SUM(qualifying_booking_count) AS STRING), '/',
    CAST(COUNT(*) AS STRING), ' (',
    CAST(ROUND(SAFE_DIVIDE(SUM(qualifying_booking_count), COUNT(*)) * 100, 2) AS STRING), '%)'
  ) AS conversion_display,
  SUM(qualifying_tire_quantity) AS qualifying_tire_quantity,
  SUM(qualifying_gross_sales_amount) AS qualifying_gross_sales_amount,
  SUM(qualifying_net_sales_amount) AS qualifying_net_sales_amount,
  SUM(qualifying_total_cost_amount) AS qualifying_total_cost_amount,
  SUM(qualifying_gross_profit_amount) AS qualifying_gross_profit_amount,
  MAX(loaded_at) AS loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_detail`
GROUP BY report_month, reporting_lane;
