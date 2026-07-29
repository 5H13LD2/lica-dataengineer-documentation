#!/usr/bin/env python3
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ID = "gulong-chatbot-459723"
DATASET = "gulong_backend"
TOKEN_ENV = "GOOGLE_BQ_ACCESS_TOKEN"
EXPORT_ROOT = Path("exports/mobile_snapshot_2026-07-14")


EXPORT_QUERIES = {
    "brands.csv": """
WITH source AS (
  SELECT DISTINCT
    UPPER(TRIM(brand)) AS brand_name,
    captured_at
  FROM `gulong-chatbot-459723.gulong_backend.price_current`
  WHERE TRIM(COALESCE(brand, '')) <> ''
)
SELECT
  TO_HEX(SHA256(brand_name)) AS brand_id,
  brand_name,
  TRUE AS is_active,
  FORMAT_DATETIME('%Y-%m-%dT%H:%M:%S', MAX(captured_at)) AS updated_at
FROM source
GROUP BY brand_name
ORDER BY brand_name
""".strip(),
    "products.csv": """
WITH source AS (
  SELECT
    product_id,
    NULLIF(TRIM(COALESCE(dot_sku, product_slug)), '') AS sku,
    UPPER(TRIM(brand)) AS brand_name,
    model,
    product_slug,
    load_rating,
    speed_rating,
    truck_type,
    default_image,
    captured_at
  FROM `gulong-chatbot-459723.gulong_backend.price_current`
  WHERE product_id IS NOT NULL
)
SELECT
  CAST(product_id AS STRING) AS product_id,
  sku,
  TO_HEX(SHA256(brand_name)) AS brand_id,
  NULLIF(TRIM(model), '') AS product_name,
  NULLIF(TRIM(model), '') AS display_name,
  '' AS description,
  '' AS category,
  NULLIF(TRIM(load_rating), '') AS load_index,
  NULLIF(TRIM(speed_rating), '') AS speed_rating,
  IFNULL(truck_type = 1, FALSE) AS is_light_truck,
  NULLIF(TRIM(default_image), '') AS image_url,
  TRUE AS is_active,
  FORMAT_DATETIME('%Y-%m-%dT%H:%M:%S', captured_at) AS updated_at
FROM source
ORDER BY product_id
""".strip(),
    "tire_sizes.csv": """
SELECT
  CAST(product_id AS STRING) AS product_id,
  CAST(SAFE_CAST(section_width AS INT64) AS STRING) AS section_width,
  CAST(SAFE_CAST(aspect_ratio AS INT64) AS STRING) AS aspect_ratio,
  CAST(SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\\d+') AS INT64) AS STRING) AS rim_diameter,
  CASE
    WHEN SAFE_CAST(section_width AS INT64) IS NOT NULL
      AND SAFE_CAST(aspect_ratio AS INT64) IS NOT NULL
      AND SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\\d+') AS INT64) IS NOT NULL
    THEN CONCAT(
      CAST(SAFE_CAST(section_width AS INT64) AS STRING),
      '/',
      CAST(SAFE_CAST(aspect_ratio AS INT64) AS STRING),
      ' R',
      CAST(SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\\d+') AS INT64) AS STRING)
    )
    ELSE ''
  END AS size_display,
  IFNULL(truck_type = 1, FALSE) AS is_light_truck,
  FORMAT_DATETIME('%Y-%m-%dT%H:%M:%S', captured_at) AS updated_at
FROM `gulong-chatbot-459723.gulong_backend.price_current`
WHERE product_id IS NOT NULL
ORDER BY product_id
""".strip(),
    "product_prices.csv": """
SELECT
  CAST(product_id AS STRING) AS product_id,
  CAST(ROUND(srp, 2) AS STRING) AS srp,
  CASE
    WHEN promo IS NOT NULL AND promo > 0 AND promo < srp THEN CAST(ROUND(promo, 2) AS STRING)
    ELSE ''
  END AS promo_price,
  'PHP' AS currency,
  '' AS promo_start_at,
  '' AS promo_end_at,
  TRUE AS is_current,
  FORMAT_DATETIME('%Y-%m-%dT%H:%M:%S', captured_at) AS updated_at
FROM `gulong-chatbot-459723.gulong_backend.price_current`
WHERE product_id IS NOT NULL
ORDER BY product_id
""".strip(),
    "validation_report.csv": """
WITH brands AS (
  WITH source AS (
    SELECT DISTINCT
      UPPER(TRIM(brand)) AS brand_name,
      captured_at
    FROM `gulong-chatbot-459723.gulong_backend.price_current`
    WHERE TRIM(COALESCE(brand, '')) <> ''
  )
  SELECT
    TO_HEX(SHA256(brand_name)) AS brand_id,
    brand_name,
    TRUE AS is_active,
    FORMAT_DATETIME('%Y-%m-%dT%H:%M:%S', MAX(captured_at)) AS updated_at
  FROM source
  GROUP BY brand_name
),
products AS (
  SELECT
    CAST(product_id AS STRING) AS product_id,
    NULLIF(TRIM(COALESCE(dot_sku, product_slug)), '') AS sku,
    TO_HEX(SHA256(UPPER(TRIM(brand)))) AS brand_id,
    NULLIF(TRIM(model), '') AS product_name,
    NULLIF(TRIM(model), '') AS display_name,
    '' AS description,
    '' AS category,
    NULLIF(TRIM(load_rating), '') AS load_index,
    NULLIF(TRIM(speed_rating), '') AS speed_rating,
    IFNULL(truck_type = 1, FALSE) AS is_light_truck,
    NULLIF(TRIM(default_image), '') AS image_url,
    TRUE AS is_active,
    FORMAT_DATETIME('%Y-%m-%dT%H:%M:%S', captured_at) AS updated_at
  FROM `gulong-chatbot-459723.gulong_backend.price_current`
  WHERE product_id IS NOT NULL
),
tire_sizes AS (
  SELECT
    CAST(product_id AS STRING) AS product_id,
    SAFE_CAST(section_width AS INT64) AS section_width,
    SAFE_CAST(aspect_ratio AS INT64) AS aspect_ratio,
    SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\\d+') AS INT64) AS rim_diameter,
    CASE
      WHEN SAFE_CAST(section_width AS INT64) IS NOT NULL
        AND SAFE_CAST(aspect_ratio AS INT64) IS NOT NULL
        AND SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\\d+') AS INT64) IS NOT NULL
      THEN CONCAT(
        CAST(SAFE_CAST(section_width AS INT64) AS STRING),
        '/',
        CAST(SAFE_CAST(aspect_ratio AS INT64) AS STRING),
        ' R',
        CAST(SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\\d+') AS INT64) AS STRING)
      )
      ELSE ''
    END AS size_display,
    IFNULL(truck_type = 1, FALSE) AS is_light_truck,
    FORMAT_DATETIME('%Y-%m-%dT%H:%M:%S', captured_at) AS updated_at
  FROM `gulong-chatbot-459723.gulong_backend.price_current`
  WHERE product_id IS NOT NULL
),
product_prices AS (
  SELECT
    CAST(product_id AS STRING) AS product_id,
    srp,
    promo,
    TRUE AS is_current,
    FORMAT_DATETIME('%Y-%m-%dT%H:%M:%S', captured_at) AS updated_at
  FROM `gulong-chatbot-459723.gulong_backend.price_current`
  WHERE product_id IS NOT NULL
)
SELECT * FROM (
  SELECT
    'brands.csv' AS dataset,
    brand_id AS row_identifier,
    'error' AS severity,
    'duplicate_primary_key' AS rule,
    'Duplicate brand_id detected.' AS message,
    'Investigate brand-name normalization and deduplicate before publish.' AS recommended_action
  FROM brands
  GROUP BY brand_id
  HAVING COUNT(*) > 1

  UNION ALL

  SELECT
    'products.csv',
    product_id,
    'error',
    'missing_required_id',
    'Product is missing product_id.',
    'Backfill product_id in source or exclude with documented approval.'
  FROM products
  WHERE TRIM(COALESCE(product_id, '')) = ''

  UNION ALL

  SELECT
    'products.csv',
    product_id,
    'error',
    'duplicate_primary_key',
    'Duplicate product_id detected.',
    'Deduplicate source rows before export.'
  FROM products
  GROUP BY product_id
  HAVING COUNT(*) > 1

  UNION ALL

  SELECT
    'products.csv',
    product_id,
    'error',
    'broken_foreign_key',
    'brand_id does not resolve to brands.csv.',
    'Backfill brand value or regenerate brand dimension.'
  FROM products p
  LEFT JOIN brands b
    ON b.brand_id = p.brand_id
  WHERE b.brand_id IS NULL

  UNION ALL

  SELECT
    'products.csv',
    product_id,
    'warning',
    'missing_sku_source',
    'Source table has no dedicated sellable SKU; exported sku uses dot_sku fallback to product_slug when available.',
    'Confirm whether product_slug is acceptable for app routing and cart references.'
  FROM products
  WHERE sku IS NULL OR sku LIKE '%-%'

  UNION ALL

  SELECT
    'products.csv',
    product_id,
    'warning',
    'missing_description',
    'Product description is empty.',
    'Backfill copy from a trusted product-content source if needed in-app.'
  FROM products
  WHERE description IS NULL

  UNION ALL

  SELECT
    'products.csv',
    product_id,
    'warning',
    'missing_category',
    'Category is unavailable in the accessible warehouse source.',
    'Leave blank until a reliable category dimension is exposed.'
  FROM products
  WHERE category = ''

  UNION ALL

  SELECT
    'tire_sizes.csv',
    product_id,
    'error',
    'invalid_tire_measurements',
    'One or more tire size components are missing or invalid.',
    'Correct section_width, aspect_ratio, or rim_size in source.'
  FROM tire_sizes
  WHERE section_width IS NULL OR aspect_ratio IS NULL OR rim_diameter IS NULL

  UNION ALL

  SELECT
    'product_prices.csv',
    product_id,
    'error',
    'missing_current_price',
    'Current SRP is missing.',
    'Backfill current price in source before publish.'
  FROM product_prices
  WHERE srp IS NULL

  UNION ALL

  SELECT
    'product_prices.csv',
    product_id,
    'error',
    'negative_or_zero_price',
    'SRP or promo price is non-positive.',
    'Fix invalid monetary values in source.'
  FROM product_prices
  WHERE srp <= 0 OR (promo IS NOT NULL AND promo <= 0)

  UNION ALL

  SELECT
    'product_prices.csv',
    product_id,
    'error',
    'promo_greater_than_srp',
    'Promo price is greater than SRP.',
    'Review promo logic before publish.'
  FROM product_prices
  WHERE promo IS NOT NULL AND srp IS NOT NULL AND promo > srp

  UNION ALL

  SELECT
    'products.csv',
    CAST(product_id AS STRING),
    'warning',
    'leading_or_trailing_whitespace',
    'Whitespace detected in a text field.',
    'Trim source values before export.'
  FROM `gulong-chatbot-459723.gulong_backend.price_current`
  WHERE product_id IS NOT NULL
    AND (
      brand != TRIM(brand)
      OR model != TRIM(model)
      OR IFNULL(dot_desc, '') != TRIM(IFNULL(dot_desc, ''))
    )

  UNION ALL

  SELECT
    'branches.csv',
    'source_unavailable',
    'warning',
    'unavailable_source',
    'No accessible branch master table with stable branch_id, address, phone, coordinates, lead_days, and customer-approved status.',
    'Do not export branches.csv until a reliable non-PII branch dimension is exposed.'

  UNION ALL

  SELECT
    'branch_services.csv',
    'source_unavailable',
    'warning',
    'unavailable_source',
    'No accessible service availability mapping by branch_id.',
    'Do not export branch_services.csv until a reliable branch-service source is exposed.'

  UNION ALL

  SELECT
    'inventory.csv',
    'source_unavailable',
    'warning',
    'unavailable_source',
    'No accessible inventory table or customer-safe stock status feed by branch and product.',
    'Do not export inventory.csv until a safe inventory source is exposed.'

  UNION ALL

  SELECT
    'appointment_capacity.csv',
    'source_unavailable',
    'warning',
    'unavailable_source',
    'Accessible appointment data is order history, not a capacity schedule.',
    'Do not fabricate appointment capacity from booked orders.'

  UNION ALL

  SELECT
    'vehicle_fitments.csv',
    'source_unavailable',
    'warning',
    'unavailable_source',
    'No authoritative vehicle fitment source is accessible in this warehouse project.',
    'Do not infer fitments from SKU text or historical orders.'
)
ORDER BY dataset, row_identifier, rule
""".strip(),
}


