#standardSQL

-- Hybrid Looker source:
-- - frozen exact PDF-card daily rows through 2026-07-28
-- - live warehouse-equivalent continuation from 2026-07-29 onward
--
-- Use this when you want:
-- - exact historical alignment to the 2026-07-29 PDF cards
-- - day-level filtering in Looker
-- - continued freshness for later days

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_pdf_cards_hybrid_daily`
OPTIONS (
  description = "Hybrid daily Looker source. Uses exact frozen PDF-card daily rows through 2026-07-28, then continues with live warehouse-equivalent inquiry-date conversion rows from 2026-07-29 onward."
) AS
WITH frozen_history AS (
  SELECT
    snapshot_date,
    observation_cutoff_at,
    report_section,
    agent_name,
    report_date,
    report_month,
    period_start_date,
    period_end_date,
    period_label,
    CAST(actual_inquiries AS INT64) AS actual_inquiries,
    CAST(validated_moderate_inquiries AS INT64) AS validated_moderate_inquiries,
    CAST(booking_count AS INT64) AS booking_count,
    moderate_rate,
    booking_per_moderate_rate,
    conversion_rate,
    is_selected_four_cs,
    comparison_group,
    'frozen_pdf_cards' AS data_freshness_mode,
    FALSE AS is_live_continuation,
    source_note
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_pdf_cards_agent_daily_2026_07_29`
  WHERE report_date <= DATE '2026-07-28'
),
live_continuation AS (
  SELECT
    DATE '2026-07-29' AS snapshot_date,
    DATETIME '2026-07-28 22:38:00' AS observation_cutoff_at,
    CASE
      WHEN reporting_lane = 'Taira (Chatbot/JCo)' THEN 'chatbot_performance'
      ELSE 'human_cs_conversion'
    END AS report_section,
    reporting_lane AS agent_name,
    report_date,
    report_month,
    DATE_TRUNC(report_date, WEEK(MONDAY)) AS period_start_date,
    DATE_ADD(DATE_TRUNC(report_date, WEEK(MONDAY)), INTERVAL 6 DAY) AS period_end_date,
    FORMAT_DATE('%b %-d', DATE_TRUNC(report_date, WEEK(MONDAY)))
      || '-' ||
      FORMAT_DATE('%-d', DATE_ADD(DATE_TRUNC(report_date, WEEK(MONDAY)), INTERVAL 6 DAY)) AS period_label,
    actual_inquiries,
    validated_moderate_inquiries,
    traceable_qualifying_bookings AS booking_count,
    SAFE_DIVIDE(validated_moderate_inquiries, actual_inquiries) AS moderate_rate,
    SAFE_DIVIDE(traceable_qualifying_bookings, validated_moderate_inquiries) AS booking_per_moderate_rate,
    SAFE_DIVIDE(traceable_qualifying_bookings, actual_inquiries) AS conversion_rate,
    reporting_lane IN ('Aira L. Garcia', 'Rem Reyes', 'Rolyn Ang', 'Sarah') AS is_selected_four_cs,
    CASE
      WHEN reporting_lane = 'Taira (Chatbot/JCo)' THEN 'Taira'
      ELSE 'Four-CS'
    END AS comparison_group,
    'live_continuation' AS data_freshness_mode,
    TRUE AS is_live_continuation,
    'Live continuation after the frozen 2026-07-28 PDF-card cutoff. Uses warehouse-equivalent inquiry-date conversion logic from t_actual_inquiry_booking_conversion_daily.' AS source_note
  FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_daily`
  WHERE report_date >= DATE '2026-07-29'
    AND reporting_lane IN (
      'Aira L. Garcia',
      'Rem Reyes',
      'Rolyn Ang',
      'Sarah',
      'Taira (Chatbot/JCo)'
    )
)
SELECT * FROM frozen_history
UNION ALL
SELECT * FROM live_continuation;
