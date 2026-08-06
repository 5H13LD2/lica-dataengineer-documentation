# Gulong Chatbot Analytics — Target Architecture

Ito ang target architecture para sa **stable, scalable, at accurate** na chatbot analytics data source na naka-anchor sa **mature downstream cohort** na meron na sa repo.

Hindi ito greenfield rebuild. Ang strategy ay:

- gamitin ang mature `moderate -> first reply -> follow-up -> booking` cohort bilang truth backbone
- i-promote iyon into a canonical session-level source
- ihiwalay ang risky upstream guided-surface stitching
- i-derive ang mga funnel at serving views mula sa canonical layer

---

## 1. Goal

Gumawa ng analytics layer na:

- **stable**: hindi madaling masira kapag may bagong enrichment o bagong funnel
- **scalable**: isang canonical session spine, maraming derived funnel views
- **accurate**: iisang attribution logic at iisang session grain lang ang source of truth
- **reconcilable**: bawat layer may sariling tamang gate at golden checks

---

## 2. Architectural principle

Ang pinakaimportanteng principle:

**Mature cohort muna ang backbone, hindi raw events.**

Ibig sabihin:

- ang downstream cohort na validated na natin ang magiging canonical base
- ang guided-surface layer ay enrichment lang muna
- ang channel taxonomy at overlay/operating framework ay idadagdag bilang controlled extension
- hindi natin hahayaang ang pinaka-risky join ang mag-define ng buong model

---

## 3. Canonical grain

Kailangan isang canonical session grain lang.

### Recommended rule

- **Canonical row grain:** one row per inquiry session
- **Canonical cohort date:** `inquiry_date`
- **Canonical attribution basis for conversion:** inquiry-based, not booking-based

### Key decision

Kailangan i-finalize kung alin ang canonical session key:

- `silver_session_id`
- or derived `user_id + inquiry_date`

### Recommendation

Sa architecture na ito, practical na **`silver_session_id` ang internal canonical session key** dahil ito ang mature key na ginagamit na ng existing cohort SQL.

Pero para aligned sa metric contract:

- keep `silver_session_id` as `session_id`
- expose `user_id`
- expose `inquiry_date`
- clearly document na ang session identity sa implementation ay `silver_session_id`, habang ang business cohorting remains inquiry-date based

Kung gusto talagang i-enforce ang `user_id + inquiry_date`, kailangan i-prove muna na one-to-one siya sa current `silver_session_id` population bago gawing canonical.

---

## 4. Target data model

### A. `session_fact`

Ito ang pinakaimportanteng table/view sa buong architecture.

**Purpose:**
Canonical one-row-per-session source for chatbot analytics.

**Built from:**

- mature downstream cohort assets
- existing first-reply layer
- existing follow-up coverage layer
- booking reconstruction logic
- later: guided/session enrichment and taxonomy enrichment

**Minimum fields:**

- `session_id`
- `silver_session_id` if kept separately for traceability
- `user_id`
- `inquiry_date`
- `report_week`
- `report_month`
- `owner_agent`
- `intent_level`
- `channel_role`
- `scope`
- `reply_status`
- `first_cs_reply_at`
- `minutes_to_first_reply`
- `minutes_to_reply_sla`
- `followup_count`
- `first_followup_at`
- `hours_to_first_followup`
- `booking_count`
- `first_booking_at`
- `days_from_inquiry_to_booking`
- `booking_owner_bucket`
- `is_mature_cohort`
- stage flags:
  - `inquiry_start`
  - `guided_engaged`
  - `intent_moderate_high`
  - `reached_pricing`
  - `reached_ip_stage`
  - `reached_schedule`
  - `captured_contact`
  - `booked`

**Why this matters:**

- dito iisa ang attribution logic
- dito iisa ang session grain
- dito manggagaling ang most funnel metrics

---

### B. `session_engagement_fact`

Ito ang guided-surface enrichment layer.

**Purpose:**
One-row-per-session guided engagement rollup na hiwalay sa core session backbone.

**Why separate muna:**

- ito ang pinaka-risky join area
- pwedeng magbago ang stitching rules
- ayaw nating masira ang canonical cohort truth kapag may upstream join issue

**Example fields:**

- `session_id`
- `surface_shown_location`
- `surface_clicked_location`
- `surface_shown_price`
- `surface_clicked_price`
- `surface_shown_promo`
- `surface_clicked_promo`
- `guided_depth`
- `price_tier`
- `promo_brand`
- `guided_engaged`

**Join rule:**

- dapat strictly 1:1 sa `session_fact`
- no session inflation allowed

---

### C. `booking_fact` or booking-side reconstruction view

Hindi lahat ng question ay inquiry-date question.

Kaya kailangan ng hiwalay na booking-side layer.

**Purpose:**
Support booking-date reporting, audit, and official booking reconciliation nang hindi sinisira ang inquiry-based conversion truth.

**Example use cases:**

- official booking totals by booking day
- audit ng order IDs
- canonical vs recovered bookings
- Calls exception handling

**Important rule:**

- booking-date reporting is a separate question from inquiry-date conversion

---

### D. Funnel facts / serving views

Ito ang thin derived views mula sa canonical layers.

Recommended set:

- `funnel_fact_master_conversion`
- `funnel_fact_guided_readiness`
- `funnel_fact_response_followup`
- `funnel_fact_channel_origin`
- `funnel_fact_cohort_maturation`
- `funnel_fact_intent_progression`

**Design rule:**

- huwag mag-duplicate ng core attribution logic sa bawat funnel
- derived aggregations lang dapat sila over canonical facts

---

### E. Dimensions

Reusable dimension layers para hindi paulit-ulit ang logic sa funnel views.

