# Gulong Chatbot Runtime

Clean repository for the deployable Gulong.PH chatbot runtime service.

The repository name intentionally does not include a runtime version. Runtime generations are release metadata and environment config (`RUNTIME_GENERATION=v7`), not repository identity. The current deployable generation is Runtime V7.

## Runtime Contract

- FastAPI entrypoint: `app:app`
- Runtime route: `POST /gulong/chat`
- Tester route: `POST /gulong/chat/tester`
- Compatibility routes: `POST /gulong/v7/chat`, `POST /gulong/v7/chat/tester`
- Follow-up routes: `POST /gulong/v7/followup`, `POST /gulong/v7/followup/tester`
- Staging-only authenticated persistence diagnostic:
  `POST /gulong/v7/session-persistence/tester`
- Staging-only authenticated representation comparison:
  `POST /gulong/v7/session-persistence/representation-tester`
- Health routes: `GET /health`, `GET /gulong/health`
- Cloud Run staging service: `gulong-chatbot-runtime-staging`
- Customer-facing live host: Gulong runtime VM (`RUNTIME_HOST=vm-live`)

Runtime V7 interprets free-form customer requests and chooses ordinary
read-only tools, response structure, transitions, and the next useful CTA
through the main model and structured final composer. Phrase matching does not
classify free-text product, location, payment, comparison, or sales-stage
intent. Deterministic runtime code owns provider facts, exact rendered
controls, validated guided-action tokens, delivery mechanics, side effects,
and hard submission safety. Product/service/order prompt and tool surfaces are
selected from normalized signals and trusted refs; initially unclassified
turns retain a bounded general capability-recovery tool rather than loading the
full product domain by default. Evaluator scenarios and their expected contracts
receive one-time CS-perspective verification; routine runs are automated and
do not require per-run human approval.

Published promo search and gallery delivery share the same Manila-date validity
boundary, so expired campaigns cannot be ranked, described as current, or
rendered. Every successful reviewed promo search carries a stable evidence ref
bound to its catalog version and normalized search scope. This lets the model
state a verified empty-search result without inventing a promo; individual
offer mechanics still require their separate allowed promo refs. Direct
requests for alternatives can therefore be answered truthfully when the exact
reviewed scope returned none: that is a complete scoped result, not permission
to invent another offer and not a global claim about the full catalog.
The reviewed campaign catalog and exact product search remain separate fact
providers. A campaign no-match cannot deny quantity, bundle, voucher,
discount, price, or SKU promos that only an exact-size product result can
verify; without that product evidence, Runtime keeps the exact applicability
and price pending and asks for the tire size.
The promo lookup contract also carries the model's presentation decision. When
the model requests `gallery_if_available`, Runtime validates provider-issued
promo refs and completes the deterministic gallery in the same execution round;
  it does not spend another model round selecting refs it already has. Main-loop,
composer, and deterministic claim validation share one compact promo response
contract, while full retrieval diagnostics remain available only in the trace
artifact.
This keeps the integrated promo/product feature without repeating full campaign
payloads or relaxing claim validation.
When an unmatched-brand promo search returns no verified offer and Runtime has
ordinary price-category controls, the provider-owned result layer uses only the
typed scoped result and labels those controls as non-promo shopping choices.
This prevents either normal composition or fail-closed repair from widening the
commercial claim. Direct contact and delivery/order-policy questions remain
model-led, but customer-visible business facts must come from their runtime-
owned contact or FAQ/policy tool evidence. The main model can request
independent payment lookups for compound questions; active checkout metadata
resolves exact method, bank, term, and brand-eligibility facts. A model-
authorized delivery-policy question carries a typed delivery scope into the
authored FAQ provider. That scope can establish the general delivery process
through a stable FAQ evidence ref, but never exact-address serviceability or a
delivery date. The structured composer and typed claim contracts validate the
answer in the serving path. Older second-pass semantic decision and audit
models remain only where an explicit offline evaluator still uses them; they
do not classify or rewrite a normal customer turn.

Answer-only authored FAQ and business-contact turns use a compact mode of the
same final composer. The current answer goal, trusted evidence, recent
conversation continuity, and voice contract remain; stale lead gaps, product or
service progression, active working memory, and generated drafts do not compete
with the requested answer. Mixed FAQ plus product/service/order turns retain the
full packet and normal progression behavior.

Multi-SKU product discovery renders a complete long-form price list followed by
the matching image gallery and tracked `ps1|...` choices. Gallery subtitles are
supplementary, not the sole price presentation. One image-backed displayed-card
set owns the text order, gallery order, and click allowlist. Missing or rejected
images are replaced from the already fetched eligible ranked pool when possible;
otherwise only that product is excluded from both surfaces. The same exact list
is suppressed only when its v2 list-plus-gallery presentation was previously
delivered successfully and the pending step is still SKU selection.

