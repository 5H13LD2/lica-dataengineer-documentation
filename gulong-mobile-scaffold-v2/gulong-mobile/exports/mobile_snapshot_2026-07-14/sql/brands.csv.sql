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
