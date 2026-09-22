# Runtime V7 Documentation Index

Last updated: 2026-09-10

Runtime V7 documentation is intentionally split by ownership. Use this file as
the routing table before adding another note or appending to a large existing
document.

## Runtime V7 Status

Runtime V7 is a deployable Gulong assistant runtime slice with `/gulong/v7/chat`,
`/gulong/v7/chat/tester`, the protected `/gulong/v7/chat/tester/hydrated`
evaluation boundary, and `/gulong/v7/followup` API boundaries. It is
designed around one model-led Chat Completions tool loop with deterministic
validation, canonicalization, rendering, refs, and side-effect boundaries.

The current foundation includes:

- Product discovery, details, FAQ, deterministic cards, and visibility checks.
- Service FAQ, installation partner and slot lookup, area-only partner
  disclosure, addon lookup, and slot validation.
- Active Working Memory, Background Signals, observations, order readiness,
  image evidence, and channel-history hydration.
- Order quote, summary, API-ready payload validation, submit order,
  order-details readback, payment request, and payment-proof matching
  foundation.
- ManyChat-ready response rendering, content delivery shape, QR/image messages,
  turn traces, idempotency/replay metadata, and passive tagging.
- Optional Compute Engine + Cloud SQL runtime stores for shadow/canary testing,
  gated by explicit VM environment variables while Firestore remains the Cloud
  Run default.
- Lead-qualification CTA focus that can prioritize missing location after
  product quote while keeping final wording model-led.
- Authenticated one-call proactive follow-up planning plus customer-last missed
  turn recovery, deterministic evidence validation/rendering, version-2 attempt
  and delivered-presentation ledgers, and normalized follow-up monitoring.
- ManyChat Moderate/High Intent handoff notes through the existing note
  delivery boundary.
- Composer-owned complete-turn ordering through `CustomerTurnPlanV1`, with
  runtime-owned evidence/state validation and province-to-city authorization.
- Fail-soft typed request coverage with required direct-answer surfaces,
  optional supporting context, and a renderer-owned first-TPP warranty
  replacement that preserves the structured product text/image-button template.
- Typed Background Signal relations that keep conditional/question/historical
  values turn-scoped and apply explicit rejection/correction semantics before
  durable memory or ledger persistence.
- Model-requested human handoff with durable requested state, truthful composer
  constraints, `Stop Chatbot` tagging, a compact CS note, and proactive
  follow-up suppression.

Runtime V7 is still being hardened through focused probes before broader
promotion decisions. Do not treat a passing local harness test as proof of live
ManyChat behavior without an endpoint smoke/probe when live behavior matters.

## Documentation Map

- `runtime_v7/AGENTS.md`
  - Local operating contract for Runtime V7 code/docs changes.
  - Update when V7 development rules, anti-patterns, or test expectations
    change.
- `docs/RUNTIME_V7_ARCHITECTURE.md`
  - Top-level project design, request flow, state boundaries, and component
    relationships, including the follow-up request flow.
  - Update when the architecture or ownership boundaries change.
- `docs/RUNTIME_V7_COMPONENTS.md`
  - Per-component responsibilities, key modules, usage notes, and primary test
    surfaces, including `runtime_v7.followup` and source-backed brand-knowledge
    ownership.
  - Update when adding or materially changing V7 modules/tools/renderers.
- `cloudbuild.brand-knowledge-infra.yaml`
  - Declares the brand chunk vector index, daily sync job, and Manila
    scheduler used by the published brand-knowledge source.
- `docs/RUNTIME_V7_VERSION_HISTORY.md`
  - Commit-backed milestone timeline with what changed and why it mattered.
  - Update when a new commit group changes a V7 capability boundary.
- `docs/RELEASE_HISTORY.md`
  - CI/CD staging checkpoints and explicit production promotion decisions.
  - Update after each staged release candidate and any live promotion or hold.
- `docs/RUNTIME_V7_DECISIONS_AND_GAPS.md`
  - Design decisions, learnings, anti-pattern migrations, parked ideas,
    pending gaps, and validation notes.
  - Update after reviews, probes, root-cause investigations, or intentional
    deferrals.
- `docs/RUNTIME_V7_PRODUCT_AGENT_IMPLEMENTATION_NOTE.md`
  - Detailed implementation narrative for product/service/order/prompt/state
    behavior.
  - Keep for longer explanations; do not use it as the only change log.
- `docs/RUNTIME_V7_PRODUCT_SERVICE_FOUNDATION_CHECKPOINT.md`
  - Historical checkpoint at the product/service foundation split.
  - Update only if explicitly adding a new checkpoint section.
- `docs/RUNTIME_V7_PRODUCTION_OBSERVABILITY_NOTE.md`
  - Observability design and desired production trace/log surfaces.
  - Update when trace/log schema or observability strategy changes.
- `docs/RUNTIME_V7_FOLLOWUP_PRODUCTION_SAFETY.md`
  - Authoritative follow-up endpoint, state, test, staging, VM canary,
    monitoring, and kill-switch runbook.
  - Update whenever follow-up delivery admission or release gates change.
- `docs/RUNTIME_V7_PROMO_BRAND_LEAD_MILESTONE.md`
  - Approved narrow scope for model-led promo routing, AI-derived eligibility,
    interactive price-category choices, and funnel instrumentation.
  - Use as the implementation and rollout contract until this milestone is
    deployed; keep its explicitly deferred work out of the release branch.
