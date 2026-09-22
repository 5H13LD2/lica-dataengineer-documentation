# Release History

This log records CI/CD staging checkpoints and production promotion decisions.
It complements `RELEASE.md`, which owns the release process.

## 2026-09-12 - Scoped promo alternatives pass targeted staging gate

- Normal product-trigger build `87d6e805-e765-49b8-a139-a0d4a2497097`
  deployed exact `1df9264` to staging revision
  `gulong-chatbot-runtime-staging-00462-nv9` at 100% traffic. Both health routes
  reported the exact SHA. Return-only delivery, four workers, canonical JSON
  persistence, disabled tag mutation, and disabled follow-up sending were
  verified.
- The no-LLM health profile passed both runtime endpoints, all five commerce API
  contracts, and both Secret Manager-backed ManyChat read contracts. The exact
  two-case model diagnostic then passed both affected mechanical contracts with
  zero HTTP, runtime, tool, or telemetry failures, 51,793 ms p95 latency, and
  203,926 tokens. The nonlinear case fell from roughly 228,530 to 116,368
  tokens.
- Rendered review found future-tense fallback copy beside an already-presented
  provider-authorized promo card. A local correction now acknowledges the shown
  alternative and passes 28 focused commercial tests plus all 1,830 repository
  tests. That follow-up is not yet rebuilt on staging, so the complete frozen
  matrix remains pending. Live Cloud Run and VM were not changed.

## 2026-09-12 - Canonical Firestore writer verified; promotion remains gated

- Normal staging build `31bc1064-be7d-412c-a1ff-26789008f3f0` redeployed the
  same exact `6458fd6` compatibility code as revision
  `gulong-chatbot-runtime-staging-00459-t6r` at 100% traffic, with only the
  writer setting changed to `canonical_json_v1`. Both health routes reported
  the exact SHA and the return-only safety settings remained intact.
- The deployed transition canary passed legacy read, nested-to-canonical
  switch, exact authoritative raw shape, stale-CAS no-mutation, non-CAS
  creation, and five-document cleanup. Canonical save measured about 79 ms p50
  and 102 ms p95 in the probe, versus about 7,483 ms p50 for the nested map.
- The exact-product smoke passed mechanically and structurally, rendered the
  product image and tracked selection controls, and saved the session in 57 ms.
  The complete serial matrix then passed 19/19 mechanical scenarios and
  133/133 structural CS checks, with zero HTTP, runtime, or tool errors.
  Session persistence measured 79/119 ms p50/p95.
- Live Cloud Run and VM promotion remain blocked. The matrix reported
  2,009,655 tokens against the 2,000,000 ceiling, two retry attempts lacked
  usage telemetry, and its 95-second profile is incompatible with the existing
  120-second live baseline. Including the separately budgeted hydrated-history
  layer, the outer run used 2,101,084 reported tokens. No live or VM change was
  made.

## 2026-09-12 - Firestore compatibility Release A verified on staging

- Normal product-trigger build `585fca36-5bb3-42a0-80f4-0aea6af35f74`
  deployed exact `6458fd6` to staging revision
  `gulong-chatbot-runtime-staging-00458-tj6` at 100% traffic. Both health routes
  reported the exact SHA. The deployed writer was `nested_map_v1`; delivery
  remained return-only with four workers, tag mutation disabled, and follow-up
  sending disabled.
- The protected generated-data canary seeded canonical JSON, read it through
  the deployed dual reader, switched the same document to nested state, and
  verified one authoritative raw representation. Stale CAS made no mutation,
  non-CAS session creation passed, and all five exact documents were removed.
- The nested-map comparison still reproduced the environment-specific tail at
  about 6,115 ms p50, while canonical JSON measured about 60 ms. Release A
  establishes the rollback bridge but intentionally does not migrate serving
  sessions. Live Cloud Run and VM remain unchanged.

## 2026-09-12 - Firestore representation mechanism confirmed on staging

- Normal product-trigger build `302bbf28-1c46-4a5a-b093-3744bc823c82`
  deployed exact `90173d2` with digest
  `sha256:fb37c0763cbf238dc45861532ca00256215e8fa24f99e87018f1e9e594a66c80`.
  Staging revision `gulong-chatbot-runtime-staging-00457-8r6` is ready at
  100% traffic; both health routes report that SHA. Return-only delivery, four
  workers, tag mutation disabled, and follow-up sending disabled were verified.
- Generated 40 KiB runtime-shaped state measured 6,637/6,690 ms p50/p95 CAS
  save as a nested map, versus 58/58 ms as canonical JSON and 41/47 ms as gzip
  JSON. At 140 KiB, the corresponding p50/p95 values were 18,626/19,034 ms,
  91/120 ms, and 61/72 ms.
- Nested commits consumed 5.86-5.91 CPU seconds and about 339/31/3 GC cycles
  per 40 KiB write, rising to 15.59-16.20 CPU seconds and 1,212/110/9 cycles at
  140 KiB. The scalar variants recorded zero commit-side GC cycles. Every
  round-trip/hash/revision check and stale-CAS control passed, and a final
  collection-group read confirmed zero benchmark documents remained.
- This confirms a versioned scalar state representation as the preferred
  mitigation direction. It does not yet change production persistence; reader
  compatibility, rollback, migration, real-state compression benefit, and a
  targeted evaluator rerun remain separate gates. Live Cloud Run and VM were
  not changed.

## 2026-09-12 - Firestore transport observer on staging; CPU split pending

- An observability-only candidate preserves the existing transactional CAS and
  Firestore retry policy while exposing each underlying begin/commit RPC
  attempt, retry classification, process/instance identity, active-save
  concurrency, process CPU time, and retry-backoff/wrapper remainder.
- The protected no-model probe is authenticated, staging-only, generated-data
  only, and limited to dedicated benchmark collections with exact cleanup.
  Cloud Build now accepts an explicit `GUNICORN_WORKERS` substitution so the
  same SHA can be compared at four versus one worker through the normal staging
  trigger.
- Local Firestore proof completed with one successful commit per save: 40 KB
  measured 314/333 ms p50/p95 and 140 KB measured 452/455 ms. Staging serial
  probes stayed below 0.36 seconds and controlled concurrency stayed below
  1.32 seconds; reducing from four workers to one did not improve the measured
  distribution, so four workers were restored.
- Exact staging product replay passed but reproduced an 18.16-second save. It
  contained one successful 17.66-second commit, no retries, and only 17 ms of
  wrapper/backoff remainder while the worker accumulated 16.93 CPU seconds.
  The next observability-only revision splits commit-thread versus other-thread
  CPU and records GC/scheduler counters. All 1,786 repository tests pass. Live
  Cloud Run and VM remain unchanged and unapproved.
- Exact `bd050fa` replay confirmed the commit-thread mechanism: one successful
  17.75-second commit consumed 16.35 seconds on that thread, versus 20 ms on
  other threads, while cyclic GC ran 487/44/2 times and collected zero objects.
  The runtime-shaped 41 KB document is materially deeper and more fragmented
  than the simple size-matched probe. This supports a separate compact/blob
  persistence design or narrowly controlled GC experiment; retry timeout and
  production persistence behavior remain unchanged.

## 2026-09-11 - Firestore index fan-out bounded; save diagnostics pending staging

- An isolated paired benchmark used synthetic evaluator state and benchmark-only
  collection groups. With 3,462 nested leaves changed per alternating 141 KB
  write, the normal recursively indexed path measured 647/695 ms p50/p95 and a
  temporary `strategy_state`-exempt path measured 466/479 ms. The approximately
  0.2-second absolute difference cannot explain the 20-35 second staging saves.
- No serving or evaluator collection index was changed. A compact/delta storage
  rewrite is not being promoted on this evidence. The next candidate adds only
  content-free transaction attempt/read/body/commit-overhead diagnostics to the
  existing transaction path. Payload-size measurement runs only after a slow or
  failed store operation and records its own overhead. The guarded benchmark
  runner pre-registers exact cleanup targets before its first write and supports
  reciprocal variant ordering.
- All 1,780 repository tests pass locally. Staging deployment through the normal
  product trigger and one exact product-path diagnostic remain pending. Live
  Cloud Run and the VM remain unchanged and unapproved.

