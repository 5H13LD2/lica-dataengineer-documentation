# Moderate Follow-up Reporting User Manual

## Purpose

This guide explains which tables to use for Chatbot/JCo moderate reporting, how the booking reconstruction works, and how to set up the reporting in Looker Studio.

Current note as of `2026-08-04`:
- `t_moderate_booking_reconstruction` is a refreshable physical copy of the live reconstruction view
- if `orders_booked` and `t_moderate_booking_reconstruction` already agree, do not assume a reconstruction code issue
- a mismatch against `p_looker_agent_daily_conversion` can be a separate downstream refresh or logic issue


## Reporting Objects

### 1. `gulong_reporting.v_looker_first_reply_detail`

Purpose:
- Source of truth for the refreshed `Chatbot/JCo` moderate cohort
- One row per moderate session
- Used as the upstream source for moderate denominator and reply analysis

Best for:
- Moderate counts
- Reply vs no reply
- First reply timing


### 2. `gulong_reporting.v_looker_moderate_followup_coverage`

Purpose:
- Session-level moderate coverage layer
- One row per moderate session
- Adds follow-up and session-level booking attribution fields

Best for:
- Moderate funnel reporting
- CS follow-up reporting
- Session-level conversion analysis

Main grain:
- `silver_session_id`


### 3. `gulong_reporting.t_moderate_followup_coverage`

Purpose:
- Physical table copy of `v_looker_moderate_followup_coverage`
- Recommended for Looker Studio when using the session-level coverage layer

Best for:
- Faster dashboard use
- Stable Looker Studio source


### 4. `gulong_reporting.v_looker_moderate_booking_reconstruction`

Purpose:
- Order-level reconstruction of official `Chatbot/JCo` bookings from `orders_booked`
- One row per booked `order_id`
- Matches bookings back to the nearest available moderate or inquiry lineage

Best for:
- Booking reconciliation
- Order ID tracing
- Reporting booked users with booking date and moderate date

Main grain:
- `order_id`


### 5. `gulong_reporting.t_moderate_booking_reconstruction`

Purpose:
- Physical table copy of `v_looker_moderate_booking_reconstruction`
- Recommended source for Looker Studio when the report needs official order IDs

Best for:
- Booked orders table
- Conversion date table
- Booking export

Important operational note:
- this is a physical table and can temporarily lag behind the live view until refreshed
- if refreshed and it already matches `orders_booked`, the remaining discrepancy is somewhere else


## Which Table To Use

Use `t_moderate_followup_coverage` if the main question is:
- How many moderates were there?
- How many had CS reply?
- How many had CS follow-up?
- How many converted at session level?

Use `t_moderate_booking_reconstruction` if the main question is:
- Which exact `order_id` got booked?
- What is the booking date?
- Which user booked?
- What moderate or inquiry lineage was used to match the booking?


## Booking Reconstruction Logic

Official booking source:
- `gulong_core.orders_booked`

Included booking universe:
- `sales_reporting_agent_name = 'Chatbot/JCo'`
- `is_reportable_booked_order = TRUE`

Match priority used in `t_moderate_booking_reconstruction`:
1. `EXACT INQUIRY SESSION`
2. `SESSION WINDOW`
3. `LATEST PRIOR MODERATE`
4. `LATEST PRIOR INQUIRY`
5. `UNMATCHED OFFICIAL BOOKING`

Interpretation:
- `EXACT INQUIRY SESSION`
  The booking points directly to the same inquiry session as the moderate lineage.
- `SESSION WINDOW`
  The booking happened within the same manychat session window.
- `LATEST PRIOR MODERATE`
  No exact/session-window hit; booking was attached to the latest earlier moderate for the same `manychat_id`.
- `LATEST PRIOR INQUIRY`
  No moderate match survived, but a prior inquiry lineage exists for the same `manychat_id`.
- `UNMATCHED OFFICIAL BOOKING`
  The booking is official, but no usable moderate or inquiry lineage could be matched.


## Current Reconciliation Result

For the CSV source:
- `Gulong Operations Report_fb inquries daily_Table.csv`

Current result after reconstruction:
- `22 / 23` order IDs matched into `t_moderate_booking_reconstruction`
- `1 / 23` not matched: `36740`

Important note:
- `36740` is present in the operations CSV but was not found in the raw `orders_booked` booking source during reconciliation.


## Looker Studio Setup

## Refresh Runbook

If the `t_` tables fall behind the live `v_` views, rerun:

- [refresh_moderate_reporting_tables.sql](/home/jerico/Desktop/gulong-data/followups_manual/refresh_moderate_reporting_tables.sql)

This refreshes, in order:

- `gulong_reporting.t_moderate_followup_detail`
- `gulong_reporting.t_moderate_followup_coverage`
- `gulong_reporting.t_moderate_booking_reconstruction`

Use this when new moderate, follow-up, or booking rows are visible in the live views but missing in Looker Studio.

Do not use this as the default fix for every booking mismatch.

Check in this order:
- `orders_booked`
- `v_looker_moderate_booking_reconstruction`
- `t_moderate_booking_reconstruction`
- `p_looker_agent_daily_conversion`

If `orders_booked = view = table`, then the issue is not a reconstruction refresh problem.

### A. Booked Orders Table

Recommended source:
- `gulong_reporting.t_moderate_booking_reconstruction`

Use these fields:
- `moderate_report_date`
- `booking_day`
- `user_name`
- `contact_number`
- `manychat_id`
- `order_id`
- `booking_match_rule`
- `booking_owner_bucket`

Recommended display labels:
- `moderate_report_date` -> `Moderate Date`
- `booking_day` -> `Booking Date`
- `user_name` -> `User Name`
- `contact_number` -> `Contact No`
- `manychat_id` -> `Manychat ID`
- `order_id` -> `Order ID`
- `booking_match_rule` -> `Match Rule`
- `booking_owner_bucket` -> `Booking Owner`

Recommended calculated fields:

```text
Is Booked = "Yes"
```

```text
Days To Convert = DATE_DIFF(booking_day, moderate_report_date)
```

Recommended sort:
1. `booking_day` descending
2. `moderate_report_date` ascending
3. `order_id` descending


### B. Strict Moderate-to-Booking Table

If the user only wants rows with a proven moderate date, use:
- source: `gulong_reporting.t_moderate_booking_reconstruction`
- filter: `moderate_report_date is not null`

This excludes:
- `LATEST PRIOR INQUIRY` rows without moderate date
- `UNMATCHED OFFICIAL BOOKING`


### C. Official Bookings Table Including Fallbacks

If the user wants all official bookings from the reconstruction output, including fallback-linked orders:
- source: `gulong_reporting.t_moderate_booking_reconstruction`
- no filter on `moderate_report_date`

This includes:
- exact moderate-linked orders
- inquiry fallback orders
- unmatched official bookings


## Recommended Filters

For moderate cohort reporting:
- filter by `moderate_report_date`

For booking volume reporting:
- filter by `booking_day`

For strict moderate conversions only:
- `moderate_report_date is not null`

For fallback review:
- `booking_match_rule in ('LATEST PRIOR INQUIRY', 'UNMATCHED OFFICIAL BOOKING')`


## Recommended KPI Usage

If the KPI is about moderates:
- use `t_moderate_followup_coverage`

If the KPI is about official booked orders:
- use `t_moderate_booking_reconstruction`

Important:
- Do not use `first_chatbot_order_id` from the coverage table as the official booking source of truth.
- Use `t_moderate_booking_reconstruction` for order-level official booking reporting.
- Do not use `p_looker_agent_daily_conversion` as the row-level order-ID source of truth.


## Field Reference

### `t_moderate_followup_coverage`

Important fields:
- `moderate_report_date`
- `manychat_id`
- `user_name`
- `contact_number`
- `reply_status`
- `cs_followup_status`
- `booked_in_chatbot_cohort`
- `booking_owner_bucket`
- `first_chatbot_booking_date`
- `first_chatbot_order_id`


### `t_moderate_booking_reconstruction`

Important fields:
- `booking_day`
- `order_id`
- `manychat_id`
- `user_name`
- `contact_number`
- `moderate_report_date`
- `booking_match_rule`
- `booking_owner_bucket`
- `days_from_moderate_to_booking`


## Practical Rule Of Thumb

If you need:
- session funnel -> use `t_moderate_followup_coverage`
- exact booked orders -> use `t_moderate_booking_reconstruction`
- official order ID validation -> use `t_moderate_booking_reconstruction`
- strict moderate conversion rows only -> filter `moderate_report_date is not null`

If counts disagree:
- `orders_booked` and `t_moderate_booking_reconstruction` together usually answer the official order-level question
- `p_looker_agent_daily_conversion` is a separate aggregated reporting layer and may need its own refresh or logic review


## Validation Query Example

```sql
SELECT
  order_id,
  booking_day,
  moderate_report_date,
  user_name,
  manychat_id,
  booking_match_rule,
  booking_owner_bucket
FROM `gulong-chatbot-459723.gulong_reporting.t_moderate_booking_reconstruction`
WHERE booking_day BETWEEN DATE '2026-07-01' AND DATE '2026-07-24'
ORDER BY booking_day, order_id;
```
