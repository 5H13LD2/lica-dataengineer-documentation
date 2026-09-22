# Runtime V7 Promotion Health Evaluator

Last updated: 2026-09-16

This is the pre-promotion quality and health gate for a deployed Runtime V7
candidate. It combines exact serving-path contracts, technical telemetry,
and deterministic customer-service checks over a versioned, pre-verified
scenario contract. It requires neither per-run human approval nor an LLM judge.

The current contract version is `2026-09-13.1`. It distinguishes a bare,
ambiguous store-location request from both an explicit head-office-address
question and an explicit installation/service-area request. The ambiguous case
must ask for the customer's free-form city/area without supplying the Makati
address or showing province buttons; a separate negative-control case preserves
the direct grounded address answer when the head office is explicitly named.
The contract continues to require provider identities and complete rendered-
card evidence instead of one response sentence or a globally required button.

The nonlinear product-first scenario also accepts a deterministic payment-
claim safety fallback only when runtime records the dedicated guarded status,
preserves at least one already-authorized product surface, exposes the required
tracked product token, and emits no unsupported commercial claim. The generic
renderer fallback remains a failure, and no other scenario accepts this status
by default.

Pure typed payment-policy scenarios may also accept
`provider_grounded_payment_composition`. This status is valid only when every
expected claim has provider-backed typed authority and the final visible prose
contains the matching method, outcome, brand, and payment option. It is not a
generic composer-failure waiver and is not accepted for mixed turns.

Operational-funnel contract `2026-09-15.1` adds four reviewed, privacy-safe,
transcript-derived journeys for the primary size+brand completion KPI. They
evaluate the final rendered response before delivery and the deterministic
Moderate qualification payload before persistence; neither ManyChat delivery
nor a BigQuery landing is required for these synthetic checks.

For selective orchestration across deterministic, read-only API, and metered
model checks, use `scripts/runtime_v7_layered_health_runner.py` and
`docs/RUNTIME_V7_LAYERED_HEALTH_RUNNER.md`. This document remains the scoring
contract for model-backed promotion layers.

Scheduling, regular email delivery, BigQuery persistence, and historical
backfills are intentionally deferred until the evaluator is tuned against a
deployed candidate. The first objective is confidence in the current patch.

## Evaluation boundary

The matrix runs only against `/gulong/v7/chat/tester` and
`/gulong/v7/choice-action/tester`. Requests use unique synthetic IDs,
`delivery_mode=return_only`, disabled analytics, and isolated tester session
collections. The evaluator fails if delivery or tag application is not skipped
or if a scenario reaches an order/payment mutation tool.

Tester sessions and traces still persist in isolated `_test` collections. This
is not a zero-write probe and the report states that limitation.

The layered pre-staging, pre-live, and complete profiles add one separately
authenticated `/gulong/v7/chat/tester/hydrated` turn for the designated
synthetic ManyChat account. Default tester scenarios remain history-disabled
and reproducible; the protected turn independently proves deployed channel
loading and hydration before the model path. It is allowlisted, return-only,
analytics-disabled, and transcript-redacted. Its metered usage is added to the
separate hydrated-history bucket with a `100,000`-token cap and is also included
in the disclosed combined usage total.

The current promotion tier contains 16 single-turn cases, three multi-turn
tracked-action journeys, and four operational-funnel journeys. It spans promotion, payment, product availability,
tire-size normalization, business contact, delivery policy, store/location,
scheduling, and mixed/nonlinear intent. Variation is distributed across the
matrix: Tagalog/Taglish and English, yes/no and short-form questions, a typo,
missing location precision, unsupported and unknown payment methods, multiple
brands and installment terms, reordered two-brand clauses, shorthand, typo
variation, quantities, dates, and negative progression controls. This is a
cost-bounded release sample, not a claim that every
possible customer inquiry has been enumerated.

### Size+brand operational funnel

