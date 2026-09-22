# VM Cloud SQL Phase 2I Runtime Read-Compare Report - 2026-07-09

## Scope

Phase 2I adds compare-only Cloud SQL reads for Runtime V7 ManyChat conversation
history. It does not flip runtime reads to Cloud SQL and does not alter the
model-facing conversation hydration order.

Current authoritative order remains:

1. provided request history, when explicitly supplied,
2. Firestore channel-history cache,
3. live ManyChat `loadMessages` refresh when the cache does not contain the
   current inbound message,
4. session/runtime state fallback.

The new Cloud SQL path is observability-only. It reads
`manychat_shadow.messages`, compares compact message keys/counts against the
hydrated runtime history, and logs a bounded summary without message bodies.

## Code Change

Branch:

- `feature/runtime-v7-phase2i-read-compare-vm`

Commits:

- `2d512f0 Add ManyChat CloudSQL read-compare for Runtime V7`
- `5d7401f Add sampling guard for ManyChat CloudSQL compare`

Deploy branch:

- `feature/runtime-v7-vm-cloudsql-shadow` fast-forwarded to `5d7401f`

Image:

- `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:5d7401f-phase2i-read-compare-20260709`
- digest: `sha256:2cefa22e34af4bb6870836e1f007026c012346c8689b601fc0d2af0d98764a37`

Cloud Build:

- build id: `8c427002-d02d-41c2-a808-153cddbf2c5b`
- status: `SUCCESS`

Implementation:

- Added `runtime_v7/manychat_cloudsql_reader.py`.
- Added env-gated Runtime V7 hydration compare hook.
- Added deterministic request sampling:
  - `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_ENABLED`
  - `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_SAMPLE_RATE`
  - `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_LIMIT`
- Cloud SQL read config reuses the existing runtime Postgres DSN unless
  `RUNTIME_V7_MANYCHAT_CLOUDSQL_DSN` is explicitly provided.
- The reader validates schema/table identifiers, uses bounded `LIMIT`, and
  applies short connect/statement timeouts.

## Validation

Local tests:

- `python -m pytest test/test_manychat_cloudsql_reader.py test/test_runtime_v7_ingress_trace.py -q`
  - result: `37 passed`
- `python -m pytest test -q`
  - result: `670 passed`

Live schema/access check:

- The runtime VM container can read:
  - `manychat_shadow.messages`
  - `manychat_shadow.users_current`
  - `manychat_shadow.agent_assignment_events`
  - `manychat_shadow.agent_assignments_current`

## No-Traffic Candidate

Candidate container:

- name: `gulong-chatbot-runtime-phase2i-candidate`
- port: `18082`
- delivery mode override: `return_only`
- ManyChat tag writes override: disabled
- compare enabled with sample rate `1`

Health checks:

- `http://127.0.0.1:18082/health` -> HTTP `200`
- `http://127.0.0.1:18082/gulong/health` -> HTTP `200`
- release: `5d7401f-phase2i-read-compare-20260709`
- git sha: `5d7401f`

Candidate smoke:

- request id: `req_867e0b471e854b05aee355c56c77bd27`
- delivery result: `skipped`, reason `return_only`
- compare log:
  - `cloudsql_status=success`
  - `cloudsql_latency_ms=42`
  - `cloudsql_row_count=2`
  - `match_status=current_missing_in_cloudsql`

The mismatch status was expected for the synthetic smoke because the current
probe message was not a real ManyChat message in Cloud SQL. The important
candidate signal was that the read path returned non-empty rows, logged only a
summary, and did not affect response delivery.

The candidate container was removed after validation.

## Live Deployment

Live VM container replaced:

- container: `gulong-chatbot-runtime-shadow`
- started: `2026-07-09 05:27:32` Manila time
- image:
  `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:5d7401f-phase2i-read-compare-20260709`
- release: `5d7401f-phase2i-read-compare-20260709`
- git sha: `5d7401f`

Live compare configuration:

- `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_ENABLED=1`
- `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_SAMPLE_RATE=0.25`
- `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_LIMIT=20`

