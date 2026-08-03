-- =====================================================================
-- GULONG.PH — MODERATE-INTENT FOLLOW-UP REPORTING LAYER
-- Project: gulong-chatbot-459723
-- Dataset: gulong_reporting
--
-- Canonical source of truth for the moderate follow-up pipeline.
-- Maintain this file only.
--
-- Full rebuild order:
--   0. VIEW   v_looker_cs_followup_detail
--   1. VIEW   v_looker_moderate_followup_detail
--   2. TABLE  t_moderate_followup_detail
--   3. VIEW   v_looker_moderate_followup_coverage
--   4. TABLE  t_moderate_followup_coverage
--   5. VIEW   v_looker_moderate_followup_booking_summary
--   6. VIEW   v_looker_moderate_followup_booking_detail
--   7. VIEW   v_looker_moderate_booking_reconstruction
--   8. TABLE  t_moderate_booking_reconstruction
--
-- Minimal reruns:
--   - If only v_looker_first_reply_detail changed: rerun 1, 2, 3, 4, 5, 6, 7, 8
--   - If only follow-up phrase/counting logic changed: rerun 0, 1, 2, 3, 4, 5, 6, 7, 8
--   - If only coverage table is stale after upstream rebuild: rerun 3 and 4
--
-- Table statements are 2, 4, and 8.
-- =====================================================================


