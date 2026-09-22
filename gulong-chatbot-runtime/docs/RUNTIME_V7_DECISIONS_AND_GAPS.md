# Runtime V7 Decisions, Learnings, And Gaps

Last updated: 2026-09-16

This ledger records decisions that should survive individual probe threads.
Update it when a review creates a durable rule, exposes an anti-pattern,
parks an idea, or changes the validation bar.

## Decision: Nearby locations are preferences, not service evidence

- Preserve one customer location anchor independently from acceptable nearby
  service areas. Do not infer that an alternative is the customer's location,
  and do not replace the anchor with whichever area the model selects.
- Execute an unscoped service query against the normalized anchor. A provider
  result authorizes availability only for that exact query area; separate areas
  require separate lookups and evidence refs.
- Empty product observations cannot unlock schedule progression. A usable
  delivered/validated product or explicit schedule constraint is required
  before slot lookup; otherwise check partner coverage first.
- Exact service summaries and partial product-match notices remain
  provider-owned. The composer may add connective prose and one next question,
  while typed claim validation and claim-unit sanitization prevent unsupported
  restatement without keyword matching.
- Adaptive return-only replay and local tests validate pre-delivery behavior,
  provider calls, synthetic Firestore persistence, and trace generation. They
  do not prove ManyChat delivery, live traffic behavior, or BigQuery landing;
  those remain release-gate responsibilities.

## Decision: Vehicle fitment and customer prohibitions are hard

- Exact tire size, explicit EV compatibility, and explicit exclusions are the
  hard presentation boundary. Brand, model, terrain/category, budget, origin,
  warranty, availability, promo, guarantee, and installment requests are
  preferences that may relax only on exact-fitment products with deterministic
  per-card disclosure.
- A brand mention is not itself a prohibition. `brand_match_mode` defaults to
  `prefer`; only explicit brand-only/no-other-brand semantics become `strict`.
  Requested-brand options appear before cross-brand alternatives, and strict
  mode never crosses the requested brands.
- Relaxing a search preference never relaxes commercial truth. A card can be
  shown as a non-promo, unavailable/pre-order, non-guarantee, or unsupported-
  installment alternative only when that mismatch is explicit; the renderer
  never claims the requested benefit for that card.
- Missing media does not erase a valid product from the text price list. It
  does prevent visual-card rendering and tracked-button authorization.
- Canonical terrain abbreviations are recovered from the latest customer turn,
  but ordinary conversational `at` is a negative control. A terrain label is
  not accepted as a product model, and model prose cannot preempt a
  provider-owned partial-match disclosure.

## Decision: Card links fail soft; delivered-card selections retain identity

- Catalog link validation is generic and based on structured card identity.
  A stale link is withheld without discarding valid product, price, image, or
  tracked-action content. Card-specific URL substitutions are prohibited.
- A customer category/value selection over delivered cards must bind through
  trusted visible-product state before product facts carry into service/order
  progression. New product filters still require a fresh read.
- Local multi-turn probes must simulate delivery only from customer-visible
  rendered cards; generated but unseen observations are not selectable.
- The 9/10 semantic result permits controlled staging evaluation, not direct
  production promotion or a claim of measured Moderate/High intent lift. The
  explicit warranty-coverage miss remains open.

## Decision: Required answers fail softly; supporting warranty remains renderer-owned

- A successful grounded product, location, service, order, payment, or FAQ
  result creates a visible answer obligation. The final composer may order and
  connect those answers naturally, but it cannot omit a required surface or
  return an empty/unknown-only plan.
- Runtime validation is structural and fail-soft. It checks unit renderability,
  exact refs, required surfaces, typed request mappings, and optional decision
  conflicts. It does not score prose quality or reject a complete turn through
  broad keyword rules. One bounded repair is allowed; failed repair preserves
  unaffected prose and appends required grounded surfaces.
- The automatic first-TPP Double Warranty gallery remains the replacement for
  the old long warranty spiel. It is a `supporting_replacement`, not a new
  customer request or CTA layer. Its card mechanics are withheld from composer
  prose; the renderer still owns the exact gallery and Promo Details button,
  while the model may keep at most one next question on the active product
  choice.
- The product renderer continues to own the structured product text and trusted
  image gallery with tracked product-selection buttons. Information-overload
  correction removes duplicate prose and unrelated optional surfaces; it does
  not strip this product presentation.
- Low-information behavior is starter-specific. Tire-help leads with one
  size/vehicle discovery input and may use promo only as support; `How to
  avail?` answers purchase process first; availability may still use a useful
  reviewed promo entry. Observational August cohorts do not prove a universal
  promo or no-promo winner, so release evaluation needs a stable holdout.
- A complete-size price or concrete-options request is a product-evidence
  obligation. Reviewed promo retrieval may support that turn but cannot replace
  `product_search` or a deliberate product-narrowing surface. TPP alone never
  authorizes the model to request a broad promo gallery; the runtime attaches
  the single reviewed Double Warranty replacement card.
- Cross-domain recovery is fail-safe and bounded. An unexposed registered
  read-only tool call can trigger one schema recompile that preserves current
  domains. The call is not executed until the model retries against the exposed
  schema; unknown tools, mutations, and repeated domains remain rejected.
- Scope/owner: `runtime_v7.model_contract`, `runtime_v7.runtime_harness`,
  `runtime_v7.triage_seeds`, and `runtime_v7.channel_renderer` verification.
  Bounded local semantic evaluation is complete; staging and live channel
  delivery remain pending.

## Decision: Deterministic intent lineage is metadata, not a new qualification rule

- Provisional Runtime V7 lineage is identified by
  `decision_mode="deterministic"` and
  `rule_version="gulong_intent_v2_20260811"` on the lead snapshot and its
  analytical Moderate record. The analytical record copies snapshot values;
  older callers use the exported rule-version constant as fallback.
- The existing predicate remains authoritative: tire size plus at least two of
  tire brand, location, and a plausible Philippine mobile contact. Size plus
  brand/product alone stays incomplete, while size plus brand plus location or
  qualifying contact remains Moderate; arbitrary contact text cannot fill the
  gate.
  Lineage fields must not change `qualification_level="moderate"` or
  `countable=True` behavior.
- Scope/owner: `runtime_v7.lead_qualification` owns the snapshot metadata and
  existing predicate; `runtime_v7.tagging` records the same metadata in the
  routing-independent analytical object. This local decision does not claim a
  deployment or warehouse schema migration.

## Decision: Analytical qualification is independent from ManyChat routing tags

- A synthetic Moderate is a countable Runtime V7 analytical event even when
  Website Inquiry policy suppresses the `Moderate Intent` routing tag. The
  `turn_trace_log.tagging.analytical_qualifications` object owns the durable
  analytical record; a tag is only downstream routing/application evidence.
- The record must retain stable event/idempotency identity, environment,
  user/session/turn context, occurred-at time, qualification level, redacted
  source signals, evidence refs, and tag application outcome. Append-only trace
  rows are deduplicated by `qualification_event_id`.
- Tracked actions must preserve presentation/card/surface/choice identifiers.
  A retained delivered presentation ref is authoritative for what was shown;
  a catalog-card fallback supports correlation only and cannot prove delivery.
- Positive scenario: a Website-derived customer satisfies Moderate fields and
  produces one countable Moderate with routing outcome
  `suppressed_by_website_inquiry`. Negative control: a non-Moderate turn emits
  no analytical qualification object.
- Scope/owner: `runtime_v7.tagging`, API trace persistence, and the typed
  action ledgers. ManyChat still owns tag delivery and downstream assignment.

## Learning candidate: Normalize clear customer terminology silently

- Captured: 2026-08-11
- Promotion status: candidate
- Symptom: A grounded payment answer quoted the customer's word `downpayment`
  and explicitly announced that it was called a reservation fee, making a
  routine reply sound corrective and assistant-like.
- Root cause: The prompt required the correct term but did not distinguish
  silent normalization from customer-facing correction.
- Proposed practice: When context makes shorthand, a typo, or an informal
  equivalent unambiguous, use the correct business term naturally without
  quoting or announcing the correction. Clarify only when plausible meanings
  would materially change the answer or action.
- Scope/owner: Runtime V7 model and final-composer voice contracts.
- Positive scenario: A downpayment question receives a direct reservation-fee
  answer. Negative control: an ambiguous size fragment still requests
  clarification rather than silently choosing a dimension.
- Expected benefit: More natural human-agent tone without weakening commercial
  authority or adding deterministic text rewriting.

## Learning candidate: Aggregate broad commercial choices before composition

- Captured: 2026-08-11
- Promotion status: candidate
- Symptom: A broad credit-card installment question could be answered from the
  first checkout row even while the deterministic product card displayed a
  second, equally valid installment term.
- Root cause: A broad customer category was passed through a narrow single-row
  selector, and malformed typed extractor fields could accidentally narrow it
  further.
- Proposed practice: At the commercial source boundary, validate typed scope and
  aggregate all currently applicable options for broad questions. Preserve
  narrow selection only for an explicit customer bank or term. Let the model
  compose the grounded set naturally while deterministic cards retain exact
  presentation ownership. Resolve product-card installment text against active
  checkout metadata on every search, not only when the model happened to add an
  installment filter; the renderer is presentation, not a competing authority.
- Scope/owner: Runtime V7 typed payment hydration and active-checkout FAQ
  projection.
- Positive scenario: "Credit card installment?" receives every applicable term
  and source-backed bank association without a standalone checkout label.
- Negative control: "BPI 6 months?" remains a BPI/six-month lookup and does not
  dump unrelated options.
- Expected benefit: Removes source-order contradictions without adding
  brand-specific prompt rules or post-model rewriting.

## Learning candidate: Preserve typed control meaning through final composition

