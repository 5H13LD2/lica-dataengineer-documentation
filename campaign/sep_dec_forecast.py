"""September–December budget and sales-target planning; August efficiency baseline."""
def add(ctx):
    globals().update({k:ctx[k] for k in ['w','page','title','subtitle','header','section','caution','wrap','style','money','pct','num','decimal']})
    blue=w.add_format({'bg_color':'#FFF2CC','font_color':'#0000FF','num_format':pct})
    inp=w.add_format({'bg_color':'#FFF2CC','font_color':'#0000FF','num_format':money})
    s=page('Sep Dec Forecast',9);s.set_column(0,0,43);s.set_column(1,4,24);s.set_column(5,8,18)
    s.merge_range('A1:I1','September–December 2026 — Budget & Sales Plan',title);s.set_row(0,34)
    s.merge_range('A2:I2','August actual efficiency baseline • September daily budget schedule • monthly sales targets rising ₱1M to ₱14M in December',subtitle);s.set_row(1,32)
    s.merge_range('A3:I3','PLANNING ESTIMATE: sales use August purchases × supplied Average Net Sales, assuming that field is per purchase. Branding sales are missing. October–December growth rates are editable and temporarily use 0% until supplied.',caution);s.set_row(2,44)
    s.write_row(4,0,['Baseline / assumption','Value','Meaning'],header)
    inputs=[('August actual ad spend',119119.2,money,'Sum of August campaign costs.'),('August recorded purchases',188,num,'Reported purchase events; not verified fulfilled orders.'),('August cost per purchase',119119.2/188,money,'August actual spend / recorded purchases.'),('August estimated sales — source proxy',3244492.26,money,'Purchases × Average Net Sales for 5 campaigns; missing Branding excluded. Replace with verified comparable sales when available.'),('December monthly sales goal',14000000,money,'User goal; monthly sales, not cumulative.'),('Monthly sales-goal increase',1000000,money,'September 11M; October 12M; November 13M; December 14M.')]
    for r,(label,value,code,note) in enumerate(inputs,5):
        s.write(r,0,label,style());s.write_blank(r,1,None,inp) if value is None else s.write(r,1,value,style(code));s.merge_range(r,2,r,8,note,wrap);s.set_row(r,29)
    s.write_formula('B9',"='August Sales Basis'!E12",inp,3244492.26)
    s.write_row(12,0,['Plan metric','September','October','November','December'],header)
    labels={13:'Days in month',14:'Budget increase vs prior month',15:'Planned monthly ad spend',16:'Average daily ad budget',17:'August CPA baseline',18:'Projected purchases — August CPA',19:'Monthly sales goal',20:'Estimated August sales / ad spend',21:'Estimated sales — August proxy',22:'Sales gap to goal',23:'Required sales / planned ad spend',24:'Spend needed at August sales efficiency',25:'Budget gap to target-implied spend'}
    for r,label in labels.items():s.write(r,0,label,style())
    spend=123000
    for c,(month,days) in enumerate([('September',30),('October',31),('November',30),('December',31)],1):
        col=chr(65+c);prev=chr(64+c);goal=11000000+(c-1)*1000000
        s.write(13,c,days,style(num))
        if c==1:s.write_formula(14,c,'=B16/$B$6-1',style(pct),spend/119119.2-1)
        else:s.write_blank(14,c,None,blue)
        formula="='Daily Budget Schedule'!G11" if c==1 else f'={prev}16*(1+IF(ISNUMBER({col}15),{col}15,0))'
        s.write_formula(15,c,formula,style(money),spend)
        s.write_formula(16,c,f'={col}16/{col}14',style(money),spend/days)
        s.write_formula(17,c,'=$B$8',style(money),119119.2/188)
        s.write_formula(18,c,f'={col}16/{col}18',style(decimal),spend/(119119.2/188))
        s.write_formula(19,c,f'=$B$10-(4-{c})*$B$11',style(money),goal)
        s.write_formula(20,c,'=IF(AND(ISNUMBER($B$9),$B$9>0),$B$9/$B$6,"Pending sales input")',style(decimal),3244492.26/119119.2)
        for r,form in [(21,f'=IF(ISNUMBER({col}21),{col}16*{col}21,"Pending sales input")'),(22,f'=IF(ISNUMBER({col}22),{col}20-{col}22,"Pending sales input")'),(24,f'=IF(ISNUMBER({col}21),{col}20/{col}21,"Pending sales input")'),(25,f'=IF(ISNUMBER({col}25),{col}25-{col}16,"Pending sales input")')]:s.write_formula(r,c,form,style(money),{21:spend*3244492.26/119119.2,22:goal-spend*3244492.26/119119.2,24:goal/(3244492.26/119119.2),25:goal/(3244492.26/119119.2)-spend}[r])
        s.write_formula(23,c,f'={col}20/{col}16',style(decimal),goal/spend)
    s.data_validation('C15:E15',{'validate':'decimal','criteria':'>=','value':-1,'input_title':'Monthly total budget increase','input_message':'Enter e.g. 10% for +10% over the previous monthly budget.'})
    s.data_validation('B9',{'validate':'decimal','criteria':'>','value':0})
    s.merge_range('A28:I29','Growth applies to TOTAL MONTHLY budget. Daily budget = monthly budget / calendar days, so a 0% monthly increase gives different daily budgets in 30- and 31-day months. No growth rates have been supplied; 0% is a temporary calculation fallback, not an approved budget.',caution)
    s.merge_range('A31:I32','Sales model: estimated August sales / August spend × planned spend; purchase counts × Average Net Sales are a proxy, not verified revenue. Use only comparable Google Ads-attributed sales. If the ₱11M–₱14M goals are company-wide, this ratio is not ROAS and cannot establish the Google Ads budget required to achieve company sales; channel allocation is needed.',wrap)
    s.merge_range('A34:I35','Model limits: a constant August CPA / sales efficiency assumes unchanged conversion quality, campaign mix and scale effects. These are scenario projections, not a statistical trend fit or confidence interval. Sales targets are goals, not forecast results.',wrap)
    s.write_row(37,0,['September tracking','Actual Sep 1–8','Remaining budget','Remaining purchases at Aug CPA','Actual + remaining forecast'],header);s.set_row(37,44)
    s.write(38,0,'Actuals anchored update');s.write(38,1,50,style(num));s.write_formula(38,2,'=MAX(0,B16-38950.37)',style(money),84049.63);s.write_formula(38,3,'=C39/$B$8',style(decimal),84049.63/(119119.2/188));s.write_formula(38,4,'=B39+D39',style(decimal),50+84049.63/(119119.2/188))
    s.merge_range('A41:I42','September planning projection uses the full monthly budget at August CPA; the tracking estimate separately preserves 50 purchases already observed on ₱38,950.37 spend. The daily schedule is a planning assumption, not a reconciliation of actual daily delivery.',wrap)
    ch=w.add_chart({'type':'column'});ch.add_series({'name':'Monthly sales target','categories':['Sep Dec Forecast',12,1,12,4],'values':['Sep Dec Forecast',19,1,19,4],'fill':{'color':'#2F75B5'},'data_labels':{'value':True,'num_format':'0,,"M"'}});ch.set_title({'name':'Sales goals | September–December'});ch.set_y_axis({'num_format':'0,,"M"'});ch.set_legend({'none':True});ch.set_size({'width':900,'height':320});s.insert_chart('A45',ch)
    s=page('Daily Budget Schedule',8);s.set_column(0,0,47);s.set_column(1,7,21)
    s.merge_range('A1:H1','September Daily Budget Schedule',title);s.set_row(0,32)
    s.merge_range('A2:H3','Campaign names mapped from the five funded September rows in the combined source: All Brands, BFG PMax [New], Michelin, BFG Traffic, Branding. Rates and effective dates supplied by user; constant rates assumed from September 1 for the first three.',caution);s.set_row(1,32);s.set_row(2,26)
    s.write_row(4,0,['Campaign','Sep 1–6 daily','Sep 7–8 daily','Sep 9–30 daily','Days before Sep 7','Days Sep 7–8','September budget','Days Sep 9–30'],header);s.set_row(4,44)
    entries=[('All Brands - PMax',937.5,937.5,937.5),('BFG PMax [New]',937.5,937.5,937.5),('Michelin - PMax',937.5,937.5,937.5),('BFG - PMax (Traffic)',450,500,500),('Gulongph Branding - PMax',400,400,937.5)]
    for r,row in enumerate(entries,5):
        s.write(r,0,row[0]);s.write_row(r,1,list(row[1:]),inp);s.write(r,4,6);s.write(r,5,2);s.write(r,7,22)
        s.write_formula(r,6,f'=B{r+1}*E{r+1}+C{r+1}*F{r+1}+D{r+1}*H{r+1}',style(money),row[1]*6+row[2]*2+row[3]*22)
    s.write(10,0,'TOTAL',section)
    for c,value in [(1,3662.5),(2,3712.5),(3,4250),(6,123000)]:s.write_formula(10,c,f'=SUM({chr(65+c)}6:{chr(65+c)}10)',style(money),value)
    s.merge_range('A13:H14','September schedule totals ₱123,000, +3.26% vs August actual spend. Daily run rate from September 9 is ₱4,250. No separate SRC All Brands allocation was supplied, although it appears in September actuals; no extra budget is invented for it.',wrap)
    s.merge_range('A16:H17','BFG PMax [New] in the budget source differs from BFG Advantage Touring in September actuals. This schedule follows supplied budget rows; campaign-level mapping is not verified. Actual platform delivery may differ from the daily plan.',wrap)
    import csv
    from pathlib import Path
    source=Path(__file__).resolve().parent/'GulongPH Web _Google ads_Table - Sheet1.csv'
    sh=page('August Sales Basis',7);sh.set_column(0,0,46);sh.set_column(1,6,24)
    sh.merge_range('A1:G1','August Sales Basis — supplied combined CSV',title);sh.set_row(0,32)
    sh.merge_range('A2:G3','ASSUMPTION: Average Net Sales means net sales per recorded purchase. The file does not define this field or verify attribution. Branding has no average; its sales remain excluded. These estimates are not actual revenue or proven ROAS.',caution);sh.set_row(1,34);sh.set_row(2,30)
    sh.write_row(4,0,['Campaign','August spend','Purchases','Average Net Sales','Estimated sales proxy','Source line','Coverage'],header);sh.set_row(4,38)
    month=None;records=[]
    with source.open(encoding='utf-8-sig',newline='') as h:
        for line,row in enumerate(csv.reader(h),1):
            if row[0].strip().lower() in ['august','september']:month=row[0].strip().lower();continue
            if month!='august' or not row[0] or row[0] in ['Campaign','OVERALL TOTAL']:continue
            records.append((line,row))
    total=0
    for i,(line,row) in enumerate(records,5):
        cost=float(row[2].replace(',',''));purchases=float(row[8]);avg=float(row[12].replace('₱','').replace(',','')) if row[12] else None
        sh.write(i,0,row[0]);sh.write(i,1,cost,style(money));sh.write(i,2,purchases,style(num));sh.write(i,5,line);sh.write(i,6,'Included under assumption' if avg else 'Missing average')
        if avg:
            sh.write(i,3,avg,style(money));sh.write_formula(i,4,f'=C{i+1}*D{i+1}',style(money),purchases*avg);total+=purchases*avg
        else:sh.write(i,3,'Not supplied');sh.write(i,4,'Not estimated')
        sh.set_row(i,32)
    sh.write(11,0,'TOTAL KNOWN-AVERAGE PROXY',section);sh.write_formula(11,4,'=SUM(E6:E11)',style(money),total)
    sh.merge_range('A14:G15','Coverage: 183 of 188 August purchases (97.3%) have an average-sales value. The proxy is ₱3,244,492.26; all August ad spend is retained in the efficiency denominator. Missing Branding sales are not assumed to be zero in reality.',wrap)
    sh.merge_range('A17:G18','Budget source discrepancy: the combined September Cost total is ₱111,574.21, but dated daily budgets imply ₱123,000. The plan uses the explicit daily schedule requested by the user. The combined September section is not the Sep 1–8 actual export.',wrap)
    # Promote new requested forecast and label old one as historical context.
    main=w.get_worksheet_by_name('Executive Summary')
    main.write('I5','September Plan • August CPA',section);main.write('I6',123000/(119119.2/188),style(decimal))
    main.merge_range('A48:L49','UPDATED FORECAST: See Sep Dec Forecast for September–December budget growth inputs and ₱11M / ₱12M / ₱13M / ₱14M sales goals. September planned spend is ₱123,000. Earlier MTD pace scenarios are retained as historical context.',caution)
    main.print_area('A1:L49')
    # Replace stale management forecast statement in an existing merged row.
    main.write('A25','• September plan: ₱123,000 spend, using supplied daily budgets. At August CPA this implies 194.1 purchases; October–December budget growth rates are pending. Sales estimates use the explicitly qualified August sales proxy.',wrap)
    for name in ['September Forecast']:
        w.get_worksheet_by_name(name).hide()
    promoted=['Executive Summary','Sep Dec Forecast','Daily Budget Schedule']
    w.worksheets_objs.sort(key=lambda sh:promoted.index(sh.name) if sh.name in promoted else 3)
