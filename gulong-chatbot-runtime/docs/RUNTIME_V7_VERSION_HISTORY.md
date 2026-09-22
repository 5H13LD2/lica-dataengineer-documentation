# Runtime V7 Version History

Last updated: 2026-09-17

This is the human-readable Runtime V7 timeline. It groups commits into the
runtime capabilities they introduced and records why each phase mattered. Use
this with `docs/IMPLEMENTATION_NOTES_RUNTIME_V2.md`: the implementation notes
are chronological change logs, while this file explains how the architecture
evolved.

## 2026-09-17 - Compound payment identity and deterministic preload reuse

- Compound payment hydration can use the full per-call identity—method, brand,
  and payment option—to recover one unique customer-authored installment plan.
  Generic `installment` alone remains insufficient, and ambiguous repeated
  terms still fail closed.
- The resolved canonical scope flows unchanged through provider execution and
  same-turn cache identity, preventing one sibling clause from overwriting or
  deduplicating another.
- Successful deterministic current-promo preloads are now reusable when a
  model redundantly repeats the hidden read-only promo tool. This preserves the
  provider evidence and avoids turning fulfilled work into a false tool error.
- These changes address the two remaining exact `d545e13` complete-gate
  findings. All 1,933 local tests pass; exact staging evidence is pending.

## 2026-09-17 - Post-repair provider-surface normalization

- Provider-owned service-summary deduplication now applies after a model
  contract repair as well as before it. This covers turns where an unrelated
  tone or schema issue first requires model repair and duplicate service prose
  is the only remaining violation.
- Acceptance still fails closed unless renderer, request-coverage, and typed
  claim contracts all pass after sanitization. This closes the sole remaining
  exact `c3e98b6` complete-gate blocker; all 1,930 local tests pass.

## 2026-09-17 - Deterministic composer surface completion

- The renderer now completes omitted required supporting-replacement surfaces
  only from exact turn-plan authorization. These surfaces contain deterministic
  promo/warranty presentation and are not model-selected customer decisions.
- Duplicate prose already owned by those surfaces is sanitized before a costly
  model repair, and validated installation selections expose one canonical
  evidence ref for typed `validated_state` and `order_facts` claims.
- Controlled pre-product slot-to-partner progression redirects remain recorded
  but are no longer counted as external tool failures. The evaluator also
  distinguishes asking where installation is available in a known city from
  asking the customer to provide their location again.
- The changes close exact `a6b443f` composer/routing findings and target a
  stable reduction below the unchanged 2M core budget. All 1,929 local tests
  pass; fresh exact staging evidence is pending.

## 2026-09-16 - Prompt-owned canonical location completion

- Short typed locations are recovered deterministically only when the immediately
  preceding assistant turn directly asks for the customer's city or area and
  the answer resolves to an unambiguous canonical location.
- Uncertain answers, relative terms such as `near me`, store/head-office asks,
  and questions remain excluded. This closes the integrated gap where the final
  prose understood `qc po` but the qualification ledger did not.
- Scenario contract `2026-09-16.2` also removes one redundant full-journey turn
  by including the already-known date in the initial customer facts. The core
  limit remains 2M tokens; all 1,926 local tests pass and exact staging evidence
  is pending.

## 2026-09-16 - Evidence-bounded adaptive evaluator journeys

- The full product-to-payment journey can continue through a typed schedule
  reply when structured order state already owns a canonical installation area
  and the rendered turn explicitly requests a date. It still requires the
  resulting tracked schedule and payment surfaces.
- Operational scoring accepts expected no-tool composition after a typed
  location only inside the scenario that separately proves canonical capture,
  planned qualification, and visible output.
- Provider-owned service prose sanitization is an accepted final-composer
  outcome only with its exact guard event, a positive removal count, no
  remaining violations, and a successful location-scoped partner result with
  provider and presentation authority.
- These changes address the three evaluator-only blockers from exact staging
  `1f98658`; all 1,920 local tests pass and fresh staging evidence is pending.

## 2026-09-16 - Cross-tool promo evidence and resilient release probes

- Explicit promo mechanics are merged from both product-search and promo-
  catalog calls. Model variation in which provider call carries `promo_types`
  can no longer let a generic brand discount clear a typed requested-mechanic
  mismatch.
- The release evaluator retries transient tester-route transport disconnects
  with the same idempotency key, capped at three attempts and bounded by the
  original per-action deadline. It records all attempts and still fails closed
  after repeated disconnects or any non-successful HTTP response.
- This closes the two distinct findings from the first exact `ec9516d`
  complete run: a genuine cross-tool commercial-scope defect and transient
  transport failures that previously cascaded into unrelated scenario errors.
  All 1,915 local tests pass; fresh exact staging evidence is pending.

## 2026-09-16 - Requested-promo truth and deterministic location progression

- Requested promo mechanics are now evaluated independently from generic brand
  promo availability. Provider-backed exact-size cards may still be shown when
  the requested promo is a soft-filter miss, but the typed per-card disclosure
  must identify that mismatch and the requested-brand miss remains observable.
- A single exact product produced from customer-backed size plus brand now has
  a deterministic progression postcondition: absent existing location/contact
  or another active decision, final pre-delivery output asks directly for city
  or area while preserving the product and supporting promo surfaces.
- Expected suppression of a province/city picker after the customer says their
  location is unavailable is classified as a progression redirect rather than
  a tool error. Invalid location plans outside that reviewed path still fail.
- Operational evaluator contract `2026-09-16.1` accepts deterministic location
  progression ownership only when the exact guard reason, one product card,
  matching preserved surface ref, and visible direct area question are all
  present. A generic skipped composer remains a failure.
- These additions close the two customer-path blockers found in the exact
  `8ee0f38` complete staging run and pass all 1,913 local tests. Staging, live,
  and VM promotion remain gated on fresh deployed evaluator evidence.

## 2026-09-16 - Promotion-gate correctness and metered-budget isolation

- A customer who semantically says that a requested installation/delivery
  location is unavailable now produces the closed, current-turn-only
  `location_response_status=unavailable_now` signal. After size+brand or a
  selected product, runtime advances to an optional contact follow-up instead
  of repeating the location question. Concrete locations, store-location
  questions, coverage questions, and relative `near me` requests are negative
  controls and cannot enter this path.
- If the model nevertheless proposes the province/city picker on that turn,
  runtime rejects it as incompatible with the extracted current-turn state,
  removes the pending picker surface, and renders contact follow-up. Other
  grounded tools and validated customer actions still prevent this override.
- Pure payment-policy turns whose every result has one typed, checkout-backed
  claim now use `provider_grounded_payment_composition`. The deterministic text
  is validated against the same payment-claim and ungrounded-assertion
  contracts before rendering; mixed product, promo, service, FAQ, and surface
  turns still use the final composer.
- The evaluator accepts that payment status only for reviewed payment cases
  with provider authority, complete expected typed claims, and matching final
  prose. Location-request scoring now reads rendered text units and tracked
  location actions, with reviewed meaning-level positive and negative controls.
- Metered limits are explicit per workload: core matrix `2,000,000`,
  operational funnel `1,200,000`, and hydrated history `100,000` tokens.
  Combined usage remains visible but is not compared with the historical core
  cap. Caps may be lowered per run but cannot be raised through CLI arguments.
- Exact staging `3ed42de` passed the payment correction and exposed the forced-
  picker integration edge above. The follow-up correction passes all 1,901
  repository tests locally; exact staging evaluation, then live Cloud Run and
  VM promotion, remain pending.

## 2026-09-16 - Fitment-first product fallbacks and scoped service grounding

- Customer location state now separates one current/home anchor from an
  ordered set of acceptable nearby areas. Alternatives are advisory search
  preferences: they cannot replace the anchor or prove serviceability.
- Installation-partner and slot arguments without an explicit selected area
  are deterministically hydrated from the normalized anchor. Provider evidence
  and composer claims are bound to the exact queried area, so one successful
  lookup cannot authorize claims about the other acceptable locations.
- A zero-card product observation no longer authorizes slot progression.
  Without a delivered/validated product or an explicit schedule constraint,
  an attempted slot lookup is redirected to partner coverage.
- Latest-turn product constraints are rehydrated independently by brand,
  terrain, origin, category, promo type, and model. Stale ledger preferences
  cannot silently narrow a new search.
- Provider-owned service summaries and partial-product-match notices preserve
  exact facts even when model wording varies. Typed claim declarations remove
  duplicate model availability prose without phrase matching.
- Product presentation now treats exact tire size, explicit EV compatibility,
  and customer exclusions as hard constraints. Named brand, model, terrain,
  category, budget, origin, warranty, stock, promo, guarantee, and installment
  requests are ranked preferences: exact-fitment near matches may be shown only
  with typed, per-card disclosure. Requested-brand options remain first.
- Explicit exclusivity is canonical rather than phrase-bound:
  `brand_match_mode=strict` is emitted only for customer wording such as "brand
  only/no other brands" and prevents cross-brand fallback. Ordinary brand
  availability questions default to `prefer` and cannot hide valid exact-size
  alternatives. Complete source-backed options remain visible in text; trusted
  media separately controls visual galleries and tracked selections.
- This branch remains locally implemented only. The complete repository suite
  passed 1,888 tests; staging, live, VM, and ManyChat delivery are unchanged.

## 2026-09-15 - Operational-funnel evaluator coverage

- Promotion and complete model layers now include four reviewed,
  transcript-derived paths for the primary operational KPI: size+brand
  near-miss to customer-owned location/contact to planned official Moderate.
- The gate validates rendered pre-delivery requests, typed or guided completion,
  canonical signal provenance, and the deterministic qualification payload.
  It remains independent of actual ManyChat delivery and BigQuery persistence.
- A complete negative control prevents unnecessary location re-asking, while
  fail-closed provenance rules prevent product cards, province-only actions,
  and store/relative-location wording from becoming customer evidence.
- Operational technical totals are isolated from historical baseline
  denominators but included in the absolute combined token/model-call budget.
  Production abandonment and 7/14-day booking conversion remain separate
  observational health metrics.

## 2026-09-13 - Typed current-promo discovery and surface-safe payment fallback

- Broad requests to browse current promotions now have a canonical transient
  semantic scope instead of depending on a model independently choosing promo
  tools on every sample. The extractor owns meaning across language and phrasing
  variation; the runtime owns a bounded read-only provider search and exact
  gallery projection. The scope never becomes a durable customer preference or
  commercial fact.
- Specific brand, campaign, and mechanic questions remain on the scoped
  model/tool path. Source and relation controls prevent historic context, raw
  keyword detection, or an asserted preference from opening the general gallery.
- A failed payment composer can no longer erase a valid required product
  surface. Runtime replaces unsupported prose with provider-derived fallback
  text but preserves the already-authorized renderer refs, so the channel keeps
  the exact product cards, images, and tracked selections chosen by the turn
  plan.
- The dedicated guarded path reports
  `payment_claim_safe_surface_fallback` with its preserved-surface count.
  Scenario contract `2026-09-13.1` accepts it only for the reviewed nonlinear
  product-first expectation when the product provider, tracked surface, guard,
  and zero-claim evidence all agree. Generic renderer fallbacks remain invalid.
- Broad current-promo turns no longer expose the two promo tools to the main
  loop after typed runtime preload has already completed them. This selective
  projection removes duplicate model/tool rounds while leaving the provider
  evidence available to the composer; specific promo paths are unchanged.
- Cost/latency comparison can bridge only the exact approved prior and current
  scenario digests. This preserves the immutable `50e5975` baseline while all
  candidate correctness checks remain bound to the current contract.
- The generalized contracts pass 840 affected tests and all 1,848 repository
  tests locally. The zero-cost evaluator also passes both deterministic layers
  with zero model calls and zero tokens. Staging model stability, token usage,
  rendered output, and the unchanged 19-scenario deployment gate remain
  pending.

## 2026-09-12 - Scoped promo alternatives and deferred payment evidence

- The first complete exact-staging matrix on `5cca58d` passed 18 of 19
  mechanical scenarios. The remaining Toyo promo turn correctly denied the
  requested scoped offer but failed to show the explicitly requested valid
  alternatives and incorrectly asked for a tire size already supplied.
- Promo search now carries a canonical fallback scope: no fallback, the same
  mechanic on other brands, or any current promo. The lightweight semantic
  extractor records explicit latest-customer consent; deterministic hydration
  rejects broader model proposals without that typed provenance. Provider
  results keep scoped and fallback refs separate, bind the fallback scope into
  the evidence hash, and authorize only current renderable catalog refs.
- Payment evidence recovery now distinguishes a question-only or conditional
  scope from a confirmed preference saved for later checkout. A product-first
  turn no longer spends extra model rounds answering future payment or schedule
  work, while mixed selected-option plus payment-question and compound
  multi-clause questions remain strict positive controls.
- Promo truth fallback copy no longer assumes one hard-coded mechanic and does
  not ask again for a known tire size. It claims a shown alternative only when
  the deterministic promo presentation contains cards and a valid surface ref,
  and its prose acknowledges that an already-rendered alternative is shown.
  Empty/invalid visual output remains a negative control.

## 2026-09-12 - Cross-clause payment-scope recovery

- The first exact-staging smoke run on `599b6ba` passed deterministic, API,
  channel-history hydration, contact, and delivery checks, but correctly
  blocked promotion when the model merged a named payment method with a
  sibling installment term. Hydration protected provider execution from the
  merged scope, but only two of three independent payment claims were produced.
- Runtime now detects when one model-proposed payment method draws its
  distinctive tokens from multiple hard customer clauses. It derives only a
  contiguous customer-backed named-method span from the non-installment clause
  and schedules a separate canonical `answer_order_faq` lookup. It does not
  maintain provider, bank, brand, SKU, or customer-phrase exceptions and never
  decides support or brand eligibility.
- The exact merged-call regression and three adjacent negative controls pass,
  along with 905 affected-path tests, all 1,817 repository tests, Ruff,
  compilation, diff checks, and the no-cost evaluator profile. Exact staging
  rerun evidence remains required before promotion.

## 2026-09-12 - Complete retry metering and production domain projection

- Background-signal extraction now aggregates usage-only metadata across all
  returned retry attempts. The runtime still discards invalid response content,
  while evaluator and trace records distinguish fully metered retries from
  attempts that failed before usage became observable.
- The production harness now follows the capability compiler's intended
  signal/ref-driven domain selection instead of loading the product domain by
  default. General tools and bounded `request_capability` recovery remain
  available when the initial normalized evidence does not select a domain.
- After the exact compatibility SHA passed both staging migration directions,
  the normal Cloud Build default advanced to canonical JSON. Rollback uses an
  explicit nested-writer substitution on dual-reader code.
- Capability expansion is a replacement round rather than consumed customer
  work, including at a one-round configured tool cap. Retry metrics distinguish
  missing initial usage from missing retry usage, and normalized LLM spans
  retain both provider-attempt counts.
- This is a prompt/tool-surface projection, not deterministic phrase routing:
  normalized evidence controls exposure, the model controls interpretation,
  providers control facts, and guarded runtime boundaries still control
  commercial claims and side effects.
- Focused telemetry and construction regressions pass locally. Full repository,
  staging, exact-live baseline, and complete promotion-health evidence remain
  required.

## 2026-09-12 - Versioned Firestore strategy-state migration boundary

- The Firestore adapter now isolates persisted representation from Runtime
  V7's stable dictionary state contract. It reads legacy nested maps and
  schema-versioned canonical JSON, validates canonical content by SHA-256, and
  never exposes storage metadata to runtime orchestration.
- A full state write selects one configured format and atomically removes the
  other representation. Narrow lock and interaction-inbox merges preserve the
  state fields. Invalid canonical metadata fails closed instead of silently
  reviving a stale legacy copy.
- The first staging release used the legacy nested writer to establish reader
  compatibility, then the same SHA passed canonical writes. The current build
  default is canonical JSON; migration is lazy and rollback must retain the
  dual reader.
- Local generated-data controls prove both representation transitions,
  decoded equality, stale-CAS immutability, and cleanup. Deployed staging and
  complete evaluator validation remain release gates.

## 2026-09-12 - Staging-only Firestore transport diagnostics

- The CAS save boundary can now observe individual Firestore begin and commit
  RPC attempts below the unchanged GAPIC retry/timeout wrapper. Diagnostics
  separate network-attempt time, retry backoff/wrapper time, transaction body,
  and process CPU/concurrency evidence without exposing saved content.
- A protected staging-only no-model endpoint exercises generated 40 KB or
  140 KB documents in benchmark-only collections and always attempts exact
  cleanup. Live environments hard-disable both the endpoint and RPC observer.
- Staging Cloud Build supports an explicit Gunicorn worker substitution so
  process-count experiments can compare the same code and Firestore method one
  variable at a time.
- After exact staging replay proved the slow segment was one successful commit
  rather than retries, per-attempt diagnostics gained current-thread versus
  other-thread CPU, GC, page-fault, and scheduler-context-switch counters.
  These fields remain content-free and staging-only.
- Exact staging evidence shows the slow commit is current-thread CPU and
  repeated zero-yield cyclic-GC scanning during Firestore encoding, not retry
  backoff or concurrent saves. This is diagnosis only; storage representation
  and GC policy remain unchanged pending a separately gated mitigation.
- A separate staging-only generated-data endpoint now compares that realistic
  nested state with canonical JSON text and deterministic gzip JSON through the
  same CAS method. It rotates execution order, verifies exact decoded state and
  revision after each save, rejects a stale revision per variant, and verifies
  exact cleanup. The experiment does not alter the production representation.
- Exact staging comparison confirmed the representation mechanism: canonical
  JSON and gzip JSON reduced 40 KiB saves from roughly 6.6 seconds to under
  60 ms and 140 KiB saves from roughly 18.6 seconds to under 125 ms, while
  eliminating the observed commit-side cyclic-GC storm. Production state still
  uses the nested map pending a versioned compatibility and rollback design.

## 2026-09-11 - Protected deployed history-hydration gate

- An exact-staging experiment replaced the Firestore transaction with an
  atomic update-time precondition after the turn lock. The matched rerun showed
  no persistence improvement, so the transaction implementation is retained.
  Phase telemetry still separates local state assembly from the remote save;
  any future index-exemption, compaction, or delta-write change requires a
  separate storage review.
- Runtime-completed promo gallery projections now report zero-millisecond
  in-process latency when no provider latency applies, so the strict tool-
  latency contract distinguishes deterministic surfaces from missing evidence.
- Tester diagnostics now expose bounded runtime phase timings for session
  load/reload/lock, conversation and harness hydration, interaction settling,
  model harness execution, rendering, freshness, delivery/tagging, session
  persistence, inbox cleanup, trace emission, and the total handler. Promotion
  health aggregates p50/p95/max per phase and tool plus client-versus-handler
  overhead; missing or invalid phase/tool timing is a hard telemetry failure.
- Turn-level model accounting now includes the paid background-signal
  extractor, active-working-memory compactor, and image-evidence calls in
  addition to the main tool loop and composer. The aggregate exposes logical,
  metered, missing-usage, provider-attempt, and retry counts; incomplete usage
  or unmetered retries fail the promotion gate instead of borrowing validity
  from another call in the same response.
- Supplemental model components now appear in normalized LLM span logs, while
  the dedicated state-extraction span maps its real `model_usage`, cache,
  latency, model, and attempt fields. Tool latency is also present in both the
  bounded tester debug contract and component spans. This closes the evaluator
  gap that previously labeled only main/composer telemetry as 100% complete.
- Structural duplicate scoring now compares bubbles within each rendered turn
  instead of flattening an entire multi-step journey. It still catches genuine
  same-response duplicates, while allowing a state summary or missing-details
  reminder to recur after a later tracked customer action.
- Default tester conversations remain isolated from ManyChat history. A new
  authenticated hydrated tester route is restricted to a configured synthetic
  account, rejects injected history/reset requests, forces return-only
  delivery, and exposes only bounded hydration and numeric usage evidence.
- The layered pre-staging, pre-live, and complete profiles now include this
  integrated loader -> hydration -> model-path sentinel. Its usage counts
  toward the shared 2,000,000-token ceiling and its latency must remain within
  95,000 ms, closing the gap between component API checks and isolated tester
  scenarios.
- Channel-history cache reuse now requires the exact provider message ID when
  one is available. A newly received repeated phrase therefore refreshes
  ManyChat history instead of matching an older cached turn by text, while a
  true duplicate event keeps the inexpensive cache path. The protected route
  also reports its enforced `return_only` contract independently of optional
  provider delivery metadata.
- The no-tool model path performs one bounded retry when the model emits empty
  output or a JSON response contract with no renderable text, image, or surface
  unit. Non-empty ordinary prose retains its existing specialized repair path.
- Ranked city previews may support scoped availability facts, but they do not
  complete a schedule request while the customer's city is unselected. The
  composer obligation now requires `pending_validation` in that state and
  changes to `answered` only after city-level schedule evidence is actionable.
- Compound installment hydration now expands a partial model proposal to the
  complete customer-authored method only when clause parsing yields one unique
  scope. The complete method, brand, and option therefore own execution,
  cache identity, and deduplication; repeated ambiguous terms are not guessed.
- Composer repair has a narrow deterministic last guard for duplicate warranty
  or promo prose already replaced by a typed supporting surface. It removes
  only contract-identified duplicate sentences, preserves response-unit
  indexes and remaining model prose, and accepts the repair only after renderer
  and request-coverage revalidation.
- Scenario contract `2026-09-11.4` distinguishes model-plan flexibility from
  execution exactness. Serial model scenarios are the default semantic gate;
  concurrent model workers are reserved for an explicitly separate load test.
- Baseline token efficiency is now normalized at stable
  `case/action/occurrence` grain with valid usage on both revisions. A minimum
  80% of baseline actions must remain comparable. Newly restored guided steps
  and usage-missing failures stay visible in aggregate workload totals but are
  not treated as zero-token baseline turns in the relative efficiency gate.
- Generic empty/no-renderable model recovery now receives one bounded
  replacement round even when deployment limits ordinary tool rounds to one.
  Previously the retry prompt could be queued and then skipped by the loop
  ceiling, causing a safe but unhelpful resend response.
- Main model transport now defaults to one bounded retry for classified
  transient provider failures, with a 0.75-second backoff and a maximum
  configurable value of two. Attempts remain inside the shared tester call
  budget and expose retry telemetry; semantic and contract failures do not
  qualify.
- The no-renderable retry recognizes an unfenced JSON response-unit array that
  omitted the required object envelope. It receives the same single bounded
  replacement attempt; bracket-prefixed customer prose remains owned by the
  existing renderer and service-card recovery paths.
- Product/promo discovery policy is projected only into product-capable main
  turns instead of the shared core. Product and mixed-domain turns retain the
  same rules, while an order-only prompt drops 6,729 irrelevant characters.
  The shared and final-composer voice contracts also make the one-question
  rule concrete: state understood details instead of stacking a confirmation
  question before the next-step CTA.
- Isolated no-tool business-location turns now have a deterministic
  postcondition after model rendering. A high-confidence explicit own-address
  request may fall back to the canonical reviewed head-office address, while a
  bare store/branch-location request with no customer area asks one city/area
  question and cannot surface the head-office address. The classifier combines
  multilingual intent cues and abstains for fulfillment, mixed, tool-backed,
  active-choice, and selected-product turns; this is a policy boundary rather
  than an exact-sentence matcher.
- Empty or non-renderable JSON arrays receive the existing one bounded
  replacement attempt. The check parses actual array syntax and retains
  bracket-prefixed customer prose such as product budget/premium sections as a
  negative control.
- The business-location disposition now also constrains planning. Isolated
  explicit-address and bare store-location goals expose no tool schemas before
  the model runs unless the latter already has a reusable customer area. This
  prevents incompatible installation pickers and internal choice tokens from
  escaping before the post-render boundary, without matching one customer
  phrase.
- FAQ providers can attach typed required-answer facts to their evidence. The
  final composer validates those facts using canonical term sets or bounded
  regex variants, repairs omissions, and can fall back to the provider-authored
  semantic answer. Delivery policy is the first adopter, requiring the Greater
  Manila/Lalamove path and canonical 7-10-day lead time while accepting natural
  equivalents such as `7 to 10 araw`.
- A changed business-location boundary now synchronizes the accepted text into
  both the harness final response and the channel renderer's preferred
  assistant field. This closes an ordering escape where the guard recorded a
  correction but the renderer recovered the earlier rejected model paragraph.