-- =====================================================================
-- STATEMENT 0 — SOURCE FOLLOW-UP VIEW
-- Grain: one row per qualifying follow-up message
--
-- Purpose:
--   Normalize agent follow-up phrases from ManyChat without per-user-day
--   dedupe. This is the source for agent-day follow-up activity counts.
-- =====================================================================

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail` AS
WITH followup_messages AS (
  SELECT
    DATE(TIMESTAMP(m.datetime, 'Asia/Manila'), 'Asia/Manila') AS report_date,
    DATE_TRUNC(DATE(TIMESTAMP(m.datetime, 'Asia/Manila'), 'Asia/Manila'), WEEK(MONDAY)) AS report_week,
    DATE_TRUNC(DATE(TIMESTAMP(m.datetime, 'Asia/Manila'), 'Asia/Manila'), MONTH) AS report_month,
    m.user_id AS manychat_id,
    COALESCE(NULLIF(u.user_name, ''), NULLIF(m.user_name, ''), CONCAT('manychat:', m.user_id)) AS user_name,
    m.sender AS agent_name,
    m.datetime AS followup_at,
    m.text_content AS followup_text,
    CASE
      WHEN REGEXP_CONTAINS(LOWER(m.text_content), r'\bproceed\b')
        OR REGEXP_CONTAINS(LOWER(m.text_content), r'would you like to proceed')
      THEN 'proceed_nudge'
      WHEN REGEXP_CONTAINS(LOWER(m.text_content), r'still interested')
      THEN 'still_interested'
      WHEN REGEXP_CONTAINS(LOWER(m.text_content), r'do you still need help with your inquiry')
        OR REGEXP_CONTAINS(LOWER(m.text_content), r'just checking')
        OR REGEXP_CONTAINS(LOWER(m.text_content), r'may napili na po kayong')
      THEN 'checking_in'
      ELSE NULL
    END AS followup_type
  FROM `gulong-chatbot-459723.manychat_data.messages` m
  LEFT JOIN `gulong-chatbot-459723.manychat_data.users_current` u
    ON u.business_unit = m.business_unit
   AND u.user_id = m.user_id
  WHERE m.business_unit = 'gulong'
    AND m.role = 'agent'
    AND m.type = 'msgout_lc'
    AND m.datetime >= DATETIME '2026-06-01 00:00:00'
    AND m.text_content IS NOT NULL
    AND m.sender IN (
      'sarah gulongph',
      'Aira L. Garcia',
      'Rem Reyes',
      'Becca Armstrng',
      'Atossa Saremi',
      'Rolyn Ang'
    )
    AND (
      REGEXP_CONTAINS(LOWER(m.text_content), r'still interested')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'do you still need help with your inquiry')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'just checking')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'may napili na po kayong')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'\bproceed\b')
      OR REGEXP_CONTAINS(LOWER(m.text_content), r'would you like to proceed')
    )
)
SELECT
  report_date,
  report_week,
  report_month,
  manychat_id,
  user_name,
  agent_name,
  followup_at,
  followup_type,
  followup_text,
  CAST(1 AS INT64) AS followup_count
FROM followup_messages
WHERE followup_type IS NOT NULL;


-- =====================================================================
-- STATEMENT 1 — TRUE FOLLOW-UP DETAIL VIEW
-- Grain: silver_session_id + followup_at
--
-- Purpose:
--   Event-level source for "which follow-ups happened" and
--   "which follow-ups converted to bookings".
--
-- Important:
--   This view EXCLUDES the first CS reply itself. Only true follow-ups
--   remain, so there are no synthetic zero rows here.
-- =====================================================================

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_detail`
OPTIONS (
  description = "One row per TRUE CS follow-up matched to a replied moderate-intent session. GRAIN: silver_session_id + followup_at. BASE COHORT: v_looker_first_reply_detail where reply_status = 'Has CS Reply'. MATCH RULE: same manychat_id, followup_at >= first_cs_reply_at, followup_date <= moderate_report_date + 7 days, then each follow-up is attributed to the most recent prior replied moderate for that manychat_id. Use this table for event-level follow-up analysis. Use COUNT_DISTINCT(attributed_order_id) for booking counts. Use t_moderate_followup_coverage for the moderate denominator and NO CS FOLLOWUP reporting."
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
   AND f.followup_at >= m.first_cs_reply_at
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
  -- ---------- cohort dates ----------
  moderate_report_date,
  moderate_week,
  moderate_month,

  -- ---------- follow-up dates ----------
  followup_date AS report_date,
  followup_date,
  DATE_TRUNC(followup_date, WEEK(MONDAY)) AS followup_week,
  DATE_TRUNC(followup_date, MONTH)        AS followup_month,

  -- ---------- identity ----------
  silver_session_id,
  manychat_id,
  COALESCE(followup_user_name, moderate_user_name) AS user_name,
  contact_number,

  -- ---------- reply / follow-up ownership ----------
  reply_agent_name,
  reply_agent_name_norm,
  followup_agent_name,
  followup_agent_name_norm,

  -- ---------- timestamps ----------
  first_cs_reply_at,
  followup_at,
  booking_at,
  booking_day,

  -- ---------- attributes ----------
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
  COALESCE(contact_number, '—')              AS contact_display,
  COALESCE(CAST(booking_day AS STRING), '—') AS booking_day_display,
  COALESCE(order_id, '—')                    AS order_display,

  -- ---------- flags ----------
  CAST(1 AS INT64) AS is_true_followup,
  CAST(days_from_moderate_to_followup = 0 AS INT64) AS is_same_day_followup,
  CAST(days_from_moderate_to_followup = 1 AS INT64) AS is_next_day_followup,

  -- ---------- measures ----------
  CAST(1 AS INT64) AS row_count,
  CAST(1 AS INT64) AS followed_up_moderate_count,
  CAST(order_id IS NOT NULL AS INT64) AS booked_from_followup_count,
  CAST(raw_booking_count_within_14d AS INT64) AS booking_count_within_14d,
  order_id AS attributed_order_id,
  minutes_from_reply_to_followup AS followup_gap_minutes_true_only
FROM with_booking;


-- =====================================================================
-- STATEMENT 2 — DETAIL TABLE
-- =====================================================================

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
CLUSTER BY followup_date
AS SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_detail`;


-- =====================================================================
-- STATEMENT 3 — SESSION STATUS / COVERAGE VIEW
-- Grain: silver_session_id
--
-- Purpose:
--   One row per replied moderate session, including sessions that never
--   received any true follow-up.
--
-- Dependency note:
--   This view is the session-level denominator. If
--   v_looker_first_reply_detail is rebuilt or its reply logic changes,
--   rerun this statement and Statement 4 or the coverage table can go
--   stale versus the source view.
--
-- Current business note:
--   The denominator in this view inherits the cohort already selected by
--   v_looker_first_reply_detail. If that upstream view was updated to use
--   the official Chatbot/JCo row-level cohort basis, this coverage view
--   will inherit that denominator after rebuild.
--
-- Booking note:
--   booking_count_total_chatbot / first_chatbot_order_id are now rebuilt
--   from the official Chatbot/JCo booking universe in orders_booked
--   (sales_reporting_agent_name + is_reportable_booked_order), then
--   matched back to the nearest eligible moderate session.
--   This improves order-id coverage, but booking-day totals from official
--   reporting are still a different date basis from moderate_report_date.
-- =====================================================================

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
  m.moderate_report_date AS report_date,
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
  COALESCE(fr.first_followup_agent_name, 'NO FOLLOWUP') AS first_followup_agent_name,
  COALESCE(fr.first_followup_agent_name_norm, 'no followup') AS first_followup_agent_name_norm,
  COALESCE(fr.first_followup_type, 'NO FOLLOWUP') AS first_followup_type,
  COALESCE(fr.first_followup_text, 'NO FOLLOWUP') AS first_followup_text,
  COALESCE(fr.first_followup_speed_bucket, 'NO FOLLOWUP') AS first_followup_speed_bucket,
  CASE
    WHEN COALESCE(fu.followup_count, 0) = 0 THEN 'NO FOLLOWUP'
    ELSE COALESCE(fr.first_followup_is_booked, 'No')
  END AS first_followup_is_booked,
  CASE
    WHEN COALESCE(fu.followup_count, 0) = 0 THEN 'NO FOLLOWUP'
    ELSE COALESCE(fr.first_attributed_order_id, '—')
  END AS first_attributed_order_id,

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


-- =====================================================================
-- STATEMENT 4 — COVERAGE TABLE
-- =====================================================================

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
CLUSTER BY moderate_report_date
AS SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`;


-- =====================================================================
-- STATEMENT 5 — FOLLOW-UP BOOKING SUMMARY VIEW
-- Grain: grouped by followup_date + agent + type + cohort offsets
--
-- Purpose:
--   Fast summary for agent-day reporting such as:
--   - how many matched manychat_ids were followed up
--   - how many matched sessions were followed up
--   - how many of those followups booked within 14 days
-- =====================================================================

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_booking_summary` AS
WITH replied_moderates AS (
  SELECT
    report_date AS moderate_report_date,
    silver_session_id,
    manychat_id,
    first_cs_reply_at
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE reply_status = 'Has CS Reply'
    AND manychat_id IS NOT NULL
),
followups AS (
  SELECT
    report_date AS followup_date,
    manychat_id,
    followup_at,
    followup_type,
    agent_name AS followup_agent_name
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail`
),
matched_followups AS (
  SELECT * EXCEPT(match_rank)
  FROM (
    SELECT
      m.moderate_report_date,
      m.silver_session_id,
      m.manychat_id,
      f.followup_date,
      f.followup_at,
      f.followup_type,
      f.followup_agent_name,
      DATE_DIFF(f.followup_date, m.moderate_report_date, DAY) AS days_from_moderate_to_followup,
      DATE_DIFF(f.followup_date, DATE(m.first_cs_reply_at), DAY) AS days_from_reply_to_followup,
      ROW_NUMBER() OVER (
        PARTITION BY f.manychat_id, f.followup_at
        ORDER BY m.first_cs_reply_at DESC, m.silver_session_id DESC
      ) AS match_rank
    FROM replied_moderates m
    JOIN followups f
      ON f.manychat_id = m.manychat_id
     AND f.followup_at >= m.first_cs_reply_at
     AND f.followup_date <= DATE_ADD(m.moderate_report_date, INTERVAL 7 DAY)
  )
  WHERE match_rank = 1
),
first_booking AS (
  SELECT * EXCEPT(booking_rank)
  FROM (
    SELECT
      mf.silver_session_id,
      mf.followup_at,
      b.order_id,
      b.booking_day,
      ROW_NUMBER() OVER (
        PARTITION BY mf.silver_session_id, mf.followup_at
        ORDER BY b.booking_at ASC, b.order_id ASC
      ) AS booking_rank
    FROM matched_followups mf
    LEFT JOIN `gulong-chatbot-459723.gulong_core.orders_booked` b
      ON b.manychat_user_id = mf.manychat_id
     AND b.booking_at >= mf.followup_at
     AND b.booking_day <= DATE_ADD(mf.followup_date, INTERVAL 14 DAY)
  )
  WHERE booking_rank = 1
     OR order_id IS NULL
),
base AS (
  SELECT
    mf.moderate_report_date,
    mf.followup_date,
    mf.silver_session_id,
    mf.manychat_id,
    mf.followup_type,
    mf.followup_agent_name,
    mf.days_from_moderate_to_followup,
    mf.days_from_reply_to_followup,
    CAST(mf.days_from_moderate_to_followup = 1 AS INT64) AS is_next_day_followup,
    CAST(1 AS INT64) AS followups_from_moderate,
    CAST(fb.order_id IS NOT NULL AS INT64) AS bookings_from_followups
  FROM matched_followups mf
  LEFT JOIN first_booking fb
    ON fb.silver_session_id = mf.silver_session_id
   AND fb.followup_at = mf.followup_at
)
SELECT
  moderate_report_date,
  followup_date,
  followup_agent_name,
  followup_type,
  days_from_moderate_to_followup,
  days_from_reply_to_followup,
  is_next_day_followup,
  COUNT(DISTINCT manychat_id) AS matched_manychat_ids,
  COUNT(DISTINCT silver_session_id) AS matched_sessions,
  SUM(followups_from_moderate) AS followups_from_moderate,
  SUM(bookings_from_followups) AS bookings_from_followups,
  SAFE_DIVIDE(SUM(bookings_from_followups), SUM(followups_from_moderate)) AS booking_rate
