# Runtime V7 Product And Service Slice Implementation Note

Runtime V7 is currently an isolated product-search and service-availability
tool-loop slice. It is not the production chatbot runtime yet.

## Documentation System

Runtime V7 documentation is now routed through
`docs/RUNTIME_V7_DOCUMENTATION_INDEX.md`. Use that index before adding another
standalone note or appending to this file.

This implementation note remains the long-form narrative for detailed
product/service/order behavior. It should not be the only place where Runtime V7
changes are recorded. Significant behavior changes still need a dated entry in
`docs/IMPLEMENTATION_NOTES_RUNTIME_V2.md`; component ownership changes belong
in `docs/RUNTIME_V7_COMPONENTS.md`; architecture/state-flow changes belong in
`docs/RUNTIME_V7_ARCHITECTURE.md`; durable decisions, learnings,
anti-patterns, parked ideas, and pending gaps belong in
`docs/RUNTIME_V7_DECISIONS_AND_GAPS.md`.

Runtime V7 contributors should follow `runtime_v7/AGENTS.md`, which defines the
local documentation update contract and the current good/bad implementation
patterns.

## Active Working Memory

Active Working Memory is the short, always-loaded narrative summary of the
current conversation. It preserves intent, nuance, unresolved goals, and
confirmed versus unconfirmed details. It should stay decision-oriented and
compact, not become a transcript.

The memory updater may use a lightweight model, but deterministic seed memory is
kept as fallback. Missing-info signals, background signals, order readiness, and
tool observations are not part of memory; they are separate context-packet
sections.

The memory generator evidence packet may include advisory background signals,
latest product-observation refs, compact normalized product-search query basis,
and external evidence refs. Background signals are awareness hints, not forced
truth. Product facts should be remembered only by `observation_ref` /
`presentation_ref`; exact prices, promos, stock, installment facts, DOT,
warranty, and URLs must be retrieved from the stored observation or refreshed
through tools.

Human-agent and customer-provided images are handled the same way. If a human
agent sends a pricelist image, or a customer sends an order screenshot with
product, discount, total, installation partner, or payment details, memory may
remember an `evidence_ref`, source, media type, summary, and validation status.
It must not turn screenshot-extracted commercial details into trusted memory
facts. Future OCR/vision/order parsers should convert those images into
validated tool/state evidence before action.

## Image Evidence Intake

Runtime V7 now has a product-slice image evidence boundary in
`runtime_v7.image_evidence`. The harness detects likely image URLs from the
latest customer message, including Facebook redirect URLs, and can call a
LiteLLM/Gemini vision extractor to read visible tire sidewalls, vehicle photos,
website product cards, conversation screenshots, order screenshots, and payment
proofs.

The image path produces two outputs:

- External evidence refs for memory and context. These refs include validation
  status, media type, summary, and compact extracted field names.
- Advisory background-signal candidates for facts such as tire size, vehicle,
  product-card brand/model, or payment method when OCR confidence is high.

Image-derived candidates use source `external_evidence`, status
`external_evidence_unvalidated`, and model-facing `requires_validation=true`.
The older internal `safe_for_action=false` metadata may still appear in stored
diagnostics for backward compatibility. Image evidence may guide product
discovery or clarification, but it must not authorize order, payment,
reservation, schedule, fulfillment, price, promo, stock, discount, or total
claims without a trusted tool/state validation path.

Conversation screenshots use image type `conversation_screenshot`. The OCR
contract preserves visible message snippets, human-agent-looking snippets,
promo terms, discount text, and timestamps when visible. These snippets are
supplementary continuity context only. Even when a screenshot appears to show a
human-agent message, the resulting evidence remains `requires_validation=true`
for guarded actions, and pricing, discount, order, payment, reservation,
schedule, or fulfillment details still need tool/runtime-state validation.

## Human-Agent Conversation Hydration

Runtime V7 can hydrate stored customer/chatbot/human-agent conversation messages
before the Runtime V7 model call through `runtime_v7.conversation_evidence`.
The hydrator normalizes text messages into prompt-facing `recent_turns` and
adds compact refs for human-agent messages with source `human_agent_history`.

Human-agent messages are trusted conversation-continuity context. They can carry
current customer preferences, agent-stated next steps, and business info into
the context packet, Active Working Memory evidence, and model-owned background
signal extraction. The signal extractor may emit candidates with source
`human_agent_history`, which normalize to status `human_agent_context` and
`requires_validation=true` for guarded actions.

