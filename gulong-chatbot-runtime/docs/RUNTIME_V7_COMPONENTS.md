# Runtime V7 Components

Last updated: 2026-09-16

This document maps Runtime V7 modules to responsibilities, downstream
dependencies, and primary tests. Keep it current when adding or changing V7
modules.

## How To Read Component Entries

Each component should be understood by five questions:

- What inputs does it accept?
- What outputs does it produce?
- What durable state or refs does it read/write?
- What is the trust boundary?
- Which tests or probes validate it?

When adding a component, update this document with those answers. Do not only
list a filename.

## Signal Extraction And Query Hydration

- `runtime_v7.state_signal_model`, `state_signal_normalization`, and
  `state_signal_schema`
  - Represent the customer's canonical current/home location separately from
    `acceptable_service_locations`.
  - Preserve explicit brand exclusivity as canonical
    `brand_match_mode=strict`; an ordinary brand mention remains a preferred
    search anchor rather than a cross-brand prohibition.
  - Normalize and deduplicate each alternative without flattening canonical
    city/province labels into a comma-delimited signal.
  - Clear alternatives when the customer replaces the anchor, preventing stale
    nearby-area preferences from carrying into a later inquiry.
- `runtime_v7.runtime_harness`
  - Rehydrates unscoped service calls from the canonical anchor and product
    calls from explicit latest-turn constraints.
  - Guards slot progression with delivered/validated product authority or a
    typed schedule constraint; provider observations with zero cards do not
    satisfy the product prerequisite.
  - Emits provider-owned area summaries and partial-match notices, and validates
    composer claims against typed evidence instead of customer-facing phrases.
  - Restores explicit latest-turn terrain syntax and removes model queries that
    contain only brand, terrain, and size rather than a genuine SKU/model.
- `runtime_v7.product_search`
  - Keeps exact tire size, explicit EV compatibility, and exclusions hard.
    Other shopping filters may relax only on exact-fitment candidates with
    typed per-card mismatch metadata; requested-brand options are ordered first
    and explicit strict-brand requests never cross brands.
- `runtime_v7.channel_renderer`
  - Renders deterministic product-scope disclosures before source-backed price
    lists, limits visual choices to trusted-image cards, and prevents adjacent
    model prose from overstating a relaxed result as exact.

## API And Channel Boundary

- `runtime_v7.api_runtime`
  - Deployable `/gulong/v7/chat` and `/gulong/v7/followup` service boundary.
  - Owns request shape, session restore/save, harness construction,
    profile/channel hydration, delivery, tagging, inbound event replay, and
    compact result payloads.
  - Plans location/checkout renderer surfaces before final composition when the
    turn-plan flag is enabled. Its location plan executor resolves both the
    general serviceable-province choice surface and isolated city-availability
    previews, while validating province/city transitions before rendering.
  - Owns per-session active-turn locking, pre-delivery ManyChat freshness
    checks, CAS-backed session saves, BigQuery debug trace persistence, and
    compact Cloud Logging trace summaries.
  - Owns the durable allowlist for renderer-created product, location,
    schedule, and checkout choices. Public click status comes from the runtime
    allowlist, not from successful token parsing. Return-only presentations are
    marked `evaluated` so isolated stateful probes can exercise later clicks.
  - Inputs: API request payload, session doc, profile hints, optional ManyChat
    loader/profile results, delivery mode.
  - Outputs: channel-safe response payload, content messages, delivery/tagging
    result, turn trace summary, persisted debug trace, persisted strategy
    state.
- `runtime_v7.model_contract.CustomerTurnPlanV1`
  - Internal positive authorization contract for one complete customer-visible
    turn: accepted transitions, satisfied fields, decision layers, evidence
    refs, and compact required/optional surface metadata.
  - Preserves whether a surface is a required direct answer, a
    `supporting_replacement`, or optional context, plus the missing fields of an
    incomplete order summary. Grounded direct answers compile stable request
    obligations; supporting replacements do not create a second customer
    request or CTA layer. Successful current-turn service coverage also creates
    a text obligation when its anonymous area-only cards are intentionally not
    customer-visible.
  - Full renderer bodies and provider payloads are intentionally excluded.
- `runtime_v7.model_contract.CustomerTurnPlanV1` and
  `RuntimeV7FinalResponseModel`
  - The main model proposes read-only tool calls, and the final composer chooses
    ordered text and validated surface refs for the complete visible turn.
  - Location, product, promo, payment, comparison, and sales-stage decisions do
    not pass through separate phrase classifiers or second-pass semantic
    decision models. This removes competing authorities and duplicate model
    calls while preserving provider and renderer boundaries.
  - `runtime_v7.runtime_harness` can carry a model-selected typed delivery scope
    into `runtime_v7.faq_tools`. The FAQ facade may establish the reviewed
    general delivery process, but the scope itself cannot confirm exact-address
    serviceability or delivery timing.
  - Successful FAQ providers emit stable `faq:<domain>:<faq_id>` evidence refs.
    The turn plan grants those refs only to `faq_facts`; it does not broaden
    service or schedule availability. `no_match` results grant no fact
    authority. Usable current-turn FAQ results become required grounded answers
    so composer repair preserves their supported scope while removing only an
    unauthorized narrower claim.
  - `runtime_v7.faq_tools` owns DOT-code interpretation and delegates formal
    quotation progression to `runtime_v7.delivery_payment_policy`. An authored
    V7 policy answer takes precedence over nearby legacy RAG chunks after goal
    selection, so retrieval similarity cannot change the chosen fact source.
  - A truncated/invalid final-composer object receives one bounded format retry
    with the same evidence and positive contracts. Retry success is recorded in
    guard/LLM telemetry. A truncated contract-repair object gets the analogous
    one-shot retry from the original compact context and typed violations; a
    second invalid object retains the legacy safe fallback.
  - Empty, empty-content, unknown-only, duplicate, or missing-required-surface
    plans are structural contract violations. Failed repair preserves valid
    initial prose and required grounded surfaces instead of collapsing the turn.
    Typed `request_coverage` mappings are strictly checked when emitted, while
    legacy local clients remain compatible through the existing surface/claim
    contracts.
  - Runtime validates proposal shape and executes only read-only providers;
    provider results, not model fields, authorize customer-visible facts.
  - Domain-specific FAQ readers are consistently available as registered
    read-only tools. Phrase-ranked hints remain retrieval telemetry only and do
    not expose a domain or force a call.
  - Customer-facing composition silently normalizes clear shorthand, minor
    typos, and informal business-term equivalents. It uses the correct term
    naturally without quoting or announcing a correction; only materially
    ambiguous interpretations trigger clarification.
