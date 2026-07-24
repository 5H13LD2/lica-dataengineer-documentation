# Warehouse Discovery Report

Project: `gulong-chatbot-459723`
Region: `asia-southeast1`
Discovery timestamp (UTC): 2026-07-14T07:05:16Z

## Accessible datasets inspected

- `gulong_backend`
- `gulong_core`
- `gulong_reporting`
- Region-wide `INFORMATION_SCHEMA` metadata in `asia-southeast1`

## Reliable catalog export source

### `gulong_backend.price_current`
- Business purpose: latest current active Gulong `/shop` product price snapshot.
- Table type: table.
- Approximate row count: 3,294.
- Primary key reliability: `product_id` is unique in current snapshot.
- Foreign keys: none declared; `brand` is text only, no native `brand_id`.
- Relevant columns:
  - `captured_at DATETIME`
  - `captured_date DATE`
  - `product_id INTEGER`
  - `product_slug STRING`
  - `product_url STRING`
  - `brand STRING`
  - `model STRING`
  - `pattern STRING`
  - `section_width STRING`
  - `aspect_ratio STRING`
  - `rim_size STRING`
  - `load_rating STRING`
  - `speed_rating STRING`
  - `truck_type INTEGER`
  - `default_image STRING`
  - `srp FLOAT`
  - `promo FLOAT`
  - `product_price FLOAT`
  - `dot_sku STRING`
  - `dot_desc STRING`
- Active/deleted/status fields:
  - Table description says it is already the latest active current snapshot.
  - `status_id` is null and `activity` is `0` for all rows, so they are not useful as runtime filters.
- Last-updated field: `captured_at`.
- Data-quality concerns:
  - `dot_sku` is blank for all 3,294 rows.
  - `product_slug` exists for all rows but is duplicated across 3 slugs.
  - `category_name` is null for all rows.
  - `dot_desc` behaves like a DOT year token, not a customer-facing description, so `description` is exported blank.
  - 340 rows have missing `default_image`.
  - 49 rows have invalid `section_width`.
  - 132 rows have invalid `aspect_ratio`.
  - All `rim_size` values require parsing from strings like `R16`.
- Recommended joins:
  - Join brands by normalized `brand` text only.
  - Join prices, products, and tire sizes by `product_id`.

### `gulong_backend.price_snapshots`
- Business purpose: historical snapshots of active `/shop` products and prices.
- Table type: partitioned table on `captured_date`.
- Approximate row count: 59,443.
- Primary key reliability: no single-row primary key across history; use `product_id + captured_at`.
- Foreign keys: none declared.
- Relevant columns: largely the same as `price_current`.
- Active/deleted/status fields: inherits the same active snapshot semantics as `price_current`.
- Last-updated field: `captured_at`.
- Data-quality concerns:
  - Snapshot coverage is sparse, not daily.
  - Verified July 1 to July 13, 2026 coverage exists only on `2026-07-03`, `2026-07-07`, and `2026-07-10`.
- Recommended joins:
  - Use for historical freshness checks and source max-updated timestamps.
  - Do not use as the default app export grain when `price_current` exists.

## Supporting but not export-safe sources

### `gulong_core.orders_all`
- Business purpose: canonical cleaned non-test order lifecycle view for analytics.
- Table type: view.
- Approximate logical row count from query: 23,786.
- Primary key reliability: `order_id`.
- Foreign keys: none declared.
- Relevant columns:
  - `order_id STRING`
  - `order_date DATETIME`
  - `order_day DATE`
  - `branch_name STRING`
  - `installation_partner_name STRING`
  - `appointment_at DATETIME`
  - `appointment_day DATE`
  - `sku STRING`
  - `brand STRING`
  - `canonical_order_tire_size STRING`
  - `quantity_int INTEGER`
- Active/deleted/status fields:
  - Contains full lifecycle rows, including cancelled and unpaid orders.
  - Excludes test orders in view logic.
- Last-updated field: no stable source freshness field for branch-master export; `loaded_at` is view runtime.
- Data-quality concerns:
  - Contains customer and sales data outside mobile catalog scope.
  - Branch values are names only; no stable `branch_id`, address, phone, or coordinates.
- Recommended joins:
  - Use only for discovery and date coverage, not branch master export.

### `gulong_reporting.v_appointment_installation_analytics`
- Business purpose: appointment and installation analytics view over `orders_all`.
- Table type: view.
- Primary key reliability: order-level analytics row, not slot capacity grain.
- Relevant columns:
  - `appointment_date DATE`
  - `appointment_at DATETIME`
  - `branch_name STRING`
  - `installation_partner STRING`
  - `sku STRING`
  - `quantity INTEGER`
  - `appointment_status STRING`
- Data-quality concerns:
  - Represents booked order history, not branch capacity or availability.
  - Includes financial fields (`gross_sales_amount`, `total_cost_amount`, `gross_profit_amount`) that are confidential and must not be exported.
- Recommended joins:
  - Do not use for `appointment_capacity.csv`.

## Relationship assessment

- Reliable:
  - `product_id` links current products, prices, and tire sizes within `gulong_backend.price_current`.
  - Normalized `brand` can support a derived brand dimension.
- Not reliable:
  - No native `brand_id`.
  - No accessible branch master table with stable `branch_id`.
  - No accessible branch service, inventory, approved-branch, or vehicle fitment tables.
  - No authoritative appointment capacity source.

## Stop condition

Required relationships for `branches.csv`, `branch_services.csv`, `inventory.csv`, `appointment_capacity.csv`, and `vehicle_fitments.csv` cannot be determined reliably from the currently accessible warehouse objects. Those exports are omitted rather than inferred.
