# Jeanel Co — Daily Inquiries, Moderate/High, Bookings (Aug 1–31, 2026)

## What this report covers
Daily counts for the chatbot **Jeanel Co** (internally labeled **Taira**, the automated first-touch agent) as the *original owner* of the inquiry, for August 1–31, 2026.

Columns in `jeanel_co_aug_2026.csv`:
- `date` — inquiry date (Asia/Manila)
- `inquiries_assigned` — inquiries where Jeanel Co is the original owner
- `moderate_high` — of those, inquiries classified Moderate Intent or higher
- `bookings` — bookings attributed to those inquiries

## Data source
- **Project:** `gulong-chatbot-459723`
- **Table:** `gulong_reporting.t_inquiry_funnel_conversion_daily_v2`
- **Slice used:** `original_owner = 'Taira'`, `view_scope = 'primary original-owner conversion'`, `funnel = 'Overall Inquiry-to-Booking'`, `date_basis = 'inquiry date'`
- **Rule version:** `gulong_intent_v2_20260811`
- **Refreshed:** 2026-08-19 (source_refreshed_at on the pull)

This slice is the non-double-counting per-owner view. The table also carries "non-additive handoff-stage overlay" rows (Chatbot Handoffs, Sunday Experiment) that intentionally overlap other agents — those are **excluded** here so totals don't get counted twice.

## Definitions

**Inquiry (original owner).** An inquiry is a customer session assigned to an agent. "Original owner" is the first agent the inquiry was assigned to — Jeanel Co / Taira as the automated first responder — regardless of any later handoff to a human CS agent. Attribution to the original owner is why a later handoff doesn't move the inquiry out of Jeanel's count.

**Moderate/High.** Intent is scored on a 5-tier ladder: No → Low → Moderate → High → Hot (source: `chat_analysis` intent v2 classifier, `intent_rating.top_intent`). The `moderate_high` column counts inquiries rated **Moderate Intent or higher**, i.e. it combines Moderate, High (and Hot) into one number. It is **not** moderate-only. If you need Moderate broken out separately from High/Hot, that can be pulled from `gulong_core.moderate_intent_inquiries`.

**Bookings.** Bookings attributed to a Jeanel-owned inquiry, on an inquiry-date basis (the booking is credited to the day the inquiry started, not the day the order was placed). Only reportable bookings are counted (`is_reportable_booking = true`); test/excluded orders are dropped. Booking attribution has an observation cutoff, meaning very recent inquiries may still convert after this pull and later-dated numbers can tick up on refresh.

## Known caveats
1. **Moderate + High are combined** in this table's `moderate_high_inquiries` field.
2. **Late-arriving bookings.** Figures for the most recent days can increase on later refreshes as attribution catches up. Numbers for a few August days already shifted between refreshes.
3. **High-volume days** (e.g. Aug 2, 9, 16, 23) reflect campaign/traffic spikes, not a data error.
4. Counts are **inquiry-date based**, so a booking placed in September from an August inquiry is credited to the August inquiry date.

## Totals (Aug 1–31, 2026)
- Inquiries assigned: **3,966**
- Moderate/High: **634**
- Bookings: **33**
