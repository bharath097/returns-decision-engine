import json
charts=open('charts.json').read(); DATA=open('data.json').read(); VARS=open('vars.json').read()
H2="font-family:'Big Shoulders Display',Impact,sans-serif;font-weight:900;font-size:clamp(48px,6vw,88px);line-height:.9;text-transform:uppercase;margin:0"
MONO="font-family:'IBM Plex Mono',monospace"
def sec(id_, title, sub, body, bg="#e4e8ea", fg="#0e1420", pad="72px 48px"):
    return f'''<div id="{id_}" style="background:{bg};color:{fg};padding:{pad}"><div style="max-width:1344px;margin:0 auto">
<div style="display:flex;flex-wrap:wrap;gap:14px 40px;align-items:flex-end;justify-content:space-between;margin-bottom:30px"><h2 style="{H2};text-wrap:balance">{title}</h2><p style="margin:0;max-width:480px;opacity:.8">{sub}</p></div>{body}</div></div>'''
def card(tag, title, rows):
    r=''.join(f'<div style="padding:10px 18px;border-top:1px solid #c3cad0"><div style="{MONO};font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#ff4a12">{k}</div><div style="font-size:15.5px;color:#27303b">{v}</div></div>' for k,v in rows)
    return f'''<div style="background:#f6f7f7;border:2px solid #0e1420;display:flex;flex-direction:column"><div style="background:#0e1420;color:#e4e8ea;padding:8px 18px;{MONO};font-size:12px;letter-spacing:.1em;text-transform:uppercase">{tag}</div><div style="padding:16px 18px 10px 18px;font-family:'Big Shoulders Display',Impact,sans-serif;font-weight:800;font-size:32px;line-height:1;text-transform:uppercase">{title}</div>{r}</div>'''