The separate operational section answers whether the deployed runtime can
progress realistic size+brand near-misses to valid customer location/contact
and a planned official Moderate qualification. Its four versioned paths are:

- typo/spacing-heavy size+brand input followed by a typed city shorthand;
- size+brand input followed by validated province-to-city guided actions;
- size+brand input, location uncertainty, then an offered and completed
  customer-contact fallback;
- a size+brand+location negative control that must qualify immediately without
  asking for location again.

Eligibility and capture use the post-turn canonical signal ledger and accept
only customer-owned `latest_user_message`, `customer_history`, or
`validated_choice_action` provenance. A brand shown on a product card, a
province-only click, relative "near me" wording, or a store/service-area
question cannot complete the customer evidence. Guided location succeeds only
after a valid `serviceable_city` action.

Rendered requests are checked against reviewed meaning-preserving wording
patterns and structured `lc1` actions, not one exact sentence. Canonical signal
capture and qualification remain exact schema/provenance checks. The full
rendered turn is retained so matcher behavior remains auditable.

The final stage requires a planned `Moderate Intent` trigger and a countable,
deterministic analytical qualification whose source signals contain tire size,
brand, and the newly completed location or contact. This is a pre-persistence
capability check. Production abandonment and linked 7/14-day booking conversion
are reported as `not_measured_in_synthetic_evaluator`; they require a separate
observational status query and must never be inferred from synthetic passes.

## Evidence and scoring layers

### Mechanical contracts

Mechanical checks are exact where exactness is required:

- HTTP/runtime success and expected release, Git SHA, and environment.
- Return-only delivery and skipped tag application.
- Required, alternative, forbidden, and mutating tool calls.
- Canonical tool arguments such as payment method, product brand, payment
  option, tire-size fields, and FAQ IDs.
- Explicit tool-chain contracts match pre-hydration model calls to actual
  provider executions by round and tool-call ID. They independently score the
  expected post-hydration scope and bounded deduplication disposition, so a
  scope that is overwritten and then collapsed cannot pass because the final
  answer happens to look plausible.
- Provider-relative payment claims. The accepted outcome comes from the
  checkout-backed tool scope captured for that run, not from a stale response
  sentence or hard-coded pack value.
- Composer/repair state, guard evidence, structured product/cards, choice
  tokens, and journey transitions. The product journey positively exercises
  tracked product, location, schedule, payment-option, and payment-method
  clicks through the non-mutating boundary. Promo Details and About Brand are
  separate source-backed tracked-action journeys.
- On the completed product-to-payment journey, both Moderate and High trigger
  actions plus the versioned, countable Moderate analytical qualification
  payload are required. Its 24-hex qualification ID and non-empty event and
  idempotency identity must bind to the final tracked action. This proves runtime generation of the observability
  contract, not downstream warehouse persistence.

Customer prose is not compared with a reference answer. Stable policy concepts
may be checked with alternative term sets or narrowly scoped patterns, such as
recognizing `7-10 days`, `7 to 10 days`, or `7 hanggang 10 araw` as the same
lead-time fact. Exact wording is reserved for cases where the business actually
requires an approved spiel.

Tester diagnostics expose bounded call IDs, rounds, canonical/routing model
arguments, executed arguments, and dedupe dispositions. Raw cache keys and
free-form tool questions are excluded. Equivalent duplicate calls may reuse an
existing result, but every distinct required commercial scope must have at
least one identity-linked provider execution. A dedupe event whose hydrated
arguments no longer match its model-proposed scope is a mechanical failure.

### Technical health

The report computes response count, HTTP/runtime/tool error counts, tool error
rate, mutation-tool exposure, p50/p95/max endpoint latency, per-tool latency,
and prompt, uncached, cache-read, completion, reasoning, and total tokens. A
provider `no_match` is a business result rather than a technical tool error.

Core matrix technical totals remain separate from operational-funnel totals so
the historical baseline keeps the same latency and token denominators. The
report also exposes combined metered usage. The core matrix retains its
`2,000,000`-token and 250-model-call ceilings; the additive operational funnel
has a separate `1,200,000`-token cap.

