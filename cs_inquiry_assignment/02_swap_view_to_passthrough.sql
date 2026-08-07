-- =====================================================================
-- STEP 2: Replace the heavy view with a thin passthrough over the table.
-- Same view name -> nothing downstream breaks. Every consumer
-- (Looker + t_moderate_* pipeline in follow_ups_manual.md) keeps
-- reading `v_looker_first_reply_detail` but now gets the precomputed
-- table instead of a live 6-scan recompute.
--
-- Run AFTER STEP 1 has successfully built t_first_reply_detail.
-- =====================================================================

CREATE OR REPLACE VIEW
  `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
AS
SELECT * FROM `gulong-chatbot-459723.gulong_reporting.t_first_reply_detail`;
