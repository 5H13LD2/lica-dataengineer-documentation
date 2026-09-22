# Implementation Notes

## 2026-09-17 - Preserve per-call payment scope and reuse promo preload evidence

- Exact staging `d545e13` passed every deterministic, API, channel-read,
  hydration, latency, and independent token-budget gate. The complete model
  layer remained blocked by one payment-scope mechanical failure and one
  redundant promo call counted as a tool error.
- Payment hydration now resolves an incomplete generic method only when the
  model's customer-backed per-call brand and Pay Now/Pay Later option identify
  exactly one customer-authored installment scope. Repeated or otherwise
  ambiguous terms remain unresolved; the exact canonical method, brand,
  option, question, provider execution, and cache identity stay aligned.
- A model repetition of a successful deterministic promo preload now reuses
  that exact read-only provider result. Failed, malformed, non-preloaded, and
  non-promo calls retain the normal unexposed-tool guard.
- All 1,933 repository tests pass, along with scoped Ruff, compilation, and
  diff checks. Fresh exact staging targeted and complete evidence is required
  before live or VM promotion.

## 2026-09-17 - Sanitize provider-owned service copy after composer repair

- Exact staging `c3e98b6` passed every deterministic/API/hydration layer, all
  operational-funnel stages, and all independent token budgets: core
  1,916,070/2M, operational 967,755/1.2M, and hydrated 50,558/100k.
- Its only blocker was ordering-dependent: the initial composer combined a
  tone violation with service prose duplicated by a provider-owned summary;
  model repair fixed tone, but the existing service sanitizer ran only before
  repair, leaving `renderer_contract_fallback` despite grounded final output.
- The same bounded sanitizer now runs after repair when that duplicate-service
  violation is the sole remainder. It revalidates renderer, request coverage,
  and typed claim contracts before acceptance. All 1,930 local tests pass;
  fresh exact staging evidence remains required.

## 2026-09-17 - Complete renderer-owned surfaces before model repair

- Exact staging `a6b443f` passed deterministic, commerce, authenticated
  channel-read, hydrated-history, identity, compatible-baseline, HTTP
  correctness, and planned-Moderate checks. It remained blocked by a 14.1s
  cold health probe, one controlled slot-plan redirect counted as an error, two
  renderer-contract fallbacks, and 2,030,599 core tokens versus the 2M cap.
- Required supporting-replacement surfaces are renderer-owned and now complete
  deterministically from exact authorized surface refs when omitted. Existing
  duplicate supporting-copy sanitization also runs before a model repair. This
  preserves the model's prose and active decision while avoiding unnecessary
  repair calls.
- A validated installation selection now contributes the canonical
  `validated_installation_selection` evidence ref to `validated_state` and
  `order_facts`, matching the structured composer context instead of forcing a
  repair or fallback for a source-owned customer selection.
- The exact pre-product slot-to-partner guard is reported as a deterministic
  `not_applicable` progression redirect rather than a provider/tool error; its
  guard event and authorized alternative remain observable. Location-request
  scoring now requires the customer-location wording to follow the question,
  so a CTA to check sites in an already-known city is not a location re-ask.
- All 1,929 repository tests, scoped Ruff, compilation, and diff checks pass.
  Fresh exact staging evidence remains required; limits are unchanged.

## 2026-09-16 - Canonicalize prompted locations within the approved cost gate

- Exact staging `8d8f3c3` passed deterministic, API, authenticated channel-read,
  hydrated-history, identity, compatible-baseline, HTTP/runtime, and latency
  checks. It remained blocked because `qc po` was understood in customer prose
  but omitted from the background-signal ledger, and core metered usage reached
  2,025,247 tokens against the approved 2,000,000-token ceiling.
- A bounded completion now handles only short customer replies immediately
  after a direct city/area question. It must resolve canonically and rejects
  uncertainty, relative-location answers, business-address questions, explicit
  questions, and ambiguous locations. General raw-message extraction remains
  model-owned.
- The reviewed product-to-payment journey now supplies its already-known date
  with the initial size, location, and quantity. This removes one redundant
  model exchange while preserving every tracked product, schedule, and payment
  assertion; the 2M gate is not increased.
- Scenario contract `2026-09-16.2` records the deliberate journey-input change
  and exact bridges permit cost/latency comparison only against the prior
  reviewed contracts. All 1,926 repository tests pass. Fresh exact staging
  targeted and complete evidence is required before live or VM promotion.

## 2026-09-16 - Align complete journeys with validated runtime progression

- Exact staging `1f98658` passed deterministic, commerce, authenticated
  channel-read, hydrated-history, target-identity, baseline-compatibility,
  HTTP/runtime, latency, and all customer-visible operational-funnel stages.
  The complete gate still blocked on three evaluator-only contract gaps.
- The product journey now adapts when a selected-product order snapshot already
  contains a canonical installation area and the rendered response asks for a
  date. It sends a reviewed typed date reply, then continues through the actual
  schedule, payment-option, and payment-method actions. A missing location
  button alone is no longer treated as failure in that exact state.
- Typed location completion may use the expected no-tool composer-skip path;
  the scenario still requires canonical customer-signal capture, planned
  Moderate qualification, and a visible final response. Generic skipped
  composition remains rejected outside the reviewed contract.
- `service_claim_surface_sanitized` is accepted only when the exact sanitizer
  event reports removed prose, zero remaining violations, and a successful
  location-scoped installation-partner result with provider authority and a
  presentation ref. Missing authority, residual violations, and missing final
  prose are negative controls.
- The revised evaluator passes all 1,920 repository tests, scoped Ruff,
  compilation, and diff checks. A rebuilt exact staging targeted and complete
  run remains required before live or VM promotion.

## 2026-09-16 - Preserve cross-tool promo scope and retry transient probes

- Exact staging `ec9516d` passed the deterministic, dependency, authenticated
  channel-read, and hydrated-history layers. Its complete model layer was not a
  promotion pass: eight `RemoteDisconnected` probe failures produced cascading
  identity, telemetry, journey, and operational-funnel failures, and one
  successful Toyo turn exposed a real requested-promo scope gap.
- The promo guard had read `promo_types` only from `search_promo_catalog`. If
  the model preserved the explicit mechanic on `product_search` but omitted it
  from the later catalog call, a generic same-brand sale could erase the typed
  requested-mechanic miss. Requested promo mechanics are now merged from both
  provider calls before generic brand authority is considered.
- Tester POSTs now retry an identical idempotent payload up to three attempts
  within the existing total timeout. Attempt count and every transport error
  remain in evidence. HTTP responses are not retried, the deadline is not
  extended, and repeated transport failures still block promotion.
- The cross-tool regression and transport-retry controls pass with all 1,915
  repository tests, scoped Ruff, compilation, and diff checks. A rebuilt exact
  staging run remains required; no live or VM promotion is authorized by the
  failed `ec9516d` complete run.

## 2026-09-16 - Close promo-scope and single-product progression blockers

- Exact staging `8ee0f38` passed the deterministic, dependency, authenticated
  channel-read, and hydrated-history layers. The complete model layer passed
  21/23 scenarios with zero HTTP/runtime failures, but promotion remained
  blocked by one requested-promo scope error, one weak single-product CTA, one
  expected picker redirect counted as a tool error, and an incompatible older
  baseline artifact.
- Promo truth now distinguishes generic brand promo authority from the exact
  mechanic requested by the customer. A generic Toyo discount can no longer
  clear an unmatched Toyo Buy-3-Get-1 result. When the product provider returns
  an exact-size requested-brand card with a typed `promo_only`/`promo_type`
  miss, runtime preserves that useful fitment result and separately verified
  alternatives under an observable scoped-disclosure guard.
- A narrow post-composition progression invariant now applies when the latest
  customer message supplies tire size plus brand and exactly one exact product
  card is rendered. If no location/contact or competing decision exists, the
  runtime preserves product/promo surfaces and asks directly for the customer's
  city or area. Multiple products, existing location/contact, tracked actions,
  and competing tools remain negative controls.
- A rejected location picker caused by explicit current-turn location
  unavailability is an expected deterministic redirect and now reports
  `not_applicable`, not a tool failure. Other unauthorized location plans remain
  errors. Operational contract `2026-09-16.1` accepts a skipped composer only
  when the exact location-progression guard, one rendered product card, its
  preserved surface ref, and the direct visible area request all agree.
- Exact `355f626` staging passed the Toyo promo and contact-fallback paths. Its
  typed short-form path was also customer-correct; the obsolete composer-status
  rule was the sole reported failure and is corrected by the bounded contract
  above. The revised runtime and evaluator pass 1,913 local repository tests,
  scoped Ruff, compilation, and diff checks; a rebuilt exact staging run remains
  required.

## 2026-09-16 - Close payment and contact-fallback promotion blockers

- Exact staging `00ff8d5` passed deterministic, dependency, ManyChat-read, and
  hydrated-history checks, but the complete gate remained blocked. The core
  matrix passed 18/19: the Yokohama payment answer was customer-correct only
  after the generic payment safety fallback. The operational location-
  uncertainty journey repeated the location request instead of offering a
  contact fallback. Combined metered usage also mixed three independently sized
  workloads under one core-matrix cap.
- Added the transient semantic signal
  `location_response_status=unavailable_now`. The extractor recognizes meaning
  across wording variation; deterministic normalization accepts only the
  closed value and the runtime guard requires size+brand or selected-product
  progression, no captured location/contact, and no competing tool or tracked
  action before rendering the reviewed contact fallback. A model-requested
  province/city picker is specifically rejected and suppressed on this path;
  it is the unavailable input, not a competing customer objective.
- Added pure typed-payment composition. It is eligible only when every tool
  result is a payment-scoped `answer_order_faq` result and every result yields
  one typed claim. The provider-derived text must pass both payment claim
  coverage and ungrounded assertion validation. Mixed turns remain model-
  composed.
- Hardened the evaluator to validate the new status from provider authority,
  expected typed claims, and visible final prose. Its location-request check
  uses rendered text/action evidence with adjacent business-location and
  descriptive-statement negative controls.
- Preserved the approved `2,000,000` core cap and added explicit independent
  caps of `1,200,000` operational-funnel tokens and `100,000` hydrated-history
  tokens. Reports expose all three buckets and the combined consumption; CLI
  configuration fails closed if a cap is raised.
- Exact staging `3ed42de` proved the compound Yokohama payment response and
  typed claims correct. Its operational rerun then exposed a real integration
  edge: semantic extraction emitted `unavailable_now`, but the model's location
  picker prevented contact fallback. The general boundary now rejects that
  picker before execution, suppresses any attached location surface, and keeps
  other tools and validated actions as negative controls.

## 2026-09-16 - Generalize multi-location service and product-scope grounding

- Added `acceptable_service_locations` as a structured customer signal beside
  the canonical `location` anchor. Each area is normalized independently,
  deduplicated, and stored with per-location provenance; a later anchor
  correction clears stale alternatives.
- Service tool hydration now treats a model location as a proposed query. When
  no explicit partner or guided location selection exists, runtime executes
  against the current customer anchor. Authorized service claims carry the
  evidence ref and exact queried location into the turn plan and composer.
- Slot lookup is guarded by usable product context or a typed schedule
  constraint. Empty/zero-card product observations do not qualify as product
  context and therefore fall back to installation-partner discovery.
- The deterministic service surface states only the provider-queried area and
  explicitly says that alternatives require separate checks. Structured
  composer claim-unit sanitization suppresses duplicate or out-of-scope model
  availability claims without depending on wording.
- Product-search hydration preserves explicit latest-turn brand, terrain,
  exclusion, origin, category, promo, and model constraints through the model
  call. A provider-owned partial-match notice is shown before any fallback
  cards; no cards are rendered when the provider returns none.
- Product presentation now uses a fitment-first constraint hierarchy. Exact
  tire size, explicit EV compatibility, and customer exclusions remain hard;
  brand, model, terrain/category, budget, origin, warranty, availability,
  promo, guarantee, and installment preferences may relax only on exact-fitment
  products with typed deterministic disclosure. Explicit "brand only/no other
  brands" wording is preserved separately as canonical
  `brand_match_mode=strict` and never crosses brands.
- Requested-brand exact-size options are ordered before other-brand
  alternatives. Every fallback card carries its own
  `missing_requested_filters` and customer-facing mismatch labels, while promo,
  stock, and payment facts are claimed only when present on that exact card.
  All provider-backed options stay in the text list, while only trusted-image
  products receive visual cards and tracked buttons.
- Explicit terrain syntax is restored from the latest customer turn if model
  extraction or tool arguments omit it. Brand/terrain/size-only pseudo-model
  queries are removed, and the channel suppresses adjacent model prose when a
  deterministic partial-match notice owns the exact scope.
- The complete local repository suite passes 1,888 tests. The
  adaptive local replay used return-only channel output and synthetic session
  state; Cloud Run/VM deployment and ManyChat delivery were not part of this
  change.

## 2026-09-15 - Data-derived size+brand operational-funnel gate

- The release evaluator now contains a separate versioned operational-funnel
  contract built from privacy-safe, reviewed transcript examples. Four
  scenarios cover typed short-form location, guided province-to-city selection,
  contact fallback after location uncertainty, and a size+brand+location
  negative control.
- Eligibility and completion use canonical post-turn signal-ledger evidence
  from customer-authored history or validated choices. Product-card brands,
  relative/store-location language, rejected/conditional facts, and a
  province-only click cannot complete the funnel.
- The evaluator checks the final return-only response before delivery and the
  deterministic countable Moderate qualification before persistence. It does
  not require ManyChat delivery or BigQuery landing and labels production
  abandonment and 7/14-day linked booking conversion as observationally not
  measured.
- Operational latency, errors, and tokens are reported separately to preserve
  historical core-baseline comparability. Combined core plus operational token
  and model-call usage still enforces the absolute run budget. The redacted
  external-review bundle includes stage outcomes and provenance keys without
  raw signal values.

## 2026-09-13 - Enforce broad promo discovery and preserve grounded surfaces

- The first complete exact-staging run on `ed3fb08` finished without transport,
  tool, persistence, or telemetry errors but passed only 16/19 frozen scenarios.
  Two journeys interpreted the same broad current-promo request without calling
  catalog tools, while the nonlinear product-first path retrieved valid products
  and then lost their surface when a failed payment composer was replaced by a
  plain-text commercial fallback.
- The semantic signal contract now permits one bounded action scope:
  `promo_discovery_scope=all_current`. It is emitted only from the latest
  customer message with `question_only` relation, canonicalized independently
  of wording, and removed from continuity state. Runtime uses that typed scope
  for one read-only general catalog search and provider-authorized gallery
  projection. Raw phrases, historic signals, casual promo mentions, and
  brand/campaign/mechanic-specific questions cannot enter this path.
- When a structured final-composer surface plan remains authoritative but its
  payment prose fails the commercial contract, the last-resort guard now
  replaces all model prose with validated fallback text while retaining only
  the plan's deduplicated `render_surface` refs. Images and unknown units do not
  survive this fallback. This preserves grounded product cards and tracked
  `ps1` choices without preserving an unsupported payment assertion.
- The first exact-staging targeted replay proved that output was safe and kept
  the cards, but the generic `renderer_contract_fallback` status correctly
  remained ineligible for promotion. Runtime now emits the narrower
  `payment_claim_safe_surface_fallback` only on this guarded path, with the
  preserved-surface count. Scenario contract `2026-09-13.1` accepts that status
  only for the pre-verified nonlinear product-first case and only with a
  successful product search, a tracked `ps1` surface, positive guard evidence,
  and zero structured commercial claims. Other scenarios and the generic
  renderer fallback remain blocked.
- The prior complete run consumed 1,990,898 tokens. Replacing its three affected
  paths with the average of two green targeted replays projected approximately
  2,010,846 tokens, so launching the full gate unchanged was not sufficiently
  safe under the 2,000,000 ceiling. For the exact typed broad-promo scope only,
  the capability compiler now hides `search_promo_catalog` and
  `present_promo_gallery` after runtime has already fulfilled both operations.
  The main model retains their provider results for composition but cannot add
  redundant catalog/gallery rounds. Named and otherwise scoped promo paths keep
  their normal schemas.
- Contract `2026-09-13.1` retains an exact-digest baseline bridge to the prior
  approved `2026-09-11.4` definitions for cost and latency comparison only.
  Candidate scenario scoring always uses the current digest. The bridge cannot
  apply when artifact integrity, schema, tier, workers, timeout, feature or
  health policy, required scenario IDs, journey IDs, or exact identities differ.
- Validation includes semantic-signal normalization and prompt contracts,
  source/relation negative controls, direct catalog/provider checks, an
  integrated signal-to-gallery renderer test, and the complete product-search
  to failed-composer to image-card/channel path. The affected suite passes
  840/840 and the full repository passes 1,848/1,848. The zero-cost evaluator
  also passes its deterministic core and intent/observability layers with zero
  model calls and zero tokens. Exact staging targeted and frozen complete gates
  remain required; live Cloud Run and the VM are unchanged.

## 2026-09-12 - Ground scoped promo fallbacks and defer saved payment preferences

- The complete staging evaluator for exact `5cca58d` recorded 18/19 mechanical
  passes, zero HTTP/runtime/tool errors, 58,133 ms p95 latency, and 2,044,679
  tokens. Promotion was correctly blocked by `promo_toyo_truth` and by the
  temporary 2,000,000-token ceiling. The customer had supplied `175/65R14` and
  explicitly requested valid promo alternatives, but the runtime rendered no
  gallery and asked for the size again.
- `search_promo_catalog` now accepts canonical `alternative_scope` values
  `none`, `same_mechanic`, and `any_current`. A latest-turn
  `promo_alternative_scope` signal is extracted semantically and canonicalized;
  hydration fails closed to `none` unless that customer-authored signal supports
  the broader model proposal. The catalog keeps `primary_promo_refs` separate
  from `alternative_promo_refs`, includes the scope in its evidence hash, and
  exposes their union only as the renderer allowlist.
- The deterministic promo completion path may render fallback refs without a
  second model-selection round. Scoped promo facts still use only primary refs,
  and a named-brand question without fallback consent cannot broaden into
  unrelated cards. Runtime fallback prose preserves a promo surface only when
  it has a successful presentation ref and renderable cards, and uses
  present-tense acknowledgement instead of offering to fetch a card that is
  already included in the rendered turn.
- Commercial-evidence retry now treats typed `question_only`, `conditional`, or
  otherwise unconfirmed payment signals as due now. Confirmed payment details
  remain saved preferences and do not force a policy round during a product-first
  turn. The exact compound payment regressions and a mixed selected-option plus
  separate-question control remain green.

## 2026-09-12 - Recover named payment methods merged across customer clauses

- Exact staging `599b6ba` passed deterministic, core API, commerce API,
  channel-read, and protected history-hydration layers. The three-scenario
  model smoke used 166,809 matrix tokens with complete attempt metering, and
  contact plus delivery passed. Promotion correctly remained blocked because
  the model proposed `Home Credit 3-month 0%` as one FAQ method while separately
  proposing BPI 6-month. Hydration narrowed the merged call to the grounded
  three-month scope, leaving Home Credit without an independent provider call
  or typed claim even though the generated prose happened to state the right
  result.
- `_required_commercial_evidence_retry_context` now supplements explicit
  numeric installment scopes with model-recognized named-method spans only
  when one proposal overlaps multiple hard customer clauses. The derived span
  must be contiguous in both the proposal and one non-installment customer
  clause. Any locally authored brand or Pay Now/Pay Later scope stays local to
  that clause. The normal retry then requires a separate `answer_order_faq`
  call, whose active checkout metadata remains the sole commercial authority.
- A single-clause request such as `Is Home Credit 3-month 0% available?` does
  not split into an extra lookup, and a repeated generic token cannot create a
  shorter duplicate scope beside a more specific recovered method. The exact
  cross-clause integration regression proves model calls through hydration,
  provider execution, retry, claims, and composer. One-token recovery also
  requires an independently grounded typed payment-method signal. The patch
  passes 905 affected-path tests, all 1,817 repository
  tests, Ruff, compilation, diff checks, and the no-cost evaluator profile.
  Staging deployment and the paid rerun remain pending.

## 2026-09-12 - Complete retry metering and signal-driven prompt projection

- The promotion evaluator correctly exposed a usage-accounting gap in
  background extraction: the extractor reported every provider attempt but
  retained usage only from the final response. Invalid or semantically
  unusable earlier responses were reduced to error strings, causing valid paid
  usage to appear as unmetered retries.
- `runtime_v7.state_signals` now retains content-free usage, cache, and latency
  metadata for every returned extraction attempt and aggregates it into the
  existing component record. Attempts that raise without a provider response
  remain explicitly unmetered. `runtime_v7.runtime_harness` and the normalized
  turn trace distinguish metered provider attempts from missing retry usage, so
  the cost ceiling uses all observable calls without storing discarded model
  text.
- Production harness construction no longer supplies `product` as a fallback
  domain for every unclassified message. Normalized signals and trusted refs
  select product/service/order policy and schemas; ambiguous turns retain the
  general `request_capability` recovery path. This removes the 31,825-character
  product policy and roughly 19,000-character product-schema delta from direct
  contact and business-location turns without phrase matching or weakening
  product, promo, guided-action, or commercial authority boundaries.
- Because exact staging `6458fd6` already passed both dual-reader migration
  directions and canonical-writer safety, Cloud Build now defaults subsequent
  staging builds to `canonical_json_v1`. Rollback remains an explicit
  `nested_map_v1` substitution on reader-compatible code; pre-bridge rollback
  remains forbidden.
- Independent review hardened three edge contracts before deployment. Explicit
  `request_capability` schema expansion receives one replacement round even
  when `RUNTIME_V7_MAX_TOOL_ROUNDS=1`; `unmetered_retry_count` excludes the
  initial missing attempt and counts only retries; and normalized LLM span
  metadata now carries both provider and metered-provider call counts.
- Focused extraction, aggregation, trace, and production-construction tests
  pass. Broader deterministic and deployed model-backed validation remain
  required before the change can replace staging `6458fd6` or be considered
  for live Cloud Run or VM promotion.

## 2026-09-12 - Versioned Firestore strategy-state compatibility bridge

- Runtime-shaped nested Firestore maps caused the reproduced 6-19 second
  commit-thread encoding and zero-yield GC tail. `FirestoreSessionStore` now
  owns a versioned storage adapter while `SessionsGateway` and Runtime V7 keep
  the unchanged in-memory `strategy_state` dictionary contract.
- The reader accepts both the legacy nested map and `canonical_json_v1`. The
  scalar format stores deterministic UTF-8 JSON, schema version `1`, encoding,
  and SHA-256 metadata. Canonical metadata is authoritative if both formats
  exist; unknown schema/encoding, missing or mismatched hash, invalid JSON, and
  non-object state fail closed with bounded content-free diagnostics.
- The writer is controlled by
  `RUNTIME_V7_FIRESTORE_STRATEGY_STATE_FORMAT`. The initial compatibility build
  defaulted to `nested_map_v1`; after both staging transitions passed, the
  checked-in default advanced to `canonical_json_v1`. Every full state write
  atomically deletes fields from
  the opposite representation, preserving one authoritative copy. Partial
  lock and interaction-inbox writes do not touch either representation.
- Migration is lazy on the next successful full session save; there is no
  bulk historical rewrite. Rollback after enabling canonical writes must use
  the reader-capable nested-writer release, not a pre-bridge revision.
- Both generated real-Firestore transition controls passed locally: canonical
  seed to nested writer and nested seed to canonical writer each passed
  pre-switch dual-read, post-switch raw-shape and decoded equality, stale-CAS
  no-mutation, configured non-CAS creation, and exact cleanup. The latest
  switch saves measured about 370 ms and 324 ms respectively. Forty-five
  focused tests and all
  1,810 repository tests pass; changed-file Ruff, compilation, and diff checks
  also pass. Release A then passed on exact staging `6458fd6` with the legacy
  writer: dual read, canonical-to-nested switch, raw shape, stale-CAS
  no-mutation, non-CAS creation, and cleanup all succeeded. Release B then
  redeployed the same SHA with `canonical_json_v1`; its inverse migration
  canary and safety checks passed, and canonical persistence measured about
  79/102 ms p50/p95 versus about 7,483 ms nested-map p50.
- The targeted product path passed and saved in 57 ms. The complete serial
  matrix passed all 19 mechanical scenarios and 133 structural CS checks with
  zero HTTP, runtime, or tool errors; serving-session persistence measured
  79/119 ms p50/p95. Promotion is nevertheless gated because matrix usage was
  2,009,655 tokens, two provider retries were unmetered, and the available live
  baseline uses a different timeout profile. Live Cloud Run and VM remain
  unchanged pending telemetry/cost correction and one compatible rerun.

## 2026-09-12 - Firestore state-representation benchmark

- Added a separate bearer-authenticated, staging/test-only
  `/gulong/v7/session-persistence/representation-tester` endpoint. It compares
  a nested map, canonical JSON text, and deterministic gzip-compressed JSON
  through the unchanged `FirestoreSessionStore.save_session_cas` method. No
  serving session schema, reader, retry policy, GC policy, or index setting is
  changed.
- Every variant persists the same generated logical state and content hash in
  a separate pre-registered benchmark document. The 40 KiB state approximates
  the reproduced product session with 983 scalar leaves, 207 maps, 101 lists,
  and depth 11. Execution order rotates by round; representation encoding and
  CAS latency are measured separately.
- Each save is read back and decoded outside the timed CAS interval. The probe
  requires logical equality, hash equality, and the expected revision, then
  runs a stale-revision negative control per variant. Its `finally` cleanup
  deletes all exact synthetic documents and verifies their absence; incomplete
  cleanup makes the run fail.
- A local real-Firestore control with one warmup and three measured 40 KiB
  rounds passed all round-trip, revision, stale-CAS, and cleanup checks. Nested
  map, canonical JSON, and gzip JSON measured approximately 362, 220, and
  162 ms p50 end-to-end respectively; gzip stored about 2.7 KiB for this
  intentionally repetitive generated state. These local numbers are
  directional only because the reproduced 18-second tail is Cloud Run-specific.
  Seven focused tests and all 1,790 repository tests pass, along with Ruff,
  compilation, diff validation, manifest JSON parsing, and the strict change
  audit.
- Normal product-trigger build `302bbf28-1c46-4a5a-b093-3744bc823c82`
  deployed exact `90173d2` to staging revision
  `gulong-chatbot-runtime-staging-00457-8r6` at 100%. On Cloud Run, 40 KiB
  nested-map saves measured 6,637/6,690 ms p50/p95 versus 58/58 ms for
  canonical JSON and 41/47 ms for gzip JSON. At 140 KiB the same formats
  measured 18,626/19,034 ms, 91/120 ms, and 61/72 ms.
- Nested-map commits reproduced thousands of milliseconds of current-thread
  CPU and hundreds to thousands of zero-yield GC cycles; both scalar formats
  recorded zero commit-side GC cycles. All round-trip and stale-CAS controls
  passed, and the final benchmark collection-group check returned zero
  documents. This proves the mitigation mechanism but does not authorize a
  production schema or migration.

## 2026-09-12 - Firestore commit-transport diagnostic

- The prior `commit_retry_overhead_ms` bucket could not distinguish one slow
  successful commit from several SDK retries or process-local contention.
  Staging-only RPC observation now wraps the generated Firestore GAPIC
  `begin_transaction` and `commit` targets beneath their existing retry and
  timeout decorators. It records each content-free attempt's operation,
  latency, outcome, exception/status type, and retry classification without
  inspecting request metadata, document paths, transaction IDs, or payloads.
- Each CAS save also records an opaque observation ID, hashed instance ID,
  revision, process ID/uptime, process-local active-save concurrency, CPU time,
  and unattributed retry-backoff/wrapper time. The observer is explicit and
  fails open on unsupported client internals; it is hard-disabled for live and
  production environments. Existing retry limits and persistence semantics are
  unchanged.
- A bearer-authenticated, staging-only
  `/gulong/v7/session-persistence/tester` route runs generated 40 KB or 140 KB
  payloads through the exact CAS path without model calls, customer/evaluator
  reads, analytics, delivery, or tags. It writes only to dedicated benchmark
  collections and deletes its exact document in `finally`.
- Local real-Firestore validation measured 40 KB writes at 314/333 ms p50/p95
  and 140 KB writes at 452/455 ms. All eight measured saves used one successful
  commit RPC with about 1-2 ms unattributed overhead, and both temporary
  documents were deleted. This validates the decomposition but does not explain
  the Cloud Run-only 18-44 second tail. Seventy-four focused tests and all 1,786
  repository tests pass locally; staging four-worker versus one-worker evidence
  remains pending.
- Exact staging replay subsequently showed one 17.66-second successful commit
  with no retry and 16.93 seconds of process CPU. Attempt diagnostics now also
  split current-thread from other-thread CPU and add generation-level GC,
  page-fault, and context-switch deltas so the next identical replay can
  distinguish local serialization/GC work from concurrent work in the worker.
- That replay measured 16.35 seconds of current-thread CPU inside a
  17.75-second successful commit, only 20 ms of other-thread CPU, and
  487/44/2 generation-level GC collections with zero collected objects. The
  evidence localizes the delay to allocation/GC pressure while encoding the
  nested Firestore write. No retry, GC, or persistence policy was changed.

## 2026-09-11 - Isolated Firestore persistence diagnosis

- The deployed slow-save evidence was reproduced against two synthetic
  evaluator sessions: one approximately 141 KB five-turn document and one
  approximately 41 KB single-turn product document. The smaller document still
  took 19.8 seconds to persist on staging, so document size alone does not
  explain the observed 20-35 second tail.
- Firestore has no explicit field exemption for `strategy_state` in the
  serving or evaluator session collection groups. A benchmark-only collection
  group was given a temporary recursive exemption and compared with an indexed
  twin using the exact transactional full-document CAS path. The hardened
  benchmark changed 3,462 nested scalar leaves per alternating write so it
  measured index churn instead of near-no-op updates.
- Across ten measured 141 KB writes, the indexed path measured 647/695 ms
  p50/p95 and the exempt path measured 466/479 ms. Removing nested index churn
  improved p50/p95 by 27.9%/31.2%, but only by about 0.2 seconds in absolute
  terms. Index fan-out is therefore real but is not the primary cause of the
  deployed 20-35 second save delay. A compact/delta state rewrite is deferred
  because this evidence does not justify its persistence-semantic risk.
- Firestore CAS saves now collect content-free, caller-thread diagnostics:
  transaction attempt count, per-attempt read/body timing, aggregate
  commit/retry overhead, save outcome, and exception type. Payload and
  strategy-state JSON byte counts are calculated only after a slow or failed
  store operation; fast saves do not synchronously serialize the payload.
  Diagnostic overhead and instrumented-call total are recorded separately.
  Slow saves emit the same bounded fields in logs; tester debug exposes only an
  explicit allowlist. No messages, product data, profile fields, or state
  values are emitted.
- The reusable benchmark runner rejects serving and evaluator target
  collections, requires explicit isolated-write confirmation, hashes source
  identifiers, and deletes only the exact benchmark documents it creates.
  All 1,780 repository tests, focused checks, Ruff, compilation, and diff checks
  pass locally. An observability-only staging deployment and one exact targeted
  product rerun remain required before deciding whether worker/concurrency or
  Firestore client/backend contention needs a separate experiment.

## 2026-09-11 - Matched-action baseline cost comparison

- Complete staging evaluation exposed a cost-attribution defect in the
  evaluator: exact live baseline `50e5975` stopped the primary guided journey
  after two actions, while staging completed five. Aggregate subtraction
  labeled the three restored turns as a 30.28% token regression even though
  they had no baseline counterparts.
- Baseline efficiency now compares stable `case/action/occurrence` pairs only
  when both responses contain valid usage. It requires at least 80% coverage of
  baseline-observed actions, records excluded and candidate-only actions, and
  preserves raw aggregate observed workload deltas separately. The absolute
  candidate token ceiling continues to include all measured actions.
- Rescoring the immutable run artifacts produced 18/21 matched baseline actions
  (85.71% coverage) and a 1.76% matched-action token reduction, while retaining
  the 30.28% aggregate increase for workload visibility. The run remained red
  for two scenario failures and one runtime/missing-usage response; cost
  normalization did not clear those blockers. Focused evaluator tests pass
  `31/31` and changed-file Ruff is clean.
- The same complete run exposed a deployed-configuration gap in generic empty
  output recovery. With `max_tool_rounds=1`, the runtime recorded the bounded
  `empty_model_output_retry` but exited before executing its replacement round,
  producing a customer-visible resend request for an explicit address question.
  Empty/no-renderable recovery now owns one explicit replacement-round allowance
  independent of the ordinary tool budget. A regression pins the one-round
  deployment setting and proves exactly two calls followed by the reviewed
  address; no address phrase or intent-specific fallback was added.
- The main LLM gateway already classified only transient transport/provider
  failures (timeouts, 408/429, and retryable 5xx including the observed
  `ServiceUnavailableError`), but harness construction left retries disabled.
  Main-path calls now default to one bounded retry with 0.75-second backoff,
  configurable from zero to two. Every attempt consumes the existing shared
  tester provider-call ceiling and emits a redacted transport-retry event;
  semantic, grounding, and tool-contract failures are not retried.
- Exact staging `2f7bdb1` passed all deterministic, API, channel-read, and
  protected hydration layers with zero HTTP/runtime/tool errors. Its complete
  matrix stayed inside the approved limits at 1,767,963 combined tokens and
  70,555 ms p95, but remained red at 18/19 because the explicit-address case
  produced a non-renderable output and did not retry. The recovery classifier
  recognized object envelopes and fenced JSON but not an unfenced response-unit
  array. Arrays beginning with an object now receive the existing single
  replacement attempt. Bracketed brand-menu prose is a negative control and
  remains on its specialized recovery path. All 1,743 repository tests pass;
  normal staging deployment and exact evaluation reruns remain required.
- Exact `85fbf79` subsequently passed 19/19 mechanical scenarios with complete
  telemetry and zero matrix operational failures, but one high-variance run
  used eight more model calls than the prior candidate and exceeded the
  combined 2,000,000-token budget by 8,842. The safety retries and composer
  repairs remain intact. Instead, product/promo discovery guidance has been
  separated from the shared core and is included only when the capability
  profile exposes the product domain. Static prompt measurement keeps product
  and mixed-domain policy intact while reducing the order-only main prompt from
  55,901 to 49,172 characters (12.04%). The shared and composer prompts now
  explicitly prevent a confirmation question plus a second CTA. Focused tests
  and all 1,744 repository tests pass; deployed token/latency evidence is still
  required.
- Exact staging `daca2ea` verified that projection reduced the complete matrix
  to 1,733,450 tokens and the outer hydrated total to 1,772,902, with p95
  81,736 ms and a compatible 3.47% matched-action token increase over live
  `50e5975`. The complete gate remained red at 17/19 because two no-tool turns
  bypassed semantic composition: explicit head-office output was
  non-renderable, while a bare store-location request rendered the canonical
  head-office fact despite requiring a customer-area question.
- A pure business-location classifier now combines location/address, business
  entity, store/branch, and fulfillment cue groups. The post-render guard runs
  only for isolated no-tool goals without active choices or selected products.
  It preserves compliant model phrasing, uses the canonical identity source for
  an explicit-address fallback, and prevents head-office substitution for a
  bare store/branch ask. English, Tagalog, Taglish, shorthand, known-area,
  mixed-intent, fulfillment, active-state, empty-array, raw-array, and bracketed
  product-menu controls are covered. Candidate `b180a74` deployed through the
  normal product trigger to staging revision
  `gulong-chatbot-runtime-staging-00444-rfn` at 100%, with image digest
  `sha256:30b625ade499dff672c81de1e1637aaa53d92e478c8fa90115fd67c5ce34f6b5`.
- The targeted deployed recheck passed all five affected and adjacent cases.
  The complete exact-candidate run stayed under the approved hard ceilings at
  1,917,496 combined tokens and 77,981 ms matrix p95, but remained red at
  17/19. The bare store-location case still called the incompatible
  installation-location picker before the post-render boundary, and the
  delivery-policy composer omitted the provider's required 7-10-day fact. A
  root-health request also took 10,683 ms against its 5,000 ms API SLA while
  the product health route returned in 181 ms.
- The next hardening applies the business-location disposition before model
  planning and exposes no tools for isolated address/location goals when no
  reusable customer location exists. This prevents an incompatible location
  picker from creating customer-visible choice tokens; it is driven by the
  semantic cue-group classifier, not the literal `location ng store?` phrase.
- FAQ providers may now attach typed required-answer facts. The delivery-policy
  provider emits canonical Greater Manila/Lalamove and delivery-lead-time facts,
  while the composer accepts natural variants such as `7 to 10 araw`. Missing
  facts trigger bounded repair and then the provider-authored safe semantic
  answer, so correctness does not depend on an exact spiel. Candidate
  `b451b77` deployed through normal Cloud Build
  `f8073324-424e-4a94-a95f-163c2e823ae0` to staging revision
  `gulong-chatbot-runtime-staging-00445-m7q` at 100%, digest
  `sha256:7ce4d90763f87eee3d42fc1e4cf4749fa48d49b9156c50f9bd1827ec2c6029ce`.
- Four of the first six targeted requests passed, including both delivery
  variants. Two location requests failed before HTTP during a temporary local
  DNS outage. After DNS recovered, explicit address passed and ambiguous store
  location exposed zero tools but still rendered the rejected model paragraph
  before the corrected area question. The channel renderer preferred
  `assistant_text` over the guarded `runtime_final_response`.
- The boundary now synchronizes its accepted text into the renderer-owned field.
  An end-to-end channel-render regression proves the original head-office text
  cannot reappear. Exact `ffde9fe` deployed through normal Cloud Build
  `26142079-ec29-4702-9a2b-3aa1561516d5` to staging revision
  `gulong-chatbot-runtime-staging-00446-ctn`; both targeted location cases then
  passed, including zero tool exposure for the ambiguous store-location turn.
- The complete exact-target matrix subsequently passed 19/19 mechanical cases
  with zero HTTP/runtime/tool failures, but remained blocked at 95,341 ms p95,
  341 ms above the approved hard limit. It reported 1,886,073 combined tokens,
  but an audit found the deployed aggregate counted only main/composer calls:
  paid background extraction and memory compaction were stored separately.
- Complete turn accounting now projects background extraction, memory
  compaction, and image evidence into the aggregate and normalized LLM spans.
  It reports missing component usage and unmetered retries explicitly, maps the
  extractor's actual model/usage/cache/latency fields, and exposes tool latency
  in tester and trace evidence. All 1,768 repository tests pass locally. The
  prior token result is withdrawn as incomplete; exact staging deployment and
  rerun are required before any live or VM promotion.
- The two structural CS concerns in that run came from flattening every bubble
  in the five-step journey before duplicate comparison. The repeated order
  summary and missing-details reminder occurred on different state-changing
  turns, not twice in one response. Duplicate scoring is now turn-local;
  same-turn duplicate bubbles remain a failing negative control.
- Exact telemetry candidate `1f9715a` deployed through normal Cloud Build
  `3423940b-af19-45d6-8ce1-665529f80b5e` to staging revision
  `gulong-chatbot-runtime-staging-00447-dhn` at 100%, digest
  `sha256:684633ed5bdde2ce31899d42d575271605026776071accdd54de4a98a6212feb`.
  A cost-bounded two-case plus five-step journey diagnostic passed 3/3 paths
  with zero operational errors and complete model accounting, but used 41
  model calls and 926,358 tokens for seven responses. P95 was 86,913 ms.
- Tool calls accounted for only a minority of elapsed time; each response still
  had roughly 27-40 seconds beyond aggregated model and tool latency. The API
  now records bounded handler phase timings and the evaluator rolls up those
  phases, tools, and client-versus-handler overhead. Missing phase or executed-
  tool latency blocks promotion. The complete matrix is held until a focused
  exact-staging diagnostic identifies the dominant phase.
- Normal Cloud Build `5df69ffb-4f13-4273-adf8-168b97ac0606` deployed exact
  phase candidate `3479955` to staging revision
  `gulong-chatbot-runtime-staging-00448-sg7` at 100%, digest
  `sha256:bf2bb276df9b227a8b67d1dd2282fe1573536921ec9896e7c2fc58eb2e58cd0d`.
  The bounded province-schedule plus product-journey run made 35 model calls,
  used 783,534 tokens, and measured 91,253 ms p95 across six responses.
  Session persistence was the dominant non-model phase at 29,460/31,908 ms
  p50/p95; client-versus-handler overhead was only 242/484 ms.
- The Firestore save path no longer opens a full transaction after the session
  lock is held. It reads the current revision, then performs an update guarded
  by the document's exact update time; stale revision or concurrent update
  remains a conflict and the caller-owned lock is cleared atomically. New
  session creation retains create-only semantics. State assembly and remote
  store timing are now separate. Runtime-completed deterministic promo gallery
  records use a valid zero-millisecond latency rather than a missing value.
- Exact conditional-write candidate `e047694` deployed through normal build
  `42abd47d-9394-43de-8161-7084ec509b48` to staging revision
  `gulong-chatbot-runtime-staging-00449-6gs`, digest
  `sha256:6f0bbf0550aade190a88e49fbbdbf629c4c93eec52e353c929ad25b97019c85b`.
  The matched six-response run passed 2/2 selected paths and all 14 structural
  CS checks with zero operational/telemetry errors and 740,697 tokens. Remote
  save remained 31,834/35,190 ms p50/p95, so the conditional update was not an
  improvement and is reverted. The split timings and deterministic promo-
  surface latency remain. Further work should compare index exemption versus
  compact/delta persistence in a dedicated storage-safe evaluation.

## 2026-09-11 - Authenticated ManyChat hydration evaluator path

- Ordinary tester endpoints intentionally continue to disable real ManyChat
  history so versioned scenarios remain reproducible. That isolation did not
  prove the deployed loader -> conversation hydration -> model-input path.
- Added authenticated `/gulong/v7/chat/tester/hydrated`, restricted by
  `RUNTIME_V7_TESTER_HISTORY_USER_ALLOWLIST` to matching ManyChat IDs. It
  rejects request-provided history and reset, uses tester storage, disables
  analytics/profile retrieval, and forces return-only delivery.
- The response and layered artifact expose only hydration provenance/counts,
  release identity, numeric model usage, latency, and failures. They exclude
  transcript text and authentication material.
- `model-hydrated-history` is now part of pre-staging, pre-live, and complete
  profiles. Its metered usage is combined with matrix usage under the approved
  2,000,000-token ceiling; the hydrated turn uses the approved 95,000 ms
  latency ceiling. Nineteen focused endpoint/layered tests and all 1,732
  repository tests pass. Staging `9aa1c46` verified the protected route and
  successful loader refresh, but the gate remains held because the designated
  account has no usable message inside the production 30-day history window.
- The first rerun after a fresh inbound message exposed a cache-identity defect:
  a new provider event with the same text as an earlier probe could be treated
  as the cached event, suppressing the required channel refresh. Refresh
  decisions now use an available provider message ID as authoritative identity;
  text matching remains only for inputs that lack provider identity. Exact
  duplicate IDs still reuse cache, while a new ID with repeated text refreshes.
  The protected route also emits its enforced `return_only` mode directly even
  when the underlying delivery result omits that field. Seventy-seven focused
  ingress/endpoint/runner tests and all 1,733 repository tests pass locally;
  staging redeployment and rerun are pending.
- Exact staging `f965edf` then passed the protected hydration sentinel and the
  three-case smoke. Its complete profile passed deterministic, core API,
  commerce API, channel-read, hydration, technical-health, identity, and
  integrity layers, but correctly blocked on two model-matrix cases. The head-
  office case returned a non-empty JSON contract with no renderable response
  units; the province schedule case safely rendered city choices but the turn
  plan incorrectly expected its schedule obligation to be fully answered.
- The model loop now retries empty or JSON-contract output with no potentially
  renderable units once, while leaving ordinary prose to existing specialized
  repair paths. Province-level ranked slot previews remain grounded evidence,
  but a requested schedule obligation is `pending_validation` until the
  customer selects a city. This avoids weakening preview authority or accepting
  a false province-wide schedule claim. The affected 813-test set and all 1,735
  repository tests pass; staging redeployment remains pending.
- The earlier `50e5975` artifact is not a compatible complete baseline: it used
  tier `promotion`, while the complete candidate uses tier `full`, and tier is
  deliberately included in the scenario digest. A fresh exact-live `full`
  baseline remains required before final comparison.
- Fresh inbound messages from the designated account then proved the deployed
  loader end to end: the protected staging turn refreshed from
  `manychat_load_messages`, loaded six channel messages, exposed eight
  model-facing messages, returned HTTP 200 in 39,006 ms, and recorded 59,913
  tokens without persisting transcript content in the health artifact.
- A three-worker complete run created staging CPU contention and produced one
  client timeout plus one transient 502 while the backend continued. A serial
  targeted rerun returned HTTP 200 with complete telemetry for all seven
  requests and p95 75,605 ms. Semantic promotion gates now default to one model
  worker; higher concurrency remains an explicit separate load-health mode.
- Scenario contract `2026-09-11.4` allows a model tool plan to abbreviate one
  payment term only when it already preserves the customer-backed provider and
  brand pairing. Deterministic hydration must enrich that proposal to the one
  unique complete customer-authored installment scope before provider
  execution, cache-key construction, and deduplication; ambiguous scopes remain
  unfilled. Post-hydration execution stays exact.
- If composer repair leaves only duplicate prose already owned by a typed
  supporting-replacement surface, a bounded sanitizer removes just the
  duplicate sentences while retaining the same response-unit indexes and
  non-duplicate CTA. It declines to rewrite when no safe sentence remains and
  rechecks renderer and request-coverage contracts before accepting repair.
  The affected 824-test set and all 1,737 repository tests pass; a fresh staging
  build and complete gate are still required.

## 2026-09-10 - Ambiguous store-location clarification contract

- The prior evaluator/runtime guidance over-resolved `location ng store?` as a
  direct head-office-address request. The corrected general rule treats a bare
  store/branch-location request with no customer area as ambiguous: ask one
  concise free-form city/area question, do not volunteer the Makati address,
  and do not infer installation intent or show province buttons.
- Explicit ownership remains the boundary. A question that clearly asks for
  Gulong.PH's own or head-office address still receives the reviewed `1166
  Chino Roces Avenue corner Estrella, Makati City` fact; an explicit
  installation/service-area request can still use the appropriate guided or
  provider lookup.
- Scenario contract `2026-09-10.3` adds the explicit head-office question as a
  negative control and introduces phrase-tolerant forbidden-fact scoring so an
  unsolicited address cannot pass merely because the required clarification
  also appears. This is implemented locally on the feature branch and has not
  been deployed or model-probed yet. All 70 focused evaluator/release tests and
  all `1,724` repository tests pass; the consolidated all-domain prompt remains
  within budget at 98,930 of 99,000 characters.

## 2026-09-10 - Provisional promotion-health limit retuning

- The user-approved provisional hard ceilings are now p95 latency above
  `95,000 ms` and complete-run usage above `2,000,000` total tokens. The
  `45,000 ms` latency concern threshold and 10%/25% compatible-baseline token
  regression thresholds remain unchanged.
- The prior exact staging cohort (`91,788 ms` p95; `1,860,861` total tokens) is
  numerically within the revised absolute ceilings. Its immutable artifact
  still embeds the former policy, so it is historical evidence rather than a
  retroactive promotion pass; a fresh exact-target run must carry the revised
  policy and pass the remaining baseline and dependency gates.
- Boundary tests verify that equality at both ceilings is allowed and any
  value above either ceiling blocks. The combined focused set passed 39 tests,
  and the complete repository passed all `1,722` tests.

## 2026-09-10 - Independent pre-verified promotion-health evaluator

- The first in-depth candidate/baseline comparison exposed evaluator-contract
  drift as well as one real promo-grounding risk. Scenario contract
  `2026-09-10.2` now checks valid product-level Buy 3 Get 1 claims against the
  rendered provider card's brand, canonical size, mechanic, quantity, dynamic
  payable total, and evidence identities. Negative campaign-catalog answers
  require a deterministic guard plus bounded reviewed/verified wording; an
  unmatched campaign is no longer allowed to become a broad claim that a
  brand's products have no promo.
- Journey scoring now treats a location choice as unnecessary when the
  customer already supplied a location and the product click returns a valid
  schedule surface. About Brand is N/A only when every current promo card was
  rendered and none exposes that action; an incomplete render still fails
  closed. A direct store-location question requires the published head-office
  address and forbids a serviceability picker.
- The tester provider-call guard remains bounded but defaults to ten actual
  provider requests because two valid compound/promo paths required a ninth
  call. Limit diagnostics expose only a safe reservation ordinal and validated
  component/phase labels. The complete local suite now passes `1,719` tests.
- Staging `0e990e7` passed exact health identity and all five read-only commerce
  API contracts. The complete 15-case/3-journey run had zero HTTP, runtime, or
  tool errors and complete telemetry; after correcting one pre/post-hydration
  evaluator boundary, every observed customer-correctness path has a passing
  focused result. Promotion remains blocked because the complete cohort
  recorded p95 `91,788 ms` and `1,860,861` total tokens, above the provisional
  `90,000 ms` and `1,500,000` limits. A compatible `50e5975` baseline was not
  run because these absolute candidate gates already failed.
- The first deployed staging sentinel exposed two post-composer evidence-shape
  gaps before live promotion. Provider-backed payment claims are now recorded
  unconditionally after composition, including when the validated final
  composer owns the visible answer; the runtime never infers these typed claims
  from prose. The release gate also recognizes a genuinely empty `no_tags`
  plan as safe in return-only mode while continuing to reject applied tags or
  unmarked non-empty tag plans. Equivalent repeated tool scopes are counted
  once after canonicalization, while distinct method, outcome, brand, or
  payment-option scopes still require separate typed claims.
- A repeated staging smoke then exposed model variance where one sibling
  installment call retained its numeric/bank method but omitted the customer's
  shared brand. Hydration now binds a missing brand and payment option from the
  unique customer-authored installment clause matched to that method. It fails
  closed when the same term appears under multiple brands, and it never uses a
  sibling tool call as commercial authority.
- A new layered runner separates focused and full deterministic pytest,
  deterministic Moderate/High plus observability contracts, core runtime HTTP
  health, independently selectable and opted-in commerce/channel read APIs,
  and initial/in-depth/complete
  metered model gates. Profiles support pull-request, daily, pre-staging,
  pre-live, and complete use cases; repeated layer selectors override them.
- External API and metered model layers require separate explicit opt-ins.
  Read-only dependency probes require
  product, payment, transaction, partner, slot, ManyChat-history, and
  ManyChat-profile components across the aggregate profile. Component-specific
  resolved method/path allowlists, mandatory schema/value and latency
  contracts, disabled redirects, and mutation-path rejection precede transport;
  bodies and headers remain redacted from artifacts.
- The completed deployed product-to-payment journey now requires Moderate and
  High trigger actions and a versioned countable Moderate analytical record
  whose event and idempotency identity is bound to the tracked action.
  Actual tags, notes, delivery, and analytics persistence remain suppressed or
  unproven under tester isolation. BigQuery freshness checks, staging-only
  mutation canaries, scheduling, and email remain deferred.
- `runtime_v7.promotion_health_evaluator` deterministically scores completed
  deployed matrix artifacts without per-run human approval. It reports exact
  mechanical failures, technical error/latency/token health, domain coverage,
  and seven CS dimensions through disclosed structural proxies over versioned,
  pre-verified expected contracts.
- The release matrix now uses `/gulong/v7/chat/tester` and tester tracked-action
  routes with unique synthetic identifiers. It fails if return-only delivery or
  tag suppression is violated or if order/payment mutation tools appear.
- Tester diagnostics expose only bounded canonical/routing tool arguments and
  source/evidence identifiers. They now also expose bounded model/execution
  call identity and dedupe disposition, while excluding raw cache keys and
  free-form questions. Compound payment claims are validated against provider-
  owned result scope for that run instead of stale fixed commercial outcomes
  or expected response sentences.
- Required payment scopes are scored as an explicit pre-hydration model call to
  post-hydration provider-execution chain. A changed scope before deduplication
  or a required scope with no identity-linked provider execution is a hard
  failure; equivalent duplicate reuse remains allowed.
- The promotion tier contains 15 varied single-turn scenarios plus three
  multi-turn journeys. The product journey now positively validates the full
  non-mutating tracked chain through product, location, schedule, payment
  option, and payment method; promo details and About Brand retain their
  separate source-backed journeys. The three-case smoke tier retains the original contact,
  delivery, and payment customer-correctness sentinels. A typo delivery variant
  plus a reordered, two-brand, shorthand/typo compound-payment case and existing
  incomplete, ambiguous, unsupported, canonical-size, and nonlinear cases
  broaden coverage without a Cartesian-product cost explosion.
- A versioned feature-expectation profile distinguishes required enabled
  surfaces, explicitly unavailable surfaces, and intentionally disabled
  surfaces. Promo N/A requires an explicit provider-owned empty ref list;
  absent scope evidence fails closed. Baseline comparison includes the profile,
  and matrix schema v4 prevents older cohorts from being compared silently.
- Promotion/full artifacts must execute the exact required case and journey
  sets, match the scenario-definition digest, carry valid action sequences,
  exact release/SHA/environment identity, positive latency, explicit model
  usage, and internally consistent row outcomes. Partial, forged, telemetry-
  incomplete, wrong-target, or post-run modified artifacts fail closed.
- `scripts/runtime_v7_score_release_candidate.py` recomputes a saved artifact
  without another model run. `scripts/runtime_v7_export_evaluator_review.py`
  creates a checksummed, data-minimized bundle containing synthetic prompts,
  customer-visible surfaces, aggregate health, and tool names/statuses while
  excluding private identifiers, tool arguments/results, raw bodies, and logs.
  Local artifacts remain under gitignored `tmp/`; private immutable Cloud
  Storage publication and retention are deferred operational work.
- Earlier focused evaluator/matrix/layered/export tests passed 62 tests. All
  1,611 Runtime V7 tests passed, and the then-current full repository passed
  1,690; the later hardening above supersedes the final full-suite count.
  Scheduling, email
  reporting, BigQuery storage, deployment, live traffic movement, VM mutation,
  and actual ManyChat delivery were not performed.

## 2026-09-09 - General policy grounding, scoped payment contracts, and prompt ownership

- Explicit delivery questions now receive one bounded policy-evidence retry when
  the main model omits every tool call. The trigger uses typed delivery state and
  question structure rather than an FAQ answer-phrase matcher. Delivery
  statements and unrelated location questions remain negative controls.
- General delivery evidence is kept separate from case-specific serviceability.
  When the latest request names a city, area, address, or landmark that has not
  been validated, the composer must state that the exact case remains pending
  instead of converting Greater Manila policy into an exact-address promise.
- Compound payment FAQ hydration now preserves the method, brand, payment option,
  and term attached to each customer-authored clause. A sibling clause cannot
  overwrite those fields, and deduplication therefore retains distinct Home
  Credit, unbranded installment, and BPI installment checks. If the model merges
  clauses or omits a customer-authored numeric installment plan, the runtime
  scopes the emitted lookup to its own clause and schedules one bounded lookup
  for each missing plan. FAQ obligation IDs are canonicalized before request-
  coverage validation.
- The main prompt no longer repeats the complete business-identity and final-
  composition contracts owned by the composer. Composer payloads now project
  only the authorized surfaces and turn-specific voice deltas. Against live
  baseline `50e5975`, static main-prompt size fell from 38,434 to 32,624
  characters with no optional domain and from 104,433 to 98,929 with every
  domain. The payment scenario's actual composer input fell from 8,388 tokens
  across two attempts to 3,886 tokens in one successful attempt.
- End-to-end regressions cover model calls through hydration, cache keys,
  provider results, obligations, and final composition, with adjacent negative
  controls. All 28 Runtime V7 test modules passed (`1560 tests`); the directly
  affected four-file suite passed `888 tests`, and the full repository suite
  passed `1639 tests`.
- Seven metered bounded local live-model runs exercised 27 scenario turns and
  115 model calls, reporting 1,626,655 total tokens and an estimated USD
  0.55626459.
  The final delivery and original/reordered payment probes met the scoped
  correctness contracts. No BigQuery query or change, deployment, customer
  delivery, backfill, or production mutation was performed. Staging and actual
  channel evaluation remain release gates.

## 2026-09-02 - Deterministic numeric warranty-unit normalization

- A live-model evaluation card exposed a bare catalog warranty value of `5` as
  `Warranty: 5`. The model did not generate this text: product normalization
  passed the explicit catalog field through unchanged and the deterministic
  product-card renderer inserted it verbatim.
- `_manufacturer_warranty_text` now converts only wholly numeric positive
  explicit warranty values to singular/plural year text. Authored values such
  as `5 years from purchase date` are preserved, and no brand, SKU, or product
  exception was added.
- This presentation correction does not supply warranty coverage semantics.
  The separate compound warranty scenario still needs both coverage-scope and
  claim-process evidence before the composer can distinguish manufacturer
  warranty from TPP accurately.
- Verification passed 4 focused tests, all 101 product-search runner tests, 172
  related product/renderer/commercial tests, and all 1,608 local tests. No model
  call, staging run, deployment, customer delivery, or production mutation was
  performed.

## 2026-09-02 - Generic product-link and selected-card continuity repair

- Product normalization validates every URL slug against structured product
  pattern/model identity. Contradictory links are omitted from text cards and
  public card payloads with `product_link_status` and aggregate suppression
  telemetry; no brand, model, product ID, or SKU is hard-coded.
- Follow-up selection planning treats an explicit selected category over
  delivered cards as a visible-product resolution goal. The narrow no-retry
  continuity path accepts only an exact prior-card brand/model anchor for a
  category-only refinement; brand-only prose and new product filters cannot
  bypass catalog evidence.
- The local live-test pack records a synthetic successful product presentation
  only when the exact card title appears in the rendered customer response,
  restoring production-like multi-turn reference behavior without changing the
  production channel-delivery boundary.
- The final repaired exact-price/comparison/installation conversation retained
  ARIVO PREMIO COMFORT 6 and suppressed the stale Primacy 3-to-Primacy 4 link.
  The ten-scenario matrix reached 9/10 satisfactory; 1,607 tests passed. No
  deployment or customer delivery occurred.

## 2026-08-31 - Answer-first and fail-soft surface coverage (implemented locally)

- `RuntimeV7FinalResponseModel` now requires at least one response unit and can
  declare typed coverage for grounded request obligations. Runtime mechanically
  rejects empty content, unknown-only surfaces, duplicate refs, and omitted
  required surfaces, then uses the existing single bounded composer repair.
- The failed-repair fallback preserves valid initial prose, removes invalid or
  optional competing surfaces, and appends required grounded surfaces. A
  successful product, location, or FAQ result can no longer collapse into the
  generic resend response because a later repair emitted empty or unknown-only
  units.
- Direct-answer product/location surfaces are required. A broad promo beside a
  non-promo answer is optional when the latest typed signals did not request a
  promo, so exact price/product/location requests remain answer-first without a
  blanket promo ban. When a successful current-turn service/location lookup
  intentionally suppresses anonymous partner cards, its provider-backed area
  result becomes a required text obligation instead.
- The automatic first-TPP Double Warranty gallery remains. It is now typed as a
  required `supporting_replacement` for the old warranty spiel; its promo
  catalog payload is withheld from composer prose/auditing, and the composer is
  instructed not to add a separate warranty caption, explanation, or CTA. The
  existing structured product text and image gallery with tracked product
  buttons are unchanged. The old spiel is suppressed only when the warranty
  card is structurally renderable for the channel.
- Exact starter guidance is now specific: tire-help leads with one tire-size or
  vehicle question and treats promo as optional support; `How to avail?`
  answers the short purchase process before optional promo; bare `Get Started`
  asks one useful discovery question with promo only as optional support; and
  availability can still use a useful reviewed promo entry.
- Complete-size product/price requests now make `product_search` or guided
  product discovery the primary objective. A promo-only result cannot satisfy
  that objective. When a compound request makes the main model select a
  registered read-only tool outside the cheaper signal extractor's selected
  domain, the runtime recompiles once with the missing domain; it never directly
  executes an unexposed, unknown, mutating, or repeatedly unavailable tool.
- The main model no longer calls broad promo search solely because product
  cards contain TPP. The deterministic supporting policy fetches only the
  reviewed Double Warranty card, preserving the replacement gallery while
  avoiding unrelated promo expansion.
- Independent release review hardened four edge paths. Empty exposed schemas
  fail closed for every hallucinated tool, including mutations. The automatic
  warranty lookup cannot substitute a related promo when its exact reviewed
  title is absent, in which case the existing grounded text fallback remains.
  When the replacement gallery is present, composer product headers omit
  warranty/TPP fields and the response contract repairs duplicate warranty
  prose or CTA; explicit provider-backed warranty FAQ answers remain allowed.
  That exception permits the grounded answer only; an added warranty/promo-
  details CTA remains a contract violation and enters bounded repair.
  Finally, cross-domain read recovery receives one bounded replacement round so
  the normal product objective can still complete without raising the ordinary
  turn budget for unaffected requests.
- Focused deterministic verification passed `881 tests`; the required full
  Runtime V7 regression suite passed `1518 tests`. Six bounded local live-model
  runs used the development `GEMINI_API_KEY` for 29 provider calls, 538,034
  reported tokens, and an estimated USD 0.114582. The final production-like
  promo-plus-location probe grounded both requests; the final exact-size/price
  probe rendered product prices plus only the supporting Double Warranty card.
  No BigQuery query, deployment, customer delivery, backfill, or production
  mutation occurred. Staging and actual channel-delivery evaluation remain
  pending before release.

## 2026-08-27 - Final-composer repair-cause observability (deployed)

- Existing final-composer model-call records now carry a stable
  `attempt_kind`: `initial`, `format_retry`, `contract_repair`,
  `repair_format_retry`, or `semantic_scope_repair`.
- Repair attempts also carry a coarse `repair_reason` and sorted,
  deduplicated `violation_types` when typed contract violations caused the
  call. The normalized `llm_span_log.meta` projection preserves these fields
  while retaining `component="final_composer"` for metric continuity.
- The patch is observability-only. It does not change prompts, input context,
  response schemas, models, token limits, temperatures, retry depth,
  validation, fallbacks, rendering, or customer-visible responses.
- Focused deterministic validation passed `5 tests`; the full Runtime V7
  regression set passed `1502 tests`. The patch was then deployed through the
  normal staging and live Cloud Build triggers and to the customer-facing VM
  using the immutable live image digest. Bounded post-release telemetry showed
  successful initial-attempt labels and no runtime errors; no natural repair
  occurred in the window, so repair-cause production projection remains
  deterministically covered but not yet naturally sampled. No warehouse schema
  migration was required.

## 2026-08-15 - Model-owned guided location eligibility hotfix (implemented locally)

- The rejected adaptive next-best-move candidate was removed from the release
  lineage while retaining the Cloud Build traffic and exact-health routing
  corrections. The restored application tree matches stable `34fa89c` / VM
  rollback `adfa53f` before this hotfix.
- Durable `service_type=installation` with no usable service area or delivery
  address now inventories `present_serviceable_location_choices` as an optional
  candidate. The main model chooses whether that reversible location action is
  useful from the full conversation; Runtime V7 no longer forces the tool as an
  initial named tool choice.
- Prompt guidance permits one guided location move after answering owed product
  help when comparison or hesitation makes installation practicality useful.
  Product incompleteness is not a rigid veto, and the existing one-decision-layer
  renderer contract continues to prevent stacked CTAs.
- Structured guards suppress province/city surfaces for delivery, an accepted
  delivery address, a resolved city, or a completed location choice. `Cavite`
  remains province-only while explicit `Cavite City` resolves as a city.
- No new endpoint, schema, dedicated planner model, model call, schedule action,
  follow-up implementation, commercial authority, or side effect was added.
  Focused and deployment evidence will be recorded after verification.
- Deferred candidate work is preserved in
  `docs/RUNTIME_V7_ADAPTIVE_NEXT_BEST_MOVE_DEFERRED_2026-08-15.md`; do not
  restore the rejected commits wholesale.

## 2026-08-12 - Marketing images excluded from Website Inquiry routing (implemented locally)

- `runtime_v7.image_evidence` now retains Gulong-branded marketing images as
  unvalidated product/image context but does not create the routing-only
  `website_inquiry_evidence` candidate for them.
- `runtime_v7.tagging` independently rejects `gulong_surface="marketing_asset"`
  and never treats an image OCR-derived Gulong URL as routing proof. Image
  routing now requires an explicit Gulong product, cart, checkout/payment,
  order-page, or order-email surface classification. This prevents an image
  logo or promo URL from reassigning a Facebook inquiry through the downstream
  `Customer from website` flow, even when the extractor does not classify the
  creative's surface.
- Gulong product cards/pages, carts, checkout/payment pages, order pages, and
  order emails remain routable Website Inquiry evidence. Their product/order
  fields remain unvalidated until the relevant trusted tool validates them.
- Focused tagging and product-observation validation passed: `675 passed`.
  Actual August ManyChat marketing-image URLs are reserved for the required
  staging return-only probe; no deployment or ManyChat automation mutation is
  asserted here.

## 2026-08-11 - Runtime V7 deterministic intent lineage (provisional, implemented locally)

- Added the exported `runtime_v7.lead_qualification.INTENT_RULE_VERSION`
  constant with value `gulong_intent_v2_20260811`. `LeadQualificationSnapshot`
  now reports `decision_mode="deterministic"` and the same `rule_version`.
- `runtime_v7.tagging` copies those fields into each analytical Moderate
  qualification record and falls back to the exported rule version for legacy
  callers that provide an older snapshot shape.
- Moderate remains tire size plus two distinct supports among brand, location,
  and contact, but contact support now requires a plausible Philippine mobile
  rather than arbitrary non-empty text. `qualification_level="moderate"` and
  `countable=True` behavior are otherwise unchanged. Focused lead/tagging
  validation passed: `49 passed`; the broader Runtime V7 regression selection
  passed `1476 tests`.
- This is a provisional local lineage label only; no deployment, ManyChat
  mutation, production-data change, or warehouse schema migration was run.

## 2026-08-11 - Runtime V7 analytical Moderate lineage (implemented locally)

- `runtime_v7.tagging` now emits one `analytical_qualification` object whenever
  its synthetic Moderate signal is true. The object is deliberately separate
  from the ManyChat `Moderate Intent` routing action, so Website Inquiry can
  retain its routing exclusivity while Moderate remains measurable.
- API trace persistence enriches the object only where request identity and
  serving metadata are available: event/idempotency/request IDs, environment,
  user/channel/session/trace/turn context, source occurrence time, signal
  provenance, stable evidence refs, tracked-action correlation, and final tag
  application outcome. `qualification_event_id` is stable across an idempotent
  replay and is the required deduplication key for append-only trace rows.
- Promo action state now retains actual delivered presentation refs when present
  in the session ledger, alongside card/surface/choice refs. The catalog-card
  fallback is marked correlation-only and is not presentation/delivery proof.
- Focused validation passed: 216 Runtime V7 tagging/ingress/action tests and
  17 analytics-gateway tests. The audit and compile checks passed after adding
  docstrings for the bounded evidence-ref collector. No deployment, ManyChat
  tag delivery, production mutation, or production analytics write was run.

## 2026-08-11 - Commercial answer reconciliation and reviewed warranty surface (implemented locally)

- Fixed generic credit-card/installment answers that previously selected the
  first matching checkout row while the deterministic product card could show a
  different valid term. The payment FAQ projection now returns every current,
  brand-applicable installment term and only the bank/provider association
  present in checkout metadata. A specifically named bank or term remains a
  narrow lookup.
- Removed the remaining conditional authority split in product cards. Every
  product search now reconciles `/shop` installment fields against active
  `/payment/list` checkout metadata before rendering, even when the model did
  not add an installment filter. A successful empty checkout result clears
  stale catalog installment text; `/shop` data is retained only as the bounded
  fallback when checkout metadata is unavailable or fails.
- Added typed payment-field validation before FAQ hydration so generic phrases
  cannot be misfiled as a bank or installment-month value. This validates the
  extractor schema; it does not classify or rewrite the customer's prose.
- In an active tire-order context, customer wording such as down payment or
  deposit is answered as the reservation fee from current checkout metadata.
  Its purpose is explained directly and no amount is invented when the source
  does not provide one. Clear shorthand, minor typos, and informal equivalents
  are silently normalized in customer prose without quoting or explicitly
  correcting the customer; genuinely ambiguous meanings still require
  clarification.
- Removed the obsolete general `How to order?` FAQ and its aliases because its
  answer redirected customers to the website. General ordering questions now
  stay in the model-led in-chat sales flow and reuse any supplied size, quantity,
  brand, or preference.
- Corrected supporting-promo completion so only a successfully renderable,
  reviewed warranty surface suppresses the product-inclusions fallback. A
  failed or empty earlier promo call can no longer block the approved Gulong
  Double Warranty catalog surface; the paragraph remains the grounded fallback
  if that surface is genuinely unavailable.
- Focused deterministic coverage passed for varied installment terms/providers,
  brand filtering, explicit bank/term narrowing, reservation-fee wording,
  removed order FAQ behavior, warranty-surface success/fallback, and product
  quantities. Bounded live runs verified a BFGoodrich answer that reconciled
  general three-month and BPI six-month 0% terms, a two-tire ordering turn that
  mapped down payment to reservation fee and kept ordering in chat, and a
  Westlake turn whose response units contained the reviewed Double Warranty
  gallery after the product surface.
- These were local live-model harness and structural renderer checks. They did
  not deliver a ManyChat message and do not claim a commit or deployment.

## 2026-08-11 - Typed Get Started entry-action boundary (implemented locally)

- Fixed `runtime_v7.triage_seeds` so exact ManyChat starter labels with an
  approved leading checkmark decoration and optional emoji/text variation
  selector normalize to the same typed control as plain `Get Started`.
  The normalizer strips only that known platform chrome before requiring a
  whole-label match; order questions and compound size, brand, location, or
  promo messages stay ordinary model-owned free text.
- Strengthened the typed context and `runtime_v7.model_contract`: a bare
  `Get Started` begins a shopping conversation and is explicitly not an
  order-process request. The model chooses the compact natural welcome, uses
  retained details when present, and otherwise chooses one useful next step or
  an eligible reviewed promo surface. No deterministic CTA, surface, commercial
  claim, or order-FAQ routing was added.
- Passed the already-validated normal response seeds into the existing final
  composer seed context, so a later composition pass retains the same entry
  meaning rather than seeing only explicit flow overrides.
- Generalized the same model-led behavior to every low-information first turn.
  When the customer has not supplied useful tire, vehicle, brand, preference,
  or location criteria and has no specific service, policy, business, or order
  request, the model now normally uses the reviewed promo catalog as a concrete
  no-brand entry, adds a brief contextual lead-in, and asks one connected
  discovery question. This includes generic availability, assistance, tire-help,
  greeting, and ambiguous-price starters; their question form no longer excludes
  them from low-information handling. The model asks directly for size/vehicle
  or city/area instead when the gallery is unavailable, already shown recently,
  or unhelpful in context. It does not add a permission-seeking turn before a
  safe read-only lookup or available surface. Specific customer questions and
  useful details still take priority, and no deterministic promo trigger, fixed
  M/H field sequence, or welcome router was added.
- Local verification: `test/test_runtime_v7_triage_seeds.py` passed `19` focused
  contracts; the bounded `test_runtime_v7_lead_tagging.py` plus
  `test_runtime_v7_turn_plan.py` slice passed `121` tests. Compile and diff
  checks also passed.
- Independent live-model harness run
  `runtime_v7_live_pack_20260811_105042` exercised plain and decorated controls,
  an explicit order-question negative control, and a compound size/budget/
  location message. Both bare controls produced a compact welcome/next step
  with no order-FAQ call; compound details remained model-owned and were used
  in grounded discovery. The run used 7 Gemini 2.5 Flash calls across 4 turns
  with an estimated model cost of USD 0.05437. This was a local harness and
  structural channel-render review, not a delivered ManyChat check. The
  explicit order-question control gave the practical first shopping step but
  did not retrieve the full order FAQ, which remains an adjacent routing gap.
- Follow-up live-model harness run `runtime_v7_live_pack_20260811_113240`
  exercised a decorated starter, generic greeting, location-only opener,
  explicit promo question, and substantive brand-plus-size request. The
  generic and location-only turns asked directly for size/vehicle without a
  permission step; the two promo-entry turns retrieved and rendered the
  reviewed promo gallery before asking for size; and the brand-plus-size turn
  answered with grounded product cards instead of restarting intake. The run
  used 11 Gemini 2.5 Flash calls across 5 turns with an estimated model cost of
  USD 0.06657. Promo cards were structurally verified with
  `service_environment=staging`; this was not a delivered ManyChat check.
- Preference-focused live run `runtime_v7_live_pack_20260811_121746` then
  exercised bare `Get Started`, a generic greeting, and an explicit order-process
  negative control. Both genuinely low-information turns selected the reviewed
  promo catalog and composed text -> five-card gallery -> one connected
  size/vehicle question; the substantive order question did not call a promo
  tool. Eleven Gemini 2.5 Flash/Flash Lite calls across three turns cost an
  estimated USD 0.04073. The gallery, images, tracked staging targets, and card
  ordering were verified structurally with `service_environment=staging`, not by
  sending a ManyChat message.
- A wider BQ-derived matrix sampled the first nonempty customer text from each
  Gulong inquiry session dated August 1-10. The bounded query joined
  `gulong_core.inquiry_sessions` to `manychat_data.messages`, used direct message
  datetime filters, selected no customer IDs, redacted phone/email patterns, and
  processed an estimated 10,664,258 bytes in dry run. Sixteen exact observed
  openings covered high-volume automated prompts and less-common free text across
  generic assistance, greetings, location, price fragments, promos, service,
  warranty, ordering, quote requests, varied tire-size formats, brand/size, and
  compound product/payment questions.
- The first wider pass showed that generic assistance, tire-help, `Hello`, and
  `hm` could still skip the catalog because the planner treated their question
  form as substantive. The reusable correction now defines low information by
  missing usable criteria and missing a specific service/policy/business/order
  goal. It also tells the final composer not to mention or promise current promo
  cards unless a reviewed promo result/surface is actually supplied.
- Post-adjustment live run `runtime_v7_live_pack_20260811_124451` replayed those
  four affected cases plus location, same-day installation, and quote negative
  controls. All four low-information turns called the reviewed catalog and
  structurally rendered six cards; the three specific-request controls rendered
  zero promo cards. Generic assistance, tire-help, and `Hello` used text -> cards
  -> one question. The ambiguous `hm` case used one contextual text/CTA bubble ->
  cards, which passed but has slightly less ideal CTA placement. The seven-turn
  run used 35 model calls and cost an estimated USD 0.11140.
- The two successful wider pre-adjustment batches used 72 model calls across 16
  turns and cost an estimated USD 0.23371. An earlier attempt to enable explicit
  evaluator-side context caching failed before producing a scenario because the
  local Vertex cache location was unset (`locations/None`); it was rerun without
  explicit cache creation. Provider-reported cache reads remained included in
  successful-run telemetry.
- Adjacent findings outside this welcome preference remain: one Altis
  size-plus-promo turn showed promotions but omitted the requested price; an
  explicit order/installment/size turn produced an overly long generic ordering
  procedure; a BFGoodrich product/installment turn mentioned the general
  three-month option while its product cards also showed BPI six-month terms
  without reconciling both; and a Westlake size turn retained the older warranty
  text instead of a visible Double Warranty card in structural channel rendering.
  These are not treated as passes or silently fixed by the welcome patch.
- No ManyChat mutation, deployment, release, or traffic change is claimed by
  this implemented-local note.

## 2026-08-10 - Compound intent and readable commercial responses

- Corrected multi-intent planning so promo and payment evidence are requested
  together without forcing every subquestion through one tool. A payment
  lookup remains required even after an unrelated promo result exists.
- Added a targeted-promo-without-size objective. Runtime answers reviewed
  campaign mechanics and shows the matching promo card, then asks for size;
  it does not display unrelated tire sizes as though they answered an exact
  price question.
- Applied the same identity boundary to informational product turns. A named
  model without tire size, vehicle, or selected exact product does not trigger
  an arbitrary product presentation. A live return-only DOT plus Marikina
  delivery replay answered both questions directly, rendered no product card,
  and asked once for tire size.
- Clarified DOT intent ownership. When the customer asks for the DOT or
  manufacturing date of an offered product, the composer uses that product's
  exact API/presentation field and gives the value directly. If the field is
  empty, it says the DOT is not listed for that option and offers to verify the
  actual stock. It explains the week/year code only when the customer asks what
  DOT means or how to read it. Live source inspection confirmed product `12332`
  currently returns empty `DOT_SKU` and `DOT_DESC`, so no value was invented.
- Added a compact customer-facing payment-category projection derived from
  active checkout rows. Final composition uses the categories for broad
  questions while retaining exact validated facts for named-method questions.
- The commercial response validator now accepts the customer's natural
  ``credit card`` or ``debit card`` wording for the corresponding validated
  combined checkout row. It no longer forces the internal
  ``Straight Credit Card / Debit Card`` label into customer prose or replaces
  a valid concise answer with a generic fallback.
- If both model composition and its single repair still omit a validated
  payment answer, the existing last-resort commercial guard now states the
  exact provider-backed fact using the customer's method wording. It no longer
  replaces the turn with a vague promise to check payment options; runtime-owned
  promo and other presentation surfaces remain available after that text. For
  a compound promo question, the same last-resort path also preserves the exact
  reviewed offer summary before the promo card.
- Local evidence: the final repository-wide suite passed with 1501 tests, plus
  focused signal, payment, normalization, planning, and DOT contract checks. A return-only live-model
  replay answered both Apollo 3+1 and card support in one turn, rendered one
  Apollo promo card, made no arbitrary product presentation, and completed in
  three model calls under the normal tester ceiling. No ManyChat delivery,
  branch promotion, staging deployment, or production traffic change is
  claimed here.

## 2026-08-09 - Runtime contract audit and authority-boundary cleanup

- Removed seventeen unreachable private-helper tombstone tests and replaced
  the affected coverage with serving-boundary contracts. Deleted helpers are
  no longer treated as customer behavior, while token validation, surface
  authority, state transitions, and side-effect safety remain strict.
- Removed the unused deterministic service `fallback_cta_text` producer and
  propagation path. Service tools now return typed coverage, clarification,
  policy, and next-lookup facts; the model owns ordinary transition and CTA
  wording. V1 follow-up code remains because serving imports its pricing
  redaction utility, but obsolete fixed missing-field rotation and prompt-copy
  assertions were removed.
- Corrected typed-state precedence so a current customer or validated guided
  choice cannot be displaced by model-re-emitted older `customer_history`.
  Fresh customer corrections still win. Read-only product/service observations
  remain model context but cannot create product selection, fulfillment,
  high-intent progression, or order readiness by themselves.
- Product readiness now requires a trusted selected-product context or one
  durable customer/validated product identity that resolves uniquely against
  the current observation. A single visible card is not customer consent.
- Made authoritative tire size and fulfillment state binding on conflicting
  model-proposed tool arguments. Normalization events retain the proposed and
  restored values for diagnosis. Human-agent and sidewall-image size evidence
  may still scope read-only product lookup without becoming order authority.
- Narrowed partial tire-size reconstruction to one complete prior size plus an
  unambiguous one-component correction. It does not generalize to payment,
  location, schedule, or other typed fields.
- Product price-list repeat suppression now includes a commercial fingerprint
  for quantity, price/total, promo, installment, warranty, protection plan,
  and inclusions. The same product identities render again when those facts
  change, and legacy identity-only history no longer suppresses current facts.
- Verification: focused state, renderer, location, promo, transaction,
  follow-up, and composition suites passed. The final repository-wide Runtime
  V7 suite passed `1373` tests. These were local deterministic tests; no live
  model, ManyChat send, deployment, or traffic change was part of this audit.

## 2026-08-09 - Customer-choice precedence and adaptive weak-point closure

- Aligned the main and final-composer instructions around one customer
  disposition rule: first decide whether the customer is continuing, pausing,
  or closing. A pure pause/close turn does not call discovery/presentation
  tools and does not receive a sales CTA. This remains model-owned; no phrase
  matcher or customer-visible CTA rewrite was added.
- Added an abstract Gulong.ph brand-voice rule for model-authored prose: speak
  as the business with natural `kami`/`tayo`/`natin` wording for grounded
  results, avoid outside-assistant narration such as `may nakita`, and avoid
  narrating routine UI grouping. Exact inventory/service claims still require
  trusted tool results.
- Changed the guided province fallback to `Others - Outside these areas? Check
  delivery options`. A validated Others click clears stale installation state
  and gives the model a typed `recommended_service_path=delivery` with
  `service_path_selected=false`. A shared state boundary prevents the router's
  synthetic transition text from becoming customer fulfillment consent.
- Kept a listed serviceable province as valid installation context even before
  city precision is known. The model may show serviceable city choices when
  the customer is actively continuing, but it should answer a new topic
  instead of repeatedly forcing the city CTA.
- Removed renderer fallback CTA copy from compact model-visible service results.
  The later contract-audit increment also removed the unused raw producer; the
  normal transition and CTA are composed by the model.
- Stopped product and service observation stores from becoming durable
  customer-choice signals. They remain trusted read-only tool context, while an
  explicit customer fulfillment choice or correction remains authoritative
  until the customer changes it.
- Made carried ledger scoring preserve the signal's original authority with a
  recency discount. A later installation lookup can no longer replace a prior
  customer delivery choice, while a fresh customer correction still wins.
- Added model extraction guidance for unambiguous partial tire-size
  corrections and for `delivery to <area>` messages. The bounded three-turn
  signal probe retained `225/65R17`, four tires, a Montero Sport, Bacolod City,
  and delivery after correcting an earlier `255/65R17`.
- Unified rapid same-dimension guided choices at the interaction boundary: the
  newest validated button is accepted unless the customer explicitly asks to
  compare. Added the previously missing price-category commit path so accepted
  Budget, Economy, Mid Range, or Premium choices replace the prior value.
- Kept the renderer-owned product price list and image gallery intact. Exact
  SKU, price, quantity total, promo, installment, warranty, image, and tracked
  button details remain deterministic; only connective prose and the reasoned
  CTA are model-owned.
- Made explicit customer deferment a model composition rule rather than a
  phrase matcher or post-model rewrite. A live replay ended with `Sige po, no
  worries! Update niyo lang po ako bukas. Ingat! 😊` and no repeated CTA or
  surface.
- Exposed the general policy FAQ reader on mixed-domain turns so product choice
  plus delivery-policy questions can be answered in one turn. Exact free-text
  product selection is now bound before answering related fulfillment/payment
  questions, without treating the selection as order authorization.
- Automatic promo-gallery recovery now ignores a prior failed presentation
  attempt and skips only an already successful presentation. Catalog search
  remains the authority for eligible promo refs.
- Explicit price-tier/category browsing now takes precedence over automatic
  promo discovery and does not imply Budget. A return-only replay rendered all
  four category cards; a rapid Economy-then-Premium replay suppressed the older
  click and showed Premium product text, images, and tracked product buttons.
- Verification: the final repository-wide Runtime V7 suite passed `1464`
  tests. The local
  adaptive endpoint used tester state and `return_only`; it did not send any
  customer messages or mutate staging/live traffic.

## 2026-08-09 - Model-resolved promo navigation after retained tire size

- Corrected the advisory context produced by a generic promo-card **Find
  Tires** / `choose_brand` action. It no longer declares that size collection
  must precede brand choices; the main model resolves that need from the current
  conversation state, using an already known exact size or asking only when it
  is genuinely missing.
- Kept the transactional authority boundary unchanged. Generic navigation does
  not become a brand, product, or order selection, and `trusted_tire_size`
  remains limited to the stricter selected-product context used by transactional
  promo actions.
- Added a regression with a remembered `235/60R18` signal and working-memory
  summary. The click remains navigation, preserves conditional model guidance,
  and does not promote remembered context into a deterministic selection.
- The pre-change staging replay already showed the model retaining `235/60R18`
  and rendering size-scoped Budget, Economy, Mid Range, and Premium controls;
  this change removes the contradictory advisory telemetry exposed by that
  trace. No deployment is claimed for this increment.

## 2026-08-09 - Controlled channel-delivery closure

- Fixed the API/channel identity boundary found by the first controlled probe:
  synthetic runtime session IDs remain valid for isolated state, while
  ManyChat send, tag, and note operations use the real `channel_user_id`.
- Reused the promo catalog's published-title entity resolution at the common
  presentation boundary. A customer may naturally omit a leading `The`, but an
  exact named-promo request still authorizes only that reviewed campaign rather
  than the vector search's related alternatives.
- Added regressions for different runtime/channel IDs, natural named-promo
  wording, automatic gallery completion, and explicit model gallery calls.
  The two affected component files passed 116 tests before the controlled send.
- The safe `return_only` preview produced one Double Warranty card. The single
  actual controlled send then returned ManyChat HTTP 200. A bounded hidden-app
  message-history read independently found outbound event `27700344869` with
  the exact text bubbles, the square promo image, and both guided buttons. The
  curated BigQuery transcript had not ingested the event at the time of the
  check, so message history is the direct channel proof for this gate.
- The controlled send exposed a minor model-copy mismatch: it mentioned other
  current promos around a deliberately single-card presentation. This was not
  treated as permission for deterministic prose rewriting or a duplicate send.
  It remains a sampled response-quality item for later prompt/evaluation work.
- No deployment, branch merge, or traffic movement occurred in this check.

## 2026-08-06 - Model-compose first-turn openings around visible surfaces

- On every nonempty `welcome_only` first turn, the model now writes the complete
  natural opening text before any guided or deterministic surface. Runtime still
  decides whether an opening is required, but no longer inserts fixed welcome
  prose on the successful normal path. The exact welcome remains a fallback when
  the model opening is empty, malformed, or surface-first. `full_intake` remains
  only as a compatibility/failure mode, not the normal response to a greeting or
  starter question.
- Exact automated starter labels now contribute advisory intent and defer to the
  main model/tool loop. They no longer carry prewritten customer response units;
  deterministic product, promo, service, order, and payment presentations retain
  their existing authority.
- Human-support availability wording is no longer allowed to retrieve the
  product limited-stock FAQ merely because it contains `available`. Genuine
  product-stock questions and direct limited-stock FAQ questions remain intact.
- The final composer now receives a compact manifest of renderer-owned message
  roles and an explicit complete-turn contract. It can write customer-specific
  context around product, promo, fitment, service, order, and payment surfaces
  without copying their exact facts or assuming that optional content will
  always render.
- The pricing safety guard now audits model-authored structured text before
  deterministic surfaces are materialized. Exact renderer-owned price and promo
  rows are no longer mistaken for invented arithmetic, so a composer fallback
  cannot erase a valid guided product surface. Legacy unstructured responses
  retain the existing whole-response pricing guard.
- Typed claim validation now distinguishes an absent turn-plan authorization
  contract from an explicitly empty allowlist. Feature-off/no-plan turns no
  longer enter unnecessary composer repair, while an explicit empty contract
  still fails closed.
- Focused renderer, turn-plan, composer-context, and pricing regressions cover
  model-authored opening preservation, fallback-only fixed copy, opening-before-
  surface ordering, compact role-only manifests, and unsafe model arithmetic
  without loss of trusted product presentation.
- The composer contract validates only one mechanical opening requirement: the
  first structured unit is nonempty text before any surface. The prompt still
  asks the model to identify Gulong.ph on a new conversation, but wording,
  identity phrasing, greeting style, casual language, and emoji are not inferred
  as quality by deterministic code. Empty, malformed, or surface-first output
  gets the exact fixed-copy fallback.
- An unavailable location-choice provider now authorizes only the runtime-owned
  online-store business fact, while explicitly denying physical-shop-presence,
  partner-coverage, and serviceability claims. The API also records
  `provider_unavailable` without attaching choices or authorizing slots.
- The post-change live check on a new Goodyear/Mirage inquiry produced a fully
  model-authored two-paragraph opening and sidewall-confirmation CTA, with no fixed
  welcome insertion (`first_turn_opening_model_composed=true`). It used three
  model calls, 13.404 seconds of model latency, an 89.45% cache hit rate, and an
  estimated USD 0.00481259. This is structural harness evidence, not deployed
  ManyChat delivery proof.
- A separate same-day-installation probe reached the existing semantic-answer
  safe fallback after bounded composer repair. Its fixed welcome fallback was
  safe but less natural. That case remains evidence that the failure fallback
  works, not evidence that the broader semantic-repair path is solved here.

## 2026-08-06 - Behavior-neutral complete-turn human review foundation

- Added `test_packs/runtime_v7_human_response_eval_pack.json`, a 13-scenario
  complete-turn pack based on paraphrased patterns from the bounded ManyChat
  study. Brand, tire size, vehicle, and location values do not repeat across
  their populated variation fields. The pack covers direct price, missing
  fitment detail, guided discovery, correction, Double Warranty catalog use,
  pricelist plus supporting promo, location, schedule, payment, order
  correction, complaint/handoff, reactivation, and free-text product choice.
- Added `scripts/runtime_v7_human_review_bundle.py`. It consumes existing live
  pack or API debug artifacts, reuses `render_turn_for_channel` only when the
  persisted rendered payload is absent, removes prompts/profile/raw tool bodies
  through a customer-visible allowlist, redacts phone/email patterns, and writes
  UTF-8 per-case review artifacts plus an aggregate summary. Source artifacts
  must still be approved or pre-redacted because arbitrary names and addresses
  in free-form text cannot be removed reliably.
- Real renderer shapes are retained: numbered response bubbles, cards, action
  tokens, image refs, and allowlisted promo/choice/product/payment presentation
  evidence. Router targets are reduced to a configured/not-configured marker;
  request/session/trace IDs, absolute source paths, URL query secrets, and raw
  violation bodies are not copied.
- The bundler reports only mechanical structural/evidence failures such as an
  absent visible response, duplicated tracked choice tokens, multiple active
  choice layers, repeated rendered messages, non-HTTPS images, or explicit
  runtime contract violations. It does not score tone from greetings, phrases,
  emoji, length, or question marks. The seven human-CS dimensions and hard-fact
  decisions remain blank until the primary orchestrator reviews the complete
  visible episode.
- Product selection and one supporting promo action are explicitly compatible;
  the mechanical layer gate still blocks other mixed progression choices.
- No production telemetry hook was added. Existing Runtime V7 debug/probe
  artifacts already contain the full turn record, rendered content, delivery
  result, model/tool calls, token/cache usage, and state. Harness reconstruction
  is labeled `structural_only`; API `return_only` is labeled
  `customer_path_return_only`; an API-success artifact remains explicitly short
  of observed Messenger delivery.
- Explicitly empty rendered output is never reconstructed over, and missing
  customer input or visible output blocks qualitative approval. Both full debug
  envelopes and the ordinary bounded `include_debug` API result are accepted;
  compact API artifacts naturally carry less telemetry than a full turn record.
- Validation is intentionally cost-bounded. During tooling-only implementation,
  use JSON
  pack validation, `py_compile`, and
  `pytest test/test_runtime_v7_human_review_bundle.py -q`. Run the existing
  channel-renderer file once as the broader integration gate. The combined
  first-turn runtime/prompt/renderer increment requires one full Runtime V7 suite
  after focused tests pass and before commit; do not repeat that suite during the
  edit loop. A live smoke should select only the affected scenarios with hard
  model-call caps, then persist the artifact for orchestrator review.

## 2026-08-04 - Consolidate promo presentation and response context

- Production trace analysis attributed the largest expensive sequence to
  `search_promo_catalog -> present_promo_gallery -> product_search`, with the
  same reviewed campaign facts then repeated in the turn plan, final composer,
  and semantic audit. The change preserves promo/product discovery and removes
  duplicated orchestration instead of imposing a hard call cutoff.
- `search_promo_catalog` now carries the model-owned presentation decision as
  `answer_only` or `gallery_if_available`. For the latter, Runtime passes only
  current provider-issued allowed refs into the deterministic promo renderer in
  the same execution round. Explicit redisplay remains a model-declared field,
  and an answer-only result can still use the separate presentation tool when
  the usefulness of cards genuinely depends on the result.
- Independent provider lookups may be emitted together by the main model.
  Dependent lookups remain sequential; the change does not execute speculative
  tools or infer intent from raw utterance keywords.
- Composer and semantic audit now share `promo_response_contract_v1`, containing
  only exact claimable campaign facts, verified product-promo facts, provider
  scope, and renderer refs. Full candidates, retrieval scores, source
  diagnostics, and repeated composition guidance remain in the full trace but
  are omitted from later model payloads.
- Added explicit `execution_efficiency_events` telemetry for each promo gallery
  completed from the combined search contract. Existing per-component LLM
  usage remains the release monitor for main-loop rounds, composer input, audit
  and repair rates, and total calls per customer request.
- Safety boundaries are unchanged: the model decides whether a promo surface is
  useful; Runtime validates refs and facts; the renderer owns cards; exact
  product search owns SKU price and product-level promos; semantic audit remains
  independent.
- Staging exposed a mixed-ref model proposal after an answer-only targeted
  search: it contained valid current alternatives plus candidates outside the
  search allowlist. The promo renderer now preserves the allowed intersection
  and reports rejected refs as normalization metadata; a proposal with no
  allowed ref still fails closed. This is generic allowlist enforcement, not a
  campaign exception.
- Staging also confirmed that a reviewed promo-alternative gallery fully owns a
  direct promo-alternatives request. The release matrix no longer requires an
  unrelated product/category surface in that case; it still requires current
  provider refs and tracked tokens, supported promo audit, a scoped requested-
  brand negative, and no false requested-brand promo claim. This preserves one
  active choice layer and avoids an unnecessary progression/provider action.

## 2026-08-04 - Scope promo review, publication, and runtime lookup by month

- Promo source material now resolves from an explicit monthly Drive folder,
  and catalog evaluation cases are derived from that month's reviewed source
  rather than a permanent July workbook. Review workbooks use month-first tab
  names, reject a cross-month source/catalog mismatch, and archive only within
  the same month. Infrastructure no longer hardcodes the July workbook ID.
- Source-backed promotional warranty entries may omit a brand only when their
  promo type is `warranty`; all other commercial promo types retain the brand
  and source-evidence publication requirements. This supports The Gulong Double
  Warranty without creating a general brandless-commercial escape hatch.
- The catalog sync preserves exact source operational URLs after AI extraction.
  Runtime promo mechanics include a bounded operational URL row after the
  standard mechanics, so the Michelin cashback Google Form remains usable in
  the customer response instead of being silently truncated.
- Runtime routing obtains the current catalog titles from the active published
  catalog. An exact title request is constrained to `search_promo_catalog`
  before general FAQs; ordinary warranty questions remain on the normal FAQ
  path. The rule is catalog-data driven rather than tied to a brand, title, or
  SKU constant.
- August catalog `catalog-202608-5f4ddb23ee0c-v2` passed `11/11` AI,
  `11/11` human, and `6/6` eligibility review rows and was approved at
  `2026-08-04T01:19:55+08:00`. Validation and production evidence are recorded
  in `docs/RELEASE_HISTORY.md`.

## 2026-08-04 - Keep promo negatives within provider coverage

- Early production observation of the composition-simplification release found
  a successful reviewed-catalog search followed by a global denial of a Buy N
  Get M offer. The reviewed campaign catalog had returned no allowed campaign
  ref, but exact product search independently owns product-level quantity,
  bundle, voucher, discount, price, and SKU promo facts.
- Empty reviewed-catalog results now tell the composer to state only the exact
  scoped no-match. Exact promo price or applicability remains pending until an
  exact-size product search runs. The promo semantic audit independently types
  a cross-provider negative as unsupported and sends it through the existing
  single evidence-only repair path.
- This is a provider-coverage contract, not a Buy 3 Get 1, Michelin, SKU, or
  response-phrase exception. It adds no classifier, provider, composer, or
  audit call and should avoid repair when the initial composer follows the
  compact result guidance.
- Human-CS review of the first staging repair kept the fact boundary but exposed
  the phrase "general catalog search." Customer-facing composition and repair
  now express only what can be confirmed and what input is needed next; internal
  catalog, search, provider, evidence, scope, review, and validation terms stay
  out of the reply.
- A second human-CS replay showed that a source-free phrase such as "wala
  tayong nakitang promo sa ngayon" could still sound global. With no exact tire
  size and no exact product evidence, the contract now keeps product-promo
  availability, applicability, and price pending and asks only for the size.

## 2026-08-03 - Simplify answer composition and semantic repair

- Trace-backed cost diagnosis found that expensive turns were repeating the
  same reasoning across the final composer, broad contract repair, and a later
  evidence-only semantic repair. The broad repair retained too much stale
  customer/progression context and could recreate the exact unsupported meaning
  that the independent audit had rejected.
- A semantic answer-goal or promo-fact failure now goes directly to one clean
  evidence-only recomposition. The repair retains provider facts, typed claim
  and renderer contracts, required FAQ answers, voice guidance, and continuity;
  it omits generated drafts and customer-origin context as factual anchors. The
  repaired result is independently audited once. If it still fails, the
  existing authored safe fallback runs instead of a second semantic composition
  cycle. This is a call-graph simplification, not a hard per-turn call budget or
  a retry ban; transport and schema-format recovery remain available.
- The first deployed candidate exposed an audit-disagreement edge case: the
  first audit correctly classified a delivery-policy answer as relevant but
  over-scoped, while the repair audit later labeled the same authored policy
  misaligned and caused the fallback to hide it. Safe fallback relevance now
  follows the first audit that evaluated the normal composed answer. When that
  audit found the authored goal aligned, partial, or unresolved, provider facts
  remain visible with the existing exact-case-pending boundary; only an
  explicitly misaligned initial answer is omitted. This uses typed audit state,
  not place names or response-text matching, and adds no model call.
- Answer-only FAQ and business-contact turns now compact the existing final
  composer packet. They keep the latest request, recent-turn continuity,
  conversation state, trusted tool results, exact evidence refs, required FAQ
  facts, and voice/commercial contracts while removing stale AWM, lead gaps,
  product/service/order progression, decision packets, and generated draft
  prose. Mixed answer plus commerce/service turns retain the full packet.
- Payment FAQ composition uses that answer-only boundary even when no separate
  checkout claim list is present. The composer answers the authored payment
  fact first and may stop after the complete answer; an unrelated location,
  product, or service question cannot be framed as necessary to validate a
  general payment answer.
- Promo result authority is now consistent across the composer and claim
  validator: provider-issued `allowed_promo_refs` from a successful catalog
  search join the canonical evidence-ref set. A proactive grounded promo is not
  treated as an omitted customer request merely because the latest customer
  turn asked about another shopping step. Direct promo requests and every
  visible promo claim remain independently audited.
- `prepare_payment_request` evidence now authorizes both order and payment claim
  categories, matching the provider payload's actual responsibility without
  widening authority to customer text or prior assistant prose.
- Local validation passed the focused turn-plan/transaction gate (`181` tests),
  the complete product/observation harness (`579` tests), the complete Runtime
  V7 suite (`1,263` tests), and the full repository suite (`1,326` tests). Ruff,
  `py_compile`, and `git diff --check` passed. Deployment evidence is recorded
  separately in `docs/RELEASE_HISTORY.md` only after the exact candidate is
  built and observed.

## 2026-08-03 - Contain unrelated payment-decision model calls

- Live runtime telemetry showed that the pre-composer
  `payment_query_decision` evaluator ran on approximately 99% of requests in
  recent releases, including product, location, promo, and ordinary FAQ turns.
  This contributed nearly one avoidable model call per unrelated request while
  adding no commercial authority.
- Pre-composer payment completion now runs only when the model/tool path has
  already established payment scope through a typed payment decision or a
  payment-scoped `answer_order_faq` result. An existing typed negative decision
  remains reusable; an unrelated turn records
  `payment_policy_lookup.reason=no_payment_scope_evidence` without another
  model call.
- The boundary is evidence-based rather than keyword-, provider-, brand-, or
  SKU-specific. The main model/tool loop still interprets the customer request,
  active `/payment/list` data remains the only payment authority, and the final
  composer keeps ownership of customer-facing language.
- No renderer, order-state, tag, ManyChat delivery, or provider-fact behavior
  changed. Broader composer and semantic-audit simplification is intentionally
  deferred until this containment change has production call-rate evidence.
- Regression coverage proves both sides of the invariant: unrelated product
  and non-payment order-FAQ turns cannot invoke the payment evaluator, while
  payment-scoped turns keep the existing typed lookup and composition path.
  Local validation passed the transaction suite (`111` tests), the focused
  product/payment gate (`689` tests), the complete Runtime V7 suite (`1,253`
  tests), and the full repository suite (`1,316` tests).

## 2026-08-02 - Preserve reviewed informational promo actions

- Human-CS review found that the release matrix could pass a tracked
  `Promo Details` journey even when the visible second turn fell back to the
  generic ongoing-promos FAQ. The click carried valid reviewed offer and
  mechanics evidence, but the enabled general turn planner bypassed the
  existing deterministic informational renderer. A later semantic FAQ audit
  then treated the generic FAQ as the answer owner and removed the requested
  promo details.
- Validated informational promo actions now resolve before general turn
  planning in both ordinary and batched tracked-interaction modes. This applies
  to every reviewed promo/brand action type, adds no brand or offer exception,
  performs no extra provider/model call, and cannot authorize facts outside the
  reviewed action context. Other tracked interactions remain model-led.
- Regression coverage uses a neutral test promotion across both interaction
  modes and verifies that reviewed offer/mechanics text is retained with zero
  LLM or tool calls.
- The exact staging matrix then exposed a reusable semantic-audit ambiguity:
  the audit correctly rejected an exact-area serviceability confirmation but
  sometimes treated the safe boundary "exact details still need checking" as
  an invented validation workflow. The audit contract now distinguishes an
  epistemic limitation from claims about who validates, how validation works,
  required customer input, or a promised outcome. Only those concrete process
  claims need separate authority.
- The release matrix recognizes About Brand's reviewed zero-call path only
  when the exact published profile is visible and no tool/composer call ran;
  this replaces its stale requirement for an LLM composer without weakening
  source or surface checks.
- A policy answer that exhausts semantic composition/audit repairs now records
  the typed `answer_goal_safe_fallback` status instead of the generic renderer
  fallback. The release gate accepts it only with the matching guard event, a
  non-supported semantic audit, the required successful authority tool, and
  complete human-CS review of the authored response. Arbitrary renderer
  fallbacks remain failures; this makes the existing evidence-backed fail-closed
  path observable without pretending model composition succeeded.
- Human review of the first mechanically green typed-fallback matrix caught a
  vague "please clarify" delivery response. The selected authored FAQ covered
  general delivery availability/path and timing, but its semantic answer-goal
  metadata described timing only; an audit could therefore mark the relevant
  evidence misaligned and omit it from the safe response.
- Delivery-process evidence now declares its complete general answer goal while
  preserving the exact-location boundary. The release case also requires the
  authored Greater Manila path, courier, and lead-time facts to be visible, so
  internal guard evidence alone cannot pass a non-answer. This is policy-type
  based and contains no place-name routing exception.
- Fresh staging delivery replays then exposed a narrower composition issue:
  model repairs could state the exact case was pending but frame an otherwise
  useful shopping input as the means to validate that case. The semantic audit
  now treats any "to verify X, provide Y" dependency as a concrete process
  claim unless separately authorized. An optional CTA remains allowed only
  when clearly separated as serving another customer goal.
- The focused delivery/gate suite passed `70` tests and the full repository
  gate passed `1,315` tests.

## 2026-08-02 - Typed payment categories and owned FAQ guidance

- Varied staging probes found three failures that the standard release matrix
  did not cover: a DOT/manufacturing-date question retrieved a warranty chunk,
  a formal-quotation request was misrouted through generic location recovery,
  and a compound `Maya Credit` plus e-wallet-category question treated both
  phrases as supported/unsupported wallet names.
- Added authored product and order FAQ entries for DOT code interpretation and
  formal company/corporate/fleet quotations. These answers state the useful
  next step while preserving the authority boundary: the actual tire owns its
  exact DOT, and CS/provider validation owns a final quotation, availability,
  taxes, totals, and order state.
- Runtime V7-owned product policy now takes precedence over semantically nearby
  RAG chunks. The retriever may help select an FAQ goal, but it cannot replace
  an authored policy answer with unrelated evidence after that goal is chosen.
- Payment-query scopes now declare `named_method` or `method_category`.
  Concrete known or unknown providers continue through `/payment/list`
  validation. Open categories carry a bounded type (`e_wallet`, `card`,
  `installment`, `bank_transfer`, `financing`, or `all_methods`) and receive a
  separate provider-backed catalog result, optionally filtered by payment
  option. They are never converted into unsupported provider lookups.
- The compatibility scalar used by the main FAQ tool is derived from the first
  explicitly named scope, not simply the first clause. Category-first compound
  questions therefore preserve customer order without turning that category
  into the provider lookup.
- Wallet canonicalization now matches standalone rails plus benign payment/QR
  qualifiers. A distinct credit, loan, card, or installment product retains
  its full typed name for provider validation. Background-signal and checkout
  paths share this helper so their interpretation cannot drift.
- Strict payment matching is terminal: once exact aliases/catalog labels and
  bounded close matches reject a proposed financial product, generic substring
  matching cannot discard a distinguishing loan/credit suffix. Submitted order
  payloads reuse one authoritative payment-row label instead of concatenating
  row prose, preserving valid payment-request progression without fuzzy match.
- Provider payment conflicts now render from checkout metadata even when no row
  is selected. They cannot fall back to the legacy static installment FAQ and
  introduce a contradictory bank/rate claim.
- If the capability profile already selected a strong authored FAQ but the main
  loop answered without calling its exposed tool, Runtime performs one forced
  evidence retry using the selected FAQ id. This is generic across FAQ domains,
  suppressed after another retry or during an active payment choice, and adds
  no classifier/model call to normally grounded turns.
- The typed payment semantic gate now applies only to resolved payment,
  installment, and delivery-payment FAQ identities (or explicit typed payment
  scopes). Other `answer_order_faq` goals such as formal quotations cannot be
  rejected merely because the correct payment decision is
  `no_payment_request`.
- The API pre-composer cleanup follows the same boundary: a negative payment
  decision removes payment-policy order results only, rather than deleting
  every non-payment result behind the shared `answer_order_faq` facade.
- The typed payment planner and its existing ambiguity audit now distinguish a
  concrete duration/rate installment term from an open request for an entire
  method category. Concrete terms retain shared brand and Pay Now/Pay Later
  scope for provider validation; broad category questions still receive a
  category list. This changes no normal-path model-call count.
- Regression coverage includes current/legacy DOT routing, formal-quotation
  progression, schema backward compatibility, category exclusion from named
  lookups, category-first scope identity, provider category filtering, stale
  payment-copy exclusion, FAQ evidence recovery, and positive/negative wallet
  alias cases. The adjacent gate passed `693` tests; the repository gate passed
  `1,309`.
## 2026-08-03 - Month-first promo approval tabs and Double Warranty carry-over

- Refreshed the August mechanics compilation after Marketing supplied the
  Michelin cashback Google Form. The obsolete missing-submission-channel note
  was removed, and pending catalog `catalog-202608-5f4ddb23ee0c-v2` now stores
  the exact form URL as a separate, reviewer-visible mechanic. Operational
  source URLs are preserved deterministically after AI extraction so model
  summarization cannot silently remove a claim or submission destination.
- Fixed same-month workbook refresh ordering. Completed tabs are renamed first,
  replacement visible tabs are created, and only then are archived tabs hidden;
  this avoids the Google Sheets rejection caused by temporarily hiding every
  sheet in the workbook.
- Added the July `THE GULONG DOUBLE WARRANTY` mechanics and original poster to
  the August Drive source package. The current pending catalog contains six
  promo/warranty parents, six visual cards, and 50 mechanic chunks. Its 11
  source-derived retrieval cases
  all report `AI_PASS`; human review remains `PENDING`.
- Reworked review storage around one dedicated workbook per catalog month in
  the separate `Promo Catalog Reviews` folder. August now uses
  `Promo Catalog Review - 2026-08`
  (`1c8n7geVXPRRYiAW-IqJF6I3l-z2_EAFPJ4LFDEOasQg`), whose first tab is
  `AUG 2026 APPROVAL - START HERE` and whose remaining six tabs contain only
  August review data. The former shared workbook was renamed
  `Promo Catalog Reviews - Legacy Archive`; it retains the historical tabs and
  is no longer authoritative for August.
- The stable runtime contract still uses logical `Version`, `Promos`, `Cards`,
  `Mechanics`, `Eligibility`, `Brand Profiles`, and `Evaluation` keys. The
  Sheets integration maps those keys to month-labeled physical tabs when it
  writes or reads a catalog, so publication validation remains deterministic.
- Same-month source revisions may archive and replace tabs within that month's
  workbook. A deterministic guard rejects any attempt to reuse a workbook that
  already belongs to another catalog month. When no workbook ID is supplied,
  sync reuses only a Firestore version explicitly marked with
  `review_workbook_scope=monthly`; otherwise it creates
  `Promo Catalog Review - YYYY-MM` in the review folder.
- Source discovery now accepts either a parent containing a `YYYY-MM` folder or
  a Drive folder that is already the requested month's root. This matches the
  supplied August folder layout without a one-off source adapter.
- The promo catalog job infrastructure no longer pins a legacy review workbook.
  An empty `PROMO_REVIEW_SPREADSHEET_ID` lets the sync resolve and reuse only a
  Firestore-recorded workbook for the source month. Deployments may also set
  `_IMAGE_TAG` so the job runs the same immutable runtime image that passed the
  release gates instead of following a mutable tag.
- Publication validation now applies the same brand rule as extraction:
  customer-wide warranty content may be brandless when it remains source-backed,
  while commercial promo types still require at least one reviewed brand. This
  keeps the Double Warranty record valid without weakening evidence checks.
- Runtime promo mechanics keep the first four reviewed conditions plus one
  bounded exact operational URL mechanic, so a later claim-form link cannot be
  dropped merely because it follows the offer summary and eligibility rows.
  When the customer names an exact active catalog title, the first model round
  is constrained to `search_promo_catalog` so an adjacent general FAQ cannot
  pollute the answer. Matching is derived from the active reviewed titles, not
  campaign keywords.
- Prior August drafts `catalog-202608-2258fde5883c-v2` and
  `catalog-202608-4be43c193cc9-v2` were superseded. The
  current pending draft now points to the dedicated August workbook. The
  active pointer remains `catalog-202607-3574297cf6ef-v2`; no publication,
  staging deployment, live deployment, or traffic change was performed.
- Focused builder/sync validation passes `34` tests. The directly affected
  builder, sync, and runtime promo suite passes `90` tests; changed-file Ruff and `git diff --check`
  also pass.

## 2026-08-01 - August promo catalog build and source-derived review gates

- Superseded the incomplete four-promo draft
  `catalog-202608-c06c95ca5c5e-v2` and built pending catalog
  `catalog-202608-2258fde5883c-v2`. The corrected immutable draft contains five
  promo parents, five visual cards, 28 mechanic chunks, three brand profiles,
  and all five original poster binaries: the new BFGoodrich and Michelin
  offers, reviewed Michelin/Apollo 3+1 carry-overs, and Michelin Passion
  Experience through August 31. Eight private build objects are present.
- The copied August `MANYCHAT_MECHANICS.docx` is byte-identical to the reviewed
  July source (`sha256`
  `44f57a92853c006b28ce5a0130bc0882b78d79016e441b6f8f3164691f888e97`).
  The review workbook archived the superseded tabs and now exposes the new
  fixed-name tabs as `PENDING`. The active pointer still references
  `catalog-202607-3574297cf6ef-v2`; no public poster, staging, live, or traffic
  state changed.
- The publication review matrix is now derived from the promos in the pending
  version. Every enabled promo gets an exact retrieval case, brands with
  multiple offers get a brand-scope case, available 3+1 offers get positive
  and unavailable-brand controls, and expired/unrelated controls remain
  mandatory. This removes permanent July-specific Michelin Japan and Yokohama
  requirements without weakening the fail-closed human review gate.
- Added `cashback` as a distinct catalog promo type. A post-purchase verified
  payout is no longer mislabeled as an immediate fixed discount, and the new
  Michelin draft extracts directly as `cashback`.
- Reviewer decisions now record that `every tire` means every eligible tire:
  BFGoodrich is PHP 1,000 off per eligible Advantage Touring tire with no
  stated maximum, while Michelin is PHP 1,000 cashback per eligible pattern
  capped at PHP 4,000 per qualified purchase. Michelin cashback and 3+1
  stacking is confirmed, and Michelin Passion Experience remains active.
- Live validation found `MICHELIN` in `/promo_brands`; eligible Michelin
  `/shop` rows simultaneously carry `promo_tag=1` and an active
  `PHP 1,000 CASHBACK PER TIRE` banner. Current Gulong.ph product pages show the
  cashback badge, although the website does not explicitly state stacking.
  The catalog therefore describes cashback as a separate post-purchase claim
  that may stack with 3+1, not another checkout price reduction.
- The carry-over posters contain `1 YEAR Tire Protection` and
  `5 YEARS WARRANTY` badges. Those creative disclosures are noted for review,
  but the 3+1 mechanics do not authorize coverage details; product and
  published warranty sources remain authoritative.
- Draft evaluation now applies the same explicit-offer constraint boundary as
  Runtime before grading result order. A semantically related cashback or
  event record cannot make an explicit 3+1 review case fail or pass. All ten
  source-derived evaluations pass on the pending vectors. Focused builder/sync
  validation passes `28` tests; the broader promo regression suite passes
  `124` tests. Changed-file Ruff and `git diff --check` pass.
- Human approval and publication were intentionally not performed. The final
  Michelin cashback claim form URL or submission email is still missing from
  the supplied mechanics and is recorded in the review workbook.

## 2026-08-01 - Complete semantic grounding plans from failed staging cases

- Exact staging candidate `7185d1b` passed the focused delivery matrix
  mechanically but failed human-CS and authority review: repair changed the
  typed category while preserving an unsupported exact-area delivery promise.
  Typed claim declarations alone therefore were not sufficient evidence that
  the visible prose matched the declared meaning.
- General-policy FAQ turns now receive an independent structured semantic audit
  of the complete customer-visible response. The auditor compares authored FAQ
  facts, scope boundaries, required-answer coverage, separate availability
  authority, and the customer's request. It does not use customer-wording,
  place, brand, SKU, or provider exceptions.
- A composer repair is audited again. A repeated unsupported/incomplete result,
  or an invalid audit, fails closed to the authored policy answer plus a
  neutral statement that exact request details still require validation. This
  fallback is reserved for the failed semantic boundary; successful
  conversational answers remain composer-owned.
- Added `faq_facts` to the structured final-response schema and passed the
  authored answer/applicability through the required-FAQ turn-plan record so
  both normal composition and repair see the complete positive scope.
- The first full pinned candidate matrix showed the repaired policy answer was
  safe, but its second audit exhausted the original 900-token response budget
  while producing the small structured verdict. The bounded audit budget is
  now 1,600 tokens for both policy and promo fact audits so model reasoning and
  the required schema can complete; invalid output still fails closed.
- Renderer fallback remains a runtime safety boundary, not release evidence.
  The candidate matrix continues to require a normal used/repaired composer
  result for the delivery-policy case.
- Pinned replays then showed both policy and promo repair repeating meanings
  already rejected by their semantic auditors because the generic repair packet
  still contained the invalid assistant response and draft fields. Semantic
  scope repair now removes those generated anchors and recomposes from the
  trusted tool results, turn plan, renderer surfaces, and explicit violations.
  Other renderer/voice/interaction repairs retain their existing context.
- Exact candidate `614bd20` then produced a semantically supported no-match
  promo answer, but the typed claim contract rejected the model's synthetic
  tool/path citations because a successful empty promo search exposed no
  authorized result-level ref. Successful promo searches now emit a stable
  `promo_search:<catalog_version>:<scope_digest>` evidence ref derived from
  the normalized search scope. It authorizes the reviewed search conclusion,
  including an empty match, but cannot authorize offer mechanics absent from
  `allowed_promo_refs`. The compact tool packet and promo semantic-audit
  context preserve the ref through composition and repair.
- On exact candidate `bac61d2`, the scoped promo ref closed the promo failure,
  but three successive delivery drafts still converted a general-area policy
  into a customer-specific serviceability confirmation. Each independent
  audit rejected the overclaim and Runtime failed closed correctly, but the
  strict matrix does not accept fallback as normal composition. The last
  semantic retry now receives an evidence-only composition packet: authored
  policy/promo facts, typed claim and renderer contracts, and voice guidance
  remain; raw customer wording, recent turns, working memory, background
  signals, tool arguments, and generated drafts do not. This is a generic
  provenance boundary for any case-specific context, not a place or phrase
  rule, and the corrected output is audited again against the original request.
- Exact candidate `0d0b845` confirmed that context isolation removed the named
  place but did not by itself remove the conversational implication: stating
  the broader delivery policy alone in direct response to a narrower request
  can still read as confirmation. Semantic repair now carries a typed scope-
  resolution contract after an unsupported policy inference. The model must
  state both the supported general policy and that the exact case remains
  unconfirmed/pending; this applies to any case-specific inference and remains
  subject to the independent whole-response audit.
- Candidate `80c54f3` passed the affected matrix mechanically (`2/2`), but
  human-CS review held promotion because the repaired delivery reply described
  tire size and brand as prerequisites for checking exact-area delivery. The
  policy auditor now treats a claimed validation prerequisite as a factual
  process claim. An unrelated lead or shopping question can remain as a
  separate optional CTA, but it cannot be framed as required or sufficient to
  resolve a pending policy fact without provider authority.
- The pinned `2595a06` Toyo replay then removed invented alternative offers but
  the independent promo audit still marked the answer incomplete because the
  customer had requested valid alternatives. Successful promo-search evidence
  now carries an explicit reviewed-scope outcome into the audit: zero allowed
  refs means no verified applicable promo was returned for that exact search
  scope. Stating that scoped absence is a complete truthful alternatives
  answer; it is neither a global no-promo claim nor authority for an absent
  offer. The evidence-only retry also receives an ordered list of required
  answer meanings for the requested negative, no verified alternative, and
  non-promo category navigation.
- Exact merged promotion candidate `f603145` passed three of four final staging
  smoke cases. The repeated semantic repair again knew the scoped negative but
  described ordinary price categories as promo alternatives; the generic
  renderer fallback then dropped the required category surface. Repeated promo
  audit failure now uses a bounded provider-fact fallback: it states only the
  typed scoped no-match and no-verified-alternative outcome, then preserves any
  price-category surface with an explicit non-promo shopping role. Normal copy
  remains model-owned; this deterministic path activates only after all audited
  composition attempts fail and contains no brand, size, wording, or promo
  exception. Runtime records this as `promo_fact_safe_fallback` with a dedicated
  guard event. The release matrix accepts that status only for a promo-audited
  case with the guard present; all existing provider, unmatched-scope, and
  required-surface assertions still apply.
- The first 0%-traffic live-tag smoke for `0afb672` passed mechanically but
  human-CS review caught a subtler accepted overreach: the model said no other
  promo was available for the requested size, while the reviewed empty scope
  was still brand-specific. An independent audit can itself vary, so final
  commercial wording cannot rely on its semantic verdict alone. Whenever typed
  evidence has an unmatched requested brand, a successful scoped empty result,
  and an ordinary price-category surface, Runtime now owns the visible result:
  the model still chose the search and progression, while deterministic code
  renders the exact scoped no-match/no-verified-alternative facts and labels
  the categories as non-promo navigation. This condition is derived entirely
  from provider results and renderer state, not customer keywords or catalog
  exceptions.
- Pinned live-model probes found two intermittent typed-plan disagreements.
  Every multi-query payment plan now receives one bounded semantic audit; a
  single-query plan is also audited when it conflicts with exposed capability
  or typed option shape. The audit removes promo/price-only false positives and
  repairs coordinated brand/payment-option scope without deciding provider
  support.
- The audit also activates when a model combines product brand and canonical
  transaction option in one typed payment-option field. Runtime recognizes the
  enum-shape violation mechanically; the audit model separates the brand and
  decides which coordinated queries inherit it.
- The audit receives the current canonical tire-brand list. This prevents a
  bank, card issuer, provider, or installment label from occupying the typed
  product-brand field while keeping entity-role interpretation model-led and
  catalog-driven.
- After a validated product click, service retry now accepts normalized order
  readiness as the fulfillment source when the fresh signal ledger has no
  separate service-type row. A concrete installation area plus product context
  therefore reaches read-only slot lookup instead of asking the customer for a
  date before showing current options.
- A fresh staging failure showed that the model could correctly authorize a
  delivery-policy lookup while labeling the broader turn as a concrete
  location lookup. Policy recovery now consumes the typed business-fact and
  grounding-tool fields independently of that broader label. The semantic
  prompt also makes explicit delivery/order questions take precedence over a
  supplied area, and bounded debug output records the complete decision.
- The next exact staging replay executed that policy tool but returned
  `no_match`, so the response safely avoided a serviceability claim while
  still failing to answer whether delivery is generally offered. Semantic
  policy recovery now passes `service_type=delivery` as structured retrieval
  scope. The FAQ facade maps that scope to the existing authored general
  delivery-process record and explicitly forbids treating it as exact-address
  coverage or date authority.
- The first typed-scope candidate still failed human-CS review even though the
  FAQ result was `ok`: the composer categorized its initial sentence as
  service availability, but the positive claim contract had no stable FAQ ref,
  so repair safely removed the answer. Successful FAQ results now expose a
  namespaced evidence ref and authorize `faq_facts`. Composer guidance treats
  general published policy as FAQ fact while reserving exact-address coverage
  for separately validated `service_availability`. A `no_match` result cannot
  authorize either category.
- A second exact staging replay proved that category authorization alone was
  insufficient: the first draft still proposed a narrower address-level claim,
  and repair dropped the answer rather than narrowing it. Successful current-
  turn FAQ calls are now listed as required grounded answers in the turn plan.
  Initial composition and repair must preserve the supported FAQ scope and may
  leave only the narrower unvalidated point pending. This is derived from typed
  tool evidence and claim categories, not from delivery wording or place names.
- The next staging call ended with `finish_reason=length` before producing a
  valid structured composer object, so the existing path fell directly to
  legacy draft text and failed mechanically. Invalid or truncated final-
  composer format now receives one bounded low-temperature retry. The retry
  reuses the full typed turn plan, required surfaces, FAQ answers, commercial
  claims, and evidence allowlist, asks for the schema object immediately, and
  then passes through the unchanged renderer/claim/voice/service contracts.
  A second invalid format still fails closed to the existing fallback.
- The following staging replay produced a valid first draft with typed claim
  violations, then truncated the contract-repair response. Format recovery now
  applies once at both structured boundaries: initial composition and contract
  repair. A repair-format retry uses the original compact composer context plus
  the typed violations and allowlists, avoiding the larger invalid draft while
  retaining the same evidence and validation requirements.
- The location semantic decision owns two independent axes: the viable
  location-choice classification and a paired business-fact/read-only-tool
  authorization. A concrete area cannot suppress a delivery/order fact lookup.
  Delivery
  feasibility, availability, fees, and process questions cannot silently fall
  through to ungrounded prose; a location mention alone still authorizes
  neither province choices nor a commercial fact.
- Payment semantic output now carries a bounded ordered list of every
  independent customer question. Runtime validates the shape of each proposed
  method, product-brand, and Pay Now/Pay Later scope, then resolves every scope
  against the canonical checkout provider before composition. The model
  interprets clause relationships; it does not decide support or eligibility.
- Canonical checkout resolution receives each typed payment scope in isolation.
  A bank or term from a later clause cannot contaminate an earlier installment
  query. Policy deduplication also removes an unscoped row only when the scoped
  replacement contains a claimable canonical fact; a conflicting proposal
  cannot erase a validated unsupported-method result.
- Product-progression decisions now receive bounded typed promo-result counts,
  including applicable refs, requested-scope matches, and provider
  availability. After a verified no-applicable-promo result for a confirmed
  size, the model must reason to a useful product/category continuation instead
  of ending at the negative fact or opening an unrelated location question.
  Provider errors remain distinct and cannot authorize that fallback.
- Customer-visible promo turns now receive an independent semantic fact audit
  against current applicable promo refs, verified product-promo facts, and
  unmatched requested scope. The audit treats category-choice cards as product
  navigation only, so the composer cannot turn a useful no-promo fallback into
  an invented discount or free-item claim. One normal structured repair remains
  the correction path; no response keyword or brand-specific rewrite is added.
- The promo audit receives enough bounded output budget for model reasoning and
  its short typed verdict. Legacy surface suppression no longer hides a later
  exact-size product surface with grounded discount facts merely because an
  earlier requested-brand search was partial; it still suppresses an ungrounded
  partial surface when no usable alternative exists.
- If the normal composer contract repair is mechanically valid but still fails
  only the semantic policy/promo audits, Runtime performs one final bounded
  model-produced scope correction. It receives the typed auditor findings and
  the unchanged evidence/renderer contracts, then passes every deterministic
  and semantic check again. Repeated failure still uses the existing fail-closed
  boundary; Runtime does not rewrite the response text.
- The final semantic correction also accepts accompanying unknown-ref or
  unauthorized-category violations from the same failed factual claim. This
  lets the model remove both the unsupported meaning and its invented claim
  declaration in one bounded retry; unrelated mechanical violations still do
  not enter this lane.
- General-region policy cannot authorize a customer-named city, district,
  barangay, landmark, or address by geographic-membership inference. The
  semantic auditor and bounded correction treat that as case-specific
  serviceability until a separate provider validates it; no place list or text
  matcher is used.
- The last bounded semantic correction receives explicit typed constraints
  derived from the failed evidence scope: omit customer-named locations and
  leave exact serviceability pending for general policy, or state that an empty
  promo search returned no verified alternative while treating any category
  surface only as a non-promo shopping continuation. The model still authors
  the complete customer response and every normal contract is rechecked.
- The complete bounded `payment_queries` list remains authoritative when the
  legacy single-method compatibility field is malformed. Runtime reuses the
  first validated ordered query for scalar consumers; it still fails closed
  when neither the scalar nor any list item has a valid entity shape.
- The release-candidate matrix supports named single-turn and journey subsets.
  Long live-model probes can therefore write a complete artifact after each
  bounded batch while retaining the same assertions and exact-release gate.
- Added regressions for multi-clause payment plans, canonical completion of
  supported and unsupported rows, explicit delivery grounding, and semantic
  location negatives, including the concrete-location/broader-label
  disagreement observed on staging. No provider, brand, SKU, place, or
  customer-phrase exception was added to production routing.

## 2026-08-01 - Staging-matrix truth and response-contract corrections

- Promo discovery now filters the active published catalog with the same
  Manila-date validity rule already enforced by gallery rendering and click
  validation. Vector retrieval is intersected with that current set, so an
  expired campaign cannot be reintroduced after the initial filter. Search
  diagnostics expose published/current/expired counts without exposing full
  catalog records.
- The release matrix now derives promo-card expectations from current allowed
  promo refs. It no longer requires expired Buy 3 Get 1 campaigns to produce
  cards, while the informational Promo Details and About Brand journeys use a
  general current-promo request so they continue to exercise tracked actions
  against whichever reviewed campaign is active.
- The typed location decision can authorize a bounded read-only policy lookup
  when a delivery/order question would otherwise bypass grounding. This does
  not authorize location-specific delivery, serviceability, or order facts;
  the selected FAQ/policy result remains the only business-fact source.
- Turn-plan mode no longer allows the legacy missing-lead-location fallback to
  attach province controls. Semantic planning owns that surface; structured
  state still validates the provider action and tracked renderer controls.
- Runtime-owned contact answers now carry a stable evidence ref and an explicit
  claim category, allowing the final composer to preserve exact phone details
  instead of falling back after inventing an object-path citation. A grounded
  direct-answer tool also compacts the first-turn intro to welcome-only, while
  greeting-only product discovery retains the established full intake.
- Safe debug output now includes compact payment lookup scopes. This makes a
  lost provider, term, brand, option, or eligibility visible during staging
  diagnosis without exposing credentials or raw checkout metadata.
- Local validation passed `845` focused regressions and `1,245`
  repository-wide tests. The changed-file Ruff gate, staging build, full live
  matrix, human-CS response review, and production promotion remain separate
  release gates.

## 2026-08-01 - Model-led product progression after an unusable promo surface

- Reproduced the reported confirmed-size failures on staging `140bafa`. Tire
  size extraction and fitment pruning were already correct: a concrete size
  supplied beside a vehicle did not call fitment. The failed turns instead
  spent the main model's tool rounds on promo search and promo presentation;
  `present_promo_gallery` returned `no_visual_cards`, after which the
  non-tool final composer could only acknowledge that the conversation could
  continue.
- Added `RuntimeV7ProductProgressionDecisionModel`, a bounded post-tool
  semantic checkpoint. It reads the complete latest request, short recent
  conversation, normalized signals, and compact tool outcomes, then decides
  whether the useful next surface is priced products, concrete products,
  brand/price-category choices, promo-only information, fitment/size
  clarification, or no product progression.
- Removed the legacy zero-promo-ref retry that always forced
  `discover_brand_buckets`. Empty promo evidence and a gallery with no usable
  visual cards now enter the same semantic checkpoint, so category choices are
  a model conclusion rather than a runtime default.
- The checkpoint also evaluates an already-produced promo or broad-category
  surface when no exact product surface exists. It leaves a semantically
  matching category surface alone, but can authorize `product_search` when the
  whole turn asked for exact available tires or current prices.
- Deterministic code does not infer the customer's goal from words or rewrite
  the response. It only verifies that a single normalized tire size and the
  proposed read-only tool are available, then executes `product_search` or
  `discover_brand_buckets`. Existing successful promo, product, and choice
  surfaces are left unchanged.
- Product-card pricing was verified as a downstream renderer capability rather
  than patched: when `product_search` runs, the existing cards include the
  per-tire price, four-tire payable total, and supported promo text. The missing
  price list in the reported conversations was caused by the absent product
  surface, not a price-field renderer defect.
- Added regression coverage for failed-promo eligibility, malformed-size and
  already-rendered controls, typed tool authorization, priced-product
  progression, and model-selected brand/price-category progression. The full
  product observation harness passes (`556` tests).

## 2026-08-01 - Semantic service-location planning and tracked choices

- Replaced the natural-language generic-location regex/seed path with the
  always-exposed `present_serviceable_location_choices` model tool. Store,
  branch, coverage-area, and installation-location questions are interpreted
  semantically instead of being admitted by a list of matching phrases.
- Added a bounded typed semantic decision for every proposed location-choice
  surface. It distinguishes a viable province-choice step from a concrete
  location lookup, an existing partner/selection detail, a contact-channel
  request, and delivery/order context. A no-tool recovery uses the same
  decision when the main loop understood the turn but omitted the renderer
  action; it does not add a keyword fallback.
- Deterministic guards remain limited to structured facts and mechanics. They
  reject province discovery after a validated province/city, for a normalized
  concrete location, or in delivery state; the provider supplies the current
  serviceable provinces and the renderer supplies tracked `lc1|...` controls.
  The surface is routing-only and cannot establish availability, partner
  selection, order state, or any commercial fact.
- Generic unresolved location nouns no longer expose concrete partner/slot
  tools. Conversely, a validated city still exposes the appropriate service
  lookup. This keeps capability exposure useful without turning advisory model
  text into customer location.
- Human response review exposed a separate hard-fact normalization issue: a
  question such as a hotline inquiry could be emitted as `contact_number`.
  Contact normalization now accepts only structurally valid Philippine mobile
  numbers, while the model still owns contact-channel intent.
- Live local evidence covered three independent runs of the original
  `location ng store?` turn (3/3 with eight tracked province cards), five
  varied location-choice inquiries (5/5 across the full and focused recovery
  probes), and six negative/adjacent scenarios (6/6 with no province surface).
  A transient catalog outage correctly produced no cards and no fabricated
  availability; the next direct provider check returned the current eight
  choices. Customer-visible replies and tracked controls were reviewed in
  addition to structured assertions.
- Final deterministic validation passed: `650` focused location/turn-plan
  regressions, `1,179` Runtime V7 tests, `1,242` repository-wide tests, Ruff,
  `git diff --check`, and the strict behavioral/customer-facing change audit.
- Commit `140bafa` was pushed to `product` and deployed to return-only staging
  as revision `gulong-chatbot-runtime-staging-00303-jps`. Focused location
  mechanics passed, but human-CS adjacent-response review and the broader
  release matrix did not. The release remains held; it has not been promoted
  to `main` or deployed to the customer-facing VM. Exact release evidence is
  recorded in `docs/RELEASE_HISTORY.md`.

## 2026-08-01 - Typed signal relations and explicit human handoff

- Background-signal candidates now declare a typed semantic relation:
  `asserted`, `selected`, `conditional`, `question_only`, `rejected`,
  `corrected`, or `historical`. `status_hint` remains diagnostic detail and no
  longer has to carry the meaning of a condition, question, or correction.
- Conditional, question-only, and historical values remain available for the
  current read-only lookup but cannot enter Active Working Memory or the
  durable signal ledger. A latest-user rejection removes the prior value;
  a correction replaces it. Existing asserted/selected facts retain the
  prior normalization and action-safety boundaries.
- Added the always-exposed model tool `request_human_handoff`. It records a
  durable requested state and truthful assignment status, authorizes the final
  composer to acknowledge only the recorded request, and emits `Stop Chatbot`
  through the existing post-delivery ManyChat tag adapter. It does not claim a
  human is connected, assigned, or has replied. The typed action also suppresses
  the normal first-turn sales welcome/intake so the handoff acknowledgement is
  the only customer-visible response.
- A second bounded typed semantic decision now authorizes that side effect.
  The main tool loop may propose handoff, but an availability-only question,
  complaint without takeover, or unclear request is rejected without storing
  state or emitting `Stop Chatbot`. This protects against model tool misfires
  without matching keywords in raw customer text.
- A successful handoff tag also creates a compact ManyChat CS note. Durable
  handoff state independently suppresses later chat ingress and proactive
  Runtime V7 follow-ups; a plain question about whether human support exists
  does not trigger the tag.
- Regression coverage includes conditional Pay Now questions, explicit
  payment retraction, corrected selection, unchanged selected-choice behavior,
  state export/hydration, typed handoff tagging, CS-note creation, and negative
  human-availability controls.
- Payment FAQ scope now has a bounded typed semantic decision that separates a
  named-method lookup, payment-option lookup, generic payment question, and no
  payment request. Named method values are rebuilt from that decision and typed
  customer evidence; a model-proposed full sentence cannot be treated as a
  provider and produce an irrelevant "unsupported" response. The main tool
  executor and the API pre-composer completion hook reuse the same decision, so
  runtime-required policy completion cannot bypass the semantic boundary. A
  generic scalar-shape check rejects sentence-length model output in the named
  entity slot without provider lists, regexes, or customer-text keywords.

## 2026-07-31 - Image-backed product selection and Website Inquiry priority

- Multi-product search results now use the existing tracked product-choice
  gallery with each product's current `/shop` `default_image`, exact SKU/model,
  per-tire price, four-tire payable total, a compact complete promo label, and
  the existing validated product-ref button. The renderer suppresses the
  duplicated long product text only when every visible card has a trusted
  catalog image; otherwise it retains the prior text presentation as a
  completeness fallback.
- Product image URLs are normalized at the catalog boundary and revalidated at
  the renderer boundary. Only HTTPS URLs on the established Gulong DigitalOcean
  Spaces hosts or `storage.googleapis.com` are rendered. Images never become
  product, price, promo, availability, or selection authority.
- The existing vision extraction call now identifies visible source ownership
  and Gulong surface type for product pages/cards, carts, checkout/payment
  pages, order pages, order emails, and marketing assets. This adds no model
  call. The resulting `website_inquiry_evidence` is routing-only and remains
  unsafe for commercial or order actions.
- Website Inquiry has exclusive routing priority over Moderate Intent and High
  Intent. If the current turn has validated Gulong website-image/text evidence,
  or the contact already has the Website Inquiry tag, the runtime emits only
  Website Inquiry from those three routing tags. Irate, Chatbot Error, Order
  Booked, and Payment Confirmation remain independent operational outcomes.
- Website Inquiry tag application still occurs through the existing ManyChat
  adapter after delivery. The runtime tag is not proof of the downstream
  ManyChat assignee; assignment must be verified from ManyChat assignment
  events and the active routing flow.
- Text detection no longer mistakes an address such as `hello@gulong.ph` for a
  customer-sent Gulong website URL.
- Screenshot transport URLs are removed before payment-intent interpretation,
  and a URL-bearing model proposal cannot become a payment-method value. This
  keeps signed/CDN query parameters out of commercial routing and prevents
  routing-only screenshot evidence from triggering payment-policy rewrites.

## 2026-07-31 - Human-reviewed release gates and model-led progression fixes

- Release-candidate automation validates transport, release identity, trusted
  tool evidence, state, renderer surfaces, and choice progression. Complete
  factual synthesis, natural tone, continuity, and next-step quality are
  reviewed from the rendered turn; sentence regexes are not semantic judges.
- Brandless promo-only turns now give the model an explicit primary objective
  to use the reviewed promo catalog/gallery without also opening a competing
  product-selection layer.
- Province-level schedule questions explicitly direct the model to
  `recommend_serviceable_cities` when the customer is unsure of the city. The
  read-only recommendation plan is validated by its state effects, not by a
  second deterministic interpretation of the customer's wording. The existing
  tool-plan boundary still rejects province-wide selectable slots.
- Composer guidance now requires one CTA for the active decision layer. Runtime
  does not delete or rewrite ordinary duplicate wording after composition.
- Named-brand warranty questions use authored FAQ topic metadata plus the
  API-backed canonical brand list to expose the published brand source when
  background signal extraction misses the brand. This is not a brand-specific
  branch; generic product warranty FAQs remain available for non-brand and
  selected-product questions.
- Published Gulong guarantee records now keep their source conditions inside
  the same scoped evidence object as duration and coverage, reducing accidental
  mixing with manufacturer warranty facts.
- Brand claim assertions now declare the exact published profile fields used.
  Runtime rejects unpublished manufacturer coverage/start/condition fields and
  requires published Gulong damage-coverage conditions to travel with a
  coverage assertion. This validates typed evidence rather than response prose.

## 2026-07-29 - Composer-owned turn plan and location authorization

- Added the internal `CustomerTurnPlanV1` contract. Runtime compiles accepted
  state changes, satisfied fields, the current/next decision layer, authorized
  evidence, and compact required/optional surface metadata before the existing
  final composer call. Full cards and API payloads remain renderer-owned.
- Location and checkout choice surfaces are now planned before final
  composition when `RUNTIME_V7_TURN_PLAN_ENABLED=1`. The composer therefore
  owns the customer-visible acknowledgement, surface order, and single next
  question. Runtime validates required/unknown/duplicate surfaces, competing
  decision layers, and direct re-asks for already-satisfied fields. One repair
  is allowed; failed repair uses a minimal neutral renderer fallback.
- Successful turn-plan responses no longer pass through ordinary CTA or order
  progression prose rewrites. Pricing/evidence safety, renderer facts,
  idempotency, legal state transitions, side effects, and delivery safety
  remain deterministic.
- A province is insufficient authorization for partner or slot tools. Runtime
  rejects those proposed plans before execution, attaches exactly one current
  serviceable-city surface, clears incompatible city/partner/schedule state,
  and preserves compatible product/commercial state. Exact serviceable cities
  remain eligible for current slot lookup.
- If the customer is unsure which city to select, the model can propose
  `discovery_mode=recommend_serviceable_cities` on the existing slot tool.
  Runtime runs isolated read-only previews, ranks city cards by earliest
  availability then partner count, and does not persist or select a city,
  partner, or schedule. A city click reruns authoritative city-specific
  availability.
- The staged rollback switch is `RUNTIME_V7_TURN_PLAN_ENABLED=0`. No ManyChat
  request, token, or button contract changed.
- Payment FAQ tool arguments remain proposed query plans. If the model passes a
  shortened bank value such as `BPI`, runtime restores an explicit installment
  term from the current customer question before matching the payment-option
  scoped `/payment/list` rows. Support and brand eligibility then come from
  the matched active row, including its current `available_brands`,
  `is_disabled`, transaction exclusion, and `updated_at` fields.
- Compound payment questions can retain a model-proposed brand even when the
  signal extractor does not emit a separate brand signal, but only when that
  normalized brand is explicitly present in the current customer-backed
  question/context. A proposed brand absent from customer text and validated
  selected-product state is removed before the lookup.
- Installment-term parsing accepts normal customer forms such as `3-month`,
  `3 months`, `6-mos`, and `6 months`, preventing a generic installment match
  from selecting the wrong active row when several terms share one payment
  option.
- Multi-question payment turns retain every restrictive API-backed result
  instead of allowing the last lookup to replace earlier answers. A correct
  composer response is preserved; the commercial guard supplies a minimal
  grounded fallback only when an unsupported method or brand exclusion is
  missing or contradicted.
- Distinct installment questions in one customer turn are compiled as
  separate proposed query plans from customer-authored clauses, canonical
  product brands, and generic bank/term parsing. If the model omits one plan,
  runtime resolves only the missing pairing against the same `/payment/list`
  snapshot before final composition. It does not add an LLM call or infer
  eligibility from wording. A single brand established for the compound
  question remains shared scope for following payment clauses unless the
  customer names another brand. When composition omits or contradicts one of
  several validated facts, the existing composer repair receives every
  resolved pairing so one brand's result cannot leak into another.
- Multi-claim answer validation is clause-scoped: a positive word such as
  `available` must occur in the same response segment as the validated method
  and brand. A positive Apollo sentence can no longer make a separate,
  unresolved Yokohama sentence appear answered merely because both strings
  occur somewhere in the complete response.
- Payment claims now participate in the existing final-composer contract and
  one-repair path before turn finalization. Equivalent model lookups are
  deduplicated by authoritative payment-row ID plus brand, and every validated
  outcome must be stated once. Repair receives structured facts and the normal
  persona instructions, so ordinary wording remains model-owned. The
  deterministic Taglish response is retained only if structured repair fails.
- The later API safety pass now reuses that same commercial-claim contract
  instead of applying a second phrase matcher to natural composer prose. This
  prevents a correct Filipino/Taglish answer from being replaced merely
  because it paraphrases an internal `/payment/list` label.
- If the model first proposes a general payment-row lookup and Runtime then
  validates the same row for the customer's explicit brand, the scoped result
  supersedes the brandless proposal in the claim contract. Multiple genuinely
  different brand scopes remain separate claims.
- Pay Now and Pay Later remain payment-timing choices, not payment methods, so
  a malformed unsupported-method lookup for either cannot become a commercial
  claim. Composer repair now receives the complete compact list of validated
  claims and must answer each once in natural customer language before asking
  one next question.
- When a compound question establishes exactly one Pay Now/Pay Later scope,
  Runtime applies it to following payment clauses unless the customer changes
  the option. Model-proposed rows from a conflicting option are rejected
  before composition and retained only as compact audit events.
- Composer-contract repair now follows a standard correction exchange: the
  invalid assistant response is followed by an explicit user repair request.
  This replaces the unreliable late-system-message shape without adding a
  model call or changing evidence authority.
- A globally unsupported payment method is represented as a method-level
  claim, without incidental brand or Pay Now/Pay Later query context. Brand
  and payment-option scope remain required for supported-method compatibility
  claims.
- Payment-claim validation accepts common grounded Filipino/Taglish negative
  forms such as `hindi kasama`, `hindi applicable`, `doesn't apply`, and
  `walang`, while still requiring the validated method/term and brand anchors
  in the same response segment. Composer guidance also avoids introducing
  unasked bank/provider names in compound answers.
- Positive payment claims are also checked for cross-method association. A
  bank/provider anchor from a separate unsupported or brand-ineligible claim
  cannot be attached to the positive method unless that anchor is part of the
  validated positive row.
- The failed-repair safety fallback now formats exact checkout names into
  natural customer labels such as `3-month installment na 0% interest`, uses
  readable brand and Pay Now/Pay Later labels, and asks one simple tire-size
  question. This wording path remains limited to failed structured repair.
- Final-composer guidance now explicitly translates exact payment method,
  term, brand, and Pay Now/Pay Later facts into brief, natural Filipino/Taglish
  service language instead of echoing internal policy labels or phrases such
  as `active checkout options`.
- Payment composition now treats `not_eligible` as the complete named method
  being unavailable for the brand, rather than implying that only the 0%
  interest or another benefit is unavailable.
- After a read-only payment compatibility answer with no established product,
  the composer asks for tire size as the single next qualification input. It
  does not combine tire size and location in one CTA; this remains model-owned
  wording and adds no post-composer rewrite.
- Promo search records matched and unmatched requested brands separately.
  When an explicit brand fails the active promo constraint, a partial product
  result cannot compete as a promo-selection surface. The composer should
  state the reviewed negative and offer active alternatives; the commercial
  guard supplies that fact only if the successful composer omitted it.
- Model-led promo routing remains unchanged, but runtime now validates explicit
  offer constraints such as Buy 3 Get 1 or a stated discount amount against
  each reviewed candidate before authorizing its ref. Tire-size numbers are
  not treated as offer amounts. An unrelated active offer for the same brand
  therefore cannot turn a failed 3+1 query into a positive brand match.
- Promo tool arguments are completed from every explicit latest-turn brand
  before execution. This prevents a model that splits one compound question
  into a brand product search plus a generic promo search from dropping the
  brand at the commercial evidence boundary.

## 2026-07-28 - Model-led multi-click interpretation

- Tracked promo, category, product, location, schedule, and payment actions now
  have an internal `InteractionEventV1` contract. Runtime validates each token
  against the delivered session allowlist and records provider occurrence
  time, server receipt/processing time, and stable event identity before any
  multi-click interpretation.
- A bounded `InteractionPacketV1` carries at most five unresolved events and
  2,500 serialized characters to both the main reasoning loop and final
  composer. Runtime supplies only objective structure (`runtime_relation`),
  trusted decision layers, and the legal interpretation envelope. The model
  decides correction, comparison, acceptance, or clarification from the event
  sequence, current free text, recent conversation, and sales context.
- Same-layer distinct clicks are provisional. Product, schedule, and payment
  state is restored before reasoning and only the model-selected, runtime-
  validated effective event can be committed. Promo Details and other
  informational actions never select a brand, SKU, location, schedule, or
  payment field.
- Order submission, order-payload creation, and payment-request side effects
  are unavailable while a choice sequence is unresolved. The existing
  structured composer repair runs once for an illegal decision; failed repair
  preserves state and returns one minimal clarification.
- Tracked clicks use an optional 400 ms settling check. If a newer customer
  event is present, the obsolete turn is saved as provisional and suppressed;
  the waiting request composes once from the ordered sequence. Exact request
  retries remain idempotent, and a delivered resolution closes every event in
  the batch.
- Controlled staging replay on revision `61c1de3` exposed a provider-history
  gap: ManyChat's message loader still returned the prior assistant gallery
  while a second button request was already waiting on the session lock. A
  small bounded interaction inbox now records structurally parsed click events
  before lock acquisition. The first turn checks this inbox again before
  delivery, yields to any newer ordered click, and the resolved batch removes
  its inbox events only after state and delivery are durable. Firestore,
  Postgres, and in-memory stores share this contract; ordinary free text does
  not read or write the inbox.
- The same replay also showed that the model could treat Premium followed by
  Budget as a definite correction without explicit customer context. For
  distinct button-only discovery or same-level location selections, the legal
  envelope now requires clarification. A later free-text turn restores the
  broader model-led accept/compare/clarify envelope. Transactional
  schedule/payment supersession and informational promo comparison keep their
  original legal choices.
- The first clarification-only staging replay then exposed a response-contract
  gap: the composer returned a valid clarification decision but also requested
  the latest Budget product surface. Clarification-only packets now expose no
  discovery, service, order, or payment tools, and the composer contract permits
  text response units only. Runtime suppresses renderer-owned surfaces while
  clarification is pending, without rewriting the model-authored wording.
  This prevents an unresolved click from biasing the customer toward one
  option, persisting a new observation, or paying for an unnecessary tool call.
- Interaction audit rows retain `delivery_status` as the transport result for
  the one batch response and add `resolution_status`,
  `resolution_interpretation`, and `effective_for_state`. A delivered
  clarification is therefore explicit and cannot be mistaken for two accepted
  selections.
- Ordinary free-text turns do not wait or load a batch unless a prior
  provisional click remains unresolved. Customer wording remains model-owned;
  Runtime V7 batching bypasses deterministic promo/location navigation and
  tracked-choice acknowledgement rewrites while retaining evidence, state,
  side-effect, idempotency, and renderer safeguards.
- When a price-category or product surface already has one model-authored CTA
  for that active decision layer, the renderer preserves it and does not append
  a second canonical question. The deterministic CTA remains only a fallback
  when the composer omitted the active input entirely.
- Rollout flags:
  `RUNTIME_V7_INTERACTION_BATCHING_ENABLED` (default `0`),
  `RUNTIME_V7_INTERACTION_SETTLE_MS` (default `400`),
  `RUNTIME_V7_INTERACTION_MAX_WAIT_MS` (default `600`), and
  `RUNTIME_V7_INTERACTION_MAX_EVENTS` (default `5`). Rollback is the first flag
  set to `0`; no external API or ManyChat flow contract changes are required.

## 2026-07-27 - Evidence-bound choice progression and checkout surfaces

- Repeated ManyChat controls are now deduplicated against hydrated
  authoritative state as well as event IDs and recent action history. A second
  click that proposes the already-applied SKU, schedule, or payment choice is
  a no-op even when ManyChat assigns a different event/idempotency ID. The
  first explicit click on an automatically bound single product remains
  visible to the customer.
- Product and location decisions already present in trusted state are not
  requested again unless the customer explicitly changes or reopens them.
  Schedule questions require a current source-backed slot surface; a raw or
  remembered location alone cannot authorize a schedule request.
- Installation checkout controls require serviceability evidence from a
  partner/slot observation. Payment controls render only at the confirmed
  payment layer and remain bound to the selected product, fulfillment path,
  schedule/service evidence, and current `/payment/list` metadata.
- A normalized latest customer payment choice, including free-text full
  payment, supersedes an older readiness snapshot before payment controls are
  built. Each payment surface now includes a short pretext explaining the
  active decision.
- Generic payment FAQ answers keep `/payment/list` rows as a method catalog
  until product/brand and service/payment-option dimensions are known. They no
  longer flatten a transaction-excluded method into both Pay Now and Pay Later;
  exact compatibility remains the checkout surface's filtered decision.
- ManyChat handoff-note pending fields pass through one human-label
  normalizer, so internal names such as `selected_product` and
  `email_address` are not exposed to CS agents.
- Customer free text remains model-led. Runtime does not interpret objections,
  comparisons, fitment corrections, promo questions, or other non-linear
  replies as SKU selection merely because they followed product cards.

## 2026-07-26 - Shared ManyChat follow-up cadence contract

- The published ManyChat Follow-up automation uses one flow for both the
  1-hour and 12-hour Last Interaction triggers. Runtime now accepts
  `cadence=auto` with the authoritative Last Interaction timestamp and resolves
  the request to the existing `first` or `second` timing layer before
  idempotency and follow-up planning.
- Auto-cadence requests fail before runtime I/O when the event timestamp is
  invalid. Their idempotency keys are namespaced by the resolved cadence, so
  the later 12-hour attempt can target a different missing field without
  duplicating the 1-hour delivery.
- The ManyChat request remains responsible for authenticated ingress and stable
  event fields. Runtime still hydrates fresh transcript/profile evidence,
  enforces stop and human-takeover gates, validates one eligible focus field,
  and admits delivery only through server environment configuration.

## 2026-07-26 - Compact CS handoff notes and follow-up VM activation gate

- Moderate/High Intent ManyChat notes now use a short CS-facing summary instead
  of copying the latest message, a long timestamp, intent rationale, and a
  suggested reply. The note contains only available trusted facts: tire
  size/brand, selected SKU, quantity/total, service/location/partner, compact
  schedule, payment, customer details, and one deduplicated `Pending` line.
- Selected SKU, pricing, schedule, payment, and customer fields come from
  deterministic order readiness and validated selection state. Raw assistant
  text and synthetic button messages are not treated as handoff facts.
- Dates omit the year in the internal CS note and flexible schedule wording is
  shortened to `preferred`. Individual values are bounded so one verbose
  upstream label cannot make the note difficult to scan.
- Follow-up sending remains server-controlled. The customer-facing VM release
  must set `FOLLOWUP_SEND_ENABLED=true`,
  `FOLLOWUP_EXPECT_SEND_ENABLED=true`, a non-empty initial trial-user
  allowlist, and `FOLLOWUP_SEND_CANARY_PERCENT=0`. Cloud Run staging and
  no-traffic candidates remain send-disabled except for an explicitly audited
  trial deployment.
- VM admission must expand through the existing trial, 10%, 50%, and 100%
  gates in `RUNTIME_V7_FOLLOWUP_PRODUCTION_SAFETY.md`; the emergency rollback
  remains configuration-only.

## 2026-07-26 - Keep deterministic guards after model interpretation

- Audited the commercial, journey, renderer, persistence, and action guards
  against free-form changes, mixed questions, repeated clicks, and non-linear
  checkout turns. The durable boundary is now explicit: the model interprets
  the complete latest turn and proposes tool/query/action arguments; runtime
  validates structured evidence, refs, commercial claims, and real-world
  actions; the renderer limits only competing interactive controls.
- A resolved schedule or payment choice can now be reopened from a current
  model-extracted typed signal, not only a narrow raw-text phrase match. The
  signal must retain latest-customer provenance. Stale memory and rejected or
  superseded signals cannot reopen a choice, and an unconfirmed payment inquiry
  cannot become a payment selection.
- `submit_order` no longer treats the model-authored payload reason as customer
  authorization. Submission requires a ready deterministic summary plus a
  current latest-customer `explicit_order_confirmation` signal. A mixed turn
  such as confirming submission and asking for the selected partner address is
  valid; a question about whether submission is possible is not confirmation.
- When one turn contains both an unsupported payment request and a selected
  partner-address question, both validated facts are preserved. The address
  answer suppresses unrelated automatic checkout controls for that read-only
  turn instead of opening a new payment decision layer.
- Product/category decision instructions now say that one active decision
  governs only the next requested input and visible controls. The model must
  still answer every explicit current factual question using grounded evidence
  before the one matching CTA. Typed answers remain equivalent to button
  clicks; exact validated button actions may bypass model interpretation only
  for deterministic navigation.
- When a customer with an already selected product asks for new alternatives in
  wording outside the legacy comparison phrase list, a current model-led
  multi-product decision surface now preserves its product-selection CTA. The
  trusted post-tool decision is authoritative; phrase matching is only a
  fallback when no structured decision exists.
- An adaptive staging turn, `May 195/60R15 ba? Also, puwede ba Home Credit?`,
  exposed a conflicting extractor instruction: payment inquiries were omitted
  from typed signals, so the product domain was available but the API-backed
  payment resolver was not. Named payment methods/providers in inquiries are
  now retained as `mentioned_unconfirmed`. This exposes the existing
  `answer_order_faq` resolver while remaining unsafe for checkout selection,
  readiness, persistence as availability, or order action. Unknown providers
  are preserved by the customer-stated name so the active checkout catalog can
  return `unsupported`; there is no Home Credit-specific routing branch.
- The post-composer payment guard also recognizes generic financing, credit,
  loan, wallet, monthly, and installment availability language. If the model
  still omits the read-only lookup, runtime calls the same checkout-backed
  resolver and rewrites an unsupported claim before delivery.
- The adaptive product -> typed SKU/location -> typed slot replay found a
  payment-option surface paired with a separate "review the order summary?"
  question. The renderer now treats order review/finalization as a later input
  while Pay Now/Pay Later controls are active. It preserves the schedule
  acknowledgement and payment explanation, then defers order review until the
  payment choice is resolved.
- A zero-traffic live candidate replay found a second proposed-plan failure:
  the customer asked for Yokohama products and whether BPI 6-month was
  available under Pay Later, but the model proposed `fulfillment_path=delivery`
  without customer evidence. Delivery filtering removed the BPI rows, after
  which a legacy generic fuzzy fallback misresolved the specific request as a
  straight-card row. Runtime now replaces FAQ brand, payment-option, and
  fulfillment scopes with current customer/validated-state evidence and drops
  an ungrounded fulfillment guess before calling `/payment/list`.
- Bank and installment term are binding query constraints. If the strict
  checkout matcher cannot find that bank/term, it can no longer fall back to an
  unrelated generic payment row. A parallel product plus payment question
  retains current product cards while the unsupported brand/method fact is
  rewritten; the commercial guard limits the invalid assertion rather than
  discarding the independently grounded discovery result.
- The adaptive matrix also caught an extractor that labeled `Pay Later` as both
  payment option and payment method in a three-month inquiry. Typed evidence
  may constrain brand, option, and fulfillment, but it cannot overwrite a more
  specific model-proposed method with an option-only label. The active payment
  catalog still accepts or rejects the resulting proposed method. If the model
  also puts the option label in the method field but supplies a structured bank
  or installment term, runtime repairs the query plan from those typed fields;
  it does not add a phrase-specific intent rule.
- A final-composer omission can no longer silently drop an explicit payment
  answer after the resolver succeeds. Runtime inserts the validated positive
  fact only when the composed response lacks a direct resolution, while
  preserving current product cards and their model-led selection CTA. An
  already-correct model answer is left unchanged.

Guard acceptance matrix:

| Customer behavior | Runtime responsibility |
| --- | --- |
| Types a valid choice instead of clicking | Model extracts it; runtime validates and binds the same typed ref/state |
| Changes a prior slot in natural free text | Current typed signal reopens schedule validation without a keyword patch |
| Asks about payment while choosing a product | Answer source-backed payment facts; keep product as the only new control layer |
| Confirms an order and asks another question | Honor typed confirmation after a ready summary and answer the grounded question |
| Merely asks whether the order can be submitted | Do not submit; a question is not customer authorization |
| Repeats the same button click | Validate the interaction token and suppress semantic duplicates |
| Clicks an older superseded control | Reject the stale action without erasing current validated state |
| Model proposes unsupported commercial/action args | Reject or rewrite only the unsupported assertion/action; preserve unrelated grounded content |
| Model guesses fulfillment in a payment inquiry | Replace it with customer/validated state or remove it before checkout lookup |
| Specific bank/term is absent after filtering | Return unsupported/ineligible; never coerce it to a generic card or different installment row |

## 2026-07-26 - Enforce one active decision and evidence-safe recovery

- Runtime V7 now applies one generic customer-decision priority across all
  interactive surfaces: product, price category, location, schedule, payment
  option, then payment method. A later layer cannot be rendered while an
  earlier choice is unresolved. The final CTA is rewritten to match the
  controls that are actually visible.
- Delivering a new choice surface supersedes older delivered surfaces in the
  session interaction ledger. A click on a superseded control is rejected
  instead of reopening an obsolete province, city, schedule, or payment step.
- Repeated delivery of the same ManyChat click is suppressed by a
  session-owned semantic key (`presentation_ref` plus `choice_ref`) for a
  bounded window. The first valid click remains auditable; a duplicate does
  not call the model, repeat an acknowledgement, or advance state twice.
- Exact tire size is now a hard product-card boundary. When an exact-size base
  query verifies a miss, nearby-size results may be retained as diagnostic
  evidence but are not selectable or described as matching inventory.
  Unavailability is stated only after that exact base query succeeds; provider
  failure is distinguished from a verified miss.
- Promo-catalog failure follows the same commercial-truth rule. An unavailable
  or disabled provider cannot be rewritten as "no current promo." The runtime
  returns a retry/current-price recovery response unless another validated
  product promo source already supports a claim.
- A customer asking where the selected installation partner is receives the
  exact validated partner name and address from the selected slot context.
  The response states that the slot is selected for order review, not yet
  booked, and does not restart location qualification.
- Price-category state is now part of the final-composer decision contract,
  preventing category cards and province cards from appearing together.
  These changes contain no brand, SKU, bank, province, city, or conversation
  exceptions; they operate on typed evidence and presentation refs.
- VM releases must set `RUNTIME_V7_PROMO_CATALOG_ENABLED=1` with an empty
  allowlist when the reviewed catalog is intended for all customers. Container
  environment copied from an older VM instance is not authority for that
  rollout setting; the declared VM release metadata is.
- Current `/payment/list` rows and a customer website checkout replay agree:
  BPI 6-month installment has a populated `available_brands` allowlist that
  excludes Yokohama under both Pay Later and Pay Now. The runtime therefore
  treats Yokohama as ineligible for that method while preserving unrestricted
  3-month installment. This supersedes the earlier visual interpretation that
  BPI 6-month was available for Yokohama. There is no Yokohama branch in code;
  any brand outside a populated payment-row allowlist receives the same result.
- A stateful selected-product replay found that an earlier installment inquiry
  could be reused as if the customer had selected Pay Now/BPI after choosing a
  schedule. Order tools now treat model payment arguments as proposed plans:
  when the only customer evidence is a `mentioned_unconfirmed` inquiry, the
  runtime drops proposed option/method/bank/term fields. Order readiness also
  excludes payment facts sourced from unconfirmed inquiry or assistant/memory
  text. Explicit latest-customer choices and validated payment-button refs
  remain valid authority. The payment conflict response now reuses a selected
  product and points to the visible schedule layer instead of asking for tire
  size again.
- The first stateful replay showed that signal-ledger normalization later
  relabeled an unconfirmed payment question as a generic remembered signal.
  Ledger metadata now preserves the original authority source and status.
  Order readiness and model-plan validation consult that provenance, so an
  inquiry stays unconfirmed across turns. A final delivery guard also blocks
  positive payment-compatibility wording when a payment availability question
  completed without a validated payment-policy result.

Customer and business regression matrix:

| Risk | Required result |
| --- | --- |
| Product/category and location controls collide | Show only product/category controls and a matching CTA |
| Schedule and payment controls collide | Show only schedule controls until a schedule choice is resolved |
| ManyChat repeats the same click | Record a duplicate validation result; emit no duplicate customer response |
| Customer clicks an older visible control | Reject it as superseded; do not reopen completed state |
| Exact size has no inventory | Show no nearby-size product cards; claim a miss only after the exact base query |
| Promo provider is disabled or fails | State that current promos cannot be verified; never claim there are none |
| Customer asks for selected partner address | Disclose the validated partner and address without requalification |
| Valid promo/payment evidence exists | Preserve existing source-backed claims and checkout compatibility |
| Customer asks a payment question while schedule choices are visible | Answer safely, keep schedule as the only clickable decision, and do not preselect payment |
| Customer explicitly selects payment after an earlier inquiry | Preserve the newer customer/validated selection; strip only model-proposed fields sourced solely from the inquiry |

Backward-compatibility rule:

- A new guard must not replace an already-correct behavior merely because the
  same domain is being changed. Each intended delta is checked at both the
  helper/contract boundary and the rendered customer-response boundary.
- Existing source-backed promo claims, exact product pricing, serviceable
  province-to-city navigation, selected product/location/schedule continuity,
  typed answers, checkout payment choices, order-summary progression, and
  partner-address disclosure remain required acceptance cases.
- Safety guards suppress only the unsupported claim or competing CTA. They do
  not suppress a grounded answer to the customer's latest question, erase a
  newer explicit choice, or restart an earlier completed qualification layer.
- Product lookup may still run as evidence for a selected-SKU payment inquiry,
  but its detail surface is not redisplayed when that SKU was already selected
  and another qualification layer is active.
- Production promotion requires the compatibility pack to pass alongside the
  new regression. A passing new-case test alone is insufficient.

Local validation:

- Changed-scope Ruff: passed.
- Focused customer-journey regressions: passed.
- Full repository suite: `1026 passed`.
- Live API contract probe: Yokohama resolved as `not_eligible` for Pay Later
  BPI 6-month (`payment_type_id=10`); its rendered method set excluded BPI
  6-month, retained 3-month installment, and classified e-wallet/card/bank
  rows as reservation-fee methods.
- Exact-revision staging, zero-traffic live Cloud Run, and isolated VM
  acceptance remain release gates.

## 2026-07-25 - Close validated-choice progression gaps from trial replay

- Reconstructed the matching staging trial path for session
  `sess_fdf277bbb2d748708eaa9c6ffd284e73`. The relevant turns were:
  `req_7b4a82582f41473bbbb1054b72c6fb7e` (Quezon City and slot
  presentation), `req_7841925305eb40fc85de9d6e2972a148` (flexible
  afternoon), `req_0080a09e88274fd4b7dc61fd49f8c386` (Pay Later),
  `req_33f18ede80c64574a51425d0c13ea829` (BPI method),
  `req_d62b769ff5fe48378fadddf7b4e8cc58` (flexible afternoon repeated),
  and `req_49baf67f3ed140e796072cc2f4d3829a` (exact 8:30 AM). The supplied
  external request ids were used
  as investigation anchors; the runtime failures were matched by user,
  timestamp, content, session, tool, state, and rendered output.
- All schedule and payment clicks passed the delivered-choice allowlist. Order
  readiness also retained the selected schedule/payment fields. The defects
  were downstream: current-turn checkout attachment ignored older collected
  payment values, model-authored transitions could reopen resolved choices,
  and the renderer exposed generic button captions that hid the selected value
  in the visible ManyChat transcript.
- A validated schedule/payment click now has one runtime-owned transition:
  acknowledge the exact allowlisted label, suppress unrelated model-requested
  product/service surfaces for delivery only, then attach only the next
  unresolved checkout layer. Tool calls and full results remain in the turn
  trace; suppression does not delete evidence or mutate the observation store.
- Checkout attachment now starts from collected Payment option/method state.
  An exact schedule selected after Pay Later and BPI therefore cannot reopen
  Pay Now/Pay Later. A new Pay Now/Pay Later click intentionally clears the old
  method for the next layer, preventing a method compatible with the previous
  option from carrying across. A payment-method click also retains the
  API-backed payment option of the delivered method surface.
- Flexible afternoon remains a preference, not availability or a booking. It
  is nevertheless complete for the conversational qualification layer:
  subsequent contact/order-form turns must not ask the same schedule question
  or redisplay slot cards. Exact slot validation remains a final
  booking/submission requirement and can be reopened when the customer
  explicitly asks to change or recheck the schedule.
- The first exact-revision staging probe found a remaining cross-turn gap:
  the flexible preference was honored for surface suppression but checkout
  gating recognized it only on the original click turn. Later contact turns
  could therefore ask for an exact slot instead of advancing. Checkout now
  recognizes the persisted preferred schedule as conversationally complete,
  and the final guard covers natural select/pick phrasing such as
  `pakipili ang exact installation slot`.
- Checkout quote construction now binds the validated product observation,
  presentation, card, item, product ID, and slug refs already stored by the
  delivered product choice. It no longer rediscovers the SKU from newer
  product observations or conversational signals. This is a generic evidence
  boundary for every product and payment path, not a brand or SKU rule.
- Exact-revision staging then exposed the same persistence issue one layer
  later: selecting an API-backed `6-mos` method retained its bank/method but
  not the term encoded by the selected row, so the model asked for months
  again. Payment choices now normalize a declared term from structured API
  fields or standard `N mos/months` labels and seed option, method, and term
  signals directly from the validated delivered choice. Selecting a new
  Pay Now/Pay Later option also supersedes method, bank, and term signals from
  the previous option before the compatible method layer is rebuilt.
- Live `/payment/list` verification on 2026-07-25 confirmed that BPI 6-mos
  rows exist under both Pay Later (`id=10`,
  `main_payment_type_id=1`) and Pay Now (`id=26`,
  `main_payment_type_id=2`). The legacy resolver incorrectly treated the
  presence of installment months as proof of Pay Now before checking the
  selected option's API rows. It now resolves the scoped payment row first:
  an installment route is valid when checkout metadata authorizes it for the
  selected option and remains a conflict when no scoped row matches.
- Order readiness loads the API checkout catalog only for a commercial signal
  seeded by a validated delivered choice. This keeps product-discovery turns
  free of a new metadata request while ensuring the final payment decision
  uses the same versioned source that rendered the button. The selected row's
  typed payment role determines whether it satisfies the reservation-fee or
  post-service-balance layer.
- Signal-ledger normalization rewrites a prior signal's immediate source to
  `signal_ledger` on later turns. The commercial authority check therefore
  recognizes the preserved delivered `choice_ref` plus payment
  `presentation_ref`, not only the transient source label. Typed/unvalidated
  methods have neither ref and do not gain API-authorized status.
- Pay Later payment choices now retain their checkout role. Current
  non-installment rows pay the reservation fee; installment rows apply to the
  post-service balance. The role comes from the selected option plus the API
  `is_installment` field and is persisted with the validated choice ref. This
  prevents a reservation e-wallet from being mislabeled as the balance method
  and lets the runtime request a reservation method after a balance
  installment choice without bank- or brand-specific logic.
- Exact-revision staging then caught a cross-boundary conflict: a validated
  Pay Later reservation e-wallet click was correctly stored, but the model
  proposed Pay Now when compiling the order summary. The runtime now passes
  the current validated choice context into the order-tool boundary, removes
  conflicting model payment args, and attaches only the selected option,
  method role, and declared term. Model order args remain proposed plans;
  the delivered allowlisted click is authoritative for that turn.
- The replacement staging replay verified that Pay Later remained Pay Later,
  but found two adjacent gaps. If the model omitted `answer_order_faq` for an
  explicit payment-availability question, the runtime returned an unnecessarily
  uncertain answer; it now performs the required lookup itself through the
  same canonical API provider. A reservation-only e-wallet was also repeated
  as the balance method in the summary; reservation and balance are now kept
  separate unless the customer explicitly supplies both.
- When newly supplied contact fields advance a deterministic order summary,
  the runtime owns the short acknowledgement and review/remaining-field CTA.
  An older payment FAQ topic in the transcript cannot resurface on that form
  turn. The guard recognizes latest-message form signals after pre-turn state
  merging, matching the deployed pipeline rather than relying only on a
  before/after missing-field difference.
- A repeated contact-form message after a ready summary exposed a separate
  submit-authorization gap in staging and created test order `37567`. The
  submit tool now requires an explicit latest-customer confirmation after a
  ready summary. Contact details, remembered intent, model-authored payload
  reasons, and stale confirmation signals cannot authorize the `/order` write.
  A blocked attempt is rendered as not submitted with one explicit
  confirmation question.
- Added a narrow resolved-choice composer guard. It removes only schedule,
  Pay Now/Pay Later, or payment-method questions contradicted by current
  trusted readiness state. Explicit `change`, `switch`, `instead`, `other`,
  `palit`, `iba`, or equivalent recheck requests remain model-led.
- ManyChat product, Pay Now/Pay Later, and payment-method buttons now use the
  actual compact choice label within the 20-character channel limit. The
  clicked user bubble is therefore auditable (`MICHELIN PILOT SPORT`,
  `Pay Later`, `BPI 6-mos 0%`) instead of `Choose this tire`, `Choose`, or
  `Use this method`. Full refs and labels remain in the interaction ledger.
- The installation-partner application FAQ is now gated by an explicit latest
  customer objective to apply/join. Ordinary customer searches for an
  installation partner cannot surface the unrelated B2B application answer
  through lexical or vector similarity. The FAQ remains available for an
  explicit partner-application question.

Failure matrix:

| Observed turn | Evidence | Root cause | Shared correction |
| --- | --- | --- | --- |
| Quezon City slots added a partner-application spiel | `answer_service_faq` called with `service_how_to_be_a_gulong_ph_installation_partner` | Semantic FAQ overlap treated customer service context as a B2B objective | Latest-turn explicit-objective gate |
| Flexible afternoon immediately showed schedules again | Valid `d1aft`; preferred schedule persisted; `find_installation_slots` called again | Model interpretation and renderer were not normalized after a typed validated action | Runtime-owned acknowledgement and surface suppression |
| Pay Later/BPI turns asked for schedule again | Readiness retained `2026-07-28 afternoon`, Pay Later, and BPI | Technical exact-slot blocker was treated as a conversational missing field | Resolved-choice context plus output guard |
| Exact 8:30 turn showed Pay Now/Pay Later again | Readiness was `ready_for_summary` with payment fields present | Checkout attachment read payment only from the current action | Start from collected checkout state |
| Product details reappeared on BPI click | `get_product_details` ran on the payment action | Tool evidence surface was also treated as a customer presentation | Preserve trace result but suppress unrelated channel surface |
| Click bubbles said `Choose` / `Use this method` | Valid click ledger had the real label | Static renderer captions | Compact label-derived captions |
| Later contact turn asked for an exact slot after flexible afternoon | Preferred schedule was persisted; slot cards were suppressed | Checkout recognized flexible choice only from the current click, while quote construction could rediscover product context | Accept persisted preference for conversational progression and bind quote to validated product refs |
| BPI 6-mos click later asked for installment months | Delivered API row and visible button already declared six months | Choice persistence kept generic method/bank but omitted the validated term | Generic term projection plus direct validated-choice commercial signals |
| API-authorized Pay Later BPI installment remained incomplete/conflicting | `/payment/list` rows 10 and 26 authorize the same method under Pay Later and Pay Now respectively | Legacy resolver assumed installment months imply Pay Now before checking option-scoped API rows | Resolve scoped checkout row first; reject only unmatched option/method plans |

Validation:

- Changed-file Ruff: passed.
- Focused renderer, transaction-choice, FAQ, context, and final-composer tests:
  `528 passed` for the final changed transaction/composer set.
- Full repository suite: `981 passed`.
- Repository-wide Ruff still reports the same 18 pre-existing findings in
  unrelated legacy ManyChat/storage/scripts files; none are in this change
  set.
- Exact-revision staging acceptance remains required before promotion.

## 2026-07-25 - Unify API quantity-promo pricing across product and checkout

- Runtime V7 now treats an active `/shop` `product_promo` row as the
  authoritative quantity-promo contract for any brand. The resolver validates
  `required_quantity` and `discount_amount`, preserves the API promo ID as an
  evidence ref, and applies the amount only when the selected quantity meets
  the requirement. This is generic and contains no product, SKU, or brand
  decision branch.
- Quantity pricing follows the website order of operations: apply the standard
  quantity tier to SRP, subtract the active per-tire `product_discount`, then
  subtract the qualifying `product_promo` amount once. For product 417 this
  produces PHP 4,315.60 per tire before the quantity promo, PHP 17,262.40 for
  four, and PHP 16,062.40 after API promo 35's PHP 1,200 discount.
- Product cards, structured pricing facts, order summaries, Pay Now/Pay Later
  quotes, and order payloads now reuse the same normalized payable total.
  Removed the competing checkout-only sale-tag calculation that could change
  the amount after the customer selected a card. Pricing facts expose the
  pre-promo total, promo discount, and source ref while clearly marking the
  final payable total as already discounted.
- For structured quantity promos, customer surfaces do not invent or volunteer
  one aggregate "total savings" figure because the website's displayed savings
  baseline is not exposed by `/shop` and does not reconcile consistently with
  SRP. The card instead states the validated per-tire tier, pre-promo total,
  API quantity-promo amount, and final payable total.
- A return-only staging continuation also found that an older optional
  installation-location CTA could attach serviceable province cards after the
  same turn explicitly selected delivery and supplied a complete address.
  Location-surface attachment now consults post-tool order readiness and
  suppresses installation province/city controls for the delivery path.
- A reviewed Yokohama banner/SKU fallback remains only for legacy responses
  where `/shop` omits structured `product_promo`. Structured API evidence always
  takes precedence; migrating the remaining fallback rows into the product or
  reviewed promo source remains deferred maintenance.

## 2026-07-25 - Refresh durable session state after acquiring the turn lock

- Runtime V7 now reloads the active session after every successful turn-lock
  acquisition, including when the lock succeeds on the first poll. Session
  resolution must occur before locking to obtain the session id, so a fast
  button click could previously retain a pre-lock snapshot while the preceding
  turn committed the newly delivered choice allowlist. This caused a valid
  schedule click to be rejected as stale and could replay an earlier
  qualification question. The post-lock reload is generic across interactive
  choices and restores the invariant that validation runs against the latest
  durable, customer-visible state. The refresh reads only the exact locked
  session document; it does not re-read or rewrite the user-to-session pointer.

## 2026-07-24

- Fixed the post-product/schedule progression defects found in the controlled
  trial conversation without adding Apollo-, brand-, SKU-, or message-specific
  rules. A structured required-brand query now binds the sole matching
  requested-brand card as the active product even when the renderer also shows
  other-brand comparisons. Multiple matching cards remain unresolved.
- An explicit `top_k=1` product query plan now stays one card through the
  customer presentation. The presentation layer no longer expands a narrowed
  selection back to three options and re-sends unrelated alternatives.
- Added `ps1` product-choice tokens to the existing ManyChat choice router.
  Product results now include compact buttons whose title is the full SKU and
  whose subtitle contains the trusted current price/total. A click carries only
  the delivered presentation/card refs; Runtime V7 validates them against the
  successfully delivered session allowlist and the product observation store
  before updating selected-product state. Tampered or expired refs are rejected.
- Added a delivery-aware service-policy ledger. Stable policy note IDs such as
  `no_walkin_setup` are persisted only after successful customer delivery and
  removed from later slot surfaces. Suppressed note text remains
  renderer-owned so a model cannot reinsert the duplicate in surrounding prose.
  Explicit policy FAQ answers remain available when the customer asks.
- Added prompt-facing trusted state for the exact selected product and the
  latest validated installation slot. The selected SKU is marked resolved so
  the model must not ask for it again. The validated service observation
  exposes its source-backed partner name/address for a direct "where will this
  be installed?" answer and order-summary/proceed context while retaining the
  read-only/not-booked boundary.
- Recompute order readiness after the turn's tools finish and pass the exact
  validated selected-product state into the final composer. This closes the
  same-turn gap where a sole requested-brand card was already bound by the
  runtime but the composer still saw the pre-search readiness snapshot and
  asked which product to use.
- Added a narrow post-composer consistency guard: when a trusted product is
  already selected and the customer did not request a comparison, a final
  product-choice CTA is contradictory and is replaced by the current
  source-backed slot CTA (or the next unresolved location/schedule step).
  Explicit comparison/alternative requests retain normal model-led choices.

## 2026-07-23

- Fixed the interactive discovery delivery boundary after a production audit
  found that an eligible price-category presentation could be persisted and
  counted as `surface_delivery_succeeded` even when the VM lacked its ManyChat
  router namespace and therefore sent only surrounding text. Promo/category
  presentation metadata is now exposed only when the rendered `cards` payload
  contains the matching tracked `pc1` or `bc1` action token. Health output also
  reports `interactive_choice_router_not_configured` when the active
  environment has no router target.
- Added `products_presented_from_choice` for successful promo actions that
  actually deliver renderer-owned product cards. The compact event links the
  promo/card/action and selected brand to product presentation refs, bounded
  product refs/IDs/brands, card count, and trusted tire size without copying
  prices or customer-authored text into analytics.
- Implemented location choices as another instance of the tracked-choice
  contract, not as a static prompt list. The current `/branch_list_loc`
  catalog used by the installation-partners website defines serviceability;
  `/get_province` and `/get_city` provide canonical hierarchy and codes. Level
  one contains only provinces with current partner coverage plus `Others`.
  A validated parent click shows only cities with at least one current partner
  in that province. Large city sets are split at Messenger's ten-card limit.
  Each impression and click preserves the branch-source version, choice ref,
  parent/code, freshness, turn, and delivery status in the existing choice
  ledger. Typed city/barangay remains available, and `Others` never implies
  coverage. A validated province click is deterministic UI navigation and
  cannot invoke partner/slot tools or claim province-wide availability; the
  exact city click returns to the normal model-led tool path. Antipolo is
  correctly nested under Rizal.
- Repaired the shared interactive router contract. Category cards already
  emitted valid `bc1` tokens, but the API model rejected their ManyChat
  request when promo-only catalog fields were blank, before the token could be
  parsed. `POST /gulong/v7/choice-action` now parses the typed token first and
  applies evidence requirements by token type: `pc1` requires promo catalog
  evidence, while `bc1` and `lc1` validate against the delivered session
  presentation. `/gulong/v7/promo-action` remains a compatibility alias.

## 2026-07-22

- Closed the promo/gallery rollback investigation at the implementation level:
  92efa2d reverted the unnecessary price-category quick-reply workaround on
  product only; it was never merged to main or the production VM. The active
  runtime payloads contain the intended promo/category card controls. Repeated
  controls in ManyChat Live Chat use the platform dynamic-flow ID
  deadbeef-dead-feef-dead-baadf00d0004 and remain an operator-interface issue
  unless customer-side duplication is demonstrated.
- Replaced Runtime V7 static payment/installment business rules with active
  checkout metadata. /payment/list is now the authority for supported payment
  methods, bank/term labels, allowed brands, disabled rows, and fulfillment
  exclusions. At the time, this replaced a stale local Yokohama exclusion with
  the then-current API row; the July 26 source correction above supersedes that
  snapshot. It also makes Home Credit explicitly
  unsupported when absent from the current metadata. Installment-filtered
  product discovery projects these same rows onto candidate products, allowing
  brand/product compatibility questions before a specific SKU is selected.
- Promo-only product results retain the active promo source as evidence and no
  longer render products that only matched size/brand but failed the promo
  eligibility constraint. This fixes the Toyo Buy 3 Get 1 presentation path
  without a Toyo-specific rule.

## 2026-07-20 - Production-Safe Runtime V7 Follow-Up Remediation

- Replaced the active two-model decision/composer path with one structured
  follow-up planning call. The model selects `send`, `defer`, or `suppress`, a
  stance, one eligible focus field, an optional declarative lead-in, and up to
  two evidence refs. Deterministic code validates the plan and renders the
  exact benefit wording plus one CTA. Invalid plans suppress rather than fall
  back to generic sales copy.
- Added authenticated `/gulong/v7/followup` and always-return-only
  `/gulong/v7/followup/tester` routes. `FOLLOWUP_SEND_ENABLED` defaults false;
  request fields cannot enable sending, force evaluation, supply authoritative
  transcript/profile data, or disable analytics. Server allowlists and stable
  contact hashing own trial/canary admission.
- Split latest-customer triggers from assistant-last proactive follow-ups.
  Customer-last events up to 24 hours old enter normal Runtime V7 chat using
  the original ManyChat message ID. Delivered events suppress; failed stored
  responses can be redelivered; unknown delivery reconciles against refreshed
  transcript content and fails closed when ambiguous.
- Added source-separated follow-up cases, evidence-linked customer/profile
  facts, lead-field rotation, stop-tag and human-takeover gates, current
  `/promo_brands` authority, selected product/service context, and a durable
  delivered-product-presentation ledger. Raw AWM and Background Signal payloads
  are not sent to the follow-up model as independent truth.
- Replaced attempted/sent field lists with bounded version-2 attempt records.
  `sending` is persisted before delivery, only confirmed ManyChat success is
  `sent`, return-only remains `evaluated`, failed/invalid attempts retry after
  cooldown, unknown outcomes require reconciliation, and only sent fields are
  removed from later focus rotation.
- Added normalized `followup_event_log` analytics, release/host metadata,
  Cloud Logging alerts, a redacted 95-case July corpus with all nine rollback
  incidents, 15 explicit safety scenarios, and 71 bounded live-transcript
  cases, plus a three-run real-model evaluator. Cloud Run deployment config
  injects the bearer token from Secret Manager and remains return-only by
  default. The VM remains the sole customer-facing runtime.
- Tightened stored-fact provenance so normalized state is accepted only when
  it links to an active customer message or a freshly loaded trusted profile.
  Canonical tire size, brand, and contact presence can also be recovered
  directly from customer transcript evidence when an earlier extraction pass
  missed them. Contact values are redacted from the case prompt. Human-agent
  interpretations and unsupported stale values no longer become customer
  facts. Dynamic response schemas are isolated by their case-specific eligible
  focus set.
- Pre-final Cloud Run probes found that an early cadence trigger was persisted
  as durable `suppressed`, which could consume the valid later cadence. Timing,
  transient profile/transcript, reconciliation, and freshness outcomes now use
  retryable `evaluated` records; timing and unresolved-delivery records do not
  restart cooldown. Legacy suppressed records with those reasons are interpreted
  compatibly. Customer/model/stop/human suppressions remain durable.
- A production-model corpus run also encountered transient Gemini 503 responses.
  The follow-up client now allows one bounded transport retry with short
  exponential backoff. It remains one logical planning call, retries no
  authentication/schema/client errors, and records transport attempts/retries
  in traces and follow-up monitoring.
- Local validation on exact commit `441dcc5`: focused follow-up, ingress,
  renderer, observation, promo-action, gateway, analytics, and persistence
  integration suite `654 passed`; full repository suite `834 passed`. The final
  production-model corpus completed 285 evaluations with 258 logical model
  calls, zero invalid structured outputs, one safely suppressed semantic
  validation failure (`0.39%`), zero model errors, zero transport retries, and
  zero customer-visible invariant failures. The rejected plan contained an
  ungrounded brand lead-in and produced no message. Artifact:
  `tmp/followup_v2/july_full_eval_3x_441dcc5_final.json`. Final staging and VM
  release evidence remain required before delivery is enabled.

## 2026-07-21 - Model-Led Promo And Brand Discovery

- Removed the Runtime V7 raw-utterance promo preload. Customer wording such as
  `price`, `magkano`, `hm`, or `promo` does not activate a gallery in
  deterministic code. The main model decides among `search_promo_catalog` plus
  `present_promo_gallery`, `discover_brand_buckets`, and `product_search` from
  the current message and accumulated state. Channel support, active version,
  allowed refs, repeat suppression, rendering, and delivery remain deterministic.
- Promo catalog schema v2 adds AI-derived eligibility to each Gemini extraction
  and a generated `Eligibility` review tab. Rules store scope, included/excluded
  brands, patterns, and sizes, qualifying/free quantities, confidence, and
  source evidence. Low-confidence output is `NEEDS_REVIEW`; every published
  promo requires a source-backed `PASS`. The schema version participates in
  source deduplication, so unchanged July source files can produce a new v2
  review artifact without replacing the active v1 pointer before approval.
- `search_promo_catalog` accepts canonical `tire_size`. When supplied, the
  runtime performs one hidden exact-size product lookup and combines visible
  inventory with the reviewed rule. Candidates remain available to the model
  for source-backed explanations, but only inventory-verified promo refs are
  allowed into the gallery. Missing reviewed eligibility or an unverified
  exact-size product fails closed.
- `discover_brand_buckets` now returns stable `choice_ref` and
  `presentation_ref` values, exact-size minimum/maximum current prices,
  product/brand counts, representative brands, and ordered category positions.
  Messenger renders available Budget, Economy, Mid Range, and Premium options
  as a compact four-card gallery with one tracked button per tier. ManyChat text
  messages support only three regular buttons, so a four-option text row is not
  used.
- Category buttons encode
  `bc1|presentation_ref|category|width|aspect|rim` in the existing
  `promo_selected_id` router field. `/gulong/v7/promo-action` distinguishes
  `bc1` category tokens from `pc1` promo tokens, restores the exact tire size,
  validates the selected category against a successfully delivered session
  presentation, then asks Runtime V7 for two to four focused products. Stale
  choices request current options instead of applying the old category.
- The authoritative session state adds latest/history ledgers for category
  presentations and actions. ManyChat mirrors only the latest discovery
  surface and choice fields. Best-effort BigQuery table
  `interaction_event_log` records `surface_delivery_succeeded`,
  `surface_delivery_failed`, `choice_clicked`, `choice_rejected`,
  `choice_response_delivered`, and `products_presented_from_choice` events.
- Category rendering uses `PRICE_CATEGORY_STAGING_ROUTER_FLOW_NAMESPACE` and
  `PRICE_CATEGORY_LIVE_ROUTER_FLOW_NAMESPACE`, falling back to the corresponding
  existing promo router namespace variables. The staging/live promo router
  flows remain reusable because both token families use the same field and
  `/gulong/v7/promo-action` endpoint.
- Final local validation on code commit `5673722`: focused product/prompt/probe
  coverage `465 passed`, focused promo renderer coverage `26 passed`, and the
  full repository suite `855 passed`. Changed-file Ruff and
  `git diff --check` passed.
- Cloud Build `dcc087fe-2c02-491a-b098-0710d04d2480` succeeded for `5673722`.
  Staging revision `gulong-chatbot-runtime-staging-00113-2jr` serves 100% of
  staging traffic with `RUNTIME_DELIVERY_MODE=return_only`; both health routes
  report release `5673722`.
- A fresh synthetic staging turn for `Hi hm po 195 60 15` called
  `search_promo_catalog` and then `discover_brand_buckets`, did not call direct
  product search, and rendered four tracked exact-size category cards. The
  active schema-v1 catalog has no reviewed size eligibility, so promo cards
  correctly failed closed and category discovery became the qualification
  surface. The final renderer keeps representative brand labels within the
  ManyChat subtitle limit without cutting a brand name.
- Schema-v2 version `catalog-202607-3574297cf6ef-v2` was initially review-gated
  in workbook `1MPFt1ievuiHYAKW3EguTOvAPidT7oiJRwGCYlbE0luk`. Its seven
  AI-derived eligibility rows and seven retrieval evaluations had to pass human
  review before the prior schema-v1 active pointer could move.
- Marketing approved schema-v2 on 2026-07-21. Cloud Run Job execution
  `gulong-promo-catalog-sync-tstl6` published it and atomically moved the active
  pointer from schema-v1. The published catalog contains seven approved promo
  parents, 47 mechanic chunks, four brand profiles, and eight visual cards. All
  eight public image URLs returned HTTP 200 with immutable one-year cache
  headers.
- Publication cleanup now deletes obsolete same-version AI draft documents
  before activation. This matters when a schema rebuild is retried after
  reviewed carry-forward corrects an AI-generated ID: post-query status checks
  prevent the draft from being shown, but its embedding could otherwise consume
  a Firestore nearest-neighbor result slot. The first schema-v2 publication
  removed two obsolete promo drafts and 19 obsolete mechanic chunks.
- Live-vector retrieval checks ranked Michelin Japan first, both Michelin 3+1
  and Apollo 3+1 first for generic and Bridgestone-negative 3+1 questions, and
  Yokohama PHP 6,000 first over PHP 5,200. A normal return-only staging path for
  `Hi hm po 195 60 15` presented eligible Apollo, Michelin, and Yokohama cards.
  Clicking Apollo `Check Price` reused the same session and tire size, ran
  `product_search`, returned the matching Apollo recommendation and 3+1 savings,
  and advanced to an installation-area question. Full repository validation
  after the publication safeguard: `856 passed`; Ruff and `git diff --check`
  passed.
- Controlled trial delivery to `4843256405786522` exposed an ambiguous ManyChat
  boundary. `sendContent` returned client read timeouts and direct HTTP 504s,
  while `loadMessages` initially showed no new message; ManyChat then delivered
  the accepted requests several minutes later. Retrying those ambiguous results
  produced duplicate galleries and diagnostic card messages. This was not an
  image, button, or top-level field-action validation failure: full, cards-only,
  single-card, and no-button requests were all eventually accepted.
- The ManyChat client now classifies read timeouts and HTTP 502/503/504 as
  `unknown` with `manychat_delivery_ambiguous`, never as a confirmed failure.
  Identical general or targeted galleries are suppressed while their ledger
  status is `pending` or `unknown`, preventing unsafe retries. A category click
  itself is accepted as proof that a pending/unknown presentation was visible.
  Confirmed success remains the only impression denominator; ambiguous sends do
  not become either success or failure analytics. Full validation after this
  protection: `863 passed`; changed-file Ruff and `git diff --check` passed.
- Rollback is independent: revert through the normal branch/Cloud Build release
  path to restore the prior model policy/category renderer, disable
  `RUNTIME_V7_PROMO_CATALOG_ENABLED` to remove promo tools, or restore the prior
  `promo_catalog_config/active` pointer. An unapproved schema-v2 build cannot
  move the active pointer.

## 2026-07-20 - Dynamic Promo Catalog and Gallery

- Added the review-gated promo path: current Manila-month Google Drive source
  `18s3IRvGJ52Zbcnqibyiz9I7VlMKDi-GD` -> immutable private artifacts in
  `lica-gulong-chatbot-embeddings` -> formatted review Sheet in folder
  `1gyeRwn3_Yd9Tsky4quSVqfjCwN9wxOhO` -> published Firestore catalog ->
  immutable public posters in `gulong-chatbot-459723-promo-media` -> Runtime V7
  search/selection -> ManyChat gallery. The hourly sync hashes the DOCX and
  images, skips duplicate builds, and still checks approved pending Sheets when
  the source hash is unchanged. Missing next-month content does not move the
  active pointer.
- Production catalog data uses `promo_catalog_versions`,
  `promo_catalog_cards`, `promo_catalog_mechanics`, versioned
  `promo_brand_profiles`, and `promo_catalog_config/active`. Existing `_trial`
  collections are not read or written. Parent promo and child mechanic vectors
  are 768-dimensional. Vector queries filter only by active
  `catalog_version_id`; literal/normalized retrieval results are unioned and
  reranked for exact amounts, `3+1` aliases, and literal overlap.
- Schema-v1 review workbooks contain `Version`, `Promos`, `Cards`, `Mechanics`,
  `Brand Profiles`, and `Evaluation` tabs. Schema v2 adds `Eligibility`.
  Publication requires an explicit approval,
  reviewer and timestamp, valid IDs/dates/evidence/image assignments/button
  policies/text limits, reviewed brand profiles, and PASS for all required
  positive, ambiguous, negative, expired, and unrelated retrieval evaluations.
  Reviewed values are authoritative; corrections retain original values and
  source evidence in the version audit.
- Review-Sheet creation supports a service account when the output folder is
  in a Workspace Shared Drive, or owner-authorized OAuth JSON supplied through
  `PROMO_REVIEW_GOOGLE_OAUTH_JSON` for personal My Drive. The current consumer
  Gmail setup instead uses the shared workbook configured by
  `PROMO_REVIEW_SPREADSHEET_ID`. Before a new version is written, the completed
  version's tabs are renamed with a stable version prefix; fresh fixed-name tabs
  are then created for the pending review. An unfinished review blocks reuse.
  This preserves prior formatted reviews in one workbook without giving the
  service account personal Drive storage quota.
- When a schema rebuild uses the same immutable source hash, poster assignments
  match the prior published records and carry forward the human-reviewed promo
  IDs, titles, dates, mechanics, and card values. The new AI eligibility remains
  pending review. This prevents extraction nondeterminism from discarding prior
  marketing corrections during a schema-only upgrade.
- Published posters use immutable `catalog/<version>/cards/<sha>.<ext>` object
  names, `Cache-Control: public,max-age=31536000,immutable`, retained private
  `gs://` provenance, and durable `https://storage.googleapis.com/...` URLs.
  Publication fails closed if the public bucket cannot grant
  `allUsers:roles/storage.objectViewer`; signed URLs are not accepted.
- Added `search_promo_catalog` and `present_promo_gallery`. General mode returns
  reviewed active cards in display order. Targeted mode returns compact
  source-backed promo facts and child mechanics. Presentation accepts only
  current-search promo refs and emits immutable stored card definitions, up to
  eight general cards or three targeted promos. As of the 2026-07-21 milestone,
  the main model decides whether promo discovery is useful; the runtime no
  longer activates it from utterance markers. Unsupported channels, invalid
  refs, stale versions, and duplicate successful presentations remain
  deterministically suppressed. Failed or return-only attempts remain retryable.
- Added `promo_catalog` channel rendering. Cards are square, contain no poster
  `action_url`, and choose a prepublished staging/live flow target from
  `SERVICE_ENVIRONMENT`. Cards and top-level contact actions are sent in one
  atomic `sendContent` call without text pacing. The session ledger records the
  version, promo/card refs, trigger mode, fingerprint, version-scoped show
  count, delivery result, and timestamps; ManyChat fields are only the mirror.
- Added `POST /gulong/v7/promo-action`. It validates active version, current
  dates, promo/card/action/brand, and reviewed brand profiles before entering
  the normal Runtime V7 session, assistant, delivery, and logging path. Required
  event/idempotency IDs are deduplicated by the locked authoritative session
  event ledger; the click path does not perform a redundant outer Firestore
  response write. Stale clicks do not expose old mechanics and instead request
  the current catalog.
- Published trigger-free reusable ManyChat routers:
  `Promo Catalog Router - Staging` = `content20260719224556_101828`, targeting
  the staging Runtime V7 service; `Promo Catalog Router - Live` =
  `content20260719225032_161939`, targeting the VM runtime. Each flow has one
  action node: set field `promo_selected_at` (`14790801`) with
  `nowDateTime()`, then POST the tracked card fields to `/gulong/v7/promo-action`.
- Verified ManyChat semantic fields: reused `promo_selected_id` (`14765456`)
  and `promo_selected_action` (`14765457`); created `promo_catalog_version`
  (`14790794`), `promo_gallery_shown` (`14790795`),
  `promo_gallery_last_shown_at` (`14790796`), `promo_gallery_show_count`
  (`14790797`), `promo_gallery_promo_ids` (`14790798`),
  `promo_selected_card_id` (`14790799`), `promo_selected_brand` (`14790800`),
  `promo_selected_at` (`14790801`), `promo_source` (`14790802`), and
  `chatbot_state` (`14790803`). Public API card actions use field names; CMS
  router actions use the verified IDs.
- Infrastructure is declared in `cloudbuild.promo-catalog-infra.yaml`: public
  bucket, Firestore composite vector index, Cloud Run Job
  `gulong-promo-catalog-sync`, and hourly Manila scheduler
  `gulong-promo-catalog-hourly`. The service feature flag is
  `RUNTIME_V7_PROMO_CATALOG_ENABLED`; no active Firestore pointer means the
  runtime remains inert even when the flag is enabled.
- Release status: `feature/promo-catalog-runtime-gallery`, `origin/product`, and
  `origin/main` contain release `ca74290`. Staging Cloud Build
  `45491cf5-db9b-401a-8b9f-0be1c0678b31` deployed revision
  `gulong-chatbot-runtime-staging-00099-9cg` in `return_only` mode; the main
  trigger build `da888676-b245-4da8-b6b4-4a777f00370d` also passed.
  Infrastructure provisioning is complete: the public
  bucket is uniformly accessible, the production 768-dimension vector index is
  `READY`, the Cloud Run Job is ready, and the hourly Manila scheduler is
  provisioned. The scheduler remains `PAUSED` until controlled rollout finishes.
  Local validation: `837 passed`; Cloud Build YAML parsing, `git diff --check`,
  and Ruff on the promo change set passed. The repository-wide Ruff scan still
  reports 20 unrelated legacy findings that predate this feature and are tracked
  as non-blocking cleanup. Both staging health routes return HTTP 200 with
  release `ca74290`.
- Source hash `3574297cf6ef248a203aa8bc84b88cfeff1ca6cae94d7e71a53d8a8a199cd26d`
  produced version
  `catalog-202607-3574297cf6ef` from `MANY CHATS MECHANICS.docx`: 7 promo
  records, 8 visual cards, 47 mechanic records, and all private source objects
  are present. Owner-created workbook
  `1MPFt1ievuiHYAKW3EguTOvAPidT7oiJRwGCYlbE0luk` is attached, formatted with
  exactly the six required tabs, and stored in the version manifest. CARLO
  SOLIBET approved all 7 promos, 8 cards, 47 mechanics, 4 brand profiles, and 7
  retrieval evaluations after completing the validity dates. Review timestamps
  accept ISO-8601 and Manila-local values such as `7/20/2026 8:58:11`; naive
  values are normalized to `2026-07-20T08:58:11+08:00`. The approved version is
  published and `promo_catalog_config/active` points to it. Public poster probes
  return HTTP 200 with immutable cache headers.
- Published-version retrieval diagnostics passed the required ranking cases:
  Michelin Japan ranked the event first; Michelin promos returned
  the three Michelin offers first; generic and Bridgestone `3+1` ranked
  Michelin/Apollo first; and exact Yokohama PHP 6,000 and PHP 5,200 queries each
  ranked the matching discount first.
- Controlled staging delivery to trial user `4843256405786522` created
  `msgout_api` message `25444828244` with all 8 approved cards, immutable HTTPS
  images, stored text, and tracked buttons. The exact delivered version,
  promo/card refs, selection fingerprint, and successful delivery result were
  persisted in the Runtime V7 session ledger. Cards encode one compact
  `pc1|version|promo|card|action|brand` value in `promo_selected_id`; the router
  validates and expands it before mirroring normalized fields. This keeps each
  button within the ManyChat action limit while preventing request-time card
  mutation.
- The controlled `choose_brand=Michelin` click produced `msgout_api` message
  `25444830970` and correctly mirrored the promo ID, card ID, action, brand, and
  source fields. That first response incorrectly substituted Yokohama because
  product promo filtering recognized only explicit `product_discount_amount`
  and ignored the Michelin row's trusted `sale_price_discount_amount=1000`.
  Release `e06d2a3` treats that positive sale discount as a product discount,
  renders its discount text, and suppresses broad alternatives after an exact
  requested-brand promo match. Brand-selection clicks now explicitly request
  eligible promo prices for the current tire size. The final analytics-enabled,
  return-only staging regression
  returned only `MICHELIN 175/65/R14 ENERGY XM2+` at PHP 5,490/tire, with PHP
  1,000 off/tire and Buy 3 Get 1, and persisted a valid `choose_brand` action
  ledger entry and trusted product context for product ID `7420`.
- The latency hardening removed synchronous per-table BigQuery flushes, moved
  batch-writer network I/O outside the enqueue lock, removed the redundant
  promo-action idempotency response write, cleared owned turn locks in the
  successful session CAS, scrubbed legacy active-memory prompt metadata, and
  capped persisted full product observations to the same latest three refs
  exposed to the model. The trial session is now about 141 KB, its product
  observations are about 19 KB, active memory is about 2.5 KB, and the saved
  lock fields are null.
- Live promotion is no longer blocked by inherited Runtime V7 latency. The
  final analytics-enabled promo-action request improved from 133 seconds to 53
  seconds; correctness, gallery delivery, click routing, and durable state
  passed. The remaining multi-round model orchestration and full-session
  persistence costs predate the promo catalog and remain baseline runtime debt.
  A pre-carousel live turn for the same trial user on release `f309308` already
  made three LLM calls with 13.2 seconds of model time. In the final staging
  click trace, the feature-specific promo search added 3.84 seconds and product
  lookup added 0.33 seconds. Promotion may therefore proceed through the
  normal `origin/main` and no-traffic VM candidate gates. Continue to gate on
  promo-specific correctness, search latency/regressions, gallery delivery,
  click idempotency, session state, and trial-user verification; track the
  inherited Runtime V7 latency separately rather than treating it as a promo
  rollout failure.
- The first VM candidate exposed a feature-specific Vertex AI credential gap:
  the VM runtime identity could impersonate `promo-catalog-bot`, but the runtime
  embedder still used direct ADC and the target identity lacked Vertex access.
  Release `8584309` added explicit service-account impersonation through
  `PROMO_CATALOG_EMBEDDING_SERVICE_ACCOUNT`; the target identity now has
  `roles/aiplatform.user`. A direct two-hop identity probe returned 768
  dimensions, and the no-traffic candidate request
  `req_23b85ad9396b4a8580d5777313be5a2c` returned the exact Michelin
  `175/65R14 ENERGY XM2+` product at PHP 5,490/tire and PHP 16,470/four, with
  PHP 1,000 off/tire and Buy 3 Get 1.
- Release `ca74290` adds `RUNTIME_V7_PROMO_CATALOG_USER_ALLOWLIST` to both the
  normal catalog tool path and `/gulong/v7/promo-action`. The final isolated VM
  candidate used port `18082`, `return_only`, tags off, follow-up sending off,
  and allowlist `4843256405786522`. The allowlisted request
  `req_7308c19c20be49a78a1d19924488a684` validated Michelin, used source-backed
  mechanics, and saved state; a non-allowlisted control returned
  `feature_disabled` before catalog or model access.
- The customer-facing VM now runs immutable image
  `ca74290-promo-gallery-20260720` at digest
  `sha256:8d4177b7408d891849d07e5b1f1c4036bd4c58bc66b6e60fa4a1451da409b20d`.
  Promo access is enabled only for trial user `4843256405786522`; other users
  run without promo tools. The public return-only request
  `req_1e8d209703ee4dd0b29ecc10979de00c` returned HTTP 200, validated the
  Michelin action, persisted state, and skipped delivery. The authoritative VM
  service metadata points to `ca74290`, and the edge metadata/public Caddy route
  includes `/gulong/v7/promo-action`. The prior live container is retained as
  `gulong-chatbot-runtime-shadow-rollback-f309308-20260720`.
- Controlled live request `req_7e905e16f0f64791a9457df00ecc356f` delivered
  `msgout_api` message `25444862299`: three reviewed Michelin promo cards, square
  immutable HTTPS images, live router namespace
  `content20260719225032_161939`, and tracked button tokens. `loadMessages`
  confirmed the stored cards. Two subsequent button clicks completed as
  requests `req_df6885300e5d41c2a33ee978540b90da` and
  `req_34348aa40a5742059ce10f6e25f141c0`, producing `msgout_api` messages
  `25444862403` and `25444862510`. The settled ManyChat mirror agrees on the
  selected promo, card, `check_price` action, Michelin brand, selection time,
  catalog version, gallery timestamp, show count, and three displayed promo IDs.
- Promo-click progression hotfix `2ee4031` bridges a validated card selection to
  the trusted selected-product context before Runtime V7 compiles the turn. A
  brand button is now an explicit current brand signal, and a persisted selected
  product size is reused without asking the customer to repeat it. For
  `choose_brand` and `check_price`, the high-priority action context requires an
  immediate exact-size/brand `product_search`, followed by one missing lead field
  (location before contact). Informational buttons answer the reviewed mechanics
  or brand profile first, then ask one missing qualification field. Staging build
  `91d4145c-78e5-4d23-9aa0-72791bf8b159` deployed revision
  `gulong-chatbot-runtime-staging-00102-4bn`. Return-only request
  `req_57514ec8b33f404db514e8f565504bc8` reused `175/65R14` after a Yokohama
  click, called `search_promo_catalog` and `product_search`, returned only the two
  eligible Yokohama products, asked for location rather than tire size, and saved
  the updated click and qualification state. A later live return-only probe
  confirmed the search and size reuse but exposed model variance in the final
  CTA. The response renderer now deterministically replaces that CTA after a
  successful promo price search: it collects city/barangay when location is
  missing, or contact number when location is already known.
- Rollback: disable `RUNTIME_V7_PROMO_CATALOG_ENABLED` through the normal
  environment release path, or execute `promo_catalog_sync.py rollback` to
  atomically restore `promo_catalog_config/active` to its retained previous
  version. For a VM binary rollback, remove the current
  `gulong-chatbot-runtime-shadow`, rename the retained rollback container to
  that live name, restore `--restart=unless-stopped`, and start it. The static
  ManyChat promo flow remains unchanged as the fallback.

## 2026-07-15

- Refined Runtime V7 follow-up generation so each proactive follow-up CTA
  targets exactly one missing field. Product-list follow-ups now use a single
  `tire_brand` focus first, keep shown brand choices visible, include one
  grounded offer/benefit when product promos or warranty details were shown,
  and avoid asking for city/barangay/location in the same message. Location can
  rotate into a later follow-up after the brand/product-choice focus has been
  sent or attempted.
- Added separate internal attempted-focus tracking for follow-ups:
  `last_attempted_focus_field`, `attempted_focus_fields`,
  `last_attempted_context_fingerprint`, `last_attempted_at`, and
  `attempted_count`. Deterministic goal selection skips both sent and attempted
  focus fields, while customer-visible duplicate suppression still uses
  `last_sent_focus_field`, `sent_focus_fields`, and the visible message hash.
  Hard suppressions such as latest customer message recovery, human-agent
  messages, completed order/payment state, and too-recent assistant messages
  still run before any attempted-focus rotation is recorded.
- Validation: focused follow-up endpoint tests and full Runtime V7 tests passed
  locally before staging promotion.

## 2026-07-03

- Changed Runtime V7 BigQuery analytics writes to append-only for runtime
  event/audit tables. The gateway still stamps deterministic `row_id` values
  for downstream dedupe/latest views, but it no longer passes `key_columns` to
  the batch writer for `assistant_log`, `tool_output_log`, `error_log`,
  `slots_log`, `debug_log`, `request_state_log`, `request_attempt_log`,
  `turn_trace_log`, `turn_fact_log`, `llm_span_log`, or `tool_call_log`.
  This avoids per-request staging-table MERGE jobs while preserving the emitted
  observability payloads. Any current-state reporting should be built as a
  scheduled latest/dedup view or table outside the request path.

## 2026-06-28

- Tightened Runtime V7 explicit-brand availability interpretation through the
  model contract and tool schema. Latest customer turns that ask whether a
  named brand is available or how much it costs, such as `May Yokohama
  185/65R15?` or `Michelin or Yokohama 175/65R14 meron?`, are now described as
  hard `product_search.required_brands` requirements unless the same latest
  turn explicitly relaxes to other brands. Soft `preferred_brands` remains for
  remembered preferences and customer wording that accepts unnamed
  alternatives.
- Aligned the advisory Background Signal prompt with that same contract so
  latest-turn explicit brand availability and price asks are extracted as
  `required_brands` instead of nudging the main model toward a soft preference.
  The runtime still keeps Background Signals advisory; the main model chooses
  the tool call, and product cards remain renderer-owned.
- Tightened hard requested-brand result semantics. `requested_brand_status`
  for `product_search.required_brands` now treats only products matching the
  active requested size/filter set as `matched`; requested brands found only in
  broader partial fallback pools are reported under
  `available_outside_requested_filters` and remain `missing` for the requested
  size/filter set. The final composer prompt now explicitly uses that status
  instead of claiming the requested brand is available.
- Added explicit `ZR`/commercial suffix preservation to the product-search
  tool schema and Background Signal examples. Customer text such as
  `265/35ZR21` should produce `rim_size=ZR21`, while commercial sizes such as
  `195R14C` keep `R14C`.
- Validation: affected Runtime V7 slices passed locally:
  `python -m pytest test/test_runtime_v7_product_search_runner.py -q` with
  83 tests passing, and the focused model-contract/background-signal/card
  regression slice with 9 tests passing. The seven-scenario local live matrix
  at
  `tmp/runtime_v7_brand_availability_live_probe_matrix_final_v2/runtime_v7_live_pack_20260628_210455/summary.json`
  passed with zero explicit-brand contract failures and product cards inserted
  for all product-search scenarios, including the true known-brand/exact-size
  miss `Yokohama 265/35ZR21`. The full local Runtime V7 suite passed with
  659 tests.

- Repaired Runtime V7 Buy 3 Get 1 pricing authority. `/promo_brands` is now
  the brand-level source of truth for 3+1 eligibility, so sale-tagged Michelin
  rows with `promo_tag = 0` are still priced as Buy 3 Get 1. Regular bundle
  tiers are disabled after a product is confirmed as promo-brand eligible,
  preventing Michelin `225/60/R18 Primacy SUV+` from using the generic
  four-tire bundle total instead of PHP 14,050.00 x 3 = PHP 42,150.00.
- Added Runtime V7 sale-price grounding for sale-tagged Buy 3 Get 1 products.
  When the API exposes an active sale price through `sale_tag`, `srp`, and
  `promo` but omits a `product_discount` object, product cards keep the
  customer-visible unit price and 3+1 total unchanged while model-facing
  `pricing_facts` mark the sale discount as already reflected in the unit price.
  This prevents the assistant from subtracting the PHP off/tire sale amount a
  second time when explaining totals.
- Locked Runtime V7 promo-tag Buy 3 Get 1 pricing to the website card and modal
  behavior. Apollo and Vredestein rows can expose `promo_tag = 1`,
  `sale_tag = 0`, and a lower raw `promo` value, but the storefront card/modal
  still prices 3+1 from the visible card unit price. Runtime cards therefore
  keep using that visible unit price for Buy 3 Get 1 totals.
- Added selected-SKU Yokohama set-promo pricing for July 2026 creatives. All
  Yokohama sale rows continue to use the explicit `YOKOHAMA Promo: PHP 1,000.00
  off/tire` product discount. Runtime now reads `banner.description` first for
  `additional PHP 1,200` or `additional PHP 2,000` four-tire set discounts,
  falling back to the creative SKU tables only when banner metadata is missing.
  Non-selected Yokohama sale SKUs no longer receive the old generic bundle
  percentage discount.
- Hardened Runtime V7 Firestore session state against recursive active-memory
  prompt growth. Active Working Memory now persists only compact cross-turn
  state and a small allowlisted metadata set; prompt previews, system/user
  prompts, raw model output, raw model responses, and full error strings are
  stripped on generation, hydration, and export. The memory generator evidence
  packet also receives only the prompt-safe memory subset so legacy polluted
  session documents cannot be fed back into future memory prompts.
- Compacted the Runtime V7 inbound-event replay ledger. Duplicate replay still
  keeps customer-visible bubbles, images, payment payloads, response text, and
  tagging summary, but raw delivery payloads and nested ManyChat handoff-note
  API responses are bounded before Firestore persistence.
- Validation: passed the focused active-memory and inbound-event regressions,
  then passed the broader affected local subset:
  `python -m pytest test\test_runtime_v7_ingress_trace.py test\test_runtime_v7_product_observation_harness.py -q`
  with 488 tests passing.
## 2026-07-09

- Phase 2J hardens the VM Cloud SQL parity path before any read flip. The
  ManyChat Cloud SQL compare summary now excludes runtime-local synthetic
  assistant message ids such as `assistant_evt_*` from the Cloud SQL coverage
  denominator while keeping real numeric ManyChat message-id gaps visible. The
  Postgres analytics writer now coerces fields declared as `JSON` in the
  analytics schema through the JSONB adapter even when the compact runtime
  payload is a scalar string, preserving BigQuery fallback behavior while
  preventing `runtime_shadow.turn_trace_log` JSON syntax failures.
- Validation and VM rollout: targeted analytics/Cloud SQL reader tests passed
  with `15 passed`, Runtime V7 tests passed with `650 passed`, image
  `chatbot-runtime:4dca6f4-phase2j-parity-20260709` was smoke-tested as a
  no-traffic VM candidate, then deployed to `gulong-chatbot-runtime-shadow`.
  Public return-only smoke `req_81818f891a5244b8b3f35af13701a201` matched
  BigQuery and Cloud SQL `runtime_shadow` rows, post-swap runtime logs showed
  zero Postgres analytics write failures, and VM metadata now points at the
  Phase 2J image. Full evidence and rollback steps are in
  `docs/VM_CLOUDSQL_PHASE2J_PARITY_HARDENING_REPORT_2026-07-09.md`.
- Phase 2I added compare-only Cloud SQL reads for Runtime V7 ManyChat
  conversation history. The runtime still uses the existing authoritative
  hydration order and does not feed Cloud SQL rows into model context yet:
  provided request history, Firestore channel-history cache, live ManyChat
  `loadMessages` when needed, then session/runtime state fallback. The new
  reader queries `manychat_shadow.messages` only behind
  `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_ENABLED`, logs bounded summaries
  without message bodies, validates SQL identifiers, uses short timeouts, and
  has deterministic sampling through
  `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_SAMPLE_RATE`.
- Validation before VM rollout: targeted read-compare/hydration tests passed
  with `37 passed`; full local runtime tests passed with `670 passed`. Built
  image `chatbot-runtime:5d7401f-phase2i-read-compare-20260709`, smoke-tested
  it as a no-traffic candidate on VM port `18082`, then replaced the live
  `gulong-chatbot-runtime-shadow` VM container with compare enabled at sample
  rate `0.25`. Live return-only analytics smoke matched BigQuery and Cloud SQL
  `runtime_shadow`; actual runtime/pipeline MERGE jobs and Cloud Run leakage
  were zero after deployment. The previous Phase 2H container remains available
  as `gulong-chatbot-runtime-shadow-pre-phase2i-20260708T212732Z`. Full details
  and rollback steps are in
  `docs/VM_CLOUDSQL_PHASE2I_READ_COMPARE_REPORT_2026-07-09.md`.
- Phase 2H prepared the VM runtime analytics cost hardening patch. Runtime
  analytics rows still receive deterministic `row_id` values and still dual
  write through the configured BigQuery/Cloud SQL analytics writer, but the
  BigQuery gateway no longer passes `key_columns=["row_id"]` for runtime log
  tables. This keeps request-time analytics writes append-only in BigQuery and
  avoids staging-table `MERGE` jobs from the runtime hot path.
- Cloud SQL keeps its `row_id` primary-key protection for the
  `runtime_shadow.*_log` mirror. Parity checks for this phase should compare
  same-window unique `row_id` rows across BigQuery and Cloud SQL, and should
  separately monitor raw BigQuery physical counts for unexpected duplicate
  appends.
- Validation before VM candidate build: `python -m pytest
  test/test_analytics_gateway.py test/test_runtime_v7_ingress_trace.py -q`
  passed with `41 passed`, and `python -m pytest test -q` passed with
  `665 passed`.
- Built VM image
  `chatbot-runtime:d0a7c55-phase2h-append-only-20260709`, smoke-tested it as a
  no-traffic candidate on VM port `18082`, then replaced the live
  `gulong-chatbot-runtime-shadow` VM container. Public `/health` and
  `/gulong/health` checks passed after deployment. A return-only live smoke
  and one real post-deploy customer turn both matched across BigQuery and
  Cloud SQL `runtime_shadow`, with zero runtime log MERGE jobs after the live
  container start. The previous live container remains available as
  `gulong-chatbot-runtime-shadow-pre-phase2h-20260708T203808Z`. Full details
  and rollback steps are in
  `docs/VM_CLOUDSQL_PHASE2H_RUNTIME_APPEND_ONLY_REPORT_2026-07-09.md`.

## 2026-06-30

- Added a Runtime V7 Cloud SQL analytics parity writer for VM deployments.
  `RUNTIME_ANALYTICS_WRITER_PROVIDER=dual` keeps the existing BigQuery
  analytics path while also writing the same normalized runtime facts to
  Postgres `runtime_shadow.*_log` tables.
- Added `docs/sql/runtime_cloudsql_analytics.sql` as the explicit Cloud SQL
  schema contract for runtime analytics parity. The Postgres analytics writer
  remains fail-open by default so analytics persistence cannot block ManyChat
  delivery.

## 2026-06-27

- Added optional Postgres-backed Runtime V7 session and idempotency stores for
  the Compute Engine + Cloud SQL shadow path. The default runtime remains
  Firestore-backed; Postgres is only selected when the VM sets
  `RUNTIME_SESSION_STORE_PROVIDER=postgres`,
  `RUNTIME_IDEMPOTENCY_STORE_PROVIDER=postgres`, and `RUNTIME_POSTGRES_DSN`.
- Added environment-driven Postgres table/schema settings and guarded
  identifier validation so VM canary state can use Cloud SQL without committing
  VM-only JSON config. The implementation keeps the same `SessionStore` and
  `IdempotencyStore` interfaces used by the existing runtime gateway.
- Validation: added focused config/factory tests covering Firestore defaults,
  Postgres opt-in, missing DSN failure, idempotency provider selection, and
  unsafe Postgres identifier rejection.
- Updated the Docker entrypoint to honor `PORT`, `GUNICORN_WORKERS`, and
  `GUNICORN_TIMEOUT` so the VM can run multiple service containers on unique
  host-network ports without changing Cloud Run defaults.

## 2026-06-26

- Changed Runtime V7 Background Signal extraction to fail open after exhausted
  model retries. Gemini/LiteLLM transport or runtime failures now return an
  empty advisory extraction with structured-context candidates only, while
  preserving retry errors, attempt count, and degraded status in
  `background_signal_extraction` metadata. This keeps advisory state failures
  from aborting customer delivery.
- Validation: added a regression proving repeated background extractor
  failures no longer raise from `build_commercial_state_context` and still
  record degraded extraction diagnostics.

## 2026-06-24

- Hardened Runtime V7 conversation hydration segment boundaries so model-facing
  history cannot bridge across stale customer batches. The 30-day checkpoint now
  uses exact elapsed seconds instead of floored calendar days, and undated or
  unparsable prior rows are dropped whenever the current turn has a reliable
  timestamp anchor.
- Validation: added focused ingress regressions for a 30-day-plus-one-minute
  stale gap and for unparsable old request history being excluded from the
  current segment.

## 2026-07-13

- Updated Runtime V7 follow-up context to include a follow-up-safe
  `lead_qualification` packet with present fields, missing fields, priority
  order, next suggested field, and non-lead follow-up fields for installation
  partner, schedule, and payment option. The composer prompt now treats this as
  business guidance rather than a fixed script, preserving natural Taglish
  follow-up wording while avoiding already-known fields. Contact numbers are
  exposed only as `provided` in follow-up model context. Product-list follow-ups
  now prefer a shown-option or brand-choice continuation, with city/barangay as
  an installation-availability alternate, so product-card brands are not treated
  as customer-selected lead facts.
- Replaced the follow-up composer payload's duplicated nested JSON context with
  a plain-text case brief covering only case-specific facts: lead
  qualification, grounded offer highlights, and the recent conversation.
  Reusable task framing, tone, field-priority, pricing, location, and output
  rules now live in the system prompt. Grounded offer labels already shown to
  the customer, such as Buy 3 Get 1 FREE, BPI 6mo 0% interest, Tire Protection
  Plan, warranty, and authorized-partner installation inclusions, may now be
  used to enrich a follow-up. Exact amounts, product links, stock, service
  slots, payment account details, and unverified installation-partner
  availability remain blocked. The redactor no longer corrupts ordinary wording
  such as `budget` or safe promo labels while still removing price/quote/total
  language and amounts.
- Refined follow-up priority handling so the case brief no longer exposes a
  generic `next_best_field` that can conflict with the trigger-specific
  objective. The deterministic goal now tracks one focus field per follow-up
  trigger and persists `last_sent_focus_field` plus `sent_focus_fields` in the
  Runtime V7 follow-up ledger. Duplicate suppression compares the current focus
  field against the previous one, allowing a later rotation trigger, such as a
  12-hour location follow-up after an earlier tire-brand follow-up, while still
  suppressing repeat sends for the same field/context. Tire-brand follow-up
  guidance now asks the model to reason from the shown brands and grounded
  offer highlights in the price list, including at least one concise grounded
  offer/benefit when product options and promos were shown, without scripting a
  specific brand/promo sentence into the case brief.
- Validation: focused follow-up endpoint tests passed
  (`python -m pytest test/test_runtime_v7_followup_endpoint.py`, 31 passed),
  and Runtime V7 follow-up/API modules passed `py_compile`.
- Added a focused Buy 3 Get 1 regression for the live Michelin Primacy 5
  incident shape: `required_brands=["Michelin"]`, `promo_types=["buy3get1"]`,
  `215/55R16`, `promo_tag = 0`, and `sale_tag = 1`. The expected behavior is
  that `/promo_brands` remains the authority, Michelin stays eligible, the
  four-tire total is computed as pay-three, and generic bundle pricing is not
  rendered.

## 2026-06-19

- Fixed Runtime V7 exact-size product presentations so soft
  `preferred_brands` carried from remembered state do not disable the broad
  price-tier ladder. Size-only quote/list requests now keep the Premium-first
  tier order and can expand from three to four cards when four price categories
  are available, while preferred brands only choose the representative within a
  tier.
- Preserved the Premium-tier Michelin preference for those broad ladder
  presentations. Soft preferred brands no longer double-count through
  `match_score`, so Michelin is shown ahead of other Premium brands when
  available unless the request has a hard explicit brand constraint such as
  `required_brands`.
- Validation: added and passed a regression for a `175/70R14` exact-size
  request with four price tiers, `top_k=3`, and non-empty `preferred_brands`,
  confirming Premium, Mid Range, Economy, and Budget cards are all shown with
  Premium first. The full local Runtime V7 suite also passed (`646 passed`).

## 2026-06-15

- Added a Runtime V7 service-location quality guard after a live audit found a
  service phrase (`Free Installation`) being treated as a customer location.
  Service lookup now classifies service-only phrases such as installation,
  delivery, wheel balancing, mounting, valves, service, availability, and
  partner as non-location input, hides that text from model-facing compact
  service results, and asks for the customer's city/area instead of echoing the
  phrase as a failed area match.
- The same guard now protects lead qualification, Background Signal
  normalization, passive tagging, and ManyChat handoff notes. Rejected service
  phrases no longer complete the location lead field, no longer inflate
  Moderate/High Intent location progress, and render in handoff notes as
  `Location: not collected` with city/barangay still listed as needed.
- Validation: focused regressions for service lookup, slot fallback,
  service-observation projection, lead qualification, tagging, and handoff
  note rendering passed, plus nearby existing Runtime V7 service/location,
  tagging, and handoff tests passed. Touched Runtime V7 modules also passed
  `python -m py_compile`.

## 2026-06-14

- Added Runtime V7 lead-qualification CTA focus for product-quote turns. After
  lead qualification, when tire size and brand/product context are known but
  location is missing, the runtime now exposes a model-facing `lead_cta_focus`
  business goal that asks the final composer to softly progress toward
  city/barangay for installation availability. The focus intentionally avoids a
  hardcoded customer-facing CTA string: the model sees the business goal,
  priority missing fields, and constraints such as keeping the location ask
  optional-feeling, keeping product selection secondary unless the customer asks
  to choose/compare, and not saying exact price is missing after product cards.
- Hardened `/gulong/v7/followup` for the ManyChat Last Interaction trigger.
  The endpoint now deterministically routes latest-customer transcripts up to
  24 hours old through normal Runtime V7 chat recovery, suppresses stale
  customer-last triggers, allows proactive assistant-last nudges only in the
  45-minute to 3-hour window, suppresses human-agent takeover, hard-no/order
  completion, stale, and duplicate contexts, and computes a binding
  `deterministic_followup_goal` before the composer model writes copy. The
  missing-location goal asks for a light one-hour nudge to share city/barangay
  only if the customer wants installation availability checked next, while
  explicitly avoiding repeat tire-size, brand, or product-choice asks.
- Added Runtime V7 ManyChat handoff notes for newly applied Moderate/High
  Intent tags through the existing ManyChat `createNote` boundary. Notes are
  human-readable bullet summaries with customer context, latest customer
  message, Asia/Manila human-native timestamp, still-needed fields, suggested
  next reply, and a High Intent reason when applicable. Existing tags do not
  create duplicate notes.
- Normalized timezone-aware follow-up timestamps to Asia/Manila before
  deterministic age checks. This keeps `2026-06-14T13:07:44+08:00` style
  trigger payloads in the same comparison frame as runtime request times and
  prevents valid one-hour follow-ups from being misread as stale.
- Validation and deploy: focused local Runtime V7 tests passed
  (`69 passed`), staging release `478541b` passed product-quote CTA,
  60-minute missing-location follow-up, and too-early suppression probes, then
  live promotion `ff0e53c` deployed to
  `gulong-chatbot-runtime-live-00017-cj9` with build
  `7d0c7412-f2c9-4618-a85c-8bc9a0d3bf9e`. Live return-only probe artifact:
  `tmp/runtime_v7_live_soft_cta_ff0e53c/final_summary.json`.

## 2026-06-13

- Added authoritative Runtime V7 product-card pricing facts to stored product
  observations. Follow-up turns now expose `payable_total` as the amount the
  customer pays for the shown quantity, with total savings and included promos
  marked as already reflected in that payable total.
- Added a final-response pricing guard for unsupported visible-product payable
  totals. When the model introduces a PHP amount that is not grounded in the
  latest trusted product-card pricing facts, Runtime V7 first asks a small
  structured pricing-repair composer to regenerate the clarification from the
  authoritative card facts. The deterministic clarification is now only the
  final fallback if the repair model is unavailable or still emits an
  unsupported amount. Same-turn order/payment tools remain allowed to introduce
  their own trusted totals.

## 2026-06-11

- Added a deterministic Runtime V7 product-presentation ranking rule for broad
  Premium-category searches: Michelin is shown ahead of Yokohama when the
  customer has not explicitly requested/preferred a brand and the turn is not a
  budget, promo-only, or model-specific request. Explicit Yokohama requests and
  preferred-brand order are preserved.
- Hotfixed Runtime V7 product presentation cards so four-tire totals render as
  `if for 4 tires`, matching the requested customer-facing wording.
- Enriched product-card warranty normalization from API warranty fields,
  `warranty_year`, warranty badge URLs, and conservative brand fallbacks so
  shown products include manufacturer warranty before any Tire Protection Plan
  line.
- Added regression coverage for BFGoodrich and Yokohama products with both
  PHP 1,000 off/tire promos and bundle pricing, ensuring four-tire totals use
  the bundle-tier total (for example BFGoodrich PHP 20,250.00) while savings
  still separates per-tire promo and bundle savings.

## 2026-06-28

- Fixed Runtime V7 follow-up hydration for empty follow-up trigger payloads.
  Follow-up requests now refresh live ManyChat channel history even when the
  trigger has no `user_text`, preventing stale cached assistant-last history
  from suppressing sessions whose actual latest visible message is from the
  customer. The ManyChat fast loader now also tolerates commented Python-literal
  header secrets before falling back to `{}`, matching the live app-header
  format used for `loadMessages`.

## 2026-06-09

- Updated Runtime V7 product-card price formatting to show the base price per
  tire and the total for the requested quantity, instead of an "effective price
  per tire" figure. Quantity=1 cards now show only the one-tire base price and
  suppress bundle/promo/savings lines. Quantity 2-4 cards show the quantity
  total and a separate savings line only when trusted bundle/promo math produces
  an actual savings amount.

- Product-level PHP off/tire promos now use the trusted list/SRP as the
  product-card base price and compute savings against that baseline, so the
  displayed savings includes both the per-tire promo discount and any quantity
  bundle savings already reflected in the quantity total. When both a PHP
  off/tire promo and bundle-tier savings are present, the card shows those promo
  components separately, then shows total savings versus the base list price.

- Updated Runtime V7 delivery-fee policy so only Premium category products have
  free delivery. Apollo is no longer a free-delivery brand override; Apollo
  products now follow their trusted product category, so Budget/Economy/Mid-Range
  Apollo products use the standard PHP 500 delivery fee.

- Added a Runtime V7 central policy FAQ facade for cross-domain service/order
  policy questions such as free delivery, shipping fee, and delivery fee. The
  facade routes delivery-fee policy to the order FAQ domain, preserves metadata
  that the answer is policy-general, and tells the model to apply the policy to
  trusted visible product context instead of reciting the full FAQ. The
  installation slots tool no longer advertises `delivery` as a supported
  `service_type`; if delivery still reaches the tool, it now returns
  `not_applicable_for_delivery` without partner lookup or
  `no_installation_partner_match`, with explicit guidance to answer delivery via
  policy/quote and check installation slots separately when Metro Manila
  install-first applies.

- Suppressed Runtime V7 anonymous area-only installation partner cards when
  `find_installation_partners` recommends `find_installation_slots` as the next
  tool. These partner rows remain trusted internal coverage proof, but they no
  longer render customer-facing "Installation partner option 1/2/3" choices by
  themselves because that presentation hides useful partner identity/address
  detail without giving the customer actionable schedules. The compact tool
  result now marks these cards as suppressed and removes render surfaces. If the
  model tries to answer after only the hidden partner lookup, the harness now
  performs one forced `find_installation_slots` follow-up and drops stale
  partner-choice CTAs once slot cards are rendered.

## 2026-06-04

- Disabled Runtime V7 explicit Gemini context caching by default to stop cached-content storage cost spikes. Production deploys now set `RUNTIME_V7_ENABLE_CONTEXT_CACHE=0`, `RUNTIME_V7_MAIN_ENABLE_CONTEXT_CACHE=0`, `RUNTIME_V7_MEMORY_ENABLE_CONTEXT_CACHE=0`, `RUNTIME_V7_BACKGROUND_SIGNAL_ENABLE_CONTEXT_CACHE=0`, and `RUNTIME_V7_FOLLOWUP_ENABLE_CONTEXT_CACHE=0`; the fallback TTL is now `300s` for any deliberate future re-enable. Cache control is component-scoped: the legacy `RUNTIME_V7_ENABLE_CONTEXT_CACHE` only acts as a main-orchestrator fallback when `RUNTIME_V7_MAIN_ENABLE_CONTEXT_CACHE` is unset, while memory/background/follow-up remain off unless their own flags are enabled. Runtime debug payloads now include `context_cache_summary`, and each `llm_span_log.meta` includes `cache_summary` plus the existing `request_cache` detail so staging/live can verify `explicit_cache_enabled=false` without relying on billing lag.
- Bootstrapped clean `gulong-chatbot-runtime` repository from the Runtime V7 product-search foundation worktree.
- Kept deployable behavior under `runtime_v7`; retained `runtime` only for shared gateways, storage, config, and analytics plumbing.
- Added V7-only FastAPI routes, release metadata, Cloud Build CI/CD, staging/live branch policy, and native normalized Runtime V7 analytics rows.
- Updated Runtime V7 ManyChat history hydration to retain automated outbound ManyChat flow messages. The V7-owned `loadMessages` reader now accepts `msgout_default` outbound text turns, marks them as `manychat_automation`, and keeps them as assistant continuity evidence in the channel-history cache and model-facing Recent Conversation section. The runtime loader intentionally does not set `hide_automation=1`, because V7 needs welcome/intake automation context when ManyChat returns it. These messages remain conversation context only, not validated product, price, order, payment, schedule, or service facts.
- Updated Runtime V7 generic location response guidance. Exact automated `Where are you located` turns now use the same direct answer shape as recent human-agent spiels: Gulong.ph is online, has 100+ installation partners across Metro Manila, CALABARZON, Pampanga, and Bulacan, includes free mounting/balancing/weights/valves, and requires reservation/booking because fresh warehouse stocks are sent to the partner after reservation. Free-text generic location questions, including `location po`, now stay in the full Runtime V7 path with model-facing guidance to answer directly first, preserve paragraph breaks, include the reservation/fresh-stock sentence, and avoid asking "Para saan po ang location?". Mixed location/product turns preserve concrete Background Signal facts and continue through the full Runtime V7 flow instead of sending the generic location response by itself.
- Fixed Runtime V7 static landmark service fallback for no-geocoder partner lookups. `normalize_location_text` now keeps already-canonical phrases like `sm megamall` from expanding to `sm sm megamall`, and `find_installation_partners` can use a known point landmark's city hint for area-level partner matching when no coordinates are available, preserving staged disclosure while avoiding false no-match/delivery fallback responses for serviceable landmarks such as SM Megamall, Mandaluyong.
- Hardened Runtime V7 Mirage G4 vehicle canonicalization across BSE and fitment. Known Mitsubishi Mirage G4 aliases now normalize missing-make or shorthand variants such as `mirage g4`, `car_make_model=Mirage G4`, `car_make=Mirage` plus `car_model=G4`, and `GLS G4 mitsubishi` to `Mitsubishi Mirage G4` before storing Background Signals and before calling `/car_tire_sizes`, while preserving raw customer text separately in fitment diagnostics.
- Repaired Runtime V7 Buy 3 Get 1 BSE handling. Promo wording such as `3+1`, `3plus1`, and `buy 3 take 1` now produces both `promo_types=buy3get1` and implied `quantity=4`, because Buy 3 Get 1 interest means four tires total unless the customer explicitly states a different quantity.
- Added a Runtime V7 product-presentation inclusions bubble. Product and selected-product surfaces now render a data-aware `Warranty and inclusions` block after the shown cards, including the Tire Protection Plan explanation only when a shown card has TPP and bullet-style installation inclusions with the brand-new/warranty assurance line unless the turn context is delivery. Manufacturer warranty details remain on the individual product cards instead of being repeated in this bubble.
- Added a Runtime V7 first-turn welcome/intake intro. The final composer inserts the three-message welcome, info request, and tire-size guide when hydrated recent turns have no prior assistant/chatbot, human-agent, or ManyChat automation outbound message, no active working memory, and the latest customer message has no actionable details, including exact automated starter-button turns before the deterministic button answer. Actionable latest messages such as tire sizes, concrete vehicle hints, brand/budget/quantity/contact details, and specific service/order questions receive only the compact welcome bubble before continuing through the normal lead or full-runtime path. The runtime passes first-turn intro context to the main model, lead qualifier, and final composer so each model writes the natural continuation after the runtime-owned intro instead of opening with another greeting. The channel renderer mirrors the insertion as customer-visible bubbles for structured responses without duplicating fallback text that already contains the intro.
- Added reusable Runtime V7 live probe assets in the clean runtime repository. The restored `scripts/runtime_v7_live_test_pack.py` and `test_packs/runtime_v7_live_model_test_pack.json` cover broader harness-level live model probes, while `test_packs/runtime_v7_first_turn_intro_live_pack.json` and `scripts/runtime_v7_first_turn_intro_endpoint_probe.py` target first-turn intro scenarios through the return-only tester endpoint for customer-visible bubble assertions.
- Hardened Runtime V7 first-turn endpoint probes and fallback observability. Seeded-history endpoint scenarios now keep `reset=0` so request-provided prior assistant, human-agent, and ManyChat automation messages are actually hydrated instead of discarded by reset semantics. The lead-qualifier and first-turn context now explicitly tell the model not to start the runtime-owned-intro continuation with `Hi po`, `Hello`, `Good day`, or another welcome, and the live endpoint probe fails that repeated-greeting shape. Unexpected Runtime V7 API exceptions are now logged with request identifiers before the unchanged safe customer fallback is returned.
- Updated Runtime V7 product presentation rendering to keep shown product SKU cards in one bubble when they fit channel limits, falling back to limit-based splitting only for long card sets. The `Warranty and inclusions` bubble is now session-scoped through `strategy_state.runtime_v7.product_inclusions_sent`, and existing sessions can infer the flag from hydrated prior transcript text containing the inclusions block.
- Added Runtime V7 ManyChat bubble pacing for live send modes. When a rendered reply contains adjacent text bubbles, the API delivery boundary can send them as separate `sendContent` calls with a short delay between text-to-text bubbles, defaulting to `RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS=1200` and capped by `RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MAX_MESSAGES=6`; return-only/tester paths and payloads without adjacent text bubbles stay on the existing no-delay batch path.
- Tightened Runtime V7 generic price/location response quality without adding a free-text intent classifier. Free-text turns such as `how much` and `location po` remain model-led with response-seed/context guidance, while the final response guard removes prohibited clarification phrasing such as `Para saan po 'yan?`, `Para saan po pala, ...`, or `Para saan po ang location?` from model output and rewrites weak generated prefixes such as `Para sa anong tire size` into direct tire-size questions. Exact ManyChat button/postback responses remain the only deterministic generic-location shortcut.
- Strengthened Runtime V7 mixed product/location tool objectives without adding raw-text intent matching. When model-extracted latest-turn signals include both product context, such as a tire size, and a customer location, the prompt now lists both product discovery and read-only service partner coverage as primary objectives so the model should call `product_search` and the relevant installation service tool before finalizing.
- Strengthened Runtime V7 first-turn intro continuation guidance after staging endpoint probe `runtime_v7_first_turn_endpoint_20260604_214407` found a duplicate `Hi po!` opening after the runtime-owned full-intake intro. The lead qualifier and final composer now explicitly require a non-greeting action phrase such as `Send niyo lang po` or `Pwede niyo pong` when `first_turn_intro_context.mode=full_intake`, without adding post-response greeting stripping.
- Fixed Runtime V7 normalized analytics durability on Cloud Run. `request_state_log`, `request_attempt_log`, `turn_trace_log`, `turn_fact_log`, `llm_span_log`, and `tool_call_log` now flush their BigQuery writer buffer immediately after enqueue, matching the existing `debug_log` behavior, so short-lived request workers do not leave normalized rows waiting on a timer.
- Added `POST /gulong/v7/followup` for proactive Runtime V7 follow-ups. The endpoint loads durable session/channel context, uses a lightweight follow-up decision model to abort or continue, uses a separate composer model for one short meaningful sales follow-up, then sends through the existing ManyChat delivery boundary. It persists `strategy_state.runtime_v7.followup`, suppresses repeat sends for the latest visible follow-up, performs the pre-delivery freshness check, and emits the existing debug, turn fact, turn trace, and LLM span logs. Follow-up model clients default Gemini thinking to disabled so short structured decision/composer responses do not spend the output budget on hidden reasoning. Eligibility is sales-permissive: old waiting-response suppressions can be overridden into sends when no hard stop signal is present. Follow-up composer context is compacted and includes tone guidance to match the main Runtime V7 chatbot voice, especially casual Taglish when the thread uses Filipino/Taglish or `po`. Follow-up context now includes `normalized_entities`, a deterministic projection from stored Background Signals and recent turns through the central Runtime V7 signal/entity normalizer, so composer-facing context prefers canonical values such as `Westlake` over raw transcript typo variants. Follow-up composer guidance and fallback copy require a concrete reply/action CTA, not only a neutral check-in. Follow-up copy is sanitized to remove product links/trailing generic thanks, normalize English `let me know` phrasing, remove unbacked pricing/promo clauses, drop candidate-size list sentences, and add a friendly emoji when missing. Composer context, debug decision/composer fields, and the durable follow-up ledger redact pricing/promo terms because the endpoint does not refresh trusted product/pricing tools and should not echo transcript prices, quotes, estimates, totals, budgets, discounts, promos, savings, or Buy 3 Get 1 details. Invalid or empty composer output falls back to a safe no-pricing Taglish follow-up. Latest-customer transcripts from the follow-up trigger are routed to the full Runtime V7 chat path with a deterministic late-reply apology seed instead of proactive follow-up copy. The final no-send Jeanel sample artifact `tmp/runtime_v7_followup_dry_samples_20260604_normalized_entities_cta_v2_summary.json` showed six return-only follow-up candidates using `gemini/gemini-2.5-flash-lite`, with zero pricing/promo/`Wedtlake` hits in customer-visible messages and stronger reply CTAs.

## 2026-06-05

- Hardened Runtime V7 staging-probe regressions before product deployment. Explicit fitment rim clues such as `rim 15` now hard-filter compatible-size candidates when at least one catalog candidate matches, preventing mixed R15/R16/R17/R18 candidate lists from leaking into BSE/model context for an Innova R15 query. Buy 3 Get 1 repair now recognizes spaced `3 + 1` phrasing and replaces stale prior quantity signals when the latest user turn introduces the promo without restating the old quantity, so the current path uses implied `quantity=4`. The local Runtime V7 harness now tracks whether the product `Warranty and inclusions` block has already been shown in the session and suppresses repeats in subsequent product turns, matching the persisted API/session behavior.
- Validation before staging merge: targeted hardening slice `8 passed`, broader Runtime V7 product/search/channel/trace slice `557 passed`, full local suite `609 passed`, high-priority live multi-turn harness pack `mt01`-`mt04` completed without aborts with corrected Innova R15 candidates, Buy 3 Get 1 quantity/tool args, and one inclusions block per session, and the 9-scenario first-turn live harness pack completed without aborts.
- Fixed the API/channel renderer ordering for product inclusions after staging endpoint observation. The API now captures `product_inclusions_previously_sent` before `harness.run_turn()`, because the harness may mark the session flag true while composing its internal final text. This preserves the first visible `Warranty and inclusions` bubble on deployed return-only/send paths while still saving the session flag afterward to prevent repeats.
- Added bounded Runtime V7 session-lock recovery for chat and follow-up ingress. When the initial per-session lock wait is exhausted, normal chat requests now refresh visible ManyChat history, select the latest visible customer message when it differs from the triggering payload, wait one additional bounded window (`RUNTIME_V7_SESSION_LOCK_RECOVERY_WAIT_S`, default 45 seconds), reload durable session state after the prior turn completes, and run the full Runtime V7 chat path instead of returning an empty customer-visible busy response. Follow-up triggers also use the bounded secondary wait before evaluating the latest durable/channel context, so a locked follow-up can still route a latest-customer transcript through normal chat after the prior turn finishes. If the lock remains held, the existing retryable `session_busy_retry_later` result is preserved with `session_lock_recovery` metadata in the turn trace and delivery result.

## 2026-07-21

- Added explicit promo-gallery redisplay. The model may set `explicit_redisplay=true` only when the latest customer message explicitly asks to see, reopen, or resend the promo cards/gallery. That new customer request bypasses the session's catalog-version/fingerprint repeat guard, while automatic discovery, ordinary follow-ups, and delivery retries remain suppressed. The redisplay flag is persisted in presentation state and response metadata for funnel analysis.

## 2026-07-24 - Preserve validated installation selection across later lookups

- Service state now resolves the newest `slot_validated` observation instead
  of assuming the latest service observation is still the validation result.
  Later read-only partner or FAQ lookups therefore cannot erase the selected
  partner/schedule used by order readiness.
- The initial model context and final composer both receive the same trusted
  validated partner/slot context. They disclose the exact partner at the
  approved proceed/detail stage, avoid redisplaying general partner choices,
  and advance to the next unresolved order field without claiming a booking.
- An exact customer date/time choice is now treated as a proposed slot plan:
  if the model performs another slot lookup, the runtime requires a subsequent
  `validate_installation_slot` pass against the visible candidates. Natural
  date/time text binds only when it resolves to exactly one trusted slot.
- Validated slot candidates retain the selected partner's address and location
  fields, so approved high-intent disclosure can use the exact trusted address
  without performing another broad partner lookup.

## 2026-07-24 - Qualification choices and checkout controls

- Scoped one-primary-decision behavior to lead qualification through schedule
  selection. If multiple products and schedules are available in one turn,
  product selection owns the customer controls and schedule controls are
  deferred. A single visible product is auto-selected and does not receive an
  unnecessary SKU-choice button.
- Replaced free-text slot rows with one Messenger card per day. Each card shows
  at most two well-distributed morning times plus the channel-safe
  `Anytime in afternoon` button. The underlying choice label remains
  `Anytime in the afternoon`; it is always shown for a displayed day, while
  individual afternoon times are hidden.
- Exact time clicks are checked against the delivered schedule presentation and
  then passed through `validate_installation_slot`. The afternoon control is a
  flexible customer preference even when current afternoon rows exist; it never
  authorizes a current-availability, booking, or reservation claim.
- After an exact schedule is selected, the bot may request contact number, full
  name, email, and Pay Now/Pay Later together for the order form/summary.
  Runtime also attaches optional payment controls: Pay Now/Pay Later amounts
  come from the read-only quote, and method choices come from active
  `/payment/list` metadata filtered by payment option, selected brand, and
  fulfillment transaction.
- Schedule, payment-option, and payment-method controls use the existing
  delivered-choice allowlist, compact ManyChat router tokens, durable session
  history, and interaction events. Typed answers remain supported.
- Choice-action requests now hydrate from the session-authoritative delivered
  ledger/cache and cannot be replaced by an older visible ManyChat message
  during normal hydration or busy-lock recovery. This keeps a reset trial
  segment isolated even though synthetic button payloads are not transcript
  messages.
- Checkout controls are admitted only after the service-specific qualification
  boundary: an exact or flexible schedule choice for installation/pickup, or a
  complete address for delivery. Product/location clicks own their turn, and
  stale payment fields cannot append checkout controls beside them. This does
  not change the accepted bundled order-form request after schedule selection.
- Interactive click paraphrases use `shown` instead of the ambiguous
  `delivered`, and fulfillment aliasing no longer treats the past participle
  alone as delivery intent. Explicit wording such as `delivery`, `deliver`, or
  `delivered to <location>` remains recognized. This preserves a prior
  installation choice across product, schedule, and payment clicks.
- When slot discovery ran in the same turn as multiple product cards, Runtime
  keeps the slot observation hidden until the product decision. A validated
  product click now reattaches that same trusted schedule presentation from
  the session service-observation store. It does not repeat the API lookup or
  depend on the model calling the slot tool again.
- The post-schedule Pay Now/Pay Later surface reuses the current
  `build_order_summary.quote_summary.payment_options_preview` when available,
  while labels/IDs still come from checkout metadata. Debug output records
  whether checkout controls attached or the generic gate that withheld them.

## 2026-07-24 - Order UX grounding review and simplification

- Reconstructed the July 24 trial path from
  `manychat_data.messages` for user `4843256405786522`. Message
  `25445704670` showed product and schedule decisions together, while
  `25445704456` switched a known installation path to delivery. The review
  treated these as state/decision-boundary failures rather than copy-only
  defects.
- Centralized the qualification rule used by the final composer and channel
  renderer: whenever more than one current product card is visible, product
  selection is the only active decision. Partner/schedule controls are
  deferred, while a verified service no-match remains visible as a concise
  notice without adding a delivery-address CTA.
- Checkout attachment now uses the same rule, so stale selected-product,
  schedule, address, or payment state cannot place payment controls beside a
  new product decision. API-attached checkout cards receive a short
  runtime-owned introduction only when the model did not already provide one.
- Deferred slot controls are reusable only for the same normalized customer
  location and for ten minutes. A valid product click receives one concise
  selected-product acknowledgement followed by the schedule controls; stale
  or cross-location observations are not replayed.
- Product, service, and FAQ objectives can still coexist, but service and FAQ
  work is conditional in mixed turns. The model completes it in the same turn
  only when the latest customer message directly asks that question. Generic
  lexical overlap no longer makes unrelated FAQ retrieval mandatory.
- Choice-action routes now preserve Runtime V7's delivered-allowlist result.
  A parsed token can no longer overwrite an internal stale decision with a
  public `accepted` status. Return-only evaluations are recorded separately
  from failed sends so isolated adaptive tests can exercise subsequent clicks.
  The deployed adaptive probe also verified that the return-only transport
  reports `status=skipped, reason=return_only` without always echoing a
  `delivery_mode`; the shared classifier accepts either form. Stale non-location
  clicks no longer receive a misleading `location:` diagnostic ref.
- Session `load()` remains the sole owner of the
  `user -> active_session_id` pointer. A long-running superseded turn can save
  its own session document but cannot reactivate that old session after a
  reset.
- Typed payment methods fail closed when an authoritative API-backed checkout
  catalog was expected but returned no payment rows. With active
  `/payment/list` metadata, unsupported methods are rejected generically and
  supported method/brand/fulfillment combinations remain data-driven.
- Payment-method cards keep their rows, Pay Now/Pay Later association,
  installment compatibility, and brand exclusions from `/payment/list`, but
  prefer the API's specific method name over a generic label. Their short
  customer description is generated from the already-selected Pay Now/Pay
  Later layer so stale upstream copy cannot tell a Pay Now customer to pay
  after service or submit a reservation fee.
- A deployed fresh-session Home Credit inquiry showed that normalization
  correctly recorded `checkout_metadata_no_match`, but capability compilation
  exposed only product tools. `answer_order_faq` now declares the structured
  payment signal keys it can validate. This applies to any named payment
  method or Pay Now/Pay Later signal; the model decides whether the latest
  message is an inquiry or only a preference, while `/payment/list` remains
  the resolver authority.
- The same deployed replay then exposed a second boundary defect: the model
  proposed `requested_payment_method=Home Credit` without choosing a FAQ id,
  the generic FAQ matcher returned `no_match`, and the model happened to give
  the correct unsupported answer anyway. Any typed
  `requested_payment_method` query now deterministically selects the payment
  policy entry before resolving the proposed method against current
  `/payment/list` metadata. Unknown methods, supported methods, and
  brand-level installment inquiries therefore share one source-backed path
  without brand or provider special cases.
- Named-method replies now keep the full active catalog as structured evidence
  but do not place that entire list in the answer text. The composer answers
  the requested method directly and may offer at most three relevant
  alternatives; generic "how can I pay?" questions still receive the complete
  Pay Now/Pay Later catalog.
- Payment-policy tool evidence also carries the checkout metadata generation
  time and cache TTL supplied by the API-backed provider. These fields stay
  model-visible as freshness evidence instead of being dropped by the shared
  canonical metadata wrapper.
- Active Working Memory no longer sends runtime assistant turns or raw
  assistant response prose to its compactor as fact evidence. Customer and
  human-agent turns remain available, while tool-backed turns use a
  deterministic evidence-only compactor that persists normalized customer
  signals and stable product, service, order, or payment refs rather than
  copying totals, discounts, eligibility, partner details, or availability
  statements. This also removes one memory-model call from the tool-heavy
  shopping path.
- Tool schemas describe a generic named payment method or financing provider;
  they no longer prime one unsupported lender name. Regression coverage uses a
  second unknown provider to verify that rejection comes from catalog absence,
  not a Home Credit exception.
- A Pay Now replay showed customer-area/partner-address leakage: readiness
  still held `San Pedro, Laguna`, but model summary args supplied the selected
  partner city `Biñan, Laguna` as `location`. Installation, pickup, and home
  service summary/payload validation now prefer the readiness/customer
  location, then the structured location signal, and treat model args as the
  final fallback. Partner identity/address remains a separate validated service
  field.

Validation:

- Ruff on every changed runtime/router/test file: passed.
- Focused interaction, renderer, router, ingress, and session regressions:
  `120 passed`.
- Full local suite: `944 passed`.
- Repository-wide Ruff still reports 18 pre-existing findings in unrelated
  legacy ManyChat/storage/scripts files; none are in this change set.

## 2026-07-24 - Mandatory commercial authority on unanswered inquiries

- Exact-revision acceptance found two remaining tool-omission failures: an
  unknown financing provider could be accepted without `/payment/list`, and a
  current brand-specific Buy 3 Get 1 question could be deferred without the
  reviewed promo catalog.
- Runtime now performs one forced, source-specific retry when a current typed
  commercial objective has no authority result: `search_promo_catalog` for a
  current promo objective, or `answer_order_faq` for an unanswered
  payment-policy FAQ hint. The model still proposes the brand/provider values;
  the runtime tool validates them.
- The retry does not fire for an already chosen payment method, after another
  product/payment evidence tool has run, or from a stale promo signal alone.
  This preserves COD and order progression without needless policy calls.
- If the forced payment lookup omits the provider argument, Runtime hydrates
  `requested_payment_method` only from a latest-turn signal explicitly marked
  `mentioned_unconfirmed`. A normal chosen payment signal is not recast as an
  inquiry, and a model-supplied provider remains authoritative as the proposed
  lookup value.
- Exact checkout replay exposed ManyChat's 80-character subtitle truncation:
  the shared Pay Now description ended at an incomplete `already`. Payment
  method descriptions are now complete within the channel limit for both Pay
  Now and Pay Later; exact totals and fee details remain in the order summary.

Validation:

- Changed-file Ruff: passed.
- Focused commercial retry/hydration regressions: `8 passed`.
- Full Runtime V7 suite: `895 passed`.
- Full repository suite: `957 passed`.

## 2026-07-25 - Promo information actions do not select or qualify

Trial evidence:

- Trial user `4843256405786522` clicked `Promo Details` on the active Michelin
  card at `2026-07-25 21:59:14 +08:00`.
- Staging request `req_781a97197da341e78836c810b7898a31` validated the current
  catalog/card/action and carried `selected_brand=""`.
- Runtime nevertheless converted the click to a synthetic brand-named customer
  message, instructed the model to advance qualification, and persisted
  Michelin as a preference. The model asked for location, but the province
  surface was not attached because the model-only question did not establish
  the runtime location-focus contract.

Action contract:

| Action | Meaning | May write a brand query preference | May advance qualification |
| --- | --- | --- | --- |
| `promo_details` | Read reviewed promo mechanics | No | No |
| `about_brand` | Read reviewed brand profile | No | No |
| `check_price` | Request grounded products/prices | Yes | After grounded results |
| `choose_brand` | Explicitly narrow product discovery | Yes | After grounded results |

Implementation:

- Valid informational clicks render directly from the already validated
  catalog mechanics or brand profile. They do not call the model or repeat a
  catalog search.
- The informational response stays in the promo decision layer and offers only
  two next steps: check eligible products/prices or compare promos.
- Informational clicks do not copy card brand or selected-product size into
  qualification profile fields, do not attach location/schedule/payment
  surfaces, and do not run checkout progression.
- The validated promo context and click ledger remain available for audit.
  Existing customer-selected product or brand state is preserved; the
  informational click neither creates nor supersedes it.
- The same action semantics apply to every reviewed catalog brand and promo;
  there are no Michelin-, Apollo-, Toyo-, or SKU-specific branches.

Validation:

- Changed-file Ruff: passed.
- Focused promo, renderer, location, checkout, and ingress regressions:
  `185 passed`.
- Full repository suite: `986 passed`.
- Repository-wide Ruff still reports the same 18 pre-existing findings in
  unrelated legacy ManyChat, storage, runtime, and script files; none are in
  this change set.
- Deployed staging validation remains required before any production
  promotion.

## 2026-07-25 - Flexible afternoon schedule and order-summary progression

Trial evidence:

- Staging request `req_11130dbe0a2f48a7a10928e92ef07930` successfully
  extracted and persisted the customer's name, contact number, and email.
- Order readiness nevertheless remained incomplete because the earlier
  `Anytime in the afternoon` action was stored only as an unvalidated
  preference. The model therefore acknowledged the contact fields without
  calling the deterministic order-summary tool.

Implementation:

- Each schedule-day `Anytime in the afternoon` choice now carries the earliest
  actual afternoon slot from the delivered trusted observation. Clicking it
  validates that exact slot and preserves the associated installation partner
  evidence. Individual afternoon times remain hidden from the card.
- When the delivered observation has no afternoon slot, the action records
  `12:00 PM` as a flexible preference. It remains summary-ready but is not an
  availability, booking, payload, or submission claim.
- Order readiness now separates customer-review readiness from submission
  readiness through `schedule_status` and `submission_blockers`. A validated
  flexible preference may render the deterministic order summary, while
  `build_order_payload` remains gated on an exact validated service slot.
- Completing requested contact/form fields can therefore activate the existing
  runtime-owned order-summary retry in the same turn. The response cannot stop
  after a contact acknowledgement when the summary is ready.
- The deterministic summary keeps the selected schedule visible. A noon
  fallback explicitly marks the installation partner/time as pending
  validation rather than silently clearing or re-asking already supplied
  customer information.

Validation:

- Changed-file Ruff: passed.
- Focused transaction-choice and order-state regressions: `532 passed`.
- Runtime V7 suite: `928 passed`.
- Ingress-trace suite: `42 passed`.
- Full repository suite: `990 passed`.
- Deployed staging validation remains a release gate.

## 2026-07-30 - Reconcile promo authorities and defer later choice layers

- Kept `/promo_brands` authoritative for current brand-level Buy 3 Get 1
  eligibility. A reviewed promo-gallery record supplies curated mechanics and
  gallery content, but absence from that catalog does not revoke a brand
  returned by the live eligibility endpoint.
- Reconciled catalog negative matches with the product search
  `promo_evidence.verified_brands` contract before suppressing a product
  surface or rewriting a promo answer. The rule is source- and
  version-driven; it contains no brand-specific allowlist.
- Made any rendered product-search surface, including a single exact SKU, own
  the current product decision. Prepared location and checkout choices are
  retained as optional later surfaces instead of competing in the same turn.
- When a requested promo brand is absent from both the reviewed catalog and
  the live promo-brand authority, the validated alternative promo gallery
  owns the turn and partial product/location surfaces are deferred.
- Brandless Buy 3 Get 1 discovery without a tire size also keeps the reviewed
  promo gallery as the active surface. Arbitrary SKU examples returned by an
  over-broad model tool plan are deferred until the customer supplies a size
  or chooses a promo action.
- Added a reusable return-only staging matrix covering promo positives and
  negatives, payment compatibility, exact availability, size normalization,
  province authorization, non-linear product/location/schedule progression,
  and informational promo clicks.

Validation:

- Changed-file Ruff: passed.
- Focused turn-plan and commercial regressions: `113 passed`.
- Broader Runtime V7 regressions: `881 passed`.
- Full repository suite: `1146 passed`.
- Deployed staging and controlled trial-account validation remain release
  gates.

## 2026-07-26 - Align multi-product CTA with SKU controls

Trial evidence:

- Staging request `req_77ef73e2ca394a92b4359b25616bbb2c` on release
  `0fe0fe6` showed that missing-location lead focus could remain active while
  product discovery rendered multiple exact SKU controls.
- The composer therefore received conflicting instructions: product selection
  owned the visible decision, but location was still declared the primary CTA.

Implementation:

- The shared primary-decision result now supersedes missing-location focus when
  more than one exact product is visible.
- The final composer receives one aligned `product_selection` CTA focus:
  choose one visible SKU first; location, schedule, payment, contact, and order
  details wait for later turns.
- The channel renderer enforces the same invariant on the delivered response.
  It preserves renderer-owned product facts and inclusions, removes a competing
  post-card question, and ends with one generic product-selection CTA.
- The behavior is based on visible product-choice count and trusted card refs;
  it contains no brand, SKU, promo, or location-specific exceptions. Customers
  may still type their product choice instead of using a button.

Validation:

- Changed-file Ruff: passed.
- Focused lead-focus, transaction-choice, and channel-renderer regressions:
  `92 passed`.
- Runtime V7 suite: `931 passed`.
- Ingress-trace suite: `42 passed`.
- Full repository suite: `993 passed`.
- Staging validation remains a release gate.

## 2026-07-26 - Unify decision authority and typed product selection

Problem:

- The main CTA policy still preferred guided priority questions while the
  renderer required one exact SKU-selection question.
- The final composer received multiple overlapping next-step inputs and could
  treat a readiness field as more important than the runtime's active product
  decision.
- Free-text product selection was model-led and ref-validated, but a brand-only
  phrase could still be bound to one valid ref even when several visible SKUs
  shared that brand.

Implementation:

- Added one post-tool `decision_contract` for final composition. It declares
  the active decision, allowed customer input, deferred customer inputs, and
  deferred surface refs. Lead focus and order readiness remain useful runtime
  state but no longer appear as competing final-composer decision authorities.
- Aligned the static CTA policy with the renderer: when multiple exact SKU
  controls are visible, ask for one exact product and defer location, schedule,
  payment, contact, and order details.
- Added a typed product-reference plan with generic `exact_ref`, `ordinal`,
  `brand`, `model`, and `attribute` bases. Runtime checks brand/model
  cardinality against trusted visible cards and returns `ambiguous` instead of
  silently selecting one of multiple same-brand or same-model candidates.
- Exact button actions continue to bind directly through the delivered
  presentation ledger. Free-text interpretation remains model-led; runtime
  validates the proposed typed plan without adding brand-, SKU-, promo-, or
  keyword-specific rules.
- Adaptive staging request `req_6eb0765f7af34bac850edf96ec8fc661`
  showed that a bare brand reply after visible products could still start a new
  `product_search`. Structured latest-turn brand/model signals plus an existing
  product presentation now make visible-reference resolution the primary
  objective, with product search retained only as fallback when the brand/model
  is not one of the visible options.
- Follow-up staging request `req_58ca11ab2ae2489d8a75550d35df3f93`
  correctly asked the customer to choose between the visible Michelin Primacy
  SUV+ and LTX Trail SKUs, but still attached province controls. The same
  structured ambiguous-brand resolution now feeds the shared pre-tool
  qualification decision, so product selection suppresses location controls
  even when the model correctly answers without another tool call.

Validation:

- Changed-file Ruff: passed.
- Focused prompt, product-reference, transaction-choice, product-choice, and
  lead-focus regressions: `579 passed`.
- Runtime V7 suite: `937 passed`.
- Ingress-trace suite: `42 passed`.
- Full repository suite: `1003 passed`.
- Adaptive deployed-model simulations and staging/live candidate validation
  remain release gates. The local live-model pack could not authenticate from
  the clean worktree, so deployed staging is the required credentialed model
  test surface.

### 2026-07-29: Customer-backed promo query-plan scope

- `search_promo_catalog` model arguments remain retrieval proposals. Runtime
  now carries the exact latest customer text and normalized latest-turn brand
  signals separately from the model query.
- Latest-turn signal labels are not sufficient authority by themselves: a
  proposed brand must also be present in the actual customer text before it can
  scope retrieval or negative-match reporting.
- The catalog removes brands present only in the model plan before vector
  retrieval, constraint matching, and negative-match reporting. Customer-
  authored brands omitted by the model are restored.
- Runtime also applies the catalog's bounded five-candidate targeted default
  when the model proposes a smaller result set. This prevents a one-result
  plan from dropping valid source-backed alternatives without adding another
  API or model call.
- The boundary is generic across brands and promo types; it introduces no
  brand-specific eligibility rule and leaves reviewed catalog records and
  mechanics as the commercial authority.
- When the composer omits a required negative promo answer, the existing
  commercial-truth fallback now produces one concise Taglish response and may
  name only alternative brands attached to allowed, constraint-matching promo
  refs. Successful composer responses are not rewritten.

### 2026-07-30: Grounded conversational synthesis for payment inquiries

- Runtime continues to treat model payment-tool arguments as proposed query
  plans. Before final composition, it now extracts every explicit installment
  term from the current customer message, including multiple alternatives in
  one sentence, and resolves only those customer-backed plans against checkout
  metadata.
- The extraction step records bank, term, brand, and Pay Now/Pay Later scope;
  it never decides support or eligibility. The checkout API remains the
  commercial authority, and equivalent model/runtime plans are deduplicated.
- The final composer now treats validated commercial claims as facts to
  synthesize rather than policy rows to transcribe. Related positive and
  negative facts should form one natural conversational thought, with one
  context-linked next question and no list-like repeated templates.
- The composer receives an explicit compact claim checklist. The validator
  permits one source-backed brand scope to carry across adjacent contrast
  clauses, so natural phrasing does not have to repeat the brand mechanically;
  mixed-brand answers still require explicit per-claim scope.
- The checklist translates internal eligibility states into composer-only
  availability meanings so API field labels do not leak into customer prose.
  It retains validated Pay Now/Pay Later scope for natural composition without
  adding a new deterministic wording rewrite.
- A compact last-mile voice contract follows the draft in composer input. It
  tells the existing composer to discard formal draft phrasing, continue
  without a duplicate greeting when runtime prepends one, synthesize related
  facts as prose, and ask one context-linked question. This adds no model call
  and does not authorize deterministic wording changes.
- Generic customer question grammar also recovers a separately named payment
  provider when the model proposes only the installment alternatives. The
  recovered text remains a query plan and is never treated as support evidence;
  checkout metadata still determines whether any named provider is available.
  A separately named provider is resolved first as general method support and
  does not borrow the brand or Pay Now/Pay Later scope of another installment
  clause. Provisional model results with no claimable checkout outcome cannot
  block this authoritative lookup or win deduplication.
- For pure payment-policy turns, the composer receives a grouped shared-scope
  contract and no main-model draft prose. This prevents an unreliable draft
  from leaking formal labels or unrequested methods while leaving mixed
  product/service turns intact. The composer still owns the final wording.
- Model-visible FAQ results now expose conversational availability meanings
  instead of raw eligibility field names. If the composer repeats a greeting
  after a runtime-owned welcome bubble, the existing one-shot composer repair
  is used; runtime does not edit the prose itself.
- Checkout row labels are normalized for composer visibility (`3-mos
  Installment (0% interest)` becomes `3-month 0% installment`). The shared
  contract also marks an already known brand so the next question does not ask
  for it again.
- A one-claim unsupported-method turn uses the same generic grouped contract
  with a shorter conversational shape and one tire-size follow-up. It does not
  add provider-specific code or a deterministic final sentence.
- Cross-method validation now honors a single validated brand established
  across adjacent clauses, so attaching BPI to an unbranded 3-month plan is
  rejected even when the brand is not repeated in that clause. Concise human
  voice rules are also placed at the top of the composer prompt.
- The commercial claim validator and truth guard remain unchanged as delivery
  safety boundaries. A normal successful turn must pass the claim contract so
  the guard stays silent; a guard rewrite is a failed conversational eval, not
  proof of acceptable composer wording.
- `runtime_v7_composer_tone_probe.py` provides a reusable return-only pack that
  stores full UTF-8 artifacts and separately checks evidence completeness,
  guard ownership, and conversational delivery across English, Filipino,
  Taglish, and non-example provider/brand phrasing.
- The composer must state a shared Pay Now/Pay Later qualifier once when it is
  present in validated claims. Omission is a commercial completeness failure
  handled by the existing one-shot composer repair; runtime still does not
  prescribe or rewrite a successful conversational sentence.
- Last-mile language matching, forbidden policy wording, and the single direct
  next-question rule are now explicit top-priority composer instructions. The
  repair prompt follows the same language boundary instead of forcing Taglish
  for an English customer.
- Final composition and its repair use a low-variance `0.1` temperature by
  default, independently overridable with
  `RUNTIME_V7_FINAL_COMPOSER_TEMPERATURE`. The main reasoning/tool loop keeps
  its existing temperature. This adds no model call or prompt tokens and is
  intended to improve structured-instruction adherence, not to hard-code copy.

### 2026-07-30: Evidence-only release checks and focused policy composition

- Replaced semantic sentence-regex verdicts in the release-candidate matrix
  with checks of typed claims, provider results, product pricing evidence,
  renderer tokens, state, and delivery behavior. Each artifact now identifies
  the synthetic user and explicitly leaves full-turn correctness, naturalness,
  clarity, continuity, and next-action quality for human/CS review.
- Product promo reconciliation now recognizes structured pricing evidence for
  the requested promo type even if `promo_evidence` was omitted because the
  model did not request `promo_only`. This preserves a live
  `/promo_brands`-authorized Buy 3 Get 1 result such as Vredestein without a
  brand exception; ordinary bundle discounts do not qualify.
- A validated promo lookup can complete its own renderer gallery before the
  composer for brandless discovery or a genuinely unresolved requested-brand
  miss. It uses only `allowed_promo_refs`, adds no model call, and does not
  infer intent from customer keywords.
- Pure payment-policy turns use a shorter prompt for the existing final
  composer call. The same source-backed claim checklist, response schema,
  one-shot repair, and commercial validators remain in force.
- The internal canonical scope `Pay Later / Pay After Service` is exposed to
  the composer as the website-facing label `Pay Later`; the underlying
  eligibility and order-state value is unchanged.
- Enforced the existing `required_brands` contract at customer-card rendering:
  a hard brand result no longer fills unused card slots with other brands.
  Explicit comparison/alternative soft preferences still authorize broader
  cards, and exact-base misses remain available as diagnostic evidence.
- Tracked-choice turns now tell the composer to inherit language/register from
  recent natural customer free text. Renderer-owned English button labels and
  the internal choice-action seed no longer imply that an ongoing Taglish
  conversation should switch to English.

# 2026-07-31 - Read-only installation commitment wording

- Extended the existing service side-effect contract so a validated slot is
  explicitly described to the final composer as a customer-selected available
  slot for order review only. The same read-only boundary now covers schedule,
  slot, appointment, and installation wording.
- A composer response that says an installation or appointment is confirmed,
  booked, reserved, or secured without an authorized order-submission side
  effect is rejected for one normal composer repair. Runtime still does not
  author or post-process successful customer-facing prose.
- This correction came from direct customer/Filipino-CS review of the
  zero-traffic live candidate. The objective release matrix passed, but the
  rendered Taglish phrase implied a completed booking that had not occurred.
  Human semantic review therefore remains a separate release gate from
  deterministic evidence and serialization checks.
- The same human review gate found that a valid negative Toyo answer offered
  reviewed promo alternatives and then asked for location in the same reply.
  Promo galleries now retain the promo-discovery decision layer in the final
  composer contract, deferring location and later qualification inputs until
  the customer chooses a promo direction or supplies the tire size needed for
  eligibility.
- No-traffic VM human review then found a province-level schedule reply asking
  for the specific city and also asking the customer to confirm the already
  anchored product. The location decision contract now explicitly defers
  product/SKU selection or confirmation, keeping city/barangay as the only
  requested customer input without post-composer prose rewriting.
- A later VM replay exposed two further semantic contradictions that the
  mechanical matrix did not judge: a long Taglish sentence used `na-confirm`
  for an unsubmitted installation outside the former 48-character proximity
  window, and the prose said only payment remained while the rendered summary
  listed five missing contact/payment fields. The side-effect validator now
  checks the complete sentence for service commitments, while the composer
  receives an authoritative missing-field list and count. Successful prose
  remains composer-owned.

## Runtime V7 positive service-claim authorization

Release validation separates mechanical contracts from human conversation
review. Mechanical checks inspect transport, trusted tool results, renderer
surfaces, state transitions, and side-effect authorization; they do not use
sentence regexes to grade semantic correctness or human tone.

`CustomerTurnPlanV1.authorized_claim_categories` is now a positive allowlist
compiled from current-turn trusted tools. Customer-provided location, date,
time, or installation preferences remain proposed future lookup context and do
not authorize service or schedule availability wording. The final composer may
acknowledge those preferences, but it can claim service availability only from
a current service result and exact time availability only from current slot
evidence. This keeps the correction model/composer-owned and avoids a
post-composer wording rewrite.

The first public-edge replay showed that a prompt-only allowlist was not
sufficient under normal model variance: a product-only turn still implied
installation availability in the requested city. The composer response format
therefore also carries typed `claim_assertions` from the same existing composer
call. The model declares the factual category, affected response units, and
current evidence refs; runtime validates that declaration against the turn
plan and uses the existing one-shot repair path when it is outside the
allowlist. Rejected or failed tool plans never grant claim authority. Runtime
still does not classify ordinary sentence meaning or customer-service tone
with regexes, and it does not rewrite a successful response.

Zero-traffic live review then caught a tracked Promo Details regression that
the objective matrix marked as mechanically valid. With interaction batching
enabled, the informational action correctly bypassed state mutation but its
reviewed catalog evidence lived in the validated response seed rather than a
tool result. The typed claim validator therefore rejected the correct promo
answer and fell back to a generic acknowledgement. Valid tracked-action seeds
now contribute their catalog version and source refs to the same claim
evidence map. Invalid or stale actions still contribute no authority, and
informational actions still cannot mutate product or order state.

The paired About Brand replay exposed a separate evidence-shaping conflict:
the validated action seed contained both the clicked promo and the brand
profile, so the composer answered a brand question with promo mechanics.
About Brand composer context now contains only the validated brand profile,
catalog version, and selected brand. Promo mechanics remain available only to
Promo Details. This narrows model input at the source without post-composer
wording inspection or rewriting.

The active promo catalog's generated brand profiles still contain only current
offer summaries, not general brand background. Until the separately gated
website brand/warranty knowledge slice is published, About Brand must state
that reviewed background is not yet available instead of presenting a promo
offer as brand history or positioning. The following entry supersedes this
temporary fallback once its independent feature flag is enabled.

### 2026-07-31 - Gulong.ph brand knowledge publication

The temporary About Brand fallback is replaced by a separately versioned
Gulong.ph publication. `scripts/brand_knowledge_sync.py` reads the public brand
directory and each active brand detail page, validates all source pages, builds
narrative and warranty embeddings, and atomically moves
`brand_knowledge_config/active` only after every write is ready. A failed
fetch, parse, schema validation, or embedding leaves the previous active
version unchanged.

Runtime reads exact profiles through `runtime_v7.brand_knowledge`. About Brand
buttons use the exact selected brand profile; free-text background and
comparison questions may use `get_brand_knowledge` semantic retrieval. Exact
warranty claims remain structured. A brand/product warranty duration is not
the same fact as the separately published Gulong.ph unconditional-damage
warranty and its eligibility conditions.

Exact named-brand questions do not spend an embedding call. Broad discovery
uses the active vector index and falls back to a bounded lexical scan of the
same published profiles while an index is building or an embedding provider is
temporarily unavailable.

The model owns the friendly explanation and comparison. Runtime owns the
active source version, proposed-brand validation, evidence refs, factual claim
authorization, and the rule that an informational brand action cannot mutate
brand, product, location, or order state. The feature is independently gated
by `RUNTIME_V7_BRAND_KNOWLEDGE_ENABLED`.

General brand background and comparison are discovery questions, not product
availability queries. They do not require tire size. The model answers them
from `get_brand_knowledge` first and may then offer a size-specific product
check. Tire size remains required before claims about fit, current stock,
exact price, or size-specific promo eligibility. This boundary stays
model-led; no brand-comparison keyword router or response rewrite is used.

Composer contract repair receives the exact authorized evidence-ref strings
and may not invent tool names, array indexes, or object paths. If both
composition attempts still omit a required negative promo answer, the
commercial-truth fallback may replace the unsafe prose, but it preserves the
validated renderer-owned alternative promo surface. This fallback remains a
correctness boundary; it does not reorder or rewrite a successful composer
turn.

The product domain can be broadly exposed for model recovery, but brand-level
warranty questions have a more specific authority. When
`get_brand_knowledge` is a grounded candidate and there is no selected product,
or product observation, Runtime withholds that redundant generic FAQ tool.
This is source/type-based capability pruning, not brand or phrase routing.
Selected-SKU turns keep the tool, while a general warranty question without a
named brand continues through normal FAQ retrieval.

When the composer explains the separately scoped Gulong.ph damage coverage, it
must retain every eligibility condition present in the published coverage
record. If a concise answer would omit a condition, it states only the policy
duration. This prevents natural-language shortening from broadening coverage.

The first real staging replay also showed that the internal phrase "reviewed
brand profile" could be mistaken for a customer-review request when older
conversation history contained unrelated topics. The tracked action now names
the selected tire brand and explicitly distinguishes brand information from
submitting feedback. A valid tracked promo action also suppresses first-contact
welcome/intake bubbles because the delivered card is already a continuation
surface. These are composer inputs and turn-state rules; no customer-response
regex or post-composer rewrite was added.

The tracked About Brand path reuses the same published profile without a
second semantic lookup. Its validated action seed now carries both the exact
profile evidence refs and the profile's authorized structured fact fields
into `CustomerTurnPlanV1`. This lets the composer explain the published
background naturally while the claim contract still rejects unpublished
warranty fields. A missing renderer surface is valid for this informational
turn; it must not collapse into a generic order-progression acknowledgement.

When a customer asks for province-level schedules and explicitly remains
unsure of the city, the ranked serviceable-city surface becomes the one
required decision layer. Incidental product results are retained as optional
evidence but deferred from the visible turn. Final composition now derives
its active decision from the validated turn plan, so a product surface cannot
displace the city choices selected by the location planner.

If the model instead proposes an exact-slot query with only province-level
location evidence, Runtime rejects that plan and uses the typed
`required_decision_layer=city` result to attach the current serviceable-city
surface. This is a safe renderer/state recovery: it does not execute the
rejected lookup, select a city, or fabricate schedule availability. A
`tool_plan_not_authorized` result remains guard telemetry but is not tagged as
a Chatbot Error because the safety boundary operated as designed.

Ranked-city recommendation results now register their preview observation
refs and location-surface source version under both service and schedule
claim categories. Product-search observations likewise authorize promo
claims only when the trusted result contains validated promo evidence. These
are existing provider refs, not prose-derived permissions; they let a correct
composer turn pass without weakening unsupported-claim rejection.

A general About Brand action now leads with background, origin, and
positioning. It may mention a published warranty duration briefly, but it
does not volunteer coverage or eligibility terms unless the customer asks
about warranty or protection. This keeps a short brand reply from making a
subset of policy conditions sound complete; detailed warranty questions
continue to use the full structured policy evidence.

### 2026-08-01: Evidence-only semantic retry answer obligations

The first immutable staging replay of the evidence-only retry showed two
remaining failure modes. A generic affirmative delivery opening still answered
the customer's narrower location question by implication, even after the place
name was removed. An empty promo retry preserved the category surface but
omitted both the requested-brand negative result and the absence of a verified
alternative. Both responses correctly reached the semantic auditor and safe
fallback, but normal composition did not satisfy the release gate.

The evidence-only retry now receives typed answer obligations derived from the
provider results and semantic violation category. General policy location
retries cannot use a yes/no case answer and must leave exact serviceability
pending. Empty promo retries must state each scoped negative result, state when
no verified alternative was returned, and retain category choices only as a
non-promo shopping continuation. This adds no phrase matcher, brand exception,
or post-model response rewrite; the model still constructs and localizes the
complete customer response.

The next pinned replay confirmed the general-policy obligation but showed that
the promo retry could still turn an ordinary category continuation into a claim
that other brands have promos. The promo contract now makes the provider result
cardinality explicit: zero verified alternative promos, no other-brand promo
claim authority, and a required ordinary price-category meaning for the
renderer surface. The values are computed from trusted promo and presentation
results rather than customer wording.

Repeated replay also showed that a single free-form audit decision could be
internally inconsistent: an auditor could label a response supported while its
reasoning still treated a customer-named place as part of a broader policy area.
Policy and promo auditors now return typed semantic classifications in addition
to their overall decision. Runtime validates those model-produced fields as a
contract: case-specific policy questions require an explicit pending state when
not separately authorized, and empty promo evidence cannot coexist with an
unverified positive alternative or a category surface used as promo proof.

For rejected responses, the same auditor also returns a typed semantic repair
contract containing required meanings, forbidden meanings, allowed evidence,
and renderer roles. The final composer receives that model-produced contract
without the unsafe draft or customer-origin factual anchors. This keeps tone
and response construction model-owned while making whole-response reasoning
iterative and mechanically enforceable at the typed-decision boundary.

### 2026-08-02: Price-list/gallery consistency and answer-goal hardening

Recent customer-visible review found three separate boundary failures. Fully
imaged product galleries suppressed the readable long-form price list, selected
product detail projections dropped catalog images that were already present,
and a partially imaged gallery allowed ManyChat to reuse a neighboring visual.
Separately, an authored FAQ could be factually repeated even when retrieval did
not answer the customer's actual question, and the API fallback could treat a
whole non-payment utterance as an unsupported payment-method name.

The product runner now prefers image-backed alternatives from the already
retrieved and query-filtered ranked pool, so the correction adds no API call or
image probe. The renderer applies trusted-image eligibility once and uses that
same displayed-card set for the complete price list, gallery, tracked `ps1|...`
buttons, presentation metadata, and click allowlist. Selected-product
projections carry the trusted image forward. If no compatible image-backed
alternative exists, the affected product is absent from both interactive
surfaces; an all-missing result remains truthful text-only rather than borrowing
a placeholder or another SKU's image.

Initial multi-SKU delivery always includes the long-form price list before the
gallery. The product delivery ledger records renderer variant, list/gallery
presence, provider-backed card identities, delivery outcome, and expiry. Only
the exact same non-expired v2 list-plus-gallery presentation may omit a repeated
list during continued SKU selection. Legacy, failed, differently ordered, and
text-only ledger entries cannot authorize suppression.

The existing conditional semantic audit was generalized from policy-only scope
to overall authored answer goals for product/service/order/policy FAQ and
business-contact results. It compares the customer's request, the tool's answer
goal, authored evidence, and complete visible response. A misaligned result is
removed from repair authority and falls back to one concise clarification; it
cannot deliver an unrelated FAQ simply because that answer is source-backed.
Renderer-owned products, location choices, checkout controls, and exact numeric
facts keep their deterministic contracts and do not incur this semantic call.

Payment-policy fallback now passes a named provider only from typed current-user
signals. Unknown providers still enter checkout validation as
`mentioned_unconfirmed`, while quotation requests and other free-form phrases do
not. A validated unsupported method is stated briefly and followed by up to
three active checkout alternatives when available; checkout selection and order
submission authority are unchanged.

The first staging matrix exposed two adjacent scope bugs. The generalized
answer audit was applying the general-policy exact-case restriction to
checkout-backed brand/method facts, even though checkout metadata directly
resolved those facts. That restriction is now conditioned on explicit
`policy_general` evidence. Separately, the provider-owned empty-promo result was
installed only after `used` or `repaired` composer outcomes; a later renderer
fallback could therefore erase the already validated non-promo category
surface. The scoped empty result now wins for every composer terminal status.
Both corrections are typed evidence/state decisions and add no keyword gate,
provider call, or model call.

Human review of the mechanically green second staging matrix then found a
separate interaction-boundary regression: a validated Promo Details click had
no main-loop tool call, so generic semantic location recovery added an
unrelated delivery FAQ. The answer-goal audit rejected that mismatch, but the
fail-closed fallback also hid the valid promo answer. Validated informational
promo actions now own their continuation turn and suppress only that generic
no-tool location recovery. Later free-text location questions remain eligible.
The change uses tracked action evidence and removes an unnecessary model/API
path; it does not match captions, brands, or sample text.

Local validation before staging: `393 passed` across the affected renderer,
product, answer-goal, payment, ingress, tagging, and transaction-choice slices;
the complete Runtime V7 suite passed `1,230` tests and the full repository suite
passed `1,295` tests after the staging corrections. Ruff, `git diff --check`, and the behavioral/customer-
facing change audit also passed. No staging, main, Cloud Run, or VM promotion is
claimed by this local implementation entry.

### 2026-08-06: Shared operating identity and model-owned complete-turn prose

A bounded July 1-August 6 ManyChat agent-message review found that general
location, branch, walk-in, and installation questions share the same business
explanation. The most common approved partner-count wording was `100+`; smaller
samples used `150+` or `200+`. Runtime therefore verbalizes the conservative
lower bound as `over 100 trusted installation partners` or `mahigit 100 trusted
installation partners`; it does not infer exact geographic coverage or a higher
current total from that branding. The paired-message query processed
at most 41,759,475 bytes and returned only customer question/agent answer text,
with no customer identifiers.

The reviewed operating identity is centralized in
`runtime_v7/business_identity.py` and is included in the cacheable tool-loop
prompt and final-composer prompt. It authorizes the stable online-tire-shop,
head-office installation-site, over-100 partner, and warehouse-to-booked-site
facts. It expressly does not authorize nearby partner availability, coverage,
slots, stock, prices, promos, payment terms, booking, pickup, or installation at
an unverified site. The user corrected the earlier local assumption that the
head office could not perform installation: it is also an installation site,
and Runtime now states that positive fact. General business-presence questions are answered from this
identity without forcing a location picker; actual installation discovery still
uses current service tools. This avoids the awkward hybrid `mahigit 100+`.
Every final-composer plan carries a versioned `business_identity` evidence ref
and typed `business_identity_facts` category, so mixed-intent turns use the same
authority without borrowing coverage or availability from it.

For a valid structured final-composer result, Runtime now preserves the
model-authored acknowledgement, transitions, and CTA. The older lead-focus and
promo-action CTA rewrites remain only on invalid-format, renderer-contract, or
legacy/failure paths. Deterministic surfaces and commercial guards continue to
own exact product, service, payment, promo, and order facts. The varied review
matrix adds operating-identity and generic-assistance cases alongside product,
fitment, promo, service, schedule, payment, order, complaint, reactivation, and
guided-choice scenarios; qualitative review remains model/orchestrator-owned.

The first varied live matrix exposed three adjacent general defects. The
operating-identity voice anchor made the lower-bound partner count look like a
required sentence; a customer soft preference for quietness was restated as if
the returned products supported that feature; and a selected-product-to-service
transition lacked the prior product evidence ref in the composer plan. Runtime
now treats the partner count as optional support, treats preferences as context
rather than product facts, and carries trusted selected-product observation refs
into later service/schedule composition.

The location recheck also proved that a good model-authored CTA was being removed
after composition. The signal model correctly marked `saan kayo located` as
`relation=question_only`, but lead qualification and order readiness still
counted its text as the customer's area. Transient relations now remain useful
for current-turn interpretation and read-only lookup but cannot satisfy lead or
order fields. This preserves the model's area question without adding a
location-phrase rule.

Bounded validation followed the cost plan: the initial affected local slice
passed 55 tests; the expanded lead/readiness/composer slice completed 88 passing
tests before one stale prompt-string assertion failed, and that corrected case
then passed independently. Eight focused relation, selected-product-evidence,
service-policy, system-prompt, and operating-identity tests passed after the
head-office correction. Python compilation, Ruff, JSON parsing, and
`git diff --check` passed. The full suite was not repeated by the implementing
agent because the prior increment already established the 1,313-test Runtime V7
baseline and these changes are confined to composition ownership and typed
operating identity.

Focused Gemini Flash probes covered a bare greeting, vehicle-only price ask,
generic assistance ask, colloquial physical-shop/location ask, grounded product
surfaces, and a selected-product-to-schedule transition. The final
post-correction location probe used one main-model call plus one
background-signal call, no tools, 4,607 ms main-model latency, 11,316 ms total
model latency, and an estimated USD 0.006030. It retained the useful area CTA
and removed the earlier false denial, but it overemphasized the corrected
head-office installation fact as customer-facing copy. That probe is diagnostic
evidence, not the accepted response target. The authority packet now makes the
fact available only when directly useful and explicitly says it is not required
or promotional copy. The artifact is
`tmp/runtime_v7_live_test_pack_head_office_corrected/runtime_v7_live_pack_20260806_231346/`.
The bounded three-scenario matrix cost an estimated USD 0.092794; the two-case
recheck cost USD 0.028553.
The product result's long renderer-owned warranty/inclusions body remains a
separate presentation concern; this composition increment did not rewrite it.
One earlier product probe had its product/promo capabilities disabled by an
invalid local signal-generator setting and was excluded from response-quality
evidence. No staging or production deployment is claimed.

The surrounding state and response audit found four customer-visible mutation
layers after model reasoning: harness composer repair/prose guards, API
commercial-truth rewrites, channel-renderer suppression/reordering, and legacy
CTA progression. Exact authority decisions and mechanical rendering remain
necessary, but broad sentence deletion, whole-response replacement, and CTA
rewriting are not appropriate for schema-valid final-composer turns. The next
increment should instrument model units, post-harness units, post-API units,
rendered messages, and transform reasons before bypassing those prose mutators.

The same audit found duplicated continuity and readiness projections: hydrated
conversation, recent turns, Active Working Memory, legacy `memory_note`, the
signal ledger, simplified missing-info readiness, full `OrderReadiness`, lead
focus, and selected-product augmentation. Active Working Memory is synchronous
on no-tool turns, while the background extractor also runs on every production
turn. These calls should be ablated before introducing another memory layer.
The first safe experiment is recent-turn plus durable-signal continuity with
model AWM skipped only for no-tool/no-durable-signal turns; the second removes
the lightweight readiness projection while preserving full `OrderReadiness`.
Mem0 or a graph framework is not selected in this increment because neither
addresses duplicated ownership by itself and both add integration/persistence
surface. They remain shadow candidates only if the lean internal-state controls
show a measured continuity gap or the explicit state machine remains
unmanageable after consolidation.

## 2026-08-08 - Staging-parity guided evaluation and qualitative tire advice

The adaptive local evaluator had loaded the repository dotenv but not the
literal feature configuration retained on the current Cloud Run staging
service. With no staging router-flow namespace, the channel renderer correctly
refused to emit schedule, payment, location, product, and price-category button
targets. Brand-knowledge lookup was also disabled locally. Those missing local
values invalidated the earlier claim that invisible controls and unavailable
brand grounding represented deployed staging.

`scripts/runtime_v7_local_endpoint_server.py` now reads only literal, non-secret
environment values from the deployed staging service, requires the guided
router, turn-plan, promo-catalog, and brand-knowledge flags, and then forces a
return-only local safety profile before importing the API. It never copies
secret references or prints configuration values. `/gulong/v7/choice-action/tester`
routes real returned button tokens through tester-session state and forcibly
keeps delivery in `return_only`, even if a probe asks for channel delivery.

With parity enabled, an adaptive run rendered four real price-category buttons,
accepted an Economy click, rendered two grounded product buttons, accepted the
Deestone product click, and progressed naturally to the customer's area. The
validated category and product refs were recorded and interpreted correctly.
A pre-fix tester request attempted channel delivery against a synthetic blank
subscriber and received a ManyChat 400; no customer message was delivered. The
tester route now overrides that request-level mode unconditionally.

The same evidence exposed two runtime defects rather than evaluator defects.
First, a reviewed promo gallery could be deferred behind a generic price-
category surface even after the model deliberately presented the promo. A
non-supporting promo gallery now owns that turn when the competing surface is
only generic category discovery; grounded product results can still remain the
active decision when they directly answer the promo request. Second, a newer
validated category click now supersedes the older typed category signal, which
prevents Active Working Memory from describing an Economy result as based on a
prior Mid Range choice.

Qualitative tire advice is now an explicit bounded claim category. The model may
combine stable tire expertise with visible product identity, grounded card
facts, and published brand knowledge to answer comfort, noise, wet-road,
durability, value, and use-case comparisons. It should give a calibrated
recommendation instead of a broad refusal, while exact measurements,
certifications, test results, features, and guarantees still require evidence.
The focused recheck recommended BFGoodrich Advantage Touring for a city-driving
customer seeking a more refined and quieter ride, explained its touring
positioning, did not repeat the product cards, and asked whether to proceed or
compare another option.

Current bounded verification is 275 passing tests across the local parity
launcher, guided-action endpoint, renderer, transaction choices, turn plan,
brand knowledge, and qualitative claim contract. The staging-parity preflight
reports all four required flags present. No repository-wide suite, deployment,
real ManyChat delivery, or production mutation was performed in this increment.

The response voice contract also now prefers the ordinary tire-quantity wording
`pcs` or `tires` over the more formal `piraso`, except when naturally mirroring
the customer's own phrase. This remains model-owned wording rather than a
post-model replacement rule.

## 2026-08-08: Long-horizon signal retention and delivered-surface truth

The retention matrix now covers corrections, retractions, transient questions,
eight-to-twelve-turn business interruptions, all guided choice families, and
selected-product evidence beyond the ordinary observation window. A bounded
live extraction probe passed four varied scenarios and 31 evaluated turns.

Adaptive endpoint review found that generated product metadata could be stored
as delivered even when the channel rendered only location buttons. Runtime now
records product presentation state only when the actual customer payload
contains the relevant product text/cards or tracked product buttons. The model
contract treats internal product candidates as unshown until that boundary is
met. This fixes progression context without adding a deterministic
location-to-product CTA or post-model schedule suppression.

The same review fixed a `mostly`/`mos` payment false positive, a generic Double
Warranty Choose Brand click being extracted as a SKU, a contradictory promo
audit discarding a valid gallery, stale payment qualifiers after option changes,
and customer-facing Pay Later label inconsistency. Detailed transcripts and
verification limits are in
`docs/RUNTIME_V7_CHOICE_AND_SIGNAL_RETENTION_EVALUATION_2026-08-08.md`.

## 2026-08-08 - Retired competing stage and semantic decision authorities

Runtime still contained an incremental-migration seam: the main tool model and
final composer could make a complete turn decision, then legacy product,
location, payment, lead-stage, CTA, and semantic-audit layers could independently
reclassify or replace parts of it. The seam remained for rollback compatibility
and fail-closed safety during earlier surface migrations, but it duplicated
model calls, created conflicting state interpretations, and made ordinary sales
progression depend on incomplete flags and phrase-like classifiers.

The serving contract now gives the main model and structured final composer
ownership of ordinary read-only tool selection, connective prose, surface
choice, transitions, and the next useful CTA. Runtime retains deterministic
authority only for exact provider facts, trusted surface refs, guided-action
tokens, delivery mechanics, side effects, and hard order/submission safety.
`lead_cta_focus` and its production module were removed rather than retained as
an advisory instruction. Separate product-progression, location-choice, and
payment-query semantic decisions and the pre-composer commercial callback were
removed from the serving path. FAQ hints may expose registered read-only tools
as advisory capability context but cannot authorize mutations or facts.

The follow-up audit then found three remaining phrase-authority leaks. FAQ
hints could still expose or withhold a domain, assistant/customer phrases could
trigger extra tool rounds, and an empty-output keyword list could invent a
service CTA. Serving no longer builds FAQ hints for capability selection;
product, service, and order FAQ schemas are safe read-only options visible to
the main model, while keyword/vector matching remains only inside an explicitly
selected retrieval tool. The phrase-triggered retry rounds were removed, and
empty output now receives one neutral resend request with no inferred topic or
CTA. Supporting surfaces are excluded from the one-active-transactional-layer
check, so the model can coherently place a grounded Double Warranty card beside
product selection without creating a competing customer decision.

Signal normalization no longer interprets free `evidence` or `status_hint`
phrases as recency, merge, or confirmation authority. The extraction contract
now carries closed `relation` and `confirmation_state` fields. Multi-value
merging uses typed values/source equality, and only the closed confirmation
field can mark an explicitly uncertain value unconfirmed.

The decisive negative case was a realistic mixed request for a tire size,
preferred brand, alternatives, two-tire promo, and card installment. The
overlapping architecture attempted a ninth model/provider call against the
tester ceiling of eight. After the serving simplification, the same request
completed within the original ceiling, returned grounded product and payment
facts, and retained the customer's later Bridgestone, BDO installment, quantity,
and Sta. Rosa context into the next natural scheduling CTA.

Approved Double Warranty catalog evidence now also counts as delivered product
inclusions when that exact promo ref is visible. Return-only evaluator sessions
record the same customer-visible state that Codex actually received; production
state still depends on successful delivery.

Final focused verification is 989 passing tests across ingress, product,
transaction, turn-plan, lead-tagging, typed-signal authority, long-horizon
retention, follow-up, and renderer files. Adaptive transcript artifacts are under
`tmp/runtime_v7_adaptive_eval`, and the customer-visible evidence is summarized
in `docs/RUNTIME_V7_CHOICE_AND_SIGNAL_RETENTION_EVALUATION_2026-08-08.md`.
No repository-wide suite, external ManyChat delivery, commit, deployment, or
production mutation was performed. The full suite and controlled delivery check
remain immediate pre-merge release gates.

## 2026-08-09 adaptive replay closeout notes

The final adaptive review used the local staging-parity endpoint in
`return_only` mode. Codex selected each next customer reply after reading the
actual rendered bubbles and controls; replies were not a fixed scripted
sequence. The reviewed August catalog was rebuilt and published as
`catalog-202608-5f4ddb23ee0c-v2-p2`. Its Double Warranty card now displays
`Find Tires` while retaining the generic tracked `choose_brand` discovery
action. The active pointer retains
`catalog-202608-5f4ddb23ee0c-v2` as the rollback version.

Catalog publication now carries an explicit publisher revision in addition to
the source hash and schema version. This lets a reviewed customer-visible
caption or rendering-policy change create a new immutable catalog even when the
source package is unchanged. Source-hash reuse remains idempotent within the
same publisher revision, and publication still requires the normal AI,
eligibility, human-review, and validation gates.

The principal rendering defect was not model intent: safe
`renderer_contract_fallback` units already contained one selected decision
layer, but the channel renderer appended unused tool surfaces. Structured
safe-fallback surface plans now own exact rendering without being promoted to
accepted model prose or bypassing commercial/submission guards.

The principal transition defect was competing typed tool objectives. A tire
size and quantity made product/promo discovery primary even when the latest
goal was installation coverage. Product criteria now remain retained context,
while service/payment goals suppress that competing priority. Location-first
city clicks remove only irrelevant broad-promo schemas; the model still chooses
between product search and category discovery and owns the acknowledgement and
CTA.

Two customer-visible deterministic surfaces were simplified. Product results
use compact exact price/promo/benefit text plus image-backed tracked choice
cards, without raw product URLs in the list. Incomplete order summaries show
only collected values and leave one grouped, language-matched completion ask to
the model. These are renderer changes over trusted facts, not model-authored
commercial data.

The replay budget was stopped after repeated high-token location-first calls.
One final bounded live smoke then verified the corrected location-first path.
For `4 tires na 235/60R18` and an installation request in Laguna, the model
asked for a specific city, the renderer displayed six grounded Laguna city
controls, and the CTA asked the customer to choose one. Clicking the displayed
San Pablo City control retained the size and quantity, acknowledged the city,
and resumed grounded Budget, Economy, Mid Range, and Premium choices instead of
jumping to scheduling. The capability profile exposes product discovery for
this unresolved mixed product/service transition; the model still chooses the
tool, acknowledgement, connective prose, and CTA.

The pre-publication local verification completed on August 9: the focused
promo/renderer/product/location/retention set passed 138 tests, the complete
product harness module passed 594 tests after the mixed service-and-product
objective was made model-conditional, and the repository-wide suite passed
1,442 tests. After the catalog publisher-revision and final location-transition
changes, the focused promo suite passed 122 tests and the targeted
location/product set passed 24 tests. The final post-change repository-wide
suite passed 1,443 tests in 25.05 seconds.

A controlled ManyChat send to the designated internal contact was accepted by
the API with HTTP 200. The exact outbound order was a text marker, the square
Double Warranty card with customer-visible `Find Tires` and `Promo Details`
buttons, then a second text marker. The authenticated hidden-history session
was stale, and the new event had not yet appeared in the bounded raw or curated
BigQuery message trail at review time. This proves provider acceptance and the
submitted ordering, not final Messenger UI observation; no duplicate send is
allowed while ingestion is pending.

## 2026-08-09 normalized warehouse durability and free-text monitoring

The VM dual-write audit compared distinct non-null `row_id` values with the
same Asia/Manila-local settled window. The apparent several-hundred-row gap was
a UTC-versus-Manila cutoff error. The real seven-day difference was two
complete turn bundles retained by CloudSQL but absent from BigQuery; one landed
two seconds before a container replacement. Runtime analytics writers are
request-scoped, so the five-second BigQuery age timer provided no cross-request
batching benefit and created the replacement loss window.

Completed normalized per-table batches now dispatch immediately in background
after the full turn, including all LLM spans, tool calls, and interaction
events. Customer delivery does not wait for warehouse I/O. CloudSQL remains the
reconciliation source if a process still ends before a background write lands.

Published BigQuery views now expose deduplicated Runtime V7 turns, free-text
turns, tool calls, LLM spans, interactions, and errors. The obsolete
`assistant_log`, `tool_output_log`, and `error_log` are not revived. Versioned
health and free-text review queries use a five-minute observation cutoff and do
not classify semantic quality with phrase matching.

A bounded live review of 48 non-empty free-text turns from 22 users on release
`341e154` found 38 pass, 8 concern, and 2 fail turns. Size, brand/product,
location, schedule, promo, payment, and proceed intent generally progressed
without requiring guided clicks. The material failures were an unsafe
near-compatible-size answer after an out-of-stock `225/50R19` request and then
re-asking the already known size. Other review candidates included asking for
a more specific city after recognizing Dasmarinas and failing to answer an
installation-charge question directly. These are semantic review findings,
not deterministic intent gates; no new phrase-matching authority was added.

The first `8340ed7` staging smoke retained a combined free-text vehicle, exact
size, location, value, and comfort request and rendered grounded products, but
the composed lead-in incorrectly called the products comfortable and perfect
for the customer's local roads. The shared complete-turn composition contract
now separates acknowledgement of a soft preference from claims about rendered
products: when evidence proves only size/category/price/warranty/promo, the
model introduces options for comparison and may give calibrated advice, but it
cannot turn the requested preference or location into a product feature.

## 2026-08-10 location-first continuity and brand-voice increment

Location-first progression now uses one general continuity rule instead of a
lane-specific stage gate. The final composer receives compact
`known_customer_context` separately from action authority, so it can reuse a
customer's location without claiming service, fulfillment, or schedule
validation and without asking for the same location again. Coverage-only
installation evidence answers coverage first; if no product is selected, the
model asks for the tire input needed to show a suitable tire before schedule
lookup rather than implying that size alone unlocks a schedule.

The main model's unresolved service goal is preserved across tool-backed turns
by the model-led Active Working Memory compactor. Exact provider refs and typed
signals remain its evidence boundary, and the existing evidence-bound compactor
remains the failure fallback. A short size reply in an active service, order, or
payment thread resumes product/category discovery for that goal instead of
silently resetting to broad promo discovery.

Brand voice now asks the model to speak as Gulong.ph using natural
`kami`/`tayo`/`natin` language or to state the result directly. Routine catalog
and service results must not be narrated as something the assistant "found."
Payment FAQ composition keeps selected-product and order context when a sale is
already active, allowing the answer to return naturally to the pending decision.

Validated product clicks no longer flatten card prices or four-tire totals into
synthetic customer prose. The exact card facts remain available through trusted
selected-product context and observation refs, while the signal extractor no
longer mistakes renderer-owned totals for customer-stated budget or quantity.

A bounded return-only adaptive replay covered San Fernando installation
coverage, a free-text `215/65R16` reply, a tracked CST product click, grounded
schedule cards, and a BPI installment interruption. The runtime retained the
location, avoided a broad-promo detour and duplicate fulfillment question, then
answered the payment question and resumed the visible schedule choice. No
ManyChat delivery, analytics save, commit, deployment, or traffic change was
performed. The affected product-choice, service, turn-plan, and product-harness
set passed 705 tests. The final pre-merge repository gate subsequently passed
1,456 tests; changed-file Ruff, Python compilation, `git diff --check`, the
strict behavioral/customer-facing audit, and a 747-test post-lint affected
recheck also passed.

The first two deployed staging coverage-first probes then showed that prompt
guidance alone could not keep the CTA on product discovery. The partner provider
still emitted `suggested_next_tool=find_installation_slots`, and its compact
result told the composer to advance because anonymous area-only partner rows
were hidden. That was a competing legacy stage instruction, not service truth.
The provider and compact result no longer prescribe the next sales stage.
Anonymous-card suppression now derives only from typed partner disclosure level
and the absence of customer-visible names. Product/service state and the latest
customer goal remain model inputs for deciding whether product discovery or
schedule lookup is appropriate. The revised candidate passed the complete
1,456-test repository gate, changed-file Ruff, compilation, diff check, and the
strict behavioral/customer-facing audit before rebuilding staging.

A subsequent staging replay confirmed the correct tire-discovery action but
showed that the generic service-action packet still represented partner coverage
and slot lookup identically. That packet now exposes the factual lookup scope,
whether a slot lookup ran, and whether a trusted product is already selected.
The composer still owns the wording and CTA; the packet only prevents it from
describing a product input as the final dependency for schedule checking when
the current result established coverage alone. No phrase matcher, fixed stage,
or post-model response rewrite was added.

The final guided-click replay then exposed a separate stale retry: any
latest-message time expression could force `validate_installation_slot` after a
slot lookup. A flexible request such as "around 10 AM" therefore applied the
nearest 9:00 AM candidate before the customer clicked it, even though the
rendered turn still asked the customer to choose. That retry and its time regex
were removed. The service model contract already limits validation to a
customer-chosen visible slot or exact shown date/time, while tracked schedule
buttons validate their refs directly at ingress.

## 2026-08-10 guided-choice authority and conversational checkout increment

Validated location buttons now remain authoritative through the complete
turn. Previously, API ingress stored a valid city or province selection, then
ordinary extraction of the synthetic click text could replace that trusted
state with a lower-authority latest-message interpretation. The post-extraction
boundary now reprojects the delivered location choice and installation intent
as `validated_choice_action` signals. A city is action-safe; a province remains
known context that may still require a city where the provider needs that
precision. The existing `Other` behavior remains navigation-only and does not
silently select delivery.

The same current-action source is now recognized by service objectives and
location planning. A tracked city choice outranks stale province or ambiguity
state from an earlier turn, while later genuine free text can still correct the
choice. Passive tagging also distinguishes visible product options from a
trusted selected-product context, so merely showing a price list no longer
creates a false product-selection signal.

Conversation progression now gives customer pause or close meaning precedence
over a pending sales milestone. Payment-only composition and Active Working
Memory guidance preserve unresolved product context for later without
repeating the previous CTA when the customer is deciding or ending the current
exchange.

Receipt, invoice, and quotation questions are modeled as transaction-document
questions rather than payment methods. A reviewed official-receipt FAQ answers
that Gulong.ph issues the receipt for completed purchases and sends it by email
after installation or order completion. Compound payment-and-document messages
retain each question as a separate grounded answer. Generic payment-process
questions no longer infer cash or another unstated method.

The turn-surface authorization schema now preserves `supporting_context` and
`missing_fields`. An incomplete deterministic order summary and its immediate
Pay Now/Pay Later controls are one customer interaction: the summary remains
renderer-owned supporting context while the checkout buttons own the active
decision. This prevents a false multiple-decision repair fallback and lets the
model keep the acknowledgement and CTA in the customer's Taglish register.
Independent product, city, schedule, and payment decisions remain mutually
exclusive.

Focused and broader deterministic validation passed 228 tests, with five
additional receipt, payment, pause, and document tests passing. Bounded
return-only adaptive review covered a pure pause, payment plus receipt,
receipt-after-installation shorthand, a Metro Manila city surface and Makati
click, product-first province retention, and the complete product to schedule
to order-summary journey. The final journey kept deterministic product/order
facts, rendered Pay Now/Pay Later controls, used model-composed Taglish, and
described the selected schedule as review state rather than a completed
booking. The repository-wide gate initially exposed one stale assertion that
still expected five signal scenarios after the two document/payment scenarios
were added; the assertion now validates the complete seven-scenario identity
set. Its focused recheck passed, and the final repository-wide suite passed
1,470 tests. These checks did not prove real ManyChat delivery, staging, or
live behavior; those remain release gates.

The first staging journey on commit `5652c71` passed the product, schedule,
order-summary, and Pay Now/Pay Later mechanics, but human/CS review held live
promotion. The model still opened routine inventory with "May nakita po
kaming" and translated four tires as "4 piraso" later in the journey. The
final-composer voice contract now explicitly prohibits search-intermediary
lead-ins for ordinary grounded results and requires `pcs` or `tires` unless the
customer personally used `piraso` in free text. This is model-owned voice
guidance, not a post-model phrase deletion or deterministic response rewrite.

The follow-up staging journey on `6563872` removed both phrases and preserved
all guided mechanics, but product and schedule button turns switched the
existing Taglish conversation into English. The voice packet already said a
button label was not a language sample, while the system prompt separately said
to match the latest message; synthetic click prose made those instructions
compete. The tracked-interaction contract now gives the most recent natural
customer free text absolute language/register precedence over the current
synthetic action message. The model still composes the complete response; no
language detector or post-generation rewrite was added.

Cloud Build `4b67d455-ebd1-43e4-8ee3-9ca786b1dfe8` correctly blocked deployment
before image creation because a prompt-ordering test inspected only the first
1,500 normalized characters. The new language-precedence rule lengthened the
intended highest-priority section without moving any voice rule below the
response schema. The test now checks that every required voice rule exists and
appears before `Return only response_units`, which preserves the actual
contract without a brittle character window.

The rebuilt staging revision `gulong-chatbot-runtime-staging-00402-4x7` on
`39c3848` was healthy at 100% traffic, but the final adaptive journey exposed
two further general conflicts and live promotion remained held. The composer
again used search-intermediary inventory wording even though the prompt
prohibited it; the final-composer validator did not classify that miss, so no
model repair ran. Brand-owned inventory/service voice is now both a
highest-priority instruction and a compact voice-contract requirement. If the
model still returns the narrow prohibited search-intermediary construction,
the contract requests one model rewrite; runtime does not delete, splice, or
replace the sentence itself.

After the tracked product choice, retained installation and location were
present, but tool-objective planning checked only `product_presentation` while
the validated click exposed `product_observation`. It also treated the retained
installation choice as inactive because the current synthetic action concerned
the product. That left `build_order_summary` competing without the intended
slot objective. Product context now accepts a still-visible presentation or an
observation backed by selected-product authority, and a current trusted product
choice may resume a retained installation path at its known location. Stale
unselected observations, delivery, missing locations, and already validated
slots do not open a new slot objective. This is a reusable typed-state rule for
all products and locations; it does not inspect SKU, brand, city, or raw
customer phrasing. The affected 216-test set passed before the next staging
build.

Cloud Build `10d626f2-9180-4c30-915e-b71f2e1696d1` then stopped in its test
step (`1 failed, 1,475 passed`) before image creation or deployment. The sole
failure was an existing contract-repair fixture whose nominal repaired response
still said "I found ...", which is now correctly rejected by the brand-voice
contract. The fixture retains that phrase in its intentionally invalid initial
response, but its final recovered response now complies with the same contract
the test is validating.

A narrow staging compound check then found a separate FAQ precedence defect.
The model correctly split "Pwede BPI card? May official receipt ba?" into two
`answer_order_faq` calls, but carried `requested_payment_method=credit card`
into the receipt call. `_answer_faq` used any payment-method argument before it
interpreted the explicit question, so the receipt call was silently redirected
to the generic payment FAQ. Explicit FAQ question matching now runs first;
payment metadata remains a constraint/fallback only when the question itself
does not resolve. This preserves model-led question decomposition while keeping
reviewed FAQ facts authoritative.

The location smoke also separated a stale release assertion from an actual
service gap. A pure "location ng store?" turn correctly answered the reviewed
Makati head-office/installation-site fact and should not be forced into a
province picker merely to answer business presence; the old single-turn matrix
still required `lc1|` unconditionally and is not authoritative for that FAQ.
However, a separate turn that explicitly said the customer wanted installation
but had not supplied an area also asked for the city in prose without calling
the available guided surface. Tool objectives now offer
`present_serviceable_location_choices` when installation is active and no
usable area exists. The model still owns the response and may accept natural
free-text city/area replies; the surface remains routing-only and does not prove
service coverage.

Cloud Build `0ac3ea97-6c5b-4b88-81d4-e0e0fb6b06c1` stopped before image
creation/deployment (`1 failed, 1,475 passed`). A payment-policy test still
required the established `runtime_payment_policy_query` diagnostic label; the
new explicit-question-first path returned the same checkout-backed installment
answer but labeled its match `lexical`. Payment-scoped FAQ entries with a named
method now retain the prior telemetry label, while receipt/document entries
remain lexical and cannot be redirected into payment policy.

The first alternate-port VM smoke for promotion merge `a63fe4a` correctly ran
with return-only delivery, tags disabled, and follow-ups disabled, but exposed
a real release blocker before cutover. On one live-model run, the main loop
passed `Service Areas` to `find_installation_partners` as a location and then
explained the no-match instead of showing the available province choices. The
provider already rejected singular generic business-location wording; its
central validation now also rejects plural/compound labels such as service
areas, installation locations, available branches, and partner locations. The
model-visible provider note directs the next tool round to
`present_serviceable_location_choices` when that guided capability exists,
with a free-text city question only as the fallback. This is argument safety at
the existing tool boundary, not phrase-based intent routing or deterministic
response composition. Five varied generic-label cases plus explicit
service/location regressions pass locally; staging and the repeated VM
candidate smoke remain required before production replacement.

The exact `82afbe9` staging replay produced one transient Gemini
`ServiceUnavailableError`, then a valid response that still asked the customer
to type a city without calling the province surface. This showed the remaining
gap was not catalog visibility or partner lookup validation: primary Tool
Objectives were advisory, so the main model could ignore a typed
`service_location_choice` objective. Runtime now makes that one routing-only
guided objective the initial named tool choice. It does not generate or rewrite
the greeting, explanation, transition, or CTA. The deterministic control is
limited to a surface that cannot confirm coverage or commercial facts, and it
is derived from normalized current service state rather than customer phrase
matching. Explicit city, delivery, and absent-service-state controls return no
required surface. A harness integration test verifies the model receives the
required tool, the surface executes, and the model-authored prose remains the
visible response.

The final VM candidate exposed one remaining model-led extraction ambiguity:
the same customer could explicitly request installation while saying that both
tire size and location were still unknown, and the lightweight extractor could
drop the known service type together with the unknown details. Without typed
`service_type`, service tools and the province surface were not exposed even
though the main model understood the question. The extraction contract now
separates known fulfillment intent from missing inputs: explicit installation
or delivery remains a typed service fact, while unknown size, location, or
address stays omitted. This is prompt/model-owned semantic extraction; it does
not add phrase matching, invent a location, or write the customer response.

## 2026-08-18 - Guided location eligibility rebalance

The August 15 location hotfix remained too dependent on a durable
`service_type=installation` signal. Product-comparison customers who had already
received usable product cards therefore often could not receive a guided
province progression unless they first stated installation intent, limiting the
intended increase in location-button exposure.

The capability profile now treats a successfully delivered product-card
presentation as sufficient typed evidence to permit, but never require, guided
location on a later turn when no delivery address or resolved service location
is known. A hidden product observation or failed presentation is insufficient.
The existing main model remains the only conversational planner and may choose
the location surface when hesitation or an installation-practicality check makes
it useful; no planner call, funnel stage, deterministic prose, follow-up rewrite,
or new commercial authority was added. Existing delivery, known-location,
one-decision-layer, serviceability, and renderer guards remain authoritative.
Optional re-engagement also backs off when a delivered province surface still
awaits action or a validated location action already exists. A new explicit
installation request may still reopen the model-visible tool.

The first isolated VM candidate correctly authored a province-selection CTA but
did not call the guided tool, leaving no buttons below the text. Runtime now
strengthens the main model's location guidance and typed objective instead of
forcing a tool choice. An explicit installation-location request remains a
primary objective, while post-product hesitation makes location a preferred
next-best move when no stronger current need conflicts. The model still chooses
the move from the full conversation and writes the transition; no deterministic
planner forces location ahead of product work.

The repaired candidate exposed a second typed-state mismatch before promotion.
Extraction retained a generic question label such as `Service Areas` for
conversation continuity and correctly marked it unsafe for action, but service
objective construction still treated its display label as a usable customer
area. Unsafe location signals are now excluded from partner/slot lookup and no
longer suppress the guided province objective. This uses the extractor's
existing safety decision rather than matching any customer phrase.

The model prompt explicitly prefers the guided province surface after delivered
product help when hesitation, comparison fatigue, choice overload, or stalled
progress makes a practical location check useful. It also names the deferral
conditions: owed product help, delivery, known location, another surface already
selected for the same turn, and pause/close turns. A prior product surface is
not a blanket blocker: on a later hesitation turn, location may replace it as
the sole current decision. This adds no model call and does not make the surface
deterministic.

Eligibility is observable through the existing capability-profile candidate and
selection-reason trace, while execution, rendering, delivery, and click events
continue through the established guided-interaction telemetry. Focused local
validation passed 745 tests across turn planning, service progression, location
rendering, and the runtime harness; the complete local suite passed 1,577 tests. Staging, live
release, and monitoring evidence are recorded separately
after completion and must not be inferred from this local result.

## 2026-08-18 - Model-led guided-location surface preference

The prior model-facing contract made the province surface eligible but still
left a semantic choice to ask an unknown location appearing interchangeable
with prose asking the customer to type a province. The Runtime V7 model
contract now states that, when the model selects unknown location as the next
needed move and the permitted guided surface is available, it calls
`present_serviceable_location_choices` in the same turn so the deterministic
province buttons are the execution. The main tool loop remains
`tool_choice="auto"`; this is prompt and typed-objective guidance, not a forced
tool, new planner, model call, renderer change, or funnel stage.

Free-text city/barangay/landmark collection remains appropriate when precision
is required, when a partial or concrete location is already present, or when a
product or other decision surface owns the current turn. Immediate branch,
installation-location, service-area, and available-location questions remain
eligible when province selection advances the actual goal; a concrete area
continues to route to grounded partner or slot lookup instead. Existing
delivery, known-location, one-active-decision-layer, serviceability, and
renderer guards remain unchanged.

Focused deterministic coverage asserts the shared prompt/tool-schema wording,
primary installation and preferred post-product objectives, competing product
surface deferral, and concrete-location lookup path. No staging, live release,
delivery, routing, or external-state action was performed by this local change.
