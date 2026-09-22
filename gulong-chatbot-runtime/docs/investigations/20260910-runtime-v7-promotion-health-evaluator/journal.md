# Runtime V7 Promotion Health Evaluator

Investigation ID: `20260910-runtime-v7-promotion-health-evaluator`
Started: 2026-09-10T10:53:11+08:00
Status: release_gated

## Conclusion

The automated promotion-health evaluator is implemented, locally verified,
and exercised through a complete cohort against staging candidate `0e990e7`.
Customer-correctness, configured commerce dependencies, current channel reads,
and an exact compatible live baseline now have evidence. Contract
`2026-09-10.3` requires a bare store-location request to ask for the customer's
city/area and reserves the Makati address for an explicit Gulong.PH/head-office
question. The provisional ceilings remain 95-second p95 latency and 2,000,000
combined model tokens. Fresh inbound history is available, but its first exact
staging rerun exposed stale same-text cache reuse: a new provider event was
mistaken for the cached probe and ManyChat refresh was skipped. A general
provider-ID identity correction is locally green and awaits staging deployment.
This is not promotion approval; live Cloud Run and the VM remain unchanged. No
new per-run human approval is required.

## Ambiguous store-location contract correction

- The prior contract treated `location ng store?` as a direct business-address
  question. The user clarified that this wording should ask for the customer's
  location instead.
- The owning model policy now separates ambiguous store/branch lookup, explicit
  corporate address, and explicit installation/service area. The ambiguous
  path asks one free-form city/area question and forbids both unsolicited
  head-office facts and installation province choices.
- The evaluator now supports phrase-tolerant forbidden response facts. The
  ambiguous case fails on an unsolicited `1166 Chino Roces` address even if it
  also asks for the customer area; a separate explicit-address case requires
  the full reviewed address as a negative control.
- This correction is local only. A fresh model-backed run is required after
  deployment because prompt-contract tests establish instructions and scoring,
  not the model's rendered response.
- Local verification passed 70 focused evaluator/release tests and all 1,724
  repository tests. The consolidated all-domain prompt is 98,930 characters
  against its 99,000-character ceiling.

## Final staging gate update

- Cloud Build `cc7673d7-4e3a-480a-8383-4e4703a17bec` deployed exact runtime
  `0e990e7` as staging revision
  `gulong-chatbot-runtime-staging-00435-2b2` at 100% traffic. Both health
  routes identify staging and follow-up sending remains disabled.
- Core runtime health and all five configured read-only commerce dependencies
  passed. The supplied test account is now configured only in the gitignored
  read-only contract. Its public profile returned HTTP 200 with the required
  tags/custom-fields shape but took 10,362 ms against a 10,000 ms endpoint SLA.
  Message history returned HTTP 401 both through the redacted probe and the
  runtime's full-header loader, supporting stale or invalid browser-session
  credentials. No message, tag, field, or note mutation was attempted.
- The complete 15-case/3-journey cohort produced zero HTTP, runtime, or tool
  errors and 100% telemetry. Product promos, scoped promo negatives, delivery,
  business contact/address, compound payments, products, schedules, guided
  actions, and the tracked Moderate/High journey have passing focused evidence.
- The original `17/18` result was caused by an evaluator boundary that required
  hydrated Yokohama/Pay Later values in the model's pre-hydration BPI call.
  The corrected contract requires the authored BPI method before hydration and
  all three scoped fields at provider execution; a fresh deployed turn passed.
- The complete artifact measured p50/p95/max
  `34,037/91,788/113,040 ms`, 82 model calls, and `1,860,861` total tokens with
  `318,207` cache-read tokens. Those values are below the newly approved
  95-second p95 and 2-million-token hard limits, while p95 remains above the
  unchanged 45-second concern threshold. Offline rescoring correctly rejects
  the old immutable artifact because it embeds the former health policy and an
  older scenario-definition digest; a fresh run is required. A compatible
  `50e5975` baseline remains deferred.
- Live Cloud Run and VM were not changed. BigQuery, ManyChat mutation,
  scheduling, email, and durable GCS publication remain deferred.
- The revised boundary contract passed 39 focused tests and all 1,722
  repository tests. Equality at 95,000 ms and 2,000,000 tokens is allowed;
  values above either ceiling block.

## Evidence

- Clean candidate branch:
  `feat/runtime-v7-promotion-health-evaluator-20260910` at base `26cdbc6`.
- The deployed matrix now uses tester-only chat and tracked-action routes,
  enforces return-only/tag suppression, and blocks order/payment mutation
  tools.
- Four separate layers are reported: exact mechanical contracts, technical
  error/latency/token health, a disclosed structural CS proxy, and the complete
  seven-dimension human review.
- Commercial outcomes are checked against provider-owned run evidence. Tool
  arguments use canonical comparisons; delivery concepts allow equivalent
  phrasing instead of one reference sentence.
- Coverage is 14 varied single-turn cases and three multi-turn journeys; the
  cost-bounded smoke tier retains contact, delivery, and compound payment.
- Verification: 83 focused tests and 1,654 full-repository tests passed; the
  full run included all 1,575 collected Runtime V7 tests. Ruff checks and
  script import/help smoke passed.

## Tool-chain hardening update

- The two highest-risk payment cases now score pre-hydration model arguments,
  post-hydration provider executions, and dedupe disposition as one
  identity-linked chain. Missing identities, overwritten scopes, and required
  scopes that never reach a provider are mechanical failures.
- Equivalent duplicate calls may still reuse one matching provider result. A
  dedupe event fails only when the hydrated scope no longer matches the
  customer-backed model scope or the required logical scope has no real
  provider execution.
- The promotion tier now has 15 single-turn cases and three journeys. The new
  payment case reverses installment order, uses Michelin and Yokohama, and adds
  `6mos`/`3mos` shorthand plus a harmless typo. Eligibility remains provider-
  relative rather than hard-coded.
- Tester evidence now retains bounded model/execution call IDs, canonical
  arguments, and dedupe dispositions while excluding raw cache keys and free-
  form tool questions.
- Post-hardening verification passed 93 focused tests and all 1,660 repository
  tests, including all 1,581 collected Runtime V7 tests. Python compilation,
  Ruff, diff checks, and the runtime change audit also passed.

## Feature-surface contract update

- Each covered rendered surface now has an explicit environment expectation:
  required when enabled, N/A only when authoritative diagnostics prove it is
  unavailable, or forbidden when intentionally disabled. The profile is part
  of schema-v4 baseline compatibility.
- Promo Details and About Brand can report N/A only when the catalog tool
  exposes an explicit empty provider-owned `allowed_promo_refs` list. Missing
  scope diagnostics fail closed rather than masquerading as an empty catalog.
- The product journey now positively clicks and validates product, location,
  schedule, payment option, and payment method in sequence. It stops before
  order or payment mutation and verifies the two payment selections remain in
  order-readiness state.
- Checkout empty-surface diagnostics now disclose payment-option and payment-
  method catalog counts so each configurable surface can be assessed against
  the correct authoritative availability evidence.
- Verification passed 179 focused evaluator/release/choice-surface tests and
  all 1,668 repository tests, including all 1,589 collected Runtime V7 tests.

## Cost and operational impact

The final staging smoke made ten model calls and measured `152,879` total
tokens: `148,189` prompt, `4,690` completion, and `17,960` cache-read input
tokens. P50/p95/max response latency was `25,271/36,191/36,191 ms`. Monetary
cost remains explicitly unavailable because the deployed tester telemetry does
not expose priced per-model call records. No BigQuery query/write, live Cloud
Run or VM mutation, ManyChat delivery, email, or scheduled job occurred.

## Recommendation and gates

1. Refresh the non-secret alias backing the ManyChat browser session, then
   rerun both read-only channel contracts until message history passes and the
   profile is within its independent endpoint SLA.
2. Run the in-depth/complete pre-verified corpus against staging and an exact
   compatible `50e5975` baseline, then review deterministic failures and
   latency/token deltas.
3. Promote only if those automated gates classify the exact candidate as
   `ready_for_promotion`; repeat independently on the approved live Cloud Run
   candidate and VM alternate-port candidate, then rerun smoke after cutover.
4. Do not schedule or email reports until coverage and the revised provisional
   latency/token thresholds have been exercised by fresh repeated runs.

## Layered health-runner update

- Local checks, commerce API reads, channel API reads, and metered conversation
  evaluation can now be selected independently or through named profiles. API
  and model layers require separate explicit opt-ins.
- Local deterministic layers are labelled as having no intended metered calls;
  external API layers are separately labelled because they make real requests
  and may consume provider or infrastructure quota.
- Commerce coverage now requires product search, payment-method catalog,
  transaction types, installation partners, and installation slots. Channel
  reads require ManyChat messages and profile schema, including tag and custom-
  field shape.
