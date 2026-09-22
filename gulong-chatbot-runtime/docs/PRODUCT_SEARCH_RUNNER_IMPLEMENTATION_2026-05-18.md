# Runtime V7 Product Search Runner Implementation

Date: 2026-05-18

## Implemented Files

- `runtime_v7/product_search.py`
- `scripts/runtime_v7_product_search_probe.py`
- `test/test_runtime_v7_product_search_runner.py`

## Model-Facing Input Contract

The single product-search tool contract uses `brands` only. Do not expose both
`brand` and `brands`.

```json
{
  "section_width": "185",
  "aspect_ratio": "60",
  "rim_size": "R15",
  "brands": ["YOKOHAMA"],
  "model_or_pattern": "BluEarth",
  "budget_max": 5000,
  "budget_scope": "per_tire",
  "promo_only": false,
  "promo_types": [],
  "ev_compatible": null,
  "gulong_guarantee_only": null,
  "gulong_guarantee_tiers": [],
  "origins": ["Japan"],
  "warranty_years": [5],
  "tire_categories": ["Premium"],
  "terrain_types": ["ALL_TERRAIN"],
  "availability": "in_stock",
  "installment_only": true,
  "installment_banks": ["BPI"],
  "installment_months": [6],
  "installment_max_interest": 0,
  "quantity": 4,
  "sort": "best_value",
  "top_k": 6,
  "semantic_query": "quiet daily comfort",
  "soft_preferences": []
}
```

All fields are optional. The runner searches using the fields it has and labels
the match basis in the output.

## Output Contract

```json
{
  "status": "ok|partial_match|no_match",
  "result_level": "exact|near_exact|partial|alternate|none",
  "query_basis": {
    "normalized_filters": {},
    "partial_match": false,
    "stopped_reason": "..."
  },
  "best_products": [],
  "facets": {},
  "match_tiers": {},
  "result_pool_summary": {},
  "attempted_queries": [],
  "no_match_reasons": [],
  "requested_brand_status": {},
  "requested_model_pattern_status": {},
  "budget_status": {},
  "recommended_response_strategy": "...",
  "observation_ref": "obs_product_search_...",
  "latency_ms": 0,
  "api_call_count": 0
}
```

Each product carries compact match evidence:

```json
{
  "match": {
    "match_score": 92,
    "tier": "exact",
    "passed_filters": ["rim_size", "brand", "section_width", "aspect_ratio"],
    "missed_filters": [],
    "soft_matches": [],
    "why_shown": "..."
  }
}
```

The runner also returns deterministic product cards:

```json
{
  "product_cards": [
    {
      "card_ref": "card_1",
      "item_ref": "prod_1",
      "category": "Premium",
      "sku_model": "MICHELIN 185/60/R15 ENERGY XM2+ 88H",
      "deal_price_line": "PHP 6,570.00/tire | PHP 25,491.60 for 4 tires",
      "promo_savings_line": "Bundle: Save PHP 788.40",
      "dot": "2024",
      "url": "https://gulong.ph/product/...",
      "card_text": "[PREMIUM]\n🛞 MICHELIN 185/60/R15 ENERGY XM2+ 88H\n💰 PHP 6,570.00/tire | PHP 25,491.60 for 4 tires\n🎁 Bundle: Save PHP 788.40\n🗓️ DOT: 2024\n🔗 https://gulong.ph/product/..."
    }
  ],
  "presentation_strategy": {
    "mode": "size_category_mix|size_brand_with_alternatives|budget_satisfied|nearest_budget|diverse_ranked",
    "brands": [],
    "categories": []
  }
}
```

Card text is composed by code in this line order:

1. category badge, for example `[PREMIUM]`
2. tire/SKU/model display from grounded model/slug fields
3. base price per tire and total for the requested quantity
4. promo/voucher/savings when present and applicable to the requested quantity
5. DOT/date-of-tire only when present
6. product URL

`DOT_SKU` is not SKU/model evidence. It is used only as DOT/date-of-tire
presentation evidence when present. If DOT is absent, the DOT line is omitted.

Card selection is intentionally more diverse than raw ranking:

- size-only: prefer one card per price category, up to 4 cards.
- size + brand: include the requested-brand card, then same-category other
  brands, then adjacent price categories.
- budget: prefer cards within budget; if fewer than about 3 useful cards
  qualify, fill with the best same-hard-filter alternative such as a
  near-budget upsell. If none qualify, show nearest budget options and mark
  `presentation_strategy.mode = nearest_budget`.
