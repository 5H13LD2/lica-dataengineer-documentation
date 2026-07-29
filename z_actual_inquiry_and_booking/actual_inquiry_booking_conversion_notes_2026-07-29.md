# Actual Inquiry Funnel Notes

## Readout Headline

The headline is not that Taira beats human CS.

The main story is that qualified demand is being built on both channels, then dropped at the same leak:
- contact capture

The most important insight:
- contact capture is stuck around `5%` to `6%` regardless of how ready the customer already is

Implication:
- the biggest recoverable conversion is a product-controlled fix at the contact step
- contact should not be asked as a cold field
- contact capture should be gated behind a value exchange such as:
  - reserve stock
  - confirm branch availability
  - send the quote

This should be treated as the first action, not the third.

## Strategic Interpretation

Taira's advantage is real, but it is a stage-depth story, not an intent story.

What that means:
- Moderate/High intent rates are broadly similar across channels
- the difference comes later in the funnel
- Taira does more of the selling motion inside each conversation
- Taira reaches quotation, IP stage, and scheduling more often
- the booking lift is therefore more consistent with deeper funnel progression than better lead classification

Caveat:
- qualified handoffs may already be higher-quality leads
- this supports giving Taira more volume directionally
- it does not yet prove clean causal uplift by setup alone

## SLA Interpretation

Queue depth is the real SLA lever.

Sarah's apparent improvement should not be read as a clean operational win:
- average response improved
- median response worsened
- `30-minute` coverage fell

Interpretation:
- the average moved because some extreme long tails improved
- the typical customer experience got worse

Operating control:
- do not frame this as simply "respond faster"
- cap concurrent open cases
- load-balance the handoff queue
- monitor response performance against active queue depth, not averages alone

## Additional Flags

Two smaller but important watchouts:

- Human CS conversion appears to be falling uniformly across all four agents.
- Treat that as a possible systemic signal on the next refresh, not an individual agent-performance issue.

- Demand skews Budget and promo engagement is dominated by `Check Price`.
- Michelin leads promo-brand interest.
- That supports Michelin-focused H2 targeting.

## Recommended Readout Line

If one line is needed for leadership:

- the funnel qualifies well and closes poorly at contact; fix the contact step as a value exchange, cap the handoff queue, and give Taira more of the volume it is already converting

## What the new views do

File:
- `create_actual_inquiry_booking_conversion_live_views.sql`

Views created:
- `gulong_reporting.v_actual_inquiry_booking_conversion_detail`
- `gulong_reporting.v_actual_inquiry_booking_conversion_daily`
- `gulong_reporting.v_actual_inquiry_booking_conversion_monthly`

Business logic:
- denominator = deduplicated original inquiry ownership from `gulong_core.inquiry_assignments`
- moderate flag = validated rows from `gulong_core.moderate_intent_sessions`
- booking numerator = reportable FB/Chatbot bookings from `gulong_core.orders_all`
- booking attribution = booking rows linked back to the original inquiry key

## Workbook alignment

Source workbook checked:
- `gulong_july_booking_conversion_audit_2026-07-29.xlsx`

Key workbook tabs used:
- `Lane_Summary`
- `Denominator_Recon`
- `Inquiry_Cohorts`
- `SQL_Log`

The workbook logic clearly favors:
- original inquiry owner
- inquiry-date cohorting
- deduped `inquiry_assignments` as the actual inquiry denominator

Exact booking reproduction path for the inquiry-date conversion numerator:
- use `Bookings_All`
- filter `is_reportable_booked_order = TRUE`
- filter `is_call_order = FALSE`
- filter `inquiry_in_july_scope = TRUE`
- filter `in_scope_original_owner = TRUE`
- use `original_owner_lane` for:
  - `Rem Reyes`
  - `Aira L. Garcia`
  - `Rolyn Ang`
  - `Sarah`
  - `Taira (Chatbot/JCo)`

This reproduces the `Lane_Summary` inquiry-date conversion bookings:
- `111` total bookings

For the live warehouse view:
- the exact workbook flags are not persisted in `gulong_core.orders_all`
- the SQL therefore uses the closest warehouse-equivalent booking universe:
  - `is_reportable_booked_order = TRUE`
  - non-call behavior approximated by `sales_channel IN ('fb', 'chatbot')`
  - original-owner scope approximated from `original_assigned_is_chatbot_jeanel` and original-owner name fields
- that live warehouse-equivalent filter set also returns `111` July bookings

## Important caveat

The workbook is a frozen audit snapshot with extraction timestamp:
- `2026-07-29 12:07:58 Asia/Manila`

The new views are live views.

That means live monthly totals can still differ slightly from the frozen workbook because:
- upstream data may have loaded additional rows after the workbook extraction
- live views are not cut off at the workbook snapshot timestamp
- the PDF was not machine-readable in this environment, so the workbook was used as the primary logic source

## Current live July check

Live reconstruction for `report_month = 2026-07-01` currently returns:

- `Taira (Chatbot/JCo)` = `3706` inquiries, `404` moderates, `32` bookings, `31` converted inquiries
- `Sarah` = `1953` inquiries, `195` moderates, `18` bookings, `16` converted inquiries
- `Aira L. Garcia` = `2577` inquiries, `175` moderates, `26` bookings, `25` converted inquiries
- `Rolyn Ang` = `1662` inquiries, `188` moderates, `13` bookings, `13` converted inquiries
- `Rem Reyes` = `2574` inquiries, `209` moderates, `22` bookings, `22` converted inquiries

Workbook snapshot values were slightly lower on some lanes, which is consistent with a frozen partial-day extraction.

## Recommended Looker usage

Use:
- `v_actual_inquiry_booking_conversion_daily` for day-level funnel cards/charts
- `v_actual_inquiry_booking_conversion_monthly` for month-level funnel cards/charts
- `v_actual_inquiry_booking_conversion_detail` for drill-down tables and validation

Filter primarily on:
- `report_date` for daily inquiry cohort reporting
- `report_month` for monthly inquiry cohort reporting
