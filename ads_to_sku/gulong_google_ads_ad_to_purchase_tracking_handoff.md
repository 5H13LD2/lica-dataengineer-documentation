# GulongPH Google Ads Ad-to-Purchase Brand Tracking — AI Handoff

**Status:** Working proof-of-concept; GA4-to-backend bridge confirmed  
**Date documented:** 2026-08-20  
**Primary goal:** Determine whether users/orders attributed to a specific Google Ads campaign for one tire brand (example: **Michelin**) ultimately purchased a different brand (example: **BFGoodrich**).

---

## 1. Business Goal

Answer questions such as:

> A user/order came from the **Michelin - PMax PH** Google Ads campaign. What tire brand was actually ordered in the GulongPH backend?

Desired final reporting example:

| Google Ads Campaign | Ad Brand | Purchased Brand | Unique Orders | Cross-Brand? |
|---|---|---|---:|---|
| Michelin - PMax PH | Michelin | Michelin | 45 | No |
| Michelin - PMax PH | Michelin | BFGoodrich | 8 | Yes |
| Michelin - PMax PH | Michelin | Hankook | 3 | Yes |

Useful downstream KPIs:

- Same-brand attributed orders
- Cross-brand attributed orders
- Cross-brand order rate
- Fulfilled cross-brand orders
- Fulfilled cross-brand rate
- Revenue by campaign × purchased brand
- Quantity by campaign × purchased brand

---

## 2. Why the Original GA4-Only Approach Did Not Work

The original plan was to use GA4 Exploration with:

- `Session campaign`
- `Item brand`
- `Items purchased`

However, testing showed:

- `Item brand` = `(not set)`
- `Item name` = `(not set)`
- `Transaction ID` was not usable/populated for this analysis

Therefore, GA4 knows that ecommerce activity/purchases happened, but the current GA4 ecommerce payload does **not expose enough product/order detail** to directly answer:

> Michelin campaign → BFGoodrich purchase

The old GA4 → BigQuery analytics pipeline is also no longer updating, so the solution should not depend on that pipeline.

---

## 3. Key Discovery / Workaround

The GA4 purchase/complete-order page contains an encoded backend request/order ID in the URL.

Example:

```text
/complete-order?requestid=MzgwNTY=
```

Decoding process:

```text
MzgwNTY=
↓ Base64 decode
38056
```

The decoded value `38056` was checked against the backend and **matched an actual backend order with `id = 38056`**.

Backend proof sample:

```text
id: 38056
brand: HANKOOK
quantity: 4
status: Pending
payment_status: Pending
payment_option: INSTALLMENT LATER-GP
```

This confirms the bridge:

```text
GA4 Session Campaign
        ↓
/complete-order?requestid=<encoded>
        ↓
URL decode if needed
        ↓
Base64 decode
        ↓
Backend order/request ID
        ↓
Backend purchased brand
```

This is the current working method.

---

## 4. Looker Studio / GA4 Extraction Setup

Use the GA4-connected Looker Studio data source to make a simple export/staging table.

### Dimensions

Use:

1. `Session campaign`
2. `Page path + query string`

Do **not** include the following in the final extraction table unless needed for QA:

- Item brand
- Item name
- Transaction ID
- Session default channel group
- Date

Reason for omitting `Date` in the final export: adding more dimensions can split the same request/order across multiple rows. If Date is needed for QA, deduplicate by decoded request ID afterward.

### Metric

Use:

```text
Ecommerce purchases
```

Keep it for QA/reference only.

Do **not** use `SUM(Ecommerce purchases)` as the final backend order count.

### Recommended calculated metric

Create:

```text
Unique Request Orders
```

Formula:

```text
COUNT_DISTINCT(Page path + query string)
```

This is useful for scorecards/QA while the table is already filtered to complete-order request URLs.

### Required Filters

#### Filter 1 — Google Ads traffic

```text
Session source / medium = google / cpc
```

#### Filter 2 — Complete-order URLs only

```text
Page path + query string
contains
/complete-order?requestid=
```

#### Filter 3 — Positive ecommerce activity only

```text
Ecommerce purchases > 0
```

### Final extraction shape

| Session campaign | Page path + query string | Ecommerce purchases |
|---|---|---:|
| Michelin - PMax PH | `/complete-order?requestid=...` | 1 or more |
| All Brand - PMax PH | `/complete-order?requestid=...` | 1 or more |

Export the table as CSV.

---

## 5. Request ID Decoding Logic

For each exported `Page path + query string`:

1. Extract the value after `requestid=`
2. URL-decode it
   - Example: `%3D` becomes `=`
3. Base64-decode the result
4. Treat the decoded numeric value as the backend order/request ID

### Python reference implementation

```python
import base64
import urllib.parse
import re

def decode_request_id(page_path):
    match = re.search(r"(?:\?|&)requestid=([^&]+)", page_path)
    if not match:
        return None

    encoded = match.group(1)
    url_decoded = urllib.parse.unquote(encoded)

    # Restore Base64 padding if needed.
    padded = url_decoded + "=" * ((4 - len(url_decoded) % 4) % 4)

    return base64.b64decode(padded).decode("utf-8")
```

