# Runtime V7 Agentic Customer Service Implementation Plan

## Summary

Build Runtime V7 as a new customer-service runtime lane beside Runtime V6 in
`gulong-chat-platform`. Runtime V7 should reuse V6's proven assets and failure
cases, but rebuild the control loop around first-class evidence, entity
resolution, bounded product search, compact context, and guarded response
generation.

Slots and sales stages are derived background views, not the conversation
controller. The agent should converse from the latest message, memory, active
references, trusted observations, and tools. Slot/state/readiness layers exist
to validate consistency and block unsafe commitments, not to block exploratory
search, service lookup, clarification, or normal conversation.

The target runtime flow is:

```text
HTTP/chat request
 -> session load
 -> turn/evidence extraction
 -> entity/reference resolution
 -> domain state reduction
 -> context + strategy compilation
 -> single orchestrator tool loop
 -> bounded tool execution
 -> observation + recovery
 -> guarded response rendering
 -> state/log persistence
```

Default implementation choice:

- Use existing `LLMGateway`, Firestore/session patterns, and tool/logging
  conventions.
- Do not adopt LangGraph or OpenAI Agents SDK in the first production slice.
- Keep the core framework-neutral so a framework wrapper can be added later if
  it proves useful.

## Key Decisions

### Build beside V6

Create a new runtime lane instead of patching V6 directly.

Use V6 as source material for:

- API clients and tool gateways
- product lookup/fetch logic
- Firestore/session patterns
- logging and trace conventions
- product presentation renderer ideas
- golden tests and failure cases
- Cloud Run deployment/smoke patterns

Rebuild clean:

- turn/evidence ledger
- entity registry
- state reducers
- context compiler
- `ProductSearchIntent` and query runner
- strategy compiler
- orchestrator/tool loop
- recovery and validation loop

### Model/runtime responsibility split

The model owns:

- semantic interpretation
- customer intent detection
- task selection
- conversational strategy
- final phrasing
- use of latest conversation, memory, references, and trusted observations to
  choose safe exploratory next steps

The runtime owns:

- durable state
- entity/reference resolution
- tool execution
- business-rule validation
- side-effect gates
- trusted-source and TTL checks
- response validation
- logging and replay
- readiness validation for risky commitments and side effects

The runtime should not use derived slots, stage labels, or confidence scores as
hard gates for read-only exploration. It should gate final price claims,
discount promises, payment instructions, order review, order submission, and
schedule commitments.

### Memory architecture

Use custom business memory first.

Firestore working memory:

- active session
- lead state
- turn ledger
- evidence ledger
- entity registry
- product/service/order state
- trusted tool observations
- last presentations
- unresolved references

BigQuery:

- immutable logs
- audit/history
- analytics
- historical conversation lookup

Vector/semantic memory:

- optional auxiliary layer only
- useful for prior preferences, objections, unresolved issues, and similar
  cases
- not allowed for current price, stock, installation slots, payment
  instructions, or order status

## Implementation Changes

### 1. Runtime V7 package structure

In the clean runtime repository, deployable Runtime V7 code lives under:

```text
runtime_v7/
```

Related documentation lives under:

```text
docs/
```

or rename this folder to `runtime_v7` after approval. Python modules should not
use a hyphenated import path.

Recommended implementation package:

```text
runtime_v7/
  api_runtime.py
  orchestrator.py
  models.py
  prompts/
  shared/
  product/
  service/
  orders/
  memory/
  evaluation/
```

Core contracts:

- `RuntimeV7SessionState`
- `TurnLedger`
- `EvidenceLedger`
- `EntityRegistry`
- `PromptContextPacket`
- `StrategyPacket`
- `ToolObservation`
- `RuntimeV7TurnResult`

### 2. Turn ledger and evidence ledger

Implement a first-class evidence flow:

```text
raw customer turn
 -> TurnRecord
 -> EvidenceCandidate records
 -> validated EvidenceRecord records
 -> domain reducers
```

Evidence records should preserve:

- raw text
- normalized value
- kind/field
- source
- confidence
- status
- turn id
- timestamp
- validation status
- canonical match status
- conflicts
- confirmation requirement