- API probes validate the resolved URL against a component-specific method/path
  allowlist, require schema/value and latency contracts, reject redirects, and
  suppress response bodies and headers from artifacts. Actual message, tag,
  custom-field, and note mutations remain outside these read-only layers.
- The deployed journey's Moderate analytical record now requires the exact
  24-hex event ID format and non-empty event/idempotency identity bound to the
  synthetic tracked action.
- Final local verification passed 193 focused tests, 318 core profile tests,
  159 intent/observability profile tests, and all 1,680 repository tests. The
  full collection included all 1,601 Runtime V7 tests.
- Status remains `release_gated`: commerce contracts passed, but channel reads
  are not green and no compatible-baseline in-depth run, BigQuery work,
  ManyChat mutation, live Cloud Run, or VM result was produced.

## Staging execution and integrated defect closure

- Candidate `5b227d8` passed all `1,698` repository tests, changed-file Ruff,
  focused positive and negative controls, diff checks, and the strict release
  audit.
- Regional Cloud Build `d32db396-6cec-42a6-96b1-e7f370bd38ae` succeeded and
  produced immutable digest
  `sha256:8ac369ae981a0cc0ce415b3e03006d5652a31f5c47705de6908a89423e146621`.
  Staging revision `gulong-chatbot-runtime-staging-00434-k6m` serves the exact
  SHA at 100% in return-only mode; the health endpoint reports staging identity
  with follow-up sending disabled.
- Earlier smoke iterations exposed evidence-contract defects, equivalent-claim
  over-counting, and then the real missing-brand hydration defect. The final
  fix recovers a missing method/brand/option only when the customer-authored
  compound scope maps uniquely; ambiguous same-method/two-brand input remains
  unresolved. Provider-derived typed claims are recorded after accepted
  composition rather than inferred from generated prose.
- Final run `20260910_165210_818246` passed `3/3` cases and `21/21` CS
  structural checks with zero HTTP, runtime, tool, or artifact-integrity
  failures. The evidence digest is
  `90b69879c5816d3cbe7be5bc7494753595d9eabb01c1976ce2b5e828472378d0`.
- Results currently remain in the local gitignored evaluator tree. The private
  immutable GCS path is documented, but the uploader and scheduled email
  delivery are intentionally not implemented yet.

## 2026-09-11 hydration gate and compatible baseline

The prior channel-read blocker is closed. Current Secret Manager-backed
ManyChat message and profile reads both returned HTTP 200 for synthetic account
`4843256405786522`. A new protected tester route now covers the integration gap
left by ordinary history-disabled tester scenarios: authenticated and
allowlisted message loading flows through runtime conversation hydration and
the model path while delivery remains return-only. Only scalar hydration
counts/status and numeric usage enter the layered artifact.

The hardened path passed 76 focused endpoint, layered-runner, and ingress tests;
all 1,732 repository tests passed, as did Ruff, compilation, diff checks, and
the strict behavioral release audit. The complete profiles combine this
sentinel's metered usage with matrix usage under the approved 2,000,000-token
budget and enforce the 95,000 ms hydrated-turn limit.

A fresh scenario-contract `2026-09-10.3` baseline against exact live
`50e5975` completed with integrity-valid evidence: 11 of 19 cases/journeys,
67 model calls, 1,520,097 total tokens, p95 90,296 ms, zero HTTP errors, and two
runtime errors. Its red correctness result is expected historical behavior;
the artifact is retained for compatible candidate comparison, not approval.

Candidate `9aa1c46` is now on staging revision
`gulong-chatbot-runtime-staging-00436-kg4` at 100% after successful Cloud Build
`3a1682e7-6eb5-4b74-9ac5-414e482faab1`. Core, commerce, and both channel-read
layers are green. The protected turn reached the exact revision and refreshed
ManyChat successfully, but loaded zero model-facing messages because the test
account's last interaction was August 10, outside the production 30-day
window. Status therefore remains `release_gated`; smoke and complete candidate
evaluation are intentionally held until the account has a fresh message and
the hydration sentinel is green. Live Cloud Run and VM remain unchanged.

Fresh inbound verification subsequently returned six bounded messages. The
next exact `9aa1c46` staging probe still failed because its new synthetic
provider ID carried the same text as an earlier probe; the refresh check fell
back from the unmatched ID to text equality, selected the stale cache entry,
and did not call ManyChat. The runtime now treats an available provider message
ID as the sole cache identity: exact duplicate IDs reuse cache, new IDs refresh
even when their text repeats, and no-ID requests remain refresh-first. The
protected response also states its ingress-enforced `return_only` mode. This
general correction passed 77 focused tests, all 1,733 repository tests, Ruff,
and compilation. Staging redeployment and a fresh sentinel remain required.

## 2026-09-11 exact `1a073c8` complete-gate findings

Normal product-branch deployment produced staging revision
`gulong-chatbot-runtime-staging-00439-lsb` from Cloud Build
`9dceca98-79b9-4568-ba67-3eeca62edb39`, image digest
`sha256:9391e28df09eb5a5f001dfe6abfbb6e92428e3963a14e5779488f3db5bf19bb2`.
The revision served exact `1a073c8` at 100% in staging return-only mode. The
protected hydration turn refreshed six ManyChat messages into 11 model-facing
messages with HTTP 200, 32,655 ms latency, two model calls, and 39,570 tokens.

The first complete run was blocked by two upstream `ServiceUnavailableError`
responses and one cold root-health request; both failed model scenarios passed
an immediate serial 2/2 recheck, and warmed root health returned in 394 ms. A
second complete run passed 17/19 model cases with zero HTTP/tool errors, p95
85,834 ms, and 1,547,557 matrix tokens. Its Vredestein failure was another
confirmed upstream `ServiceUnavailableError`; the other failure was a
customer-visible resend response after an empty structured model result.

The second run also exposed invalid aggregate baseline math. Exact live
`50e5975` stopped the primary guided journey after two actions while staging
completed all five, so raw subtraction compared three restored actions against
zero baseline tokens. Matched `case/action/occurrence` rescoring covered 18 of
21 baseline actions (85.71%) and measured staging at 1.76% fewer tokens; the
30.28% aggregate observed increase remains separately disclosed. The evaluator
now requires at least 80% matched valid-usage coverage and never zero-fills
unmatched or missing-usage actions.

The resend response revealed a general retry-budget defect: staging's
`max_tool_rounds=1` allowed the runtime to queue `empty_model_output_retry` but
the loop exited before the replacement call. Empty/no-renderable recovery now
receives one explicit bounded replacement-round allowance. The regression uses
the deployed one-round setting and proves exactly two calls and a grounded
answer without phrase-specific routing. Full local verification passes 1,741
tests, changed-file Ruff, compilation, and diff checks. A new staging build and
fresh exact-target complete gate remain required; live Cloud Run and VM remain
unchanged.

Staging `1412ada` subsequently passed both health routes in 443/365 ms and the
protected hydration sentinel with six loaded messages, 11 model-facing
messages, 30,563 ms latency, two calls, and 39,423 tokens. Before spending on
another complete matrix, the repeated upstream 503 evidence was traced to the
main harness leaving the gateway's existing transient retry support disabled.
The main path now defaults to one retry with 0.75-second backoff, bounded to at
most two by configuration and to the existing shared tester provider-call
ceiling. Retry classification remains limited to transport/timeouts, 408/429,
and retryable 5xx; semantic failures are not retried. All 1,742 repository tests
pass with Ruff, compilation, and diff checks. This follow-up requires one more
normal staging deployment before the complete gate.

Exact `2f7bdb1` then passed deterministic-full, core API, commerce API,
ManyChat channel-read, and protected hydrated-history layers. The complete
matrix had zero HTTP, runtime, and tool errors, used 1,767,963 tokens across all
metered layers, and observed p95 model-case latency of 70,555 ms. Nineteen
candidate actions matched 21 valid-usage live-baseline actions, with a 1.23%
matched token delta; the 42.10% aggregate workload delta remains disclosed.

The gate remained red at 18/19 because `explicit_head_office_address`
intermittently returned the neutral resend response. Trace evidence showed one
successful model call, no tool call, no renderable response units, and no
replacement attempt. Existing recovery recognized empty objects and fenced
JSON but omitted an unfenced raw response-unit array. The generalized fix now
classifies an array beginning with an object as JSON-like contract output and
grants the existing one bounded replacement attempt. Bracketed customer prose
such as renderer-owned brand menus remains on its specialized recovery path.
The focused recovery and negative-control tests pass, and the full repository
passes all 1,743 tests with Ruff and diff checks. A normal staging deployment
and exact targeted plus complete-gate reruns are still required.