- `runtime_v7` semantic answer and promo audit helpers
  - Retained only for explicit offline evaluation and regression diagnosis.
    They are not serving-path gates and cannot delete sentences, replace a
    schema-valid composed reply, choose a surface, or rewrite its CTA.
- `runtime_v7.runtime_harness` promo execution and response contract
  - Accepts the model's typed promo query plus `presentation_mode`; validates
    search output and may complete a requested gallery mechanically from only
    the current `allowed_promo_refs`. Result-dependent mixed proposals are
    intersected with that allowlist; an empty intersection fails closed.
  - Produces `promo_response_contract_v1` for the customer turn plan, composer,
    typed claim validation, and bounded structural repair. The contract
    contains customer-claimable facts and surface refs but excludes retrieval
    diagnostics and duplicate composition guidance.
  - Records `requested_promo_surface_completed` guard telemetry and
    `promo_gallery_completed_from_search_contract` efficiency telemetry. The
    former proves the rendering path; neither event authorizes a promo fact.
  - Primary tests: `test/test_runtime_v7_promo_catalog.py`,
    `test/test_runtime_v7_turn_plan.py`, and
    `test/test_runtime_v7_product_observation_harness.py`.
- `runtime_v7.channel_renderer`
  - Serializes accepted composer response-unit order. Under the turn-plan
    contract it resolves location and checkout refs like other trusted
    surfaces and does not append, reorder, or collapse successful units.
  - Preserves a complete model-authored opening on every nonempty `welcome_only`
    first turn. Runtime adds the exact fixed welcome only when the output is
    empty, malformed, or surface-first, and never moves prose across a surface.
    `full_intake` remains a compatibility/failure sequence rather than the normal
    path for greetings or starter questions.
  - On a low-information first turn, the model acknowledges the exact starter
    goal and asks one connected discovery question. Tire-help leads with
    sidewall size or vehicle; `How to avail?` answers purchase process first;
    availability may still use a reviewed promo as a concrete entry. A promo
    gallery may support a generic entry when useful, but cannot replace the
    answer/discovery step or displace a required non-promo surface. This remains
    model-owned; no free-text keyword router or deterministic promo insertion
    was added.
  - Prepares one consistent displayed-product set for the initial long-form
    price list, square image gallery, tracked product buttons, metadata, and
    delivery fingerprints. Cards without a trusted image are excluded rather
    than borrowing or reusing another card's image. Exact product refs remain
    in the existing tracked buttons.
  - Keeps the complete price list beside the initial gallery. Suppression is
    allowed only for an exact repeat of an already delivered/evaluated
    list-and-gallery presentation with identical stable card identities.
  - Keeps the first-TPP reviewed warranty gallery as the visual replacement for
    the long warranty/inclusions spiel. The renderer suppresses that old spiel
    only when the warranty card has a trusted image, a valid target, and the
    tracked promo-selection action required to render. The structured product
    text and product image buttons remain intact.
- `runtime_v7.service_observations`
  - Clears location-dependent partner/slot evidence after a province change and
    retains only city-compatible evidence after a city correction.
  - ManyChat delivery pacing: in live send modes, rendered text bubbles can be
    sent as separate `sendContent` calls with a short delay between text-to-text
    bubbles. The policy is owned here, after rendering and before tagging, and
    is controlled by `RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MS` (default `1200`, set
    `0` to disable) and `RUNTIME_V7_MANYCHAT_BUBBLE_DELAY_MAX_MESSAGES`
    (default `6`).
  - Session-busy behavior: returns explicit `session_busy_retry_later`, leaves
    response content empty, skips state save, and still persists a debug trace
    row through the analytics gateway when configured.
  - State: reads/writes `strategy_state.runtime_v7`,
    `strategy_state.channel_conversation_history_v1`, and
    `strategy_state.inbound_events_v1`; reads/writes session lock metadata via
    the session gateway. Follow-up sends additionally read/write
    `strategy_state.runtime_v7.followup`. Human handoff requests are stored at
    `strategy_state.runtime_v7.human_handoff_state`; the same state suppresses
    later chat ingress and proactive follow-ups even before channel tags are
    reloaded.
  - Channel refresh identity: when ingress supplies a provider message/event
    ID, only that exact ID can prove the current inbound is already cached.
    Equal text under a different ID is a new event and must refresh; text-only
    ingress remains refresh-first because repeated replies are ambiguous.
  - Trust boundary: should not interpret customer commerce intent itself; it
    wires the harness, identity, persistence, delivery, and replay.
  - Primary tests: `test/test_runtime_v7_ingress_trace.py`,
    `test/test_runtime_v7_followup_endpoint.py`.
- `apps/api/routers/gulong.py`
  - FastAPI routing for `/gulong/v7/chat`, isolated tester endpoints, the
    authenticated allowlisted `/gulong/v7/chat/tester/hydrated` probe, and
    `/gulong/v7/followup`.
  - Ordinary tester turns disable channel history for reproducibility. The
    hydrated probe alone enables ManyChat message loading while forcing
    return-only delivery, tester storage, no analytics/profile fetch, and a
    transcript-redacted diagnostic response. That response states the enforced
    `return_only` mode even when downstream delivery metadata omits it.
  - Should stay thin: parse request, wire service, return payload.
  - Inputs: HTTP payload.
  - Outputs: `RuntimeV7APIResult.to_payload()`.
  - Trust boundary: no business logic beyond request normalization.
