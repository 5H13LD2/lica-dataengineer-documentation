# Runtime V7 Follow-Up Production Safety

Last updated: 2026-08-01

## Runtime Shape

```text
ManyChat trigger
  -> authenticated follow-up endpoint
  -> fresh ManyChat transcript/profile/tags
  -> customer recovery or proactive route
  -> one proactive model call
  -> deterministic validation and rendering
  -> sending ledger transition
  -> idempotent ManyChat delivery
  -> Firestore/Cloud SQL state plus BigQuery monitoring
```

Cloud Run is the staging service. It is return-only by default. The VM is the
only customer-facing production runtime. Both environments must run the same
approved commit/image before VM promotion.

## Human CS Handoff Notes

An explicit human-takeover request now uses the typed
`request_human_handoff` runtime action. The runtime persists
`human_handoff_state.status=requested`, asks ManyChat to apply `Stop Chatbot`,
and creates a note headed `Human Handoff Requested`. This records a request;
it is not proof that a human was assigned or connected. The durable requested
state is also a later-chat and proactive-follow-up hard stop, including when
profile tag hydration is delayed. Resumption requires clearing/resetting the
handoff state through the controlled session/flow path; customer text is not
keyword-matched to bypass the stop.

When Runtime V7 first applies Moderate or High Intent, it creates one compact
ManyChat note for the human CS agent. The note is deliberately operational:

```text
Gulong.ph CS Handoff | High Intent
Tire: 225/55R19 | MICHELIN
Product: MICHELIN 225/55R19 PRIMACY SUV+ 99V
Qty / total: 4 tires | PHP 31,800.00
Service: Installation | Baguio
Schedule: Jul 29 - 12:00 PM (preferred)
Payment: Pay Later | Balance: BPI 6-mos Installment (0% interest)
Pending: contact number
```

Only available lines are shown. The note does not copy the raw latest message,
long dates, intent rationale, last actions, or suggested replies. Commercial
and checkout lines come from deterministic order readiness and validated
selection state rather than assistant transcript text.

## Endpoint Contract

Routes:

- `POST /gulong/v7/followup`: server-controlled delivery.
- `POST /gulong/v7/followup/tester`: always return-only.

Both routes require:

```text
Authorization: Bearer <FOLLOWUP_WEBHOOK_TOKEN>
```

`X-Gulong-Shadow-Token` is an edge-routing credential and is not a substitute
for this application-level bearer token.

Production request fields:

```json
{
  "user_id": "<manychat subscriber id>",
  "channel_event_id": "<manychat event id>",
  "channel_event_ts": "<event timestamp>",
  "idempotency_key": "<stable trigger key>",
  "cadence": "first"
}
```

`cadence` is `first`, `second`, or `nurture`. A shared ManyChat timer flow may
send `auto` together with the authoritative `last_interaction` timestamp as
`channel_event_ts`; runtime resolves the 1-hour layer to `first` and the
12-hour layer to `second` before idempotency and timing validation. Invalid
timestamps fail before runtime I/O. Deprecated profile, transcript, force,
logging, delivery, and agent fields are accepted temporarily but ignored and
audited. ManyChat must not send secrets in the request body.

The shared ManyChat flow should map Contact ID to `user_id`, and map the Last
Interaction system field to `channel_event_id`, `channel_event_ts`, and
`idempotency_key`, with root-level `cadence` set to `auto`. Profile/name fields
may remain during migration but are ignored in favor of fresh hydration.

Authentication rejects a request before runtime I/O. A missing server token is
a `503`; a missing or incorrect bearer token is a `401`.

## Server Configuration

Required:

```text
FOLLOWUP_WEBHOOK_TOKEN=<Secret Manager injection>
FOLLOWUP_SEND_ENABLED=false
FOLLOWUP_SEND_USER_ALLOWLIST=
FOLLOWUP_SEND_CANARY_PERCENT=0
RUNTIME_V7_FOLLOWUP_TEMPERATURE=0.1
FOLLOWUP_EXPECT_SEND_ENABLED=false
RUNTIME_V7_FOLLOWUP_TRANSPORT_RETRIES=1
RUNTIME_V7_FOLLOWUP_TRANSPORT_RETRY_BACKOFF_S=0.75
RUNTIME_V7_FETCH_MANYCHAT_MESSAGES=1
RUNTIME_V7_SESSION_LOCK_ENABLED=1
IDEMPOTENCY_ON=1
```

