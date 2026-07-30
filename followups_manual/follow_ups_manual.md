# Follow Ups Manual

Canonical files:
- [moderate_followup_deploy.sql](/home/jerico/Desktop/gulong-data/moderate_followup_deploy.sql)
- [follow_ups_manual.md](/home/jerico/Desktop/gulong-data/follow_ups_manual.md)

## Purpose

This is the current operating guide for the moderate follow-up reporting pipeline.

Use it for:
- source follow-up message counts
- matched moderate follow-up counts
- session-level follow-up coverage
- bookings from matched follow-ups
- order-level booking reconstruction

## Maintain Only These Objects

The pipeline is now maintained from one SQL file:
- `moderate_followup_deploy.sql`

Do not maintain split-out copies of:
- source follow-up view SQL
- booking summary view SQL
- booking detail view SQL
- dated audit rebuild SQL

## What Each Statement Builds

### Statement 0

Builds:
- `gulong_reporting.v_looker_cs_followup_detail`

Grain:
- one row per qualifying follow-up message

Use it for:
- "ilang follow-up messages ang sinend ni agent on followup_date"

Important logic:
- no per-user-per-day dedupe
- phrases like `Hi 😊 Still interested po?` are included

### Statement 1

Builds:
- `gulong_reporting.v_looker_moderate_followup_detail`

Grain:
- `silver_session_id + followup_at`

Use it for:
- matched follow-up events
- follow-up text, type, agent
- bookings attributed to follow-up events

Important logic:
- match on `manychat_id`
- `followup_at >= first_cs_reply_at`
- `followup_date <= moderate_report_date + 7 days`

### Statement 2

Builds:
- `gulong_reporting.t_moderate_followup_detail`

This is the physical table copy of Statement 1.

### Statement 3

Builds:
- `gulong_reporting.v_looker_moderate_followup_coverage`

Grain:
- `silver_session_id`

Use it for:
- moderate denominator
- replied vs no-reply
- followed-up vs not-followed-up
- session-level booked-from-follow-up flags

### Statement 4

Builds:
- `gulong_reporting.t_moderate_followup_coverage`

This is the physical table copy of Statement 3.

### Statement 5

Builds:
- `gulong_reporting.v_looker_moderate_followup_booking_summary`

Use it for:
- agent-day matched follow-up counts
- matched `manychat_id` counts
- matched session counts
- bookings from those matched follow-ups

Key fields:
- `followup_date`
- `followup_agent_name`
- `matched_manychat_ids`
- `matched_sessions`
- `followups_from_moderate`
- `bookings_from_followups`

### Statement 6

Builds:
- `gulong_reporting.v_looker_moderate_followup_booking_detail`

Use it for:
- row-level matched follow-up and booking trace

### Statement 7

Builds:
- `gulong_reporting.v_looker_moderate_booking_reconstruction`

Use it for:
- booking-first reconciliation
- official Chatbot/JCo order tracing

### Statement 8

Builds:
- `gulong_reporting.t_moderate_booking_reconstruction`

This is the physical table copy of Statement 7.

## Which Statement To Run

### Full rebuild

Run in this exact order:

1. `STATEMENT 0`
2. `STATEMENT 1`
3. `STATEMENT 2`
4. `STATEMENT 3`
5. `STATEMENT 4`
6. `STATEMENT 5`
7. `STATEMENT 6`
8. `STATEMENT 7`
9. `STATEMENT 8`

### If only `v_looker_first_reply_detail` changed

Run:

1. `STATEMENT 1`
2. `STATEMENT 2`
3. `STATEMENT 3`
4. `STATEMENT 4`
5. `STATEMENT 5`
6. `STATEMENT 6`
7. `STATEMENT 7`
8. `STATEMENT 8`

### If only follow-up phrase logic or follow-up counting changed

Run the full rebuild starting from `STATEMENT 0`.

### If only coverage is stale

Run:

1. `STATEMENT 3`
2. `STATEMENT 4`

## Which Table To Use

### "Ilang finollow-up ni Sarah noong July 29, 2026?"

Use:
- `v_looker_cs_followup_detail`

Filter:
- `report_date = DATE '2026-07-29'`
- `agent_name = 'sarah gulongph'`

This is source message count.

### "Ilang finollow-up ni Sarah noong July 29, 2026 na nagmatch sa moderate logic via manychat_id?"

Use:
- `v_looker_moderate_followup_booking_summary`

Filter:
- `followup_date = DATE '2026-07-29'`
- `followup_agent_name = 'sarah gulongph'`

Use metrics:
- `SUM(matched_manychat_ids)` only if you keep the current grouped dimensions aligned
- better: filter the row slice you want, then read `matched_manychat_ids`

### "Aling users / orders ang galing sa follow-up?"

Use:
- `v_looker_moderate_followup_booking_detail`

### "How many moderate sessions got follow-up coverage?"

Use:
- `t_moderate_followup_coverage`

Date basis:
- `moderate_report_date`

## Date Meaning

### `report_date` in source follow-up view

Meaning:
- actual day the follow-up message was sent

### `followup_date` in matched follow-up views

Meaning:
- actual day the matched follow-up event was sent

### `moderate_report_date`

Meaning:
- day of the original moderate session cohort

## Current Logic Notes

- Source follow-up counts are message-level, not deduped per user-day.
- Matched moderate follow-ups use `manychat_id` plus time ordering.
- Exact-timestamp rows where `followup_at = first_cs_reply_at` are included.
- A source follow-up message can still fail to match the moderate pipeline if:
- there is no replied moderate for that `manychat_id`
- it falls outside the `moderate_report_date + 7 day` window

## QA

Run the QA block at the end of:
- [moderate_followup_deploy.sql](/home/jerico/Desktop/gulong-data/moderate_followup_deploy.sql)

Most important checks:
- coverage denominator reconciliation
- true follow-up timing check
- sample agent-day follow-up check

## Cleanup Status

Superseded split files were folded into `moderate_followup_deploy.sql`.
