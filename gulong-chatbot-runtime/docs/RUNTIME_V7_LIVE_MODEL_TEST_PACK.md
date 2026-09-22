# Runtime V7 Live Model Test Pack

This compact pack is for live Runtime V7 model probes, not scripted local-only
tests. The runner executes selected scenarios through the Runtime V7 harness
with live LLM clients, live background-signal extraction, live Active Working
Memory generation, live FAQ embedding retrieval, and live tool APIs where
configured.

Production-runtime observability is tracked separately in
`docs/RUNTIME_V7_PRODUCTION_OBSERVABILITY_NOTE.md`. The test-pack metrics are
eval artifacts only; they are not a substitute for production assistant, LLM
span, tool, state, memory, guard, delivery, latency, and cost logs.

Scenario definitions live in:

`test_packs/runtime_v7_live_model_test_pack.json`

Focused first-turn intro scenarios live in:

`test_packs/runtime_v7_first_turn_intro_live_pack.json`

Runner:

`scripts/runtime_v7_live_test_pack.py`

Customer-visible endpoint runner for first-turn intro checks:

`scripts/runtime_v7_first_turn_intro_endpoint_probe.py`

## Safety Boundary

Do not run the full pack casually. It is intentionally designed to call live
models and, for service/product scenarios, live tool integrations where the
current Runtime V7 tool layer is configured to do so.

Each scenario is isolated in a fresh harness with fresh in-memory state, fresh
product/service observation stores, and a scenario-specific `session_id`. Context
cache may reuse stable prompt/schema prefixes for cost, but it is not a source
of runtime state.

Live runs have hard guardrails:

- model calls are capped at 60 seconds each by default
- model calls are capped per turn, per scenario, and per run
- tool-loop LLM rounds are capped per turn
- if any model-call budget is exceeded, the runner writes the partial summary
  and exits with a non-zero status before making the next model call

Defaults:

- `--model-timeout-s 60`
- `--max-tool-rounds 4`
- `--max-model-calls-per-turn 12`
- `--max-model-calls-per-scenario 60`
- `--max-model-calls-per-run 350`

The pack does not commit customer media URLs. Image scenarios use environment
variable placeholders:

- `RUNTIME_V7_TEST_TIRE_IMAGE_URL`
- `RUNTIME_V7_TEST_CONVERSATION_SCREENSHOT_URL`
- `RUNTIME_V7_TEST_PRODUCT_CARD_IMAGE_URL`

Use `--strict-env` when intentionally running image scenarios so missing media
URLs fail fast instead of silently skipping image evidence.

The runner defaults to the live image evidence extractor. Non-image scenarios do
not incur image extraction calls because they pass no image URLs.

Scenarios may set `request_time` to force relative-date behavior. This is used
for the 2 AM `bukas` schedule case.

## Review Command

List scenarios without model calls:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_live_model_test_pack.json --list
```

Run one live scenario:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_live_model_test_pack.json --mode live --scenario mt01_product_discovery_details_close --enable-context-cache
```

Run by tag:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_live_model_test_pack.json --mode live --tag service --limit 5 --enable-context-cache
```

Run with stricter budget guardrails:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_live_model_test_pack.json --mode live --tag service --limit 3 --max-model-calls-per-turn 8 --max-model-calls-per-scenario 25 --max-model-calls-per-run 75 --enable-context-cache
```

Outputs are written under:

`tmp/runtime_v7_live_test_pack/<run_id>/`

## Complete-turn human response evaluation

The complete-turn pack is separate from the broad technical pack:

`test_packs/runtime_v7_human_response_eval_pack.json`

It covers 13 varied customer episodes derived from paraphrased patterns in the
bounded ManyChat study. Populated brand, tire-size, vehicle, and location
variation values are unique across the pack. The scenarios do not contain a
target response script or required style phrases.

List or validate the pack without a model/tool call:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_human_review_bundle.py --validate-pack test_packs/runtime_v7_human_response_eval_pack.json
python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_human_response_eval_pack.json --list
```

During implementation, run one selected live scenario only after the offline
focused tests pass:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
$env:LANGSMITH_TRACING='false'; $env:LANGCHAIN_TRACING_V2='false'
python scripts/runtime_v7_live_test_pack.py `
  --pack test_packs/runtime_v7_human_response_eval_pack.json `
  --mode live --scenario <scenario_id> `
  --memory-generator heuristic --background-signal-generator none `
  --image-evidence-generator none --lead-qualifier-generator none `
  --max-model-calls-per-turn 8 --max-model-calls-per-scenario 16 `
  --max-model-calls-per-run 20
```

