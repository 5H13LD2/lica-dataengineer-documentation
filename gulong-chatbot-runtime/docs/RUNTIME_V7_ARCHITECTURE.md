# Runtime V7 Architecture

Last updated: 2026-09-16

Runtime V7 is a Gulong assistant runtime slice built around one model-led
Chat Completions tool loop. It uses deterministic code for facts, validation,
canonicalization, side-effect safety, rendering, persistence, and observability.

## Location Anchor And Service-Claim Scope

A turn may contain one canonical customer location anchor and several
acceptable nearby service areas. The anchor describes where the customer is;
alternatives describe where they are willing to search. Neither customer text
nor model interpretation proves partner or schedule availability.

When no explicit guided/partner selection scopes a service call, Runtime
hydrates it from the canonical anchor. Each provider result authorizes claims
only for its executed query area and evidence ref. Other named areas must be
queried separately before the composer can claim service there. This prevents
one successful result from becoming a blanket multi-area claim.

Installation slots additionally require usable product context or a typed
schedule constraint. A product observation with no delivered cards and no
validated selection authority does not satisfy that prerequisite. Runtime
redirects premature slot proposals to partner coverage, then uses a
provider-owned summary so model phrasing cannot broaden or duplicate the fact.

## Product Fitment And Preference Relaxation

Exact tire size, explicit EV compatibility, and explicit customer exclusions
are the presentation safety boundary. Brand, model/pattern, terrain/category,
budget, origin, warranty, availability, promo, guarantee, and installment
requirements are ranking preferences. When no product satisfies every
preference, Runtime may present only exact-fitment candidates, orders the
requested brand first, and exposes typed per-card misses to the deterministic
renderer. Commercial facts are never inferred from the relaxation: promo,
stock, guarantee, and payment claims remain true only for cards whose provider
data explicitly contains them.

An explicit customer prohibition remains hard. The signal/tool contract uses
canonical `brand_match_mode=strict` only for semantics such as "Michelin only"
or "no other brands"; ordinary named-brand availability and price questions
default to `prefer`. This separates product identity ranking from customer
consent without depending on a fixed phrase matcher.

Product availability and media are separate trust boundaries. Every
source-backed option can appear in the deterministic text price list, while a
visual gallery and tracked selection token require a trusted catalog image.
This avoids hiding valid products merely because media is incomplete without
inventing an image or authorizing an unseen button.

## Design Goals

- Preserve a natural customer-service conversation while grounding business
  facts in tools and runtime state.
- Make product discovery, service feasibility, order review/submission, and
  payment request flows possible across turns.
- Keep model interpretation responsible for user intent and response wording.
- Keep deterministic code responsible for things the model should not invent:
  prices, promos, stock, URLs, partner/slot availability, payment details,
  order payloads, and side effects.
- Treat a catalog URL as a separate action boundary from the rest of its card.
  If slug identity conflicts with structured model/pattern evidence, suppress
  the URL while retaining valid product, price, image, and tracked-selection
  content.
- Treat tool arguments as proposed query plans. Runtime validates them against
  the fixed authoritative provider for that claim type, attaches compact
  evidence/refs, and keeps unsupported assertions out of deterministic cards,
  payment surfaces, and durable commercial state.
- Keep Cloud Run statelessness: Firestore/session state is authoritative for
  Cloud Run. Compute Engine shadow/canary deployments can opt into Cloud SQL
  Postgres session and idempotency stores through the same storage interfaces
  without changing customer-facing runtime logic.
- Keep V7 deployable behind `/gulong/v7/chat` without making it the implicit
  default runtime for every ManyChat flow.

## Composer-Owned Customer Turn

With `RUNTIME_V7_TURN_PLAN_ENABLED=1`, Runtime compiles
`CustomerTurnPlanV1` after tools and renderer surface planning but before the
existing final composer call. The contract contains compact surface metadata,
accepted transitions, satisfied fields, decision layers, and authorized
evidence. It never copies full cards or raw provider responses into the
composer input.

The final composer owns ordinary wording and the complete order of text,
renderer surfaces, and the one next question. Runtime validates the result
and may request one structured repair. It does not reorder or rewrite a
successful turn. Deterministic behavior remains responsible for evidence,
surface refs, legal transitions, side effects, idempotency, and a minimal
failed-repair fallback.

The same ownership applies between surfaces. Before calling a discovery or
presentation tool, the model determines whether the customer is actively
continuing, pausing, or closing. Pure pause/close turns do not receive another
surface or sales CTA. For active turns, the model writes the acknowledgement,
contextual bridge, and useful next question in Gulong.ph's collective voice;
renderer-owned card facts and buttons are not flattened into that prose.

Surface metadata distinguishes an active customer decision from renderer-owned
supporting context. For example, an incomplete deterministic order summary can
support the immediate Pay Now/Pay Later choice without becoming a second
decision layer. The renderer still owns every summary fact and button; the
model owns only the connected acknowledgement and CTA. Independent product,
location, schedule, and payment choices remain separate layers.

Guided navigation and customer consent are separate typed concepts. For
example, selecting `Others` from serviceable installation provinces means the
area is outside the listed guided choices. Runtime may recommend delivery in
the model-visible action context, but records `service_path_selected=false`
and removes only current synthetic location/fulfillment candidates before
readiness and persistence. It preserves an earlier explicit delivery choice
and delivery address; navigation cannot erase customer-owned state. A listed
province, by contrast, is a validated installation context and may lead to city
choices when the active goal needs more precision.

