# Gulong Chatbot Analytics — Architecture & Build Manual

*A "GA4 for the chatbot" reference. Reconstructs every number in the weekly DT Update from source tables, then extends it into a self-serve funnel/cohort layer.*

Project: `gulong-chatbot-459723` · Reporting dataset: `gulong_reporting`

---

## Verdict: Kaya ba i-architect?

**Oo — at hindi ito bagong warehouse.** Lahat ng kailangan ay nasa `gulong_core` na. Ang "GA4 for chatbot" ay isang bagong **gold layer** lang sa ibabaw ng existing core tables, na:

1. ginagawang isang unified session fact ang moderate sessions (downstream) at
2. dinudugtong dito ang guided-surface engagement (upstream)

...via isang session key. Yun lang talaga ang bago. Walang re-instrumentation; consolidation.

Ang sentro ng lahat ay **`gulong_core.moderate_intent_sessions`** — siya ang katumbas ng GA4 session table. Pinagta-tagpuan niya ang intent (classifier), owner (assignments), booking (orders), at journey (guided/semantic).

---

## Part 1 — The data model (medallion)

Ito ang lineage na na-reconstruct mula sa "Reporting Definitions and Data Sources" ng PDF.

| Layer | Dataset | Table | Rol |
|---|---|---|---|
| **Raw** | `manychat_data` | `messages` | Bawat mensahe. Partitioned sa `datetime`. |
| **Raw** | `manychat_data` | `agent_assignment_events` | Kailan na-assign / na-handoff sa agent. |
| **Core** | `gulong_core` | `moderate_intent_sessions` | **Session grain.** Isang row per moderate inquiry + intent level. |
| **Core** | `gulong_core` | `inquiry_assignments` | Original inquiry owner (attribution). |
| **Core** | `gulong_core` | `orders_booked` | Booking truth (qualifying orders). |
| **Reporting** | `gulong_reporting` | `p_looker_agent_daily_conversion` | Materialized daily rollup na binabasa ng Looker. |
| **Reporting** | `gulong_reporting` | guided-surface + semantic tables | Click logs + stage analysis. |

**Flow:** ManyChat/FB → `manychat_data` (raw) → `gulong_core` (curated) → `gulong_reporting` (materialized) → DT Update PDF + Looker.

---

## Part 2 — Session definition (LOCKED)

```
session_id  = user_id (PSID / contact) + inquiry_date
user_id     = person (persistent across weeks)
cohort_key  = inquiry_date
```

Rules:

- Isang inquiry episode kada araw = isang session.
- Kung nag-inquire ulit ang parehong customer next week → **bagong session** sa bagong petsa.
- **Booking attribution:** umuuwi sa *original inquiry_date*, hindi sa order creation date. **Walang fixed conversion window** — patuloy na aakyat ang booking count ng lumang cohort habang tumatanda ito ("revisit after maturation").
- Order creator ay retained lang bilang closing-workload view, hindi para sa conversion attribution.

---

## Part 3 — Build manual: pano nakuha ang bawat number sa PDF

Bawat section ng PDF ay may deterministic path pababa sa lineage. Ito ang "manual."

> Note sa column names: ang mga SQL sa ibaba ay **sketches**. Kung saan may `-- confirm`, i-map sa actual na column ng existing views mo.

### 3.1 — Chatbot Performance Snapshot (Section 1)

**Sagot sa:** Inquiries · Moderate/High · Moderate rate · Bookings · Booking rate, per weekly cohort, Taira-origin.

**Sources:** `moderate_intent_sessions` (denominator + intent) → `orders_booked` (numerator, joined back sa inquiry).

