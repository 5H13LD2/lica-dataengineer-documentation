#standardSQL

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_resilient_inquiry_booking_fact`
OPTIONS (
  description = "Resilient inquiry-grain Looker fact view for actual inquiry-to-booking analysis. Includes cohort-age, backfill-maturity, and partial-day controls so dashboard filters recalculate safely without daily manual edits."
) AS
SELECT
  report_date,
  report_week,
  report_month,
  reporting_lane AS agent_name,
  business_unit,
  inquiry_key,
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
  validated_moderate,
  IF(validated_moderate, 'Yes', 'No') AS is_moderate,
  CAST(validated_moderate AS INT64) AS validated_moderate_count,
  first_moderate_at,
  first_moderate_day,
  first_moderate_source,
  chat_analysis_top_intent,
  moderate_evidence_sources,
  linked_order_count_all,
  qualifying_booking_count,
  converted_inquiry,
  IF(converted_inquiry, 'Yes', 'No') AS is_booked,
  CAST(converted_inquiry AS INT64) AS converted_inquiry_count,
  first_qualifying_booking_at,
  first_qualifying_booking_day,
  latest_qualifying_booking_at,
  latest_qualifying_booking_day,
  DATE_DIFF(first_qualifying_booking_day, report_date, DAY) AS days_to_first_booking,
  qualifying_tire_quantity,
  qualifying_gross_sales_amount,
  qualifying_net_sales_amount,
  qualifying_total_cost_amount,
  qualifying_gross_profit_amount,
  linked_order_ids,
  qualifying_order_ids,
  CAST(1 AS INT64) AS actual_inquiry_count,
  CURRENT_DATE('Asia/Manila') AS as_of_date,
  CURRENT_DATETIME('Asia/Manila') AS as_of_datetime,
  DATE_DIFF(CURRENT_DATE('Asia/Manila'), report_date, DAY) AS cohort_age_days,
  report_date = CURRENT_DATE('Asia/Manila') AS is_current_partial_day,
  report_date < CURRENT_DATE('Asia/Manila') AS is_closed_reporting_day,
  report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 1 DAY) AS is_backfill_1d_mature,
  report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 3 DAY) AS is_backfill_3d_mature,
  report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 7 DAY) AS is_backfill_7d_mature,
  report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 14 DAY) AS is_backfill_14d_mature,
  report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 21 DAY) AS is_backfill_21d_mature,
  report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 28 DAY) AS is_backfill_28d_mature,
  CASE
    WHEN report_date = CURRENT_DATE('Asia/Manila') THEN 'current_partial_day'
    WHEN DATE_DIFF(CURRENT_DATE('Asia/Manila'), report_date, DAY) BETWEEN 1 AND 2 THEN 'backfill_1_to_2d'
    WHEN DATE_DIFF(CURRENT_DATE('Asia/Manila'), report_date, DAY) BETWEEN 3 AND 6 THEN 'backfill_3_to_6d'
    WHEN DATE_DIFF(CURRENT_DATE('Asia/Manila'), report_date, DAY) BETWEEN 7 AND 13 THEN 'backfill_7_to_13d'
    WHEN DATE_DIFF(CURRENT_DATE('Asia/Manila'), report_date, DAY) BETWEEN 14 AND 27 THEN 'backfill_14_to_27d'
    ELSE 'backfill_28d_plus'
  END AS backfill_maturity_bucket,
  CASE
    WHEN report_date = CURRENT_DATE('Asia/Manila') THEN 'Exclude from headline cards'
    WHEN report_date > DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 7 DAY) THEN 'Use with caution'
    WHEN report_date > DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 14 DAY) THEN 'Directional'
    ELSE 'Stable for management readout'
  END AS reporting_readiness_label,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 7 DAY) THEN 1 ELSE 0 END AS mature_7d_inquiry_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 14 DAY) THEN 1 ELSE 0 END AS mature_14d_inquiry_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 21 DAY) THEN 1 ELSE 0 END AS mature_21d_inquiry_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 28 DAY) THEN 1 ELSE 0 END AS mature_28d_inquiry_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 7 DAY) THEN qualifying_booking_count ELSE 0 END AS mature_7d_booking_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 14 DAY) THEN qualifying_booking_count ELSE 0 END AS mature_14d_booking_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 21 DAY) THEN qualifying_booking_count ELSE 0 END AS mature_21d_booking_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 28 DAY) THEN qualifying_booking_count ELSE 0 END AS mature_28d_booking_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 7 DAY) AND converted_inquiry THEN 1 ELSE 0 END AS mature_7d_converted_inquiry_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 14 DAY) AND converted_inquiry THEN 1 ELSE 0 END AS mature_14d_converted_inquiry_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 21 DAY) AND converted_inquiry THEN 1 ELSE 0 END AS mature_21d_converted_inquiry_count,
  CASE WHEN report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 28 DAY) AND converted_inquiry THEN 1 ELSE 0 END AS mature_28d_converted_inquiry_count,
  loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_detail`;

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_resilient_inquiry_booking_daily`
OPTIONS (
  description = "Backfill-aware daily summary view built from the resilient inquiry fact. Safe for Looker charts and scorecards when users need cohort-age filtering and stable rates."
) AS
SELECT
  report_date,
  report_week,
  report_month,
  agent_name,
  backfill_maturity_bucket,
  reporting_readiness_label,
  MAX(as_of_date) AS as_of_date,
  MAX(as_of_datetime) AS as_of_datetime,
  LOGICAL_OR(is_current_partial_day) AS is_current_partial_day,
  LOGICAL_AND(is_closed_reporting_day) AS is_closed_reporting_day,
  LOGICAL_AND(is_backfill_7d_mature) AS is_backfill_7d_mature,
  LOGICAL_AND(is_backfill_14d_mature) AS is_backfill_14d_mature,
  LOGICAL_AND(is_backfill_21d_mature) AS is_backfill_21d_mature,
  LOGICAL_AND(is_backfill_28d_mature) AS is_backfill_28d_mature,
  COUNT(*) AS actual_inquiries,
  SUM(validated_moderate_count) AS validated_moderate_inquiries,
  SAFE_DIVIDE(SUM(validated_moderate_count), COUNT(*)) AS moderate_rate,
  SUM(qualifying_booking_count) AS booking_count,
  SUM(converted_inquiry_count) AS distinct_converted_inquiries,
  SAFE_DIVIDE(SUM(qualifying_booking_count), COUNT(*)) AS conversion_rate,
  SAFE_DIVIDE(SUM(converted_inquiry_count), COUNT(*)) AS unique_inquiry_conversion_rate,
  SAFE_DIVIDE(SUM(qualifying_booking_count), NULLIF(SUM(validated_moderate_count), 0)) AS booking_per_moderate_rate,
  SUM(qualifying_tire_quantity) AS qualifying_tire_quantity,
  SUM(qualifying_gross_sales_amount) AS booking_revenue,
  SUM(qualifying_net_sales_amount) AS qualifying_net_sales_amount,
  SUM(qualifying_total_cost_amount) AS qualifying_total_cost_amount,
  SUM(qualifying_gross_profit_amount) AS qualifying_gross_profit_amount,
  SUM(mature_7d_inquiry_count) AS mature_7d_inquiries,
  SUM(mature_14d_inquiry_count) AS mature_14d_inquiries,
  SUM(mature_21d_inquiry_count) AS mature_21d_inquiries,
  SUM(mature_28d_inquiry_count) AS mature_28d_inquiries,
  SUM(mature_7d_booking_count) AS mature_7d_bookings,
  SUM(mature_14d_booking_count) AS mature_14d_bookings,
  SUM(mature_21d_booking_count) AS mature_21d_bookings,
  SUM(mature_28d_booking_count) AS mature_28d_bookings,
  SAFE_DIVIDE(SUM(mature_7d_booking_count), NULLIF(SUM(mature_7d_inquiry_count), 0)) AS mature_7d_conversion_rate,
  SAFE_DIVIDE(SUM(mature_14d_booking_count), NULLIF(SUM(mature_14d_inquiry_count), 0)) AS mature_14d_conversion_rate,
  SAFE_DIVIDE(SUM(mature_21d_booking_count), NULLIF(SUM(mature_21d_inquiry_count), 0)) AS mature_21d_conversion_rate,
  SAFE_DIVIDE(SUM(mature_28d_booking_count), NULLIF(SUM(mature_28d_inquiry_count), 0)) AS mature_28d_conversion_rate,
  MAX(loaded_at) AS loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_resilient_inquiry_booking_fact`
