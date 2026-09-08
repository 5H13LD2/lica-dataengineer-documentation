# Jeanel Co — Daily Inquiries, Moderate/High, Bookings (Jul 1–31, 2026)

## What this report covers
Daily counts for chatbot **Jeanel Co** (internally labeled **Taira**, the automated first-touch agent) as the original owner of the inquiry, for July 1–31, 2026.

Columns in `jeanel_co_july_2026.csv`:
- `date` — inquiry date (Asia/Manila)
- `inquiries_assigned` — inquiries where Jeanel Co is the original owner
- `moderate_high` — of those, inquiries classified Moderate Intent or higher
- `bookings` — bookings attributed to those inquiries

## Data source
- **Project:** `gulong-chatbot-459723`
- **Table:** `gulong_reporting.t_inquiry_funnel_conversion_daily_v2`
- **Slice used:** `original_owner = 'Taira'`, `view_scope = 'primary original-owner conversion'`, `funnel = 'Overall Inquiry-to-Booking'`, `date_basis = 'inquiry date'`
- **Rule version:** `gulong_intent_v2_20260811`
- **Refreshed:** 2026-09-03 23:45:13 (source_refreshed_at on the pull)
- **Booking observation cutoff:** 2026-09-03 23:45:59

This is the non-double-counting per-owner view. Non-additive handoff-stage overlay rows are excluded.

## Definitions and caveats

**Inquiry (original owner).** The inquiry remains attributed to Jeanel Co / Taira when Taira was the first assigned agent, even after a handoff to a human CS agent.

**Moderate/High.** This combines Moderate, High, and Hot intent. It is not moderate-only.

**Bookings.** Only reportable bookings are counted. They are credited to the inquiry start date rather than the order date.

## Totals (Jul 1–31, 2026)
- Inquiries assigned: **3,913**
- Moderate/High: **713**
- Bookings: **41**

## June availability
This reporting mart and all retained historical copies begin on **2026-07-01**. Therefore, an equivalent June extract is not available from this source. Producing June requires reconstructing the mart logic from the underlying assignment, intent-classification, and booking-attribution sources; missing June rows must not be treated as zero activity.
