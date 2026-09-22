# Runtime V7 Multi-Turn Response Evaluation — 2026-08-06

> Superseded serving boundary, 2026-08-08: this document preserves the earlier
> incremental evidence. The active branch has since removed `lead_cta_focus`,
> the separate product/location/payment semantic decision gates, and normal-
> path semantic CTA/response rewriting. Current adaptive evidence and release
> limits are in
> `RUNTIME_V7_CHOICE_AND_SIGNAL_RETENTION_EVALUATION_2026-08-08.md`.

## Decision

The first safe increment is ready for review, but not yet for a production
quality claim. It moves ordinary customer-facing composition toward the model
while preserving deterministic authority for exact commercial facts, guided
surfaces, tracked actions, and submission safety.

The strongest verified improvements are:

- a mid-thread greeting is recomposed by the model instead of deleted by a
  sentence-level guard;
- a valid model-composed promo-action reply bypasses the legacy deterministic
  CTA rewrite;
- the first applicable Tire Protection Plan pricelist can reuse the reviewed
  Double Warranty catalog card instead of appending the long warranty and
  installation paragraph;
- the supporting warranty card remains part of the product-selection turn and
  does not become a competing promo decision;
- question-only, conditional, historical, and rejected signals do not satisfy
  lead or order-readiness fields.

## Human-agent reference

A privacy-safe July 20–August 5 human-agent sample contains 30,702 deduplicated
agent messages across 7,216 conversations. The median message was 71
characters, 71.8% were at most 120 characters, 40.8% contained a question, and
58.3% contained `po` or `opo`.

The useful style pattern is not a script. It is usually a short Taglish
acknowledgement or direct answer, enough relevant substance to help, and one
locally useful question. Longer forms and repeated spiels are stage-specific.
Human-agent wording is style evidence only; it is not authority for price,
promo, payment, serviceability, stock, or booking facts.

Evidence: `tmp/gulong_human_agent_reply_sample_2026-07-20_to_2026-08-05.md`.

## Evaluation matrix

The human-response pack now has 25 varied scenarios. It covers:

- direct price, size-only discovery, vehicle fitment, sidewall correction, and
  product comparison;
- first-turn assistance, physical-shop/location questions, reactivation, and
  complaint/handoff;
- product, promo, service-area, schedule, payment, order-summary, fulfillment,
  and guided-choice transitions;
- free-text product choices, preference changes, exclusions, FAQ interruption,
  historical context, and late-stage correction.

Each case separates hard authority checks from human review. A structurally
valid response is not automatically a human-quality pass. Likewise, harness
output is not proof of delivery or conversion impact.

## Live multi-turn result

Scenario: generic assistance → vehicle/budget context → confirmed sidewall
size.

### Turn 1

Customer:

> Hello, may makaka-assist ba?

Assistant:

> Hello! Yes, ako po ang Gulong.PH tire sales assistant niyo. Paano po ako
> makakatulong sa inyo today?

Assessment: acceptable and safe, although “tire sales assistant” is slightly
more role-explicit than the most natural human-agent phrasing. It does not claim
that a human teammate has been assigned.

### Turn 2

Customer:

> Need ko tires para sa 2019 Toyota Vios, daily drive lang. Around 12k sana for
> four.

Assistant:

> Para makahanap tayo ng best tires for your 2019 Toyota Vios na pasok sa 12k
> budget mo for four, ano po ang tire size na gamit niyo? Usually makikita niyo
> po 'yan sa sidewall ng gulong niyo or sa sticker sa loob ng driver's side
> door.

Assessment: good. It continues without another welcome, uses the vehicle,
budget, quantity, and use context, does not convert them into fitment facts, and
asks one useful next question. The repair was another model composition pass;
the runtime did not delete the greeting or insert a fixed CTA.

### Turn 3

The confirmed `185/60R15` turn produced grounded product cards and a product
choice CTA, but the run predated the catalog-backed warranty integration and
therefore still appended the long warranty/inclusions paragraph. That version
is not acceptable as the target customer experience. It is retained as
baseline evidence, not as an approved transcript.

Artifact:
`tmp/runtime_v7_multiturn_acceptance_recheck/runtime_v7_live_pack_20260807_000834/`.

## Live catalog-backed product result

