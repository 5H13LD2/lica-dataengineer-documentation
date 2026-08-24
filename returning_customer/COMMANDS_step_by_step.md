# Command Playbook — Returning Customers (August 2026)

Puro command, sunod-sunod. Kopyahin-patakbo. Project: `gulong-chatbot-459723`.

Legend: **[BQ]** = BigQuery console/MCP · **[SH]** = bash/terminal · **[PY]** = python3

---

## 1. [BQ] Tingnan kung may email/contact sa order data (wala — name lang)
```sql
SELECT column_name, data_type
FROM `gulong-chatbot-459723.gulong_core.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'orders_raw_deduped'
ORDER BY ordinal_position;
```
Expected: `customer_name`, `customer_name_key`, `many_chat_id` lang — walang email/phone.

---

## 2. [BQ] Listahan ng tables (walang hiwalay na customers table)
```sql
SELECT 'gulong_backend' AS dataset, table_name, table_type
FROM `gulong-chatbot-459723.gulong_backend.INFORMATION_SCHEMA.TABLES`
UNION ALL
SELECT 'gulong_core' AS dataset, table_name, table_type
FROM `gulong-chatbot-459723.gulong_core.INFORMATION_SCHEMA.TABLES`
ORDER BY dataset, table_name;
```

---

## 3. [BQ] Coverage + bilang ng August booked
```sql
SELECT MIN(order_day) AS first_day, MAX(order_day) AS latest_day,
  COUNTIF(order_day >= DATE '2026-08-01' AND order_day < DATE '2026-09-01'
          AND is_reportable_booked_order) AS aug_booked
FROM `gulong-chatbot-459723.gulong_core.orders_all`;
```
Expected: 2024-01-01 → 2026-08-19, `aug_booked = 302`.

---

## 4. [BQ] I-validate ang customer_name_key
```sql
SELECT COUNT(*) AS booked_rows,
  COUNTIF(customer_name_key IS NULL OR TRIM(customer_name_key)='') AS null_blank,
  COUNT(DISTINCT customer_name_key) AS distinct_keys
FROM `gulong-chatbot-459723.gulong_core.orders_all`
WHERE is_reportable_booked_order AND order_day >= DATE '2024-01-01';
```
Expected: 9,875 rows, 1 blank lang.

---

## 5. [BQ] Name-based returning (reference = 18)
```sql
WITH booked AS (
  SELECT order_id, order_day, customer_name_key, net_sales_amount
  FROM `gulong-chatbot-459723.gulong_core.orders_booked`
  WHERE customer_name_key IS NOT NULL AND TRIM(customer_name_key) != ''
),
prior AS (SELECT DISTINCT customer_name_key FROM booked WHERE order_day < DATE '2026-08-01'),
aug AS (SELECT * FROM booked WHERE order_day >= DATE '2026-08-01' AND order_day < DATE '2026-09-01'),
cls AS (SELECT a.*, (p.customer_name_key IS NOT NULL) AS is_ret
        FROM aug a LEFT JOIN prior p USING (customer_name_key)),
cust AS (SELECT customer_name_key, MAX(is_ret) AS is_ret FROM cls GROUP BY customer_name_key)
SELECT (SELECT COUNT(*) FROM cust) AS total,
       (SELECT COUNTIF(is_ret) FROM cust) AS returning,
       ROUND((SELECT SUM(net_sales_amount) FROM cls WHERE is_ret),2) AS returning_net_sales;
```
Expected: total 297, returning 18.

---

## 6. [SH] Inspect ang uploaded CSV (temp_orders)
```bash
head -c 2000 New_Query_2026_08_20.csv ; echo ; wc -l New_Query_2026_08_20.csv
```
Expected: may `email_address`, `client_contact_no`, `customer_client_id`; 26,335 rows.

---

## 7. [PY] Fill rates ng email/contact
```python
import pandas as pd
df = pd.read_csv('New_Query_2026_08_20.csv', dtype=str, keep_default_na=False)
for c in ['email_address','client_contact_no','customer_client_id','customer_name']:
    s = df[c].str.strip()
    print(f"{c:20s} {100*(s!='').mean():.1f}%")
```
Expected: contact 100%, customer_client_id 99.7%, email 99.2%.

---

## 8. [PY] Placeholder check (email at contact)
```python
sub = df[df['email_address'].str.strip()!='']
g = sub.assign(e=sub['email_address'].str.lower()).groupby('e').agg(
        names=('customer_name','nunique'), orders=('id','count'))
print("EMAIL placeholders:\n", g.sort_values('orders',ascending=False).head(10), "\n")

import re
c = df['client_contact_no'].str.replace(r'\D','',regex=True)
gc = df.assign(c=c).query("c!=''").groupby('c').agg(
        names=('customer_name','nunique'), orders=('id','count'))
print("CONTACT placeholders:\n", gc.sort_values('orders',ascending=False).head(10))
```
Expected: makikita ang `-@gmail.com`, `noemail@gmail.com`, `00000000000`, atbp. → dapat i-clean.

---

## 9. [BQ] Prior (pre-August) booked order IDs → isang string
```sql
SELECT COUNT(*), STRING_AGG(order_id, ',')
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE order_day < DATE '2026-08-01';
```
I-save ang string sa **`prior_booked_ids.txt`** (9,573 IDs).

---

## 10. [BQ] August booked + net sales → isang string
```sql
SELECT COUNT(*), STRING_AGG(FORMAT('%s~%.2f', order_id, net_sales_amount), '|')
FROM `gulong-chatbot-459723.gulong_core.orders_booked`
WHERE order_day >= DATE '2026-08-01' AND order_day < DATE '2026-09-01';
```
I-save ang string sa **`aug_booked.txt`** (302 orders).

---

## 11. [SH] Ihanda ang folder
```bash
# dapat magkasama sa iisang folder:
#   New_Query_2026_08_20.csv
#   prior_booked_ids.txt
#   aug_booked.txt
#   returning_customers_analysis.py
ls -1
pip install pandas --quiet   # kung wala pa
```

---

## 12. [SH] Patakbuhin ang analysis
```bash
python3 returning_customers_analysis.py
```
Expected output:
```
EMAIL     usable 295/302 | customers 291 | returning 20 (6.9%)
CONTACT   usable 300/302 | customers 295 | returning 22 (7.5%)
NAME      usable 302/302 | customers 297 | returning 18 (6.1%)
COMBINED  customers 297 | returning 26 (8.8%)
returning net sales P651,362.11 / total P6,571,915.11
```
Gagawa rin ng **`august_2026_returning_customers_with_channel.csv`** (channel journey).

---

## Debug snippet (kung magkaka-inflated na bilang ulit)
```python
# tignan kung anong identifier ang nag-match ng sobrang daming prior orders
# (dapat maliit lang; kung 900+, may junk/shared identifier na nakalusot)
print("max prior-match:", A['prior'].map(len).max())
```
Kung malaki: (1) siguraduhing `''` ang sentinel ng missing (HINDI `None` → NaN bug),
at (2) dagdagan ang volume threshold sa `shared_by_volume()`.
