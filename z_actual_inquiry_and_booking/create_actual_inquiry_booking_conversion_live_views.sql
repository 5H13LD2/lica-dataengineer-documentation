#standardSQL

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_actual_inquiry_booking_conversion_detail`
OPTIONS (
  description = "Inquiry-grain actual inquiry conversion detail for Gulong FB/Chatbot reporting lanes. Denominator is deduplicated original inquiry ownership from gulong_core.inquiry_assignments. Moderate flags come from validated moderate_intent_sessions. Booking facts come from gulong_core.orders_all and are attributed back to the original inquiry key using the inquiry-date/original-owner booking universe behind the workbook Lane_Summary. Use report_date/report_month as the primary date filters for inquiry-cohort funnel reporting."
) AS
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
),
booking_flags AS (
  SELECT
    COALESCE(
      NULLIF(TRIM(inquiry_silver_session_id), ''),
      CONCAT('event:', NULLIF(TRIM(inquiry_assignment_event_id), '')),
      CONCAT('user:', manychat_user_id, ':', CAST(inquiry_assignment_at AS STRING))
    ) AS inquiry_key,
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
    AND sales_channel IN ('fb', 'chatbot')
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
        'rolyn ang',
        'sarah',
        'sarah gulongph',
        'sarah mae manansala'
      )
    )
  GROUP BY inquiry_key
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
  c.session_seq,
  c.session_start_at,
  c.session_end_at,
  c.first_user_message_at,
  c.latest_user_message_at,
  c.user_message_count,
  c.assignment_at,
  c.assignment_event_id,
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
  b.qualifying_order_ids
FROM inquiry_cohorts c
LEFT JOIN moderate_flags m
  ON m.silver_session_id = c.silver_session_id
LEFT JOIN booking_flags b
  ON b.inquiry_key = c.inquiry_key;


CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_actual_inquiry_booking_conversion_daily`
OPTIONS (
  description = "Daily inquiry-cohort funnel summary for Gulong FB/Chatbot reporting lanes. Denominator is actual inquiries from v_actual_inquiry_booking_conversion_detail."
) AS
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
    CAST(SUM(qualifying_booking_count) AS STRING),
    '/',
    CAST(COUNT(*) AS STRING),
    ' (',
    CAST(ROUND(SAFE_DIVIDE(SUM(qualifying_booking_count), COUNT(*)) * 100, 2) AS STRING),
    '%)'
  ) AS conversion_display,
  SUM(qualifying_tire_quantity) AS qualifying_tire_quantity,
  SUM(qualifying_gross_sales_amount) AS qualifying_gross_sales_amount,
  SUM(qualifying_net_sales_amount) AS qualifying_net_sales_amount,
  SUM(qualifying_total_cost_amount) AS qualifying_total_cost_amount,
  SUM(qualifying_gross_profit_amount) AS qualifying_gross_profit_amount
FROM `gulong-chatbot-459723.gulong_reporting.v_actual_inquiry_booking_conversion_detail`
GROUP BY report_date, report_week, report_month, reporting_lane;


CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_actual_inquiry_booking_conversion_monthly`
OPTIONS (
  description = "Monthly inquiry-cohort funnel summary for Gulong FB/Chatbot reporting lanes. Denominator is actual inquiries from v_actual_inquiry_booking_conversion_detail."
) AS
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
    CAST(SUM(qualifying_booking_count) AS STRING),
    '/',
    CAST(COUNT(*) AS STRING),
    ' (',
    CAST(ROUND(SAFE_DIVIDE(SUM(qualifying_booking_count), COUNT(*)) * 100, 2) AS STRING),
    '%)'
  ) AS conversion_display,
  SUM(qualifying_tire_quantity) AS qualifying_tire_quantity,
  SUM(qualifying_gross_sales_amount) AS qualifying_gross_sales_amount,
  SUM(qualifying_net_sales_amount) AS qualifying_net_sales_amount,
  SUM(qualifying_total_cost_amount) AS qualifying_total_cost_amount,
  SUM(qualifying_gross_profit_amount) AS qualifying_gross_profit_amount
FROM `gulong-chatbot-459723.gulong_reporting.v_actual_inquiry_booking_conversion_detail`
GROUP BY report_month, reporting_lane;
