# Actual Inquiry Booking Conversion Architecture

## Purpose

This note documents how the actual inquiry booking conversion reporting layer was engineered on `2026-07-29`, what business logic it implements, and which local SQL files are part of the stack.

Main goal:
- create a stable source of truth for inquiry-date conversion reporting
- align the denominator and booking attribution to the workbook audit logic
- expose a reporting-safe layer for Looker Studio

---

## Business Definition

This reporting layer answers:
- how many actual inquiries each lane owned
- how many of those inquiries converted to traceable bookings
- what the conversion rate is
- how much booking revenue those converted inquiries produced

Core business grain:
- inquiry-date cohort
- original inquiry owner

This is not:
- booking-date reporting
- booking-creator reporting
- final-owner reporting

---

## Source Logic

### Denominator

Actual inquiries come from:
- `gulong_core.inquiry_assignments`

Logic:
- `business_unit = 'gulong'`
- use deduplicated inquiry rows
- group the inquiry into one of these reporting lanes:
  - `Taira (Chatbot/JCo)`
  - `Rem Reyes`
  - `Aira L. Garcia`
  - `Rolyn Ang`
  - `Sarah`

Deduplication key:
- `silver_session_id`
- fallback to assignment event id
- fallback to `user_id + assignment_at`

### Moderate flag

Moderate intent comes from:
- `gulong_core.moderate_intent_sessions`

Logic:
- keep only `validated_moderate = TRUE`
- join back by `silver_session_id`

This is used for funnel depth analysis, but not required for the basic inquiry-to-booking KPI table.

### Booking attribution

Bookings come from:
- `gulong_core.orders_all`

Reporting booking universe:
- `is_reportable_booked_order = TRUE`
- `sales_channel IN ('fb', 'chatbot')`
- must be attributable back to the original inquiry-owner universe

Workbook-equivalent interpretation:
- this was engineered to reproduce the inquiry-date conversion booking universe behind `Bookings_All`
- target result is `111` total July bookings across the five lanes

Attribution key:
- `inquiry_silver_session_id`
- fallback to assignment event id
- fallback to `manychat_user_id + inquiry_assignment_at`

---

## Data Model

The stack is intentionally split into three layers.

### 1. Draft logic layer

Purpose:
- hold the first-pass reporting SQL
- make the transformation readable before materializing

Local file:
- [create_actual_inquiry_booking_conversion_live_views.sql](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/create_actual_inquiry_booking_conversion_live_views.sql)

What it contains:
- logical detail view
- logical daily rollup view
- logical monthly rollup view

This file is useful as the readable transformation spec, but it is not the primary deployed source anymore.

### 2. Materialized staging layer

Purpose:
- provide a stable source of truth
- make reporting less dependent on recomputing the full query each time
- support repeatable downstream reporting

Local file:
- [build_actual_inquiry_booking_conversion_tables.sql](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/build_actual_inquiry_booking_conversion_tables.sql)

BigQuery tables created:
- `gulong_reporting.t_actual_inquiry_booking_conversion_detail`
- `gulong_reporting.t_actual_inquiry_booking_conversion_daily`
- `gulong_reporting.t_actual_inquiry_booking_conversion_monthly`

Roles:
- `t_actual_inquiry_booking_conversion_detail`
  - inquiry-grain source of truth
  - one row per inquiry cohort row
- `t_actual_inquiry_booking_conversion_daily`
  - reporting aggregate by `report_date + lane`
- `t_actual_inquiry_booking_conversion_monthly`
  - reporting aggregate by `report_month + lane`

This is the primary operational source of truth.

### 3. Looker reporting layer

Purpose:
- give Looker Studio stable, presentation-ready objects
- avoid pointing dashboards directly at staging tables
- preserve freedom to rebuild staging independently