Convert the resulting per-scenario JSON, an API debug envelope, or a directory
of approved or pre-redacted artifacts into a data-minimized review bundle:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_human_review_bundle.py `
  --input <scenario-json-or-directory> `
  --pack test_packs/runtime_v7_human_response_eval_pack.json
```

The bundler writes UTF-8 per-scenario JSON/Markdown plus a summary under
`tmp/runtime_v7_human_review_bundle/<run_id>/`. It includes ordered customer
payloads, allowlisted renderer-owned presentation evidence, and compact
telemetry; prompts, profile fields, raw tool bodies, request/session/trace IDs,
absolute source paths, and raw violation bodies are not copied. Action tokens
remain available for structural checks, but router targets are normalized to a
configured marker. Phone/email patterns and URL query secrets are redacted.
This is not general de-identification: arbitrary names and addresses in
free-form messages require an approved source or preprocessing before the
bundle is shared.

The input may be a full persisted debug envelope or an ordinary API result made
with bounded `include_debug` diagnostics. The latter preserves the final
customer payload and aggregate diagnostics but cannot provide model-call detail
that was never present. An explicitly empty rendered payload stays empty and is
blocked; it is never replaced with reconstructed output. Missing customer-input
evidence is also blocking because understanding cannot be reviewed without it.

Evidence labels are deliberately strict:

- `structural_only`: reconstructed from a harness turn; not a customer-path
  rendering or delivery claim.
- `customer_path_return_only`: produced by the API/channel path without sending
  to a customer.
- `manychat_api_send_success`: the artifact records API delivery success; actual
  Messenger visibility still requires transcript or controlled-contact proof.

Mechanical findings cover only observable invariants: missing output, exact
duplicate messages/tokens, multiple active choice layers, image transport, and
explicit recorded contract violations. They do not infer naturalness from
phrases, greetings, emoji, length, or punctuation.
Product selection plus a supporting promo action is treated as one compatible
presentation, not two competing booking decisions; other mixed decision layers
remain blocking.

The primary orchestrator reads the complete visible episode and fills the seven
dimensions: understanding, natural language, directness, grounding,
progression, presentation, and consistency. Validate a completed review with:

```powershell
python scripts/runtime_v7_human_review_bundle.py --validate-review <review.json>
```

### Proportional test cadence

Use this order and do not restart from the largest gate after every edit:

1. Every meaningful edit: pack validation, `py_compile`, and
   `pytest test/test_runtime_v7_human_review_bundle.py -q`.
2. Final tooling integration: run `test/test_runtime_v7_channel_renderer.py`
   once because the bundler reuses its renderer.
3. Live smoke: one selected scenario once, with explicit call caps. Reuse the
   resulting artifact for review and bundler validation.
4. Full Runtime V7 suite: only when a later increment changes runtime code,
   prompts, renderer behavior, state, or API ingress, and once before merge or
   release rather than after each patch.
5. Full human-response/live pack: only for an approved release candidate after
   focused failures are resolved. Do not use it as an edit-loop test.

## First-Turn Intro Probe

The first-turn pack targets the welcome/intake cases separately from the broad
product/service live pack:

- vague new-customer greeting -> one complete model-composed opening
- exact automated starter buttons -> advisory intent routed through model-owned
  composition, with no prewritten customer response
- product, vehicle, service, location, and assistance first turns -> complete
  model-composed opening; exact fixed welcome is failure fallback only
- seeded prior ManyChat automation, human-agent, or chatbot outbound message ->
  no runtime-owned intro

List the first-turn scenarios without model calls:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_first_turn_intro_endpoint_probe.py --pack test_packs/runtime_v7_first_turn_intro_live_pack.json --list
```

