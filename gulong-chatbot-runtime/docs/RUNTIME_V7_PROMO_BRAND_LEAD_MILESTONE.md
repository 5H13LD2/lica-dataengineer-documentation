# Runtime V7 Promo And Brand Lead Milestone

Status: approved implementation scope

Baseline: `origin/product` at `c08ef2a`

Last updated: 2026-07-21

## Objective

Ship the next promo-gallery release as a focused lead-discovery improvement:

1. Let the main model decide when promo discovery is useful from the latest
   customer message and conversation state.
2. Derive promo eligibility automatically during the review-gated catalog
   build.
3. Give brandless customers low-effort price-category choices.
4. Record presentations and choices as a measurable customer funnel.

This milestone does not include the broader payment-policy, memory-truth,
capability-skill, instruction-RAG, or product-query redesigns listed in
`RUNTIME_V7_DECISIONS_AND_GAPS.md`.

## Release Boundaries

In scope:

- Model-led promo discovery and gallery selection.
- Brandless, brand-specific, and explicit-promo shopping turns.
- AI-extracted, evidence-backed, human-reviewed promo eligibility.
- Exact-size applicability checks before a promo card is selectable.
- Interactive Premium, Mid Range, Economy, and Budget choices.
- Tracked promo, brand, promo-action, and price-category selections.
- Session-authoritative impression/click state and append-only analytics.
- Trial-user, staging, and VM allowlist rollout.

Out of scope:

- General commercial-policy or payment-method redesign.
- Evidence-linked response claim validation outside promo eligibility.
- Active Working Memory redesign.
- Dynamic instruction skills or instruction-vector retrieval.
- General product-search filter planning and no-result recovery redesign.
- Changes to unrelated service, order, payment, or follow-up behavior.

## Decision 1: Model-Led Promo Routing

Remove raw-utterance promo activation from the customer path. In particular,
`should_auto_present_general_gallery` must not classify shopping intent using
terms such as `price`, `magkano`, `hm`, or `promo`.

The model receives compact state for the current turn:

- latest customer message and recent conversation;
- confirmed tire size or fitment context;
- active brand preferences, required brands, and exclusions;
- latest promo/category presentation and selected choices;
- active catalog version and channel capability;
- whether an eligible gallery has already been delivered this session/version.

The model may choose these existing operations:

- `search_promo_catalog` then `present_promo_gallery`;
- `discover_brand_buckets` for price-category/brand narrowing;
- `product_search` when the customer explicitly wants concrete products or has
  already selected enough constraints.

Prompt policy makes promo eligibility assessment the first step for a broad
shopping turn with a known size but no brand, category, budget, or model
preference. The model then chooses the eligible promo gallery or interactive
price categories as the brand-awareness surface. Exact products follow a
customer selection or an explicit request for concrete options. This remains a
model decision over structured context, not a keyword route. Explicit brand and
promo questions may also search and present matching reviewed promos.

Deterministic code remains responsible only for:

- Messenger/channel support and feature allowlists;
- active catalog/version checks;
- applicability and public-image validation;
- allowed promo/card/choice refs;
- repeat and stale-presentation suppression;
- idempotency, rendering, field actions, and delivery accounting.

## Decision 2: AI-Derived Promo Eligibility

Marketing continues to maintain poster images and mechanics documents. The
catalog-building AI extracts eligibility and generates the review rows; the
marketing reviewer does not manually build a source table.

Add a generated `Eligibility` tab to the review workbook. Each row should keep
the original AI value beside the authoritative reviewed value and source
evidence. The extraction contract includes:

- `eligibility_id` and `promo_id`;
- scope: `all_brand_products`, `selected_patterns`, `selected_sizes`, or
  `selected_products`;
- included and excluded brands;
- included and excluded patterns/models;
- included and excluded tire sizes;
- qualifying quantity and free quantity when applicable;
- evidence refs and extraction confidence;
- review status and notes.

The builder should infer these fields from DOCX mechanics and poster evidence.
Ambiguous, unsupported, or contradictory eligibility remains `NEEDS_REVIEW`
and blocks publication for that promo. Reviewers only approve or correct the
generated values.

At runtime, `search_promo_catalog` accepts the current canonical tire size when
known. An eligibility resolver combines the reviewed rule with currently
visible exact-size products. Only promos with at least one eligible product are
allowed into a size-qualified gallery. Semantic retrieval can find mechanics,
but it cannot decide product eligibility.

## Decision 3: Interactive Price Categories

Extend the existing `discover_brand_buckets` result instead of adding a second
product-data implementation. Each available category should expose:

- stable `choice_ref`;
- category label;
- exact-size minimum and maximum current price;
- available product and brand counts;
- representative brands;
- current-size/context ref and expiry.

Preferred Messenger presentation is one compact text prompt with four tracked
buttons. This has less interaction cost than four decorative cards. If the
ManyChat v2 contract does not support the required tracked text-button payload,
use deterministic category gallery cards as the fallback.

