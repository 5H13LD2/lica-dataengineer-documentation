#standardSQL
CREATE OR REPLACE VIEW
  `gulong-chatbot-459723.gulong_reporting.v_looker_cs_inquiry_reply_detail`
AS
WITH cs_assignments AS (
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

-- real-time name mula sa ManyChat users_current
user_name_realtime AS (
  SELECT
    user_id,
    user_name
  FROM `gulong-chatbot-459723.manychat_data.users_current`
  WHERE business_unit = 'gulong'
    AND user_name IS NOT NULL
    AND TRIM(user_name) != ''
),

-- unang customer message sa araw ng assignment (±1 day window)
message_first_customer AS (
  SELECT
    c.report_date,
    c.manychat_id,
    c.silver_session_id,
    MIN(m.datetime) AS first_customer_message_at
  FROM cs_assignments c
  JOIN `gulong-chatbot-459723.manychat_data.messages` m
    ON m.business_unit = 'gulong'
   AND m.user_id = c.manychat_id
   AND m.role = 'user'
   AND m.datetime >= DATETIME '2026-03-01 00:00:00'
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
    COALESCE(c.assigned_agent_name, c.agent_reporting_name, 'Unassigned') AS agent_name,
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
      CONCAT('manychat:', CAST(c.manychat_id AS STRING))
    ) AS user_name,
    DATE(sbd.first_customer_message_at) AS inquiry_date,
    sbd.first_customer_message_at,
    sbd.next_customer_message_at
  FROM cs_assignments c
  LEFT JOIN user_name_realtime unr
    ON unr.user_id = CAST(c.manychat_id AS STRING)
  LEFT JOIN session_boundaries sbd
    ON sbd.report_date = c.report_date
   AND sbd.silver_session_id = c.silver_session_id
   AND sbd.manychat_id = c.manychat_id
),

messages_filtered AS (
  SELECT
    user_id AS manychat_id,
    datetime AS agent_reply_at,
    sender AS agent_reply_sender
  FROM `gulong-chatbot-459723.manychat_data.messages`
  WHERE business_unit = 'gulong'
    AND role = 'agent'
    AND type = 'msgout_lc'
    AND datetime >= DATETIME '2026-03-01 00:00:00'
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
)

SELECT
  fr.report_date,
  fr.report_week,
  fr.report_month,
  fr.agent_name,
  fr.manychat_id,
  fr.silver_session_id,
  fr.user_name,
  fr.assignment_at,
  fr.effective_assignment_at,
  fr.assigned_outside_hours,
  fr.assigned_during_lunch,
  fr.inquiry_date,
  fr.first_customer_message_at,
  fr.first_cs_reply_at,
  DATE(fr.first_cs_reply_at) AS first_cs_reply_date,
  fr.first_cs_reply_sender,
  COALESCE(NULLIF(TRIM(fr.first_cs_reply_sender), ''), 'No CS Reply') AS reply_agent_name,
  CASE
    WHEN fr.first_cs_reply_at IS NULL THEN 'No CS Reply'
    ELSE 'Has CS Reply'
  END AS reply_status,
  DATETIME_DIFF(fr.first_cs_reply_at, fr.first_customer_message_at, MINUTE) AS minutes_to_first_reply,
  DATETIME_DIFF(fr.first_cs_reply_at, fr.assignment_at, MINUTE) AS minutes_from_assignment_to_reply,
  GREATEST(
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
  ) AS minutes_to_reply_sla,
  CASE
    WHEN fr.first_cs_reply_at IS NOT NULL
      AND fr.agent_name != 'Unassigned'
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
  END AS minutes_to_reply_sla_today,
  IF(
    fr.first_cs_reply_at IS NOT NULL
    AND fr.first_cs_reply_at < fr.effective_assignment_at,
    1, 0
  ) AS replied_outside_hours,
  1 AS inquiry_count,
  IF(fr.first_cs_reply_at IS NOT NULL, 1, 0) AS replied_inquiry_count,
  IF(fr.first_cs_reply_at IS NULL, 1, 0) AS no_reply_inquiry_count
FROM first_reply fr