Example:

```text
/complete-order?requestid=Mzg0MDk%3D

Mzg0MDk%3D
↓ URL decode
Mzg0MDk=
↓ Base64 decode
38409
```

---

## 6. Current Export Results

The cleaned Looker/GA4 export used in this proof-of-concept contained:

- **77 rows**
- **77 unique decoded request IDs**
- **0 zero-purchase rows**
- **102 total GA4 `Ecommerce purchases`**

Campaign breakdown:

| Session Campaign | Unique Request IDs | GA4 Ecommerce Purchases |
|---|---:|---:|
| Michelin - PMax PH | **44** | **58** |
| All Brand - PMax PH | 12 | 17 |
| BFG Advantage Touring – PMax PH | 7 | 8 |
| BFG - PMax (Traffic) | 5 | 8 |
| SRC \| All Brands \| PH | 5 | 6 |
| (cross-network) | 4 | 5 |
| **Total** | **77** | **102** |

### Important QA finding

`Ecommerce purchases = 102` while there are only `77` unique complete-order request IDs.

Therefore:

```text
SUM(Ecommerce purchases)
```

must **not** be treated as the actual backend order count for this analysis.

The correct order-counting basis is:

```text
COUNT(DISTINCT decoded_request_id)
```

The exact reason for the 102 vs 77 difference has not yet been proven. Possible causes include duplicate/repeated ecommerce purchase measurement or other GA4 event behavior. Do not label it as a confirmed tagging bug until investigated.

---

## 7. Decoded Output File Already Created

A decoded CSV has already been generated:

```text
gulong_google_ads_decoded_request_ids.csv
```

Columns:

- `Session campaign`
- `Page path + query string`
- `Encoded requestid`
- `Decoded request_id`
- `Ecommerce purchases`

Current file status:

```text
Rows: 77
Unique decoded request IDs: 77
```

This decoded file is ready to join to backend order data.

---

## 8. Backend Join

Join:

```text
decoded_request_id
=
backend order.id
```

The backend data currently exposes useful fields such as:

- `id`
- `order_date`
- `pickup_date`
- `payment_status`
- `status`
- `customer_type`
- `payment_option`
- `transaction_type`
- `quantity`
- `sku`
- `brand`

For row-level order QA, the current Gulong BigQuery source map uses backend/core order data. Validate the live schema before hard-coding a production join.

Conceptual SQL:

```sql
SELECT
  a.session_campaign,
  a.decoded_request_id,
  o.id AS backend_order_id,
  o.brand AS purchased_brand,
  o.sku,
  o.quantity,
  o.status,
  o.payment_status,
  o.payment_option
FROM attribution_export a
LEFT JOIN backend_orders o
  ON CAST(o.id AS STRING) = a.decoded_request_id;
```

### Required QA after join

Calculate:

```text
backend_match_rate =
matched unique request IDs / total unique decoded request IDs
```

For the current dataset:

```text
denominator = 77 unique decoded request IDs
```

Target: ideally near 100%.

Investigate every unmatched ID before final reporting.

---

## 9. Campaign-to-Ad-Brand Mapping

To identify cross-brand purchases, map single-brand campaigns to the brand they advertise.

Suggested mapping from the current export:

| Session Campaign | Ad Brand |
|---|---|
| Michelin - PMax PH | MICHELIN |
| BFG Advantage Touring – PMax PH | BFGOODRICH |
| BFG - PMax (Traffic) | BFGOODRICH |
| All Brand - PMax PH | MULTI_BRAND |
| SRC \| All Brands \| PH | MULTI_BRAND |
| (cross-network) | UNKNOWN / REVIEW |

Do **not** classify `MULTI_BRAND` or `UNKNOWN` campaigns as same-brand/cross-brand without a defined business rule.

### Cross-brand rule

Only for campaigns with a single known advertised brand:

```text
cross_brand_flag =
UPPER(ad_brand) != UPPER(purchased_brand)
```

Example:

```text
ad_brand = MICHELIN
purchased_brand = BFGOODRICH
→ cross_brand_flag = TRUE
```

---

## 10. Recommended Final Metrics

### A. Attributed Orders

```text
COUNT(DISTINCT decoded_request_id)
```

### B. Same-Brand Orders

```text
COUNT(DISTINCT request_id)
where ad_brand = purchased_brand
```

### C. Cross-Brand Orders

```text
COUNT(DISTINCT request_id)
where ad_brand != purchased_brand
and ad_brand is a single known brand
```

### D. Cross-Brand Order Rate

```text
cross_brand_orders
/
all attributed orders from single-brand campaigns
```

### E. Fulfilled Cross-Brand Orders

Use backend fulfillment logic/status instead of assuming every GA4 `purchase` is a completed sale.

This is important because the confirmed sample `id = 38056` was:

```text
status: Pending
payment_status: Pending
payment_option: INSTALLMENT LATER-GP
```

even though it appeared in the GA4 complete-order/purchase flow.

Therefore, distinguish:

```text
Ad → Order Created
```

from:

```text
Ad → Fulfilled Purchase
```

For management/commercial reporting, fulfilled orders should be the stronger KPI.

