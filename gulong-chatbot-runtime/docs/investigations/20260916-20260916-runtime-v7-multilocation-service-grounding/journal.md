# Runtime V7 multi-location service grounding correction

Investigation ID: `20260916-20260916-runtime-v7-multilocation-service-grounding`  
Started: 2026-09-16T01:08:40+08:00  
Status: complete

## Conclusion

The generalized defects are corrected locally. Runtime now preserves the
customer's canonical location independently from acceptable nearby areas,
executes unscoped service checks against that anchor, and limits each service
claim to the provider-queried area. Empty product observations can no longer
authorize slot progression, and explicit latest-turn product constraints
survive model argument variation. Required-brand, exact-size products are no
longer hidden merely because a descriptive terrain filter or catalog image is
missing; the mismatch is disclosed before all source-backed text options.

## Evidence

- Adaptive replay queried `Rosario, Cavite` even when the model proposed
  Dasmarinas. The provider returned three current partner options, and the
  deterministic summary claimed only Rosario while requiring separate checks
  for the other named areas.
- Final adaptive replay executed `product_search` for `265/50R20` with
  `required_brands=[NITTO]` and `terrain_types=[ALL_TERRAIN]`, removed a
  terrain-only pseudo-model query, and returned a typed partial match.
- The channel first stated that no Nitto option was catalog-verified as A/T,
  then listed all three source-backed Nitto products at the exact requested
  size. Two trusted-image products received tracked visual buttons; the third
  remained visible as a text product because its API row had no trusted image.
- Final replay artifact:
  `tmp/runtime_v7_multiloc_product_fix_final9.json`.
- Focused integrated suite: 1,024 passed. Complete Runtime V7 suite: 1,781
  passed. The customer-facing change audit has no required findings.

## Cost and operational impact

The final three-turn replay remained within the temporary per-turn limits of
95 seconds and 2 million tokens. Handler time was 32.3s, 35.3s, and 59.2s;
token usage was 54,135, 61,272, and 94,065. Synthetic Firestore saves completed
in one attempt at 176-307 ms. Correctness and persistence were stable in this
bounded run, but model latency remains yellow.

## Recommendation and gates

Commit this isolated branch without deployment. Before release, run the normal
staging trigger and deployment evaluator, verify the served revision/SHA and
traffic, and test actual ManyChat rendering/delivery. This local return-only
replay does not prove channel delivery, production traffic behavior, or
BigQuery landing.

## Fitment-first constraint follow-up

The original same-brand terrain relaxation was intentionally broadened after
review. Exact tire size, explicit EV compatibility, and customer exclusions
are now the hard product-presentation constraints. Brand, model, terrain,
category, budget, origin, warranty, availability, promo, guarantee, and
installment filters are relaxable preferences on exact-fitment candidates.
Every relaxed card carries typed missing-filter metadata and deterministic
customer-facing disclosure; commercial facts remain sourced per card.

Brand exclusivity is no longer inferred from every named-brand question.
`brand_match_mode` defaults to `prefer` and becomes `strict` only from explicit
customer-only/no-alternative semantics. Hydration, cache identity, memory,
debug projection, model-visible query basis, and the product tool schema all
preserve the canonical mode.

Deterministic rendered review for Nitto 265/50R20 A/T showed the three
exact-size Nitto options first, each disclosed as missing the requested terrain
classification, followed by one exact-size A/T alternative disclosed as a
brand mismatch. The strict-brand negative control rendered no cross-brand
cards, and the EV negative control rendered no incompatible cards. Product
runner tests passed 106/106, the product-observation harness passed 721/721,
and the complete local repository suite passed 1,888/1,888. No deployment or
external data mutation was performed.