The follow-up service forces fresh ManyChat profile and transcript reads even
when the normal-chat profile-fetch setting is disabled for performance.

`FOLLOWUP_SEND_ENABLED` is read only from process environment. No request field
can override it. Admission order is:

1. Global send flag must be true.
2. A non-empty allowlist admits only listed IDs.
3. Without an allowlist, deterministic `sha256(user_id) % 100` admission uses
   `FOLLOWUP_SEND_CANARY_PERCENT`.
4. Zero percent means no sends.

Cloud Run normally uses `FOLLOWUP_SEND_ENABLED=false`. A staging trial may use
`true` only with the trial user allowlist and must return to false after the
trial. VM production uses `SERVICE_ENVIRONMENT=live` and `RUNTIME_HOST=vm-live`.
An all-user VM release uses an empty allowlist with
`FOLLOWUP_SEND_CANARY_PERCENT=100` only after the published ManyChat request
passes authentication, event identity, idempotency, first-cadence, and
second-cadence probes.

## Routing And Safety

Both `Stop Chatbot` and `Stop Followup` suppress the endpoint. A human message
after the relevant customer message or an active human assignment also
suppresses delivery.

Customer-last requests up to 24 hours old enter normal Runtime V7 chat. Runtime
uses the original ManyChat message ID, or a marked stable synthetic digest when
the ID is absent. Delivered inbound events suppress. Confirmed failures may
redeliver stored output. Unknown outcomes require a fresh transcript: a matching
assistant-response hash reconciles the send; unavailable or ambiguous evidence
suppresses and alerts.

Return-only customer recovery stores a replayable rendered response in the
inbound-event ledger, but does not append that undelivered assistant output to
session messages, channel-history cache, product state, or tag state. A legacy
`completed` event without explicit delivery success is ambiguous, not delivered.

Assistant-last requests use proactive evaluation. The model receives recent
conversation, evidence-linked facts, lead qualification, eligible focus fields,
delivered product cards, allowed benefits, cadence, and bounded prior outcomes.
Raw AWM and Background Signal objects are not prompt sections.

The model returns strategy only. Deterministic code owns exact benefit text and
the single CTA. It rejects:

- A focus outside the closed eligible set.
- Brand focus after a customer brand preference is present.
- A lead-in containing a question, request, second field, or commercial claim.
- Any benefit ref not supplied by runtime evidence.
- Installation/schedule progression without selected-product evidence.
- Empty or over-limit rendered output.

Buy 3 Get 1 is rendered only when the delivered product card contains the
promotion and the current `/promo_brands` response includes that card's brand.
Promo lookup failure removes that benefit; it never broadens eligibility.

One logical planning call may retry one transient provider transport failure
such as HTTP 429/503 or a timeout. Authentication, request/schema, and other
non-transient failures are never retried. Transport attempts and retry events
remain visible in the turn trace and normalized follow-up metadata.

## Durable State

`strategy_state.runtime_v7.followup.version=2` stores up to 20 attempts:

```text
attempt_id, trigger_key, conversation_anchor_id, cadence, route,
action, stance, focus_field, status, reason, message_hash, evidence_refs,
benefit_refs, validation status/reasons, timestamps, delivery result
```

`sending` is saved before ManyChat. Only confirmed success becomes `sent`.
Return-only remains `evaluated`. Failed and invalid attempts retry after the
configured cooldown and do not consume a focus field. Unknown delivery blocks
until transcript reconciliation. A new customer message creates a new anchor.
Timing-window and unresolved-delivery evaluations do not consume a cadence or
restart retry cooldown. Transient profile/transcript, persistence, and freshness
failures are retryable evaluations. Existing version-2 records stored as
`suppressed` are treated the same way when their recorded reason is transient.
Customer stance, model, stop-tag, human-takeover, domain, and completion
suppressions remain durable.

`product_presentation_history` stores the exact rendered cards, presentation
and observation refs, delivery result, delivery time, and expiry. Only
successfully delivered, unexpired presentations can ground a follow-up.

## Regression Gate

The redacted July corpus is
`test/fixtures/runtime_v7_followup_july_corpus.json`. It contains 95
July-onward cases: all nine rolled-back-release incidents, 15 explicit safety
scenarios, and 71 bounded/redacted live-transcript cases.