FROM base
GROUP BY
  moderate_report_date,
  followup_date,
  followup_agent_name,
  followup_type,
  days_from_moderate_to_followup,
  days_from_reply_to_followup,
  is_next_day_followup;


-- =====================================================================
-- STATEMENT 6 — FOLLOW-UP BOOKING DETAIL VIEW
-- Grain: silver_session_id + followup_at
--
-- Purpose:
--   Row-level matched followup + booking detail for auditing which followup
--   messages booked.
-- =====================================================================

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_booking_detail` AS
WITH replied_moderates AS (
  SELECT
    report_date AS moderate_report_date,
    report_week AS moderate_report_week,
    report_month AS moderate_report_month,
    silver_session_id,
    manychat_id,
    user_name,
    contact_number,
    first_customer_message_at,
    first_moderate_at,
    moderate_tagged_at,
    first_cs_reply_at,
    first_cs_reply_sender,
    reply_agent_name
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE reply_status = 'Has CS Reply'
    AND manychat_id IS NOT NULL
),
followups AS (
  SELECT
    report_date AS followup_date,
    report_week AS followup_week,
    report_month AS followup_month,
    manychat_id,
    user_name AS followup_user_name,
    agent_name AS followup_agent_name,
    followup_at,
    followup_type,
    followup_text
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_cs_followup_detail`
),
matched_followups AS (
  SELECT * EXCEPT(match_rank)
  FROM (
    SELECT
      m.moderate_report_date,
      m.moderate_report_week,
      m.moderate_report_month,
      f.followup_date,
      f.followup_week,
      f.followup_month,
      m.silver_session_id,
      m.manychat_id,
      m.user_name,
      m.contact_number,
      m.first_customer_message_at,
      m.first_moderate_at,
      m.moderate_tagged_at,
      m.first_cs_reply_at,
      m.first_cs_reply_sender,
      m.reply_agent_name,
      f.followup_user_name,
      f.followup_agent_name,
      f.followup_at,
      f.followup_type,
      f.followup_text,
      DATE_DIFF(f.followup_date, m.moderate_report_date, DAY) AS days_from_moderate_to_followup,
      DATE_DIFF(f.followup_date, DATE(m.first_cs_reply_at), DAY) AS days_from_reply_to_followup,
      ROW_NUMBER() OVER (
        PARTITION BY f.manychat_id, f.followup_at
        ORDER BY m.first_cs_reply_at DESC, m.silver_session_id DESC
      ) AS match_rank
    FROM replied_moderates m
    JOIN followups f
      ON f.manychat_id = m.manychat_id
     AND f.followup_at >= m.first_cs_reply_at
     AND f.followup_date <= DATE_ADD(m.moderate_report_date, INTERVAL 7 DAY)
  )
  WHERE match_rank = 1
),
booking_candidates AS (
  SELECT
    mf.silver_session_id,
    mf.followup_at,
    b.order_id,
    b.booking_at,
    b.booking_day,
    b.customer_name AS booking_customer_name,
    b.net_sales_amount,
    b.gross_sales_amount,
    b.total_cost_amount,
    b.gross_profit_amount,
    b.quantity_int,
    b.canonical_order_brand,
    b.canonical_order_tire_size,
    b.installation_partner_name,
    b.appointment_at,
    b.appointment_day,
    b.booked_inclusion_reason,
    ROW_NUMBER() OVER (
      PARTITION BY mf.silver_session_id, mf.followup_at
      ORDER BY b.booking_at ASC, b.order_id ASC
    ) AS booking_rank,
    COUNT(b.order_id) OVER (
      PARTITION BY mf.silver_session_id, mf.followup_at
    ) AS booking_count_within_14d
  FROM matched_followups mf
  LEFT JOIN `gulong-chatbot-459723.gulong_core.orders_booked` b
    ON b.manychat_user_id = mf.manychat_id
   AND b.booking_at >= mf.followup_at
   AND b.booking_day <= DATE_ADD(mf.followup_date, INTERVAL 14 DAY)
),
first_booking AS (
  SELECT * EXCEPT(booking_rank)
  FROM booking_candidates
  WHERE booking_rank = 1
     OR order_id IS NULL
)
SELECT
  mf.moderate_report_date,
  mf.moderate_report_week,
  mf.moderate_report_month,
  mf.followup_date,
  mf.followup_week,
  mf.followup_month,
  mf.silver_session_id,
  mf.manychat_id,
  mf.user_name,
  mf.contact_number,
  mf.first_customer_message_at,
  mf.first_moderate_at,
  mf.moderate_tagged_at,
  mf.first_cs_reply_at,
  mf.first_cs_reply_sender,
  mf.reply_agent_name,
  mf.followup_user_name,
  mf.followup_agent_name,
  mf.followup_at,
  mf.followup_type,
  mf.followup_text,
  mf.days_from_moderate_to_followup,
  mf.days_from_reply_to_followup,
  CAST(mf.days_from_moderate_to_followup = 1 AS INT64) AS is_next_day_followup,
  fb.order_id,
  fb.booking_at,
  fb.booking_day,
  fb.booking_customer_name,
  fb.net_sales_amount,
  fb.gross_sales_amount,
  fb.total_cost_amount,
  fb.gross_profit_amount,
  fb.quantity_int,
  fb.canonical_order_brand,
  fb.canonical_order_tire_size,
  fb.installation_partner_name,
  fb.appointment_at,
  fb.appointment_day,
  fb.booked_inclusion_reason,
  IF(fb.order_id IS NOT NULL, 'Yes', 'No') AS is_booked,
  CAST(fb.order_id IS NOT NULL AS INT64) AS is_booked_flag,
  COALESCE(fb.booking_count_within_14d, 0) AS booking_count_within_14d,
  DATE_DIFF(fb.booking_day, mf.followup_date, DAY) AS days_from_followup_to_booking,
  CAST(1 AS INT64) AS followed_up_moderate_count
