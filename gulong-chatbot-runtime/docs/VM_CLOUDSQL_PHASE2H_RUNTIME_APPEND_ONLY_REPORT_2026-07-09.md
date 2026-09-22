# VM Cloud SQL Phase 2H Runtime Append-Only Report - 2026-07-09

## Scope

Phase 2H remediates the remaining runtime-observability BigQuery MERGE cost
identified after the `manychat-utils` VM migration phases. It does not change
chatbot response logic, ManyChat routing, session state semantics, or Cloud SQL
read paths.

Goal:

- Keep runtime analytics dual-write enabled.
- Keep BigQuery as an audit/reporting fallback.
- Keep Cloud SQL `runtime_shadow` parity writes enabled.
- Stop request-time BigQuery MERGE jobs for runtime observability log tables.

## Code Change

Branch:

- `feature/runtime-v7-phase2h-append-only-vm`

Commit:

- `d0a7c55 Make runtime analytics BigQuery writes append-only`

Image:

- `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:d0a7c55-phase2h-append-only-20260709`
- digest: `sha256:08474b473e38cca5ac62cb139251ce1cf43f3f37ba25d30a79f50f0814be35ab`

Cloud Build:

- build id: `3ea9abc5-2b91-48aa-9a5c-08d37eee06c1`
- status: `SUCCESS`

Implementation:

- `runtime/gateways/analytics_gateway.py` still materializes deterministic
  `row_id` values.
- The gateway now passes `key_columns=None` for runtime analytics BigQuery
  writes, so the BigQuery writer uses append ingestion instead of staging-table
  `MERGE`.
- The VM dual-writer path remains unchanged. The Postgres writer continues to
  enforce `row_id` uniqueness in `runtime_shadow`.

Parity implication:

- Normal parity checks should compare per-window unique `row_id` counts across
  BigQuery and Cloud SQL.
- BigQuery physical row counts should still be monitored for unexpected
  duplicate appends.

## Local Validation

Commands:

- `python -m pytest test/test_analytics_gateway.py test/test_runtime_v7_ingress_trace.py -q`
  - result: `41 passed`
- `python -m pytest test -q`
  - result: `665 passed`

## No-Traffic Candidate

Candidate container:

- name: `gulong-chatbot-runtime-phase2h-candidate`
- port: `18082`
- delivery mode override: `return_only`
- ManyChat tag writes override: disabled
- ManyChat message fetch override: disabled

Health checks:

- `http://127.0.0.1:18082/health` -> HTTP `200`
- `http://127.0.0.1:18082/gulong/health` -> HTTP `200`
- release: `d0a7c55-phase2h-append-only-20260709`
- git sha: `d0a7c55`

Candidate probe:

- request id: `req_10d1ab9b6de548f3a5178b4096453bbe`
- delivery result: `skipped`, reason `return_only`
- BigQuery dataset: `gulong_chatbot_dev`
- BigQuery rows:
  - `debug_log`: `1`, distinct `row_id` `1`
  - `request_state_log`: `1`, distinct `row_id` `1`
  - `request_attempt_log`: `1`, distinct `row_id` `1`
  - `turn_trace_log`: `1`, distinct `row_id` `1`
  - `turn_fact_log`: `1`, distinct `row_id` `1`
  - `llm_span_log`: `3`, distinct `row_id` `3`
  - `tool_call_log`: `1`, distinct `row_id` `1`
- Cloud SQL `runtime_shadow` rows matched exactly.
- BigQuery MERGE jobs against candidate `gulong_chatbot_dev.*_log` tables:
  `0`.

The candidate container was removed after live deployment.

## Live Deployment

Live VM container replaced:

- container: `gulong-chatbot-runtime-shadow`
- started: `2026-07-09 04:38:18` Manila time
- image:
  `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:d0a7c55-phase2h-append-only-20260709`
- release: `d0a7c55-phase2h-append-only-20260709`
- git sha: `d0a7c55`

VM metadata was updated so a VM restart recreates the Phase 2H image and
release metadata.