## 2026-09-11 - Hydrated-history evaluator deployed to staging; gate held

- Candidate `9aa1c46` was promoted through the normal `product` trigger.
  Regional Cloud Build `3a1682e7-6eb5-4b74-9ac5-414e482faab1` succeeded with
  digest `sha256:9961eb8dee678b3061a98ef323b1fde47d6743f312926f42232181d24462588a`.
  Staging revision `gulong-chatbot-runtime-staging-00436-kg4` serves that exact
  SHA at 100% in return-only mode; both health routes report the expected
  staging identity.
- The green no-LLM staging artifact passed core health, five commerce
  dependencies, and both ManyChat channel reads. A prior local wrapper attempt
  generated a false 401 by treating the JSON secret as an array rather than
  selecting its actual object; no credential rotation was required.
- The authenticated hydrated-history turn reached the exact staging revision,
  returned HTTP 200, recorded three model calls and 59,725 tokens in 39,090 ms,
  and confirmed a successful loader refresh. It correctly failed the gate
  because account `4843256405786522` last interacted on August 10, outside the
  30-day runtime window, leaving zero loaded/model-facing messages. No later
  smoke, in-depth, live, or VM promotion was run.
- The compatible live `50e5975` baseline is now available under scenario
  contract `2026-09-10.3`: 67 model calls, 1,520,097 tokens, p95 90,296 ms,
  integrity pass, and 11/19 legacy correctness. It is comparison evidence, not
  an approval artifact.
- Follow-up candidate `f965edf` deployed through Cloud Build
  `0d112e37-f060-4658-af55-304d839ce0b2` to staging revision
  `gulong-chatbot-runtime-staging-00437-h9x` at 100%, image digest
  `sha256:95736424d001597fa29bd7f2188127af981104ccd78affcf16457ff9972d8d32`.
  Its exact protected turn successfully refreshed six fresh channel messages
  into eight model-facing messages and stayed return-only.
- Candidate `bff16bd` deployed through Cloud Build
  `76257818-6194-42c8-b99c-1199d6e49d50` to staging revision
  `gulong-chatbot-runtime-staging-00438-g88` at 100%, image digest
  `sha256:06d3aa7fb415a2e9eddac612f04b0f632ba700f9680aa782497a97a75adc08a3`.
  It passed all deterministic/API/channel/hydration layers. Its first complete
  run was held: three concurrent model workers caused one client timeout and
  one transient 502, while a serial affected-path rerun returned seven of seven
  HTTP 200 responses with p95 75,605 ms and exposed two general hardening needs.
- The next candidate enriches uniquely identifiable partial installment scopes
  before provider execution/cache identity and sanitizes only duplicate prose
  already owned by a supporting replacement surface. Scenario contract
  `2026-09-11.4` records the updated pre/post hydration boundary. No live Cloud
  Run or VM promotion has occurred; a fresh exact staging build, compatible
  full-tier live baseline, and complete green gate remain required.
- Candidate `85fbf79` deployed through normal product-branch Cloud Build
  `b1cfcc7c-32bc-4b54-bb1b-3938ef59ed50` to revision
  `gulong-chatbot-runtime-staging-00442-fzv` at 100%, image digest
  `sha256:e50b59d9acf049c889a507c128a0f97ef6080ae9a9c4dd95331e2d07a4aaf30c`.
  Both health routes identify exact staging `85fbf79` in return-only mode.
- The exact complete run passed all 19 mechanical scenarios with zero HTTP,
  runtime, or tool errors and 100% telemetry. The protected hydration layer
  also passed with the fresh test-account history. Promotion remains held:
  combined usage was 2,008,842 tokens (8,842 above the approved budget), p95
  was 83,476 ms and therefore remained a concern, three turns triggered the
  directness concern, and an operator-supplied 95-second request timeout did
  not match the exact live baseline's 120-second profile. A corrected isolated
  channel-read rerun passed both ManyChat probes; the prior 302 came from an
  incorrectly assembled local URL, not the deployed loader.
- Prompt-projection candidate `daca2ea` deployed through normal product-branch
  Cloud Build `b36a2c60-0efc-4aef-ad42-8ab4ee076678` to staging revision
  `gulong-chatbot-runtime-staging-00443-bwd` at 100%, image digest
  `sha256:8c90148c3abcf62d0a601edace890fc0dbe4901d926fe103c0be0f0de2dc59c1`.
  Both health routes reported exact staging identity; delivery remained
  return-only, follow-up sending disabled, and ManyChat tag mutation disabled.
- Its complete serial gate stayed within the approved hard budgets at
  1,772,902 combined tokens and 81,736 ms p95, and passed all deterministic,
  API, channel-read, hydration, telemetry, integrity, and baseline checks. It
  remained red at 17/19: the explicit head-office case produced a non-renderable
  response and the bare store-location case incorrectly volunteered the head
  office. Live and VM promotion did not occur.
- The next local correction adds a narrow deterministic business-location
  postcondition for isolated no-tool turns. Explicit address requests receive
  the canonical reviewed address when model output is unusable; bare
  store/branch requests cannot substitute that address and ask one city/area
  question instead. Mixed, tool-backed, active-choice, selected-product,
  fulfillment, and non-location office turns are negative controls. Real JSON
  arrays receive the existing bounded format retry while bracketed product-menu
  prose does not. Candidate `b180a74` was deployed by normal product-branch
  Cloud Build `cab18f89-97a0-4680-a4c7-d9d3a348cbf6` to staging revision
  `gulong-chatbot-runtime-staging-00444-rfn` at 100%, image digest
  `sha256:30b625ade499dff672c81de1e1637aaa53d92e478c8fa90115fd67c5ce34f6b5`.
- Its five-case targeted run passed. The complete run remained red at 17/19:
  the bare store-location turn invoked the installation-location picker before
  the post-render guard, and the delivery composer dropped the required
  7-10-day fact. The run stayed inside the approved 95,000 ms and 2,000,000
  token hard ceilings; one root-health request exceeded its separate API SLA.
- The pending candidate suppresses all tool schemas before planning for
  isolated business-location goals, using the general semantic disposition and
  current state rather than one phrase. It also carries typed provider-required
  FAQ facts through the turn plan and validates natural-language coverage after
  composition. Candidate `b451b77` deployed through normal Cloud Build
  `f8073324-424e-4a94-a95f-163c2e823ae0` to staging revision
  `gulong-chatbot-runtime-staging-00445-m7q` at 100%, digest
  `sha256:7ce4d90763f87eee3d42fc1e4cf4749fa48d49b9156c50f9bd1827ec2c6029ce`.
- Both delivery cases passed. After two client-side DNS failures were isolated,
  explicit address passed and bare store location proved pre-planning tool
  suppression, but the channel renderer reintroduced the original model text
  because it preferred `assistant_text` over the guarded final field. The next
  local correction synchronizes those fields and passes all 1,764 repository
  tests. Live Cloud Run and VM remain unchanged pending another exact staging
  deployment and complete green gate.
- Candidate `ffde9fe` deployed through normal Cloud Build
  `26142079-ec29-4702-9a2b-3aa1561516d5` to staging revision
  `gulong-chatbot-runtime-staging-00446-ctn` at 100%, image digest
  `sha256:049408ec3646d7b1befa245a673dfe90e1289e3daa5e450f44c2ccf4986df85d`.
  Both location cases passed on that exact revision. The complete matrix then
  passed all 19 mechanical contracts with zero HTTP/runtime/tool errors, but
  promotion remained blocked because p95 was 95,341 ms, 341 ms above the
  approved hard limit. The run also had two structural duplicate concerns and
  a 12.73% matched-action token warning.
- The reported 1,886,073 combined-token result is not accepted as complete
  release evidence. A post-run audit found that deployed aggregate telemetry
  omitted paid background-extraction and active-memory calls even though their
  metadata existed separately. A local hardening now includes all model-backed
  components, rejects missing component usage or unmetered retries, emits
  supplemental normalized LLM spans, and exposes per-tool latency. All 1,768
  repository tests pass. A new exact staging build and complete rerun are
  required; live Cloud Run and the VM remain unchanged.