- Captured: 2026-08-11
- Promotion status: candidate
- Symptom: A customer clicking the ManyChat `Get Started` entry control received
  a long how-to-order FAQ answer instead of a compact shopping welcome.
- Root cause: Decorated control text could miss exact starter normalization, and
  normal typed response seeds reached the main planner but not the final
  composer after a tool call.
- Proposed practice: Normalize only approved platform chrome before exact
  control matching, then carry the resulting typed intent through every model
  composition stage. Keep wording, CTA, and optional surface selection
  model-owned. For a genuinely low-information welcome, acknowledge the exact
  starter goal and ask one connected discovery question. A reviewed promo
  gallery may accompany that step when useful, but is not universally primary:
  tire-help leads with size/vehicle, `How to avail?` answers process first, and
  availability may use promo as a concrete entry. Define low information by the
  absence of usable shopping criteria and a specific
  service/policy/business/order goal. When the chosen action is an available
  read-only lookup or reviewed surface, perform it in the same turn instead of
  adding a permission question. Do not repair the response afterward with
  scripted prose.
- Scope/owner: Runtime V7 guided-control normalization, model context, and final
  composition context.
- Positive scenario: Plain or checkmark-decorated `Get Started` opens a shopping
  conversation and asks or presents one useful next step.
- Negative control: `How do I get started with ordering?` and compound messages
  containing size, brand, location, or promo details remain ordinary free text
  for whole-message model reasoning.
- Expected benefit: Prevents starter controls from drifting into unrelated FAQ
  answers while avoiding phrase routing for normal customer messages.

## Learning candidate: Separate guided navigation from customer consent

- Captured: 2026-08-09
- Promotion status: candidate
- Symptom: An `Others` installation-area click correctly led the model to offer
  delivery, but synthetic bridge prose also caused order readiness to record
  delivery before the customer accepted it.
- Root cause: The state extractor could not distinguish router-authored
  transition guidance from a customer-authored fulfillment choice.
- Proposed practice: Guided actions should declare both their recommended next
  path and whether the customer actually selected that path. Deterministic
  state boundaries may enforce that typed consent distinction, while the model
  still owns the wording and next question.
- Scope/owner: Runtime V7 guided-action context, signal extraction/retention,
  order readiness, and adaptive endpoint evaluation.
- Positive scenario: `Others` offers delivery without selecting it. If the
  customer had already explicitly chosen delivery, that trusted choice and
  address remain; otherwise fulfillment stays unset until the customer
  confirms or supplies delivery details.
- Negative control: Clicking a listed serviceable province or city still
  records installation context because that exact surface action carries those
  semantics.
- Expected benefit: Prevents false order progression without adding semantic
  CTA rewrites or weakening validated guided choices.

## Learning candidate: Keep first-turn quality model-owned and validation structural

- Captured: 2026-08-06
- Promotion status: candidate
- Symptom: A branded-substring gate accepted copied welcome prose as complete while rejecting valid natural openings without the exact brand phrase.
- Root cause: Deterministic code tried to infer conversational completeness and human quality from one phrase instead of checking response-unit order and leaving qualitative judgment to review.
- Proposed practice: Require only a nonempty text unit before any guided surface, retain fixed copy for empty malformed or surface-first failure, and evaluate tone/directness with bounded complete-turn review.
- Scope/owner: Runtime V7 first-turn composer, renderer, endpoint probes, and offline evaluators.
- Positive scenario: A natural first response answers the customer before a product or location surface even when its wording differs from the fixed welcome.
- Negative control: A surface-first or blank structured response still receives repair or the fixed fallback.
- Expected benefit: Reduces robotic phrasing and false evaluator failures without weakening deterministic commercial surfaces.

## Learning candidate: Disambiguate human availability from product availability before FAQ retrieval

- Captured: 2026-08-06
- Promotion status: candidate
- Symptom: A customer asking whether anyone was available to assist received limited-stock and order-confirmation language.
- Root cause: The FAQ matcher treated the token `available` as product-stock evidence despite nearby human and assistance nouns.
- Proposed practice: Suppress only the limited-stock FAQ for human-support availability context, preserve direct stock questions, and route the turn to a brief answer plus one open assistance question.
- Scope/owner: Runtime V7 FAQ hints and first-turn response seeds.
- Positive scenario: `Is there anyone available to assist?` receives a direct assistance response and no product FAQ hint.
- Negative control: `Is this tire still available today?` remains eligible for product availability guidance.
- Expected benefit: Prevents unsupported order/stock messaging while preserving genuine inventory questions.

## Durable Design Decisions

- Treat a customer-visible turn as one composed sequence even when runtime owns
  its factual surfaces. Give the model compact role/ordering context, not exact
  duplicated bodies, and let it write only the acknowledgement, direct context,
  explanation, and one appropriate next step. Deterministic surfaces remain the
  authority for price, promo, availability, order, and payment facts.
- On every nonempty first turn, the model owns the complete greeting or
  acknowledgement, answer context, and transition before any guided surface.
  Runtime owns whether an opening is required, exact high-risk surfaces, and a
  fixed-copy failure fallback—not normal-path greeting prose. Full guided intake
  remains a compatibility/failure mode. Safety guards inspect model-authored structured text
  before trusted surfaces render so fallback cannot erase valid choices.
  Opening validation checks only nonempty text-first ordering; the prompt asks
  for Gulong.ph identification, but the structural gate deliberately does not
  treat a brand phrase, greeting vocabulary, casual wording, or emoji as proof
  of customer-service quality.
- Missing authorization metadata is not the same state as an explicit empty
  allowlist. Skip the typed claim validator only when its contract is absent;
  preserve fail-closed behavior whenever the contract keys are present.
- Complete-turn qualitative approval remains an orchestrator/human-CS judgment,
  not a sentence-regex, greeting, emoji, character-count, or question-count
  classifier. Deterministic evaluation is limited to facts, refs, ordering,
  active decision layers, delivery/evidence strength, side-effect truth, and
  explicit runtime contract signals. Use varied paraphrased customer inputs and
  preserve the observed output plus rationale for review reproducibility.
- Do not add production telemetry for evaluation fields already present in the
  existing debug/probe artifact. Build a minimized offline review bundle from
  an approved or pre-redacted source first. Add a new runtime log field only after a concrete
  historical-review gap is demonstrated and cannot be recovered safely.

- Do not solve repeated semantic-composition failures with a hard customer-turn
  call cutoff. Reduce duplicated reasoning instead: answer-only turns carry only
  current answer authority, and a semantic rejection goes directly to one
  evidence-only repair plus one independent audit. Keep transport/schema
  recovery available, then fail closed to the authored fallback if meaning is
  still unsafe. This shortens the expensive path without risking an empty turn.
- A repair audit may reject implication without revoking the initial audit's
  answer-goal relevance decision. If the initial normal-response audit found an
  authored answer aligned, partial, or unresolved, safe fallback keeps the
  provider text and adds the exact-case-pending boundary. Omit authored text
  only when that first audit explicitly found the answer goal misaligned.
- Composer and validator must consume the same canonical provider refs. A
  successful promo search's allowed offer refs are evidence identities, while
  the audit's `customer_requested_promo_fact` field is only a completeness
  judgment. Neither model output nor proactive presentation creates commercial
  authority.
- Negative commercial claims must stay within one provider's actual coverage.
  A reviewed campaign-catalog no-match can establish only that exact scoped
  campaign result; it cannot deny quantity, bundle, voucher, discount, price,
  or SKU promos owned by exact-size product search. Keep those facts pending
  until product evidence exists. Encode the boundary in composer context and
  semantic audit state, not brand/promo keywords or output-text rewrites.
  Customer copy should express what is confirmed and what remains pending,
  never the internal catalog/search/provider/evidence vocabulary used to
  enforce that boundary.
- The initial multi-product selection must show both the complete long-form
  price list and the image gallery. One prepared displayed-product set owns the
  list, cards, tracked choices, metadata, and delivery history so a card cannot
  borrow a neighboring SKU's image or diverge from the price list. Prefer a
  query-valid image-backed replacement from the already fetched ranked pool;
  otherwise exclude only the image-less candidate. If no image-backed
  candidate remains, keep the truthful text-only result. Do not make extra
  provider/image calls or relax customer constraints to fill the gallery.
- Repeating a product list does not justify hiding its price details unless the
  same stable card identities were already delivered or evaluated together as
  a list-and-gallery presentation. Older, failed, expired, or text-only history
  cannot suppress the list. A selected exact SKU continues through the normal
  exact-product path.
- Successful authored FAQ and business-contact answers receive a bounded
  semantic answer-goal audit because lexical retrieval can be mechanically
  successful yet answer a different question. The audit may reject or repair
  the answer but cannot authorize facts. Keep it scoped to grounded authored
  answer turns rather than adding an LLM call to every conversation.
- Case-specific pending enforcement belongs only to authored general-policy
  evidence that cannot resolve the customer's exact case. Do not apply that
  restriction to checkout metadata or another provider result that directly
  resolves the exact requested brand, method, product, service, or order fact.
- When an exact promo scope returns no verified match and the model has already
  authorized ordinary price-category navigation, the provider-owned scoped
  result and non-promo category surface win over every composer terminal
  status, including renderer fallback. A fallback status must not erase a
  validated surface or turn "none verified" into an offer to search again.
- Named payment methods must come from a typed semantic field. Never fall back
  to treating the customer's full sentence as the method name. Unsupported
  methods should state what is available, using a bounded current-provider
  sample, instead of producing a contradictory generic denial followed by the
  complete method list.
- Keep named payment entities separate from open method categories. A concrete
  unknown provider still requires API validation, while "available e-wallets"
  or another typed category is answered from matching active catalog rows and
  must not become an unsupported named-method fact. Alias and provider matching
  must preserve distinct credit, loan, card, and installment products rather
  than using substrings after strict matching rejects the complete name.
