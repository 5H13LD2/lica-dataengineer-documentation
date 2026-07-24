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
