# Runtime V7 Final Composer Repair Observability

Investigation ID: `20260827-runtime-v7-repair-observability`  
Started: 2026-08-27T18:35:21+08:00  
Status: complete

## Conclusion

Release A is deployed to staging, Cloud Run live, and the customer-facing VM.
Existing final-composer calls now expose stable attempt kinds, coarse repair
reasons, and typed violation labels in normalized LLM-span metadata. The
component name remains `final_composer`, preserving existing cost and latency
time series. The release changed no prompt or customer-response behavior.

## Evidence

- Baseline: clean `origin/product` commit
  `71b15cadf5d012ad58c0f42349dd96127ff09ae6` in isolated branch
  `fix/runtime-v7-repair-observability-20260827`.
- Before the patch, detailed call records had distinct `round` values but the
  normalized span contract did not expose explicit attempt/cause labels.
- The implementation labels all existing initial, format-retry,
  contract-repair, repair-format-retry, and semantic-scope-repair call paths.
- Focused deterministic tests passed `5/5` for the no-repair baseline, all
  existing attempt labels, initial format retry, contract repair plus
  repair-format retry, and normalized span projection.
- The full Runtime V7 deterministic regression set passed `1502 tests` in
  `60.50s`. Ruff, compile, JSON validation, diff checks, and the behavioral
  change audit also passed; the audit reported only the expected informational
  README confirmation.
- Staging build `323caeab-033f-4341-9e1d-ad4eed30df80` deployed candidate
  `d05b05c` as revision `gulong-chatbot-runtime-staging-00429-rh9` at 100%.
  Health, three analytics-enabled requests, normalized-span projection, and
  revision error/5xx checks passed.
- The bounded quality matrix passed `1/3` on staging and the same `1/3` on the
  pre-patch `feb88a4` live baseline. The two failures are pre-existing
  delivery-policy and payment-contract quality debt, not a Release A movement.
- Live build `e0e87d06-1229-4912-8809-5d97de20f054` deployed promotion
  `54eec74` as Cloud Run revision `gulong-chatbot-runtime-live-00105-7tr` at
  100%, using immutable digest
  `sha256:d2ef953b75c679073d35a853cc64872a892708daf87b4cc0428750a0f3bec8b7`.
- The same digest passed a VM alternate-port candidate health check and became
  active as `gulong-chatbot-runtime-shadow`. Public health and a loopback
  return-only probe passed; restart, traceback, and exception counts were zero.
  Rollback `gulong-chatbot-runtime-shadow-rollback-feb88a4-20260827T1912PHT`
  is retained, and restart metadata now points to the new digest and SHA.
- Through `2026-08-27 19:17:36` Manila, VM monitoring observed eight completed
  rows: five successful deliveries, one synthetic return-only skip, and two
  intentional suppressions. No failed status was observed.
- Three staging composer spans, one Cloud Run live composer span, and six VM
  composer spans carried `attempt_kind="initial"` while main-loop spans
  remained unlabeled. No natural repair occurred in the bounded window, so
  non-initial cause values remain deterministically tested but not yet sampled
  from real traffic.

## Cost and operational impact

The patch itself does not reduce Gemini cost and adds no runtime Gemini call. It makes
repair frequency and token/latency cost attributable by cause so later prompt
or validation changes can target the largest controllable waste and can be
evaluated against a response-quality floor. The added metadata is written only
to analytics records and does not enter model context.

## Recommendation and gates

- Keep the release. Staging, Cloud Run live, and VM deployment checks passed,
  and the prior VM image remains immediately recoverable.
- Monitor `JSON_VALUE(meta, '$.attempt_kind')` and
  `JSON_VALUE(meta, '$.repair_reason')` over a larger normal-traffic window
  before sizing Release B by repair cause; no repair occurred in this bounded
  post-release sample.
- Track the baseline delivery-policy and Yokohama payment-contract failures as
  separate response-quality work. They should not be attributed to this
  analytics-only release.
- No backfill is planned: old spans retain their historical shape, while the
  stable `component` series remains comparable across the boundary.