Do not model evidence actionability as a routing authority. Evidence and slots
can be incomplete while still being useful for product search, service lookup,
or clarification. Readiness validators decide only whether a risky business
commitment is allowed.

Required evidence fields:

- tire size
- rim size
- brand
- model/pattern
- vehicle make/model/year
- quantity
- budget
- discount/haggling
- price category
- location/address
- contact number
- installation intent
- delivery intent
- order intent
- payment intent
- product selection/reference
- complaint/support intent
- customer image/product screenshot clues

### 3. LLM evidence extractor

Implement an LLM-backed evidence extractor through the existing `LLMGateway`.

Input:

```json
{
  "latest_user_message": "...",
  "recent_turns": [],
  "last_assistant_question": "...",
  "active_focus": "...",
  "last_presentations": {},
  "known_entities": {}
}
```

Output:

```json
{
  "observations": [],
  "references": [],
  "intent_flags": [],
  "ambiguities": [],
  "suggested_state_patch_candidates": []
}
```

The extractor proposes evidence only. It must not directly mutate Firestore or
domain state.

It must identify reference phrases such as:

- `yun una`
- `yan`
- `same`
- `yung mura`
- `yung premium`
- `yung BFGoodrich`
- `yung nasa taas`

### 4. Entity registry and reference resolution

Implement a registry for active customer-facing entities:

- product offers
- product presentations
- brand bucket presentations
- installation partners
- schedule options
- order drafts
- payment options
- unresolved references

When presenting products, store stable refs:

```json
{
  "presentation_ref": "pres_...",
  "domain": "product",
  "items": [
    {
      "display_index": 1,
      "item_ref": "offer_1",
      "product_id": "...",
      "title": "...",
      "price": 3200,
      "source": "product_api",
      "ttl_seconds": 900
    }
  ]
}
```

Reference rules:

- `yun una` resolves to `display_index=1` in the latest active product
  presentation.
- `yan` resolves only if there is one strong active focus.
- copied brand-bucket text does not become explicit brand selection unless the
  customer clearly selected one brand.
- multiple plausible references require a clarification question.
- resolved references become evidence with `source=presentation_selection`.

### 5. Domain reducers

Implement reducers for product, service, orders, and lead state.

Reducers produce background state, slot projections, readiness summaries, and
audit records. They do not decide whether the agent may converse or run safe
read-only tools. The orchestrator may use raw conversation, memory, refs, and
trusted observations directly when choosing exploratory actions.

Reducer rules:

- latest explicit correction wins
- weak inference cannot overwrite confirmed values
- null extraction cannot clear existing state
- contradictions mark previous evidence as stale or contradicted
- multiple valid tire sizes are allowed
- provenance is preserved for every durable field
- acknowledgements like `sige`, `ok`, or `go` are not accepted as
  location/contact/address

Product state should include:

- tire size candidates
- selected or likely tire size values
- vehicle candidates
- brand/model/budget preferences
- selected product ref
- last search intent
- last search outcome
- trusted price facts
- quote candidates
- presentation refs

Service state should include:

- location candidates
- selected service area
- installation/delivery intent
- partner candidates
- selected partner
- schedule candidates
- selected schedule
- serviceability/tool outcome

Order state should include:

- customer name
- contact number
- order draft
- selected product
- fulfillment
- payment option
- confirmation status
- submitted order reference

Order state should not imply submit readiness by itself. Submission readiness is
the output of a separate validator that checks canonical product, fulfillment,
contact, price/payment truth, and explicit customer confirmation.

### 6. Context compiler

Compile context instead of dumping memory into the prompt.

Extraction context:

```json
{
  "latest_user_message": "...",
  "last_assistant_question": "...",
  "recent_turns": [],
  "active_focus": "...",
  "last_presentations": [],
  "known_entities": {}
}
```

Orchestrator decision context:

```json
{
  "current_situation": {},
  "known_facts": {},
  "active_candidates": {},
  "resolved_references": {},
  "open_questions": [],
  "available_capabilities": [],
  "hard_constraints": [],
  "recent_observations": [],
  "last_tool_observations": []
}
```

Context rules:

- no full Firestore state
- no full transcript unless explicitly needed
- no raw full product catalog
- use refs, summaries, top candidates, and observations
- keep provenance compact but visible when it affects a decision
- explain that slots, stages, and readiness are background signals, while
  conversation, memory, refs, and trusted observations are the operating context
- do not present missing or unverified slots as blockers unless the current
  action is a commitment or side effect

### 7. Strategy compiler

Implement `StrategyPacket` generation.

The packet should include:

- business goal
- detected scenario
- suggested actions
- available tool capabilities
- readiness hints
- hard constraints
- recovery options

Supported V1 scenarios:

- tire size price inquiry
- vehicle-only inquiry
- product search refinement
- product selection
- discount/haggling
- location/serviceability question
- installation schedule question
- ready-to-book
- booking confirmation
- payment question
- order status/support
- no-match product recovery
- mixed product + service turn

Suggested action shape:

```json
{
  "skill": "product_search",
  "why": "Customer asked for price for a known tire size.",
  "helpful_inputs": ["tire_size"],
  "commitment_blockers": [],
  "safe_for_exploration": true
}
```

The strategy compiler suggests options. It should not over-script the
customer-facing reply unless safety requires deterministic fallback.

It must not turn missing slots into hard blockers for safe exploration. Missing
or candidate fields become blockers only for commitment actions such as final
order review, order submission, payment instructions, and grounded schedule
commitments.

### 8. Product search request and query runner

Implement a small model-facing `ProductSearchRequest` plus a richer internal
bounded `ProductSearchRunner`.

Implementation status as of 2026-05-18:

- runner: `runtime_v7/product_search.py`
- live/API probe: `scripts/runtime_v7_product_search_probe.py`
- focused tests: `test/test_runtime_v7_product_search_runner.py`
- implementation note and latest live results:
  `docs/PRODUCT_SEARCH_RUNNER_IMPLEMENTATION_2026-05-18.md`

The model-facing tool call should mirror the `/search` or `/shop` endpoint
filters. The model outputs only the endpoint-shaped values it can extract from
the latest customer message, recent turns, memory, and active references.

Model-facing request example:

```json
{
  "section_width": null,
  "aspect_ratio": null,
  "rim_size": null,
  "brands": null,
  "model_or_pattern": null,
  "budget_max": null,
  "budget_scope": "per_tire",
  "promo_only": null,
  "promo_types": [],
  "ev_compatible": null,
  "gulong_guarantee_only": null,
  "gulong_guarantee_tiers": [],
  "origins": [],
  "warranty_years": [],
  "tire_categories": [],
  "terrain_types": [],
  "availability": "any",
  "installment_only": null,
  "installment_banks": [],
  "installment_months": [],
  "installment_max_interest": null,
  "quantity": 4,
  "sort": "best_value",
  "top_k": 6,
  "semantic_query": "budget daily use durable"
}
```

Required model-facing search fields:

- none

Endpoint-shaped filters:

- `rim_size`
- `section_width`
- `aspect_ratio`
- `brands`
- `model_or_pattern`
- `budget_max`
- `budget_scope`
- `promo_only`
- `promo_types`
- `ev_compatible`
- `gulong_guarantee_only`
- `gulong_guarantee_tiers`
- `origins`
- `warranty_years`
- `tire_categories`
- `terrain_types`
- `availability`
- `installment_only`
- `installment_banks`
- `installment_months`
- `installment_max_interest`
- `quantity`
- `sort`
- `top_k`

All endpoint-shaped filters are optional. The endpoint may be called with no
filters, one filter, or any combination of filters. The runner must not require
`section_width + aspect_ratio + rim_size` before searching.

Endpoint adapter notes:

- Use `POST /shop`, not GET, even when filters are represented as URL query
  params.
- Map size filters directly to `section_width`, `aspect_ratio`, and `rim_size`.
- Map brand filters to the website `b` parameter, for example
  `b=MICHELIN--YOKOHAMA`.
- Expose only `brands: string[]` in the model-facing tool contract, including
  single-brand searches such as `["YOKOHAMA"]`. Do not expose both `brand` and
  `brands`; dual fields create avoidable conflict and downstream normalization
  paths.
