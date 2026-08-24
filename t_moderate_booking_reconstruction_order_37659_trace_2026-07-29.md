# t_moderate_booking_reconstruction Order 37659 Trace

Original trace date: 2026-07-29

Refreshed: 2026-08-14

## Goal

Refresh the earlier trace for `order_id = 37659` and confirm the current warehouse state for `gulong_reporting.t_moderate_booking_reconstruction`.

## Summary

The earlier 2026-08-04 trace is now stale.

As of `2026-08-14`:

- `order_id = 37659` is no longer present in `gulong_core.orders_booked`
- because the official booking row is gone, the direct reconstruction replay for `37659` returns no match candidates
- `gulong_reporting.t_moderate_booking_reconstruction` no longer contains `37659`
- `gulong_reporting.v_looker_moderate_booking_reconstruction` also no longer contains `37659`

Current `2026-07-28` booking-day state:

- `gulong_core.orders_booked` = `1`
- `gulong_reporting.t_moderate_booking_reconstruction` = `1`
- `gulong_reporting.p_looker_agent_daily_conversion` = `1`

So the old reconstruction mismatch is no longer a reconstruction issue. The current warehouse state is internally aligned for `2026-07-28`, with only `order_id = 37636` remaining in the official Chatbot/JCo booking source.

## Evidence

### 1. Official bookings source now has 1 row on 2026-07-28

Current row found in `gulong_core.orders_booked`:

- `37636`

Direct lookup for `37659` now returns no row.

### 2. `v_looker_first_reply_detail` still has the historical replied session

Historical matched session:

- `report_date = 2026-07-27`
- `silver_session_id = 31698e21bbffe3bc05784586c258d032`
- `manychat_id = 2845998122184220`
- `reply_status = Has CS Reply`
- `reply_agent_name = sarah gulongph`
- `first_customer_message_at = 2026-07-27 12:36:37`
- `first_cs_reply_at = 2026-07-27 13:29:08`

### 3. Direct replay of the current reconstruction logic no longer returns `37659`

The replay query now returns no candidate row for `37659` because the official booking CTE itself is empty for that order.

### 4. Physical reconstruction table no longer includes it

Current result for `booking_day = 2026-07-28`:

- `t_moderate_booking_reconstruction` = `1` order
- `37636` appears
- `37659` does not appear

The same is true for `v_looker_moderate_booking_reconstruction`.

## Interpretation

The warehouse state changed again after the August 4 refresh.

The refreshed trace now shows:

- the historical replied session still exists in `v_looker_first_reply_detail`
- but `37659` itself no longer exists in the official `orders_booked` source
- so it cannot be reconstructed into `t_moderate_booking_reconstruction`
- and the `2026-07-28` counts are now aligned across `orders_booked`, `t_moderate_booking_reconstruction`, and `p_looker_agent_daily_conversion`

The active issue is no longer a stale reconstruction snapshot. The source booking universe itself has changed.

## Important date-basis note

For booking volume comparisons in reconstruction, use:

- `booking_day`

not:

- `moderate_report_date`

Reference:

- [moderate_conversion_manual.md](/home/jerico/Desktop/gulong-data/moderate_conversion_manual.md:206)

## Current warehouse state on 2026-08-14

For `2026-07-28`:

- `orders_booked` official Chatbot/JCo bookings = `1`
- `t_moderate_booking_reconstruction` = `1`
- `p_looker_agent_daily_conversion` = `1`

Current reconstruction rows:

- `37636` -> `LATEST PRIOR INQUIRY`, `Chatbot Only`

So `37659` is no longer in the official booking source or the reconstruction outputs.

## Files

- [t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.sql](/home/jerico/Desktop/gulong-data/t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.sql)
- [t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.md](/home/jerico/Desktop/gulong-data/t_moderate_booking_reconstruction_order_37659_trace_2026-07-29.md)
