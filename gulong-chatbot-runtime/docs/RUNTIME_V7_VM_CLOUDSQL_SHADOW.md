# Runtime V7 VM + Cloud SQL Shadow Runbook

## Goal

Run Runtime V7 on the Gulong platform VM with Cloud SQL-backed runtime state
before any live ManyChat canary. This runbook stops before customer-facing
traffic movement.

## Pre-Canary Boundary

Allowed:

- Deploy the runtime container on the VM.
- Use `RUNTIME_DELIVERY_MODE=return_only`.
- Use `RUNTIME_V7_APPLY_MANYCHAT_TAGS=0`.
- Use tester/manual requests.
- Verify Cloud SQL session and idempotency writes.

Not allowed in this phase:

- No live ManyChat canary traffic.
- No `send_content` delivery mode for broad traffic.
- No automatic tag writes.
- No random routing of the same user between Cloud Run/Firestore and
  VM/Cloud SQL.

## VM Environment

Required for Cloud SQL state:

```text
RUNTIME_SESSION_STORE_PROVIDER=postgres
RUNTIME_IDEMPOTENCY_STORE_PROVIDER=postgres
RUNTIME_POSTGRES_DSN=<Secret Manager value>
RUNTIME_POSTGRES_SCHEMA=runtime_shadow
RUNTIME_POSTGRES_ENSURE_TABLES=true
```

Required for BigQuery + Cloud SQL analytics dual-write on VM-served traffic:

```text
RUNTIME_ANALYTICS_ENABLED=true
RUNTIME_ANALYTICS_WRITER_PROVIDER=dual
RUNTIME_ANALYTICS_POSTGRES_ENABLED=true
RUNTIME_ANALYTICS_POSTGRES_SCHEMA=runtime_shadow
RUNTIME_ANALYTICS_POSTGRES_ENSURE_TABLES=true
RUNTIME_ANALYTICS_POSTGRES_FAIL_OPEN=true
```

Required shadow safety flags:

```text
STATUS=staging
SERVICE_ENVIRONMENT=shadow
BU=gulong
RUNTIME_GENERATION=v7
RUNTIME_DELIVERY_MODE=return_only
RUNTIME_V7_APPLY_MANYCHAT_TAGS=0
RUNTIME_V7_FETCH_MANYCHAT_MESSAGES=1
IDEMPOTENCY_ON=1
SESSION_CAS_ON=1
```

The Cloud Run services continue to use the checked-in JSON defaults unless
these VM-only environment variables are set.

## Expected Cloud SQL Tables

The runtime creates these tables if `RUNTIME_POSTGRES_ENSURE_TABLES=true`:

```text
runtime_shadow.users_kv
runtime_shadow.sessions_kv
runtime_shadow.idempotency_kv
```

All payloads are compact JSONB documents keyed by runtime identifiers. This is
intentionally different from BigQuery analytics tables; Cloud SQL owns hot
state, while BigQuery remains an optional audit/reporting sink.

Runtime analytics parity tables are defined in:

```text
docs/sql/runtime_cloudsql_analytics.sql
```

These tables mirror the current BigQuery analytics schemas and are written only
when the VM selects the `dual` analytics writer.

## Manual Smoke

Use tester first:

```powershell
$body = @{
  user_id = "vm_shadow_test_1"
  user_text = "Hi, may 185/65R15 kayo?"
  return_logs = 1
  save_analytics = 0
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://chatbot-runtime.34.87.10.106.sslip.io/gulong/chat/tester" `
  -ContentType "application/json" `
  -Body $body
```

Then use non-tester with return-only:

```powershell
$body = @{
  user_id = "vm_shadow_state_test_1"
  user_text = "Need tires for Vios"
  message_id = "vm_shadow_msg_1"
  idempotency_key = "vm_shadow_msg_1"
  delivery_mode = "return_only"
  return_logs = 1
  save_analytics = 0
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://chatbot-runtime.34.87.10.106.sslip.io/gulong/chat" `
  -ContentType "application/json" `
  -Body $body
```

Expected:

- `status=success`.
- `delivery_result.status=skipped`.
- `delivery_result.reason=return_only`.
- Cloud SQL has rows for the non-tester `user_id`.
- No ManyChat customer reply is sent.

## Canary Readiness Checklist

- VM health endpoint is green.
- Runtime container remains stable after repeated tester and non-tester
  return-only requests.
- Cloud SQL writes are visible in `runtime_shadow.users_kv`,
  `runtime_shadow.sessions_kv`, and `runtime_shadow.idempotency_kv`.
- Duplicate idempotency requests replay or report in-progress instead of
  reprocessing.
- No customer delivery occurs while `RUNTIME_DELIVERY_MODE=return_only`.
- VM CPU, memory, disk, and Cloud SQL CPU/storage remain within budget.

## Reversion Before Canary

No live traffic is moved in this phase. Reversion is:

```text
Stop or disable the chatbot_runtime VM container.
Remove the chatbot_runtime service entry from Terraform if needed.
Leave Cloud Run unchanged.
```
