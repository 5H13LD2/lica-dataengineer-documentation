#standardSQL
CREATE OR REPLACE PROCEDURE `gulong-chatbot-459723.gulong_reporting.refresh_first_reply_detail_table`()
BEGIN
  DECLARE refresh_window_days INT64 DEFAULT 35;
  DECLARE refresh_start_date DATE DEFAULT DATE_SUB(
    CURRENT_DATE('Asia/Manila'),
    INTERVAL refresh_window_days DAY
  );

  CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_first_reply_detail`
  PARTITION BY report_date
  CLUSTER BY source_agent_name, reporting_agent_name AS
  WITH historical_rows AS (
    SELECT *
    FROM `gulong-chatbot-459723.gulong_reporting.t_first_reply_detail`
    WHERE report_date < refresh_start_date
  ),
  chatbot_assignments AS (
    SELECT * EXCEPT(rn)
    FROM (
      SELECT
        a.business_unit,
        a.user_id AS manychat_id,
        a.assignment_date AS report_date,
        COALESCE(
          a.silver_session_id,
          CONCAT('assignment:', CAST(a.user_id AS STRING), ':', CAST(a.assignment_date AS STRING))
        ) AS silver_session_id,
        a.assignment_at,
        a.assignment_event_id,
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
        AND a.agent_reporting_group = 'chatbot_jeanel'
        AND a.agent_reporting_name = 'Chatbot/JCo'
    )
    WHERE rn = 1
      AND report_date >= refresh_start_date
  ),
  chat_analysis_chatbot_intents AS (
    SELECT DISTINCT
      a.business_unit,
      a.manychat_id,
      a.silver_session_id,
      a.report_date,
      a.assigned_agent_name,
      a.agent_reporting_name,
      a.agent_reporting_group,
      ca.evaluation_datetime AS moderate_tagged_at,
      'chat_analysis' AS corrected_source
    FROM chatbot_assignments a
    JOIN (
      SELECT
        user_id,
        DATE(evaluation_datetime) AS analysis_date,
        evaluation_datetime,
        intent_rating.top_intent AS top_intent,
        ROW_NUMBER() OVER (
          PARTITION BY user_id, DATE(evaluation_datetime)
          ORDER BY evaluation_datetime DESC
        ) AS rn
      FROM `gulong-chatbot-459723.chat_analysis.chat_analysis_data`
      WHERE platform = 'manychat'
    ) ca
      ON ca.user_id = a.manychat_id
     AND ca.analysis_date = a.report_date
     AND ca.rn = 1
    WHERE LOWER(TRIM(ca.top_intent)) IN ('moderate intent', 'high intent')
  ),
  v7_runtime_chatbot_intents AS (
    SELECT
      a.business_unit,
      a.manychat_id,
      a.silver_session_id,
      a.report_date,
      a.assigned_agent_name,
      a.agent_reporting_name,
      a.agent_reporting_group,
      MIN(t.ts) AS moderate_tagged_at,
      'runtime_v7' AS corrected_source
    FROM chatbot_assignments a
    JOIN `gulong-chatbot-459723.gulong_chatbot_live.turn_trace_log` t
      ON t.business_unit = a.business_unit
     AND t.user_id = a.manychat_id
     AND t.runtime_version = 'v7'
     AND DATE(t.ts) = a.report_date
    WHERE
      REGEXP_CONTAINS(
        LOWER(TO_JSON_STRING(JSON_QUERY(t.tagging, '$.tags_applied'))),
        r'(moderate|high)[ _-]?intent'
      )
      OR REGEXP_CONTAINS(
        LOWER(TO_JSON_STRING(JSON_QUERY(t.tagging, '$.tags_to_add'))),
        r'(moderate|high)[ _-]?intent'
      )
      OR REGEXP_CONTAINS(
        LOWER(TO_JSON_STRING(JSON_QUERY(t.tagging, '$.tags_skipped_existing'))),
        r'(moderate|high)[ _-]?intent'
      )
    GROUP BY
      a.business_unit,
      a.manychat_id,
      a.silver_session_id,
      a.report_date,
      a.assigned_agent_name,
      a.agent_reporting_name,
      a.agent_reporting_group
  ),
  corrected_chatbot_cohort AS (
    SELECT
      report_date,
      manychat_id,
      silver_session_id,
      ANY_VALUE(assigned_agent_name) AS assigned_agent_name,
      ANY_VALUE(agent_reporting_name) AS agent_reporting_name,
      ANY_VALUE(agent_reporting_group) AS agent_reporting_group,
      STRING_AGG(DISTINCT corrected_source ORDER BY corrected_source) AS corrected_source,
      MIN(moderate_tagged_at) AS moderate_tagged_at
    FROM (
      SELECT * FROM chat_analysis_chatbot_intents
      UNION ALL
      SELECT * FROM v7_runtime_chatbot_intents
    )
    GROUP BY report_date, manychat_id, silver_session_id
  ),
  cohort_date_bounds AS (
    SELECT
      DATE_SUB(MIN(report_date), INTERVAL 1 DAY) AS start_date,
      DATE_ADD(MAX(report_date), INTERVAL 1 DAY) AS end_date
    FROM corrected_chatbot_cohort
  ),
  session_dedup AS (
    SELECT
      s.silver_session_id,
      s.user_id AS manychat_id,
      s.user_name,
      s.evidence_contact AS contact_number,
      s.first_user_message_at,
      ROW_NUMBER() OVER (
        PARTITION BY s.silver_session_id
        ORDER BY s.first_user_message_at
      ) AS rn
    FROM `gulong-chatbot-459723.gulong_core.fb_inquiry_sessions` s
    WHERE s.business_unit = 'gulong'
      AND s.channel = 'manychat'
  ),
  session_base_exact AS (
    SELECT
      silver_session_id,
      manychat_id,
      user_name,
      contact_number
    FROM session_dedup
    WHERE rn = 1
  ),
  session_base_fallback AS (
    SELECT * EXCEPT(rn)
    FROM (
      SELECT
        s.user_id AS manychat_id,
        s.user_name,
        s.evidence_contact AS contact_number,
        s.first_user_message_at,
        ROW_NUMBER() OVER (
          PARTITION BY s.user_id
          ORDER BY s.first_user_message_at DESC, s.silver_session_id DESC
        ) AS rn
      FROM `gulong-chatbot-459723.gulong_core.fb_inquiry_sessions` s
      WHERE s.business_unit = 'gulong'
        AND s.channel = 'manychat'
        AND s.user_name IS NOT NULL
    )
    WHERE rn = 1
  ),
  user_name_realtime AS (
    SELECT
      user_id,
      user_name
    FROM `gulong-chatbot-459723.manychat_data.users_current`
    WHERE business_unit = 'gulong'
      AND user_name IS NOT NULL
      AND TRIM(user_name) != ''
  ),
  cohort_messages AS (
    SELECT
      m.user_id AS manychat_id,
      m.datetime,
      m.role,
      m.type,
      m.sender,
      m.text_content
    FROM `gulong-chatbot-459723.manychat_data.messages` m
    CROSS JOIN cohort_date_bounds d
    WHERE m.business_unit = 'gulong'
      AND m.role IN ('user', 'agent')
      AND DATE(m.datetime) BETWEEN d.start_date AND d.end_date
  ),
  contact_from_analysis AS (
    SELECT
      c.report_date,
      c.manychat_id,
      ARRAY_AGG(
        NULLIF(TRIM(a.extracted_data.contact_number), '')
        IGNORE NULLS
        ORDER BY a.evaluation_datetime DESC
        LIMIT 1
      )[SAFE_OFFSET(0)] AS contact_number
    FROM corrected_chatbot_cohort c
    CROSS JOIN cohort_date_bounds d
    JOIN `gulong-chatbot-459723.chat_analysis.chat_analysis_data` a
      ON a.user_id = c.manychat_id
     AND LOWER(COALESCE(a.platform, 'manychat')) = 'manychat'
     AND DATE(a.evaluation_datetime) BETWEEN d.start_date AND d.end_date
     AND DATE(a.evaluation_datetime) BETWEEN DATE_SUB(c.report_date, INTERVAL 1 DAY)
                                         AND DATE_ADD(c.report_date, INTERVAL 1 DAY)
    WHERE NULLIF(TRIM(a.extracted_data.contact_number), '') IS NOT NULL
    GROUP BY c.report_date, c.manychat_id
  ),
  contact_from_messages AS (
    SELECT
      c.report_date,
      c.manychat_id,
      ARRAY_AGG(
        REGEXP_EXTRACT(
          m.text_content,
          r'(?i)(\+?63[\s\-]?9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}|09\d{9})'
        )
        IGNORE NULLS
        ORDER BY m.datetime DESC
        LIMIT 1
      )[SAFE_OFFSET(0)] AS contact_number
    FROM corrected_chatbot_cohort c
    JOIN cohort_messages m
      ON m.manychat_id = c.manychat_id
     AND m.role = 'user'
     AND DATE(m.datetime) BETWEEN DATE_SUB(c.report_date, INTERVAL 1 DAY)
                              AND DATE_ADD(c.report_date, INTERVAL 1 DAY)
    WHERE REGEXP_CONTAINS(
      m.text_content,
      r'(?i)(\+?63[\s\-]?9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}|09\d{9})'
    )
    GROUP BY c.report_date, c.manychat_id
  ),
  moderate_event AS (
    SELECT
      m.silver_session_id,
      m.user_id AS manychat_id,
      m.first_moderate_at,
      ROW_NUMBER() OVER (
        PARTITION BY m.silver_session_id
        ORDER BY m.first_moderate_at
      ) AS rn
    FROM `gulong-chatbot-459723.gulong_core.moderate_intent_sessions` m
    WHERE m.business_unit = 'gulong'
      AND m.channel = 'manychat'
      AND m.validated_moderate = TRUE
  ),
  moderate_base AS (
    SELECT
      silver_session_id,
      manychat_id,
      first_moderate_at
    FROM moderate_event
    WHERE rn = 1
  ),
  message_first_customer AS (
    SELECT
      c.report_date,
      c.manychat_id,
      c.silver_session_id,
      MIN(m.datetime) AS first_customer_message_at
    FROM corrected_chatbot_cohort c
    JOIN cohort_messages m
      ON m.manychat_id = c.manychat_id
     AND m.role = 'user'
     AND DATE(m.datetime) BETWEEN DATE_SUB(c.report_date, INTERVAL 1 DAY)
                              AND DATE_ADD(c.report_date, INTERVAL 1 DAY)
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
      COALESCE(c.assigned_agent_name, c.agent_reporting_name, 'Unassigned') AS reporting_agent_name,
      c.agent_reporting_name AS source_agent_name,
      c.agent_reporting_group,
      c.corrected_source,
      c.moderate_tagged_at,
      CASE
        WHEN c.moderate_tagged_at IS NULL THEN NULL
        WHEN TIME(c.moderate_tagged_at) >= TIME '18:00:00'
          THEN DATETIME(DATE_ADD(DATE(c.moderate_tagged_at), INTERVAL 1 DAY), TIME '09:00:00')
        WHEN TIME(c.moderate_tagged_at) < TIME '09:00:00'
          THEN DATETIME(DATE(c.moderate_tagged_at), TIME '09:00:00')
        WHEN TIME(c.moderate_tagged_at) >= TIME '12:00:00'
             AND TIME(c.moderate_tagged_at) < TIME '13:00:00'
          THEN DATETIME(DATE(c.moderate_tagged_at), TIME '13:00:00')
        ELSE c.moderate_tagged_at
      END AS effective_moderate_tagged_at,
      IF(
        c.moderate_tagged_at IS NOT NULL
        AND (
          TIME(c.moderate_tagged_at) < TIME '09:00:00'
          OR TIME(c.moderate_tagged_at) >= TIME '18:00:00'
        ),
        1, 0
      ) AS tagged_outside_hours,
      IF(
        c.moderate_tagged_at IS NOT NULL
        AND TIME(c.moderate_tagged_at) >= TIME '12:00:00'
        AND TIME(c.moderate_tagged_at) < TIME '13:00:00',
        1, 0
      ) AS tagged_during_lunch,
      c.manychat_id,
      c.silver_session_id,
      COALESCE(
        se.user_name,
        sf.user_name,
        unr.user_name,
        CONCAT('manychat:', CAST(c.manychat_id AS STRING))
      ) AS user_name,
      CASE
        WHEN se.user_name IS NOT NULL OR sf.user_name IS NOT NULL THEN 'session'
        WHEN unr.user_name IS NOT NULL THEN 'manychat_realtime'
        ELSE 'synthetic'
      END AS name_source,
      COALESCE(
        se.contact_number,
        sf.contact_number,
        cfa.contact_number,
        cfm.contact_number
      ) AS contact_number,
      CASE
        WHEN se.contact_number IS NOT NULL OR sf.contact_number IS NOT NULL THEN 'session_evidence'
        WHEN cfa.contact_number IS NOT NULL THEN 'chat_analysis'
        WHEN cfm.contact_number IS NOT NULL THEN 'message_regex'
        ELSE NULL
      END AS contact_source,
      DATE(sbd.first_customer_message_at) AS inquiry_date,
      sbd.first_customer_message_at,
      sbd.next_customer_message_at,
      mb.first_moderate_at
    FROM corrected_chatbot_cohort c
    LEFT JOIN session_base_exact se
      ON se.silver_session_id = c.silver_session_id
     AND se.manychat_id = c.manychat_id
    LEFT JOIN session_base_fallback sf
      ON sf.manychat_id = c.manychat_id
    LEFT JOIN user_name_realtime unr
      ON unr.user_id = CAST(c.manychat_id AS STRING)
    LEFT JOIN contact_from_analysis cfa
      ON cfa.report_date = c.report_date
     AND cfa.manychat_id = c.manychat_id
    LEFT JOIN contact_from_messages cfm
      ON cfm.report_date = c.report_date
     AND cfm.manychat_id = c.manychat_id
    LEFT JOIN session_boundaries sbd
      ON sbd.report_date = c.report_date
     AND sbd.silver_session_id = c.silver_session_id
     AND sbd.manychat_id = c.manychat_id
    LEFT JOIN moderate_base mb
      ON mb.silver_session_id = c.silver_session_id
     AND mb.manychat_id = c.manychat_id
  ),
  messages_filtered AS (
    SELECT
      manychat_id,
      datetime AS agent_reply_at,
      sender AS agent_reply_sender
    FROM cohort_messages
    WHERE role = 'agent'
      AND type = 'msgout_lc'
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
       c.moderate_tagged_at IS NULL
       OR m.agent_reply_at >= c.moderate_tagged_at
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
      reporting_agent_name,
      source_agent_name,
      agent_reporting_group,
      corrected_source,
      moderate_tagged_at,
      effective_moderate_tagged_at,
      tagged_outside_hours,
      tagged_during_lunch,
      manychat_id,
      silver_session_id,
      user_name,
      name_source,
      contact_number,
      contact_source,
      inquiry_date,
      first_customer_message_at,
      first_moderate_at,
      agent_reply_at AS first_cs_reply_at,
      agent_reply_sender AS first_cs_reply_sender
    FROM agent_messages
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY report_date, manychat_id
      ORDER BY agent_reply_at, agent_reply_sender
    ) = 1
  ),
  recent_rows AS (
    SELECT
      fr.report_date,
      fr.report_week,
      fr.report_month,
      fr.reporting_agent_name,
      fr.source_agent_name,
      fr.agent_reporting_group,
      fr.corrected_source,
      fr.moderate_tagged_at,
      fr.effective_moderate_tagged_at,
      fr.tagged_outside_hours,
      fr.tagged_during_lunch,
      DATE(fr.moderate_tagged_at) AS moderate_tagged_date,
      DATE(fr.effective_moderate_tagged_at) AS effective_moderate_tagged_date,
      b.agent_group,
      b.agent_key,
      b.total_inquiries,
      b.total_moderate_intents,
      b.total_moderate_sessions,
      b.total_bookings,
      fr.silver_session_id,
      fr.manychat_id,
      fr.user_name,
      fr.name_source,
      fr.contact_number,
      fr.contact_source,
      fr.inquiry_date,
      fr.first_customer_message_at,
      fr.first_moderate_at,
      fr.first_cs_reply_at,
      DATE(fr.first_cs_reply_at) AS first_cs_reply_date,
      fr.first_cs_reply_sender,
      COALESCE(NULLIF(TRIM(fr.first_cs_reply_sender), ''), 'No CS Reply') AS reply_agent_name,
      LOWER(COALESCE(NULLIF(TRIM(fr.first_cs_reply_sender), ''), 'no cs reply')) AS reply_agent_name_norm,
      CASE
        WHEN fr.first_cs_reply_at IS NULL THEN 'No CS Reply'
        ELSE 'Has CS Reply'
      END AS reply_status,
      DATETIME_DIFF(fr.first_cs_reply_at, fr.first_customer_message_at, MINUTE) AS minutes_to_first_reply,
      DATETIME_DIFF(fr.first_cs_reply_at, fr.first_moderate_at, MINUTE) AS minutes_from_moderate_to_first_reply,
      DATETIME_DIFF(fr.first_cs_reply_at, fr.moderate_tagged_at, MINUTE) AS minutes_from_tagged_to_first_reply,
      GREATEST(
        DATETIME_DIFF(fr.first_cs_reply_at, fr.effective_moderate_tagged_at, MINUTE)
        - GREATEST(
            DATETIME_DIFF(
              LEAST(
                fr.first_cs_reply_at,
                DATETIME(DATE(fr.effective_moderate_tagged_at), TIME '13:00:00')
              ),
              GREATEST(
                fr.effective_moderate_tagged_at,
                DATETIME(DATE(fr.effective_moderate_tagged_at), TIME '12:00:00')
              ),
              MINUTE
            ),
            0
          ),
        0
      ) AS minutes_to_reply_sla,
      CASE
        WHEN fr.first_cs_reply_at IS NOT NULL
          AND fr.reporting_agent_name != 'Unassigned'
          AND DATE(fr.first_cs_reply_at) = fr.report_date
        THEN GREATEST(
          DATETIME_DIFF(fr.first_cs_reply_at, fr.effective_moderate_tagged_at, MINUTE)
          - GREATEST(
              DATETIME_DIFF(
                LEAST(
                  fr.first_cs_reply_at,
                  DATETIME(DATE(fr.effective_moderate_tagged_at), TIME '13:00:00')
                ),
                GREATEST(
                  fr.effective_moderate_tagged_at,
                  DATETIME(DATE(fr.effective_moderate_tagged_at), TIME '12:00:00')
                ),
                MINUTE
              ),
              0
            ),
          0
        )
        ELSE NULL
      END AS minutes_to_reply_sla_today,
      IF(
        fr.first_cs_reply_at IS NOT NULL
        AND fr.first_cs_reply_at < fr.effective_moderate_tagged_at,
        1, 0
      ) AS replied_outside_hours,
      CAST(1 AS INT64) AS moderate_count,
      CAST(1 AS INT64) AS detail_row_count,
      CAST(IF(fr.first_cs_reply_at IS NOT NULL, 1, 0) AS INT64) AS reply_in_moderate_count,
      CAST(IF(fr.first_cs_reply_at IS NOT NULL, 1, 0) AS INT64) AS replied_session_count,
      CAST(IF(fr.first_cs_reply_at IS NULL, 1, 0) AS INT64) AS no_reply_session_count,
      CAST(IF(fr.first_cs_reply_at IS NOT NULL, 1, 0) AS INT64) AS agent_first_reply_count,
      SAFE_DIVIDE(
        COUNTIF(fr.first_cs_reply_at IS NOT NULL) OVER (PARTITION BY fr.report_date),
        COUNT(*) OVER (PARTITION BY fr.report_date)
      ) AS daily_response_rate
    FROM first_reply fr
    LEFT JOIN `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion` b
      ON b.report_date = fr.report_date
     AND b.agent_name = fr.source_agent_name
  )
  SELECT * FROM historical_rows
  UNION ALL
  SELECT * FROM recent_rows;
END;
