"""
Returning Customers - August 2026 (Aug 1-19, partial)  [v2: fixed + channel]
============================================================================
Kino-compare ang returning-customer detection gamit NAME, EMAIL, CONTACT NO.,
tapos tine-trace ang channel journey (first-ever -> last-prior -> August)
per returning customer, sa eksaktong parehong canonical booked scope (BigQuery).

Bakit hybrid (BQ + CSV)?
- Ang "valid/reportable booked" logic ay nasa BigQuery (orders_booked view).
- Ang email + contact + customer_type(channel) ay nasa raw Redash temp_orders CSV lang.
  BQ  -> exact booked order IDs (prior + August); CSV -> email/contact/channel per id.
  Naka-join by order_id dito sa Python.

MAHALAGANG FIXES vs v1:
1. Missing identifiers -> '' (empty string), HINDI None. Dahil kapag None sa
   object column, nagiging NaN ang pandas, at ang NaN ay "truthy" -- nagsama-sama
   ang lahat ng junk sa iisang NaN bucket at nag-inflate ng returning (32 -> mali).
2. Placeholder/shared-account cleaning: distinct-names threshold (>=5) AT
   order-volume threshold (>=20). Nito naaalis ang B2B/fleet/test na laging pareho
   ang pangalan pero daan-daang orders (hal. HERTZ fleet, 'frig test', 00000000000).
3. Per-identifier counts ay independent na (dati mali -- combined prior ang gamit).

Inputs (nasa parehong folder):
  - New_Query_2026_08_20.csv   (raw temp_orders; email + contact + customer_type)
  - prior_booked_ids.txt        (SQL #2 output; comma-separated order IDs)
  - aug_booked.txt              (SQL #3 output; "id~net_sales|...")

Requires: pandas
"""

import pandas as pd, re
from collections import defaultdict

CSV_PATH, PRIOR_PATH, AUG_PATH = 'New_Query_2026_08_20.csv', 'prior_booked_ids.txt', 'aug_booked.txt'

# ------------------------------------------------------------------
# 1) Load + normalize
# ------------------------------------------------------------------
df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
df['id']        = df['id'].str.strip()
df['email_l']   = df['email_address'].str.strip().str.lower()
df['name']      = df['customer_name'].str.strip()
df['name_key']  = df['name'].str.lower().str.replace(r'\s+', ' ', regex=True).str.strip()
df['order_day'] = pd.to_datetime(df['order_date'], format='%m/%d/%y %H:%M', errors='coerce').dt.date

def norm_contact(x):
    d = re.sub(r'\D', '', x or '')
    if d.startswith('63') and len(d) >= 12: d = '0' + d[2:]
    return d
df['contact_n'] = df['client_contact_no'].str.strip().apply(norm_contact)

# channel label mula customer_type
def channel(ct):
    ct = (ct or '').strip().lower()
    if ct == 'website': return 'Website'
    if ct == 'fb':      return 'FB'
    if ct == 'chatbot': return 'Chatbot'
    if 'marketplace' in ct: return 'Marketplace'
    if ct.startswith('b2b'): return 'B2B'
    if 'affil' in ct:   return 'Affiliate'
    if 'walk' in ct:    return 'Walk-in'
    return 'Other' if ct else 'Unknown'
df['channel'] = df['customer_type'].apply(channel)

# ------------------------------------------------------------------
# 2) Placeholder / shared-account cleaning (2 thresholds)
# ------------------------------------------------------------------
def shared_by_names(col, t=5):   # iisang value, maraming ibang pangalan
    g = df[df[col] != ''].groupby(col)['name'].nunique(); return set(g[g >= t].index)
def shared_by_volume(col, t=20): # dealer/fleet/test: parehong pangalan pero sobrang dami
    g = df[df[col] != ''].groupby(col)['id'].count();    return set(g[g >= t].index)

junk_e = shared_by_names('email_l') | shared_by_volume('email_l') | \
         {'', '-@gmail.com', 'no@email', 'noemail@gmail.com', 'none@gmail.com', 'test@gmail.com'}
for e in df['email_l'].unique():
    if e and (re.fullmatch(r'-+@.*', e) or 'noemail' in e or 'test' in e): junk_e.add(e)

junk_c = shared_by_names('contact_n') | shared_by_volume('contact_n')
for c in df['contact_n'].unique():
    if c == '' or len(set(c)) <= 1 or len(c) < 7: junk_c.add(c)   # all-same-digit / maikli

junk_n = shared_by_volume('name_key', 20)   # test/fleet names