# ---------------- HOW IT WORKS
mods=[
("Data","Simulate and load","Where the numbers come from",[
("What","A simulator builds 34 sources, 800 lots and 73,133 items over two years with hidden ground truth, a randomized fixed-price pilot, a photo experiment, wrong catalog matches, duplicate rows and late price revisions, and a source-mix change in June 2026.","") ,
("Why","With no real data available, known truth lets every method be graded against the answer it is trying to recover. The injected defects are the ones the take-home taught: duplicates inflate joins.",""),
("Impact","Staging removes 1,097 duplicate item rows and 36 duplicate lot rows. Left in, lot cost would be overstated by 3.9%.","")]),
("Warehouse","DuckDB models and tests","Clean once, define once",[
("What","Staging models de-duplicate; marts compute every cost and recovery definition; 15 data-quality tests run on every build (13 must pass, 2 report what was cleaned).",""),
("Why","One definition of net revenue, handling, holding and allocated lot price, so every model and report agrees. Lot price is allocated to items by retail share and the test checks it ties to the lot price to the cent.",""),
("Impact","Zero failing tests. Open items carry no outcome until they close, so no model trains on unfinished results.","")]),
("Model 1","Recovery rate","Predict what an item will recover, zeros included",[
("What","Two parts: probability it sells, times expected recovery if it sells. LightGBM on listing-time features, calibrated on a later window, with conformal 80% intervals.",""),
("Formula","E[recovery] = P(sold) x E[recovery | sold]. Target = sale price / retail value; unsold = 0.",""),
("Impact","Error 0.169 vs 0.187 (incumbent lookup) and 0.209 (category average). Total dollars within 2.9%. A sold-only model overstates by 13%.","")]),
("Model 2","Sale timing","How long until a fixed-price item sells",[
("What","Discrete-time survival: one row per item per day, a boosted classifier for the daily chance of sale, with unsold items censored not dropped, then recalibrated at the window end.",""),
("Why","Fixed price has no countdown. Without a timing model you cannot say how long to wait or compare strategies fairly.",""),
("Impact","Ranks items well (Brier 0.236 vs 0.250 constant). Over-predicts after the June source change (0.638 vs 0.587): flagged by monitoring.","")]),
("Decision 1","The zero problem","Is a zero a loss or just a slow sale?",[
("What","Reads the randomized pilot three ways (sold only, zeros counted, whole strategy), tests balance, and sizes the sample.",""),
("Formula","E_fixed = p(1+m)X + (1-p)(X-h). Fixed-price-first wins if p > h / (mX + h).",""),
("Impact","On average fixed-price-first is worse than auction (-0.013 per retail dollar) and takes 14 days vs 4. By category it is a clear win only for Large_appliances (+0.070); auction clearly wins for Laptops_current, Smartphones, Gaming, Beauty_health and Toys_games. Choosing per item gains +$3.94 per item over always-auction.","")]),
("Decision 2","Waiting and markdowns","When to hold, when to cut",[
("What","Per-category price response from the pilot, then backward induction over a price ladder to get the best price each day.",""),
("Formula","Hold one more day iff q(P - A) > (1 - q)(c + d). q = chance of sale today, P = price now, A = auction fallback, c = holding cost, d = decay.",""),
("Impact","Learned schedule 0.322 vs 0.295 for the best single price, scored against the true mechanism. 0.303 inside the tested range: confirm with a markdown test.","")]),
("Decision 3","Effort","Which items deserve photos or handling at all",[
("What","Randomized extra-photo experiment, uplift shrunk toward the pool, converted to dollars and compared with labor. A separate table finds the smallest band where an item earns anything.",""),
("Formula","Take extra photos iff uplift x expected sale price x (1 - fee) + avoided refunds > minutes x labor rate.",""),
("Impact","Photos pay when the expected sale price is above about $27 (roughly the $100 to $250 retail band). Below it they lose money.","")]),
("Decision 4","Sources and bids","What a pallet is worth and what to pay",[
("What","Source scorecard with points and tiers (empirical-Bayes shrinkage), a lot-value model, and a bid ceiling with a risk buffer, backtested on 800 lots.",""),
("Formula","Ceiling = (E[lot net value] - freight - k x sigma) / (1 + target margin).",""),
("Impact","Lot value correlates 0.979 with actual. Source score correlates 0.83 with true profitability. A strict ceiling skips 68% of lots; the sweep shows the cost.","")]),
("Model 3","Match quality","Is the catalog match right?",[
("What","A classifier trained on 4,388 audited matches flags likely-wrong matches and ranks a review queue by dollars at risk.",""),
("Why","Recovery is measured against the recorded retail value. A wrong match corrupts the target and the price.",""),
("Impact","Reviewing the top 5% of items captures about 75% of mismatch dollars; 20% captures 99%.","")]),
("Monitoring","Is it still good?","Drift, error by month, retrain rule, model card",[
("What","Population stability index per input, monthly error against a baseline, a retrain rule, and a model card with limits.",""),
("Why","The June 2026 source change is exactly the kind of shift that breaks a model without anyone noticing.",""),
("Impact","Alerts on listing month (seasonal), source type and source id (the new regional marketplace). Retrain recommended.","")]),
("Metric layer","Answer report requests","Same question, same number, with assumptions",[
("What","Governed metric definitions with seven fields each, gross vs net, week and month rules, and clarifying questions when a request is ambiguous.",""),
("Why","'Sales last week' has several honest answers. The layer asks, or states which one it used and why.",""),
("Impact","12 test questions resolve correctly: 'sales' and 'revenue' prompt a question; 'recovery' defaults to the documented gross-on-all-items measure and says so.","")]),
]
how=''.join(card(a,b,[(k,v) for k,v,_ in rows]) for a,b,c,rows in mods)