Normal product-branch Cloud Build
`b1cfcc7c-32bc-4b54-bb1b-3938ef59ed50` deployed exact `85fbf79` to
`gulong-chatbot-runtime-staging-00442-fzv` at 100%, image digest
`sha256:e50b59d9acf049c889a507c128a0f97ef6080ae9a9c4dd95331e2d07a4aaf30c`.
Both health routes passed in 288/55 ms and reported the exact staging identity.
The targeted address scenario then passed with HTTP 200, canonical address,
`get_business_contact`, final composer usage, three model calls, and 50,622
tokens.

Complete run `20260911_171434_420906` passed all 19 scenarios, all deterministic
tests, core and commerce APIs, and protected history hydration with zero
HTTP/runtime/tool errors and 100% telemetry. Matrix p95 was 83,476 ms and matrix
usage was 1,969,305 tokens; adding the 39,537-token hydration sentinel produced
2,008,842 combined tokens, 8,842 above the approved outer budget. The run also
used a 95-second request timeout, while the exact `50e5975` baseline was created
with 120 seconds, so the evaluator correctly marked comparison inconclusive.
An offline diagnostic only—not an approval rescore—shows that aligning that
single field would produce 19 matched actions and a 20.88% matched token
increase, below the 25% failure threshold but above the 10% concern threshold.

The channel-read failure in that bundle was operator-created: the local wrapper
inserted a slash between ManyChat's `fb` route prefix and page identifier and
received HTTP 302. Isolated rerun `20260911_174139_853220` used the loader's
canonical URL construction and passed both history and profile contracts. The
deployed protected loader had passed throughout. Promotion remains held on
cost/latency variance and deterministic directness concerns, not channel
authentication or customer correctness.

Call-level comparison against the prior exact candidate localized the usage
increase to additional bounded model rounds rather than tool/API errors:
`nonlinear_product_first` added three calls and 137,946 tokens; the reordered
two-brand payment case added two calls and 55,193 tokens; the Toyo case added a
main round plus composer repair and 40,808 tokens; and the final journey payment
action added one composer repair and 21,623 tokens. These are correctness and
format-recovery paths, so they were not disabled to clear the budget.

Static context inspection found 6,700-plus characters of product/promo
discovery policy in the shared core even though the runtime already compiles
domain-specific prompts. The unchanged policy is now projected only when the
product domain is selected. Product/all-domain prompts retain it and the
99,000-character cap; the order-only prompt falls from 55,901 to 49,172
characters (12.04%). The shared and final-composer contracts also state the
directness rule as a general behavior: acknowledge understood details as a
statement and ask only one next question, rather than pairing a confirmation
question with another CTA. All 1,744 repository tests, changed-file Ruff, and
diff checks pass locally. A new exact staging deployment and complete run with
the baseline-compatible 120-second request timeout are required.

After the operator reported sending fresh inbound messages, Secret
Manager-backed channel probes again returned HTTP 200 for both browser-history
and subscriber-profile reads. A protected hydrated-history turn also passed on
exact staging `85fbf79`: it forced a refresh, loaded six messages into eleven
model-facing messages, used two model calls and 39,354 tokens, and completed in
41,369 ms. However, the independent ManyChat profile and browser-history
sources still identified the latest inbound as the 12:16:03 promo question;
the newly reported messages were not yet present in either source. Cloud logs
also showed only the evaluator's 18:05 staging request for this subscriber in
the recent window. The hydrated turn therefore proves that deployed refresh
and model-context wiring remain healthy, but not that the newly sent messages
have reached ManyChat under the designated subscriber ID.

Normal product-branch Cloud Build
`b36a2c60-0efc-4aef-ad42-8ab4ee076678` deployed exact `daca2ea` to
`gulong-chatbot-runtime-staging-00443-bwd` at 100%, digest
`sha256:8c90148c3abcf62d0a601edace890fc0dbe4901d926fe103c0be0f0de2dc59c1`.
Both health routes were green and staging retained return-only delivery,
disabled follow-up sending, and disabled tag mutation. Five affected scenarios
passed mechanically with a 100% CS structural proxy and no operational errors;
their p95 was 91,224 ms and usage was 464,785 tokens.

Complete serial run `20260911_182245_473862` passed deterministic-full, both
health probes, five commerce probes, both ManyChat reads, and protected
hydration. Hydration refreshed six messages into eleven model-facing messages
in 25,582 ms. The 24-response model corpus had zero HTTP/runtime/tool errors,
100% telemetry, 1,733,450 tokens, and p95 81,736 ms; combined usage was
1,772,902 tokens. Its exact live baseline comparison was compatible with 19/21
matched actions and a 3.47% token increase. Promotion remained red at 17/19:
`explicit_head_office_address` fell to the neutral resend after one
non-renderable no-tool call, and `semantic_store_location` supplied the head
office instead of asking for customer area. These were model-variance escapes
around an already correct written policy.

The next local correction makes that narrow policy deterministic after render
for isolated no-tool goals. It classifies address/location intent from combined
multilingual cue groups, abstains for fulfillment, mixed, tool-backed,
active-choice, and selected-product turns, and records only disposition,
reason, and canonical evidence ref. Explicit address failures receive the
reviewed canonical address; bare store/branch failures receive one city/area
question and cannot volunteer the head office. Real JSON arrays qualify for
the existing bounded retry, while bracketed product-menu prose remains a
negative control. All 1,762 repository tests, Ruff, and diff checks pass
locally. A new normal staging deployment and exact reruns are required.

## 2026-09-11 exact `b180a74` gate and integrated hardening

Normal product-branch Cloud Build
`cab18f89-97a0-4680-a4c7-d9d3a348cbf6` deployed exact `b180a74` to staging
revision `gulong-chatbot-runtime-staging-00444-rfn` at 100%, image digest
`sha256:30b625ade499dff672c81de1e1637aaa53d92e478c8fa90115fd67c5ce34f6b5`.
Both health routes reported the exact identity and staging remained
return-only with follow-up sending and tag mutation disabled.

Targeted run `20260911_191037_299320` passed all five location, delivery,
province-schedule, and nonlinear-product controls. Complete layered run
`20260911_191534_251595` recorded 86 model calls, 1,917,496 combined tokens,
and 77,981 ms matrix p95, all inside the approved hard limits. Deterministic,
commerce, channel-read, hydration, telemetry, integrity, and baseline checks
passed. Root `/health` returned HTTP 200 in 10,683 ms, above its 5,000 ms API
SLA, while `/gulong/health` returned in 181 ms.

The complete customer matrix remained red at 17/19. The delivery-policy turn
used the correct policy tool and composer but omitted the provider's 7-10-day
fact. The bare store-location turn called
`present_serviceable_location_choices`, emitted an internal choice token, and
then volunteered the head office. This showed that a post-render location
boundary cannot prevent an incompatible pre-composer surface and that the FAQ
answer goal did not prove retention of every provider-required fact.

The pending correction applies the same semantic business-location disposition
before tool planning. Isolated address/location goals expose no tools unless an
ambiguous store-location turn already has a reusable customer area. The failed
trace had no such signal, so this is a state-aware general boundary rather than
an exact-phrase patch. Delivery policy now emits typed required facts sourced
from canonical values. The composer accepts semantic term sets and regex prose
variants, attempts bounded repair, and falls back to the provider-authored safe
answer if a required fact remains absent. All 1,764 repository tests, Ruff,
compilation, and diff checks pass locally.

A 19:48 Secret Manager-backed browser-history read again returned HTTP 200 and
normalized six text messages from 230 events. The latest inbound remained the
12:16:03 promo question and the latest visible reply was 12:16:39. The newly
reported inbound messages are still not observable under subscriber
`4843256405786522`; this is separate from loader health.

## 2026-09-11 exact `b451b77` targeted gate

Normal product-branch Cloud Build
`f8073324-424e-4a94-a95f-163c2e823ae0` deployed exact `b451b77` to staging
revision `gulong-chatbot-runtime-staging-00445-m7q` at 100%, image digest
`sha256:7ce4d90763f87eee3d42fc1e4cf4749fa48d49b9156c50f9bd1827ec2c6029ce`.
Both health routes were warm at 482/89 ms and staging retained return-only
delivery, disabled follow-up sending, and disabled tag mutation.

Targeted run `20260911_200133_260443` passed both delivery variants, the
province schedule control, and the nonlinear product-first control. The two
location requests failed before HTTP with local `getaddrinfo` errors and no
model usage. A second attempt reproduced the same DNS failure. Independent
resolution through Google DNS remained healthy, and the local resolver later
recovered without a runtime or infrastructure change.

Post-recovery run `20260911_201013_964382` passed explicit head-office address.
The bare store-location case exposed zero tools and called none, proving the
pre-planning boundary, but its rendered response retained the model's original
head-office paragraph before the corrected area question. The harness guard
had fired; the channel renderer then preferred the still-original
`assistant_text` over `runtime_final_response`. The boundary now synchronizes
the accepted text into the renderer-owned field. A channel-render regression
proves the rejected address cannot return, and all 1,764 repository tests pass.