---

## 11. Recommended Final Report

### Campaign × Purchased Brand

| Campaign | Ad Brand | Purchased Brand | Unique Orders | Fulfilled Orders | Net Sales | Cross-Brand |
|---|---|---|---:|---:|---:|---|
| Michelin - PMax PH | Michelin | Michelin | X | X | ₱X | No |
| Michelin - PMax PH | Michelin | BFGoodrich | X | X | ₱X | Yes |
| Michelin - PMax PH | Michelin | Hankook | X | X | ₱X | Yes |

### Campaign summary

| Campaign | Total Attributed Orders | Same-Brand Orders | Cross-Brand Orders | Cross-Brand Rate |
|---|---:|---:|---:|---:|
| Michelin - PMax PH | X | X | X | X% |
| BFG Advantage Touring – PMax PH | X | X | X | X% |

---

## 12. What This Method Can and Cannot Answer

### It CAN answer

With the current setup:

> For a purchase/complete-order session attributed to a Google Ads campaign, what brand exists on the matching backend order?

Example:

```text
Michelin campaign
→ request ID
→ backend order
→ HANKOOK
```

### It does NOT fully answer cross-session attribution

Scenario:

```text
Day 1: User clicks Michelin Google Ad
Day 5: User returns Direct
Day 5: User buys BFGoodrich
```

Because the current extraction uses:

```text
Session campaign
```

the purchase session may be attributed to Direct rather than the Michelin click from Day 1.

Therefore, do not describe the current method as a complete first-touch or multi-session attribution model.

Use wording such as:

> "Purchased brand by Google Ads campaign attributed to the order/complete-order session."

---

## 13. Future Production-Grade Improvement

For true:

> Michelin ad click → later BFG purchase, even across sessions

persist first-party ad attribution into the backend order.

Recommended fields:

```text
gclid
gbraid
wbraid

utm_source
utm_medium
utm_campaign

campaign_id
asset_group_id
ad_brand

landing_page
attribution_timestamp
```

Prefer storing both:

```text
first_paid_*
last_paid_*
```

Example:

```text
first_paid_ad_brand
first_paid_campaign_id
first_paid_gclid
first_paid_at

last_paid_ad_brand
last_paid_campaign_id
last_paid_gclid
last_paid_at
```

Then the backend itself becomes the durable attribution source.

A manual test confirmed that the website can preserve a URL parameter such as:

```text
https://gulong.ph/?gclid=test123
```

However, this does **not** prove that GCLID is currently persisted into the backend order.

---

## 14. Execution Checklist for Another AI / Analyst

- [ ] Confirm Looker table uses `Session campaign` and `Page path + query string`
- [ ] Metric is `Ecommerce purchases`
- [ ] Filter `Session source / medium = google / cpc`
- [ ] Filter page path contains `/complete-order?requestid=`
- [ ] Filter `Ecommerce purchases > 0`
- [ ] Export CSV
- [ ] Extract `requestid`
- [ ] URL-decode request ID
- [ ] Base64-decode request ID
- [ ] Deduplicate by decoded request ID
- [ ] Join decoded request ID to backend `id`
- [ ] Calculate backend match rate
- [ ] Retrieve backend `brand`, SKU, quantity, status, payment status, and sales fields
- [ ] Map single-brand Google Ads campaigns to `ad_brand`
- [ ] Create same-brand/cross-brand flag
- [ ] Count orders using distinct decoded/backend IDs, not GA4 purchase sum
- [ ] Separate order-created results from fulfilled-order results
- [ ] Produce campaign × purchased-brand breakdown
- [ ] Calculate cross-brand order rate
- [ ] QA unmatched IDs and suspicious duplicates before publishing

---

## 15. Success Criteria

The implementation is considered properly executed when:

1. Every exported GA4 complete-order row has a valid decoded request ID.
2. Decoded IDs have been deduplicated.
3. Backend match rate is calculated and unexplained unmatched IDs are investigated.
4. Purchased brand comes from the backend, not inferred from GA4 product fields.
5. Final order count uses distinct backend/request IDs.
6. Single-brand campaigns have an explicit `ad_brand` mapping.
7. Cross-brand flags are only calculated for campaigns where the advertised brand is known.
8. Pending/unfulfilled orders are not automatically reported as completed sales.
9. The final report clearly distinguishes session-attributed orders from true cross-session attribution.
10. Results can be reproduced from the Looker export + backend order source.

---

## 16. Current Handoff State

**Completed:**

- GA4 product fields were tested and found unusable for brand-level purchase attribution.
- Complete-order `requestid` bridge was discovered.
- Base64 decoding was validated.
- Decoded ID `38056` was confirmed against a real backend order.
- Clean Looker extraction configuration was established.
- A cleaned export with 77 positive rows was obtained.
- All 77 request IDs were decoded successfully.
- Current campaign-level unique-request counts were validated.
- GA4 purchase count vs unique request-order discrepancy was identified.

**Next task:**

> Join all 77 decoded request IDs to backend order data and produce the first real Campaign × Purchased Brand table, then separate Order Created vs Fulfilled Purchase results.

