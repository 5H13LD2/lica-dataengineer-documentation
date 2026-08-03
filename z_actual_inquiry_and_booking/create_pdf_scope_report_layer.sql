#standardSQL
-- PDF-scope reporting layer for the 2026-07-29 report pack.

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_pdf_scope_chatbot_performance`
OPTIONS (
  description = "Frozen PDF-scope chatbot performance view sourced from the 2026-07-29 report pack snapshot."
) AS
SELECT
  snapshot_date,
  observation_cutoff_at,
  agent_name,
  dashboard_card_name,
  period_start_date,
  period_end_date,
  period_label,
  actual_inquiries,
  validated_moderate_inquiries,
  moderate_rate,
  booking_count,
  booking_per_moderate_rate,
  conversion_rate,
  source_note
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_pdf_cards_agent_conversion_2026_07_29`
WHERE report_section = 'chatbot_performance';

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_pdf_scope_taira_performance`
OPTIONS (
  description = "Frozen PDF-scope Taira-only performance view. Use this for exact PDF-aligned Taira numbers such as Jul 1-28 = 3,670 inquiries and 37 bookings."
) AS
SELECT
  snapshot_date,
  observation_cutoff_at,
  agent_name,
  dashboard_card_name,
  period_start_date,
  period_end_date,
  period_label,
  actual_inquiries,
  validated_moderate_inquiries,
  moderate_rate,
  booking_count,
  booking_per_moderate_rate,
  conversion_rate,
  ROUND(conversion_rate * 100, 2) AS conversion_rate_pct,
  source_note
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_pdf_cards_agent_conversion_2026_07_29`
WHERE report_section = 'chatbot_performance'
  AND agent_name = 'Taira (Chatbot/JCo)';