```sql
WITH cohorts AS (
  SELECT
    s.session_id,
    s.inquiry_date,
    -- Wed–Tue weekly bucket
    DATE_TRUNC(DATE_SUB(s.inquiry_date, INTERVAL 2 DAY), WEEK(WEDNESDAY)) AS cohort_wk,
    s.intent_level,                                   -- confirm: low/moderate/high
    s.channel                                         -- confirm: 'taira' vs human
  FROM `gulong-chatbot-459723.gulong_core.moderate_intent_sessions` s
  WHERE s.channel = 'taira'
),
booked AS (
  SELECT DISTINCT o.session_id                        -- confirm join key to inquiry
  FROM `gulong-chatbot-459723.gulong_core.orders_booked` o
  -- NO conversion window: any booking traceable to the inquiry counts
)
SELECT
  cohort_wk,
  COUNT(*)                                                        AS inquiries,
  COUNTIF(intent_level IN ('moderate','high'))                   AS moderate_high,
  SAFE_DIVIDE(COUNTIF(intent_level IN ('moderate','high')), COUNT(*)) AS moderate_rate,
  COUNT(DISTINCT b.session_id)                                   AS bookings,
  SAFE_DIVIDE(COUNT(DISTINCT b.session_id), COUNT(*))            AS booking_rate
FROM cohorts c
LEFT JOIN booked b USING (session_id)
GROUP BY cohort_wk
ORDER BY cohort_wk;
```

**Gotchas:**
- Weekly buckets ay **Wed–Tue** (Jul 1–7, 8–14, ...).
- Ang huling cohort ay *immature* — bumababa ang booking rate hindi dahil sa performance kundi dahil kulang pa sa maturation.

### 3.2 — Human CS Inquiry Conversion (Section 2)

**Sagot sa:** bookings / inquiries per agent (Rem, Aira, Rolyn, Sarah) per cohort.

**Sources:** `inquiry_assignments` (original owner) → `orders_booked` (attributed by original owner).

```sql
SELECT
  a.owner_agent,                                       -- confirm: original owner col
  cohort_wk,
  COUNT(*)                                    AS inquiries,
  COUNT(DISTINCT b.session_id)               AS bookings,
  SAFE_DIVIDE(COUNT(DISTINCT b.session_id), COUNT(*)) AS booking_rate
FROM `gulong-chatbot-459723.gulong_core.inquiry_assignments` a
LEFT JOIN booked b USING (session_id)
WHERE a.owner_agent IN ('Rem Reyes','Aira L. Garcia','Rolyn Ang','Sarah')
GROUP BY a.owner_agent, cohort_wk;
```

**Gotcha (kritikal):** attribution ay sa **original inquiry owner**, HINDI sa booking creator. Ito ang nagpapaiba sa conversion view vs. closing-workload view.

### 3.3 — Sarah/Taira Qualified Handoff SLA (Section 3)

**Sagot sa:** response rate, within-30-min, within-1-hr, median/avg **business** response, queue-depth correlation.

**Sources:** `agent_assignment_events` (handoff time) + `messages` (first agent reply).

```sql
WITH handoffs AS (
  SELECT
    e.session_id,
    e.assigned_at AS handoff_ts,                       -- confirm
    e.to_agent                                          -- confirm
  FROM `gulong-chatbot-459723.manychat_data.agent_assignment_events` e
  WHERE e.is_qualified = TRUE                           -- confirm
),
first_reply AS (
  SELECT
    m.session_id,                                       -- confirm mapping PSID->session
    MIN(m.datetime) AS reply_ts
  FROM `gulong-chatbot-459723.manychat_data.messages` m
  WHERE m.datetime BETWEEN '2026-07-01' AND '2026-07-29'   -- REQUIRED partition filter
    AND m.sender = 'agent'                              -- confirm
  GROUP BY m.session_id
)
SELECT
  h.session_id,
  -- business-minute response: clamp to 09:00–18:00 Asia/Manila,
  -- after-hours handoff clock starts 09:00 next business day
  DATETIME_DIFF(r.reply_ts, h.handoff_ts, MINUTE) AS raw_minutes  -- then apply business clock
FROM handoffs h
JOIN first_reply r USING (session_id);
```

