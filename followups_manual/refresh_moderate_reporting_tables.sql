-- =====================================================================
-- GULONG.PH — MODERATE REPORTING PHYSICAL TABLE REFRESH
-- Project: gulong-chatbot-459723
-- Dataset: gulong_reporting
--
-- Purpose:
--   Refresh the physical reporting tables that can go stale after the
--   upstream views advance.
--
-- When to run:
--   - after changes to `v_looker_first_reply_detail`
--   - after changes to follow-up matching logic
--   - when Looker Studio is pointed at the `t_` tables and new rows are
--     missing from the dashboard
--
-- Rolling-window behavior:
--   This script keeps historical rows outside the refresh window and only
--   rebuilds the recent slice from the live views, using the current
--   Manila date as the moving anchor.
--
--   Adjust `refresh_window_days` if you want a wider or narrower window.
--
-- Safe order:
--   1. t_moderate_followup_detail
--   2. t_moderate_followup_coverage
--   3. t_moderate_booking_reconstruction
-- =====================================================================

DECLARE refresh_window_days INT64 DEFAULT 30;
DECLARE refresh_start_date DATE DEFAULT DATE_SUB(
  CURRENT_DATE('Asia/Manila'),
  INTERVAL refresh_window_days DAY
);

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
CLUSTER BY followup_date AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
WHERE followup_date < refresh_start_date

UNION ALL

SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_detail`
WHERE followup_date >= refresh_start_date;


CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
CLUSTER BY moderate_report_date AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE moderate_report_date < refresh_start_date

UNION ALL

SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`
WHERE moderate_report_date >= refresh_start_date;


CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE booking_day < refresh_start_date

UNION ALL

SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`
WHERE booking_day >= refresh_start_date;


-- Optional QA
SELECT
  't_moderate_followup_detail' AS table_name,
  CAST(refresh_start_date AS STRING) AS refresh_start_date,
  MAX(followup_date) AS max_date,
  COUNT(*) AS row_count
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`

UNION ALL

SELECT
  't_moderate_followup_coverage' AS table_name,
  CAST(refresh_start_date AS STRING) AS refresh_start_date,
  MAX(moderate_report_date) AS max_date,
  COUNT(*) AS row_count
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`

UNION ALL

SELECT
  't_moderate_booking_reconstruction' AS table_name,
  CAST(refresh_start_date AS STRING) AS refresh_start_date,
  MAX(booking_day) AS max_date,
  COUNT(*) AS row_count
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`;
