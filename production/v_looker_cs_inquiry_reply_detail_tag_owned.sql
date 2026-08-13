#standardSQL
-- =============================================================================
-- v_looker_cs_inquiry_reply_detail_tag_owned  (revised)
--
-- CHANGES vs previous version:
--   [#3] manychat_id normalized to STRING at source -> all joins consistent.
--   [#4 + new logic] message_first_customer now SAME-DAY only (DATE = report_date).
--        Removes the +/-1 day overlap AND implements the "count only inquiries
--        that actually came in on that report_date" requirement.
--   inquiry_count / replied / no_reply now gated on a real same-day inquiry.
--   [#1] SLA minutes guarded to same-day reply (no more cross-day inflation),
--        computed ONCE in an enrichment step.
--   [#2] reply sender canonicalized via agent_aliases before matching agent_name
--        (Becca Armstrng vs Rolyn Ang etc. now resolve correctly).
--
-- VERIFY BEFORE DEPLOY:
--   - manychat_data.messages partition column must be `datetime` (or DATE(datetime)).
--     The literal `datetime >= '2026-03-01'` below is what satisfies
--     require_partition_filter / enables pruning. If the partition col is a
--     separate DATE column, swap the literal filters accordingly.
--   - If you only need recent data in Looker, uncomment the rolling lower bound
--     marked [COST] to cap scan growth (or materialize into a t_ table).
-- =============================================================================

CREATE OR REPLACE VIEW
  `gulong-chatbot-459723.gulong_reporting.v_looker_cs_inquiry_reply_detail_tag_owned`
AS
WITH cs_assignments AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      a.business_unit,
      CAST(a.user_id AS STRING) AS manychat_id,          -- [#3] STRING at source
      a.assignment_date AS report_date,
      COALESCE(
        a.silver_session_id,
        CONCAT('assignment:', CAST(a.user_id AS STRING), ':', CAST(a.assignment_date AS STRING))
      ) AS silver_session_id,
      a.assignment_at,
      a.assigned_agent_name,
      a.agent_reporting_name,
      a.agent_reporting_group,
      ROW_NUMBER() OVER (
        PARTITION BY a.business_unit, a.user_id, a.assignment_date
        ORDER BY
          IF(a.silver_session_id IS NOT NULL, 0, 1),
          a.assignment_at,
          a.assignment_event_id
      ) AS rn
    FROM `gulong-chatbot-459723.gulong_core.inquiry_assignments` a
    WHERE a.business_unit = 'gulong'
      AND a.agent_reporting_group = 'cs_agent'
      AND a.assignment_date >= DATE '2026-03-01'
  )
  WHERE rn = 1
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

user_name_realtime AS (
  SELECT
    CAST(user_id AS STRING) AS user_id,                  -- [#3] STRING
    user_name
  FROM `gulong-chatbot-459723.manychat_data.users_current`
  WHERE business_unit = 'gulong'
    AND user_name IS NOT NULL
    AND TRIM(user_name) != ''
),

-- Current owner comes from active ManyChat agent tags.
-- If a contact has both a human CS tag and Chatbot/JCo tag, prefer the human CS tag.
owner_agent_current AS (
  SELECT
    manychat_id,
    canonical_agent_name AS agent_name,
    tag_name AS agent_tag_name,
    'manychat_current_tag' AS agent_name_source
  FROM (
    SELECT
      CAST(tc.user_id AS STRING) AS manychat_id,
      tc.tag_name,
      aa.canonical_agent_name,
      tc.tag_updated_datetime,
      ROW_NUMBER() OVER (
        PARTITION BY CAST(tc.user_id AS STRING)
        ORDER BY
          IF(aa.canonical_agent_name = 'Chatbot/JCo', 1, 0),
          tc.tag_updated_datetime DESC,
          aa.canonical_agent_name
      ) AS rn
    FROM `gulong-chatbot-459723.manychat_data.tags_current` tc
    JOIN agent_aliases_normalized aa
      ON aa.alias_norm = UPPER(
        REGEXP_REPLACE(TRIM(tc.tag_name), r'[^A-Za-z0-9]+', '')
      )
    WHERE tc.business_unit = 'gulong'
  )
  WHERE rn = 1
),

-- SAME-DAY first customer message only. This defines the "inquiry na pumasok
-- nung araw na yun". Literal lower bound kept for partition pruning; the
-- correlated equality restricts to report_date.
message_first_customer AS (
  SELECT
    c.report_date,
    c.manychat_id,
    c.silver_session_id,
    MIN(m.datetime) AS first_customer_message_at
  FROM cs_assignments c
  JOIN `gulong-chatbot-459723.manychat_data.messages` m
    ON CAST(m.user_id AS STRING) = c.manychat_id          -- [#3] STRING
   AND m.business_unit = 'gulong'
   AND m.role = 'user'
   AND m.datetime >= DATETIME '2026-03-01 00:00:00'        -- [COST] partition prune literal
   -- [COST] rolling window option (uncomment to cap scan):
   -- AND m.datetime >= DATETIME(DATE_SUB(CURRENT_DATE(), INTERVAL 120 DAY))
   AND DATE(m.datetime) = c.report_date                    -- [#4 + new logic] same-day only
  GROUP BY c.report_date, c.manychat_id, c.silver_session_id
),

session_boundaries AS (
  SELECT
    fc.report_date,
    fc.silver_session_id,
    fc.manychat_id,
    fc.first_customer_message_at,
    LEAD(fc.first_customer_message_at) OVER (
      PARTITION BY fc.manychat_id
      ORDER BY fc.first_customer_message_at, fc.silver_session_id
    ) AS next_customer_message_at
  FROM message_first_customer fc
),

cohort AS (
  SELECT
    c.report_date,
    DATE_TRUNC(c.report_date, WEEK(MONDAY)) AS report_week,
    DATE_TRUNC(c.report_date, MONTH) AS report_month,
    COALESCE(
      oac.agent_name,
      c.assigned_agent_name,
      c.agent_reporting_name,
      'Unassigned'
    ) AS agent_name,
    COALESCE(oac.agent_name_source, 'assignment_fallback') AS agent_name_source,
    oac.agent_tag_name,
    c.agent_reporting_group,
    c.manychat_id,
    c.silver_session_id,
    c.assignment_at,
    CASE
      WHEN c.assignment_at IS NULL THEN NULL
      WHEN TIME(c.assignment_at) >= TIME '18:00:00'
        THEN DATETIME(DATE_ADD(DATE(c.assignment_at), INTERVAL 1 DAY), TIME '09:00:00')
      WHEN TIME(c.assignment_at) < TIME '09:00:00'
        THEN DATETIME(DATE(c.assignment_at), TIME '09:00:00')
      WHEN TIME(c.assignment_at) >= TIME '12:00:00'
           AND TIME(c.assignment_at) < TIME '13:00:00'
        THEN DATETIME(DATE(c.assignment_at), TIME '13:00:00')
      ELSE c.assignment_at
    END AS effective_assignment_at,
    IF(
      c.assignment_at IS NOT NULL
      AND (
        TIME(c.assignment_at) < TIME '09:00:00'
        OR TIME(c.assignment_at) >= TIME '18:00:00'
      ),
      1, 0
    ) AS assigned_outside_hours,
    IF(
      c.assignment_at IS NOT NULL
      AND TIME(c.assignment_at) >= TIME '12:00:00'
      AND TIME(c.assignment_at) < TIME '13:00:00',
      1, 0
    ) AS assigned_during_lunch,
    COALESCE(
      unr.user_name,
      CONCAT('manychat:', c.manychat_id)
    ) AS user_name,
    DATE(sbd.first_customer_message_at) AS inquiry_date,
    sbd.first_customer_message_at,
    sbd.next_customer_message_at
  FROM cs_assignments c
  LEFT JOIN user_name_realtime unr
    ON unr.user_id = c.manychat_id                        -- [#3] both STRING
  LEFT JOIN owner_agent_current oac
    ON oac.manychat_id = c.manychat_id                    -- [#3] both STRING
  LEFT JOIN session_boundaries sbd
    ON sbd.report_date = c.report_date
   AND sbd.silver_session_id = c.silver_session_id
   AND sbd.manychat_id = c.manychat_id
),

messages_filtered AS (
  SELECT
    CAST(user_id AS STRING) AS manychat_id,               -- [#3] STRING
    datetime AS agent_reply_at,
    sender AS agent_reply_sender
  FROM `gulong-chatbot-459723.manychat_data.messages`
  WHERE business_unit = 'gulong'
    AND role = 'agent'
    AND type = 'msgout_lc'
    AND datetime >= DATETIME '2026-03-01 00:00:00'         -- [COST] partition prune literal
    -- [COST] rolling window option (uncomment to cap scan):
    -- AND datetime >= DATETIME(DATE_SUB(CURRENT_DATE(), INTERVAL 120 DAY))
),

agent_messages AS (
  SELECT
    c.*,
    m.agent_reply_at,
    m.agent_reply_sender
  FROM cohort c
  LEFT JOIN messages_filtered m
    ON m.manychat_id = c.manychat_id
   AND (
     c.first_customer_message_at IS NULL
     OR m.agent_reply_at >= c.first_customer_message_at
   )
   AND (
     c.next_customer_message_at IS NULL
     OR m.agent_reply_at < c.next_customer_message_at
   )
),

first_reply AS (
  SELECT
    report_date,
    report_week,
    report_month,
    agent_name,
    agent_name_source,
    agent_tag_name,
    agent_reporting_group,
    manychat_id,
    silver_session_id,
    assignment_at,
    effective_assignment_at,
    assigned_outside_hours,
    assigned_during_lunch,
    user_name,
    inquiry_date,
    first_customer_message_at,
    agent_reply_at AS first_cs_reply_at,
    agent_reply_sender AS first_cs_reply_sender
  FROM agent_messages
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY report_date, manychat_id
    ORDER BY agent_reply_at, agent_reply_sender
  ) = 1
),

-- Enrichment: same-day inquiry flag, canonical reply sender, SLA computed once.
enriched AS (
  SELECT
    fr.*,
    rs.canonical_agent_name AS reply_sender_canonical,     -- [#2]
    -- Inquiry counts ONLY if a real customer message landed on report_date.
    IF(
      fr.first_customer_message_at IS NOT NULL
      AND DATE(fr.first_customer_message_at) = fr.report_date,
      1, 0
    ) AS is_same_day_inquiry,
    -- [#1] SLA minutes, guarded to same-day reply (else NULL). Computed once.
    CASE
      WHEN fr.first_cs_reply_at IS NOT NULL
        AND DATE(fr.first_cs_reply_at) = fr.report_date
      THEN GREATEST(
        DATETIME_DIFF(fr.first_cs_reply_at, fr.effective_assignment_at, MINUTE)
        - GREATEST(
            DATETIME_DIFF(
              LEAST(
                fr.first_cs_reply_at,
                DATETIME(DATE(fr.effective_assignment_at), TIME '13:00:00')
              ),
              GREATEST(
                fr.effective_assignment_at,
                DATETIME(DATE(fr.effective_assignment_at), TIME '12:00:00')
              ),
              MINUTE
            ),
            0
          ),
        0
      )
      ELSE NULL
    END AS minutes_to_reply_sla_calc
  FROM first_reply fr
  LEFT JOIN agent_aliases_normalized rs
    ON rs.alias_norm = UPPER(
      REGEXP_REPLACE(TRIM(fr.first_cs_reply_sender), r'[^A-Za-z0-9]+', '')
    )
)

SELECT
  en.report_date,
  en.report_week,
  en.report_month,
  en.agent_name,
  LOWER(COALESCE(NULLIF(TRIM(en.agent_name), ''), 'unassigned')) AS agent_name_norm,
  en.agent_name_source,
  en.agent_tag_name,
  en.manychat_id,
  en.silver_session_id,
  en.user_name,
  en.assignment_at,
  en.effective_assignment_at,
  en.assigned_outside_hours,
  en.assigned_during_lunch,
  en.inquiry_date,
  en.first_customer_message_at,
  en.first_cs_reply_at,
  DATE(en.first_cs_reply_at) AS first_cs_reply_date,
  en.first_cs_reply_sender,
  -- canonical resolution of the reply sender for display + matching
  COALESCE(en.reply_sender_canonical, NULLIF(TRIM(en.first_cs_reply_sender), ''), 'No CS Reply') AS reply_agent_name,
  -- [#2] compare canonical-to-canonical so aliases (e.g. Becca Armstrng = Rolyn Ang) match
  IF(
    en.first_cs_reply_at IS NOT NULL
    AND LOWER(TRIM(COALESCE(en.reply_sender_canonical, en.first_cs_reply_sender))) =
        LOWER(TRIM(en.agent_name)),
    1, 0
  ) AS reply_matches_agent_name,
  CASE
    WHEN en.first_cs_reply_at IS NULL THEN 'No CS Reply'
    ELSE 'Has CS Reply'
  END AS reply_status,
  DATETIME_DIFF(en.first_cs_reply_at, en.first_customer_message_at, MINUTE) AS minutes_to_first_reply,
  DATETIME_DIFF(en.first_cs_reply_at, en.assignment_at, MINUTE) AS minutes_from_assignment_to_reply,
  -- [#1] now same-day guarded; NULL for cross-day replies (no inflation)
  en.minutes_to_reply_sla_calc AS minutes_to_reply_sla,
  -- same as above but also excludes Unassigned (original _today semantics)
  IF(en.agent_name != 'Unassigned', en.minutes_to_reply_sla_calc, NULL) AS minutes_to_reply_sla_today,
  IF(
    en.first_cs_reply_at IS NOT NULL
    AND en.first_cs_reply_at < en.effective_assignment_at,
    1, 0
  ) AS replied_outside_hours,
  -- ==== COUNTS: only real same-day inquiries ====
  en.is_same_day_inquiry AS inquiry_count,
  IF(en.is_same_day_inquiry = 1 AND en.first_cs_reply_at IS NOT NULL, 1, 0) AS replied_inquiry_count,
  IF(en.is_same_day_inquiry = 1 AND en.first_cs_reply_at IS NULL, 1, 0) AS no_reply_inquiry_count,
  IF(
    en.is_same_day_inquiry = 1
    AND en.first_cs_reply_at IS NOT NULL
    AND LOWER(TRIM(COALESCE(en.reply_sender_canonical, en.first_cs_reply_sender))) =
        LOWER(TRIM(en.agent_name)),
    1, 0
  ) AS reply_matches_agent_name_count
FROM enriched en