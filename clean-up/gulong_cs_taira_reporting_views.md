# Gulong CS / TAira Reporting Views — Reference

**Project:** `gulong-chatbot-459723`
**Dataset:** `gulong_reporting` (gold layer)
**Last updated:** 2026-07-21
**Owner:** Atossa (GM, Gulong.ph)

This document summarizes three reporting objects built for monitoring TAira (chatbot) moderate intents, CS inquiry response coverage, and CS follow-up activity. All three are designed to feed Looker Studio dashboards.

---

## Shared design principles

These patterns are applied consistently across the views so numbers stay comparable:

- **Cohort spine:** `gulong_core.inquiry_assignments`, filtered by `business_unit = 'gulong'` and the relevant `agent_reporting_group`.
- **First-reply attribution:** CS replies are matched from `manychat_data.messages` (`role = 'agent'`, `type = 'msgout_lc'`), bounded by session windows (first customer message → next customer message) to avoid attributing a reply to the wrong inquiry.
- **Real-time name backfill:** customer names come from `manychat_data.users_current` (215K users, ~100% name coverage), which is real-time and does not lag like `inquiry_sessions`. Join requires `CAST(manychat_id AS STRING)` because `users_current.user_id` is STRING.
- **Contact backfill (moderate view only):** 4-layer COALESCE — session evidence → `chat_analysis.extracted_data.contact_number` → regex over user messages → NULL. PH mobile regex: `r'(?i)(\+?63[\s\-]?9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}|09\d{9})'` (note: single backslashes; the `\\d` version silently matches nothing).
- **Data floor:** most message-based logic starts `2026-03-01` (the messages data floor). GA4/newer sources may differ.
- **Provenance columns:** `name_source` and `contact_source` are metadata (which fallback layer supplied the value), for QA only — the display column is still `user_name` / `contact_number`.
- **Metric columns are INT64** (`CAST(... AS INT64)`) so Looker Studio detects them as Number and `SUM()` works without manual type overrides.

---

## 1. `v_looker_first_reply_detail` — TAira moderate intent monitoring

**Purpose:** Row-level detail of Chatbot/JCo (TAira) moderate-intent sessions: when the customer first messaged, when CS first replied, and whether CS replied at all. Powers the TAira moderate monitoring dashboard.

**Cohort:** `agent_reporting_group = 'chatbot_jeanel'` AND `agent_reporting_name = 'Chatbot/JCo'`

**Moderate detection (two sources, unioned):**
- `chat_analysis.chat_analysis_data` where `top_intent IN ('moderate intent','high intent')`
- v7 runtime correction: `gulong_chatbot_live.turn_trace_log` where `runtime_version = 'v7'` and tagging JSON contains moderate/high intent (`tags_applied` / `tags_to_add` / `tags_skipped_existing`). Required for June 4+ data.

**Key columns:**

| Column | Meaning |
|---|---|
| `report_date`, `report_week`, `report_month` | assignment-based date grain |
| `reporting_agent_name` / `source_agent_name` | assigned owner vs canonical source bucket |
| `user_name`, `name_source` | customer name + provenance (session / manychat_realtime / synthetic) |
| `contact_number`, `contact_source` | contact + provenance (session_evidence / chat_analysis / message_regex) |
| `first_customer_message_at` | when customer first messaged |
| `first_moderate_at`, `moderate_tagged_at` | when moderate intent was triggered/tagged |
| `first_cs_reply_at`, `first_cs_reply_sender` | when/who first CS reply |
| `reply_agent_name` | actual responder (or 'No CS Reply') |
| `reply_status` | 'Has CS Reply' / 'No CS Reply' |
| `minutes_to_first_reply` | first customer msg → first CS reply |
| `minutes_from_moderate_to_first_reply` | moderate trigger → first CS reply |
| `minutes_to_reply_sla` | business-hours reply minutes, even if reply happened the next day |
| `minutes_to_reply_sla_today` | same as SLA minutes but only when reply happened on `report_date`; next-day replies return `NULL` so they do not affect same-day averages |
| `moderate_count`, `replied_session_count`, `no_reply_session_count` | 1/0 metric flags (INT64) |
| `daily_response_rate` | window-function rate — **do not aggregate in Looker** |

