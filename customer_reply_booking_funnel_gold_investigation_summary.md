# Customer Reply Booking Funnel Gold Investigation Summary

## Context

This document summarizes the investigation into why `gulong_reporting.customer_reply_booking_funnel_gold` does not match the Moderate counts shown in `gulong_reporting.p_looker_agent_daily_conversion` for the `Chatbot/JCo` reporting bucket.

Reference dates validated during the investigation:

- `2026-07-14`
- `2026-07-15`

Source-of-truth values from `p_looker_agent_daily_conversion`:

- `2026-07-14`: `21`
- `2026-07-15`: `16`

## Executive Summary

The primary mismatch is caused by different business definitions, not by a simple filter issue.

- `customer_reply_booking_funnel_gold` models the final inquiry state.
- `p_looker_agent_daily_conversion` models a corrected `Chatbot/JCo` reporting cohort.

As a result, this comparison is not expected to match under current production logic:

```text
customer_reply_booking_funnel_gold
assigned_agent_name = 'sarah gulongph'
AND intent_clean = 'Moderate Intent'

vs

p_looker_agent_daily_conversion
agent_name = 'Chatbot/JCo'
total_moderate_intents
```

Any future reconciliation must preserve the same business grain, date basis, and ownership logic as `p_looker_agent_daily_conversion`, or it will introduce additional count variance.

## Current Gold Logic

The current `customer_reply_booking_funnel_gold` build is a straightforward projection of session, response, and booking state.

High-level flow:

```text
gulong_core.fb_inquiry_sessions
  -> sessions CTE
manychat_data.messages
  -> response_times CTE
gulong_core.orders_booked
  -> bookings CTE
sessions + response_times + bookings
  -> joined
joined
  -> gulong_reporting.customer_reply_booking_funnel_gold
```

Core field lineage:

- `report_date`
  - from `fb_inquiry_sessions.inquiry_day`
- `assigned_agent_name`
  - from `fb_inquiry_sessions.current_assigned_agent_name`
- `intent`
  - from `fb_inquiry_sessions.chat_analysis_top_intent`
- `intent_clean`
  - `COALESCE(intent, 'Unclassified Intent')`
- `date_became_moderate`
  - `DATE(first_moderate_at)`
- `date_became_moderate_display`
  - display formatting of `first_moderate_at`

Important property of Gold:

- It reflects final/current owner semantics.
- It does not carry any first-class `Chatbot/JCo` reporting cohort flag.
- It does not apply the same ownership correction logic used in `p_looker_agent_daily_conversion`.

## p_looker_agent_daily_conversion Logic

High-level lineage:

```text
hot_inquiry_sessions
  + hot_moderate_intent_sessions
  + hot_inquiry_assignments
  + hot_corrected_chatbot_moderates
  -> stg_p_looker_agent_daily_conversion
  -> p_looker_agent_daily_conversion
```

For `Chatbot/JCo`, the Moderate metric is not based on final owner alone. It uses a reporting cohort built from:

- chatbot-origin ownership
- ownership mapping
- chatbot-specific correction logic
- staged reporting aggregation

Important property of `p_looker`:

- It is a reporting-cohort metric, not a plain final-owner metric.

## Root Cause

The mismatch is introduced by business-definition drift between the two datasets.

`customer_reply_booking_funnel_gold` uses:

- current assigned owner
- session-level intent
- current persisted moderate state

`p_looker_agent_daily_conversion` uses:

- a corrected `Chatbot/JCo` cohort
- reporting ownership logic
- chatbot-specific attribution rules before final aggregation

Therefore:

- `assigned_agent_name = 'sarah gulongph'` in Gold is not equivalent to `agent_name = 'Chatbot/JCo'` in `p_looker`
- `intent_clean = 'Moderate Intent'` in Gold is not guaranteed to represent the same reporting cohort as `total_moderate_intents` in `p_looker`

## What Was Ruled Out

The investigation did not find evidence that the mismatch is primarily caused by:

- missing report-date partitions
- booking logic
- reply timestamp logic
- SLA calculations alone

Duplicates can exist in the data, but they were not sufficient on their own to explain the gap between Gold and `p_looker`.

## Engineering Interpretation

The baseline mismatch is expected under the current data model.

That said, any reconciliation SQL can still introduce new errors if it does not preserve:

- session grain
- date basis
- ownership basis

Examples of risky reconciliation mistakes:

- joining on `user_id + date` instead of `silver_session_id`
- mixing `inquiry_day` and `first_moderate_day`
- validating with `assigned_agent_name = 'sarah gulongph' AND intent_clean = 'Moderate Intent'` instead of validating against a dedicated reporting-cohort flag

## Recommended Direction

Do not rewrite the entire Gold table.

Preferred approach:

1. Keep existing reply logic unchanged.
2. Keep booking logic unchanged.
3. Keep non-moderate behavior unchanged.
4. Introduce a dedicated reconciliation layer for the `Chatbot/JCo` moderate reporting cohort.
5. Reuse the same ownership and corrected-chatbot rules used by `p_looker_agent_daily_conversion`.

## Schema Guidance

Safest option:

- preserve the existing downstream-facing schema whenever possible

If reconciliation can be achieved through:

- an internal staging CTE
- a validation view
- a small helper snapshot table

that is preferable to changing the semantics of existing production fields.

Fields that should not be changed casually:

- `assigned_agent_name`
- `intent_clean`
- `date_became_moderate`

Those fields are already likely consumed by downstream reporting.

## Practical Recommendation

The best production-safe pattern is:

1. Build a `Chatbot/JCo` reconciliation cohort upstream.
2. Validate that cohort against `p_looker_agent_daily_conversion`.
3. Only after validation, decide whether:
   - Gold should expose helper reporting fields, or
   - downstream dashboards should read the reconciled cohort through a sibling view/table.

If exact parity with `p_looker` is required historically, the cleanest long-term solution is to persist the chatbot reporting cohort at load time as a snapshot table, then reuse that snapshot in Gold.

## Final Conclusion

The discrepancy between `customer_reply_booking_funnel_gold` and `p_looker_agent_daily_conversion` is expected under current logic because the datasets represent different reporting concepts.

- Gold represents final inquiry state.
- `p_looker` represents a corrected chatbot reporting cohort.

To align them, Gold needs an additional `Chatbot/JCo` cohort-identification layer, or an equivalent ownership-mapping transformation, implemented in a way that does not disturb existing booking, reply, SLA, or non-moderate behavior.