Recommended dimensions:

- `dim_agent`
- `dim_channel_taxonomy`
- `dim_date`
- `dim_product`
- `dim_location`
- `dim_intent_band`

---

## 5. Layer responsibilities

### Core truth layer

Includes:

- `session_fact`
- booking-side reconstruction source

Responsibilities:

- session grain
- attribution
- maturity
- reply/follow-up truth
- booking truth

### Enrichment layer

Includes:

- `session_engagement_fact`
- taxonomy enrichment helpers
- product/location enrichment

Responsibilities:

- attach context
- never redefine core attribution

### Serving layer

Includes:

- funnel facts
- Looker-facing views

Responsibilities:

- answer business questions
- aggregate safely
- preserve contract semantics

---

## 6. What comes from the mature cohort

Ang existing mature downstream cohort ang magiging starting truth para sa:

- session-level denominator
- moderate cohort membership
- first reply timing
- reply/no-reply status
- follow-up/no-follow-up status
- booking ownership split
- chatbot-only vs CS-assisted booking
- initial maturity handling

Ito ang dahilan kung bakit mali na i-gate ang Phase 1 gamit ang Taira overlay target.

Ang Phase 1 ay dapat mag-match sa existing downstream cohort truth, hindi sa cross-channel overlay taxonomy.

---

## 7. What remains greenfield

Ito ang mga totoong bagong build areas:

### A. Guided-surface stitching

Questions to solve:

- may stable `session_id` ba sa source?
- kung wala, ano ang stitching path?
- PSID + timestamp ba?
- paano i-ba-bucket sa tamang inquiry window?

### B. Cross-channel taxonomy

Need to model:

- `channel_role`
- `scope`
- additivity rules
- operating vs overlay structural separation

### C. Stage enrichment beyond mature downstream layer

Need to derive and stabilize:

- pricing reached
- IP reached
- schedule reached
- contact captured

---

## 8. Non-negotiable modeling rules

### Rule 1: one canonical session source

Huwag mag-maintain ng competing session truths sa iba-ibang funnel.

### Rule 2: inquiry-based conversion is the default truth

All conversion reporting should default to inquiry-date attribution.

### Rule 3: booking-date views are separate

Operational booking totals and inquiry conversion are different questions.

### Rule 4: `scope` must be structural

Hindi puwedeng analyst memory lang ang protection laban sa double count.

### Rule 5: maturity must be modeled

Hindi puwedeng manual warning lang na “fresh cohort yan.”

### Rule 6: enrichments cannot silently change row grain

Any join that inflates sessions fails the layer.

---

## 9. Correct reconciliation strategy

Bawat layer kailangan ang sariling tamang gate.

### Gate for core promotion layer

Match against the existing mature downstream cohort:

- session counts
- reply counts
- follow-up counts
- chatbot-total booking counts
- CS-assisted vs chatbot-only counts
- mature cohort counts

### Gate for guided enrichment layer

Match against:

- no session inflation
- 1:1 join integrity
- guided location lift benchmark

### Gate for channel-origin taxonomy layer

Match against:

- Taira overlay bookings = `37`
- operating funnel bookings = `171`
- operating funnel inquiries = `11,380`
- canonical + recovered = bookings for all non-Calls
- operating + overlay impossible to sum

### Gate for maturation layer

Match against:

- matured cohort rate > fresh snapshot rate for same cohort
- booking accumulation is non-decreasing over time

---

## 10. Recommended build order

### Step 1

Promote the mature downstream cohort into `session_fact`.

### Step 2

Add regression checks against:

- `v_looker_first_reply_detail`
- `v_looker_moderate_followup_detail`
- `v_looker_moderate_followup_coverage`

### Step 3

Build `session_engagement_fact` for guided-surface rollups.

### Step 4

Join engagement into the session spine only after 1:1 integrity is proven.

### Step 5

Build `funnel_fact_master_conversion`.

### Step 6

Build `funnel_fact_response_followup` as a formalized serving layer over the mature backbone.

### Step 7

Build `funnel_fact_channel_origin` for operating vs overlay logic.

### Step 8

Build cohort maturation and intent progression layers.

### Step 9

Harden:

- freshness checks
- partition-safe rebuilds
- schema-level guardrails
- Looker documentation

---

## 11. Looker serving strategy

Sa Looker, iwasan ang isang mega-view na lahat ng tanong doon sasagutin.

Recommended serving pattern:

- isang canonical explore over `session_fact`
- optional join to `session_engagement_fact`
- separate explores or derived views for:
  - master conversion
  - response/follow-up
  - channel-origin
  - cohort maturation

Important:

- `scope` should default safely
- operating and overlay measures should not be casually blendable
- inquiry-date and booking-date reporting should be visibly distinct

---

## 12. Risks and controls

### Risk: guided-surface join causes duplication

Control:

- isolate in `session_engagement_fact`
- fail the build if row count changes after join

### Risk: mixed attribution logic across funnels

Control:

- centralize attribution in `session_fact`

### Risk: denominator disputes

Control:

- make `scope`, `date_basis`, and `intent_level` explicit everywhere

### Risk: fresh cohorts misread as underperformance

Control:

- model `is_mature_cohort`
- create dedicated cohort maturation views

### Risk: overlay double count

Control:

- structural separation of operating vs overlay

---

## 13. Bottom line

Ang tamang architecture ay:

- **mature cohort as backbone**
- **canonical session fact as truth**
- **guided engagement as separate enrichment**
- **funnel views as thin derived serving layers**
- **taxonomy and overlay logic as controlled extension**

Ito ang pinaka-practical na path para maging stable, scalable, at accurate ang analytics layer nang hindi nire-rebuild ang mga parte na mature na.
