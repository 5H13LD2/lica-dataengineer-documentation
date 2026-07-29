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
    SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\d+') AS INT64) AS rim_diameter,
    CASE
      WHEN SAFE_CAST(section_width AS INT64) IS NOT NULL
        AND SAFE_CAST(aspect_ratio AS INT64) IS NOT NULL
        AND SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\d+') AS INT64) IS NOT NULL
      THEN CONCAT(
        CAST(SAFE_CAST(section_width AS INT64) AS STRING),
        '/',
        CAST(SAFE_CAST(aspect_ratio AS INT64) AS STRING),
        ' R',
        CAST(SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\d+') AS INT64) AS STRING)
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