When the customer selects an already rendered product and moves into service or
schedule discovery, the turn plan carries the trusted product observation and
presentation refs forward. This lets the composer acknowledge the selected
product as the bridge into the new surface without inventing evidence or asking
the customer to select it again.

Answer-only authored FAQ and business-contact inquiries use a compact mode of
that same final composer call. The payload retains the latest request,
recent-turn continuity, conversation state, provider results, exact evidence
refs, required authored answers, and voice/commercial contracts. It omits stale
lead gaps, product/service/order progression, active working memory, decision
packets, and generated drafts that could compete with the selected answer goal.
Mixed answer plus product, service, order, or renderer turns retain the full
packet. This is selected from typed tool/surface outcomes, not customer keyword
matching, and adds no classifier or model call.

Pure payment-policy inquiries also use a focused system prompt for that compact
composer call. The payload still contains typed, source-backed commercial
claims and the normal validator still checks them. This removes unrelated
product, schedule, and order-surface instructions from a simple policy answer
without adding a deterministic response template. The main model supplies each
payment lookup scope directly; active checkout metadata, not a separate
semantic payment planner, resolves named methods, categories, brands, and
terms. Exact local wallet alias matching prevents a named credit or financing
product from collapsing into its parent wallet rail.

FAQ goal selection and fact authority are also separate. Retrieval can help
identify the customer's authored FAQ goal, while a Runtime V7-owned policy
answer wins over unrelated nearby chunks once that goal is selected. This is
used for durable DOT-code and formal-quotation guidance that is not represented
correctly in the legacy corpus. In serving, the main model selects the
domain-specific read tool; phrase-ranked hints do not expose a domain, force a
tool retry, or choose customer-visible meaning.

Release evaluation follows the same ownership boundary. Automated gates
validate objective facts and mechanics; a human/CS review reads the complete
rendered turn for factual synthesis, natural language, clarity, continuity,
and the usefulness of the next action.

The turn plan distinguishes required direct answers, supporting replacements,
and optional context. A successful grounded answer surface must render exactly
once; independent explicit requests may therefore retain more than one required
answer surface. Optional surfaces cannot introduce a competing decision layer
beside a required answer. A pending product choice normally remains the active
next-input layer before an optional location, checkout, or broad promo surface.
Later optional surfaces are regenerated or revalidated when useful.

The first TPP product presentation is a bounded exception with no additional
model decision: the reviewed Double Warranty gallery is a required
`supporting_replacement` for the old prose warranty spiel. The composer sees its
role and ref but not its promo-card mechanics, so the existing structured
product text and tracked image-selection cards remain the direct answer and
active CTA. The channel suppresses the old spiel only when that warranty card is
actually structurally renderable.

Promo authority is also provider-scoped. The reviewed campaign catalog can
prove offer mechanics or an empty result for its exact search scope; it cannot
deny product-level quantity, bundle, voucher, discount, price, or SKU promos.
Those facts belong to an exact-size product search. Composer guidance and the
independent promo audit share this boundary, so missing exact product evidence
becomes a pending size/price check instead of a global commercial negative.

Promo presentation is part of the semantic lookup plan rather than a second
mechanical selection round. `search_promo_catalog.presentation_mode` records
whether the model wants a direct answer or a reviewed gallery. Runtime can
complete `gallery_if_available` immediately from the search result's allowed
refs; it cannot add refs, reinterpret applicability, or turn renderer metadata
into commercial authority. A result-dependent presentation decision after
`answer_only` still uses `present_promo_gallery` explicitly. If that proposed
selection mixes allowed and non-allowed refs, the renderer retains only the
current allowed intersection and reports the rejected refs; a selection with no
allowed ref still fails closed.

The resulting `promo_response_contract_v1` is compiled once from full tool
artifacts. Customer turn planning, final composition, typed claim validation,
and bounded structural repair consume the same compact provider scope and
claim facts.
The composer receives it once at top level, while its compact tool-result copy
omits candidates and repeated guidance. Full retrieval diagnostics remain in
the trace for operations and never become extra customer-fact authority.

A validated tracked informational action such as Promo Details or About Brand
enters the same interaction packet as every other guided selection. The main
model interprets that validated choice together with current customer text and
state. Runtime does not run generic post-loop product, location, payment, or
stage recovery classifiers against it. When a later free-text message changes
the goal, the main model may select the appropriate read-only provider or
surface on that turn.

After ordinary signal extraction, a valid delivered city or province action is
reprojected as current `validated_choice_action` state. This prevents synthetic
router prose from downgrading the click while preserving the ability of a later
real customer correction to replace it. Product-card visibility is likewise
not product selection; selection requires a trusted selected-product ref.

Location tools follow the same proposed-plan boundary:

1. The main model interprets whether serviceable province choices are the next
   realistic customer decision and may propose the registered read-only
   location-choice tool. No phrase classifier or post-loop semantic recovery
   selects that surface.