- A provider-backed payment conflict or empty category is itself an authored
  result. Never fall back to static FAQ prose merely because no exact checkout
  row was selected; that can reintroduce stale bank/rate facts.
- A selected strong FAQ hint may be enforced with one tool retry when the model
  omits its exposed authority. Reuse the selected FAQ id rather than adding
  phrase rules or a new classifier call, and suppress the retry after another
  recovery or while a current checkout choice is being committed.
- Apply the payment semantic gate by resolved authored FAQ identity, not by the
  shared `answer_order_faq` tool name. A non-payment order FAQ should remain
  executable when the payment classifier correctly returns no request.
- Once retrieval selects an authored Runtime V7 FAQ goal, an owned policy
  answer wins over semantically nearby legacy chunks. Use this boundary for
  stable guidance such as reading a DOT week/year code or progressing a formal
  quotation, while leaving exact product batches, final quotes, taxes, stock,
  totals, and order state with their authoritative providers or CS process.
- Exact operational URLs in reviewed promo source are deterministic catalog
  facts. The extractor may summarize surrounding prose, but source-section
  reconciliation must retain each exact claim, submission, or campaign URL in
  the owning promo mechanics. A reviewer-visible label without its URL is not
  an acceptable extraction result.
- A same-month review refresh must keep at least one Google Sheet visible at
  every API step. Rename the completed tabs, create the replacement visible
  month tabs, and only then hide the archive; a single batch that hides all old
  tabs before adding replacements is invalid even when its intended final
  state contains visible tabs.
- Promo approval uses one workbook per month in the separate
  `Promo Catalog Reviews` folder; source mechanics and posters remain under the
  month folders in `Promo Source`. Current physical tabs must put the month
  first and identify the approval tab explicitly. Same-month revisions may
  retain version snapshots in that workbook, but cross-month workbook reuse
  fails closed. Runtime code continues to address stable logical tab roles so
  reviewer-friendly naming cannot weaken publication validation.
- A Drive source may be either a parent of monthly folders or the month's
  folder itself. The sync must recognize the latter only when both configured
  `Promo Images` and `Promo Mechanics` folders are present, preserving a
  deterministic source boundary without folder-ID exceptions.

- When promo discovery returns evidence but no usable renderer surface, the
  next product step remains a semantic decision. A bounded model call may
  choose priced products, exact options, broad brand/price categories,
  promo-only handling, or clarification from the complete turn and compact
  outcome state. Runtime may execute only a selected read-only tool backed by
  one normalized concrete tire size. Do not convert a missing promo image into
  a hard-coded category fallback, customer-text regex, or response rewrite.
  Rationale: the main loop cannot reason again once its tool rounds are spent,
  while the final composer cannot call tools. The reasoning checkpoint restores
  that missing decision boundary without making runtime code own intent.
- Natural-language store, branch, coverage-area, and installation-location
  intent is model-led. Do not add exact phrases, regexes, brands, SKUs, or
  screenshot examples to decide eligibility for province controls. The main
  model proposes the action, a bounded typed semantic decision authorizes it,
  and one no-tool recovery may reuse that same decision.
  Rationale: free-form location language is too varied for a maintainable
  phrase gate, while provider access and a renderer action still need a
  fail-closed boundary. Deterministic code therefore validates only normalized
  delivery/location/selection state, current provider results, and tracked
  rendering mechanics. Generic unresolved location candidates cannot expose
  concrete partner/slot tools, and routing-only image evidence remains outside
  commercial, service, and order authority.
- Automated release checks own objective contracts only: transport, provider
  evidence, typed claims, state transitions, surface refs, and side effects.
  Human/CS review owns whether the complete customer-visible turn is correct in
  context, clear, natural, and commercially useful. Wording regexes must not
  overrule a correct rendered answer or stand in for customer-experience
  review.
- A structured product result may reconcile a current promo-provider fact even
  when the reviewed gallery has no brand card, but only when its pricing basis
  proves the same requested promo type. An unrelated sale or bundle discount
  cannot satisfy a Buy 3 Get 1 inquiry.
- Pure payment-policy turns may use a compact mode of the existing final
  composer. This changes prompt focus, not ownership or call count: the model
  still composes the reply, and runtime still validates the authoritative
  claim objects before delivery.
- `product_search.required_brands` and supplied tire-size components are hard
  customer-card constraints. Other brands/sizes may remain diagnostic
  candidates, but they render only when the model proposes an explicit
  alternatives/compare preference or runs a separate relaxed search.
- A tracked button label is not evidence of the customer's language
  preference. The composer continues the most recent natural free-text
  language/register from the conversation for button-only turns.
- A validated tracked informational action owns its continuation turn. Do not
  run generic no-tool location recovery after Promo Details or About Brand;
  the action's typed catalog/profile evidence is already the active answer
  goal. This is an interaction-state boundary, not a caption or keyword rule,
  and it removes an unnecessary semantic/provider call.
- The final composer is the semantic owner of a complete successful customer
  turn. Runtime supplies a validated turn plan and checks the output; it does
  not silently improve ordinary wording after composition. A deterministic
  sentence is reserved for failed structured repair.
- Location precision is an authorization fact, not conversational intent. A
  province can authorize a city-choice surface but cannot authorize selectable
  partner schedules. Exact city evidence is required before slot state or
  controls can be persisted.
- Availability-ranked city suggestions are previews, not selections. They run
  in an isolated observation store, expose only an earliest-slot preview, and
  require a fresh city-specific lookup after the customer chooses.
- Brand-level Buy 3 Get 1 eligibility comes from the current `/promo_brands`
  response. Reviewed promo documents own their mechanics and gallery content,
  but absence from that document set is not evidence that an API-listed brand
  is ineligible.
  Rationale: the live endpoint included Vredestein while the reviewed gallery
  contained Michelin and Apollo. Treating the smaller gallery as a negative
  allowlist would have rejected a valid current offer.
- A turn may answer several grounded questions, but it must render at most one
  active customer-choice layer. A product-search result awaiting confirmation
  precedes prepared location, schedule, and payment controls, even when only
  one SKU is visible.
  Rationale: simultaneous SKU buttons and a location CTA made the required
  customer action ambiguous and triggered composer fallback.
- Brandless promo discovery without a tire size remains an informational promo
  decision. It renders reviewed promo controls and asks for size; it does not
  let an over-broad product search replace the gallery with arbitrary SKUs.

- A direct contact-channel question can still receive the existing long
  first-turn intake before its answer. This predates semantic location planning
  and remains a separate response-composition review; it should not be solved
  by restoring deterministic natural-language intent replies.

- Runtime V7 remains one model-led tool loop with deterministic validation,
  canonicalization, refs, and rendering. Do not add planner/synth/multi-agent
  orchestration without an explicit architecture decision.
  Rationale: most failures reviewed so far came from missing/ambiguous context,
  stale state, tool-output semantics, or response rendering, not from needing a
  separate planning agent.
- Gemini through LiteLLM is the current model path. All LLM calls go through
  the V7 LLM gateway.
  Rationale: cache behavior, usage/cost accounting, reasoning controls, and
  response-format handling need one auditable transport boundary.
- Model interpretation owns customer intent and response composition. Runtime
  support should improve context, schemas, tool output semantics, and final
  composer instructions before adding deterministic prose mutation.
  Rationale: earlier CTA/lead-in and same-day cleanup guards fixed narrow
  examples but hid model/context weaknesses and sometimes damaged tone.
- Deterministic guards validate the result of model reasoning; they do not
  prescribe a happy-path conversation before reasoning. The model may interpret
  mixed questions, free-form choices, revised choices, and non-linear turns,
  and may run every relevant read-only evidence lookup. Runtime then validates
  proposed tool arguments, evidence refs, commercial assertions, persistence,
  and real-world actions. "One active decision" limits only the next requested
  customer input and visible control layer, not the questions that may be
  answered in that response.
  Rationale: a rigid phrase gate missed natural choice changes, while broad CTA
  suppression risked hiding grounded answers. Typed current-turn signals plus
  validated UI actions are proposed transitions; hydrated state decides
  whether applying them changes anything. Event IDs alone are insufficient
  because a channel can emit different IDs for the same repeated control.
  Narrow post-reasoning enforcement preserves flexibility and safety
  together.
- Product-card follow-up text is not assumed to be product selection.
  Objections, comparisons, fitment changes, commercial questions, and service
  questions remain conversational input. Only an explicit resolved visible
  product reference or validated product control may commit the SKU.
  Rationale: live response analysis showed that typed replies after product
  cards were mostly continued evaluation, while mixed product-and-schedule
  prompts materially reduced product-control usage.
- Background Signal candidates are advisory until normalized with closed
  provenance. Durable typed signals sourced from the latest customer message
  or a validated guided action may persist and influence readiness; AWM,
  narrative summaries, untraceable legacy rows, and product/service
  observations cannot. No signal may override a fresher customer correction or
  the exact fact authority of a trusted tool.
  Rationale: treating every signal as advisory lost valid customer choices,
  while treating observations/history as equally authoritative revived stale
  state and manufactured progression.
- Background Signal meaning is typed separately from the value. Conditions,
  questions, retractions, corrections, and historical references must not be
  encoded only in free-form status text. Only asserted, selected, and corrected
  relations may cross the memory/ledger boundary; rejected values remove prior
  state instead of becoming a new fact.
  Rationale: a conditional Pay Now question was retained as a checkout choice,
  and a later explicit "not chosen" correction did not clear it. Typed
  relations give deterministic persistence policy without reinterpreting raw
  customer text.
