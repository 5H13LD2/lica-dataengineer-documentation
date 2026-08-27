#standardSQL
/*
  Ready-to-run summaries for CS inquiries using the existing daily-grain gold table.
  All date logic uses Asia/Manila to match reporting.
*/

WITH cs_daily AS (
  SELECT
    report_date,
    agent_group,
    agent_key,
    agent_name,
    total_inquiries,
    total_cs_replied,
    avg_cs_response_minutes,
    median_cs_response_minutes,
    cs_reply_rate
  FROM `gulong-chatbot-459723.gulong_reporting.cs_inquiries_breakdown_gold`
  WHERE agent_group = 'cs_agent'
),

windowed AS (
  SELECT
    CASE
      WHEN report_date = CURRENT_DATE('Asia/Manila') THEN 'today'
      WHEN report_date BETWEEN DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 4 DAY)
        AND CURRENT_DATE('Asia/Manila') THEN 'last_5_days'
      WHEN report_date BETWEEN DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 6 DAY)
        AND CURRENT_DATE('Asia/Manila') THEN 'last_7_days'
      WHEN report_date BETWEEN DATE_TRUNC(CURRENT_DATE('Asia/Manila'), MONTH)
        AND CURRENT_DATE('Asia/Manila') THEN 'month_to_date'
      ELSE NULL
    END AS date_bucket,
    report_date,
    agent_key,
    agent_name,
    total_inquiries,
    total_cs_replied,
    avg_cs_response_minutes,
    median_cs_response_minutes
  FROM cs_daily
)

SELECT
  date_bucket,
  agent_key,
  agent_name,
  COUNT(DISTINCT report_date) AS covered_days,
  SUM(total_inquiries) AS total_inquiries,
  SUM(total_cs_replied) AS total_cs_replied,
  SAFE_DIVIDE(SUM(total_cs_replied), SUM(total_inquiries)) AS cs_reply_rate,
  AVG(avg_cs_response_minutes) AS avg_cs_response_minutes,
  APPROX_QUANTILES(median_cs_response_minutes, 100)[OFFSET(50)] AS median_cs_response_minutes
FROM windowed
WHERE date_bucket IS NOT NULL
GROUP BY date_bucket, agent_key, agent_name
ORDER BY
  CASE date_bucket
    WHEN 'today' THEN 1
    WHEN 'last_5_days' THEN 2
    WHEN 'last_7_days' THEN 3
    WHEN 'month_to_date' THEN 4
    ELSE 99
  END,
  total_inquiries DESC,
  agent_name;
