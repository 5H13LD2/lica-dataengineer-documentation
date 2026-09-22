# Runtime V7 Production Observability Note

Status: active Runtime V7 observability direction.

As of 2026-07-20, follow-up and customer-turn recovery operations also write a
normalized `followup_event_log`. It records route, cadence, action, stance,
focus field, validation result/reasons, evidence refs, attempt/delivery status,
tokens, latency, release SHA, service environment, and runtime host. This table
is the primary safety/rollout surface for the follow-up feature; full turn traces
remain the diagnostic drill-down.

Production Runtime V7 persists one full debug payload and the normalized
request, attempt, turn, LLM-span, tool-call, and interaction rows described
below. It also emits a compact searchable Cloud Logging line. The normalized
tables are the current reporting and diagnosis contract; the older
`assistant_log`, `tool_output_log`, and `error_log` stopped receiving V7 rows
and must not be used as current-health indicators.

## Goals

- Trace every customer turn end to end with stable identifiers.
- Diagnose bad responses from user/session id down to model spans, tool calls,
  context packet, memory state, and renderer output.
- Attribute token usage, cache usage, latency, and estimated cost by runtime
  component.
- Make budget/time/tool-loop aborts visible without blocking response delivery.
- Preserve grounded business-data evidence without dumping large upstream
  payloads or sensitive operational details.

## Required Identifiers

Every production log surface should include:

- `trace_id`
- `session_id`
- `user_id`
- `channel_user_id`
- `user_id_source`
- `turn_id`
- `runtime_version`
- `prompt_version`
- `tool_policy_version`
- `renderer_version`
- `slot_spec_version`
- Asia/Manila timestamps using `YYYY-MM-DD HH:MM:SS`

Firestore remains authoritative for user/session state. BigQuery or other log
sinks are audit and analytics surfaces only, and log writes must be best-effort
and non-blocking.

After a complete turn has been emitted, Runtime V7 immediately dispatches each
normalized per-table batch in the background. This preserves all spans/events
from the turn in one table batch, avoids adding warehouse I/O to customer
latency, and narrows the VM/container-replacement loss window that existed with
the former five-second age timer. It applies to
`request_state_log`, `request_attempt_log`, `turn_trace_log`,
`turn_fact_log`, `llm_span_log`, and `tool_call_log` rows when a request
finishes, as well as `interaction_event_log` when applicable.

Runtime analytics BigQuery writes are append-only. Rows keep deterministic
`row_id` values for downstream dedupe and cross-store parity, but request
workers must not pass BigQuery merge keys for these audit tables. On the VM,
the Cloud SQL `runtime_shadow` mirror may still enforce `row_id` uniqueness;
parity checks should compare unique row ids and separately watch for unexpected
duplicate physical appends in BigQuery.

## Production Log Surfaces

### current_debug_trace_payload

One JSON payload per Runtime V7 API turn, persisted through the analytics
gateway debug-log path when `save_analytics=1`.

Live Runtime V7 rows currently land in
`gulong-chatbot-459723.gulong_chatbot_live.debug_log`. The legacy
`gulong-chatbot-459723.gulong_chatbot` dataset is not the live V7 trace
surface.

Capture:

- request metadata, including `user_id`, `channel_user_id`, `message_id`,
  `idempotency_key`, `request_time`, `delivery_mode`, `reset`, and channel
  metadata
- version-neutral `turn_trace`
- full V7 `turn_record`, including component spans, model usage/cost/cache
  summaries, context snapshots, tool calls/results, renderer refs, and state
  updates when present
- rendered response, content messages, image/payment metadata, delivery result,
  and tagging result

This is intentionally a debug payload, not the final reporting schema. It gives
operators enough evidence to reconstruct a bad live turn immediately while the
team decides which fields deserve dedicated flattened tables.

### current_cloud_logging_summary

One compact app log line per Runtime V7 API turn:

- log marker: `runtime_v7_turn_trace`
- `request_id`
- `trace_id`
- `session_id`
- `user_id`
- compact JSON summary with status, model usage/cost, delivery status, tool
  names, and state-save result

This is the first lookup surface when Cloud Run request logs only show HTTP
status/latency and not the component-level trace.

### v_runtime_v7_turns

Current deduplicated customer-turn view built from `turn_trace_log`. It exposes
the user text, rendered response text, delivery status, release/host metadata,
full response/surface payload, tool/model summaries, state snapshots, and an
`input_mode` split between `free_text` and `guided_action`.