- Human takeover is a model-proposed typed action with deterministic side-effect
  and truth boundaries. A successful request stores durable state and requests
  `Stop Chatbot`; composer copy may acknowledge the request but may not claim
  downstream assignment or connection without evidence.
  Rationale: `request_capability` expands internal tools and is not a human
  handoff. Treating it as one caused false escalation language, no routing tag,
  and later automated replies.
- A mutating semantic action requires independent typed authorization when a
  false positive would silence the bot or change downstream ownership. For
  human handoff, the main loop proposes the action and a bounded semantic
  decision distinguishes takeover-now from availability-only, complaint-only,
  not-requested, or unclear. Only takeover-now may persist state or tag.
  Rationale: a live negative control asking whether human agents exist caused
  the main loop to call the handoff tool despite the tool description.
- Model-proposed lookup strings are not named commercial entities. A bounded
  payment-query decision classifies named-method, payment-option, generic, and
  no-payment-request scope. Payment FAQ execution replaces the proposed method
  with typed scope/customer evidence or rejects the lookup; it never passes the
  entire utterance as a provider.
  Rationale: a live correction/no-choice turn was rendered as if the complete
  customer sentence were an unsupported payment method. The same authorization
  must govern both main-loop tools and API pre-composer lookup completion. A
  typed named entity must also satisfy a generic bounded scalar shape; semantic
  classification alone is not sufficient evidence that the field is an entity.
- Semantic completion is not a general negative classifier. The pre-composer
  payment step may run only after a typed payment decision or payment-scoped
  tool evidence already establishes its domain; unrelated turns take a typed
  zero-call skip path.
  Rationale: running a domain-specific evaluator on nearly every request added
  about one model call per unrelated turn in recent live releases. Release
  review must therefore include per-component calls/request and token deltas,
  not only correctness, latency, and delivery checks. Broader call-graph
  simplification remains a separate change after containment is measured.
- Active Working Memory is descriptive. It should not store policy, stale
  missing-field checklists, or unvalidated prices/promos/slots/payment facts.
  Rationale: AWM is always loaded, so directive or stale content can quietly
  dominate future turns.
- Commercial authority is source-specific, not transcript-specific. The active
  checkout metadata API (/payment/list) is the authority for payment methods,
  bank/term choices, brand allow lists, and transaction exclusions; the active
  reviewed promo catalog and /promo_brands are the authority for current promo
  mechanics and promo-brand eligibility. Model arguments and AWM are proposed
  context only, never evidence.
  Rationale: a bootstrap static installment list drifted from the checkout API.
  The current API and website checkout exclude Yokohama from BPI 6-month while
  retaining unrestricted 3-month installment. A model must be able to ask a
  natural question without choosing the business source or overriding a newer
  source record.
- Structured payment signals expose payment-policy validation without making
  the signal itself authoritative. A customer may ask about any named method
  before choosing a product; the model can call `answer_order_faq`, which
  resolves support against `/payment/list`. A stated preference may remain
  unconfirmed context without being promoted to availability.
- A named payment/provider inquiry is retained as a typed
  `mentioned_unconfirmed` payment signal. This is routing evidence for the
  read-only checkout policy resolver, not a checkout selection. Omitting the
  candidate entirely can hide the payment capability during a mixed product
  turn; treating it as confirmed can leak the inquiry into order state.
- Customer area and selected partner address are separate facts. For
  installation/pickup/home-service summaries and submit payloads, validated
  readiness/customer location supersedes a conflicting model `location` arg;
  the selected service observation independently supplies partner identity and
  address.
- An unsupported commercial request and a valid-but-unavailable request are
  different outcomes. Unsupported methods/mechanics are answered from the
  source-backed policy with a natural next option; an eligible promo/brand with
  no exact-size stock is an availability result only after the exact base query
  is run. A product that misses promo_only is diagnostic context, never a
  promo card.
- Product cards, brand menus, service slot rows, order summaries, and payment
  details are deterministic renderer surfaces. The model should not rewrite
  exact card/payment/order text.
- Tool outputs should include compact headers and refs for the model, not large
  upstream dumps.
- Product visibility should use trusted customer-catalog evidence when
  available. The denylist is a temporary practical fallback, not the ideal
  visibility model.
- Installation partner disclosure is staged. Prefer area/availability first,
  then exact details at order summary/proceed context or when explicitly forced
  with the no-walk-in policy.
- `build_order_payload` and `submit_order` are separate tools. Submit consumes
  a validated payload ref rather than reconstructing an order from conversation
  text.
- Payment request follows successful submit/order context. The renderer inserts
  exact QR, link, account, and amount details.
- Payment requests must prefer backend readback amounts from `/order` or
  `/order_details` when available. If the backend amount differs from V7's
  validated payload total, expose the difference as a verification note instead
  of silently presenting one amount as unquestionably final.
- Order quotes, summaries, and payload totals must use backend checkout pricing
  semantics, not product-card display math, once the customer is in an order
  action. Sale-tag products use the backend checkout formula from the submit
  cart (`promo_price * quantity`, minus the quantity discount when applicable),
  while product cards may still show their own customer-facing quantity total.
  If these differ, keep the checkout total authoritative and expose the
  adjustment in diagnostics.
- For installation/service orders, a raw preferred date/time from Background
  Signals or model args is not a selected schedule. `validate_installation_slot`
  must ground the slot before readiness can expose a ready install summary or
  `build_order_payload`.
- Order summaries may show incomplete "details so far" surfaces, but
  `build_order_payload` remains the submit-readiness boundary. Summary
  readiness and payload readiness must use the same canonicalization helpers
  for names, email, fulfillment, payment, and selected product context.
- Order payment FAQs should be scoped by structured fulfillment context when it
  is already known. Installation/card contexts should not receive delivery-only
  wording, and this scoping must come from structured fields such as
  `service_type` / `fulfillment_path`, not raw customer-text matching.
- Product-card quantity totals already include the visible promo. The model and
  tools must not subtract the same promo again when explaining or summarizing an
  order. Cards should show the base price per tire and the requested-quantity
  total, not an amortized effective price per tire.
- Conversation hydration is segment-based. Reset and old adjacent-message gaps
  start new model-facing segments.
  Rationale: V7 must continue human-agent threads, but stale older messages can
  leak obsolete context into current turns if segment boundaries are too broad,
  causing the model to answer a fresh customer with old
  product/location/order context.
- VM + Cloud SQL runtime migration must use sticky canary routing by `user_id`.
  Rationale: mixing the same user between Cloud Run/Firestore and VM/Cloud SQL
  can create split-brain session state and duplicate idempotency records. The
  VM path should stay `RUNTIME_DELIVERY_MODE=return_only` until tester/manual
  validation is clean, then only receive a stable low-volume canary segment.
- V7 API ingress uses a short per-session active-turn lock, CAS-backed session
  saves, and a pre-delivery ManyChat freshness check.
  Rationale: ManyChat can trigger overlapping external HTTP requests and human
  agents can intervene while a model/tool loop is still running. The current
  production-safe behavior is to suppress stale responses when a newer
  human-agent message is visible before delivery. A newer user message is
  recorded as a freshness warning but does not suppress the already generated
  response, because the newer webhook can be skipped by the active-turn lock.
- If a request cannot acquire the per-session active-turn lock, return an
  explicit non-success runtime status and persist the skipped-turn trace.
  Rationale: an empty `success` payload can silently drop a legitimate
  overlapping turn and leaves no production evidence for diagnosis.
- V7 API turns persist full debug traces through the analytics gateway and emit
  compact `runtime_v7_turn_trace` Cloud Logging lines.
  Rationale: screenshots and returned debug payloads are not enough for live
  diagnosis. Operators need request/session/trace lookup, cost/usage, tool
  args/results, rendered content, delivery status, and tagging status after the
  HTTP caller has returned.
- Observability should be version-neutral: component spans and state snapshots
  should support cross-runtime analysis instead of V7-only trace names.
  Rationale: operational analysis should compare V7 with V6/future runtimes
  without rebuilding every query around runtime-specific field names.
- Follow-up remains a linear API-side flow, not a second orchestration graph.
  Assistant-last proactive evaluation uses one structured model call;
  customer-last missed turns use the existing normal Runtime V7 chat loop.
  Rationale: splitting decision and composition compounded inconsistency while
  adding no authority. One strategy call plus deterministic evidence rendering
  keeps behavior auditable without introducing LangGraph.
- Follow-up delivery admission is authenticated and server-owned. Both stop
  tags and human takeover block the route. `FOLLOWUP_SEND_ENABLED` defaults
  false and request payloads cannot override delivery, force, transcript,
  profile, time, logging, or analytics behavior.
  Rationale: the endpoint can send unsolicited customer messages and must not
  expose operational controls to a public webhook payload.
- A missing field is not sufficient reason to send. The model may defer or
  suppress, and explicit future/just-inquiry intent normally defers the first
  and second cadences. Runtime never converts a model suppression into a send.
  Rationale: the rolled-back release showed that forced sales progression can
  damage low-pressure leads.
- Conversation is primary continuity evidence. Normalized customer/profile
  facts are included only with provenance, while AWM and Background Signals are
  not independent prompt truth. Exact delivered product cards, selected-product
  refs, and service refs remain separate evidence types.
  Rationale: interpreted state can be stale or generated without the active
  conversational context; source separation lets the model reason over the
  transcript without losing canonical values.
- The model selects strategy and evidence refs; deterministic code owns exact
  commercial claims and exactly one CTA. Buy 3 Get 1 requires both delivered
  card evidence and current `/promo_brands` eligibility. Invalid output
  suppresses instead of using a generic fallback.
  Rationale: the BFGoodrich incident was an evidence-association failure, not a
  wording problem. Sanitizing or templating after generation cannot safely
  repair a wrongly attributed offer.
