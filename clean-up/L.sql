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
    COALESCE(first_customer_message_at, moderate_tagged_at) AS first_customer_message_at,
    LEAD(COALESCE(first_customer_message_at, moderate_tagged_at)) OVER (
      PARTITION BY manychat_id
      ORDER BY COALESCE(first_customer_message_at, moderate_tagged_at), silver_session_id
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
    'No CS Reply' AS reply_status,
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
    COALESCE(pi.inquiry_fallback_day, b.inquiry_day, DATE(pi.inquiry_fallback_first_customer_message_at))
      AS moderate_report_date,
    DATE_TRUNC(
      COALESCE(pi.inquiry_fallback_day, b.inquiry_day, DATE(pi.inquiry_fallback_first_customer_message_at)),
      WEEK(MONDAY)
    ) AS moderate_week,
    DATE_TRUNC(
      COALESCE(pi.inquiry_fallback_day, b.inquiry_day, DATE(pi.inquiry_fallback_first_customer_message_at)),
      MONTH
    ) AS moderate_month,
    COALESCE(pi.inquiry_fallback_silver_session_id, b.inquiry_silver_session_id) AS silver_session_id,
    pi.inquiry_fallback_user_name AS user_name,
    pi.inquiry_fallback_contact_number AS contact_number,
    'No CS Reply' AS reply_status,
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
),
reply_backfill_candidates AS (
  SELECT
    ro.order_id,
    m.datetime AS candidate_first_cs_reply_at,
    m.sender AS candidate_reply_agent_name,
    ROW_NUMBER() OVER (
      PARTITION BY ro.order_id
      ORDER BY
        CASE WHEN m.datetime <= ro.booking_at THEN 0 ELSE 1 END,
        m.datetime,
        m.message_id
  ) AS rn
  FROM resolved_orders ro
  JOIN `gulong-chatbot-459723.manychat_data.messages` m
    ON m.datetime >= DATETIME '2025-01-01 00:00:00'
   AND m.datetime < DATETIME '2030-01-01 00:00:00'
   AND m.user_id = ro.manychat_id
   AND m.business_unit = 'gulong'
   AND m.role = 'agent'
   AND m.type = 'msgout_lc'
   AND m.datetime >= ro.first_customer_message_at
  WHERE ro.first_cs_reply_at IS NULL
    AND ro.manychat_id IS NOT NULL
    AND ro.first_customer_message_at IS NOT NULL
),
reply_backfills AS (
  SELECT
    order_id,
    candidate_first_cs_reply_at AS backfilled_first_cs_reply_at,
    candidate_reply_agent_name AS backfilled_reply_agent_name,
    LOWER(TRIM(candidate_reply_agent_name)) AS backfilled_reply_agent_name_norm
  FROM reply_backfill_candidates
  WHERE rn = 1
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
  CASE
    WHEN COALESCE(ro.first_cs_reply_at, rb.backfilled_first_cs_reply_at) IS NOT NULL THEN 'Has CS Reply'
    ELSE COALESCE(ro.reply_status, 'No CS Reply')
  END AS reply_status,
  COALESCE(ro.reply_agent_name, rb.backfilled_reply_agent_name) AS reply_agent_name,
  COALESCE(ro.reply_agent_name_norm, rb.backfilled_reply_agent_name_norm) AS reply_agent_name_norm,
  ro.first_customer_message_at,
  ro.next_customer_message_at,
  COALESCE(ro.first_cs_reply_at, rb.backfilled_first_cs_reply_at) AS first_cs_reply_at,
  DATETIME_DIFF(
    COALESCE(ro.first_cs_reply_at, rb.backfilled_first_cs_reply_at),
    ro.first_customer_message_at,
    MINUTE
  ) AS minutes_to_first_reply,
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
LEFT JOIN reply_backfills rb
  USING (order_id)
LEFT JOIN followup_booking_flags fb
  USING (order_id);


-- =====================================================================
-- STATEMENT 6 — ORDER-LEVEL BOOKING RECONSTRUCTION TABLE
-- =====================================================================

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day
AS
SELECT * FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`;