- Telemetry candidate `3479955` deployed through normal product-branch Cloud
  Build `5df69ffb-4f13-4273-adf8-168b97ac0606` to staging revision
  `gulong-chatbot-runtime-staging-00448-sg7` at 100%, image digest
  `sha256:bf2bb276df9b227a8b67d1dd2282fe1573536921ec9896e7c2fc58eb2e58cd0d`.
  A six-response serial diagnostic measured 783,534 complete tokens and 91,253
  ms p95. Server phase telemetry localized the dominant non-model delay to
  session persistence: 29,460 ms p50 and 31,908 ms p95, versus 484 ms p95
  client/transport overhead. The run was diagnostic only and failed one journey
  composer contract plus two missing deterministic-surface latency records.
- The next local correction replaces the full Firestore session transaction
  with an atomic document-update-time precondition. Revision mismatch and
  concurrent-write conflicts still fail closed, and only the caller-owned lock
  is cleared. Local state assembly and remote save are timed separately;
  deterministic promo-surface projection records zero-millisecond latency.
  Live Cloud Run and VM remain unchanged pending local and exact-staging proof.
- That conditional-write experiment deployed as exact `e047694` through build
  `42abd47d-9394-43de-8161-7084ec509b48` to revision
  `gulong-chatbot-runtime-staging-00449-6gs`, digest
  `sha256:6f0bbf0550aade190a88e49fbbdbf629c4c93eec52e353c929ad25b97019c85b`.
  The matched six-response rerun passed both selected mechanical paths and all
  14 structural CS checks with zero operational or telemetry errors, using
  740,697 tokens. It did not improve the target phase: remote session save was
  31,834/35,190 ms p50/p95, versus 29,460/31,908 ms before. The conditional
  write is therefore reverted; phase splitting and deterministic surface
  latency remain. No live or VM promotion occurred.
- Safe revert `8ed58df` deployed through normal product build
  `e3732e12-6b17-4a0b-9ee2-7085158351ae` to staging revision
  `gulong-chatbot-runtime-staging-00450-6gv` at 100%, image digest
  `sha256:5f0d0cd91a5b47e7262fa1144193da1b1f9768cc637835fc2e7615afea636668`.
  Both health routes returned HTTP 200 with exact identity; return-only,
  disabled tag mutation, and disabled follow-up sending remain verified. The
  complete promotion gate is still blocked pending storage-safe latency work
  and a fresh full exact-target run under the 95,000 ms/2,000,000-token limits.

## 2026-09-10 - Ambiguous store-location contract corrected; no deployment

- The feature branch now asks for the customer's city/area on a bare request
  such as `location ng store?`, without volunteering the Makati head-office
  address or presenting installation province choices. Explicit head-office
  address and explicit installation/service-area requests retain separate
  grounded paths.
- The pre-verified corpus is now scenario contract `2026-09-10.3` with 16
  single-turn cases and three journeys. This entry records implementation only;
  staging, live Cloud Run, and the VM remain unchanged pending a fresh
  model-backed evaluation.

## 2026-09-10 - Promotion-health policy retuned; no deployment

- The provisional absolute evaluator ceilings were explicitly retuned to
  `95,000 ms` p95 latency and `2,000,000` total tokens. No runtime branch was
  promoted and no Cloud Run or VM traffic changed for this evaluator-only
  policy update.
- The existing exact staging observation (`91,788 ms`; `1,860,861` tokens) is
  within the new numerical ceilings, but its immutable artifact retains the
  former policy. Promotion still requires a fresh complete exact-target run,
  compatible baseline evidence, and all selected API dependency gates.

## 2026-09-10 - Automated promotion evaluator and customer-correctness staging gate

- Follow-up hardening `0e990e7` adds scenario contract `2026-09-10.2`,
  provider-backed product-promo claim checks, bounded negative promo scope
  after accepted composition, known-location and action-specific journey
  handling, and a tester provider-call ceiling of ten. Cloud Build
  `cc7673d7-4e3a-480a-8383-4e4703a17bec` succeeded with image digest
  `sha256:6a69abc67f99f7f694c38a3b20562d8dbe229da83150c04b4bac93afcba9ed0d`.
  Revision `gulong-chatbot-runtime-staging-00435-2b2` serves exact SHA
  `0e990e7` at 100%; both health routes are healthy and identify staging, with
  follow-up sending disabled.
- Runtime/core health plus product search, installation partners, payment and
  transaction catalogs, and installation-slot read contracts passed. Channel
  reads remain blocked until a dedicated synthetic ManyChat contact is
  configured; no customer contact was substituted.
- The complete staging cohort executed all 15 single-turn cases and three
  journeys with zero HTTP, runtime, or tool errors, 100% telemetry, and exact
  target/contract/integrity checks. Its initial mechanical score was `17/18`;
  the sole failure was an evaluator rule that required hydrated Yokohama/Pay
  Later fields to exist in the model's pre-hydration BPI call. The corrected
  boundary requires only the authored method before hydration and all scoped
  fields at provider execution; a fresh deployed turn passed that contract.
- This is still a promotion hold. The complete cohort recorded p50/p95/max
  latency `34,037/91,788/113,040 ms`, 82 model calls, and `1,860,861` total
  tokens (`318,207` cache-read), exceeding the provisional p95 and total-token
  hard limits. A fresh compatible `50e5975` baseline was not run because the
  candidate already failed absolute gates. Live Cloud Run and the VM remain
  unchanged; BigQuery, ManyChat mutation, scheduling, and email were not run.
- Candidate `5b227d8` adds a selective, pre-verified promotion-health evaluator
  and fixes the integrated customer-correctness defects it exposed. Explicit
  delivery questions now use grounded policy retrieval without claiming that
  an exact address is serviceable, and compound payment questions preserve the
  customer's method, brand, and option through hydration, deduplication,
  provider execution, and composition. Commercial evidence is derived from
  authoritative provider results rather than generated prose.
- The evaluator separates deterministic, API-contract, and metered-model
  layers. It validates target identity, tool routing and arguments, provider
  outcomes, composer use, canonical obligation IDs, guided surfaces when
  enabled, Moderate/High-intent observability contracts, latency, tool/runtime
  errors, token telemetry, immutable artifact integrity, and deterministic CS
  quality proxies over versioned human-verified scenarios. Equivalent
  commercial claims are canonically deduplicated, while distinct scopes remain
  independently required.
- Local validation passed the full repository suite (`1,698 passed`), changed-
  file Ruff, focused positive and negative controls, JSON checks, and the
  behavioral/customer-facing release audit. This specifically includes the
  complete compound sequence that the earlier component-only tests missed:
  model calls -> hydration -> cache key/deduplication -> provider result ->
  composer -> typed evidence.
- Staging Cloud Build `d32db396-6cec-42a6-96b1-e7f370bd38ae` produced digest
  `sha256:8ac369ae981a0cc0ce415b3e03006d5652a31f5c47705de6908a89423e146621`.
  Revision `gulong-chatbot-runtime-staging-00434-k6m` serves exact candidate
  `5b227d8` at 100% in return-only mode with tags and follow-up sending
  disabled; both health routes report the expected staging identity.
- The final fresh-session model smoke passed `3/3`: business contact,
  delivery policy, and compound Yokohama/Home Credit payment grounding. It
  passed all `21/21` automated CS structural checks, had zero HTTP, runtime,
  and tool errors across five tool calls, and recorded complete latency and
  usage telemetry. P50/p95/max response latency was
  `25,271/36,191/36,191 ms`; ten model calls consumed `152,879` total tokens,
  including `17,960` cache-read tokens. The immutable evidence digest is
  `90b69879c5816d3cbe7be5bc7494753595d9eabb01c1976ce2b5e828472378d0`.
- The smoke is intentionally classified `diagnostic_pass`, not
  `ready_for_promotion`. External API dependency contracts are not yet
  configured for this environment, the in-depth/complete varied corpus and a
  compatible `50e5975` baseline comparison have not been run, and per-model
  monetary cost is unavailable from deployed tester telemetry. Artifacts are
  currently stored under the local gitignored
  `tmp/runtime_v7_layered_health/` tree; the documented private immutable GCS
  target exists as a storage contract, but its uploader and scheduled email
  reporting are deferred. No live Cloud Run traffic or VM deployment changed,
  and no BigQuery work was performed.