## 2026-09-10 - Ambiguous store location separated from business address

- Model policy now distinguishes three ownership/goal states: a bare store or
  branch-location request asks for the customer's free-form city/area; an
  explicit Gulong.PH/head-office address request uses reviewed operating
  identity; and an explicit installation/service-area request may use the
  guided or provider path.
- Scenario contract `2026-09-10.3` mechanically forbids the head-office address,
  service tools, and province-choice tokens in the ambiguous case. A separate
  explicit-address negative control prevents the clarification rule from
  suppressing legitimate corporate-address answers.

## 2026-09-10 - Provisional promotion-health ceilings retuned

- The absolute complete-run ceilings are now `95,000 ms` p95 latency and
  `2,000,000` total tokens, as explicitly approved for the current gate. The
  earlier 45-second latency warning and compatible-baseline 10%/25% token
  regression thresholds are unchanged.
- Saved evaluation artifacts retain their embedded policy and integrity
  digest. Older runs are not reclassified in place; the next complete run must
  produce fresh evidence under the revised contract.

## 2026-09-10 - Independent pre-verified promotion-health gate

- Scenario contract `2026-09-10.2` replaces stale surface/spiel assumptions
  with provider-relative product-promo evidence, direct business-address
  grounding, known-location journey progression, and action-specific promo
  applicability. Positive promo claims must preserve the provider card's
  brand, size, mechanic, quantity, price, and evidence identity; negative
  claims must disclose a reviewed or verified promo scope.
- Promo source authority is enforced after accepted composition as well as on
  fallback paths. Campaign-catalog no-match evidence cannot authorize a broad
  product-level negative. The tester call guard now permits up to ten provider
  requests while preserving a hard ceiling and redacted origin diagnostics.
- Deployed evaluation refined two lifecycle contracts without weakening their
  end-state requirements: a known customer location may advance directly from
  product to schedule, and a compound payment method may be partial in the
  model call only when deterministic hydration produces the complete
  method/brand/option provider execution. Staging correctness paths pass, but
  live/VM promotion remains blocked by measured latency/token limits and the
  missing synthetic channel-read identity.
- Staging evidence hardening now records typed commercial payment claims from
  deduplicated provider results even when the final composer is accepted. The
  evaluator accepts an empty `no_tags` result as a safe return-only outcome but
  still blocks any applied tag or unexplained non-empty tag plan. Canonically
  equivalent repeated payment scopes no longer inflate the required claim
  count; distinct scopes remain independently enforced.
- Compound installment hydration now recovers a missing shared brand or
  payment-option scope only from one unambiguous customer-authored method
  clause. Identical terms under multiple brands remain unfilled instead of
  allowing cross-clause leakage.
- Health execution is now layered by cost and purpose: focused/full local
  contracts, independently opted-in read-only commerce/channel APIs, and explicitly enabled initial,
  in-depth, or complete model evaluation. Named profiles make these layers
  independently schedulable without letting a daily check silently incur model
  usage.
- The in-depth journey verifies deterministic Moderate and High trigger output
  and the routing-independent analytical qualification contract, including an
  event/idempotency identity bound to the tracked action. Tester
  isolation still disables ManyChat mutations and analytics persistence, which
  remain separate operational gates.
- The deployed release-candidate matrix now uses tester-only chat and tracked-
  action routes, verifies return-only delivery and skipped tags, and blocks all
  order/payment mutation tools. Synthetic state remains isolated but persisted.
- Promotion health is independent of per-run human review. A versioned,
  pre-verified scenario contract supplies exact required case/journey IDs and
  a definition digest; selectors remain diagnostic and cannot produce a
  promotion-ready partial result. The seven CS dimensions are reported through
  transparent deterministic proxies rather than an LLM judge.
- Payment assertions are checked against provider-owned scope captured in the
  run. Canonical method, brand, option, and tire-size comparisons replace
  sentence-level answer matching; policy concept checks tolerate equivalent
  phrasing.
- High-risk payment cases now prove an identity-linked chain from model-proposed
  arguments through hydrated provider execution and bounded deduplication
  evidence. A second reordered two-brand case adds shorthand and typo variation
  without hard-coding the provider's mutable eligibility outcome.
- Feature surfaces use an explicit environment expectation profile. Enabled
  product/location/schedule/payment controls must render and validate through
  tracked clicks; intentionally disabled controls must remain absent; a
  legitimately empty promo catalog is N/A only with provider-owned empty-ref
  evidence. The profile is part of baseline compatibility under schema v4.
- Artifacts now require exact target identity, response telemetry, valid
  journey action sequences, consistent row outcomes, and a SHA-256 evidence
  digest. The layered runner recomputes child scores. Private diagnostic and
  redacted review bundles are checksummed locally; durable Cloud Storage
  publication, scheduling, and email delivery remain deferred.

## 2026-09-09 - Clause-scoped grounding and selective prompt projection

- Runtime V7 now treats explicit delivery questions as requiring grounded
  general-policy evidence. If the model understands the request but emits no
  tool call, one typed, bounded retry exposes `answer_policy_faq`; this is not
  a hard-coded FAQ response or a replacement for semantic retrieval.
- General delivery policy and exact serviceability are separate obligations.
  A named but unvalidated destination can receive regional/courier/timing facts,
  but the composer must keep exact-address coverage pending.
- Payment FAQ calls retain customer-authored clause scope through hydration and
  deduplication. Method, brand, option, and term are validated per call, so
  compound Home Credit, Yokohama Pay Later, and BPI questions produce distinct
  provider-backed commercial claims instead of inheriting turn-wide metadata.
  A bounded evidence retry recovers explicit numeric installment plans that the
  model omits, including when its first lookup merged multiple clauses.
- FAQ obligation IDs are canonicalized and deduplicated before final response
  coverage is checked. Required scope-boundary obligations also carry an
  explicit pending disposition.
- Prompt ownership is narrower: the main model receives compact operating
  identity and planning rules, while the final composer retains the complete
  customer-language and composition contract. Dynamic composer context projects
  authorized surfaces instead of duplicating full domain state.
- The full local Runtime V7 suite passed 1,560 tests and the full repository
  suite passed 1,639. A varied live-model matrix
  confirmed the target delivery and payment paths plus negative controls.
  Deployment and production-channel validation were not requested; BigQuery was
  explicitly outside this change.

## 2026-09-02 - Numeric manufacturer-warranty display normalization

- Product normalization now treats a wholly numeric value in an explicit
  manufacturer-warranty text field as a year count. Cards therefore render
  catalog values such as `5` and `1` as `5 years` and `1 year` for every
  product, while already-authored terms remain unchanged.
- The rule belongs to deterministic catalog normalization and card rendering;
  it adds no model call and does not infer warranty scope, eligibility, or claim
  mechanics.
- Focused warranty checks passed 4 tests, the product-search runner passed 101,
  the related renderer/commercial set passed 172, and the full local suite
  passed 1,608 tests. No deployment or customer delivery occurred.

## 2026-09-02 - Generic card-link integrity and delivered-card continuity

- Every catalog card URL is now validated against the card's structured
  pattern/model identity. A stale or contradictory slug suppresses only the
  URL and emits status telemetry; product, price, image, and tracked selection
  remain available. Valid matching and abbreviated-model links remain intact.
- A selected category/value shorthand over successfully delivered product
  cards now enters typed visible-product resolution. New brand, size, SKU, or
  budget filters still require fresh product evidence.
- The local multi-turn live-test pack now simulates successful delivery only
  when an exact stored card title is present in customer-visible output; the
  production API retains its actual channel-delivery boundary.
- The varied semantic matrix reached 9/10 satisfactory scenarios. Explicit
  warranty coverage remains the failed scenario; staging and channel-delivery
  validation remain pending. The subsequent numeric-warranty normalization
  raised the full local suite to 1,608 tests without changing that semantic
  score.

## 2026-08-31 - Answer-first request coverage and warranty replacement ownership

- Final composition now carries grounded request obligations and explicit
  direct-answer, supporting-replacement, and optional-context surface roles.
  Empty/unknown-only plans and omitted required surfaces enter the existing
  bounded repair path; failed repair preserves valid grounded units and required
  surfaces instead of discarding the turn.
- Exact product, price, and location surfaces cannot be displaced by an
  unrequested broad promo. Explicit independent grounded requests may retain
  multiple required answer surfaces, while optional competing decision layers
  remain constrained. Provider-backed area coverage becomes a text obligation
  when anonymous partner cards are intentionally suppressed.
- The automatic first-TPP Double Warranty gallery is retained as the visual
  replacement for the old prose warranty spiel. Composer inputs expose only its
  replacement role/ref, not its card mechanics, which prevents a second warranty
  explanation or promo-focused CTA while preserving product text and image
  selection cards.
- Low-information policy is starter-specific rather than universally
  promo-first: tire-help leads with size/vehicle discovery, `How to avail?`
  answers process first, bare `Get Started` asks one discovery question, and
  availability may still use a reviewed promo entry.
- Complete-size price/product requests now require product evidence rather than
  treating a promo gallery as the answer. Registered read-only cross-domain
  calls can trigger one safe capability recompile, preserving all already-active
  domains without executing the initially unexposed call.
- TPP product cards no longer ask the model to run broad promo retrieval. The
  runtime-owned replacement policy fetches only the reviewed Double Warranty
  card and keeps it beside the unchanged product presentation.
- Final independent review added four bounded safety/robustness gates: an empty
  tool schema now rejects every tool call; automatic warranty replacement
  requires the exact reviewed title; its presence removes warranty fields from
  composer product headers and rejects duplicate warranty prose unless a
  grounded warranty FAQ answer is required; and cross-domain recovery receives
  only one replacement tool round.
- Local verification passed `881` focused tests and `1518` full Runtime V7
  tests. Bounded local live probes confirmed starter behavior, grounded
  promo-plus-location coverage, exact-size prices, and the supporting-only
  warranty gallery. Deployment, staging, and channel delivery remain pending.

## 2026-08-27 - Final-composer repair-cause observability (deployed)

- Final-composer calls retain the existing component identity but now expose
  stable attempt kind, repair reason, and typed violation labels in normalized
  LLM-span metadata.
- This creates a direct denominator for repair rate, tokens per repair cause,
  and repair latency without parsing prompts or joining free-form guard-event
  payloads.
- The change adds no model call and changes no composition, validation,
  retry, rendering, or customer-response behavior. It was deployed to staging,
  Cloud Run live, and the customer-facing VM. Exact-SHA/digest health checks,
  return-only probes, bounded request monitoring, and normalized initial-attempt
  telemetry passed. No natural repair occurred during the monitoring window;
  repair-path projection remains covered by deterministic regressions.

## 2026-08-18 - Model-led guided-location surface preference (implemented locally)

- When the model semantically selects asking an unknown customer location and
  the permitted guided location surface is available, the shared model/tool
  contract now prefers calling that surface in the same turn so the existing
  deterministic province buttons execute the decision instead of interchangeable
  typed-province prose.
- The main tool loop remains model-owned with `tool_choice="auto"`. No forced
  tool choice, keyword gate, funnel stage, new model call, renderer change, or
  commercial/service authority was introduced.
- Exact city/barangay/free-form detail, partial or concrete location context,
  delivery, known-location lookup, and a competing current decision surface
  remain outside the button preference. Branch, installation-location,
  operating/service-area, and available-location questions remain eligible when
  province selection is genuinely the useful next move.
- Focused deterministic tests cover the prompt/schema/objective contract,
  installation without area, delivered-product re-engagement, competing product
  work, and concrete-location lookup. This is local implementation evidence
  only; no deployment, traffic change, customer delivery, or ManyChat action is
  asserted.

## 2026-08-18 - Conditional post-product guided location eligibility

- A delivered product-card presentation can now permit guided province choices
  on a later turn even when installation intent has not yet been persisted.
  This closes the primary exposure bottleneck left by the August 15 hotfix.
- The move remains conditional and model-selected. The model must answer owed
  help first and avoid interrupting active fitment or product narrowing; no
  separate planner, rigid funnel stage, or added model call exists.
- Explicit installation with no usable location is the bounded exception: its
  typed primary routing objective requires the province presenter so authored
  “choose below” text cannot appear without controls. Post-product location
  remains conditional and model-selected.
- Delivery addresses, resolved locations, hidden/failed product presentations,
  an outstanding delivered province surface, and a prior validated location
  action suppress optional re-engagement. The existing renderer's one-active-
  decision-layer and serviceability guards are unchanged. Existing eligibility-
  to-click telemetry provides the release measurement path.

## 2026-08-15 - Model-owned guided location eligibility (implemented locally)

- Restored the stable Runtime V7 application tree after the rejected adaptive
  next-best-move candidate, retaining only the independent Cloud Build routing
  correction before adding this hotfix.
- Installation without a usable service location now creates a non-ranked
  guided-location candidate. The existing model-led loop may choose it as one
  low-friction move during comparison or hesitation after answering owed help;
  it is no longer deterministically forced as the first tool.
- Delivery, accepted address, resolved location, and prior-choice guards remain
  deterministic. Province/city overlap normalization now distinguishes Cavite
  from Cavite City.
- The patch does not include the failed candidate's typed next-best-move model,
  follow-up rewrite, finalizer, schedule parallelism, or lifecycle-state work.
  Those items are explicitly deferred for a fresh future branch.

## 2026-08-12 - Marketing images excluded from Website Inquiry routing (implemented locally)

- A Gulong-branded marketing or promo image now remains unvalidated
  product/image context rather than Website Inquiry routing evidence. This
  prevents an image logo or OCR-detected Gulong URL from triggering the
  downstream `Customer from website` reassignment flow.
- Gulong product cards/pages, carts, checkout/payment pages, order pages, and
  order emails remain Website Inquiry evidence and retain the existing routing
  priority over Moderate/High tags. The exclusion is source-type based, not a
  brand, product, or phrase exception.
- Both signal production and passive tag evaluation enforce the boundary. A
  Gulong URL recovered only by image OCR cannot fall through as a routing
  signal; image-origin routing requires an explicit routable surface. Focused
  tagging and image-observation validation passed `675 tests`. Staging and
  live/VM verification are pending.

## 2026-08-11 - Deterministic intent lineage metadata (provisional, implemented locally)

- Added `INTENT_RULE_VERSION="gulong_intent_v2_20260811"` to the lead-
  qualification boundary and exposed `decision_mode="deterministic"` plus
  `rule_version` in `LeadQualificationSnapshot.to_dict()`.
- Analytical Moderate records copy the snapshot metadata and use the same
  exported rule-version constant when an older caller omits it. The existing
  size-plus-two-support-field Moderate rule, `qualification_level`, and
  countable behavior remain unchanged, while malformed contact text no longer
  counts as the contact support.
- Focused lead/tagging regression validation passed `49 tests`; the broader
  Runtime V7 regression selection passed `1476 tests`. This is local
  implementation evidence only; no deployment, ManyChat mutation, or
  production-data change is asserted.

## 2026-08-11 - Analytical Moderate qualification lineage (implemented locally)

- Every synthetic Runtime V7 Moderate qualification now adds one versioned,
  countable `analytical_qualification` object to `turn_trace_log.tagging`.
  It carries stable event/idempotency identity, customer/session/turn context,
  occurred-at timestamp, service environment/revision metadata, redacted signal
  provenance, stable evidence refs, and the final ManyChat tag outcome.
- Website Inquiry keeps its routing exclusivity: its tag can suppress the
  Moderate Intent routing tag without removing the analytical Moderate record.
  Downstream reporting must deduplicate append-only trace rows by
  `qualification_event_id`, not infer qualification solely from a ManyChat tag.
- Guided choice and promo actions now preserve presentation/card/surface/choice
  correlation identifiers. Promo actions use the actual delivered presentation
  ref when retained in session state; the bounded catalog-card fallback is
  explicitly marked as correlation only, not proof of a rendered gallery.
- Focused regression coverage passed for applied, Website-suppressed, failed,
  duplicate/retry, and non-Moderate cases plus trace and tracked-action context.
  This is local implementation evidence only: no deployment, ManyChat mutation,
  or production-data change is asserted.

## 2026-08-11 - Commercial answer and warranty-presentation reconciliation (implemented locally)

- Generic credit-card installment answers now expose all current applicable
  terms and source-backed bank/provider associations, while exact bank or term
  questions remain narrow. Typed payment values are validated before they can
  scope the lookup, preventing generic installment prose from becoming a fake
  bank or month value.
- Product-card installment lines now use the same active checkout authority on
  every product search. `/payment/list` replaces conflicting `/shop` terms and
  an authoritative empty result removes stale installment copy; catalog terms
  survive only when checkout metadata is unavailable.
- Down-payment/deposit questions in the active tire-order flow now receive the
  authoritative reservation-fee meaning without an invented fee amount. The
  composer silently uses the normalized business term rather than quoting or
  explicitly correcting clear customer shorthand, typos, or informal wording.
- The model-to-tool contract carries that reservation-fee meaning as a typed
  semantic topic, so clear shorthand such as `DP` does not rely on exact phrase
  matching. Checkout descriptions and provider icons also use one shared
  bank-name projection, keeping payment prose and product-card installment
  lines consistent. The model silently uses the correct reservation-fee term,
  connects an amount question to the next grounded quote step, and keeps
  brand-limited installment terms distinct from each card's exact eligibility.
- The obsolete website-directed general how-to-order FAQ was removed; ordering
  continues inside the current model-led conversation and reuses known shopping
  details.
- A failed promo-gallery attempt no longer suppresses the reviewed Double
  Warranty asset. Only a renderable warranty surface replaces the legacy
  grounded paragraph fallback.
- Focused deterministic tests and three bounded local live-model scenarios
  covered installment reconciliation, reservation-fee/order progression, and
  warranty rendering. This entry records an implemented-local candidate, not a
  commit, deployment, delivered ManyChat message, or traffic change.

## 2026-08-11 - Get Started shopping-entry contract (implemented locally)

- Exact approved `Get Started` starter controls now recognize the known
  leading checkmark decoration and optional variation selector that ManyChat
  may emit, without widening recognition to ordinary customer text.
- The typed entry context and both main/final composition paths distinguish a
  bare shopping entry from an explicit how-to-order FAQ. Customer wording,
  the useful next shopping step, and any supported promo surface remain
  model-selected; exact commercial facts and renderer-owned surfaces retain
  their existing authority boundaries.
- The same progressive-intake rule now applies to generic low-information
  welcome turns. The model prefers rendering the reviewed promo catalog as a
  concrete no-brand entry and follows it with one connected question. It asks
  directly for size/vehicle or city/area when that surface is unavailable,
  recently shown, or unhelpful. It no longer adds a permission question before
  an available read-only action. Substantive questions and supplied details
  continue to override generic intake, and the preference is not a deterministic
  promo insertion.
- BQ-derived testing refined that boundary: a bare greeting, ambiguous price
  fragment, or generic availability/assistance/tire-help prompt is still a
  low-information shopping entry when it supplies no usable criteria. A specific
  location, installation, quote, warranty, policy, or order goal still takes
  precedence. Final composition also avoids mentioning unseen promo cards when
  the tool loop did not supply a reviewed promo surface.
- This is a local implementation checkpoint only. Focused positive/negative
  control tests, a bounded Runtime V7 test slice, and local Gemini 2.5 Flash
  harness run `runtime_v7_live_pack_20260811_105042` passed the bare-control
  contract. Follow-up live run `runtime_v7_live_pack_20260811_113240` covered
  five varied first turns and structurally rendered reviewed promo and product
  surfaces in the selected paths. Preference-focused live run
  `runtime_v7_live_pack_20260811_121746` additionally verified that two
  low-information openings selected the reviewed five-card catalog while an
  explicit order-process question did not. A 16-message BQ-derived matrix then
  exercised high-volume automated and varied free-text openings. Targeted
  post-adjustment run `runtime_v7_live_pack_20260811_124451` rendered six reviewed
  promo cards for all four affected low-information cases and none for three
  specific-request controls. These harness runs are not proof of delivered
  ManyChat behavior, and no release, deployment, or ManyChat flow update is
  asserted.

## 2026-08-10 - Compound commercial answers and response composition

- Compound promo and payment questions now keep their authorities separate and
  issue the independent read-only lookups together. A promo search can no
  longer satisfy or suppress a required payment lookup, and a named-brand promo
  question without size no longer produces arbitrary cross-size product quotes.
- Generic payment questions use a compact customer-facing projection of active
  checkout metadata: e-wallets, cards, installment, and bank transfer/online
  banking. Named methods, banks, terms, brand restrictions, and Pay Now/Pay
  Later scope remain exact and provider-grounded.
- Customer-facing payment wording no longer has to repeat a combined checkout
  row's internal display label. When the validated row covers the customer's
  requested credit-card or debit-card method, that natural requested wording
  satisfies the commercial claim contract; unrelated payment wording remains
  rejected.
- Normal and repaired turns remain model-composed. Only when both omit a
  validated payment claim does the existing last-resort guard state that exact
  provider-backed fact in concise customer wording, instead of returning a
  vague payment placeholder and discarding the useful answer. A compound promo
  question also retains the matching reviewed offer summary while its card
  remains renderer-owned.
- First explicit named-promo questions prefer one relevant reviewed visual.
  Targeted brand galleries retain related offers for reasoning but render only
  matching-brand cards when the requested brand has an active offer.
- A brand/model mention without tire size, vehicle, or an existing exact
  selection no longer authorizes one arbitrary-size product card during DOT,
  warranty, delivery, payment, or other informational questions. The model
  answers the independent questions, then asks for fitment context.
- DOT/manufacturing-date questions about an offered, visible, or selected tire
  now use that exact product's DOT field. The assistant states the value
  directly, or says it is not listed for that option; generic week/year code
  education is reserved for customers who ask what DOT means or how to read it.

## 2026-08-09 - Contract-audit closure and typed authority alignment

- Removed unreachable deleted-helper tombstone tests and obsolete fixed
  follow-up rotation/prompt-copy assertions. Preserved strict contracts for
  tokens, tracked actions, provider facts, renderer surfaces, order/payment
  validation, idempotency, and side effects.
- Removed the unused deterministic service fallback CTA producer. Typed service
  results continue to carry coverage and lookup semantics; ordinary customer
  wording and the next CTA remain composer-owned.
- Current customer and validated guided state now outrank model-re-emitted old
  history. Product/service observations remain trusted fact context but cannot
  manufacture product selection, fulfillment, or order readiness.
- A visible product enters readiness only through selected-product context or a
  durable customer product identity that resolves uniquely against the trusted
  observation. One visible card alone is not selection.
- Current typed tire size and fulfillment override conflicting model-proposed
  retrieval arguments. Partial tire-size correction is limited to one
  unambiguous component of one complete prior size.
- Product price-list suppression now compares commercial fingerprints as well
  as card identities, so changed price, quantity, promo, installment, warranty,
  protection-plan, or inclusion facts render again.
- The final local Runtime V7 suite passed `1373` tests. No deployment or live
  channel mutation is included in this contract-audit increment.

## 2026-08-09 - Explicit-customer precedence across state and guided choices

- Model-authored turns now share one disposition rule: customer pauses and
  closes take precedence over automatic progression, while active turns retain
  a reasoned one-step CTA. Grounded connective prose speaks as Gulong.ph rather
  than as an outside assistant narrating what it found or how cards are grouped.
- The guided `Others` installation-area action is navigation, not a location or
  fulfillment choice. Its card points toward delivery; its typed action context
  recommends delivery without selecting it; and the structured signal boundary
  prevents synthetic bridge text from being persisted as customer consent.
- A serviceable province remains usable installation context. City refinement
  is requested or shown only when needed for the active installation goal, not
  repeatedly when the customer pauses or moves to another question.
- Read-only product/service observations remain available to the model but no
  longer persist as if they were customer choices. Carried state retains its
  original customer or guided-action authority, so an installation lookup does
  not silently replace an explicit delivery choice.
- The signal model can reconstruct a clear partial correction such as `225
  pala` from the prior full tire size, and fresh corrections replace stale
  values through the same general signal precedence used by other dimensions.
- Rapid choices in one guided layer now consistently use the latest validated
  choice unless comparison is explicit. The shared rule covers category,
  product, location, schedule, and payment layers; accepted price-category
  choices now use the same durable commit path as other commercial choices.
- The model owns semantic deferment, transitions, mixed-question handling, and
  the next CTA. Exact product text, image cards, prices, promotions, warranty,
  guided tokens, tracked actions, and submission safety remain deterministic.
