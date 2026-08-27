# Gulong Chatbot Analytics — Metric Contract & Executable Build Plan

*A GA4-for-chatbot analytics layer. This is the working blueprint: definitions everyone agrees on (Part A), the numbers we test against (Part B), and a phased build where each phase has a reconciliation gate that must pass before the next starts (Part C).*

Project: `gulong-chatbot-459723` · Target dataset: `gulong_reporting`
Companion: `gulong_chatbot_analytics_build_manual.md` (detailed per-section SQL)

---

## How to use this doc

- **Part A is law.** No view ships with a definition that contradicts it. If a definition needs to change, change it here first, then rebuild — never the other way around.
- **Every phase has a gate.** A gate is a query that must return the golden number in Part B. If it doesn't reconcile, you do not proceed — you fix the current phase.
- Work **one vertical slice at a time**, not layer by layer. One funnel fully done beats four funnels at 80%.

---

## Baseline — what already exists (not greenfield)

The downstream **moderate → first reply → follow-up → booking** slice is already a mature foundation. The plan below promotes it, it does not rebuild it. Confirmed assets:

| Asset | What it already is | Ref |
|---|---|---|
| `v_looker_first_reply_detail` | Session-level cohort base: `silver_session_id`, `manychat_id`, `inquiry_date`, `first_cs_reply_at`, `reply_status`, business-hours-adjusted SLA timing, booking linkage back to the inquiry session or nearest eligible prior moderate session. | `v_looker_first_reply_detail(2).sql:391`, `:596` |
| `v_looker_moderate_followup_detail` | True event-level follow-up attribution off the replied moderate cohort: follow-up windows, response windows, booking attribution tied to follow-up timing. | `moderate_followup_deploy.sql:115` |
| `v_looker_moderate_followup_coverage` | One-row-per-session coverage model: denominator, no-reply/replied split, with-followup/no-followup split, chatbot-only vs CS-assisted booking ownership, and an `is_mature_cohort` flag. | `moderate_followup_deploy.sql:351`, `:588` |

**Consequence for the plan:**

- **Phase 1** is *promotion/consolidation*, not new build — normalize and promote the existing first-reply + follow-up cohort logic into `v_session_fact`.
- **Funnel 3 (Response & follow-up)** is *substantially implemented* — the work is *formalize + reconcile*, not build.
- **Funnel 5 (Cohort maturation)** already has a foothold via `is_mature_cohort`; only the stricter fresh-snapshot-vs-matured-snapshot reconciliation query remains.
- **The genuinely open greenfield** is upstream guided-surface stitching + the cross-channel `channel_role`/`scope` operating-vs-overlay framework. That is where new build effort actually goes.

---

## Part A — Metric Contract

The single source of truth for what every number means. When the board asks "is it 1.07% or 3.76%?", the answer is here.

### A1. Session grain

```
session_id  = user_id (PSID / contact)  +  inquiry_date
user_id     = the person, persistent across weeks
cohort_key  = inquiry_date
```

- One inquiry episode per day = one session.
- Same customer, next week = a **new** session on the new date.
- One row per session in `session_fact`. This is the GA4 "session" equivalent.

### A2. Booking attribution (non-negotiable)

- Bookings are attributed to the **original inquiry owner** and the **original inquiry_date** — never the booking creator or booking date.
- **No fixed conversion window.** Any booking traceable to the inquiry counts, whenever it lands. A cohort's booking count keeps rising as it matures.
- Order creator is retained only as a *closing-workload* view, never for conversion.
- **Consequence:** the most recent cohort always looks worse than it is. Never read a fresh cohort's conversion as a decline until it matures (see Funnel 5).

### A3. Stage definitions (deterministic)

Each stage is a boolean derived from events. All deterministic except `intent_level` (classifier-fed).