- `docs/RUNTIME_V7_VM_CLOUDSQL_SHADOW.md`
  - Pre-canary Compute Engine + Cloud SQL runtime shadow runbook, including
    env flags, manual smoke tests, Cloud SQL tables, and reversion boundary.
  - Update when VM runtime deployment, state-store flags, or canary readiness
    criteria change.
- `docs/RUNTIME_V7_LIVE_MODEL_TEST_PACK.md`
  - Live model probe usage plus the complete-turn human review bundle,
    evidence labels, orchestrator-owned rubric, and cost-bounded test cadence.
  - Update when live pack/review usage, scenarios, or safety limits change.
- `docs/RUNTIME_V7_PROMOTION_HEALTH_EVALUATOR.md`
  - Deployed tester-route promotion matrix, protected ManyChat-history
    hydration sentinel, deterministic health scoring, versioned pre-verified
    scenarios, canonical evidence contracts, artifact storage/redaction, and
    automated approval gates.
  - Use before staging, live Cloud Run, and VM promotion decisions; scheduling
    and email reporting remain deferred.
- `docs/RUNTIME_V7_LAYERED_HEALTH_RUNNER.md`
  - Selectable local deterministic, read-only commerce/channel API, and metered model health layers plus
    pull-request, daily, staging, live, and complete operator profiles.
  - Use to choose evaluation depth and cost; it delegates customer-quality
    scoring to the promotion-health evaluator.
- `docs/RUNTIME_V7_ADAPTIVE_NEXT_BEST_MOVE_DEFERRED_2026-08-15.md`
  - Recovery-safe handoff for the rejected adaptive candidate: retained
    learnings, deferred components, known failure modes, and fresh-session
    acceptance gates.
  - Use as scope input only; never restore the rejected commits wholesale.
- `docs/IMPLEMENTATION_NOTES_RUNTIME_V2.md`
  - Repository-level chronological implementation log.
  - Add dated Runtime V7 entries for significant changes, while noting that
    V2 behavior is unchanged when applicable.
- `README.md`
  - Top-level repo orientation and entrypoint links.
  - Keep concise; link to this index rather than duplicating V7 details.

## Update Rules

For any Runtime V7 change, ask which of these changed:

- API/entrypoint shape or ManyChat integration.
- Prompt or model-facing context.
- Tool schema, tool output, or capability exposure.
- State persistence, refs, memory, signals, or readiness.
- Renderer, response-unit, bubble, image, QR, or payment formatting.
- Order/payment side effect boundary.
- Test/probe scenario, validation result, or known limitation.
- Documentation ownership or development rules.

If one changed, update at least one Runtime V7 doc in the same commit.

Every significant Runtime V7 update should record:

- What changed.
- Why it changed.
- Which component owns the new behavior.
- Which decision or anti-pattern it confirms, rejects, or changes.
- What was verified, including tests or probe artifacts.
- What remains parked or risky, if anything.

Use this default update set:

- Behavior change: `IMPLEMENTATION_NOTES_RUNTIME_V2.md` plus the relevant
  V7 component/design doc.
- New component: `RUNTIME_V7_COMPONENTS.md`, `RUNTIME_V7_ARCHITECTURE.md` if
  relationships changed, and the implementation log.
- Capability milestone or branch checkpoint:
  `RUNTIME_V7_VERSION_HISTORY.md`, the implementation log, and any relevant
  architecture/component docs.
- New design decision, anti-pattern, or deferral:
  `RUNTIME_V7_DECISIONS_AND_GAPS.md` plus the implementation log if code
  changed.
- New live probe finding: `RUNTIME_V7_DECISIONS_AND_GAPS.md`; add artifacts or
  commands only when they are reusable.
- Docs-only cleanup: update this index if ownership changed.

## Current Validation Commands

- Full Runtime V7 regression set:
  `pytest $(rg --files test | rg "test_runtime_v7") -q`
- V7 ingress/history/idempotency:
  `pytest test/test_runtime_v7_ingress_trace.py -q`
- V7 follow-up endpoint:
  `pytest test/test_runtime_v7_followup_v2.py test/test_runtime_v7_followup_endpoint.py -q`
- Live model probes:
  `python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_live_model_test_pack.json --mode live --scenario <scenario_id> --enable-context-cache`
- Complete-turn pack validation:
  `python scripts/runtime_v7_human_review_bundle.py --validate-pack test_packs/runtime_v7_human_response_eval_pack.json`
- Selectable local deterministic profile (no intended metered calls; use CI
  egress isolation for a hard no-network guarantee):
  `python scripts/runtime_v7_layered_health_runner.py --profile pr-no-cost`
- Offline human-review bundle:
  `python scripts/runtime_v7_human_review_bundle.py --input <scenario-or-debug-json> --pack test_packs/runtime_v7_human_response_eval_pack.json`
- First-turn intro endpoint probe:
  `python scripts/runtime_v7_first_turn_intro_endpoint_probe.py --base-url <runtime-service-url> --pack test_packs/runtime_v7_first_turn_intro_live_pack.json --scenario <scenario_id>`
- Deployed promotion-health matrix:
  `python scripts/runtime_v7_release_candidate_matrix.py --base-url <runtime-service-url> --tier promotion --expected-release <release> --expected-git-sha <sha> --expected-environment <environment>`
- Offline deterministic rescore:
  `python scripts/runtime_v7_score_release_candidate.py <summary.json> --baseline-summary <baseline-summary.json>`
- Redacted external-review export:
  `python scripts/runtime_v7_export_evaluator_review.py <summary.json>`

Do not run broad live packs by default. Prefer focused scenarios tied to the
changed component and keep the artifact path in the handoff when live probes
are used.