- `runtime_v7.interaction_resolution`
  - Defines the internal `InteractionEventV1` and `InteractionPacketV1`
    contracts for tracked promo and choice controls.
  - Normalizes provider/server timestamps, derives trusted decision layers,
    sorts and bounds unresolved events, classifies only objective structural
    relations, and returns the legal model-interpretation envelope.
  - Validates `InteractionDecisionV1` event refs and interpretation legality.
    It does not decide whether the customer corrected, compared, accepted, or
    needs clarification.
  - Reads no external provider and owns no durable storage. API Runtime V7
    persists validated event records in the existing promo/choice histories.
    `SessionsGateway` also maintains a bounded pre-lock interaction inbox so a
    composing turn can see a newer button request before ManyChat transcript
    hydration catches up; the inbox is not commercial/order authority.
  - Primary tests:
    `test/test_runtime_v7_interaction_resolution.py`,
    `test/test_runtime_v7_ingress_trace.py`, and interaction composer tests in
    `test/test_runtime_v7_product_observation_harness.py`.
- `runtime.storage.postgres_runtime_store`
  - Optional Cloud SQL/Postgres store for VM shadow and canary deployments.
  - Implements the existing `SessionStore` and `IdempotencyStore` interfaces
    using compact JSONB tables for user, session, and idempotency records.
  - Inputs: `RUNTIME_POSTGRES_DSN`, `RUNTIME_POSTGRES_SCHEMA`, table names,
    and connection timeout settings from environment variables.
  - Outputs: the same dictionaries consumed by `SessionsGateway` and
    `IdempotencyGateway`; it does not alter customer-facing runtime semantics.
  - State: writes `users_kv`, `sessions_kv`, and `idempotency_kv` by default
    in the configured Postgres schema. CAS session saves and active-turn locks
    remain owned by the session gateway contract. The optional
    `interaction_inbox_v1` field follows the same bounded pre-lock contract as
    Firestore and is preserved across CAS saves.
  - Trust boundary: opt-in only. Firestore remains the default unless the VM
    explicitly sets the Postgres providers and DSN.
  - Primary tests: `test/test_runtime_postgres_store_config.py`.
- `runtime_v7.followup_v2`
  - Active source-separated follow-up case, one-call structured plan contract,
    proactive/customer recovery gates, deterministic semantic validation,
    exact benefit/CTA rendering, promo-brand authority, and bounded attempt
    ledger helpers.
  - Inputs: fresh compact transcript, evidence-linked customer facts, trusted
    profile fields, lead qualification, delivered product presentations,
    selected product/service refs, and prior version-2 attempts.
  - Outputs: a compact prose prompt, parsed `send|defer|suppress` plan, one
    validated focus field, deterministic customer message, evidence refs, and
    durable attempt transitions. Invalid output suppresses; there is no generic
    fallback or sales-permissive override.
  - State: pure helpers do not write. `runtime_v7.api_runtime` persists
    `sending` before delivery, final status afterward, channel history, inbound
    recovery events, and delivered product-presentation evidence.
  - Trust boundary: model chooses strategy and optional continuity prose.
    Runtime owns commercial wording, current Buy 3 Get 1 eligibility, one CTA,
    delivery, idempotency, and side effects. Raw AWM/Background Signal packets
    are not model-facing truth.
  - `runtime_v7.followup` remains only for compatibility tests and historical
    migration support; it is not the active follow-up execution path.
  - Primary tests: `test/test_runtime_v7_followup_v2.py` and
    `test/test_runtime_v7_followup_endpoint.py`.
- `runtime_v7.channel_renderer`
  - Converts final response units and deterministic surfaces into
    ManyChat-ready text/image messages and `bubble1`, `bubble2`, ... payloads.
  - Owns payment/order/product/service grouping and channel splitting.
  - Keeps deterministic product SKU cards together in one text bubble when
    they fit channel limits, with limit-based fallback splitting for long
    product sets.
  - Sends the warranty/inclusions bubble only once per session, tracked in
    `strategy_state.runtime_v7.product_inclusions_sent` and inferred from
    prior hydrated transcript text for sessions created before the flag existed.
  - Owns channel-safe plain text cleanup for model-authored text: emojis are
    preserved, while HTML and Markdown formatting are converted or stripped.
  - Inputs: turn record with final response units, renderer surfaces, payment
    metadata, images, and runtime final response fallback.
  - Outputs: `RuntimeV7ChannelRender` with response bubbles, content messages,
    images, payment metadata, and text.
  - Trust boundary: can format and insert exact surfaces; should not invent
    product/order/payment/service facts.
- `channels/manychat/*`
  - ManyChat app/client helpers. V7 may use these through the API boundary, but
    correctness must not depend on a successful live ManyChat read.

## Conversation And Trace

- `runtime_v7.conversation_hydrator`
  - Normalizes ManyChat/cache/session/request history into model-facing
    conversation evidence.
  - Owns reset segmentation and adjacent-message age-gap trimming.
  - Inputs: cached channel history, loaded channel history, session messages,
    request history, latest user message, reset flag, age-gap threshold.
  - Outputs: `ConversationHydrationResult` with model-facing prior messages,
    active channel segment, current message, source, cache status, and metadata.
  - State: does not write directly; API runtime persists its active segment.
  - Trust boundary: history is continuity evidence, not validated commercial
    truth.
- `runtime_v7.manychat_message_loader`
  - V7-owned bounded `loadMessages` reader.
  - Filters raw events to compact user/chatbot/human-agent text turns,
    including ManyChat automation turns such as `msgout_default`.
  - Best effort; errors return an error envelope and should not block runtime.
  - Inputs: ManyChat user id, headers/cookies from config, limit, timeout,
    max pages, message age days.
  - Outputs: compact normalized text turns plus loader metadata or an error
    envelope.
  - Trust boundary: transport helper only; automation messages are continuity
    evidence, not validated business facts.
- `runtime_v7.turn_trace`
  - Builds version-neutral inbound event and turn trace structures.
  - Owns replay-eligible event keys, time buckets, flow-context hashes, spans,
    and state snapshots.
  - Inputs: inbound request identity, turn record, delivery/tagging result,
    state save result.
  - Outputs: trace dict with generic component spans and state snapshots.
  - Trust boundary: observability only; traces should not drive behavior.
