# Runtime V7 Product/Service Foundation Checkpoint

Date: 2026-05-26

Branch point intent: create a clean foundation commit for Runtime V7 product,
service, memory, signal, context, FAQ, and presentation infrastructure before
starting the dedicated orders-domain branch.

## Scope Included

- Product discovery/search/detail tools:
  - `product_search`
  - `discover_brand_buckets`
  - `extract_compatible_fitment`
  - `resolve_product_reference`
  - `get_product_details`
  - `answer_product_faq`
- Service read tools:
  - `answer_service_faq`
  - `find_installation_partners`
  - `find_installation_slots`
  - `validate_installation_slot`
  - `get_branch_addons`
- Order-domain scaffold:
  - `answer_order_faq` only
  - no order creation, payment collection, reservation confirmation, checkout,
    booking, or fulfillment action
- Runtime support:
  - capability registry and profile compiler
  - model-led tool loop with bounded retries
  - active working memory
  - background signal ledger/normalization
  - image and conversation evidence intake
  - deterministic product/service card renderers
  - compact model-visible FAQ/tool outputs

## Validation

- Focused product/service harness:
  - `pytest test/test_runtime_v7_product_observation_harness.py -q`
  - latest local result before branch split: `162 passed`
- Full Runtime V7 unit/regression set:
  - `pytest $(rg --files test | rg "test_runtime_v7") -q`
  - latest local result before branch split: `221 passed`
- Latest full live pack artifact:
  - `tmp/runtime_v7_live_test_pack/runtime_v7_live_pack_20260525_135227/summary.md`
  - 14 scenarios, 37 turns, no guardrail abort

## Known Open Product/Service Gaps

- Image-derived tire size plus unvalidated brand should choose broad discovery or
  brand menu more reliably when the customer asks generally for price/options.
- Product-card screenshot availability still needs stronger validation and
  cleaner customer wording.
- Fitment responses should explain candidate uncertainty more clearly instead
  of only asking for sidewall confirmation.
- Service follow-ups after refined locations should rerun partner lookup or
  slot lookup when the new location materially changes the search.
- Add-on questions should combine `answer_service_faq` with `get_branch_addons`
  when partner refs exist.
- Customer-facing text must avoid internal terms such as `service tools`.
- Threshold-driven delivery fallback still needs a stronger live scenario path
  where trusted SKU, quantity, and service lookup all execute in the same flow.

## Orders Branch Boundary

Orders work may build on this foundation, but should remain read/quote/readiness
focused until the order/payment/schedule action boundary is explicitly approved.
The first dedicated orders pass should not assume product/service is complete;
it should consume trusted product/service refs and preserve the same model-led
tool-use pattern.