FROM matched_followups mf
LEFT JOIN first_booking fb
  ON fb.silver_session_id = mf.silver_session_id
 AND fb.followup_at = mf.followup_at;


-- =====================================================================
-- STATEMENT 7 — ORDER-LEVEL BOOKING RECONSTRUCTION VIEW
-- Grain: order_id
--
-- Purpose:
--   One row per official Chatbot/JCo booked order from orders_booked,
--   matched back to the nearest eligible moderate session.
--
-- Use this when the business question starts from source-of-truth booking
-- counts / order ids and needs to know which moderate session they trace to.
-- Date range dimension for booking-side reporting should be booking_day.
-- =====================================================================

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`
OPTIONS (
  description = "One row per official Chatbot/JCo booked order from orders_booked, matched back to the nearest eligible moderate session from v_looker_first_reply_detail. GRAIN: order_id. BOOKING SOURCE: orders_booked where sales_reporting_agent_name = 'Chatbot/JCo' and is_reportable_booked_order = TRUE. MATCH RULE: prefer exact inquiry_silver_session_id match; otherwise use the latest prior moderate session for the same manychat_id where first_customer_message_at <= booking_at. Use booking_day as the primary date range dimension when reconciling official booking counts."
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
official_bookings AS (
  SELECT
    order_id,
    booking_at,
    booking_day,
    manychat_user_id AS manychat_id,
    customer_name AS booking_customer_name,
    sales_reporting_agent_name,
    inquiry_silver_session_id,
    inquiry_day,
    order_status_norm
  FROM `gulong-chatbot-459723.gulong_core.orders_booked`
  WHERE sales_reporting_agent_name = 'Chatbot/JCo'
    AND is_reportable_booked_order = TRUE
    AND manychat_user_id IS NOT NULL
),
followup_booking_flags AS (
  SELECT
    attributed_order_id AS order_id,
    MIN(followup_date) AS first_followup_date,
    MIN(followup_at) AS first_followup_at
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
  WHERE attributed_order_id IS NOT NULL
  GROUP BY 1
),
matched_orders AS (
  SELECT
    b.order_id,
    b.booking_at,
    b.booking_day,
    b.manychat_id,
    b.booking_customer_name,
    b.sales_reporting_agent_name,
    b.inquiry_silver_session_id,
    b.inquiry_day,
    b.order_status_norm,
    m.moderate_report_date,
    m.moderate_week,
    m.moderate_month,
    m.silver_session_id,
    m.user_name,
    m.contact_number,
    m.reply_status,
    m.reply_agent_name,
    m.reply_agent_name_norm,
    m.first_customer_message_at,
    m.first_cs_reply_at,
    m.minutes_to_first_reply,
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
  FROM official_bookings b
  JOIN moderates m
    ON m.manychat_id = b.manychat_id
   AND (
     b.inquiry_silver_session_id = m.silver_session_id
     OR m.first_customer_message_at <= b.booking_at
   )
)
SELECT
  mo.booking_day,
  DATE_TRUNC(mo.booking_day, WEEK(MONDAY)) AS booking_week,
  DATE_TRUNC(mo.booking_day, MONTH)        AS booking_month,
  mo.order_id,
  mo.booking_at,
  mo.manychat_id,
  mo.booking_customer_name,
  mo.sales_reporting_agent_name,
  mo.order_status_norm,
  mo.inquiry_silver_session_id,
  mo.inquiry_day,
  mo.moderate_report_date,
  mo.moderate_week,
  mo.moderate_month,
  mo.silver_session_id,
  mo.user_name,
  mo.contact_number,
  mo.reply_status,
  mo.reply_agent_name,
  mo.reply_agent_name_norm,
  mo.first_customer_message_at,
  mo.first_cs_reply_at,
  mo.minutes_to_first_reply,
  mo.booking_match_rule,
  fb.first_followup_date,
  fb.first_followup_at,
  CASE
    WHEN fb.order_id IS NOT NULL THEN 'CS Assisted'
    ELSE 'Chatbot Only'
  END AS booking_owner_bucket,
  CASE
    WHEN fb.order_id IS NOT NULL THEN 'CS-ASSISTED BOOKING'
    ELSE 'CHATBOT-ONLY BOOKING'
  END AS booking_ownership_status,
  DATETIME_DIFF(mo.booking_at, mo.first_customer_message_at, MINUTE) AS minutes_from_first_customer_to_booking,
  DATE_DIFF(mo.booking_day, mo.moderate_report_date, DAY) AS days_from_moderate_to_booking,
  CAST(fb.order_id IS NOT NULL AS INT64) AS cs_assisted_booking_count,
  CAST(fb.order_id IS NULL AS INT64) AS chatbot_only_booking_count,
  CAST(1 AS INT64) AS booked_order_count
FROM matched_orders mo
LEFT JOIN followup_booking_flags fb
  USING (order_id)
WHERE mo.booking_match_rn = 1;


-- =====================================================================
-- STATEMENT 8 — ORDER-LEVEL BOOKING RECONSTRUCTION TABLE
-- =====================================================================

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day
AS SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`;