The category click must enter Runtime V7 through a validated choice-action
boundary. The runtime restores the tire size and presentation context from the
session ledger, records the explicit category preference, and calls focused
`product_search`. The customer must not repeat the size or category.

After a category, promo, or brand choice, show a focused product set, normally
two to four cards. Do not automatically return one product from every category
after the customer has narrowed the path.

## Decision 4: Unified Funnel Tracking

Firestore/session state is authoritative. ManyChat fields mirror the latest
operational state. BigQuery analytics are append-only and non-blocking.

Persist these presentation fields in the session ledger:

- presentation ref and type: `promo_gallery` or `price_category_choices`;
- catalog version and selection fingerprint when applicable;
- tire size/context ref;
- ordered promo, card, brand, or category choice refs;
- delivered timestamp and delivery result;
- experiment/renderer variant;
- expiry and repeat-suppression state.

Persist these action fields:

- event and idempotency IDs;
- presentation ref and selected choice ref;
- action type and selected promo, brand, or category;
- card/button position;
- click timestamp and validation result;
- response delivery result;
- resulting product presentation ref when produced.

Emit one normalized `interaction_event_log` row for each lifecycle event:

- `surface_delivery_succeeded`;
- `surface_delivery_failed`;
- `choice_clicked`;
- `choice_rejected`;
- `choice_response_delivered`;
- `products_presented_from_choice`.

Rows include `row_id`, event time, user/contact, session, request/trace/turn,
channel, release/host, surface type/ref, catalog version, choice type/ref,
promo/card/brand/category values, tire size, position, idempotency ID, delivery
status, and a bounded JSON details field.

ManyChat should mirror only the latest values needed by operations:

- latest discovery surface and shown timestamp;
- latest selected choice type/value and timestamp;
- existing promo catalog/card/action/brand fields;
- current `chatbot_state`.

Do not rely on ManyChat fields as the historical analytics ledger.

## Funnel Definitions

Use distinct session plus presentation ref as the denominator boundary:

- Impression: successful `surface_delivery_succeeded`.
- Engagement: first validated `choice_clicked` for that presentation.
- Choice response: successful `choice_response_delivered`.
- Product progression: `products_presented_from_choice`.
- Lead progression: later turn facts show product selection, location capture,
  contact capture, handoff, booking, or order.

Primary metrics:

- promo gallery click-through rate;
- price-category choice rate;
- promo/brand/category choice distribution;
- choice-to-product-presentation rate;
- product-selection, location, contact, and qualified-lead conversion;
- early drop-off after impression and after click;
- turns and elapsed time from first shopping message to qualified lead.

Guardrails:

- gallery and choice delivery success;
- stale/invalid click rate;
- no eligible promo and no category-result rate;
- repeated presentation rate;
- click-to-response latency;
- size/applicability mismatch rate.

## Acceptance Scenarios

- Brandless exact-size price inquiry: model may choose applicable promo
  awareness, then offers tracked category choices without dumping all products.
- Bare greeting: no shopping surface unless the model finds shopping context in
  the active conversation.
- Explicit promo request: answer reviewed mechanics and optionally show matching
  eligible cards.
- Brand-specific request: search matching reviewed promos and/or products;
  alternatives remain model-selected and source-backed.
- Promo not applicable to the known size: do not include it in the gallery.
- Promo with no valid public image: retain for RAG but exclude from galleries.
- Category click: preserve size, record the click once, and show focused products.
- Repeated delivery: suppress the same general presentation for the active
  catalog/session unless the model has a distinct targeted reason.
- Stale click: explain that the choice is stale and offer current choices.
- Failed delivery: do not count an impression; permit a safe retry.

Required regression utterances include `Hi hm po 195 60 15`, a separate
`195/60R14` case, explicit Michelin/Apollo/Yokohama promo questions, a brandless
promo question, and an exact-product override.

## Delivery Sequence

1. Add eligibility extraction, review tab, parser, validation, publication, and
   runtime applicability tests.
2. Replace utterance-based auto presentation with model-facing routing policy
   and deterministic presentation guards.
3. Add tracked category-choice rendering and validated click handling.
4. Add the session interaction ledger and append-only analytics event writer.
5. Run builder, renderer, endpoint, idempotency, repeat, and funnel contract
   tests plus the full Runtime V7 suite.
6. Deploy from `origin/product` through the staging Cloud Build trigger.
7. Validate return-only payloads, then send controlled gallery and category
   choices to trial user `4843256405786522`.
8. Verify ManyChat messages/buttons, click callbacks, session state, and
   `interaction_event_log` rows before preparing the live VM candidate.
9. Enable live behavior only for the trial-user allowlist, then expand after
   successful funnel and latency review.

Rollback remains independent by surface: disable model-led general promo
presentation, disable category choices, or disable interaction analytics while
retaining the current static flow and active catalog pointer.