- promo-only: show only grounded active promo cards. Active promo types include
  Buy 3 Get 1, product-level discounts such as BFGoodrich `1000 OFF`, and
  clearance sale. Do not include regular bundle-price products such as Fronway
  when `promo_only=true`. Use `promo_types=["buy3get1"]` for strict Buy 3 Get
  1 searches and `promo_types=["product_discount"]` for discount/voucher-style
  promos.

## Endpoint Behavior Observed

- `/shop` must be called with `POST`; direct `GET /shop?...` returned 405 in
  prior verification.
- Brand filters are passed as `b=BRAND1--BRAND2`.
- Brand normalization is runtime-owned. The model passes the likely brand text
  it understood, and the runner canonicalizes it before building `/shop`
  params. Deterministic aliases plus bounded fuzzy matching cover common
  customer typos such as `micheline`, `yokohana`, `bfgudruch`, `arrivo`,
  `weslake`, and `bridgeston`. The output includes compact
  `brand_corrections` metadata when the runtime changed a brand value.
- A combined multi-brand request can be incomplete or ordering-sensitive, so the
  runner issues combined and split-by-brand attempts, then dedupes by product
  key.
- `R15` and plain `15` are not equivalent at the API layer. The runner
  normalizes customer rim values like `15` to `R15` for normal tire search.
- `R21` and `ZR21` need rim-family recovery. Exact `265/35/R21` can return zero
  while `265/35/ZR21` returns Michelin products.
- Width+rim searches without aspect ratio are valid and useful.
- Model/pattern-only search is unreliable through first-page `/shop`; the runner
  uses `/product_list` as a catalog fallback for these cases.
- Model-facing results exclude inactive products. A product must have
  `status_id = 0`.
- Buy 3 Get 1 promo eligibility is authoritative from `/promo_brands`. Product
  rows may have `promo_tag = 0` while still belonging to a 3+1 promo brand, as
  seen on Michelin sale-tag rows.
- Product discount promo eligibility comes from `/shop.product_discount`, for
  example BFGoodrich rows with `name = BFG Promo`, `description = 1000 OFF`,
  and `total_discount = 1000`. The runner uses the sale/promo unit price when
  this discount is active and exposes the discount text and amount in compact
  product output and cards.
- EV-compatible means `ev_tire = 1`.
- Tire Protection Plan means `is_gulong_guarantee = 1` for 1 year or
  `is_gulong_guarantee = 2` for 6 months.
- Price/tire category is represented as `tire_categories`, with normalized
  values such as `Budget`, `Economy`, `Mid Range`, and `Premium`.
- Country of origin is represented as `origins`. The runner normalizes common
  spelling drift such as `US`, `USA`, and `United States`.
- Warranty filtering is represented as `warranty_years` and is parsed from
  product warranty text such as `5 years from purchase date`.
- Terrain/use intent is represented as `terrain_types`, not generic semantic
  text. Supported normalized values include `ALL_TERRAIN`, `MUD_TERRAIN`,
  `HIGHWAY_TERRAIN`, and `RUGGED_TERRAIN`. The runner detects safe model tokens
  such as `A/T`, `M/T`, `H/T`, `R/T`, `ALL-TERRAIN`, and `MUD TERRAIN` without
  treating brand text like `ATLAS` as an all-terrain match.
- Model/pattern search uses deterministic fuzzy matching. The searchable text
  includes brand, model, pattern, size, slug, description, and features. Do not
  use `DOT_SKU` for SKU/model search; DOT is tire-date evidence, not the product
  model/SKU. SKU-like customer strings should match only when they appear in
  grounded model or slug text. Typo tolerance uses token coverage and phrase
  similarity, so inputs such as `giolander`, `pilot spor`, and `primcy` can
  still match grounded catalog rows. Fuzzy matching is used to find candidate
  products; it does not override size, price, promo, stock, or payment truth.
- Availability is represented as `availability` with values `any`, `in_stock`,
  or `pre_order`. By default, in-stock products rank before pre-order products.
  When `availability=pre_order`, pre-order products can be searched explicitly.
- Installment availability is represented by `installment_only`,
  `installment_banks`, `installment_months`, and `installment_max_interest`.
  Product rows expose compact `installments`, `installment_text`, and
  `installment_min_interest` only when the API returns product-level
  installment data.
- Live API check: `/shop` exposes `installments` and `pre_order`; `/product_list`
  exposes `pre_order` but did not expose `installments`. Therefore installment
  search must be grounded in `/shop` results or another installment-aware
  product endpoint. Do not infer installment availability from catalog fallback
  rows that lack `installments`.