## 2026-08-27 - Final-composer repair-cause observability release

- Release A is analytics-only. Final-composer spans retain
  `component="final_composer"` and now expose stable `attempt_kind`,
  `repair_reason`, and sorted typed `violation_types` in normalized span
  metadata. Prompts, context, models, schemas, retries, validation, rendering,
  delivery, and customer-visible responses are unchanged.
- Local validation passed the focused `5/5` release slice and the full Runtime
  V7 suite (`1502 passed`). Ruff, compile, JSON, diff checks, and the strict
  release audit passed; the audit had only the expected README informational
  reminder.
- Staging Cloud Build `323caeab-033f-4341-9e1d-ad4eed30df80` produced digest
  `sha256:2d6921675093a17de21e6b254aed66381db39c49b16bee3907679fac580e338c`.
  Revision `gulong-chatbot-runtime-staging-00429-rh9` served candidate
  `d05b05c` at 100% in return-only mode with tags and follow-up sending
  disabled. Both health routes passed, three analytics-enabled requests
  completed, and no revision error or HTTP 5xx logs appeared.
- A bounded three-case live-model matrix passed `1/3` on staging. The hotline
  case passed; delivery-policy and Yokohama payment-contract checks failed.
  The exact same `1/3` pattern and failure categories reproduced on the
  pre-patch live `feb88a4` baseline, so the two failures are recorded as
  existing quality debt rather than a Release A regression.
- Promotion SHA `54eec74` passed the focused `5/5` test slice and strict release
  audit. Live Cloud Build `e0e87d06-1229-4912-8809-5d97de20f054` produced
  digest
  `sha256:d2ef953b75c679073d35a853cc64872a892708daf87b4cc0428750a0f3bec8b7`.
  Cloud Run revision `gulong-chatbot-runtime-live-00105-7tr` served the exact
  SHA at 100%; both health routes and a synthetic analytics-enabled return-only
  probe passed, with no revision errors or HTTP 5xx logs.
- The same immutable live digest passed an alternate-port VM candidate health
  check, then replaced `gulong-chatbot-runtime-shadow`. Public VM health and a
  loopback return-only probe passed on `runtime_host=vm-live`; restart count,
  traceback count, and exception count remained zero. The prior image is
  retained as
  `gulong-chatbot-runtime-shadow-rollback-feb88a4-20260827T1912PHT`.
- VM restart metadata now points to the exact digest and `54eec74`, while all
  three service definitions, live/send-content mode, tags, follow-up enabled,
  and the existing 100% follow-up setting were preserved. Disk use was 87%
  with 4.1 GB free after retaining rollback images.
- Through `2026-08-27 19:17:36` Manila, the new VM release recorded eight
  completed request rows: five successful live deliveries, one synthetic
  return-only skip, and two intentional suppressions. Six VM composer spans
  and one Cloud Run composer span carried `attempt_kind="initial"`; no natural
  repair occurred in the bounded monitoring window, so non-initial cause
  labels remain deterministically verified but not yet observed under live
  traffic.

## 2026-08-04 - Promo execution-context efficiency and VM release

- Candidate `dc1ec51` consolidates promo search and normal gallery selection in
  one model-owned contract, lets Runtime complete a requested reviewed gallery
  from current provider refs in the same tool round, and replaces repeated full
  promo retrieval payloads in planning, composition, audit, and repair with one
  compact authority contract. It does not impose a hard call cutoff, remove
  safety retries, or weaken catalog/product authority.
- Local validation passed `1,349` repository tests and `728` focused promo,
  progression, turn-plan, and release-gate tests. Changed-file Ruff, compile,
  diff, and the strict behavioral/customer-facing change audit also passed.
  Repository-wide Ruff still reports 18 pre-existing findings in untouched
  legacy files.
- Cloud Build `a59f6a4a-1dbc-437b-915a-76b66caf7805` produced immutable digest
  `sha256:b7d01c1adfd8a501df890c4ba3af8404d267fc0a359e125494fa1dddf8d3c5eb`.
  Staging revision `gulong-chatbot-runtime-staging-00381-k8j` served `dc1ec51`
  at 100% with return-only delivery, tags disabled, and follow-up sending
  disabled.
- Three fresh focused promo cases passed `3/3`; the complete varied release
  matrix then passed `16/16` across 13 single turns and three multi-turn
  journeys. Human review of all rendered turns found the responses factual,
  grounded, and usable casual Taglish. Promo and product cards retained current
  provider refs, trusted images, and tracked actions.
- In a like-for-like Apollo promo+price probe, the candidate fell from eight
  calls and `106,480` tokens to six calls and about `90,000` tokens. Brandless
  discovery remained four calls/about `49,000` tokens, while unmatched-brand
  promo alternatives remained five to six calls/about `55,000-69,000` tokens.
  This is meaningful containment for compound promo/product turns, not a claim
  that the overall execution design is fully optimized.
- The final matrix still exposed repeated payment FAQ provider calls and verbose
  first-turn intake on some promo-card journeys. These are existing follow-up
  simplification targets rather than correctness or release blockers. The
  approved customer-facing VM remained on `3c9c1b7` during staging validation.
- Promotion merge `712b605` passed the same `1,349`-test repository gate plus
  changed-file Ruff, diff, and strict release audit. Main Cloud Build
  `c6e87ac1-9348-4db2-b2aa-6f2cc54b5e72` produced immutable digest
  `sha256:63e71bd24595ea6ea8472094e6f2e451cc4738aba0aa8b6328b059e5d9aec72b`.
  Live Cloud Run revision `gulong-chatbot-runtime-live-00081-sf5` is healthy at
  the same SHA behind tag `rc-712b605` with 0% traffic; existing Cloud Run
  customer traffic remains unchanged.
- The VM alternate-port candidate passed health and a current promo-card smoke:
  four model calls, `48,905` tokens, two trusted images, six tracked `pc1`
  actions, and return-only delivery. The live VM then moved to the exact digest
  and retained `3c9c1b7` as
  `gulong-chatbot-runtime-shadow-rollback-3c9c1b7-20260804T1300PHT`.
  Public health reports `712b605`, `service_environment=live`,
  `runtime_host=vm-live`, live delivery/tags, and the existing 100% follow-up
  setting. Container restarts remained zero.
- VM restart metadata had still referenced `d0da955`; the release corrected
  only `chatbot_runtime.image`, `RELEASE_VERSION`, and `GIT_SHA` to the new
  immutable release. Chat-analysis, manychat-utils, and every other runtime
  setting were preserved.
- The first six real post-cutover requests had zero runtime errors and zero tool
  failures. The two promo-related turns averaged `5.5` calls and about `73,000`
  tokens versus the prior six-hour promo cohort's `7.24` calls and about
  `99,000` tokens. The dominant `search -> gallery -> product` sequence used
  five calls and `58,326` tokens versus the prior cohort's `7.24` calls and
  `100,153` tokens. This early sample supports keeping the release, but it is
  too small to claim the final sustained savings rate.

## 2026-08-04 - August monthly promo catalog and VM release

- Marketing source folder `1K_kQBsFzRg42mlCgka1RSDCv_uYqXCVR` was compiled
  into monthly catalog `catalog-202608-5f4ddb23ee0c-v2`. The source package has
  six reviewed promos: BFGoodrich PHP 1,000 Off, Michelin PHP 1,000 Cashback,
  Apollo Buy 3 Get 1, Michelin Buy 3 Get 1, Michelin Passion Experience, and
  The Gulong Double Warranty. The Michelin cashback claim preserves the exact
  source Google Form URL.
- The August review workbook completed `11/11` AI evaluations, `11/11` human
  reviews, and `6/6` eligibility reviews. It was approved by
  `LICA Data Team <datateam.licagroup@gmail.com>` at
  `2026-08-04T01:19:55+08:00`, published successfully, and became the active
  Firestore catalog. The hourly scheduler remains intentionally paused.
- Runtime commits `52f0e2f..3c9c1b7` make catalog evaluation and approval
  monthly, allow source-backed brandless warranty entries without weakening
  the evidence requirement for other commercial promos, preserve operational
  claim URLs, and route exact active catalog titles to promo search before
  general FAQ handling.