This keeps the chatbot able to continue from a human-handled thread without
restarting the inquiry, while still requiring product/order/payment/schedule and
fulfillment validation before real-world actions.

## API Ingress Channel History

The deployable Runtime V7 API has a separate ManyChat/channel-history hydration
boundary in `runtime_v7.conversation_hydrator`. This boundary runs before the
harness turn and is responsible for building model-facing conversation evidence
from these sources:

- Fresh ManyChat `loadMessages` output when the current inbound message is not
  already present in the Firestore channel-history cache.
- The Firestore channel-history cache stored under
  `strategy_state.channel_conversation_history_v1`.
- Stored Runtime V7/session messages and optional request-supplied history in
  tester/debug paths.

The cache is an optimization and replay aid, not the source of business truth.
It stores normalized text turns with role, content, message id, timestamp,
sender, and source. Product, service, order, payment, and schedule facts still
need the normal Runtime V7 tool/state validation paths before they can drive
guarded actions.

Reset behavior is segment-based. When a request uses `reset=true`, Runtime V7
does not hydrate older channel or session messages into the model-facing
history. After the reset turn is delivered, the runtime persists a new
channel-history segment containing only the reset customer message and the
assistant reply. The next request with `reset=false` hydrates from that new
segment and does not merge the older pre-reset messages back in.

Stale-history behavior is also segment-based. The message-age boundary is not
"30 days from the current request time." Runtime V7 walks backward from the
current or latest channel message and stops when the gap between adjacent
messages exceeds `RUNTIME_V7_MANYCHAT_MESSAGE_AGE_DAYS` (30 by default).
Messages before that old gap are excluded from the model-facing history and
from the persisted segment after the turn, even when they still exist in the
raw ManyChat transcript or older Firestore cache.

The V7-owned ManyChat loader is best effort. Loader failures, incomplete pages,
or timeout budget exhaustion should not block response delivery; the runtime
falls back to the Firestore cache, then to the latest inbound message when no
usable cached history exists. Exact duplicate replay is strongest when the
loader or cache resolves the current ManyChat message id.

## Pre-Turn Intake

The Runtime V7 harness now runs pre-turn context intake through
`runtime_v7.preturn_intake`. Active Working Memory load, latest product
observation lookup, conversation-history hydration, and image evidence
extraction are independent tasks, so they run concurrently and are joined before
the Runtime V7 context packet is built.

This is intentionally not fire-and-forget. The model receives the joined image
evidence, conversation evidence, and timing metadata in the same turn. Probe
records include a `preturn_intake` block with total latency, per-stage latency,
`parallelized=true`, `fire_and_forget=false`, and
`joined_before_model_context=true`.

The current Runtime V7 harness remains synchronous at the public `run_turn`
boundary for local probes, but the intake work inside that boundary is
parallelized. The full production runtime should reuse this joined-pre-turn
shape before calling the single model/tool loop.

## Capability Surface Compiler

Runtime V7 now has a first-pass capability registry and profile compiler for the
product slice. The compiler matches normalized signals, external evidence,
available observation refs, and lightweight message cues to candidate tools,
then derives selected domains from those candidate tools. It does not classify
exact customer intent and does not extract commercial facts from raw text.

For the isolated product-search harness, `default_domains=("product",)` can be
kept to preserve existing product behavior. For the full production runtime
shape, this default should be empty so the surface is selected from normalized
signals, refs, FAQ hints, and `request_capability` recovery instead of silently
defaulting to product. When the product domain is active, the runtime exposes
the read entry tools
`product_search`, `discover_brand_buckets`, and `extract_compatible_fitment`.
Reference/detail tools such as `resolve_product_reference` and
`get_product_details` are exposed only when product presentation refs exist.

`request_capability` is always exposed as a recovery hook. The harness now
supports an internal retry that recompiles the same turn with the requested
product/service domain. Lightweight phrase cues remain advisory only; if a
service cue is present while only product tools are exposed, the runtime can
retry once and ask the model to call `request_capability(service)` or answer
without unsupported service claims.

## Background Signals

Background signals are advisory structured facts extracted from the latest
message, active working memory, recent turns, and visible tool observation
headers.

They are not the primary planning substrate and they are not commercial truth.
The model can use them to reason about the conversation, but guarded actions
must still validate through tools and state.

## Extraction Policy

Runtime V7 uses model-primary extraction when a background-signal model client is
available:

1. Raw customer-message extraction is model-owned. Deterministic code must not
   derive slot/state candidates from customer prose, active memory prose, or
   recent-turn prose.