DISCOVERY_REPORT = """# Warehouse Discovery Report

Project: `gulong-chatbot-459723`
Region: `asia-southeast1`
Discovery timestamp (UTC): {exported_at}

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
"""


DATA_DICTIONARY = """# Data Dictionary

## brands.csv
- `brand_id`: deterministic SHA256 hash of normalized `brand` text because no native warehouse `brand_id` is exposed.
- `brand_name`: uppercase normalized brand name from `price_current.brand`.
- `is_active`: always `true`; source table is already the current active snapshot.
- `updated_at`: ISO 8601 datetime from the latest `captured_at` for that brand.

## products.csv
- `product_id`: stable warehouse `product_id`.
- `sku`: `dot_sku` when present, otherwise `product_slug`; source has no dedicated sellable SKU field populated.
- `brand_id`: deterministic brand key used to join to `brands.csv`.
- `product_name`: `model`.
- `display_name`: `model`.
- `description`: blank; the accessible source does not expose reliable customer-facing product copy, and `dot_desc` behaves like a DOT year token.
- `category`: blank because no reliable category field is populated in the accessible source.
- `load_index`: `load_rating`.
- `speed_rating`: `speed_rating`.
- `is_light_truck`: `true` when `truck_type = 1`, else `false`.
- `image_url`: `default_image`.
- `is_active`: always `true`; source table is already the current active snapshot.
- `updated_at`: ISO 8601 datetime from `captured_at`.

Row grain: one row per current sellable `product_id` in `price_current`.

## tire_sizes.csv
- `product_id`: stable warehouse `product_id`.
- `section_width`: integer parsed from `section_width`; blank when invalid.
- `aspect_ratio`: integer parsed from `aspect_ratio`; blank when invalid.
- `rim_diameter`: integer parsed from `rim_size` digits; blank when invalid.
- `size_display`: normalized `section_width/aspect_ratio Rrim_diameter` when all components are valid.
- `is_light_truck`: `true` when `truck_type = 1`, else `false`.
- `updated_at`: ISO 8601 datetime from `captured_at`.

## product_prices.csv
- `product_id`: stable warehouse `product_id`.
- `srp`: current SRP from `price_current.srp`.
- `promo_price`: current promo from `price_current.promo` only when positive and below SRP.
- `currency`: constant `PHP`.
- `promo_start_at`: blank; the accessible source does not expose promo start timestamps.
- `promo_end_at`: blank; the accessible source does not expose promo end timestamps.
- `is_current`: always `true`; export is sourced from `price_current`.
- `updated_at`: ISO 8601 datetime from `captured_at`.

Current-price selection: `price_current` is already the latest active snapshot table. No multi-record price arbitration was required inside the export.

## validation_report.csv
- `dataset`: target CSV name under validation.
- `row_identifier`: dataset-specific key or `source_unavailable`.
- `severity`: `error`, `warning`, or `info`.
- `rule`: validation rule code.
- `message`: human-readable issue summary.
- `recommended_action`: remediation guidance.

## export_manifest.csv
- `file_name`: CSV artifact name.
- `source_tables`: upstream warehouse tables or views.
- `row_grain`: business grain of one row.
- `row_count`: exported row count.
- `exported_at`: UTC ISO 8601 export timestamp.
- `source_max_updated_at`: max source freshness timestamp used for the export.
- `filters_applied`: explicit source filters or source-table semantics.
- `contains_sensitive_data`: `true` when commercial sensitivity exists.
- `notes`: export caveats or omission reason.
"""


