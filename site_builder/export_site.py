import json,glob,pandas as pd,duckdb,yaml,numpy as np
import os
HERE=os.path.dirname(os.path.abspath(__file__))
R=os.path.dirname(HERE)+'/'
old=json.load(open(HERE+'/data_shape.json'))
tabs={f.split('/')[-1][:-4]:pd.read_csv(f) for f in glob.glob(R+'outputs/tables/*.csv')}
m={'impact':'pricing_anchor_impact','sweep':'bid_sweep','bt':'bid_backtest','photo':'photo_rule_by_band','photo_cat':'photo_effects_by_category','sc':'source_scorecard','views':'zero_problem_three_views','pol':'policy_comparison','prem':'pilot_premium_table','minv':'min_item_value','drift':'drift_psi','match':'match_review_gain','rm':'recovery_metrics','cerr':'recovery_error_by_category','dq':'data_quality_tests','fi':'recovery_feature_importance','req':'required_sample','be':'breakeven_table'}
def clean(df,cols):
    df=df[cols].replace({np.nan:None}); out=json.loads(df.to_json(orient='records')); return out
new={}
for k,t in m.items(): new[k]=clean(tabs[t],list(old[k][0].keys()))
con=duckdb.connect(R+'data/warehouse.duckdb',read_only=True)
new['cat']=json.loads(con.execute("""select category, count(*) n, sum(cast(sold as int)) nsold, sum(case when sold then sale_price else 0 end) sale, sum(retail_value) retail, sum(net_revenue) netrev, sum(handling_cost) handling, sum(holding_cost) holding, sum(holding_days) hdays, sum(allocated_lot_cost+allocated_freight) lotcost, sum(contribution_margin) cm, sum(contribution_margin)/sum(retail_value) cm_per_retail from mart_item where status='closed' group by 1 order by 1""").df().round(2).to_json(orient='records'))
cal=yaml.safe_load(open(R+'config/calculations.yaml'))['aggregate_calculations']; ct=tabs['calculations']
new['calcs']=[]
for c in cal:
    v=ct[(ct.calculation==c['name'])&(ct.level=='overall')]['value']
    new['calcs'].append(dict(name=c['name'],sql=c['sql'],where=c.get('where'),levels=c['levels'],desc=c['description'],value=float(v.iloc[0]) if len(v) else None))
w=tabs['waiting_policy_results']; pv=w.pivot_table(index='category',columns='policy',values='net_value_per_retail').reset_index()
new['wait']=json.loads(pv.round(3).to_json(orient='records'))
print(list(old['wait'][0].keys()),list(new['wait'][0].keys()))
q=con.execute("select category, strftime(close_date,'%Y-%m') ym, sum(contribution_margin) cm, sum(retail_value) rv from mart_item where status='closed' group by 1,2").df()
ms=sorted(q.ym.unique()); rec=ms[-3:]; prev=ms[-9:-3]
b=con.execute("select category, avg(case when channel='auction' then bidders end) bid, avg(days_listed) d, avg(cast(sold as int)) st from mart_item where status='closed' group by 1").df().set_index('category')
pa=tabs['pilot_ate_by_category'].set_index('group'); mv=tabs['min_item_value'].set_index('category'); pc=tabs['photo_effects_by_category'].set_index('category')
pb=[]
for c,g in q.groupby('category'):
    r=lambda d: float(d.cm.sum()/d.rv.sum())
    pb.append(dict(category=c,recent=round(r(g[g.ym.isin(rec)]),3),prev=round(r(g[g.ym.isin(prev)]),3),st=round(float(b.loc[c,'st']),3),bid=round(float(b.loc[c,'bid']),2),days=round(float(b.loc[c,'d']),1),fx=round(float(pa.loc[c,'effect']),3),fxlo=round(float(pa.loc[c,'lo95']),3),fxhi=round(float(pa.loc[c,'hi95']),3),minband=(str(mv.loc[c,'smallest_profitable_band']) if c in mv.index else 'none'),photo_min=(round(float(pc.loc[c,'min_expected_sale_price_worth_extra_photos']),0) if c in pc.index and pc.loc[c,'min_expected_sale_price_worth_extra_photos']==pc.loc[c,'min_expected_sale_price_worth_extra_photos'] else None)))
