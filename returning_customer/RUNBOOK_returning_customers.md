# Runbook — Returning Customers, August 2026

Kumpletong step-by-step ng buong analysis: mga command (BigQuery SQL + Python),
mga file, ang sinuri ko sa bawat step, at ang mga desisyon. Layunin: masundan mo
at ma-reproduce mo ito nang mag-isa.

- **Project:** `gulong-chatbot-459723`  ·  **Location:** `asia-southeast1`
- **Scope:** August 2026 = Aug 1–19 (partial pa; ngayon Aug 20)
- **Definition ng "valid order":** reportable **booked** order (galing `gulong_core.orders_booked`)
- **Returning:** customer na may booked order sa August AT may booked order bago mag-Aug 1

---

## Tools na ginamit

- **Gulong BigQuery MCP** (`execute_sql_readonly`, `get_table_info`) — read-only BQ access
- **Python 3 + pandas** (local) — para sa join at analysis
- Files sa `/home/claude` (scratch) at `/mnt/user-data/outputs` (deliverables)

---

## STEP 1 — Hanapin ang customer identifier sa order data

**Bakit:** Para malaman kung "returning" ang isang customer, kailangan ng stable
identifier na tumatawid sa maraming order (contact no / email / customer id).

**Command (BQ) — schema check:**
```
-- via get_table_info (o INFORMATION_SCHEMA.COLUMNS)
SELECT column_name, data_type
FROM `gulong-chatbot-459723.gulong_core.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'orders_raw_deduped'
ORDER BY ordinal_position;
```
Ganito rin sa `gulong_core.orders_all` at `gulong_backend.orders_raw`.

**Finding:** Walang contact/email kahit saan sa BQ. Ang identity fields lang:
`customer_name`, `customer_name_key`, `many_chat_id` (FB/chatbot orders lang).

**Desisyon:** Sa BQ, `customer_name_key` (normalized name) lang ang universal
identifier. Name-based muna tayo, may caveat na name collision (pataas) at name
variation/typo (pababa).

---

## STEP 2 — I-verify ang datasets/tables at date coverage

**Command (BQ) — anong tables meron:**
```
SELECT 'gulong_backend' AS dataset, table_name, table_type
FROM `gulong-chatbot-459723.gulong_backend.INFORMATION_SCHEMA.TABLES`
UNION ALL
SELECT 'gulong_core' AS dataset, table_name, table_type
FROM `gulong-chatbot-459723.gulong_core.INFORMATION_SCHEMA.TABLES`
ORDER BY dataset, table_name;
```
**Finding:** Walang hiwalay na customers/contacts table. `gulong_backend` = orders_raw + price lang.

**Command (BQ) — coverage:**
```
SELECT MIN(order_day), MAX(order_day),
  COUNTIF(order_day >= DATE '2026-08-01' AND order_day < DATE '2026-09-01'
          AND is_reportable_booked_order) AS aug_booked
FROM `gulong-chatbot-459723.gulong_core.orders_all`;
```
**Finding:** 2024-01-01 → 2026-08-19; 302 reportable booked orders para sa August.

---

## STEP 3 — I-validate ang `customer_name_key` bilang identifier

**Command (BQ):**
```
SELECT COUNT(*) AS booked_rows,
  COUNTIF(customer_name_key IS NULL OR TRIM(customer_name_key)='') AS null_blank,
  COUNT(DISTINCT customer_name_key) AS distinct_keys
