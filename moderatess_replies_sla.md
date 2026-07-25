# Moderates And Bookings Validation

## Scope

This note documents the investigation for the mismatch between:

- `gulong_reporting.p_looker_agent_daily_conversion`
- [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql)

Target discrepancy discussed in this thread:

- official `p_looker_agent_daily_conversion`: `571 moderates`, `25 bookings`
- rebuilt detail query from [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql): `569` rows

This document covers:

- findings
- architecture
- engineering interpretation
- user manual

## Executive Summary

The `571` vs `569` gap is not explained by first-reply logic alone.

The stronger explanation from the local source-of-truth notes is:

1. `p_looker_agent_daily_conversion` is not a raw rebuild.
2. It is a scheduled physical reporting snapshot built by `refresh_dashboard_physical_hot_full()`.
3. For `Chatbot/JCo`, its moderate denominator is not just the corrected chatbot cohort.
4. It uses a staged override with:

```sql
GREATEST(c.total_moderate_intents, b.total_moderate_intents)
```

where:

- `c` = corrected chatbot moderate count
- `b` = base moderate count from the original reporting pipeline

By contrast, [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql) builds only the corrected chatbot cohort and emits one row per `report_date + manychat_id`.

So the most likely explanation for `571` vs `569` is:

- there are `2` user-day rows that survive in the official base/staged aggregate path
- but do not survive in the rebuilt corrected-detail path

The `22 bookings` number is also not computed inside [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql).
That view only exposes `b.total_bookings` by joining the already-aggregated `p_looker_agent_daily_conversion` table at the end, so the bookings metric there is inherited, not rebuilt.

## Live Validation Results

Live BigQuery validation was rerun on `2026-07-25`.

### Current mismatches by date

The exact `571 moderates / 22 bookings / 569 detail rows` combination is not the current single-day state anymore.

Current live daily differences for `Chatbot/JCo`:

| report_date | official moderates | detail rows | detail minus official |
|---|---:|---:|---:|
| `2026-07-25` | `26` | `27` | `+1` |
| `2026-07-01` | `14` | `12` | `-2` |
| `2026-06-23` | `16` | `15` | `-1` |
| `2026-06-19` | `9` | `8` | `-1` |
| `2026-05-31` | `6` | `1` | `-5` |

There are additional older historical mismatches before July 2026.

### Current range totals

For `2026-07-01` to `2026-07-24`:

- official moderates: `571`
- detail rows: `569`
- official bookings: `25`

For `2026-07-01` to `2026-07-25`:

- official moderates: `597`
- detail rows: `596`
- official bookings: `25`

For `2026-07-01` to `2026-07-22`:

- official moderates: `523`
- official bookings: `25`

So for the exact filter `2026-07-01` to `2026-07-24`, the live gap is `2`.

### Refresh-log finding

The latest entries in `p_dashboard_physical_refresh_log` show an operational hot refresh note saying:

- inquiry / moderate / response fields are refreshed in the hot window
- booking and sales fields are preserved from existing physical rows
- booking and sales are refreshed by a lower-frequency full dashboard job

Operational meaning:

- moderate and reply numbers may move on the hot refresh cadence
- booking fields may lag behind and should not be expected to change in lockstep with live detail rebuilds

## Findings

### 1. `v_looker_first_reply_detail.sql` is a detail rebuild, not the official denominator

The detail view starts from `inquiry_assignments`, filters `Chatbot/JCo`, corrects the cohort through `chat_analysis` and `turn_trace_log`, then keeps one row per `report_date + manychat_id + silver_session_id` before first-reply enrichment. See [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L5) and [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L107).

Its final grain is effectively one row per `report_date + manychat_id` because of:

```sql
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY report_date, manychat_id
  ORDER BY agent_reply_at, agent_reply_sender
) = 1
```

See [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L381).

### 2. The official `p_looker_agent_daily_conversion` moderate count is a staged reporting metric

