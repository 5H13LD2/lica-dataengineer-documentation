# VM Cloud SQL Phase 2J Runtime Parity Hardening Report - 2026-07-09

## Scope

Phase 2J hardens Runtime V7 Cloud SQL parity before any Cloud SQL read flip.
It does not change model-facing conversation hydration order and does not make
Cloud SQL authoritative for ManyChat history.

The deployed changes:

- keep BigQuery analytics writes and BQ fallback behavior intact;
- keep Cloud SQL runtime analytics dual-write enabled;
- fix Cloud SQL JSONB writes for schema-declared JSON fields that contain
  compact scalar values;
- improve ManyChat Cloud SQL compare summaries by excluding runtime-local
  synthetic assistant message ids from the Cloud SQL coverage denominator.

Real numeric ManyChat message-id gaps remain visible as `partial` or
`current_missing_in_cloudsql`.

## Code Change

Branch:

- `fix/runtime-v7-phase2j-cloudsql-parity`

Commit:

- `4dca6f4 Harden VM CloudSQL parity logging`

Deploy branch:

- `feature/runtime-v7-vm-cloudsql-shadow` fast-forwarded to `4dca6f4`

Image:

- `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:4dca6f4-phase2j-parity-20260709`
- digest: `sha256:0d0058058f2f903dc9331c8f78be092256c8aa67da695c1f736be3f4f61e2b71`

Cloud Build:

- build id: `33119888-5f92-45e4-88d1-46eb79a75acf`
- status: `SUCCESS`

## Local Validation

Commands:

- `python -m py_compile runtime/storage/postgres_analytics_writer.py runtime_v7/manychat_cloudsql_reader.py runtime_v7/api_runtime.py`
  - result: passed
- `python -m pytest test/test_analytics_gateway.py test/test_manychat_cloudsql_reader.py -q`
  - result: `15 passed`
- `python -m pytest $(rg --files test | rg 'test_runtime_v7') -q`
  - result: `650 passed`

## No-Traffic Candidate

Candidate container:

- name: `gulong-chatbot-runtime-phase2j-candidate`
- network mode: `host`
- port: `18082`
- delivery mode override: `return_only`
- ManyChat tag writes override: disabled

Health checks:

- `http://127.0.0.1:18082/health` -> HTTP `200`
- `http://127.0.0.1:18082/gulong/health` -> HTTP `200`
- release: `4dca6f4-phase2j-parity-20260709`
- git sha: `4dca6f4`

Candidate smoke:

- request id: `req_24b34cc4d1af4d8f92a385d51a4ab790`
- delivery result: `skipped`, reason `return_only`
- BigQuery and Cloud SQL matched:
  - `debug_log`: `1/1`
  - `request_state_log`: `1/1`
  - `request_attempt_log`: `1/1`
  - `turn_trace_log`: `1/1`
  - `turn_fact_log`: `1/1`
  - `llm_span_log`: `3/3`
  - `tool_call_log`: `1/1`
- Candidate logs showed `0` Postgres analytics write failures.

The candidate container was removed after live deployment.

## Live Deployment

Live VM container replaced:

- container: `gulong-chatbot-runtime-shadow`
- started: `2026-07-09 15:28` Manila time
- image:
  `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:4dca6f4-phase2j-parity-20260709`
- release: `4dca6f4-phase2j-parity-20260709`
- git sha: `4dca6f4`

VM metadata was updated so a VM restart recreates this image and release
metadata.

Rollback container retained:

- `gulong-chatbot-runtime-shadow-pre-phase2j-20260709T0728Z`
- image:
  `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:5d7401f-phase2i-read-compare-20260709`

Public health after deployment:

- `https://chatbot-runtime.34.87.10.106.sslip.io/health` -> HTTP `200`
- `https://chatbot-runtime.34.87.10.106.sslip.io/gulong/health` -> HTTP `200`

## Live Verification

Public return-only smoke used the configured edge-auth header and did not print
the token.

- request id: `req_81818f891a5244b8b3f35af13701a201`
- delivery result: `skipped`, reason `return_only`
- BigQuery and Cloud SQL matched:
  - `debug_log`: `1/1`
  - `request_state_log`: `1/1`
  - `request_attempt_log`: `1/1`
  - `turn_trace_log`: `1/1`
  - `turn_fact_log`: `1/1`
  - `llm_span_log`: `3/3`
  - `tool_call_log`: `1/1`
- Live logs after the swap showed:
  - Postgres analytics write failures: `0`
  - Cloud SQL compare reads: `success`

Operational guardrails after deployment:

- VM health endpoints were green for runtime, manychat-utils, and chat-analysis.
- Cloud Tasks queues were empty:
  - `gulong-manychat-message-events`
  - `gulong-manychat-user-info`
  - `cs-routing-reconcile`
  - `chat-analysis-shadow-async`
- Cloud Run leakage for migrated paths in the last 30 minutes:
  - `manychat-utils`: `0` `/v1/ingestion/*` or `/v2/assign*` hits
  - `lica-ai-platform`: `0` entries
- BigQuery job guardrail in the last 30 minutes:
  - `pipeline_logs` MERGE jobs: `0`
  - total MERGE billed: `0.762 GiB`

## Remaining Read-Flip Gate

Cloud SQL reads remain compare-only. The latest monitoring still shows
`cloudsql_empty` and some numeric current-message gaps for real ManyChat users,
which means Cloud SQL is healthy but not yet complete enough to become the
authoritative ManyChat history source.

The next phase should focus on:

- distinguishing expected runtime synthetic ids from true ManyChat coverage
  gaps in monitoring;
- backfilling or repairing users with no Cloud SQL raw/message rows;
- measuring numeric current-message lag after manychat-utils ingestion catches
  up;
- keeping BigQuery as fallback until coverage is stable.

## Rollback

If runtime errors or Cloud SQL write failures appear:

1. Stop the Phase 2J container:
   `sudo docker rm -f gulong-chatbot-runtime-shadow`
2. Restore the retained Phase 2I container:
   `sudo docker rename gulong-chatbot-runtime-shadow-pre-phase2j-20260709T0728Z gulong-chatbot-runtime-shadow`
3. Start it:
   `sudo docker start gulong-chatbot-runtime-shadow`
4. Revert `shadow_services_json.chatbot_runtime.image` to
   `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:5d7401f-phase2i-read-compare-20260709`.
5. Revert `shadow_services_json.chatbot_runtime.env.RELEASE_VERSION` to
   `5d7401f-phase2i-read-compare-20260709` and `GIT_SHA` to `5d7401f`.
6. Recheck public health, one return-only smoke, BigQuery / Cloud SQL runtime
   parity, Cloud Tasks queues, Cloud Run leakage, and BigQuery MERGE jobs.