**Response rate in Looker:** use a calculated field `SUM(replied_session_count) / SUM(moderate_count)` (Type = Percent). Do NOT use `daily_response_rate` (it is a per-date window function and averages incorrectly across other grains).

**Filter controls:** dimension = `reply_agent_name` (or `reporting_agent_name`), metric = `SUM(moderate_count)` or Record Count. Never use conditional counts (e.g. `reply_in_moderate_count`) as the filter metric — the 'No CS Reply' option shows 0.

**Backfill result:** synthetic (`manychat:...`) names dropped from ~1,670 to 3 across all history after adding the `users_current` layer.

---

## 2. `v_looker_cs_inquiry_reply_detail` — CS inquiry response coverage

**Purpose:** Same first-reply logic as the moderate view, but across **all** CS inquiries (not just moderate). Answers: per CS agent, how many inquiries, how many replied, how many with no reply, and reply speed.

**Cohort:** `agent_reporting_group = 'cs_agent'`, `assignment_date >= '2026-03-01'`
(CS agents in this group: Rem Reyes, sarah gulongph, Aira L. Garcia, Rolyn Ang, Becca Armstrng, Atossa Saremi, and historical agents.)

**Cost note:** lighter than the moderate view — no `chat_analysis`, `turn_trace_log`, `fb_inquiry_sessions`, or regex scans. Just `inquiry_assignments` + `messages` + `users_current`.

**Key columns:**

| Column | Meaning |
|---|---|
| `report_date`, `report_week`, `report_month` | assignment date grain |
| `agent_name` | assigned owner of the inquiry |
| `reply_agent_name` | actual responder (may differ from assigned owner) |
| `user_name` | customer name (real-time backfill) |
| `first_customer_message_at`, `first_cs_reply_at` | timestamps |
| `reply_status` | 'Has CS Reply' / 'No CS Reply' |
| `minutes_to_first_reply`, `minutes_from_assignment_to_reply` | speed metrics |
| `inquiry_count`, `replied_inquiry_count`, `no_reply_inquiry_count` | 1/0 flags |

**Looker table setups:**

*Per-agent summary:*
- Dimension: `agent_name`
- Metrics: `SUM(inquiry_count)`, `SUM(replied_inquiry_count)`, `SUM(no_reply_inquiry_count)`, calc field `SUM(replied_inquiry_count)/SUM(inquiry_count)` (Percent)

*Detail / follow-up list:*
- Dimensions: `user_name`, `agent_name`, `first_customer_message_at`, `first_cs_reply_at`, `reply_status`
- Filter: `reply_status = 'No CS Reply'`; sort by `first_customer_message_at` desc

**Filter controls:** dimension `agent_name` (checkbox), metric `SUM(inquiry_count)`. Date range dimension = `report_date`.

**Note on assigned vs responder:** `agent_name` = who owns the inquiry; `reply_agent_name` = who actually replied first. They can differ (e.g. Sarah owns it, Rem replies).

**Related existing objects (check before duplicating):**
- `p_mancom_cs_agent_daily_performance` — physical table with per-agent daily `response_rate`, `first_response_minutes`, targets. Use this for aggregate monitoring if row-level detail isn't needed.
- `p_cs_agent_daily_conversion` — daily conversion/bookings per CS agent.
- `v_looker_first_reply` — older per-session first-reply view (moderate-focused, has hardcoded Sarah columns; predates the dynamic-agent approach).

---

## 3. `v_looker_cs_followup_detail` — CS follow-up activity

**Purpose:** Track proactive CS follow-up messages ("Hi 😊 still interested po?" type canned replies): who follows up, with which customer, and when. Follow-up templates are predefined in ManyChat and clicked by CS.