`v_runtime_v7_free_text_turns` is its bounded free-text review surface. The
view definition is versioned in
`docs/sql/runtime_v7_normalized_warehouse_views.sql`.

### llm_span_log

One row per model call through the production `LLMGateway`.

Capture:

- component, such as main tool loop, background-signal extraction, Active
  Working Memory update, FAQ retrieval helper, image evidence extraction, or
  retry
- provider and model
- latency milliseconds
- input tokens
- cached input tokens
- uncached input tokens
- output tokens
- reasoning tokens, when available
- cache hit rate
- estimated model cost
- timeout seconds
- retry attempt and retry reason
- finish reason
- error type and safe fallback metadata
- compact prompt/context refs, not full giant prompts by default

Final-composer spans keep `component="final_composer"` so existing component
time series remain continuous. Their `meta` adds:

- `attempt_kind`: `initial`, `format_retry`, `contract_repair`,
  `repair_format_retry`, or `semantic_scope_repair`
- `repair_reason` on non-initial attempts: `invalid_response_format`,
  `contract_violations`, `invalid_repair_response_format`, or
  `semantic_scope_violations`
- `violation_types`: sorted, deduplicated typed contract failures when a
  contract or semantic-scope violation caused the repair

These labels are analytics-only. They must not become runtime decision input.
Use `JSON_VALUE(meta, '$.attempt_kind')` and
`JSON_VALUE(meta, '$.repair_reason')` to group repair call rate, token usage,
and latency. Use `JSON_QUERY_ARRAY(meta, '$.violation_types')` only for bounded
cause drill-down.

### tool_call_log

One row per tool call attempt.

Capture:

- tool name
- sanitized args
- `args_hash`
- `idempotency_key`
- latency milliseconds
- status
- error type
- timeout seconds
- retry attempt and retry reason
- upstream source metadata

`v_runtime_v7_tool_calls` is the deduplicated current tool surface. Compact
output/evidence and deterministic presentation details are available through
`summary_context`, `presentation`, and the corresponding `turn_trace_log`
record. Do not store raw upstream payload dumps, supplier/base prices, private
payment details, private partner contact details, or exact partner addresses
unless the surface is explicitly approved for internal-only debugging.

### turn_trace_log

One row per turn context compilation.

Capture:

- selected capability profile
- selected domains
- exposed tools
- capability expansion/retry events
- compiled context summary
- Background Signals snapshot
- Missing Info snapshot
- Active Working Memory version/ref
- product/service/image/conversation evidence refs
- request time used for relative-date reasoning
- deterministic renderer refs

### state_signal_log

One row per normalized fact or signal update.

Capture:

- fact type
- raw value
- normalized value
- source, such as user text, human-agent message, image OCR, tool output, or
  memory refresh
- provenance/evidence ref
- confidence
- status
- `requires_validation`
- stale/conflict markers

Use `requires_validation` for facts that are useful for reasoning but should
still be confirmed or tool-validated before real-world actions.

### memory_log

One row per Active Working Memory update.

Capture:

- pre-update memory ref/version
- post-update memory ref/version
- extracted durable facts
- evidence refs used
- memory model usage/cost
- fallback reason, if the memory update failed
- whether the update incorporated human-agent messages, image evidence, tool
  observations, or customer corrections

Avoid storing a full raw transcript unless policy allows it. Prefer compact
memory and evidence refs.

### guard_event_log

One row per deterministic guard or runtime budget event.

Capture:

- guard code
- triggering condition
- enforced action
- component
- related tool/model span refs
- customer-safe fallback status

Expected codes include:

- model timeout
- request model-call budget exceeded
- scenario/turn tool-loop cap reached
- token budget exceeded
- estimated-cost budget exceeded
- untrusted price blocked
- TTL-expired price blocked
- order/payment/schedule readiness blocked
- deterministic card renderer inserted content
- response truncation or channel sanitation

### v_runtime_v7_errors

Current deduplicated error view combining structured turn errors and failed
tool calls. Request/delivery failures also remain in `request_attempt_log` and
`request_state_log`; pre-emitter exceptions remain in Cloud Logging.

### channel_delivery_log

One row per channel delivery attempt.

Capture:

- channel
- bubble count
- bubble sizes
- delivery status
- delivery latency
- truncation events
- channel API error type

## Budget Guardrails

Production runtime should enforce bounded execution:

- central model timeout config in `LLMGateway`, with default per-call max at or
  below 60 seconds unless explicitly overridden