| Stage | Definition (derive from) | Source |
|---|---|---|
| `inquiry_start` | first inbound message of the session | `messages` |
| `guided_engaged` | any `surface_clicked` in session | guided-surface logs |
| `intent_moderate_high` | classifier label in (moderate, high) | `moderate_intent_sessions` (classifier) |
| `reached_pricing` | pricing/quotation stage reached | semantic tables / field capture |
| `reached_ip_stage` | installation-partner stage reached | semantic tables |
| `reached_schedule` | scheduling stage reached | semantic tables |
| `captured_contact` | contact field captured | `field_captured` |
| `booked` | traceable booking exists | `orders_booked` |

Rule: a stage is TRUE only if all prior *hard* stages are consistent. Do not let `booked` be TRUE with `inquiry_start` FALSE — flag as a data bug.

### A4. Channel taxonomy & the additivity rule

Two dimensions from the CS_SALES_FUNNEL taxonomy. **This is the guardrail that prevents double-counting.**

```
channel_role = funnel      -- Pure CS Only | Mixed | Mixed with Chatbot |
                              Chatbot Handoff | Chatbot Handoff + Sarah Closing |
                              Sunday Experiment Handoffs | Calls
scope        = view_scope   -- 'operating' | 'overlay'
```

- **`operating`** buckets are mutually exclusive and **additive** — you may sum them.
- **`overlay`** (Taira handoff-origin) **overlaps** operating funnels and is **never summed** into them. A Taira handoff that a CS agent closes appears in both the overlay (as origin) and the operating funnel (as close). Adding them double-counts.
- **Enforcement:** the two scopes must be structurally impossible to blend in Looker (separate the measure, or gate with a scope filter that defaults to one). Do not rely on the analyst remembering.

### A5. Metric definitions

- `conversion_rate` = bookings / inquiries (raw; one inquiry may yield multiple bookings).
- `unique_inquiry_conversion_rate` = converted_inquiries / inquiries (deduped). **This is the default reporting rate** unless raw is explicitly requested.
- `bookings` = `canonical_bookings` + `recovered_bookings`. Reconciles everywhere **except Calls** (Calls are booking-date, no inquiry link, outside the recovery framework).
- **Business-minute SLA:** response time counted only within 09:00–18:00 Asia/Manila. After-hours handoff → clock starts 09:00 next business day. Use `DATETIME_DIFF`, never `TIMESTAMP_DIFF`.
- **Denominator honesty:** the same 37 Taira bookings give 3.76% over *handoff-origin* inquiries and ~1.07% over *all-Taira* inquiries. Both are valid; always label which denominator a rate uses.

### A6. Non-negotiable filters

Three filters change the *meaning* of a number, not just the slice. They must always be explicit:

1. **`scope`** (operating vs overlay) — additivity.
2. **`date_basis`** (inquiry date vs booking date) — a different question, not a different cut.
3. **`intent_level`** — the whole M/H story.

All others (agent, brand, price tier, guided depth, region, business-hours) are segmentation — nice, but they don't redefine the metric.

---

## Part B — Golden reconciliation targets (test oracle)

These verified numbers are the gates. A phase passes when its query returns these.

| ID | Target | Value | Guards against |
|---|---|---|---|
| G1 | Taira **overlay** bookings, July | **37** (35 canonical + 2 recovered) | matches DT Update Taira Jul 1-28 = 37 |
| G2 | **Operating funnel** bookings, July | **171** | channel taxonomy sum |
| G3 | Operating funnel inquiries, July | **11,380** | denominator integrity |
| G4 | `canonical + recovered = bookings` | true for **all non-Calls** rows | recovery logic |
| G5 | Guided **location** lift (clicked vs shown-no-click M/H) | **~60.19% vs ~11.18%** | shown/clicked split intact |
| G6 | operating + overlay summed into one measure | **must be impossible** | double-count |

---

## Part C — Phased build plan (with gates)

### Phase 0 — Frame & de-risk *(no production code)*

**Goal:** remove ambiguity before building.