## 2026-09-11 exact `ffde9fe` gate and complete telemetry correction

Normal product-branch Cloud Build
`26142079-ec29-4702-9a2b-3aa1561516d5` deployed exact `ffde9fe` to staging
revision `gulong-chatbot-runtime-staging-00446-ctn` at 100%, image digest
`sha256:049408ec3646d7b1befa245a673dfe90e1289e3daa5e450f44c2ccf4986df85d`.
Health identity, return-only delivery, disabled follow-up sending, and disabled
tag mutation were verified. Targeted run `20260911_202325_607665` passed both
location cases: the ambiguous store-location turn rendered only the customer-
area question and exposed/called no tools; the explicit address turn returned
the canonical address.

Complete layered run `20260911_202551_624773` passed all deterministic, core,
commerce, ManyChat read, protected hydration, target-identity, integrity, and
19/19 mechanical customer contracts with zero HTTP/runtime/tool errors. It
remained blocked at 95,341 ms p95, 341 ms above the 95,000 ms hard limit. The
model matrix reported 81 calls and 1,846,662 tokens; including hydration, the
outer artifact reported 83 calls and 1,886,073 tokens. It also raised two
cross-turn duplicate structural concerns in the five-step product journey and
a 12.73% matched-action token warning.

Those call/token totals are withdrawn as incomplete release evidence. The API
aggregate was built only from `llm_calls`, while paid background extraction and
active-memory compaction lived under separate metadata. The state-extraction
trace also read obsolete `usage`/`latency_ms` keys, and tester tool calls did
not expose their already-recorded latency. The local correction aggregates all
model-backed components, tracks provider attempts, missing usage, and
unmetered retries, emits supplemental normalized LLM spans, maps the extractor's
actual fields, and exposes tool latency. All 1,768 repository tests pass. No
live or VM promotion is authorized until this is deployed and the exact gate is
rerun.

A fresh Secret Manager-backed ManyChat read returned HTTP 200 across 15 pages.
The designated subscriber had new custom-field/rule activity at 20:48-20:55,
but no corresponding `msgin` event; the latest actual inbound remains the
12:16:03 promo question. This proves current browser-session authentication and
pagination, but not that the newly sent messages arrived under subscriber
`4843256405786522`.

The two reported structural CS concerns were evaluator false positives. The
scorer flattened bubbles across the five-step journey, so a summary/reminder
shown after a later tracked action collided with the same text from the prior
turn. Duplicate comparison is now turn-local. A positive journey control
allows cross-turn recurrence, while a negative control still flags two exact
bubbles inside one response.

## 2026-09-11 exact `1f9715a` telemetry diagnostic and phase hardening

Normal product-branch Cloud Build
`3423940b-af19-45d6-8ce1-665529f80b5e` deployed exact `1f9715a` to staging
revision `gulong-chatbot-runtime-staging-00447-dhn` at 100%, image digest
`sha256:684633ed5bdde2ce31899d42d575271605026776071accdd54de4a98a6212feb`.
Both health routes passed and return-only delivery, disabled follow-up sending,
and disabled tag mutation were verified.

Cost-bounded run `20260911_212950_219650` exercised two single-turn cases and
the five-step product/location/schedule/payment journey. All 3 paths and seven
responses passed mechanically with zero HTTP/runtime/tool errors and complete
model accounting. The run used 41 provider calls, 897,133 prompt tokens,
73,699 cache-read input tokens, 29,225 completion tokens, and 926,358 total
tokens. P50/p95/max endpoint latency was `72,716/86,913/86,913 ms`.

Per-turn model and tool latency left approximately 27-40 seconds unexplained.
Tools were not the dominant source: the largest tested per-response sum was
about 17.5 seconds, while several responses spent under four seconds in tools.
The complete 24-response matrix is therefore held to avoid spending through the
2,000,000-token ceiling without diagnostic value. The API now records bounded
monotonic timings for session load/reload/lock, conversation and harness
hydration, interaction settling, harness execution, rendering, freshness,
delivery/tagging, session persistence, inbox cleanup, trace emission, and total
handler time. The evaluator aggregates each phase/tool and client-versus-
handler overhead; missing or invalid phase or tool timing blocks promotion.
Turn-local duplicate scoring and phase telemetry add positive and negative
controls. All 1,772 repository tests, focused checks, Ruff, compilation, and
JSON validation pass locally. Live Cloud Run and the VM remain unchanged.

## 2026-09-11 exact `3479955` phase result and persistence correction

Normal product trigger build `5df69ffb-4f13-4273-adf8-168b97ac0606`
succeeded and deployed exact `3479955` to revision
`gulong-chatbot-runtime-staging-00448-sg7` at 100%, image digest
`sha256:bf2bb276df9b227a8b67d1dd2282fe1573536921ec9896e7c2fc58eb2e58cd0d`.
Both health routes returned HTTP 200 with the exact staging identity and all
return-only/follow-up/tag safety controls remained unchanged.

Serial diagnostic `20260911_215922_736446` exercised the province schedule case
and five-step product journey. It returned six HTTP-200/runtime-success
responses with zero tool errors, 35 model calls, 757,937 prompt tokens, 209,884
cache-read input tokens, 25,597 completion tokens, and 783,534 total tokens.
P50/p95/max was `70,677/91,253/91,253 ms`. The schedule case passed. The journey
failed its final-composer-status contract once with
`renderer_contract_fallback`; this remains a real immutable-run failure and is
not waived by the latency diagnosis.

Phase evidence localized the repeated non-model delay to session persistence:
`29,460/31,908/31,908 ms` p50/p95/max. Handler time tracked client time closely;
client/transport overhead was only `242/484/484 ms`. Conversation hydration,
freshness, rendering, delivery, and trace emission were negligible. The final
tester session document was about 150 KB, well below Firestore's size limit.
Two strict telemetry failures were deterministic `present_promo_gallery`
surface records with no latency field, not external-provider omissions.

The persistence correction removes the full Firestore transaction after the
runtime turn lock is held. It reads the current snapshot/revision and performs
one update guarded by that exact snapshot update time. Revision mismatch,
concurrent precondition failure, and create collision fail closed; owned-lock
clearing remains in the same write. State assembly and remote store phases are
now measured separately. Runtime-completed in-process promo galleries record a
zero-millisecond latency. Focused storage/ingress/promo/evaluator verification
passes 176 tests; all 1,777 repository tests also pass. Exact-staging rerun
remains pending. Live Cloud Run and the VM remain unchanged.

## 2026-09-11 exact `e047694` matched persistence result

Normal product build `42abd47d-9394-43de-8161-7084ec509b48` deployed exact
`e047694` to staging revision `gulong-chatbot-runtime-staging-00449-6gs` at
100%, image digest
`sha256:6f0bbf0550aade190a88e49fbbdbf629c4c93eec52e353c929ad25b97019c85b`.
Both health routes and return-only/follow-up/tag safety checks passed.

Matched run `20260911_223111_021785` used the same province schedule case,
five-step product journey, one worker, 95-second timeout, and full-tier contract
as `3479955`. Both selected paths passed mechanically; all 14 structural CS
checks passed; HTTP/runtime/tool errors and missing usage/tool latency were all
zero. Six responses made 35 model calls and used 713,794 prompt, 104,829 cache-
read, 26,903 completion, and 740,697 total tokens. P50/p95/max endpoint latency
was `73,026/91,996/91,996 ms`.

The conditional write did not improve persistence. Local state assembly was
only `7/10 ms` p50/p95, but remote `session_store_save` was
`31,834/35,190 ms`, compared with `29,460/31,908 ms` under the original
transaction. The immutable partial run is red only because it intentionally
omits the rest of the complete scenario corpus; its selected paths are green.
The conditional update is reverted because it added core persistence semantic
risk without measured benefit. The transaction path, phase split, and valid
zero-millisecond deterministic promo-surface timing are retained. The evidence
now points to full nested state write/index fanout or payload architecture;
index exemptions and compact/delta persistence require a separate controlled
storage review. Live Cloud Run and the VM remain unchanged.

The safe revert plus retained phase/surface telemetry passes all 1,772
repository tests, focused checks, Ruff, compilation, JSON validation, and the
strict behavioral/customer/release audit. A normal staging restoration is the
remaining external action; no further paid model rerun is warranted for the
reverted no-benefit mechanism.

