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