new['pb']=pb
json.dump(new,open(HERE+'/data.json','w'))
why=json.load(open(HERE+'/why.json')); vr=tabs['variable_registry']; import ast
vs=[]
for _,r in vr.iterrows():
    u=r['used_in']; u=ast.literal_eval(u) if isinstance(u,str) else []
    vs.append(dict(name=r['name'],dtype=r['dtype'],role=r['role'],known_at=r['known_at'],status=r['status'],used_in=u,description=r['description'],why=why.get(r['name'],'')))
json.dump(vs,open(HERE+'/vars.json','w'))
print({k:len(v) for k,v in new.items()})

# ---------------- facts used in the plain-language text (parsed from RESULTS.md and tables)
import re, datetime
txt = open(R + 'outputs/RESULTS.md').read()
def g(pat, cast=float, default=None, grp=1):
    m = re.search(pat, txt)
    if not m: return default
    try: return cast(m.group(grp).replace(',', '')) if cast else m.group(grp)
    except Exception: return default
ate = tabs['pilot_ate'].iloc[0]
ph = tabs['photo_rule_by_band']
facts = dict(
    built_at=datetime.datetime.utcnow().strftime('%d %b %Y, %H:%M UTC'),
    mae_new=g(r'two-part model has MAE ([0-9]+(?:\.[0-9]+)?)'), mae_inc=g(r'MAE [0-9]+(?:\.[0-9]+)? vs ([0-9]+(?:\.[0-9]+)?) for an incumbent'), mae_cat=g(r'and ([0-9]+(?:\.[0-9]+)?) for a category average'),
    tot_err=g(r'within (-?[0-9]+(?:\.[0-9]+)?)% of actual'), tot_inc=g(r'incumbent ([+-]?[0-9]+(?:\.[0-9]+)?)%'), tot_naive=g(r'naive sold-only model ([+-]?[0-9]+(?:\.[0-9]+)?)%'),
    auc=g(r'AUC ([0-9]+(?:\.[0-9]+)?)'), cover=g(r'cover ([0-9]+(?:\.[0-9]+)?)% of outcomes'),
    ate=float(ate.effect), ate_lo=float(ate.lo95), ate_hi=float(ate.hi95), days_fx=float(ate.avg_days_fixed), days_au=float(ate.avg_days_auction),
    fx_win=g(r'clearly wins in: (.*?); auction clearly', None, 'none'), au_win=g(r'auction clearly wins in: (.*?);', None, 'none'),
    learned=g(r'changes value by \$(-?[0-9]+(?:\.[0-9]+)?) per item'),
    wait_dp=g(r'earns ([0-9]+(?:\.[0-9]+)?) net value per retail dollar against'), wait_best=g(r'against ([0-9]+(?:\.[0-9]+)?) for the best single'), wait_sup=g(r'tested the schedule earns ([0-9]+(?:\.[0-9]+)?)'),
    photo_band=g(r'from roughly the (.*?) retail band', None, 'n/a'), pooled=g(r'pooled uplift ([0-9]+(?:\.[0-9]+)?)%'), labor=g(r'against about \$([0-9]+(?:\.[0-9]+)?) of labor'),
    src_corr=g(r'source score correlates ([0-9]+(?:\.[0-9]+)?)'), lot_corr=g(r'lot value correlates ([0-9]+(?:\.[0-9]+)?)'), ceil_lots=g(r'buys only ([0-9]+) of 800'),
    hz_pred=g(r'\(([0-9]+(?:\.[0-9]+)?) predicted vs'), hz_act=g(r'predicted vs ([0-9]+(?:\.[0-9]+)?) actual'), retrain=g(r'Retrain recommended: (\w+)', None, 'n/a'), alerts=g(r'Alert features: (.*?) \(seasonality', None, ''),
    top5=float(tabs['match_review_gain'].query('review_share==0.05').share_of_dollar_error_captured.iloc[0]),
    top20=float(tabs['match_review_gain'].query('review_share==0.2').share_of_dollar_error_captured.iloc[0]),
    n_items=int(tabs['data_profile'].iloc[0]['rows']) if 'rows' in tabs['data_profile'] else 0,
    n_closed=int(tabs['data_profile'].iloc[0]['closed']) if 'closed' in tabs['data_profile'] else 0,
    n_open=int(tabs['data_profile'].iloc[0]['open']) if 'open' in tabs['data_profile'] else 0,
    n_dq=int(len(tabs['data_quality_tests'])), n_dq_fail=int(((tabs['data_quality_tests'].severity=='error')&(tabs['data_quality_tests'].status!='pass')).sum()),
)
json.dump(facts, open(HERE + '/facts.json', 'w'), indent=1)
print({k: v for k, v in facts.items() if v in (None, '', 'n/a')})
