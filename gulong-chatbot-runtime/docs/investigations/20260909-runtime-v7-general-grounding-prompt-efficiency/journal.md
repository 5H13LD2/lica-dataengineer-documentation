# Runtime V7 General Grounding and Prompt Efficiency

Investigation ID: `20260909-runtime-v7-general-grounding-prompt-efficiency`
Started: 2026-09-09T15:55:16+08:00
Status: release-gated

## Conclusion

The customer-correctness defects are fixed locally on a clean product-baseline
branch. Explicit delivery questions cannot silently bypass policy evidence, and
general delivery policy can no longer authorize an exact named address. Compound
payment checks retain their customer-authored method, brand, option, and term
through hydration, deduplication, provider lookup, and final composition.

The observed delivery failure was not caused by a weak ranking algorithm. The
main model understood the question but chose no FAQ tool, so retrieval and any
future reranker never ran. The repair therefore closes the tool-omission boundary
using typed delivery-question evidence while preserving semantic FAQ retrieval
as the source of policy facts. A broader FAQ RAG evaluation remains useful but
is not required to explain or fix this incident.

## Evidence

- Live baseline `50e5975` passed only the hotline case. The BGC delivery case
  made an unsupported exact-area promise without a policy tool, and the compound
  payment case proposed three useful calls before turn-wide hydration corrupted
  their scopes and deduplication collapsed them.
- The new end-to-end fixtures span model output, hydration, cache-key generation,
  deduplication, provider responses, request obligations, and final composition.
  Delivery statements, non-delivery location questions, payment selections, and
  unbranded installment questions provide adjacent negative controls.
- The affected four-file suite passed 888 tests. All 28 `test_runtime_v7*.py`
  modules passed 1,560 tests, and the full repository suite passed 1,639.
- Final independent review identified and closed three additional boundary
  gaps: omitted composer coverage declarations now fail required-obligation
  validation; multi-brand detection comes from customer-visible canonical brand
  mentions rather than only the model's sibling-call list; and conditional or
  negated delivery mentions cannot trigger the forced policy retry.
- A second independent pass closed same-term/different-brand completion,
  cross-brand payment-option inheritance, partial multi-scope retry progress,
  and repeated no-progress multi-authority retry gaps.
- In the final payment probes, Home Credit was `unsupported`, Yokohama Pay Later
  3-month installment was eligible/not brand-restricted as appropriate, and
  Yokohama BPI 6-month was `not_eligible`. Both original and reordered clause
  forms produced separate provider calls.
- A later exact live probe exposed a broader variant: the model merged Home
  Credit with the 3-month clause and omitted that plan as a separate call. The
  deterministic boundary now scopes even a single merged lookup to its matching
  clause, prevents turn-wide option/brand bleed, and schedules a bounded lookup
  for every missing explicit numeric plan. The final rerun produced three
  distinct provider calls and the three correct commercial dispositions.
- Delivery-question probes called the policy provider and included Greater
  Manila Area, Lalamove, and 7-10 day facts where relevant. Named-location
  responses explicitly kept the exact address unconfirmed. Delivery statements
  did not force retrieval.
- Human CS-perspective review of the latest BGC and original/reordered payment
  turns found the target answers correct, understandable, and grounded. The BGC
  turn is somewhat verbose and makes a regional BGC inclusion statement before
  its explicit exact-address caveat; that is acceptable for this scoped gate but
  should remain in the broader response-quality review rather than being treated
  as proof of the overall quality floor.
- Static main-prompt size versus `50e5975` fell 15.5% with no optional domain
  (38,434 to 32,624 characters) and 5.3% with all domains (104,433 to 98,929).
  The exact payment probe's composer input fell from 8,388 tokens over two
  attempts to 3,886 tokens in one attempt.
- Missing August 27 repair-observability release evidence was ported into the
  release history, implementation notes, version history, and prior
  investigation record without changing runtime behavior.

## Cost and operational impact

Seven metered bounded development-key live-model runs covered 27 scenario turns
and 115 model calls. They reported 1,538,236 prompt tokens, including 166,349
cached tokens, 88,419 completion tokens, 1,626,655 total tokens, and estimated
cost of USD 0.55626459 at the harness price table. This is test spend, not posted
billing.

No BigQuery query, table change, backfill, deployment, traffic movement,
ManyChat delivery, or production mutation occurred.

## Recommendation and gates

The branch is ready for code review and then the normal staging-branch Cloud
Build path. Before live promotion, rerun the varied semantic matrix on the exact
staging revision and complete human CS review of full rendered turns. Treat FAQ
RAG/reranking as a separate measured investigation using a broad question set;
do not infer from this tool-omission defect that ranking itself failed.

Keep the change release-gated until exact staging revision, traffic, channel
delivery, and post-release telemetry are verified. BigQuery historical repair
work remains explicitly deferred to a dedicated session.