2. Deterministic runtime guards validate normalized delivery/location/selection
   state, the provider supplies current serviceable choices, and the renderer
   emits tracked controls. Neither screenshot evidence nor the choice surface
   establishes product, promo, partner, order, or availability facts.
   Location selection and business-fact grounding remain independent. The main
   model may also request an appropriate read-only policy lookup when the
   customer asks a delivery or order question, even when a concrete area is
   already present. The proposed call authorizes retrieval only; the returned
   provider evidence authorizes the answer. For a validated
   delivery-policy request, Runtime preserves `service_type=delivery` as a
   structured FAQ scope. The authored general delivery-process record may
   establish available fulfillment paths, but does not establish exact-address
   serviceability or a promised date. Successful FAQ results carry a stable
   namespaced evidence ref into the positive composer claim contract. They
   authorize `faq_facts`, not `service_availability`; no-match retrievals
   authorize no customer-visible fact. Successful current-turn FAQ calls are
   also explicit required answers in the turn plan. If a draft overstates the
   evidence, repair narrows it to the supported FAQ scope instead of deleting
   the customer's answer.
3. A validated province commits province precision and invalidates dependent
   city, partner, and schedule state.
4. Partner or slot execution is rejected until a serviceable city is
   validated.
5. A precise serviceable city authorizes current partner or slot discovery.
6. If the customer is unsure, isolated preview lookups may rank city controls;
   previews do not enter authoritative service state and are never selectable
   schedules.
7. Selecting a previewed city reruns city-specific availability before
   schedule controls can be rendered.

If a final-composer call is truncated or otherwise lacks a valid structured
response, Runtime performs one concise, low-temperature format retry. It does
not author customer prose or bypass validation: the retry receives the same
turn plan and evidence, and its output must pass every normal renderer, claim,
commercial, voice, and service-action contract before delivery. The same
single retry applies when a contract-repair call is truncated; that retry uses
the original compact context plus typed violations instead of repeating the
larger invalid draft.

Compound payment questions use the same model-led tool boundary. The main model
may request more than one independent lookup, preserving only the bank, term,
brand, and Pay Now/Pay Later scope relevant to each call. Runtime bounds and
deduplicates those calls and resolves them against canonical checkout metadata.
Model wording never establishes provider support, installment eligibility, or
payment availability.

## Why This Shape

The runtime was shaped by repeated review findings:

- Product/service/order turns often contain mixed intent. A customer can ask
  for installment policy, a brand, a vehicle, a budget, and installation in the
  same turn. Hardcoded stage gates tend to block one of those intents. The main
  model therefore remains responsible for interpreting the customer turn.
- Exact commercial facts are high-risk. Prices, promos, stock, DOT, warranty,
  slot availability, payment details, and order submit payloads must come from
  tools or state, not model memory.
- Commercial sources are deliberately narrow: `/promo_brands` authorizes
  current brand-level Buy 3 Get 1 eligibility, while reviewed promo records
  authorize their published mechanics and gallery content. A missing gallery
  record cannot negate a brand returned by the live endpoint. `/payment/list`
  plus
  transaction metadata for payment, installment, brand compatibility, and
  fulfillment exclusions. Vector/FAQ retrieval can explain policy, but cannot
  authorize an active commercial claim.
- Cross-turn continuity cannot live in one memory string. V7 separates AWM,
  Background Signals, product observations, service observations, order
  readiness, channel history, and tool refs so conflicting facts can be
  diagnosed by source and trust level.
- Deterministic cards and summaries improve grounding, but deterministic
  rewriting of model prose tends to damage tone and hide prompt/tool-output
  issues. The architecture therefore keeps exact surfaces deterministic and
  surrounding conversation model-authored.
- ManyChat live ingress does not reliably provide all identifiers needed for
  idempotency. V7 resolves message identity from channel history when possible,
  records replay metadata, and uses a per-session active-turn lock plus CAS
  save to reduce simultaneous duplicate responses.

## Tracked Interaction Resolution

Tracked controls use a hybrid ownership boundary:

1. API ingress resolves the full choice from the delivered session allowlist.
2. Structurally parsed clicks enter a bounded session-store interaction inbox
   before waiting for the main turn lock. This is a freshness journal, not
   authoritative commercial/order state.
3. Under the lock, Runtime validates the click against the delivered allowlist
   and records `InteractionEventV1` with provider `occurred_at`, server
   `received_at`/`processed_at`, stable identity, trusted presentation/choice
   refs, customer-visible label, and decision layer.
4. A tracked-click-only settling check and the pre-delivery check can yield to
   a newer inbox event even when ManyChat message history has not exposed the
   button bubble yet. Events are ordered by occurrence time, receipt time, then
   event ID.
5. Runtime compiles at most five unresolved events into a 2,500-character
   `InteractionPacketV1`. `runtime_relation` reports structural facts only;
   `allowed_model_interpretations` defines legal state transitions.
6. The main model and final composer receive the same packet. The composer
   proposes `InteractionDecisionV1`; Runtime validates the interpretation and
   effective event IDs.
7. Runtime commits only the validated effective transition. Comparison and
   clarification do not mutate singular selection state, and unresolved
   sequences cannot authorize order/payment side effects.
8. Successful/evaluated delivery and durable state save close the event ledger
   and remove the matching inbox events. Failed or superseded delivery cannot
   create a commercial/order-state mutation.

