# Follow Ups Manual

Reference files:
- [moderate_followup_deploy.sql](/home/jerico/Desktop/gulong-mobile/moderate_followup_deploy.sql)
- [moderate_followup_summary.md](/home/jerico/Desktop/gulong-mobile/moderate_followup_summary.md)

## Purpose

This manual documents the current moderate follow-up reporting setup used for:
- no. of moderates
- no. of replies
- no. of follow-ups
- no. of bookings from follow-ups
- booking conversion from follow-ups
- `WITH CS FOLLOWUP` vs `NO CS FOLLOWUP`

## Source of truth

### 1. Replied moderate denominator

Base source:
`gulong_reporting.v_looker_first_reply_detail`

Coverage base filter:
- `reply_status = 'Has CS Reply'`
- `manychat_id IS NOT NULL`

This is the denominator used for session-level moderate follow-up reporting.

### 2. True follow-up events

Event source:
`gulong_reporting.t_moderate_followup_detail`

This table contains only true follow-ups.

Key rule:
- `followup_at > first_cs_reply_at`

So the first CS reply is not counted as a follow-up.

### 3. Session-level coverage

Coverage source:
`gulong_reporting.t_moderate_followup_coverage`

This table answers:
- which replied moderates got followed up
- which replied moderates did not get followed up
- which followed-up moderates later booked

## Grain

### `t_moderate_followup_detail`

Grain:
- `silver_session_id + followup_at`

Use this for:
- actual follow-up activity date
- follow-up agent
- follow-up text
- follow-up type
- booking attribution by follow-up event

### `t_moderate_followup_coverage`

Grain:
- `silver_session_id`

Use this for:
- moderate denominator
- `WITH CS FOLLOWUP`
- `NO CS FOLLOWUP`
- booked from follow-up

## KPI definitions

### No. of Moderates

Source:
- `t_moderate_followup_coverage`

Metric:
- `SUM(moderate_session_count)`

Date range dimension:
- `moderate_report_date`

### No. of Reply

Current note:
The coverage table already starts from replied moderates only.

So right now:
- `No. of Reply = SUM(moderate_session_count)`

If later you need all moderates including no-reply sessions, that requires a different base table.

### No. of Follow-ups

Session-level funnel version:
- source: `t_moderate_followup_coverage`
- metric: `SUM(followed_up_session_count)`
- date range dimension: `moderate_report_date`

Event-level activity version:
- source: `t_moderate_followup_detail`
- metric: `SUM(followed_up_moderate_count)`
- date range dimension: `followup_date`

### No. of Bookings from Follow-ups

Session-level funnel version:
- source: `t_moderate_followup_coverage`
- metric: `SUM(booked_session_count)`

Event-level version:
- source: `t_moderate_followup_detail`
- metric: `COUNT_DISTINCT(attributed_order_id)`

### Booking Conversion from Follow-ups

Session-level funnel version:

```text
SUM(booked_session_count) / SUM(followed_up_session_count)
```

Event-level version:

```text
COUNT_DISTINCT(attributed_order_id) / SUM(followed_up_moderate_count)
```

## Date logic

There are two valid date perspectives.

### 1. `moderate_report_date`

Use for funnel/cohort reporting:
- no. of moderates
- no. of followed-up moderates
- no. of no-follow-up moderates
- no. of bookings from follow-ups

Meaning:
The follow-up is counted under the date of the original moderate session.

### 2. `followup_date`

Use for operational follow-up activity:
- how many follow-ups were sent that day
- which agent sent them
- which follow-ups converted

Meaning:
The follow-up is counted under the actual day it was sent.

## Recommended Looker setup

### Scorecards for funnel page

Data source:
- the Looker source connected to `t_moderate_followup_coverage`

Metrics:
- `No. of Moderates` = `SUM(moderate_session_count)`
- `No. of Reply` = `SUM(moderate_session_count)`
- `No. of Follow-ups` = `SUM(followed_up_session_count)`
- `No. of Bookings from Follow-ups` = `SUM(booked_session_count)`

Date range dimension:
- `moderate_report_date`

### Detail table for actual follow-ups

Data source:
- the Looker source connected to `t_moderate_followup_detail`

Dimensions:
- `followup_date`
- `followup_agent_name`
- `user_name`
- `followup_type`
- `followup_text`
- `is_booked`

Metrics:
- `SUM(followed_up_moderate_count)`
- `COUNT_DISTINCT(attributed_order_id)`

Date range dimension:
- `followup_date`

### Session table for moderate follow-up status

Data source:
- the Looker source connected to `t_moderate_followup_coverage`

Dimensions:
- `moderate_report_date`
- `user_name`
- `reply_agent_name`
- `cs_followup_status`
- `booked_from_followup`
- `first_followup_agent_name`

Metrics:
- `SUM(moderate_session_count)`
- `SUM(followed_up_session_count)`
- `SUM(no_followup_session_count)`
- `SUM(booked_session_count)`

Date range dimension:
- `moderate_report_date`

## Dropdown control

### For funnel/session page

Data source:
- coverage source

Control field:
- `first_followup_agent_name`

Metric:
- `followed_up_session_count`

Aggregation:
- `Sum`

Date range dimension:
- `moderate_report_date`

### For follow-up activity page

Data source:
- detail source

Control field:
- `followup_agent_name`

Metric:
- `followed_up_moderate_count`

Aggregation:
- `Sum`

Date range dimension:
- `followup_date`

## Important QA lesson

The session-level coverage table can become stale if `v_looker_first_reply_detail` changes and `t_moderate_followup_coverage` is not rebuilt.

Actual case found on July 23, 2026:
- `v_looker_first_reply_detail` for July 22, 2026 showed `17` replied moderates
- `t_moderate_followup_coverage` still showed `16`

Missing row identified:
- `silver_session_id = assignment:26091421717130765:2026-07-22`
- `user_name = Tramjay Ocsalev Tejada`

Meaning:
- the source view was updated
- the coverage table was stale

This is not a Looker issue.

## Rebuild rule

If `v_looker_first_reply_detail` changes:
- rerun `STATEMENT 3`
- rerun `STATEMENT 4`

Safest full rebuild:
1. `STATEMENT 1`
2. `STATEMENT 2`
3. `STATEMENT 3`
4. `STATEMENT 4`

## QA checks

Use the SQL file QA section in:
- [moderate_followup_deploy.sql](/home/jerico/Desktop/gulong-mobile/moderate_followup_deploy.sql)

Most important check:
- denominator reconciliation between `v_looker_first_reply_detail` and `t_moderate_followup_coverage`

Expected:
- `moderates_first_reply = moderates_coverage`
- `moderates_first_reply = with_followup + no_followup`

If not:
- rebuild `STATEMENT 3` and `STATEMENT 4`
