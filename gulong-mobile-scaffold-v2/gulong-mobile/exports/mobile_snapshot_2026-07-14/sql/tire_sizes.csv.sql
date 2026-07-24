SELECT
  CAST(product_id AS STRING) AS product_id,
  CAST(SAFE_CAST(section_width AS INT64) AS STRING) AS section_width,
  CAST(SAFE_CAST(aspect_ratio AS INT64) AS STRING) AS aspect_ratio,
  CAST(SAFE_CAST(REGEXP_EXTRACT(COALESCE(rim_size, ''), r'\d+') AS INT64) AS STRING) AS rim_diameter,
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
ORDER BY product_id