- Local validation passed `1,343` repository tests, `63` focused promo tests,
  changed-file Ruff, compile, and diff checks. The exact staging revision
  `gulong-chatbot-runtime-staging-00373-b9f` passed the four-case/journey promo
  gate (`4/4`) plus human review of the Michelin claim-form and Double Warranty
  responses.
- Cloud Build `7269d145-c171-4c72-b778-577a97a9b0e5` produced immutable digest
  `sha256:6c66bd0ebb27ac077cc2f564dec5b88565c64943a96ce375923e682b03690aed`.
  Commit `3c9c1b7` is on both `product` and `main`. No-traffic live revision
  `gulong-chatbot-runtime-live-00153-qog` is healthy at the same SHA; customer
  Cloud Run traffic remains unchanged on `gulong-chatbot-runtime-live-00073-7zl`.
- Promo sync job generation `16` is pinned to the same digest without
  re-executing the already-published August catalog. The customer-facing VM
  passed its alternate-port candidate smoke (`1/1`) and post-cutover smoke
  (`1/1`), then served `3c9c1b7` with production delivery, tags, and follow-up
  sending restored. It had zero restarts and zero failed turns at verification.
  The prior `c484319` container is retained as
  `gulong-chatbot-runtime-shadow-rollback-c484319-20260804T1035PHT`.

## 2026-08-03 - Composition simplification release candidate

- Candidate `4aca4b9` built successfully as Cloud Build
  `24d1efce-45be-4c25-bf56-74ebbdcaa53c`, immutable digest
  `sha256:2910883de89417ffa8f88475c5cddd07f5d83a325a22a189ccfc41bc107be54d`,
  and staging revision `gulong-chatbot-runtime-staging-00360-tpx` at 100%.
  Both health routes reported the exact SHA with return-only delivery, tags
  disabled, and follow-up sending disabled.
- The bounded five-case live-model matrix passed `4/5`. Direct Apollo promo,
  proactive product/promo composition, compound Yokohama payment, and
  business-contact answer-only turns passed mechanically and human-CS review.
  Delivery-policy grounding called the correct provider but fell back to a
  vague clarification after its initial and repair audits disagreed about
  answer-goal alignment. Production and the VM were held.
- The follow-up patch preserves provider-authored facts in safe fallback when
  the first normal-response audit found the answer goal relevant; an initially
  misaligned FAQ remains omitted. The rule is typed and generic, adds no model
  call, and has positive delivery-policy and unrelated-FAQ negative controls.
  Local validation passed `1,263` Runtime V7 tests and `1,326` repository tests.
- Corrected candidate `7f2d3c5` built successfully as Cloud Build
  `11fe82b7-1cfd-41b9-ab8a-71d70e496ede`, immutable digest
  `sha256:5d92860205d3c157fcb19416a7468b81847e5fb33f60fcdbca11649476a78434`,
  and staging revision `gulong-chatbot-runtime-staging-00361-v9r` at 100%.
  Both health routes reported the exact SHA and safe staging flags.
- Two fresh delivery-policy replays passed. One repair composed the complete
  Greater Manila/Lalamove/7-10-day answer with BGC explicitly pending. The
  other repair introduced an unsupported tire-selection prerequisite; the new
  bounded fallback removed that process claim while preserving every authored
  delivery fact and the exact-case-pending boundary.
- The exact corrected-SHA sweep passed `4/4`: Apollo direct promo, nonlinear
  product/proactive-promo, compound Yokohama payment, and business contact.
  Human-CS review found the responses factual, casual Taglish, direct, and free
  of unrelated location/product CTAs. The product result contained the complete
  price list plus one three-card square gallery; every card had a trusted catalog
  image, matching SKU/order, and tracked `ps1|...` action.
- Cost telemetry remained bounded without a hard call cutoff: product-first
  used four calls because one unauthorized composer claim label required
  mechanical repair; compound payment used six, direct promo six, contact four,
  and both delivery paths six. The semantic failure path used one evidence-only
  recomposition and one re-audit, not the former broad repair followed by a
  second semantic recomposition. Larger general FAQ/contact system-prompt and
  main-loop simplification remains a measured follow-up after production cohort
  evidence, not another pre-release redesign.
- Candidate `7f2d3c5` is approved for promotion. The following documentation-only
  commit records this evidence and requires health/SHA verification but no
  repeated live-model matrix because it changes no executable file.
- Documentation commit `2552745` built successfully for staging as Cloud Build
  `abf96622-28b6-4f1b-88ee-6752b918d1d4`, revision
  `gulong-chatbot-runtime-staging-00362-hkw`, and digest
  `sha256:d03a615e73b9200afdb960e8c668f2a1c961eb793d54cea91b11a1af0d177e03`.
  The main build `f9d688ce-340f-4030-a71e-15c13faa3c2f` produced digest
  `sha256:7962d96759c7c09fe1295ac0d2eca82c182400041aa9d81a93ea3b093ae06b79`
  and zero-traffic live revision `gulong-chatbot-runtime-live-00076-4hx`.
  The customer-facing VM then served that immutable digest at SHA `2552745`
  with zero restarts; `1b165da` and `66be12f` rollback containers were retained.
  Promotion metadata is also recorded in annotated tag
  `runtime-v7-2026-08-04-2552745`.
- Early production monitoring showed zero request/error-log matches and zero
  tool failures. A like-for-like three-tool promo turn improved from ten calls
  and 104,216 tokens on `1b165da` to eight calls and 83,400 tokens. Human review
  then caught one successful campaign-catalog no-match incorrectly widened to
  a global product quantity-promo denial. The follow-up candidate scopes every
  negative to its provider and requires exact-size product evidence for product
  promo price/applicability; it adds no call and must pass a new staging gate
  before replacing `2552745` on the VM.

## 2026-08-02 - Gallery, FAQ, payment, and promo-action release candidate

- Candidate `4ad4bb2` built successfully as Cloud Build
  `5eaace40-6c51-425f-907d-b5c39c30316b`, immutable digest
  `sha256:71cf5bf346e546678b7ff1513de76f9974723be60ea2e87c33931297983a6abf`,
  and staging revision `gulong-chatbot-runtime-staging-00352-vgv` at 100%.
  Exact health metadata matched the candidate. Three fresh Yokohama installment
  probes passed, the full matrix passed `16/16`, and the independent varied pack
  passed `9/9` across two product sizes, multiple brands, named/category
  payments, DOT, and quotation journeys.
- Human-CS review nevertheless held production. A tracked Promo Details click
  exposed generic ongoing-promo FAQ copy instead of its reviewed selected-promo
  mechanics. Diagnosis found that the enabled turn planner bypassed the
  existing deterministic information renderer; later FAQ auditing safely but
  incorrectly made the generic FAQ the visible answer.
- Repair `57c0c1f` gives any validated informational promo action precedence
  over general planning in both ordinary and batched interaction modes. It is
  action/evidence based, adds no normal-path call, and does not widen promo
  authority. Local gates passed `59` focused promo tests and `1,311` repository
  tests. Production remains unchanged until this exact repair is rebuilt and
  the complete staging/human-CS gate is repeated.
- Documented candidate `00c3609` built as Cloud Build
  `9fa531f6-d6d9-44e4-b1bf-0e2bd0f37e21`, digest
  `sha256:a7c8b0d988ece630c21a48af236b4f1f159e7012d66095546006ee1dfa2dc257`,
  and healthy 100%-traffic staging revision
  `gulong-chatbot-runtime-staging-00353-p8g`. Three fresh Promo Details
  journeys passed and visibly retained exact reviewed mechanics with zero
  click-turn calls. The complete matrix finished `14/16`: its About Brand
  assertion was stale after the intentional zero-call renderer, while one of
  four delivery-policy runs reached a factually safe authored fallback because
  successive semantic audits disagreed over whether an uncertainty boundary
  was an unsupported validation process.
- The follow-up repair clarifies that distinction generically and updates the
  matrix to accept About Brand only when the exact published profile is visible
  with no composer/tool call. Focused tests passed `125`; the repository passed
  `1,312`. A new exact staging build and repeated complete matrix remain gates;
  production is still unchanged.
