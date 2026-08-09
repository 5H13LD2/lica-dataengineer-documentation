-- =====================================================================
-- GULONG.PH — MODERATE FOLLOW-UP COVERAGE VIEW  (Sarah tag-logic upgrade)
-- Drop-in replacement for STATEMENT 3 + STATEMENT 4 in
-- moderate_followup_deploy.sql
--
-- WHY THIS FILE EXISTS — three fixes found by validating against live data
-- (gulong-chatbot-459723), not just the spec:
--
--   FIX 1  JOIN TYPE (deploy blocker)
--          The draft cast labels_current/tags_current user_id to INT64,
--          then joined USING(manychat_id). But manychat_id is STRING
--          everywhere (first_reply_detail, labels_current, tags_current).
--          USING on STRING vs INT64 = hard type error -> view will not
--          deploy. Fixed by keeping the key STRING (TRIM(user_id)) and
--          joining ON TRIM(m.manychat_id).
--
--   FIX 2  HANDLER COLUMN (silently returned 0)
--          Spec keyed on reporting_agent_name = 'sarah gulongph'. In
--          first_reply_detail, reporting_agent_name is ALWAYS 'jeanel co'
--          for Chatbot/JCo moderates -> 0 matching rows. Sarah's handling
--          actually lives in reply_agent_name (the CS agent who took the
--          thread). Switched the handler condition to reply_agent_name.
--          Result: 0 -> ~1,233 Sarah moderate sessions in scope.
--
--   FIX 3  'stop chatbot' EXCLUSION (10x swing on the headline number)
--          Among Sarah's moderate, not-booked sessions (1,226):
--            no need follow label ....  19
--            stop follow up tag ......  40
--            stop chatbot tag ....... 1,092   (1,038 excluded by this alone)
--          'stop chatbot' fires when a human takes over the bot flow — for
--          a Sarah-handled moderate that is the NORMAL state, not a
--          "do not follow up" signal. Folding it into the stop marker drops
--          85% of the real backlog.
--          -> stop_chatbot is now its OWN flag (has_stop_chatbot_tag) and is
--             NOT part of has_followup_stop_marker. Two metrics are exposed:
--               needs_followup_by_tag_logic         = spec-literal (excl. stop_chatbot)  ~129
--               needs_followup_active_by_tag_logic  = RECOMMENDED  (keeps human-handled) ~1,167
--          Confirm the business meaning of 'stop chatbot' before locking the
--          dashboard metric.
--
-- Everything else is preserved exactly from the current view.
-- =====================================================================


