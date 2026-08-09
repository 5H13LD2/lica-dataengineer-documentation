-- Manual full refresh for the moderate follow-up reporting tables.
-- Run these three statements in BigQuery when the Looker data source needs fresh rows.

-- STATEMENT 1
CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
CLUSTER BY followup_date AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_detail`;

-- STATEMENT 2
CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
CLUSTER BY moderate_report_date AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`;

-- STATEMENT 3
CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`;
