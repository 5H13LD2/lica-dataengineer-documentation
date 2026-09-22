# Runtime V7 Layered Health Runner

Last updated: 2026-09-16

The layered runner separates local deterministic contracts, read-only API health, and
metered conversation evaluation so operators can select the appropriate cost
and depth for pull requests, schedules, staging, and promotion.

It is an orchestrator, not a replacement for the underlying pytest suites or
the promotion-health evaluator. Every run writes a versioned UTF-8 summary and
one log per subprocess layer before returning its exit status.

## Layers

| Layer | Cost class | What it proves |
|---|---|---|
| `deterministic-core` | Local/no intended metered calls | Focused provider, endpoint, tracked-action, evaluator, and schema contracts |
| `deterministic-intent-observability` | Local/no intended metered calls | Moderate/High rules, tag and handoff behavior, analytical qualification shape, and trace/event schemas |
| `deterministic-full` | Local/no intended metered calls | Complete local repository regression suite |
| `api-core` | External API/no LLM | `/health` and `/gulong/health`, release identity, environment, and shallow runtime configuration |
| `api-commerce` | External API/no LLM | Product search, payment and transaction catalogs, partners, and schedules |
| `api-channel-reads` | External API/no LLM | ManyChat message-history and profile reads, including tag/custom-field shape |
| `api-dependencies` | External API/no LLM | Aggregate of all commerce and channel-read dependency probes |
| `model-hydrated-history` | Metered | One authenticated, return-only tester turn proving deployed ManyChat loader -> hydration -> model-path integration for an allowlisted synthetic account |
| `model-initial` | Metered | Three deployed customer-correctness sentinels |
| `model-in-depth` | Metered | Promotion matrix, tracked journeys, technical health, and four data-derived size+brand progression checks through planned Moderate qualification |
| `model-complete` | Metered | Full pre-verified scenario and operational-funnel contracts plus required compatible core baseline |

`model-complete` currently has stronger approval requirements but uses the
same checked-in scenario corpus as promotion. It must not be described as a
larger exhaustive corpus until additional rotating cases are checked in.

## Profiles

- `pr-no-cost`: focused deterministic plus intent/observability contracts; the
  selected tests contain no intended external/model calls, but hard egress
  isolation remains a CI responsibility.
- `daily-no-llm`: core, commerce, and channel-read APIs. These make real HTTP
  requests and may consume provider or infrastructure quota.
- `pre-staging`: full deterministic, both API layers, one protected hydrated-
  history turn, and initial model smoke.
- `pre-live`: full deterministic, both API layers, one protected hydrated-
  history turn, and the in-depth model matrix.
- `complete`: full deterministic, both API layers, and the complete automated
  promotion gate with a compatible baseline. Core, operational-funnel, and
  hydrated-history token budgets are enforced independently and also reported
  as one combined consumption total.

Use repeated `--layer` values to override the selected profile. External API
layers require `--allow-external-apis`; metered layers independently require
`--allow-metered-models`.

Model-backed child evidence is accepted only from the single matrix directory
created for that layer. The runner recomputes the score and binds the child
tier, run-directory name, base URL, release, Git SHA, environment, and required
baseline flag to the outer invocation; it does not trust a stored derived
green status or the newest unrelated artifact.

Model scenarios run serially by default (`--model-workers 1`). This measures
the customer-path latency without making a one-CPU staging revision contend
with the evaluator itself. Use a higher worker count only for an explicitly
separate concurrency/load-health run; do not substitute that stress result for
the semantic promotion gate.

```powershell
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONUTF8="1"
# Load FOLLOWUP_WEBHOOK_TOKEN through a secret-safe local mechanism before a
# profile containing model-hydrated-history. Never put its value on the CLI.

# Zero-LLM pull-request gate.
python scripts/runtime_v7_layered_health_runner.py --profile pr-no-cost

# Inspect a profile without running anything.
python scripts/runtime_v7_layered_health_runner.py --profile complete --dry-run

# Read-only scheduled API health.
python scripts/runtime_v7_layered_health_runner.py `
  --profile daily-no-llm `
  --allow-external-apis `
  --base-url <candidate-url> `
  --api-contracts <approved-contracts.json> `
  --expected-release <release> `
  --expected-git-sha <sha> `
  --expected-environment staging

# Explicitly metered initial gate.
python scripts/runtime_v7_layered_health_runner.py `
  --profile pre-staging `
  --allow-external-apis `
  --allow-metered-models `
  --base-url <candidate-url> `
  --expected-release <release> `
  --expected-git-sha <sha> `
  --expected-environment staging `
  --hydrated-history-user-id 4843256405786522 `
  --hydrated-history-auth-env FOLLOWUP_WEBHOOK_TOKEN `
  --hydrated-history-max-latency-ms 95000 `
  --max-core-model-tokens 2000000 `
  --max-operational-funnel-tokens 1200000 `
  --max-hydrated-history-tokens 100000
```

