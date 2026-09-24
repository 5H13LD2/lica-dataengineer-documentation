import base64,csv,json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from decimal import Decimal
from collections import defaultdict
B=Path(__file__).resolve().parent
rows=list(csv.DictReader((B.parent/'referral.csv').open(encoding='utf-8-sig')))
backend=json.loads((B/'backend_orders.json').read_text())
orders={x['order_id']:x for x in backend}
assert len(orders)==len(backend)
out=[]
for r in rows:
    oid=base64.b64decode(parse_qs(urlsplit(r['Page path + query string']).query)['requestid'][0],validate=True).decode()
    o=orders.get(oid,{k:None for k in backend[0]})
    good=o.get('is_fulfillment_success_order')=='true' and o.get('is_excluded_test_order')=='false'
    out.append({**r,'decoded_order_id':oid,'match_status':'Matched' if oid in orders else 'Unmatched',**{k:v for k,v in o.items() if k!='order_id'},'fulfilled_net_revenue':o.get('net_sales_amount') if good else ('0.00' if oid in orders else None)})
assert len(set(x['decoded_order_id'] for x in out))==len(out)
assert all(x.get('net_sales_amount') is not None for x in out if x['match_status']=='Matched')
def write(name,rs):
    with (B/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
write('decoded_orders_with_revenue.csv',out)
def summarize(key):
    groups=defaultdict(list)
    for r in out:groups[r[key] or 'Unmatched'].append(r)
    result=[]
    for k,rs in groups.items():
        result.append({key:k,'unique_orders':len(rs),'matched_orders':sum(r['match_status']=='Matched' for r in rs),'purchase_events':sum(int(r['Ecommerce purchases']) for r in rs),'net_sales_all_orders':str(sum(Decimal(r['net_sales_amount'] or '0') for r in rs)),'fulfilled_orders':sum(r['is_fulfillment_success_order']=='true' and r['is_excluded_test_order']=='false' for r in rs),'fulfilled_net_revenue':str(sum(Decimal(r['fulfilled_net_revenue'] or '0') for r in rs))})
    return sorted(result,key=lambda x:Decimal(x['fulfilled_net_revenue']),reverse=True)
campaign=summarize('Session campaign');status=summarize('order_status_raw')
write('revenue_by_campaign.csv',campaign);write('revenue_by_status.csv',status)
summary={'unmatched_order_ids':[r['decoded_order_id'] for r in out if r['match_status']=='Unmatched'],'matched_orders':len(orders),'purchase_events':sum(int(r['Ecommerce purchases']) for r in out),'net_sales_all_orders':str(sum(Decimal(r['net_sales_amount'] or '0') for r in out)),'fulfilled_net_revenue':str(sum(Decimal(r['fulfilled_net_revenue'] or '0') for r in out)),'gross_sales_all_orders':str(sum(Decimal(r['gross_sales_amount'] or '0') for r in out)),'order_date_min':min(r['order_date'] for r in out if r['order_date']),'order_date_max':max(r['order_date'] for r in out if r['order_date']),'campaigns':campaign,'statuses':status}
(B/'summary.json').write_text(json.dumps(summary,indent=2))
(B/'README.md').write_text('''# Revenue match\n\nSource: referral.csv. URL-decode requestid, then Base64-decode to backend order ID. 28 of 28 unique IDs matched; unmatched orders have unknown revenue and are excluded from totals. 39 ecommerce purchase events are not revenue multipliers.\n\nSource table: gulong-chatbot-459723.gulong_backend.orders_raw, accessed through gulong_core.orders_raw_deduped. The requested gulong_backend.raw table does not exist. The view chooses the latest row per order and defines net_sales_amount as ROUND(total_amount_due / 1.12, 2). This is the existing reporting model's VAT-exclusive order value, not a cash-receipts amount.\n\nAll-order net sales include cancelled, unpaid, pending and return orders. Fulfilled net revenue uses the view's is_fulfillment_success_order flag (fulfilled/partially fulfilled and fully paid/partial payment) and excludes test orders. Partial payments use full order value; actual cash collected is unavailable in this extract. Campaigns come from the supplied CSV. Order dates are backend dates and may differ from analytics dates. Latest raw ingestion: 2026-09-25 02:00:22.\n\nFiles: decoded_orders_with_revenue.csv (row-level match), revenue_by_campaign.csv, revenue_by_status.csv, summary.json, backend_orders.json (query result), match_orders.sql, build_report.py.\n''')
print(json.dumps(summary,indent=2))
