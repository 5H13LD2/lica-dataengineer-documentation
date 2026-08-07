#standardSQL
-- Replace DATE literals with a fixed historical period before release.

-- 1. Row parity by report_date.
SELECT
  report_date,
  COUNT(*) AS row_count,
  COUNT(DISTINCT manychat_id) AS manychat_ids
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
WHERE report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-07'
GROUP BY 1
ORDER BY 1;

SELECT
  report_date,
  COUNT(*) AS row_count,
  COUNT(DISTINCT manychat_id) AS manychat_ids
FROM `gulong-chatbot-459723.gulong_reporting.t_first_reply_detail`
WHERE report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-07'
GROUP BY 1
ORDER BY 1;

-- 2. Name/contact source parity.
SELECT
  report_date,
  name_source,
  contact_source,
  COUNT(*) AS row_count
FROM `gulong-chatbot-459723.gulong_reporting.t_first_reply_detail`
WHERE report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-07'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;

-- 3. SLA sanity checks.
SELECT
  COUNTIF(minutes_to_reply_sla < 0) AS negative_sla_rows,
  COUNTIF(minutes_to_reply_sla_today < 0) AS negative_same_day_sla_rows,
  COUNTIF(reply_status = 'Has CS Reply' AND first_cs_reply_at IS NULL) AS bad_reply_flag_rows
FROM `gulong-chatbot-459723.gulong_reporting.t_first_reply_detail`
WHERE report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-07';

-- 4. Dry-run target query template.
-- Run this with dry-run enabled in BigQuery UI or API and inspect totalBytesProcessed.
SELECT
  report_date,
  COUNT(*) AS detail_rows,
  SUM(reply_in_moderate_count) AS replied_rows,
  SUM(no_reply_session_count) AS no_reply_rows
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
WHERE report_date = DATE '2026-07-03'
GROUP BY 1;
