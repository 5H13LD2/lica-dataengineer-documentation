# Materialization deploy runbook — v_looker_first_reply_detail

## Why (verified, not assumed)

Dry-run tests against `manychat_data.messages`:

- Table is `PARTITION BY DATE(datetime)` with `require_partition_filter=true`.
- A **subquery/correlated** date bound is **REJECTED**: *"Cannot query ... without a filter over 'datetime' that can be used for partition elimination."* → so you **cannot** optimize this inside a plain view; it always scans the wide static floor.
- A **literal** datetime range (`datetime >= '2026-07-18'`) prunes cleanly: **642 KB** processed vs the wide static-floor scan.

Conclusion: the fix is **materialize into a partitioned table + rolling refresh with a literal date window**, not a view rewrite. `chat_analysis_data` and `turn_trace_log` are NOT partition-gated (they scan fully regardless), so the big win is bounding `messages`.

## Files (run in order)

| Step | File | Run when | Cost |
|---|---|---|---|
| 1 | `01_create_t_first_reply_detail.sql` | ONCE (initial build) | expensive one-time full-history pass |
| 2 | `02_swap_view_to_passthrough.sql` | ONCE, after step 1 succeeds | trivial |
| 3 | `03_refresh_rolling_window.sql` | every scheduled refresh | cheap (literal-bounded, prunes) |

## Deploy sequence

1. Run **step 1** in BigQuery console. Confirm `t_first_reply_detail` populated (row count ≈ current view row count for all history).
2. Run **step 2**. The view name now points at the table. Looker + all `t_moderate_*` downstream keep working unchanged (they still read `v_looker_first_reply_detail`).
3. Run **step 3** once manually to confirm it succeeds and prunes (check the job's bytes processed — should be MB-scale, not GiB).
4. Add **step 3** to the FRONT of `gulong_reporting.refresh_moderate_reporting_tables()` — before the `t_moderate_*` rebuilds, since they depend on this table.
5. Confirm the scheduler cadence matches the moderate pipeline (align with `p_dashboard_physical_refresh_log`).

## Validation (run after step 2, before trusting dashboards)

Use a FIXED historical week, not "today":

1. **Row parity:** per `report_date`, `COUNT(*)` and `COUNT(DISTINCT manychat_id)` from `t_first_reply_detail` must match the pre-materialization view. (Keep a saved copy of the old view SQL to diff against, or snapshot counts before step 2.)
2. **Backfill coverage:** `name_source` / `contact_source` distributions unchanged (synthetic ~0).
3. **SLA sanity:** no negative `minutes_to_reply_sla`.
4. **Dashboard bytes:** dry-run the one-day dashboard aggregate against the passthrough view. Target well under 1 GiB (was ~9 GiB).

Reference queries: `../validation/`.

## Rollback

If anything looks wrong after step 2, restore the original live view:

```sql
CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_first_reply_detail` AS
<original full view body>;
```

Keep the original view SQL saved before starting. The table `t_first_reply_detail` can be left in place (harmless) or dropped.

## Tuning

- `WINDOW_DAYS` = 35 (in step 3). Covers late-arriving chat_analysis re-evals + session backfills. Lower = cheaper refresh but risk of missing late corrections; higher = safer but more scan.
- Consider a periodic (weekly) full rebuild via step 1 to catch anything older than the window that changed.

## Invariants (do not regress)

Same as the model's core rules: grain = one row per `report_date + manychat_id`; reply window uses RAW `moderate_tagged_at`; SLA fairness only in `effective_moderate_tagged_at` + lunch subtraction with `GREATEST(...,0)`; name/contact backfill order intact; single-backslash phone regex; INT64 metric casts; `type='msgout_lc'` on agent replies.