The ordinary tester routes continue to disable ManyChat history retrieval.
`model-hydrated-history` uses the separate authenticated
`/gulong/v7/chat/tester/hydrated` route. That route accepts only a matching
ManyChat `user_id`/`channel_user_id` from
`RUNTIME_V7_TESTER_HISTORY_USER_ALLOWLIST`, rejects request-supplied history
and reset, uses isolated tester storage, disables analytics and profile fetch,
and forces return-only delivery. Its artifact retains only release identity,
hydration status/counts, model usage totals, and latency—not response text,
  transcripts, authorization material, cookies, or headers.

The protected route reports `delivery_mode=return_only` as an ingress contract,
not as an optional echo from the delivery provider. Repeated runs use a fresh
synthetic provider message ID; cache reuse is valid only when that exact ID is
already present, so a new repeated phrase still exercises live hydration.

## Read-only API contracts

`configs/runtime_v7_health_api_contracts.example.json` documents the probe
shape. Copy it to an environment-specific, secret-free contract and enable
only probes with reviewed expected values.

The current public commerce responses use these root shapes: product search
and payment catalog are objects with a non-empty `data` array; installation
partners and transaction types are root arrays; installation slots are an
object with a `sched` array. Keep environment-specific contracts aligned to
the observed API version instead of copying an assumed common envelope.

Each dependency probe declares:

- a stable `id` and component;
- GET, or POST explicitly declared `read_only`;
- URL, query, and optional JSON body;
- secret values through `$ENV:VARIABLE_NAME` references;
- expected HTTP statuses, root type, required paths, exact stable values,
  field types, non-empty paths, and a latency ceiling.

The aggregate dependency layer fails closed unless enabled probes cover product
search, payment methods, transaction types, installation partners, installation
slots, ManyChat messages, and ManyChat profile. The commerce and channel-read
layers require only their own subset, so they can be scheduled independently.
Channel-read probes must use a dedicated synthetic ManyChat contact. Do not
substitute a customer contact merely to make the aggregate dependency profile
green; until such an identity is configured, report that layer as blocked.
Tags and custom fields are checked as profile response fields.
Response bodies and secret headers are never written to the health artifact.
Message delivery, tag/custom-field writes, and note creation are covered only
by deterministic adapter/runtime tests in the local layers; they are not live
endpoint-health claims.

Every configured component is restricted to a reviewed method/path allowlist,
after environment variables are resolved. Each probe must declare a real
schema/value assertion and a positive latency ceiling; redirects are not
followed. Mutation-like paths for tags, custom fields, notes, message delivery,
orders, bookings, and payment creation are rejected before network access. The
contract still requires operator review because a client cannot prove a remote
endpoint is side-effect-free from its URL alone. A future staging-
only side-effect canary must use a dedicated synthetic contact, explicit
authorization, readback, cleanup, and its own layer; it must not be hidden in a
read-only or daily profile.

## Moderate/High and observability boundary

The no-LLM intent/observability layer validates deterministic qualification,
tag priority, handoff-note construction, analytical qualification identity,
and analytics event schemas using local fixtures and fakes.

The in-depth deployed journey additionally requires `Moderate Intent` and
`High Intent` triggers plus a countable Moderate analytical record with schema,
rule version, deterministic decision mode, a 24-hex qualification event ID,
and non-empty event/idempotency identity bound to the tracked action. Return-only execution still suppresses actual ManyChat tag/note
mutation.

The in-depth and complete layers also run four realistic, privacy-safe
size+brand journeys: typed city shorthand, guided province-to-city selection,
contact fallback after location uncertainty, and an already-complete negative
control. They score the customer-visible response produced before delivery,
canonical customer-owned signal capture, and the planned Moderate payload
before persistence. Return-only delivery is intentional and does not weaken
these pre-delivery contracts.

Core technical totals remain comparable with the historical baseline. The
approved hard caps are `2,000,000` core-matrix tokens, `1,200,000`
operational-funnel tokens, and `100,000` hydrated-history tokens. Each bucket
fails independently. `metered_usage.combined` discloses aggregate consumption
without comparing additive workloads with the historical core cap. CLI values
may lower these caps but cannot raise them. The legacy
`--max-total-model-tokens` option maps only to the core cap.

Neither layer requires or proves that analytics rows landed in BigQuery. A separate
read-only persistence/freshness layer remains deferred to the dedicated
BigQuery session because it needs bounded bytes, source freshness, exact table
grains, and reconciliation with official `gulong_reporting`/`gulong_core`
Moderate/High definitions.

## Scheduling recommendation

- Per pull request: `pr-no-cost`.
- Daily per deployed environment: `daily-no-llm` after approving the exact API
  contract file.
- Before staging promotion: `pre-staging` with explicit metered opt-in.
- Before live/VM promotion: `pre-live` with an exact target identity and
  compatible baseline. The child matrix score is recomputed by the layered
  runner; a stored derived green status is not trusted.
- Weekly or before a high-risk release: `complete` after the corpus and
  thresholds have been tuned.

Every run remains under the selected gitignored local output root. The model
matrix emits a checksummed private bundle and can produce a separate redacted
external-review bundle. Private immutable Cloud Storage publication is the
durable target but is not yet performed automatically; see
`RUNTIME_V7_PROMOTION_HEALTH_EVALUATOR.md`.

Scheduling and email delivery are not implemented by this milestone. First run
the profiles manually and tune expected values, latency ceilings, model-call
budgets, and false-positive behavior.