- `/shop` often omits origin and warranty fields even when the product exists.
  If requested origin/warranty/category/terrain refiners do not produce exact
  matches from `/shop`, the runner may use `/product_list` catalog fallback
  before settling for a near match.
- Commercial tire rims such as `R14C` and `R15C` are distinct from passenger
  `R14` and `R15`. Preserve the `C` suffix in endpoint params and fallback
  matching.
- Commercial width/rim requests without an aspect ratio, such as `195/R14C` or
  `195/R15C`, intentionally include blank/implicit aspect rows and explicit
  `70+` aspect rows. Explicit `70+` rows are ranked above blank/implicit rows;
  lower explicit profiles can remain in the pool but should not crowd out the
  implicit/70+ commercial profile matches.
- Non-standard section widths are valid endpoint values. Preserve values such as
  `LT265`, `31X`, `31X10.5`, `7.50`, `8.25`, `11`, and similar instead of
  forcing every section width into a three-digit passenger width.

## Budget and Bundle Pricing

Budget filtering uses the effective payable price for the requested quantity,
not only `unit_price * quantity`.

- `budget_scope = total`: compare `budget_max` against the effective total for
  `quantity`.
- `budget_scope = per_tire`: compare `budget_max` against effective total
  divided by `quantity`.
- Buy 3 Get 1 takes priority when `quantity = 4` and the product brand is
  present in `/promo_brands`. The payable total is 3 tires.
- Regular bundle pricing is used next. If the API exposes `bundle_pricing`
  tiers, those tiers are trusted. Otherwise the runner builds the existing
  Gulong-style 1/2/3/4 tire tiers from the unit price.
- Current live `/product_list` and `/shop` probes did not expose API
  `bundle_pricing` tiers, so the local tiers are the active source today.
- `sale_tag = 1` does not mean the API supplied bundle tiers. It only changes
  the base unit price choice: use `promo` when sale-tagged, otherwise use `srp`.
  Regular bundle tiers are not generated for products whose brand is eligible
  through `/promo_brands`.
- Active `product_discount` also selects the sale/promo unit price and is shown
  as discount promo evidence, for example `BFG Promo: PHP 1,000.00 off/tire`.
  For bundle quantities, apply the bundle discount to SRP/list price first,
  then subtract the product discount per tire. This matches BFGoodrich website
  cards such as PHP 4,040.05 bundle price minus PHP 1,000.00 = PHP 3,040.05.
- Regular bundle-tier generation is behind `RUNTIME_V7_ENABLE_BUNDLE_PRICING`.
  Default is enabled to match V6 behavior. When disabled, Buy 3 Get 1 still
  works, but non-promo products fall back to unit price times quantity.
- If no promo or bundle tier applies, the fallback is `unit_price * quantity`.

Products expose `total_price`, `total_price_text`, `pricing_basis`, and
`bundle_pricing` so the response layer can explain whether a budget match came
from `buy3get1`, `bundle_tier`, or `unit_price`.

## Ranking Rules

Ranking is explainable filter-pass scoring:

1. rim size
2. requested brand
3. requested model or pattern
4. section width and aspect ratio
5. budget, promo, EV, guarantee, category, origin, warranty, terrain,
   availability, installment bank/month/interest, and other refiners
6. semantic query as a tie-breaker only

The runner does not rely on vector similarity for price, stock, promo, brand,
size, model/pattern, category, origin, warranty, terrain, availability, or
installment truth.

## Live Probe Results

Latest suite artifact:

- JSON: `tmp/runtime_v7_product_search/suite_20260518_084143.json`
- Markdown: `tmp/runtime_v7_product_search/suite_20260518_084143.md`

Latest suite artifact after category/origin/warranty/terrain filters:

- JSON: `tmp/runtime_v7_product_search/suite_20260518_090633.json`
- Markdown: `tmp/runtime_v7_product_search/suite_20260518_090633.md`

Latest suite artifact after pre-order/installment filters:

- JSON: `tmp/runtime_v7_product_search/suite_20260518_091850.json`
- Markdown: `tmp/runtime_v7_product_search/suite_20260518_091850.md`

Latest suite artifact after typo/fuzzy model-pattern checks:

- JSON: `tmp/runtime_v7_product_search/suite_20260518_092621.json`
- Markdown: `tmp/runtime_v7_product_search/suite_20260518_092621.md`

Latest suite artifact after DOT/SKU correction and catalog-cache optimization:

- JSON: `tmp/runtime_v7_product_search/suite_20260518_094155.json`
- Markdown: `tmp/runtime_v7_product_search/suite_20260518_094155.md`

Latest suite artifact after brand typo canonicalization:

- JSON: `tmp/runtime_v7_product_search/suite_20260518_095235.json`
- Markdown: `tmp/runtime_v7_product_search/suite_20260518_095235.md`

Latest warm-catalog suite artifact after parallel brand attempts and model
candidate refinement:

- JSON: `tmp/runtime_v7_product_search/suite_20260518_100252.json`
- Markdown: `tmp/runtime_v7_product_search/suite_20260518_100252.md`

Latest warm-catalog suite artifact after deterministic product-card rendering:

- JSON: `tmp/runtime_v7_product_search/suite_20260518_114349.json`
- Markdown: `tmp/runtime_v7_product_search/suite_20260518_114349.md`

Latest characterization artifact:

- JSON: `tmp/runtime_v7_product_search/characterize_20260518_075131.json`
- Markdown: `tmp/runtime_v7_product_search/characterize_20260518_075131.md`

Bundle/commercial-size probe artifact:

- JSON: `tmp/runtime_v7_product_search/bundle_commercial_probe_20260518_080815.json`
- Follow-up C-suffix verification:
  `tmp/runtime_v7_product_search/commercial_c_suffix_verify_20260518_081017.json`
- Non-standard size probe:
  `tmp/runtime_v7_product_search/nonstandard_size_probe_20260518_082407.json`
- Non-standard size follow-up after normalization patch:
  `tmp/runtime_v7_product_search/nonstandard_size_followup_20260518_082715.json`
- Commercial no-aspect profile verification:
  `tmp/runtime_v7_product_search/commercial_no_aspect_rerank_20260518_083718.json`
- Commercial no-aspect 70+ verification:
  `tmp/runtime_v7_product_search/commercial_no_aspect_70plus_20260518_084100.json`

Latest suite summary:

- scenarios: 68
- successful result pools: 68
- inactive best products: 0
- status counts: `{"ok": 61, "partial_match": 7}`
- result levels: `{"exact": 61, "near_exact": 5, "partial": 2}`
- promo brands observed: 3 (`APOLLO`, `MICHELIN`, `VREDESTEIN`)
- warm catalog: 3769 products loaded in 2922 ms before scenario execution
- overall latency after warm catalog and deterministic product-card rendering:
  min 57 ms, median 566 ms, p90 1375 ms, max 2569 ms
- exact/near latency after warm catalog: min 57 ms, median 550 ms, p90
  1247 ms, max 2048 ms

New focused scenario results:

- `model_pilot_sport_265_35_r21`: exact after R21 -> ZR21 recovery.
- `model_pilot_sport_only`: exact model/pattern match from broad discovery.
- `ev_pilot_sport_265_35_zr21_michelin`: exact match on size, brand, model, and
  `ev_tire = 1`.
- `promo_buy3get1_175_65_r14_budget_total_15000`: exact match on size,
  Buy 3 Get 1, and total budget.
- `promo_discount_bfgoodrich_brand_only`: exact product-discount promo pool
  using `/shop.product_discount` rows such as `BFG Promo` / `1000 OFF`.
- `promo_buy3get1_bfgoodrich_should_not_match_discount`: negative check proving
  BFGoodrich discount-only promos are not treated as Buy 3 Get 1 when
  `promo_types=["buy3get1"]`.
- `budget_total_15000_175_65_r14_including_promo`: exact total-budget pool using
  promo totals where applicable.
- `guarantee_any_185_60_r15`: exact Tire Protection Plan pool.
- `guarantee_tier_1_185_60_r15`: exact 1-year Tire Protection Plan pool.
- `guarantee_tier_2_r15_yokohama`: near-exact pool because Yokohama R15 matched
  rim and brand but did not satisfy tier 2 in the observed pool.
- `195/R14C`: exact commercial-size pool with 19 products in one `/shop` call.
- `195/R15C`: exact commercial-size pool with 24 products in one `/shop` call.
- `195/R14C` no-aspect now surfaces explicit `70+` rows plus implicit profile
  rows in the top results.
- `195/R15C` no-aspect now surfaces explicit `70+` rows plus implicit profile
  rows in the top results.
- `7.5-15`: exact legacy-size pool after normalizing `7.5` to catalog value
  `7.50` and preserving bare numeric rim `15`.