Rollback container retained:

- `gulong-chatbot-runtime-shadow-pre-phase2h-20260708T203808Z`
- image:
  `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:6704487-vm-bq-cloudsql-dual-20260630`

Public health after deployment:

- `https://chatbot-runtime.34.87.10.106.sslip.io/health` -> HTTP `200`
- `https://chatbot-runtime.34.87.10.106.sslip.io/gulong/health` -> HTTP `200`

## Live Verification

Return-only smoke:

- request id: `req_4ba5b923a3964cd9a00648e305daf2db`
- delivery result: `skipped`, reason `return_only`
- BigQuery dataset: `gulong_chatbot_live`
- Cloud SQL schema: `runtime_shadow`
- matched tables:
  - `debug_log`: `1/1`
  - `request_state_log`: `1/1`
  - `request_attempt_log`: `1/1`
  - `turn_trace_log`: `1/1`
  - `turn_fact_log`: `1/1`
  - `llm_span_log`: `1/1`
  - `tool_call_log`: `0/0` because the greeting probe did not call tools.

Real post-deploy customer turn:

- request id: `req_79669400e5504a39b87027aa460abd42`
- delivery result in runtime log: `success`
- BigQuery and Cloud SQL matched:
  - `debug_log`: `1/1`
  - `request_state_log`: `1/1`
  - `request_attempt_log`: `1/1`
  - `turn_trace_log`: `1/1`
  - `turn_fact_log`: `1/1`
  - `llm_span_log`: `1/1`
  - `tool_call_log`: `0/0`

Cost guardrails after live container start:

- runtime `gulong_chatbot_live.*_log` MERGE jobs since
  `2026-07-08T20:38:18Z`: `0`
- `manychat_data.pipeline_logs` MERGE jobs since `2026-07-08T20:38:18Z`: `0`

Operational guardrails:

- VM containers were up after deployment:
  - `gulong-chatbot-runtime-shadow`
  - `gulong-manychat-utils-shadow`
  - `gulong-chat-analysis-shadow`
  - `gulong-platform-edge`
- `manychat-utils` `/readyz`: HTTP `200`
- `chat-analysis` `/healthz`: HTTP `200`
- Cloud Tasks final check:
  - `gulong-manychat-message-events`: empty
  - `gulong-manychat-user-info`: empty
- Cloud Run leakage for ingestion, assign, and dataUpdate paths since the live
  runtime swap: `0` matched entries.

Runtime logs showed the expected `runtime_v7_turn_trace` lines for the smoke
and real customer turn. A LiteLLM async logging warning was observed after a
turn, but no application `ERROR`, traceback, analytics write failure, BigQuery
failure, or Postgres failure appeared in the sampled live logs.

## Rollback

If runtime errors or write parity issues appear:

1. Stop the Phase 2H container:
   `sudo docker rm -f gulong-chatbot-runtime-shadow`
2. Restore the retained previous container:
   `sudo docker rename gulong-chatbot-runtime-shadow-pre-phase2h-20260708T203808Z gulong-chatbot-runtime-shadow`
3. Start it:
   `sudo docker start gulong-chatbot-runtime-shadow`
4. Revert `shadow_services_json.chatbot_runtime.image` to
   `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:6704487-vm-bq-cloudsql-dual-20260630`.
5. Revert `shadow_services_json.chatbot_runtime.env.RELEASE_VERSION` to
   `6704487-vm-bq-cloudsql-dual` and remove or reset `GIT_SHA`.
6. Recheck `/health`, `/gulong/health`, one return-only smoke, and BigQuery /
   Cloud SQL parity.

## Next Phase

Proceed to Phase 2I only after continued monitoring confirms:

- runtime observability MERGE jobs remain at zero,
- BigQuery physical counts do not show unexpected duplicate appends,
- Cloud SQL `runtime_shadow` unique-row parity remains stable, and
- `manychat-utils` ingestion queues and Cloud Run leakage remain clean.

Phase 2I should be compare-only Cloud SQL read-path work. Do not flip reads
directly.