2. The lightweight model is called under `auto` whenever a model client is
   available, unless the caller forces `never`.
3. The model returns candidate facts only.
4. Runtime normalization, canonicalization, merge rules, and readiness checks
   construct the final `BackgroundSignal` list.
5. If the model call raises, Runtime V7 retries up to two times. If all attempts
   fail, extraction raises an error instead of falling back to deterministic
   raw-message parsing.
6. If the model returns malformed, truncated, or schema-invalid JSON, Runtime V7
   treats that as an extraction failure and uses the same retry path.
7. Candidate values must be non-empty strings or non-empty lists of strings.
   Placeholder objects such as `{}` are invalid because they hide extraction
   failure until normalization.
8. If the model returns candidates but none can be normalized, Runtime V7 treats
   that as an unusable extraction attempt and retries. Empty `candidates` is still
   valid when there are no advisory facts to extract.

Deterministic logic is not a semantic extractor. Its durable role is
normalization, canonicalization, validation, structured context projection, and
readiness projection after the model supplies candidate facts.

## Signal Module Boundaries

The signal layer is split by responsibility:

- `runtime_v7.state_signals`: public orchestration API and compatibility import
  surface.
- `runtime_v7.state_signal_model`: lightweight model prompt, model client, and
  model JSON parsing.
- `runtime_v7.state_signal_fallback`: structured observation projection and
  non-candidate diagnostics only.
- `runtime_v7.state_signal_normalization`: canonicalization, validation, signal
  merge rules, action-safety metadata, and missing-info projection.
- `runtime_v7.state_signal_schema`: shared field lists, constants, and
  `BackgroundSignal`.

## Extraction Diagnostics

Diagnostics no longer inspect customer prose to infer commercial features or
fallback facts. They record that raw-message extraction is disabled, whether the
latest message, active memory, recent turns, and latest product observation were
present, and whether structured observation candidates normalized correctly.

If the model produces candidates that cannot be normalized, the failures are
reported in extraction metadata and the extraction attempt is retried. It must
not recover by parsing the raw message deterministically.

The signal extractor prompt is intentionally compact. It asks for at most eight
deduplicated candidates, prefers latest message over active memory over recent
turns, and avoids repeating recent-turn facts already represented in Active
Working Memory. This keeps follow-up turns from producing long duplicate JSON
that can hide or truncate the actual useful signals.

Negated category preferences are model-signaled instead of phrase-list parsed.
When the customer excludes a category, such as avoiding premium or expensive
options, the extractor should emit `excluded_tire_categories=Premium`. The
product model then turns that exclusion into allowed product-search categories
such as Budget, Economy, and Mid Range when appropriate.

Warranty, comfort, durability, and road-condition wording are not separate
background-signal fields. They stay as product-search soft preferences for the
main product model and tool call.

The extractor prompt carries a few commerce/chat shorthand examples so the
model, not deterministic raw-message code, owns semantic interpretation. For
example, `hm` / `hm po` means "how much" and must not be extracted as Hankook,
while vehicle typo examples such as `wgo` are prompt-level guidance for Toyota
Wigo in fitment context.

Tire-size cleanup still happens after extraction. Previously, `164 60 14`
passed normalization because the normalizer only checked that the section width
looked numeric; it did not apply passenger-metric size sanity checks. Runtime V7
now corrects one-off 5 mm section-width typos when a full metric size is present
(`164/60R14` -> likely `165/60R14`) and records the correction in signal/tool
metadata. Larger nonstandard metric section widths are flagged as suspicious
rather than silently changed. This correction is limited to full passenger metric
sizes with three-digit section width, two-digit aspect ratio, and rim. Flotation
sizes such as `33X10.5R15` are preserved as flotation sizes and are not rounded
to 5 mm metric increments.

## Product Presentation Fallback

Product cards should not disappear just because customer preferences over-
constrain the presentation layer. Runtime V7 keeps strict search/ranking
evidence, but if no product matches all presentation refiners, the card selector
relaxes those refiners and shows the best near matches from the available pool.

Examples of presentation refiners include promo, price category, EV,
availability, Gulong guarantee, terrain, and installment filters. Core fitment
and product-reference matching remain ranked strongly; the relaxation only
prevents a no-card customer response when useful alternatives exist.

When relaxation is applied, `presentation_strategy.relaxation` records that the
shown cards missed one or more requested presentation filters. The model should
explain the miss briefly and offer the useful alternatives instead of claiming no
products exist.

