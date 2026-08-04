# t_moderate_booking_reconstruction Reconciliation Notes

Date: 2026-07-28

Refreshed note: 2026-08-04

## Goal

I-verify kung bakit may discrepancy sa `2026-07-27` bookings:

- `gulong_reporting.p_looker_agent_daily_conversion` = `5`
- `gulong_reporting.t_moderate_booking_reconstruction` = `2`

## Status Today

This document is a historical reconciliation note for the `2026-07-27` booking-day incident.

It should not be read as the current live state for all later dates.

As of `2026-08-04`, the current separate issue for `2026-07-28` is:

- `gulong_core.orders_booked` = `2`
- `gulong_reporting.t_moderate_booking_reconstruction` = `2`
- `gulong_reporting.p_looker_agent_daily_conversion` = `1`

So for the current live discrepancy, the lag is no longer in `t_moderate_booking_reconstruction`.
The remaining mismatch is in `p_looker_agent_daily_conversion`.

## Ginawa

1. Cinonfirm ang official KPI source:

```sql
SELECT report_date, agent_name, total_bookings
FROM `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
WHERE report_date = DATE '2026-07-27'
  AND agent_name = 'Chatbot/JCo';
```

Result: `5`

2. Cinonfirm ang raw official bookings source:

```sql
SELECT
  order_id,
  booking_day,
  booking_at,
  manychat_user_id,
  customer_name,
  inquiry_silver_session_id,
  inquiry_day
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE sales_reporting_agent_name = 'Chatbot/JCo'
  AND is_reportable_booked_order = TRUE
  AND booking_day = DATE '2026-07-27'
ORDER BY booking_at, order_id;
```

Result: `5` rows

Missing from the physical table at the time:

- `37622`
- `37625`
- `37626`

3. Cinonfirm ang physical table mismatch:

```sql
SELECT
  order_id,
  booking_day,
  moderate_report_date,
  booking_match_rule
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE booking_day = DATE '2026-07-27'
ORDER BY booking_at, order_id;
```

Result before refresh: `2` rows only

4. Cinonfirm ang live view:

```sql
SELECT
  order_id,
  booking_day,
  moderate_report_date,
  booking_match_rule
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`
WHERE booking_day = DATE '2026-07-27'
ORDER BY booking_at, order_id;
```

Result: `5` rows

Conclusion:

- tama ang live view logic
- stale lang ang `t_moderate_booking_reconstruction`

5. Ni-refresh ang physical table from the live view:

```sql
CREATE OR REPLACE TABLE `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
CLUSTER BY booking_day AS
SELECT *
FROM `gulong-chatbot-459723.gulong_reporting.v_looker_moderate_booking_reconstruction`;
```

6. Post-refresh verification:

```sql
SELECT COUNT(DISTINCT order_id) AS booking_count
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE booking_day = DATE '2026-07-27';
```

Result after refresh: `5`

## Final Accurate Rows For 2026-07-27

| order_id | booking_day | moderate_report_date | booking_match_rule |
|---|---|---|---|
| 37598 | 2026-07-27 | 2026-07-26 | EXACT INQUIRY SESSION |
| 37602 | 2026-07-27 | 2026-07-24 | LATEST PRIOR INQUIRY |
| 37622 | 2026-07-27 | 2026-07-27 | SESSION WINDOW |
| 37625 | 2026-07-27 | 2026-07-26 | EXACT INQUIRY SESSION |
| 37626 | 2026-07-27 | 2026-07-27 | EXACT INQUIRY SESSION |

## Root Cause

Hindi sira ang SQL matching logic ng booking reconstruction view. Ang discrepancy ay nanggaling sa stale physical table copy:

- live view had `5`
- physical table still had `2`

This root cause applies to the `2026-07-27` incident documented here.
It is not the current root cause of the separate `2026-07-28` mismatch checked on `2026-08-04`.

## Second Issue: Null `first_cs_reply_at`

After the booking count mismatch was fixed, a second issue appeared:

- `moderate_report_date` and `booking_day` were correct
- but many rows still had `first_cs_reply_at = null`

Example:

- `order_id = 37602`
- `moderate_report_date = 2026-07-24`
- `booking_day = 2026-07-27`
- `booking_match_rule = LATEST PRIOR INQUIRY`
- `first_cs_reply_at = null`

## Investigation For `37602`

The booking row itself:

```sql
SELECT
  order_id,
  booking_at,
  booking_day,
  moderate_report_date,
  booking_match_rule,
  first_customer_message_at
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE order_id = '37602';
```

Validated values:

- `booking_at = 2026-07-27 10:52:00`
- `moderate_report_date = 2026-07-24`
- `first_customer_message_at = 2026-07-24 11:28:24`

Raw ManyChat messages showed real human CS handling before booking:

```sql
SELECT
  datetime,
  role,
  sender,
  type,
  text_content
FROM `gulong-chatbot-459723.manychat_data.messages`
WHERE user_id = '27725099880464329'
  AND datetime >= DATETIME '2026-07-24 00:00:00'
  AND datetime < DATETIME '2026-07-28 00:00:00'
  AND role = 'agent'
ORDER BY datetime;
```

Important result for `37602`:

- first agent message after inquiry = `2026-07-26 14:50:37`
- sender = `sarah gulongph`

Conclusion:

- `37602` was CS handled
- the null `first_cs_reply_at` was a reconstruction gap
- the issue was not absence of CS handling

## Backfill Strategy

Rows with null `first_cs_reply_at` were checked against raw `manychat_data.messages` using:

- same `manychat_id`
- `business_unit = 'gulong'`
- `role = 'agent'`
- `type = 'msgout_lc'`
- `datetime >= first_customer_message_at`

Ranking rule used:

1. prefer earliest agent message `<= booking_at`
2. if none exists, use earliest agent message after inquiry

## Backfill Result

The in-place table backfill updated `38` rows.

`37602` after backfill:

- `reply_status = Has CS Reply`
- `reply_agent_name = sarah gulongph`
- `first_cs_reply_at = 2026-07-26 14:50:37`
- `minutes_to_first_reply = 3082`

## Remaining Nulls After Backfill

After the raw-message backfill:

- total remaining null `first_cs_reply_at` rows = `81`

Breakdown:

- `UNMATCHED OFFICIAL BOOKING` = `66`
- `SESSION WINDOW` = `13`
- `EXACT INQUIRY SESSION` = `2`

These were not resolved by the current raw ManyChat backfill run.

## Operational SQL Used

1. Rebuild the physical table from the live view
2. Run an in-place update from `manychat_data.messages`

See:

- `t_moderate_booking_reconstruction_latest.sql`

## Operational Fix

Kapag may ganitong discrepancy ulit:

1. Compare `p_looker_agent_daily_conversion`
2. Compare `orders_booked`
3. Compare `v_looker_moderate_booking_reconstruction`
4. Compare `t_moderate_booking_reconstruction`
5. If view is correct and table is behind, rerun the table rebuild
6. If `first_cs_reply_at` is still null on rows with valid session lineage, run the raw ManyChat backfill update

Current practical note for `2026-08-04`:

- do not rebuild `t_moderate_booking_reconstruction` just because `p_looker_agent_daily_conversion` is still `1`
- the reconstruction table already matches `orders_booked` for `2026-07-28`
- investigate or refresh the `p_looker_agent_daily_conversion` pipeline instead

## Related Files

- `L.sql` = latest local source for the reconstruction view/table definition
- `t_moderate_booking_reconstruction_latest.sql` = latest rebuild + CS reply backfill SQL for the physical table