The model decides conversational meaning and wording. For a button-only
sequence in one guided dimension, Runtime applies the newest validated action
as the current correction; the customer does not need to explain a normal
change of mind. Comparison is allowed only when customer-authored free text
explicitly asks to compare, while genuinely stale, invalid, cross-layer, or
unordered packets may still require clarification. Hierarchical choices such
as Cavite followed by a delivered Dasmarinas child advance normally, and
schedule/payment layers remain single-select. Informational promo controls can
be answered or compared but cannot select commerce state. When clarification
is the only legal interpretation, Runtime exposes no business tools for that
turn and accepts text response units only.
Per-event audit state separates the batch transport result from semantic
resolution: `delivery_status` records whether the batch response reached the
channel, while `resolution_status` and `effective_for_state` identify
clarification/comparison, the effective selection, or a superseded event.

There is no extra classifier model call, vector lookup, BigQuery serving query,
or external API change. Ordinary free-text turns have no settling delay.
`RUNTIME_V7_INTERACTION_BATCHING_ENABLED=0` restores the prior click path.

## Current Accomplishments

- Built a product/service/order/payment foundation around one model-led
  tool-calling harness.
- Added deterministic product, service, order, and payment renderer surfaces
  while keeping lead-ins and CTAs model-authored through the composer.
- Added model-primary typed Background Signals with closed provenance and
  Active Working Memory as descriptive continuity. Only latest-customer or
  validated-action signal state may persist and influence readiness; AWM,
  narrative summaries, and observations remain advisory.
- Added typed Background Signal relations. Conditions, questions, and
  historical references are current-turn read context only; rejections retract
  prior state; corrections replace it; and only durable positive relations
  cross the memory/ledger boundary.
- Added product observations, service observations, order readiness, payload
  refs, payment refs, and turn traces to support cross-turn review.
- Added API-side ManyChat conversation hydration with reset and stale-gap
  segmentation.
- Added per-session active-turn locking, pre-delivery channel freshness checks,
  CAS-backed session saves, BigQuery debug trace persistence, and compact Cloud
  Logging trace summaries for API turns.
- Added an authenticated follow-up boundary with two explicit routes. Latest
  customer messages recover through the normal chat path; assistant-last
  proactive cases use one structured plan call followed by evidence validation,
  exact one-CTA rendering, idempotent delivery, and a bounded attempt ledger.
- Session-lock-busy turns now return an explicit non-success runtime status and
  persist a debug trace even when the model/tool loop is not admitted.
- Added order quote, summary, API-ready payload build, submit order,
  order-details readback, payment request, and payment-proof matching
  foundation.
- Added order-tool structured arg alias normalization at the tool boundary so
  reasonable model-emitted aliases such as `customer_email`,
  `customer_first_name`, slot date/time, and checkout metadata IDs are resolved
  before order validation.
- Added passive lead qualification and tagging foundations, including Moderate
  Intent, High Intent, Irate, Chatbot Error, Order Booked, Website Inquiry, and
  Payment Proof Received paths where supported.
- Added a first-class model-requested human handoff action. Runtime stores the
  request and unconfirmed assignment state, the channel boundary applies
  `Stop Chatbot` and writes a CS note after delivery, and follow-up admission
  plus later chat ingress treat the durable request as a hard stop.
- Added focused live-probe workflows and a growing Runtime V7 regression test
  suite for product, service, order, payment, ingress, and rendering behavior.

## Request Flow

1. API ingress receives `user_id`, `channel_user_id` if present, `user_text`,
   optional profile hints, and delivery mode.
2. Session gateway resolves the active user/session state. Cloud Run defaults
   to Firestore; VM shadow/canary deployments may explicitly select the
   Postgres-backed Cloud SQL provider.
3. API runtime acquires a short active-turn lock for the session when enabled.
   If another turn is active, V7 returns `session_busy_retry_later` and logs the
   skipped turn for diagnosis instead of returning an empty success payload.
4. API-side conversation hydration loads or reuses compact ManyChat/channel
   history when available.
5. Harness state is restored from `strategy_state.runtime_v7`.
6. Pre-turn intake prepares Active Working Memory, Background Signals,
   image evidence, conversation evidence, product observations, service
   observations, order readiness, and capability profile inputs. The existing
   image-evidence call also emits routing-only Gulong source/surface metadata
   when ownership is visible in the image.
7. The main model receives stable policy, dynamic context, and exposed tool
   schemas, then chooses tool calls in a bounded loop.
   If a compound request makes it select a registered read-only tool from a
   domain that the cheaper signal pass did not expose, the harness recompiles
   once with that missing domain while preserving already-active domains. It
   does not execute the initially unexposed call and does not expand unknown,
   mutating, or previously retried domains.
8. Runtime executes tools, stores observations/refs, and returns compact tool
   outputs to the model.
9. Final composer returns structured response units.
10. Runtime inserts deterministic render surfaces and converts the result into
    ManyChat-safe text/image content messages.
    If several exact product cards are visible, product selection owns the
    response; service and checkout controls remain deferred. Multi-product
    choices use catalog-image gallery cards when every image URL passes the
    delivery allowlist, with the prior detailed text surface retained as the
    missing-image fallback. A validated product click can reuse only a fresh
    same-location slot observation.
11. For send modes, API runtime reloads a small slice of channel history before
    delivery. If a newer user or human-agent message is visible, the stale
    response is suppressed and state/tag side effects are skipped.
12. Delivery optionally sends rendered ManyChat text bubbles as separate
    `sendContent` calls with a short env-controlled delay after the freshness
    check, while return-only/tester paths keep returning the rendered payload
    without sleeping or sending.