- Normalize all model-facing brand values into canonical uppercase brand names.
  The model should pass the likely brand text it interpreted from the message;
  the runtime normalizer then maps it to canonical catalog/API values. This
  prevents typo inputs such as `micheline`, `yokohana`, `bfgudruch`, `arrivo`,
  `weslake`, and `bridgeston` from becoming zero-result `/shop` calls. Keep the
  correction deterministic with aliases plus bounded fuzzy matching, and return
  compact `brand_corrections` metadata so the response layer knows a correction
  happened.
- For multiple requested brands, support both a combined `b=BRAND1--BRAND2`
  attempt and split-by-brand attempts. Merge and dedupe by stable product key.
  Do not assume one combined brand page or one page number is a complete eligible
  corpus. Same-level attempts can run in parallel to protect latency, but each
  attempt still needs trace metadata so failures and recoveries are debuggable.

API characterization required before final search runner tuning:

- no-filter baseline
- brand-only single brand
- brand-only multi-brand
- rim-only
- brand + rim
- width + rim without aspect ratio
- full tire size
- full tire size + brand
- `R##` versus `ZR##` rim-family variants
- page behavior and duplicate behavior across attempts
- local model/pattern filtering over each eligible corpus
- budget, promo, EV, guarantee, price/tire category, origin, warranty, and
  terrain refiners
- zero-result recovery paths and which broader attempt recovered results

The characterization artifact should include request params, latency, category
counts, total product counts, brand/model samples, duplicate keys, recovered
zero-result attempts, and notes on which filters appear to be endpoint-supported
versus local-only. This artifact becomes the basis for ranking weights, attempt
ordering, and hard caps.

`model_or_pattern` is a first-class structured filter for tire lines and pattern
names such as `BluEarth`, `B3G1`, `Turanza`, `Ecopia`, `Geolandar`, `Pilot
Sport`, or similar. Treat it as deterministic search evidence before semantic
ranking. Use catalog fields, aliases, token matching, and normalized pattern
lookups before falling back to vector/text similarity. Add typo-tolerant fuzzy
matching for model, pattern, and slug text so common customer misspellings such
as `giolander`, `pilot spor`, and `primcy` can still recover grounded products.
SKU-like strings should match through model or slug text only. Do not use
`DOT_SKU` as product SKU evidence; DOT is tire-date evidence. Keep fuzzy
matching as candidate discovery only; it must not change size, price, promo,
stock, installment, or payment truth.

Optional semantic ranking fields:

- `semantic_query`
- `soft_preferences`

The runtime already has the raw customer message in the turn ledger. Do not
require the model to echo raw text as a product-search argument. Use
`semantic_query` only when the customer provides qualitative preferences such as
`matibay`, `quiet`, `daily use`, `pang long drive`, `premium`, `budget pero ok`,
or similar.

Bounded attempt order:

1. supplied endpoint filters as-is
2. supplied filters + normalized model/pattern aliases when present
3. supplied filters + optional budget/promo/value refiners
4. rim-size, brand-only, or model/pattern-only discovery when only partial data
   exists
5. broader endpoint query with local deterministic narrowing when the API is too
   coarse
6. compact brand/model/price/facet buckets when results are too broad
7. fitment-authorized alternatives only if vehicle/fitment truth supports them

Hard limits:

- max 6 API attempts per product search
- no full catalog dumps to model
- no alternate tire size suggestions without fitment authorization
- no price claim outside trusted product/policy tool output
- no inactive products in model-facing results; `status_id` must be `0`
- do not refuse exploratory search only because the inferred input is a
  candidate rather than a fully verified slot
- do not treat aspect ratio as mandatory; some valid tire formats omit it and
  many customers search by rim size only
- do not run semantic/vector matching only after an arbitrary top-N truncation
  from `/shop` or `/search`; that can remove the best semantic matches before
  ranking starts

Search exactness is relative to the filters supplied. `rim_size=15` is an exact
rim-size search, not a complete fitment claim. If only partial size data exists,
return compact candidates/facets and label the match basis clearly.

Semantic/vector ranking must run over the eligible corpus for the deterministic
filters, not a small prefiltered result page. If the endpoint cannot return the
full eligible set, use an indexed product catalog or paginated scan with hard
caps and traceable stopping rules. Deterministic filters still own price, stock,
promo, EV, brand, model/pattern, and tire-size eligibility; vectors only rank
qualitative fit.