- Attempt rotation is delivery-aware. `sending` precedes ManyChat, only
  confirmed success becomes `sent`, failed/invalid attempts retry after
  cooldown, and unknown delivery reconciles by transcript hash before retry.
  Only sent focus fields are excluded from later cadences.
  Rationale: evaluated or failed attempts are not customer-visible, while
  unknown delivery must block duplicate sends until resolved.

## Anti-Patterns To Migrate Or Avoid

- Raw utterance keyword/regex classification for order intent, product
  category, payment choice, service intent, or final response shape.
- Broad phrase-based response sanitizers that rewrite model copy instead of
  fixing prompts, tool semantics, response-unit contracts, or renderer-owned
  surfaces. Bounded channel-safety cleanup, such as follow-up URL/trailing
  thanks removal, is acceptable when documented and tested.
- Hardcoded service/stage fallback CTAs. Malformed structured output may use a
  minimal transport-safe response, but ordinary progression and the next CTA
  remain model-owned.
- Prompt/context packets that become scripts or micro-instructions instead of
  factual evidence.
- AWM carrying order-required fields when order intent is not active.
- Background Signals exposing vague fields such as broad order intent when the
  order-readiness state is the better structured surface.
- Brand buckets for brand-specific pricelist requests when the missing field is
  tire size.
- Treating service feasibility as selected-SKU-specific when only broad product
  options are visible and the customer has not selected one.
- Revealing exact installation partner address/name too early, which can
  encourage walk-in drop-off and bypass the reservation flow.
- Model-authored payment account numbers, QR URLs, exact order totals, product
  card bodies, or service slot bodies.
- Silent payment canonicalization when customer terms conflict. Return a
  clarification/conflict result instead of rendering an incorrect summary.
- Treating retrieval keyword overlap as customer intent. FAQ disambiguation is
  allowed at the retrieval boundary, but phrases such as "review order
  summary" must not become product/service feedback FAQ answers.
- Treating Pay Later + COD as a reservation/downpayment method. For delivery,
  COD applies to the remaining balance; reservation fee still needs a separate
  upfront method.
- Letting summary presentation imply payload/submit readiness. The summary can
  help the customer review collected details, but only `build_order_payload`
  should validate API-submit readiness.
- Letting an unvalidated schedule string make an installation order look ready.
  A preferred time can be acknowledged, but slot availability/selection must be
  grounded by `validate_installation_slot` before ready-summary or submit paths.

## Learnings From Review And Testing

- Exact inputs/outputs matter more than code-path summaries. Review recorded
  prompts, context packets, tool schemas, tool calls, tool outputs, composer
  outputs, final rendered bubbles, latency, token use, and state updates.
- Broad live matrices are less useful than focused multi-turn probes with real
  customer cadence and fresh values.
- FAQ tools can dominate a multi-intent turn if the prompt does not prioritize
  actionable product/service discovery alongside read-only policy questions.
- Model-emitted order tool args may use reasonable alternate structured names
  even when schemas prefer canonical names. Normalize those aliases at the tool
  boundary, but do not parse raw customer text there.
- The model can produce good CTAs when it sees compact card headers and the
  missing/next readiness context, but deterministic CTA replacement usually
  makes tone worse.
- Passing full deterministic card bodies to the model bloats context and risks
  rewriting. Passing compact headers plus renderer refs is the better boundary.
- Thought-signature preservation and reasoning-effort changes need A/B testing
  on multi-step tool cases; do not assume reasoning settings improve tool
  correctness without cost/latency comparison.
- ManyChat history loading is expensive and noisy. Cache-first incremental
  hydration is better than loading the full transcript on every turn.
- Loader failures must never break delivery. Proceed from Firestore cache or
  latest message only.
- Local deterministic probes validate structure. Live endpoint probes validate
  integration, model behavior, delivery formatting, and ManyChat state.
- Longer adaptive probes are necessary for order/payment paths. P06, P07, P08,
  P09, and a fresh non-Apollo/non-BPI installation run only reached useful
  conclusions after raising turn caps enough for realistic customer hesitation,
  payment questions, slot selection, and order-detail collection.
- It is better to surface backend amount drift than to mask it. The first P09
  and fresh-install probes exposed a `PHP 120.00` drift that was traced to
  sale-tag checkout math vs product-card display math. V7 now predicts that
  backend sale pricing before submit and still uses backend readback amounts
  when available.

## Prioritized Pending Gaps

### P0 Validation: In-Flight Duplicate And Freshness Control

Gap:

- Locking, CAS save, and pre-delivery freshness suppression are implemented.
  The remaining gap is live validation under overlapping ManyChat triggers and
  human-agent intervention.
- Same-request retry for newer user messages is intentionally not implemented
  yet. With the session lock, the newer user message should normally arrive as
  its own webhook and process after the stale turn is suppressed. Add retry only
  if live evidence shows ManyChat does not reliably send the newer webhook.
- Live Rudy Tumacay evidence on 2026-06-03 showed the edge case that drove the
  current rule: the image turn generated a valid Westlake 185R14C response but
  suppressed delivery because a newer user message was visible; the newer
  request itself was skipped while the lock was busy. This was not a runtime
  crash. After the patch, newer user messages no longer suppress delivery, but
  newer human-agent messages still do.

Why this is P0:

- Resolved message ids and replay help after a turn is persisted, but they do
  not fully prove behavior under real simultaneous Cloud Run requests until
  live-tested.
- Human agents can intervene while the model is still running. If the latest
  message becomes human-agent authored, V7 should not send a competing reply.

Owner components:

- `runtime_v7.api_runtime`
- session gateway / Firestore admission boundary
- `runtime_v7.conversation_hydrator`

Validation needed:

- Concurrent duplicate request test.
- Newer-human-agent abort test.
- Newer-user-message suppression plus queued-webhook follow-up test.

### P0 Validation: Production Observability Storage

Gap:

- Full V7 turn trace persistence is implemented through the analytics gateway
  debug-log path, and compact searchable Cloud Logging lines are emitted.
- Live BigQuery storage was validated on 2026-06-03 in
  `gulong-chatbot-459723.gulong_chatbot_live.debug_log`.
- Remaining gap: decide whether to keep this as a generic debug payload or
  promote selected fields into a dedicated normalized `runtime_turn_trace`
  table.

Why this is P0:

- Live response quality review depends on seeing the actual model inputs,
  tool schemas, tool outputs, composer output, final renderer output, state
  before/after, latency, tokens, and cost.
- The first implementation gives operators trace evidence, but reporting teams
  may later need a flatter query-optimized schema.

Owner components:

- `runtime_v7.turn_trace`
- `runtime_v7.api_runtime`
- analytics/logging gateway

Validation:

- `gulong_chatbot_live.debug_log` contained 131,584 rows through
  `2026-06-03 13:19:53`, with rows for recently explored V7 users including
  `2690947677699495`, `23892826493729485`, `27785526911050339`, and
  `27569528529301592`.
- Still validate which debug-payload fields should be flattened for cost,
  cache, latency, tool, and final-response reporting.

### P0: Order Submit And Payment End-To-End Stress

Gap:

- P06 urgent install, P07 delivery, P08 installment-first, P09 website image,
  and one fresh non-Apollo/non-BPI installation probe all reached payment
  request after iterative fixes. Remaining stress scope is broader live testing
  and payment-proof ingestion/tagging, not the basic summary -> payload ->
  submit -> payment request transition.

Why this is P0:

- The order/payment tools exist, but the highest risk is transition handling:
  selected product carry-forward, payment canonicalization, service schedule
  state, incomplete summary behavior, and confirmation boundaries.

Owner components:

- `runtime_v7.order_state`
- `runtime_v7.order_canonicalization`
- `runtime_v7.checkout_plan`
- `runtime_v7.channel_renderer`
- `runtime_v7.runtime_harness`

Validation needed:

- Additional adaptive customer probes with new products/locations and both
  easy and high-friction customers.
- Payment-proof image ingestion and `Payment Proof Received` tag verification.
- Real `/order` submit only with explicit test customer data.

Recent evidence:

- P06 urgent install reached payment request in 9 turns.
- P07 delivery with privacy/refusal reached payment request in 12 turns.
- P08 installment-first reached payment request in 12 turns.
- P09 website image/promo inquiry reached payment request in 12 turns and
  applied `Website Inquiry`, `Moderate Intent`, `High Intent`, and
  `Order Booked`.
- Fresh non-Apollo/non-BPI installation path reached payment request in 8
  turns with Metrobank installment preserved.
- Focused order FAQ / slot-summary gating regressions passed on 2026-06-03:
  payment FAQs now accept structured fulfillment context, and unvalidated
  install schedules keep summaries incomplete until slot validation grounds
  them.

### P0 Validation: Backend Order Amount Drift

Gap:

- P09 and the fresh non-Apollo/non-BPI installation path showed backend
  readback totals `PHP 120.00` higher than V7's validated payload total.
- Root cause was identified locally: V7 order math reused the product-card
  synthetic `product_discount_after_bundle` quantity total, while the backend
  order endpoint calculates sale-tag carts from submitted `promo`/`srp` fields
  using checkout sale pricing.
- Runtime V7 now uses backend checkout sale pricing for `calculate_order_quote`,
  `build_order_summary`, and `build_order_payload`, and keeps product-card
  quantity totals only as diagnostics when they differ.

Why this is P0:

- Payment request amounts must match the submitted order before the customer is
  asked to pay. The local fix prevents avoidable mismatch notes for sale-tag
  products, but live submit/readback confirmation is still needed after deploy.

Owner components:

- `runtime_v7.order_state`
- order submit/readback API
- product/catalog pricing and fee rules

Validation needed:

- After deploy, submit one fresh sale-tag test order and compare validated
  payload, `/order` response, `/order_details`, and backend admin UI totals.
