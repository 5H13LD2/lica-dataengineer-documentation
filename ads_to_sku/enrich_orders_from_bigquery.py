#!/usr/bin/env python3
"""Enrich decoded Google Ads request IDs from the Gulong backend order model."""

import csv
import json
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
INPUT_CSV = BASE_DIR / "gulong_google_ads_decoded_request_ids.csv"
OUTPUT_CSV = BASE_DIR / "gulong_google_ads_decoded_request_ids_with_orders.csv"


def main() -> None:
    with INPUT_CSV.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))

    order_ids = [row["Decoded request_id"].strip() for row in rows]
    if not order_ids or any(not order_id.isdigit() for order_id in order_ids):
        raise ValueError("Decoded request IDs must all be numeric")

    id_list = ",".join(order_ids)
    query = f"""
    SELECT
      r.id AS order_id,
      CAST(r.order_date AS STRING) AS order_date,
      r.status,
      r.payment_status,
      r.customer_type,
      r.customer_source,
      CAST(c.net_sales_amount AS STRING) AS net_sales_amount,
      r.quantity,
      r.sku,
      r.brand
    FROM `gulong-chatbot-459723.gulong_backend.orders_raw` r
    LEFT JOIN `gulong-chatbot-459723.gulong_core.orders_raw_deduped` c
      ON c.order_id = r.id
    WHERE SAFE_CAST(r.id AS INT64) IN UNNEST([{id_list}])
    """
    result = subprocess.run(
        [
            "bq",
            "query",
            "--use_legacy_sql=false",
            "--format=json",
            "--max_rows=1000",
            query,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    orders = {row["order_id"]: row for row in json.loads(result.stdout)}

    extra_fields = [
        "backend_match_status",
        "order_date",
        "order_status",
        "payment_status",
        "backend_customer_type",
        "backend_customer_source",
        "net_sales_amount",
        "quantity",
        "sku",
        "purchased_brand",
    ]
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]) + extra_fields)
        writer.writeheader()
        for row in rows:
            order = orders.get(row["Decoded request_id"].strip())
            row.update(
                {
                    "backend_match_status": "Matched" if order else "Unmatched",
                    "order_date": order["order_date"] if order else "",
                    "order_status": order["status"] if order else "",
                    "payment_status": order["payment_status"] if order else "",
                    "backend_customer_type": order["customer_type"] if order else "",
                    "backend_customer_source": order["customer_source"] if order else "",
                    "net_sales_amount": order["net_sales_amount"] if order else "",
                    "quantity": order["quantity"] if order else "",
                    "sku": order["sku"] if order else "",
                    "purchased_brand": order["brand"] if order else "",
                }
            )
            writer.writerow(row)

    print(f"Input rows: {len(rows)}")
    print(f"Matched orders: {sum(order_id in orders for order_id in order_ids)}")
    print(f"Output: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
