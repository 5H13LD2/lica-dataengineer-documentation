#standardSQL

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_actual_inquiry_booking_conversion_detail`
OPTIONS (
  description = "Looker-facing inquiry-grain detail view for actual inquiry booking conversion. Source of truth is t_actual_inquiry_booking_conversion_detail. Use for drill-down tables, booked inquiry lists, and agent-level investigation."
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
  loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_detail`;


CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_actual_inquiry_booking_conversion_daily`
OPTIONS (
  description = "Looker-facing daily actual inquiry booking conversion summary by reporting lane. Source of truth is t_actual_inquiry_booking_conversion_daily."
) AS
SELECT
  report_date,
  report_week,
  report_month,
  reporting_lane AS agent_name,
  actual_inquiries,
  validated_moderate_inquiries,
  moderate_rate,
  traceable_qualifying_bookings AS booking_count,
  distinct_converted_inquiries,
  booking_per_inquiry_rate AS conversion_rate,
  unique_inquiry_conversion_rate,
  booking_per_moderate_rate,
  conversion_display,
  qualifying_tire_quantity,
  qualifying_gross_sales_amount AS booking_revenue,
  qualifying_net_sales_amount,
  qualifying_total_cost_amount,
  qualifying_gross_profit_amount,
  loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_daily`;


CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_actual_inquiry_booking_conversion_monthly`
OPTIONS (
  description = "Looker-facing monthly actual inquiry booking conversion summary by reporting lane. Source of truth is t_actual_inquiry_booking_conversion_monthly."
) AS
SELECT
  report_month,
  reporting_lane AS agent_name,
  actual_inquiries,
  validated_moderate_inquiries,
  moderate_rate,
  traceable_qualifying_bookings AS booking_count,
  distinct_converted_inquiries,
  booking_per_inquiry_rate AS conversion_rate,
  unique_inquiry_conversion_rate,
  booking_per_moderate_rate,
  conversion_display,
  qualifying_tire_quantity,
  qualifying_gross_sales_amount AS booking_revenue,
  qualifying_net_sales_amount,
  qualifying_total_cost_amount,
  qualifying_gross_profit_amount,
  loaded_at
FROM `gulong-chatbot-459723.gulong_reporting.t_actual_inquiry_booking_conversion_monthly`;