- `runtime.gateways.sessions_gateway` and `runtime.storage.session_store`
  - Shared session storage/admission boundary used by V7 ingress.
  - Owns active-turn lock acquire/release and CAS-aware session save support.
  - Keeps Runtime V7 on a stable dictionary state contract while the Firestore
    adapter dual-reads legacy nested maps and schema-versioned canonical JSON.
    Full writes select one configured representation and atomically remove the
    other; narrow lock/inbox merges preserve both until the next full save.
  - Inputs: user id, session id, lock owner, lock TTL, expected session update
    state.
  - Outputs: lock acquire result, lock expiry, loaded/saved session docs.
  - Trust boundary: concurrency and persistence only; no business intent
    interpretation.
- `runtime.storage.firestore_transport_probe`
  - Authenticated staging-only diagnostic using generated 40 KB or 140 KB
    state and the exact Firestore CAS boundary without model calls.
  - Inputs: bounded warmup/round counts and an allowed generated payload size.
  - Outputs: aggregate latency plus content-free begin/commit RPC, retry,
    process, and cleanup evidence.
  - The representation probe compares one identical runtime-shaped logical
    state as nested map, canonical JSON text, and deterministic gzip JSON. It
    reports application encoding separately from CAS time and verifies decoded
    equality, content hash, revision, stale-CAS rejection, and cleanup.
  - Its configured-format canary first seeds the opposite supported format,
    verifies the deployed reader can decode it, switches the same document,
    checks obsolete-field deletion, proves stale CAS cannot mutate it, and
    verifies a new non-CAS session can be created in the configured format.
  - State: writes only uniquely named documents under dedicated collections
    containing `benchmark`, then deletes and verifies absence of those exact
    documents in `finally`.
  - Trust boundary: never reads customer, serving, or evaluator sessions and is
    hard-disabled outside staging/test environments.
- analytics gateway debug-log path
  - Best-effort BigQuery persistence surface for full V7 turn traces.
  - Inputs: request/session identifiers, trace payload, turn record, rendered
    response, delivery result, tagging result.
  - Outputs: debug log row enqueue/flush result through the configured
    analytics gateway.
  - Trust boundary: audit only. Logging failures must not block delivery.

## Model Gateway And Prompt Contract

- `runtime_v7.llm_gateway`
  - LiteLLM `acompletion` gateway for Gemini models, tool loops, response
    formats, usage/cost/cache metadata, and cache fallback behavior.
  - No direct vendor SDK calls elsewhere.
  - Inputs: messages, tool schemas, response format, model config, metadata.
  - Outputs: model message/tool calls, parsed structured output when requested,
    usage/cost/cache metadata, bounded transient-transport retry events, and
    cache guard diagnostics. Follow-up enables one transport retry; other V7
    clients retain their configured retry count.
  - Trust boundary: gateway owns transport and metadata, not prompt policy.
- `runtime_v7.model_contract`
  - Stable policy prompts, final response-unit schema, tool schemas,
    context packet compiler, CTA policy, and domain policies.
  - Keep main tool loop guidance separate from final-composer response format.
  - The promo response contract distinguishes a promo fact requested by the
    latest customer from a provider-authorized proactive promo surface. This
    guides composition completeness only and never authorizes promo claims.
  - A reviewed campaign-catalog no-match cannot deny product-level quantity,
    bundle, voucher, discount, price, or SKU promo facts owned by exact-size
    product search.
  - Product-search contract treats latest-turn explicit brand availability or
    price asks as hard `required_brands` tool arguments unless the same latest
    turn explicitly accepts unnamed alternatives; `preferred_brands` is only
    soft presentation/ranking context.
  - Product-search schema preserves explicit rim suffixes such as `ZR21` and
    commercial `R14C` so model-chosen tool args keep the customer's actual tire
    size.
  - The always-exposed `present_serviceable_location_choices` tool asks the
    model to decide semantically whether province selection is a viable next
    step. It explicitly separates contact channels, delivery/order context,
    concrete locations, and existing partner selections from broad discovery.
    Durable installation state without a usable area adds a non-ranked
    eligibility candidate. A successfully delivered product-card presentation
    can also add that conditional candidate for a later low-friction move;
    hidden/failed presentations, delivery state, and resolved locations do not
    qualify. Neither path forces a tool call or funnel stage.
  - Inputs: latest message, AWM, signals, observations, readiness, capability
    profile, renderer refs, request time.
  - Outputs: cacheable system prompt sections, dynamic context packet, tool
    schemas, response-format models.
  - Trust boundary: policy/context must remain decision-supportive, not a
    hardcoded script.
