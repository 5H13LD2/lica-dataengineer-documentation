# Chatbot/JCo -> Sarah Reporting Notes

## Scope

This note documents the work done to investigate and rebuild reporting for:

- `gulong_reporting.p_looker_agent_daily_conversion`
- `gulong_reporting.v_looker_chatbotjco_sarah_base`
- `gulong_reporting.v_looker_first_reply_detail`
- `gulong_reporting.v_looker_chatbotjco_sarah_report`
- the related Looker Studio custom queries

Main business goal:

- treat `Chatbot/JCo` as Sarah's reporting bucket
- keep the official `total_moderate_intents` from `p_looker_agent_daily_conversion`
- show session/user-level details such as `manychat_id`, `user_name`, timestamps, and first reply

---

## Source Tables And Views Used

### Official reporting source

- `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
  - official daily reporting table
  - source of truth for `Chatbot/JCo` `total_moderate_intents`

### Views created for reporting

- `gulong-chatbot-459723.gulong_reporting.v_looker_chatbotjco_sarah_base`
  - daily base view
  - remaps `Chatbot/JCo` to `sarah gulongph` for reporting display

- `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  - row-level detail view
  - intended to expose one corrected moderate row per `manychat_id` per `report_date`
  - includes customer and CS reply timestamps

- `gulong-chatbot-459723.gulong_reporting.v_looker_chatbotjco_sarah_report`
  - daily rollup / report-layer view
  - combines official moderate totals with reconstructed first-reply metrics

### Core operational tables used in investigation

- `gulong-chatbot-459723.gulong_core.inquiry_assignments`
- `gulong-chatbot-459723.gulong_core.inquiry_sessions`
- `gulong-chatbot-459723.gulong_core.fb_inquiry_sessions`
- `gulong-chatbot-459723.gulong_core.moderate_intent_sessions`
- `gulong-chatbot-459723.gulong_core.moderate_intent_inquiries`
- `gulong-chatbot-459723.gulong_core.agent_aliases`
- `gulong-chatbot-459723.gulong_core.fb_response_time_user_agent_daily`
- `gulong-chatbot-459723.gulong_core.fb_response_time_turns`

### Chatbot / analysis sources used in corrected cohort logic

- `gulong-chatbot-459723.chat_analysis.chat_analysis_data`
- `gulong-chatbot-459723.gulong_chatbot_live.turn_trace_log`
- `gulong-chatbot-459723.manychat_data.messages`

### Metadata / procedure inspection sources used

- `region-asia-southeast1.INFORMATION_SCHEMA.ROUTINES`
- `region-asia-southeast1.INFORMATION_SCHEMA.JOBS_BY_PROJECT`
- `gulong-chatbot-459723.gulong_reporting.p_dashboard_physical_refresh_log`

---

## Data Lineage Diagram

```text
gulong_core.inquiry_assignments
  -> Chatbot/JCo assignment seed
  -> corrected chatbot cohort ownership

gulong_core.inquiry_sessions / fb_inquiry_sessions
  -> session windows
  -> user_name
  -> first customer message
  -> contact context

gulong_core.moderate_intent_sessions
  -> validated moderate session facts
  -> moderate_evidence_* fields

chat_analysis.chat_analysis_data
  -> top_intent
  -> extracted_data.* evidence

gulong_chatbot_live.turn_trace_log
  -> runtime_v7 moderate/high intent tags

manychat_data.messages
  -> user message history
  -> CS reply timestamps

inquiry_assignments
  + chat_analysis
  + turn_trace_log
  -> hot_corrected_chatbot_moderates

hot_corrected_chatbot_moderates
  + hot_moderate_by_original_agent_day
  -> stg_p_looker_agent_daily_conversion

stg_p_looker_agent_daily_conversion
  -> p_looker_agent_daily_conversion

p_looker_agent_daily_conversion
  -> v_looker_chatbotjco_sarah_base

corrected chatbot cohort
  + session context
  + moderate evidence
  + manychat messages
  -> v_looker_first_reply_detail

v_looker_chatbotjco_sarah_base
  + v_looker_first_reply_detail
  -> v_looker_chatbotjco_sarah_report
```

