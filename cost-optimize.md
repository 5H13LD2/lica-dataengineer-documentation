# BigQuery Cost Optimization Plan

**Scope:** [`v_looker_first_reply_detail(2).sql`](/home/jerico/Desktop/gulong-data/v_looker_first_reply_detail(2).sql) and [`followups_manual/`](/home/jerico/Desktop/gulong-data/followups_manual)  
**Goal:** reduce dashboard query cost without removing booking attribution, contact backfill, name backfill, or SLA logic.

## Summary

The cost spike is not caused by one thing only.

There are two separate expensive patterns in the current reporting layer:

1. `v_looker_first_reply_detail` scans `manychat_data.messages` multiple times across a broad static date floor.
2. downstream follow-up and booking views still compute booking attribution live at dashboard/query time.

Because both patterns sit behind reporting views, a one-day dashboard filter does not keep the workload cheap.

That is why the correct fix is:

- tighten and reduce the raw message scans in `v_looker_first_reply_detail`
- move booking attribution out of interactive views and into scheduled physical tables

Do not weaken attribution logic to save cost.

## Current Cost Drivers

### 1. Repeated raw-message scans in first-reply detail

In [`v_looker_first_reply_detail(2).sql`](/home/jerico/Desktop/gulong-data/v_looker_first_reply_detail(2).sql), the logic reads `manychat_data.messages` in at least these places:

- `contact_from_messages`
- `message_first_customer`
- `messages_filtered`

Those scans use broad lower bounds like:

```sql
datetime >= DATETIME '2026-03-01 00:00:00'
```

That satisfies partition filtering, but it still opens a large date range. When the dashboard asks for one day, BigQuery can still end up scanning far more than that one day because the expensive work is inside the view body.

### 2. Repeated chat-analysis scans

The same pattern also exists for `chat_analysis.chat_analysis_data`:

- moderate intent correction
- contact backfill

This is smaller than the raw-message issue, but it still adds unnecessary repeated scan cost.

### 3. Live booking attribution in follow-up views

The bigger structural problem is in [`followups_manual/moderate_followup_deploy.sql`](/home/jerico/Desktop/gulong-data/followups_manual/moderate_followup_deploy.sql).

In the coverage and reconstruction logic, official bookings are matched back to moderates using predicates like:

```sql
b.inquiry_silver_session_id = m.silver_session_id
OR m.first_customer_message_at <= b.booking_at
```

That match rule is correct for attribution, but expensive for interactive use. It creates a broad temporal join between bookings and the full moderate cohort. When done inside a view, every tile refresh can recompute it.

### 4. Refresh procedure still depends on the live first-reply view

[`followups_manual/REFRESH.sql`](/home/jerico/Desktop/gulong-data/followups_manual/REFRESH.sql) rebuilds downstream tables from `v_looker_first_reply_detail`.

That means even scheduled refreshes still pay the live view cost unless `v_looker_first_reply_detail` itself becomes cheap or materialized.

## What To Change

## Phase 1

Reduce the scan range inside `v_looker_first_reply_detail`.

Replace broad static date floors with cohort-bounded date filters derived from the selected report dates. Apply that to:

- `contact_from_analysis`
- `contact_from_messages`
- `message_first_customer`
- `messages_filtered`

Keep per-row matching logic exactly the same. Only reduce the scanned date range.

## Phase 2

Collapse repeated `manychat_data.messages` reads into a single bounded staging CTE.

Recommended shape:

- one cohort-bounded `messages` CTE
- project only needed columns
- split into user-message and agent-message logic downstream

Do not select large unused JSON columns.

## Phase 3

Materialize `v_looker_first_reply_detail` into a partitioned physical table, then keep the view name as a thin passthrough.

Recommended pattern:

1. build `gulong_reporting.t_first_reply_detail`
2. partition by `report_date`
3. cluster by reporting dimensions used most often
4. replace `v_looker_first_reply_detail` with:

```sql
SELECT * FROM `gulong-chatbot-459723.gulong_reporting.t_first_reply_detail`
```

This keeps downstream SQL unchanged while removing heavy raw-message work from dashboard time.

## Phase 4

Move booking attribution fully out of interactive views.

The current repo already points in the right direction with [`followups_manual/t_moderate_booking_reconstruction_latest.sql`](/home/jerico/Desktop/gulong-data/followups_manual/t_moderate_booking_reconstruction_latest.sql), which builds a physical booking reconstruction table.

That approach should become the canonical source for booking attribution used by dashboards.

Interactive reporting views should join precomputed attribution results instead of re-running booking matching logic live.

## Required Guardrails

- Do not remove booking attribution.
- Do not reduce the matching window just to lower cost.
- Do not remove contact or name backfills.
- Do not change reply-SLA semantics.

The fix is computation placement, not metric weakening.

## Validation Gates

Before release:

1. Compare booking IDs and booking counts for a fixed historical period.
2. Compare row counts and distinct `manychat_id` counts by `report_date`.
3. Dry-run the exact one-day dashboard queries.
4. Block release if a one-day query exceeds `1 GiB`.

After release:

- alert if this workload exceeds `0.5 TiB/day`
- alert if an individual dashboard query exceeds `1 GiB`

## Practical Repo Interpretation

Based on the current files:

- [`v_looker_first_reply_detail(2).sql`](/home/jerico/Desktop/gulong-data/v_looker_first_reply_detail(2).sql) contains the expensive raw-message scan pattern
- [`followups_manual/moderate_followup_deploy.sql`](/home/jerico/Desktop/gulong-data/followups_manual/moderate_followup_deploy.sql) contains the expensive live booking-attribution pattern
- [`followups_manual/REFRESH.sql`](/home/jerico/Desktop/gulong-data/followups_manual/REFRESH.sql) shows that downstream tables still depend on the live first-reply view

So the real fix is broader than optimizing one view in isolation.

## Immediate Recommendation

If only one change can be made first, do this:

1. materialize `v_looker_first_reply_detail`
2. keep the view name as a passthrough
3. repoint downstream dashboard booking logic to precomputed tables

That gives the highest confidence cost reduction without changing business logic.

## Implementation In This Repo

Use this order.

### Step 1: create a physical first-reply serving table

Add a new build script for:

- `gulong_reporting.t_first_reply_detail`

Recommended object shape:

- `PARTITION BY report_date`
- `CLUSTER BY source_agent_name, reporting_agent_name`

The SQL body should come from the current production logic in [`v_looker_first_reply_detail(2).sql`](/home/jerico/Desktop/gulong-data/v_looker_first_reply_detail(2).sql), but with these implementation changes:

- replace broad static `messages` date floors with bounded partition filters
- collapse repeated `manychat_data.messages` scans where safe
- keep all output columns and business logic unchanged

This table becomes the heavy-compute object.

### Step 2: replace the live dashboard view with a thin passthrough

After `t_first_reply_detail` exists, replace:

- `gulong_reporting.v_looker_first_reply_detail`

with:

```sql
CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail` AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.t_first_reply_detail`;
```

This is the rename-swap pattern.

Result:

- dashboards keep the same view name
- downstream SQL keeps working
- raw-message scans stop happening on every dashboard request

### Step 3: add rolling-window refresh for first-reply detail

Before rebuilding follow-up tables, refresh only the recent slice of `t_first_reply_detail`.

The right place for that is:

- [`followups_manual/REFRESH.sql`](/home/jerico/Desktop/gulong-data/followups_manual/REFRESH.sql)
- [`followups_manual/refresh_moderate_reporting_tables.sql`](/home/jerico/Desktop/gulong-data/followups_manual/refresh_moderate_reporting_tables.sql)

Add a new first block that:

1. keeps historical rows older than the rolling window
2. rebuilds only recent `report_date` rows from the optimized heavy SQL

Recommended window:

- `35 days`

That gives room for late bookings and backfilled upstream evidence.

### Step 4: stop doing booking attribution live in dashboard-facing views

Do not compute booking matching inside interactive dashboard views.

Instead:

- keep `t_moderate_booking_reconstruction` as the canonical precomputed booking attribution table
- make dashboard detail views read from that table
- where possible, make dashboard tiles read from a small daily aggregate table instead of event-level joins

Files to update:

- [`followups_manual/moderate_followup_deploy.sql`](/home/jerico/Desktop/gulong-data/followups_manual/moderate_followup_deploy.sql)
- [`followups_manual/t_moderate_booking_reconstruction_latest.sql`](/home/jerico/Desktop/gulong-data/followups_manual/t_moderate_booking_reconstruction_latest.sql)

Goal:

- live views may join precomputed booking results
- live views must not perform the expensive booking matching themselves

### Step 5: keep the procedure entrypoint the same

The scheduler can still call:

```sql
CALL `gulong-chatbot-459723.gulong_reporting.refresh_moderate_reporting_tables`();
```

Only the procedure internals change.

That keeps rollout risk lower.

## Concrete File Changes

Minimum repo change set:

1. Add a new SQL file for building `t_first_reply_detail`.
2. Replace the production view definition in [`v_looker_first_reply_detail(2).sql`](/home/jerico/Desktop/gulong-data/v_looker_first_reply_detail(2).sql) with the thin passthrough view after the table builder is ready.
3. Update [`followups_manual/REFRESH.sql`](/home/jerico/Desktop/gulong-data/followups_manual/REFRESH.sql) to refresh `t_first_reply_detail` before `t_moderate_followup_detail`.
4. Update [`followups_manual/refresh_moderate_reporting_tables.sql`](/home/jerico/Desktop/gulong-data/followups_manual/refresh_moderate_reporting_tables.sql) the same way.
5. Update downstream dashboard-facing SQL so booking attribution reads from `t_moderate_booking_reconstruction` instead of re-matching live.

## Safe Rollout Order

1. Build `t_first_reply_detail` in parallel with the current view.
2. Validate row parity and booking parity for a fixed historical period.
3. Dry-run the exact one-day dashboard queries.
4. If the one-day query is under `1 GiB`, swap `v_looker_first_reply_detail` to the passthrough view.
5. After the swap, update follow-up reporting views to consume the precomputed booking table where needed.
6. Monitor daily bytes after release.

## What Not To Do

- Do not delete booking columns from `v_looker_first_reply_detail`.
- Do not remove session-window logic from the business logic.
- Do not point dashboards directly at a heavy rebuild query.
- Do not keep both live booking attribution and precomputed booking attribution active in the same dashboard path.
