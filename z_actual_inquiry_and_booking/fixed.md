# Rebuild Spec — Actual Inquiry → Booking Conversion (Looker report layer)

Author handoff doc. Follow this to rebuild the conversion reporting stack from
scratch so it reproduces the audit workbook exactly. Every rule below is the
**target logic**, already corrected for the join/call/dedup bugs found in the
2026-07-29 build.

---

## 1. Objective

Produce a stable, Looker-facing reporting layer that answers, per reporting lane:

- how many **actual inquiries** the lane owned (denominator)
- how many of those inquiries converted to **traceable bookings**
- the conversion rate, and the booking revenue behind it

Source of truth for correctness is the audit workbook
`gulong_july_booking_conversion_audit_2026-07-29.xlsx`. If the rebuild does not
reproduce Section 7 targets, it is wrong — do not ship it.

**Grain:** inquiry-date cohort, original inquiry owner.
**This is NOT:** booking-date reporting, booking-creator reporting, or
final-owner reporting.

---

## 2. Reporting lanes

Five lanes only. Everything else is out of scope (Atossa/admin, other names).

- `Taira (Chatbot/JCo)`
- `Rem Reyes`
- `Aira L. Garcia`
- `Rolyn Ang`
- `Sarah`

Name normalization (lowercased, trimmed) that must be applied identically
everywhere a lane is derived:

| Raw value | Lane |
|---|---|
| `is_chatbot_jeanel = TRUE` | Taira (Chatbot/JCo) |
| `rem reyes` | Rem Reyes |
| `aira l. garcia`, `aira` | Aira L. Garcia |
| `rolyn ang` | Rolyn Ang |
| `sarah gulongph`, `sarah mae manansala`, `sarah` | Sarah |

The `aira` bare alias must appear in **every** lane list — denominator,
booking attribution, and base views. Asymmetry here silently drops bookings.

---

## 3. Source tables

- Denominator: `gulong-chatbot-459723.gulong_core.inquiry_assignments`
- Moderate flag: `gulong-chatbot-459723.gulong_core.moderate_intent_sessions`
- Bookings: `gulong-chatbot-459723.gulong_core.orders_all`

All filtered to `business_unit = 'gulong'`.

---

## 4. The three build rules

### 4a. Denominator — actual inquiries

One row per **silver session per month**, restricted to the five lanes.

- Filter: `business_unit = 'gulong'` AND
  (`is_chatbot_jeanel` OR `agent_reporting_name` in the lane list incl. `aira`).
- Dedup key (grain): `COALESCE(silver_session_id, 'event:'||assignment_event_id, 'user:'||user_id||':'||assignment_at)`.
- **Dedup must be partitioned by month.** Partition the `ROW_NUMBER()` by
  `DATE_TRUNC(assignment_date, MONTH)` + the dedup key, order by
  `assignment_at ASC, loaded_at DESC, assignment_event_id`, keep row 1.
  Without the month partition, a session that spans months is pulled into the
  earlier month and disappears from the month you are reporting.
- `report_date = assignment_date`; also derive `report_week`, `report_month`.

### 4b. Moderate flag (funnel depth, not required for the core KPI)

- From `moderate_intent_sessions`, keep `validated_moderate = TRUE`, one row
  per `silver_session_id` **per month**.
- Join to the cohort on `silver_session_id` + `report_month`. Session-less cohort rows simply
  get `validated_moderate = FALSE`.

### 4c. Booking attribution — the traceable bookings

A booking qualifies when **all** of these hold on `orders_all`:

1. `is_reportable_booked_order = TRUE`
2. **Not a CALL order.** In this environment, exclude via
   `LOWER(TRIM(customer_source_norm)) <> 'call'`.
   Do **not** try to exclude calls via `sales_channel` — all call orders are
   `sales_channel = 'fb'`, so a channel filter keeps every one of them.
3. `inquiry_assignment_date IS NOT NULL` and `booking_day IS NOT NULL`
4. Original owner is in-scope: `original_assigned_is_chatbot_jeanel = TRUE` OR
   `COALESCE(original_assigned_agent_name, inquiry_agent_reporting_name, inquiry_assigned_agent_name)`
   in the lane list (incl. `aira`).

Aggregate to inquiry grain with `COUNT(DISTINCT order_id)` and the revenue
`SUM(...)`s. An inquiry can have >1 booking, which is why total bookings (111)
exceed distinct converted inquiries (107).

---

## 5. The join rule (this is what was broken)

Keep **two separate keys** and never conflate them:

- **Denominator grain key** = SESSION-first: `COALESCE(silver_session_id, event:…, user:…)`.
  Used only for the month-scoped dedup in 4a.
- **Booking join key** = EVENT-first: `COALESCE('evt:'||assignment_event_id, 'sess:'||silver_session_id, 'usr:'||user_id||':'||assignment_at)`.
  Built with the **identical expression on both the cohort side and the order
  side** (order side uses `inquiry_assignment_event_id`, `inquiry_silver_session_id`,
  `manychat_user_id`, `inquiry_assignment_at`).