Normal product build `e3732e12-6b17-4a0b-9ee2-7085158351ae` restored the safe
lineage as exact staging `8ed58df`, revision
`gulong-chatbot-runtime-staging-00450-6gv` at 100%, image digest
`sha256:5f0d0cd91a5b47e7262fa1144193da1b1f9768cc637835fc2e7615afea636668`.
`/health` and `/gulong/health` returned HTTP 200 in 186/61 ms with exact
staging identity. Delivery remains return-only; tag mutation and follow-up
sending remain disabled. No additional paid model run was made because the
restored transaction path was already measured by the exact `3479955` phase
artifact. Live Cloud Run and the VM remain unchanged and unapproved.

## 2026-09-11 isolated Firestore persistence diagnosis

Firestore database `(default)` is Native mode in `asia-southeast1`. Neither
`sessions` nor `sessions_test` has a composite index or explicit
`strategy_state` field exemption, and repository access to session state is by
direct document path rather than nested-state queries. A synthetic five-turn
evaluator session was about 141 KB, of which about 135 KB was
`strategy_state`; its largest Runtime V7 contributors were product/service
observations, choice presentation/action history, and background signals. A
separate exact one-turn product session was only about 41 KB yet had taken
19,783 ms to save on staging, contradicting a simple payload-size explanation.

The paired benchmark wrote only to guarded benchmark collection groups and
used the runtime's exact transactional full-document CAS method. The first
stable-state comparison was rejected as weak because it changed almost no
nested values. The hardened run alternated 3,462 nested scalar leaves. Across
ten measured 141 KB updates, the indexed path was 646.748/695.438 ms p50/p95;
the temporary recursive `strategy_state` exemption was 466.182/478.639 ms.
Index churn therefore contributed 27.92%/31.17%, but the absolute difference
was only about 0.2 seconds. Both paths read back successfully and all exact
benchmark documents were deleted.

An additional diagnostic run showed one transaction attempt throughout. The
indexed path spent roughly 162-205 ms reading and 397-455 ms in commit-side
overhead; the exempt path spent roughly 157-205 ms reading and 236-274 ms in
commit-side overhead. This confirms a measurable index cost but rules it out as
the primary source of 20-35 second deployed saves. Compact/delta persistence is
deferred until a simpler cause is excluded.

The existing transaction path now records content-free attempt count,
per-attempt read/body timing, aggregate commit/retry overhead, save status, and
exception type. Payload and strategy-state byte counts run only after a slow or
failed store operation; diagnostic overhead is measured separately. Tester
debug and slow-save logging expose only those allowlisted scalar fields. The
benchmark runner rejects serving/evaluator targets, requires an explicit
confirmation, hashes source identifiers, pre-registers exact cleanup targets,
and supports reciprocal variant ordering. The temporary benchmark-only field
exemption was restored to inherited default indexing after measurement. All
1,780 repository tests, focused tests, Ruff, compilation, and diff checks pass. The
next gate is an observability-only staging build followed by one exact product
case under the existing 95-second request and two-million-token run ceilings;
live and VM remain untouched.

## 2026-09-12 Firestore commit-transport diagnostic implementation

The previous save diagnostic proved that slow staging turns spent 18-44 seconds
after the transaction body, but that aggregate could not distinguish one slow
commit from Firestore GAPIC retries or local process contention. The new
staging-only observer wraps the generated client's raw `begin_transaction` and
`commit` targets beneath the unchanged retry and timeout decorators. Each
actual attempt records only operation, ordinal, latency, outcome,
exception/status type, retry classification, process ID, hashed instance ID,
and process-local active-save count. It does not inspect request metadata,
document paths, transaction IDs, or saved state.

An authenticated `/gulong/v7/session-persistence/tester` endpoint now runs
generated 40 KB or 140 KB payloads through the exact CAS method without any
model, customer/evaluator read, analytics, delivery, or tagging path. The
endpoint is hard-disabled outside staging/test, writes only to uniquely named
benchmark collections, and deletes its exact document in `finally`. The normal
Cloud Build configuration also accepts an explicit `GUNICORN_WORKERS`
substitution for same-SHA four-worker versus one-worker staging comparison.

Fresh local-process validation against Firestore measured 40 KB at 314/333 ms
p50/p95 and 140 KB at 452/455 ms. All eight measured saves contained one
successful commit RPC and approximately 1-2 ms of unattributed wrapper/backoff
time; both exact documents were deleted. This validates the decomposition and
shows no comparable delay in the local process, but does not yet identify the
Cloud Run cause. Seventy-four focused tests and all 1,786 repository tests pass.
Staging A/B remains required; retry duration is deliberately unchanged until
attempt-level evidence shows whether retries are actually involved.

Normal product build `93497774-cc46-4e16-842d-404dc670e23e` deployed exact
`81f7261` to staging revision `gulong-chatbot-runtime-staging-00453-dkn`.
Generated 40 KB and 140 KB serial probes completed at approximately 161/286 ms
and 174/260 ms p50/p95. Eight-request concurrent probes increased individual
save maxima to 1,315 ms and process-local CPU to about 98 percent, but every
write still used one successful commit with no retry. Same-SHA one-worker
revision `gulong-chatbot-runtime-staging-00454-lv6` did not improve the serial
or concurrent distributions, so build `464b6a13-63ae-43d7-adea-f2741000a100`
restored four workers as revision `gulong-chatbot-runtime-staging-00455-8l7`.

Exact product case `availability_exact_brand_size` then passed mechanically
with HTTP 200, five fully metered model calls, 68,759 tokens, and 60,708 ms
client latency. Its 41,277-byte session save reproduced at 18,164 ms. The raw
observer proved this was one 17,662 ms successful commit, not a retry sequence;
begin transaction was 27 ms and wrapper/backoff remainder was 17 ms. The worker
used 16,930 ms process CPU during the save despite one active save and no other
Cloud Run request on that revision. Retry deadline reduction therefore cannot
fix this occurrence. The next narrow diagnostic splits commit-thread CPU from
other-thread CPU and records GC, page-fault, and context-switch deltas before
any persistence redesign or retry-policy change.

Normal product build `eef7164e-9234-482e-8c59-f577559f0ebd` deployed exact
`bd050fa` to four-worker staging revision
`gulong-chatbot-runtime-staging-00456-m8r`. The same product case again passed
with HTTP 200, 69,637 fully metered tokens, and 62,926 ms client latency. Its
41,477-byte session took 18,302 ms to save; the sole successful commit occupied
17,753 ms.

The new split localized 16,350 ms of CPU to the commit thread itself, only
20 ms to other threads, and recorded 11,990 ms user plus 4,380 ms system CPU.
During that one call Python ran 487/44/2 cyclic-GC collections across
generations 0/1/2 and collected zero objects. It recorded no major or minor
page faults and no voluntary or involuntary context switches. The synthetic
evaluator document contains 1,111 scalar leaves, 201 maps, 101 lists, and depth
11, versus 135 scalar leaves, six maps, no lists, and depth five in the simple
40 KB generated probe. The immediate mechanism is therefore CPU-bound
Firestore request encoding/object allocation with repeated cyclic-GC scans on
the commit thread, amplified by realistic nested shape and the loaded runtime
heap. Backend waiting, retries, competing save calls, document bytes alone,
and index fan-out are excluded as primary explanations by the paired evidence.
No GC policy or persistence representation was changed in this diagnostic.

## 2026-09-12 versioned strategy-state compatibility implementation

The mitigation is implemented as a Firestore-adapter concern rather than a
Runtime V7 state-contract change. The adapter dual-reads the legacy nested map
and schema-versioned `canonical_json_v1`, verifies canonical bytes by SHA-256,
and returns the same dictionary-or-null `strategy_state` shape to callers.
Canonical metadata wins if both formats exist; malformed or unknown canonical
state fails closed with a content-free reason instead of falling back to a
possibly stale nested copy.

The writer is configuration-selected and Cloud Build still defaults to
`nested_map_v1`. Full state writes delete every field owned by the opposite
representation in the same update. Lock and interaction-inbox writes remain
narrow merges and do not rewrite state. Historical sessions migrate lazily on
their next successful full save, avoiding a broad Firestore rewrite. Once
canonical writes are enabled, the rollback floor is the reader-capable legacy
writer release, not any earlier revision.

The staging-only representation probe now tests the migration bridge itself.
It seeds the opposite format, reads it through the configured adapter, switches
the same document, verifies the raw authoritative shape and decoded state, then
proves a stale CAS leaves the exact document unchanged. Local authenticated
Firestore runs passed both canonical-to-nested and nested-to-canonical paths,
including exact cleanup. Their switch saves measured approximately 386 ms and
320 ms. A later repetition also verified non-CAS creation in both formats and
measured the switch saves at approximately 370 ms and 324 ms. Forty-five
focused tests and all 1,810 repository tests pass; changed-
file Ruff, Python compilation, and diff checks pass. Repository-wide Ruff still
reports 27 pre-existing findings in unrelated files and those files were not
changed.