Run deterministic tests:

```powershell
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONUTF8="1"
python -m pytest test -q
```

Run every corpus case three times against the configured production model:

```powershell
python scripts/evaluate_followup_july_corpus.py `
  --corpus test/fixtures/runtime_v7_followup_july_corpus.json `
  --output tmp/followup_v2/july_full_eval_3x.json `
  --runs 3 `
  --concurrency 6 `
  --env-file configs/.env
```

The evaluator blocks on model errors, structured-output failures above 1%,
semantic validation failures above 2%, or any customer-visible invariant
failure. Release also requires zero unsupported claims, multi-field CTAs,
preference contradictions, stop/human sends, return-only-as-sent records, and
duplicate delivery.

Latest local gate (2026-07-20 on exact commit `441dcc5`): `834 passed` in the
full repository suite and `654 passed` in the focused follow-up, ingress,
renderer, observation, promo-action, gateway, analytics, and persistence
integration suite. The final three-run production-model corpus completed 285
evaluations and 258 logical model calls with zero invalid structured outputs,
one safely suppressed semantic validation failure (`0.39%`), zero model errors,
zero transport retries, and zero failed customer-visible invariants, using
545,040 total tokens. The rejected plan contained an ungrounded brand lead-in
and produced no message. The retained artifact is
`tmp/followup_v2/july_full_eval_3x_441dcc5_final.json`.

Pre-final Cloud Run probes on the ancestor merge `8a1ac8a` verified 401 rejection
for both unauthenticated routes, send-disabled health metadata, return-only
state, stable duplicate replay, stop-tag suppression, human-message takeover,
and active-human-assignment suppression. Those probes exposed the transient
cadence-consumption issue fixed by `c7a8ff4`; final staging evidence must use a
descendant containing the retry fix `16d5f03`.

## Release Sequence

1. Merge the tested branch to `product` and deploy Cloud Run staging with send
   disabled.
2. Verify `/health` reports staging, expected host, send disabled, token
   configured, and no follow-up configuration alerts.
3. Call the authenticated tester endpoint for selected real users. Compare the
   returned case, model plan, validation, response, Firestore state, and
   `followup_event_log` without sending.
4. Run the full July corpus against the real model and retain the artifact.
5. For a trial ManyChat send, enable Cloud Run only for the trial user ID. Test
   stop tags, profile/transcript refresh, a confirmed send, return-only state,
   duplicate HTTP retry, delivery failure, and first-to-second field rotation.
6. Restore Cloud Run to send disabled.
7. Promote the approved commit to `main`, build the exact production image,
   and deploy that SHA to the VM with only the trial user allowlisted.
8. Verify one real first cadence and one real second cadence on the VM. Do not
   broaden admission before the stated 24-hour observation and volume gates.
9. Expand VM deterministic canary to 10%, 50%, and 100% only after each gate's
   delivery volume, monitoring, and 24-hour hold pass.

Do not create or use a customer-facing Cloud Run live service for this path.

## Monitoring And Rollback

`followup_event_log` records route, action, stance, focus, validation,
evidence, attempt/delivery status, token usage, latency, release SHA, service
environment, runtime host, and transport retry count.

Alert immediately on:

- `unsupported_commercial_claim_blocked`.
- `followup_duplicate_send_violation`.
- `followup_stop_tag_send_violation`.
- `followup_human_takeover_send_violation`.
- `followup_delivery_unknown`.
- `customer_recovery_delivery_ambiguous`.
- Customer recovery of an already delivered event.
- VM send unexpectedly disabled or Cloud Run unexpectedly enabled.
- Validation failure rate above 2%.
- Delivery failure rate above 5%.
- Invalid structured output above 1%.

Monitor reply and requested-field recovery within 24/72 hours, Moderate Intent
conversion, deferred/negative responses, unsubscribes, and near misses by field.

Emergency rollback is configuration-only:

```text
FOLLOWUP_SEND_ENABLED=false
FOLLOWUP_SEND_CANARY_PERCENT=0
FOLLOWUP_SEND_USER_ALLOWLIST=
```

Restart/redeploy the VM with those server values, then verify `/gulong/health`
reports send disabled. Do not use a request parameter as a kill switch.
