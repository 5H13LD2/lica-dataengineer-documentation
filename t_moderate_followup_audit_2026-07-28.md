# t_moderate_followup Audit Notes

Date: 2026-07-28

## Scope

Audit of:

- `gulong_reporting.t_moderate_followup_detail`
- `gulong_reporting.t_moderate_followup_coverage`
- `gulong_reporting.t_moderate_booking_reconstruction`
- upstream dependency `gulong_reporting.v_looker_first_reply_detail`

Main question:

- Is the follow-up count unchanged because CS did not follow up, or because the reporting data is stale / misaligned?

## Executive summary

The unchanged follow-up count was caused by stale downstream reporting tables, not by lack of CS follow-up activity.

During the audit:

- raw follow-up source activity existed on `2026-07-27` and `2026-07-28`
- `t_moderate_followup_detail` was still only loaded through `2026-07-25`
- `t_moderate_followup_coverage` was also lagging on follow-up dates
- rebuilding the follow-up pipeline updated the counts

## What was verified

### 1. Raw follow-up activity existed

`v_looker_cs_followup_detail` already had:

- `151` source follow-up messages on `2026-07-27` to `2026-07-28`
- `23` source rows on `2026-07-28`

This proved CS follow-up activity existed in source data.

### 2. Follow-up detail table was stale before rebuild

Before rebuild:

- `t_moderate_followup_detail.max(followup_date) = 2026-07-25`

After rebuild:

- `t_moderate_followup_detail.max(followup_date) = 2026-07-28`
- total detail rows = `334`

### 3. Coverage table was stale before rebuild

Before rebuild:

- `t_moderate_followup_coverage.max(first_followup_date) = 2026-07-25`

After rebuild:

- `t_moderate_followup_coverage.max(first_followup_date) = 2026-07-28`

### 4. July 1 to July 27 result

For `2026-07-01` to `2026-07-27`:

- `212` moderate sessions were `WITH CS FOLLOWUP`
- `388` were `NO CS FOLLOWUP`
- `688` total mature moderate sessions

Event-level count over the same July date range:

- `222` follow-up rows
- `213` distinct followed-up sessions

Note:

- `212` vs `213` is expected because coverage is cohort-based by `moderate_report_date`, while detail is event-based by `followup_date`

## Important logic finding

The current denominator QA query is misleading for this table design.

Why:

- `t_moderate_followup_detail` is replied-only by design
- `t_moderate_followup_coverage` is not replied-only; it includes all moderate sessions with `manychat_id`
- the existing QA block compares replied-only counts from `v_looker_first_reply_detail` against total rows from `t_moderate_followup_coverage`

This creates apparent mismatches on days that contain `No CS Reply` rows.

Examples found:

- `2026-07-19`: coverage had `91` total sessions, but only `41` replied sessions and `50` no-reply sessions
- `2026-07-26`: coverage had `72` total sessions, `69` replied, `3` no-reply
- `2026-07-27`: coverage had `39` total sessions, `38` replied, `1` no-reply

## Booking validation

Validated:

- all `3` follow-up-attributed order IDs found in `t_moderate_followup_detail` existed in `t_moderate_booking_reconstruction`

Remaining issue:

- reconstruction booking ownership was not fully aligned after the follow-up rebuild
- specific mismatch found:
  - order `37598` was `CS Assisted` in follow-up coverage/detail
  - order `37598` was still `Chatbot Only` in `t_moderate_booking_reconstruction`

Interpretation:

- `t_moderate_booking_reconstruction` depends on `t_moderate_followup_detail`
- if follow-up tables are rebuilt but reconstruction is not refreshed cleanly afterward, booking ownership can lag

## Code references

- follow-up detail is replied-only by design:
  - [moderate_followup_deploy.sql](/home/jerico/Desktop/gulong-mobile/moderate_followup_deploy.sql:41)
- coverage base cohort includes all moderates with `manychat_id`:
  - [moderate_followup_deploy.sql](/home/jerico/Desktop/gulong-mobile/moderate_followup_deploy.sql:251)
- current denominator QA compares against replied-only source:
  - [moderate_followup_deploy.sql](/home/jerico/Desktop/gulong-mobile/moderate_followup_deploy.sql:649)
- booking reconstruction reads follow-up booking flags from detail:
  - [moderate_followup_deploy.sql](/home/jerico/Desktop/gulong-mobile/moderate_followup_deploy.sql:538)

## Recommended operating rule

When upstream reply logic changes or source follow-up data advances, rebuild in this order:

1. `v_looker_moderate_followup_detail`
2. `t_moderate_followup_detail`
3. `v_looker_moderate_followup_coverage`
4. `t_moderate_followup_coverage`
5. `v_looker_moderate_booking_reconstruction`
6. `t_moderate_booking_reconstruction`

## Recommendation on QA

Choose one of these and keep it consistent:

### Option A

Define coverage as replied moderates only.

Then change the coverage `moderates` CTE to filter:

- `reply_status = 'Has CS Reply'`

### Option B

Keep coverage as all moderates, but fix QA to compare:

- `v_looker_first_reply_detail replied count`
against
- `SUM(replied_session_count)` and `SUM(followed_up_session_count) + SUM(no_followup_session_count)`

## Files created for this audit

- [t_moderate_followup_audit_2026-07-28.sql](/home/jerico/Desktop/gulong-mobile/t_moderate_followup_audit_2026-07-28.sql)
- [t_moderate_followup_audit_2026-07-28.md](/home/jerico/Desktop/gulong-mobile/t_moderate_followup_audit_2026-07-28.md)