FROM `gulong-chatbot-459723.gulong_core.orders_all`
WHERE is_reportable_booked_order AND order_day >= DATE '2024-01-01';
```
**Finding:** 9,875 booked orders; 1 blank lang (0.01%); usable.

---

## STEP 4 — Name-based returning (reference number)

**Command (BQ):** tignan ang `returning_customers_queries.sql` (query #1).
**Finding:** 18 returning customers (6.06%). Ito ang ginamit sa unang CSV
(`august_2026_returning_customers.csv`).

**Cross-check:** Pinatakbo rin sa `gulong_core.orders_booked` (canonical view) —
eksaktong 18 din → confirmed reconciled ang scope.

---

## STEP 5 — Pivot: may email + contact pala sa raw Redash export

Nag-upload ka ng `New_Query_2026_08_20.csv` (`SELECT * FROM temp_orders`).

**Command (bash) — header + laki:**
```
head -c 2000 New_Query_2026_08_20.csv ; wc -l New_Query_2026_08_20.csv
```
**Finding:** May `email_address`, `client_contact_no`, `customer_client_id`.
26,335 rows — **eksaktong kapareho ng `orders_raw`** (same universe). Ibig sabihin,
existing ang email/contact sa raw source; na-drop lang sa BQ load.

**Command (python) — fill rates + status:**
```python
import pandas as pd
df = pd.read_csv('New_Query_2026_08_20.csv', dtype=str, keep_default_na=False)
for c in ['email_address','client_contact_no','customer_client_id','customer_name']:
    s=df[c].str.strip(); print(c, (s!='').mean())
```
**Finding:** contact 100%, customer_client_id 99.7%, email 99.2%.

---

## STEP 6 — Quality check: placeholder pollution

**Bakit:** Bago gamitin ang email/contact, kailangan tignan kung may shared/placeholder
values (maraming tao, iisang email/number).

**Command (python) — value → distinct names:**
```python
sub=df[df['email_address'].str.strip()!='']
g=sub.assign(e=sub['email_address'].str.lower()).groupby('e').agg(
    names=('customer_name','nunique'), orders=('id','count'))