Why event-first: on qualifying bookings, `inquiry_assignment_event_id` is
populated 100% of the time; `inquiry_silver_session_id` only ~75%. A
session-first join key means a cohort row keyed `sess:…` never matches an order
keyed `evt:…`, and the booking is lost. Event-first, symmetric on both sides,
fixes it. This is safe because attribution connects the **original** assignment
event and the dedup keeps the **earliest** (= original) event, so the two align.

Final join in the detail table:

- `LEFT JOIN moderate_flags ON silver_session_id + report_month`
- `LEFT JOIN booking_flags ON booking_join_key` (the EVENT-first key)

`LEFT JOIN` from the cohort guarantees bookings whose inquiry falls outside the
reporting month (e.g. June inquiry, July booking) do not attach to that month —
which is exactly why 19 such July bookings are correctly excluded from the 111.

---

## 6. Layer architecture

```
gulong_core.*  (inquiry_assignments, moderate_intent_sessions, orders_all)
   -> t_actual_inquiry_booking_conversion_detail    (inquiry grain, source of truth)
   -> t_actual_inquiry_booking_conversion_daily      (report_date + lane)
   -> t_actual_inquiry_booking_conversion_monthly     (report_month + lane)
   -> v_looker_actual_inquiry_booking_conversion_detail / _daily / _monthly
   -> Looker Studio  (point at v_looker_..._monthly)
```

- Detail table is partitioned by `report_date`, clustered by `reporting_lane, inquiry_key`.
- Daily/monthly are pure `GROUP BY` rollups off the detail table — no source
  logic lives there. Metrics: `actual_inquiries = COUNT(*)`,
  `validated_moderate_inquiries = COUNTIF(validated_moderate)`,
  `traceable_qualifying_bookings = SUM(qualifying_booking_count)`,
  `distinct_converted_inquiries = COUNTIF(converted_inquiry)`, plus
  `SAFE_DIVIDE` rates.
- Looker views only rename/project columns (e.g. `reporting_lane AS agent_name`,
  `traceable_qualifying_bookings AS booking_count`). They need **no change**
  when the detail logic changes — rebuild the tables, refresh fields in Looker.

Keep the PDF-card snapshot layer (`t_pdf_cards_agent_conversion_2026_07_29`)
entirely separate. It is a frozen report-pack source with a different cutoff
(Jul 1–28, 22:38) and different totals; never merge it into this live stack.

---

## 7. Validation targets (July 2026 — must match exactly)

Run against `t_actual_inquiry_booking_conversion_monthly` where
`report_month = DATE '2026-07-01'`:

| Lane | actual_inquiries | traceable bookings | distinct converted |
|---|---|---|---|
| Taira (Chatbot/JCo) | 3,699 | 32 | 31 |
| Aira L. Garcia | 2,567 | 26 | 25 |
| Rem Reyes | 2,564 | 22 | 22 |
| Sarah | 1,943 | 18 | 16 |
| Rolyn Ang | 1,656 | 13 | 13 |
| **Total** | **12,429** | **111** | **107** |

If bookings come out **> 111** and lanes still match: check the CALL exclusion
(4c.2) first. If bookings come out **< 111**: check the join key is EVENT-first
and symmetric (Section 5). If inquiries drift a few off 12,429: check the
month-partitioned dedup (4a) and note live-data drift vs the 12:07 snapshot.

The old architecture-doc figure `12,472` was an earlier data state — ignore it;
`12,429` is the audit truth.

---

## 8. Run order

1. Build `t_actual_inquiry_booking_conversion_detail` (has all the logic).
2. Build `t_actual_inquiry_booking_conversion_daily`.
3. Build `t_actual_inquiry_booking_conversion_monthly`.
4. Run the validation query in Section 7. Stop and fix if it doesn't match.
5. Rebuild the three `v_looker_actual_inquiry_booking_conversion_*` views.
6. Refresh fields in Looker Studio; confirm the source still points at the
   `v_looker_...` objects.

Deploy manually in the BigQuery console or via the available BigQuery execution tooling.

---

## 9. Caveats to carry forward

- **Live drift:** the workbook is a fixed snapshot; July bookings can rise above
  111 as late bookings land against July inquiries (no observation cap). Compare
  only at a same-time cutoff.
- **`is_call_order` availability:** confirm it exists on `orders_all`; fall back
  to `customer_source_norm <> 'call'` if not (verified: all 27 call orders carry
  `customer_source_norm = 'call'`).
- **Session-less inquiries** (null `silver_session_id`) never receive a moderate
  flag, by design — moderate is session-keyed on both sides.
- **Multi-event sessions:** the join assumes attribution links the original
  (earliest) event, which the dedup also keeps. If a booking is ever linked to a
  later re-assignment event, revisit Section 5.