- [ ] Ratify Part A metric contract with stakeholders (async sign-off is fine).
- [ ] Lock Part B golden targets.
- [ ] **Resolve the one blocking unknown — guided-surface join key.** Run the probe:

```sql
-- Do guided-surface logs already carry a session key,
-- or only PSID + timestamp?
SELECT column_name, data_type
FROM `gulong-chatbot-459723.gulong_reporting.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'guided_surface_events'   -- confirm actual table name
ORDER BY ordinal_position;
```

- [ ] Decide the join path based on the result:
  - **Has `session_id` / user + date** → direct `USING (session_id)`. Proceed clean.
  - **Only PSID + timestamp** → add a stitching step first: resolve PSID→user_id, bucket each event into the correct `inquiry_date` window, then join.

**Gate 0:** contract signed, golden targets locked, join path chosen. *No schema written until this passes.*

---

### Phase 1 — Promote the existing downstream cohort into `v_session_fact`

**Goal:** *not a build* — normalize and promote the existing first-reply + follow-up cohort logic (see Baseline) into a single `v_session_fact`. The spine already exists; this consolidates it under the Part A contract.

- [ ] Map existing columns to the contract: `silver_session_id`→`session_id`, `manychat_id`→`user_id`, `inquiry_date`, `first_cs_reply_at`, `reply_status`, SLA timing, plus follow-up windows and booking linkage from the follow-up detail/coverage views.
- [ ] Promote `v_looker_moderate_followup_coverage`'s one-row-per-session shape as the base grain (it already carries denominator, reply/no-reply, with/without-followup, booking ownership, `is_mature_cohort`).
- [ ] Add the contract fields not yet present: `channel_role`, `scope`, and stage flags (A3) that aren't already derived.
- [ ] Confirm booking attribution already matches A2 (original owner, original date, no window) — reconcile, don't re-implement.

**Gate 1:** `v_session_fact` reproduces the existing first-reply/follow-up dashboard numbers exactly (regression check, not new truth), and G1 (Taira overlay = 37) reconciles. Any drift from the existing views is a promotion bug — fix before Phase 2.

---

### Phase 2 — Attach upstream engagement

**Goal:** complete the spine — upstream guided engagement joined to downstream outcomes.

- [ ] Build `guided_surface_rollup` (one row per session: clicked_location, clicked_price, clicked_promo, price_tier, promo_brand) using the Phase 0 join path.
- [ ] Left-join it into `v_session_fact`.
- [ ] Validate no session-count inflation after the join (join must be 1:1 on session).

**Gate 2:** session count unchanged after the join, and G5 (location lift 60% vs 11%) reproduces from the enriched view. The `surface_shown` vs `surface_clicked` split must survive — that split *is* the lift.

---

### Phase 3 — First vertical slice: the master conversion funnel

**Goal:** prove the whole pattern end-to-end on **one** funnel before replicating.

- [ ] Build `v_funnel_master`: inquiry → guided → M/H → pricing → IP → schedule → contact → booking, as `GROUP BY` over `v_session_fact`.
- [ ] Build the Looker tile (funnel viz + the A6 non-negotiable filters wired as controls).
- [ ] Enforce G6: operating and overlay cannot be summed in this tile.
- [ ] Write the reconciliation test as a saved query.

**Gate 3:** master funnel renders in Looker with working scope/date_basis/intent filters; G2, G3, G6 all pass. This is the pattern proof — after this, the rest is replication.

---

### Phase 4 — Replicate the pattern (remaining five funnels)

**Goal:** one funnel per sprint, each a slice of the same spine, each with its own gate. Detailed stages in Part D. Note the mix: Funnel 3 is *formalize + reconcile* (already built), Funnel 5 needs *one reconciliation query* (foothold exists), and Funnel 4 is the real *new build*. Funnels 2 and 6 depend on the upstream guided-surface work.

- [ ] Funnel 2 — Guided-surface readiness *(gate: G5)*
- [ ] Funnel 3 — Response & follow-up — **formalize + reconcile, not build** (already substantially implemented in the follow-up detail/coverage views) *(gate: reproduces ops dashboard + queue-depth correlation ≈ 0.596)*
- [ ] Funnel 4 — Channel-origin operating vs overlay — **genuine new build** *(gate: G2, G4, G6)*
- [ ] Funnel 5 — Cohort maturation — foothold exists via `is_mature_cohort`; **add the formal fresh-vs-matured reconciliation query** *(gate: a matured old cohort's rate exceeds its fresh-snapshot rate)*
- [ ] Funnel 6 — Intent progression turn-by-turn *(gate: sanity — M/H share rises with guided depth, per DT Update 12.9%→25.4%→61.5%)*

**Gate 4:** each funnel passes its own reconciliation before the next starts. No batching.

---

### Phase 5 — Harden & hand off

**Goal:** the layer runs without you.

- [ ] Freshness monitor (flag stale partitions / late-arriving bookings).
- [ ] Idempotent partitioned rebuild; partition filters enforced as cost guardrails (`messages` requires `datetime` filter).
- [ ] Metric contract checked into the repo; data dictionary published in Looker.
- [ ] Additivity guardrail (G6) enforced at schema level, not by convention.
- [ ] DDL run manually in BigQuery Console (MCP is read-only) and version-controlled.

**Definition of done:** the layer is self-serve, self-reconciling, and definitions are no longer argued. It runs when you're not looking.

---

## Part D — The six funnels (stages + purpose)

1. **Master conversion** — inquiry → guided → M/H → pricing → IP → schedule → contact → booking. *Where the biggest leak is* (known: contact capture ~5-6%).
2. **Guided-surface readiness** — per surface: shown → clicked → M/H → field → booking, clicked vs shown-no-click. *Which surface actually drives readiness* (location strongest).
3. **Response & follow-up** — handoff → first reply → follow-up → booking, with timing. *Response gaps, follow-up execution, queue-depth effect.*
4. **Channel-origin** — parallel operating vs overlay tracks. *True channel contribution without double-count.*
5. **Cohort maturation** — one cohort tracked as bookings accrue. *Separates "low conversion" from "immature cohort."*
6. **Intent progression** — turn-by-turn intent trajectory. *The earliest leading indicator; not available in GA4.*

Cross-cutting filters (all funnels): **segment** — agent, channel_role, `scope`*; **readiness** — `intent_level`*, guided depth, surface engaged; **product** — brand, price tier; **time/attribution** — `date_basis`*, grain, business-hours; **place** — location captured, region. *(\* = non-negotiable, per A6.)*

---

## Part E — Explicitly NOT building yet (scope guardrails)

- **Event stream / path analysis** (sequence of surfaces) — want-not-need. Phase 6+, only if path questions actually come up. Do not let it pull the schedule.
- Any new instrumentation — everything above uses existing sources; this is consolidation, not collection.
- Real-time / streaming — batch grains (daily/weekly/monthly) are sufficient.

Senior discipline enforced by this plan: reconcile continuously (not at the end), vertical slice over horizontal layers, and resist the tempting-but-unneeded event stream until a real question demands it.

---

## Appendix — technical constraints

| Constraint | Implication |
|---|---|
| BigQuery MCP read-only | DDL runs manually in Console, version-controlled. |
| `manychat_data.messages` needs `datetime` partition filter | else full-scan / error; also a cost guardrail. |
| `DATETIME_DIFF` not `TIMESTAMP_DIFF` | Manila-local datetime fields. |
| Business hours 09:00–18:00 Asia/Manila | after-hours SLA clock resets next business day. |
| Weekly definitions differ across sources | DT Update = Wed–Tue; CS_SALES_FUNNEL = Mon–Sun. Pick one forward; weekly numbers won't cross-reconcile until you do. |
| Looker custom queries can't use `@DS_START_DATE` natively | handle in the view or parameterize. |
| Most recent cohort is immature | never read fresh conversion as decline (A2). |