GROUP BY report_date, report_week, report_month, agent_name, backfill_maturity_bucket, reporting_readiness_label;

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_resilient_inquiry_booking_monthly`
OPTIONS (
  description = "Backfill-aware monthly summary view built from the resilient inquiry fact. Use this for management reporting that must survive Looker filters and late-arriving bookings."
) AS
SELECT
  report_month,
  agent_name,
  MAX(as_of_date) AS as_of_date,
  MAX(as_of_datetime) AS as_of_datetime,
  COUNT(*) AS actual_inquiries,
  SUM(validated_moderate_count) AS validated_moderate_inquiries,
  SAFE_DIVIDE(SUM(validated_moderate_count), COUNT(*)) AS moderate_rate,
  SUM(qualifying_booking_count) AS booking_count,
  SUM(converted_inquiry_count) AS distinct_converted_inquiries,
  SAFE_DIVIDE(SUM(qualifying_booking_count), COUNT(*)) AS conversion_rate,
  SAFE_DIVIDE(SUM(converted_inquiry_count), COUNT(*)) AS unique_inquiry_conversion_rate,
  SAFE_DIVIDE(SUM(qualifying_booking_count), NULLIF(SUM(validated_moderate_count), 0)) AS booking_per_moderate_rate,
  SUM(qualifying_tire_quantity) AS qualifying_tire_quantity,
  SUM(qualifying_gross_sales_amount) AS booking_revenue,
  SUM(qualifying_net_sales_amount) AS qualifying_net_sales_amount,
  SUM(qualifying_total_cost_amount) AS qualifying_total_cost_amount,
  SUM(qualifying_gross_profit_amount) AS qualifying_gross_profit_amount,
  SUM(mature_7d_inquiry_count) AS mature_7d_inquiries,
  SUM(mature_14d_inquiry_count) AS mature_14d_inquiries,
  SUM(mature_21d_inquiry_count) AS mature_21d_inquiries,
  SUM(mature_28d_inquiry_count) AS mature_28d_inquiries,
  SUM(mature_7d_booking_count) AS mature_7d_bookings,
  SUM(mature_14d_booking_count) AS mature_14d_bookings,
  SUM(mature_21d_booking_count) AS mature_21d_bookings,
  SUM(mature_28d_booking_count) AS mature_28d_bookings,
  SAFE_DIVIDE(SUM(mature_7d_booking_count), NULLIF(SUM(mature_7d_inquiry_count), 0)) AS mature_7d_conversion_rate,
  SAFE_DIVIDE(SUM(mature_14d_booking_count), NULLIF(SUM(mature_14d_inquiry_count), 0)) AS mature_14d_conversion_rate,
  SAFE_DIVIDE(SUM(mature_21d_booking_count), NULLIF(SUM(mature_21d_inquiry_count), 0)) AS mature_21d_conversion_rate,
  SAFE_DIVIDE(SUM(mature_28d_booking_count), NULLIF(SUM(mature_28d_inquiry_count), 0)) AS mature_28d_conversion_rate,
  MAX(loaded_at) AS loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_resilient_inquiry_booking_fact`
GROUP BY report_month, agent_name;