Ranking:

Use an explainable filter-pass ranking model over the eligible corpus. The
ranker should emit both a numeric `match_score` for sorting and readable match
evidence for the agent.

Default scoring priorities:

- rim size match and requested brand match are the strongest signals
- requested model/pattern match is also strong, but should be scored separately
  from generic semantic similarity
- section width and aspect ratio refine fit when present
- budget fit, near-budget fit, promo, EV compatibility, Gulong Guarantee,
  price/tire category, origin, warranty, terrain, availability, installment
  bank/month/interest, and other structured refiners are secondary signals
- semantic similarity only ranks qualitative fit after deterministic eligibility

Eligibility/filter semantics:

- Active product: `status_id = 0`.
- EV-compatible: `ev_tire = 1`.
- `promo_only=true` means grounded active promos only. Active promo types
  include Buy 3 Get 1, product-level discounts such as BFGoodrich `1000 OFF`,
  and clearance sale. If the customer specifically asks for Buy 3 Get 1, the
  model should pass `promo_types=["buy3get1"]`; if they ask for discount or
  voucher-style promos, pass `promo_types=["product_discount"]`.
- Buy 3 Get 1 promo: product brand is present in `/promo_brands`. Treat that
  endpoint as the brand-level authority; product rows can have `promo_tag = 0`
  and still be eligible.
- Product discount promo: `/shop` exposes a `product_discount` object with
  fields such as `name`, `description`, and `total_discount`. For bundle
  quantities, compute the bundle-discounted unit price from SRP/list price
  first, then subtract the product discount per tire. For quantity 1, the
  sale/promo unit price can be used directly. Expose the discount text/amount
  in cards and compact product output.
- Total budget must use effective payable total for the requested quantity.
  For quantity 4, Buy 3 Get 1 uses the promo total first. Non-promo products use
  API bundle tiers when present, then local 1/2/3/4 tire bundle tiers, then unit
  price times quantity.
  `sale_tag = 1` only determines whether the bundle base price comes from
  `promo` rather than `srp`; it does not indicate API-provided bundle tiers.
  Do not generate regular bundle tiers for products whose brand is eligible
  through `/promo_brands`.
- Tire Protection Plan: `is_gulong_guarantee = 1` means 1 year and
  `is_gulong_guarantee = 2` means 6 months. `gulong_guarantee_only` accepts
  either tier; `gulong_guarantee_tiers` requests specific tiers.
- Price/tire categories such as Budget, Economy, Mid Range, and Premium should
  be model-facing list filters under `tire_categories`.
- Country origin should be represented as `origins` and normalized for common
  spelling drift such as `US`/`USA`.
- Warranty should be represented as `warranty_years` and parsed from product
  warranty text.
- Terrain/use requests such as all terrain, A/T, mud terrain, M/T, highway
  terrain, H/T, rugged terrain, and R/T should be represented as
  `terrain_types`. Infer them from safe model/pattern tokens; do not match
  short tokens like `AT` inside unrelated brand names.
- Availability should be represented as `availability=any|in_stock|pre_order`.
  In-stock products should rank above pre-order products unless pre-order is
  explicitly requested.
- Installment search should be represented as `installment_only`,
  `installment_banks`, `installment_months`, and
  `installment_max_interest`. Only product rows with grounded structured
  installment data should satisfy those filters. `/shop` exposes installments;
  `/product_list` may not, so catalog fallback rows without installment data
  are unknown for installment eligibility.
- Commercial rims such as `R14C` and `R15C` must remain distinct from passenger
  `R14` and `R15`, even when fallback matching compares rim families.
- Commercial no-aspect requests such as `195/R14C` and `195/R15C` should include
  blank/implicit profile rows and explicit `70+` aspect rows, with explicit
  `70+` rows ranked first. Lower explicit aspects remain valid pool members
  only when returned by the endpoint, but should not crowd out the implicit/70+
  commercial matches unless specifically requested.
- Non-standard section widths such as `LT265`, `31X`, `31X10.5`, `7.50`,
  `8.25`, and `11` are valid endpoint filters and must be preserved. Do not
  force all widths into three-digit passenger values. Normalize customer `7.5`
  to catalog-style `7.50`.