Run one return-only endpoint check against a deployed Runtime V7 service:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_first_turn_intro_endpoint_probe.py --base-url https://<runtime-service-url> --pack test_packs/runtime_v7_first_turn_intro_live_pack.json --scenario ft04_actionable_size_welcome_only
```

Run the same scenarios through the harness runner when prompt/context/tool
artifacts are needed:

```powershell
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_first_turn_intro_live_pack.json --mode live --scenario ft04_actionable_size_welcome_only --memory-generator heuristic --background-signal-generator hybrid-live --image-evidence-generator none --max-model-calls-per-run 20
```

Endpoint probe outputs are written under:

`tmp/runtime_v7_first_turn_intro_endpoint_probe/<run_id>/`

`tmp/` is gitignored.

## What To Inspect

Each scenario artifact includes:

- user turns and final runtime responses
- capability profile history and exposed tools
- compiled context packets and system prompt
- Background Signals before the turn
- image and conversation evidence refs
- tool calls, args, results, and latency
- LLM usage, cache usage, and model latency
- estimated model cost by model and component
- Active Working Memory after each turn
- final product and service observation headers

Primary review questions:

- Did the model choose the right tool or request capability when the tool was
  missing?
- Did broad product inquiries use brand discovery before exact SKU search?
- Were prices, promos, product details, installation partners, and slots
  grounded by trusted tool or FAQ output?
- Did normalized locations, tire sizes, selected products, schedules, and human
  agent context stay aligned across Background Signals, memory, and tool args?
- Did the response stay conversational and customer-led while deterministic
  cards owned product/service facts?
- What were the per-turn latency and cost drivers?
- Does a general business-location/physical-shop answer state the reviewed
  operating model directly and credibly, without turning the `over 100
  partners` brand claim into exact nearby coverage or presenting the head
  office as a retail site?
- Across different intents and transition states, did the model own the full
  acknowledgement/answer/surface-transition/CTA sequence rather than relying
  on deterministic connective copy?

For response-composition changes, use a varied focused subset before any full
pack run. Include at least one general first turn, one grounded deterministic
surface, one missing-information case, one service/location transition, and
one continuing or corrective turn. Change brands, sizes, vehicles, locations,
and SKU context between probes; do not treat repeated success on one example as
general-quality evidence. The orchestrator reviews naturalness and commercial
progression; mechanical checks cover only structure and authority.

For adaptive guided-surface evaluation, start the endpoint through the
staging-parity launcher rather than importing the API under a dotenv-only
process:

```powershell
python scripts/runtime_v7_local_endpoint_server.py --check-only
python scripts/runtime_v7_local_endpoint_server.py --port 8765
```

The launcher fetches only literal, non-secret values from the current staging
Cloud Run service, verifies the router namespace plus turn-plan, promo-catalog,
and brand-knowledge flags, and forces local `return_only` delivery. Feed buttons
returned by `/gulong/v7/chat/tester` back through
`/gulong/v7/choice-action/tester`. Do not invent button replies: the adaptive
customer/orchestrator should choose among the choices actually rendered, or
reply naturally in free text when that is what a customer would do. A rendered
payload and accepted tester click prove local render/state behavior, not real
ManyChat delivery; retain one controlled live-contact check for the release
gate.

Promo-dependent probes must opt into the same published read-only catalog used
by the API harness:

```powershell
python scripts/runtime_v7_live_test_pack.py --pack test_packs/runtime_v7_human_response_eval_pack.json --scenario hr06_pricelist_supporting_warranty --enable-promo-catalog --memory-generator heuristic --background-signal-generator none --image-evidence-generator none
```

The flag is intentionally off by default so unrelated probes do not incur a
catalog vector search or hidden promo-applicability inventory lookup.

## Cost Reporting

`summary.json` and `summary.md` include model-cost estimates from the live usage
metadata returned by the provider. Cost is split by:

- uncached input tokens
- cached input tokens
- output tokens
- model
- runtime component such as main tool loop, background signal extraction,
  Active Working Memory update, and image evidence extraction

The built-in pricing profile is `gemini_paid_standard_2026_05_22`, using Gemini
Developer API paid-tier standard token rates. Pass `--pricing-config <path>` to
override or refresh rates without changing the runner.

Cost estimates exclude context-cache storage, Google Search/Maps grounding
charges, Gulong API calls, geocoding/API charges, embeddings without token usage
metadata, and failed model attempts when the provider did not return usage.

The current pack intentionally favors fewer, denser multi-turn scenarios over
many one-off cases. Location aliases/landmarks are covered only where they
exercise different risks: General Trias shorthand, Megamall landmark flow, SM
North precision, SLEX ambiguity, and Bukidnon typo/outside-area delivery.

## Current Scope

The pack intentionally does not validate order confirmation, payment collection,
or final booking actions. Runtime V7 remains a product/service discovery and
availability slice until the order domain is explicitly added.
