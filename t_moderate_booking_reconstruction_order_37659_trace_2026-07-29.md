# t_moderate_booking_reconstruction Order 37659 Trace

Date: 2026-07-29

## Goal

Trace why `order_id = 37659` does not appear in `gulong_reporting.t_moderate_booking_reconstruction` even though it exists in the official booking source.

## Summary

`order_id = 37659` exists in `gulong_core.orders_booked` and has a valid exact inquiry-session match in `gulong_reporting.v_looker_first_reply_detail`.

When the reconstruction match logic is replayed directly, the order qualifies as:

- `booking_match_rule = EXACT INQUIRY SESSION`
- `booking_match_rn = 1`

So the order should be eligible for reconstruction.

However:

- `gulong_reporting.t_moderate_booking_reconstruction` currently does not contain `37659`
- current warehouse snapshot on `2026-07-29` also shows `gulong_reporting.p_looker_agent_daily_conversion` = `1` booking for `2026-07-28`

That means the current live discrepancy is not:

- `p_looker_agent_daily_conversion` vs `t_moderate_booking_reconstruction`

The current discrepancy is:

- `gulong_core.orders_booked` = `2`
- `p_looker_agent_daily_conversion` = `1`
- `t_moderate_booking_reconstruction` = `1`

So `37659` is currently missing from both downstream reporting outputs.

## Evidence

### 1. Official bookings source has 2 rows on 2026-07-28

Rows found in `gulong_core.orders_booked`:

- `37636`
- `37659`

### 2. `37659` has a valid inquiry session

Official booking row:

- `order_id = 37659`
- `booking_day = 2026-07-28`
- `booking_at = 2026-07-28 17:06:00`
- `manychat_id = 2845998122184220`
- `inquiry_silver_session_id = 31698e21bbffe3bc05784586c258d032`
- `customer_name = joan gonzales`

### 3. `v_looker_first_reply_detail` has the matching replied session

Matched session:

- `report_date = 2026-07-27`
- `silver_session_id = 31698e21bbffe3bc05784586c258d032`
- `manychat_id = 2845998122184220`
- `reply_status = Has CS Reply`
- `reply_agent_name = sarah gulongph`
- `first_customer_message_at = 2026-07-27 12:36:37`
- `first_cs_reply_at = 2026-07-27 13:29:08`

### 4. Direct replay of the reconstruction logic matches the order

Direct replay result:

- `order_id = 37659`
- `booking_match_rule = EXACT INQUIRY SESSION`
- `booking_match_rn = 1`

This means the order qualifies under the deployed reconstruction matching rule.

### 5. Physical reconstruction table still excludes it

Current result for `booking_day = 2026-07-28`:

- `t_moderate_booking_reconstruction` = `1` order
- only `37636` appears
- `37659` is missing

## Interpretation

This is not explained by the core reconstruction match rule.

The trace shows that `37659`:

- is in official booked orders
- has an exact inquiry-session link
- has a valid replied moderate session
- qualifies when the reconstruction join logic is replayed

So the likely cause is downstream reporting refresh / snapshot lag rather than failure of the SQL matching condition itself.

## Important date-basis note

For booking volume comparisons in reconstruction, use:

- `booking_day`

not:

- `moderate_report_date`

Reference:

- [moderate_conversion_manual.md](/home/jerico/Desktop/gulong-mobile/moderate_conversion_manual.md:206)

## Current warehouse state on 2026-07-29

For `2026-07-28`:

- `orders_booked` official Chatbot/JCo bookings = `2`
- `p_looker_agent_daily_conversion` = `1`
- `t_moderate_booking_reconstruction` = `1`

So the missing order is currently absent from both downstream reporting outputs, not just reconstruction.

## Files

- [t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.sql](/home/jerico/Desktop/gulong-mobile/t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.sql)
- [t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.md](/home/jerico/Desktop/gulong-mobile/t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.md)