- Three exact `f013c57` delivery repeats remained factually safe but only one
  composed normally; two exhausted the model audit and used the authored FAQ
  fallback. The next candidate types this already-guarded path as
  `answer_goal_safe_fallback` and requires its guard event, failed audit, and
  successful FAQ authority in the mechanical gate. Generic renderer fallbacks
  are still rejected. Focused typed-fallback regressions passed `68` tests;
  the full repository passed `1,313`. Production remains unchanged pending a
  new exact staging gate.
- Candidate `ab943a7` built as Cloud Build
  `4bbdd213-d7a0-4789-b210-36a503b3c3df`, digest
  `sha256:5c0fab221c0c56815edda38e2199660527423894b3a4ad21a379a6466cdd5732`,
  and healthy 100%-traffic staging revision
  `gulong-chatbot-runtime-staging-00355-6bk`. The complete matrix passed
  mechanically `16/16`, but human-CS review held promotion because its delivery
  safe fallback asked the customer to clarify instead of showing the available
  authored delivery facts.
- The next repair expands delivery-process answer-goal metadata to its complete
  general purpose and makes the release gate require the published GMA path,
  courier, and lead-time facts in the visible response. Focused tests passed
  `70`; the repository passed `1,315`. Production remains unchanged pending a
  new exact staging build and human review.
- Three exact `bec12c9` delivery probes all showed the required authored facts,
  but human-CS review held two because they framed a shopping input as necessary
  to validate exact delivery. The next audit-contract repair treats any such
  dependency as a process claim while preserving clearly separate optional
  CTAs. Production remains unchanged.
- Final implementation candidate `621c9de` built as Cloud Build
  `90d43a15-0968-4804-913c-f60346e5715f`, immutable digest
  `sha256:d864ab9a6d2b6b5a978f20b8af2d9e00a35689a56ce0e75da01059eddd70d6e8`,
  and healthy 100%-traffic staging revision
  `gulong-chatbot-runtime-staging-00357-zxt`. Both health routes reported the
  exact SHA with return-only delivery and follow-up sending disabled.
- Three fresh delivery probes passed mechanically and human-CS review. The
  complete integrated matrix passed `16/16`; the independent varied pack passed
  `9/9` across two product sizes, Maya Credit/e-wallets, Apollo bank terms,
  Grab Pay/cards, GCash loan/Pay Now, DOT, and formal/fleet quotations.
- Final gallery inspection found two product galleries and seven selectable
  cards, with zero missing/untrusted image URLs. Every card retained the exact
  displayed SKU/order and tracked `ps1|...` action, and both complete long-form
  price lists were visible. Candidate `621c9de` is approved for promotion after
  the final ref/deployment/VM preflight.

## 2026-08-01 - Staging matrix remediation checkpoint

- Candidate `0afb672` passed its final staging stability gate (`3/3` fresh
  Toyo runs plus `2/2` location/product controls), then built for live as Cloud
  Build `675cfd7e-e80d-4e8f-887c-a8559758da73`, digest
  `sha256:84c879086727339d4d187579ecb84d33aeb1d3aadd2beb743a980c02725d5c29`,
  and 0%-traffic revision `gulong-chatbot-runtime-live-00072-s6b`. Tagged
  return-only smoke passed `2/2`, but human-CS review held traffic because one
  otherwise-supported Toyo reply widened the brand-scoped empty result into a
  no-other-promo-for-the-size statement. Live revision `00071-rp9` therefore
  remained at 100%, and the VM remained on `d0da955`. Evidence:
  `tmp/live_cloudrun_0afb672_smoke/runtime_v7_release_candidate_20260802_004503/summary.json`.
- Safe-fallback candidate `518e283` built as Cloud Build
  `486ee2bd-ba74-428e-b6e2-ee9d03882dc5`, digest
  `sha256:558b88b64e88e81574adee43ee595690ebd0b016c45ec8924594cce9ca5f7382`,
  and staging revision `gulong-chatbot-runtime-staging-00341-8w6` at 100%.
  Location and product-card controls passed, as did two of three parallel Toyo
  runs. The third Toyo run used the new bounded fallback and was customer-safe:
  it stated the scoped no-match and no verified alternative, explicitly labeled
  four tracked price-category buttons as non-promo navigation, and retained the
  surface. The old matrix still rejected its generic fallback status and lack
  of a final model audit. Production remained on `d0da955`; the next candidate
  gives this deterministic path a dedicated guarded status without weakening
  provider, scope, or surface assertions. Evidence:
  `tmp/staging_matrix_518e283_toyo_3/runtime_v7_release_candidate_20260802_001054/summary.json`.
- Promotion merge candidate `f603145` built as Cloud Build
  `87fbbf1c-1536-4687-b302-f7b2bb8e6971`, digest
  `sha256:0a1a60a10f3ef4f1d417e159dcd9e5e8f18e819af27bb46f3e01ea6be023aee6`,
  and staging revision `gulong-chatbot-runtime-staging-00340-kn6` at 100%.
  Canonical health routes reported the exact merge SHA. Its promotion smoke
  passed payment, semantic store location, and nonlinear product-card cases,
  but the Toyo case failed (`3/4` overall): repeated model repairs framed
  ordinary price categories as promo alternatives and renderer fallback
  removed the surface. Main and the VM remained on `d0da955`. Evidence:
  `tmp/staging_matrix_f603145_promotion/runtime_v7_release_candidate_20260801_234910/summary.json`.
- Final integrated candidate `db8a528` built successfully as Cloud Build
  `01633022-2660-4db2-963d-755472e355c0`, digest
  `sha256:959902629fd21ed1ecf6aa30d84698308ea5e897523930d14955238ad767eda0`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00339-ccz` at 100%
  return-only staging traffic. The immutable `rc-db8a528` health response
  reported the exact release SHA and staging environment.
- The exact candidate passed the complete local repository suite (`1,282`
  tests), Ruff, and `git diff --check`. Its deployed single-turn release matrix
  passed `13/13`, and all three tracked multi-turn journeys passed. Human-CS
  review approved the final delivery, promo, payment, product-gallery,
  location-choice, schedule, and order-progression responses.
- The former Toyo blocker now states the scoped no-match and absence of a
  verified alternative without inventing another offer, while preserving four
  tracked price-category controls as ordinary shopping continuation. A pure
  `location ng store?` turn now presents the tracked province-choice surface.
  Multi-product results retain trusted catalog images, exact SKU/size,
  authoritative price/promo facts, and tracked selection tokens.
- Production remained on `d0da955` during this staging gate. Its Cloud Run
  revision was `gulong-chatbot-runtime-live-00071-rp9`, and the customer-facing
  VM rollback image was
  `sha256:58837280b18d4c674625b14b8bcb4ee62a8eeca774ce9e46b4293ff188ea26cb`.
  The approved promotion merges the staged product history into main and must
  reverify the exact merged SHA before replacing either production path.
  Evidence:
  `tmp/staging_matrix_db8a528_decisive/runtime_v7_release_candidate_20260801_231218/summary.json`,
  `tmp/staging_matrix_db8a528_remaining/runtime_v7_release_candidate_20260801_231823/summary.json`,
  and
  `tmp/staging_matrix_db8a528_journeys/runtime_v7_release_candidate_20260801_232232/summary.json`.
- Combined staging revision `2595a06` built successfully as Cloud Build
  `a19b9e6c-4d2a-49ab-b097-5f95ad378eaf`, digest
  `sha256:549593c40fc50c6fc46b4f8511e660b27ce52e668075460fb8e1e6755c965895`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00337-tw7` at
  100% return-only staging traffic. Its immutable `rc-2595a06` URL reported
  the exact SHA on both health routes.
- Delivery and brandless promo passed mechanically and human-CS review. The
  Toyo no-match retry stopped inventing other-brand offers, but its final audit
  marked the requested alternatives answer incomplete instead of accepting the
  explicit absence of a verified alternative for the reviewed scope. Production
  remained `d0da955`; the next candidate makes that result-scope outcome
  explicit to composer and auditor. Evidence:
  `tmp/staging_matrix_2595a06_affected/runtime_v7_release_candidate_20260801_224249/summary.json`.