The deployment sequence remains gated: first deploy this exact compatibility
code with the nested writer, verify dual-read and rollback behavior, then
redeploy the same reader-capable code with canonical writes enabled. Only after
a targeted product-path rerun and the complete 95-second/2-million-token
evaluator pass can live Cloud Run or the VM be considered.

### Release A staging evidence

Normal product-trigger build `585fca36-5bb3-42a0-80f4-0aea6af35f74`
deployed exact `6458fd6` to staging revision
`gulong-chatbot-runtime-staging-00458-tj6` at 100% traffic with
`nested_map_v1`. Both health routes reported the exact SHA; return-only mode,
four workers, disabled tag mutation, and disabled follow-up sending remained
intact.

The protected generated-data canary seeded canonical state and proved the
deployed Release A reader could decode it before the legacy writer switched the
same document back to a single nested representation. The raw-shape check,
post-switch read, stale-CAS no-mutation control, non-CAS creation, and exact
five-document cleanup all passed. Nested saves remained slow at approximately
6,115 ms p50 while canonical saves measured approximately 60 ms p50. This is
the intended rollback bridge; no serving-session bulk migration occurred.

### Release B staging evidence and promotion decision

Normal staging build `31bc1064-be7d-412c-a1ff-26789008f3f0` redeployed the
same exact `6458fd6` reader-capable code to revision
`gulong-chatbot-runtime-staging-00459-t6r` at 100% traffic, changing only the
configured writer to `canonical_json_v1`. Both health routes reported the
exact SHA. Return-only delivery, four workers, disabled tag mutation, and
disabled follow-up sending remained intact.

The protected canary seeded the legacy nested representation, decoded it
through the dual reader, switched that same document to canonical JSON, and
verified exactly one authoritative raw representation. The post-switch read,
stale-CAS exact no-mutation control, non-CAS creation, and five-document
cleanup all passed. The switch save measured 372 ms. Its measured canonical
save p50/p95 was 79/102 ms, compared with 7,483 ms nested-map p50. This closes
the representation and rollback checks without a bulk historical rewrite.

The exact Yokohama 195/60R15 targeted case passed its mechanical contract and
all seven structural CS checks. It rendered the product card, image, price,
promo/payment/warranty details, tracked product-selection button, supporting
promo control, and location CTA. End-to-end latency was 43,581 ms, while the
session-store save was 57 ms; five model calls reported 68,814 tokens.

The complete serial scenario-contract `2026-09-11.4` run passed 19/19
mechanical scenarios and 133/133 structural CS checks. It recorded zero HTTP,
runtime, tool, and mutating-tool errors across 24 responses and 46 tool calls.
Latency was 25,805/55,850 ms p50/p95 with a 58,189 ms maximum, and session
persistence was 79/119 ms p50/p95 with a 121 ms maximum. The persistence
pathology is therefore resolved in this observed staging cohort.

Promotion remains gated by the predeclared evidence contract. The matrix
reported 2,009,655 tokens, 9,655 above the 2,000,000 ceiling, and two retry
attempts in `business_contact_grounded` lacked usage telemetry. The complete
outer layered run, including its separately executed hydrated-history sentinel,
reported 2,101,084 tokens. The current exact-live `50e5975` baseline used a
120-second timeout and is incompatible with the candidate's required
95-second profile. The matrix's 55,850 ms p95 is a concern but not a failure
under the 95-second hard ceiling. No live Cloud Run or VM promotion was made.
Fresh control-plane and VM inspection confirmed Cloud Run live still routes
100% to `gulong-chatbot-runtime-live-00106-vgr` at `50e5975`, while the
customer-facing `gulong-chatbot-runtime-shadow` container still reports
`50e5975`, `service_environment=live`, and `runtime_host=vm-live`.

The next gate is no-cost diagnosis and correction of retry usage accounting
and token concentration, followed by one fresh 95-second exact-live baseline
and one candidate rerun. Repeating the paid matrix before those corrections
would not resolve the known blockers.

### Retry metering and prompt-projection correction

The exact missing-usage boundary is confirmed. Background extraction reported
three provider attempts in `business_contact_grounded`, but
`_call_signal_model_with_retries` retained only the final successful response
and reduced earlier invalid or unusable responses to bounded error text. The
turn ledger therefore had one usage payload for three calls. This is not a
provider-billing ambiguity; it is a local aggregation omission.

The correction retains content-free usage/cache/latency metadata from every
returned extractor response, aggregates all observable attempts, and leaves
transport exceptions without response usage explicitly unmetered. A negative
control verifies that a two-attempt logical call with only one usage payload
still reports one missing/unmetered attempt.

Token concentration is predominantly prompt input: the complete artifact used
1,936,330 prompt versus 73,325 completion tokens. Main-tool-loop prompts
accounted for 1,329,647 total tokens, followed by the composer at 430,403,
background extraction at least 200,236, and active memory at 49,369. Six
responses entered the product domain solely through the production fallback.
The production builder now uses the capability compiler's intended empty
fallback: normalized signals/refs select domains, while the general
`request_capability` tool recovers a missing initial domain. This removes the
31,825-character product-policy and roughly 19,000-character product-schema
delta from genuinely general turns without adding phrase-specific routing.

Focused tests pass for successful retry aggregation, exception-only missing
usage, negative-control accounting, trace projection, and production harness
construction. Broader and deployed evidence are pending.

Independent review found no unconditional default-path blocker and confirmed
that returned retry usage is aggregated exactly once. Before deployment, three
edge cases were hardened: explicit capability expansion now has a replacement
round at a one-round tool cap; exception-only accounting reports the initial
attempt as missing but not as a retry; and normalized `llm_span_log.meta`
retains provider and metered-provider counts. Focused positive and negative
controls pass; the full deterministic suite is being repeated against these
review changes.

The repeated suite passed all 1,813 repository tests. Changed-file Ruff,
Python compilation, Cloud Build YAML parsing, diff checks, and the strict
behavioral/customer-facing audit also pass. This closes local validation for
the reviewed candidate; staging remains the next evidence boundary.

### Learning candidate: Scalar Firestore state needs a compatibility bridge

- Captured: 2026-09-12
- Promotion status: candidate
- Symptom: Deeply nested runtime session saves consumed 6-19 seconds in Cloud
  Run and drove hundreds of zero-yield cyclic-GC collections on the Firestore
  commit thread.
- Root cause: Paired process and RPC telemetry showed one successful commit
  with nearly all delay in local nested-map encoding and object allocation;
  canonical scalar JSON removed the GC tail while retaining the same logical
  state.
- Proposed practice: Keep the in-memory state contract unchanged, dual-read
  the old and new representations, switch writers by configuration, atomically
  delete the obsolete representation, migrate lazily, and gate promotion on
  bidirectional read-switch-read, stale-CAS no-mutation, non-CAS creation, and
  exact cleanup controls.
- Scope/owner: Runtime session-store adapters that persist deeply nested state
  to Firestore.
- Positive scenario: A reader-capable release first writes the legacy form;
  the same SHA then switches a generated legacy document to hash-validated
  canonical JSON and all transition controls pass before serving promotion.
- Negative control: A shallow or scalar Firestore document without reproduced
  encoder/GC pressure should not be migrated merely because one backend write
  is slow; inspect RPC retries and backend latency first.
- Expected benefit: Avoids speculative retry reductions, preserves rollback
  compatibility, and reduces observed persistence from multi-second tails to
  roughly 0.1 seconds without changing customer-facing state semantics.

## 2026-09-12 isolated state-representation benchmark implementation

The next experiment changes only the generated benchmark representation. A new
authenticated staging/test-only endpoint compares the same logical state as a
nested Firestore map, canonical JSON text, and deterministic gzip JSON. All
three variants use `FirestoreSessionStore.save_session_cas`, separate exact
benchmark documents, identical expected-revision progression, and rotating
execution order. Serving and evaluator sessions remain out of scope.

The 40 KiB generator is Firestore-valid and approximates the exact problematic
shape: 983 scalar leaves, 207 maps, 101 lists, and depth 11. Every successful
save is read back outside the timed interval, decoded, and checked for exact
logical equality, SHA-256 equality, and expected revision. One stale-revision
write per variant must fail without changing the stored revision or hash.
Cleanup deletes every pre-registered exact document and verifies absence; a
cleanup failure invalidates the run.

The first local real-Firestore control used one warmup and three measured 40
KiB rounds under inherited default indexing. All round trips and stale-CAS
controls passed, and zero benchmark documents remained. Nested map, canonical
JSON, and gzip JSON measured approximately 362, 220, and 162 ms p50
encode-plus-save respectively. Gzip reduced the generated state field from
40,960 to about 2,713 bytes, but that compression ratio is not representative
of customer data because the synthetic padding is intentionally repetitive.
The local timing is directional only; exact Cloud Run staging remains required
to determine whether either scalar representation bypasses the reproduced
commit-thread allocation and cyclic-GC tail.