-- =====================================================================
-- QA — run after deploying
-- =====================================================================

-- QA 0: denominator reconciliation against v_looker_first_reply_detail
-- If these do not match, t_moderate_followup_coverage is stale and
-- Statements 3 and 4 must be rerun.
SELECT
  f.moderate_report_date,
  f.moderates_first_reply,
  c.moderates_coverage,
  c.with_followup,
  c.no_followup,
  c.with_followup + c.no_followup AS coverage_recon,
  f.moderates_first_reply - c.moderates_coverage AS moderate_diff
FROM (
  SELECT
    report_date AS moderate_report_date,
    COUNT(*) AS moderates_first_reply
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE reply_status = 'Has CS Reply'
    AND manychat_id IS NOT NULL
  GROUP BY 1
) f
LEFT JOIN (
  SELECT
    moderate_report_date,
    SUM(moderate_session_count) AS moderates_coverage,
    SUM(followed_up_session_count) AS with_followup,
    SUM(no_followup_session_count) AS no_followup
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
  GROUP BY 1
) c
  USING (moderate_report_date)
WHERE f.moderates_first_reply != c.moderates_coverage
   OR f.moderates_first_reply != c.with_followup + c.no_followup
ORDER BY 1 DESC;

-- QA 1: detail view must contain only true follow-ups
SELECT
  MIN(minutes_from_reply_to_followup) AS min_minutes_from_reply,
  COUNTIF(minutes_from_reply_to_followup <= 0) AS non_true_followup_rows,
  COUNT(*) AS total_followup_rows
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`;

-- QA 2: coverage reconciliation
SELECT
  SUM(moderate_session_count) AS moderate_sessions,
  SUM(chatbot_total_booked_session_count) AS chatbot_total_booked_sessions,
  SUM(chatbot_only_booked_session_count) AS chatbot_only_booked_sessions,
  SUM(cs_assisted_booked_session_count) AS cs_assisted_booked_sessions,
  SUM(followed_up_session_count) AS with_followup,
  SUM(no_followup_session_count) AS no_followup,
  SUM(booked_session_count) AS booked_sessions
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE is_mature_cohort = 1;

-- QA 3: every mature moderate session should land in exactly one status
SELECT
  COUNT(*) AS bad_rows
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE is_mature_cohort = 1
  AND followed_up_session_count + no_followup_session_count != 1;

-- QA 4: sample day check — replace date / agent as needed
SELECT
  followup_date,
  followup_agent_name,
  COUNT(*) AS followup_rows,
  COUNT(DISTINCT attributed_order_id) AS distinct_bookings
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
WHERE followup_date = DATE '2026-07-22'
GROUP BY 1, 2
ORDER BY followup_rows DESC;

-- QA 5: cohort-day coverage
SELECT
  moderate_report_date,
  SUM(moderate_session_count) AS moderates,
  SUM(chatbot_total_booked_session_count) AS chatbot_total_booked,
  SUM(chatbot_only_booked_session_count) AS chatbot_only_booked,
  SUM(cs_assisted_booked_session_count) AS cs_assisted_booked,
  SUM(followed_up_session_count) AS with_followup,
  SUM(no_followup_session_count) AS no_followup,
  SUM(booked_session_count) AS booked,
  ROUND(
    SAFE_DIVIDE(SUM(followed_up_session_count), SUM(moderate_session_count)) * 100,
    1
  ) AS coverage_pct
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE is_mature_cohort = 1
GROUP BY 1
ORDER BY 1 DESC;

-- QA 6: compare coverage-booking rebuild vs official p_looker bookings
-- Use this to quantify the current booking gap before relying on the
-- coverage-layer booking fields for KPI parity.
SELECT
  p.report_date,
  p.total_bookings AS official_total_bookings,
  COALESCE(c.coverage_total_bookings, 0) AS coverage_total_bookings,
  p.total_bookings - COALESCE(c.coverage_total_bookings, 0) AS booking_diff
FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion` p
LEFT JOIN (
  SELECT
    moderate_report_date,
    SUM(booking_count_total_chatbot) AS coverage_total_bookings
  FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
  GROUP BY 1
) c
  ON c.moderate_report_date = p.report_date
WHERE p.agent_name = 'Chatbot/JCo'
ORDER BY p.report_date DESC;
