-- t_moderate_followup audit queries
-- Date: 2026-07-28
--
-- Purpose:
-- 1. Prove whether follow-up counts are stale or truly unchanged
-- 2. Rebuild the follow-up pipeline
-- 3. Reconcile against v_looker_first_reply_detail
-- 4. Validate booking linkage against t_moderate_booking_reconstruction


-- =====================================================================
-- A. Source vs downstream freshness checks
-- =====================================================================

SELECT
  MAX(followup_date) AS max_detail_followup_date,
  COUNT(*) AS detail_rows
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`;

SELECT
  MAX(report_date) AS max_source_followup_date,
  COUNT(*) AS source_rows_on_max_date
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail`
WHERE report_date = (
  SELECT MAX(report_date)
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail`
);

SELECT
  MAX(moderate_report_date) AS max_coverage_moderate_date,
  MAX(first_followup_date) AS max_coverage_first_followup_date,
  COUNTIF(followup_count > 0) AS sessions_with_any_followup
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`;

SELECT
  COUNT(*) AS source_followups_27_28
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail`
WHERE report_date BETWEEN DATE '2026-07-27' AND DATE '2026-07-28';


-- =====================================================================
-- B. Rebuild statements used
-- =====================================================================

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_detail`
OPTIONS (
  description = "One row per TRUE CS follow-up matched to a replied moderate-intent session. GRAIN: silver_session_id + followup_at. BASE COHORT: v_looker_first_reply_detail where reply_status = 'Has CS Reply'. MATCH RULE: same manychat_id, followup_at > first_cs_reply_at, followup_date <= moderate_report_date + 7 days, then each follow-up is attributed to the most recent prior replied moderate for that manychat_id. Use this table for event-level follow-up analysis. Use COUNT_DISTINCT(attributed_order_id) for booking counts. Use t_moderate_followup_coverage for the moderate denominator and NO CS FOLLOWUP reporting."
)
AS
WITH replied_moderates AS (
  SELECT
    report_date AS moderate_report_date,
    DATE_TRUNC(report_date, WEEK(MONDAY)) AS moderate_week,
    DATE_TRUNC(report_date, MONTH)        AS moderate_month,
    silver_session_id,
    manychat_id,
    user_name AS moderate_user_name,
    contact_number,
    reply_agent_name,
    LOWER(TRIM(reply_agent_name)) AS reply_agent_name_norm,
    first_cs_reply_at,
    minutes_to_first_reply
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE reply_status = 'Has CS Reply'
    AND manychat_id IS NOT NULL
),
followups AS (
  SELECT
    report_date AS followup_date,
    manychat_id,
    agent_name AS followup_agent_name,
    LOWER(TRIM(agent_name)) AS followup_agent_name_norm,
    user_name AS followup_user_name,
    followup_at,
    followup_type,
    followup_text
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail`
),
matched_followups AS (
  SELECT
    m.moderate_report_date,
    m.moderate_week,
    m.moderate_month,
    m.silver_session_id,
    m.manychat_id,
    m.moderate_user_name,
    m.contact_number,
    m.reply_agent_name,
    m.reply_agent_name_norm,
    m.first_cs_reply_at,
    m.minutes_to_first_reply,
    f.followup_date,
    f.followup_agent_name,
    f.followup_agent_name_norm,
    f.followup_user_name,
    f.followup_at,
    f.followup_type,
    f.followup_text,
    DATE_DIFF(f.followup_date, m.moderate_report_date, DAY) AS days_from_moderate_to_followup,
    DATETIME_DIFF(f.followup_at, m.first_cs_reply_at, MINUTE) AS minutes_from_reply_to_followup
  FROM replied_moderates m
  JOIN followups f
    ON f.manychat_id = m.manychat_id
   AND f.followup_at > m.first_cs_reply_at
   AND f.followup_date <= DATE_ADD(m.moderate_report_date, INTERVAL 7 DAY)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY f.manychat_id, f.followup_at
    ORDER BY m.first_cs_reply_at DESC, m.silver_session_id DESC
  ) = 1
),
with_booking AS (
  SELECT
    mf.*,
    b.order_id,
    b.booking_at,
    b.booking_day,
    COUNT(b.order_id) OVER (
      PARTITION BY mf.silver_session_id, mf.followup_at
    ) AS raw_booking_count_within_14d
  FROM matched_followups mf
  LEFT JOIN `gulong-chatbot-459723.gulong_core.orders_booked` b
    ON b.manychat_user_id = mf.manychat_id
   AND b.booking_at >= mf.followup_at
   AND b.booking_day <= DATE_ADD(mf.followup_date, INTERVAL 14 DAY)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY mf.silver_session_id, mf.followup_at
    ORDER BY b.booking_at ASC, b.order_id ASC
  ) = 1
)
SELECT
  moderate_report_date,
  moderate_week,
  moderate_month,
  followup_date,
  DATE_TRUNC(followup_date, WEEK(MONDAY)) AS followup_week,
  DATE_TRUNC(followup_date, MONTH)        AS followup_month,
  silver_session_id,
  manychat_id,
  COALESCE(followup_user_name, moderate_user_name) AS user_name,
  contact_number,
  reply_agent_name,
  reply_agent_name_norm,
  followup_agent_name,
  followup_agent_name_norm,
  first_cs_reply_at,
  followup_at,
  booking_at,
  booking_day,
  followup_type,
  followup_text,
  days_from_moderate_to_followup,
  minutes_to_first_reply,
  minutes_from_reply_to_followup,
  DATE_DIFF(booking_day, followup_date, DAY) AS days_followup_to_booking,
  CASE
    WHEN minutes_from_reply_to_followup <= 240  THEN 'A. 0-4 hrs'
    WHEN minutes_from_reply_to_followup <= 1440 THEN 'B. 4-24 hrs'
    WHEN minutes_from_reply_to_followup <= 2880 THEN 'C. 24-48 hrs'
    ELSE 'D. 48+ hrs'
  END AS followup_speed_bucket,
  CASE
    WHEN order_id IS NOT NULL THEN 'Yes'
    ELSE 'No'
  END AS is_booked,
  COALESCE(contact_number, '-')              AS contact_display,
  COALESCE(CAST(booking_day AS STRING), '-') AS booking_day_display,
  COALESCE(order_id, '-')                    AS order_display,
  CAST(1 AS INT64) AS is_true_followup,
  CAST(days_from_moderate_to_followup = 0 AS INT64) AS is_same_day_followup,
  CAST(days_from_moderate_to_followup = 1 AS INT64) AS is_next_day_followup,
  CAST(1 AS INT64) AS row_count,
  CAST(1 AS INT64) AS followed_up_moderate_count,
  CAST(order_id IS NOT NULL AS INT64) AS booked_from_followup_count,
  CAST(raw_booking_count_within_14d AS INT64) AS booking_count_within_14d,
  order_id AS attributed_order_id,
  minutes_from_reply_to_followup AS followup_gap_minutes_true_only
FROM with_booking;

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
CLUSTER BY followup_date
AS SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_detail`;

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`
OPTIONS (
  description = "One row per moderate-intent session from v_looker_first_reply_detail. GRAIN: silver_session_id. BASE COHORT: all moderate sessions with manychat_id present. This is the source of truth for the moderate denominator, replied vs no-reply splits, WITH CS FOLLOWUP vs NO CS FOLLOWUP, total chatbot-cohort bookings, chatbot-only bookings, and booked-from-followup session counts. Use moderate_report_date as the primary date range dimension for coverage reporting."
)
AS
WITH moderates AS (
  SELECT
    report_date AS moderate_report_date,
    DATE_TRUNC(report_date, WEEK(MONDAY)) AS moderate_week,
    DATE_TRUNC(report_date, MONTH)        AS moderate_month,
    silver_session_id,
    manychat_id,
    user_name,
    contact_number,
    reply_status,
    reply_agent_name,
    LOWER(TRIM(reply_agent_name)) AS reply_agent_name_norm,
    first_customer_message_at,
    first_cs_reply_at,
    minutes_to_first_reply
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE manychat_id IS NOT NULL
),
followup_ranked AS (
  SELECT
    d.*,
    ROW_NUMBER() OVER (
      PARTITION BY d.silver_session_id
      ORDER BY d.followup_at, d.followup_agent_name, d.followup_type
    ) AS rn
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail` d
),
followup_rollup AS (
  SELECT
    silver_session_id,
    COUNT(*) AS followup_count,
    MIN(followup_at) AS first_followup_at,
    DATE(MIN(followup_at)) AS first_followup_date,
    MAX(followup_at) AS last_followup_at,
    COUNT(DISTINCT attributed_order_id) AS booking_count_from_followup,
    COUNTIF(attributed_order_id IS NOT NULL) AS followup_rows_with_booking,
    MIN(minutes_from_reply_to_followup) AS minutes_to_first_followup,
    ROUND(MIN(minutes_from_reply_to_followup) / 60, 2) AS hours_to_first_followup
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
  GROUP BY 1
),
official_bookings AS (
  SELECT
    order_id,
    booking_at,
    booking_day,
    manychat_user_id AS manychat_id,
    customer_name AS booking_customer_name,
    inquiry_silver_session_id,
    inquiry_day
  FROM `gulong-chatbot-459723.gulong_core.orders_booked`
  WHERE sales_reporting_agent_name = 'Chatbot/JCo'
    AND is_reportable_booked_order = TRUE
    AND manychat_user_id IS NOT NULL
),
matched_official_bookings AS (
  SELECT
    m.silver_session_id,
    b.order_id,
    b.booking_at,
    b.booking_day,
    b.booking_customer_name,
    CASE
      WHEN b.inquiry_silver_session_id = m.silver_session_id THEN 'EXACT INQUIRY SESSION'
      ELSE 'LATEST PRIOR MODERATE'
    END AS booking_match_rule,
    ROW_NUMBER() OVER (
      PARTITION BY b.order_id
      ORDER BY
        CASE WHEN b.inquiry_silver_session_id = m.silver_session_id THEN 0 ELSE 1 END,
        m.first_customer_message_at DESC,
        m.moderate_report_date DESC,
        m.silver_session_id DESC
    ) AS booking_match_rn
  FROM moderates m
  JOIN official_bookings b
    ON b.manychat_id = m.manychat_id
   AND (
     b.inquiry_silver_session_id = m.silver_session_id
     OR m.first_customer_message_at <= b.booking_at
   )
),
direct_booking_ranked AS (
  SELECT
    silver_session_id,
    order_id,
    booking_at,
    booking_day,
    booking_customer_name,
    booking_match_rule,
    ROW_NUMBER() OVER (
      PARTITION BY silver_session_id
      ORDER BY booking_at, order_id
    ) AS rn
  FROM matched_official_bookings
  WHERE booking_match_rn = 1
),
direct_booking_rollup AS (
  SELECT
    silver_session_id,
    COUNT(DISTINCT order_id) AS booking_count_total_chatbot,
    MIN(booking_at) AS first_chatbot_booking_at,
    DATE(MIN(booking_at)) AS first_chatbot_booking_date,
    COUNTIF(booking_match_rule = 'EXACT INQUIRY SESSION') AS exact_session_booking_count,
    COUNTIF(booking_match_rule = 'LATEST PRIOR MODERATE') AS fallback_prior_moderate_booking_count
  FROM direct_booking_ranked
  GROUP BY 1
),
first_direct_booking_dim AS (
  SELECT
    silver_session_id,
    order_id AS first_chatbot_order_id,
    booking_customer_name AS first_chatbot_booking_customer_name,
    booking_match_rule AS first_chatbot_booking_match_rule
  FROM direct_booking_ranked
  WHERE rn = 1
),
first_followup_dim AS (
  SELECT
    silver_session_id,
    followup_agent_name AS first_followup_agent_name,
    followup_agent_name_norm AS first_followup_agent_name_norm,
    followup_type AS first_followup_type,
    followup_text AS first_followup_text,
    followup_speed_bucket AS first_followup_speed_bucket,
    is_booked AS first_followup_is_booked,
    attributed_order_id AS first_attributed_order_id
  FROM followup_ranked
  WHERE rn = 1
)
SELECT
  m.moderate_report_date,
  m.moderate_week,
  m.moderate_month,
  m.silver_session_id,
  m.manychat_id,
  m.user_name,
  m.contact_number,
  m.reply_status,
  m.reply_agent_name,
  m.reply_agent_name_norm,
  m.first_customer_message_at,
  m.first_cs_reply_at,
  m.minutes_to_first_reply,
  db.first_chatbot_booking_date,
  db.first_chatbot_booking_at,
  bd.first_chatbot_order_id,
  bd.first_chatbot_booking_customer_name,
  bd.first_chatbot_booking_match_rule,
  fu.first_followup_date,
  fu.first_followup_at,
  fu.last_followup_at,
  fr.first_followup_agent_name,
  fr.first_followup_agent_name_norm,
  fr.first_followup_type,
  fr.first_followup_text,
  fr.first_followup_speed_bucket,
  fr.first_followup_is_booked,
  fr.first_attributed_order_id,
  COALESCE(db.booking_count_total_chatbot, 0) AS booking_count_total_chatbot,
  COALESCE(db.exact_session_booking_count, 0) AS exact_session_booking_count,
  COALESCE(db.fallback_prior_moderate_booking_count, 0) AS fallback_prior_moderate_booking_count,
  GREATEST(
    COALESCE(db.booking_count_total_chatbot, 0) - COALESCE(fu.booking_count_from_followup, 0),
    0
  ) AS booking_count_chatbot_only,
  COALESCE(fu.followup_count, 0) AS followup_count,
  COALESCE(fu.booking_count_from_followup, 0) AS booking_count_from_followup,
  COALESCE(fu.followup_rows_with_booking, 0) AS followup_rows_with_booking,
  fu.minutes_to_first_followup,
  fu.hours_to_first_followup,
  CASE
    WHEN COALESCE(fu.followup_count, 0) > 0 THEN 'WITH CS FOLLOWUP'
    ELSE 'NO CS FOLLOWUP'
  END AS cs_followup_status,
  CASE
    WHEN COALESCE(fu.booking_count_from_followup, 0) > 0 THEN 'Yes'
    ELSE 'No'
  END AS booked_from_followup,
  CASE
    WHEN COALESCE(db.booking_count_total_chatbot, 0) > 0 THEN 'Yes'
    ELSE 'No'
  END AS booked_in_chatbot_cohort,
  CASE
    WHEN COALESCE(fu.booking_count_from_followup, 0) > 0 THEN 'CS-ASSISTED BOOKING'
    WHEN COALESCE(db.booking_count_total_chatbot, 0) > 0 THEN 'CHATBOT-ONLY BOOKING'
    ELSE 'NO BOOKING'
  END AS booking_ownership_status,
  CASE
    WHEN COALESCE(fu.booking_count_from_followup, 0) > 0 THEN 'CS Assisted'
    WHEN COALESCE(db.booking_count_total_chatbot, 0) > 0 THEN 'Chatbot Only'
    ELSE 'No Booking'
  END AS booking_owner_bucket,
  CAST(COALESCE(db.booking_count_total_chatbot, 0) > 0 AS INT64) AS was_booked_in_chatbot_cohort,
  CAST(COALESCE(fu.followup_count, 0) > 0 AS INT64) AS was_followed_up,
  CAST(COALESCE(fu.followup_count, 0) = 0 AS INT64) AS never_followed_up,
  CAST(COALESCE(fu.followup_count, 0) > 1 AS INT64) AS had_multiple_followups,
  CAST(
    COALESCE(db.booking_count_total_chatbot, 0) > 0
    AND COALESCE(fu.booking_count_from_followup, 0) = 0
    AS INT64
  ) AS was_booked_chatbot_only,
  CAST(COALESCE(fu.booking_count_from_followup, 0) > 0 AS INT64) AS was_booked_from_followup,
  CAST(m.moderate_report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 2 DAY) AS INT64)
    AS is_mature_cohort,
  CAST(1 AS INT64) AS moderate_session_count,
  CAST(m.reply_status = 'Has CS Reply' AS INT64) AS replied_session_count,
  CAST(m.reply_status = 'No CS Reply' AS INT64) AS no_reply_session_count,
  CAST(COALESCE(db.booking_count_total_chatbot, 0) > 0 AS INT64) AS chatbot_total_booked_session_count,
  CAST(
    COALESCE(db.booking_count_total_chatbot, 0) > 0
    AND COALESCE(fu.booking_count_from_followup, 0) = 0
    AS INT64
  ) AS chatbot_only_booked_session_count,
  CAST(COALESCE(fu.followup_count, 0) > 0 AS INT64) AS followed_up_session_count,
  CAST(
    m.reply_status = 'Has CS Reply' AND COALESCE(fu.followup_count, 0) = 0
    AS INT64
  ) AS no_followup_session_count,
  CAST(COALESCE(fu.booking_count_from_followup, 0) > 0 AS INT64) AS cs_assisted_booked_session_count,
  CAST(COALESCE(fu.booking_count_from_followup, 0) > 0 AS INT64) AS booked_session_count
