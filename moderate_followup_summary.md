# Moderate-Intent Follow-Up Reporting — Build Summary

**Project:** `gulong-chatbot-459723` · **Dataset:** `gulong_reporting`  
**Updated:** July 23, 2026

## Reporting model

The reporting layer now has two clear grains:

1. `t_moderate_followup_detail`
One row per **true follow-up event** matched to a replied moderate session.
Use this for:
- follow-up volume
- follow-up timing
- follow-up type / text analysis
- bookings attributed to follow-ups

2. `t_moderate_followup_coverage`
One row per **moderate session** from `v_looker_first_reply_detail`.
Use this for:
- moderate denominator
- `WITH CS FOLLOWUP` vs `NO CS FOLLOWUP`
- follow-up coverage
- total chatbot-cohort booking session counts
- chatbot-only booking session counts
- booked-from-follow-up / CS-assisted session counts

This split is intentional. The event table answers "which follow-ups happened". The session table answers "which moderates were or were not followed up".

## Build dependency

`t_moderate_followup_coverage` is downstream of:
- `v_looker_first_reply_detail`
- `t_moderate_followup_detail`

That means if `v_looker_first_reply_detail` changes, the coverage outputs can become stale even if the SQL logic itself is correct.

Example seen on **July 22, 2026**:
- `v_looker_first_reply_detail` showed `17` replied moderates
- `t_moderate_followup_coverage` still showed `16`

That mismatch means the coverage table needs to be rebuilt. It is not a Looker issue and does not automatically mean the coverage logic is wrong.

Minimum rebuild after upstream first-reply changes:
1. rerun `STATEMENT 3`
2. rerun `STATEMENT 4`

Safest rebuild after any logic change in this reporting layer:
1. rerun `STATEMENT 1`
2. rerun `STATEMENT 2`
3. rerun `STATEMENT 3`
4. rerun `STATEMENT 4`

## Logic changes

### 1. Base cohort is now the full moderate session list

The source of truth for the denominator is:
`gulong_reporting.v_looker_first_reply_detail`

Filter used:
- `manychat_id IS NOT NULL`

That means the coverage table starts from all moderate sessions with a usable `manychat_id`, then splits them into:
- `replied_session_count`
- `no_reply_session_count`
- `chatbot_total_booked_session_count`
- `chatbot_only_booked_session_count`
- `cs_assisted_booked_session_count`
- `followed_up_session_count`
- `no_followup_session_count`
- `booked_session_count`

This allows the coverage table to match total moderates from `v_looker_first_reply_detail` while still preserving the replied-moderate follow-up funnel.

### 2. First CS reply is no longer counted as a follow-up

The old issue came from allowing:
`followup_at >= first_cs_reply_at`

The new event-level match uses:
`followup_at > first_cs_reply_at`

So `t_moderate_followup_detail` contains only **true follow-ups**. There are no first-reply contamination rows and no need to filter out `0-minute` rows in that table.

### 3. Moderate-to-follow-up attribution stays session-oriented

Follow-ups are still found by:
- same `manychat_id`
- after the session's `first_cs_reply_at`
- within `7 days` of the moderate `report_date`

If a user has multiple replied moderate sessions, each follow-up is assigned to the **most recent prior replied moderate** for that `manychat_id`.

This is the best available compromise with the current source tables. It is stronger than raw user-level counting, but it still depends on time-based attribution where users have repeated moderates close together.

### 4. Reply and follow-up status now both exist explicitly

The session table adds:
- `reply_status`
- `replied_session_count`
- `no_reply_session_count`
- `cs_followup_status = 'WITH CS FOLLOWUP' / 'NO CS FOLLOWUP'`
- `followed_up_session_count`
- `no_followup_session_count`

This is the field set to use when the business question is:
"Of all moderate sessions, how many were replied, how many were not replied, and among replied sessions, how many were followed up or missed?"

### 5. Booking logic is now split into chatbot-total vs chatbot-only vs CS-assisted

There are now two booking layers in the session table:

1. **Chatbot total booking**
- booking is joined directly to the moderate session's `manychat_id`
- booking must happen on or after `first_customer_message_at`
- no CS follow-up is required

2. **CS-assisted booking**
- still based on true follow-up attribution
- for each true follow-up event:
- booking must happen `>= followup_at`
- booking day must be within `14 days` of `followup_date`
- earliest qualifying booking is attributed to that event

That means the coverage table can now report:
- total booked sessions in the chatbot cohort
- booked sessions that stayed chatbot-only
- booked sessions that had CS follow-up assistance