- Promo presentation recovery now depends on a successful prior presentation,
  not merely an attempted call. Explicit price-category browsing also wins over
  automatic promo-first discovery.
- Varied return-only replays covered delivery retention, partial size
  correction, free-text product selection, payment/delivery questions,
  deferment, price-category cards, rapid category replacement, product images,
  and the Double Warranty catalog card. The final local suite passed `1464`
  tests; no deployment is part of this increment.

## 2026-08-09 - Conditional, model-resolved Find Tires navigation

- A generic promo-card **Find Tires** action remains deterministic only for
  validating the card click and rendering grounded guided choices. It no longer
  carries an advisory instruction that assumes tire size must be collected.
- The model now resolves the next discovery step from current conversation
  state: reuse a known exact size for brand/category discovery or ask for it
  when absent. This avoids competing with durable signals and working memory
  while preserving the stricter selected-product authority used for
  transactional promo actions.
- Focused promo-action regressions passed locally. No branch promotion or
  staging/live deployment is included in this change.

## 2026-08-09 - Final-candidate channel boundary and named-promo scope

- Kept internal runtime session identity separate from ManyChat recipient
  identity. Customer-channel delivery, tag application, and handoff notes now
  target `channel_user_id` when supplied, with `user_id` retained only as the
  compatibility fallback.
- Applied exact catalog-title scope to both runtime-completed and model-issued
  promo gallery calls. The resolver is catalog-derived, accepts the optional
  leading article in a published title, and does not contain campaign-specific
  rules.
- A non-delivering local preview showed only the requested Double Warranty
  card. One subsequent controlled send to the approved trial subscriber
  returned ManyChat HTTP 200, and ManyChat message history independently
  confirmed the outbound text, square image card, and visible `Choose Brand`
  and `Promo Details` actions in event `27700344869`.
- The delivered model prose was grounded and usable, but one sentence referred
  generally to other current promos even though the turn intentionally showed
  only the requested card. This is retained as a non-blocking human-response
  quality observation; the runtime did not rewrite or resend the model text.
- No staging/live deployment or traffic change is claimed by this local
  controlled-contact gate.

## 2026-08-08 - Model-led serving authority consolidation

- Removed active `lead_cta_focus` production authority and its module instead of
  preserving a second deterministic stage/CTA instruction beside the composer.
- Removed separate serving decisions for product progression, location choice,
  and payment-query classification. The main model now selects ordinary
  read-only tools and the final composer owns the visible transition and next
  useful CTA across every surface.
- Kept deterministic authority for exact provider facts, guided controls and
  tokens, side effects, delivery mechanics, and hard submission safety.
- Removed phrase-ranked FAQ hints from serving capability selection and
  consistently exposed the safe domain-specific FAQ readers to the main model.
- Removed phrase-triggered product-detail/external-evidence retry rounds and the
  keyword-selected empty-output service CTA. Structured objectives and claim
  refs now own retries; exhausted empty output uses a neutral resend request.
- Replaced signal `status_hint`/evidence phrase authority with closed relation
  and confirmation fields for persistence, recency, merge, and action safety.
- Allowed explicitly marked supporting surfaces beside one active
  transactional decision layer; supporting warranty context no longer competes
  with the product choice it explains.
- Stopped production semantic audits from deleting sentences, replacing valid
  model-authored turns, or triggering duplicate commercial-composition cycles;
  retained explicit audit helpers only for offline evaluation where still used.
- Recovered a mixed promo/product/payment case that previously exceeded the
  eight-call tester ceiling. The corrected two-turn path retained brand, size,
  quantity, BDO installment context, and Sta. Rosa location and progressed to a
  grounded scheduling CTA.
- Counted the approved Double Warranty catalog card as visible product
  inclusions so it is not repeated because of stale delivery bookkeeping.
- Passed 989 final focused tests across the affected cross-surface, state,
  follow-up, and renderer files. No full-suite, external delivery, commit,
  staging promotion, or live promotion is claimed.

## 2026-08-08 - Guided-evaluator parity and useful qualitative advice

- Added a fail-fast local endpoint launcher that copies only current staging
  literal feature configuration, excludes secret references, and forces
  return-only/non-delivery behavior before the Runtime API is imported.
- Added a tester-isolated guided-action route so the evaluator can use the exact
  category, product, location, schedule, and payment tokens returned by the
  renderer without writing into normal session state or sending to ManyChat.
- Proved locally that price-category and product surfaces render real choices,
  their clicks validate against the delivered allowlist, the chosen category
  scopes product search, and the exact selected product advances the sales flow.
- Made a deliberately presented reviewed promo gallery primary over a generic
  category menu when no grounded product result owns the turn. This preserves
  the promo answer while leaving category discovery available for the next
  customer decision.
- Made validated price-category clicks authoritative typed state, replacing an
  older category preference instead of leaving contradictory working memory.
- Allowed model-led, calibrated tire expertise for subjective comparison and
  recommendation while retaining evidence requirements for measured features,
  exact product claims, certifications, commercial facts, and guarantees.
- Updated the model-owned voice guidance to prefer `pcs` or `tires` for tire
  quantities instead of the more formal `piraso`, while allowing natural
  mirroring when the customer uses that word first.
- Passed 275 focused tests. No full-suite, deployment, or live-channel delivery
  claim is part of this increment.

### 2026-08-08 - Long-horizon choice and signal retention

- Added varied long-horizon regressions for free-text corrections, retractions,
  business-information interruptions, and every guided choice family.
- Durable customer choices now beat question-only mentions for the same field;
  generic promo navigation no longer becomes a product/SKU choice; changing a
  payment option clears incompatible bank and term qualifiers.
- Pinned selected-product evidence survives later search-observation eviction.
- Corrected the customer-visible presentation boundary: a product observation
  may exist without its product cards having been delivered. Only actual text,
  cards, or tracked product buttons create delivered product-presentation state.
- Kept sales-stage transition model-led. Validated guided facts and delivery
  status are typed context; no post-model location-to-product CTA rewrite or
  schedule-surface deletion was added.
- Added a tester-only provider-call ceiling and a bounded live signal-retention
  probe. The combined four-scenario, 31-turn probe passed; see
  `RUNTIME_V7_CHOICE_AND_SIGNAL_RETENTION_EVALUATION_2026-08-08.md` for adaptive
  transcripts, defects found, and remaining release checks.

## 2026-08-06 - Complete-turn composition around deterministic surfaces

- Every nonempty first turn now uses one complete model-authored opening before any
  guided surface. Runtime owns the requirement and failure fallback rather than
  the successful wording, allowing natural greeting, acknowledgement, and answer
  variation. Full intake remains only for compatibility/failure handling.
- Exact starter labels now supply advisory intent to the main runtime instead of
  deterministic final prose. Product-stock FAQ routing also distinguishes human
  assistance availability from actual stock questions.
- The composer can anticipate renderer-owned message roles across product,
  promo, fitment, service, order, and payment turns. The manifest contains no
  new commercial authority and no copied surface body; it exists only so the
  model can write a cohesive acknowledgement, answer, and next step around the
  actual customer-visible sequence.
- Structured-response pricing safety moved to the model-authored text-unit
  boundary. Trusted product surfaces are inserted only after that audit, which
  preserves guided cards and exact price/promo rows even when composer repair
  falls back deterministically.
- Claim validation no longer interprets a disabled or absent turn-plan contract
  as an explicit empty allowlist. Explicit empty contracts still deny claims;
  missing contracts skip only that typed validator and retain the other fact,
  payment, voice, and renderer checks.
- The earlier live smoke exercised the transitional fixed-welcome merge and
  revealed the renderer re-audit defect in one product-price fallback. The
  bounded model-authored-opening recheck then passed on a new missing-size
  vehicle inquiry: the model identified Gulong.ph, acknowledged the requested
  brand/vehicle, and asked only for the sidewall size without fixed welcome
  insertion. This is local harness evidence only; no staging or release claim
  is made.

## 2026-08-06 - Offline complete-turn evaluation foundation

- Added a data-minimized offline review layer over existing Runtime V7 probe
  and API-debug artifacts. It preserves ordered customer-visible bubbles,
  cards/images/buttons, evidence strength, and compact model/tool/cache/state
  telemetry without changing production runtime behavior. It redacts phone and
  email patterns but still requires approved or pre-redacted source artifacts.
- Preserved real renderer payload shapes and allowlisted presentation evidence
  while removing operational identifiers and normalizing internal router
  targets. Explicitly empty output and missing customer input fail closed.
- Added a deliberately varied 13-scenario pack using paraphrased customer
  patterns rather than repeated brands, sizes, vehicles, locations, exact
  response scripts, or phrase-based quality gates.
- Kept mechanical authority/structure findings separate from human-CS review.
  The primary orchestrator must score understanding, natural language,
  directness, grounding, progression, presentation, and consistency from the
  complete visible episode and supply rationale for every concern or failure.
- Established a proportional test cadence: focused offline tests during edits,
  one renderer integration file at final review, one selected live scenario
  when needed, and the full Runtime V7/live pack only for a later behavioral
  release whose scope justifies it.

## 2026-08-04 - Promo execution and context consolidation

- Combined the model's promo lookup and normal gallery decision into the
  `search_promo_catalog` contract. Runtime now completes a requested reviewed
  gallery from provider-issued allowed refs in the same execution round,
  eliminating the otherwise redundant `present_promo_gallery` selection round.
- Encouraged the main model to batch independent provider lookups while keeping
  truly dependent execution sequential. No hard per-turn call ceiling, raw-text
  gate, speculative provider call, or removed retry was introduced.
- Replaced repeated full promo candidate/guidance payloads across turn planning,
  composition, audit, and semantic repair with one shared compact
  `promo_response_contract_v1`. Full retrieval details remain in operational
  traces; exact campaign and product-provider authority is unchanged.
- Hardened result-dependent gallery selection so a mixed proposal retains only
  current provider-allowed refs instead of losing every valid alternative. A
  wholly unauthorized proposal remains an error.
- Corrected the release gate for unmatched-brand promo-alternative requests:
  the current reviewed promo gallery is sufficient, while product/category
  surfaces remain deferred under the one-choice-layer contract. Current promo
  refs and tracked tokens, supported audit, the scoped requested-brand negative,
  and absence of a false requested-brand promo remain required.
- Added focused contract, same-round gallery, answer-only, compact-authority,
  composer deduplication, and repair-packet regressions.
- Promoted merge `712b605` after `1,349` local tests and a `16/16` exact-staging
  matrix. Live Cloud Run revision `gulong-chatbot-runtime-live-00081-sf5`
  remains at 0% traffic, while the customer-facing VM serves immutable digest
  `sha256:63e71bd24595ea6ea8472094e6f2e451cc4738aba0aa8b6328b059e5d9aec72b`.
  The first six real turns had no runtime/tool failures; the two early promo
  turns used about 24% fewer calls and 26% fewer tokens than the prior six-hour
  promo cohort. The sample remains preliminary.

## 2026-08-03 - Composition-contract and repair simplification

- Answer-only FAQ and business-contact turns now carry one compact composer
  packet containing the selected answer goal, provider evidence, exact refs,
  required authored facts, continuity, and voice contract. Stale lead gaps,
  commerce/service progression, working memory, decision packets, and draft
  prose no longer compete with the requested answer. Mixed turns keep the full
  progression packet.
- Semantic answer-goal and promo-fact failures now skip the old broad repair
  and enter one evidence-only recomposition followed by one independent audit.
  A repeated failure uses the existing safe fallback rather than paying for a
  second semantic composition cycle. Mechanical format/renderer repair and
  transport retry remain intact; there is no hard per-turn call cutoff.
- Safe semantic fallback preserves provider-authored facts when the initial
  normal-response audit found the answer goal relevant. A conflicting repair
  audit can still force fallback but cannot replace those facts with a vague
  clarification; only an initially misaligned answer is omitted.
- Provider-issued promo refs now cross the turn-plan boundary as canonical promo
  evidence for both composition and claim validation. Proactive grounded promo
  presentation is distinguished from an unanswered promo request without
  weakening claim auditing.
- Payment FAQ answers take precedence over unrelated stale CTAs, and
  `prepare_payment_request` evidence declares its actual payment plus order
  claim scope.
- Local gates passed `1,263` Runtime V7 tests and `1,326` repository tests;
  release/build evidence belongs in the separate release history after exact
  staging verification.
- Early VM observation found one remaining provider-scope defect: an empty
  reviewed campaign search was composed as a global denial of a product-level
  quantity promo. Follow-up hardening keeps catalog negatives scoped and makes
  exact product promo price/applicability wait for exact-size product evidence;
  it adds no model or provider call.

## 2026-08-02 - Consistent product galleries and semantic answer goals

- Initial multi-SKU results now always show the complete renderer-owned price
  list before the matching image gallery. Gallery subtitles remain compact
  secondary context rather than the only visible pricing presentation.
- The product runner prefers image-backed alternatives from its existing
  query-filtered ranked pool without another provider call. The renderer then
  uses one displayed-card set for price text, gallery order, `ps1|...` buttons,
  delivery metadata, and the subsequent click allowlist. A rejected image can
  no longer leave a text/button mismatch or trigger a neighboring card image.
- Selected-product projections preserve the trusted catalog image already held
  by the stored product observation. Exact single-product progression remains
  text/details-first and does not invent a multi-card selection surface.
- Price-list suppression is versioned and delivery-backed. Only the exact same
  v2 list-plus-gallery presentation, with the same provider-backed card
  identities and a successful/evaluated non-expired delivery, can suppress a
  repeated list while the customer is still choosing a SKU. Older, failed,
  text-only, and differently ordered presentations cannot suppress it.
- The existing conditional semantic audit now evaluates answer-goal alignment
  for all authored FAQ domains and business-contact answers. It compares the
  request, tool answer goal, authored evidence, and visible response. A
  semantically unrelated result is omitted instead of being faithfully repeated.
  Case-specific pending enforcement remains limited to general-policy evidence;
  exact checkout-backed brand/method facts are not downgraded merely because
  they answer a case-specific question.
- Runtime payment fallback no longer treats the entire customer message as a
  method name. Only typed latest-user payment signals can authorize a named
  method lookup; unknown providers remain valid typed lookup candidates, while
  quotation and other non-payment requests stay outside the unsupported-method
  path. Unsupported typed methods offer current checkout alternatives
  positively when the provider returns them.
- Payment-query items now distinguish concrete named methods from open method
  categories. Category questions receive a separately typed and filtered
  active-checkout result, while named providers retain API-backed support
  checks. Exact wallet-alias matching
  prevents credit/loan/card/installment products from collapsing into a wallet
  merely because the names share a token.
  The legacy single-method scalar is derived only from an explicitly named
  scope, so category-first compound questions cannot change lookup identity.
- Strict payment resolution no longer falls through to generic substring
  matching after rejecting a proposed named product. Checkout conflicts also
  retain their provider answer instead of exposing stale static FAQ copy, while
  submitted order payloads preserve valid payment progression through one
  authoritative row label.
- Strong selected FAQ hints receive one bounded tool retry when the main loop
  omits their authority. This recovers quotation and other authored FAQ goals
  generically without a new classifier call or keyword-specific execution path.
- Payment semantic authorization is now scoped to resolved payment FAQ ids and
  explicit payment fields. Non-payment order FAQs no longer fail solely because
  they share the `answer_order_faq` facade.
- Added Runtime V7-owned DOT-code and formal-quotation guidance. DOT questions
  no longer resolve through a stale warranty alias or allow an unrelated RAG
  chunk to override the selected answer goal. Formal quotation requests receive
  a useful CS progression path without inventing a final quote or order fact.
- Provider-owned empty-promo results and their explicitly non-promo category
  controls now survive every composer terminal status, including renderer
  fallback, so a validated continuation surface cannot be replaced by a vague
  offer to search again.
- Validated informational promo-card actions suppress generic post-loop
  location recovery. Promo Details and About Brand therefore continue from
  their exact tracked evidence instead of allowing a model-proposed unrelated
  delivery FAQ to displace the requested answer.
- Reviewed informational promo-card actions also precede the general turn
  planner itself. Their already-authorized catalog evidence is rendered without
  a model/tool call in ordinary and batched interaction modes, preventing a
  generic FAQ from replacing the exact requested mechanics.
- General-policy semantic auditing now treats "the exact case is not yet
  confirmed" as an epistemic boundary, not a claimed validation workflow.
  Concrete required inputs, responsible parties, procedures, or promised
  verification outcomes still require their own evidence.
- Exhausted general-policy repairs now expose a typed
  `answer_goal_safe_fallback` status. Release automation recognizes it only
  when the matching guard event, failed semantic audit, and required successful
  FAQ authority are present; generic renderer fallbacks remain blocked and the
  visible authored response still requires human-CS review.
- Delivery-process policy evidence now advertises the complete general answer
  goal (availability/path plus timing), while exact-location serviceability
  remains pending. Release checks require the authored path, courier, and
  lead-time facts to be visible; a vague clarification cannot pass solely on
  internal fallback metadata.
- Semantic audits also distinguish a separate optional CTA from an invented
  validation dependency. Saying that input Y is needed to verify pending policy
  outcome X requires process authority even when Y is useful for another goal;
  a clearly separate offer to help with that other goal remains permitted.
- Local validation: focused delivery/gate suite `70 passed`; full repository
  suite `1,315 passed`; Ruff,
  `git diff --check`, and the behavioral/customer-facing change audit passed.
  Staging and live promotion are not recorded by this entry until their exact
  builds, revisions, health, traffic, and customer-visible probes are verified.
## 2026-08-03 - Monthly promo approval surface and Double Warranty draft

- Marketing's Michelin cashback claim form is now present in the August source
  compilation and in pending catalog `catalog-202608-5f4ddb23ee0c-v2` as an
  exact reviewer-visible mechanic. Source URLs are retained deterministically
  after extraction rather than relying on the model to reproduce them.
- Same-month workbook replacement now creates the new visible month tabs before
  hiding archived tabs, preserving the Google Sheets requirement that at least
  one sheet remain visible throughout the update.
- Review artifacts now use one workbook per catalog month in the separate
  `Promo Catalog Reviews` folder. Tabs remain month-first and put an explicit
  `APPROVAL - START HERE` tab first. Same-month revisions may retain version
  history in that workbook, but cross-month reuse fails closed; the publication
  parser continues to consume stable logical tab roles.
- The August pending catalog now includes the July Gulong Double Warranty
  poster and mechanics as a separate warranty item. The new six-item draft is
  `catalog-202608-5f4ddb23ee0c-v2`; all 11 generated retrieval evaluations pass
  the automated draft gate and await human review.
- Month source discovery supports both the established parent/month layout and
  a supplied folder that directly contains `Promo Images` and
  `Promo Mechanics`.
- The July catalog remains active. This change rebuilt the pending review
  draft and migrated its approval pointer to the dedicated August workbook;
  it did not deploy or publish Runtime. The old shared file remains as a
  clearly labeled legacy archive.

## 2026-08-01 - Source-derived promo review gates and August catalog draft

- Promo publication evaluations now follow the enabled offers in each pending
  catalog instead of retaining campaign-specific requirements after those
  campaigns expire. Exact-promo, multi-offer brand, 3+1 positive/negative,
  expired, and unrelated cases remain mandatory and human-reviewed.
- Cashback is a first-class catalog type, separate from an immediate fixed
  discount.
- The incomplete four-promo draft was superseded by pending catalog
  `catalog-202608-2258fde5883c-v2`, which contains the two new
  Michelin/BFGoodrich offers, reviewed Michelin/Apollo 3+1 carry-overs, and
  Michelin Passion Experience through August 31. Reviewer-confirmed
  per-eligible-tire wording and Michelin cashback/3+1 stacking are recorded;
  the missing cashback submission destination remains a human review item.
- Draft evaluation applies Runtime's explicit-offer constraint boundary before
  grading rankings, so an explicit 3+1 case is evaluated against 3+1 records
  rather than semantically related cashback or event records. All ten generated
  cases pass; the July catalog remains active and no release was performed.

## 2026-08-01 - Complete semantic query plans for business facts

- General-policy FAQ composition now has a separate model-based semantic audit.
  It verifies that visible prose covers the required authored answer without
  converting customer context into narrower service, schedule, product,
  payment, or order authority. This closes the gap where a composer could omit
  or relabel its own claim assertion while leaving an unsupported promise in
  the response.
- The same audit runs after repair. Repeated mismatch or invalid audit output
  uses the authored policy as a bounded safe fallback; it does not inspect
  customer prose with keywords or add place-, provider-, brand-, or SKU-level
  routing rules.
- `faq_facts` is now an explicit final-response schema category, and required
  FAQ plan entries carry the authored answer and policy applicability alongside
  their stable evidence ref.
- Semantic policy and promo fact audits have a 1,600-token bounded response
  budget after a pinned staging repair audit ended at the former 900-token
  limit. This changes format reliability only; unsupported or invalid verdicts
  still fail closed, and fallback is not accepted as release proof.
- Repairs triggered by semantic fact scope now discard generated draft prose
  before recomposition. Provider results, authorized refs, required surfaces,
  and the typed turn plan remain; unsupported meaning is removed rather than
  relabeled or repeated through conversational anchoring.
- A successful reviewed promo search now has a stable result-level evidence
  ref bound to its catalog version and normalized query scope. This authorizes
  a verified negative search conclusion even when there are no offer refs,
  while individual promo mechanics remain limited to `allowed_promo_refs`.
- When ordinary repair remains semantically over-scoped, one evidence-only
  model retry keeps provider facts, typed response/renderer contracts, and
  voice guidance while excluding customer-origin context and generated prose.
  The resulting customer copy still passes the same independent audit against
  the original request before it can be delivered.
- A repaired general-policy answer cannot rely on broad policy prose alone
  after a case-specific overclaim. Its typed scope-resolution contract requires
  a natural explicit statement that the exact case is still unconfirmed and
  needs checking, preventing contextual implication from recreating the claim.
- Required-input and validation-step wording is audited as policy/process fact,
  not harmless CTA copy. Product qualification may be offered separately, but
  cannot be claimed as the way to validate a pending service, policy, or order
  outcome unless current evidence establishes that process.
- Empty promo searches expose their reviewed-scope outcome to both repair and
  the independent audit. A scoped “no verified alternative returned” answer
  satisfies an alternatives request without becoming a global catalog claim;
  price-category cards remain ordinary product navigation only.
- If all audited promo-composition attempts still blur that boundary, the
  fail-closed renderer keeps only the typed scoped negative and explicitly
  labels retained price-category controls as non-promo shopping navigation.
  This safety path is catalog- and scope-driven rather than brand- or
  wording-specific.
- The same provider-owned rendering now applies before delivery whenever an
  unmatched-brand search has a successful scoped empty result plus ordinary
  price-category controls. The model continues to decide the tool and customer
  progression, but it cannot widen the commercial negative after an audit
  false-negative.
- Multi-scope payment plans are audited once by the model before canonical
  lookup. This keeps coordinated scope complete and excludes product
  promotions/prices from the payment-policy lane without phrase matching.
- Canonical payment-option fields cannot carry a product brand. A compound
  typed value triggers the same bounded audit so brand inheritance remains
  semantic while option validation remains mechanical.
- Audit packets include current canonical tire brands, keeping payment
  providers and banks in the method field without brand-specific routing.
- Normalized fulfillment readiness can activate the existing read-only service
  retry after a validated product selection, preventing a known concrete
  installation area from stalling before slot presentation.
- Delivery/order business-fact authorization is independent of the broader
  location classification. A supplied area cannot suppress an authorized
  read-only policy lookup, and the decision remains visible in bounded staging
  diagnostics.
- The semantic location checkpoint distinguishes choice viability from an
  explicit business-fact question and selects a bounded read-only grounding
  tool. Runtime still requires provider evidence before customer-visible
  delivery or order facts.
- Authorized delivery-policy recovery preserves a typed delivery scope through
  the FAQ boundary. That scope selects the existing general delivery-process
  policy when wording retrieval has no match, while exact-address coverage and
  delivery-date claims remain unauthorized without a separate provider.
- Successful FAQ answers now cross the composer boundary with stable evidence
  refs and a dedicated `faq_facts` category. This preserves a grounded policy
  answer during repair without weakening the separate positive authorization
  required for exact service or schedule availability.