Payment-policy lookups accept named methods only from typed customer-backed
signals. Free-form customer messages are never interpolated as provider names;
unsupported typed methods are answered with a short positive list of current
checkout alternatives when available. The typed plan distinguishes concrete
providers/methods from open categories such as e-wallets or installment
options. Each category becomes a provider-backed catalog scope rather than an
unsupported named provider, and can be filtered by Pay Now/Pay Later when the
customer asks. Local wallet aliases
match only the payment rail and benign qualifiers; distinct credit, loan, card,
or installment products retain their complete name for provider validation.

Durable product/order guidance that is absent from the legacy FAQ corpus is
owned by Runtime V7 policy entries. DOT guidance explains how to read the
sidewall week/year code without promising a batch date, and formal-quotation
guidance progresses a company request to CS preparation without treating a
draft quote, availability, tax, total, or order state as confirmed.

## Repository Layout

- `apps/api`: Cloud Run/FastAPI API surface.
- `runtime_v7`: Runtime V7 orchestration, tools, state, rendering, and telemetry.
- `runtime`: shared gateways, storage, configuration, and analytics plumbing used by V7.
- `runtime/bu/gulong/config`: business-unit runtime config.
- `test`: Runtime V7 regression and contract tests.
- `cloudbuild.yaml`: parameterized CI/CD pipeline for staging and live.

There are no legacy generation directories in this repository. The shared `runtime` package is infrastructure only; deployable chatbot behavior lives in `runtime_v7`.

## Branch Model

- `product`: collaborative integration branch. Pushes deploy to `gulong-chatbot-runtime-staging`.
- `main`: approved production source. Build the exact approved image from this
  branch and deploy that SHA to the VM.

Use pull requests into `product` for feature work. Promote to `main` only after
Cloud Run staging verification. Cloud Run is not a customer-facing live host.

## Local Test

```powershell
python -m pip install -r requirements.txt
python -m pytest test -q
```

Before promotion, run the deployed tester-route matrix against the versioned,
pre-verified scenario contract. The evaluator enforces return-only delivery,
canonical provider/tool contracts, identity-linked model-to-execution scope
preservation, bounded dedupe evidence, technical health, and exact release
metadata, corpus completeness, telemetry completeness, and evidence integrity;
it does not send to ManyChat. Declare deployment-specific promo and
guided-surface availability with `--feature-expectations`; missing controls are
never silently treated as unavailable without authoritative empty-surface
evidence. Promotion/full runs also exercise reviewed data-derived size+brand
progression through rendered location/contact collection, canonical
customer-owned capture, and the planned Moderate qualification before
persistence. Actual delivery, BigQuery landing, abandonment, and linked booking
conversion remain separate observational checks. See
`docs/RUNTIME_V7_PROMOTION_HEALTH_EVALUATOR.md`.

Use `scripts/runtime_v7_layered_health_runner.py` when checks need to be
selected by cost and purpose. It provides no-LLM pull-request/full-regression
layers, separately opted-in read-only commerce/channel API contracts, and
independently opted-in initial, in-depth, or complete model gates. Promotion
profiles also include one authenticated, allowlisted ManyChat-history hydration
turn whose redacted usage counts toward the shared model budget. See
`docs/RUNTIME_V7_LAYERED_HEALTH_RUNNER.md`.

## Local Run

```powershell
$env:STATUS="staging"
$env:SERVICE_ENVIRONMENT="local"
$env:BU="gulong"
$env:RUNTIME_GENERATION="v7"
$env:RUNTIME_DELIVERY_MODE="return_only"
python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

## CI/CD

Cloud Build uses `cloudbuild.yaml`.

Trigger substitutions:

- staging/product:
  - `_SERVICE_NAME=gulong-chatbot-runtime-staging`
  - `_SERVICE_ENVIRONMENT=staging`
  - `_STATUS=staging`
  - `_RUNTIME_DELIVERY_MODE=return_only`
  - `_RUNTIME_V7_APPLY_MANYCHAT_TAGS=0`
  - `_RUNTIME_V7_FIRESTORE_STRATEGY_STATE_FORMAT=canonical_json_v1`
  - `_MAX_INSTANCES=20`

The checked-in persistence default is canonical JSON after the dual-reader and
both migration directions were verified on staging. An explicit trigger
substitution may set `_RUNTIME_V7_FIRESTORE_STRATEGY_STATE_FORMAT=nested_map_v1`
for rollback, but only on a dual-reader revision; a pre-bridge runtime cannot
read sessions already migrated by a successful full save.

The checked-in Cloud Build deployment is used for return-only Cloud Run
staging. Production VM promotion uses the exact image SHA approved on `main`.
See `docs/RELEASE.md` and
`docs/RUNTIME_V7_FOLLOWUP_PRODUCTION_SAFETY.md`.

Images are pushed to:

```text
asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-chatbot-runtime/gulong-chatbot-runtime
```

Secrets are read from Secret Manager during Cloud Run deploy. Do not commit `.env` or service-account JSON files.
