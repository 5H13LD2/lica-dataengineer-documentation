#standardSQL

-- CS-only headline validation against the new Gold table.
SELECT
  report_date,
  SUM(total_inquiries) AS cs_only_total_inquiries
FROM `gulong-chatbot-459723.gulong_reporting.cs_inquiries_breakdown_gold`
WHERE agent_group = 'cs_agent'
  AND report_date = DATE '2026-07-15'
GROUP BY report_date;

SELECT
  SUM(total_inquiries) AS cs_only_mtd_total_inquiries
FROM `gulong-chatbot-459723.gulong_reporting.cs_inquiries_breakdown_gold`
WHERE agent_group = 'cs_agent'
  AND report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-15';

-- Source-of-truth comparison from p_looker_agent_daily_conversion.
SELECT
  report_date,
  SUM(total_inquiries) AS source_of_truth_cs_only_total_inquiries
FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
WHERE agent_group = 'cs_agent'
  AND report_date = DATE '2026-07-15'
GROUP BY report_date;

SELECT
  SUM(total_inquiries) AS source_of_truth_cs_only_mtd_total_inquiries
FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
WHERE agent_group = 'cs_agent'
  AND report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-15';

-- Row-level consistency check on reporting dimensions and inquiry counts.
SELECT
  COALESCE(g.report_date, p.report_date) AS report_date,
  COALESCE(g.agent_group, p.agent_group) AS agent_group,
  COALESCE(g.agent_key, p.agent_key) AS agent_key,
  COALESCE(g.agent_name, p.agent_name) AS agent_name,
  g.total_inquiries AS gold_total_inquiries,
  p.total_inquiries AS p_looker_total_inquiries,
  g.total_cs_replied,
  g.avg_cs_response_minutes,
  g.median_cs_response_minutes,
  g.cs_reply_rate
FROM `gulong-chatbot-459723.gulong_reporting.cs_inquiries_breakdown_gold` g
FULL OUTER JOIN `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion` p
  ON p.report_date = g.report_date
 AND p.agent_group = g.agent_group
 AND p.agent_key = g.agent_key
 AND p.agent_name = g.agent_name
WHERE COALESCE(g.report_date, p.report_date) BETWEEN DATE '2026-07-01' AND DATE '2026-07-15'
  AND COALESCE(g.agent_group, p.agent_group) = 'cs_agent'
ORDER BY report_date, agent_name;

-- Operational metric spot check by reporting agent.
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
WHERE report_date = DATE '2026-07-15'
  AND agent_group = 'cs_agent'
ORDER BY agent_name;
