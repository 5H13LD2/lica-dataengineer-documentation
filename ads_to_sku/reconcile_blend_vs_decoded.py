#!/usr/bin/env python3
"""Reconcile the GA4/backend blend export with the decoded order-ID export."""

import csv
from pathlib import Path


BASE = Path(__file__).resolve().parent
BLEND = BASE / "GulongPH Web _Purchases_Table.csv"
DECODED = BASE / "gulong_google_ads_decoded_request_ids_with_orders.csv"
OUTPUT = BASE / "gulong_google_ads_blend_reconciliation.csv"


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    blend_rows = read_csv(BLEND)
    decoded_rows = read_csv(DECODED)
    blend_by_id = {row["Order ID"].strip(): row for row in blend_rows}

    output_rows = []
    for decoded in decoded_rows:
        order_id = decoded["Decoded request_id"].strip()
        blend = blend_by_id.get(order_id)
        mismatches = []
        if blend:
            comparisons = [
                ("campaign", blend["Session campaign"], decoded["Session campaign"]),
                ("sku", blend["SKU"], decoded["sku"]),
                ("quantity", blend["quantity"], decoded["quantity"]),
                ("status", blend["Status"], decoded["order_status"]),
                ("payment_status", blend["Payment Status"], decoded["payment_status"]),
            ]
            mismatches = [name for name, left, right in comparisons if left.strip() != right.strip()]

        output_rows.append(
            {
                "order_id": order_id,
                "decoded_campaign": decoded["Session campaign"],
                "ecommerce_purchases": decoded["Ecommerce purchases"],
                "blend_match_status": "Matched" if blend else "Missing from blend",
                "field_match_status": "Matched" if blend and not mismatches else ", ".join(mismatches),
                "decoded_order_status": decoded["order_status"],
                "blend_order_status": blend["Status"] if blend else "",
                "decoded_payment_status": decoded["payment_status"],
                "blend_payment_status": blend["Payment Status"] if blend else "",
                "backend_customer_type": decoded.get("backend_customer_type", ""),
                "backend_customer_source": decoded.get("backend_customer_source", ""),
                "net_sales_amount": decoded["net_sales_amount"],
                "quantity": decoded["quantity"],
                "sku": decoded["sku"],
                "purchased_brand": decoded["purchased_brand"],
                "customer_source_in_blend": blend["customer_source"] if blend else "",
            }
        )

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Decoded rows: {len(decoded_rows)}")
    print(f"Blend rows: {len(blend_rows)}")
    print(f"Matched IDs: {sum(r['blend_match_status'] == 'Matched' for r in output_rows)}")
    print(f"Missing from blend: {sum(r['blend_match_status'] == 'Missing from blend' for r in output_rows)}")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    main()
