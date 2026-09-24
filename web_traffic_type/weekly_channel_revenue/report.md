# Weekly net sales by source channel

Backend order dates; September 2026. Week 1: 1–7; Week 2: 8–14; Week 3: 15–21; partial Week 4: 22–24. Source channels represent the three supplied CSVs; Direct and Organic are combined. Google Ads is the first CSV label, including its cross-network row. Results use the previously retrieved backend snapshot, not a fresh query.

Net sales use the existing reporting calculation ROUND(total_amount_due / 1.12, 2). All-order values include cancelled, unfinished, return and refund orders. Fulfilled revenue requires fulfilled/partially fulfilled status and fully paid/partial payment status, excluding test orders. Full order value is included for partial payments; this is not cash collected. Each order is counted once. There are no overlapping IDs across the three input files.

## all_order_net_sales

| Week | Google Ads | Direct & Organic | Referral | Total |
|---|---:|---:|---:|---:|
| 1 | ₱522,608.31 | ₱793,046.80 | ₱90,845.09 | ₱1,406,500.20 |
| 2 | ₱232,561.16 | ₱1,071,884.97 | ₱208,630.37 | ₱1,513,076.50 |
| 3 | ₱552,631.53 | ₱684,801.78 | ₱134,840.53 | ₱1,372,273.84 |
| 4 | ₱165,308.48 | ₱312,389.11 | ₱30,268.12 | ₱507,965.71 |
| Total | ₱1,473,109.48 | ₱2,862,122.66 | ₱464,584.11 | ₱4,799,816.25 |

## fulfilled_net_revenue

| Week | Google Ads | Direct & Organic | Referral | Total |
|---|---:|---:|---:|---:|
| 1 | ₱324,575.99 | ₱403,835.56 | ₱76,986.61 | ₱805,398.16 |
| 2 | ₱85,278.66 | ₱601,332.86 | ₱125,783.22 | ₱812,394.74 |
| 3 | ₱100,852.85 | ₱302,360.43 | ₱70,459.11 | ₱473,672.39 |
| 4 | ₱0.00 | ₱0.00 | ₱0.00 | ₱0.00 |
| Total | ₱510,707.50 | ₱1,307,528.85 | ₱273,228.94 | ₱2,091,465.29 |

Excluded from September totals: Google Ads order 38959 (August 31), ₱27,053.57; Direct & Organic order 38805 (August 26), ₱54,174.11. Both are fulfilled. Three unmatched Direct & Organic IDs (39900, 39109, 39052) have unknown dates and revenue. See excluded_orders.csv.