Product-card bodies remain deterministic, but the short lead-in before cards can
be model-authored. The runtime accepts a model lead-in only when it stays short
and does not copy card text, mention product URLs/prices, push payment/order
steps, assert vehicle compatibility, or claim that all cards satisfy budget,
promo, category, or other preferences without support from the latest
presentation strategy. Unsafe lead-ins fall back to a neutral runtime sentence.

Product installment availability is treated as a product fact, not an order
payment action, when the customer explicitly asks for installment options and
the product tool result supports the filter. Runtime lead-in guards should block
reservation, checkout, balance-payment, schedule, and contact-collection claims,
but should not strip a grounded product-installment lead-in.

The product-card composer still validates the model-authored lead-in before
appending deterministic cards. It now accepts up to two short prose paragraphs
and collapses them inline, so a natural acknowledgement followed by a short card
lead-in is not rejected solely because the model inserted a paragraph break.
General wording such as "fit your criteria" is allowed. The guard still rejects
card-like lists, copied card details, price/URL leakage, ungrounded fitment
claims, order-action pushes, and narrow unsupported claims that directly
contradict relaxation/budget evidence.

When a customer asks a mixed follow-up, such as confirming a promo detail from a
shown card and also asking for newly filtered options, the model should satisfy
both parts. It may answer visible card details directly from `Last Product
Presentation` when the compact card line contains the fact, or call
`get_product_details` with a concrete `card_ref`, `item_ref`, product id, slug,
or ordinal when the detail is not visible. A new `product_search` can then handle
the additional filter request.

Product cards may include origin, warranty wording, and Tire Protection Plan
wording when those fields are available in trusted product data. These remain
renderer-owned product facts, not memory facts.

`get_product_details` now supports selected-product card insertion. The tool
returns `card_runtime_insert=true` plus compact safe headers/details for the
model and a deterministic selected-product card body for the runtime composer.
Model-visible selected details may include customer-facing price lines,
promos, in-stock/pre-order status, installment text, warranty/TPP, DOT, origin,
and URL. They must not include supplier/base/internal prices. If the customer
asks about two or more visible SKUs, the model can call `get_product_details`
for each chosen ref; the composer de-duplicates and inserts up to three
selected-product cards from the latest tool round while preserving the
model-authored lead-in/CTA.

`answer_product_faq` now reads from the real Gulong FAQ/RAG pool filtered to
product-classified FAQ and warranty/product documents. Product FAQ hints remain
answer-free, and the tool handles product questions such as brand-new tires,
tire-size checking, warranty, promos, limited stock, returns/exchanges, wrong
tires, mags/motorcycle tires, and product installment policy. Order-domain
questions such as how to order or how to pay belong to the order domain and
should not be answered by `answer_product_faq`.

When the V7 harness is backed by an embedding-capable gateway,
`answer_product_faq` generates a query embedding with the RAG index embedding
model and ranks only the product-classified FAQ/warranty chunks by vector
similarity. If embedding is unavailable, fails, or returns the wrong dimension,
the tool falls back to lexical ranking over the same product-only subset.
Model-visible FAQ tool output is intentionally simple: status, domain,
`source_type=faq`, `faq_id`, question, answer, reason, and TTL. Retrieval
diagnostics such as corpus version, selected chunk, method, embedding model,
latency, and cache-hit state stay in the full tool result/logs. Product FAQ
retrieval also uses soft in-memory caches keyed by normalized query, FAQ/RAG
corpus version, FAQ version, embedding model, and domain-scoped retrieval mode.
These caches reduce repeated embedding calls and retrieval latency without
becoming authoritative state.

The compiled context includes shared FAQ-result guidance. When a tool result has
`source_type=faq`, the model should treat its question/answer as retrieved
FAQ/policy grounding, answer naturally in the customer's language, avoid
mentioning retrieval/RAG/internal details, and avoid inventing policy beyond the
FAQ answer.

## Brand Bucket Discovery

`discover_brand_buckets` is a V7-native narrowing tool. It returns deterministic
brand/category menu cards grouped by price category so the assistant can answer broad
questions such as "what brands do you have?" or help the customer choose a
bucket before exact SKU/product cards.

Product inquiry still requires a product tool call before the assistant claims
that options, choices, prices, or details are available. If the model does not
call a tool, it should not say that it found or is showing options.