Each successful tester response must also expose bounded monotonic timings for
the runtime handler and its session, lock, conversation hydration, harness,
rendering, freshness, delivery/tagging, persistence, and trace phases when
those phases execute. The report rolls up each phase, each tool, and the gap
between server-reported handler time and client-observed endpoint time. Missing
or invalid phase durations and missing latency on an executed tool block the
gate; no message content, credentials, or provider payloads are included.

The turn total covers every model-backed runtime component: image evidence,
background-signal extraction, the main tool loop and composer/repair calls,
and active-working-memory compaction. Logical records, provider attempts,
metered calls, missing-usage calls, and retries are counted separately. A
response with one metered main call cannot hide an unmetered supplemental call
or retry; either condition blocks promotion. Normalized observability emits a
component span for each model-backed record and preserves the state extractor's
own typed span without double-counting it as a second call.

Every token field must be a non-negative integer. Uncached prompt tokens must
equal prompt tokens minus cache-read input tokens (bounded at zero), and total
tokens cannot be lower than prompt plus completion tokens. Missing cache or
reasoning fields are not silently converted to healthy zero values.

The deployed tester response does not currently expose priced per-model call
records, so monetary cost is reported as unavailable instead of being guessed.
Token movement can still be compared. Cost estimation may be added later with
a versioned pricing profile and per-component model evidence.

The explicitly provisional guardrails mark p95 latency above 45 seconds as a
concern and above 95 seconds as a failure. The absolute core-matrix budget is
2,000,000 total tokens, with separate operational and hydrated caps documented
above. A compatible baseline marks core total-token growth above
10% as a concern and above 25% as a failure. Any retuning must be recorded with
the evidence and approver rather than silently changed to clear a release.
Relative token growth is computed only across matching
`case/action/occurrence` responses with valid usage on both revisions. At least
80% of the baseline's observed actions must be comparable. Candidate-only
actions restored by a correctness fix, baseline-only actions, and usage-missing
failures are disclosed separately under aggregate observed workload cost; they
are never zero-filled into the per-action efficiency gate. The candidate's
core 2,000,000-token ceiling still covers every measured core action; additive
operational and hydrated actions remain independently capped.

Contract `2026-09-13.1` may compare cost and latency with `2026-09-11.4` only
through checked-in exact old/new digest pairs. This bridge does not rescore the
baseline or relax candidate correctness. Artifact integrity, profile schema,
tier, workers, timeout, feature expectations, health policy, and the complete
case/journey cohort must still match; any unapproved digest fails closed.
Operational rows do not enter the relative baseline comparison because the
historical baseline predates their contract. They are independently fail-closed
under their own absolute metered budget.

### Automated CS contract

The evaluator maps transparent deterministic checks to the established seven
CS dimensions: understanding, natural language, directness, grounding,
progression, presentation, and consistency. The scenario inputs and expected
hard-fact/tool/surface outcomes are versioned and pre-verified. The run checks
the generated response against those contracts without requiring exact prose.

Natural-language checks are deliberately bounded to mechanically observable
problems such as empty output, mojibake, duplication, excessive bubbles, and
question overload. This is an automated regression gate, not a claim that code
can reproduce every subjective judgment a CS reviewer might make. Complete
rendered output remains in the artifact for optional audit, but audit is not a
promotion prerequisite.

Duplicate-bubble scoring is turn-local. Exact repeated bubbles inside one
rendered response are a presentation/consistency concern; a summary or missing-
details reminder repeated after a later state-changing click is not. Journey-
level repetition remains visible in the full artifact and can be governed by a
separate explicit scenario contract when a particular phrase must not recur.

The rubric dimensions are:

1. Understands the customer.
2. Natural language.
3. Directness.
4. Grounding.
5. Progression.
6. Presentation.
7. Consistency.