13. Tagging, trace persistence, CAS session save, and lock release run best
    effort without letting observability failures block response delivery.
    Session `load()` alone may change the user-to-active-session pointer, so an
    older long-running save cannot reactivate a session superseded by reset.
    Website Inquiry is exclusive over Moderate/High Intent at this boundary;
    operational tags remain independently eligible.

## Follow-Up Request Flow

`POST /gulong/v7/followup` is an authenticated side-effect boundary. The
ManyChat trigger supplies event identity and cadence only; the runtime reloads
the transcript, profile, tags, agent state, and session evidence itself.

1. Bearer authentication runs before transcript loading, model calls, state
   writes, or delivery. `/gulong/v7/followup/tester` uses the same authentication
   and is always return-only.
2. The server computes delivery admission. `FOLLOWUP_SEND_ENABLED` defaults
   false, then a trial allowlist or deterministic canary percentage narrows the
   enabled population. Request payloads cannot override it.
3. Runtime reloads ManyChat messages and profile/tags, acquires the normal V7
   session lock, and suppresses either stop tag or human takeover.
4. If the latest message is from the customer and is at most 24 hours old, the
   original message enters normal Runtime V7 chat as
   `customer_turn_recovery`. Inbound-event state prevents a second generated
   response; failed stored output may be redelivered, while unknown delivery is
   reconciled against refreshed transcript content before any retry.
5. If the latest message is from the assistant, runtime builds a source-separated
   `FollowupCase`: recent transcript, evidence-linked customer/profile facts,
   present/missing lead fields, sent-field rotation, selected product/service
   refs, and successfully delivered product cards. AWM and raw Background
   Signals are not separate prompt truth.
6. Deterministic gates apply cadence windows, stop/human/completion/domain
   conditions, unresolved delivery, retry cooldown, and deferred/closed stance.
7. One logical model call returns a structured action, stance, one focus field,
   an optional declarative lead-in, evidence refs, and CTA style. The transport
   may retry one transient provider failure with explicit telemetry. There is
   no sales-permissive override and no forced-send fallback.
8. Runtime revalidates grounded benefits, including current Buy 3 Get 1 brand
   authority from `/promo_brands`. It rejects an ineligible focus, extra ask,
   model-authored commercial claim, unsupported evidence ref, preference
   contradiction, or non-renderable CTA.
9. Deterministic rendering emits exact evidence-backed benefits and exactly one
   CTA. Invalid model output suppresses; it is never replaced with generic copy.
10. Runtime checks channel freshness again, persists `sending`, calls ManyChat,
    and marks `sent` only on confirmed success. Return-only, failure, and unknown
    outcomes never consume sent-field rotation.
11. Session state retains bounded attempt records and delivered product
    presentations. BigQuery receives normalized follow-up route, validation,
    evidence, usage, delivery, release, and host metadata.

Cloud Run is the return-only staging service. The VM is the sole
customer-facing production runtime. See
`docs/RUNTIME_V7_FOLLOWUP_PRODUCTION_SAFETY.md` for release gates and rollback.

### Request Flow Rationale

- API ingress is separate from the harness so Cloud Run, ManyChat delivery,
  session persistence, and replay concerns do not leak into tool reasoning.
- Conversation hydration happens before harness state restoration because
  latest channel messages can affect BSE/AWM and duplicate detection.
- Pre-turn intake is joined before the model call because image evidence,
  recent human-agent turns, and product/service observations can change the
  correct first tool call.
- Final composer is separate from the main tool loop because the main loop
  should choose tools and reason over results, while the composer should order
  text/render surfaces into customer-ready response units.
- Delivery is after rendering so ManyChat formatting, text splitting, images,
  and payment QR surfaces are visible in the same response payload and trace.
- ManyChat bubble pacing lives in the API delivery boundary, not the renderer:
  the renderer still decides what the bubbles are, while delivery decides
  whether to send already-rendered text bubbles in paced calls.
- The pre-delivery freshness check is intentionally late: it catches human
  agent intervention or a newer customer message that arrived while the model
  and tools were running.

## State Ownership

- `strategy_state.runtime_v7`
  - Durable V7 harness state, including AWM, background signal ledger,
    product/service observations, order/payment snapshots, refs, and human
    handoff request state.
  - Stored product/service observations are trusted read-only results and
    continuity context; they do not become durable customer-choice signals.
    Explicit latest-customer corrections and validated guided choices outrank
    carried customer state, while carried customer state outranks a later
    read-only lookup scope.
- `strategy_state.channel_conversation_history_v1`
  - Compact channel-history cache for ManyChat hydration and duplicate replay.
  - It is a conversation-continuity cache, not business truth.
- `strategy_state.inbound_events_v1`
  - Compact completed inbound-event ledger for duplicate replay after a real
    message id or replay-eligible event key is available.
- Session document lock fields
  - `active_lock_owner` and `active_lock_until` coordinate one active V7 turn
    per user/session.
  - Locks are admission control only. They are not business state and expire
    automatically after a short TTL.
- Runtime tools and canonicalization modules
  - Source of truth for product, service, order, payment, and fulfillment
    validation.
- Active Working Memory
  - Short descriptive memory only. It should not contain directives, stale
    missing-field lists, or unvalidated commercial facts.
  - Runtime assistant prose is not supplied as memory fact evidence. Tool
    turns use deterministic evidence-only compaction and retain normalized
    customer signals plus stable tool/state refs instead of exact commercial
    claims.
