-- Latest operational SQL for `t_moderate_booking_reconstruction`.
-- Use these statements in order:
-- 1. Rebuild the physical table from the live reconstruction view.
-- 2. Backfill `first_cs_reply_at`, `reply_status`, and `reply_agent_name`
--    from raw ManyChat agent messages for rows that still have null reply fields.

CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`;

UPDATE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction` AS t
SET
  first_cs_reply_at = c.backfilled_first_cs_reply_at,
  reply_status = 'Has CS Reply',
  reply_agent_name = c.backfilled_reply_agent_name,
  reply_agent_name_norm = LOWER(TRIM(c.backfilled_reply_agent_name)),
  minutes_to_first_reply = DATETIME_DIFF(c.backfilled_first_cs_reply_at, t.first_customer_message_at, MINUTE)
FROM (
  SELECT
    order_id,
    candidate_first_cs_reply_at AS backfilled_first_cs_reply_at,
    candidate_reply_agent_name AS backfilled_reply_agent_name
  FROM (
    SELECT
      t.order_id,
      m.datetime AS candidate_first_cs_reply_at,
      m.sender AS candidate_reply_agent_name,
      ROW_NUMBER() OVER (
        PARTITION BY t.order_id
        ORDER BY
          CASE WHEN m.datetime <= t.booking_at THEN 0 ELSE 1 END,
          m.datetime,
          m.message_id
      ) AS rn
    FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction` t
    JOIN `gulong-chatbot-459723.manychat_data.messages` m
      ON m.datetime >= DATETIME '2025-01-01 00:00:00'
     AND m.datetime < DATETIME '2030-01-01 00:00:00'
     AND m.user_id = t.manychat_id
     AND m.business_unit = 'gulong'
     AND m.role = 'agent'
     AND m.type = 'msgout_lc'
     AND m.datetime >= t.first_customer_message_at
    WHERE t.first_cs_reply_at IS NULL
      AND t.manychat_id IS NOT NULL
      AND t.first_customer_message_at IS NOT NULL
  )
  WHERE rn = 1
) AS c
WHERE t.order_id = c.order_id;