Local verification passes seven focused probe/API tests and all 1,790
repository tests, plus Ruff, compilation, diff validation, manifest JSON
parsing, and the strict behavioral-change audit.

## 2026-09-12 staging state-representation result

Normal product-trigger build `302bbf28-1c46-4a5a-b093-3744bc823c82`
deployed exact `90173d2` and digest
`sha256:fb37c0763cbf238dc45861532ca00256215e8fa24f99e87018f1e9e594a66c80`
to `gulong-chatbot-runtime-staging-00457-8r6` at 100% traffic. Both health
routes reported the exact SHA. Staging remained return-only with four workers,
tag mutation disabled, and follow-up sending disabled.

The three-round 40 KiB run `20260912T035214Z-99edb10f` measured nested-map,
canonical-JSON, and gzip-JSON save p50/p95 at 6,637/6,690 ms, 58/58 ms, and
41/47 ms. Nested commit attempts used 5,860-5,910 ms of current-thread CPU and
339-340/31/3 GC cycles; both scalar variants recorded zero commit-side GC
cycles. Their complete encode-plus-save p50 values were 6,639 ms, 58 ms, and
43 ms respectively.

The two-round 140 KiB run `20260912T035312Z-e059ac8b` measured save p50/p95 at
18,626/19,034 ms, 91/120 ms, and 61/72 ms. Nested commits used 15,590-16,200
ms of current-thread CPU and 1,212/110/9 GC cycles, versus zero cycles for both
scalar formats. Canonical JSON retained 143,360 bytes; gzip stored 8,328 bytes,
but that ratio must not be projected to real state because generated padding is
highly repetitive.

Every measured save used the unchanged transactional full-document CAS path.
All decoded-state hashes, expected revisions, stale-revision negative controls,
and cleanup checks passed. A separate final collection-group read returned zero
benchmark documents. The causal conclusion is confirmed: scalarizing the
deeply nested state bypasses the Firestore encoder/object-allocation and
cyclic-GC pathology. Canonical JSON is the lower-complexity production
candidate; gzip should remain optional until representative compression and
read/write CPU are measured. No production reader, stored schema, live Cloud
Run revision, VM process, index configuration, retry setting, or GC policy was
changed.

## 2026-09-12 exact-staging pre-gate and cross-clause payment recovery

Normal product-trigger build `6ecf1e9a-5055-4645-a9a4-142a848c7490`
deployed exact `599b6ba` and image digest
`sha256:c71b1c328fcbcf3449b44f6eeafdeceec5a655acf3e315174ba4ebf65b39f3d3`
to revision `gulong-chatbot-runtime-staging-00460-vgp` at 100% traffic. Both
health routes reported the exact SHA, canonical JSON persistence, return-only
delivery, four workers, disabled tag mutation, and disabled follow-up sending.

The Secret Manager-backed no-model profile passed all core, commerce, and
channel-read contracts. Product search, partner, payment, transaction-type,
slot, ManyChat message-history, and ManyChat profile probes all returned HTTP
200. The protected hydrated-history turn loaded six messages into eleven
model-facing messages and passed in 29,226 ms with 49,943 tokens.

The three-case model smoke artifact
`tmp/runtime_v7_staging_599b6ba_pre_staging/runtime_v7_health_20260912_160845_402678/model-initial/runtime_v7_release_candidate_20260912_161008_643423/summary.json`
used 166,809 tokens with complete attempt metering. Contact and delivery
passed. The payment case blocked because the initial model joined the named
method and a sibling term as `Home Credit 3-month 0%`; hydration safely
executed the grounded three-month and BPI six-month scopes, but no independent
Home Credit provider result or third typed claim existed.

The pending local patch detects model proposals spanning multiple hard customer
clauses and derives only a contiguous named-method span from the customer-backed
non-installment clause. That span receives its own canonical provider lookup;
no method, provider, brand, or phrase exception decides the outcome. Strict
token-subset pruning prevents a repeated generic token from becoming a shorter
duplicate method scope, while a one-token scope requires an independent typed
latest-message payment signal. The exact integration regression and three
adjacent negative controls pass, as do 905 affected-path tests, all 1,817
repository tests, Ruff, compilation, diff checks,
and the no-cost evaluator profile. A new exact staging build and matched rerun
are required before the complete matrix or any live/VM promotion.

## 2026-09-12 complete-matrix blocker and generalized remediation

After the laptop resumed, the remaining `model-complete` layer ran fresh from
22:39 to 22:52 Asia/Manila; the five-hour shutdown was not included in measured
latency. Exact staging `5cca58d` produced 18/19 mechanical passes, a 96.24%
structural-CS proxy, zero HTTP/runtime/tool errors, 58,133 ms p95 latency, and
2,044,679 tokens. The artifact is
`tmp/runtime_v7_staging_5cca58d_model_complete/runtime_v7_health_20260912_223920_923464/model-complete/runtime_v7_release_candidate_20260912_223921_363458/summary.json`.
Promotion remained blocked because `promo_toyo_truth` omitted
`present_promo_gallery` and the run exceeded the temporary 2,000,000-token
ceiling by 44,679 tokens.

The failure was customer-visible rather than a phrase-matcher artifact. The
customer supplied an exact tire size and explicitly requested fallback promos;
the catalog safely rejected the requested brand but the runtime showed no
fallback and asked for the known size again. The pending patch introduces a
canonical semantic fallback scope with latest-customer typed provenance,
separate provider-issued primary and alternative refs, scope-bound evidence
identity, and renderability checks. It also removes a hard-coded Buy 3 Get 1
truth-guard sentence.

The token trace exposed an independent deterministic inefficiency. A
product-first turn containing a confirmed future BPI/Pay Later preference was
treated as an immediate policy question, causing three extra model rounds and
premature payment/schedule lookups. Retry eligibility now uses typed relation
and confirmation status: questions remain due now, while saved preferences wait
for the later checkout step. Local validation after independent review includes
the exact positive/negative controls, the no-cost evaluator, and a full
repository pass; exact rebuilt staging evidence remains required.

## 2026-09-12 exact-staging targeted remediation check

Normal product-trigger build `87d6e805-e765-49b8-a139-a0d4a2497097`
deployed exact `1df9264` to revision
`gulong-chatbot-runtime-staging-00462-nv9` at 100% traffic. Both health routes
reported the exact SHA. Staging remained return-only with four workers,
canonical JSON persistence, disabled tag mutation, and disabled follow-up
sending. The Secret Manager-backed no-model profile passed both health routes,
all five commerce API contracts, and both ManyChat read contracts.

The exact targeted matrix artifact
`tmp/runtime_v7_staging_1df9264_targeted/runtime_v7_release_candidate_20260912_234140_068089/summary.json`
passed both `promo_toyo_truth` and `nonlinear_product_first` with zero HTTP,
runtime, tool, telemetry, or mechanical failures. The partial run used 203,926
tokens across eleven model calls and measured 51,793 ms p95. The nonlinear case
used 116,368 tokens, down from roughly 228,530 in the prior complete trace. Its
status is red only because a two-case diagnostic intentionally cannot satisfy
the frozen complete scenario-set and compatible-baseline contracts.

Rendered-output review found that the provider-authorized alternative card was
present, but fallback prose still offered to check alternatives in the future.
The guard recognized the already-rendered surface only in the adjacent partial
product branch, not the campaign-only branch used by this scenario. The pending
follow-up applies the same renderability evidence to that branch so it says the
current verified alternatives are shown. The exact no-product positive control,
the invalid-surface negative control, 28 focused commercial tests, and all 1,830
repository tests pass locally. A rebuilt targeted staging replay is required
before the complete matrix.

## 2026-09-13 bounded correctness hardening before the final gate

The complete exact `ed3fb08` matrix made two latent runtime invariants concrete.
The two generic-promo journey failures shared one root cause: the semantic
extractor intentionally returned no reusable fact for a broad intent, and the
main model did not consistently request promo capability. The nonlinear
product-first failure had a different owner: provider-backed products and an
authoritative surface plan existed, but the last-resort payment guard replaced
the structured plan with plain text after composer repair failed.

The local candidate adds canonical transient
`promo_discovery_scope=all_current`, restricted to latest-customer
`question_only` evidence. That typed scope triggers one bounded read-only
general catalog lookup and provider-authorized gallery; raw wording and prior
turns cannot route it. Specific brand, campaign, or mechanic questions retain
their scoped model/tool path. The payment safety boundary now replaces unsafe
text while preserving only renderer refs already selected by the authoritative
composer plan.