- `runtime_v7.runtime_harness`
  - Main model-led tool loop and state orchestration.
  - Guided location selection uses normal model-owned `tool_choice=auto`;
    deterministic code validates delivery, resolved-location, prior-choice,
    one-decision-layer, and renderer safety invariants after the model chooses.
  - Restores AWM/signals/observations/order state, builds capability profile,
    executes tool calls, records spans/results, runs final composer, updates
    memory and tagging.
  - Normalizes structured order-tool arg aliases before order validation. This
    accepts equivalent model-emitted fields and checkout metadata IDs without
    parsing raw customer text or making intent decisions.
  - Applies a bounded typed semantic authorization to each proposed province
    choice surface and can run the same decision once after a no-tool main-loop
    result. Structured state guards fail closed before provider execution; no
    raw-text location phrase list is used.
  - Final composer context exposes service action state, including whether a
    current-turn service tool result exists. The composer may use this to drop
    ungrounded draft service availability claims without phrase-based response
    mutation.
  - Gives the final composer a compact customer-visible surface manifest. It
    lists renderer-owned roles and optionality but never grants facts or copies
    complete renderer bodies. The accompanying voice contract asks for
    purposeful complete-turn prose around those surfaces.
  - Applies unsupported product-pricing checks to structured model text before
    deterministic surface insertion. Renderer-owned price and promo rows stay
    outside that audit; the legacy prose path keeps its whole-response guard.
  - Runs typed claim-allowlist validation only when the turn plan actually
    supplies authorization keys. An explicit empty allowlist remains a deny-all
    contract; an absent feature-off contract is not converted into one.
  - Compiles one required customer-choice surface per turn. Product choices
    precede prepared location or checkout controls; a validated negative promo
    focus can instead make the reviewed alternatives gallery active. Other
    valid surfaces are deferred rather than deleted.
  - Reconciles promo-gallery negative matches with product-search
    `/promo_brands` evidence before choosing the active promo or product
    surface. This keeps source authority separate from conversational wording.
  - Compacts answer-only FAQ/contact composition to current answer authority and
    conversational continuity. Mixed product/service/order turns keep the full
    context packet.
  - Pure payment-policy turns with one complete typed provider claim per result
    bypass stochastic prose composition and render only contract-validated
    provider facts. Mixed turns retain normal composer ownership.
  - A transient `location_response_status=unavailable_now` can advance an
    established product path to a reviewed contact fallback only when location
    and contact remain missing and no grounded tool/action competes.
  - Retries one empty or JSON-structured but non-renderable main-model result
    before falling back. Ordinary prose is not intercepted and continues to
    use the existing renderer-duplication and service-presentation repairs.
  - Keeps province-level ranked slot previews as scoped schedule evidence while
    marking the customer's requested schedule obligation `pending_validation`
    until a city is selected. This prevents a safe city-choice answer from
    failing composition or implying province-wide slot availability.
  - Sends semantic answer-goal and promo-fact failures directly through one
    evidence-only repair and one independent re-audit. A remaining failure uses
    the authored safe fallback; mechanical contract repair and invalid-schema
    retries remain separate.
  - Keeps an authored answer in semantic fallback when the initial audit found
    its goal relevant, even if the repair audit later disagrees about
    implication. An initially misaligned FAQ remains omitted.
  - Registers successful promo-search offer refs in the same canonical claim
    evidence set consumed by both composer and validator. Payment-request
    evidence likewise declares both payment and order claim categories.
  - Compacts an empty campaign-catalog result with an explicit cross-provider
    boundary: state the scoped result, keep product-promo price/applicability
    pending, and request exact size instead of emitting a global denial.
  - Inputs: latest user message, optional images, conversation history,
    restored harness state, profile fields, request time.
  - Outputs: turn record, final response units, tool results, observations,
    memory/signals/readiness updates, usage/cost, tagging.
  - State: owns the runtime_v7 strategy-state shape exported by API runtime.
  - Trust boundary: orchestrates tool calls but should not bypass tool/action
    validation.

## Memory, Signals, And Intake

- `runtime_v7.memory`
  - Active Working Memory model/fallback generation and compact state.
  - Tool-backed turns take the deterministic evidence-only path, which skips
    the memory model and records customer/human-agent context plus stable refs.
    Toolless turns may still use the model compactor for conversational nuance.
  - Descriptive only; not a policy or commercial-fact source.
  - Inputs: prior memory, latest message, recent turns, advisory signals,
    observation refs, external evidence refs.
  - Outputs: short AWM narrative and diagnostics.
  - Trust boundary: may preserve refs and intent, not exact commercial claims.
- `runtime_v7.state_signals`
  - Public background-signal orchestration API.
  - Aggregates content-free usage metadata across every returned extraction
    attempt. Invalid response content is discarded; attempts that fail before
    usage is observable remain explicitly unmetered in promotion telemetry.
  - Keeps Buy 3 Get 1 interest as `promo_types=buy3get1` without promoting the
    offer mechanics into a durable customer quantity. The product tool uses a
    four-tire search/presentation path for this promo; `quantity=4` becomes a
    customer/order signal only when the customer separately states or selects
    four tires.
- `runtime_v7.state_signal_model`
  - Model-primary extraction prompt/client.
  - Should interpret latest turn in context; avoid direct keyword-slot
    extraction patterns.
  - Extracts latest-turn explicit brand availability or price asks into
    advisory `required_brands` candidates so the main model receives context
    consistent with the product tool contract.
  - Inputs: latest customer turn, AWM, recent turns, previous signals,
    observation refs, external evidence.
  - Outputs: candidate facts with source/confidence/status for normalization,
    including order-payment components such as payment method, payment bank,
    and installment term when the customer has actually chosen that route.
  - Trust boundary: extraction is advisory and must pass normalization.
  - Generic store/location objects being asked about are not treated as the
    customer's own location unless a concrete customer place is supplied.
  - When a requested installation/delivery location cannot be supplied yet,
    emits only the transient closed
    `location_response_status=unavailable_now` semantic signal. It is not a
    location value, lead field, or durable fact.
- `runtime_v7.state_signal_normalization`
  - Deterministic normalization/canonicalization of extracted candidates.
  - Owns schema validation, advisories, and canonical projections.
  - Inputs: model candidates, prior ledger entries, canonical values provider,
    tool observations.
  - Outputs: normalized signals, diagnostics, ledger-ready entries, compact
    model-facing projections.
  - Trust boundary: can reject/clarify/canonicalize candidates, but should not
    invent customer intent.
  - `question_only`, `conditional`, `historical`, and rejected relations remain
    visible as context but are excluded from lead/order completeness.
  - Contact-number candidates must have a structurally valid Philippine mobile
    shape; free-form contact questions cannot become confirmed phone facts.
  - Canonicalizes `location_response_status` through a closed allowlist; the
    signal remains `question_only`, unsafe for action, and excluded from
    qualification/readiness.
- `runtime_v7.state_signal_schema`
  - Candidate field names and schema-level extraction descriptions.
- `runtime_v7.state_signal_ledger`
  - Signal carry-forward with provenance and freshness.
- `runtime_v7.preturn_intake`
  - Joined intake helper for memory/evidence/context work before model context.
- `runtime_v7.image_evidence`
  - General image/OCR intake for product, service, order, and payment evidence.
  - Produces external evidence refs and advisory candidates; not trusted action
    facts by itself.
  - Extracts visible source ownership and Gulong surface type in the same
    existing model call. Gulong product, cart, checkout/payment, order-page,
    and order-email surfaces produce routing-only
    `website_inquiry_evidence`; marketing assets remain unvalidated
    product/image context and cannot authorize Website Inquiry routing. An
    OCR-discovered Gulong URL alone is also product context, not routing proof.
- `runtime_v7.conversation_evidence`
  - Harness-level conversation evidence for stored/human-agent turns.

## Product Domain