The existing engineering notes explicitly state that the official table is built from:

- `hot_corrected_chatbot_moderates`
- `stg_p_looker_agent_daily_conversion`
- `p_looker_agent_daily_conversion`

and that `Chatbot/JCo` moderates are overridden with:

```sql
GREATEST(c.total_moderate_intents, b.total_moderate_intents)
```

This means the official denominator can be higher than a pure corrected-cohort rebuild. See [chatbotjco_sarah_reporting_notes.md](/home/jerico/Desktop/gulong-mobile/chatbotjco_sarah_reporting_notes.md#L120) and [customer_reply_booking_funnel_gold_investigation_summary.md](/home/jerico/Desktop/gulong-mobile/customer_reply_booking_funnel_gold_investigation_summary.md#L61).

### 3. The `571` vs `569` gap is most likely caused upstream of first-reply matching

The first-reply logic only affects:

- which agent reply is selected
- `reply_status`
- reply-time metrics

It does not create the moderate denominator itself. The denominator is already established earlier by `corrected_chatbot_cohort`. See [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L107) and [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L449).

So if the official count is `571` and the detail rebuild is `569`, the first thing to suspect is not the CS reply window. The first thing to suspect is:

- snapshot-vs-live drift
- staged `GREATEST(...)` override in the official pipeline
- two user-days present in base moderate counts but absent from the corrected rebuild
- or two user-days lost in the rebuild because of assignment/session deduping

Live validation now confirms this is not just theory. On `2026-07-01`:

- official moderates = `14`
- corrected cohort users = `12`
- detail rows = `12`
- base moderate users mapped to `Chatbot/JCo` = `14`

That means the gap on that date is definitively upstream of the first-reply logic.

### 4. `total_bookings = 22` is inherited from the official aggregate table

The detail SQL does not calculate booking rows from `orders_booked`.

Instead, it does this at the end:

```sql
LEFT JOIN `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion` b
  ON b.report_date = fr.report_date
 AND b.agent_name = fr.source_agent_name
```

and then selects:

- `b.total_moderate_intents`
- `b.total_moderate_sessions`
- `b.total_bookings`

See [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L410).

So if you are looking at `22 bookings` in the detail dataset, that value is not proof that the detail view independently found `22` booking rows. It only means the official daily aggregate row for `Chatbot/JCo` had `total_bookings = 22`.

Live validation also showed that the current `2026-07-01` to `2026-07-24` official total bookings is `25`, which confirms that `22 bookings` was a point-in-time result, not a stable truth built by the detail view.

### 5. The current detail SQL has no refresh cutoff protection

The local notes say same-day parity with `p_looker_agent_daily_conversion` requires applying the latest reporting cutoff from `p_dashboard_physical_refresh_log`.

The current local file does not apply any `<= cutoff_dt` filter to:

- `chat_analysis.chat_analysis_data`
- `gulong_chatbot_live.turn_trace_log`
- `manychat_data.messages`

See the recommendation in [chatbotjco_sarah_reporting_notes.md](/home/jerico/Desktop/gulong-mobile/chatbotjco_sarah_reporting_notes.md#L204) and compare with the live SQL in [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L36), [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L67), and [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql#L351).

If the `571` vs `569` comparison was done on or near the refresh boundary, snapshot-vs-live drift remains a valid explanation.

### 6. The detail view uses CS working-hours + lunch-break logic for reply SLA anchoring

CS working hours: **9:00 AM – 6:00 PM, Monday–Sunday**, with a **simultaneous lunch break 12:00 PM – 1:00 PM** (all agents off at once, so no one replies during lunch). There is no weekend exception — CS works all 7 days.

**`effective_moderate_tagged_at`** shifts the SLA start out of non-working windows:

- before `09:00` -> same day `09:00`
- `18:00` or later -> next day `09:00`
- during lunch `12:00`–`13:00` -> same day `13:00`
- otherwise keep the original tag timestamp

**`minutes_to_reply_sla`** is the fair, business-hours response time. It measures from `effective_moderate_tagged_at` to `first_cs_reply_at`, then **subtracts any minutes that fall inside the 12:00–13:00 lunch window**, and is floored at 0:

```sql
GREATEST(
  DATETIME_DIFF(first_cs_reply_at, effective_moderate_tagged_at, MINUTE)
  - GREATEST(
      DATETIME_DIFF(
        LEAST(first_cs_reply_at,
              DATETIME(DATE(effective_moderate_tagged_at), TIME '13:00:00')),
        GREATEST(effective_moderate_tagged_at,
                 DATETIME(DATE(effective_moderate_tagged_at), TIME '12:00:00')),
        MINUTE
      ), 0
    ),
  0
) AS minutes_to_reply_sla
```

Worked examples (these are the agreed-upon behaviors):

| Moderate tagged | CS first reply | effective start | Raw diff | Lunch subtracted | `minutes_to_reply_sla` |
|---|---|---|---|---:|---:|
| 9:00 AM | 12:30 PM | 9:00 AM | 210 | 30 | **180** |
| 11:45 AM | 12:30 PM | 11:45 AM | 45 | 30 | **15** |
| 11:45 AM | 1:15 PM | 11:45 AM | 90 | 60 | **30** |
| 12:20 PM (during lunch) | 12:40 PM | 1:00 PM | -20 → floored | 0 | **0** |
| 8:00 PM (after hours) | 8:30 PM (after hours) | 9:00 AM next day | negative → floored | 0 | **0** (flagged `replied_outside_hours`) |
| 6:00 AM (before hours) | 9:10 AM | 9:00 AM | 10 | 0 | **10** |

Key principle: the lunch subtraction only removes the minutes that literally overlap 12:00–13:00. A long genuine delay that merely touches lunch at its tail (e.g. 9:00 AM → 12:30 PM) is only reduced by the overlap (30 min), not zeroed — the 3 hours of unanswered working time before lunch is real delay and stays counted. Only when the moderate itself occurs during lunch (or after hours) and the reply is fast does the metric reach 0.

**Reply matching lower bound** uses the **raw** `moderate_tagged_at` (not the effective one) so that genuine after-hours or during-lunch replies are still counted as replies rather than dropped. SLA fairness is handled entirely by `effective_moderate_tagged_at` + the lunch subtraction downstream — not by shrinking the match window.

**Supporting flags / columns emitted:**

- `effective_moderate_tagged_at`, `effective_moderate_tagged_date`
- `tagged_outside_hours` — moderate tagged before 9 AM or at/after 6 PM
- `tagged_during_lunch` — moderate tagged within 12:00–13:00
- `replied_outside_hours` — CS replied before the effective SLA start (bonus effort, not penalized)
- `minutes_to_reply_sla` — the metric to use for CS response-time reporting

**Which reply-time column to use:**

- `minutes_to_reply_sla` — **use this** for CS performance (business-hours + lunch aware)
- `minutes_from_tagged_to_first_reply` — raw wall-clock from tag to reply (reference only; can be negative if replied before effective start)
- `minutes_from_moderate_to_first_reply`, `minutes_to_first_reply` — raw reference clocks from the moderate event / first customer message; **do not use for SLA** (they ignore working hours)

None of this affects the moderate denominator — it only shapes reply-time metrics and reply-window matching. It does not explain the `571` vs `569` gap. See [v_looker_first_reply_detail.sql](/home/jerico/Desktop/gulong-mobile/v_looker_first_reply_detail.sql).

## Architecture

### Official pipeline

```text
hot_inquiry_assignments
  + hot_moderate_by_original_agent_day
  + hot_corrected_chatbot_moderates
  -> stg_p_looker_agent_daily_conversion
  -> p_looker_agent_daily_conversion
```

Important property:

- this is the official reporting snapshot
- `Chatbot/JCo` moderate totals come from staged reporting logic
- the final denominator can be `GREATEST(corrected, base)`

### Detail pipeline

```text
gulong_core.inquiry_assignments
  -> chatbot_assignments

chat_analysis.chat_analysis_data
  -> chat_analysis_chatbot_intents

gulong_chatbot_live.turn_trace_log
  -> v7_runtime_chatbot_intents

chat_analysis_chatbot_intents
  + v7_runtime_chatbot_intents
  -> corrected_chatbot_cohort

corrected_chatbot_cohort
  + fb_inquiry_sessions
  + users_current
  + manychat_data.messages
  + moderate_intent_sessions
  -> cohort
  -> agent_messages
  -> first_reply
  -> v_looker_first_reply_detail
```

Important property:

- this is a row-level rebuilt detail dataset
- it is not the authoritative moderate denominator by itself
- it inherits official booking totals only through the final join to `p_looker_agent_daily_conversion`

## Engineering Interpretation

### Why `571` can be higher than `569`

Most likely causes, in order:

1. Official staged override:
   `p_looker_agent_daily_conversion` can keep the higher of corrected chatbot counts and base moderate counts.
2. Snapshot-vs-live timing:
   official table is a physical refresh; detail SQL reads live raw sources.
3. Dedup grain difference:
   the detail SQL dedupes at `report_date + manychat_id`, while upstream official staging may preserve two extra user-days differently before final aggregation.
4. Input-table timing/lag:
   `fb_inquiry_sessions`, `messages`, or same-day source timing may cause two corrected user-days to miss enrichment or matching.

### Why `22 bookings` should not be used as a direct reconciliation proof

In the detail view, `total_bookings` is a copied aggregate field from `p_looker_agent_daily_conversion`, not a row-level booking attribution built from `orders_booked`.

That means this statement is valid:

- `p_looker_agent_daily_conversion` says the day had `22 bookings`

But this statement is not valid from the detail view alone:

- `v_looker_first_reply_detail` independently proved `22` booked moderates

For that second question, use the follow-up/booking coverage models instead of the first-reply detail view.

## Validation Gaps

Live BigQuery reconciliation queries were run in this session.

What is now confirmed:

- the official stored procedure logic for `p_looker_agent_daily_conversion`
- the current mismatch dates between official and detail
- the current July 2026 range totals
- the fact that `2026-07-01` official counts are being driven by the base moderate path, not by the corrected detail path

What is still incomplete:

- a full historical explanation for every mismatch date before July 2026
- a single exact range that produced the earlier `571 / 22 / 569` snapshot
- a production decision on whether the detail view should mirror the official snapshot or remain a live operational rebuild

## Recommended Live Checks

Run these in BigQuery to isolate the exact `2` missing rows.

### 1. Official headline

```sql
SELECT
  report_date,
  agent_name,
  total_moderate_intents,
  total_moderate_sessions,
  total_bookings
FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
WHERE agent_name = 'Chatbot/JCo'
ORDER BY report_date DESC;
```

### 2. Rebuilt detail denominator

```sql
SELECT
  report_date,
  COUNT(*) AS detail_rows,
  COUNT(DISTINCT manychat_id) AS distinct_manychat_ids
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
WHERE source_agent_name = 'Chatbot/JCo'
GROUP BY report_date
ORDER BY report_date DESC;
```

### 3. Find dates where the official and detail counts disagree

```sql
WITH p AS (
  SELECT
    report_date,
    total_moderate_intents
  FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
  WHERE agent_name = 'Chatbot/JCo'
),
v AS (
  SELECT
    report_date,
    COUNT(*) AS detail_rows
  FROM `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail`
  WHERE source_agent_name = 'Chatbot/JCo'
  GROUP BY report_date
)
SELECT
  COALESCE(p.report_date, v.report_date) AS report_date,
  p.total_moderate_intents,
  v.detail_rows,
  p.total_moderate_intents - v.detail_rows AS diff
FROM p
FULL OUTER JOIN v
  ON p.report_date = v.report_date
WHERE COALESCE(p.total_moderate_intents, 0) != COALESCE(v.detail_rows, 0)
ORDER BY report_date DESC;
```

### 4. Find the actual missing `manychat_id` rows

This requires rebuilding the official corrected cohort or extracting the staged cohort from the stored procedure logic. The key point is:

- compare official cohort user-days vs detail view user-days
- at grain `report_date + manychat_id`

Expected output:

- the `2` user-days present in the official denominator but absent from the detail output

### Actual resolved example: `2026-07-01`

For `2026-07-01`:

- official moderates = `14`
- corrected users = `12`
- base users mapped to `Chatbot/JCo` = `14`
- detail rows = `12`

Symmetric difference at `manychat_id + silver_session_id`:

`base_only`

- `24558006153868221` / `af937b58278b374cf9af03e0170350b4`
- `25158658697073264` / `d414ad399713c1932fa1573094c1f49e`
- `27261161383553075` / `cb11ba507381df59f96dbfb0f14d1077`
- `27338345002443177` / `5af3496accdffbc20d12813b6dfaeb05`
- `27350864761244323` / `05f49e05cb604090387a47cd43184925`
- `28343973998524116` / `828969507633b45a8c4eeb53896e972b`

`detail_only`

- `26814794628199106` / `296383aa06cdc847dacbcd9b6711651f`
- `27904793135771778` / `assignment:27904793135771778:2026-07-01`
- `6811251325669647` / `bd2825b3b143702906f7490e7bb7290f`
- `7227095780656736` / `c5372362da479e84367aa6ae5bea18c2`

Net effect:

- base path has `6` rows not in detail
- detail path has `4` rows not in base
- official minus detail = `2`

This is direct evidence that the mismatch is a cohort-definition mismatch, not a reply-SLA bug.

## User Manual

### What to use for official KPI reporting

Use:

- `gulong_reporting.p_looker_agent_daily_conversion`

For:

- `total_moderate_intents`
- `total_moderate_sessions`
- `total_bookings`
- official daily dashboard headline metrics

### What to use for row-level reply investigation

Use:

- `gulong_reporting.v_looker_first_reply_detail`

For:

- `manychat_id`
- `user_name`
- `contact_number`
- `moderate_tagged_at`
- `effective_moderate_tagged_at`
- `tagged_outside_hours`, `tagged_during_lunch`, `replied_outside_hours`
- `first_customer_message_at`
- `first_cs_reply_at`
- `reply_status`
- `minutes_to_reply_sla` (business-hours + lunch aware response time)
- reply-time investigation

For CS response-time reporting, use `minutes_to_reply_sla`. Do not use the raw clocks (`minutes_to_first_reply`, `minutes_from_moderate_to_first_reply`, `minutes_from_tagged_to_first_reply`) — they ignore working hours and lunch and will overstate reply time.

### What not to do

Do not assume:

- `COUNT(*)` from `v_looker_first_reply_detail` is always the official moderate denominator
- `total_bookings` inside the detail view is a row-level booking proof
- reply-SLA logic explains aggregate denominator mismatches

### Safe interpretation rule

Use this decision tree:

1. If the question is "what is the official number?", use `p_looker_agent_daily_conversion`.
2. If the question is "which user/session is included and when was the first reply?", use `v_looker_first_reply_detail`.
3. If the question is "which bookings came from follow-up or chatbot cohort booking logic?", use the follow-up/coverage booking models, not the first-reply detail view.

## Engineer Manual

### When editing the detail SQL

Preserve these invariants:

1. Start from `inquiry_assignments`.
2. Keep `agent_reporting_group = 'chatbot_jeanel'`.
3. Keep `agent_reporting_name = 'Chatbot/JCo'`.
4. Correct the cohort using both:
   - latest same-day `chat_analysis` moderate/high top intent
   - same-day V7 runtime moderate/high tags
5. Keep detail grain at one row per `report_date + manychat_id`.
6. Treat bookings in this view as borrowed aggregate fields unless a true row-level booking join is intentionally added.
7. Reply-window lower bound must stay on **raw** `moderate_tagged_at`, not `effective_moderate_tagged_at`. Using the effective timestamp here would drop legitimate after-hours / during-lunch replies and misclassify them as "No CS Reply."
8. SLA fairness (working hours 9–18, lunch 12–13, Mon–Sun, simultaneous lunch) lives only in `effective_moderate_tagged_at` and the lunch-subtraction inside `minutes_to_reply_sla`. Keep `GREATEST(..., 0)` floors on both the lunch-overlap term and the final result so nothing goes negative.
9. If working hours, lunch window, or the simultaneous-lunch assumption ever change, update the `effective_moderate_tagged_at` CASE and the lunch-overlap `LEAST/GREATEST` bounds together — they must use the same window constants.

### Name / contact backfill (production — do not regress)

The view resolves customer identity through layered fallbacks. Keep this order:

- **name:** session exact -> session fallback -> `manychat_data.users_current` real-time -> `manychat:<id>` synthetic. The `users_current` join needs `CAST(manychat_id AS STRING)` (its `user_id` is STRING). This layer dropped synthetic names from ~1,670 to ~3 across all history.
- **contact:** session evidence -> `chat_analysis.extracted_data.contact_number` -> PH-mobile regex over user messages -> NULL. Regex uses single backslashes: `r'(?i)(\+?63[\s\-]?9\d{2}[\s\-]?\d{3}[\s\-]?\d{4}|09\d{9})'`. The `\\d` form silently matches nothing.
- `name_source` and `contact_source` are QA provenance columns; the display columns remain `user_name` / `contact_number`.

### If exact parity is required

Best long-term fix:

1. Persist the corrected chatbot user-day cohort during the same reporting refresh.
2. Build `v_looker_first_reply_detail` from that persisted snapshot instead of rebuilding from live raw tables.

Suggested physical table:

- `gulong_reporting.p_chatbotjco_corrected_users_daily`

Suggested fields:

- `report_date`
- `manychat_id`
- `silver_session_id`
- `moderate_tagged_at`
- `corrected_source`

### If you need to resolve the current gap

Do this in order:

1. Compare `p_looker_agent_daily_conversion` vs detail view by `report_date`.
2. Identify the exact dates with non-zero diff.
3. Compare official cohort user-days vs detail user-days at `report_date + manychat_id`.
4. Check whether the missing rows are:
   - base-only rows surviving `GREATEST(...)`
   - snapshot timing rows
   - assignment-dedupe losses
   - session/message enrichment losses

## Final Conclusion

The cleanest reading of the current evidence is:

- the mismatch is architectural, not just a reply-timestamp bug
- official `p_looker_agent_daily_conversion` can be driven by the base moderate path through `GREATEST(...)`
- the detail view is a corrected live rebuild and not the official denominator
- booking totals in the detail view are inherited from the official aggregate table

As of `2026-07-25`, the live July 1 to July 24 totals are:

- official moderates = `571`
- detail rows = `569`
- official bookings = `25`

So the immediate fix is not to force the detail view to "invent" two more rows blindly.
The correct next step is to decide whether the detail view should mirror the official snapshot or remain a live operational rebuild, then align the data model accordingly.

Separately from the denominator question, the detail view now carries a full business-hours SLA model (working hours 9 AM–6 PM, simultaneous lunch 12–1 PM, Mon–Sun) via `effective_moderate_tagged_at` and `minutes_to_reply_sla`. This is a reply-time fairness feature and is orthogonal to the moderate-count reconciliation above — it does not change which rows are counted, only how reply time is measured. Note that anchoring the reply window on `moderate_tagged_at` (replies now only count if they occur after the moderate trigger) will reduce the response rate versus the older logic; this is intended and should be communicated before rollout.