**Detection:** `manychat_data.messages` with `business_unit = 'gulong'`, `role = 'agent'`, `type = 'msgout_lc'`, `datetime >= '2026-06-01'`, sender in the known CS roster, and text matching follow-up patterns. Deduplicated to one follow-up event per user per day (earliest).

**Follow-up taxonomy (from investigation of sarah gulongph, Jun–Jul):**

Follow-up volume is dominated by sarah gulongph (2,029 "still interested" alone) >> Aira L. Garcia (275) >> Rem Reyes (48).

| Category | Examples | Nature |
|---|---|---|
| **still_interested** | "Hi 😊 Still interested po?" (1,687), "Still interested po?" (38) | Re-engagement of quiet leads — the clearest follow-up |
| **checking_in** | "Hello! Just checking in if you still need help with your tire inquiry?" (652), "Hello po, do you still need help with your inquiry?" (90), "Just checking if may napili na po kayong brand..." (297+41) | Soft re-engagement |
| **proceed_nudge** | "would you like to proceed?" (106+164 variants), "are you still interested to proceed?" (119), "proceed na po ba kayo sa michelin?" (many per-brand variants) | Ambiguous — often a live closing nudge *inside* an active conversation after a quote, not re-engagement of a dead lead |

**Design decision:** keep `proceed_nudge` in the view, but expose `followup_type` so Looker can include/exclude it with a filter. Classification order matters: evaluate `proceed_nudge` before generic `still_interested`, otherwise phrases like "are you still interested to proceed?" get misclassified. Current observed volumes since `2026-06-01`: `still_interested` = 2,001 deduped user-days, `checking_in` = 1,049, `proceed_nudge` = 1,668.

**Excluded (not follow-up):** reservation detail forms, payment option lists, T&C, "available options" carousels, delivery/COD explanations — these are normal transaction flow.

**Key columns:**

| Column | Meaning |
|---|---|
| `report_date`, `report_week`, `report_month` | follow-up date grain |
| `agent_name` | CS agent who sent the follow-up |
| `user_name` | customer followed up |
| `manychat_id` | ManyChat user id |
| `followup_at` | timestamp |
| `followup_type` | `still_interested`, `checking_in`, or `proceed_nudge` |
| `followup_text` | exact wording used |
| `followup_count` | 1 per deduped event |

**Looker setups:**
- Per-agent: Dimension `agent_name`, Metric `SUM(followup_count)`
- Re-engagement-only view: add filter `followup_type IN ('still_interested', 'checking_in')`
- Detail: Dimensions `user_name`, `agent_name`, `followup_at`, `followup_text`
- Filter control: `agent_name` (checkbox)

**Cost:** light — `messages` (~50 MB) + `users_current` (~70 MB), no heavy joins.

**Note:** a follow-up→booking conversion version was drafted (join to `orders_all.manychat_user_id` where `is_reportable_booked_order`, booking within N days of follow-up) but set aside — current scope is follow-up activity only.

---

## Operational reminders

- **MCP is read-only.** All `CREATE OR REPLACE VIEW` DDL must be run manually in the BigQuery Console. `DECLARE` is unsupported by the MCP tool; inline date literals.
- **After deploying a view:** Refresh Fields in Looker Studio to pick up new columns; force a data refresh if names/contacts look stale (BigQuery data-source cache defaults to ~12h).
- **`inquiry_sessions` / `fb_inquiry_sessions` loader lags** — it does not run intraday reliably, so same-day names/contacts must come from real-time sources (`users_current`, `messages`, `chat_analysis`), which is why the backfill layers exist.
- **Cost optimization path:** if a view gets heavy on refresh, materialize it into a `p_` physical table via a scheduled query (same pattern as `p_looker_agent_daily_conversion` / `p_dashboard_physical_refresh_log`) and point Looker at the table. Trade-off: freshness becomes as-of-last-refresh.
- **agent_reporting_group values:** `chatbot_jeanel` (TAira/JCo) and `cs_agent` (human CS) are cleanly separated in `inquiry_assignments`.