- `runtime_v7.product_search`
  - Product search, brand buckets, fitment extraction, exact-size behavior,
    visibility filtering, promos, ranking, and deterministic product surfaces.
  - Validates every product URL slug against structured pattern/model identity.
    A mismatch suppresses only the link, records card-level and aggregate
    telemetry, and retains the grounded product, price, image, and selection
    surface. Matching links and abbreviated model slugs remain supported.
  - Preserves `/shop` catalog image URLs after an HTTPS host allowlist check and
    carries them into renderer cards. Image metadata never overrides structured
    price, promo, availability, fitment, or product-ref evidence.
  - When a multi-product selection contains an image-less card, prefers a
    replacement from the already fetched, query-filtered ranked image-backed
    pool. It performs no additional provider or image calls, never relaxes the
    customer's hard filters, and leaves single exact-product behavior intact.
  - A promo_only request emits source-backed promo evidence and must not fall
    back to cards which failed the active promo eligibility constraint; those
    products remain diagnostic candidates only.
  - Broad full-tire-size presentation is a customer-choice ladder: when no
    required brand, budget, promo, model, category, availability, origin,
    terrain, warranty, or installment constraint is active, cards are selected
    by price tier from premium to budget and may expand to four cards to show
    the tier spread. Soft `preferred_brands` from remembered state do not
    disable this ladder; they only rank representative products inside each
    tier. For the Premium tier, Michelin remains the preferred representative
    when available unless the request has a hard explicit brand constraint such
    as `required_brands`.
  - Required brands are a hard requested-brand surface with matched and missing
    status; preferred brands remain soft ranking context and do not prove
    requested-brand availability.
  - Requested-brand status is scoped to the active requested size/filter set:
    a requested brand found only in broader fallback pools is reported as
    `missing` plus `available_outside_requested_filters`, so the model can say
    the exact brand/size is unavailable while still offering grounded
    alternatives.
  - Fitment extraction uses normalized vehicle context from Background Signals
    where available, strips trim/year noise before the compatibility endpoint,
    preserves the raw query for trace/debug, and returns a deterministic
    candidate-size presentation surface when candidate tire sizes exist.
  - Vehicle canonicalization shared with Background Signal normalization keeps
    stored `car_make_model`, model context, tool args, and `/car_tire_sizes`
    params aligned for known aliases such as Mitsubishi Mirage G4.
  - Concrete tire-size signals, including sidewall OCR sizes such as `185R14`
    or `195R14C`, anchor product search. They prune fitment-discovery exposure
    for that turn so vehicle candidate sizes do not override the visible
    sidewall size.
  - Inputs: model tool args plus hydrated trusted/advisory context such as tire
    size, brand, model/pattern, budget, promo, quantity, vehicle/rim clues.
  - Outputs: compact product headers, full trusted result, observation refs,
    presentation refs, deterministic card surfaces, query basis diagnostics,
    and card-level warranty/Tire Protection Plan fields for renderer summaries.
  - State: product observations and presentation refs are stored by the harness.
  - Trust boundary: customer-facing product cards must be exact-size/customer
    catalog visible unless explicitly labeled otherwise.
- `runtime_v7.product_observations`
  - Stores trusted product observations and presentation refs, including the
    validated image URL through compact and selected-product projections.
- `runtime_v7.product_visibility_denylist.json`
  - Customer-facing visibility denylist until a trusted visibility API/field is
    available.

## Service Domain

- `runtime_v7.service_tools`
  - Service-facing tool wrapper for partner lookup, slot lookup, slot
    validation, and add-ons.
  - Owns service observations, slot presentation surfaces, and no-walk-in
    policy insertion. Area-only partner lookup rows are internal coverage proof
    when slot lookup is the recommended next step; grouped slot cards and
    schedule CTAs are the preferred customer-facing surface.
  - Inputs: location, selected/candidate product refs, tire size, quantity,
    service type, schedule candidates, partner refs, addon names.
  - Outputs: partner/slot/addon observations, area-only or slot presentation
    refs, policy notes, validation results.
  - Trust boundary: partner/slot lookup is read-only until order submission;
    slot validation can say available/selected but not booked/reserved.
- `runtime_v7.installation_partners`
  - Partner lookup, geographic ranking, compatibility handling, and
    presentation groups.
- `runtime_v7.installation_slots`
  - Slot date/time lookup and normalization helpers.
- `runtime_v7.location_resolution`
  - Location normalization, geocoding, ambiguity, and carry-forward support.
- `runtime_v7.service_observations`
  - Stores trusted service observations and presentation refs.
- `runtime_v7.transaction_choices`
  - Projects trusted slot, quote, and checkout metadata into bounded schedule,
    payment-option, and payment-method choices.
  - Owns the shared explicit-change detector used by API presentation
    suppression and final-composer consistency guards.
  - It performs no API fetches or state mutation. Exact click validation remains
    in the API/service boundary.
- `runtime_v7.choice_actions`
  - Encodes and parses compact product, category, location, schedule, payment
    option, and payment method tokens for the shared ManyChat router.
  - Tokens are references only; delivery history is the authorization allowlist.
- `runtime_v7.fulfillment_aliases`
  - Normalizes common customer words such as shipping/delivery/pakabit into
    advisory fulfillment aliases.

## Order, Payment, And Policy

- `runtime_v7.order_state`
  - Order readiness, quote, summary, payload build, submit order, order details,
    payment request, and payment proof matching.
  - Side effects must pass through validated payload refs.
  - Inputs: selected product refs, quantity, customer/contact fields,
    fulfillment, service observation refs, schedule, payment selection,
    submitted order refs, payment proof evidence refs.
  - Outputs: readiness state, quote breakdown, deterministic order summary,
    validated `{data, newCartItems}` payload ref, submit result, order details
    readback, payment request surface, payment proof match result.
  - State: stores quote/summary/payload/order/payment refs in harness state.
  - Trust boundary: summary can be incomplete and conversational; submit can
    only use a validated payload ref. Generic installment payment cannot submit
    until bank and installment term are known.
  - Transient signal relations cannot populate fulfillment, customer location,
    payment, or other order-readiness fields.
