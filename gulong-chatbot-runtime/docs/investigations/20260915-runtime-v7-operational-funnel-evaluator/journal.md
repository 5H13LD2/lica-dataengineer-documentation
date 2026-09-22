# Runtime V7 operational funnel evaluator

Investigation ID: `20260915-runtime-v7-operational-funnel-evaluator`
Started: 2026-09-15T07:02:38+08:00
Status: evaluator release approved; runtime remediation gated

## Conclusion

The evaluator now measures the primary synthetic capability path from a
customer-owned size+brand near-miss through rendered location/contact
collection, canonical capture, and a planned deterministic Moderate
qualification. It evaluates the final response before delivery and does not
require BigQuery persistence.

Current staging release `639a0c3` is not operational-funnel green. Corrected
targeted evidence supports typed city completion, guided province-to-city
completion, and the already-complete negative control. The contact-fallback
path remains blocked because the runtime re-asks for location after the
customer says the city is unknown instead of offering contact.

The evaluator release is intentionally independent of that runtime result. It
may be committed and deployed so future gates expose the failure consistently;
the failing contact-fallback and incorrect service/product response behavior
must be repaired in a separate runtime branch and cannot be waived when that
runtime candidate is evaluated for promotion.

## Evidence

- Clean feature branch:
  `feat/runtime-v7-operational-funnel-evaluator-20260915`, based on `399fcb8`.
- Serving target: Cloud Run staging revision
  `gulong-chatbot-runtime-staging-00467-t7x`, release/Git SHA `639a0c3`, 100%
  traffic, `return_only`.
- Hardened four-scenario artifact:
  `tmp/runtime_v7_operational_funnel_targeted_20260915_hardened/runtime_v7_release_candidate_20260915_064936_438116/summary.json`.
- Corrected guided-path artifact:
  `tmp/runtime_v7_operational_funnel_guided_20260915/runtime_v7_release_candidate_20260915_065519_933074/summary.json`.
- Local validation: 1,863 repository tests passed; changed-file Ruff and
  definition-digest checks passed.

The four-scenario diagnostic had eight responses, zero HTTP/runtime/tool
errors, 40 model calls, 679,164 tokens, p50 32.5 seconds, and p95 44.2 seconds.
The corrected five-turn guided path passed all stages with 453,297 tokens and
p95 69.2 seconds, which is a concern above 45 seconds but below the 95-second
failure threshold.

## Cost and operational impact

Token usage is exact deployed runtime telemetry. Monetary cost is unavailable
because the tester aggregate does not expose a priced per-model call ledger;
no estimate is presented as posted billing. The evaluator keeps operational
technical totals separate from the historical core baseline while combining
both sections for the absolute 2,000,000-token and 250-model-call run limits.

## Recommendation and gates

1. Commit and deploy the evaluator independently without changing serving
   response behavior.
2. Fix the general contact-fallback decision for a customer who cannot yet
   provide installation city, without treating `Unknown` or negated/uncertain
   place text as location evidence.
3. Rerun the targeted contact scenario, then one complete final-contract
   evaluator on the exact candidate revision.
4. Treat guided-path p95 as a yellow concern and inspect the 43-second
   installation-slot provider call observed in the earlier guided run.
5. Keep actual ManyChat delivery, BigQuery landing, production abandonment,
   and linked 7/14-day booking conversion as separate observational checks.

## Learning candidate: Keep operational funnels separate but promotion-blocking

- Captured: 2026-09-15
- Promotion status: candidate
- Symptom: Previously green core model matrices did not reveal whether size-plus-brand near-misses progressed to customer location or contact and planned Moderate.
- Root cause: Component and broad journey contracts lacked an explicit data-derived cross-turn funnel, while adding new rows directly to core totals would break historical baseline denominators.
- Proposed practice: Version a separate operational-funnel corpus using rendered pre-delivery responses, canonical customer-owned signal provenance, planned qualification evidence, independent technical totals, and combined absolute metered budgets.
- Scope/owner: Gulong Runtime V7 deployed release evaluation and reporting.
- Positive scenario: A typed city or validated city choice completes size-plus-brand and produces a countable planned Moderate qualification.
- Negative control: A store-location question, product-card brand, province-only click, or uncertain location does not become customer qualification evidence.
- Expected benefit: Exposes progression regressions before promotion without false grounding or invalidating historical core latency and token comparisons.
