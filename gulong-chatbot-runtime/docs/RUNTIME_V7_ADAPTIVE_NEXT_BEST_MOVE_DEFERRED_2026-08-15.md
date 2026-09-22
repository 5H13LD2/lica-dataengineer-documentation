# Runtime V7 Adaptive Next-Best-Move Deferred Work

Status: rejected candidate archived as design evidence; not deployed.

2026-08-18 update: post-product guided location eligibility resumed as a
bounded capability-profile change. It reuses the existing main model and
renderer, adds no planner call, and does not revive the rejected broad
next-best-move or follow-up architecture. The remaining deferred areas below
are unchanged.

## Proven and retained now

The rejected `f38fbe5` / `9cb2bee` candidate demonstrated useful adaptive
location timing, but its broad runtime integration was not safe for customers.
The location-only hotfix retains the reusable part: a model-owned, optional
guided location move with deterministic delivery/location and one-surface
guards. The stable follow-up endpoint and predictive read-only schedule behavior
remain unchanged.

Do not cherry-pick or restore either rejected commit wholesale. Resume from the
accepted post-hotfix `product`/`main` tree and reintroduce one bounded ownership
area at a time.

## Deferred implementation areas

1. Planning contract
   - Evaluate whether a dedicated trained/planning model materially improves
     full-conversation planning over the main model without a rigid funnel.
   - Keep model ownership of connective prose and CTA choice; deterministic
     code owns only hard facts, schemas, side effects, and safety invariants.

2. Follow-up continuity
   - Unify live and `/gulong/v7/followup` context assembly so proactive replies
     remain attached to the latest customer goal, visible surfaces, product,
     location, and prior unanswered question.
   - Preserve normal-turn model-call cost and existing send admission,
     allowlist, canary, idempotency, and opt-out controls.

3. Predictive service progression
   - Generalize conservative proactive schedule previews after a concrete
     serviceable area is known. A preview is reversible and may reduce
     hesitation; it must never imply acceptance, reservation, or booking.
   - Avoid customer-request-only gating, but suppress repeated, declined,
     contradictory, or high-commitment moves.

4. Lifecycle and response composition
   - Repair fresh/resumed seed topology, turn-state authority, answer priority,
     response-unit/move consistency, stacked CTA prevention, and transient
     failure handling before any broad planner promotion.
   - Avoid deterministic prose repair that detaches a response from the prior
     turn or rewrites natural Filipino CS language.

5. Evaluation and measurement
   - Use Sol High and Terra Extra High as adaptive customers/evaluators, not a
     static predefined Gemini conversation matrix. Include English, Taglish,
     Filipino, hesitation, correction, interruption/resumption, known/unknown
     product, delivery, location, guided clicks, and follow-up ingress.
   - Use deterministic tests for exact buttons, payloads, facts, guards,
     idempotency, delivery, and one-interactive-layer behavior.
   - Measure eligible -> rendered -> delivered -> clicked -> field completion ->
     Moderate/High -> booking, plus abandonment, latency, error rate, and cost.
     Offline surface appearance and shown/clicked associations are not causal
     M/H proof; use eligible-traffic randomized evidence for that claim.

## Known candidate rejection signals

- Follow-up move and authored text could disagree.
- Lifecycle state and adaptive seed topology were inconsistent.
- Some responses deferred an owed answer or stacked CTAs.
- At least one customer path returned HTTP 500.
- The candidate changed too many ownership boundaries at once, making repair
  and causal evaluation expensive.

Location timing itself passed the reviewed adaptive cases; retain it as a
bounded capability, not as evidence that the full planner was acceptable.

## Fresh-session acceptance and stop conditions

- Two complete fresh adaptive batches with independent Sol/Terra role reversal.
- Zero unsupported commercial, policy, serviceability, schedule, reservation,
  or booking claims.
- Zero forbidden or repeated guided surfaces and zero stacked interactive
  decision layers.
- At least 95% direct-answer priority and 100% context-connected guided-click
  and follow-up responses.
- No added dedicated model call unless a paired cost/quality test proves the
  benefit; normal-turn P95 latency and model cost must remain within the agreed
  release tolerance.
- Stop and repair the owning boundary for any HTTP 5xx, detached follow-up,
  unanswered customer question, move/text mismatch, state loss, or side-effect
  authorization error. Diagnose general runtime ownership rather than patching
  one SKU, location, phrase, or scripted scenario.
- Promotion still requires controlled staging, exact SHA/image provenance,
  rollback preservation, monitoring, and randomized online evidence before a
  causal M/H or conversion claim.

## Cost-optimized orchestration

- Sol owns architecture, acceptance, integration, release decisions, and final
  evaluation.
- Terra handles bounded judgment-heavy implementation and independent customer
  review.
- Luna handles mechanical matrices, fixture generation, test execution, output
  normalization, and regression comparison only.
- Use one writing agent per code area, compact two-to-three-turn adaptive cases,
  and deterministic coverage for combinatorial variants. Escalate only repeated
  release-blocking failures; do not spend adaptive-model budget on mechanical
  permutations.