Scenario: a customer asks for Deestone or Toyo `215/65R16` options and prices.

The live read-only path successfully ran:

1. current product search;
2. reviewed promo-catalog search scoped to the Double Warranty;
3. reviewed promo-gallery presentation;
4. structured final model composition;
5. staging-mode channel rendering.

The visible staging-mode sequence was:

1. a personalized first-turn lead-in that answers the requested-brand result;
2. exact renderer-owned Toyo price/product details;
3. a brief model-written Double Warranty transition;
4. the reviewed `THE GULONG DOUBLE WARRANTY` card and catalog image;
5. a product-selection CTA.

This deliberately omits the old generic installation-inclusions paragraph from
the same pricelist turn. It does not discard product authority: each product
card still owns its exact manufacturer-warranty and Tire Protection Plan fields.
Installation inclusions can be explained later when installation is the active
stage; the catalog image is not treated as evidence for those service facts.

The latest live model asked whether the customer wanted a Toyo product checked
or more warranty details. That creates two next questions and is weaker than the
target. The composer guidance now explicitly treats this warranty card as
supporting context and keeps the one next question on product selection. That
prompt-only refinement was locally verified and was not followed by another
paid rerun.

Artifact:
`tmp/runtime_v7_promo_catalog_acceptance_fixed/runtime_v7_live_pack_20260807_001947/`.

The run used four model calls and four tools, took 20.9 seconds in model latency
plus 10.2 seconds in tool latency, used 61,701 total tokens with a 27.2% cache
hit rate, and was estimated at USD 0.0203 under the runner's pricing profile.
Those values are one-case diagnostic measurements, not expected production
averages.

An earlier three-turn catalog-enabled run stopped because the configured
12-call scenario cap blocked the attempted thirteenth model call. The Gemini
credential was available and later completed the bounded live catalog run; the
failure was not caused by a missing `.env` credential.

## Authority and composition boundary

Model-owned when valid:

- greeting or acknowledgement;
- direct answer phrasing;
- transitions before and after deterministic surfaces;
- relevant explanation and technical context supported by evidence;
- one reasoned next step for the active decision.

Runtime-owned:

- exact prices, totals, discounts, product details, and current promo facts;
- guided product, promo, location, schedule, payment, order, and other tracked
  surfaces;
- tool and evidence-ref authorization;
- choice-token validation, deduplication, state transitions, delivery
  integrity, action idempotency, and submission gates;
- deterministic fallback when model composition is missing or invalid.

The runtime still has legacy sentence deletion, response replacement, and CTA
repair paths. This increment bypasses the promo CTA rewrite for a valid
model-composed turn and routes the observed mid-thread greeting failure back to
the model. It does not remove all legacy fallbacks at once.

## Context and memory decision

Do not replace Background Signals, authoritative observations, order readiness,
FAQ/catalog retrieval, or brand retrieval with Mem0.

The only plausible Mem0 role is advisory cross-session recall of non-commercial
preferences or open conversational goals. Before that experiment:

- ablate model-generated Active Working Memory on low-value/no-state turns;
- retire duplicate `memory_note` only after compatibility/read telemetry;
- remove duplicate readiness projections where one authoritative projection is
  sufficient;
- measure whether any missing cross-session continuity remains after recent
  turns, durable typed signals, observations, and full order readiness.

If Mem0 is still useful, first run shadow retrieval with no prompt injection and
no effect on tools, facts, readiness, actions, or customer output. It must not
store or retrieve commercial truth as authority.

## Verification completed

- 111 channel-renderer and promo-catalog tests passed.
- 15 targeted composition, identity, signal, handoff, guided-choice, payment,
  schedule, and state-transition tests passed after one stale expectation was
  updated for the new business-identity evidence ref.
- 16 focused new/changed human-composition checks passed in the targeted
  selection.
- The 25-scenario pack lists and parses successfully.
- `git diff --check` passed; the repository emitted only its existing
  LF-to-CRLF checkout warnings.

The full repository suite was intentionally not rerun. The next full-suite gate
belongs immediately before a release candidate is merged, after the remaining
selected multi-turn cases and endpoint delivery checks are approved.

## Remaining acceptance work

- Human-review the rendered outputs for the dense product → selection →
  location → schedule path, promo → product transition, payment-before-product
  path, correction/reactivation, FAQ interruption/resume, and complaint/handoff.
