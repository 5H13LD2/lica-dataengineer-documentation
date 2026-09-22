"""Apply user-supplied updated Aug–Dec summary as the authoritative planning input."""
import csv
from pathlib import Path

def add(ctx):
    globals().update({k:ctx[k] for k in ['w','page','title','subtitle','header','section','caution','wrap','style','money','pct','num','decimal']})
    base=Path(__file__).resolve().parent
    with (base/'Forecast_Updated_Summary_Source.csv').open(encoding='utf-8-sig',newline='') as h:raw=list(csv.reader(h))
    src=page('Updated Summary Source',12);src.set_column(0,11,24)
    for r,row in enumerate(raw):
        src.write_row(r,0,row,wrap if r!=2 else header)
    src.set_row(12,100)
    forecasts=raw[4:8]
    s=page('Aug Dec Forecast',12);s.set_column(0,0,33);s.set_column(1,5,24);s.set_column(6,11,17)
    s.merge_range('A1:L1','Gulong.ph Ads & Sales Forecast | August–December 2026',title);s.set_row(0,34)
    s.merge_range('A2:L2','Updated user summary is the current plan. August sales baseline: ₱10.02M as supplied; September–December sales and funnel figures are targets.',subtitle);s.set_row(1,30)
    s.merge_range('A3:L3','Planning targets, not a statistically validated sales forecast. August sales scope is not defined; sales divided by ad spend must not be interpreted as attributed ROAS.',caution);s.set_row(2,36)
    s.write_row(4,0,['Metric','August actual','September','October','November','December'],header);s.set_row(4,32)
    labels={5:'Sales baseline / goal',6:'PMax campaign count',7:'PMax daily budget each',8:'PMax daily budget increase',9:'Days in month',10:'PMax monthly capacity',11:'Search daily budget',12:'Search monthly capacity',13:'Total monthly budget capacity',14:'Projected spend / planning budget',15:'Monthly planning-budget growth',16:'Sessions actual / target',17:'Campaign users actual / target',18:'Add to carts actual / target',19:'Checkouts actual / target',20:'Purchases actual / target',21:'Purchase growth vs August',22:'Implied cost per target purchase',23:'Purchases at August CPA',24:'Target vs August-CPA purchase count'}
    for r,label in labels.items():s.write(r,0,label,style())
    aug=[155599,136325,7923,659,188];augspend=119119.2;augcpa=augspend/188
    s.write(5,1,10020000,style(money));s.write(13,1,augspend,style(money));s.write(14,1,augspend,style(money))
    for r,value in enumerate(aug,16):s.write(r,1,value,style(num))
    s.write(22,1,augcpa,style(money));s.write(23,1,188,style(decimal))
    inp=w.add_format({'bg_color':'#FFF2CC','font_color':'#0000FF','num_format':money})
    previous=augspend
    for c,(record,days,daily,goal) in enumerate(zip(forecasts,[30,31,30,31],[1000,1100,1200,1300],[11000000,12000000,13000000,14000000]),2):
        col=chr(65+c);prev=chr(64+c);cap=5*daily*days+500*days;plan=157000 if c==2 else cap
        s.write(5,c,goal,style(money));s.write(6,c,5,style(num));s.write(7,c,daily,inp);s.write(9,c,days,style(num));s.write(11,c,500,inp)
        if c>2:s.write_formula(8,c,f'={col}8/{prev}8-1',style(pct),daily/(daily-100)-1)
        else:s.write(8,c,'Mixed August baseline',wrap)
        s.write_formula(10,c,f'={col}7*{col}8*{col}10',style(money),5*daily*days)
        s.write_formula(12,c,f'={col}12*{col}10',style(money),500*days)
        s.write_formula(13,c,f'={col}11+{col}13',style(money),cap)
        if c==2:s.write(14,c,157000,inp)
        else:s.write_formula(14,c,f'={col}14',style(money),plan)
        s.write_formula(15,c,f'={col}15/{prev}15-1',style(pct),plan/previous-1);previous=plan
        values=[float(record[k].replace(',','')) for k in range(6,11)]
        for r,value in enumerate(values,16):s.write(r,c,value,style(num))
        s.write_formula(21,c,f'={col}21/$B$21-1',style(pct),values[-1]/188-1)
        s.write_formula(22,c,f'={col}15/{col}21',style(money),plan/values[-1])
        s.write_formula(23,c,f'={col}15/$B$23',style(decimal),plan/augcpa)
        s.write_formula(24,c,f'={col}21-{col}24',style(decimal),values[-1]-plan/augcpa)
    s.merge_range('A27:L28','September: ₱165,000 full-month capacity versus ~₱157,000 projected spend because the higher daily budget did not run from September 1. The updated source does not give enough effective-date detail to independently reproduce ₱157,000; it is retained as a supplied estimate.',wrap)
    s.merge_range('A30:L31','October capacity is exactly ₱186,000; November ₱195,000; December ₱217,000. PMax daily increases are +10.0%, +9.1% and +8.3%. Monthly total budget changes also reflect calendar days and September’s partial rollout.',wrap)
    s.merge_range('A33:L34','Funnel targets are preserved from the updated summary. Purchase targets are 206 / 225 / 244 / 263. They imply CPAs of ₱762.14 / ₱826.67 / ₱799.18 / ₱825.10, above August’s ₱633.61. Purchases at August CPA are a separate spend-based sensitivity, not an additional target.',wrap)
    s.merge_range('A36:L37','December goal is ₱14M+ in the source; calculations use ₱14M as the minimum planning target. Sales targets are not inferred from campaign Average Net Sales. The updated ₱10.02M August baseline supersedes the earlier partial sales proxy for this plan.',wrap)
    s.merge_range('A39:L40','Yellow inputs control budget scenarios; source funnel targets remain fixed when budgets change, intentionally showing the CPA needed to hit them. The source does not provide an estimated budget-to-sales response or evidence that increased spend causes proportional sales growth.',caution)
    chart=w.add_chart({'type':'column'});chart.add_series({'name':'Purchases actual / target','categories':['Aug Dec Forecast',4,1,4,5],'values':['Aug Dec Forecast',20,1,20,5],'fill':{'color':'#2F75B5'}});chart.set_title({'name':'August purchases and September–December targets'});chart.set_legend({'none':True});chart.set_size({'width':920,'height':330});s.insert_chart('A43',chart)
    # Update the visible executive page to the latest authoritative scenario.
    main=w.get_worksheet_by_name('Executive Summary')
    main.write('I5','September Purchase Target',section);main.write('I6',206,style(num))
    main.write('A25','• Updated plan: September projected ad spend ~₱157K; October–December capacity ₱186K / ₱195K / ₱217K. Purchase targets: 206 / 225 / 244 / 263.',wrap)
    main.write('A48','CURRENT PLAN: Aug Dec Forecast uses the latest supplied summary: August sales ₱10.02M; September–December goals ₱11M / ₱12M / ₱13M / ₱14M+. Earlier budget and sales-proxy scenarios are hidden as historical context.',caution)
    for name in ['Sep Dec Forecast','Daily Budget Schedule','August Sales Basis']:
        w.get_worksheet_by_name(name).hide()
    meth=w.get_worksheet_by_name('Methodology');meth.write(17,0,'Updated plan',section);meth.merge_range('B18:F20','Latest source: Forecast_Updated_Summary_Source.csv, copied from the supplied Downloads summary. Supersedes previous budget assumptions and August sales proxy for planning. Historical June–August actuals and September 1–8 actuals remain unchanged. Approximate source budget labels are reconciled to exact daily capacities in Aug Dec Forecast.',wrap)
    order=['Executive Summary','Aug Dec Forecast','Monthly Summary','September MTD']
    w.worksheets_objs.sort(key=lambda sh:order.index(sh.name) if sh.name in order else len(order))