It is also the usual broad-discovery tool when the customer only provides a
confirmed tire size/rim and no brand, category, promo, budget, or SKU preference
has been selected yet. General inquiry terms such as `hm`, `how much`,
`price list`, or `pricelist` are broad product-inquiry wording by default, not
automatic exact-card requests. The model should still use `product_search` when
the latest message asks for promos, budget/cheaper filters, quantity totals,
specific recommendations, exact SKU/model options, exact prices for a selected
brand/category/product, or product-card details.

The bucket cards are not exact product recommendations. They should be used to
ask which bucket, brand, or price tier the customer wants to inspect next.
Actual SKU/model cards, exact prices, promos, URLs, stock, warranty details, and
installment facts still come from `product_search` / `get_product_details`.
Bucket cards therefore do not show category price ranges. They use deterministic
category emojis, category-level sales pitches, compact brand markers such as
`3+1`, `PHP 1,000.00 off/tire`, `TPP 1Y`, and `TPP 6 MOS`, plus a legend
explaining the markers.
Customer-facing copy should say brand choices, categories, or options; `brand
bucket` is internal implementation language only.

This intentionally avoids the Runtime V6 selection/presentation-mode split.
Runtime V7 keeps one model-led tool loop: the model chooses whether a bucket
menu or exact product search is useful, and the runtime deterministically
renders whichever card type the selected tool returns.

## Vehicle Fitment Discovery

`product_search` is not a vehicle-fitment compatibility tool. If the customer
only provides vehicle text such as make/model/year and no confirmed tire size,
the model should call `extract_compatible_fitment`.

`extract_compatible_fitment` is a read-only discovery aid. It first uses
`/shop?search=` to extract candidate tire sizes from product search results and
falls back to the legacy `/car_tire_sizes` endpoint when shop search yields no
candidate sizes. Candidate sizes are not treated as confirmed fitment. The
assistant should ask the customer to confirm the sidewall size before presenting
product cards, unless it clearly labels the next step as provisional.

Uncertain tire-size handling is model-owned at the conversation/tool-choice
layer. The context packet and tool policy tell the model to shift focus to
sidewall confirmation when the size is `mentioned_unconfirmed` or expressed with
uncertain phrasing such as `parang` or `ata`, unless the customer explicitly
asks for a provisional search. Runtime validation still normalizes tool inputs
and grounds product facts, but it does not deterministically block
`product_search` based on raw-message uncertainty.

From Runtime V6 `fetch_compatible_tires`, the parts worth porting into
`extract_compatible_fitment` are the endpoint-backed candidate-size discovery,
the `/car_tire_sizes` fallback, compact sample product evidence, and explicit
"requires customer confirmation" semantics. Parts not worth porting into V7 now
are auto-prefetch chains, strategy-stage routing, provisional product-card
selection from vehicle-only context, stale tool-cache replay, and any hard flow
gates that would box in the model's conversation.

Product detail lookup by slug does not need a separate first-class V7 tool yet.
When a shown card exists, `get_product_details` resolves refs/ids/slugs against
stored observations. When no observation exists, product lookup by tire size,
brand, and model/pattern is close enough to normal `product_search` and keeps the
tool surface smaller.

The product tools keep split tire-size fields (`section_width`, `aspect_ratio`,
`rim_size`) instead of adding separate full-size and partial-size string inputs.
Full and partial tire-size interpretation belongs in extraction/background
signals, while tool calls stay normalized and explicit. A full-size input can be
added later if live traces show repeated model tool-call errors that the split
schema does not handle well.

Commercial-use wording such as `6 ply`, `8 ply`, `8PR`, `pang karga`, and
delivery-van context is handled as a model-extracted `ply_rating` hint. Runtime
normalization may prefer commercial `C` rim interpretation when the model passes
that hint, but it does not round or rewrite flotation sizes such as
`33X10.5R15`.

## Recency And Multiple Values

Recency dominates same-field conflicts. Latest user message values outrank
recent turns and active memory unless the latest message explicitly refers back
to older context.

Multiple values are preserved for:

- `tire_size`
- `preferred_brands`
- `required_brands`
- `branch_addons`

This is required because customers may ask for multiple cars, multiple tire
requests, or alternatives in the same turn. Older memory values are not carried
forward automatically when the latest user message provides a replacement value.

## Order Readiness

Order readiness is the guarded action gate. Product search is not blocked by
order-readiness gaps.

Required order-readiness fields:

- `quantity`
- `specific_sku_model`
- `chosen_schedule_slot`
- `delivery_address`
- `selected_installation_partner`
- `reservation_payment_method`
- `balance_payment_method`
- `payment_option`
- `first_name`
- `last_name`
- `email_address`
- `explicit_order_confirmation`