print(g.sort_values('orders',ascending=False).head(10))
```
**Finding (placeholders):** `-@gmail.com` (265 names), `noemail@gmail.com` (158),
`no@email` (70), `hello@gulong.ph`, LICA staff emails, `00000000000` (contact, 833
orders). **Kailangang i-clean bago gamitin.**

---

## STEP 7 — Hybrid method (BQ scope + CSV identifiers)

**Bakit hybrid:** Ang "valid booked" logic ay nasa BQ; ang email/contact ay nasa
CSV. Kaya: **BQ → exact booked order IDs**, **CSV → email/contact per order_id**,
i-join by `order_id` sa Python. Ganito, eksaktong-reconciled sa canonical 302.

**Command (BQ) — prior booked IDs (isang string):**
```
SELECT COUNT(*), STRING_AGG(order_id, ',')
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE order_day < DATE '2026-08-01';
```
→ isinave sa `prior_booked_ids.txt` (9,573 IDs)

**Command (BQ) — August booked + net sales (isang string):**
```
SELECT COUNT(*), STRING_AGG(FORMAT('%s~%.2f', order_id, net_sales_amount), '|')
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE order_day >= DATE '2026-08-01' AND order_day < DATE '2026-09-01';
```
→ isinave sa `aug_booked.txt` (302 orders)

**Command (python):** buong logic nasa `returning_customers_analysis.py`.
Susi: (a) placeholder cleaning, (b) prior identifier sets, (c) classify bawat
August order per identifier + combined.

---

## STEP 8 — Idagdag ang channel journey (customer_type)

**Bakit:** Para makita ang scope ng bawat returning customer (first-ever →
last-prior → August channel).

**Command (python) — channel field check:**
```python
print(df['customer_type'].str.strip().value_counts().head(12))
```
**Finding:** `customer_type` ang pinakamalinis: Website, Fb, Chatbot, Marketplace,
B2B*, Affiliate, Walk-in. Ginawa kong `channel` label.

---

## STEP 9 — BUG na nahanap (mahalagang aral)

Nang idagdag ang channel journey, may lumabas na **prior_orders = 1015 / 932** sa
ilang customer — imposible sa retail.

**Debug (python):**
```python
# tingnan kung anong identifier ang nag-match ng ganun kadami
print(pe.get(email_k), pc.get(contact_k), pn.get(name_key))
```
**Ugat ng bug:** Ang missing identifiers ay ginawa kong `None`. Sa pandas, ang
`None` sa object column ay nagiging **`NaN`**, at ang `NaN` ay **truthy** — kaya
`if key:` ay pumasa, at lahat ng junk emails ay nagsama-sama sa iisang `NaN`
bucket (932 orders) na tumugma sa lahat → **inflated ang returning (32 = mali).**

**Fixes:**
1. Gamitin ang `''` (empty string) bilang sentinel para sa missing — falsy siya, hindi NaN.
2. Dagdag na cleaning: **order-volume threshold (≥20)** para maalis ang
   dealer/fleet/test accounts (parehong pangalan pero daan-daang orders — hal.
   HERTZ fleet, `frig test`, `00000000000`).
3. Ayusin ang per-identifier counts (dati mali — combined prior ang gamit).

**Verify:** matapos i-fix, `max prior-match = 7` (si Mikhail, lehit).

---

## STEP 10 — Tamang final results

| Identifier | Usable | Returning | Rate |
|---|---|---:|---:|
| Name lang | 302/302 | 18 | 6.1% |
| Email (clean) | 295/302 | 20 | 6.9% |
| Contact (clean) | 300/302 | 22 | 7.5% |
| **Combined** | 297 | **26** | **8.8%** |

- Name-only = **18** = eksaktong canonical BigQuery → reconciled.
- Combined = **26** (hindi 32; 32 = bug). Returning net sales = **₱651,362**.
- Email/contact nakahuli ng **8 orders** na na-miss ng name (name-variation cases).

**Channel journey (26 returning):**

| Channel path | Customers |
|---|---:|
| Website → Website → Website | 11 |
| FB → FB → Website | 7 |
| FB → FB → FB | 7 |
| Walk-in → Walk-in → FB | 1 |
| FB → FB → Chatbot | 1 |

---

## File inventory

| File | Ano ito |
|---|---|
| `RUNBOOK_returning_customers.md` | Itong dokumentong ito |
| `returning_customers_queries.sql` | Lahat ng BigQuery queries (schema check, name-based, prior IDs, August pull) |
| `returning_customers_analysis.py` | Buong Python analysis (v2, fixed + channel) |
| `august_2026_returning_customers.csv` | Unang output: 18 name-based returning |
| `august_2026_returning_customers_with_channel.csv` | Final: 26 returning + channel journey |
| `prior_booked_ids.txt` | (intermediate) 9,573 prior booked order IDs — galing SQL #2 |
| `aug_booked.txt` | (intermediate) 302 August booked `id~net_sales` — galing SQL #3 |

---

## Pano i-reproduce (end-to-end)

1. Sa BigQuery console, patakbuhin ang SQL #2 at #3 sa `returning_customers_queries.sql`.
   I-save ang output strings sa `prior_booked_ids.txt` at `aug_booked.txt`.
2. Ilagay sa iisang folder: ang dalawang `.txt`, ang `New_Query_2026_08_20.csv`
   (`SELECT * FROM temp_orders`), at ang `returning_customers_analysis.py`.
3. `pip install pandas` kung wala pa.
4. `python3 returning_customers_analysis.py`
   → ipi-print ang per-identifier + combined counts, at gagawa ng
   `august_2026_returning_customers_with_channel.csv`.

---

## Mga caveat na dapat malaman ng report reader

- **Partial month** — Aug 1–19 lang; aakyat pa ang bilang.
- **Name-based ay floor** — hindi nahuhuli ang typo/spelling variations (kaya
  mas mataas ang combined vs name-only).
- **Placeholder/shared cleaning ay judgment call** — ang ≥5 distinct-names at ≥20
  order-volume thresholds ay pwedeng i-tune. B2B/fleet/test accounts ay tinanggal.
- **One-time CSV pa ang pinagmulan ng email/contact** — hindi pa repeatable hangga't
  hindi nadadala ang mga column na 'to sa gold layer (BQ pipeline).