Each dimension is scored from explicit scenario and rendering evidence.

## Cost-bounded workflow

Run the deployed promotion matrix once:

```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts/runtime_v7_release_candidate_matrix.py `
  --base-url <candidate-url> `
  --tier promotion `
  --expected-release <release-version> `
  --expected-git-sha <git-sha> `
  --expected-environment staging
```

The output directory contains:

- `summary.json`: private complete diagnostic evidence and promotion score.
- `summary.md`: customer inputs, all bubbles/cards/buttons, tool names, and
  contract evidence for convenient audit.
- `integrity.json`: SHA-256 over the immutable run evidence.
- `run_manifest.json`: file checksums, exact target identity, result, and the
  canonical external-storage key.

Rescore an unchanged artifact without repeating model calls:

```powershell
python scripts/runtime_v7_score_release_candidate.py `
  <output-directory>/summary.json `
  --baseline-summary <compatible-baseline>/summary.json
```

Export a data-minimized bundle for external review:

```powershell
python scripts/runtime_v7_export_evaluator_review.py `
  <output-directory>/summary.json
```

The review export retains synthetic prompts, rendered customer content,
aggregate health, and tool names/statuses. It removes tool arguments/results,
request/session/user/trace identifiers, raw HTTP bodies, subprocess logs, and
local paths.

Use `--tier smoke` for the three customer-correctness sentinels: business
contact, explicit delivery policy, and compound Yokohama payment scope. The
smoke tier can return `diagnostic_pass` but never `ready_for_promotion`. The
promotion tier remains required before environment promotion. `full` is
currently an alias of promotion and is reserved for a larger rotating corpus;
do not imply broader coverage until that corpus is checked in.

Operational journeys run automatically for `promotion` and `full`. Use
`--operational-funnel-scenario <id>` only for targeted diagnosis. Selecting or
skipping part of the required operational corpus cannot produce
`ready_for_promotion`.

Feature availability is an explicit operator-owned input, not something the
evaluator guesses from a missing button. The artifact records one of these
modes for each covered surface:

- `required_when_enabled`: the environment is expected to expose the surface;
  a missing tracked token fails.
- `not_applicable_when_unavailable`: absence passes only when authoritative
  provider/surface diagnostics prove there is currently nothing to render.
- `forbidden_when_disabled`: any rendered tracked token fails; absence is the
  expected result.

Defaults require product, location, schedule, payment-option, and payment-
method choices. Promo guided actions default to
`not_applicable_when_unavailable`, where N/A requires an explicit empty
provider-owned `allowed_promo_refs` list. Missing promo scope evidence is a
failure, not N/A. Override deployment-specific expectations with a JSON object:

For action-specific journeys such as About Brand, N/A may also be proven when
the current `promo_presentation.card_refs` set is complete in the rendered
`pc1` cards and none offers that action. Partial or unbound rendering does not
prove unavailability. Likewise, the product journey may proceed directly to a
validated schedule when the initial customer request already supplied the
location; it must not manufacture an unnecessary location-picker failure.

Commercial response wording is meaning-based. Product promo positives are
matched to typed card evidence and the dynamic payable total. Promo negatives
require the deterministic provider guard and bounded source language such as
"reviewed" or "verified" promo evidence, but no exact spiel is required.

```json
{
  "promo_guided_actions": "required_when_enabled",
  "product_choices": "required_when_enabled",
  "location_choices": "required_when_enabled",
  "schedule_choices": "required_when_enabled",
  "payment_option_choices": "required_when_enabled",
  "payment_method_choices": "required_when_enabled"
}
```

Pass it as `--feature-expectations <path-to-json>`. Use
`forbidden_when_disabled` only when that environment is intentionally
configured to suppress the named surface. Unknown feature names and modes are
rejected.