- Run guided-click paths with locally generated valid tokens and delivered
  surface state; the paid live runner accepts text turns and cannot prove a real
  button/postback transition.
- Run a controlled endpoint delivery check for the promo gallery. The current
  evidence is staging-mode channel rendering, not ManyChat delivery.
- Measure no-mutation rate and sampled before/after response-unit diffs before
  bypassing additional deterministic guards.
- Do not claim conversion or customer-response lift without a controlled
  holdout and defined attribution window.

## Pre-release gate update (2026-08-07)

This checkpoint is not approved for merge yet. The selected semantic reviews
found useful product, FAQ-resume, schedule, and handoff behavior, but also found
customer-visible quality and efficiency failures that should be resolved before
the repository-wide suite is run.

### Dense multi-turn reviews

- `hr17` product choice to location and schedule exceeded the bounded per-turn
  model-call ceiling twice on turn 3. It was not rerun with a larger ceiling.
- `hr20` promo to product reached the six-call ceiling before its structured
  promo audit could complete. One bounded rerun then exceeded the test process's
  two-minute envelope and produced no complete review artifact. The runner now
  identifies semantic FAQ, promo, pricing, and progression calls separately
  instead of labeling every structured call as `final_composer`.
- `hr21` payment before product completed four turns with 23 model calls,
  228,785 tokens, 132.2 seconds of model latency, and an estimated USD 0.0882.
  The initial BDO answer was direct and grounded. Product and promo progression
  worked, and the first product pricelist rendered only the reviewed Double
  Warranty promo as supporting context. The final Pay Later reply was too long,
  recited the method catalog, and did not resume the unresolved tire choice.
- `hr22` correctly propagated a corrected tire size and calculated a grounded
  two-piece total, but it asked permission to check service after the customer
  had already supplied a usable area.
- `hr24` resumed the second shown product after an FAQ interruption and then
  progressed a supplied location to grounded schedule options. The review also
  exposed the promo-surface scoping defect fixed below.
- `hr25` correctly stopped sales progression after a human-handoff request, but
  its earlier complaint response speculated about why a prior price differed.

### Bounded fixes from the review

- An exact catalog-title lookup now renders only that exact reviewed promo. A
  Double Warranty lookup can no longer expand into unrelated event and 3+1
  cards. When the model requests it as support for a Tire Protection Plan
  pricelist, both the exact promo surface and product cards are required in the
  complete-turn plan; connective wording and the CTA remain model-owned.
- A Pay Later or Pay Now option question now receives the grounded option status
  and compatibility boundary without dumping every current payment method. The
  payment composer is instructed to return to an unresolved shown-product
  choice with one short question when that is the active sales decision.
- Model prose that asserts a generic `promo` now receives the semantic promo
  audit. A renderer-owned Double Warranty image with a non-commercial caption
  remains eligible for the lower-cost audit skip.

### Guided clicks and controlled endpoint

- The deterministic guided-click fixture gate passed 34/34 cases across product,
  promo, price category, location, schedule, and payment choices, including
  stale, tampered, superseded, duplicate, and change-of-mind paths. No fixture
  produced an unauthorized submission.
- Focused return-only endpoint safety tests passed 18/18 across follow-up state,
  recovery state, tag suppression, and promo-action endpoint handling.
- The controlled staging call returned HTTP 200 in 21.1 seconds with delivery
  explicitly skipped as `return_only`. Staging still served `05c56af`, not this
  patch, and therefore returned the old four-bubble full intake. This proves the
  endpoint/no-send transport path only; it is not patch acceptance or Messenger
  delivery proof.

### Test decision

The affected component run completed 789 passing tests and found one promo-audit
trigger failure. After the trigger fix, the failed regression and four adjacent
promo-audit cases passed, as did the focused Pay Later and exact-title promo
tests. `git diff --check` passed apart from the checkout's existing line-ending
warnings.

The full repository suite remains intentionally deferred. Run it once, only
after the dense semantic blockers are resolved and immediately before merging.
After the exact patch reaches staging through the normal staging-branch Cloud
Build trigger, repeat one return-only endpoint probe and verify the deployed SHA
before considering a named controlled-contact delivery check.
