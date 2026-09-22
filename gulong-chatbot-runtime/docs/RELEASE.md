# Release Process

This repository uses branch-based releases.

Staging deployments and explicit promotion decisions are recorded in
`RELEASE_HISTORY.md`.

## New Staging Release

1. Merge feature work into `product`.
2. Push `product`.
3. Cloud Build deploys `gulong-chatbot-runtime-staging`.
4. Verify:
   - `GET /health`
   - `GET /gulong/health`
   - a tester request to `POST /gulong/chat/tester`
   - BigQuery rows in the staging analytics dataset (`STATUS=staging` maps to `gulong_chatbot_dev`)

## New VM Live Release

1. Confirm staging behavior and logs.
2. Merge `product` into `main`.
3. Push `main`.
4. Build/tag the exact `main` SHA in Artifact Registry.
5. Deploy that image SHA to the customer-facing VM. Start with the trial-user
   follow-up allowlist; Cloud Run remains return-only.
6. Verify:
   - `GET /health`
   - `GET /gulong/health`
   - `service_environment=live` and `runtime_host=vm-live`
   - image/release SHA matches the approved staging commit
   - authenticated follow-up tester and trial-user delivery evidence
   - BigQuery rows in `gulong-chatbot-459723.gulong_chatbot_live`

Follow the 10%, 50%, and 100% deterministic-contact canary and 24-hour hold
gates in `RUNTIME_V7_FOLLOWUP_PRODUCTION_SAFETY.md`.

## Rollback

Disable follow-up sending first:

```text
FOLLOWUP_SEND_ENABLED=false
FOLLOWUP_SEND_CANARY_PERCENT=0
```

Then redeploy the prior known-good image SHA to the VM. Do not force-push
`main`; keep release history auditable.
