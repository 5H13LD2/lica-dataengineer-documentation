# t_moderate_booking_reconstruction Order 37659 Trace

Original trace date: 2026-07-29

Refreshed: 2026-08-04

## Goal

Refresh the earlier trace for `order_id = 37659` and confirm the current warehouse state for `gulong_reporting.t_moderate_booking_reconstruction`.

## Summary

The earlier 2026-07-29 trace is now stale.

As of `2026-08-04`:

- `order_id = 37659` is present in `gulong_core.orders_booked`
- it still has a valid exact inquiry-session match in `gulong_reporting.v_looker_first_reply_detail`
- direct replay of the current reconstruction logic still ranks it as:
- `booking_match_rule = EXACT INQUIRY SESSION`
- `booking_match_rn = 1`
- `gulong_reporting.t_moderate_booking_reconstruction` now contains `37659`

Current `2026-07-28` booking-day state:

- `gulong_core.orders_booked` = `2`
- `gulong_reporting.t_moderate_booking_reconstruction` = `2`
- `gulong_reporting.p_looker_agent_daily_conversion` = `1`

So the old reconstruction gap has been resolved. The remaining mismatch is now between:

- `orders_booked` / `t_moderate_booking_reconstruction` = `2`
- `p_looker_agent_daily_conversion` = `1`

## Evidence

### 1. Official bookings source still has 2 rows on 2026-07-28

Rows found in `gulong_core.orders_booked`:

- `37636`
- `37659`

### 2. `37659` still has a valid inquiry session

Official booking row:

- `order_id = 37659`
- `booking_day = 2026-07-28`
- `booking_at = 2026-07-28 17:06:00`
- `manychat_id = 2845998122184220`
- `inquiry_silver_session_id = 31698e21bbffe3bc05784586c258d032`
- `customer_name = joan gonzales`

### 3. `v_looker_first_reply_detail` still has the matching replied session

Matched session:

- `report_date = 2026-07-27`
- `silver_session_id = 31698e21bbffe3bc05784586c258d032`
- `manychat_id = 2845998122184220`
- `reply_status = Has CS Reply`
- `reply_agent_name = sarah gulongph`
- `first_customer_message_at = 2026-07-27 12:36:37`
- `first_cs_reply_at = 2026-07-27 13:29:08`

### 4. Direct replay of the current reconstruction logic still matches the order

Direct replay result:

- `order_id = 37659`
- `booking_match_rule = EXACT INQUIRY SESSION`
- `booking_match_rn = 1`

This means the order still qualifies under the current reconstruction matching rule.

### 5. Physical reconstruction table now includes it

Current result for `booking_day = 2026-07-28`:

- `t_moderate_booking_reconstruction` = `2` orders
- `37636` appears
- `37659` appears

Current row for `37659` in `t_moderate_booking_reconstruction`:

- `order_id = 37659`
- `booking_day = 2026-07-28`
- `moderate_report_date = 2026-07-27`
- `silver_session_id = 31698e21bbffe3bc05784586c258d032`
- `booking_match_rule = EXACT INQUIRY SESSION`
- `booking_owner_bucket = CS Assisted`
- `reply_status = Has CS Reply`
- `reply_agent_name = sarah gulongph`

## Interpretation

The earlier missing row was consistent with refresh lag or a stale physical snapshot, not with a failure of the reconstruction matching logic itself.

That old gap is no longer present in the current warehouse state.

The refreshed trace shows that `37659`:

- is in official booked orders
- has an exact inquiry-session link
- has a valid replied moderate session
- qualifies when the current reconstruction join logic is replayed
- is now physically present in `t_moderate_booking_reconstruction`

So the open reporting discrepancy has shifted downstream to `p_looker_agent_daily_conversion`, not the reconstruction table.

## Important date-basis note

For booking volume comparisons in reconstruction, use:

- `booking_day`

not:

- `moderate_report_date`

Reference:

- [moderate_conversion_manual.md](/home/jerico/Desktop/gulong-data/moderate_conversion_manual.md:206)

## Current warehouse state on 2026-08-04

For `2026-07-28`:

- `orders_booked` official Chatbot/JCo bookings = `2`
- `t_moderate_booking_reconstruction` = `2`
- `p_looker_agent_daily_conversion` = `1`

Current reconstruction rows:

- `37636` -> `LATEST PRIOR INQUIRY`, `Chatbot Only`
- `37659` -> `EXACT INQUIRY SESSION`, `CS Assisted`

So `37659` is no longer missing from reconstruction.

## Files

- [t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.sql](/home/jerico/Desktop/gulong-data/t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.sql)
- [t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.md](/home/jerico/Desktop/gulong-data/t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.md)