- `runtime_v7.order_canonicalization`
  - Central checkout metadata, transaction, payment, customer source, and
    submit-value canonicalization. Active /payment/list metadata is the
    authority for payment method, bank/term, brand allow-list, disabled, and
    transaction-exclusion facts; model values are proposed lookup inputs.
  - Used with runtime-harness arg alias normalization so order summary and
    payload tools share checkout labels and metadata IDs. Summary and payload
  boundaries should preserve canonical payment terms such as
  `Credit card installment (BPI 6 months)`.
- `runtime_v7.channel_renderer`
  - Enforces qualification-surface priority, renders one schedule card per day,
    and renders optional checkout controls without allowing model-authored card
    facts.
- `runtime_v7.transaction_choices`
  - Owns the shared one-primary-decision contract plus deterministic schedule,
    Pay Now/Pay Later, and payment-method choice surfaces.
  - Multiple visible product cards defer service/checkout controls. Schedule
    cards show distributed morning choices and one afternoon control. That
    control binds to the earliest delivered afternoon slot when one exists;
    otherwise it records a truthful, unvalidated `12:00 PM` preference.
    Malformed times are never silently classified as morning.
- `runtime_v7.order_state`
  - Separates summary readiness from submit readiness. A customer-authorized
    flexible schedule may appear in the deterministic review summary, while
    `submission_blockers` keep payload creation behind exact service-slot
    validation.
- `runtime_v7.checkout_plan`
  - Compatibility/resolver layer for selected product, fulfillment, schedule,
    and payment planning across summary/payload stages.
  - Inputs: order context and candidate selections.
  - Outputs: compatibility verdicts, blocking issues, advisory notes, and
    canonical selections.
  - Trust boundary: validates selected product and fulfillment against active
    checkout metadata without boxing the model into a single customer-facing
    CTA. It does not use static brand/bank rules as commercial authority.
- `runtime_v7.delivery_payment_policy`
  - Static delivery/location policy helper only. Payment and installment facts
    are resolved from active checkout metadata through faq_tools and order
    canonicalization, preventing static checkout-policy drift.
- `runtime_v7.product_search` installment presentation
  - Reconciles every product card against active checkout `/payment/list`
    metadata before rendering; this is not conditional on the model requesting
    an installment filter. Current bank/term and brand eligibility replace
    `/shop` installment fields, including an authoritative empty result.
    Product-catalog installments remain only as an availability-failure
    fallback when checkout metadata cannot be read.
- `runtime_v7.contact_policy`
  - Business contact response policy and assigned-agent contact resolution.
- `runtime_v7.faq_tools`
  - Product/service/order FAQ retrieval from static/RAG-like FAQ source, with
    payment-policy answers dynamically grounded in active checkout metadata.
  - Generic installment questions project all current, brand-applicable terms
    rather than selecting the first checkout row. Bank/provider associations
    are included only when supplied by that metadata; specifically named banks
    or terms retain narrow lookup behavior.
  - Maps down-payment/deposit wording to current reservation-fee guidance in an
    active tire-order context without inventing an amount. General how-to-order
    requests are intentionally excluded from the legacy FAQ set and remain in
    the model-led in-chat sales flow.
  - Treats official receipts, invoices, and quotations as transaction-document
    questions, never as payment-method names. Compound payment/document turns
    keep the two answer scopes separate.
  - FAQ tools supplement but should not dominate actionable product/service
    turns.
  - Owns FAQ retrieval disambiguation, including suppressing the review/
    feedback FAQ when "review" refers to reviewing an order summary.
  - Named payment lookup arguments come only from the typed semantic payment
    signal. Unknown methods receive a concise answer plus a bounded sample of
    current active alternatives; arbitrary customer prose is not interpolated
    as a payment-method name.
  - Broad payment-method questions expose a compact customer-facing category
    projection derived from active checkout rows. The projection improves
    composition readability but does not replace exact method, bank, term,
    brand-eligibility, or payment-path evidence for specific questions.
  - Pre-composer compound-query completion consumes an existing typed payment
    decision or a payment-scoped FAQ result. It does not run a semantic
    payment classifier on unrelated product, location, promo, or FAQ turns.
- `runtime_v7.runtime_harness` supporting warranty presentation
  - Only a successfully renderable reviewed warranty surface counts as already
    presented. Failed, empty, or suppressed promo calls do not block automatic
    search and presentation of the approved Double Warranty catalog asset.
    Grounded inclusion text remains the fallback when no reviewed surface can
    render.
- `runtime_v7.tagging`
  - Passive tag derivation and ManyChat tag application result handling.
  - Uses trusted selected-product context rather than mere product-presentation
    visibility when deriving the selected-product signal.
  - Gives Website Inquiry exclusive priority over Moderate/High Intent for a
    current validated website turn and for later turns where that contact tag
    already exists. Image-origin Website Inquiry requires an explicit routable
    Gulong surface; marketing-image OCR or a visible Gulong URL alone cannot
    enter this routing boundary. Operational tags remain independent. Actual
    CS assignment remains owned by the downstream ManyChat routing flow.
  - Emits a versioned analytical Moderate qualification independently from
    routing tags. At API trace persistence it is enriched with durable
    event/idempotency, environment, user/session/turn, occurred-at, signal,
    evidence-ref, and tag-application context; reporting deduplicates its
    `qualification_event_id` rather than treating routing tags as the count.
  - Analytical qualification records carry `decision_mode` and `rule_version`
    copied from the lead-qualification snapshot. Older snapshot shapes fall
    back to `decision_mode="deterministic"` and
    `INTENT_RULE_VERSION="gulong_intent_v2_20260811"`; these fields are lineage
    metadata and do not change qualification level or countability.
  - Keeps tracked choice and promo presentation/card/surface/choice refs as
    correlation metadata. A promo fallback ref identifies the catalog card only
    and is never evidence that a specific presentation reached the customer.
  - Converts only a successful typed `request_human_handoff` tool result into
    `Stop Chatbot`. Customer prose alone is not a deterministic handoff trigger.
- `runtime_v7.lead_qualification`
  - Lead-stage completeness and fast-lane triage for incomplete low-complexity
    turns.
  - Counts only current asserted/selected/corrected facts; questions,
    hypotheticals, and historical values do not satisfy Moderate fields.
  - `LeadQualificationSnapshot.to_dict()` exposes deterministic lineage fields
    `decision_mode="deterministic"` and
    `rule_version="gulong_intent_v2_20260811"` without changing the existing
    Moderate predicate.