- Background Signals
  - Advisory extracted candidates with provenance and normalization metadata.
    They support model reasoning and capability selection, but do not authorize
    action.
  - Each model candidate declares its relation to current state. Only
    `asserted`, `selected`, and `corrected` are eligible for memory/ledger
    continuity. `conditional`, `question_only`, and `historical` are usable for
    the current read-only turn only; `rejected` acts as a retraction and is not
    itself persisted as a fact.

### State Conflict Rules

When state surfaces disagree, use this precedence:

1. Latest explicit customer statement or validated guided action for customer
   choices, corrections, and fulfillment intent.
2. Current typed customer state retained with closed provenance.
3. Trusted tool observations and stored refs for the exact facts they own;
   observations do not become customer choices.
4. Validated order/payment/service action state and submitted-order truth.
5. Recent human-agent/channel history within the active segment.
6. Active Working Memory and narrative summaries as descriptive continuity.

This precedence is a reasoning rule for humans and prompt design, not a hidden
deterministic override. If the model sees conflicting state, the better fix is
usually clearer context labeling or validation semantics.

## Model And Tool Boundary

Runtime V7 keeps customer interpretation model-led:

- The model decides whether the latest turn needs product discovery, FAQ,
  fitment extraction, service lookup, order review, payment request, or a
  clarifying response.
- Tool exposure is an affordance, not an instruction.
- Tool objectives and compact context should help the model reason, not force a
  hardcoded path.

Runtime V7 keeps business facts deterministic:

- Product cards come from trusted product tool results and renderer surfaces.
- Service partner/slot rows come from service tools and renderer surfaces.
- Order summaries, payloads, submit responses, payment details, and QR/image
  messages come from order/payment tools and renderers.
- Canonical payment, transaction, delivery, installation, partner, and product
  compatibility checks happen in runtime-owned resolvers and validation tools.

For a successful authored FAQ or business-contact lookup, Runtime also runs a
bounded semantic answer-goal audit. The audit compares the customer's request,
the provider's authored answer goal, the authored answer, and the composed
reply. It can reject an unrelated answer or require repair of a partial answer,
but it cannot invent a missing fact. This checkpoint reuses the existing LLM
gateway only for those successful grounded-answer turns; ordinary product,
location, ordering, and conversational turns do not pay an additional call.
The narrower case-specific-pending rule applies only when the answer evidence
is explicitly general policy. A checkout-backed brand/method eligibility fact
or other provider-resolved case fact remains usable within its exact scope.

Named payment-method resolution accepts only the typed payment signal produced
by the semantic query plan. Raw customer sentences are never reused as method
names. An unknown named method therefore produces a concise unsupported-method
answer with a small set of current active alternatives, while generic payment
questions continue to use the current checkout-method list.

### Tool Exposure Rationale

Exposed tools are the available capability surface for the current turn. They
are not commands. Earlier probe failures showed that exposing order tools too
early can tempt the model into summary/payment paths when the customer only
asked service feasibility. The current direction is:

- Capability exposure should be permissive enough for recovery.
- Tool policy should explain when a tool is useful.
- Action tools should require trusted refs or validated payload state.
- If a side-effect action lacks required validated data, the tool should return
  missing/invalid fields instead of runtime silently guessing.

## Conversation Hydration

API-side hydration is separate from harness pre-turn intake.

- ManyChat `loadMessages` is used only when the current inbound message is not
  already known in Firestore cache.
- Automated outbound ManyChat flow turns such as `msgout_default` are retained
  as assistant continuity evidence when the loader returns them; V7 does not
  request `hide_automation=1`.
- Loader failure falls back to Firestore cache or the latest inbound message.
- Reset creates a new persisted conversation segment.
- A gap larger than `RUNTIME_V7_MANYCHAT_MESSAGE_AGE_DAYS` between adjacent
  messages starts a new segment.
- Old segment messages should not be merged back into model-facing context
  after reset or after a stale gap boundary.

### Hydration Rationale

V7 must support conversations that were previously handled by a human agent.
At the same time, stale 2024/2025 conversations must not leak into a fresh
customer inquiry. The solution is not "always load everything" or "only trust
V7 state"; it is segment-based hydration:

- Load recent channel messages when the cache does not already include the
  current inbound message.
- Stop at reset or at an old adjacent-message gap.
- Persist only the active segment after the turn.
- Treat loaded conversation text as continuity evidence, not validated product,
  payment, order, or slot truth.

## Rendering And Delivery

The final composer returns response units. Runtime validates those units and
inserts exact deterministic surfaces:

- Product cards and selected product details.
- Service area/slot/addon surfaces.
- Order summaries, including incomplete summaries.
- Payment request details, QR images, links, and fallback bank details.

The channel renderer converts response units into ManyChat-ready content:

- Text bubbles are split within channel limits.
- Image bubbles are sent separately.
- Payment details are grouped to avoid crowded unreadable bubbles.
- Model-authored text is normalized to plain ManyChat-safe text: emojis are
  allowed, but HTML tags, Markdown bold, asterisk bullets, and code/table
  formatting are stripped or converted without changing the meaning.
