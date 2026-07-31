#standardSQL

-- Frozen PDF-card source for the 2026-07-29 report pack.
-- This is intentionally separate from the live actual-inquiry conversion stack.
--
-- Use this when the dashboard must match the values printed in:
--   DT-2026-07-29_Updates.md
--
-- Scope:
-- - observation cutoff: 2026-07-28 22:38 Asia/Manila
-- - periods: Jul 1-7, Jul 8-14, Jul 15-21, Jul 22-28, Jul 1-28
-- - ownership: original inquiry owner
-- - report family: PDF card snapshot, not live warehouse MTD

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_pdf_cards_agent_conversion_2026_07_29`
AS
WITH rows AS (
  SELECT
    DATE '2026-07-29' AS snapshot_date,
    DATETIME '2026-07-28 22:38:00' AS observation_cutoff_at,
    'chatbot_performance' AS report_section,
    'agent' AS entity_type,
    'Taira (Chatbot/JCo)' AS entity_name,
    DATE '2026-07-01' AS period_start_date,
    DATE '2026-07-07' AS period_end_date,
    'Jul 1-7' AS period_label,
    647 AS actual_inquiries,
    110 AS validated_moderate_inquiries,
    0.1700 AS moderate_rate,
    9 AS booking_count,
    0.0818 AS booking_per_moderate_rate,
    0.0139 AS conversion_rate
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'chatbot_performance', 'agent', 'Taira (Chatbot/JCo)', DATE '2026-07-08', DATE '2026-07-14', 'Jul 8-14', 934, 183, 0.1959, 3, 0.0164, 0.0032
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'chatbot_performance', 'agent', 'Taira (Chatbot/JCo)', DATE '2026-07-15', DATE '2026-07-21', 'Jul 15-21', 972, 213, 0.2191, 13, 0.0610, 0.0134
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'chatbot_performance', 'agent', 'Taira (Chatbot/JCo)', DATE '2026-07-22', DATE '2026-07-28', 'Jul 22-28', 1117, 235, 0.2104, 12, 0.0511, 0.0107
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'chatbot_performance', 'agent', 'Taira (Chatbot/JCo)', DATE '2026-07-01', DATE '2026-07-28', 'Jul 1-28', 3670, 741, 0.2019, 37, 0.0499, 0.0101

  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Aira L. Garcia', DATE '2026-07-01', DATE '2026-07-07', 'Jul 1-7', 539, NULL, NULL, 9, NULL, 0.0167
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Aira L. Garcia', DATE '2026-07-08', DATE '2026-07-14', 'Jul 8-14', 647, NULL, NULL, 8, NULL, 0.0124
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Aira L. Garcia', DATE '2026-07-15', DATE '2026-07-21', 'Jul 15-21', 684, NULL, NULL, 7, NULL, 0.0102
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Aira L. Garcia', DATE '2026-07-22', DATE '2026-07-28', 'Jul 22-28', 666, NULL, NULL, 5, NULL, 0.0075
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Aira L. Garcia', DATE '2026-07-01', DATE '2026-07-28', 'Jul 1-28', 2536, NULL, NULL, 29, NULL, 0.0114

  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rem Reyes', DATE '2026-07-01', DATE '2026-07-07', 'Jul 1-7', 540, NULL, NULL, 6, NULL, 0.0111
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rem Reyes', DATE '2026-07-08', DATE '2026-07-14', 'Jul 8-14', 647, NULL, NULL, 9, NULL, 0.0139
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rem Reyes', DATE '2026-07-15', DATE '2026-07-21', 'Jul 15-21', 678, NULL, NULL, 7, NULL, 0.0103
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rem Reyes', DATE '2026-07-22', DATE '2026-07-28', 'Jul 22-28', 668, NULL, NULL, 5, NULL, 0.0075
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rem Reyes', DATE '2026-07-01', DATE '2026-07-28', 'Jul 1-28', 2533, NULL, NULL, 27, NULL, 0.0107

  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rolyn Ang', DATE '2026-07-01', DATE '2026-07-07', 'Jul 1-7', 325, NULL, NULL, 3, NULL, 0.0092
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rolyn Ang', DATE '2026-07-08', DATE '2026-07-14', 'Jul 8-14', 391, NULL, NULL, 2, NULL, 0.0051
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rolyn Ang', DATE '2026-07-15', DATE '2026-07-21', 'Jul 15-21', 463, NULL, NULL, 7, NULL, 0.0151
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rolyn Ang', DATE '2026-07-22', DATE '2026-07-28', 'Jul 22-28', 459, NULL, NULL, 3, NULL, 0.0065
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Rolyn Ang', DATE '2026-07-01', DATE '2026-07-28', 'Jul 1-28', 1638, NULL, NULL, 15, NULL, 0.0092

  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Sarah', DATE '2026-07-01', DATE '2026-07-07', 'Jul 1-7', 541, NULL, NULL, 5, NULL, 0.0092
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Sarah', DATE '2026-07-08', DATE '2026-07-14', 'Jul 8-14', 646, NULL, NULL, 11, NULL, 0.0170
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Sarah', DATE '2026-07-15', DATE '2026-07-21', 'Jul 15-21', 376, NULL, NULL, 3, NULL, 0.0080
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Sarah', DATE '2026-07-22', DATE '2026-07-28', 'Jul 22-28', 348, NULL, NULL, 1, NULL, 0.0029
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'agent', 'Sarah', DATE '2026-07-01', DATE '2026-07-28', 'Jul 1-28', 1911, NULL, NULL, 20, NULL, 0.0105

  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'team', 'Four-CS team', DATE '2026-07-01', DATE '2026-07-07', 'Jul 1-7', 1945, NULL, NULL, 23, NULL, 0.0118
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'team', 'Four-CS team', DATE '2026-07-08', DATE '2026-07-14', 'Jul 8-14', 2331, NULL, NULL, 30, NULL, 0.0129
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'team', 'Four-CS team', DATE '2026-07-15', DATE '2026-07-21', 'Jul 15-21', 2201, NULL, NULL, 24, NULL, 0.0109
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'team', 'Four-CS team', DATE '2026-07-22', DATE '2026-07-28', 'Jul 22-28', 2141, NULL, NULL, 14, NULL, 0.0065
  UNION ALL SELECT DATE '2026-07-29', DATETIME '2026-07-28 22:38:00', 'human_cs_conversion', 'team', 'Four-CS team', DATE '2026-07-01', DATE '2026-07-28', 'Jul 1-28', 8618, NULL, NULL, 91, NULL, 0.0106
)
SELECT
  snapshot_date,
  observation_cutoff_at,
  report_section,
  entity_type,
  entity_name,
  period_start_date,
  period_end_date,
  period_label,
  actual_inquiries,
  validated_moderate_inquiries,
  moderate_rate,
  booking_count,
  booking_per_moderate_rate,
  conversion_rate,
  CASE
    WHEN entity_name = 'Four-CS team' THEN 'CS Performance'
    WHEN entity_name = 'Taira (Chatbot/JCo)' THEN 'Taira Performance'
    ELSE entity_name
  END AS dashboard_card_name,
  'Frozen from DT-2026-07-29_Updates.md to match PDF cards exactly.' AS source_note
FROM rows;


CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_pdf_cards_agent_conversion_2026_07_29`
OPTIONS (
  description = "Looker-facing frozen snapshot that matches the 2026-07-29 PDF card totals exactly. Use this for PDF-aligned cards, not for live warehouse MTD reporting."
) AS
SELECT
  snapshot_date,
  observation_cutoff_at,
  report_section,
  entity_type,
  entity_name AS agent_name,
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
FROM `gulong-chatbot-459723.gulong_reporting.t_pdf_cards_agent_conversion_2026_07_29`;