- Regular bundle-tier generation is controlled by
  `RUNTIME_V7_ENABLE_BUNDLE_PRICING`, enabled by default for V6 parity. If
  disabled, product search should continue normally and budget math should fall
  back to unit price times quantity except for Buy 3 Get 1.

Candidate-level match evidence:

```json
{
  "match_score": 87,
  "passed_filters": ["rim_size", "brand", "section_width", "budget_max"],
  "missed_filters": ["promo_only"],
  "soft_matches": ["daily_use"],
  "why_shown": "Matches requested R15 Yokohama search and is within budget."
}
```

The model should see compact match evidence and product cards, not raw scoring
internals or full upstream payloads. If no product satisfies the strongest
requested filters, the runner should return grouped fallback tiers such as
`same_rim_requested_brand`, `same_rim_other_brand`, and `requested_brand_other_size`
instead of mixing weak alternatives into the top list without explanation.

Search outcome:

```json
{
  "status": "ok|partial_match|no_match|needs_clarification|tool_error",
  "best_products": [],
  "product_cards": [],
  "presentation_strategy": {},
  "facets": {},
  "search_summary": {},
  "attempted_queries": [],
  "no_match_reasons": [],
  "requested_model_pattern_status": {},
  "recommended_response_strategy": "..."
}
```

### 9. Product tools and renderers

Expose a small model-facing product capability set:

- `build_product_search_intent`
- `run_product_search`
- `render_product_presentation`
- `fetch_compatible_tires`
- optional `analyze_product_image`

Internally reuse V6 product service and rendering logic where compatible.

Renderer requirements:

- render from grounded search outcome only
- return presentation-ready cards
- include stable `presentation_ref` and item refs
- never invent price, promo, DOT, origin, warranty, stock, or availability
- if search outcome is stale, recommend refresh

Runtime V7 product cards should be deterministic tool output, not model prose.
Each card returns structured fields and a ready-to-send `card_text` in this
order:

1. category badge, for example `[ECONOMY]`
2. tire/SKU/model display, grounded in model/slug fields only
3. base price per tire and total for the requested quantity
4. promo/voucher/savings when present
5. DOT/date-of-tire only when present
6. product URL

Do not use `DOT_SKU` as model/SKU evidence. In V7 it is DOT/date-of-tire
presentation evidence only. If no DOT field is available, omit the DOT line.
Use concise customer-facing icons in card text for tire/model, price,
promo/savings, DOT, and link lines.

Card selection rules:

- size-only search: show 3-4 products across different price categories when
  available.
- size + brand search: include the requested-brand match, then show other brand
  options in the same price category when possible, then adjacent price
  categories.
- budget search: prioritize products that satisfy the requested budget. If the
  strict budget set has fewer than about 3 useful cards, fill with the best
  same-hard-filter alternative such as a near-budget upsell. If no products
  satisfy it, show nearest budget options and mark the strategy as
  `nearest_budget`.
- `promo_only=true` cards must be grounded active promo products only. Do not
  show regular bundle-price products as promo-only recommendations. Use
  `promo_types=["buy3get1"]` for strict Buy 3 Get 1 searches and
  `promo_types=["product_discount"]` for discount/voucher-style promos.

### 10. Service and order tools

Reuse V6 service/order gateways through V7 adapters.

Service capabilities:

- resolve customer location
- check serviceability
- fetch installation partners
- fetch branch slots
- validate schedule
- render service options

Order capabilities:

- build order draft
- render order review
- validate booking readiness
- prepare payment request
- submit order only after explicit confirmation

Side-effect gates:

- no order submission without confirmed product, fulfillment, contact, and
  explicit customer confirmation
- no payment instruction unless payment/order tool produced trusted output
- no same-day installation promise unless service tool confirms
- no branch/partner commitment unless service tool confirms

Implementation note as of 2026-05-30:

- Installation partner discovery now supports explicit presentation disclosure
  levels. Default `find_installation_partners` output is area-only, while
  `find_installation_slots` defaults to area-level slot availability collated
  across nearby partners. Full partner records remain in service observations
  for validation and order summaries. Exact names/addresses are opt-in through
  `partner_detail_level=name_only|full_address`, intended for explicit detail
  requests or order-summary/proceed context with the reservation/no-walk-in
  policy.