**Gotchas:**
- **Business minutes lang** (09:00–18:00 Asia/Manila). After-hours handoff → clock starts 09:00 next business day (hindi in-e-exclude, ni-re-reset).
- Gamitin ang **`DATETIME_DIFF`**, hindi `TIMESTAMP_DIFF`.
- `messages` **kailangan ng partition filter sa `datetime`** — kung wala, tatama sa full-scan error.
- Queue depth = bilang ng open qualified cases sa mismong sandali ng handoff → Spearman vs response delay = 0.596. Ito ang pinakamalinaw na operating control.

### 3.4 — Guided Surfaces & Lift (Section 4)

**Sagot sa:** click rate + M/H lift (clicked vs shown-no-click) per surface.

**Sources:** guided-surface event logs (`surface_shown` + `surface_clicked`) joined sa `moderate_intent_sessions`.

```sql
SELECT
  g.surface_type,                                       -- promo_carousel/price_category/location_buttons/product_choices
  COUNTIF(g.event = 'shown')                            AS shown,
  COUNTIF(g.event = 'clicked')                          AS clicked,
  SAFE_DIVIDE(COUNTIF(g.event='clicked'), COUNTIF(g.event='shown')) AS click_rate,
  -- lift: M/H rate among clickers vs shown-no-click
  SAFE_DIVIDE(COUNTIF(g.event='clicked' AND s.intent_level IN ('moderate','high')),
              COUNTIF(g.event='clicked'))               AS mh_clicked,
  SAFE_DIVIDE(COUNTIF(g.event='shown'  AND s.clicked IS NULL
                      AND s.intent_level IN ('moderate','high')),
              COUNTIF(g.event='shown' AND s.clicked IS NULL)) AS mh_shown_no_click
FROM `gulong-chatbot-459723.gulong_reporting.guided_surface_events` g   -- confirm name
LEFT JOIN `gulong-chatbot-459723.gulong_core.moderate_intent_sessions` s
  USING (session_id)
GROUP BY g.surface_type;
```

**Gotcha (ito ang buong insight):** kailangang **hiwalay** ang `shown` sa `clicked`. Dito nakabatay ang location lift na 60.19% (clicked) vs 11.18% (shown-no-click). Kapag pinagsama, mawawala ang pinakamalakas na conversion signal mo.

### 3.5 — Journey Stages (Section 5)

**Sagot sa:** reached pricing → IP stage → scheduling → contact, per guided-selection depth.

**Sources:** semantic conversation analysis tables + field captures, joined sa session.

Bawat stage ay **deterministic** — derived mula sa `field_captured` / `surface_clicked` / keyword sa `messages`. Isa lang ang classifier-fed: ang `intent_level`. Kaya malinis ang hati: lahat deterministic maliban sa isang enrichment field.

```sql
SELECT
  s.guided_depth,                                       -- 0,1,2,3+
  COUNT(*) AS inquiries,
  COUNTIF(s.intent_level IN ('moderate','high')) / COUNT(*) AS mh_rate,
  COUNTIF(s.reached_pricing)   / COUNT(*)               AS pct_pricing,
  COUNTIF(s.reached_ip_stage)  / COUNT(*)               AS pct_ip,
  COUNTIF(s.reached_schedule)  / COUNT(*)               AS pct_schedule,
  COUNTIF(s.captured_contact)  / COUNT(*)               AS pct_contact
FROM `gulong-chatbot-459723.gulong_core.moderate_intent_sessions` s
GROUP BY s.guided_depth;
```

---

## Part 4 — Ang GA4-for-chatbot target layer

Tatlong bagong object sa `gulong_reporting`. Item 1 ang core; items 2–3 ay slices.

### 4.1 — `v_looker_session_fact` (ang unified session view)

Isang row per session, lahat ng dimensions + stage flags sticky na. Ito ang binabasa ng lahat ng funnel.