- request-level model-call cap
- request-level tool-loop round cap
- request-level token budget
- request-level estimated-cost budget
- bounded retry policies with short backoff
- partial-span logging before abort whenever possible
- safe customer fallback when budgets/timeouts are hit

These guardrails should stop the runtime before the next model/tool call once a
budget is exceeded. They should not depend on prompt compliance.

## Cost Attribution

Track model cost by:

- runtime component
- provider
- model
- prompt/cache profile
- turn
- session
- runtime version

Token fields should split:

- uncached input tokens
- cached input tokens
- output tokens
- reasoning tokens, when available
- total tokens
- cache hit rate
- explicit context-cache state from `llm_span_log.meta.request_cache` and
  `llm_span_log.meta.cache_summary`

Cost estimates should state exclusions clearly. Likely exclusions include
context-cache storage, Google Search or Maps grounding, Geocoding API calls,
Gulong API calls, embedding calls without returned token usage, and failed
attempts where the provider returned no usage metadata.

Explicit Gemini context caching is disabled by default in production. Verify new
revisions by checking that `meta.cache_summary.explicit_cache_enabled` is false
for each LLM span and that `meta.request_cache.skipped_reason` is
`context_cache_disabled` for Gemini calls where cache metadata is present.

## Retrieval Flows

### Bad Response Investigation

1. Look up `v_runtime_v7_turns` by `user_id`, `session_id`, or timestamp.
2. Use `trace_id` or `request_id` to retrieve the raw `turn_trace_log`.
3. Inspect selected domains, exposed tools, context summary, Background
   Signals, Missing Info, and Active Working Memory refs.
4. Inspect `llm_span_log` for model calls, retries, latency, tokens, and
   finish/error reasons.
5. Inspect `v_runtime_v7_tool_calls` and the turn presentation/context fields
   for grounded business data.
6. Inspect `guard_event_log` for blocked or altered behavior.
7. Compare final bubbles against deterministic renderer refs and tool evidence.

### Cost Or Latency Spike

1. Aggregate `llm_span_log` by date, runtime version, component, provider, and
   model.
2. Compare model-call counts, token totals, cached/uncached input tokens, cache
   hit rate, latency percentiles, and estimated cost.
3. Join to `turn_trace_log` to identify domains, exposed tools, and retry or
   capability-expansion patterns.
4. Inspect `tool_call_log` for slow external APIs such as product, service,
   slots, geocoding, image evidence, or FAQ retrieval.

### Missing Tool Or Ungrounded Claim

1. Inspect selected domains and exposed tools in `turn_trace_log`.
2. Check whether the model requested a capability expansion.
3. Check whether the relevant tool call was made.
4. Inspect tool outputs and observation refs.
5. Inspect guard events for grounding blocks or retry caps.
6. If the tool was not exposed, inspect Background Signals, FAQ hints, image
   evidence, and memory facts used by capability compilation.

### Stale Memory Or Conflicting Context

1. Inspect `memory_log` pre/post versions.
2. Inspect `state_signal_log` for fact provenance, normalized values, stale
   markers, and conflicts.
3. Inspect `turn_trace_log` for which memory/signals were actually included in
   the prompt.
4. Compare tool observations and deterministic card refs with final bubbles.

## Implementation Shape

- Keep local live test-pack metrics as eval artifacts.
- Use the normalized views for routine reporting and the debug payload/raw
  normalized tables for drill-down.
- Keep logs small and structured.
- Use refs for bulky evidence.
- Keep logging best-effort and non-blocking.
- Do not let observability introduce new runtime decision authority.

## Operational Checks

- Run `docs/sql/runtime_v7_telemetry_health.sql` with a five-minute observation
  cutoff. Compare CloudSQL using the same Asia/Manila-local DATETIME bounds and
  distinct non-null `row_id`; a zero-lag or UTC-vs-Manila comparison is invalid.
- Use `docs/sql/runtime_v7_free_text_review.sql` for bounded adjacent-turn
  reviews. Do not replace semantic review with phrase matching.
- Keep CloudSQL `runtime_shadow` as the reconciliation source for the rare case
  where a process is replaced before a background BigQuery write completes.

## Retrieval Keywords

Runtime V7 production observability, `llm_span_log`, `tool_call_log`,
`tool_output_log`, cost attribution, token budgets, model-call budget, cache hit
rate, Active Working Memory, Background Signals, `trace_id`,
`requires_validation`, deterministic card renderer, guard events.