FROM moderates m
LEFT JOIN direct_booking_rollup db
  USING (silver_session_id)
LEFT JOIN first_direct_booking_dim bd
  USING (silver_session_id)
LEFT JOIN followup_rollup fu
  USING (silver_session_id)
LEFT JOIN first_followup_dim fr
  USING (silver_session_id);

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
CLUSTER BY moderate_report_date
AS SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`;


-- =====================================================================
-- C. Denominator checks
-- =====================================================================

SELECT
  report_date,
  COUNT(*) AS replied_moderates
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
WHERE reply_status = 'Has CS Reply'
  AND manychat_id IS NOT NULL
  AND report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
GROUP BY 1
ORDER BY 1;

SELECT
  moderate_report_date,
  COUNT(*) AS coverage_rows,
  SUM(CASE WHEN reply_status = 'Has CS Reply' THEN 1 ELSE 0 END) AS coverage_replied_rows,
  SUM(moderate_session_count) AS moderate_sessions,
  SUM(replied_session_count) AS replied_sessions,
  SUM(followed_up_session_count) AS followed_up_sessions,
  SUM(no_followup_session_count) AS no_followup_sessions
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
GROUP BY 1
ORDER BY 1;

SELECT
  moderate_report_date,
  COUNTIF(reply_status = 'No CS Reply') AS no_reply_rows,
  COUNTIF(reply_status = 'Has CS Reply') AS replied_rows,
  COUNT(*) AS total_rows
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
GROUP BY 1
ORDER BY 1;

SELECT
  moderate_report_date,
  silver_session_id,
  manychat_id,
  user_name,
  reply_status,
  followup_count,
  first_followup_date,
  first_followup_at
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE moderate_report_date IN (DATE '2026-07-19', DATE '2026-07-26', DATE '2026-07-27')
  AND reply_status = 'No CS Reply'
ORDER BY moderate_report_date, silver_session_id;


-- =====================================================================
-- D. July 1 to July 27 rollups
-- =====================================================================

SELECT
  SUM(followed_up_session_count) AS with_followup_sessions,
  SUM(no_followup_session_count) AS no_followup_sessions,
  SUM(moderate_session_count) AS total_sessions
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
  AND is_mature_cohort = 1;

SELECT
  COUNT(*) AS followup_rows,
  COUNT(DISTINCT silver_session_id) AS followed_up_sessions,
  COUNT(DISTINCT manychat_id) AS followed_up_users
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
WHERE followup_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27';

SELECT
  moderate_report_date,
  SUM(followed_up_session_count) AS with_followup_sessions
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
  AND is_mature_cohort = 1
GROUP BY 1
ORDER BY 1;

SELECT
  followup_date,
  COUNT(*) AS followup_rows
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
WHERE followup_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
GROUP BY 1
ORDER BY 1;


-- =====================================================================
-- E. Booking validation against reconstruction
-- =====================================================================

SELECT
  SUM(CASE WHEN booking_count_from_followup > 0 THEN 1 ELSE 0 END) AS coverage_sessions_booked_from_followup,
  SUM(booking_count_from_followup) AS coverage_followup_booking_count
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
  AND is_mature_cohort = 1;

SELECT
  COUNT(*) AS detail_rows_with_booking,
  COUNT(DISTINCT attributed_order_id) AS distinct_followup_orders,
  COUNT(DISTINCT silver_session_id) AS sessions_with_followup_booking
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
  AND attributed_order_id IS NOT NULL;

SELECT
  COUNT(*) AS reconstruction_booked_rows,
  COUNT(DISTINCT order_id) AS distinct_orders,
  COUNT(DISTINCT silver_session_id) AS distinct_sessions,
  COUNTIF(booking_owner_bucket = 'CS Assisted') AS cs_assisted_rows,
  COUNTIF(booking_owner_bucket = 'Chatbot Only') AS chatbot_only_rows
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
  AND booked_order_count = 1;

WITH followup_orders AS (
  SELECT DISTINCT attributed_order_id AS order_id
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
  WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
    AND attributed_order_id IS NOT NULL
),
recon_orders AS (
  SELECT DISTINCT order_id
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
  WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
    AND booked_order_count = 1
)
SELECT
  COUNT(*) AS followup_orders,
  COUNTIF(r.order_id IS NOT NULL) AS orders_found_in_reconstruction,
  COUNTIF(r.order_id IS NULL) AS orders_missing_in_reconstruction
FROM followup_orders f
LEFT JOIN recon_orders r USING (order_id);

WITH coverage AS (
  SELECT
    silver_session_id,
    first_attributed_order_id AS order_id,
    moderate_report_date,
    first_followup_date,
    booking_count_from_followup,
    booking_owner_bucket
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
  WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
    AND booking_count_from_followup > 0
),
recon AS (
  SELECT
    silver_session_id,
    order_id,
    moderate_report_date,
    first_followup_date,
    booking_owner_bucket,
    booking_ownership_status
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
  WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
    AND booked_order_count = 1
)
SELECT
  c.order_id,
  c.silver_session_id AS coverage_session_id,
  c.moderate_report_date AS coverage_moderate_date,
  c.first_followup_date AS coverage_followup_date,
  c.booking_owner_bucket AS coverage_owner_bucket,
  r.silver_session_id AS recon_session_id,
  r.moderate_report_date AS recon_moderate_date,
  r.first_followup_date AS recon_followup_date,
  r.booking_owner_bucket AS recon_owner_bucket,
  r.booking_ownership_status AS recon_owner_status
FROM coverage c
LEFT JOIN recon r USING (order_id)
ORDER BY c.order_id;

SELECT
  order_id,
  silver_session_id,
  moderate_report_date,
  first_followup_date,
  booking_owner_bucket,
  booking_ownership_status,
  inquiry_silver_session_id,
  booking_day
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
  AND booked_order_count = 1
  AND booking_owner_bucket = 'CS Assisted'
ORDER BY booking_day, order_id;

SELECT
  attributed_order_id AS order_id,
  silver_session_id,
  moderate_report_date,
  followup_date,
  followup_at,
  followup_agent_name,
  followup_text
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
WHERE moderate_report_date BETWEEN DATE '2026-07-01' AND DATE '2026-07-27'
  AND attributed_order_id IS NOT NULL
ORDER BY followup_at, order_id;