- `runtime_v7.triage_seeds`
  - Typed advisory context for exact, approved automated starter controls.
    Its reusable control-label boundary accepts only known leading checkmark
    platform decoration (including variation selectors) plus the exact label;
    ordinary customer prose and compound messages remain model-owned.
  - A bare `Get Started` control means begin shopping, not an order-process
    request. The model still composes the complete welcome, next step, and any
    supported surface; the seed cannot prescribe a fixed CTA or commercial fact.
    When the model selects the reviewed promo catalog, it calls and renders it
    in the same turn rather than asking whether the customer wants to see it.

## Capability And Canonical Data

- `runtime_v7.capability_profile`
  - Tool exposure profile from signals, readiness, observations, and cues.
  - Tool exposure is not a model instruction to call every exposed tool.
  - Inputs: normalized signals, observations, readiness, retrieval telemetry,
    and safe default domains.
  - Outputs: selected domains, exposed tool names, capability diagnostics.
  - Trust boundary: exposure should enable possible actions, not decide intent.
  - Production supplies no product/service/order fallback domain. Normalized
    signals and trusted refs select those surfaces; general tools and bounded
    `request_capability` recovery handle initially unclassified turns.
  - Concrete service tools require normalized city/province/landmark precision.
    Generic model-proposed location nouns expose only the general semantic
    location-choice capability.
  - The harness has one bounded recovery for a compound turn where the main
    model selects a registered read-only tool from an unexposed product,
    service, or order domain. It recompiles the real schema while preserving
    active domains; unknown tools, mutations, and repeated expansions remain
    guarded. This is capability recovery, not direct execution authority.
  - Explicit `request_capability` recompilation also receives one bounded
    replacement round, including when the ordinary tool-round cap is one, so
    exposing a missing schema cannot consume the only execution opportunity.
- `runtime_v7.model_contract.build_tool_objectives`
  - A complete tire size without a current brand/category preference no longer
    means promo-first. Concrete option, availability, or price requests use
    `product_search`; broader narrowing can use brand/price buckets. Promo
    search is supporting only when the customer actually asks about promos,
    and a promo-only result cannot complete the primary product objective.
- `runtime_v7.tool_capabilities`
  - Registry of tool capability requirements and exposure hints.
  - Exposes `request_human_handoff` as a general mutation-capable model action
    on every normal turn. The harness result records requested state while
    keeping `human_assignment_confirmed=false` until downstream evidence exists.
- `runtime_v7.state_signal_model`, `state_signal_normalization`,
  `state_signal_ledger`
  - The extractor proposes typed relations; normalization applies retractions
    and corrections; the ledger persists only durable positive relations.
  - Read-only conditional/question scope remains visible in the current context
    without becoming reusable checkout, order, or follow-up state.
- `runtime_v7.canonical_values`
  - Lazy canonical metadata provider for checkout, brand/category, location,
    and business-value lookups.
- `runtime_v7.brand_knowledge`
  - Reads the active Firestore brand publication.
  - Resolves exact About Brand actions and bounded semantic comparisons.
  - Keeps narrative retrieval separate from structured warranty authority.
- `runtime_v7.business_identity`
  - Supplies one reviewed, cacheable operating identity to the main model and
    final composer: online-first tire shop, Makati head-office installation
    site, warehouse-to-booked-site fulfillment, and the approved over-100
    partner brand claim.
  - Exposes a versioned evidence ref under `business_identity_facts` in every
    typed final-composer plan, including mixed-intent turns.
  - Does not authorize exact coverage, nearby availability, partner identity,
    stock, schedules, prices, promos, payments, or order state. It makes the
    head-office installation fact available when relevant; it does not require
    the model to surface or promote it.
- `runtime_v7.model_contract.COMPLETE_TURN_COMPOSITION_PROMPT`
  - Gives the main model and final composer the same customer-visible sequence
    contract across plain-text, mixed-intent, and deterministic-surface turns.
  - Connects acknowledgements and lead-ins to the latest customer context,
    keeps post-surface CTAs on the active sales stage, and prevents detached
    branding or policy fragments.
- `scripts.brand_knowledge_sync`
  - Fetches and validates Gulong.ph brand directory/detail pages.
  - Embeds background and warranty chunks, writes an immutable version, and
    atomically activates it only after a complete successful build.
  - Intended for daily Cloud Run Job execution and on-demand synchronization.

## Qualification CTA alignment

- `runtime_v7.transaction_choices.qualification_primary_decision`
  - Selects product choice as the active response decision when multiple exact
    product refs are visible.
- `runtime_v7.lead_cta`
  - Converts that shared decision into model-facing reasoning context instead
    of independently promoting the next missing lead field.
- `runtime_v7.channel_renderer`
  - Preserves deterministic product cards and controls and can suppress a
    competing unsafe decision. A valid final-composer turn owns the natural
    transition and CTA; deterministic CTA copy is reserved for legacy/failure
    fallback.
- The boundary uses presentation refs and choice counts. It does not maintain
  brand-, SKU-, or promo-specific CTA rules.

## Current Test Surfaces

- Full V7 regression:
  `pytest $(rg --files test | rg "test_runtime_v7") -q`
- API ingress/history/idempotency:
  `pytest test/test_runtime_v7_ingress_trace.py -q`
- Live model pack docs:
  `docs/RUNTIME_V7_LIVE_MODEL_TEST_PACK.md`
- Complete-turn human response evaluation:
  `test_packs/runtime_v7_human_response_eval_pack.json` supplies varied,
  de-identified scenarios; `scripts/runtime_v7_human_review_bundle.py`
  converts approved or pre-redacted probe/debug artifacts into minimized structural evidence
  and blank orchestrator review forms. It is offline tooling and is not imported
  by the deployed runtime.
- First-turn intro endpoint probe:
  `python scripts/runtime_v7_first_turn_intro_endpoint_probe.py --base-url <runtime-service-url> --pack test_packs/runtime_v7_first_turn_intro_live_pack.json --scenario <scenario_id>`