- Continue surfacing mismatch diagnostics for true backend adjustments unrelated
  to sale-tag pricing.

### P1: Legacy Guard Migration

Gap:

- Continue migrating phrase-based response guards toward prompt/tool-output
  semantics and structured renderer contracts.

Why this is P1:

- These guards can mutate model-owned copy and hide root causes, but some still
  serve as last-mile safety nets while composer/tool semantics are being
  hardened.

Owner components:

- `runtime_v7.runtime_harness`
- `runtime_v7.model_contract`
- `runtime_v7.channel_renderer`
- domain tool outputs

Validation needed:

- Before/after probes for same-day slots, product cards, service wording,
  brand menus, and order/payment summaries.

### P1: Installation Disclosure Happy Path

Gap:

- Validate area-only/slot-first service presentation in live-like customer
  turns and measure whether it reduces partner-address drop-off.

Why this is P1:

- Research showed customers often prefer to walk in when exact partner details
  are revealed early. V7 must support a less leaky path without sounding
  evasive or unhelpful.

Owner components:

- `runtime_v7.service_tools`
- `runtime_v7.installation_partners`
- `runtime_v7.installation_slots`
- `runtime_v7.model_contract`

Validation needed:

- Happy path: area availability -> slot choice -> nearest eligible partner ->
  order summary.
- Forced reveal path with no-walk-in/warehouse/reservation-required policy.
- Explicit walk-in intent path.

### P1: Compatibility Resolver Hardening

Gap:

- Harden product compatibility so shown products, service partners, slots,
  fulfillment path, and payment options are proactively compatible without
  forcing the model into rigid routing.

Why this is P1:

- The central resolver direction is correct, but compatibility hints must not
  become another hidden instruction layer that boxes the model into one CTA.

Owner components:

- `runtime_v7.checkout_plan`
- `runtime_v7.product_search`
- `runtime_v7.service_tools`
- `runtime_v7.order_state`

Validation needed:

- Product filters plus installation threshold.
- Install vs delivery switching.
- Installment compatibility by brand/card/bank/term.
- Quantity/promo conflicts such as 2 pcs vs 3+1.

### P1: Commercial Evidence And Safe Memory Persistence

Gap:

- Extend the current source-backed payment/promo boundary to final composer
  assertion validation and commercial-state persistence. The current patch
  removes the discovered checkout-policy conflict and prevents promo-only
  cards from falling back to non-eligible products, but the broader invariant
  still needs trace-backed composer and memory coverage.

Why this is P1:

- The remaining risk is an otherwise natural model sentence repeating an
  unsupported claim from history after a tool has returned newer evidence.

Owner components:

- runtime_v7.runtime_harness
- runtime_v7.memory
- runtime_v7.state_signal_ledger
- runtime_v7.model_contract

Validation needed:

- Trace-backed regressions for unsupported Home Credit, Toyo Buy 3 Get 1,
  Yokohama BPI 6-month, stale contradictory memory, and valid alternatives.

### P1: Product-First Versus Early Service Disclosure

Gap:

- After the service-grounding patch, the model no longer claims installation
  availability without service tools. However, product-discovery turns that
  include a customer area can still call `find_installation_partners` and show
  area-only partner rows earlier than the customer explicitly asked for
  installation.

Why this is P1:

- The result is grounded, but it may conflict with the anti-dropoff design that
  delays exact installation partner disclosure until product/order progression.
  Area-only cards are safer than names/addresses, but they can still shift the
  conversation away from product selection.

Owner components:

- `runtime_v7.model_contract`
- `runtime_v7.runtime_harness` final composer context
- `runtime_v7.service_tools`

Validation needed:

- Product inquiry plus location only should decide whether to preserve location
  for later or proactively check area-only installation partners.
- Product inquiry plus explicit install/nearby/schedule wording should call
  the service tools and keep partner disclosure staged.
- Delivery-intent turns should not render installation partner cards unless the
  customer asks or shows interest in switching.

Recent evidence:

- `tmp/runtime_v7_persona_research/targeted_p08_service_grounding_probe.json`
  grounded the service statement by calling `find_installation_partners`, but
  still showed area-only partner options in a product+location turn.

### P1: Runtime V7 Cost/Call Count On Long Persona Runs

Gap:

- Long order/payment conversations still accumulate many model calls and large
  context packets. The targeted 8-turn P08 payment run reached payment request
  but used 26 model calls and about `$0.0748`. The 2026-08-03 containment work
  removed unrelated payment-decision calls; the composition simplification
  then removed stale context from answer-only packets and one duplicate broad
  repair from semantic-failure turns. Exact deployed before/after call and cost
  evidence is still required before closing this gap.

Why this is P1:

- Higher max-turn caps are useful for realistic testing, but they make
  redundant tool-loop/composer calls and repeated context payloads much more
  visible. This needs a separate optimization pass after behavior is stable.

Owner components:

- `runtime_v7.runtime_harness`
- `runtime_v7.llm_gateway`
- final-composer packet construction
- tool-result compaction/reuse

Validation needed:

- Compare matched deployed cohorts and a bounded adaptive persona sample before
  and after the two containment changes.
- Track duplicate same-turn tool calls, composer prompt size, and cache misses.
- Confirm ordinary payment FAQ turns do not acquire unrelated location/product
  CTAs and that semantic failures show at most one evidence-only recomposition.

### P2: Product Visibility Source

Gap:

- Replace `product_visibility_denylist.json` with trusted customer-catalog
  visibility metadata or API response when available.

Why this is P2:

- The denylist is fast and low latency, but it is a workaround. A trusted
  visibility field/API would be more accurate and easier to maintain.

Owner components:

- `runtime_v7.product_search`
- upstream product/catalog APIs

Validation needed:

- Product card URLs and website-visible catalog checks for active SKUs.

### P2: Order Status Follow-Up

Gap:

- Build customer-facing order status follow-up behavior around
  `get_order_details` once readback examples are validated.

Why this is P2:

- The read-only tool exists. The next risk is natural follow-up wording and
  ensuring the model does not imply it can mutate schedule/payment/status.

Owner components:

- `runtime_v7.order_state`
- `runtime_v7.model_contract`
- `runtime_v7.channel_renderer`

Validation needed:

- "status ng order", "paid na ba", "ano appointment date", and unsupported
  "change schedule/payment" turns.

### P2: FAQ Data And Retrieval Strategy

Gap:

- Keep FAQ data static for now, but revisit RAG/embedding strategy only if FAQ
  coverage or maintenance becomes a blocker.

Why this is P2:

- Current issues have mostly been routing/context/semantics problems, not a
  lack of FAQ retrieval infrastructure.

Owner components:

- `runtime_v7.faq_tools`
- future RAG/index pipeline if needed

Validation needed:

- FAQ coverage audit against gulong.ph FAQ and common ManyChat questions.

## Deferred Until After Promo And Brand Lead Deployment

The following issues are intentionally excluded from the promo/brand lead
milestone in `RUNTIME_V7_PROMO_BRAND_LEAD_MILESTONE.md`. Start them only after
that feature is deployed and its gallery/category click path is verified.

### P1 Deferred: Commercial Policy Truth And Claim Grounding

Observed failures:

- The assistant confirmed Home Credit even though it is not a supported payment
  option.
- A response discussed six-month installment in a way that implied Yokohama
  products could use it, despite product/brand restrictions.
- Static FAQ/RAG snapshots and runtime payment policy can contain overlapping
  or different installment wording.

Required follow-on outcome:

- Establish one versioned authoritative payment/installment policy source.
- Separate general payment-method support from product-specific installment
  eligibility.
- Require trusted policy or product evidence before confirming payment methods,
  banks, terms, brand eligibility, fees, stock, or availability.
- Add negative and scope-sensitive regressions for Home Credit, Yokohama,
  Apollo, BPI terms, and unknown payment methods.

Owner components:

- `runtime_v7.delivery_payment_policy`
- `runtime_v7.faq_tools`
- `runtime_v7.product_search`
- `runtime_v7.model_contract`
- final composer and renderer contracts

### Partially Implemented: Evidence-Safe Conversation Memory

Implemented boundary:

- Runtime assistant turns and raw assistant response prose are excluded from
  Active Working Memory fact evidence.
- Tool-backed turns use deterministic evidence-only compaction, retaining
  normalized customer/human-agent context and stable tool/state refs rather
  than exact prices, promos, stock, installment, payment, partner, or order
  claims.
- This makes the next tool-backed turn clean stale assistant assertions out of
  AWM and removes a memory-model call from the main commercial path.

Residual follow-on:

- Support correction/supersession when a later trusted source contradicts an
  older structured commercial claim outside AWM.
- Old assistant messages remain in transcript history for conversational
  continuity, so all future commercial composition must continue to prefer
  current tool/state evidence.

Owner components:

- `runtime_v7.memory`
- `runtime_v7.runtime_harness`
- session export/import and conversation hydration
- Background Signal and fact provenance contracts

### P1 Deferred: Objective-Based Skills And Capability Exposure

Gap:

- Current broad capability domains can expose overlapping tools and prompt
  guidance. Raw-message keyword routing is not an acceptable replacement, while
  vector retrieval alone is too unreliable for mandatory operating rules.

Required follow-on outcome:

- Extend model-led turn understanding with typed objectives.
- Load versioned prompt/instruction skills from those objectives without adding
  a second planner agent when the existing extraction pass can carry them.
- Keep a small static invariant prompt and retain `request_capability` recovery.
- Use semantic/vector retrieval for evidence and long-form knowledge, not as the
  sole selector for safety-critical instructions.
- Evaluate missed, conflicting, and unnecessary capability exposure plus token
  and latency impact.

Owner components:

- `runtime_v7.state_signal_model`
- `runtime_v7.capability_profile`
- `runtime_v7.tool_capabilities`
- `runtime_v7.model_contract`
- context compiler and LLM gateway metrics

### P1 Deferred: Product Query Planning And Verified Availability

Observed failure:

- Incorrect hard filters can remove an existing size/brand product and lead the
  assistant to state that it is unavailable.

Required follow-on outcome:

- Track filter provenance from latest customer statements, button choices,
  persisted preferences, tool context, and defaults.
- Keep explicit requirements separate from soft preferences.
- Treat model tool arguments as a proposed query plan that is validated against
  current structured state.
- Diagnose empty results by relaxing optional filters and distinguish verified
  unavailability from a constraint conflict or unknown result.
- Permit a customer-facing unavailable claim only after an exact base query
  verifies the miss.

Owner components:

- `runtime_v7.product_search`
- `runtime_v7.product_observations`
- `runtime_v7.model_contract`
- Background Signal provenance and product-search evaluation packs

### Implemented: Qualification Choice Priority And Checkout Accelerators

Decision:

- Apply one-primary-decision behavior only from product qualification through
  schedule selection. When multiple product cards and schedules coexist,
  product selection owns the turn. A single card is unambiguous.
- After schedule selection, allow the remaining order-form fields to be
  requested together. Payment buttons are optional accelerators and do not
  prevent a customer from typing Pay Now/Pay Later with contact details.
- Always include an afternoon option for every displayed schedule day. Resolve
  it to the earliest actual delivered afternoon slot when available; otherwise
  store `12:00 PM` only as an unvalidated preference.
- Source Pay Now/Pay Later amounts from quote math and payment methods from
  active checkout metadata. Never encode brand-specific rules in the buttons.
- Treat interactive clicks as session-authoritative events rather than visible
  transcript messages. Do not refresh or replace them from ManyChat history,
  and do not attach checkout controls to a product/location click from stale
  readiness fields.

Residual gap:

- A noon fallback is not an availability claim and cannot make an order
  submit-ready. It may make the read-only summary reviewable, but a later exact
  allocation or team-confirmed scheduling step is still required.
- Customer-facing trial validation must confirm that ManyChat renders and routes
  the new controls without operator-interface duplication.
- Stateful return-only probes must use the normal chat store plus the generic
  choice-action route. The tester endpoint intentionally uses an isolated
  session store, so mixing tester chat with normal clicks produces a false
  stale-control result.
- ManyChat can still invoke the runtime twice when separate automations use
  different event IDs. Runtime replay protects the same event; one invocation
  path or a shared upstream event ID remains an integration requirement.
- Product-search now prefers the structured `/shop` `product_promo` contract
  for any brand and carries its promo ID into normalized pricing evidence.
  Legacy SKU-specific Yokohama set-pricing tables are consulted only when that
  structured row is absent. They are not payment/installment authority and
  remain commercial-maintenance debt to migrate into the product or reviewed
  promo source.
- Named payment-method inquiries do not depend on semantic FAQ similarity or
  a model-selected FAQ id. The model proposes the method and optional brand;
  Runtime selects the payment-policy resolver and validates against active
  checkout metadata. This is a generic authority boundary, not a Home Credit
  or Yokohama exception.
- Merely exposing a commercial tool was insufficient in live model acceptance:
  the model could answer or defer without calling it. The selected boundary is
  one source-backed retry driven by current typed objectives. It is narrower
  than forcing every payment- or promo-related turn: persisted promo context
  cannot interrupt a later delivery step, and a customer selecting COD, Pay
  Now, or Pay Later does not trigger an extra policy lookup.
- FAQ keyword/vector retrieval remains only a routing hint and cannot authorize
  a payment claim. The checkout resolver result is authoritative, so a provider
  added to the API needs no runtime provider dictionary or embedding refresh.
  Reviewed promo records provide the equivalent promo authority.

## Current Validation Bar

- Code-level Runtime V7 changes should pass:
  `pytest $(rg --files test | rg "test_runtime_v7") -q`
- API ingress/history/idempotency changes should pass:
  `pytest test/test_runtime_v7_ingress_trace.py -q`
- Live model probes should be focused, artifact-backed, and tied to the change.

### Decision: operating identity is reusable context, not a location script

- Maintain one reviewed, cacheable operating-identity packet for stable brand
  facts used across general location, physical-shop, walk-in, installation, and
  trust questions.
- Use `over 100 trusted installation partners` or `mahigit 100 trusted
  installation partners` as the approved conservative brand claim. Do not turn
  it into an exact count or a coverage/availability claim.
- Let the model decide whether and how to use those facts in the current turn;
  do not inject a fixed location spiel or repeat the identity after the opening
  unless the customer asks.
- Treat partner-network scale as optional supporting context. If used, connect
  it to the operating explanation, customer benefit, or useful location step;
  do not append it as a standalone credential.
- Treat the head-office installation capability the same way: it corrects the
  authority base and prevents false denials, but it is not required or
  promotional customer copy.
- Exact partner identities, supported areas, availability, stock, schedules,
  prices, promos, payment, and order state remain provider/tool-owned.

### Decision: valid model composition owns transitions and CTA

- A valid structured final-composer turn owns all low-risk customer prose:
  greeting or acknowledgement, direct answer, connective text around surfaces,
  and the one useful next step.
- Deterministic rendering remains mandatory for guided choices and exact or
  high-risk commercial/service/order facts.
- Deterministic CTA insertion/replacement is a legacy/failure fallback, not the
  normal composed path. Safety guards may still remove unsupported claims or
  contradictory questions without supplying creative customer copy.
- Evaluation must vary intent, completeness, product and location values,
  surfaces, and single-/multi-turn transitions; a green reproduction of one
  example is not sufficient evidence of general response quality.
- Use one shared complete-turn composition contract for both the main model and
  final composer so acknowledgements, surface transitions, and CTAs follow the
  same conversational and sales-stage rules.
- Preserve prior trusted product refs in the turn plan when a selected product
  transitions into service, schedule, payment, or order composition.
- Do not let transient signal relations satisfy lead or order fields. Their text
  may describe the subject of a question rather than a customer-owned value.

### Planned boundary: consolidate state before adding external memory

- Keep hydrated recent turns, durable typed signals, authoritative observation
  refs, and full `OrderReadiness`; they have distinct continuity or action-safety
  roles.
- Treat legacy `memory_note`, model AWM on no-tool/no-durable-signal turns, and
  the lightweight missing-info readiness projection as ablation candidates.
  Measure next-turn recovery, tool selection, rendered quality, latency, and
  cost before removing them.
- Record whether extracted signals became durable, affected routing/readiness,
  or changed the final response. Also record AWM latency and conflicts where a
  latest customer correction disagrees with narrative memory.
- Use one reconciliation priority for conversational context: latest customer
  correction, then validated tool/state evidence, then durable signal ledger,
  then narrative memory/recent history. This priority cannot create action
  authority.
- Do not add Mem0, semantic memory search, or graph persistence merely to
  replace local storage. Shadow-test them only if the lean baseline shows a
  real cross-thread retrieval need or if explicit workflow checkpointing is the
  measured problem.

### Planned boundary: reduce deterministic guards to authority and mechanics

- Preserve schema repair, exact product/payment/order/service authority,
  trusted-image validation, guided-surface refs, dedupe, tracked actions, and
  submit authorization.
- Instrument every post-model mutation with before/after units and a typed
  reason. Establish a no-mutation rate and review a varied diff sample before
  changing behavior.
- For schema-valid final-composer turns, shadow-bypass lead-focus rewrites,
  qualification/product progression rewrites, generic clarification deletion,
  sentence-level deletion, and renderer CTA injection.
- Replace whole-response API truth rewrites with structured authority facts
  made available to one evidence-aware composer repair. Deterministic full-copy
  fallback remains only for failed/invalid composition.
- Negative controls must retain unsupported-payment rejection, brand
  eligibility, exact price/promo/order totals, no false booking, one active
  guided-choice layer, and change-of-mind handling.

### Decision: visible controls own the primary CTA layer

- When multiple exact product controls are delivered, asking for location in
  the same response is a contract conflict even if location is the next missing
  qualification field.
- Resolve the conflict through the existing shared primary-decision structure,
  not through brand/SKU rules or customer-text keywords.
- Align the model-facing lead focus first, then retain a renderer-level safety
  invariant because the channel renderer—not raw model prose—is the customer
  delivery boundary.
- Keep typed answers supported. The invariant defines which decision is primary;
  it does not force button use.

### Decision: embeddings retrieve brand narrative, structured fields authorize warranty

- The Gulong.ph website is the source for brand background and brand-specific
  warranty policy. Promo catalog offer summaries are not a substitute.
- Vector retrieval is appropriate for open-ended background and comparisons,
  but similarity does not authorize exact duration, coverage, exclusion, or
  claim-process statements.
- Store those exact facts as versioned structured profile fields with source
  URLs and hashes. The model may explain them naturally; Runtime validates
  evidence refs and keeps product-level warranty evidence more specific.
- Automatic publication is allowed only after the complete source build,
  schema checks, and embeddings succeed. Partial or failed syncs retain the
  previous active version.
- A daily Cloud Run Job and scheduler still need infrastructure activation
  before this becomes a self-refreshing production source.

## Learning candidate: Derive promo retrieval gates from the pending catalog

- Captured: 2026-08-01
- Promotion status: candidate
- Symptom: The August review workbook failed mandatory Michelin Japan and
  Yokohama 6000 checks even though neither campaign belonged to the August
  catalog.
- Root cause: The publication gate stored July campaign identities in a global
  constant instead of deriving positive cases from the immutable pending
  version.
