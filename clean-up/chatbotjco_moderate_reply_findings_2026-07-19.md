# Chatbot/JCo Moderate Reply Findings

## Scope

This note summarizes the current findings for `Chatbot/JCo` moderate reporting and CS reply tracking as of Sunday, July 19, 2026.

Main question:

- For the current moderate cohort, who replied from CS and how many moderates were replied to?

---

## Current Official Context

Official daily moderate counts come from:

- `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`

For `2026-07-19`:

- `agent_name = 'Chatbot/JCo'`
- `total_moderate_intents = 82`

Important meaning:

- this is an official corrected moderate count
- it is a reporting snapshot count
- it is not always the same as a live raw-table rebuild later in the day

---

## Live Rebuild Finding For July 19, 2026

Using the live corrected cohort rebuild from:

- `gulong_core.inquiry_assignments`
- `chat_analysis.chat_analysis_data`
- `gulong_chatbot_live.turn_trace_log`
- `manychat_data.messages`

the current live cohort returned:

- `91` total moderates

Reply breakdown:

- `22` moderates had a CS reply
- `69` moderates had no CS reply

Reply sender breakdown from the live rebuild:

- `Rem Reyes = 22`
- `No CS Reply = 69`

Current live reply rate:

- `22 / 91 = 24.18%`

Important note:

- `82` and `91` are not necessarily contradictions
- `82` is the earlier official snapshot
- `91` is the later live rebuild from raw sources

---

## Main Problems Found

### 1. Hardcoded reporting owner

Earlier versions of `v_looker_first_reply_detail` hardcoded:

- `reporting_agent_name = 'sarah gulongph'`
- `source_agent_name = 'Chatbot/JCo'`

Problem:

- assigned owner can change
- actual replying CS can be a different person
- this makes Looker filters misleading

### 2. Missing usernames

Some moderate rows had null `user_name`.

Cause:

- corrected moderate rows often use synthetic session IDs like:
  - `assignment:<manychat_id>:<report_date>`
- those do not always match `fb_inquiry_sessions`

Fix:

- fallback by `manychat_id`
- fallback final display to:
  - `manychat:<manychat_id>`

### 3. Null reply should mean no reply

Some rows had null `first_cs_reply_at`.

Desired business meaning:

- null reply should explicitly mean:
  - `No CS Reply`

Fix:

- added:
  - `reply_agent_name`
  - `reply_agent_name_norm`
  - `reply_status`
- used:
  - `COALESCE(first_cs_reply_sender, 'No CS Reply')`

### 4. Deleted view dependency

`v_looker_first_reply_detail` previously joined:

- `gulong_reporting.v_looker_chatbotjco_sarah_base`

Problem:

- that view was deleted
- downstream query would fail if the join stayed

Fix:

- replaced the join with:
  - `gulong_reporting.p_looker_agent_daily_conversion`

---

## Current Recommended Field Meanings

### Ownership fields

- `reporting_agent_name`
  - dynamic assigned owner from `inquiry_assignments.assigned_agent_name`
- `source_agent_name`
  - reporting bucket from `inquiry_assignments.agent_reporting_name`
- `agent_reporting_group`
  - reporting group from `inquiry_assignments.agent_reporting_group`

### Actual reply fields

- `first_cs_reply_sender`
  - raw actual first agent sender
- `reply_agent_name`
  - actual reply sender, or `No CS Reply`
- `reply_status`
  - `Has CS Reply` or `No CS Reply`

### Metrics

- `moderate_count = 1`
- `reply_in_moderate_count = IF(first_cs_reply_at IS NOT NULL, 1, 0)`
- `no_reply_session_count = IF(first_cs_reply_at IS NULL, 1, 0)`

These make Looker reporting straightforward.

---

## Current Recommended View Logic

The corrected `v_looker_first_reply_detail` should:

1. Start from corrected `Chatbot/JCo` assignment cohort.
2. Determine moderates from:
   - latest same-day `chat_analysis` moderate/high intent
   - or same-day V7 runtime moderate/high tags
3. Keep the assigned owner dynamic from `inquiry_assignments`.
4. Derive first customer message from `manychat_data.messages`.
5. Derive first CS reply from `manychat_data.messages`.
6. Keep unreplied moderates in the view.
7. Label null replies as `No CS Reply`.
8. Use fallback username logic when profile/session data is missing.

---

## Looker Usage Recommendation

Use this view for reply tracking.

Recommended dimensions:

- `report_date`
- `reporting_agent_name`
- `source_agent_name`
- `reply_agent_name`
- `reply_status`
- `manychat_id`
- `user_name`

Recommended metrics:

- `SUM(moderate_count)`
- `SUM(reply_in_moderate_count)`
- `SUM(no_reply_session_count)`
- `SUM(reply_in_moderate_count) / SUM(moderate_count)`

Recommended filter behavior:

- filter by `reply_agent_name` to see which CS replied
- filter by `reply_status = 'Has CS Reply'` for replied-only moderates
- filter by `reporting_agent_name` for assigned-owner analysis

---

## Business Interpretation

For Sunday, July 19, 2026:

- official snapshot moderate count:
  - `82`
- current live rebuilt moderate count:
  - `91`
- current live rebuilt replied moderates:
  - `22`
- current live rebuilt unreplied moderates:
  - `69`

So the operational statement is:

- as of the latest live check, `22` out of `91` moderates had a CS reply

This should be treated as a live operational view, while `82` remains the official snapshot count from the reporting table.

---

## What Was Solved

- removed hardcoded Sarah ownership from the detail logic
- made assigned owner dynamic
- separated assigned owner from actual replying CS
- preserved unreplied moderates
- made null reply explicitly mean `No CS Reply`
- added fallback username display
- removed dependency on deleted `v_looker_chatbotjco_sarah_base`
- replaced daily summary join with `p_looker_agent_daily_conversion`

---

## Remaining Caveat

Exact parity between:

- official snapshot count in `p_looker_agent_daily_conversion`
- and live rebuilt detail rows

is still not guaranteed on same-day data.

Reason:

- official table is a snapshot
- detail rebuild reads live raw tables

If exact same-day parity is required, the corrected moderate user cohort should be persisted as a physical daily reporting table during the same refresh process.