- Renderer-owned facts must not be rewritten by model prose.
- An initial multi-SKU product result uses one prepared displayed-product set
  for the complete long-form price list, image gallery, tracked `ps1|...`
  choices, metadata, and delivery history. Cards without a trusted image are
  excluded from that displayed set; product search first tries to replace them
  from its already fetched, query-valid ranked pool. If no image-backed product
  can be shown, Runtime retains the truthful text-only result instead of
  emitting a partial gallery. This adds no catalog or image-probe calls.
- The long-form price list accompanies the initial gallery because gallery
  subtitles are too small to be the only pricing surface. It may be omitted
  only for an exact repeat of a successfully delivered or return-only-evaluated
  list-and-gallery presentation with the same stable card identities. A later
  exact SKU selection keeps its existing selected-product progression.
- An authoritative empty promo result paired with a non-promo category
  continuation replaces any weaker composer or renderer fallback before
  delivery. Its category controls remain ordinary product navigation and never
  become evidence that another promo exists.
- Qualification controls have an explicit priority before schedule selection:
  product, then location, then schedule. If multiple product cards and a slot
  lookup coexist, the composer cannot reference the schedule surface and the
  renderer suppresses it. A later turn can reuse trusted service observations.
- Schedule day cards and checkout controls are projections of trusted runtime
  data. Their compact tokens carry only presentation and choice refs; click
  handling resolves the full choice from the delivered session allowlist.
- Exact schedule clicks are revalidated against the service observation.
  `Anytime in the afternoon` resolves to the earliest afternoon slot carried by
  that delivered observation and validates its exact partner/time. If the
  observation contains no afternoon slot, Runtime stores `12:00 PM` only as a
  flexible preference. Order readiness may show that preference in a read-only
  summary, while a separate submission blocker prevents payload creation until
  an exact service slot exists. Pay Now/Pay Later uses quote evidence, and
  payment methods use active checkout metadata filtered for the current order.
- After a schedule or payment token passes the delivered allowlist, Runtime
  owns the short transition acknowledgement and next-layer selection. The
  model may still call evidence tools and update state, but unrelated product
  or slot surfaces are not delivered on that action. A later free-text turn
  cannot reopen a collected choice unless the customer explicitly changes or
  rechecks it.
- Button captions contain a compact form of the actual product/payment label so
  the customer transcript is auditable. The session interaction ledger retains
  the full choice label/ref when the channel's 20-character caption limit
  requires abbreviation.

### Renderer Rationale

V7 moved away from prose parsers and response mutation because those guards
became hidden classifiers. The current renderer boundary is:

- The model can decide order and wording of text units.
- The model can reference render surfaces by ref.
- Runtime inserts exact surface bodies.
- Runtime performs channel safety work such as splitting, image messages,
  duplicate removal, and HTML/markdown cleanup.
- Runtime should not rewrite a weak CTA into a sales CTA unless it is a narrow
  malformed-output fallback.
- A question that asks again for a schedule/payment choice already present in
  trusted order readiness is a state contradiction, not merely weak copy. The
  narrow resolved-choice guard removes that question while preserving explicit
  customer change/recheck requests.

## Observability

Runtime V7 uses version-neutral turn traces:

- Inbound event identity and replay eligibility.
- Component spans for model calls, tools, rendering, delivery, tags, and state.
- State snapshots for context, memory, signals, readiness, and outputs.
- Token/cost/cache metadata per model call when available.

The trace should be detailed enough to reconstruct a bad turn without creating
a V7-only schema that cannot be compared with future runtime iterations.

API turns now persist trace payloads through the analytics gateway when
`save_analytics=1`. The persisted debug payload includes the version-neutral
turn trace, full V7 turn record, rendered response/content messages, delivery
result, and tagging result. The API also emits a compact searchable Cloud
Logging line with `runtime_v7_turn_trace`, `request_id`, `trace_id`,
`session_id`, `user_id`, status, model usage summary, delivery status, and
tool names.

When synthetic qualification finds Moderate, `turn_trace_log.tagging` contains
one versioned analytical qualification object. It carries stable
event/idempotency identity, environment, user/session/turn context,
occurred-at time, qualification level, redacted source-signal provenance,
stable evidence refs, tracked-action correlation context, and the tag delivery
outcome. The object remains countable when routing policy suppresses a
Moderate Intent tag; append-only trace rows must be deduplicated by
`qualification_event_id`.

The full trace can still be returned to the caller with `return_logs=1`, but
returned debug output is no longer the only observability surface.

### Multi-product decision boundary

When one product search renders more than one selectable trusted SKU, the
shared qualification decision owns both composition and channel rendering.
Product selection supersedes a missing-location lead CTA for that response.
The renderer keeps one catalog-image card per SKU, compact source-backed
pricing, and the tracked SKU controls. The valid final composer supplies one
matching product-selection CTA in its complete-turn sequence; only the legacy
or malformed-output fallback supplies deterministic CTA copy.
Location, schedule, payment, contact, and order-detail collection resume only
after a product is selected. Selection requires a trusted tracked product
action, selected-product context, or a durable customer product identity that
resolves uniquely against the trusted current observation; card visibility
alone is not consent. The renderer accepts only HTTPS images from the
established Gulong catalog hosts and reverts to the detailed text surface if
any choice lacks a trusted image. A single visible product can be discussed
without ambiguity but does not enter order readiness until the customer selects
or explicitly names it.

### Operating-identity boundary