An optional `--baseline-summary` is accepted only when schema, tier, execution
settings, feature-expectation profile, scenario-contract version and digest,
exact required IDs, and exact observed IDs match. Both candidate and baseline
must pass artifact-integrity validation. Base
URL or environment differences are disclosed as comparison context rather than
silently ignored; other cohort differences fail closed as `inconclusive`.
Feature-surface hardening uses release-matrix schema v4, so older v2/v3
artifacts are intentionally incompatible baselines.
Use `--require-baseline` for the final candidate gate measured against the
matching `50e5975` run; it blocks when the baseline is absent or incompatible.
It also blocks when matched valid-usage coverage is below 80% of baseline
actions. This permits an older revision to stop before newly restored guided
steps without misclassifying those extra functional turns as per-turn prompt
regression.

## Approval criteria

- Green / ready for promotion: every mechanical and technical gate passes;
  the exact pre-verified scenario corpus and target identity match; telemetry
  is complete; every required operational-funnel stage passes; artifact
  integrity passes; and no automated CS concern remains.
- Yellow: hard gates pass but a latency, token-regression, or structural CS
  concern exceeds its warning threshold.
- Red / blocked: any mechanical, transport, runtime, tool-error, mutation,
  unsafe delivery/tagging, incomplete corpus, wrong target, missing telemetry,
  incompatible baseline, or integrity failure exists.

Case/journey/operational selectors remain available for diagnosis, but a partial artifact
is always red and can never become `ready_for_promotion`.

All model-backed tiers require explicit `--expected-release`,
`--expected-git-sha`, and `--expected-environment`. Every response must match
all three values. Chat turns require positive recorded model usage and model-
call trace evidence; all chat/click responses require positive latency plus an
explicit complete usage record (zero tokens is allowed only for a genuinely
deterministic click). Missing component usage and unmetered retries fail the
gate. Missing markers cannot opt a response out of telemetry.

## Result storage and external review

Local runs are written under the selected `--out-dir` (by default under
gitignored `tmp/`). Local files are scratch evidence and are not durable.

The durable publication target is a private, immutable Cloud Storage prefix:

```text
gs://<private-runtime-health-bucket>/v1/<surface>/<git_sha>/<run_id>/
```

Use distinct surfaces such as `cloud-run-staging`,
`cloud-run-live-candidate`, and `vm-live`. Upload passing and failing bundles,
write the manifest last, require no-overwrite object-generation preconditions,
enable object versioning/retention, and record the immutable manifest URI in
release history. Cloud Logging remains correlated operational telemetry; it is
not the source of complete evaluator evidence.

The embedded SHA-256 detects accidental or post-run content changes; because
it is not a keyed signature, it is not proof against a malicious producer.
Promotion provenance therefore depends on the controlled layered-runner job,
exact outer-to-child target/path binding, and immutable object generation in
the later Cloud Storage publication step.

Externally shared artifacts must come from the redacted exporter and use a
separate private review prefix with restricted identity access or a short-lived
signed URL. The current implementation creates the checksummed local bundles;
Cloud Build/GCS upload and retention configuration are a later operational
step and are not silently performed by the evaluator.

## Promotion sequence

Run the promotion tier independently on Cloud Run staging, the exact approved
Cloud Run live candidate, and the VM alternate-port candidate before VM
cutover. Verify release metadata and traffic/health separately at each layer.
Cloud Run success never proves that the customer-facing VM was updated.

Before each matrix, run the protected hydrated-history layer with the same
target identity and synthetic account. A successful direct ManyChat API read
does not substitute for this runtime-path check, and the ordinary isolated
tester matrix does not substitute for it either.

After cutover, rerun the smoke tier against the VM tester route and retain the
rollback image. Actual ManyChat delivery is a separate, explicitly authorized
validation and is not performed by this evaluator.

## Deferred automation

Daily rotation, scheduled status reports, email delivery, automated GCS
publication, durable trend storage, and optional LLM-written summaries can be
added after thresholds and case coverage are tuned. Any future LLM review remains advisory: typed extraction may
feed deterministic scoring, but an LLM must not become the sole promotion gate.
