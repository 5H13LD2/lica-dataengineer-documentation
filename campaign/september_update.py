"""Add September 1–8 actuals and an actuals-anchored forecast to the workbook."""
import csv

def add_september(ctx):
    globals().update({k:ctx[k] for k in ['BASE','w','sheet','val','fmt','wrap','head','sub','tot','number']})
    with (BASE/'sep .csv').open(encoding='utf-8-sig',newline='') as f:
        raw=list(csv.DictReader(f))
    mapping={'cost':'Cost','sessions':'Sessions','users':'Total users','carts':'Add to carts','checkouts':'Checkouts','purchases':'Purchase'}
    rows=[dict(campaign=r['Campaign'],**{k:number(r[v]) for k,v in mapping.items()}) for r in raw]
    t={k:sum(r[k] for r in rows) for k in mapping};a=tot['August']
    days=8;remaining=22;budget=t['cost']/days*30;cpa=t['cost']/t['purchases'];projection=t['purchases']/days*30
    s=sheet('September MTD',['Metric','September 1–8 actual','August full month','Sep daily / ratio','Aug daily / ratio','Comparable change'],[32,25,25,24,24,25])
    for i,(k,label) in enumerate([('cost','Spend'),('sessions','Sessions'),('users','Campaign users (sum)'),('carts','Add to carts'),('checkouts','Checkouts'),('purchases','Recorded purchases')],1):
        s.write(i,0,label)
        for c,v in enumerate([t[k],a[k],t[k]/days,a[k]/31,(t[k]/days)/(a[k]/31)-1],1):val(s,i,c,v,'pct' if c==5 else 'money' if k=='cost' else 'decimal' if c in (3,4) else 'num')
    ratios=[('Cost / purchase','cost','purchases','money'),('Cost / session','cost','sessions','money'),('Purchases / session','purchases','sessions','pct'),('Carts / session','carts','sessions','pct'),('Checkouts / carts','checkouts','carts','pct'),('Purchases / checkouts','purchases','checkouts','pct')]
    for i,(label,num,den,kind) in enumerate(ratios,8):
        sv=t[num]/t[den];av=a[num]/a[den];s.write(i,0,label)
        for c,v in [(1,sv),(2,av),(3,sv),(4,av)]:val(s,i,c,v,kind)
        val(s,i,5,sv-av if kind=='pct' else sv/av-1,'pct')
    s.merge_range('A16:F17','September covers September 1–8, 2026 inclusive (8 elapsed days), per user. Raw totals are shown for context; volume changes compare daily rates, not 8-day totals against full months. Ratio changes use percentage points; cost-ratio changes use relative percentages.',wrap)
    findings=[f"September recorded {t['purchases']:.0f} purchases on ₱{t['cost']:,.2f} spend; CPA is ₱{cpa:,.2f} ({cpa/a['cpa']-1:+.1%} vs August).",f"Purchases/day are {t['purchases']/8:.2f} vs {a['purchases']/31:.2f} in August ({(t['purchases']/8)/(a['purchases']/31)-1:+.1%}); spend/day is {(t['cost']/8)/(a['cost']/31)-1:+.1%} higher.",f"At unchanged daily pace, September would finish near {projection:.1f} purchases and ₱{budget:,.2f} spend. This extrapolates eight days and is not a confidence interval.","Michelin PMax supplies 23 of 50 purchases (46.0%) at ₱370.47 CPA. It remains the lowest observed CPA campaign, although its CPA is 54.7% above August.","SRC All Brands records 8 purchases at ₱534.96 CPA vs ₱1,520.02 recalculated for August; eight-day results are an early signal requiring more observation.","All Brand PMax and BFG Advantage Touring have CPAs of ₱1,724.51 and ₱2,413.11, respectively. Review their purchase quality and spend allocation alongside Michelin and SRC All Brands.","No August 1–8 data is available. Daily normalization does not control for weekday mix, conversion lag, promotion timing or within-month seasonality; statistical significance cannot be established from these aggregates."]
    for i,line in enumerate(findings,19):s.merge_range(i,0,i,5,line,wrap);s.set_row(i,43)
    s=sheet('September Campaigns',['Campaign','Sep 1–8 spend','Sessions','Campaign users','Carts','Checkouts','Purchases','Sep CPA','Aug CPA','CPA change','Sep purchases/day','Aug purchases/day','Daily purchase change','Spend share','Purchase share'],[43]+[21]*14)
    aug={r['campaign']:r for r in ctx['rows'] if r['month']=='August'}
    for i,r in enumerate(rows,1):
        p=aug[r['campaign']];sc=r['cost']/r['purchases'];ac=p['cost']/p['purchases']
        values=[r['campaign'],r['cost'],r['sessions'],r['users'],r['carts'],r['checkouts'],r['purchases'],sc,ac,sc/ac-1,r['purchases']/8,p['purchases']/31,(r['purchases']/8)/(p['purchases']/31)-1,r['cost']/t['cost'],r['purchases']/t['purchases']]
        for c,v in enumerate(values):val(s,i,c,v,'text' if c==0 else 'money' if c in (1,7,8) else 'pct' if c in (9,12,13,14) else 'decimal' if c in (10,11) else 'num')
    s.autofilter(0,0,6,14)
    s=sheet('September Source',list(raw[0]),[43]+[23]*7)
    for i,r in enumerate(raw,1):s.write_row(i,0,list(r.values()))
    s=sheet('September Forecast',['Input / scenario','Value / full spend','Future CPA','Remaining purchases','Full-month purchases','Explanation'],[39,25,24,25,26,80])
    inputs=[('Elapsed days',8,'num'),('Days in September',30,'num'),('Actual MTD spend',t['cost'],'money'),('Actual MTD purchases',t['purchases'],'num')]
    for i,(label,v,kind) in enumerate(inputs,1):s.write(i,0,label);val(s,i,1,v,kind)
    for i,label,formula,value,kind in [(5,'MTD CPA','=B4/B5',cpa,'money'),(6,'Planned full-month spend','=B4/B2*B3',budget,'money'),(7,'Remaining spend','=MAX(0,B7-B4)',budget-t['cost'],'money'),(8,'August actual CPA',None,a['cpa'],'money'),(9,'Assumed CPA sensitivity',None,.20,'pct')]:
        s.write(i,0,label)
        if formula:s.write_formula(i,1,formula,fmt[kind],value)
        else:val(s,i,1,value,kind)
    s.merge_range('C2:F4','Actuals are September 1–8. B7 defaults to the observed daily spending pace for 30 days; replace it with a planned total budget. Remaining-month estimates are added to the 50 purchases already recorded. B10 sets the ±CPA sensitivity assumption.',wrap)
    s.merge_range('C7:F8','If planned total spend is below actual spend, remaining spend is floored at zero; sunk spend cannot be reversed. Forecast purchase counts are expected values, not guaranteed integer outcomes.',wrap)
    scenarios=[('Downside: MTD CPA +20%',cpa*1.2,'=$B$6*(1+$B$10)','Assumed deterioration in remaining-month efficiency.'),('Base: maintain MTD CPA',cpa,'=$B$6','Maintains observed September efficiency for the remaining 22 days.'),('Upside: MTD CPA −20%',cpa*.8,'=$B$6*(1-$B$10)','Assumed improvement; not a statistical upper bound.'),('Reference: August CPA',a['cpa'],'=$B$9','Remaining spend converts at August blended efficiency.')]
    for i,(label,cp,formula,explain) in enumerate(scenarios,12):
        s.write(i,0,label);s.write_formula(i,1,'=$B$7',fmt['money'],budget);s.write_formula(i,2,formula,fmt['money'],cp)
        estimate=(budget-t['cost'])/cp
        s.write_formula(i,3,f'=IFERROR($B$8/C{i+1},"N/A")',fmt['decimal'],estimate)
        s.write_formula(i,4,f'=IFERROR($B$5+D{i+1},"N/A")',fmt['decimal'],t['purchases']+estimate);s.write(i,5,explain,wrap);s.set_row(i,42)
    s.merge_range('A19:F20','Method: actual MTD purchases + remaining planned spend / assumed future CPA. Eight days provide no daily variance estimate or dependable seasonal pattern. Scenarios are assumption-driven, not calibrated prediction intervals. Conversion lag and campaign mix changes can alter the result.',wrap)
    s.write_row(22,0,['Remaining-spend sensitivity','Future CPA +20%','Future MTD CPA','Future CPA −20%'],head)
    for i,factor in enumerate([.8,1,1.2],23):
        s.write_formula(i,0,f'=$B$8*{factor}',fmt['money'],(budget-t['cost'])*factor)
        for c,cf in enumerate([1.2,1,.8],1):s.write_formula(i,c,f'=IFERROR($B$5+A{i+1}/($B$6*{cf}),"N/A")',fmt['decimal'],t['purchases']+(budget-t['cost'])*factor/(cpa*cf))
    s.merge_range('A28:F29','Sensitivity cells report full-month purchases including actuals. The Prior Sep Forecast tab retains the original pre-September scenarios for comparison; this tab supersedes those estimates using observed September activity.',wrap)
    chart=w.add_chart({'type':'bar'});chart.add_series({'categories':['September Forecast',12,0,15,0],'values':['September Forecast',12,4,15,4],'fill':{'color':'#007F86'},'data_labels':{'value':True,'num_format':'0'}});chart.set_title({'name':'September full-month purchases | as of Sep 8'});chart.set_legend({'none':True});chart.set_size({'width':930,'height':330});s.insert_chart('A32',chart)
    ctx['d'].merge_range('B74:N76',f"SEPTEMBER 1–8 UPDATE: {t['purchases']:.0f} purchases | ₱{t['cost']:,.2f} spend | ₱{cpa:,.2f} CPA. Current pace implies {projection:.1f} full-month purchases. See September MTD and September Forecast; June–August cards above remain completed-month results.",wrap)
    ctx['d'].print_area(0,0,76,14)
    s=w.get_worksheet_by_name('Methodology');n=len(ctx['notes'])+1;s.write(n,0,n);s.write(n,1,'September source: sep .csv; September 1–8 inclusive per user, not verified from daily dates. September in the combined CSV is not used as actuals. New forecast anchors on MTD actuals; prior forecast retained separately.',wrap);s.set_row(n,55)
    s=w.get_worksheet_by_name('Data Quality');s.write_row(14,0,['September 1–8','Source completeness','PARTIAL MONTH','6 campaign rows. 8 elapsed days per user; no daily data or independent September total supplied.'],wrap);s.set_row(14,40)
    ctx['september_text']='\n\n## September 1–8 update\n\n'+'\n\n'.join(findings)+'\n\nUpdated full-month forecast uses actual MTD purchases plus remaining spend divided by assumed CPA. Prior September scenarios are retained separately in Excel.\n'
    assert len(rows)==6 and t['purchases']==50
    print('September totals:',t,'Projected purchases:',projection)