-- =====================================================================
-- STATEMENT 3 — SESSION STATUS / COVERAGE VIEW  (upgraded)
-- Grain: silver_session_id
-- =====================================================================

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`
OPTIONS (
  description = "One row per moderate-intent session from v_looker_first_reply_detail. GRAIN: silver_session_id. Adds tag-driven Sarah follow-up business logic keyed on reply_agent_name (the actual CS handler) plus ManyChat labels/tags. stop_chatbot is exposed as its own flag and is NOT treated as a do-not-follow-up marker; use needs_followup_active_by_tag_logic for the live backlog, or needs_followup_by_tag_logic for the strict spec-literal version. Use moderate_report_date as the primary date dimension."
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
    reporting_agent_name,
    LOWER(TRIM(reporting_agent_name)) AS reporting_agent_name_norm,
    source_agent_name,
    LOWER(TRIM(source_agent_name)) AS source_agent_name_norm,
    reply_status,
    reply_agent_name,
    LOWER(TRIM(reply_agent_name)) AS reply_agent_name_norm,
    first_customer_message_at,
    first_cs_reply_at,
    minutes_to_first_reply
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE manychat_id IS NOT NULL
),
manychat_label_flags AS (
  -- FIX 1: key stays STRING (was CAST ... AS INT64)
  SELECT
    TRIM(user_id) AS manychat_id,
    MAX(IF(LOWER(TRIM(label_name)) = 'moderate intent tag from chatbot', 1, 0))
      AS has_moderate_intent_tag_from_chatbot_label,
    MAX(IF(LOWER(TRIM(label_name)) = 'moderate intent cf from chatbot', 1, 0))
      AS has_moderate_intent_cf_from_chatbot_label,
    MAX(IF(LOWER(TRIM(label_name)) = 'booked', 1, 0)) AS has_booked_label,
    MAX(IF(LOWER(TRIM(label_name)) = 'no need follow', 1, 0)) AS has_no_need_follow_label
  FROM `gulong-chatbot-459723.manychat_data.labels_current`
  WHERE business_unit = 'gulong'
    AND LOWER(TRIM(label_name)) IN (
      'moderate intent tag from chatbot',
      'moderate intent cf from chatbot',
      'booked',
      'no need follow'
    )
  GROUP BY 1
),
manychat_tag_flags AS (
  -- FIX 1 + FIX 3: STRING key; 'stop chatbot' split into its own flag
  SELECT
    TRIM(user_id) AS manychat_id,
    MAX(IF(LOWER(TRIM(tag_name)) = 'followup - eligible', 1, 0)) AS has_followup_eligible_tag,
    MAX(IF(LOWER(TRIM(tag_name)) = 'stop follow up', 1, 0))      AS has_stop_followup_tag,
    MAX(IF(LOWER(TRIM(tag_name)) = 'stop chatbot', 1, 0))        AS has_stop_chatbot_tag,
    MAX(IF(REGEXP_CONTAINS(LOWER(TRIM(tag_name)), r'^booked($|-)'), 1, 0)) AS has_booked_tag
  FROM `gulong-chatbot-459723.manychat_data.tags_current`
  WHERE business_unit = 'gulong'
    AND (
      LOWER(TRIM(tag_name)) IN ('followup - eligible', 'stop follow up', 'stop chatbot')
      OR REGEXP_CONTAINS(LOWER(TRIM(tag_name)), r'^booked($|-)')
    )
  GROUP BY 1
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
    SUM(customer_response_count_after_followup) AS customer_response_count_after_followup,
    SUM(responded_followup_count) AS responded_followup_count,
    COUNTIF(responded_to_followup = 1) AS followup_rows_with_response,
    MIN(IF(responded_to_followup = 1, first_customer_response_at, NULL)) AS first_customer_response_at,
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
  m.reporting_agent_name,
  m.reporting_agent_name_norm,
  m.source_agent_name,
  m.source_agent_name_norm,
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
  fu.first_customer_response_at,
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
  COALESCE(fu.customer_response_count_after_followup, 0) AS customer_response_count_after_followup,
  COALESCE(fu.responded_followup_count, 0) AS responded_followup_count,
  COALESCE(fu.followup_rows_with_response, 0) AS followup_rows_with_response,
  COALESCE(fu.booking_count_from_followup, 0) AS booking_count_from_followup,
  COALESCE(fu.followup_rows_with_booking, 0) AS followup_rows_with_booking,
  fu.minutes_to_first_followup,
  fu.hours_to_first_followup,

  CASE
    WHEN COALESCE(fu.responded_followup_count, 0) > 0 THEN 'Yes'
    ELSE 'No'
  END AS responded_to_followup,

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

  -- ------------------------------------------------------------------
  -- Tag-driven flags
  -- ------------------------------------------------------------------
  COALESCE(lf.has_moderate_intent_tag_from_chatbot_label, 0)
    AS has_moderate_intent_tag_from_chatbot_label,
  COALESCE(lf.has_moderate_intent_cf_from_chatbot_label, 0)
    AS has_moderate_intent_cf_from_chatbot_label,
  CAST(
    COALESCE(lf.has_moderate_intent_tag_from_chatbot_label, 0) = 1
    OR COALESCE(lf.has_moderate_intent_cf_from_chatbot_label, 0) = 1
    AS INT64
  ) AS has_moderate_chatbot_label,
  COALESCE(lf.has_booked_label, 0) AS has_booked_label,
  COALESCE(tf.has_booked_tag, 0) AS has_booked_tag,
  CAST(
    COALESCE(lf.has_booked_label, 0) = 1
    OR COALESCE(tf.has_booked_tag, 0) = 1
    AS INT64
  ) AS has_any_booked_marker,
  COALESCE(lf.has_no_need_follow_label, 0) AS has_no_need_follow_label,
  COALESCE(tf.has_stop_followup_tag, 0) AS has_stop_followup_tag,   -- 'stop follow up' ONLY (no longer folds in stop chatbot)
  COALESCE(tf.has_stop_chatbot_tag, 0)  AS has_stop_chatbot_tag,    -- NEW: bot flow stopped / human took over
  CAST(
    COALESCE(lf.has_no_need_follow_label, 0) = 1
    OR COALESCE(tf.has_stop_followup_tag, 0) = 1
    AS INT64
  ) AS has_followup_stop_marker,                                    -- excludes stop_chatbot by design
  COALESCE(tf.has_followup_eligible_tag, 0) AS has_followup_eligible_tag,

  -- ------------------------------------------------------------------
  -- Sarah follow-up status (keyed on reply_agent_name = actual handler)
  -- ------------------------------------------------------------------
  CASE
    WHEN m.source_agent_name = 'Chatbot/JCo'
      AND m.reply_agent_name_norm = 'sarah gulongph'
      AND (
        COALESCE(lf.has_moderate_intent_tag_from_chatbot_label, 0) = 1
        OR COALESCE(lf.has_moderate_intent_cf_from_chatbot_label, 0) = 1
      )
      AND COALESCE(lf.has_booked_label, 0) = 0
      AND COALESCE(tf.has_booked_tag, 0) = 0
    THEN
      CASE
        WHEN COALESCE(lf.has_no_need_follow_label, 0) = 1
          OR COALESCE(tf.has_stop_followup_tag, 0) = 1
        THEN 'EXCLUDED - NO NEED FOLLOWUP'
        WHEN COALESCE(tf.has_stop_chatbot_tag, 0) = 1
        THEN 'NEEDS FOLLOWUP - BOT STOPPED (HUMAN HANDLED)'
        ELSE 'NEEDS FOLLOWUP'
      END
    WHEN m.source_agent_name = 'Chatbot/JCo'
      AND m.reply_agent_name_norm = 'sarah gulongph'
      AND (
        COALESCE(lf.has_booked_label, 0) = 1
        OR COALESCE(tf.has_booked_tag, 0) = 1
      )
    THEN 'EXCLUDED - BOOKED'
    WHEN m.source_agent_name = 'Chatbot/JCo'
      AND m.reply_agent_name_norm = 'sarah gulongph'
      AND COALESCE(tf.has_followup_eligible_tag, 0) = 1
    THEN 'FOLLOWUP ELIGIBLE - CHECK MODERATE TAG'
    ELSE 'OUT OF SARAH FOLLOWUP SCOPE'
  END AS sarah_followup_tag_logic_status,

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
  CAST(COALESCE(fu.responded_followup_count, 0) > 0 AS INT64) AS was_responded_to_followup,
  CAST(COALESCE(fu.followup_count, 0) = 0 AS INT64) AS never_followed_up,
  CAST(COALESCE(fu.followup_count, 0) > 1 AS INT64) AS had_multiple_followups,

  -- SPEC-LITERAL: reply=Sarah, moderate label, no booked marker,
  -- no no-need/stop-follow-up, AND no stop_chatbot  (~129 sessions)
  CAST(
    m.source_agent_name = 'Chatbot/JCo'
    AND m.reply_agent_name_norm = 'sarah gulongph'
    AND (
      COALESCE(lf.has_moderate_intent_tag_from_chatbot_label, 0) = 1
      OR COALESCE(lf.has_moderate_intent_cf_from_chatbot_label, 0) = 1
    )
    AND COALESCE(lf.has_booked_label, 0) = 0
    AND COALESCE(tf.has_booked_tag, 0) = 0
    AND COALESCE(lf.has_no_need_follow_label, 0) = 0
    AND COALESCE(tf.has_stop_followup_tag, 0) = 0
    AND COALESCE(tf.has_stop_chatbot_tag, 0) = 0
    AS INT64
  ) AS needs_followup_by_tag_logic,

  -- RECOMMENDED: same, but stop_chatbot (human handoff) is KEPT in scope (~1,167 sessions)
  CAST(
    m.source_agent_name = 'Chatbot/JCo'
    AND m.reply_agent_name_norm = 'sarah gulongph'
    AND (
      COALESCE(lf.has_moderate_intent_tag_from_chatbot_label, 0) = 1
      OR COALESCE(lf.has_moderate_intent_cf_from_chatbot_label, 0) = 1
    )
    AND COALESCE(lf.has_booked_label, 0) = 0
    AND COALESCE(tf.has_booked_tag, 0) = 0
    AND COALESCE(lf.has_no_need_follow_label, 0) = 0
    AND COALESCE(tf.has_stop_followup_tag, 0) = 0
    AS INT64
  ) AS needs_followup_active_by_tag_logic,

  CAST(
    COALESCE(db.booking_count_total_chatbot, 0) > 0
    AND COALESCE(fu.booking_count_from_followup, 0) = 0
    AS INT64
  ) AS was_booked_chatbot_only,
  CAST(COALESCE(fu.booking_count_from_followup, 0) > 0 AS INT64) AS was_booked_from_followup,
  CAST(m.moderate_report_date <= DATE_SUB(CURRENT_DATE('Asia/Manila'), INTERVAL 2 DAY) AS INT64)
    AS is_mature_cohort,

  -- ------------------------------------------------------------------
  -- Session-count measures (SUM these in Looker)
  -- ------------------------------------------------------------------
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
  CAST(COALESCE(fu.responded_followup_count, 0) > 0 AS INT64) AS responded_session_count,
  CAST(
    m.reply_status = 'Has CS Reply' AND COALESCE(fu.followup_count, 0) = 0
    AS INT64
  ) AS no_followup_session_count,

  -- Spec-literal Sarah backlog (excludes stop_chatbot)  ~129
  CAST(
    m.source_agent_name = 'Chatbot/JCo'
    AND m.reply_agent_name_norm = 'sarah gulongph'
    AND (
      COALESCE(lf.has_moderate_intent_tag_from_chatbot_label, 0) = 1
      OR COALESCE(lf.has_moderate_intent_cf_from_chatbot_label, 0) = 1
    )
    AND COALESCE(lf.has_booked_label, 0) = 0
    AND COALESCE(tf.has_booked_tag, 0) = 0
    AND COALESCE(lf.has_no_need_follow_label, 0) = 0
    AND COALESCE(tf.has_stop_followup_tag, 0) = 0
    AND COALESCE(tf.has_stop_chatbot_tag, 0) = 0
    AS INT64
  ) AS needs_followup_by_tag_logic_session_count,

  -- RECOMMENDED live backlog (keeps human-handled)  ~1,167
  CAST(
    m.source_agent_name = 'Chatbot/JCo'
    AND m.reply_agent_name_norm = 'sarah gulongph'
    AND (
      COALESCE(lf.has_moderate_intent_tag_from_chatbot_label, 0) = 1
      OR COALESCE(lf.has_moderate_intent_cf_from_chatbot_label, 0) = 1
    )
    AND COALESCE(lf.has_booked_label, 0) = 0
    AND COALESCE(tf.has_booked_tag, 0) = 0
    AND COALESCE(lf.has_no_need_follow_label, 0) = 0
    AND COALESCE(tf.has_stop_followup_tag, 0) = 0
    AS INT64
  ) AS needs_followup_active_by_tag_logic_session_count,

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
  USING (silver_session_id)
LEFT JOIN manychat_label_flags lf
  ON lf.manychat_id = TRIM(m.manychat_id)   -- FIX 1: STRING = STRING
LEFT JOIN manychat_tag_flags tf
  ON tf.manychat_id = TRIM(m.manychat_id);  -- FIX 1: STRING = STRING


-- =====================================================================
-- STATEMENT 4 — COVERAGE TABLE  (unchanged; rebuild after Statement 3)
-- =====================================================================

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
CLUSTER BY moderate_report_date
AS SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`;