---

## What We Learned About The Official Cohort

The official `Chatbot/JCo` count in `p_looker_agent_daily_conversion` is not just:

- `original_assigned_agent_name = 'Jeanel Co'`
- or `agent_reporting_name = 'Chatbot/JCo'`
- or all Sarah sessions
- or plain `validated_moderate` sessions

It uses corrected chatbot attribution logic upstream.

### Exact upstream logic found

We inspected the stored procedure DDL and found the exact logic inside:

- `gulong_reporting.refresh_dashboard_physical_hot_full()`

This procedure creates:

- `hot_corrected_chatbot_moderates`
- `stg_p_looker_agent_daily_conversion`

### `hot_corrected_chatbot_moderates`

This temporary table:

1. starts from `hot_inquiry_assignments`
2. keeps only rows where:
   - `business_unit = 'gulong'`
   - `agent_reporting_group = 'chatbot_jeanel'`
   - `agent_reporting_name = 'Chatbot/JCo'`
3. dedupes one row per:
   - `business_unit`
   - `user_id`
   - `assignment_date`
4. marks a row as corrected moderate if either:
   - same-day `chat_analysis.chat_analysis_data` latest record has `top_intent IN ('moderate intent', 'high intent')`
   - or same-day `turn_trace_log` V7 tags contain moderate/high intent

Final aggregation:

- `COUNT(DISTINCT user_id) AS total_moderate_intents`
- `COUNT(DISTINCT silver_session_id) AS total_moderate_sessions`

### `stg_p_looker_agent_daily_conversion`

This stage:

1. computes base moderate counts from `hot_moderate_by_original_agent_day`
2. maps `original_assigned_agent_name = 'jeanel co'` to `Chatbot/JCo`
3. overrides `Chatbot/JCo` moderate counts using:

```sql
GREATEST(c.total_moderate_intents, b.total_moderate_intents)
```

where:

- `c` = corrected chatbot counts from `hot_corrected_chatbot_moderates`
- `b` = base moderate counts

This is why official `Chatbot/JCo` counts can be higher than simple moderate-session rebuilds.

---

## Cohort Definition Used In Rebuilt Detail Logic

For exact `manychat_id` matching to official `total_moderate_intents`, the rebuilt detail query must use:

- `inquiry_assignments`
- filtered to `agent_reporting_group = 'chatbot_jeanel'`
- filtered to `agent_reporting_name = 'Chatbot/JCo'`
- corrected by:
  - same-day `chat_analysis` moderate/high top intent
  - or same-day V7 runtime moderate/high tags

Correct detail grain:

- one row per `report_date + manychat_id`

Reason:

- official `total_moderate_intents` is a distinct `user_id` metric
- not a distinct `silver_session_id` metric

---

## Problems Encountered

### 1. Reconstructed detail rows did not match official moderate totals

Observed issue:

- official `p_looker_agent_daily_conversion` showed counts like:
  - `2026-07-14`: `21`
  - `2026-07-15`: `16`
  - `2026-07-16`: `17`
  - `2026-07-17`: `22`
- earlier session rebuilds did not match those numbers

Cause:

- those rebuilds were based on `moderate_intent_sessions`, Sarah filters, or `Jeanel Co` ownership
- official reporting used corrected chatbot logic instead

Fix:

- rebuilt query from the exact corrected chatbot cohort logic
- matched by `manychat_id`

### 2. Detail counts matched on historical dates but not same-day

Observed issue:

- historical days matched exactly
- current-day `2026-07-18` sometimes returned more detail rows than official reporting

Cause:

- `p_looker_agent_daily_conversion` is a refreshed snapshot
- custom query / view rebuild used live raw source tables
- raw sources can advance after the last refresh

Fix:

- added `refresh_cutoff` from `p_dashboard_physical_refresh_log`
- filtered chat analysis, V7 runtime, and messages to `<= cutoff_dt`

Note:

- this reduces drift but same-day perfect parity can still break if source records arrive late with older timestamps
- the only perfect fix would be persisting the corrected user cohort during the same reporting refresh

### 3. `manychat_data.messages` partition error

Observed issue:

- BigQuery error:
  - cannot query `manychat_data.messages` without a partition filter on `datetime`

Fix:

- added direct filter like:

```sql
AND datetime >= DATETIME '2026-03-01 00:00:00'
```

and later:

```sql
AND datetime <= refresh_cutoff.cutoff_dt
```

### 4. Query syntax issues

Observed issues:

- missing closing `)` in calculated fields
- missing `refresh_cutoff` CTE

Fix:

- added full `refresh_cutoff` CTE at the top
- corrected the broken `IF(...)` expression

### 5. Custom query returned fewer rows than official counts

Observed issue:

- a custom query returned `17` instead of `22` on `2026-07-17`

Cause:

- it used:
  - `original_assigned_agent_name = 'jeanel co'`
  - `moderate_intent_sessions`
  - a custom `synthetic_signals.moderate_intent` path
- it did not use the official corrected `Chatbot/JCo` user-day cohort

Fix:

- rewrote the custom query to use the corrected cohort logic:
  - `inquiry_assignments`
  - `chat_analysis`
  - `turn_trace_log` V7 tag arrays

### 6. Moderate evidence fields were often null

Observed issue:

- some rows had `moderate_triggered_at` but null:
  - `moderate_evidence_tire_size`
  - `moderate_evidence_location`

Cause:

- corrected cohort was broader than `moderate_intent_sessions`
- some rows came from runtime correction only
- some rows used synthetic `silver_session_id`
- some rows had no exact session match
- some rows had chat analysis rows, but the latest row had `No Intent` and no extracted evidence

Fix:

- added session resolution logic:
  - exact `silver_session_id` match first
  - fallback to nearest same-day user session if exact session is missing
- this improved `session_start_at` and `session_end_at`
- which improved evidence backfill from `chat_analysis`

---

## Evidence Investigation Findings

We checked rows with:

- `moderate_triggered_at IS NOT NULL`
- but null tire size / location evidence

Finding:

- these were mostly not `High Intent` or `Moderate Intent` chat-analysis rows with empty extracted fields
- they were mostly:
  - `runtime_v7` corrected rows
  - whose available chat-analysis row in the session window was `No Intent`
  - or had no matched chat-analysis row at all

This means:

- a row can be counted as moderate
- have a valid moderate trigger timestamp
- but still have no structured evidence fields

Reason:

- moderate classification and evidence extraction are different things

Business interpretation:

- `total_moderates` = intent/routing metric
- `moderates_with_evidence` = data completeness / actionability metric

Example:

- `22` total moderates
- `17` with evidence
- `5` without evidence

---

## Reporting Recommendation

### Use for official reporting totals

Use:

- `gulong_reporting.p_looker_agent_daily_conversion`
- or derived `v_looker_chatbotjco_sarah_base`

for:

- `total_moderate_intents`
- official agent/day count reporting

### Use for detail reporting

Use:

- `gulong_reporting.v_looker_first_reply_detail`

for:

- `manychat_id`
- `user_name`
- `contact_number`
- `first_customer_message_at`
- `moderate_tagged_at`
- `moderate_tagged_source`
- `first_cs_reply_at`
- `first_cs_reply_sender`

### Use for dashboard KPI rollups

Use:

- `gulong_reporting.v_looker_chatbotjco_sarah_report`

for:

- daily scorecards
- trend lines
- response rates
- Sarah first reply metrics

---

## Looker Studio / Data Studio Guidance

### Main dashboard source

- `gulong_reporting.v_looker_chatbotjco_sarah_report`

### Detail table source

- `gulong_reporting.v_looker_first_reply_detail`