Stable operating facts are compiled into the cacheable main-model and
final-composer prompts from `runtime_v7.business_identity`. They cover the
online-first model, Makati head-office installation site, warehouse-to-booked-site
fulfillment, and the approved over-100 partner-network claim. This is reusable
brand context, not a question-specific rendered spiel.

Every final-composer turn plan carries the same versioned evidence ref and typed
`business_identity_facts` claim category so mixed intents and transitions use
one authority. That authority cannot establish exact coverage, nearby
availability, partner identity, stock, schedules, booking, pickup, or an
unreserved walk-in visit; those remain owned by their current providers and
deterministic surfaces. It does positively authorize installation at the head
office and must not be used to deny that service.

The main model and final composer also share one complete-turn composition
policy. It treats renderer-owned surfaces as part of the conversation: prose
before a surface connects the customer's request to the presented result, and
prose after it helps with the active decision or asks the next stage-appropriate
question. Operating facts such as partner-network scale are optional supporting
context and must be integrated into the answer or progression, not appended as
detached branding copy.

Signal relations remain semantic boundaries downstream of extraction.
`question_only`, `conditional`, and `historical` values may guide current-turn
interpretation or a read-only lookup, but they cannot satisfy lead qualification
or order readiness. A question such as `saan kayo located?` therefore cannot be
mistaken for the customer's own area or suppress the model's location CTA.

### Website Inquiry routing boundary

The existing image-evidence model classifies both semantic content and visible
source ownership. Gulong website, cart, checkout, payment, order-page, order
email, product-card/page, and marketing-asset surfaces produce a compact
`website_inquiry_evidence` signal only when the image visibly establishes
Gulong ownership. A tire photo or another merchant's page does not qualify.

This signal is routing context, not business truth. It cannot select a product,
confirm an order, authorize payment, or persist a commercial fact. When it is
present, or the contact already has the Website Inquiry tag, Runtime does not
emit Moderate Intent or High Intent routing tags. A synthetic Moderate still
emits a separate countable analytical qualification record whose routing
outcome is `suppressed_by_website_inquiry`; it is not a request to apply the
ManyChat Moderate tag. Independent operational tags such as Irate, Chatbot
Error, Order Booked, and Payment Confirmation are unaffected. The runtime owns
tag eligibility; the active ManyChat flow owns downstream CS assignment, which
must be audited separately.

### Commercial authority and tool-selection boundary

Capability exposure consistently includes the safe domain-specific FAQ readers
without consuming phrase-ranked hints. The main model decides whether product,
promo, location,
payment, policy, or brand evidence is relevant and supplies the proposed lookup
scope. The reviewed promo catalog, product provider, service provider, or active
checkout metadata returns the supported result; neither retrieval ranking nor
customer wording authorizes the fact.

The serving path does not run a second product-progression, location-choice, or
payment-query semantic decision after the main model. It also does not run an
independent model audit that can replace valid composed prose or its CTA. The
structured composer sees the complete typed evidence packet and owns the
concise Filipino/Taglish answer and next step. Deterministic validation remains
for exact commercial claims, trusted surface refs, tracked guided actions,
side effects, and hard order/submission safety. A structural or fact-contract
failure may request one bounded composer repair; it cannot silently invoke the
retired stage/CTA architecture.

### Brand knowledge authority

The public Gulong.ph brand directory and brand detail pages feed one immutable
Firestore publication:

`Gulong.ph pages -> brand sync/validation -> embeddings + structured profiles
-> active pointer -> Runtime V7 brand tool/composer`

Narrative background and comparisons may use vector similarity over the active
version. Exact origin, market segment, warranty duration, coverage, conditions,
claim process, and limitations come from structured fields on the selected
profile. Product/SKU warranty evidence remains more specific and wins when it
is available. The promo catalog continues to own promotional mechanics; its
offer-summary profiles are not brand-background authority.

The model proposes brands and a semantic question. Runtime verifies proposed
brand names against the current customer text or normalized trusted signals,
selects the active publication, attaches evidence refs, and authorizes only
the returned brand facts. Retrieval does not select a brand or advance an
order.

### Cross-surface continuity boundary

The current customer goal is model-owned across product, promo, service,
schedule, payment, and order transitions. Tool execution is evidence acquisition
and does not by itself replace that goal. Active Working Memory is updated by a
bounded model compactor on both plain and tool-backed turns using compact typed
signals and stable observation/presentation refs; an evidence-bound compactor
is retained only as the failure fallback.

`customer_turn_plan.known_customer_context` carries recognized facts that the
composer should reuse conversationally. It is deliberately separate from
`already_satisfied_fields`, authorized claim categories, side effects, and tool
action safety. A known location can therefore keep the conversation coherent
without being treated as a selected fulfillment path or validated schedule.

Short field-only replies inherit the unresolved conversational goal. For
example, a tire size supplied after installation coverage drives tire/product
selection for that same service journey; it does not automatically become a
new broad-promo inquiry. Once a trusted product is selected, the model can
resume service lookup with the retained location. FAQ interruptions similarly
answer the question first and then resume the pending customer decision when
the customer is still continuing.

Tracked product clicks bind the exact selected-product ref before model
composition. Their synthetic customer sentence contains only the selected
identity, not renderer-owned price, total, quantity, or promo text. Commercial
facts stay in the trusted product observation and deterministic presentation.
