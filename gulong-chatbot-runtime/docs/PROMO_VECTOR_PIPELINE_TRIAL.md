# Promo Vector Pipeline Trial

This branch contains an isolated trial of the future promo-mechanics retrieval path:

```text
Google Drive source -> GCS immutable build artifacts -> Firestore vector chunks -> semantic query
```

The entry point is `scripts/promo_vector_trial.py`. It reads the shared `Promo Source` Drive folder directly through Google Drive API calls authenticated as `promo-catalog-bot`, which the VM runtime impersonates. The source folder must be shared with that account as a Viewer; its private parent folder does not need to be shared.

The default source layout is `Promo Source/2026-07/Promo Images` and
`Promo Source/2026-07/Promo Mechanics`. The configured source may also point
directly to a monthly folder that contains both `Promo Images` and
`Promo Mechanics`; pass the matching `--month-folder-name` so the catalog and
review tabs retain the correct monthly boundary. Folder names can be changed
with command-line options when marketing uses a new convention.

Review workbooks live separately under `Promo Catalog Reviews`, with one file
named `Promo Catalog Review - YYYY-MM` per source month. Same-month revisions
may reuse that file; the catalog sync rejects a workbook that already contains
another month.

The script writes only to a caller-selected GCS prefix and Firestore collection. It never updates an active catalog pointer or sends a ManyChat message.

`scripts/promo_catalog_builder.py` is the next isolated stage. It uses Gemini to extract one source-evidenced record per promo, creates parent promo-card vectors plus child mechanics vectors, and writes a `pending_review` catalog version. It cannot publish an active version or affect chatbot answers.

Parent-card embeddings include deterministic amount and mechanic aliases such as `PHP 6000`, `6K`, and `buy three get one`. Query-time multi-query retrieval is still required for amount-sensitive questions because a single dense-vector query can rank neighboring offers together.

Before the first query, create a Firestore composite vector index for the selected collection with an ascending `catalog_version_id` field and a 768-dimension `embedding` vector field. This allows the semantic query to pre-filter to one immutable catalog version.