-- =====================================================================
-- VALIDATION — run after deploy
-- =====================================================================

-- V1: status breakdown for Sarah's pool (sanity of the new logic)
SELECT
  sarah_followup_tag_logic_status,
  COUNT(*) AS sessions,
  COUNT(DISTINCT manychat_id) AS people
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
GROUP BY 1
ORDER BY sessions DESC;

-- V2: headline metric — spec-literal vs recommended
SELECT
  SUM(needs_followup_by_tag_logic_session_count)        AS needs_fu_strict,        -- excl. stop_chatbot
  SUM(needs_followup_active_by_tag_logic_session_count) AS needs_fu_recommended,   -- keeps human-handled
  COUNT(DISTINCT IF(needs_followup_active_by_tag_logic = 1, manychat_id, NULL)) AS needs_fu_recommended_people
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`;

-- V3: spot-check 20 sample users against their live ManyChat labels/tags
SELECT
  manychat_id, user_name, moderate_report_date, reply_agent_name,
  has_moderate_chatbot_label, has_any_booked_marker,
  has_no_need_follow_label, has_stop_followup_tag, has_stop_chatbot_tag,
  sarah_followup_tag_logic_status, needs_followup_active_by_tag_logic
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
WHERE reply_agent_name_norm = 'sarah gulongph'
  AND has_moderate_chatbot_label = 1
ORDER BY moderate_report_date DESC
LIMIT 20;