- The turn plan marks each usable current FAQ as a required answer. Composer
  repair must narrow an over-scoped draft to the supported FAQ fact rather than
  replacing the answer with only a lead-intake question.
- Final composition now retries one truncated or invalid structured response
  at low temperature. The retry is format recovery only and remains subject to
  all positive evidence, renderer, commercial, voice, and side-effect checks.
- Contract repair has the same one-shot format recovery. It retries from the
  original compact context plus typed violations so a truncated repair cannot
  silently replace a grounded answer with legacy draft text.
- Payment interpretation emits every independent method/term and its explicit
  brand/payment-option scope. Runtime bounds and deduplicates those proposals,
  then canonical checkout metadata independently decides support and brand
  eligibility for each one.
- Each proposed payment scope is canonicalized independently, and only a
  claimable scoped result can supersede a general unsupported-method fact.
- A malformed legacy single-method field no longer discards an independently
  valid bounded query list. With no valid list item, the same path still fails
  closed as unclear.
- Release-candidate probes can run checkpointed case or journey subsets without
  weakening exact-SHA or return-only assertions.
- The typed product-progression packet distinguishes a verified empty promo
  result from provider failure. With a confirmed size, the model can therefore
  continue to price-category choices after no applicable offer while preserving
  promo-only handling when an applicable promo surface exists.
- A separate whole-response promo audit verifies positive and negative promo
  meaning against current provider/product evidence. Price-category surfaces
  authorize navigation but never promo mechanics, preventing a model-authored
  continuation from overstating the unavailable-promo result.
- A semantic-only composer mismatch gets one bounded model correction after the
  normal repair. The corrected response is re-audited and must still satisfy all
  renderer, claim, voice, payment, and service-action contracts before use.

## 2026-08-01 - Unified current-promo and grounded business-fact boundaries

- Reviewed promo search, gallery rendering, and tracked clicks now share one
  current-date boundary. Both literal and vector candidates must belong to the
  current published set before they can become model evidence or card refs.
- The semantic location planner remains responsible for whether a province
  picker makes sense. It may separately authorize a read-only delivery/order
  policy lookup, but that routing decision is not serviceability evidence.
- Contact facts carry stable runtime evidence refs, and direct grounded answers
  use a compact first-turn welcome rather than the unrelated intake sequence.
- The legacy lead-focus location attachment is disabled in turn-plan mode, so
  a completed promo/payment/business question cannot silently open a competing
  province decision layer.
- Release-candidate promo assertions are source-time-aware and the matrix now
  covers grounded contact, grounded delivery policy, and semantic store
  location alongside commercial and tracked-choice journeys.

## 2026-08-01 - Semantic product progression after promo discovery

- A failed or non-renderable promo surface no longer ends a confirmed-size
  product turn at a generic acknowledgement. A bounded model decision receives
  the newly observed promo outcome and chooses the next useful product surface.
- The decision can select priced products, concrete products, or broad
  brand/price-category choices, or intentionally remain promo-only or request
  clarification. Runtime validates only normalized size state and read-only
  tool availability; it does not use customer-text regexes or rewrite the
  final response.
- The previous empty-promo retry that unconditionally forced category choices
  was removed; both empty reviewed results and unusable promo galleries pass
  through the same semantic decision.
- An existing promo or broad-category surface is now part of the same semantic
  validation. It remains when it fits the complete request, while an explicit
  exact-product or price request can progress to the normal priced product
  presentation.
- Existing product cards remain the price-list authority and renderer. This
  change makes them reachable when the model concludes that current products
  or prices are the customer's actual next need.

## 2026-08-01 - Semantic service-location planning

- Natural-language store, branch, installation-area, and coverage questions
  now remain in the model-led tool path. The old generic location regex and
  deterministic seed response were removed.
- The main model may request current serviceable province choices through an
  always-exposed general tool. A bounded typed semantic decision distinguishes
  that viable choice from contact channels, concrete customer locations,
  existing partner selections, and delivery/order context. One no-tool
  recovery reuses the same decision instead of introducing phrase matching.
- Deterministic runtime code validates normalized state and provider mechanics,
  then renders the current provider choices with tracked `lc1|...` controls.
  Generic unresolved location text cannot expose concrete service tools, and
  the choice surface cannot authorize product, promo, partner, availability,
  order, or payment facts.
- Human response review also led contact-number normalization to reject prose
  and retain only structurally valid Philippine mobile values.

## 2026-08-01 - Typed semantic state and truthful human handoff

- Background Signals now separate the extracted value from its typed
  relationship to current state. Conditions, questions, retractions,
  corrections, and historical references no longer depend on free-form status
  wording.
- Only asserted, selected, and corrected relations cross the memory/ledger
  boundary. Rejected relations remove prior state, while current-turn policy
  questions can still expose read-only tools without becoming checkout truth.
- Human takeover is a first-class model action. The runtime records the
  request, declares it as an authorized side effect, applies the existing
  `Stop Chatbot` control through ManyChat, writes a CS note, and suppresses
  later chat ingress and proactive follow-ups from durable state.
- A bounded typed authorization call validates each proposed takeover before
  the mutation. Availability questions and non-takeover complaints remain in
  the normal conversation path even if the main loop miscalls the tool.
- Payment FAQ query scope now uses a bounded typed semantic decision plus
  customer signals, preventing a whole correction/no-choice utterance from
  becoming a supposed provider name or an irrelevant payment lookup. The API
  pre-composer payment completion path consumes the same decision and cannot
  add back a lookup that the semantic gate rejected. Named-method output must
  also fit a generic bounded entity shape before it can reach policy lookup.
- Customer copy remains model/composer-owned, but the typed tool result forbids
  false claims that an agent is already connected, assigned, or responding.

## 2026-07-31 - Evidence tests versus human conversation review

- The release gate now records a strict ownership boundary: structured
  evidence, state, surfaces, and side effects are machine-validated; complete
  customer wording and conversation quality are reviewed semantically.
- Model planning was clarified for three reusable cases: promo-only discovery
  uses one promo decision layer, province uncertainty uses serviceable-city
  recommendations before schedules, and product presentation uses one CTA.
- Named-brand warranty recovery combines API-backed canonical brand identity
  with authored FAQ topic metadata so published brand profiles take precedence
  over generic warranty text without hard-coded brand rules.
- Typed brand fact fields now keep manufacturer-warranty duration separate from
  unpublished manufacturer coverage, and bind Gulong damage coverage to its
  published eligibility conditions.

## 2026-07-31 - Product image galleries and Website Inquiry routing priority

- Multi-product selection cards now carry trusted current catalog images,
  compact exact price/quantity totals, and tracked SKU buttons. The previous
  detailed text block remains the automatic fallback if any visible card lacks
  a trusted image.
- Extended the existing image-evidence schema with visible Gulong ownership and
  surface type, covering product pages/cards, carts, checkout/payment, order
  pages, order emails, and marketing assets without adding another model call.
- Added a routing-only Website Inquiry signal that cannot mutate product,
  order, payment, or commercial state.
- Website Inquiry now suppresses competing Moderate/High Intent tag emission on
  the same and later turns. Irate, Chatbot Error, Order Booked, and Payment
  Confirmation remain independent operational tags.
- Tightened text evidence so a Gulong email address is not misclassified as a
  Gulong website URL.
- Hardened the payment-policy boundary so signed/CDN image URLs are ignored as
  customer language and rejected as payment-method values. Screenshot routing
  evidence therefore cannot manufacture a payment inquiry or commercial fact.

## Current Branch Snapshot

- Branch: `fix/runtime-v7-payment-cost-containment`, based on the exact shared
  `origin/product`/`origin/main` checkpoint `66be12f`.
- The deployed checkpoint includes the reviewed price-list/gallery, Website
  Inquiry routing, semantic FAQ, typed payment, location, promo, and tracked
  action fixes. The isolated candidate adds only the evidence-gated
  pre-composer payment-call containment invariant.
- Before candidate promotion, staging was healthy at 100% on
  `gulong-chatbot-runtime-staging-00358-ttk`, and the customer-facing VM served
  immutable `66be12f`. Cloud Run live traffic remained on its prior ready
  revision. These are rollback/preflight facts, not evidence that the new
  containment code is deployed.
- Candidate local validation passed the transaction suite (`111`), focused
  product/payment gate (`689`), complete Runtime V7 suite (`1,253`), and full
  repository suite (`1,316`). Staging, varied live-model, exact revision,
  customer-VM, and post-promotion component call-rate checks remain mandatory
  before declaring the containment release complete.

## Milestone Timeline

### 2026-07-31: Typed composer claim authorization

- Mechanical release checks are limited to objective transport, evidence,
  renderer, state-transition, and side-effect contracts. Customer-visible
  truth, conversational sense, and Filipino-CS quality remain direct semantic
  review gates rather than sentence-regex pass/fail rules.
- The existing final composer call now declares typed factual assertions and
  current evidence refs alongside its ordered response units. Runtime validates
  those declarations against `CustomerTurnPlanV1` and repairs an unauthorized
  service or schedule assertion once without adding a normal-path model call.
- Failed or rejected proposed tool plans do not authorize customer-facing
  claims. Successful prose remains composer-owned and is not rewritten after
  composition.
- Validated informational Promo Details and About Brand actions expose their
  reviewed catalog/profile refs through the same typed claim contract. This
  keeps multi-click batching model-led without losing the source authority
  attached to the clicked renderer surface.

### 2026-07-31: Validated product-click progression

- An exact tracked product click is resolved against the delivered product
  surface and committed before the model turn. Once that trusted product
  context exists, the turn no longer exposes redundant product discovery,
  promo, FAQ, or reference-resolution tools; the model retains the remaining
  service and order tools and decides the next grounded conversational action.
- If the model initially answers without using the already-ready service
  lookup, the existing evidence-lookup retry now recognizes the validated
  product click together with remembered installation intent and a precise
  location, then requires the read-only slot tool before composition. This
  authorizes evidence collection only; the model still writes the response.
- This capability pruning prevents a second model-authored selection plan from
  stalling product-to-location/schedule progression. It does not rewrite,
  insert, delete, or reorder customer-facing prose.
- The release matrix no longer requires a product-choice control after a
  province-level schedule inquiry when a single exact product is already
  grounded. It validates the objective boundary instead: no successful
  province-level slot lookup and no schedule/payment selection surface.
- The composer now keeps its one next question aligned with the active
  renderer-owned choice surface. Promo, product, location, schedule, and
  payment cards therefore remain the current decision layer until the customer
  resolves them; ordinary prose is still model-authored rather than rewritten
  after composition.
- Final-composer validation now treats a selected installation slot as
  read-only evidence until an authorized order submission exists. A composer
  response that calls the slot confirmed, reserved, booked, or secured receives
  one normal composer repair rather than a runtime-authored wording rewrite.
- Composer repair now follows the same voice contract as the normal composer:
  a language-neutral button label is not treated as an English-language switch,
  so tracked choices continue the customer's recent natural language.
- If that repair still fails at an incomplete order-summary surface, the
  last-resort fallback preserves the renderer-owned summary first and then asks
  clearly for the remaining contact/payment details. This fallback is not used
  on successful composer turns.
- Province-level schedule questions no longer authorize availability-preview
  execution by themselves. The city-recommendation plan is allowed only when
  the customer explicitly says they are unsure which serviceable city to use;
  otherwise runtime keeps the turn at the city-choice layer.
- Product-card installment labels now deduplicate equivalent bank, term, and
  interest facts while retaining the underlying API rows for evidence.
- Validated Promo Details context now reaches both the reasoning loop and final
  composer. Brand-level mechanics cannot be broadened into universal SKU,
  model, or size eligibility without explicit reviewed evidence.

### 2026-07-30: Promo authority reconciliation and one active choice layer

- Confirmed the live `/promo_brands` response as the brand-level Buy 3 Get 1
  authority. Reviewed promo records remain authoritative for their published
  mechanics and renderer-owned gallery content, but catalog omission alone is
  not negative brand-eligibility evidence.
- Reconciled catalog and product evidence generically so current API-authorized
  brands remain valid while unsupported requested brands still receive a
  source-backed negative answer and reviewed alternatives.
- Made product selection own the visible turn whenever product-search cards
  are awaiting a choice, including a single exact SKU. Location, schedule,
  promo, and checkout controls are deferred rather than rendered as competing
  decision layers.
- Added an adaptive staging release matrix and explicit positive coverage for
  Vredestein product pricing evidence even when the reviewed gallery has no
  matching brand card. A structured Buy 3 Get 1 product card can reconcile the
  live promo provider without a brand-specific exception.
- Split release evaluation into mechanical contracts and human/CS review.
  Sentence regexes no longer decide whether a grounded answer is semantically
  correct or sounds human; they are limited to serialization-level checks.
- Added a compact prompt mode to the existing final composer for pure payment
  policy turns. It uses the same validated claim objects and same model call,
  but avoids unrelated order/surface instructions that caused intermittent
  claim omission and rigid policy-row fallback.
- Added an evidence-driven promo-surface completion step after a validated
  promo lookup. It invokes no extra model and cannot infer intent from raw
  wording; it only renders allowed refs for brandless discovery or a genuinely
  unresolved requested-brand miss.
### 2026-07-29: Composer-Owned Turn And Location Progression

- Added `CustomerTurnPlanV1` without adding a normal-path LLM call.
- Promo search now treats model-authored brand terms as a proposed query plan:
  the runtime binds requested-brand truth to the current customer message and
  latest-turn signals that are also present in that message, removes model-only brands before retrieval,
  and records rejected plan brands for audit. This is brand-agnostic and keeps
  negative promo answers and active alternatives source-backed.
- Moved trusted location/checkout surface planning before the existing final
  composer so it can order the complete visible response.
- Replaced successful-turn prose rewriting with structural validation, one
  composer repair, and a minimal failed-repair fallback.
- Enforced province-to-city authorization before partner/slot execution and
  added isolated, non-committing city availability previews for customers who
  are unsure which city to choose.
- Added the independent rollback flag
  `RUNTIME_V7_TURN_PLAN_ENABLED`.
- Hardened model-proposed payment lookups by restoring explicit bank and term
  constraints from customer-backed text before resolving an active,
  payment-option-scoped `/payment/list` row.
- Retained a proposed payment-compatibility brand only when the same brand is
  explicit in the current customer question or validated selected-product
  state, covering compound questions without trusting an invented tool arg.
- Normalized hyphenated installment terms before row matching so `3-month`
  cannot fall through to the first installment row in `/payment/list`.
- Preserved all validated payment claims in multi-question turns and stopped
  rewriting composer prose when it already states the API-backed negative
  facts correctly.
- Completed distinct customer-authored installment/brand query plans that the
  model omitted from a compound turn, using canonical brands plus generic
  bank/term parsing and the active checkout metadata. Multi-claim validation
  now covers positive and negative results without a separate model call.
- Scoped payment-answer validation to individual response segments so a
  positive result for one method/brand cannot satisfy a second unresolved
  pairing elsewhere in the same turn.
- Added payment claims to the existing final-composer validation and repair
  contract. Equivalent payment-row/brand lookups are deduplicated, missing or
  contradictory facts trigger one persona-aware composer repair, and
  deterministic Taglish remains only the failed-repair fallback.
- Completed customer-stated compound payment plans before final composition
  and retained a single named brand as shared scope for following clauses.
  This keeps every API-backed outcome available to the normal composer and
  avoids both internal policy phrasing and post-composer fact insertion.
- Unified final-composer and post-composer payment validation on one
  evidence contract, removing the legacy phrase-matcher disagreement that
  could replace a correct natural response with deterministic policy labels.
- Treated a validated brand-scoped payment-row result as superseding an
  earlier brandless lookup for that row, preventing one compound question
  from manufacturing an extra customer-visible policy claim.
- Excluded Pay Now/Pay Later timing choices from unsupported payment-method
  claims and supplied the composer-repair call with the complete validated
  claim set for reliable natural multi-method answers.
- Inherited one explicit Pay Now/Pay Later scope across compound clauses and
  rejected conflicting model-proposed option rows before final composition.
- Changed the existing composer repair instruction from a late system message
  to an explicit correction request after the invalid response, improving
  adherence without introducing another LLM call.
- Removed incidental brand/payment-option scope from globally unsupported
  method claims, allowing natural answers such as Home Credit being
  unsupported without falsely tying that fact to one tire brand.
- Expanded the grounded claim validator's Filipino/Taglish negative vocabulary
  without weakening method/term/brand anchoring, reducing false fallback
  rewrites of correct natural payment answers.
- Added generic cross-method association validation so a positive installment
  fact cannot borrow Home Credit, BPI, or another provider anchor from a
  separate restrictive claim.
- Naturalized the deterministic commercial fallback used only after composer
  repair failure, removing API label syntax and stiff qualification wording.
- Kept post-FAQ qualification composer-owned while directing it to ask only
  for tire size when product context is absent, avoiding a simultaneous
  tire-size and location request.
- Split reviewed promo matches into matched and unmatched requested brands,
  suppressing only partial product surfaces that failed the active promo
  constraint and requiring the customer-visible turn to answer each unmatched
  brand before offering reviewed alternatives.
- Validated explicit promo mechanics and offer amounts against reviewed
  candidates after model-led routing, so an unrelated same-brand offer cannot
  satisfy a Buy 3 Get 1 or exact-discount request.
- Completed proposed promo queries with explicit customer-authored brands
  before catalog execution, keeping compound product/promo planning from
  weakening the reviewed lookup scope.

### 2026-07-28: Model-Led Multi-Click Interpretation

What changed:

- Added typed, timestamped provisional interaction events and a compact packet
  shared by the reasoning loop and final composer.
- Runtime derives only delivered-control decision layers, event ordering,
  hierarchy, legal transitions, and evidence refs. The model decides whether
  rapid clicks mean acceptance, correction, comparison, or clarification.
- Same-layer distinct choices cannot mutate selected product, schedule, or
  payment state until a validated `InteractionDecisionV1` identifies the
  effective event. Informational promo actions remain non-selecting.
- Added tracked-click settling and late freshness suppression so rapid clicks
  produce at most one composed response. Ordinary free text has no batching
  wait and can provide the context that resolves a pending sequence.
- A controlled Premium -> Budget staging replay showed that ManyChat history
  can still expose the previous assistant gallery while the newer click is
  already waiting on the session lock. A bounded pre-lock interaction inbox in
  the existing session store now makes that later event visible to settling
  and pre-delivery checks without treating it as validated state. Firestore,
  Postgres, and memory backends preserve the inbox across session saves and
  clear resolved events after durable delivery/state persistence.
- The replacement replay then correctly suppressed the obsolete Premium
  output but showed that a button-only Premium -> Budget sequence could still
  be interpreted as an unconditional switch. Distinct discovery/location
  selections now require clarification unless a free-text turn supplies
  context; schedule/payment supersession and promo-information comparison are
  unchanged.
- A same-session acceptance replay found that a valid clarification decision
  could still be rendered beside Budget product cards. Clarification-only
  packets now expose no business tools, accept text response units only, and
  suppress renderer-owned surfaces until the customer resolves the choice.
  The model still owns the clarification wording.
- Added side-effect blocking for unresolved sequences, structured composer
  repair, bounded safe clarification, batch analytics, and rollout/rollback
  flags. No separate model call, vector search, BigQuery read, or external API
  change was introduced.

Why it matters:

- Customers can click non-linearly without forcing one brittle response per
  button, while Runtime V7 still prevents stale or ambiguous clicks from
  contaminating commercial/order state or creating duplicate side effects.

### 2026-07-28: Composer-Owned Order Progression and Inbound Identity

What changed:

- Removed the API-layer order-form prose rewrite. The final composer receives
  typed progression state, accepted fields, and the intended
  text/surface/text unit order, then owns the customer-facing wording.
- Removed the phrase-specific delivery-permission paragraph filter. Service
  no-match evidence and the active decision contract now guide the composer
  without deleting ordinary customer-facing questions after generation.
- Renderer-owned input surfaces expose a structural unit contract. If the
  composer adds a second input layer, it receives one typed recomposition
  request; only a failed repair falls back to the grounded pretext and
  renderer-owned surface.
- A successful authorized order submission continues to the grounded payment
  request in the same turn when the selected payment route is already valid.
- Typed payment-option/method transitions invoke the final composer even when
  no read tool is needed. This keeps the acknowledgement model-owned while the
  renderer supplies the validated payment controls and pretext.
- The signal interpreter now treats a concise payment label as a selection
  when the immediately preceding assistant turn requested that exact checkout
  input, while preserving questions and compatibility inquiries as
  unconfirmed lookup plans. Runtime accepts the resulting commercial state
  only when the typed value canonicalizes to current checkout API metadata.
- Unconfirmed payment inquiries are excluded from composer "accepted field"
  context, preventing conversational acknowledgement from getting ahead of
  evidence validation.
- Completing all requested order fields now authorizes the read-only
  renderer-owned summary without a redundant consent turn. Order payload
  creation and submission still require their existing explicit confirmation
  and side-effect gates.
- Typed and clicked payment methods now share the same API-row stage
  classifier. Under Pay Later, non-installment methods fill the reservation
  fee layer and installment rows fill the balance layer, matching the labels
  and explanations shown in the payment gallery.
- A read-only FAQ or policy lookup no longer prevents a newly complete order
  state from rendering its grounded summary in the same turn. Existing
  summary, payload, submit, or payment-request tools still suppress the retry
  because those are already later order-progression stages.
- ManyChat requests without a provider message ID refresh channel history.
  Busy-lock recovery selects the newest unprocessed provider event, so
  distinct repeated replies are not collapsed by identical text.
- Duplicate inbound replays are persisted in turn traces for visibility.

Why it matters:

- The model and final composer remain responsible for conversation quality,
  while deterministic code stays focused on evidence, state transitions,
  side-effect authorization, idempotency, renderer-owned facts, and delivery
  integrity.

### 2026-07-27: State-Idempotent Sales Journey Controls

What changed:

- Choice actions now use state-based no-op detection in addition to
  event-level idempotency.
- Schedule requests require current serviceability/slot evidence.
- Checkout controls are stage-bound and use selected-product, service, and
  current payment metadata together.
- Resolved product, location, schedule, and payment layers are not requested
  again unless the customer reopens them.
- Handoff notes translate internal pending-field names into compact CS labels.

Why it matters:

- ManyChat can emit distinct event IDs for repeated clicks, and customers often
  continue in free text after cards. These changes keep free-form conversation
  flexible while making only the commercial/order state transition
  deterministic.

### 2026-07-26: Post-Reasoning Guard Boundary

What changed:

- Deterministic journey rules now govern only the next requested input and
  interactive control layer. Mixed current questions still receive all
  available grounded answers before the one matching CTA.
- Free-form schedule/payment revisions use model-extracted current-turn signals
  with provenance validation, while raw phrase matching remains only a
  compatibility fallback.
- Order submission requires current customer confirmation after a ready
  deterministic summary; a model-authored tool reason cannot authorize a write.
- Independent validated facts, such as an unsupported payment method and the
  selected partner address, are preserved together without attaching an
  unrelated checkout surface.
- Named payment/provider questions remain typed as unconfirmed routing context,
  including when mixed with product discovery. The API-backed order FAQ
  resolver is exposed without promoting the question to a payment choice, and
  the delivery guard supplies the lookup if the main model omits it.
- Pay Now/Pay Later controls no longer compete with a simultaneous order-review
  question. Payment option owns that input layer; summary review follows after
  the payment choice.
- Payment FAQ arguments are now validated query plans. Customer-backed typed
  brand/payment-option/fulfillment facts replace model proposals; an
  unsupported fulfillment guess is removed. A specific bank or installment
  term cannot fall through to an unrelated generic checkout row.
- Query-plan validation keeps the model's more specific payment-method
  interpretation when a typed extractor accidentally repeats Pay Now/Pay
  Later as the method. Deterministic state constrains the plan without becoming
  a second brittle intent parser. An option-only method plus a structured bank
  or installment term is repaired into a catalog query before validation.
- If the final composer omits a resolved positive payment answer in a mixed
  turn, the commercial guard adds that source-backed fact without replacing
  independently grounded product cards or an already-correct model response.
- Commercial correction preserves an independently grounded product
  presentation in the same mixed turn. The runtime rewrites the invalid
  payment assertion without turning post-reasoning validation into a rigid
  replacement for the model's complete conversational decision.

Why it mattered:

- Customer behavior is not linear and does not always mirror button labels.
  Moving validation after interpretation keeps model-led conversation flexible
  while retaining hard boundaries around commercial truth, stale controls,
  persistent state, and real-world actions.

### 2026-07-26: Active Decision And Evidence-Safe Recovery

What changed:

- Product, category, location, schedule, payment option, and payment method now
  share one decision priority. Only the earliest unresolved layer is visible,
  and the CTA describes that layer.
- New choice presentations supersede older ones. Duplicate delivery of the
  same semantic click is suppressed without another model turn.
- Exact-size inventory cards require exact-size evidence. Diagnostic nearby
  results cannot be presented as matches, and a provider error cannot become a
  false unavailability or no-promo claim.
- Selected installation-partner addresses are disclosed from validated slot
  evidence when customers ask where they will go.

Why it mattered:

- Actual conversations showed competing controls, stale location buttons,
  repeated acknowledgements, wrong-size selectable products, false promo
  absence during provider failure, and location requalification after a slot
  had already been selected. The correction uses the existing interaction and
  evidence ledgers rather than brand-, SKU-, or conversation-specific rules.

### 2026-07-26: Payment Allowlist And Pay Later Role Correction

What changed:

- A populated `/payment/list.available_brands` value is now an authoritative
  allowlist. Brands absent from that row are ineligible for that method; an
  empty value remains unrestricted.
- Current API rows and the website Pay After Service checkout both exclude
  Yokohama from BPI 6-month installment while retaining 3-month installment.
  The earlier contrary interpretation is superseded.
- Pay Later choices carry a typed role derived from checkout option and
  `is_installment`: reservation-fee method or post-service balance method.
  Validated click state and order summaries preserve that role.
- Order-tool arguments are rebound to the current validated checkout click
  before quote, summary, or payload execution. A conflicting model proposal
  cannot switch Pay Later to Pay Now or move a reservation method to balance.
- The delivery guard completes a required API-backed payment-policy lookup
  when the model omits it, and order summaries no longer reuse a
  reservation-fee method as the post-service balance method.
- `submit_order` now independently requires an explicit latest-customer
  confirmation after a ready order summary. Repeated contact/form data cannot
  trigger an order write even if the model proposes submission.
- Contact-form turns that build an order summary no longer repeat a stale
  payment FAQ from older transcript context.

Why it mattered:

- The same structured API row now drives button visibility, direct FAQ answers,
  persisted payment state, and the final order summary for every brand and
  method without one-off exceptions.

### 2026-07-25: Validated Choice Progression Closeout

What changed:

- Valid schedule/payment clicks now produce one runtime-owned acknowledgement
  and only the next unresolved control layer. Model tool results remain
  traceable but cannot redisplay unrelated products or schedules.
- Collected schedule and payment state is reused across later turns. Flexible
  afternoon is complete for conversational qualification while remaining
  explicitly unbooked; exact validation is still required before submission.
- Checkout quotes bind the selected product's validated observation and card
  refs. A later observation or model-proposed product phrase cannot silently
  change the SKU used to build the next payment layer.
- Payment-option changes clear a previous method before the compatible method
  layer is rebuilt from active checkout metadata.
- Validated checkout clicks seed only their API-backed option, method, and
  declared installment term into commercial state. A new option supersedes
  method details from the previous option, while a method label such as
  `N mos` cannot trigger a redundant term question.
- Payment-option compatibility is resolved against the selected option's
  current `/payment/list` rows before applying any generic conflict rule.
  Installment therefore does not imply Pay Now when the API explicitly
  authorizes that method under Pay Later.
- Delivered payment choice refs remain the authority marker after the
  normalized signal moves into the durable session ledger; transcript text
  alone cannot activate the scoped resolver.
- Product/payment button captions expose the compact selected label in the
  visible transcript, and the installation-partner application FAQ requires an
  explicit customer application objective.

Why it mattered:

- The trial path validated every click but still repeated schedule/payment
  questions because delivery composition did not honor the already-persisted
  state. The fix makes the delivered-choice ledger the transition authority
  without adding brand, SKU, bank, or conversation-specific branches.

### 2026-07-24: Qualification Sequencing And Interactive Checkout

What changed:

- Runtime now treats model requests for product and schedule lookup as planning,
  while the final composer and renderer expose only one qualification decision.
  Multiple product cards defer schedule controls; one product card is treated
  as an unambiguous selection.
- Installation availability renders as one day card with two distributed
  morning choices and an always-present flexible afternoon preference. Exact
  clicks validate against the delivered service observation before entering
  order state.
- Once the exact schedule is selected, bundled order-form collection is
  allowed. Pay Now/Pay Later controls use quote math, while payment-method
  controls use active checkout metadata and current brand/fulfillment
  compatibility.
- Payment-method cards retain API-authoritative availability while adapting
  their explanation to the selected Pay Now/Pay Later layer. Specific API
  names are preferred over generic labels, avoiding contradictory checkout
  copy without adding bank- or brand-specific runtime rules.
- Structured payment signals now expose the API-grounded order FAQ resolver
  even before product selection. This closes the generic failure where an
  unsupported named method was normalized correctly but the model lacked the
  payment-policy tool needed to answer the question.
- Order summaries and payloads keep the customer's requested area distinct
  from the selected installation partner's city/address, preventing payment or
  order-review turns from silently moving the customer location.
- Product, service, renderer, and checkout attachment now share the same
  product-first decision helper. Deferred slots require a fresh exact-location
  observation, public click status comes from the persisted allowlist, and
  return-only stateful probes can traverse evaluated controls without sending.
- Session saves no longer rewrite the active-session pointer, preventing a
  superseded long-running turn from restoring stale product/order context after
  reset.

Why it mattered:

- The trial flow previously asked customers to choose a product and type a
  schedule in the same response, then could lose the selected SKU or reinterpret
  a schedule. The new controls preserve model-led conversation while moving
  choice identity and commercial compatibility to runtime validation.

Validation:

- Focused transaction-choice, router, renderer, and product-selection
  regressions are required before staging, followed by the full Runtime V7 and
  repository suites.

### 2026-07-22: Checkout Metadata Authority And Promo-Only Card Safety

What changed:

- Replaced the stale static installment brand/bank policy with the active
  checkout metadata returned by /payment/list. Canonical payment matching and
  checkout planning now validate the requested bank, term, product brand, and
  fulfillment transaction exclusion from that response.
- Yokohama is therefore eligible for BPI 6-month 0% when the active API row
  lists it and the order path is not excluded. Home Credit is returned as an
  unsupported method because it is absent from the active payment metadata.
- Installment-filtered product discovery uses the same active checkout rows,
  so brand/product inquiries are grounded before SKU selection and stale
  embedded product installment fields cannot incorrectly hide Yokohama.
- Payment FAQ lookups accept a proposed brand plus payment method and return an
  explicit validated brand-eligibility outcome. Tire size remains the next step
  for matching products/stock; it is not required to establish the API's
  brand-level payment rule.
- Promo-only product searches now return promo evidence from the active promo
  provider and do not render same-size brand matches that failed the promo
  requirement. This prevents non-eligible Toyo products from appearing as
  Buy 3 Get 1 cards.

Why it mattered:

- The prior static list was created during the checkout bootstrap and drifted
  from the live website/API. Source-backed resolution preserves natural model
  conversation while keeping active commercial facts at the runtime boundary.

Validation:

- Focused product-search, canonical-values, and order/payment harness tests:
  564 passed.

### 2026-07-20: Production-Safe Follow-Up Contract

What changed:

- Follow-up ingress now requires a bearer token and ignores caller attempts to
  control delivery, force, transcript/profile authority, request time, or
  analytics. Sending defaults off and is admitted only by server allowlist or
  deterministic canary configuration.
- Assistant-last proactive work now uses one structured model plan followed by
  deterministic evidence validation and exact one-CTA rendering. The previous
  decision/composer, forced-send, broad sanitizer, and generic fallback path is
  no longer active.
- Customer-last events route into normal Runtime V7 chat with delivery-aware
  inbound replay. Version-2 attempt records and delivered product-presentation
  evidence support failure retry, unknown-delivery reconciliation, and
  brand-to-location focus rotation.
- Current `/promo_brands` authority and exact delivered card evidence jointly
  control Buy 3 Get 1 wording. Unsupported commercial claims fail closed.
- Added normalized follow-up analytics and a redacted 95-case July corpus with
  all nine rollback incidents, 15 explicit safety scenarios, and 71 bounded
  live-transcript cases.

Why it mattered:

- The rolled-back release combined multi-field CTAs, an unsupported
  BFGoodrich Buy 3 Get 1 claim, and an aggressive response to deferred intent.
  These were architecture and evidence-association failures, not isolated copy
  defects.

Validation:

- Focused follow-up, ingress, renderer, observation, promo-action, gateway,
  analytics, and persistence integration suite: `654 passed` on exact commit
  `441dcc5`.
- Full repository suite: `834 passed`.
- Real-model corpus: 95 cases run three times, 285 evaluations, 258 model
  calls, zero invalid structured outputs, one safely suppressed semantic
  validation failure (`0.39%`), zero model errors, zero transport retries, zero
  failed customer-visible invariants, and 545,040 total tokens. Artifact:
  `tmp/followup_v2/july_full_eval_3x_441dcc5_final.json`.
- Pre-final staging probes exposed and corrected cadence consumption by
  transient suppressions. Follow-up planning now also retries one transient
  provider transport error with explicit trace/monitoring metadata.
- Cloud Run staging and VM canary evidence remain release gates and must be
  appended only after those environments are validated.

### 2026-06-28: Explicit Brand Availability Tool Contract

What changed:

- Runtime V7 product policy now tells the main model that latest-turn brand
  availability and price questions must pass every named brand through
  `product_search.required_brands`, including multi-brand asks such as
  `Michelin or Yokohama 175/65R14 meron?`.
- The `product_search` schema now makes the hard-vs-soft distinction explicit:
  `required_brands` means the customer is asking for that brand, while
  `preferred_brands` is only presentation/ranking context for remembered or
  explicitly flexible preferences.
- Background Signal extraction now uses the same interpretation so advisory
  context no longer pushes explicit latest-turn brand asks into soft
  `preferred_brands`.
- `product_search.requested_brand_status` now scopes `matched` to the active
  requested size/filter set. A brand that exists only in broader fallback
  results stays `missing` for the exact request and is separately exposed as
  `available_outside_requested_filters`.
- Product-search tool schema and Background Signal examples now preserve rim
  suffixes such as `ZR21` and `R14C`, preventing full tire sizes like
  `265/35ZR21` from being softened into `R21`.

Why it mattered:

- A generic exact-size value ladder can legitimately return Michelin,
  BFGoodrich, Kinto, Fronway, or other options. If an explicit customer brand
  such as Yokohama is sent as only a soft preference, the model and product
  presentation can omit the requested brand while still answering as though
  alternatives are acceptable. The fix keeps interpretation model-led but makes
  the tool contract non-optional for explicit brand asks.
- Known-brand-but-not-that-size cases need the same treatment: the tool result
  must tell the model that the requested brand is missing for the exact
  size/filter set, while still allowing useful same-size alternatives instead
  of an empty answer.

Validation:

- `python -m pytest test/test_runtime_v7_product_search_runner.py -q`
  -> `83 passed`.
- Focused model-contract/background-signal/card regression slice
  -> `9 passed`.
- Local seven-scenario live matrix
  `tmp/runtime_v7_brand_availability_live_probe_matrix_final_v2/runtime_v7_live_pack_20260628_210455/summary.json`
  -> zero explicit-brand contract failures; all product-search scenarios kept
  product-card insertion enabled.
- Full local Runtime V7 suite
  `$files = rg --files test | rg "test_runtime_v7"; python -m pytest $files -q`
  -> `659 passed`.

### 2026-07-09: VM Cloud SQL Parity Compare Hardening

What changed:

- Runtime V7 ManyChat Cloud SQL compare summaries now ignore runtime-local
  synthetic assistant ids such as `assistant_evt_*` when measuring whether
  Cloud SQL contains ManyChat history rows.
- Numeric ManyChat message-id gaps and current inbound message gaps still
  remain visible as `current_missing_in_cloudsql` or `partial`.
- Postgres analytics JSON fields are now coerced according to the analytics
  schema, so compact scalar strings in JSON columns are written as valid JSONB
  values instead of failing `runtime_shadow.turn_trace_log` writes.

Why it mattered:

- Phase 2I compare logs mixed true ManyChat coverage gaps with messages that
  only exist in the runtime cache. Separating those cases keeps the read-flip
  gate strict without overstating Cloud SQL misses.
- Cloud SQL analytics parity needs to stay durable while BigQuery remains the
  fallback reporting sink.

Validation:

- `python -m pytest test/test_analytics_gateway.py test/test_manychat_cloudsql_reader.py -q`
  -> `15 passed`.
- `python -m pytest $(rg --files test | rg 'test_runtime_v7') -q`
  -> `650 passed`.
- VM candidate and live return-only smokes passed, with BigQuery and Cloud SQL
  runtime analytics rows matching for `req_81818f891a5244b8b3f35af13701a201`.
- Post-swap VM logs showed zero Postgres analytics write failures. Cloud SQL
  ManyChat reads remain compare-only until numeric message coverage is stable.

### 2026-07-09: VM Runtime Analytics Append-Only Cost Hardening

What changed:

- Runtime analytics BigQuery writes now keep stable `row_id` values but omit
  `key_columns` when enqueued through `BigQueryAnalyticsGateway`.
- The VM dual-writer path remains intact, so BigQuery keeps receiving runtime
  analytics logs while Cloud SQL continues mirroring the same rows into
  `runtime_shadow`.

Why it mattered:

- Passing `key_columns=["row_id"]` made the BigQuery writer stage runtime log
  rows and issue request-time `MERGE` jobs. Runtime observability tables are
  append audit logs, so dedupe/latest-row semantics should be handled
  downstream instead of inside the request worker.

Validation:

- `python -m pytest test/test_analytics_gateway.py test/test_runtime_v7_ingress_trace.py -q`
  -> `41 passed`.
- `python -m pytest test -q`
  -> `665 passed`.

### 2026-06-27: VM + Cloud SQL Runtime Shadow Readiness

What changed:

- Added optional Postgres-backed runtime session and idempotency stores for the
  Compute Engine + Cloud SQL shadow path.
- Added environment-variable provider selection so Cloud Run remains on
  Firestore by default while the VM can opt into Cloud SQL state.
- Added a pre-canary shadow runbook with return-only delivery, no tag writes,
  Cloud SQL table expectations, and reversion boundaries.

Why it mattered:

- Runtime canary testing needs a durable state path on the VM without mixing
  the same user across Cloud Run/Firestore and VM/Cloud SQL. Keeping the
  provider opt-in protects current Cloud Run behavior while allowing the VM
  path to be tested before live traffic movement.

Validation:

- Added focused config/factory tests for Firestore defaults, Postgres opt-in,
  DSN validation, idempotency provider selection, and identifier safety.

### 2026-06-26: Background Signal Fail-Open Guard

What changed:

- Runtime V7 Background Signal extraction now degrades to empty advisory
  model candidates plus structured context after exhausted model retries,
  instead of raising out of the turn.
- Degraded extraction metadata records status, retry errors, attempt count,
  and the `model_extraction_failed_after_retries` reason for turn-trace and
  BigQuery diagnosis.

Why it mattered:

- Background Signals are advisory context. Gemini/LiteLLM transport failures in
  that component should not prevent the main orchestrator and composer from
  producing a safe customer reply.

Validation:

- Added a focused regression for repeated background extractor failures that
  confirms the turn can continue with degraded extraction diagnostics.

### 2026-06-19: Premium-First Size Ladder With Soft Preferred Brands

What changed:

- Runtime V7 exact-size product presentation now treats non-empty
  `preferred_brands` as soft ranking context, not as a hard brand constraint.
- Broad size-only quote/list requests keep the Premium-first price ladder and
  can expand from three cards to four when Premium, Mid Range, Economy, and
  Budget categories are available.
- Preferred brands still choose representative products within each price tier,
  except the Premium tier still prefers Michelin when available. Hard explicit
  brand constraints such as `required_brands` bypass that Michelin preference.
  The cross-category preferred-brand reshuffle is skipped for broad size
  ladders.

Why it mattered:

- Remembered/default preferred brands from conversation state could previously
  make a broad exact-size request look brand-constrained. When only three cards
  were shown, the low-to-high fallback order could omit Premium even though
  Premium exact-size products were available.

Validation:

- `python -m pytest test/test_runtime_v7_product_observation_harness.py::test_product_search_size_ladder_keeps_premium_first_with_soft_preferred_brands -q`
  -> covered by the focused product-ladder regression slice.
- `python -m pytest test/test_runtime_v7_product_observation_harness.py::test_product_search_size_ladder_keeps_premium_first_with_soft_preferred_brands test/test_runtime_v7_product_observation_harness.py::test_product_search_size_ladder_keeps_explicit_premium_brand_request -q`
  -> `2 passed`.
- `python -m pytest $files -q` where
  `$files = rg --files test | rg "test_runtime_v7"` -> `646 passed`.

### 2026-06-14: Lead CTA, Follow-Up Goal, And Handoff Notes

What changed:

- Runtime V7 now computes a shared `lead_cta_focus` after lead qualification.
  When tire size and brand/product context are known but location is missing,
  the final composer sees a business goal to softly progress from quote/options
  into city/barangay for installation availability. It does not receive a
  hardcoded customer-facing sentence.
- Product quote CTAs keep product selection valid, but location/service
  qualification becomes the preferred next lead field unless the customer
  explicitly asks to choose or compare products.
- The follow-up endpoint now has deterministic Last Interaction gates:
  latest-customer triggers recover through normal V7 chat up to 24 hours,
  latest-assistant proactive nudges are allowed only from 45 minutes to
  3 hours, human-agent takeover and hard-stop/order-complete states suppress,
  and duplicate same-context sends are suppressed.
- Follow-up composition now receives a binding
  `deterministic_followup_goal`. For missing location, the composer is asked to
  write a light one-hour nudge for city/barangay/area and is explicitly told
  not to ask again for tire size, brand, or product choice.
- Newly applied Moderate/High Intent tags create a ManyChat `createNote`
  handoff note with customer context, latest customer message, human-readable
  Asia/Manila timestamp, still-needed fields, suggested next reply, and a High
  Intent reason when applicable.
- Follow-up age checks normalize timezone-aware timestamps to Asia/Manila
  before comparing against runtime request time.

Why it mattered:

- Jeanel Co-assigned conversations often already have tire size and brand by
  quote time; location is the higher-leverage missing lead field needed to move
  toward installation partner/service qualification.
- Last Interaction follow-ups need to be safe enough for a one-hour ManyChat
  trigger while still recovering if the original real-time chatbot reply failed.
- Human agents need a quick narrative handoff after Moderate/High Intent so the
  receiving agent can continue the exact lead journey without re-reading the
  whole thread.

Validation:

- Focused local Runtime V7 tests:
  `python -m pytest test/test_runtime_v7_followup_endpoint.py test/test_runtime_v7_lead_tagging.py test/test_runtime_v7_channel_renderer.py -q`
  -> `69 passed`.
- Staging release `478541b` passed quote CTA, 60-minute missing-location
  follow-up, and too-early suppression probes with artifact
  `tmp/runtime_v7_staging_soft_cta_478541b/summary.json`.
- Live promotion `ff0e53c` deployed to
  `gulong-chatbot-runtime-live-00017-cj9`; return-only live probe artifact
  `tmp/runtime_v7_live_soft_cta_ff0e53c/final_summary.json` passed quote CTA,
  60-minute missing-location follow-up, and too-early suppression.

### 2026-06-09: Installation Partner Presentation Hardening

What changed:

- Runtime V7 no longer treats area-only `find_installation_partners` cards as
  customer-facing render surfaces when the lookup recommends
  `find_installation_slots`.
- Anonymous rows such as `Installation partner option 1 - Pasig area` remain
  internal coverage proof, but the compact tool result marks them suppressed so
  the final response can move toward grouped nearby slot availability instead
  of asking the customer to choose hidden partners.
- If the model tries to finalize after only a hidden partner lookup, the harness
  performs one forced `find_installation_slots` retry and drops stale
  partner-choice CTAs once slot cards are rendered.
- Exact slot cards from `find_installation_slots` are unchanged and continue to
  render grouped schedule lines without revealing partner names early.

Why it mattered:

- Live Moderate Intent review showed the anonymous partner-card format was one
  of the most common customer-facing quality issues: it hides the useful branch
  name/address while also failing to provide actionable schedules.

Validation:

- `python -m pytest test/test_runtime_v7_service_slot_first.py test/test_runtime_v7_product_observation_harness.py::test_runtime_v7_harness_defers_service_presentation_retry_to_final_composer_when_available test/test_runtime_v7_product_observation_harness.py::test_runtime_final_response_uses_model_generated_service_cta_with_partner_cards test/test_runtime_v7_product_observation_harness.py::test_runtime_final_response_preserves_safe_three_paragraph_service_reply_with_cards test/test_runtime_v7_product_observation_harness.py::test_runtime_final_response_uses_singular_cta_for_single_installation_partner_card test/test_runtime_v7_product_observation_harness.py::test_final_composer_marks_partner_lookup_as_slots_not_checked test/test_runtime_v7_product_observation_harness.py::test_structured_service_text_is_not_phrase_mutated_without_slot_grounding -q`
  -> `8 passed`.
- `python -m pytest test/test_runtime_v7_product_observation_harness.py -k "installation_partner or installation_slots or service_card or slot or service_slot" -q`
  -> `51 passed, 388 deselected`.
- `python -m pytest test -q`
  -> `617 passed`.

### 2026-06-05: Staging Probe Hardening

What changed:

- `extract_compatible_fitment` now enforces explicit rim-size clues when the
  compatible-size catalog has at least one matching candidate, so an `Innova
  rim 15` request no longer returns R16/R17/R18 candidates beside the R15 match.
- Background Signal repair now recognizes spaced `3 + 1` promo wording and
  removes a stale remembered quantity when the latest turn introduces Buy 3 Get
  1 without explicitly repeating the old quantity.
- The local Runtime V7 harness now carries a session flag for product
  inclusions and suppresses repeat `Warranty and inclusions` blocks after the
  first product presentation in a scenario.
- The API/channel boundary captures the product-inclusions session flag before
  the harness runs, so the harness can update durable state during composition
  without hiding the first visible inclusions bubble in deployed endpoint
  responses.
- The live model probe pack expectation for direct `hm 175 65 14` now reflects
  current product-card behavior: `product_search` is allowed on the first turn
  when the tire size is complete and the customer is asking for price/options.

Why it mattered:

- The staging probe pack exposed cross-layer inconsistencies where candidate
  fitment sizes, stale BSE quantity, and repeated renderer blocks could diverge
  from the customer-visible flow.
- These fixes keep canonical fitment/product facts tighter before deployment
  without adding response stripping or model-only assumptions.

Validation:

- Targeted hardening slice -> `8 passed`.
- Broader Runtime V7 product/search/channel/trace slice -> `557 passed`.
- Full local suite -> `609 passed`.
- High-priority live multi-turn harness pack `mt01`-`mt04` completed without
  aborts and confirmed R15-only Innova candidates, Buy 3 Get 1
  `quantity=4`/promo tool args, and one inclusions block per local session.
- 9-scenario first-turn live harness pack completed without aborts.
- API ordering regression for first visible product inclusions -> focused slice
  `5 passed`.

### 2026-06-04: Proactive Follow-Up Endpoint

What changed:

- Added `POST /gulong/v7/followup` as a separate Runtime V7 API path.
- The endpoint loads recent conversation and durable state, uses a lightweight
  model to decide whether a follow-up is appropriate, uses a separate composer
  model to write one short message, and sends through the existing ManyChat
  delivery boundary.
- Follow-up attempts persist `strategy_state.runtime_v7.followup`, suppress
  repeat sends for the latest visible follow-up, reuse the late freshness check,
  and emit the same normalized debug, turn trace, turn fact, and LLM span logs
  as chat turns.
- Follow-up eligibility is sales-permissive: unanswered assistant/human-agent
  CTAs are valid candidates unless the customer already purchased, bought
  elsewhere, is irritated, opted out, explicitly said no, or the context is not
  actionable. Customer-last transcripts route into the full Runtime V7 chat path
  with a late-reply apology seed instead of proactive copy.