For Looker booking counts on the coverage table:
- use `SUM(chatbot_total_booked_session_count)` for **total chatbot bookings**
- use `SUM(chatbot_only_booked_session_count)` for **chatbot-only bookings**
- use `SUM(cs_assisted_booked_session_count)` for **CS-assisted bookings**

For event-level booking counts:
- use `COUNT_DISTINCT(attributed_order_id)` on the detail table
- use `SUM(booked_session_count)` on the coverage table only for the existing CS-assisted session metric

## Objects created

| Object | Grain | Primary use |
|---|---|---|
| `v_looker_moderate_followup_detail` | `silver_session_id + followup_at` | True follow-up event logic |
| `t_moderate_followup_detail` | same | Looker event-level source |
| `v_looker_moderate_followup_coverage` | `silver_session_id` | Session status / coverage logic |
| `t_moderate_followup_coverage` | same | Looker session-level source |

Run order remains:
1. Statement 1
2. Statement 2
3. Statement 3
4. Statement 4

## Looker Studio usage

### Use `t_moderate_followup_detail` for follow-up event reporting

Recommended metrics:
- `SUM(followed_up_moderate_count)` as `Follow-ups`
- `COUNT_DISTINCT(attributed_order_id)` as `Bookings`

Recommended dimensions:
- `followup_date`
- `followup_agent_name`
- `user_name`
- `followup_type`
- `followup_text`
- `is_booked`

Recommended calculated field:

```text
Booking Conversion Rate =
COUNT_DISTINCT(attributed_order_id) / SUM(followed_up_moderate_count)
```

Date range dimension:
- `followup_date`

### Use `t_moderate_followup_coverage` for moderate coverage reporting

Recommended metrics:
- `SUM(moderate_session_count)` as `Moderates`
- `SUM(replied_session_count)` as `Replies`
- `SUM(no_reply_session_count)` as `No Reply`
- `SUM(chatbot_total_booked_session_count)` as `Total Chatbot Bookings`
- `SUM(chatbot_only_booked_session_count)` as `Chatbot-Only Bookings`
- `SUM(cs_assisted_booked_session_count)` as `CS-Assisted Bookings`
- `SUM(followed_up_session_count)` as `With CS Follow-up`
- `SUM(no_followup_session_count)` as `No CS Follow-up`
- `SUM(booked_session_count)` as `Booked from Follow-up`

Recommended dimensions:
- `moderate_report_date`
- `reply_agent_name`
- `booking_owner_bucket`
- `booking_ownership_status`
- `cs_followup_status`
- `booked_in_chatbot_cohort`
- `booked_from_followup`
- `first_followup_agent_name`

Recommended calculated fields:

```text
Follow-up Coverage =
SUM(followed_up_session_count) / SUM(replied_session_count)
```

```text
Reply Rate =
SUM(replied_session_count) / SUM(moderate_session_count)
```

```text
No Reply Rate =
SUM(no_reply_session_count) / SUM(moderate_session_count)
```

```text
No Follow-up Rate =
SUM(no_followup_session_count) / SUM(replied_session_count)
```

```text
Booking Conversion from Follow-ups =
SUM(booked_session_count) / SUM(followed_up_session_count)
```

```text
Chatbot Booking Rate =
SUM(chatbot_total_booked_session_count) / SUM(moderate_session_count)
```

Date range dimension:
- `moderate_report_date`

Recommended filter for stable coverage reporting:
- `is_mature_cohort = 1`

## Practical guidance

- If the question starts with "how many moderates..." or "how many replies...", use `t_moderate_followup_coverage`.
- If the question starts with "which follow-ups..." or "which agent/text converted...", use `t_moderate_followup_detail`.
- Do not use `Record Count` for KPI reporting.
- On the detail table, booking counts should use `COUNT_DISTINCT(attributed_order_id)`.
- On the coverage table, denominator and missed-follow-up reporting should use the prebuilt session count fields.
- `booked_session_count` is still the current **CS-assisted** logic.
- For the new business split:
  - `chatbot_total_booked_session_count` = all booked sessions in the chatbot cohort
  - `chatbot_only_booked_session_count` = booked sessions with no CS-assisted attribution
  - `cs_assisted_booked_session_count` = booked sessions with follow-up attribution
- After any upstream change to `v_looker_first_reply_detail`, run the denominator QA before trusting the coverage table.

## Remaining tradeoff

Attribution still relies on `manychat_id` plus time ordering when a single user has multiple moderate sessions close together. That is acceptable for reporting, but if the business later needs perfect session-to-follow-up attribution, the upstream follow-up source will need a direct session key.