VM metadata was updated so a VM restart recreates this image and these compare
flags.

Rollback container retained:

- `gulong-chatbot-runtime-shadow-pre-phase2i-20260708T212732Z`
- image:
  `asia-southeast1-docker.pkg.dev/gulong-chatbot-459723/gulong-platform-shadow/chatbot-runtime:d0a7c55-phase2h-append-only-20260709`

Public health after deployment:

- `https://chatbot-runtime.34.87.10.106.sslip.io/health` -> HTTP `200`
- `https://chatbot-runtime.34.87.10.106.sslip.io/gulong/health` -> HTTP `200`

## Live Verification

Local non-tester return-only smoke:

- request id: `req_33a8e13cb73a41c3b71830cd5159bb47`
- delivery result: `skipped`, reason `return_only`
- BigQuery `gulong_chatbot_live` rows matched Cloud SQL `runtime_shadow`:
  - `debug_log`: `1/1`
  - `request_state_log`: `1/1`
  - `request_attempt_log`: `1/1`
  - `turn_trace_log`: `1/1`
  - `turn_fact_log`: `1/1`
  - `llm_span_log`: `1/1`
  - `tool_call_log`: `0/0`

Sampled live compare logs appeared after deployment:

- `cloudsql_status=success`
- observed `cloudsql_latency_ms` around `42-50`
- sampled statuses included `cloudsql_empty` for contacts without mirrored
  Cloud SQL message rows in the queried window.

Cost and traffic guardrails after live start:

- actual runtime/pipeline BigQuery MERGE jobs since `2026-07-08T21:27:32Z`:
  `0`
- expected scheduled ManyChat refresh MERGEs since `2026-07-08T21:27:32Z`:
  `0` at the check time
- Cloud Run leakage for ingestion, assign, and dataUpdate paths in the last
  hour: `0` matched entries
- Cloud Tasks final check:
  - `gulong-manychat-message-events`: empty
  - `gulong-manychat-user-info`: empty

Operational health:

- `gulong-chatbot-runtime-shadow`: up on Phase 2I image
- `gulong-manychat-utils-shadow`: up
- `gulong-chat-analysis-shadow`: up
- public `manychat-utils` `/readyz`: HTTP `200`
- public `chat-analysis` `/healthz`: HTTP `200`

## Guardrails

- Do not use the compare summary as model context.
- Do not flip Cloud SQL reads authoritative until compare windows show stable
  coverage for the required ManyChat users/messages.
- Keep sample rate bounded during live soak. Increase only if latency/error
  guardrails remain clean.
- Treat `cloudsql_empty` as a parity/backfill signal, not a runtime failure.
- Any Cloud SQL read failure must remain fail-open and must not affect delivery.

## Rollback

If latency, errors, or Cloud SQL pressure appear:

1. Disable compare without image rollback by recreating the live container with:
   `RUNTIME_V7_MANYCHAT_CLOUDSQL_COMPARE_ENABLED=0`.
2. If code rollback is required, stop the Phase 2I container:
   `sudo docker rm -f gulong-chatbot-runtime-shadow`
3. Restore the retained Phase 2H container:
   `sudo docker rename gulong-chatbot-runtime-shadow-pre-phase2i-20260708T212732Z gulong-chatbot-runtime-shadow`
4. Start it:
   `sudo docker start gulong-chatbot-runtime-shadow`
5. Revert VM metadata image/release/git sha and remove the Phase 2I compare
   env flags.
6. Recheck `/health`, `/gulong/health`, one return-only smoke, and BigQuery /
   Cloud SQL runtime-log parity.

## Next Phase

Soak Phase 2I at the bounded sample rate and review:

- compare log coverage by `match_status`,
- Cloud SQL latency distribution,
- runtime error logs,
- BigQuery MERGE guardrails,
- Cloud Tasks queue drain,
- Cloud Run leakage.

Only after the sampled read-compare data is stable should the next phase define
which Cloud SQL fallback reads can become authoritative.