# CLEAN keys -> '' kapag junk (HINDI None, para iwas NaN bug)
df['email_k']   = df['email_l'].map(  lambda e: '' if (e == '' or e in junk_e) else e)
df['contact_k'] = df['contact_n'].map(lambda c: '' if (c == '' or c in junk_c) else c)
df['name_k']    = df['name_key'].map( lambda n: '' if (n == '' or n in junk_n) else n)

rec = df.set_index('id')[['order_day', 'channel', 'email_k', 'contact_k', 'name_k', 'name']].to_dict('index')

# ------------------------------------------------------------------
# 3) Canonical booked id sets (BigQuery) + index prior orders per identifier
# ------------------------------------------------------------------
prior_ids = set(open(PRIOR_PATH).read().strip().split(','))
aug = [(t.split('~')[0].strip(), float(t.split('~')[1])) for t in open(AUG_PATH).read().strip().split('|')]
aug_ids, aug_ns = [a[0] for a in aug], dict(aug)

pe, pc, pn = defaultdict(list), defaultdict(list), defaultdict(list)
for oid in prior_ids:
    r = rec.get(oid)
    if not r: continue
    if r['email_k']:   pe[r['email_k']].append(oid)
    if r['contact_k']: pc[r['contact_k']].append(oid)
    if r['name_k']:    pn[r['name_k']].append(oid)

# ------------------------------------------------------------------
# 4) Classify bawat August order (independent per identifier + combined)
# ------------------------------------------------------------------
rows = []
for oid in aug_ids:
    r = rec[oid]
    re_ = bool(r['email_k']   and pe.get(r['email_k']))
    rc_ = bool(r['contact_k'] and pc.get(r['contact_k']))
    rn_ = bool(r['name_k']    and pn.get(r['name_k']))
    # prior matches (union) para sa journey
    pm = {}
    for key, idx in [(r['email_k'], pe), (r['contact_k'], pc), (r['name_k'], pn)]:
        if key:
            for poid in idx.get(key, []):
                pm[poid] = (rec[poid]['order_day'], rec[poid]['channel'])
    rows.append(dict(oid=oid, ns=aug_ns[oid], name=r['name'], email=r['email_k'],
                     contact=r['contact_k'], name_k=r['name_k'], channel=r['channel'],
                     order_day=r['order_day'], re_=re_, rc_=rc_, rn_=rn_,
                     ret=(re_ or rc_ or rn_), prior=pm))
A = pd.DataFrame(rows)

# ------------------------------------------------------------------
# 5) Per-identifier + combined summary
# ------------------------------------------------------------------
def one(field, retcol, label):
    sub = A[A[field] != '']
    cust = sub.groupby(field)[retcol].max()
    print(f"{label:9s} usable {len(sub):>3}/302 | customers {len(cust):>3} | "
          f"returning {int(cust.sum()):>2} ({100*cust.mean():.1f}%)")
one('email', 're_', 'EMAIL'); one('contact', 'rc_', 'CONTACT'); one('name_k', 'rn_', 'NAME')

A['ckey'] = A.apply(lambda r: r['contact'] or r['email'] or r['name_k'] or r['name'], axis=1)
cust = A.groupby('ckey')['ret'].max()
print(f"\nCOMBINED   customers {len(cust)} | returning {int(cust.sum())} ({100*cust.mean():.1f}%)")
print(f"returning net sales P{A[A['ret']]['ns'].sum():,.2f} / total P{A['ns'].sum():,.2f}")
print(f"caught by email/contact na na-miss ng NAME: {A[(~A['rn_'])&(A['re_']|A['rc_'])]['oid'].nunique()} orders")

# ------------------------------------------------------------------
# 6) Channel journey (first-ever -> last-prior -> August) para sa returning
# ------------------------------------------------------------------
out = []
for _, r in A[A['ret']].iterrows():
    pm = r['prior']
    allev = list(pm.values()) + [(r['order_day'], r['channel'])]
    fd, fc = min(allev, key=lambda x: x[0])
    lpd, lpc = max(pm.values(), key=lambda x: x[0])
    out.append(dict(customer=r['name'], contact=r['contact'], email=r['email'],
                    prior_orders=len(pm),
                    first_ever_date=fd, first_ever_channel=fc,
                    last_prior_date=lpd, last_prior_channel=lpc,
                    august_date=r['order_day'], august_channel=r['channel'],
                    channel_path=f"{fc} \u2192 {lpc} \u2192 {r['channel']}",
                    august_net_sales=round(r['ns'], 2)))
J = (pd.DataFrame(out).drop_duplicates(['customer', 'august_date'])
       .sort_values(['prior_orders', 'last_prior_date'], ascending=[False, True]))
print("\nChannel path distribution:\n" + J['channel_path'].value_counts().to_string())
J.to_csv('august_2026_returning_customers_with_channel.csv', index=False)
print(f"\nsaved journey rows: {len(J)}")