### Recommended dashboard metrics

- `total_moderate_intents`
- `sarah_first_reply_count`
- `replied_session_count`
- `no_reply_session_count`
- `avg_sarah_first_reply_minutes`

### Recommended detail fields

- `report_date`
- `manychat_id`
- `user_name`
- `contact_number`
- `moderate_tagged_at`
- `moderate_tagged_source`
- `first_customer_message_at`
- `first_moderate_at`
- `first_cs_reply_at`
- `first_cs_reply_sender`

---

## Dataset Structure From Inquiry To Moderate

### 1. Inquiry ownership layer

- Dataset: `gulong_core`
- Table: `inquiry_assignments`

Purpose:

- identify reporting ownership for `Chatbot/JCo`
- seed the corrected chatbot cohort

Important fields:

- `business_unit`
- `user_id`
- `assignment_date`
- `assignment_at`
- `silver_session_id`
- `agent_reporting_group`
- `agent_reporting_name`
- `assigned_agent_name`

### 2. Session context layer

- Dataset: `gulong_core`
- Tables:
  - `inquiry_sessions`
  - `fb_inquiry_sessions`

Purpose:

- define session window for evidence lookup
- provide display and customer timestamps

Important fields:

- `session_start_at`
- `session_end_at`
- `first_user_message_at`
- `user_name`
- `evidence_contact`
- `original_assigned_agent_name`

### 3. Moderate validation layer

- Dataset: `gulong_core`
- Table: `moderate_intent_sessions`

Purpose:

- store validated moderate session facts
- store direct structured evidence if available

Important fields:

- `first_moderate_at`
- `first_moderate_source`
- `validated_moderate`
- `moderate_evidence_tire_size`
- `moderate_evidence_brand`
- `moderate_evidence_location`
- `moderate_evidence_contact`

### 4. Intent correction layer

- Datasets:
  - `chat_analysis`
  - `gulong_chatbot_live`

Tables:

- `chat_analysis.chat_analysis_data`
- `gulong_chatbot_live.turn_trace_log`

Purpose:

- identify corrected moderate users for `Chatbot/JCo`
- supply intent and extracted evidence signals

### 5. Raw conversation layer

- Dataset: `manychat_data`
- Table: `messages`

Purpose:

- get user messages
- derive first CS reply timestamps
- fallback contact extraction from message text

### 6. Reporting layer

- Dataset: `gulong_reporting`

Objects:

- `p_looker_agent_daily_conversion`
- `v_looker_chatbotjco_sarah_base`
- `v_looker_first_reply_detail`
- `v_looker_chatbotjco_sarah_report`
- `p_dashboard_physical_refresh_log`

---

## Infrastructure And Engineering Manual

### BigQuery reporting architecture

- `gulong_core` contains curated operational tables.
- `chat_analysis` contains classified intent and extracted entities.
- `gulong_chatbot_live` contains runtime tagging traces.
- `manychat_data` contains raw message history.
- `gulong_reporting` contains dashboard-facing tables and views.

### Official reporting refresh

Important procedure found:

- `gulong_reporting.refresh_dashboard_physical_hot_full()`

Important audit table:

- `gulong_reporting.p_dashboard_physical_refresh_log`

The procedure builds temp objects including:

- `hot_inquiry_assignments`
- `hot_inquiry_sessions`
- `hot_moderate_intent_sessions`
- `hot_turn_trace_v7`
- `hot_corrected_chatbot_moderates`
- `stg_p_looker_agent_daily_conversion`

### How to inspect the official logic

1. Query BigQuery routines metadata.
2. Read the stored procedure DDL.
3. Search inside the procedure for:
   - `hot_corrected_chatbot_moderates`
   - `stg_p_looker_agent_daily_conversion`
4. Trace which source tables feed each temp table.

Useful metadata sources:

- `region-asia-southeast1.INFORMATION_SCHEMA.ROUTINES`
- `region-asia-southeast1.INFORMATION_SCHEMA.JOBS_BY_PROJECT`

