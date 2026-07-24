# Temporary CSV Snapshot Data

## Purpose

The prototype uses sanitized warehouse CSV snapshots because a production mobile API is not available yet. CSV files are build inputs only: the React Native application does not parse CSV files at runtime and never connects directly to the data warehouse.

This is a temporary architecture. Production must use an authenticated backend API that owns authorization, pricing rules, availability, inventory, and data freshness.

## Data flow

```text
Read-only warehouse export
        ↓
exports/mobile_snapshot_YYYY-MM-DD/*.csv
        ↓ npm run data:snapshot
Zod validation + relationship joins
        ↓
src/data/generated/*.ts
        ↓
catalogSnapshot adapter
        ↓
mockApi / TanStack Query
        ↓
application screens
```

Screens do not import CSV files or generated files directly. The snapshot is exposed through `src/features/catalog/data/catalog.snapshot.ts`, which provides a narrow replacement point for the future API-backed repository.

## Current snapshot

- Directory: `exports/mobile_snapshot_2026-07-14`
- Source catalog rows: 3,294
- Generated valid products: 3,133
- Rejected products: 161
- Brands: 31
- Source export time: `2026-07-14T07:05:16Z`
- Inventory feed: unavailable
- Reliable branch export: unavailable

The generator reads `export_manifest.csv` and `validation_report.csv`; it does not hide warehouse warnings. Generated metadata is available from `src/data/generated/snapshot.metadata.ts`.

## Commands

Generate typed application data:

```bash
npm run data:snapshot
```

Use a specifically named snapshot:

```bash
MOBILE_SNAPSHOT=mobile_snapshot_2026-07-14 npm run data:snapshot
```

Without `MOBILE_SNAPSHOT`, the generator selects the lexically latest `mobile_snapshot_*` directory. `npm start` and `npm run typecheck` generate the data automatically.

## Required files

The current catalog generator requires:

- `brands.csv`
- `products.csv`
- `tire_sizes.csv`
- `product_prices.csv`
- `export_manifest.csv`
- `validation_report.csv`

Discovery reports, SQL, and the data dictionary should stay with the snapshot for auditability.

## Validation and rejection rules

The generator validates CSV rows with Zod and rejects a product when any required relationship or value is invalid, including:

- Missing product, SKU, brand, or display name
- Missing or invalid tire measurements
- Missing brand relationship
- Missing current price
- Non-positive SRP
- Promo price equal to or greater than SRP
- Inactive product or brand

Invalid data must be corrected in the source/export. Do not manually edit the generated TypeScript files.

## Inventory behavior

The warehouse snapshot does not contain a customer-safe inventory feed. Products therefore use:

```ts
stock: null
inStock: null
```

The UI displays “Availability to confirm” and does not claim that an item is in stock. For prototype cart interaction only, unknown-inventory products have a maximum quantity of eight. This is a UX limit, not an inventory value, and final availability must be checked by the production checkout API.

## Refresh procedure

1. Create a new dated directory such as `exports/mobile_snapshot_2026-08-01`.
2. Export the required CSV files using read-only warehouse queries.
3. Include the manifest, validation report, SQL, discovery report, and data dictionary.
4. Run `MOBILE_SNAPSHOT=mobile_snapshot_2026-08-01 npm run data:snapshot`.
5. Review generated/rejected counts and validation severities.
6. Run `npm run typecheck` and perform a catalog/search/cart smoke test.
7. Commit the approved snapshot and generated output together if repository policy permits commercial pricing data.

## Security rules

- Never add warehouse credentials, tokens, service-account keys, customer PII, payment data, supplier costs, or margins.
- Treat price snapshots as commercially sensitive until approved for repository storage and demos.
- Do not connect the mobile client directly to BigQuery, MySQL, or another production database.
- Use read-only warehouse extraction outside the mobile runtime.
- Review image URLs and branch/contact fields before public distribution.

## Production migration

Replace the temporary snapshot adapter with a repository that calls secured endpoints, while keeping domain types and query consumers stable:

```text
catalogSnapshot + mockApi  →  catalogRepository + HTTP API
```

The production API should provide:

- Catalog and product details
- Server-authoritative prices and promotions
- Customer-safe inventory/availability
- Branches and services
- Appointment capacity
- Cart validation and checkout
- Authentication and authorization

CSV generation can remain useful for tests and offline demo fixtures after production API integration, but it must not be the source of truth for live transactions.
