# Gulong Chatbot Analytics — Correct Phase Gating

This file corrects the phase gates in `gulong_chatbot_analytics_execution_plan.md` so each phase reconciles only to outputs that phase can actually produce.

---

## Why this exists

The current execution plan now correctly acknowledges that the downstream `moderate -> first reply -> follow-up -> booking` slice is already mature.

That changes the gating logic:

- Phase 1 should reconcile to the existing downstream cohort layer.
- Guided-surface gates should stay with guided-surface work.
- Overlay / operating-funnel gates should stay with channel-origin work.
- Taira overlay target `G1 = 37` should **not** block downstream cohort promotion.

---

## Core rule

Each gate must match the scope of the phase:

- If a phase promotes an existing downstream cohort, it should reconcile to the existing downstream cohort.
- If a phase introduces guided-surface enrichment, it should reconcile to guided-surface lift and join integrity.
- If a phase introduces operating-vs-overlay taxonomy, it should reconcile to operating and overlay golden numbers.

Anything else creates false failures and sends debugging to the wrong layer.

---

## Correct gating by phase

### Phase 0 — Frame & de-risk

Purpose:
Lock the contract, confirm golden numbers, and resolve the guided-surface join path.

Correct gate:

- Part A metric contract is signed off
- Part B golden targets are locked
- guided-surface join path is chosen

Notes:

- No production schema should be written yet.

---

### Phase 1 — Promote the existing downstream cohort into `v_session_fact`

Purpose:
Promote the mature `moderate -> first reply -> follow-up -> booking` layer into a contract-aligned `v_session_fact`.

Correct gate:

- `v_session_fact` reproduces the existing downstream cohort exactly for the promoted population
- no drift in session count versus `v_looker_first_reply_detail`
- no drift in replied vs no-reply counts
- no drift in with-followup vs no-followup counts
- no drift in chatbot-total booked session counts
- no drift in CS-assisted vs chatbot-only booking counts
- no drift in mature cohort counts

Recommended regression sources:

- `v_looker_first_reply_detail`
- `v_looker_moderate_followup_detail`
- `v_looker_moderate_followup_coverage`

What should **not** be in Gate 1:

- `G1` Taira overlay bookings = 37
- `G2` operating funnel bookings = 171
- `G3` operating funnel inquiries = 11,380
- `G6` operating + overlay impossible to sum

Reason:

- Those are channel-origin / taxonomy validations, not downstream Chatbot/JCo cohort validations.

---

### Phase 2 — Attach upstream engagement

Purpose:
Join guided-surface engagement into the downstream session spine.

Correct gate:

- session count is unchanged after the join
- enriched model remains 1:1 at session grain
- no duplicated sessions introduced by guided-surface stitching
- `G5` guided location lift reproduces: clicked vs shown-no-click remains approximately `60.19% vs 11.18%`

Reason:

- This phase proves the upstream join path and preserves the shown/clicked split.

---

### Phase 3 — First vertical slice: master conversion funnel

Purpose:
Prove that the unified session spine can support an end-to-end funnel under the Part A contract.

Correct gate:

- funnel stages render correctly from `v_session_fact`
- stage progression is monotonic and contract-consistent
- booking attribution in the funnel matches the inquiry-based contract
- non-negotiable filters are wired correctly: `scope`, `date_basis`, `intent_level`

Conditional note:

- If Phase 3 is still scoped only to the promoted chatbot cohort, do **not** require `G2` and `G3` yet.
- If Phase 3 is already truly cross-channel and operating-funnel complete, then it may additionally require:
  - `G2` operating funnel bookings = `171`
  - `G3` operating funnel inquiries = `11,380`
  - `G6` operating + overlay impossible to sum

Reason:

- `G2/G3/G6` only belong here if the model is already operating-funnel complete.

---

### Phase 4 — Replicate the pattern by funnel

Purpose:
Finish the remaining funnels, with each funnel gated by the numbers its own scope can produce.

#### Funnel 2 — Guided-surface readiness

Correct gate:

- `G5` guided location lift reproduces
- shown vs clicked split remains intact

#### Funnel 3 — Response & follow-up

Correct gate:

- reproduces the existing response/follow-up ops dashboard
- queue-depth correlation check remains approximately `0.596` if still part of the accepted benchmark

Important:

- This is a formalize-and-reconcile funnel, not a net-new build.

#### Funnel 4 — Channel-origin operating vs overlay

Correct gate:

- `G1` Taira overlay bookings = `37`
- `G2` operating funnel bookings = `171`
- `G3` operating funnel inquiries = `11,380`
- `G4` canonical + recovered = bookings for all non-Calls rows
- `G6` operating and overlay cannot be summed into one measure

Important:

- This is the correct home for the Taira overlay gate.
- This is the real additivity / taxonomy proof phase.

#### Funnel 5 — Cohort maturation

Correct gate:

- a matured historical cohort converts better than its own fresh snapshot
- booking accumulation for a cohort is non-decreasing over time
- `is_mature_cohort` classification behaves as expected

Important:

- The existing downstream layer already provides a foothold for this via `is_mature_cohort`.

#### Funnel 6 — Intent progression turn-by-turn

Correct gate:

- moderate/high share rises with guided depth
- benchmark sanity remains in the expected direction: `12.9% -> 25.4% -> 61.5%`

---

## The key correction

The biggest gating fix is simple:

- Move `G1` out of Phase 1.
- Put `G1` under Funnel 4: channel-origin operating vs overlay.

Phase 1 is a downstream cohort promotion gate.
Funnel 4 is the overlay/operating taxonomy gate.

That separation matches the actual SQL maturity already present in the repo.

---

## Suggested replacement gate text

If you want a short replacement for the execution plan:

### Replacement Gate 1

`v_session_fact` reproduces the existing downstream moderate/reply/follow-up booking layer exactly for the promoted population. Any drift in session counts, reply counts, follow-up counts, booking ownership counts, or mature cohort counts is a promotion bug and must be fixed before Phase 2.

### Replacement Gate for Funnel 4

The channel-origin model reconciles to the operating and overlay golden numbers: Taira overlay bookings = `37`, operating funnel bookings = `171`, operating funnel inquiries = `11,380`, `canonical + recovered = bookings` for all non-Calls rows, and operating plus overlay cannot be blended into one additive measure.

---

## Bottom line

Use downstream cohort parity to gate downstream cohort promotion.
Use guided-surface lift to gate guided-surface enrichment.
Use operating/overlay golden numbers to gate channel-origin taxonomy.

That is the correct reconciliation structure.
