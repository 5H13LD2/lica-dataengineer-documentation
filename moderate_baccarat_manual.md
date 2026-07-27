# Moderate Baccarat View Manual

**Object:** `gulong_reporting.v_looker_moderate_baccarat`  
**Purpose:** Combine moderate session coverage, first follow-up context, and first matched booking into one moderate-level reporting view.

## Grain

One row per `silver_session_id`.

This is a **moderate-session-level** view, not an event-level or order-level view.

That means:
- follow-up fields come from the **first follow-up** attached to the moderate
- booking fields come from the **first matched booking** attached to the moderate

## Source tables

`v_looker_moderate_baccarat` is built from:
- `gulong_reporting.v_looker_moderate_followup_coverage`
- `gulong_reporting.v_looker_moderate_booking_reconstruction`

## Why this view exists

This view is intended for simple Looker tables where the main question is:

- which moderates became bookings
- when the booking happened
- whether the moderate had a follow-up
- what follow-up text was sent
- how many days it took for the moderate to convert

It avoids switching between the session-level coverage table and the order-level booking reconstruction table for basic funnel analysis.

## Fields included

The current view includes:

- `moderate_report_date`
- `moderate_tagged_at`
- `first_cs_reply_at`
- `booking_day`
- `user_name`
- `order_status`
- `contact_number`
- `manychat_id`
- `order_id`
- `days_to_moderate_conversion`
- `followup_date`
- `reply_agent_name`
- `cs_followup_text`
- `isbooked`

## Field behavior

### `moderate_report_date`

The date of the moderate session.

Use this when the reporting question starts from:
- "how many moderates..."
- "which moderates converted..."
- "how long did moderates take to convert..."

### `moderate_tagged_at`

The original moderate tagging timestamp from `v_looker_first_reply_detail`.

Use this when you need the exact time the moderate entered the CS reply workflow.

### `first_cs_reply_at`

The first CS reply timestamp from `v_looker_first_reply_detail`.

Use this when you need to compare:
- moderate tag time vs first CS reply
- first CS reply vs follow-up timing
- first CS reply vs booking conversion timing

### `booking_day`

The date of the first matched booking for that moderate session.

If no booking was matched, this field is `NULL`.

### `order_status`

Comes from `order_status_norm` in the booking reconstruction view.

If no booking was matched, this field is `NULL`.

### `order_id`

The first matched booking order for the moderate session.

If a session has multiple matched bookings, only the first one is shown in this view.

### `days_to_moderate_conversion`

This is the same booking lag logic from booking reconstruction:

`DATE_DIFF(booking_day, moderate_report_date, DAY)`

If no booking exists, this field is `NULL`.

### `followup_date`

Comes from the first follow-up attached to the moderate session in `v_looker_moderate_followup_coverage`.

If the moderate never had a follow-up, this field is `NULL`.

### `cs_followup_text`

The text of the first follow-up message associated with the moderate.

If no follow-up exists, this field is `NULL`.

### `isbooked`

Custom convenience field:
- if booked: shows the `order_id`
- if not booked: shows `No`

This is useful for quick table display, but for strict booking metrics, use `order_id`.

## Recommended usage

Use `v_looker_moderate_baccarat` when the business question is:

- "show me the moderates and whether they became bookings"
- "show me the booking date beside the moderate date"
- "show me the follow-up text beside the conversion result"
- "show me the days from moderate to booking in one table"

## Recommended metrics

For booking counts:

- `COUNT_DISTINCT(order_id)`

For average moderate-to-booking lag:

- `AVG(days_to_moderate_conversion)`

For booked vs not booked table logic:

- `order_id IS NOT NULL`

## Recommended date usage

Use `moderate_report_date` when the KPI is moderate-based:
- moderate conversion
- moderate-to-booking lag
- moderate funnel analysis

Use `booking_day` only when the KPI is booking-date-based:
- bookings that happened on a given day
- booking-month reporting

## Important limitation

This view is intentionally simplified to one row per moderate session.

Because of that:
- it does **not** preserve multiple follow-ups as separate rows
- it does **not** preserve multiple bookings as separate rows
- it only keeps the first follow-up and first matched booking for display

If the question is about:
- all follow-up events
- all official bookings
- exact order-level reconciliation

use these source views instead:
- `gulong_reporting.v_looker_moderate_followup_detail`
- `gulong_reporting.v_looker_moderate_booking_reconstruction`

## Build file

Local SQL definition:
- [moderate_baccarat_view.sql](/home/jerico/Desktop/gulong-mobile/moderate_baccarat_view.sql)
