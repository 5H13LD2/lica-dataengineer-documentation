-- =====================================================================
-- GULONG.PH — MODERATE FOLLOW-UP COVERAGE REBUILD
-- Project: gulong-chatbot-459723
-- Dataset: gulong_reporting
--
-- Purpose:
--   Deploy-ready copy of the current coverage-layer rebuild logic.
--
-- Current state as of July 25, 2026:
--   - the moderate denominator should inherit the updated
--     v_looker_first_reply_detail cohort after rebuild
--   - booking_count_total_chatbot / first_chatbot_order_id are rebuilt
--     from the official Chatbot/JCo booking universe in orders_booked,
--     then matched back to moderate sessions
--   - an order-level reconstruction layer is included so all official
--     order ids can be traced even when a session has multiple bookings
--   - booking fallback chain:
--       1. exact inquiry_silver_session_id
--       2. same manychat_id within the session window
--       3. latest prior moderate for the same manychat_id
--
-- Run order:
--   1. STATEMENT 3
--   2. STATEMENT 4
--   3. STATEMENT 5
--   4. STATEMENT 6
-- =====================================================================


-- =====================================================================
-- STATEMENT 3 — SESSION STATUS / COVERAGE VIEW
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
    LEAD(first_customer_message_at) OVER (
      PARTITION BY manychat_id
      ORDER BY first_customer_message_at, silver_session_id
    ) AS next_customer_message_at,
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
      WHEN m.first_customer_message_at <= b.booking_at
       AND (
         m.next_customer_message_at IS NULL
         OR b.booking_at < m.next_customer_message_at
       ) THEN 'SESSION WINDOW'
      ELSE 'LATEST PRIOR MODERATE'
    END AS booking_match_rule,
    ROW_NUMBER() OVER (
      PARTITION BY b.order_id
      ORDER BY
        CASE WHEN b.inquiry_silver_session_id = m.silver_session_id THEN 0 ELSE 1 END,
        CASE
          WHEN m.first_customer_message_at <= b.booking_at
           AND (
             m.next_customer_message_at IS NULL
             OR b.booking_at < m.next_customer_message_at
           ) THEN 0
          ELSE 1
        END,
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
    COUNTIF(booking_match_rule = 'SESSION WINDOW') AS session_window_booking_count,
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
  COALESCE(db.session_window_booking_count, 0) AS session_window_booking_count,
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
AS
SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`;


-- =====================================================================
-- STATEMENT 5 — ORDER-LEVEL BOOKING RECONSTRUCTION VIEW
-- =====================================================================

CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`
OPTIONS (
  description = "One row per official Chatbot/JCo booked order from orders_booked, matched back to the nearest eligible moderate session. GRAIN: order_id. BOOKING SOURCE: orders_booked where sales_reporting_agent_name = 'Chatbot/JCo' and is_reportable_booked_order = TRUE. MATCH CANDIDATES: current v_looker_first_reply_detail rows plus base fallback moderate sessions reconstructed from inquiry_sessions + moderate_intent_sessions for Chatbot/JCo. MATCH RULE: prefer exact inquiry_silver_session_id match, then same-manychat session window match, then latest prior moderate session, then latest prior inquiry session, and finally retain the order as an unmatched official booking if no moderate match exists. Use booking_day as the primary date range dimension when reconciling official booking counts."
)
AS
WITH primary_moderates AS (
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
    LEAD(first_customer_message_at) OVER (
      PARTITION BY manychat_id
      ORDER BY first_customer_message_at, silver_session_id
    ) AS next_customer_message_at,
    first_cs_reply_at,
    minutes_to_first_reply
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE manychat_id IS NOT NULL
),
agent_aliases_normalized AS (
  SELECT
    alias_norm,
    canonical_agent_name
  FROM (
    SELECT
      UPPER(REGEXP_REPLACE(TRIM(alias_value), r'[^A-Za-z0-9]+', '')) AS alias_norm,
      canonical_agent_name,
      ROW_NUMBER() OVER (
        PARTITION BY UPPER(REGEXP_REPLACE(TRIM(alias_value), r'[^A-Za-z0-9]+', ''))
        ORDER BY
          IF(alias_type = 'manychat_agent_name', 0, 1),
          updated_at DESC
      ) AS rn
    FROM `gulong-chatbot-459723.gulong_core.agent_aliases`
    WHERE business_unit = 'gulong'
      AND active
      AND alias_type IN ('manychat_agent_name', 'agent_key', 'added_by_normalized')
  )
  WHERE rn = 1
    AND alias_norm IS NOT NULL
    AND alias_norm != ''
),
base_session_context AS (
  SELECT
    silver_session_id,
    user_id AS manychat_id,
    user_name,
    evidence_contact AS contact_number,
    first_user_message_at,
    ROW_NUMBER() OVER (
      PARTITION BY silver_session_id
      ORDER BY first_user_message_at
    ) AS rn
  FROM `gulong-chatbot-459723.gulong_core.fb_inquiry_sessions`
  WHERE business_unit = 'gulong'
    AND channel = 'manychat'
),
base_chatbot_moderates AS (
  SELECT
    s.inquiry_day AS moderate_report_date,
    DATE_TRUNC(s.inquiry_day, WEEK(MONDAY)) AS moderate_week,
    DATE_TRUNC(s.inquiry_day, MONTH)        AS moderate_month,
    s.silver_session_id,
    s.user_id AS manychat_id,
    COALESCE(sc.user_name, sf.user_name) AS user_name,
    sc.contact_number,
    CAST(NULL AS STRING) AS reply_status,
    'Chatbot/JCo' AS reply_agent_name,
    'chatbot/jco' AS reply_agent_name_norm,
    COALESCE(sc.first_user_message_at, m.first_moderate_at) AS first_customer_message_at,
    CAST(NULL AS DATETIME) AS next_customer_message_at,
    CAST(NULL AS DATETIME) AS first_cs_reply_at,
    CAST(NULL AS INT64) AS minutes_to_first_reply
  FROM `gulong-chatbot-459723.gulong_core.inquiry_sessions` s
  JOIN `gulong-chatbot-459723.gulong_core.moderate_intent_sessions` m
    ON m.business_unit = s.business_unit
   AND m.channel = s.channel
   AND m.user_id = s.user_id
   AND m.silver_session_id = s.silver_session_id
   AND m.validated_moderate = TRUE
  LEFT JOIN agent_aliases_normalized aa
    ON aa.alias_norm = UPPER(
      REGEXP_REPLACE(TRIM(COALESCE(s.original_assigned_agent_name, '')), r'[^A-Za-z0-9]+', '')
    )
  LEFT JOIN (
    SELECT
      silver_session_id,
      manychat_id,
      user_name,
      contact_number,
      first_user_message_at
    FROM base_session_context
    WHERE rn = 1
  ) sc
    ON sc.silver_session_id = s.silver_session_id
  LEFT JOIN (
    SELECT * EXCEPT(rn)
    FROM (
      SELECT
        user_id AS manychat_id,
        user_name,
        ROW_NUMBER() OVER (
          PARTITION BY user_id
          ORDER BY first_user_message_at DESC, silver_session_id DESC
        ) AS rn
      FROM `gulong-chatbot-459723.gulong_core.fb_inquiry_sessions`
      WHERE business_unit = 'gulong'
        AND channel = 'manychat'
        AND user_name IS NOT NULL
    )
    WHERE rn = 1
  ) sf
    ON sf.manychat_id = s.user_id
  WHERE s.business_unit = 'gulong'
    AND s.channel = 'manychat'
    AND COALESCE(
      aa.canonical_agent_name,
      IF(LOWER(TRIM(s.original_assigned_agent_name)) = 'jeanel co', 'Chatbot/JCo', NULL),
      s.original_assigned_agent_name,
      'Unassigned'
    ) = 'Chatbot/JCo'
),
moderates AS (
  SELECT
    moderate_report_date,
    moderate_week,
    moderate_month,
    silver_session_id,
    manychat_id,
    user_name,
    contact_number,
    reply_status,
    reply_agent_name,
    reply_agent_name_norm,
    first_customer_message_at,
    LEAD(first_customer_message_at) OVER (
      PARTITION BY manychat_id
      ORDER BY first_customer_message_at, silver_session_id
    ) AS next_customer_message_at,
    first_cs_reply_at,
    minutes_to_first_reply
  FROM (
    SELECT * FROM primary_moderates
    UNION ALL
    SELECT
      b.moderate_report_date,
      b.moderate_week,
      b.moderate_month,
      b.silver_session_id,
      b.manychat_id,
      b.user_name,
      b.contact_number,
      b.reply_status,
      b.reply_agent_name,
      b.reply_agent_name_norm,
      b.first_customer_message_at,
      b.next_customer_message_at,
      b.first_cs_reply_at,
      b.minutes_to_first_reply
    FROM base_chatbot_moderates b
    LEFT JOIN primary_moderates p
      USING (silver_session_id)
    WHERE p.silver_session_id IS NULL
      AND b.manychat_id IS NOT NULL
  )
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
raw_inquiry_sessions AS (
  SELECT
    silver_session_id,
    inquiry_day,
    user_id AS manychat_id,
    first_user_message_at AS first_customer_message_at,
    user_name,
    evidence_contact AS contact_number
  FROM `gulong-chatbot-459723.gulong_core.fb_inquiry_sessions`
  WHERE business_unit = 'gulong'
    AND channel = 'manychat'
),
prior_inquiry_match AS (
  SELECT
    b.order_id,
    s.silver_session_id AS inquiry_fallback_silver_session_id,
    s.inquiry_day AS inquiry_fallback_day,
    s.first_customer_message_at AS inquiry_fallback_first_customer_message_at,
    s.user_name AS inquiry_fallback_user_name,
    s.contact_number AS inquiry_fallback_contact_number,
    ROW_NUMBER() OVER (
      PARTITION BY b.order_id
      ORDER BY s.first_customer_message_at DESC, s.silver_session_id DESC
    ) AS inquiry_fallback_rn
  FROM official_bookings b
  JOIN raw_inquiry_sessions s
    ON s.manychat_id = b.manychat_id
   AND s.first_customer_message_at <= b.booking_at
),
best_prior_inquiry AS (
  SELECT
    order_id,
    inquiry_fallback_silver_session_id,
    inquiry_fallback_day,
    inquiry_fallback_first_customer_message_at,
    inquiry_fallback_user_name,
    inquiry_fallback_contact_number
  FROM prior_inquiry_match
  WHERE inquiry_fallback_rn = 1
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
    m.next_customer_message_at,
    m.first_cs_reply_at,
    m.minutes_to_first_reply,
    CASE
      WHEN b.inquiry_silver_session_id = m.silver_session_id THEN 'EXACT INQUIRY SESSION'
      WHEN m.first_customer_message_at <= b.booking_at
       AND (
         m.next_customer_message_at IS NULL
         OR b.booking_at < m.next_customer_message_at
       ) THEN 'SESSION WINDOW'
      ELSE 'LATEST PRIOR MODERATE'
    END AS booking_match_rule,
    ROW_NUMBER() OVER (
      PARTITION BY b.order_id
      ORDER BY
        CASE WHEN b.inquiry_silver_session_id = m.silver_session_id THEN 0 ELSE 1 END,
        CASE
          WHEN m.first_customer_message_at <= b.booking_at
           AND (
             m.next_customer_message_at IS NULL
             OR b.booking_at < m.next_customer_message_at
           ) THEN 0
          ELSE 1
        END,
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
),
best_matched_orders AS (
  SELECT
    order_id,
    booking_at,
    booking_day,
    manychat_id,
    booking_customer_name,
    sales_reporting_agent_name,
    inquiry_silver_session_id,
    inquiry_day,
    order_status_norm,
    moderate_report_date,
    moderate_week,
    moderate_month,
    silver_session_id,
    user_name,
    contact_number,
    reply_status,
    reply_agent_name,
    reply_agent_name_norm,
    first_customer_message_at,
    next_customer_message_at,
    first_cs_reply_at,
    minutes_to_first_reply,
    booking_match_rule
  FROM matched_orders
  WHERE booking_match_rn = 1
),
unmatched_official_bookings AS (
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
    CAST(NULL AS DATE) AS moderate_report_date,
    CAST(NULL AS DATE) AS moderate_week,
    CAST(NULL AS DATE) AS moderate_month,
    COALESCE(pi.inquiry_fallback_silver_session_id, b.inquiry_silver_session_id) AS silver_session_id,
    pi.inquiry_fallback_user_name AS user_name,
    pi.inquiry_fallback_contact_number AS contact_number,
    CAST(NULL AS STRING) AS reply_status,
    CAST(NULL AS STRING) AS reply_agent_name,
    CAST(NULL AS STRING) AS reply_agent_name_norm,
    pi.inquiry_fallback_first_customer_message_at AS first_customer_message_at,
    CAST(NULL AS DATETIME) AS next_customer_message_at,
    CAST(NULL AS DATETIME) AS first_cs_reply_at,
    CAST(NULL AS INT64) AS minutes_to_first_reply,
    CASE
      WHEN pi.order_id IS NOT NULL THEN 'LATEST PRIOR INQUIRY'
      ELSE 'UNMATCHED OFFICIAL BOOKING'
    END AS booking_match_rule
  FROM official_bookings b
  LEFT JOIN best_matched_orders mo
    USING (order_id)
  LEFT JOIN best_prior_inquiry pi
    USING (order_id)
  WHERE mo.order_id IS NULL
),
resolved_orders AS (
  SELECT * FROM best_matched_orders
  UNION ALL
  SELECT * FROM unmatched_official_bookings
)
SELECT
  ro.booking_day,
  DATE_TRUNC(ro.booking_day, WEEK(MONDAY)) AS booking_week,
  DATE_TRUNC(ro.booking_day, MONTH)        AS booking_month,
  ro.order_id,
  ro.booking_at,
  ro.manychat_id,
  ro.booking_customer_name,
  ro.sales_reporting_agent_name,
  ro.order_status_norm,
  ro.inquiry_silver_session_id,
  ro.inquiry_day,
  ro.moderate_report_date,
  ro.moderate_week,
  ro.moderate_month,
  ro.silver_session_id,
  ro.user_name,
  ro.contact_number,
  ro.reply_status,
  ro.reply_agent_name,
  ro.reply_agent_name_norm,
  ro.first_customer_message_at,
  ro.next_customer_message_at,
  ro.first_cs_reply_at,
  ro.minutes_to_first_reply,
  ro.booking_match_rule,
  fb.first_followup_date,
  fb.first_followup_at,
  CASE
    WHEN fb.order_id IS NOT NULL THEN 'CS Assisted'
    WHEN ro.booking_match_rule = 'UNMATCHED OFFICIAL BOOKING' THEN 'Unmatched Official Booking'
    ELSE 'Chatbot Only'
  END AS booking_owner_bucket,
  CASE
    WHEN fb.order_id IS NOT NULL THEN 'CS-ASSISTED BOOKING'
    WHEN ro.booking_match_rule = 'UNMATCHED OFFICIAL BOOKING' THEN 'UNMATCHED OFFICIAL BOOKING'
    ELSE 'CHATBOT-ONLY BOOKING'
  END AS booking_ownership_status,
  DATETIME_DIFF(ro.booking_at, ro.first_customer_message_at, MINUTE) AS minutes_from_first_customer_to_booking,
  DATE_DIFF(ro.booking_day, ro.moderate_report_date, DAY) AS days_from_moderate_to_booking,
  CAST(fb.order_id IS NOT NULL AS INT64) AS cs_assisted_booking_count,
  CAST(fb.order_id IS NULL AND ro.booking_match_rule != 'UNMATCHED OFFICIAL BOOKING' AS INT64) AS chatbot_only_booking_count,
  CAST(ro.booking_match_rule = 'UNMATCHED OFFICIAL BOOKING' AS INT64) AS unmatched_official_booking_count,
  CAST(1 AS INT64) AS booked_order_count
FROM resolved_orders ro
LEFT JOIN followup_booking_flags fb
  USING (order_id);


-- =====================================================================
-- STATEMENT 6 — ORDER-LEVEL BOOKING RECONSTRUCTION TABLE
-- =====================================================================

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day
AS
SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`;