def bq_request(path, payload):
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise RuntimeError(f"Missing {TOKEN_ENV}")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://bigquery.googleapis.com/bigquery/v2/{path}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bq_get(url):
    token = os.environ.get(TOKEN_ENV)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_query(sql):
    payload = {"query": sql, "useLegacySql": False, "timeoutMs": 30000}
    result = bq_request(f"projects/{PROJECT_ID}/queries", payload)
    while not result.get("jobComplete", True):
        job_ref = result["jobReference"]
        time.sleep(2)
        result = bq_get(
            "https://bigquery.googleapis.com/bigquery/v2/projects/"
            f"{job_ref['projectId']}/queries/{job_ref['jobId']}"
        )
    rows = result.get("rows", [])
    schema = result.get("schema", {}).get("fields", [])
    page_token = result.get("pageToken")
    job_ref = result.get("jobReference")
    while page_token:
        next_page = bq_get(
            "https://bigquery.googleapis.com/bigquery/v2/projects/"
            f"{job_ref['projectId']}/queries/{job_ref['jobId']}?pageToken={page_token}"
        )
        rows.extend(next_page.get("rows", []))
        page_token = next_page.get("pageToken")
    return schema, rows


def normalize_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def flatten_row(schema_fields, row):
    out = []
    raw_cells = row.get("f", [])
    for field, cell in zip(schema_fields, raw_cells):
        value = cell.get("v")
        if field.get("mode") == "REPEATED":
            if not value:
                out.append("")
            else:
                out.append(json.dumps([item.get("v") for item in value], ensure_ascii=False))
        else:
            out.append(normalize_value(value))
    return out


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def write_text(path, content):
    path.write_text(content, encoding="utf-8")


