# Data Dictionary

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
