import csv,json
from pathlib import Path
from decimal import Decimal
B=Path(__file__).resolve().parent
sources={'Google Ads':'revenue_match','Direct & Organic':'direct_and_organic_revenue','Referral':'referral_revenue'}
rows=[];exceptions=[]
for channel,folder in sources.items():
    for r in csv.DictReader((B.parent/folder/'decoded_orders_with_revenue.csv').open(encoding='utf-8-sig')):
        r={'source_channel':channel,**r}
        date=r['order_date'][:10]
        if not date: r['exclusion_reason']='Unmatched order; date and revenue unknown';exceptions.append(r);continue
        if not '2026-09-01'<=date<='2026-09-24':r['exclusion_reason']='Outside September 1–24';exceptions.append(r);continue
        r['week']=(int(date[-2:])-1)//7+1
        rows.append(r)
assert len({r['decoded_order_id'] for r in rows})==len(rows)
def write(name,rs):
    fields=list(dict.fromkeys(k for r in rs for k in r))
    with (B/name).open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rs)
summary=[]
for week in range(1,5):
    for channel in sources:
        rs=[r for r in rows if r['week']==week and r['source_channel']==channel]
        summary.append({'week':week,'date_start':f'2026-09-{1+(week-1)*7:02}','date_end':f'2026-09-{min(week*7,24):02}','source_channel':channel,'matched_orders':len(rs),'fulfilled_orders':sum(r['is_fulfillment_success_order']=='true' and r['is_excluded_test_order']=='false' for r in rs),'all_order_net_sales':str(sum((Decimal(r['net_sales_amount']) for r in rs),Decimal(0))),'fulfilled_net_revenue':str(sum((Decimal(r['fulfilled_net_revenue']) for r in rs),Decimal(0)))})
write('weekly_channel_revenue.csv',summary);write('weekly_order_detail.csv',rows);write('excluded_orders.csv',exceptions)
lines=['# Weekly net sales by source channel','','Backend order dates; September 2026. Week 1: 1–7; Week 2: 8–14; Week 3: 15–21; partial Week 4: 22–24. Source channels represent the three supplied CSVs; Direct and Organic are combined. Google Ads is the first CSV label, including its cross-network row. Results use the previously retrieved backend snapshot, not a fresh query.','','Net sales use the existing reporting calculation ROUND(total_amount_due / 1.12, 2). All-order values include cancelled, unfinished, return and refund orders. Fulfilled revenue requires fulfilled/partially fulfilled status and fully paid/partial payment status, excluding test orders. Full order value is included for partial payments; this is not cash collected. Each order is counted once. There are no overlapping IDs across the three input files.','']
for metric in ['all_order_net_sales','fulfilled_net_revenue']:
    lines += [f'## {metric}','','| Week | Google Ads | Direct & Organic | Referral | Total |','|---|---:|---:|---:|---:|']
    totals=[Decimal(0)]*3
    for week in range(1,5):
        values=[Decimal(next(r[metric] for r in summary if r['week']==week and r['source_channel']==ch)) for ch in sources]
        totals=[a+b for a,b in zip(totals,values)]
        lines.append('| '+str(week)+' | '+' | '.join(f'₱{v:,.2f}' for v in values+[sum(values)])+' |')
    lines+=['| Total | '+' | '.join(f'₱{v:,.2f}' for v in totals+[sum(totals)])+' |','']
lines += ['Excluded from September totals: Google Ads order 38959 (August 31), ₱27,053.57; Direct & Organic order 38805 (August 26), ₱54,174.11. Both are fulfilled. Three unmatched Direct & Organic IDs (39900, 39109, 39052) have unknown dates and revenue. See excluded_orders.csv.']
(B/'report.md').write_text('\n'.join(lines)+'\n')
# Reconcile every input amount against included and excluded known amounts.
for channel,folder in sources.items():
    original=json.loads((B.parent/folder/'summary.json').read_text())
    for metric,old in [('net_sales_amount','net_sales_all_orders'),('fulfilled_net_revenue','fulfilled_net_revenue')]:
        total=sum((Decimal(r[metric] or '0') for r in rows+exceptions if r['source_channel']==channel),Decimal(0))
        assert total==Decimal(original[old]),(channel,metric)
print('\n'.join(lines))