Mechanical evidence covers canonical aliases, invalid values, wrong provenance,
wrong relation, raw-wording non-routing, provider refs, transient-state removal,
and final channel rendering. A full integrated regression drives product search
through repeated invalid payment composition and proves the safe response still
contains image-backed product cards and tracked `ps1` buttons. The affected
suite passes 840 tests and the complete repository passes 1,845 tests. The
zero-cost `pr-no-cost` evaluator then passed deterministic core and
intent/observability with zero model calls and zero tokens; its summary is
`tmp/runtime_v7_predeploy_pr_no_cost_20260913/runtime_v7_health_20260913_043255_626278/summary.json`.
Staging deployment, two fresh targeted passes, token projection, and the
unchanged 19-scenario matrix remain pending. Live Cloud Run and the VM were not
changed.

The first exact-staging targeted replay on `9551350` passed both promo journeys
and rendered provider-backed product image cards with tracked `ps1` buttons for
the nonlinear product-first case. That case still failed because the response
reported the generic `renderer_contract_fallback` status after its unsafe model
payment prose was removed. This is a contract-identity gap rather than grounds
to accept generic repair failure.

The bounded replacement gives that exact branch a dedicated
`payment_claim_safe_surface_fallback` status and positive preserved-surface
count. Scenario contract `2026-09-13.1` accepts it only for the reviewed
nonlinear product-first case when product search succeeded, a `ps1` token is
rendered, the dedicated guard event has a positive count, and structured
commercial claims are empty. All other cases still default to `used` or
`repaired`; `renderer_contract_fallback` is still rejected. Focused contract
checks pass 132 tests, the complete repository passes 1,846 tests, and the
replacement zero-cost run `20260913_045334_110399` passes both deterministic
layers with zero model calls and zero tokens. A rebuilt exact-staging candidate
and both targeted passes remain required.

Exact `015d5a3` then passed both targeted repeats at 3/3 with automated CS
21/21 and zero HTTP, runtime, tool, persistence, or telemetry failures. Pass 1
used 289,438 tokens at 53,822 ms p95; pass 2 used 211,816 tokens at 37,949 ms
p95. The nonlinear path exercised the dedicated deterministic fallback once
and normal `used` composer output once.

The prior exact complete run used 1,990,898 tokens, including 230,679 for the
three affected paths. Substituting the two-pass affected-path average of
250,627 projected approximately 2,010,846 tokens, above the hard ceiling. The
bounded cost follow-up therefore removes only `search_promo_catalog` and
`present_promo_gallery` from the main-model schema when latest-message,
question-only `promo_discovery_scope=all_current` has already caused runtime to
load both provider operations. Provider evidence remains in context; named,
brand, campaign, mechanic, historic, and asserted scopes are unchanged. All
1,846 repository tests and zero-cost run `20260913_051207_313105` pass. Exact
staging measurement is required before the complete gate.

The immutable exact-live `50e5975` baseline uses approved scenario contract
`2026-09-11.4`, while candidate correctness now uses `2026-09-13.1`. A bounded
comparison-only bridge allowlists the exact old/new digest pairs. It still
requires baseline artifact integrity plus identical schema, tier, workers,
timeout, feature and health policy, scenario IDs, and journey IDs. Unknown
digests and changed cohorts fail closed. Candidate results are never rescored
against the old contract. Eighty-two focused evaluator tests, all 1,848
repository tests, and zero-cost run `20260913_052713_616335` pass.

## 2026-09-16 exact `00ff8d5` gate result and promotion hardening

Exact staging revision `gulong-chatbot-runtime-staging-00470-jkg` served
`00ff8d5` at 100% traffic. Deterministic tests, commerce and channel-read
dependencies, and the protected ManyChat-hydrated turn passed. The complete
artifact remained blocked, so live Cloud Run and the VM were not changed.

The core matrix passed 18/19. The compound Yokohama payment turn obtained all
three correct provider claims and produced a customer-correct final answer, but
only after `payment_claim_safe_surface_fallback`; the model composer/repair had
omitted the eligible three-month claim. The operational location-uncertainty
journey asked for location again instead of offering contact. Its subsequent
contact capture and planned Moderate qualification worked. The evaluator also
missed an otherwise valid `located` wording variation. Core, operational, and
hydrated usage were `1,911,194`, `1,047,119`, and `70,597` tokens respectively;
the combined `3,028,910` exposed that the former shared cap was mixing three
different workloads. Core p95 was `53,895 ms` and operational p95 was
`75,592 ms`, both below the `95,000 ms` hard latency ceiling.

The local remediation introduces a closed transient semantic
`location_response_status=unavailable_now` signal and a deterministic contact
fallback guarded by established product progression, missing location/contact,
and no competing grounded action. Pure typed payment-policy turns now compose
directly from provider claims only after claim-coverage and ungrounded-assertion
validation; mixed turns retain the normal final composer. The evaluator accepts
the new payment status only with provider authority, all expected typed claims,
and matching visible prose, and its location-request matcher now reads rendered
text/action evidence with reviewed negative controls.

Budget reporting now retains the `2,000,000` core cap and adds explicit
`1,200,000` operational-funnel and `100,000` hydrated-history caps. Combined
usage remains visible; CLI values may lower but cannot raise these limits.
All 1,899 repository tests, scoped Ruff checks, compilation, the quality audit,
and the two-layer no-cost health profile pass. Exact staging deployment and a
fresh targeted then complete evaluator run remain required before live/VM
promotion.

## Learning candidate: Separate semantic recognition from deterministic progression

- Captured: 2026-09-16
- Promotion status: candidate
- Symptom: A green component suite missed a live multi-turn case where the model understood location uncertainty but repeated the location request, while deterministic phrase scoring also produced a false negative.
- Root cause: Recognition, progression, and evaluation were validated separately; no closed semantic signal connected varied customer wording to a bounded contact fallback and the evaluator inspected an incomplete wording set.
- Proposed practice: Represent wording-variable customer meaning as a closed transient signal, enforce business invariants and next-step eligibility deterministically, and score the final rendered surface plus structured evidence with adjacent negative controls.
- Scope/owner: Runtime V7 multi-turn progression and promotion evaluator contracts.
- Positive scenario: After size plus brand or product selection, a customer who cannot provide a requested installation location is offered contact follow-up and exact serviceability stays pending.
- Negative control: Concrete customer locations, store or branch address questions, coverage questions, near-me requests, and turns with competing grounded tools do not trigger the contact fallback.
- Expected benefit: Reduces phrase-specific fixes and false-green component tests while preserving deterministic safety and low-cost regressions.

## 2026-09-16 exact `8ee0f38` complete gate and final local blockers

Exact staging `8ee0f38` passed all deterministic, dependency, authenticated
ManyChat-read, and hydrated-history layers. The complete layer passed 21 of 23
scenarios with zero HTTP/runtime failures. Core usage was 1,814,146 of
2,000,000 tokens, operational usage was 1,008,973 of 1,200,000, and hydrated
history used 92,055 of 100,000. Core and operational p95 latency were 54,202 ms
and 77,931 ms, below the 95,000 ms hard ceiling.

Promotion remained blocked for four bounded reasons. `promo_toyo_truth` exposed
that generic Toyo promo evidence incorrectly cleared an unmatched Toyo
Buy-3-Get-1 scope. `size_brand_typed_location_shortform` rendered one exact
Westlake product but ended with a yes/no installation CTA instead of directly
asking for area. The reviewed unavailable-location picker suppression was
counted as a tool error even though contact progression succeeded. Finally,
the older `50e5975` artifact did not share the current scenario contract.

The local correction binds promo truth to the requested mechanic and preserves
exact-size soft-filter misses only when the product card carries typed promo
mismatch evidence. A single exact customer-backed size+brand result now has a
narrow deterministic city/area postcondition, with multiple products, existing
location/contact, tracked actions, and competing tools as negative controls.
The expected unavailable-location picker redirect reports `not_applicable`;
other rejected plans remain errors. The revised contracts pass 205 focused
tests and all 1,909 repository tests plus Ruff, compilation, and diff checks.
Exact staging and a current-contract live baseline remain pending.

Exact `355f626` targeted staging then passed the Toyo requested-promo case and
the full contact-fallback journey, including `not_applicable` picker redirect
status and planned Moderate qualification. The typed short-form journey also
rendered the reviewed direct city/area question and preserved its one product
surface, but the scorer still rejected `final_composer_status=skipped` even
though deterministic progression intentionally owned that CTA.

Operational contract `2026-09-16.1` closes only that bookkeeping gap. It accepts
`skipped` when positive `location_progression_guard` evidence has the exact
reviewed reason, exactly one rendered product card, a matching preserved
surface ref, and a visible location request. Missing or altered evidence keeps
the normal composer failure. The contract correction and adjacent negative
controls pass 107 focused checks and all 1,913 repository tests. A rebuilt
exact staging targeted run remains required before the complete gate.
