#standardSQL

-- Raw-only current-state rebuild candidate for the 2026-07-29 PDF-style
-- Taira vs CS performance comparison.
--
-- Important:
-- 1. This uses only raw warehouse sources (`gulong_core.*`), not frozen PDF tables.
-- 2. The 2026-07-29 PDF itself was a frozen snapshot through 2026-07-28 22:38 Asia/Manila.
-- 3. Current raw tables have been reloaded/backfilled after 2026-07-29, so exact frozen
--    parity is not guaranteed anymore from current raw alone.
-- 4. Taira and human CS do not appear to share one identical booking universe in the PDF pack.
--    This query therefore uses the best-fit raw booking logic observed from current data:
--      - Taira booking numerator: reportable booked FB/Chatbot orders where
--        `original_assigned_is_chatbot_jeanel = TRUE`
--      - Human CS booking numerator: reportable booked, non-call, inquiry-linked orders
--        attributed by original owner
--
-- Date scope can be changed in the first CTE.

WITH params AS (
  SELECT
    DATE '2026-07-01' AS date_from,
    DATE '2026-07-28' AS date_to
),

inquiry_base AS (
  SELECT
    a.assignment_date AS report_date,
    DATE_TRUNC(a.assignment_date, WEEK(MONDAY)) AS report_week,
    DATE_TRUNC(a.assignment_date, MONTH) AS report_month,
    COALESCE(
      NULLIF(TRIM(a.silver_session_id), ''),
      CONCAT('event:', NULLIF(TRIM(a.assignment_event_id), '')),
      CONCAT('user:', a.user_id, ':', CAST(a.assignment_at AS STRING))
    ) AS inquiry_key,
    CASE
      WHEN a.is_chatbot_jeanel THEN 'Taira (Chatbot/JCo)'
      WHEN LOWER(TRIM(COALESCE(a.agent_reporting_name, a.assigned_agent_name, ''))) = 'rem reyes' THEN 'Rem Reyes'
      WHEN LOWER(TRIM(COALESCE(a.agent_reporting_name, a.assigned_agent_name, ''))) IN ('aira l. garcia', 'aira') THEN 'Aira L. Garcia'
      WHEN LOWER(TRIM(COALESCE(a.agent_reporting_name, a.assigned_agent_name, ''))) = 'rolyn ang' THEN 'Rolyn Ang'
      WHEN LOWER(TRIM(COALESCE(a.agent_reporting_name, a.assigned_agent_name, ''))) IN ('sarah gulongph', 'sarah mae manansala', 'sarah') THEN 'Sarah'
    END AS agent_name,
    a.is_chatbot_jeanel,
    a.silver_session_id
  FROM `gulong-chatbot-459723.gulong_core.inquiry_assignments` a
  CROSS JOIN params p
  WHERE a.business_unit = 'gulong'
    AND a.assignment_date BETWEEN p.date_from AND p.date_to
    AND (
      a.is_chatbot_jeanel
      OR LOWER(TRIM(COALESCE(a.agent_reporting_name, a.assigned_agent_name, ''))) IN (
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
      NULLIF(TRIM(a.silver_session_id), ''),
      CONCAT('event:', NULLIF(TRIM(a.assignment_event_id), '')),
      CONCAT('user:', a.user_id, ':', CAST(a.assignment_at AS STRING))
    )
    ORDER BY a.assignment_at ASC, a.loaded_at DESC, a.assignment_event_id
  ) = 1
),

moderate_flags AS (
  SELECT
    silver_session_id,
    TRUE AS validated_moderate
  FROM `gulong-chatbot-459723.gulong_core.moderate_intent_sessions`
  WHERE business_unit = 'gulong'
    AND validated_moderate = TRUE
  GROUP BY silver_session_id
),

inquiries AS (
  SELECT
    i.report_date,
    i.report_week,
    i.report_month,
    i.inquiry_key,
    i.agent_name,
    IF(i.agent_name = 'Taira (Chatbot/JCo)', 'Taira', 'Four-CS') AS comparison_group,
    COALESCE(m.validated_moderate, FALSE) AS validated_moderate
  FROM inquiry_base i
  LEFT JOIN moderate_flags m
    ON m.silver_session_id = i.silver_session_id
  WHERE i.agent_name IS NOT NULL
),

taira_booking_orders AS (
  SELECT DISTINCT
    order_id,
    booking_day,
    'Taira (Chatbot/JCo)' AS agent_name
  FROM `gulong-chatbot-459723.gulong_core.orders_all`
  CROSS JOIN params p
  WHERE booking_day BETWEEN p.date_from AND p.date_to
    AND is_reportable_booked_order = TRUE
    AND sales_channel IN ('fb', 'chatbot')
    AND COALESCE(original_assigned_is_chatbot_jeanel, FALSE) = TRUE
),

cs_booking_orders AS (
  SELECT DISTINCT
    order_id,
    booking_day,
    CASE
      WHEN LOWER(TRIM(COALESCE(original_assigned_agent_name, inquiry_agent_reporting_name, inquiry_assigned_agent_name, ''))) = 'rem reyes' THEN 'Rem Reyes'
      WHEN LOWER(TRIM(COALESCE(original_assigned_agent_name, inquiry_agent_reporting_name, inquiry_assigned_agent_name, ''))) IN ('aira l. garcia', 'aira') THEN 'Aira L. Garcia'
      WHEN LOWER(TRIM(COALESCE(original_assigned_agent_name, inquiry_agent_reporting_name, inquiry_assigned_agent_name, ''))) = 'rolyn ang' THEN 'Rolyn Ang'
      WHEN LOWER(TRIM(COALESCE(original_assigned_agent_name, inquiry_agent_reporting_name, inquiry_assigned_agent_name, ''))) IN ('sarah', 'sarah gulongph', 'sarah mae manansala') THEN 'Sarah'
    END AS agent_name
  FROM `gulong-chatbot-459723.gulong_core.orders_all`
  CROSS JOIN params p
  WHERE booking_day BETWEEN p.date_from AND p.date_to
    AND is_reportable_booked_order = TRUE
    AND LOWER(TRIM(COALESCE(customer_source_norm, ''))) <> 'call'
    AND inquiry_assignment_date IS NOT NULL
),

booking_summary AS (
  SELECT
    agent_name,
    COUNT(DISTINCT order_id) AS bookings
  FROM (
    SELECT * FROM taira_booking_orders
    UNION ALL
    SELECT * FROM cs_booking_orders
  )
  WHERE agent_name IS NOT NULL
  GROUP BY agent_name
),

inquiry_summary AS (
  SELECT
    agent_name,
    comparison_group,
    COUNT(*) AS inquiries,
    COUNTIF(validated_moderate) AS validated_moderates
  FROM inquiries
  GROUP BY agent_name, comparison_group
)

SELECT
  s.agent_name,
  s.comparison_group,
  s.inquiries,
  s.validated_moderates,
  COALESCE(b.bookings, 0) AS bookings,
  SAFE_DIVIDE(COALESCE(b.bookings, 0), s.inquiries) AS conversion_rate
FROM inquiry_summary s
LEFT JOIN booking_summary b
  USING (agent_name)
ORDER BY
  CASE s.agent_name
    WHEN 'Aira L. Garcia' THEN 1
    WHEN 'Rem Reyes' THEN 2
    WHEN 'Rolyn Ang' THEN 3
    WHEN 'Sarah' THEN 4
    WHEN 'Taira (Chatbot/JCo)' THEN 5
    ELSE 99
  END;