### How to verify official daily Chatbot/JCo counts

```sql
SELECT
  report_date,
  agent_name,
  total_moderate_intents
FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
WHERE agent_name = 'Chatbot/JCo'
ORDER BY report_date DESC;
```

### How to rebuild the corrected Chatbot/JCo cohort

1. Start from `gulong_core.inquiry_assignments`.
2. Filter:
   - `agent_reporting_group = 'chatbot_jeanel'`
   - `agent_reporting_name = 'Chatbot/JCo'`
3. Deduplicate one row per:
   - `business_unit`
   - `user_id`
   - `assignment_date`
4. Join same-day `chat_analysis.chat_analysis_data`.
5. Keep latest same-day row where `top_intent IN ('moderate intent', 'high intent')`.
6. Join same-day `gulong_chatbot_live.turn_trace_log`.
7. Keep rows where V7 tagging shows moderate/high intent.
8. Union both corrected sources.
9. Aggregate one row per `report_date + manychat_id`.

### How to align a custom query with official reporting

1. Read the latest reporting cutoff from `p_dashboard_physical_refresh_log`.
2. Apply `<= cutoff_dt` to:
   - `chat_analysis` timestamps
   - `turn_trace_log.ts`
   - `manychat_data.messages.datetime`
3. Build the corrected cohort first.
4. Only after that, enrich with:
   - session context
   - moderate evidence
   - reply timestamps

### How to enrich evidence fields

Preferred evidence source order:

1. `moderate_intent_sessions.moderate_evidence_*`
2. `chat_analysis.chat_analysis_data.extracted_data.*`
3. user-message regex fallback for contact number

Engineering note:

- Evidence fill improves if the query resolves a usable session window first.
- Exact `silver_session_id` match should be tried first.
- If missing, nearest same-day user session fallback is a practical backup.

### How to debug evidence nulls

1. Find rows with `moderate_triggered_at IS NOT NULL`.
2. Check if tire size or location is null.
3. Check whether the row came from:
   - `chat_analysis`
   - `runtime_v7`
   - or both
4. Inspect the latest session-window chat-analysis row:
   - `top_intent`
   - tire size
   - location
   - contact number
5. Check whether another row in the same session window has evidence.

### How to debug same-day mismatch

1. Compare official `p_looker_agent_daily_conversion` counts with rebuilt detail rows.
2. Check `MAX(refresh_finished_at)` in `p_dashboard_physical_refresh_log`.
3. Inspect rows that became eligible after the cutoff.
4. Treat same-day drift as snapshot-vs-live mismatch unless a persisted corrected cohort exists.

### Production recommendation

For perfect same-day parity, persist the corrected cohort during the same reporting refresh.

Suggested physical table:

- `gulong_reporting.p_chatbotjco_corrected_users_daily`

Suggested fields:

- `report_date`
- `manychat_id`
- `silver_session_id`
- `moderate_tagged_at`
- `moderate_tagged_source`

Then build detail reporting from that physical snapshot instead of rebuilding from live raw tables.

---

## Final State Reached In This Investigation

### Confirmed

- official `Chatbot/JCo` count comes from corrected chatbot logic, not simple Jeanel/Sarah filters
- historical corrected detail matching can be made exact by `manychat_id`
- same-day drift can still happen because official reporting is a snapshot while custom rebuilds use live raw tables
- moderate rows do not always have structured evidence

### Not fully solved

- perfect same-day parity from raw tables alone
- full evidence coverage for runtime-only corrected rows

### Best long-term fix

Persist the corrected `Chatbot/JCo` user-day cohort during the same dashboard refresh into a physical reporting table, for example:

- `gulong_reporting.p_chatbotjco_corrected_users_daily`

Recommended fields:

- `report_date`
- `manychat_id`
- `silver_session_id`
- `moderate_tagged_at`
- `moderate_tagged_source`

Then build detail reporting from that persisted snapshot instead of rebuilding from live raw tables.