- Combined staging revision `80c54f3` built successfully as Cloud Build
  `4357586d-1ee0-49e8-bcc0-66632baf7f70`, digest
  `sha256:965772a1b6aee9e0206915990bab0f19e5982dd0aa9366bcea168b5aac312077`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00334-jfl` at
  100% return-only staging traffic. Its immutable `rc-80c54f3` URL reported
  the exact SHA on both health routes.
- The affected matrix passed `2/2` mechanically with normal repaired composer
  output and supported final semantic audits. Human-CS review still held
  promotion: the delivery reply incorrectly framed tire size and brand as
  prerequisites for validating exact-area delivery. Production remained
  `d0da955`; the next candidate audits claimed validation prerequisites as
  policy/process facts while allowing a separate optional shopping CTA.
  Evidence:
  `tmp/staging_matrix_80c54f3_affected/runtime_v7_release_candidate_20260801_221505/summary.json`.
- Combined staging revision `0d0b845` built successfully as Cloud Build
  `ab4721c2-ddee-4be0-9ac1-06d42c9ac839`, digest
  `sha256:83a44c104c33154b766971681deb1bd49286246f50a5e244005314389d1bc17d`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00332-6l4` at
  100% return-only staging traffic. Its immutable `rc-0d0b845` URL reported
  the exact SHA on both health routes.
- The affected replay again passed the promo case normally. The evidence-only
  delivery retry stopped naming the requested place but stated broad GMA
  delivery policy without an explicit non-confirmation, which still implied
  coverage in context. The auditor rejected that implication and Runtime used
  safe authored fallback. Production remained `d0da955`; the next candidate
  requires a natural explicit pending-status sentence after any unsupported
  case-specific policy inference. Evidence:
  `tmp/staging_matrix_0d0b845_affected/runtime_v7_release_candidate_20260801_215739/summary.json`.
- Combined staging revision `bac61d2` built successfully as Cloud Build
  `8130224b-3bec-4a8a-b16e-bb12ca0b0d09`, digest
  `sha256:360cd3f626047c9a37bee59da8cc020570fb9343ccd3d610659eebb7eb562dba`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00330-f8m` at
  100% return-only staging traffic. Its immutable `rc-bac61d2` URL reported
  the exact SHA on both health routes.
- The affected replay passed the formerly failing brandless-promo case with a
  normal composer and supported audit. Delivery remained `1/2`: three model
  drafts repeatedly inferred exact-area serviceability from general policy;
  all audits rejected them and the safe authored fallback was shown. Because
  fallback is not accepted as normal release evidence, production remained
  `d0da955` and the next candidate isolates the last semantic retry from
  customer-origin context. Evidence:
  `tmp/staging_matrix_bac61d2_affected/runtime_v7_release_candidate_20260801_213611/summary.json`.
- Combined staging revision `614bd20` built successfully as Cloud Build
  `e429b5ea-4f28-48e4-8a50-d7230fb361a4`, digest
  `sha256:f307263f9cdb7f5ff8e284a2b40badc65ed3ae605ad47774cab321b9d22605ae`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00327-lww` at
  100% return-only staging traffic. Its immutable `rc-614bd20` URL reported
  the exact SHA on both health routes.
- The focused affected matrix passed the delivery-policy case after semantic
  repair recomposed safely from trusted policy evidence. The brandless promo
  case's semantic audits also supported the intended no-match answer, but its
  final claim contract rejected invented tool/path refs and used a generic
  fallback because the successful empty search had no result-level evidence
  ref. Production remained `d0da955`; the next candidate adds a scoped promo
  search ref without authorizing any absent offer. Evidence:
  `tmp/staging_matrix_614bd20_affected/runtime_v7_release_candidate_20260801_211758/summary.json`.
- Combined staging revision `d07bd50` built successfully as Cloud Build
  `7717fc41-cbae-4a1c-a2e4-7f03d016037e`, digest
  `sha256:1674fdf537725c5f33551aba710accd135fd49863956ae1c64e62c637d88c3c7`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00325-69g` at 100%
  return-only staging traffic. Its focused delivery and brandless-promo cases
  both failed closed after repair repeated meaning already rejected by the
  semantic auditors. The next candidate rebuilt semantic repairs without the
  invalid generated draft. Production remained unchanged. Evidence:
  `tmp/staging_matrix_d07bd50_affected/runtime_v7_release_candidate_20260801_210320/summary.json`.
- Combined staging revision `695a6e7` built successfully as Cloud Build
  `84b1ae35-f816-40f4-8063-6741fa0e8c6d`, digest
  `sha256:100454e5bf08c26625c6d0517d3207871390749e86934c836c85b30d576c526a`,
  and Cloud Run revision
  `gulong-chatbot-runtime-staging-00323-n4r` at 100% return-only staging
  traffic. The immutable revision URL reported the exact SHA on both health
  routes.
- Its complete pinned single-turn matrix passed `12/13`. The only failure was
  the delivery-policy case: the first semantic audit correctly rejected an
  exact-area claim and the repair produced safe authored policy text, but the
  repair audit ended with `finish_reason=length` at the former 900-token bound.
  Runtime correctly failed closed, while the release matrix rejected the
  fallback composer status. The next candidate increases only the bounded audit
  response budget. Production remained `d0da955`. Evidence:
  `tmp/staging_matrix_695a6e7_all_cases/runtime_v7_release_candidate_20260801_203825/summary.json`.
- Combined staging revision `7185d1b` built successfully as Cloud Build
  `4f9eaef2-69d9-4ba4-bceb-21d3c4c0354e`, digest
  `sha256:3eb552b49c46f4cd5a64b1b5fe4cde717d03158eb63483526ebec6e68e24a50b`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00320-5v9` at 100%.
  Both health routes reported the exact SHA, staging, and return-only delivery.
- Its focused delivery case passed mechanically (`1/1`), including the grounded
  FAQ tool and structured repair, but failed human-CS/authority review. The
  visible answer still promised delivery to the customer's exact area even
  though the general policy authorized only published delivery paths and lead
  time. Production remained on `d0da955`; the next candidate adds an
  independent semantic scope audit instead of customer-text matching. Evidence:
  `tmp/staging_matrix_7185d1b_delivery/runtime_v7_release_candidate_20260801_200640/summary.json`.
- Combined staging revision `1c3a202` built successfully as Cloud Build
  `e06d585d-8c8a-4b07-ad40-5871b783b984`, digest
  `sha256:a0890f0bda51590919679c1b190d3397bdcb553dc4cf49c5ffbd243ec4fbd53b`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00318-cmh` at 100%.
  It included concurrent payment-scope audit commit `e36099a`; both health
  routes reported the exact combined SHA, staging, and return-only delivery.
- Its focused delivery case failed mechanically (`0/1`). The first composer
  response was structurally valid but over-scoped; the subsequent contract-
  repair call ended with `finish_reason=length`, causing renderer fallback.
  The next candidate extends the bounded structured-format retry to truncated
  repair output, still subject to the full contract suite. Evidence:
  `tmp/staging_matrix_1c3a202_delivery/runtime_v7_release_candidate_20260801_195013/summary.json`.
- Staging revision `bc23b8d` built successfully as Cloud Build
  `04baa019-6dd3-4bb4-9e1f-6e21444bd756`, digest
  `sha256:b307f151307052cbb0d4dbfa893e35147d916fd1b56a6eb2137b656030094e14`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00316-ggj` at 100%.
  Both health routes reported the exact SHA, staging, and return-only delivery.
- Its focused delivery case failed mechanically (`0/1`). The final composer
  ended with `finish_reason=length` and no valid structured object, so Runtime
  used the legacy draft fallback, which also failed human-CS review. The next
  candidate adds a single bounded structured-format retry without weakening
  downstream contracts. Evidence:
  `tmp/staging_matrix_bc23b8d_delivery/runtime_v7_release_candidate_20260801_193627/summary.json`.