```sql
CREATE OR REPLACE VIEW `gulong-chatbot-459723.gulong_reporting.v_looker_session_fact` AS
SELECT
  s.session_id,
  s.user_id,
  s.inquiry_date,
  s.channel,                       -- taira vs human
  a.owner_agent,
  s.intent_level,                  -- classifier
  s.guided_depth,
  -- upstream engagement (JOIN, hindi rebuild)
  g.clicked_location, g.clicked_price, g.clicked_promo, g.price_tier, g.promo_brand,
  -- downstream funnel (galing sa existing dashboard mo)
  s.reached_pricing, s.reached_ip_stage, s.reached_schedule, s.captured_contact,
  fr.reply_ts, fr.first_reply_business_minutes,
  fu.followup_ts, fu.followup_business_minutes,     -- follow-up monitoring mo
  b.booked, b.booking_ts,
  DATETIME_DIFF(b.booking_ts, s.inquiry_ts, HOUR) AS hours_to_book
FROM `gulong-chatbot-459723.gulong_core.moderate_intent_sessions` s
LEFT JOIN `gulong-chatbot-459723.gulong_core.inquiry_assignments` a USING (session_id)
LEFT JOIN guided_surface_rollup g USING (session_id)   -- upstream
LEFT JOIN first_reply_rollup   fr USING (session_id)
LEFT JOIN followup_rollup      fu USING (session_id)
LEFT JOIN booking_rollup       b  USING (session_id);
```

Ito ang **direktang extension ng dashboard mo ngayon** (moderate → first reply → follow-up → booking) — dinagdagan lang ng upstream guided columns.

### 4.2 — `event_stream` (optional, para sa path analysis)

Kailangan mo lang ito kapag gusto mo na ang *sequence* ng surfaces (GA4 path exploration). Long format: `event_name, ts, session_id, user_id, params`. UNION ALL ng messages + guided events + field captures + handoff + booking. **Later na ito** — hindi kailangan para sa funnel/lift/cohort.

### 4.3 — Funnel / lift / cohort slices

Lahat ng ito ay `GROUP BY` lang sa `v_looker_session_fact`:

- **Funnel:** inquiry → guided → pricing → IP → schedule → contact → booking, segmentable by channel/brand/tier.
- **Lift:** clicked vs shown-no-click M/H (Section 4, pero interactive na).
- **Cohort maturation:** bookings-over-time per inquiry_date cohort.
- **Segment compare:** Taira vs Human CS side-by-side sa iisang funnel.

**Superpower na wala sa GA4:** intent-progression turn-by-turn (mula sa classifier per turn). Anong surface ang nag-t-trigger ng jump from Low → Moderate.

---

## Part 5 — Build order + open items

**Build order:**
1. `v_looker_session_fact` (Part 4.1) — dito nakasalalay lahat.
2. Funnel + lift + cohort views (Part 4.3) — `GROUP BY` lang.
3. Event stream (Part 4.2) — kapag kailangan na ng path analysis.

**Open item (blocker sa Part 4.1):** yung `guided_surface_rollup` join.
- Kung ang guided-surface logs ay **naka-key na sa `session_id` (user + inquiry_date)** → diretsong `USING (session_id)`, tapos.
- Kung **PSID + timestamp pa lang** → kailangan muna ng stitching step: i-resolve ang PSID→user_id, tapos i-bucket ang event sa tamang `inquiry_date` window bago mag-join.

Ito ang isang bagay na dapat i-confirm bago mag-build ng session fact.

---

## Appendix — Technical constraints (gotchas)

| Constraint | Bakit |
|---|---|
| BigQuery MCP ay **read-only** | DDL (`CREATE VIEW`) ay manual sa BigQuery Console. |
| `manychat_data.messages` needs **partition filter sa `datetime`** | Kung wala, full-scan / error. |
| Gamitin **`DATETIME_DIFF`**, hindi `TIMESTAMP_DIFF` | Consistency sa business-minute logic. |
| Business hours **09:00–18:00 Asia/Manila** | After-hours handoff clock resets 09:00 next business day. |
| Attribution: **original owner + inquiry_date, walang conversion window** | Order creator = closing-workload view lang. |
| Looker Studio custom queries **hindi kaya ang `@DS_START_DATE`** natively | I-handle sa view o parameterize sa ibang paraan. |
| Huling cohort ay **immature** | Booking rate aakyat pa habang tumatanda; huwag i-interpret as decline agad. |