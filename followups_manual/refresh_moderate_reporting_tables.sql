-- Recreate the refresh procedure with a direct full rebuild from the reporting views.
-- This avoids the stale rolling-window path and the broken booking reconstruction logic.

CREATE OR REPLACE PROCEDURE `gulong-chatbot-459723.gulong_reporting.refresh_moderate_reporting_tables`()
BEGIN
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
END;