These gates apply to commitments and side effects. They must not block the
orchestrator from searching products, checking possible service areas, asking a
clarifying question, or using raw/latest conversation context to continue the
sales conversation.

### 11. Orchestrator loop

Implement a single customer-facing orchestrator loop:

```text
compile context
 -> call model through LLMGateway
 -> parse structured decision/tool calls
 -> execute allowed tool calls
 -> summarize observations
 -> recover or finalize
 -> validate response
```

Default limits:

- max 3 tool rounds
- max 6 product search API attempts inside `run_product_search`
- max 1 order side-effecting tool per turn
- no parallel execution for state-mutating tools
- allow parallel read-only tools only when inputs are independent

The model should be able to choose:

- ask clarification
- run product search
- check installer/serviceability
- create order draft
- request confirmation
- recover from no match
- answer support/FAQ
- escalate or hand off safely

The model should not need a perfect slot packet before acting. It should be
able to use the customer message, conversation brief, memory hits, active refs,
and trusted observations to choose safe exploratory tools. Validators run when
the model tries to make a commercial commitment or side effect.

### 12. Response composer and guards

Output contract:

```json
{
  "bubble1": "...",
  "bubble2": "..."
}
```

Validation:

- JSON object only
- bubble keys only
- no markdown that breaks channel delivery
- target each bubble under 1,900 chars
- no unsupported price/stock/promo/schedule/payment/order claims
- price claims require trusted source and valid TTL
- installation claims require service tool observation
- order-submitted claims require submitted order tool result

Guard event examples:

- `PRICE_BLOCKED_UNTRUSTED_SOURCE`
- `PRICE_BLOCKED_TTL_EXPIRED`
- `ORDER_REVIEW_BLOCKED_MISSING_TIRE_SIZE`
- `ORDER_SUBMIT_BLOCKED_MISSING_CANONICAL_FIELD`
- `REFERENCE_AMBIGUOUS`
- `PRODUCT_SEARCH_EXPANDED`
- `TOOL_ROUND_LIMIT_REACHED`
- `ORDER_SUBMIT_BLOCKED_MISSING_CONFIRMATION`
- `PAYMENT_BLOCKED_UNTRUSTED_SOURCE`
- `SERVICE_SCHEDULE_BLOCKED_UNGROUNDED`
- `BUBBLE_TRUNCATED`
- `MARKDOWN_STRIPPED`

### 13. API and endpoint plan

Add tester endpoint first:

```text
POST /gulong/v7/tester
```

Request:

```json
{
  "user_id": "...",
  "channel_user_id": "...",
  "user_id_source": "...",
  "message": "...",
  "channel": "tester|website|manychat",
  "debug": true
}
```

Response:

```json
{
  "trace_id": "...",
  "session_id": "...",
  "user_id": "...",
  "assistant": {
    "bubble1": "...",
    "bubble2": "..."
  },
  "debug": {
    "evidence": {},
    "state": {},
    "strategy": {},
    "tool_observations": [],
    "guard_events": []
  }
}
```

Add shadow endpoint later:

```text
POST /gulong/v7/shadow
```

Shadow mode must:

- run V7 against copied traffic
- not deliver customer replies
- not submit orders
- not write ManyChat fields
- write debug artifacts and BigQuery logs only

No production traffic movement is included in the first implementation plan.

### 14. Observability

Persist logs with:

- `trace_id`
- `session_id`
- `user_id`
- Asia/Manila timestamp

Required debug surfaces:

- request state
- evidence extraction
- state reducer summary
- strategy packet
- tool calls
- tool observations
- product search attempts
- guard events
- response validation
- LLM usage
- latency breakdown

Debug artifact should include:

- latest user message
- extraction packet
- extracted evidence
- reducer updates
- compact prompt context
- model decision
- tool calls
- tool results
- response before/after guard repair
- persisted state diff

## Test Plan

### Unit tests

Add tests for:

- evidence extraction schema parsing
- invalid extractor payload repair/rejection
- tire-size evidence normalization
- phone/contact validation
- location vs product/model false-positive handling
- `sige/ok` not becoming location/contact
- `yun una` resolving to latest product presentation item
- ambiguous `yan` asking clarification
- copied brand-bucket text not becoming explicit brand selection
- customer correction overwriting prior slot
- weak inference not overwriting confirmed value
- state reducers preserving provenance
- prompt context staying compact
- strategy compiler scenario detection
- guard events for unsupported claims

### Product search tests

Add focused tests for:

- exact size + brand + budget match
- exact size + brand but over budget
- exact size + budget but different brand
- no exact brand but same-size alternatives exist
- no exact size
- vehicle-only flow requiring `fetch_compatible_tires`
- fitment-authorized alternative sizes only
- query attempt ordering
- max attempt limit
- search outcome includes attempted queries and no-match reasons
- renderer stores stable presentation refs

### Multi-turn scenarios

Required replay scenarios:

1. `205/50R17 hm`
2. assistant presents product cards
3. customer: `yun una`
4. customer: `kaya today sa Cavite?`
5. assistant checks availability and responds with grounded next step

Additional scenarios:

- `para vios 2020 hm`
- `goodyear meron?`
- `3500 kaya sir?`
- `same day installation? Carmona`
- copied mid-range bucket text
- multiple tire sizes in one message
- image/screenshot with size clue
- contact + location + product in one turn
- ready-to-book with missing contact
- payment question without order draft
- order confirmation with explicit yes
- no-match product recovery

### Regression tests against V6 failures

Replay known V6 failure families:

- stale or copied bucket text causing wrong brand inference
- product fragment being stored as location
- unsupported broad unavailable claim
- repeated lead collection
- product/service mixed intent losing service ask
- state persistence payloads not Firestore-safe
- response generated but persistence fails afterward

### Integration tests

Use fake/mocked external services first:

- fake product API
- fake installer API
- fake order API
- fake LLMGateway structured responses

Then run live-smoke tests only after deterministic tests pass:

- product search
- serviceability
- order draft only
- payment FAQ/policy
- support FAQ

No live order submission in automated tests unless explicitly marked and
disabled by default.

## Acceptance Criteria

V7 is ready for shadow only when:

- unit tests pass
- product search scenario matrix passes
- multi-turn replay artifacts show correct evidence/state/tool behavior
- no unsupported price/stock/schedule/payment claims
- context packet is compact and excludes raw full catalog dumps
- all tool calls and state updates are traceable by `trace_id`, `session_id`,
  and `user_id`
- no state-mutating side effect occurs in shadow mode

V7 is ready for limited tester traffic only when:

- shadow results beat or match V6 on grounding and continuity
- product search recovery is better than V6 on no-match and refinement
  scenarios
- order/payment guards pass
- latency remains acceptable for tested paths
- debug artifacts are sufficient to diagnose every failed scenario

## Rollout Plan

1. Create V7 implementation package and contracts.
2. Build evidence extractor and reducers with fake LLM responses.
3. Build entity registry and reference resolution.
4. Build `ProductSearchIntent` and bounded query runner.
5. Wire product renderer and presentation refs.
6. Add strategy compiler and context compiler.
7. Implement orchestrator loop through existing `LLMGateway`.
8. Add response guards and debug artifacts.
9. Add tester endpoint.
10. Run deterministic test suite.
11. Run V6 regression replay.
12. Add shadow endpoint with side effects disabled.
13. Compare V6 vs V7 traces.
14. Deploy as no-traffic or tester-only Cloud Run revision after approval.
15. Keep production V6 traffic unchanged until explicit promotion approval.

## Assumptions And Defaults

- V7 work targets `D:\Carlo\LICA Auto\assistant\gulong-chat-platform`.
- V7 is a new runtime lane, not an in-place V6 rewrite.
- First implementation uses the existing `LLMGateway` and custom tool loop.
- Product search loop is controlled Python business logic, not arbitrary hosted
  Code Interpreter execution.
- Firestore remains authoritative for live user/session/business state.
- BigQuery remains audit/history only.
- Vector search is optional and auxiliary in V1.5, not required for V1.
- No production traffic movement is included.
- No live order submission is included in automated validation.
- All business-facing datetime values use Asia/Manila format.
- All external side effects require explicit guard checks and trace logging.
