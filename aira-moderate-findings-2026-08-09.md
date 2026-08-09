# Aira Moderate Assignment Findings

Date verified: `2026-08-09`
Scope: `gulong_reporting.v_looker_first_reply_detail` and `gulong_core.inquiry_assignments`

## Summary

As of `2026-08-09`, the moderate first-reply view shows:

- `62` total moderate sessions
- `14` sessions with a first CS reply
- `48` sessions with no CS reply
- `22.58%` response rate (`14 / 62`)

All `62` moderate sessions are currently attributed in the view to:

- `reporting_agent_name = Jeanel Co`
- `source_agent_name = Chatbot/JCo`

For actual first replier on the same date:

- `Aira L. Garcia` replied first on `14` moderate sessions

For assignment data on the same date:

- `24` sessions were assigned to `Aira L. Garcia` in `gulong_core.inquiry_assignments`

But under the current moderate-session matching logic:

- `0` of the `62` moderate sessions are matched as assigned to `Aira`
- `0` of Aira's `24` assigned sessions matched the moderate view rows for the same day

## Main Finding

The current view logic does not treat Aira as the assignment owner of the moderate sessions on `2026-08-09`.

Instead:

- the moderate sessions are bucketed under `Jeanel Co / Chatbot/JCo`
- Aira appears only as the actual `reply_agent_name` on replied sessions

This means:

- `Aira assigned workload` and `Aira actual replies` are being measured from two different workflows
- the `24` sessions assigned to Aira that day are not the same sessions represented by the `62` moderate rows in the current view output

## Query Limitation

The current query logic is not capturing the actual reassignment or handoff to Aira.

What the query captures today:

- the original chatbot-side moderate ownership bucket
- the normalized assignment bucket of `Jeanel Co / Chatbot/JCo`
- the actual first replier through `reply_agent_name`

What it does not capture:

- the operational reassignment step where a moderate may have been passed to Aira after initial chatbot ownership
- any post-tagging transfer workflow that changes who is actually responsible to reply
- any handoff mechanism that exists outside the current `v_looker_first_reply_detail` matching path

Because of that limitation, the current output can show this pattern:

- moderate is attributed to `Jeanel Co / Chatbot/JCo`
- actual reply is sent by `Aira L. Garcia`
- but the query still reports `0` assigned moderates for Aira

This should be interpreted as a visibility gap in the reporting logic, not automatically as proof that no moderate workload was handed to Aira.

## Evidence

### 1. Moderate view totals for `2026-08-09`

- `total_moderates = 62`
- `replied = 14`
- `no_reply = 48`
- `reporting_agent_name = Jeanel Co`
- `source_agent_name = Chatbot/JCo`

### 2. First replies in moderate view

- `reply_agent_name = Aira L. Garcia`
- `replied_sessions = 14`

### 3. Aira assignments in assignment table

- `assigned_agent_name = Aira L. Garcia`
- `agent_reporting_name = Aira L. Garcia`
- `agent_reporting_group = cs_agent`
- `distinct_sessions = 24`

### 4. Overlap checks

- Aira assigned sessions found in moderate view by session match: `0`
- Aira assigned sessions found in `moderate_intent_sessions` by session match: `0`
- Aira assigned users with any validated moderate on the same date: `0`
- Moderate sessions replied by Aira that were also assigned to Aira by session match: `0`
- Moderate sessions replied by Aira but not assigned to Aira by session match: `14`

## Interpretation

The most likely interpretation is:

- moderate sessions are being sourced into the view from the chatbot assignment path
- that path is normalized to `Jeanel Co / Chatbot/JCo`
- Aira is acting as the responder for some of those sessions, but not as the assignment owner in the view's current join path

There is also a strong sign that Aira's `24` assignments belong to a separate workload, because:

- only `3` of the `24` assignment rows had a raw `silver_session_id`
- `21` used fallback IDs of the form `assignment:<user_id>:<date>`
- none matched validated moderate sessions on `2026-08-09`

Another plausible explanation is that the real handoff to Aira happens after the point where the current query fixes moderate ownership. If that is true, then the view is preserving the original chatbot assignment context while missing the downstream reassignment context.

## Execution Log

The following checks were executed in BigQuery:

1. Counted moderate sessions and reply coverage from `gulong_reporting.v_looker_first_reply_detail` for `DATE '2026-08-09'`.
2. Counted actual first replies by `reply_agent_name`.
3. Checked assignment-side fields exposed by the view: `reporting_agent_name` and `source_agent_name`.
4. Queried `gulong_core.inquiry_assignments` for rows assigned to `Aira L. Garcia` on `2026-08-09`.
5. Matched Aira assignments against moderate view rows using:
   - `manychat_id`
   - `silver_session_id` or fallback assignment session ID
6. Matched Aira assignments against `gulong_core.moderate_intent_sessions`.
7. Checked whether any users assigned to Aira had validated moderates on the same date.
8. Checked whether moderate sessions replied by Aira were also assigned to Aira.

## Recommended Next Check

To answer "which sessions should Aira have replied to" in business terms, the next step is to trace how moderate handoff is supposed to happen operationally:

- whether the true handoff source is `inquiry_assignments`
- whether there is another queue or reassignment table after chatbot tagging
- whether Aira receives moderates through a manual or post-assignment transfer not represented in this view
- whether agent ownership changes in message logs, CRM events, or another operational table after the original assignment row is written

## Suggested Reporting Note

If this is presented to stakeholders, the safest wording is:

"The current moderate first-reply query captures the original chatbot assignment bucket and the actual first responder, but it does not yet capture the actual reassignment/handoff step to the responding CS agent. Because of that, Aira's real moderate workload may be under-attributed in the current report."