# ---------------- RECOMMENDATIONS (static text, numbers from results)
recs=[
("01","Use the two-part recovery model as the estimate, and show the range","Replace single-number estimates with P(sale) x price-if-sold plus an 80% interval. Keep zeros in the target.","MAE 0.169 vs 0.187 incumbent. Total predicted dollars within 2.9% (incumbent +12.6%). Intervals cover 78% against an 80% target.","About $1.17 per item at no premium (95% interval $0.69 to $1.66), roughly $1,460 a month at 1,245 fixed-price items a month.","High on method. Medium on size: the gain is real in simulation and must be re-measured on real data."),
("02","Choose the channel by category, not one rule for everything","Fixed-price-first for categories where the pilot shows it wins (Large_appliances here). Auction for high-demand categories (Smartphones, Laptops_current, Gaming). Randomize anywhere the pilot cannot tell.","Pilot effect per retail dollar: Large_appliances +0.070; Laptops_current -0.056, Smartphones -0.052, Gaming -0.052. Overall -0.013, and 14 days vs 4. Picking per item gains about $3.94 per item.","Roughly +$4 per item on the items moved, without the 3.5x longer inventory time of a blanket fixed-price rule.","Medium. It depends on the simulated demand curve, and 3 sold of 5 cannot decide on its own (23% to 88%)."),
("03","Test markdowns instead of holding one price","Randomize a markdown step (for example day 5, day 10) in a few categories and measure.","Learned schedule 0.322 vs 0.295 for the best fixed price, but only 0.303 inside the tested premium range.","Up to +0.027 per retail dollar if it holds; the experiment tells you before you commit.","Medium. Extrapolation outside the tested range is the risk."),
("04","Re-pick the premium before improving the price anchor","The best list price depends on the premium. A better anchor helps at low premiums and stops helping from +20%.","Gain per item vs incumbent: +$0.94 at 0%, +$0.33 at +10%, -$0.31 at +20%, -$0.83 at +30% (see Scenarios).","Choosing the premium first is worth more than a better estimate.","Medium."),
("05","Take extra photos only on higher-value items","Rule: extra photos when expected sale price is above about $27 (roughly retail $100 and up).","Pooled uplift 3.9% of sale price after fees against about $1.06 of labor. Net +$1.39 (100-250 retail), +$4.39 (250-500), +$9.84 (500-1000), +$22.73 (1000+). Negative below $50.","Saves labor on low-value items and adds a few dollars each where it pays.","Medium. Per-category effects are noisy, so the rule uses the pooled estimate."),
("06","Buy more of what earns, and cap what you pay for what loses","In this data 8 of 15 categories earn money and 7 lose. Smartphones and Laptops_current earn about $1.06M; Furniture, Home_decor and Toys_games lose about $0.49M between them. Raise volume in the first group, cap the price per retail dollar in the second. The Playbook tab gives the cap for each category.","Contribution margin by category after allocating lot price by retail share (Playbook and Scenarios tabs).","The seven losing categories cost about $0.64M against $1.46M earned by the eight profitable ones.","Medium. Allocation by retail share is an accounting choice and the margins are simulated."),
("07","Raise prices where demand is hot","Where sell-through is above 92% and auctions draw more than three bidders (Smartphones, Laptops_current, Gaming, Audio_wearables, Tools), raise the opening bid or test a higher fixed premium.","Those categories sell 93% to 97% of the time with 3 to 6 bidders per auction.","Extra price on items that would have sold anyway.","Low to medium: it needs a test, because sell-through can fall once you raise prices."),
("08","Negotiate by source with the scorecard and a bid ceiling","Push price down where headroom is negative, offer volume where it is positive, and keep records of seller responses.","Lot-value model correlates 0.979 with actual. A counter at the ceiling raises profit per dollar spent from 0.16 to about 0.33 to 0.35 in the backtest.","Depends on how often sellers accept: the backtest assumed 25% to 100%.","Low to medium until real acceptance history replaces the assumption."),
("09","Send the top 5% of risky matches to a human","Review by expected dollars at risk, not by confidence alone.","5% of items captures about 75% of mismatch dollars.","Removes most price distortion from wrong matches for a small review load.","High in simulation. Real catalog errors may be less separable."),
("10","Keep the metric layer, and monitor with a retrain rule","Use the definitions file and clarifying questions for report requests. Retrain when error rises 20% or an input alarms; refresh sale-timing calibration monthly.","After the June source change, input drift alarms on source type and the sale-timing model over-predicts (0.638 vs 0.587).","Removes disagreements about what a number means and catches the next shift early.","High."),
]
recs_html=''.join(f'''<div style="background:#f6f7f7;border:2px solid #0e1420;display:grid;grid-template-columns:74px minmax(0,1fr);gap:0"><div style="background:#ff4a12;color:#0e1420;font-family:'Big Shoulders Display',Impact,sans-serif;font-weight:900;font-size:46px;padding:14px 0 0 14px">{n}</div><div style="padding:16px 22px 18px 22px;display:flex;flex-direction:column;gap:8px"><div style="font-family:'Big Shoulders Display',Impact,sans-serif;font-weight:800;font-size:30px;line-height:1.05;text-transform:uppercase">{t}</div><div style="font-size:16.5px;font-weight:500">{a}</div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px 22px;margin-top:4px"><div><div style="{MONO};font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#ff4a12">Evidence</div><div style="font-size:15px;color:#27303b">{e}</div></div><div><div style="{MONO};font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#ff4a12">Impact</div><div style="font-size:15px;color:#27303b">{i}</div></div><div><div style="{MONO};font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#ff4a12">Confidence and caveat</div><div style="font-size:15px;color:#27303b">{c}</div></div></div></div></div>''' for n,t,a,e,i,c in recs)

open('parts_how.html','w').write(how); open('parts_recs.html','w').write(recs_html)