def main():
    exported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    queries_dir = EXPORT_ROOT / "sql"
    queries_dir.mkdir(parents=True, exist_ok=True)

    row_counts = {}
    source_max_updated_at = "2026-07-14T06:10:45"

    for name, sql in EXPORT_QUERIES.items():
        write_text(queries_dir / f"{name}.sql", sql + "\n")
        schema, rows = run_query(sql)
        headers = [field["name"] for field in schema]
        flat_rows = [flatten_row(schema, row) for row in rows]
        write_csv(EXPORT_ROOT / name, headers, flat_rows)
        row_counts[name] = len(flat_rows)

    manifest_rows = [
        [
            "brands.csv",
            "gulong_backend.price_current",
            "one row per normalized brand",
            row_counts.get("brands.csv", 0),
            exported_at,
            source_max_updated_at,
            "brand nonblank; source table already current active snapshot",
            "false",
            "brand_id is deterministic hash because no native brand_id is exposed",
        ],
        [
            "products.csv",
            "gulong_backend.price_current",
            "one row per current product_id",
            row_counts.get("products.csv", 0),
            exported_at,
            source_max_updated_at,
            "product_id nonnull; source table already current active snapshot",
            "false",
            "sku uses dot_sku fallback to product_slug because explicit SKU is not populated",
        ],
        [
            "tire_sizes.csv",
            "gulong_backend.price_current",
            "one row per current product_id",
            row_counts.get("tire_sizes.csv", 0),
            exported_at,
            source_max_updated_at,
            "product_id nonnull; invalid measurements kept as blanks and flagged in validation_report.csv",
            "false",
            "size_display emitted only when all size components are valid",
        ],
        [
            "product_prices.csv",
            "gulong_backend.price_current",
            "one row per current product_id",
            row_counts.get("product_prices.csv", 0),
            exported_at,
            source_max_updated_at,
            "product_id nonnull; source table already current active snapshot",
            "true",
            "commercially sensitive product pricing; promo start/end timestamps unavailable",
        ],
        [
            "branches.csv",
            "unavailable",
            "not exported",
            0,
            exported_at,
            "",
            "omitted",
            "false",
            "no reliable accessible branch master source",
        ],
        [
            "branch_services.csv",
            "unavailable",
            "not exported",
            0,
            exported_at,
            "",
            "omitted",
            "false",
            "no reliable accessible branch-service source",
        ],
        [
            "inventory.csv",
            "unavailable",
            "not exported",
            0,
            exported_at,
            "",
            "omitted",
            "false",
            "no reliable accessible inventory source",
        ],
        [
            "appointment_capacity.csv",
            "gulong_reporting.v_appointment_installation_analytics",
            "not exported",
            0,
            exported_at,
            "",
            "omitted",
            "false",
            "view is order history, not capacity availability",
        ],
        [
            "vehicle_fitments.csv",
            "unavailable",
            "not exported",
            0,
            exported_at,
            "",
            "omitted",
            "false",
            "no authoritative fitment source available",
        ],
        [
            "validation_report.csv",
            "gulong_backend.price_current",
            "one row per validation finding",
            row_counts.get("validation_report.csv", 0),
            exported_at,
            source_max_updated_at,
            "validation only",
            "false",
            "includes unavailability warnings for omitted datasets",
        ],
    ]
    write_csv(
        EXPORT_ROOT / "export_manifest.csv",
        [
            "file_name",
            "source_tables",
            "row_grain",
            "row_count",
            "exported_at",
            "source_max_updated_at",
            "filters_applied",
            "contains_sensitive_data",
            "notes",
        ],
        manifest_rows,
    )

    write_text(EXPORT_ROOT / "discovery_report.md", DISCOVERY_REPORT.format(exported_at=exported_at))
    write_text(EXPORT_ROOT / "data_dictionary.md", DATA_DICTIONARY)

    summary = {
        "export_root": str(EXPORT_ROOT),
        "row_counts": row_counts,
        "exported_at": exported_at,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        sys.stderr.write(exc.read().decode("utf-8") + "\n")
        raise
