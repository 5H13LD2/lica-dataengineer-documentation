# AGENTS.md - Runtime V7

This file applies to `runtime_v7/` and Runtime V7 API ingress, tests, and docs.

Runtime V7 is the model-led Gulong assistant slice for product discovery,
service feasibility, order review/submission, payment requests, and ManyChat
delivery experiments. It must stay compatible with Cloud Run statelessness:
Firestore/session state is authoritative, while in-memory caches are only soft
optimizations.

## Architecture Rules

- Keep one main model/tool loop. Do not add multi-agent orchestration.
- Keep customer interpretation model-led. Do not reintroduce raw-utterance
  regex or keyword classifiers for commercial meaning, intent, or slot truth.
- Use deterministic code for normalization, validation, canonicalization,
  rendering surfaces, refs, idempotency/replay, and side-effect safety.
- Treat Active Working Memory, narrative summaries, and product/service
  observations as advisory context, not customer-choice or action authority.
  Typed Background Signals may persist and inform readiness only when their
  closed provenance is the latest customer message or a validated guided
  action; untraceable legacy rows fail closed.
- Treat tool outputs, canonical metadata, stored refs, and order payload
  validation as the source of truth for prices, promos, stock, service slots,
  payment, order submission, and fulfillment.
- Keep deterministic renderers responsible for exact cards, order summaries,
  payment details, QR images, and ManyChat-safe splitting. The model writes the
  surrounding lead-in, explanation, and CTA through the final composer.
- Avoid post-response prose mutation. If wording keeps failing, improve
  model-facing policy, structured tool semantics, or renderer-owned surfaces.
- Do not reveal exact installation partner names/addresses earlier than the
  approved service disclosure stage unless the customer explicitly forces it
  and the no-walk-in/reservation-required policy is included.
- Never use in-memory state for correctness. Any state needed after the current
  request must be stored in the session strategy state or another durable store.

## Documentation Update Contract

When changing Runtime V7 behavior, update docs in the same commit.

- Always add a short dated entry to
  `docs/IMPLEMENTATION_NOTES_RUNTIME_V2.md` for significant V7 behavior,
  API, state, prompt, tool, renderer, or test changes.
- Update `docs/RUNTIME_V7_DOCUMENTATION_INDEX.md` when adding, moving, or
  changing ownership of Runtime V7 docs.
- Update `docs/RUNTIME_V7_ARCHITECTURE.md` when component boundaries,
  component relationships, state ownership, or request flow changes.
- Update `docs/RUNTIME_V7_COMPONENTS.md` when adding or materially changing a
  V7 module, tool family, renderer, state store, or gateway.
- Update `docs/RUNTIME_V7_VERSION_HISTORY.md` when a commit group, branch
  checkpoint, or feature pass changes a Runtime V7 capability boundary.
- Update `docs/RUNTIME_V7_DECISIONS_AND_GAPS.md` when a review produces a
  design decision, anti-pattern, learning, parked idea, open gap, or known
  testing limitation.
- Update `docs/RUNTIME_V7_PRODUCT_AGENT_IMPLEMENTATION_NOTE.md` only for
  detailed product/service/order implementation behavior that needs longer
  explanation than the central notes.
- Update `README.md` only for top-level project orientation and entrypoint
  changes.
- Do not leave Runtime V7 docs as a stale scaffold. If the implementation
  changes a flow, the corresponding docs must explain what changed, why the
  design is shaped that way, which component owns it, how it is verified, and
  what remains open.

## Good Patterns

- Evidence-led context: latest message, channel history, AWM, signals,
  observations, readiness, and tool refs are separated by source and trust.
- Model-led routing with deterministic capability/canonicalization support.
- Compact model-facing tool outputs with full diagnostics stored out of band.
- Stable refs: product/service/order/payment surfaces should be referenced by
  observation/presentation/payload/payment refs instead of copying bodies.
- Renderer-owned exact facts: product cards, slot cards, order summaries, and
  payment details are inserted deterministically.
- Validation before action: `build_order_payload` must succeed before
  `submit_order`; payment request should consume submitted order context.
- Segment-based conversation hydration: reset and old message gaps create a
  new model-facing segment instead of merging stale history.
- Version-neutral turn traces: use generic spans/snapshots plus component
  metadata so V7 logs can be compared with other runtimes.

## Anti-Patterns To Avoid

- Raw user-text keyword gates that decide order intent, service intent, product
  category, payment selection, or final response shape.
- Phrase-based final-response blockers that rewrite otherwise model-owned
  copy.
- Dynamic context that becomes a script telling the model exactly what to say.
- AWM that contains policy instructions, stale missing-field checklists, or
  unvalidated commercial facts.
- Background Signals that override the latest user message or trusted tool
  state.
- Treating a tool being exposed as an instruction that the model must call it.
- Tool outputs that include bulky upstream payloads or hidden business data.
- Model-written product cards, payment account numbers, QR URLs, or exact order
  summary totals.
- Order/payment side effects without an API-ready validated payload ref.
- Customer-facing text with internal words such as refs, cards, schemas,
  service tools, cache, or runtime.
- Bypassing branch-triggered Cloud Build/Cloud Run deployments by submitting a
  local feature-branch source snapshot or deploying unmerged code. Runtime V7
  staging deployments must come from `product`; live deployments must come from
  `main`. Only bypass this when the user explicitly forces it, and state the
  exact source branch, commit SHA, and provenance before and after deployment.

## Testing Expectations

- For Runtime V7 code changes, run:
  `pytest $(rg --files test | rg "test_runtime_v7") -q`
- For ingress/history/idempotency changes, also run:
  `pytest test/test_runtime_v7_ingress_trace.py -q`
- For docs-only edits, tests are not required unless the docs describe a code
  contract that was changed in the same commit.
- Live model probes are optional and should be scoped. Do not run broad live
  packs unless the task explicitly calls for it.