- Proposed practice: Create one exact retrieval case per enabled promo, add
  brand-scope cases only when a brand has multiple offers, add promo-type
  alternatives when present, and retain stable expired and unrelated negative
  controls.
- Scope/owner: Promo catalog build, review workbook, and publication
  validation.
- Positive scenario: An August catalog with BFGoodrich discount, Michelin
  cashback, Michelin and Apollo 3+1, and a still-current Michelin event
  generates exact cases for every record and all must pass review.
- Negative control: An expired or deliberately omitted prior campaign does not
  create or waive a current commercial claim; it is absent from the positive
  matrix while expired and unrelated controls still run. A prior campaign
  whose reviewed end date remains current must be included when Marketing
  confirms the carry-over scope.
- Explicit-offer control: Draft evaluation applies the same deterministic
  amount and 3+1 constraint boundary as Runtime before grading rank order.
  Semantically related offers cannot occupy the required leading slots for a
  mechanic they do not satisfy.
- Expected benefit: Prevents stale campaigns from blocking monthly publication
  while preserving deterministic fail-closed review coverage and reducing
  manual workbook exceptions.

## Decision: Observation is not customer-visible presentation

- A successful product search creates trusted candidate facts, but those facts
  are not a customer choice surface until their text/cards or tracked controls
  are present in the delivered channel payload.
- Capability context therefore keeps `product_observation` separate from
  `product_presentation`; response planning must not call internal candidates
  "shown earlier" or accept relative choices against them.
- Guided clicks deterministically settle only their own typed field. The model
  receives that fact and reasons about the next sales step. Deterministic output
  replacement remains reserved for commercial authority and hard safety, not
  ordinary location-to-product-to-schedule progression.
- Remaining gap: run one final adaptive confirmation of hidden-product recovery,
  a real price-category click path, controlled endpoint delivery, and the full
  Runtime V7 suite immediately before merge.

## Decision: One model-led serving authority, narrow deterministic boundaries

- The main model owns interpretation and ordinary read-only tool selection. The
  structured final composer owns all low-risk visible prose, ordered transitions,
  and the one useful next CTA, including text around product, promo, location,
  schedule, payment, and order surfaces.
- Do not insert separate product, location, payment, comparison, or lead-stage
  semantic classifiers after the main model. They duplicate cost and create a
  competing state authority. Phrase matching remains valid only for exact
  structured guided-action tokens or narrow mechanical formatting, never for
  free-text intent or sales progression.
- Deterministic runtime ownership remains mandatory for exact commercial and
  service facts, provider refs, guided control allowlists, idempotent actions,
  delivery mechanics, side effects, and hard order/submission safety.
- Capability hints may expose safe read tools, but cannot choose the response,
  authorize a fact, expose a mutation, or require a CTA.
- Serving capability selection does not consume phrase-ranked FAQ hints. The
  three domain-specific FAQ readers are consistently available as safe read
  tools; lexical/vector matching may rank authored records only after the main
  model has selected the relevant reader.
- Free explanation text such as signal evidence and `status_hint` is never a
  typed state transition. Relation and confirmation are closed schema fields;
  wording cannot change recency, merge behavior, persistence, or action safety.
- A structural or grounding failure may trigger one bounded composer repair.
  Valid composed prose must not pass through sentence deletion, whole-response
  replacement, or CTA rewriting merely because a legacy readiness projection
  disagrees.
- Positive case: a mixed product, promo, installment, and location conversation
  retains all typed customer choices and progresses naturally using grounded
  providers.
- Negative control: a guided token outside the delivered allowlist, an
  unsupported payment assertion, or an incomplete submission remains rejected
  deterministically even if the model proposes it.
- Remaining gap: complete the controlled channel-delivery check and the one
  repository-wide suite immediately before merge. Do not infer external
  ManyChat delivery from return-only evaluator evidence.

### Decision: known context is not action authority

- Keep recognized customer context available to the model even when a provider
  must still validate it. Do not force the customer to repeat a location, size,
  product, or fulfillment preference merely because it is not yet safe for a
  guarded action.
- Keep `known_customer_context`, satisfied order fields, factual claim
  authorization, and side-effect authorization as separate concepts.
- A coverage-only service result may answer the customer's area question but
  must not imply slot availability. If no product is selected, continue through
  product choice while retaining the area; if a product is selected, schedule
  lookup may resume for that area.
- A tool call does not settle or replace the customer's conversational goal.
  The model-led memory compactor decides whether that goal remains, is
  satisfied, is deferred, or is replaced, using typed state and exact refs.
- Synthetic guided-click prose carries the chosen identity only. Prices,
  totals, promo mechanics, and displayed quantities remain in deterministic
  observations/presentations and cannot become customer-authored signals merely
  because the customer clicked the card.
- Remaining release gates are the repository-wide suite and controlled channel
  delivery check against the final merge candidate. The 2026-08-10 adaptive
  evidence was local `return_only` only.

## Learning candidate: Renderer context and active choice are one interaction

- Captured: 2026-08-10
- Promotion status: candidate
- Symptom: An incomplete order summary plus Pay Now or Pay Later controls was
  rejected as two customer decision layers, hiding the controls and forcing a
  formal-English fallback.
- Root cause: The turn-surface schema dropped `supporting_context` and
  `missing_fields` metadata, so the validator treated a read-only summary and
  its immediate checkout input as competing authoritative layers.
- Proposed practice: Preserve typed surface relationships through the
  authorization schema. Mark deterministic summaries as supporting context
  when their immediate guided choice owns the input, while keeping facts,
  buttons, and side effects renderer-controlled.
- Scope/owner: Runtime V7 customer turn plan, final composer contract, and
  renderer validation.
- Positive scenario: A selected installation slot renders one grounded
  order-details block, then model-owned Taglish context and visible Pay Now or
  Pay Later choices in the same turn.
- Negative control: Independent product and city choice surfaces remain
  separate decision layers; the composer must present only one and defer the
  other.
- Expected benefit: Avoids false repair fallbacks and language regressions
  without weakening commercial grounding or submission safety.

## Learning candidate: Normalize deterministic catalog units before card rendering

- Captured: 2026-09-02
- Promotion status: candidate
- Symptom: A product card displayed `Warranty: 5` because a bare numeric
  catalog value was rendered as customer-visible text.
- Root cause: The explicit warranty field was treated as authored prose and
  passed through unchanged; the renderer correctly used that normalized field,
  so model prompting could not reliably repair it.
- Proposed practice: At the catalog normalization boundary, add units only
  when the entire trusted field is numeric; preserve authored strings and test
  singular, plural, and already-unitized controls.
- Scope/owner: Runtime V7 product normalization and deterministic
  customer-visible card rendering.
- Positive scenario: Catalog warranty values `1` and `5` render as `1 year` and
  `5 years` for any product.
- Negative control: An authored term such as `5 years from purchase date`
  remains unchanged, and no coverage meaning is inferred from duration.
- Expected benefit: Prevents malformed commercial presentation generically
  without model calls, brand exceptions, or loss of authored terms.

## Learning candidate: Authority-shaped deployed evaluation contracts

- Captured: 2026-09-10
- Promotion status: candidate
- Symptom: Release probes used fixed commercial answer text or narrow phrase expectations and could pass structure while missing current provider truth, or fail harmless wording variation.
- Root cause: The evaluator mixed mutable business outcomes, response phrasing, mechanical contracts, and human CS judgment in one case definition.
- Proposed practice: Use tester-only serving-path evidence; validate canonical tool arguments and provider-owned scope/refs mechanically; treat policy wording as concept alternatives; keep structural CS proxies separate from a complete human rubric. Declare each optional or configurable rendered surface as required when enabled, N/A only with authoritative unavailability evidence, or forbidden when disabled; include that declaration in baseline compatibility.
- Scope/owner: Runtime V7 deployed release-candidate evaluation and promotion gates.
- Positive scenario: Two differently phrased compound payment cases preserve each method, brand, option, and term from the model call through provider execution, then check every structured claim against checkout-backed tool scope while a reviewer scores the complete rendered turn. A separate tracked journey validates product, location, schedule, payment-option, and payment-method controls end to end.
- Negative control: Equivalent duplicate tool calls may reuse one provider result, and a greeting, punctuation choice, harmless Taglish paraphrase, or provider no_match result must not fail merely because it differs from one reference sentence.
- Expected benefit: Reduces stale commercial expectations, false failures from model variation, unsafe side effects during probes, and duplicate live-model cost.

## Learning candidate: Cost class and side-effect class are independent evaluation dimensions

- Captured: 2026-09-10
- Promotion status: candidate
- Symptom: A single health command could either overstate a local test as
  guaranteed zero-cost or hide real external API usage behind a generic
  "no-LLM" label; a nominally read-only POST flag also did not prove the target
  endpoint was non-mutating.
- Root cause: Evaluation depth, model metering, external network use, and
  side-effect authority were treated as one tier instead of separate contracts.
- Proposed practice: Make layers independently selectable and declare their
  execution/cost class. Require explicit opt-in for metered models; restrict
  API probes to resolved component-specific method/path allowlists, mandatory
  response contracts, latency ceilings, and no redirects. Keep mutation
  canaries in a separately authorized staging-only layer.
- Scope/owner: Runtime V7 health orchestration, API dependency checks, and
  release scheduling.
- Positive scenario: A pull request runs only local deterministic contracts; a
  daily operator can independently select commerce or channel reads; a
  pre-live run explicitly enables the metered matrix and records all selected
  layers in its artifact.
- Negative control: A profile-labelled product probe aimed at `/health`, an
  environment-resolved tag-write URL, a redirect, or a model tier without
  metered opt-in fails before an unsafe or misleading green result.
- Expected benefit: Reduces accidental spend and side effects while preserving
  cheap frequent coverage and honest interpretation of each green layer.