Local files:
- [create_looker_actual_inquiry_booking_conversion_views.sql](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/create_looker_actual_inquiry_booking_conversion_views.sql)
- [create_looker_actual_inquiry_booking_conversion_views_documented.sql](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/create_looker_actual_inquiry_booking_conversion_views_documented.sql)

BigQuery views created:
- `gulong_reporting.v_looker_actual_inquiry_booking_conversion_detail`
- `gulong_reporting.v_looker_actual_inquiry_booking_conversion_daily`
- `gulong_reporting.v_looker_actual_inquiry_booking_conversion_monthly`

Recommended Looker source:
- `gulong_reporting.v_looker_actual_inquiry_booking_conversion_monthly`

---

## Engineering Flow

The engineering path used here was:

1. inspect the workbook and infer the correct inquiry-date/original-owner logic
2. validate the booking universe against the workbook target
3. write readable logical SQL
4. materialize the logic into `t_...` tables
5. create `v_looker_...` reporting views on top of those tables
6. validate the outputs against expected monthly totals

Validated July monthly output:
- inquiries = `12,472`
- bookings = `111`
- conversion rate = `0.89%`
- booking revenue = `2,533,390.39`

---

## File Responsibilities

If someone needs to edit this stack later, these are the files that matter.

### Core logic files

- [create_actual_inquiry_booking_conversion_live_views.sql](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/create_actual_inquiry_booking_conversion_live_views.sql)
  - readable logical SQL version
  - edit here if you want to rethink business logic before materialization

- [build_actual_inquiry_booking_conversion_tables.sql](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/build_actual_inquiry_booking_conversion_tables.sql)
  - materialized staging deploy script
  - edit here if you want to change the real source-of-truth tables

- [create_looker_actual_inquiry_booking_conversion_views.sql](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/create_looker_actual_inquiry_booking_conversion_views.sql)
  - Looker-facing views on top of staging
  - edit here if you want to rename/expose fields for BI only

- [create_looker_actual_inquiry_booking_conversion_views_documented.sql](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/create_looker_actual_inquiry_booking_conversion_views_documented.sql)
  - single-file Looker reporting layer deploy
  - useful as the handoff file for BI/report users

### Supporting documentation files

- [actual_inquiry_booking_conversion_notes_2026-07-29.md](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/actual_inquiry_booking_conversion_notes_2026-07-29.md)
  - business notes
  - workbook alignment notes
  - key caveats

- [DT-2026-07-29_Updates.md](/home/jerico/Desktop/gulong-data/z_actual_inquiry_and_booking/DT-2026-07-29_Updates.md)
  - management readout context
  - narrative findings using the same workbook logic family

---

## Change Guidance

Use this rule of thumb:

- if business logic changes:
  - edit `build_actual_inquiry_booking_conversion_tables.sql`
  - usually also update `create_actual_inquiry_booking_conversion_live_views.sql`

- if only dashboard field naming or BI shape changes:
  - edit `create_looker_actual_inquiry_booking_conversion_views.sql`
  - or `create_looker_actual_inquiry_booking_conversion_views_documented.sql`

- if the narrative/readout changes:
  - edit the `.md` notes files only

---

## Run Order

Use this order when rebuilding or deploying the stack.

### Full rebuild

1. Review business-logic edits in:
   - `build_actual_inquiry_booking_conversion_tables.sql`
   - optionally `create_actual_inquiry_booking_conversion_live_views.sql` if you want the readable logical version to stay in sync

2. Run:
   - `build_actual_inquiry_booking_conversion_tables.sql`

3. Refresh the Looker-facing layer by running:
   - `create_looker_actual_inquiry_booking_conversion_views_documented.sql`
   - or `create_looker_actual_inquiry_booking_conversion_views.sql`

4. Validate the outputs in BigQuery:
   - monthly total inquiries
   - monthly total bookings
   - conversion rate
   - booking revenue

5. In Looker Studio:
   - refresh fields
   - confirm the data source still points to the `v_looker_...` objects

### If only business logic changed

Run in this order:

1. Update:
   - `build_actual_inquiry_booking_conversion_tables.sql`

2. Run:
   - `build_actual_inquiry_booking_conversion_tables.sql`

3. Then run:
   - `create_looker_actual_inquiry_booking_conversion_views_documented.sql`

Reason:
- the Looker views sit on top of the `t_...` tables
- if the table schema changes, the Looker views should be refreshed after the table rebuild

### If only Looker field names or exposed columns changed

Run:

1. Update:
   - `create_looker_actual_inquiry_booking_conversion_views.sql`
   - or `create_looker_actual_inquiry_booking_conversion_views_documented.sql`

2. Run only the Looker file you changed

Reason:
- staging tables do not need to be rebuilt if only the BI-facing projection changed

### If only documentation changed

No SQL deployment is needed.

Update only:
- `actual_inquiry_booking_conversion_notes_2026-07-29.md`
- `actual_inquiry_booking_conversion_architecture_2026-07-29.md`
- `DT-2026-07-29_Updates.md`

---

## Statement Order

At a practical level, the deployment sequence is:

### Statement group A — staging tables

Run from:
- `build_actual_inquiry_booking_conversion_tables.sql`

Order:
1. `t_actual_inquiry_booking_conversion_detail`
2. `t_actual_inquiry_booking_conversion_daily`
3. `t_actual_inquiry_booking_conversion_monthly`

Why this order:
- `daily` reads from `detail`
- `monthly` also reads from `detail`
- so `detail` must be rebuilt first

### Statement group B — Looker views

Run from:
- `create_looker_actual_inquiry_booking_conversion_views_documented.sql`

Order:
1. `v_looker_actual_inquiry_booking_conversion_detail`
2. `v_looker_actual_inquiry_booking_conversion_daily`
3. `v_looker_actual_inquiry_booking_conversion_monthly`

Why this order:
- all three depend on the already-materialized `t_...` tables
- they do not depend on one another, but keeping the same order makes deployment predictable

### Recommended operational sequence

1. rebuild `t_actual_inquiry_booking_conversion_detail`
2. rebuild `t_actual_inquiry_booking_conversion_daily`
3. rebuild `t_actual_inquiry_booking_conversion_monthly`
4. rebuild `v_looker_actual_inquiry_booking_conversion_detail`
5. rebuild `v_looker_actual_inquiry_booking_conversion_daily`
6. rebuild `v_looker_actual_inquiry_booking_conversion_monthly`
7. validate July totals
8. refresh fields in Looker Studio

### Validation query checklist

After deployment, verify at minimum:

1. Monthly combined totals for `2026-07-01`
   - inquiries = `12,472`
   - bookings = `111`
   - conversion rate = `0.89%`
   - booking revenue = `2,533,390.39`

2. Lane-level monthly outputs:
   - Taira
   - Rem
   - Aira
   - Rolyn
   - Sarah

3. Check that `loaded_at` updated on:
   - `t_actual_inquiry_booking_conversion_monthly`
   - `v_looker_actual_inquiry_booking_conversion_monthly`

---

## Current Source of Truth

As of `2026-07-29`, the intended source-of-truth layer is:
- `gulong_reporting.t_actual_inquiry_booking_conversion_detail`
- `gulong_reporting.t_actual_inquiry_booking_conversion_daily`
- `gulong_reporting.t_actual_inquiry_booking_conversion_monthly`

The intended Looker-facing layer is:
- `gulong_reporting.v_looker_actual_inquiry_booking_conversion_detail`
- `gulong_reporting.v_looker_actual_inquiry_booking_conversion_daily`
- `gulong_reporting.v_looker_actual_inquiry_booking_conversion_monthly`

So the architecture is:

`gulong_core.*` sources
-> transformation logic
-> `t_actual_inquiry_booking_conversion_*` staging tables
-> `v_looker_actual_inquiry_booking_conversion_*` reporting views
-> Looker Studio