- Added deterministic follow-up policy polish: waiting-response suppressions can
  be overridden into sends when no hard stop signal is present, and composed
  messages are sanitized to remove product links/trailing generic thanks and add
  a friendly emoji when missing.
- Follow-up composer tone now follows the main Runtime V7 chatbot voice through
  compact context and tone guidance: concise casual Taglish when the thread uses
  Filipino/Taglish or `po`, with English `let me know` phrasing normalized into
  Gulong-style Taglish.
- Follow-up copy now treats proactive sends as non-pricing surfaces: composer
  context, debug decision/composer fields, and the durable follow-up ledger
  redact pricing/promo terms, customer output sanitization removes unbacked
  pricing/promo clauses, and invalid composer output falls back to a safe
  no-pricing Taglish follow-up.
- Follow-up context now includes a `normalized_entities` projection through the
  central Runtime V7 signal/entity normalizer, so typo variants in recent
  transcript text are replaced with canonical display values in composer-facing
  context. Composer guidance and fallback copy also require a concrete
  reply/action CTA instead of neutral check-in wording.

Why it mattered:

- Proactive follow-ups can now be evaluated and sent without running the full
  product/service/order tool loop or treating a scheduler trigger as a customer
  message.

### 2026-05-20: Product Discovery And Model-Owned Signals

Commits:

- `00685ea feat(runtime-v7): add fitment discovery and model-owned signals`
- `e98542a Refine runtime v7 product signal handling`
- `c88b40b Add Runtime V7 brand discovery menu`
- `32bd0cd Guard Runtime V7 renderer-owned CTAs`
- `41e2e28 Steer V7 broad hm inquiries to brand menus`
- `8bb0052 Generalize V7 size-only brand menu guidance`
- `d36155f Add Runtime V7 image evidence intake`
- `46199fe Filter non-size OCR tokens from V7 image evidence`

What changed:

- Product search became the first working V7 slice.
- Fitment discovery was added for vehicle-only or rim-only cases where tire
  size needs candidate extraction before product search.
- Background-signal extraction moved toward model-primary interpretation.
- Brand menus and deterministic product cards were added as renderer surfaces.
- Image evidence intake began handling sidewall/product/order/payment-looking
  screenshots as unvalidated evidence.

Why it mattered:

- The early product slice proved the central design: the model interprets
  customer intent and chooses tools, while runtime owns exact product facts,
  refs, and card rendering.
- Discussions around budget/category confusion and keyword extraction led to a
  durable rule: do not restore deterministic raw-message commercial extraction.

### 2026-05-21 to 2026-05-22: Evidence Intake, Capability Profiles, And Service Foundation

Commits:

- `4f40c5a Add Runtime V7 human-agent conversation hydration`
- `b5873cf Add Runtime V7 joined evidence intake`
- `d877370 Add Runtime V7 capability profile scaffold`
- `d68f4d9 Add Runtime V7 service FAQ capability`
- `9b9960c Add Runtime V7 installation partner lookup`
- `611cd30 Add Runtime V7 service slot presentation and compatibility`
- `8442255 Advance Runtime V7 tool-loop grounding`
- `4bd9d15 Document Runtime V7 tool-loop grounding`

What changed:

- Human-agent/channel conversation evidence could be hydrated into the harness.
- Pre-turn evidence intake became joined instead of fire-and-forget.
- Capability profiles started selecting tool surfaces from signals,
  observations, readiness, and domain context.
- Service FAQ, partner lookup, slot lookup, slot presentation, and compatibility
  checks were introduced.

Why it mattered:

- Cross-turn feasibility required more than latest-user-message extraction.
  V7 needed AWM, signals, human-agent history, product observations, and service
  observations available before the model call.
- Service introduced the first major disclosure problem: customers can drop off
  when exact partner names/addresses are shown too early. This produced the
  staged partner-disclosure decision.

### 2026-05-24 to 2026-05-26: Product/Service Hardening And Order Readiness

Commits:

- `261b36a Harden Runtime V7 evidence and service flow`
- `ee0c0c2 Add Runtime V7 live probe pack`
- `ee45604 Stabilize Runtime V7 product service foundation`
- `88d9b7f Add Runtime V7 order readiness scaffolding`

What changed:

- The live probe pack was introduced for focused multi-turn validation.
- Product/service state became more stable around observations, refs, and
  presentation surfaces.
- Order readiness was added as a structured state surface rather than forcing
  order intent into Background Signals or AWM.

Why it mattered:

- Probe review showed that tool exposure, AWM, Background Signals, readiness,
  and observations can conflict if they are not clearly separated.
- Order readiness became the place for order-progress facts and missing fields,
  while AWM stayed descriptive and Background Signals stayed advisory.

### 2026-05-27: Order Quote, Lead Qualification, And Cross-Turn Review

Commits:

- `8111fe4 Add Runtime V7 order quote flow`
- `039b85f Refine Runtime V7 product service review flows`
- `69757e1 Add Runtime V7 lead qualification tagging`
- `7a6b5db Harden Runtime V7 cache and signal carryover`
- `77c31a4 Harden Runtime V7 cross-turn service and fitment flow`

What changed:

- Read-only quote math and order summary review flow were added.
- Lead qualification became incomplete/complete, with complete mapping to
  Moderate Intent.
- Passive tags were added for Moderate Intent, High Intent, Irate, Chatbot
  Error, Order Booked, Website Inquiry, and related flow outcomes.
- Cross-turn carry-forward for location, selected products, and service context
  was hardened.

Why it mattered:

- Common new-customer turns often only collect tire size, brand, location, and
  contact number. The fast lead lane exists to avoid expensive full tool-loop
  calls when the turn only needs intake progress.
- Review also showed the risk of stale soft preferences being hydrated into
  service/order tools as if the customer selected a SKU. That drove stricter
  selected-product carry-forward rules.

### 2026-05-28 to 2026-05-30: Product/Service Matching, Composer Boundaries, And Payment Foundation

Commits:

- `3b3c784 Harden Runtime V7 product and service matching`
- `4eaf2c2 Add Runtime V7 order payload and composer boundaries`
- `18e86a2 Add Runtime V7 reasoning controls to live probes`
- `2e93503 Add Runtime V7 payment request flow`
- `6d3fc51 Harden Runtime V7 payment follow-ups`
- `c649776 Fix Runtime V7 fresh probe routing regressions`
- `153923e Harden Runtime V7 order and service flows`
- `44c2ef3 Harden Runtime V7 order payment flow`

What changed:

- The final composer response-unit boundary was introduced and hardened.
- `build_order_payload` became the API-ready validation boundary before submit.
- Payment request and payment-proof matching were added.
- Live probes gained reasoning-effort controls and thought-signature testing
  surfaces.
- Product/service matching rules were tightened around exact tire size, brand,
  pattern/model query, selected SKU, quantity, service feasibility, and slots.

Why it mattered:

- Runtime had legacy prose guards that were too mutating. The composer boundary
  moved response organization into structured model output while keeping exact
  cards/details renderer-owned.
- Payment/order side effects needed a hard boundary: summary is conversational,
  payload build validates submit readiness, submit posts only validated payload
  refs, and payment request follows submitted order context.

### 2026-05-31 to 2026-06-01: Checkout, API Packaging, And Adaptive Probes

Commits:

- `7338439 Add Runtime V7 checkout payment hardening`
- `0129ac3 Package Runtime V7 API order payment flow`
- `2b317c7 Add Runtime V7 adaptive conversation probes`

What changed:

- Payment canonicalization, delivery/payment policy, installment handling, and
  order/payment renderer formatting were hardened.
- `/gulong/v7/chat` and `/gulong/v7/chat/tester` were packaged through
  `RuntimeV7APIService`.
- Adaptive probes simulated more realistic uncertain customers instead of only
  predetermined script turns.

Why it mattered:

- Static scripts can become incoherent when the chatbot asks a different next
  question. Adaptive probes better expose whether the assistant can carry a
  customer from uncertainty to product choice, fulfillment, order summary,
  submit, and payment request.
- Payment formatting had to be channel-friendly: exact details still need a
  deterministic renderer, but the grouping must be readable in Messenger.

### 2026-06-02: ManyChat Ingress Hydration And Documentation System

Commits:

- `8c20465 Harden Runtime V7 ManyChat ingress hydration`
- `beafed5 Document Runtime V7 architecture and update rules`

What changed:

- API ingress gained V7-owned ManyChat history loading, channel-history cache,
  reset/stale-gap segmentation, resolved message id replay, and version-neutral
  turn traces.
- Runtime V7 gained a local `AGENTS.md`, documentation index, architecture doc,
  component map, and decisions/gaps ledger.

Why it mattered:

- Live ManyChat external HTTP triggers do not provide the full event identity
  we want. V7 therefore derives message identity from loaded/cache channel
  history when possible and falls back safely when not possible.
- History hydration must include prior human-agent/customer context without
  reviving stale conversations. Reset and adjacent-message age gaps now define
  the active segment.
- Documentation had become scattered across implementation notes, probe
  summaries, and discussions. The new docs system gives future changes a clear
  place to update decisions, component ownership, gaps, and validation status.

### 2026-06-02: API Trace Persistence, Session Locking, And Channel Safety

Commits:

- `da5cf39 Harden Runtime V7 API trace delivery`

What changed:

- `/gulong/v7/chat` now wires the analytics gateway into `RuntimeV7APIService`
  when analytics saving is enabled.
- V7 API turns now enqueue a full debug trace payload with request metadata,
  version-neutral turn trace, full turn record, rendered response, delivery
  result, and tagging result.
- The API emits a compact searchable `runtime_v7_turn_trace` Cloud Logging
  line for request/session/trace lookup.
- Follow-up durability hardening flushes normalized BigQuery rows immediately
  after enqueue for `request_state_log`, `request_attempt_log`,
  `turn_trace_log`, `turn_fact_log`, `llm_span_log`, and `tool_call_log`,
  matching the existing `debug_log` flush behavior.
- Session storage and gateway layers now support short active-turn locks and
  owner-checked release.
- API turn handling now uses per-session locking, CAS save, and pre-delivery
  ManyChat freshness checks. Stale responses are suppressed if a newer user or
  human-agent message is visible before delivery.
- Final composer and channel rendering now enforce plain ManyChat-safe text:
  emojis are allowed, while HTML and Markdown formatting are stripped or
  converted.

Why it mattered:

- Live verification showed the returned trace was useful but not durable in
  BigQuery or app logs. Debug trace persistence makes bad turns diagnosable
  after the HTTP caller has returned.
- Overlapping direct API and ManyChat-triggered turns can otherwise overwrite
  session state or deliver stale responses. Locking, CAS save, and freshness
  suppression reduce that risk without introducing business-intent rules.
- Messenger formatting must stay readable and plain. Model-authored Markdown
  and HTML should not leak into customer bubbles.

Validation:

- `pytest test/test_runtime_v7_channel_renderer.py test/test_runtime_v7_ingress_trace.py -q`
- `pytest $(rg --files test | rg "test_runtime_v7") -q`

Follow-up gap:

- Deploy and validate one live delivered turn with a BigQuery debug-log row and
  a searchable Cloud Logging app line.
- Decide later whether the debug payload should be promoted into a flatter
  normalized runtime-turn schema.

### 2026-06-02: API Order Ingress Edge Hardening

Commits:

- `Harden Runtime V7 API order ingress edges` commit group

What changed:

- Session-lock-busy requests now return an explicit non-success runtime status
  and persist a skipped-turn debug trace when analytics is configured.
- API debug tool summaries now expose raw tool status and model-visible compact
  status separately.
- Order tools normalize structured model-emitted aliases such as
  `customer_email`, `customer_first_name`, slot date/time fields, and checkout
  payment metadata IDs before order validation.
- Order policy now tells the model to pass customer-facing payment labels, not
  internal checkout IDs.
- Order FAQ retrieval suppresses the leave-a-review/feedback FAQ when "review"
  refers to reviewing an order summary.

Why it mattered:

- Returning empty `success` on session-lock busy can hide dropped overlapping
  turns. The runtime should surface an explicit retry-later state and leave
  production evidence.
- Order-summary probes showed the model can emit reasonable structured aliases
  even when schemas prefer canonical keys. The tool boundary should accept
  equivalent structured data without parsing raw customer text or inventing
  missing choices.
- FAQ keyword overlap can look like intent when the customer is actually moving
  through an order review. FAQ disambiguation belongs in retrieval, not in the
  main order-intent path.

Validation:

- `pytest test/test_runtime_v7_ingress_trace.py test/test_runtime_v7_product_observation_harness.py -q`
  -> `396 passed`
- `pytest $(rg --files test | rg "test_runtime_v7") -q`
  -> `495 passed`

### 2026-06-02 to 2026-06-03: Persona Probe Iteration - Payment Terms, Order Details, And Payment Request Grounding

Commits:

- `86d15f0 Iterate Runtime V7 persona order flow fixes`
- 2026-06-03 order/payment persona hardening patch group.

What changed:

- Persona probe caps were raised for cap-hit scenarios so adaptive customer
  runs can reach order/payment endpoints when the conversation is naturally
  longer.
- Background Signal extraction and signal ordering now include order-payment
  `bank` and `installment_months` as first-class advisory facts.
- Order readiness, summary, payload build, and payment request boundaries now
  preserve canonical installment selections such as
  `Credit card installment (BPI 6 months)`.
- `build_order_payload` now rejects generic Pay Now installment selections
  when bank or installment term is still missing.
- Order payload name parsing now recovers missing `last_name` from
  `customer_name` when the model also passes only `first_name`.
- Final composer service grounding now receives
  `service_lookup_state=no_service_tool_result_this_turn` when no service tool
  ran, and prompt policy tells the composer to discard draft service
  availability/unavailability claims that are not grounded by service tools.
- Delivery order summaries now require complete delivery address during active
  order detail collection instead of accepting broad city/area location as
  submit-ready.
- Installation and delivery summaries now align with payload requirements for
  first name, last name, and email when order-detail collection is active.
- Pay Later + COD delivery now treats COD as the remaining balance method, not
  as the reservation/downpayment method. Reservation fee still needs an upfront
  method such as GCash or online banking.
- Order policy now tells the model that product-card effective totals already
  include promos; do not subtract the same promo again. Promo-math disputes
  should use visible card totals or `calculate_order_quote`.
- `build_order_summary` now exposes `can_build_order_payload` and
  `recommended_next_tool=build_order_payload` when summary state is ready, so
  the model can progress without another clarification loop.
- `build_order_payload` exposure is gated for installation/service paths until
  there is a validated service slot. A selected product and summary are not
  enough for service submit readiness.
- `submit_order` and `prepare_payment_request` now surface backend amount
  mismatches between validated payload totals and `/order` or `/order_details`
  readback. Payment requests use backend readback amount when available and
  render a verification note if it differs from the earlier payload.
- Structured final text cleanup now converts adjacent plain bullets such as
  `- Full Name- Contact Number- Email Address` back into line-separated
  bullets without rewriting meaning.

Why it mattered:

- P08-style adaptive runs were hitting the turn cap because BPI installment
  stayed as raw `installment`, causing repeated payment FAQ loops instead of
  summary/payload/payment progression.
- The model could produce a valid order summary with `Name: Carlo Test`, then
  call `build_order_payload` with `first_name=Carlo` and no `last_name`; the
  payload boundary incorrectly treated the last name as missing.
- Product-search turns with a location could claim installation availability
  without calling service tools. The new composer state keeps this model-led
  but grounded: either call service tools or acknowledge the area for later
  lookup.
- P07 delivery flows showed that delivery/address/payment readiness must use
  the same required-field boundary as `build_order_payload`; otherwise the
  model can present an order summary that cannot submit.
- P09 website/promo math showed that visible effective totals are already
  customer-facing order totals after promo. Double-discounting caused wrong
  summaries and customer confusion.
- Live order APIs exposed a final amount that differed from V7's validated
  payload by `PHP 120.00` in sale-tag cases. V7 should not hide true drift:
  payment instructions must reflect the backend amount and show the difference
  for operator/customer verification. The later checkout sale-pricing patch
  below fixes the known sale-tag source of this drift locally.
- Service orders need a validated slot before payload build. Without that
  boundary, the model could move from area/slot discussion into payload build
  before the customer's selected schedule was validated.

Validation:

- `pytest test\test_runtime_v7_product_observation_harness.py::test_build_order_payload_recovers_missing_last_name_from_customer_name test\test_runtime_v7_product_observation_harness.py::test_build_order_payload_merges_pay_now_bpi_installment_without_reservation_conflict test\test_runtime_v7_product_observation_harness.py::test_build_order_payload_requires_installment_bank_and_term_for_pay_now_installment test\test_runtime_v7_product_observation_harness.py::test_build_order_summary_snapshot_persists_canonical_payment_selection -q`
  -> `4 passed`
- `pytest test\test_runtime_v7_product_observation_harness.py::test_final_composer_service_action_state_blocks_service_claims_without_service_tool test\test_runtime_v7_product_observation_harness.py::test_final_composer_payload_prioritizes_read_only_slot_action_state_over_draft test\test_runtime_v7_product_observation_harness.py::test_build_order_payload_recovers_missing_last_name_from_customer_name test\test_runtime_v7_product_observation_harness.py::test_build_order_summary_snapshot_persists_canonical_payment_selection -q`
  -> `4 passed`
- Targeted P08 payment rerun:
  `tmp/runtime_v7_persona_research/targeted_p08_payment_terms_probe_v2.json`
  reached `payment_request` in 8 turns.
- Targeted P08 service-grounding rerun:
  `tmp/runtime_v7_persona_research/targeted_p08_service_grounding_probe.json`
  called `find_installation_partners` before stating installation partners
  exist.
- P06 urgent install to payment:
  `tmp/runtime_v7_persona_research/live_set_20260603_082432/runtime_v7_persona_live_set_findings.md`
  reached `payment_request_reached` in 9 turns.
- P07 delivery with privacy/refusal:
  `tmp/runtime_v7_persona_research/live_set_20260603_085857/runtime_v7_persona_live_set_findings.md`
  reached `payment_request_reached` in 12 turns.
- P08 installment-first to payment:
  `tmp/runtime_v7_persona_research/live_set_20260603_090637/runtime_v7_persona_live_set_findings.md`
  reached `payment_request_reached` in 12 turns.
- P09 website image/promo inquiry:
  `tmp/runtime_v7_persona_research/live_set_20260603_101230/runtime_v7_persona_live_set_findings.md`
  reached `payment_request_reached` in 12 turns and applied `Website Inquiry`,
  `Moderate Intent`, `High Intent`, and `Order Booked`.
- Fresh non-Apollo/non-BPI installation path:
  `tmp/runtime_v7_persona_research/live_set_20260603_102057/runtime_v7_persona_live_set_findings.md`
  reached `payment_request_reached` in 8 turns with Metrobank 3-month
  installment preserved through summary, payload, submit, and payment request.
- `pytest test\test_runtime_v7_product_observation_harness.py::test_structured_text_strips_html_list_markup_from_final_composer_output test\test_runtime_v7_product_observation_harness.py::test_structured_text_restores_adjacent_plain_bullet_line_breaks test\test_runtime_v7_product_observation_harness.py::test_capability_profile_exposes_order_domain_from_order_readiness test\test_runtime_v7_product_observation_harness.py::test_order_progress_expands_payload_schema_after_validated_slot test\test_runtime_v7_product_observation_harness.py::test_submit_order_surfaces_backend_total_mismatch test\test_runtime_v7_product_observation_harness.py::test_prepare_payment_request_prefers_order_details_total_after_submit -q`
  -> `6 passed`
- `pytest test\test_runtime_v7_product_observation_harness.py -q`
  -> `386 passed`
- `pytest (rg --files test | rg "test_runtime_v7") -q`
  -> `508 passed`

Follow-up gap:

- Area-only installation partner disclosure may still be too eager when the
  customer only provides location during product discovery. Decide whether
  product-first turns should preserve location for later instead of calling
  partner lookup immediately.
- Continue trimming long-turn context: the targeted payment rerun still cost
  about `$0.0748` and used 26 model calls over 8 turns.
- Backend amount drift, observed as a `+PHP 120.00` difference in P09/P15
  order readbacks, was later traced to checkout sale-tag pricing vs product-card
  display math. See the 2026-06-03 checkout sale-pricing section below.
- Continue auditing non-payment FAQ answers for fulfillment-specific wording.
  The order payment FAQ now accepts structured `service_type` /
  `fulfillment_path` context so installation/card contexts do not receive
  delivery-only wording.
- Continue live-probing summary timing around installation slots. V7 now treats
  raw `chosen_schedule_slot` values as preferences until
  `validate_installation_slot` grounds the slot, and readiness no longer
  exposes `build_order_summary` from an active install path while
  `Validated installation schedule` is still missing.

### 2026-06-03: Order FAQ Scoping And Validated Slot Summary Boundary

Commits:

- Pending commit: `Harden Runtime V7 order FAQ and slot summary gating`

What changed:

- `answer_order_faq` can now receive structured fulfillment context
  (`service_type` / `fulfillment_path`) and uses the V7 delivery/payment policy
  to scope the payment answer to installation, delivery, pickup, or home
  service.
- `build_order_readiness` distinguishes a customer's preferred installation
  schedule from a validated installation schedule. A raw BSE/background signal
  such as `chosen_schedule_slot` is advisory until the slot has been grounded
  by `validate_installation_slot`.
- `build_order_summary` no longer renders an unvalidated install/pickup
  schedule as a selected schedule. It marks `Validated installation schedule`
  missing and keeps the deterministic summary incomplete.
- Capability exposure blocks `build_order_summary` when readiness still lacks a
  validated installation schedule, preventing the model from advancing to order
  summary purely from preferred date/time text.

Why it mattered:

- Payment FAQs were leaking delivery-centric text into installation/card
  contexts because the FAQ answer did not know the fulfillment path.
- Install order summaries could look more complete than they were if the model
  or BSE carried a date/time string but no slot-validation tool had grounded it.

Validation:

- `pytest test\test_runtime_v7_product_observation_harness.py::test_build_order_summary_renders_deterministic_body_from_trusted_refs test\test_runtime_v7_product_observation_harness.py::test_build_order_summary_keeps_unvalidated_install_schedule_pending test\test_runtime_v7_product_observation_harness.py::test_order_faq_uses_v7_delivery_payment_policy_spiels test\test_runtime_v7_product_observation_harness.py::test_capability_profile_exposes_order_domain_from_order_readiness -q`
  -> `4 passed`
- `pytest test\test_runtime_v7_product_observation_harness.py -q`
  -> `387 passed`
- `pytest (rg --files test | rg "test_runtime_v7") -q`
  -> `509 passed`

Follow-up gap:

- Backend order-total drift needs live confirmation after the checkout
  sale-pricing patch is deployed.
- Live model probes should confirm the model now calls slot validation before
  presenting install summaries as ready.

### 2026-06-03: Backend Checkout Sale Pricing Alignment

Commits:

- Pending commit: `Align Runtime V7 checkout totals with backend sale pricing`

What changed:

- Order-facing total calculation now prefers backend-compatible checkout
  pricing for sale-tag products. For sale-tag carts, V7 uses the submitted
  checkout fields (`promo`, `srp`, `sale_tag`) and mirrors the backend/legacy
  formula (`promo_price * quantity`, minus the quantity discount when
  applicable) instead of reusing the product-card synthetic
  `product_discount_after_bundle` effective total.
- API-provided bundle tiers and Buy-3-Get-1 pricing still keep their existing
  precedence. The new sale-tag formula only replaces V7's locally generated
  product-discount-after-bundle card math at the order quote/payload boundary.
- `calculate_order_quote`, `build_order_summary`, and `build_order_payload`
  now surface the backend checkout subtotal as the authoritative order total.
  When the card-effective total differs, V7 records the card total and checkout
  adjustment as diagnostics so the composer/logs can explain the difference
  without changing deterministic product cards.

Why it mattered:

- P09 and a fresh non-Apollo/non-BPI install order both submitted valid payloads
  but backend readback totals were `PHP 120.00` higher than V7's pre-submit
  total. The repeated exact difference came from sale-tag checkout math, not a
  hidden installation/shipping/payment fee.
- Payment requests should not need to correct the amount after submit when the
  backend behavior is predictable from the submitted cart fields.

Validation:

- `pytest test\test_runtime_v7_product_observation_harness.py::test_order_quote_uses_backend_sale_tag_checkout_total_not_card_effective_total test\test_runtime_v7_product_observation_harness.py::test_build_order_payload_uses_backend_sale_tag_checkout_total_for_submit test\test_runtime_v7_product_observation_harness.py::test_submit_order_surfaces_backend_total_mismatch test\test_runtime_v7_product_observation_harness.py::test_prepare_payment_request_prefers_order_details_total_after_submit -q`
  -> `4 passed`
- `pytest test\test_runtime_v7_product_observation_harness.py -q`
  -> `389 passed`
- `pytest (rg --files test | rg "test_runtime_v7") -q`
  -> `511 passed`

Follow-up gap:

- Deploy and submit one fresh sale-tag test order, then compare V7 payload,
  `/order`, `/order_details`, and backend UI totals. Keep backend-readback
  mismatch surfacing for any true drift outside this sale-tag case.

### 2026-06-03: Buy 3 Get 1 Card Pricing Clarity

Commits:

- `Clarify Runtime V7 Buy 3 Get 1 card pricing`

What changed:

- Buy 3 Get 1 product cards now render the actual paid unit price first, then
  the payable total for four tires. The renderer no longer leads with an
  amortized `effective/tire` comparison for 3+1 cards.
- Product policy now tells the final composer to explain 3+1 as paid-tire
  price times three, with the fourth tire free, when customers question promo
  math.

Why it mattered:

- A live customer read `PHP 8,418.75 effective per tire` as the unit amount to
  multiply by three for a Michelin 3+1 promo. The math was correct, but the
  card presentation created avoidable confusion.

Validation:

- `pytest test/test_runtime_v7_product_search_runner.py -q`
  -> `74 passed`
- `pytest test/test_runtime_v7_lead_tagging.py::test_fitment_prompts_avoid_year_and_perfect_fit_claims -q`
  -> `1 passed`

### 2026-06-03: Bare Price-Inquiry Tone Guidance

Commits:

- Pending commit: `Tighten Runtime V7 bare price inquiry guidance`

What changed:

- Product policy now explicitly treats short messages such as `hm`, `hm po`,
  `magkano`, and `how much` as price-check requests with missing tire context.
- Fast lead-triage seeds now tell the model to acknowledge price checking and
  ask for tire size directly, instead of using unclear wording like "para saan
  po yan".

Why it mattered:

- Live V7 turns showed the model asking "Para saan po yan?" for bare or partial
  price inquiries such as `hm` and `HM 265`. The model understood that context
  was missing, but the wording made a normal price inquiry sound ambiguous.

Validation:

- `pytest test/test_runtime_v7_product_observation_harness.py::test_model_contract_hides_generic_requires_validation_from_model_context test/test_runtime_v7_product_observation_harness.py::test_response_seeds_steer_bare_price_inquiry_to_size_question test/test_runtime_v7_product_observation_harness.py::test_response_seeds_support_generic_first_question_and_incomplete_lead -q`
  -> `3 passed`
- `pytest test/test_runtime_v7_lead_tagging.py -q`
  -> `16 passed`
- `pytest test/test_runtime_v7_product_observation_harness.py -q`
  -> `396 passed`

### 2026-06-03: Mitsubishi G4 Fitment And Nitrogen Add-On FAQ

Commits:

- Pending commit: `Harden Runtime V7 fitment aliases and service add-on FAQ`

What changed:

- `extract_compatible_fitment` now prefers structured `car_make` plus
  `car_model` over raw `vehicle_query` when both are present, while still
  preserving raw customer text for trace/debug.
- The fitment boundary maps common Mitsubishi G4 shorthand, such as `GLS G4`,
  to the compatibility endpoint model name `Mirage G4`.
- Product FAQ now has a V7-owned run-flat/no-flat concept answer with a
  SKU-specific caveat instead of accidentally routing the question to the
  sidewall-size FAQ.
- Service FAQ now has a V7-owned nitrogen inflation answer, framed as an
  add-on/inflation service distinct from run-flat/no-flat tire technology.
- Product FAQ now suppresses nitrogen questions so unrelated warranty chunks
  that merely mention nitrogen are not returned.
- Product and service policies now tell the model to answer run-flat/no-flat
  from visible product details first, then switch to service/add-on reasoning
  when the customer clarifies they mean nitrogen.

Why it mattered:

- A live `Hm for GLS G4 mitsubishi` turn called the fitment tool but received no
  candidate sizes because the upstream compatibility endpoint recognizes
  `Mitsubishi Mirage G4`, not customer shorthand such as `GLS G4`.
- A live no-flat/nitrogen follow-up retrieved the wrong product FAQ first and
  then produced a weak clarification instead of explaining that nitrogen is an
  add-on service and not the same as run-flat tire technology.

Validation:

- `pytest test/test_runtime_v7_product_observation_harness.py::test_extract_compatible_fitment_maps_mitsubishi_g4_shorthand_to_mirage_g4 test/test_runtime_v7_product_observation_harness.py::test_answer_service_faq_covers_nitrogen_as_addon_not_run_flat test/test_runtime_v7_product_observation_harness.py::test_answer_product_faq_explains_run_flat_without_claiming_specific_sku_feature test/test_runtime_v7_product_observation_harness.py::test_model_contract_hides_generic_requires_validation_from_model_context test/test_runtime_v7_product_observation_harness.py::test_response_seeds_steer_bare_price_inquiry_to_size_question -q`
  -> `5 passed`
- `pytest test/test_runtime_v7_product_observation_harness.py::test_answer_service_faq_covers_nitrogen_as_addon_not_run_flat test/test_runtime_v7_product_observation_harness.py::test_answer_product_faq_explains_run_flat_without_claiming_specific_sku_feature test/test_runtime_v7_product_observation_harness.py::test_answer_product_faq_does_not_answer_nitrogen_from_unrelated_warranty_docs -q`
  -> `3 passed`

### 2026-06-04: Generic Location Response Shape

Commits:

- Pending commit: `Tighten Runtime V7 generic location triage response`

What changed:

- Exact automated `Where are you located` turns now use a direct business
  location/serviceability response that says Gulong.ph is online, has 100+
  installation partners across Metro Manila, CALABARZON, Pampanga, and
  Bulacan, includes free mounting/balancing/weights/valves, and requires
  reservation/booking because fresh warehouse stocks are sent to the partner
  after reservation.
- Free-text generic location questions, including `location po`, stay in the
  full Runtime V7 path and receive a high-priority response seed that tells the
  model to answer directly first, preserve paragraph breaks, include the
  reservation/fresh-stock sentence, and avoid asking "Para saan po ang
  location?".
- The exact automated location response also accepts the no-question-mark
  `Where are you located` text variant.

Why it mattered:

- Live ManyChat examples showed the prior V7 response asking "Para saan po ang
  location na hinahanap niyo?", which is less natural than repeated human-agent
  spiels that answer the business location/serviceability question first, then
  ask for the customer's city/barangay/landmark.
- This keeps generic location answers conversion-oriented without revealing
  exact installation partner names or addresses before the approved disclosure
  stage.

Validation:

- `pytest test/test_runtime_v7_lead_tagging.py::test_runtime_answers_exact_automated_button_without_model_call test/test_runtime_v7_lead_tagging.py::test_runtime_answers_location_button_alias_without_question_mark test/test_runtime_v7_lead_tagging.py::test_runtime_routes_pure_location_po_to_full_runtime_seed test/test_runtime_v7_product_observation_harness.py::test_response_seeds_support_generic_first_question_and_incomplete_lead test/test_runtime_v7_product_observation_harness.py::test_response_seeds_preserve_mixed_location_and_product_context -q`
  -> `5 passed`
- `pytest $(rg --files test | rg "test_runtime_v7") -q`
  -> `532 passed`
- Live probe:
  `python scripts/runtime_v7_live_test_pack.py --pack tmp\runtime_v7_location_live_probe_pack.json --mode live --scenario loc02_generic_location_po --scenario loc03_mixed_location_product --memory-generator heuristic --background-signal-generator hybrid-live --background-signal-policy auto --image-evidence-generator none --max-model-calls-per-turn 8 --max-model-calls-per-scenario 16 --max-model-calls-per-run 32 --out-dir tmp\runtime_v7_location_live_probe_seeded`
  -> `tmp/runtime_v7_location_live_probe_seeded/runtime_v7_live_pack_20260604_140157/summary.md`

### 2026-06-04: Generic Price And Location Response Guard

Commits:

- Pending commit: `Guard Runtime V7 generic price and location wording`

What changed:

- Free-text price and location turns remain model-led. Runtime V7 does not add
  a deterministic intent classifier for broad customer text such as `how much`,
  `hm`, `magkano`, or `location po`.
- Response seeds now make bare price questions a high-priority composition
  hint and explicitly tell the model not to frame the shorthand as unclear.
- The final response guard removes prohibited clarification phrasing such as
  `Para saan po 'yan?`, `Para saan po pala, ...`, `Para saan po yung price?`,
  or `Para saan po ang location?` from model output while preserving the
  model's remaining answer. It also rewrites weak generated prefixes such as
  `Para sa anong tire size` into direct tire-size questions.
- Exact automated ManyChat button/postback responses remain deterministic;
  free-text variants continue through model-led lead qualification or the full
  Runtime V7 path depending on context.

Why it mattered:

- Live ManyChat examples showed the cheap lead-qualifier path answering a
  normal price question with awkward clarification wording like `Para saan po
  'yan?`.
- A broad deterministic matcher for free-text price/location intent would not
  scale across customer wording variants and could steal mixed actionable turns
  from model/tool reasoning. The fix keeps interpretation model-led and treats
  the observed phrase as a response-quality violation instead.

Validation:

- `pytest test/test_runtime_v7_lead_tagging.py::test_runtime_routes_pure_location_po_to_full_runtime_seed test/test_runtime_v7_lead_tagging.py::test_runtime_removes_bad_para_saan_price_clarification_from_model_output test/test_runtime_v7_lead_tagging.py::test_runtime_removes_bad_para_saan_pala_prefix_from_model_output test/test_runtime_v7_lead_tagging.py::test_runtime_rewrites_bad_para_sa_tire_size_prefix_from_model_output test/test_runtime_v7_lead_tagging.py::test_runtime_removes_bad_para_saan_location_clarification_from_model_output test/test_runtime_v7_product_observation_harness.py::test_response_seeds_steer_bare_price_inquiry_to_size_question test/test_runtime_v7_product_observation_harness.py::test_response_seeds_support_generic_first_question_and_incomplete_lead test/test_runtime_v7_product_observation_harness.py::test_response_seeds_preserve_mixed_location_and_product_context -q`
  -> `8 passed`

### 2026-06-04: ManyChat Automation History Hydration

Commits:

- Pending commit: `Retain ManyChat automation history for Runtime V7`

What changed:

- Runtime V7's bounded ManyChat `loadMessages` reader now accepts outbound
  automated flow messages with type `msgout_default` and treats them as
  assistant conversation turns.
- The loader marks these rows as `message_kind=manychat_automation` with sender
  `ManyChat automation`, and the hydrator preserves that marker through the
  channel-history cache and model-facing Recent Conversation section.
- The runtime loader does not request `hide_automation=1`; the dashboard can
  hide automation for human viewing, but V7 needs the automated welcome/intake
  prompt if the customer's latest message is answering it.

Why it mattered:

- New-customer setup flows can send automated ManyChat prompts before V7 sees
  the customer's first free-text reply. If those `msgout_default` turns are
  filtered out, the model loses the immediate question the customer is
  answering and may restart the lead intake.
- Automation turns remain continuity evidence only. Product, price, order,
  payment, schedule, and service facts still need trusted tool/state grounding.

Validation:

- `pytest test/test_runtime_v7_ingress_trace.py -q`
  -> `26 passed`
- `pytest $(rg --files test | rg "test_runtime_v7") -q`
  -> `534 passed`

### 2026-06-04: Mirage G4 Fitment Alias Completion

Commits:

- `a5db9c2 Resolve Mirage G4 make-missing fitment aliases`
- `077b2bd Align BSE vehicle and promo signals with fitment`

What changed:

- Runtime V7 now shares vehicle canonicalization between Background Signal
  normalization and fitment lookup, so stored `car_make_model`, model context,
  tool args, and compatibility endpoint params agree for known aliases.
- The shared resolver now normalizes `mirage g4`,
  `car_make_model=Mirage G4`, `car_make=Mirage` plus `car_model=G4`, and
  `GLS G4 mitsubishi` to `Mitsubishi Mirage G4`; the fitment tool then calls
  `/car_tire_sizes` with `car_make=Mitsubishi` and `car_model=Mirage G4`.
- Raw customer/model text remains preserved separately in fitment diagnostics,
  so the runtime can show what was normalized without using raw text as
  trusted fitment truth.
- Buy 3 Get 1 promo wording such as `3+1`, `3plus1`, and `buy 3 take 1`
  now normalizes to `promo_types=buy3get1` and implied `quantity=4`, because
  Buy 3 Get 1 interest means four tires total unless the customer explicitly
  states a different quantity.
- Lead-qualifier fast-lane routing now treats `promo_types` as an actionable
  product signal, so promo/product turns stay in the full Runtime V7 path.

Why it mattered:

- A live ManyChat turn, "How much is for mirage g4 tire the 3plus1", reached
  the fitment flow but returned no compatible tire sizes. The likely failure
  mode was `Mirage G4` being split as make `Mirage`, model `G4`, which the
  compatibility endpoint does not recognize.
- The fix stays in deterministic make/model canonicalization before state
  storage and compatibility endpoint calls, rather than adding a raw-utterance
  intent gate.
- The live probe also showed BSE could misread `3plus1` as `quantity=3`.
  That would make stored state diverge from product-tool promo behavior, so the
  repair maps Buy 3 Get 1 interest to the four-tire quantity that the promo
  implies.

Validation:

- Direct checks confirmed `mirage g4`, `car_make_model=Mirage G4`,
  `car_make=Mirage` plus `car_model=G4`, and `GLS G4 mitsubishi` normalize to
  `Mitsubishi Mirage G4` in BSE, model context, tool args, and `/car_tire_sizes`
  params.
- Live Codex probe artifact:
  `tmp/runtime_v7_mirage_g4_probe/mirage_g4_probe_20260604_153750/probe.json`
  stored `car_make_model=Mitsubishi Mirage G4`, stored
  `promo_types=buy3get1`, called
  `extract_compatible_fitment`, hit `/car_tire_sizes` with
  `car_make=Mitsubishi` and `car_model=Mirage G4`, returned five candidate
  sizes, and asked for sidewall confirmation before product prices. This
  artifact predates the follow-up quantity-policy adjustment; local regression
  tests now verify `quantity=4` for Buy 3 Get 1.
- `pytest test/test_runtime_v7_product_observation_harness.py::test_background_signals_repair_buy3get1_quantity_to_four_tire_promo test/test_runtime_v7_product_observation_harness.py::test_background_signals_infer_buy3get1_quantity_when_model_only_extracts_promo test/test_runtime_v7_product_observation_harness.py::test_background_signals_preserve_explicit_buy3get1_order_quantity test/test_runtime_v7_product_observation_harness.py::test_runtime_v7_harness_hydrates_fitment_args_from_canonical_mirage_g4_signal -q`
  -> `6 passed`
- `pytest test/test_runtime_v7_canonical_values.py test/test_runtime_v7_ingress_trace.py test/test_runtime_v7_lead_tagging.py test/test_runtime_v7_product_observation_harness.py -q`
  -> `466 passed`
- `pytest $(rg --files test | rg "test_runtime_v7") -q`
  -> `549 passed`

### 2026-06-04: First-Turn Welcome And Intake Intro

Commits:

- Branch implementation on `feature/runtime-v7-first-turn-welcome-spiel`

What changed:

- Runtime V7 now inserts a three-bubble first-turn intro: welcome, lead info
  request, and tire-size guide.
- The intro appears only when the hydrated recent turns show no prior
  assistant/chatbot message, human-agent outbound message, or ManyChat
  automation, there is no active working memory, and the latest customer
  message does not already contain actionable details.
- Exact automated starter-button turns receive the full three-bubble intro
  first, followed by the deterministic button answer.
- Latest messages with actionable tire size, vehicle, brand, budget, quantity,
  contact, or specific service/order details receive only the compact welcome
  bubble before continuing through the normal lead triage or full Runtime V7
  path.
- Runtime V7 passes first-turn intro context to the main model, lead qualifier,
  and final composer, instructing the model to write the continuation after the
  runtime-owned intro instead of opening with another greeting.
- Follow-up staging probe hardening made the full-intake continuation more
  concrete: when the customer only greeted, the model should start with a
  non-greeting action phrase such as `Send niyo lang po` or `Pwede niyo pong`,
  not another `Hi po!`.
- The channel renderer mirrors the final-composer insertion as the first
  customer-visible bubbles even when the model response is structured, while
  avoiding duplicate intro text when fallback runtime text already includes it.
- A focused first-turn intro live pack now covers vague greetings, exact
  automated starter buttons, actionable product/vehicle/service first turns,
  and seeded prior outbound history from ManyChat automation, human agents, and
  prior chatbot messages. The endpoint probe validates return-only
  customer-visible bubbles against `/gulong/v7/chat/tester`; the harness live
  runner can use the same pack for compiled context and tool artifacts.

Why it mattered:

- New customers who send a vague greeting or tap an automated starter button
  should see the Gulong.ph intro and the exact details needed for tire
  discovery, while customers who already gave useful details should still get
  a light brand welcome without being delayed by a generic intake script.

Validation:

- Focused channel/composer/lead-triage/history tests -> `465 passed`.
- Full Runtime V7 suite -> `572 passed`.
- Non-live probe validation:
  `python -m py_compile scripts/runtime_v7_first_turn_intro_endpoint_probe.py scripts/runtime_v7_live_test_pack.py`
- Scenario listing without model calls:
  `python scripts/runtime_v7_first_turn_intro_endpoint_probe.py --pack test_packs/runtime_v7_first_turn_intro_live_pack.json --list`
  and
  `python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_first_turn_intro_live_pack.json --list`
- Staging endpoint probe before this follow-up:
  `tmp/runtime_v7_staging_smoke_20260604/runtime_v7_first_turn_endpoint_20260604_214407/summary.md`
  -> `2 passed`, `1 failed`; the failing `ft01_vague_greeting_full_intro`
  had a duplicate `Hi po!` in the model continuation after the runtime-owned
  full intro, which this hardening targets.

### 2026-06-04: Product Presentation Warranty And Installation Inclusions

Commits:

- `20550e2 Add Runtime V7 product inclusion spiel`

What changed:

- Product and selected-product presentation surfaces now render a deterministic
  `Warranty and inclusions` block after the shown product cards and before the
  CTA.
- The block is built from trusted shown card fields: the Tire Protection Plan
  explanation is included only when a shown card has TPP, delivery context
  suppresses installation inclusions, and manufacturer warranty details stay on
  the individual product cards instead of being repeated in this block.
- Installation inclusions render as a readable bullet block with free
  installation, mounting and balancing, weights and tire valves, plus the
  brand-new/warranty assurance line.
- Product/detail tool args now carry normalized `service_type` from Background
  Signals as render context, without changing product search filtering.
- The channel renderer groups product presentation paragraphs into separate
  ManyChat text messages so the warranty/inclusions block becomes one readable
  bubble before the CTA.
- Follow-up refinement: product SKU cards are now kept together in one
  customer bubble when they fit the channel limit, and the warranty/inclusions
  bubble is session-scoped through `product_inclusions_sent` so it is not
  repeated on later product presentations in the same session. For sessions
  created before the flag existed, Runtime V7 infers it from prior hydrated
  transcript text containing the inclusions block.

Why it mattered:

- Product presentations had the raw warranty/TPP data on individual cards, but
  the sales spiel was hard to scan and not consistently placed before the CTA.
- Installation inclusions are sales-relevant for install/pickup/undecided
  product discovery, but they should not be shown as an installation benefit
  once the customer is explicitly on a delivery path.

Validation:

- `pytest test/test_runtime_v7_channel_renderer.py::test_channel_renderer_adds_product_inclusions_bubble_before_cta test/test_runtime_v7_channel_renderer.py::test_channel_renderer_suppresses_product_inclusions_after_session_seen test/test_runtime_v7_channel_renderer.py::test_channel_renderer_omits_installation_inclusions_for_delivery_product_context test/test_runtime_v7_ingress_trace.py::test_product_inclusions_sent_state_survives_harness_export_hydration test/test_runtime_v7_ingress_trace.py::test_product_inclusions_sent_can_be_inferred_from_prior_visible_history test/test_runtime_v7_product_observation_harness.py::test_runtime_final_response_includes_product_inclusions_before_cta test/test_runtime_v7_product_observation_harness.py::test_runtime_final_response_omits_installation_inclusions_for_delivery_product_context -q`
  -> `7 passed`
- `pytest test/test_runtime_v7_channel_renderer.py test/test_runtime_v7_product_observation_harness.py -q`
  -> `447 passed`
- `pytest $(rg --files test | rg "test_runtime_v7") -q`
  -> `576 passed`

### 2026-06-04: ManyChat Bubble Delivery Pacing

Commits:

- Branch implementation on `feature/runtime-v7-manychat-bubble-delay`

What changed:

- Runtime V7 live ManyChat send modes can now deliver adjacent text bubbles as
  separate `sendContent` calls with a short delay between text-to-text bubbles.
- The pacing policy lives in `runtime_v7.api_runtime` after channel rendering
  and after the pre-delivery freshness check, so tester/return-only paths still
  return the same rendered payload without sleeping or sending.
- `RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS` controls the delay, defaults to
  `1200`, and can be set to `0` as a kill switch.
- `RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MAX_MESSAGES` caps paced sends, defaults
  to `6`, and sends any remaining tail messages in one normal batch.
- Payloads without adjacent text bubbles stay on the existing batch delivery
  path, which avoids adding delays around image/payment-like payloads unless
  there are text-to-text bubbles to pace.

Why it mattered:

- Multi-bubble replies can look abrupt when ManyChat receives all bubbles in
  one immediate delivery. Runtime V7 can now make live customer replies feel
  closer to a human typing cadence without changing model output, renderer
  grouping, tester payloads, or ManyChat API client semantics.

Validation:

- `python -m py_compile runtime_v7/api_runtime.py`
- `python -m pytest test/test_runtime_v7_channel_renderer.py -q`
  -> `18 passed`
- `python -m pytest $(rg --files test | rg "test_runtime_v7") -q`
  -> `583 passed` after merging the latest `origin/product` generic-guard
  staging commit

### 2026-06-04: Generic Price/Location Clarity And Mixed Service Objectives

Commits:

- Branch implementation on `fix/runtime-v7-generic-price-location-clarity`

What changed:

- Free-text generic turns such as `how much`, `hm`, and `location po` remain in
  the normal Runtime V7 model/tool path rather than a deterministic free-text
  intent classifier.
- Response seeds guide bare price questions toward a direct tire-size question
  and bare location questions toward the business/service-area answer.
- The final response guard removes prohibited generated clarification wording
  such as `Para saan po 'yan?`, `Para saan po pala, ...`, and `Para saan po ang
  location?`, and rewrites `Para sa anong tire size` to a direct tire-size
  question.
- Exact ManyChat button/postback responses remain deterministic; free-text
  commercial interpretation stays model-led.
- Mixed latest turns with structured product context plus structured customer
  location now expose both product discovery and read-only service partner
  coverage as primary tool objectives, so the model is prompted to satisfy both
  actionable parts before finalizing.
- Added a root `AGENTS.md` deployment restriction documenting that staging/live
  releases should use the normal Cloud Build trigger pipeline unless the user
  explicitly forces a manual path.

Why it mattered:

- Generic customer questions should not produce awkward clarifiers like `Para
  saan po 'yan?`.
- The fix keeps scalable model-based understanding for free text, while still
  guarding a small set of clearly bad output phrases.
- Customers can combine product and location details in one short message; the
  model needs explicit turn-level objectives so it does not stop after only the
  product lookup.

Validation:

- Focused local regression tests for generic price/location wording and mixed
  service objectives -> `5 passed`.
- Full Runtime V7 suite -> `585 passed`.
- Staging validation should confirm `/health` release metadata after the Cloud
  Build trigger deploys the target branch, then run bare price, bare location,
  and mixed product/location endpoint probes against the deployed staging
  service.

## How To Update This File

Add a new section when a commit or group of commits changes a Runtime V7
capability boundary. Each section should include:

- Commit ids or PR ids.
- What changed.
- Why it mattered.
- Validation or probe evidence.
- Any follow-up gap created by the change.

## 2026-07-24 - Order progression and validated service continuity

- Added renderer-owned product choice controls backed by delivered product
  presentation refs, exact-card validation, and trusted selected-product state.
- Kept a single requested-brand match selected even when alternative-brand
  cards are visible, while preserving explicit choice for multiple same-brand
  matches.
- Preserved the newest validated installation slot across later read-only
  service lookups and supplied that exact partner/slot evidence to both the
  main model context and final composer.
- Added delivery-backed no-walk-in notice deduplication and capped explicit
  `top_k=1` product presentations to one card.
- Routed every typed payment-method inquiry through the active checkout
  metadata policy even when the model does not select a FAQ id, so unsupported
  methods and preselection brand-installment questions are source-backed
  before composition.
- Kept named-method answers concise: the full active catalog remains structured
  evidence, while customer copy answers the requested method and offers no
  more than three relevant alternatives.
- Made tool-backed Active Working Memory updates deterministic and ref-only,
  excluding runtime assistant prose as fact evidence and skipping the memory
  model on commercial tool turns.
- Kept internal order-summary reconciliation customer-neutral: the current
  trusted summary may be confirmed without narrating a runtime correction.
- Added one source-backed retry for current promo and payment-policy inquiries
  when the model omits the required authority tool. The retry is provider- and
  brand-neutral, preserves ordinary payment selections, and ignores stale
  promo context during later order progression.

## 2026-07-25 - Separate promo information from customer selection

- Reclassified `Promo Details` and `About Brand` as read-only interactions.
  They render the reviewed catalog facts without creating a brand preference,
  advancing lead qualification, or attaching location/checkout controls.
- Kept `Check Price` and `Choose Brand` as product-discovery selections. Those
  actions may carry a validated brand query preference and advance only after
  grounded product results.
- Replaced brand-named synthetic inputs for informational card clicks with a
  neutral audited action message, preventing the state-signal and memory paths
  from interpreting viewed content as customer preference.
- Added deterministic reviewed-content responses for informational clicks.
  This removes redundant promo retrieval and model calls from that path while
  retaining the validated catalog context and click ledger.
- The change is action-based and applies to all reviewed promos and brands.

Validation:

- Changed-file Ruff: passed.
- Focused promo, renderer, location, checkout, and ingress regressions:
  `185 passed`.
- Full repository suite: `986 passed`.
- Repository-wide Ruff retains 18 pre-existing unrelated findings; changed
  files are clean.
- Deployed staging results remain a release gate.

## 2026-07-25 - Make afternoon choice executable and preserve submit safety

- Changed `Anytime in the afternoon` from a permanently unresolved schedule
  preference into a deterministic selection rule: validate the earliest
  actual afternoon slot from the delivered observation.
- When no afternoon slot is present, retain `12:00 PM` as a flexible customer
  preference without asserting availability.
- Added explicit schedule and submission readiness fields so the order summary
  can be shown after contact completion while order-payload creation remains
  blocked until an exact partner/slot is grounded.
- Preserved renderer ownership of the order summary and the existing
  `build_order_payload`/`submit_order` safety boundaries.

Validation:

- Changed-file Ruff: passed.
- Focused transaction-choice and order-state regressions: `532 passed`.
- Runtime V7 suite: `928 passed`.
- Ingress-trace suite: `42 passed`.
- Full repository suite: `990 passed`.
- Deployed staging results remain a release gate.

## 2026-07-26 - Keep multi-SKU CTA in the product decision layer

- Resolved the conflict between missing-location lead focus and the shared
  qualification decision when multiple exact product cards are rendered.
- Multiple visible SKUs now make `product_selection` the composer and renderer
  CTA focus. Location and later checkout questions are deferred until the
  customer selects or types one product.
- Added a renderer safety boundary so a competing model-written question cannot
  appear after product-selection controls.
- The rule is product-count/ref based and applies to every brand and SKU.

Validation:

- Changed-file Ruff: passed.
- Focused regressions: `92 passed`.
- Runtime V7 suite: `931 passed`.
- Ingress-trace suite: `42 passed`.
- Full repository suite: `993 passed`.
- Deployed staging validation remains a release gate.

## 2026-07-26 - Add one final decision contract and typed selection plans

- Replaced overlapping final-composer CTA authorities with one post-tool
  `decision_contract`.
- Made the multiple-visible-SKU decision authoritative over location, schedule,
  payment, contact, and order-readiness hints.
- Required model product-reference calls to declare a typed selection basis.
  Brand/model plans are matched against trusted visible cards and remain
  unresolved when more than one SKU matches.
- Made visible-reference resolution primary whenever model-extracted
  latest-turn brand/model state and a current product presentation coexist.
  A genuinely new brand remains discoverable through the existing
  product-search fallback.
- Reused the typed ambiguity result as the pre-tool qualification decision so
  province/city controls cannot appear beside an unresolved same-brand SKU
  clarification.
- Preserved exact button refs and model-led free-text interpretation without
  adding per-brand or per-SKU rules.

Validation:

- Changed-file Ruff: passed.
- Focused regressions: `579 passed`.
- Runtime V7 suite: `937 passed`.
- Ingress-trace suite: `42 passed`.
- Full repository suite: `1003 passed`.
- Adaptive deployed-model and staging/live revision validation remain release
  gates.

# 2026-07-31 - Selected-slot versus booked-installation semantics

- Clarified the final-composer service action packet so selecting a validated
  time means selected for order review, not a confirmed appointment or
  installation.
- Extended the existing side-effect authorization check to equivalent
  appointment and installation commitment claims. Invalid output receives the
  existing one-shot composer repair; successful conversational wording remains
  model-owned.
- Added a regression for the exact Taglish commitment found during direct
  human/CS review of the zero-traffic live candidate.
- Preserved `promo_catalog` as the active final-composer decision when a
  reviewed promo gallery is rendered. A location-focused lead hint can no
  longer override that earlier choice layer and create two customer asks in
  one response.
- When location is the active decision, product/SKU selection or confirmation
  is now explicitly deferred. This closes a no-traffic VM replay where the
  composer asked for both a specific city and product confirmation despite the
  customer already anchoring the exact product.
- Expanded the existing installation side-effect check from a character-window
  match to a whole-sentence commitment check, and made order-summary
  `remaining_fields` plus its count authoritative composer context. This
  prevents long product descriptions from hiding a false booking claim and
  prevents prose from narrowing several missing order fields to only one.

## 2026-07-31 - Runtime V7 positive service-claim authorization

- Made composer service and schedule claims follow a positive evidence
  allowlist in `CustomerTurnPlanV1`.
- Kept customer location/date/time input as lookup intent rather than
  availability authority.
- Kept semantic and human-tone release review outside deterministic regex
  grading.

## 2026-07-31 - Source-backed brand background and warranty

- Added automatic Gulong.ph brand directory/detail-page ingestion with
  immutable Firestore versions, embeddings, and atomic active-pointer updates.
- Replaced promo-offer summaries as the About Brand source with exact
  published brand profiles.
- Added `get_brand_knowledge` for source-backed free-text brand background,
  comparisons, and warranty questions without another model call.
- Clarified that general brand background and comparison are answered before
  any optional tire-size CTA. Tire size gates only fit, stock, exact-price, and
  size-specific promo checks.
- Made composer repair copy only exact authorized evidence refs. A commercial
  correctness fallback now retains an already-validated renderer-owned promo
  gallery instead of replacing the whole turn with text.
- When published brand knowledge is the grounded candidate and there is no
  selected product, the capability compiler
  withholds the redundant generic product FAQ. This prevents unrelated FAQ
  coverage text from being attached to a brand warranty.
- Gulong.ph damage-coverage explanations must retain every published
  eligibility condition; otherwise the composer states only the policy
  duration instead of broadening coverage through selective summarization.
- Kept manufacturer/product warranties distinct from the Gulong.ph
  unconditional-damage warranty and kept About Brand informational.
- Added `RUNTIME_V7_BRAND_KNOWLEDGE_ENABLED` for independent staging and
  rollback.

## 2026-07-31 - Tracked brand evidence and city-decision priority

- Passed validated About Brand profile fields and evidence refs from tracked
  action seeds into the typed composer claim contract.
- Prevented source-backed informational brand replies from falling into the
  generic no-surface progression fallback.
- Made a ranked serviceable-city surface authoritative when a province-level
  schedule inquiry still needs a city, deferring incidental product cards.
- Made final-composer decision context follow the required surface in
  `CustomerTurnPlanV1` for location, schedule, and payment choice layers.
- Recovered a rejected province-level exact-slot plan by presenting the
  current serviceable-city choices, without executing or persisting a slot
  lookup.
- Kept expected `tool_plan_not_authorized` safety decisions out of the
  customer-facing Chatbot Error tag while retaining guard telemetry.
- Added ranked-city preview refs to typed service/schedule claim authority and
  product-search promo refs to typed promo authority when provider validation
  is present.
- Kept general About Brand replies focused on source-backed background and
  brief warranty duration; detailed coverage and eligibility remain reserved
  for explicit warranty questions.

## 2026-08-06 - Operating identity and model-owned turn transitions

- Added a shared reviewed operating-identity context for both the main model
  and final composer: online-first tire shop, Makati head-office installation
  site, warehouse-to-booked-site fulfillment, and the approved `over 100
  trusted installation partners` brand claim.
- General business-location and physical-shop questions no longer depend on a
  location-choice surface to answer the operating-model question. Exact nearby
  availability and coverage remain service-tool-owned.
- Corrected the operating identity so the Makati head office is positively
  identified as an installation site; Runtime must not deny installation there.
- Valid final-composer output now retains its own connective prose and CTA;
  deterministic lead/promo CTA rewriting remains only for legacy or failed
  composition paths.
- Added one shared complete-turn composition policy for plain-text and
  deterministic-surface turns. It connects business facts to the answer,
  contextualizes rendered results, and keeps the CTA on the current sales
  decision instead of stacking detached spiels or jumping stages.
- Carried prior trusted product refs into later service/schedule turn plans so
  selection acknowledgements remain grounded across sales-stage transitions.
- Prevented `question_only`, conditional, historical, and rejected signals from
  satisfying lead qualification or order readiness. This keeps business-location
  questions from being mistaken for the customer's service area.
- Extended the varied human-response evaluation pack with business-identity
  and generic-assistance first turns and corrected the older no-walk-in review
  rule to allow explicit customer questions.
- Routed an unwanted mid-thread greeting through the final model composer
  instead of deleting a sentence from an otherwise valid response.
- Reused the published promo catalog for the first applicable Tire Protection
  Plan pricelist. The reviewed Double Warranty card replaces the long generic
  warranty/inclusions paragraph while exact product fields stay renderer-owned.
- Treated that warranty card as supporting product context, not a competing
  promo-decision layer, and retained the product choice as the model's single
  next step.
- Added an opt-in promo-catalog dependency to the live pack runner so catalog
  composition can be checked without adding catalog cost to every probe.

## 2026-08-09 - Adaptive conversation and ManyChat rendering candidate

- Changed the reviewed Double Warranty catalog action from `Choose Brand` to
  `Find Tires` while reusing the existing generic `choose_brand` discovery
  action and promo catalog publication path. Added an explicit publisher
  revision to immutable catalog identity so reviewed presentation changes can
  be published when source bytes are unchanged. The approved August catalog
  was rebuilt and activated as `catalog-202608-5f4ddb23ee0c-v2-p2`; the prior
  `catalog-202608-5f4ddb23ee0c-v2` pointer remains available for rollback.
- Made structured safe-fallback response units authoritative for channel
  surface selection. The ManyChat renderer no longer reattaches product,
  promo, location, schedule, or payment surfaces omitted by the validated unit
  plan.
- Removed the brandless-size product/promo-first tool objective when the latest
  typed goal is service, schedule, or payment. Province-level installation
  guidance now asks the model to render grounded city choices before schedule
  progression; a validated city without a selected product resumes model-led
  product/category discovery without broad promo tools.
- Prevented conditional/question-only signals from entering evidence-bound
  Active Working Memory. A four-tire 3+1 comparison remains lookup context;
  quantity four becomes durable only after explicit customer acceptance or a
  validated tracked choice.
- Simplified incomplete order summaries to show known facts only. Missing
  placeholders and the duplicate missing-fields block were removed; the model
  may request the remaining low-friction booking details together in natural
  Taglish.
- Replaced long product-card text plus raw URLs with a compact deterministic
  price list beside image-backed choice cards. A single exact result now keeps
  its image and tracked product-selection button.
- Clarified that a final product/quantity/promo selection is not a final or
  confirmed order until order submission succeeds.

Adaptive evidence used real return-only endpoint output and model-chosen
customer continuations. Promo details/actions, category and product clicks,
comparison, province/city/schedule buttons, grouped booking details, and the
two-tire to four-tire 3+1 transition were exercised. A final fresh location-
first model smoke displayed grounded Laguna city controls, and a displayed San
Pablo City click retained the requested size and quantity and resumed grounded
price-category controls instead of advancing prematurely to scheduling.

The catalog was published through the reviewed immutable path. A controlled
ManyChat delivery then submitted a text/card/text payload containing the new
Double Warranty `Find Tires` action and received HTTP 200 success. The exact
submitted order and tracked flow token were inspected. The hidden ManyChat
history session was stale and the bounded warehouse event trail had not yet
ingested the new outbound event, so final Messenger UI observation remains a
separate evidence boundary and the send must not be repeated merely to obtain
that evidence.

The pre-publication repository-wide suite passed 1,442 tests. The post-change
focused promo suite passed 122 tests and the targeted location/product suite
passed 24 tests. The final post-change repository-wide suite passed 1,443
tests. Commit, staging deployment, staging endpoint verification, and only then
main/VM promotion remain the release gates.

## 2026-08-10 - General location-first continuity repair

- Replaced search-intermediary wording guidance with Gulong.ph-owned brand
  voice: model prose should naturally say what `kami`/`tayo` offer or state the
  grounded result directly.
- Added reusable known customer context to the non-prescriptive turn envelope,
  separate from claim and action authority, so locations and other facts are
  not re-asked merely because they still need provider validation.
- Preserved unresolved goals through tool-backed Active Working Memory updates
  and made tool execution non-terminal for conversational intent.
- Made field-only tire-size replies continue an existing service/order/payment
  thread instead of activating automatic broad-promo discovery.
- Kept selected-product/order context in payment FAQ composition so a grounded
  answer can resume the pending sale naturally.
- Removed renderer-owned price and four-tire total from synthetic product-click
  prose; trusted product refs continue to own those facts.
- Verified the affected set with 705 passing tests and one four-turn adaptive,
  return-only location-first replay. The final pre-merge repository gate passed
  1,456 tests, followed by clean changed-file Ruff, compilation, diff, strict
  change audit, and a 747-test affected recheck after mechanical lint cleanup.

- Staging semantic validation caught a remaining deterministic progression
  conflict: coverage-only partner results still supplied a legacy
  `suggested_next_tool=find_installation_slots` instruction. Prompt-only
  reinforcement did not reliably overcome that upstream anchor. The instruction
  and corresponding compact-result fields were removed; anonymous partner cards
  remain suppressed from typed disclosure metadata, without selecting the next
  stage. The corrected increment passed all 1,456 repository tests plus Ruff,
  compilation, diff, and strict change-audit gates before its staging rebuild.
- A follow-up staging replay confirmed that the next action was tire discovery,
  but the generic service-action packet still described partner coverage and
  slot lookup identically. The packet now exposes the factual lookup scope,
  whether slots were checked, and whether a trusted product is selected. This
  gives the composer a reusable action boundary without choosing its wording or
  CTA and without adding a phrase matcher or post-model rewrite.
- The final adaptive schedule-click gate found that a legacy retry treated any
  free-text time as an exact selection and pre-applied the nearest slot before
  the customer chose from the rendered schedule controls. The retry and its
  regex were removed. Free-text time preferences now drive grounded slot
  discovery; validated tracked buttons remain the authority for applying the
  customer's chosen schedule.

### Normalized analytics durability and review surfaces

- Replaced the request-scoped five-second BigQuery wait with one non-blocking
  dispatch after the complete normalized turn is assembled. This keeps all
  rows for each table batched while sharply reducing container-replacement loss
  without adding warehouse latency to the customer response.
- Added deduplicated BigQuery views for Runtime V7 turns, free-text turns, tool
  calls, LLM spans, guided interactions, and errors. Current consumers should
  use these normalized surfaces rather than the historical legacy tables.
- Added timezone-correct, five-minute-settled warehouse health SQL and a
  bounded adjacent-turn free-text review query. The review remains semantic
  and model/human-led; no phrase classifier was promoted into runtime intent or
  CTA authority.
- Audited 48 recent free-text VM-live turns: 38 passed, 8 need review, and 2
  failed on a safety-sensitive substitute-size transition and subsequent
  repeated known-size request. Most ordinary free-text choices and booking
  intent continued successfully.
- Combined staging and no-traffic VM candidate smokes retained vehicle, size,
  location, quantity, value, and qualitative driving preferences. Qualitative
  tire recommendations may use the model's stable learned expertise even when
  every subjective attribute is not published in the catalog; they should be
  framed as practical guidance rather than measured results or guarantees.
  Exact commercial, fitment, availability, warranty, service, schedule,
  payment, and order facts remain grounded in typed tools and deterministic
  surfaces. No keyword intent gate or post-model sentence rewrite was added.

## 2026-08-10 - Guided-choice authority and conversational checkout repair

- Reprojected valid guided city/province choices after signal extraction so
  synthetic router text cannot downgrade the delivered action. Current guided
  city choices may authorize service lookup; province and `Other` retain their
  separate precision and consent boundaries.
- Made current guided actions visible to service objectives and final
  composition, while keeping later explicit free-text corrections stronger
  than carried state.
- Prevented product-option presentation from being tagged as product selection;
  selection now requires a trusted selected-product ref/context.
- Made pause/deferment override pending sales progression without discarding
  durable shopping context.
- Separated official receipts, invoices, and quotations from payment methods;
  added the reviewed receipt FAQ and compound payment/document handling.
- Preserved `supporting_context` and `missing_fields` in the turn-surface
  schema. Incomplete order details can now render beside their immediate Pay
  Now/Pay Later choice without being rejected as competing decisions.
- Passed 228 affected deterministic tests and five focused document/payment
  tests. Bounded local return-only adaptive checks passed city-click retention,
  pause/document handling, and the complete product-to-order-summary journey.
  The final repository-wide suite passed 1,470 tests after correcting one stale
  pack-count assertion to validate all seven scenarios. Staging, real ManyChat
  delivery, and live promotion remain separate release gates.
- Staging build `70eaac15-f672-4267-ab40-908036e841cf` deployed `5652c71` to
  revision `gulong-chatbot-runtime-staging-00400-czk` at 100% and passed the
  guided product-to-checkout mechanics. Human/CS review held promotion because
  model prose still used "May nakita po kaming" and "4 piraso." The composer
  contract now explicitly keeps routine inventory in Gulong-owned voice and
  uses `pcs` or `tires` unless the customer used the Tagalog term first.
- Staging revision `gulong-chatbot-runtime-staging-00401-482` on `6563872`
  removed those phrases and retained the complete guided journey, but human/CS
  review held promotion again because tracked product and schedule turns
  switched from Taglish to English. The tracked-interaction voice contract now
  makes the latest natural customer free text authoritative for language and
  register over synthetic click prose.
- Staging build `4b67d455-ebd1-43e4-8ee3-9ca786b1dfe8` for `53a01c9` stopped in
  its test step (`1 failed, 1,469 passed`) before image creation or deployment.
  The only failure was a brittle 1,500-character prompt-prefix assertion after
  the highest-priority voice section grew. The test now verifies semantic
  ordering before the response schema instead of a fixed character window.
- Staging build `0aeb833b-c7d8-4fcb-b0d3-7dd00f1eb7dc` deployed `39c3848` to
  revision `gulong-chatbot-runtime-staging-00402-4x7` at 100% and both health
  endpoints reported the exact release. The adaptive product/location journey
  held promotion: the composer again used search-intermediary inventory voice,
  then selected `build_order_summary` without presenting schedule choices.
  Final-composer voice misses now request a model repair instead of receiving a
  deterministic response rewrite. Service objectives now recognize a visible
  product presentation or selected-product-backed observation and may continue
  an already retained installation path after the tracked product choice.
  Stale unselected observations, delivery, missing locations, and already
  validated slots are negative controls. The affected 216-test set passed;
  staging, controlled ManyChat delivery, and live promotion remain pending.
- Staging build `10d626f2-9180-4c30-915e-b71f2e1696d1` stopped before image
  creation/deployment (`1 failed, 1,475 passed`). Its one stale repair-format
  fixture returned "I found ..." as the supposedly valid recovery, which the
  new voice contract correctly rejected. The fixture now keeps that wording
  only in the intentionally invalid draft and uses compliant Gulong-owned voice
  for the successful repair.
- A targeted `ccf955f` staging check separated BPI-card and official-receipt
  questions into two calls but incorrectly let the carried payment-method
  argument override the explicit receipt question. FAQ resolution now matches
  the explicit question before applying payment metadata as a fallback, so
  document questions cannot be converted into payment-policy answers by a
  sibling clause. Live promotion remains held pending the rebuilt narrow check.
- Reviewed the stale `semantic_store_location` release assertion: a pure
  business-address question should answer the Makati operating identity and is
  not required to show a province picker. The real gap was an explicit
  installation request with no area, where the model asked for a city but did
  not call the guided surface. That typed service state now produces a primary
  `present_serviceable_location_choices` objective while retaining free-text
  location replies and delivery as negative controls.
- Build `0ac3ea97-6c5b-4b88-81d4-e0e0fb6b06c1` stopped before deployment
  (`1 failed, 1,475 passed`) because the corrected FAQ order changed only the
  `matched_by` telemetry for a valid installment lookup. Named-method queries
  that resolve to payment FAQ entries now preserve
  `runtime_payment_policy_query`; document FAQ matches remain lexical.
- The first no-traffic VM candidate smoke on promotion merge `a63fe4a` caught a
  variance-sensitive location error before customer cutover: the main model
  passed the generic label `Service Areas` to partner lookup as though it were
  a customer place. The partner provider now rejects plural and compound
  business-location labels through its existing input-validation boundary and
  explicitly recommends the available guided service-area tool to the next
  model round. This does not classify customer intent or insert a response; it
  prevents a non-geographic tool argument from authorizing a lookup while the
  model retains ownership of the reply and next action. Explicit places,
  validated province/city choices, and delivery remain unchanged. Live VM
  promotion is held until the corrected exact candidate passes staging and the
  same no-traffic smoke.
- Staging build `747ad620-ceb1-46c9-a3c7-8519ca45f83d` passed 1,482 tests and
  deployed `82afbe9` to `gulong-chatbot-runtime-staging-00405-dwk`. The exact
  replay confirmed that rejecting a bad partner-lookup argument alone was not
  sufficient: on another valid model run, the model asked for a city in prose
  without calling the available province surface. Typed primary guided-surface
  objectives now set the initial tool choice to the routing-only surface. The
  model continues to own the surrounding response and CTA; delivery, explicit
  city, and no-service-state controls do not force the picker.
- An alternate-port VM replay showed that the lightweight extractor could omit
  an explicit installation choice when the same message said tire size and
  location were unknown. The extractor contract now preserves the known
  `service_type` while omitting only unknown size/location/address fields. This
  keeps capability exposure model-led and avoids raw-text routing patches.
- A later no-traffic candidate retained `Service Areas` as an unsafe
  conversational location label, but tool-objective construction still treated
  the label as a customer area and therefore skipped the required province
  surface. Service lookup now ignores any explicitly unsafe location signal.
  This aligns planning with the existing typed safety decision and applies to
  all non-actionable location extractions rather than matching a phrase.
- The initial forced-tool repair was removed before promotion. Location bias is
  now owned by the main model prompt and typed objectives: explicit
  installation/location is primary, while delivered-product hesitation makes
  location a preferred next-best move with explicit deferral conditions. Tool
  choice remains `auto`; existing renderer and service guards remain hard.
- Prior product-choice surfaces no longer create a blanket prompt-level deferral
  on later hesitation turns. The model may replace that earlier unresolved
  decision with location as the sole current surface; it still cannot stack
  product and location decisions in the same turn.