- `8.25-20`: exact legacy-size pool using bare numeric rim `20`.
- `11R22.5`: exact truck-size pool after normalizing bare `22.5` to `R22.5`.
- `31X/R15`: exact flotation-size pool after normalizing rim `15` to `R15`.
- `LT265/75R16`: exact LT-size pool with `LT265` preserved as section width.
- `category_budget_r15`: exact Budget category pool.
- `category_premium_michelin_r17`: exact rim + Michelin + Premium pool.
- `warranty_5_years_185_60_r15`: exact warranty pool.
- `terrain_all_terrain_catalog`: exact all-terrain pool using A/T model-token
  detection.
- `terrain_mud_terrain_catalog`: exact mud-terrain pool using M/T/model-token
  detection.
- `terrain_all_terrain_r17`: exact R17 all-terrain pool.
- `terrain_mud_terrain_r17`: exact R17 mud-terrain pool.
- `origin_japan_185_60_r15` and `origin_france_michelin`: near-exact after
  catalog fallback because the observed API payloads did not expose origin for
  the strongest matching products.
- `category_origin_warranty_combo`: near-exact after catalog fallback because
  the observed catalog row matched origin and warranty but lacked the category
  value.
- `availability_in_stock_185_60_r15`: exact in-stock pool.
- `availability_pre_order_r18`: exact pre-order pool.
- `installment_bpi_6mo_zero_185_60_r15`: exact pool with BPI 6-month 0%
  installment evidence.
- `installment_bpi_zero_brand_michelin`: exact Michelin installment pool with
  BPI 0% evidence.
- `installment_any_r17`: exact R17 installment pool.
- `model_typo_pilot_spor_only`: exact model/pattern match for Michelin Pilot
  Sport. With a warm product-list cache this recovered through one broad
  `/shop` attempt in 1629 ms in the latest suite.
- `model_typo_giolander_catalog_fallback`: exact model/pattern match for
  Yokohama Geolandar after `/product_list` fallback. With a warm product-list
  cache this ran in 1064 ms in the latest suite.
- `model_typo_primcy_catalog_fallback`: exact model/pattern match for Michelin
  Primacy.
- `brand_typo_micheline_r15`: canonicalized to `MICHELIN`, called `/shop`
  with `b=MICHELIN`, used catalog-backed presentation alternatives, and
  returned an exact pool in 552 ms.
- `brand_typo_yokohana_185_60_r15`: canonicalized to `YOKOHAMA`, called
  `/shop` with `b=YOKOHAMA`, and returned an exact pool in 518 ms.
- `brand_typo_bfgudruch_r17`: canonicalized to `BFGOODRICH`, called `/shop`
  with `b=BFGOODRICH`, and returned an exact pool in 525 ms.
- `brand_typo_weslake_arrivo_bridgeston`: canonicalized to `WESTLAKE`,
  `ARIVO`, and `BRIDGESTONE`, then used combined and split-by-brand attempts.
  Parallel same-level attempts returned an exact pool in 970 ms.

Slow cases:

- `missing_brand_recovery_185_60_r15`: 3479 ms because multiple exact attempts
  returned zero before rim-only recovery.
- `over_specific_missing_size_recovery`: 3661 ms because exact size was invalid
  and the runner broadened to brand/rim-level alternatives.
- These are partial zero-result recovery paths. They are intentionally slower
  than exact and near-exact searches because the runner must prove the narrower
  query missed before broadening.

## Current Interpretation

The runner now handles exact, partial, alternate, and recovered result pools with
traceable attempts. With a warm catalog, exact or near-exact searches stayed
under 2 seconds in the latest suite. Partial zero-result recovery can exceed 2
seconds because it makes several progressively broader attempts and records how
the result pool was obtained.

## Remaining Follow-Ups

- Product-list catalog cache is implemented through
  `RUNTIME_V7_ENABLE_PRODUCT_LIST_CACHE` and
  `RUNTIME_V7_PRODUCT_LIST_CACHE_TTL_SECONDS` with a default 900-second TTL.
  Call `ProductSearchRunner.warm_catalog_cache()` during Cloud Run startup or
  before routing traffic. Latest warmup loaded 3769 products in 3467 ms before
  scenario execution. The hard sub-2s target is a warm-path target; do not
  allow the first live customer request to pay the catalog-cache fill cost.
- Add a product observation store so raw attempt data can be referenced by
  `observation_ref` instead of included in prompt context.
- Keep monitoring whether `budget_max` should default to per-tire or require
  `budget_scope` when the user says a total budget for four tires.
- Wire `run_product_search` into the V7 tool gateway after product-card
  rendering is finalized.
