#standardSQL

-- Filterable daily PDF-cards layer.
-- This preserves the exact weekly and Jul 1-28 totals from
-- gulong_reporting.v_looker_pdf_cards_agent_conversion_2026_07_29,
-- while exposing day-level rows that Looker can filter on.
--
-- Important:
-- - Day-level values are allocated from the frozen weekly card totals.
-- - The intra-week daily shape comes from t_pdf_logic_agent_daily_2026_07_29.
-- - Rollups back to week or Jul 1-28 match the PDF cards exactly.

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_pdf_cards_agent_daily_2026_07_29`
AS
WITH frozen_weekly AS (
  SELECT
    snapshot_date,
    observation_cutoff_at,
    report_section,
    agent_name,
    period_start_date,
    period_end_date,
    period_label,
    actual_inquiries AS target_actual_inquiries,
    validated_moderate_inquiries AS target_validated_moderate_inquiries,
    booking_count AS target_booking_count,
    conversion_rate AS target_conversion_rate
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_pdf_cards_agent_conversion_2026_07_29`
  WHERE entity_type = 'agent'
    AND period_label IN ('Jul 1-7', 'Jul 8-14', 'Jul 15-21', 'Jul 22-28')
),
allocator_base AS (
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
    actual_inquiries,
    validated_moderate_inquiries,
    booking_count,
    distinct_converted_inquiries
  FROM `gulong-chatbot-459723.gulong_reporting.t_pdf_logic_agent_daily_2026_07_29`
),
daily_seed AS (
  SELECT
    f.snapshot_date,
    f.observation_cutoff_at,
    f.report_section,
    f.agent_name,
    a.report_date,
    a.report_month,
    f.period_start_date,
    f.period_end_date,
    f.period_label,
    f.target_actual_inquiries,
    f.target_validated_moderate_inquiries,
    f.target_booking_count,
    f.target_conversion_rate,
    a.actual_inquiries AS base_actual_inquiries,
    a.validated_moderate_inquiries AS base_validated_moderate_inquiries,
    a.booking_count AS base_booking_count,
    a.distinct_converted_inquiries AS base_distinct_converted_inquiries
  FROM frozen_weekly f
  JOIN allocator_base a
    ON a.agent_name = f.agent_name
   AND a.period_start_date = f.period_start_date
   AND a.period_end_date = f.period_end_date
),
weekly_base_totals AS (
  SELECT
    agent_name,
    period_start_date,
    period_end_date,
    SUM(base_actual_inquiries) AS weekly_base_actual_inquiries,
    SUM(base_validated_moderate_inquiries) AS weekly_base_validated_moderate_inquiries,
    SUM(base_booking_count) AS weekly_base_booking_count
  FROM daily_seed
  GROUP BY agent_name, period_start_date, period_end_date
),
actual_inquiry_alloc AS (
  SELECT
    d.*,
    SAFE_DIVIDE(d.base_actual_inquiries, w.weekly_base_actual_inquiries) AS actual_ratio,
    FLOOR(d.target_actual_inquiries * SAFE_DIVIDE(d.base_actual_inquiries, w.weekly_base_actual_inquiries)) AS actual_floor,
    (d.target_actual_inquiries * SAFE_DIVIDE(d.base_actual_inquiries, w.weekly_base_actual_inquiries))
      - FLOOR(d.target_actual_inquiries * SAFE_DIVIDE(d.base_actual_inquiries, w.weekly_base_actual_inquiries)) AS actual_frac
  FROM daily_seed d
  JOIN weekly_base_totals w
    USING (agent_name, period_start_date, period_end_date)
),
actual_inquiry_ranked AS (
  SELECT
    *,
    target_actual_inquiries
      - SUM(actual_floor) OVER (PARTITION BY agent_name, period_start_date, period_end_date) AS actual_remainder,
    ROW_NUMBER() OVER (
      PARTITION BY agent_name, period_start_date, period_end_date
      ORDER BY actual_frac DESC, report_date
    ) AS actual_remainder_rank
  FROM actual_inquiry_alloc
),
actual_inquiry_final AS (
  SELECT
    *,
    actual_floor + IF(actual_remainder_rank <= actual_remainder, 1, 0) AS actual_inquiries_final
  FROM actual_inquiry_ranked
),
moderate_alloc AS (
  SELECT
    a.*,
    CASE
      WHEN target_validated_moderate_inquiries IS NULL THEN NULL
      ELSE SAFE_DIVIDE(base_validated_moderate_inquiries, weekly_base_validated_moderate_inquiries)
    END AS moderate_ratio,
    CASE
      WHEN target_validated_moderate_inquiries IS NULL THEN NULL
      ELSE FLOOR(target_validated_moderate_inquiries * SAFE_DIVIDE(base_validated_moderate_inquiries, weekly_base_validated_moderate_inquiries))
    END AS moderate_floor,
    CASE
      WHEN target_validated_moderate_inquiries IS NULL THEN NULL
      ELSE (target_validated_moderate_inquiries * SAFE_DIVIDE(base_validated_moderate_inquiries, weekly_base_validated_moderate_inquiries))
        - FLOOR(target_validated_moderate_inquiries * SAFE_DIVIDE(base_validated_moderate_inquiries, weekly_base_validated_moderate_inquiries))
    END AS moderate_frac
  FROM actual_inquiry_final a
  JOIN weekly_base_totals w
    USING (agent_name, period_start_date, period_end_date)
),
moderate_ranked AS (
  SELECT
    *,
    CASE
      WHEN target_validated_moderate_inquiries IS NULL THEN NULL
      ELSE target_validated_moderate_inquiries
        - SUM(moderate_floor) OVER (PARTITION BY agent_name, period_start_date, period_end_date)
    END AS moderate_remainder,
    ROW_NUMBER() OVER (
      PARTITION BY agent_name, period_start_date, period_end_date
      ORDER BY moderate_frac DESC NULLS LAST, report_date
    ) AS moderate_remainder_rank
  FROM moderate_alloc
),
moderate_final AS (
  SELECT
    *,
    CASE
      WHEN target_validated_moderate_inquiries IS NULL THEN NULL
      ELSE moderate_floor + IF(moderate_remainder_rank <= moderate_remainder, 1, 0)
    END AS validated_moderate_inquiries_final
  FROM moderate_ranked
),
booking_alloc AS (
  SELECT
    m.*,
    SAFE_DIVIDE(base_booking_count, weekly_base_booking_count) AS booking_ratio,
    FLOOR(target_booking_count * SAFE_DIVIDE(base_booking_count, weekly_base_booking_count)) AS booking_floor,
    (target_booking_count * SAFE_DIVIDE(base_booking_count, weekly_base_booking_count))
      - FLOOR(target_booking_count * SAFE_DIVIDE(base_booking_count, weekly_base_booking_count)) AS booking_frac
  FROM moderate_final m
  JOIN weekly_base_totals w
    USING (agent_name, period_start_date, period_end_date)
),
booking_ranked AS (
  SELECT
    *,
    target_booking_count
      - SUM(booking_floor) OVER (PARTITION BY agent_name, period_start_date, period_end_date) AS booking_remainder,
    ROW_NUMBER() OVER (
      PARTITION BY agent_name, period_start_date, period_end_date
      ORDER BY booking_frac DESC, report_date
    ) AS booking_remainder_rank
  FROM booking_alloc
),
booking_final AS (
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
    actual_inquiries_final AS actual_inquiries,
    validated_moderate_inquiries_final AS validated_moderate_inquiries,
    booking_floor + IF(booking_remainder_rank <= booking_remainder, 1, 0) AS booking_count
  FROM booking_ranked
)
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
  actual_inquiries,
  validated_moderate_inquiries,
  booking_count,
  SAFE_DIVIDE(validated_moderate_inquiries, actual_inquiries) AS moderate_rate,
  SAFE_DIVIDE(booking_count, validated_moderate_inquiries) AS booking_per_moderate_rate,
  SAFE_DIVIDE(booking_count, actual_inquiries) AS conversion_rate,
  agent_name IN ('Aira L. Garcia', 'Rem Reyes', 'Rolyn Ang', 'Sarah') AS is_selected_four_cs,
  CASE
    WHEN agent_name = 'Taira (Chatbot/JCo)' THEN 'Taira'
    ELSE 'Four-CS'
  END AS comparison_group,
  'Daily filterable layer allocated from frozen PDF card weekly totals. Rolls back up to the PDF-card numbers exactly.' AS source_note
FROM booking_final;


CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_pdf_cards_agent_daily_2026_07_29`
OPTIONS (
  description = "Looker-facing daily PDF-card layer. Daily values are allocated from the frozen weekly card totals so date and agent filters work, while Jul 1-7 / 8-14 / 15-21 / 22-28 / 1-28 rollups match the PDF cards exactly."
) AS
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
  actual_inquiries,
  validated_moderate_inquiries,
  booking_count,
  moderate_rate,
  booking_per_moderate_rate,
  conversion_rate,
  is_selected_four_cs,
  comparison_group,
  source_note
FROM `gulong-chatbot-459723.gulong_reporting.t_pdf_cards_agent_daily_2026_07_29`;
