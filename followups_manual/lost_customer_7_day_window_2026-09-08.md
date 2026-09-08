# Lost customers: 7-day messaging window and Looker Studio

Documented: 2026-09-08. Business timezone: Asia/Manila.
Status: investigation notes and verified query results; not a change to the reporting contract.

## Purpose and agreed scorecard

The requested scorecard counts unique customers whose 7-day messaging window
expired on September 7, 2026 and who remained unbooked at that day's end.
August inquiries remain in scope. Production verification returned **77 unique
customers**, also representing 77 inquiry rows.

This is a snapshot-based operational classification, not proof that a customer
will never return or book later.

## Sources reviewed

- `gulong-dashboard/docs/investigations/20260828-dashboard-consistency-freshness-20260828/journal.md`
- `gulong-dashboard/backend/app/refresh_conversion.py`
- `gulong-dashboard/backend/app/config.py`
- `gulong-dashboard/docs/DATA_SOURCES_AND_LINEAGE.md`
- `followups_manual/moderate_followup_deploy.sql`
- `followups_manual/manage_label_logic.sql`
- `followups_manual/REFRESH.sql`
- `followups_manual/refresh_moderate_reporting_tables.sql`
- `followups_manual/t_moderate_booking_reconstruction_latest.sql`
- `clean-up/L.sql`
- `clean-up/t_moderate_booking_reconstruction_reconciliation_2026-07-28.md`

## Coverage pipeline versus lifecycle pipeline

The user's existing Gold source is:

`gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`

Its production refresh is:

```sql
CREATE OR REPLACE TABLE
  `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_detail`
CLUSTER BY followup_date AS
SELECT * FROM
  `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_detail`;

CREATE OR REPLACE TABLE
  `gulong-chatbot-459723.gulong_reporting.t_moderate_followup_coverage`
CLUSTER BY moderate_report_date AS
SELECT * FROM
  `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_followup_coverage`;
```

These statements refresh detail before coverage, matching the dependency order.
They copy deployed view definitions; they do not deploy local SQL changes.
The coverage view reads the physical follow-up detail table and calculates its
official Chatbot/JCo booking totals from `orders_booked`.

The third table refresh in `REFRESH.sql`, for booking reconstruction, is not
required for the coverage dependency chain. `clean-up/L.sql` defines that
separate reconstruction view/table. Its logic differs from the narrower direct
table rebuild in `t_moderate_booking_reconstruction_latest.sql`; the files should
not be treated as interchangeable definitions.

The coverage table has **no equivalent Lost/7-day-expiry column in the reviewed
local SQL**. The existing lifecycle classification is in:

`gulong-chatbot-459723.gulong_reporting.t_inquiry_followup_status_daily`

This is a downstream dashboard mart, maintained by the dashboard refresh. The
two coverage refresh statements do not independently refresh that lifecycle mart.

## Meaning of Lost

The reviewed dashboard code calculates:

```text
messaging_window_expires_at = last observed customer message + 7 days
```

Classification at the selected snapshot:

1. Observed attributed booking exists: `Booked`.
2. No customer-message evidence to calculate expiry: `Unresolved`.
3. Snapshot time is before expiry: `Eligible`.
4. Otherwise: `Lost`.

Relevant columns:

| Column | Use |
|---|---|
| `lifecycle_state` | Filter to `Lost` |
| `lifecycle_status` | Lost rows have `7-day messaging window expired` |
| `messaging_window_expires_at` | Actual expiry datetime used by the model |
| `snapshot_date` | Choose the observation day |
| `snapshot_at` | Exact observation cutoff |
| `inquiry_date` | Original inquiry cohort date |
| `manychat_user_id` | Distinct customer count |
| `inquiry_key` | Distinct inquiry count |
| `source_refreshed_at` | Refresh generation timestamp |

`stop chatbot` is not a Lost flag. It can indicate automation stopped while a
human continues handling the conversation. `stop follow up` and `no need follow`
are separate stop instructions, not evidence of elapsed time.

Local coverage definitions conflict: `moderate_followup_deploy.sql` folds
`stop chatbot` into the stop-follow-up marker, whereas `manage_label_logic.sql`
separates it and exposes an active-backlog metric that retains human-handled
conversations. Which version is deployed was not verified in this conversation.

## Three different questions

| Question | Date basis and filters | Verified result |
|---|---|---:|
| All customers Lost as of Sept 7, including older inquiries | Sept 7 snapshot, state Lost, no inquiry-date filter | 3,519 |
| Customers from Sept 1–7 inquiries who were Lost as of Sept 7 | Same snapshot/state, inquiry date Sept 1–7 | 0 |
| Customers whose window expired Sept 7 and were Lost at day end | Sept 7 snapshot, state Lost, expiry date Sept 7 | 77 |

For Sept 1–7 inquiry cohorts observed in the Sept 8 snapshot, the Lost customer
count was **9**.

The requested scorecard is the third question. An August inquiry is included
when its last observed customer message makes the expiry date September 7.
For example: August 28 inquiry, August 31 customer reply, September 7 expiry.

The 77 is not simply the difference between consecutive daily Lost totals:
customers can book or return, and lifecycle membership can change.

## Production freshness verification

Read-only BigQuery checks were run on September 8, 2026. No production data or
SQL definitions were modified.

All times below are Manila time:

- Lifecycle table last modified: **Sept 8, 07:47:36**.
- Latest lifecycle snapshot cutoff: **Sept 8, 07:45:11.652900**.
- Latest customer message represented in that snapshot: **Sept 8, 06:54:07**.
- Latest inquiry date represented: **Sept 7**.
- Coverage table last modified: **Sept 8, 09:22:34**.
- Follow-up detail table last modified: **Sept 8, 09:22:28**.
- All four dashboard marts had the same table modification timestamp,
  Sept 8, 07:47:36. This alone is not a full reconciliation test.

| Snapshot date | Inquiry rows | Lost inquiry rows | Distinct Lost customers |
|---|---:|---:|---:|
| Sept 1 | 3,704 | 3,139 | 3,139 |
| Sept 2 | 3,710 | 3,218 | 3,218 |
| Sept 3 | 3,725 | 3,286 | 3,286 |
| Sept 4 | 3,789 | 3,350 | 3,350 |
| Sept 5 | 3,906 | 3,397 | 3,397 |
| Sept 6 | 4,000 | 3,446 | 3,446 |
| Sept 7 | 4,102 | 3,519 | 3,519 |
| Sept 8 | 4,102 | 3,530 | 3,530 |

These totals include all available inquiry cohorts at each snapshot. They are
not newly expired counts and must not be summed across dates.

The latest represented customer message stayed at Sept 1, 07:47:59 in the Sept
1–3 snapshots, then advanced in subsequent snapshots. The table itself was not
stuck at September 1. This check did not audit raw-message ingestion end to end.

The August 28 investigation documented historical memory failures and partial
dashboard publication, followed by local remediation validation. Its historical
cutoffs are not the September 8 production state verified above.

## Final custom query for the 77-customer scorecard

In Looker Studio, choose **BigQuery → Custom Query** and paste:

```sql
SELECT
  COUNT(DISTINCT manychat_user_id) AS lost_customers
FROM
  `gulong-chatbot-459723.gulong_reporting.t_inquiry_followup_status_daily`
WHERE snapshot_date = DATE '2026-09-07'
  AND lifecycle_state = 'Lost'
  AND DATE(messaging_window_expires_at) = DATE '2026-09-07'
```

Scorecard configuration:

- Metric: `lost_customers`.
- Aggregation: **SUM**.
- Expected result at verification: **77**.
- Suggested title: **Customers expired Sept 7 — unbooked at day end**.

The SQL returns one aggregate row. It is fixed to September 7, 2026 and does
not follow the report's date control. Automatic period selection needs a
separate parameterized query with an explicit snapshot-selection rule; that
query was not implemented in this conversation.

The validation query also selected `COUNT(*) AS expired_inquiry_rows`; both
that count and the distinct customer count returned 77. The dry run estimated
167,929 bytes, and execution used a 262,144,000-byte billing cap.

## Alternative: scorecard directly on the lifecycle table

Create this calculated field:

Name: `Window Expiry Date`

```text
DATE(messaging_window_expires_at)
```

This only removes the time; the source already calculates last customer
message plus seven days.

Configure:

1. Metric: `manychat_user_id`, aggregation **Count Distinct**.
2. Date range dimension: `Window Expiry Date`.
3. Report date selection: September 7, 2026 only.
4. Include filter: `lifecycle_state = Lost`.
5. Include filter: `snapshot_date = September 7, 2026`.
6. Do not filter `inquiry_date` for the agreed scorecard.

An Auto date range filters the configured date dimension. It does not
automatically choose a matching snapshot. A fixed snapshot filter will remain
fixed when the report date changes.

## Corrections and interpretation limits

- The initial suggestion to use `moderate_report_date + 7 calendar days`
  described the SQL follow-up matching window, not this lifecycle expiry rule.
  The lifecycle uses the last customer message plus seven days.
- The suggestion that 3,519 might be caused by session counting was not borne
  out: both inquiry rows and distinct customers were 3,519 for Sept 7. Older
  inquiry cohorts explain why that total exceeds the September-only cohort.
- Filtering inquiry dates to September answers a cohort question and excludes
  August inquiries that belong in the requested expiry-period scorecard.
- The booking reconstruction refresh is not required for the user's coverage
  dependency chain; it serves a separate table.
- Distinct customers among Lost inquiry rows means customers with at least one
  qualifying Lost inquiry. It does not globally exclude someone with another
  Booked or Eligible inquiry. Such exclusion requires a customer-level rule.
- The expiry-day query counts Lost status at day end. It does not capture every
  transient expiry event followed by a customer return or booking before that
  cutoff, and it is not a first-ever-loss event count.
- Historical snapshots can carry historical refresh generations. The dashboard
  API's active-generation restrictions do not automatically apply to a direct
  Looker BigQuery query. Use the snapshot deliberately and assess historical
  repairs separately.
- The Looker report configuration itself was not inspected or changed. The
  documented SQL result was verified directly in BigQuery.

## Practices confirmed and follow-up

Good practice confirmed: separate inquiry date, expiry date, and observation
date; verify both row and distinct-customer counts; use bounded read-only
queries and dry runs before interpreting a scorecard.

Failure mode observed: treating an Auto date selection as if it filtered all
date meanings, or treating a cumulative Lost total as newly expired customers.

No reporting rule was changed. These findings support documenting the date
basis and cutoff on the scorecard. Dynamic date controls and a global
customer-level Lost definition remain separate implementation decisions.