- Combined staging revision `5eebc96` built successfully as Cloud Build
  `2752b05a-c2a4-42b5-9aa5-ffe9b96d66af`, digest
  `sha256:c47e0b9ef3bfa7ebb3d60156224dc58c673fe19089ffa24e8e48bad4eb9e7b05`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00315-pw4` at 100%.
  It included concurrent audit improvements from `a8bb217`; both builds
  completed and the service ended on the exact combined SHA.
- The delivery replay again passed mechanically (`1/1`) but failed human-CS
  review. The positive contract now offered `faq_facts`, yet the first draft
  declared a narrower `service_availability` claim and repair removed the
  answer instead of narrowing it. The next candidate makes successful current-
  turn FAQ results explicit required answers during initial composition and
  repair. Evidence:
  `tmp/staging_matrix_5eebc96_delivery/runtime_v7_release_candidate_20260801_192403/summary.json`.
- Staging revision `51c5567` built successfully as Cloud Build
  `33a35731-0bc2-4b62-8f67-d01011e6b2d6`, digest
  `sha256:f6e7feabd7cbed4342aee57098044d39ec43b0e4fd4ef69ee37b31d7de91440c`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00313-jmq` at 100%.
  Both health routes reported the exact SHA, staging, and return-only delivery.
- Its focused delivery replay passed mechanically (`1/1`) and returned the
  authored policy as `status=ok`, but human-CS review again held promotion.
  The composer repair removed the attempted answer because FAQ results lacked
  a stable positive claim ref, leaving only a delivery preference
  acknowledgement and tire-size question. The next candidate adds generic FAQ
  evidence refs and keeps exact-address serviceability as a separate authority.
  Evidence:
  `tmp/staging_matrix_51c5567_delivery/runtime_v7_release_candidate_20260801_190832/summary.json`.
- Staging revision `17350a4` built successfully as Cloud Build
  `28880464-e64b-4fa6-bd01-09cb72d97d82`, digest
  `sha256:a8e828327516b84ee302aedbcb9a449c36ecf38f71ec291d3e9a42e53072aa34`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00312-q6f` at 100%.
  Both health routes reported the exact SHA, staging, and return-only delivery.
- The focused delivery replay passed its mechanical gate (`1/1`) and invoked
  `answer_policy_faq`, but human-CS review held promotion: the provider result
  was `no_match`, leaving a safe but incomplete answer that did not explain
  general delivery availability. The next candidate carries the already
  authorized typed delivery scope into the authored delivery-process FAQ;
  exact-address serviceability remains outside that policy's authority.
  Evidence:
  `tmp/staging_matrix_17350a4_delivery/runtime_v7_release_candidate_20260801_185122/summary.json`.
- Staging revision `27a6424` built successfully as Cloud Build
  `8d3bc7cf-b2f3-4ac2-b240-3a0ecadd3c0d`, digest
  `sha256:4a1d8473f32552fb755a7ecb7d4495fc67cfbe15dbbbf0fb3291f37534356df7`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00310-4h5` at 100%.
  Exact health checks passed and delivery remained return-only.
- Payment (`2/2`), promo (`4/4`), and product (`3/3`) batches passed. The
  location/policy batch passed `3/4`; the delivery-feasibility turn again made
  an ungrounded affirmative claim because the semantic checkpoint coupled its
  concrete-location classification to policy-grounding execution.
- Decision: **not promoted to live**. Location classification and grounding
  were separated into independent semantic outputs for the next candidate.
  Evidence is under
  `tmp/staging_matrix_27a6424_batch_payment`,
  `tmp/staging_matrix_27a6424_batch_promos`,
  `tmp/staging_matrix_27a6424_batch_products`, and
  `tmp/staging_matrix_27a6424_batch_location_policy`.
- Follow-up staging revision `95dd54f` built successfully as Cloud Build
  `9c084e31-f73a-4301-a1ed-6d9daeb0d74a`, digest
  `sha256:7581bcc478453d4c078ae3cd26ef75774e04aefb55e10a089681647116a28324`,
  and Cloud Run revision `gulong-chatbot-runtime-staging-00308-94w` at 100%.
  Exact health checks passed and delivery remained return-only.
- The targeted payment replay improved to `1/2`. Apollo/Atome passed with all
  three canonical claims. Yokohama/Home Credit exposed a second generic issue:
  an invalid legacy scalar caused Runtime to discard an otherwise valid typed
  query list. Production remained unchanged while scalar/list validation was
  separated for the next candidate. Evidence:
  `tmp/staging_matrix_95dd54f_batch_payment/runtime_v7_release_candidate_20260801_181611/summary.json`.
- Staging code revision: `d3eac61`
- Cloud Build: `b2473105-e4b4-40ef-b073-710083eb2693` (`SUCCESS`)
- Image digest:
  `sha256:3e46b68d63d7b501dbd796e95f6c3b04988bc85409f73050b5f8b13a3bb9267f`
- Cloud Run revision: `gulong-chatbot-runtime-staging-00307-wfr` at 100%
  staging traffic; both health routes reported `git_sha=d3eac61`, staging,
  and return-only delivery.
- Checkpointed promo cases passed `4/4`. Compound payment cases failed `0/2`:
  a later bank clause contaminated the earlier installment lookup, and an
  unclaimable brand-scoped conflict displaced a valid unsupported-method fact.
- Decision: **not promoted to live**. The customer-facing VM and `origin/main`
  remained unchanged while generic per-scope canonicalization and claim-aware
  deduplication were implemented for the next candidate.
- Evidence:
  `tmp/staging_matrix_d3eac61_batch_promos/runtime_v7_release_candidate_20260801_180108/summary.json`
  and
  `tmp/staging_matrix_d3eac61_batch_payment/runtime_v7_release_candidate_20260801_180314/summary.json`.

## 2026-08-01 - Semantic location staging hold

- Staging code revision: `140bafa`
- Cloud Build: `756055d4-85df-451d-9912-976bc31cf7dd` (`SUCCESS`)
- Image digest:
  `sha256:c3037cb3ee5df88b629876f38989a27703799a2e86074db79791f9cfab73f805`
- Cloud Run revision: `gulong-chatbot-runtime-staging-00303-jps` at 100%
  staging traffic, with both health routes reporting `git_sha=140bafa`,
  `service_environment=staging`, and return-only delivery.
- Focused semantic-location staging probes passed mechanically (`6/6`): three
  fresh `location ng store?` turns and one English installation-location
  paraphrase each rendered eight tracked province controls; contact and
  delivery negatives rendered no province controls.
- Human-CS review did not approve the adjacent negative responses. The hotline
  turn returned the generic first-turn intake and a false "confirmed details"
  continuation instead of the grounded business number. The BGC delivery turn
  asserted delivery availability without a validated serviceability source.
- The full return-only release-candidate matrix also failed (`6` passed, `7`
  failed). Failures included missing promo-card tokens, two payment-policy
  contract gaps, one endpoint failure, and two promo journeys entering renderer
  fallback. These failures are not authorized as part of the location release.
- Decision: **not promoted to live**. `origin/main` and the customer-facing VM
  remained on `d0da955`; the VM health routes continued to report
  `service_environment=live` and `runtime_host=gulong-chatbot-runtime-shadow`.
- Probe artifacts:
  `tmp/staging_location_release_probe_140bafa.json` and
  `tmp/staging_semantic_location_release_20260801/runtime_v7_release_candidate_20260801_161521/summary.json`.

## 2026-08-01 - Semantic state and human handoff checkpoint

- Staging code revision: `235c5b6`
- Cloud Build: `43eeef6e-f211-4f7b-a266-64fd5ac53b12` (`SUCCESS`)
- Cloud Run revision: `gulong-chatbot-runtime-staging-00301-8wf` at 100% staging
  traffic
- Verification: health checks passed; the full local Runtime V7 suite passed
  (`1166` tests); Codex reviewed nine fresh multi-turn staging conversations from
  both customer and human-CS perspectives.
- Decision: **not promoted to live**. Three payment-state conversations still
  produced irrelevant payment-policy replies after the typed state decision.
  The remaining root cause is the API pre-composer payment planner independently
  inferring a plan from raw turn text. Live remained on `d0da955`.
- Next gate: replace the duplicated API inference with one typed turn goal/query
  plan shared by the main loop and completion layer, then rerun the varied live
  staging matrix before any `product` to `main` promotion.