Optional order-readiness fields:

- `branch_addons`

Branch add-ons should be captured and validated if mentioned, but absence of
add-ons must not block order readiness.

The order branch adds `build_order_summary` as a read-only order-domain tool.
It compiles the current readiness state, normalized signals, trusted product
observations, and service refs into a deterministic customer-facing summary
block. The model sees only compact preview/presentation metadata and should
write the lead-in and next-step question; the runtime inserts the summary body.
This keeps order review conversational while preserving trusted totals and
avoiding model-authored form rows. Service-only location or schedule signals do
not expose the order summary tool unless Order Readiness also has real
product/order context.

Delivery order summaries may also attach compact FAQ-sourced
`supporting_policy_context` for delivery fee, delivery lead time, and payment
options. This lets the model mention policy facts such as the Budget/Economy/Mid
Range delivery fee, Metro Manila delivery estimate, and Pay Now PHP 100 discount
without hardcoding them in the renderer. If `payment_option` is still missing,
the summary remains incomplete and the model should ask Pay Now versus Pay
Later/Pay After Service as the next clarification. Missing fields remain
model-visible CTA context and are also shown inside the deterministic
customer-facing summary as editable bracketed placeholders. The summary should
not append a separate missing-field checklist; customers can copy, edit, and
return the form, after which Runtime V7 re-extracts, normalizes, resolves,
refreshes Background Signals/memory, and rebuilds the summary.

The order branch also exposes `calculate_order_quote` as the read-only quote
entry tool. It derives product subtotal, delivery/home-service fee, Pay Now
discount, Pay Later reservation fee, balance due, and installation threshold
amount from trusted product observations and order policy math. If multiple
product cards are visible and no SKU is selected, it returns compact candidate
quotes instead of pretending there is a final order total. `build_order_summary`
uses the same quote breakdown, stores an `order_summary_snapshot`, and compares
the next snapshot before deciding whether the deterministic form should be
shown again. Simple non-critical edits such as contact number can be accepted
quietly; changes to product, quantity, fulfillment, schedule, payment option,
or totals re-show the form so the model can ask for confirmation in its own
voice. Branch add-ons remain paid-at-installation-partner context and are not
included in online totals.

## Canonical Values

Runtime V7 owns its canonical metadata endpoints through
`RuntimeV7CanonicalValuesProvider`. Endpoint-backed metadata is lazy-loaded and
TTL-cached. Prompt examples do not trigger network calls.

The provider currently supports canonical data for brands, tire categories,
checkout metadata, payment methods, transaction types, locations, installation
partners, and branch add-ons. Local aliases and deterministic cleanup run first
for cheap detection, but checkout metadata is always loaded and TTL-cached when a
new checkout/payment-related value is collected and a provider is available.

Payment signals keep compact prompt-facing values such as `gcash` or
`credit card installment`, while their `metadata.normalization` records the
matched checkout metadata row (`payment_type`, inferred `payment_option`, source,
and status). This gives the model readable context without losing the canonical
API-backed value needed for later order validation.

Checkout/payment readiness must not be reused as product-search installment
filters. `product_search.installment_*` arguments are only for explicit product
installment availability requests, not for reservation fee or balance payment
preferences.

Product search reports active and remembered brand availability separately.
`requested_brand_status` describes latest-search `brands` / `required_brands`;
`brand_match_mode` decides whether that anchor is preferred or strict.
`preferred_brand_status` describes remembered `preferred_brands` so probes can
show when a lower-priority brand was requested but unavailable in the result
pool.

Rich choice metadata should stay behind the runtime state/artifact boundary. The
context packet should expose only compact advisory projections such as
`resolution=recognized_unresolved`, `needs=selected product installment option`,
`selected=payment_type_id:...`, or `candidate_count=...`. These projections help
the model ask the right next question but must not dominate the latest customer
message, force a tool call, or override trusted tool results.

## Renderer-Owned Cards And Prompt-Guided CTAs

Product-card and brand-menu CTAs are deterministic renderer output. The model may
write one short reactive lead-in after `product_search` or `discover_brand_buckets`,
and prompt guidance asks it not to duplicate the stable CTA when possible.

Do not add deterministic stripping only to remove natural next-step wording. Keep
generated lead-ins model-led unless they copy renderer-owned card/menu facts, leak
prices or URLs, assert ungrounded product facts, or push guarded order/payment
actions.
