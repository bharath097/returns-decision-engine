"""Plain-language page content. Numbers come from facts.json / data.json so they follow each pipeline run."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
F = json.load(open(os.path.join(HERE, 'facts.json')))
D = json.load(open(os.path.join(HERE, 'data.json')))
CH = json.load(open(os.path.join(HERE, 'charts.json')))

INK, MUTED, LINE, PAPER, ACCENT = '#231f1b', '#5f574e', '#d9d1c3', '#fffdf9', '#17645f'
SERIF = "font-family:'Newsreader',Georgia,serif"
SANS = "font-family:'Source Sans 3',system-ui,-apple-system,'Segoe UI',sans-serif"
CODE = "font-family:ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace"

def p(t, extra=''): return f'<p style="margin:0 0 14px 0;max-width:760px;{extra}">{t}</p>'
def h3(t): return f'<h3 style="{SERIF};font-weight:600;font-size:26px;line-height:1.2;margin:34px 0 10px 0;color:{INK}">{t}</h3>'
def box(inner, bg=PAPER, extra=''): return f'<div style="background:{bg};border:1px solid {LINE};border-radius:8px;padding:20px 24px;{extra}">{inner}</div>'
def lab(t): return f'<div style="font-size:13px;font-weight:700;color:{ACCENT};margin-bottom:2px">{t}</div>'
def code(t): return f'<pre style="{CODE};font-size:13.5px;line-height:1.6;background:#2a2622;color:#efe9de;padding:16px 18px;border-radius:8px;overflow-x:auto;white-space:pre;margin:10px 0 18px 0">{t}</pre>'
def ul(items): return '<ul style="margin:0 0 14px 0;padding-left:22px;max-width:780px">' + ''.join(f'<li style="margin:5px 0">{i}</li>' for i in items) + '</ul>'
def table(head, rows, widths=None):
    th = ''.join(f'<th style="text-align:left;padding:9px 12px;border-bottom:2px solid {INK};font-size:14px">{c}</th>' for c in head)
    tr = ''.join('<tr>' + ''.join(f'<td style="padding:10px 12px;border-bottom:1px solid {LINE};vertical-align:top;font-size:15px">{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<div style="overflow-x:auto;margin:6px 0 20px 0"><table style="border-collapse:collapse;width:100%;min-width:640px"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'

# ------------------------------------------------------------------ START HERE
def start_here():
    n = F
    intro = (
        p('Recovery Lab is a worked example of how a company that buys truckloads of returned goods and resells them at auction can decide three things: <b>what to pay for a pallet</b>, <b>how to sell each item</b>, and <b>where extra effort is worth it</b>. Everything here was built end to end (data, database, models, decisions, tests) and then written up on this site so each result comes with its reasoning.', 'font-size:19px') +
        p('<b>All of the data is simulated.</b> No real company numbers are used. The simulator has a hidden "true" answer for every item, which lets us check each method against the truth it is trying to recover. The settings that shape the simulated world are placeholders, so read the results as a demonstration of the method and not as facts about a business.'))
    facts_row = ''.join(f'<div style="background:{PAPER};border:1px solid {LINE};border-radius:8px;padding:14px 18px"><div style="{SERIF};font-size:34px;font-weight:600;line-height:1.1">{v}</div><div style="font-size:14px;color:{MUTED}">{l}</div></div>' for v, l in [
        (f"{n['n_items']:,}", 'items in the data'), ('800', 'pallets (lots)'), ('34', 'sources you buy from'), ('15', 'product categories'), (f"{n['n_dq']}", 'data checks run each build'), ('33', 'automated tests')])
    facts_grid = f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:6px 0 10px 0">{facts_row}</div>'
    asof = f'<p style="color:{MUTED};font-size:14px;margin:0 0 6px 0">Results on this site were produced by the pipeline run of <b>{n["built_at"]}</b>. See the Pipeline tab for how that is refreshed.</p>'
    guide = table(['Tab', 'What is in it', 'Use it when'], [
        ['<b>Start here</b>', 'This page: the idea, the plain-English glossary, how to read the numbers.', 'You are new to the project.'],
        ['<b>Findings</b>', 'Nine results. Each says what question was asked, what was found, what it means and what to do.', 'You want to know what the analysis concluded.'],
        ['<b>Playbook</b>', 'A recommendation for every category: buy more, buy selectively or buy less. Has controls you can change, and you can load your own numbers.', 'You want to know what to do with each product category.'],
        ['<b>Scenarios</b>', 'Nine small calculators (break-even, price markup, bid ceiling, photos and more). Each says how to use it and how to read it.', 'You want to test a "what if".'],
        ['<b>Recommendations</b>', 'Ten actions with the evidence, expected impact and how sure we are.', 'You want the action list.'],
        ['<b>How it works</b>', 'Every model and decision: what it does, why it exists, the formula, the impact.', 'You want the method.'],
        ['<b>Variables</b>', 'All 40 inputs: what each means, when it is known and which model uses it.', 'You want to know what data goes in.'],
        ['<b>Calculations</b>', 'Every formula, a worked example with real numbers, and the 12 report numbers.', 'You want to check the arithmetic.'],
        ['<b>Pipeline</b>', 'How the whole thing runs, how it refreshes by itself, how to update each part and what breaks if you skip a step.', 'You maintain or extend it.']])
    reading = (
        p('Three things to keep in mind when you read any number:') +
        ul(['<b>Recovery rate</b> is the sale price divided by the original retail price. An item that never sells counts as <b>0</b>, not as "missing". Leaving zeros out makes every method look better than it is.',
            '<b>Gross vs net.</b> Gross is the sale price. Net takes off fees, shipping, handling and the cost of holding the item. Net is what the business keeps. We say which one we mean every time.',
            '<b>A result is a range, not a point.</b> Where you see "95% range", the true value is probably inside it. If the range includes zero, the data cannot tell the effect apart from no effect.']))
    gl = [
        ('Lot (pallet)', 'One truckload or pallet bought from a source at a single price. It holds many items you did not choose one by one.'),
        ('Source', 'The company or marketplace a lot comes from. Sources differ in how good their goods are and how accurate their manifests are.'),
        ('Retail value', 'What the item would cost new at a store. Used as the yardstick for everything.'),
        ('Recovery rate', 'Sale price divided by retail value. An unsold item is 0.'),
        ('Sell-through', 'The share of items that sold at all.'),
        ('Auction vs fixed price', 'At auction, bidders set the price in a few days. At fixed price, you list a price and wait. A fixed-price item has no deadline, so it may sit.'),
        ('Premium (markup)', 'How far above the expected auction price a fixed price is set. A 20% premium means listing at 1.2 times what an auction would likely bring.'),
        ('Open vs closed item', 'Closed means the outcome is final (sold, or given up). Open means still for sale, so its result is not known yet. Models must not treat open items as zeros.'),
        ('Handling cost', 'Labor to inspect, photograph, list and ship an item: minutes times the labor rate.'),
        ('Holding cost', 'The cost of keeping an item on a shelf each day, plus the interest on the money tied up in the lot.'),
        ('Contribution margin', 'Net revenue minus handling, holding, and the part of the pallet price assigned to that item. Positive means the item (or category) earned money after paying for the pallet.'),
        ('Allocation by retail share', 'How a pallet price is split across its items: an item that is 5% of the pallet\'s retail value is charged 5% of the pallet price. It is a convention, and it affects how categories look.'),
        ('Daily chance of selling (hazard)', 'For a fixed-price item, the probability it sells on a given day if it has not sold yet.'),
        ('Uplift', 'How much better (or worse) an item does under one treatment than another, for example fixed price vs auction, estimated from a randomized test.'),
        ('Randomized test', 'Items are assigned to a treatment by chance, so a difference in results can be credited to the treatment and not to which items happened to get it.'),
        ('80% range (interval)', 'A range the true recovery should fall inside about 80% of the time.'),
        ('Shrinkage', 'Pulling an average based on few observations toward the overall average, so one lucky lot does not make a source look great.'),
        ('Leakage', 'Accidentally letting a model see information it would not have at prediction time (for example the sale price). It makes models look perfect and fail in practice. The Variables tab shows how the registry blocks it.'),
        ('Drift', 'The data coming in no longer looks like the data the model learned from, so accuracy can quietly fall.'),
        ('Bid ceiling', 'The most you should pay for a lot to still earn your target margin after freight and a safety cushion.'),
        ('Tier (A to D)', 'A source\'s grade from a points scorecard. A is best.'),
    ]
    glossary = ''.join(f'<div style="display:grid;grid-template-columns:minmax(170px,.4fr) 1fr;gap:6px 24px;padding:11px 0;border-bottom:1px solid {LINE}"><div style="font-weight:700">{a}</div><div>{b}</div></div>' for a, b in gl)
    return intro + facts_grid + asof + h3('How to use this site') + guide + h3('Reading the numbers') + reading + h3('Plain-English glossary') + f'<div style="border-top:2px solid {INK}">{glossary}</div>'

# ------------------------------------------------------------------ FINDINGS
def money(x, d=2): return ('-$' if x < 0 else '$') + f'{abs(x):,.{d}f}'
def _imp(prem, anchor):
    for r in D['impact']:
        if abs(r['premium'] - prem) < 1e-9 and r['anchor'].startswith(anchor): return r
def finding(n, q, did, found, means, todo, sure, chart_i=None):
    img = ''
    if chart_i is not None:
        c = CH[chart_i]
        img = f'<div style="flex:1 1 380px;min-width:0"><img src="{c["url"]}" alt="{c["title"]}" style="width:100%;display:block;border:1px solid {LINE};border-radius:6px;background:#fff"><div style="font-size:13.5px;color:{MUTED};margin-top:6px">Chart: {c["cap"]}</div></div>'
    rows = ''.join(f'<div style="margin-bottom:12px">{lab(a)}<div>{b}</div></div>' for a, b in [('The question', q), ('What we did', did), ('What we found', found), ('What it means', means), ('What to do', todo), ('How sure we are', sure)])
    return f'<div style="background:{PAPER};border:1px solid {LINE};border-radius:8px;padding:24px 28px"><div style="display:flex;gap:14px;align-items:baseline;margin-bottom:14px"><span style="{SERIF};font-size:30px;font-weight:600;color:{ACCENT};line-height:1">Finding {n}</span></div><div style="display:flex;flex-wrap:wrap;gap:26px 34px"><div style="flex:1 1 420px;min-width:0;font-size:16.5px">{rows}</div>{img}</div></div>'

def findings():
    f = F
    i0, i2, o0 = _imp(0.0, 'new'), _imp(0.2, 'new'), _imp(0.0, 'oracle')
    cats = D['cat']; pos = [c for c in cats if c['cm'] > 0]; neg = [c for c in cats if c['cm'] <= 0]
    top = sorted(cats, key=lambda c: -c['cm'])[:3]; bot = sorted(cats, key=lambda c: c['cm'])[:3]
    L = []
    L.append(finding('1', 'Can we predict what an item will recover, including the items that never sell?',
        'Trained a model in two parts: the chance an item sells, and the price it fetches if it sells. We tested it on items listed <i>after</i> the training period, so it had never seen them.',
        f'Its average miss was <b>{f["mae_new"]:.3f}</b> of retail value, against {f["mae_inc"]:.3f} for the current category-and-condition lookup and {f["mae_cat"]:.3f} for a simple category average. Added across all items, predicted dollars were within <b>{abs(f["tot_err"]):.1f}%</b> of actual. A model trained only on sold items was <b>{f["tot_naive"]:.0f}% too high</b>. Its 80% ranges contained the real result {f["cover"]:.0f}% of the time (target 80%).',
        'Unsold items are zeros. A model that ignores them assumes everything sells and overestimates by about an eighth. The two-part model keeps the zeros, so its total is close to what actually came in.',
        'Use the estimate and its range when valuing pallets and setting list prices. Compare the 80% range coverage on real data; if it drifts far from 80%, recalibrate.',
        'High confidence in the method. The size of the gain depends on the simulated world.', 1))
    L.append(finding('2', 'What is a better estimate worth in dollars?',
        'Replayed every fixed-price item through the simulator\'s true sale process twice: once pricing from the old method, once from the new model. Same random draws, so the difference is the estimate alone.',
        f'With no markup, the new estimate adds about <b>{money(i0["gain_vs_first_per_item"])} per item</b> (95% range {money(i0["lo95"])} to {money(i0["hi95"])}), roughly <b>{money(i0["gain_per_month"],0)} a month</b> at 1,245 fixed-price items a month. Perfect knowledge of every item would add {money(o0["gain_vs_first_per_item"])}. At a +20% markup the gain is {money(i2["gain_vs_first_per_item"])} (range {money(i2["lo95"])} to {money(i2["hi95"])}).',
        'A better estimate only pays when the decision using it is also sound. At high markups the new, lower estimate lists items cheaper than the old method and gives money away.',
        'Decide the markup first, then improve the estimate. Try the Price anchor scenario to see how the gain changes with the markup.',
        'Medium. The direction is reliable; the dollar figure depends on the simulated demand.', 17))
    L.append(finding('3', 'Is it better to list fixed-price first than to go straight to auction?',
        'A randomized test: about 45% of eligible items were assigned to fixed price first (at +10%, +20% or +30% above the expected auction price), the rest to auction. We compared whole strategies, counting items that did not sell and the days spent waiting.',
        f'On average fixed-price-first is a little worse: <b>{f["ate"]:+.3f}</b> net value per retail dollar (95% range {f["ate_lo"]:+.3f} to {f["ate_hi"]:+.3f}), and it takes {f["days_fx"]:.0f} days to close against {f["days_au"]:.0f}. It differs a lot by category. Fixed price clearly wins in: <b>{f["fx_win"]}</b>. Auction clearly wins in: <b>{f["au_win"]}</b>. Choosing the channel item by item gains about {money(f["learned"])} per item over always using auction.',
        'Looking only at items that sold makes fixed price look great, because the high-priced ones that never sold are hidden. Counting those zeros and the waiting tells a different story. Items with thin auction demand do better with a fixed price; popular items do better at auction.',
        'Do not switch everything to fixed price. Use it where the pilot shows a win, keep auction for high-demand categories, and keep randomizing so you can keep checking.',
        'Medium. The category pattern is clear in the simulation; with real data, the range for each category will be wider.', 5))
    L.append(finding('4', 'How long should we wait before cutting the price?',
        'Estimated, for each category, how quickly a fixed-price item sells at different prices. Then worked out the best price for every day of a 21-day listing, with a rule: hold one more day only if the chance of selling today times what we would gain beats the cost of waiting.',
        f'A schedule that steps the price down over time earns <b>{f["wait_dp"]:.3f}</b> net value per retail dollar, against {f["wait_best"]:.3f} for the best single held price. Inside the range of prices the pilot actually tested it earns {f["wait_sup"]:.3f}.',
        'Most of the gain comes from marking down on a schedule. The part beyond the tested range is an extrapolation, so it is a hypothesis.',
        'Run a small randomized markdown test (for example a step down on day 5 and day 10 in a few categories) before rolling it out everywhere.',
        'Medium to low until tested.', 10))
    L.append(finding('5', 'Are three extra photos on an item worth the labor?',
        'A randomized photo experiment gave extra photos to half of the items in one test group. We measured the lift in sale price and refunds, took off fees, and compared it with the labor of taking the photos.',
        f'Extra photos paid for themselves from the <b>{f["photo_band"]}</b> retail band upward. The average lift was {f["pooled"]:.1f}% of the sale price after fees, against about {money(f["labor"])} of labor. Below about $50 of retail value it loses money.',
        'A fixed lift in percentage terms is worth more on an expensive item, while the labor is about the same. So the rule depends on item value, not on category.',
        'Take the extra photos on items expected to sell above roughly $25 to $30, and skip them on low-value items.',
        'Medium. Category-level effects are noisy, so the rule uses the pooled estimate.', 11))
    L.append(finding('6', 'Which sources are best, and what should we pay for a pallet?',
        'Scored every source on profit, goods quality, reliability, manifest accuracy and speed, with shrinkage for small samples. Also built a model of how much each pallet is worth and turned it into a bid ceiling.',
        f'The source score tracks true profitability well (correlation <b>{f["src_corr"]:.2f}</b>). The pallet-value model correlates <b>{f["lot_corr"]:.2f}</b> with what lots actually returned. Buying only lots priced under the ceiling means buying just {f["ceil_lots"]:.0f} of 800 lots, which doubles profit per dollar spent but cuts total profit.',
        'You can rank sources and value pallets before buying. A strict ceiling is safe but leaves money on the table; countering at the ceiling can win more, but only if sellers accept.',
        'Negotiate price down with sources whose headroom is negative, and record how often sellers accept counter-offers. The backtest assumes a constant acceptance rate, which is the weakest part.',
        'Medium for rankings. Low to medium for the counter-offer gains until you have real acceptance history.', 12))
    L.append(finding('7', 'Is the product we matched each item to the right one?',
        'Trained a classifier on a sample of audited matches (4,388 items checked by a person) to flag likely mismatches, then ranked items by dollars at risk.',
        f'Reviewing the riskiest 5% of items finds about <b>{f["top5"]*100:.0f}%</b> of the dollar error from wrong matches. Reviewing 20% finds about {f["top20"]*100:.0f}%.',
        'Recovery is measured against the recorded retail price, so a wrong match corrupts both the target and the price. A small, well-aimed review removes most of it.',
        'Send the riskiest 5% of matches to a person, ranked by expected dollars at risk.',
        'High in simulation. Real catalog errors may be harder to separate.', 14))
    L.append(finding('8', 'Is the model still reliable as the business changes?',
        'Compared each input today with what the model was trained on (a drift score), tracked error month by month, and checked the sale-timing model after the June 2026 expansion into new regional sources.',
        f'Retrain recommended: <b>{f["retrain"]}</b>. Inputs flagged: {f["alerts"]}. After the expansion the sale-timing model predicted {f["hz_pred"]:.3f} of items sold by day 21 and the real figure was {f["hz_act"]:.3f}, so it is too optimistic.',
        'New sources and a new product mix are exactly the kind of change that makes a model quietly worse. The alarms exist so you find out from a chart and not from a bad quarter.',
        'Refresh the sale-timing calibration on recent data now and set a rule: retrain when error is 20% above baseline or an input alarms.',
        'High. This is measured, not assumed.', 15))
    L.append(finding('9', 'Which product categories make money after paying for the pallet?',
        'Took each category\'s net revenue, took off handling, holding and its share of the pallet price and freight, and summed it over the whole period.',
        f'<b>{len(pos)} of 15</b> categories earned money; <b>{len(neg)}</b> lost money. Best: {", ".join(f"{c["category"]} ({money(c["cm"]/1000,0)}k)" for c in top)}. Worst: {", ".join(f"{c["category"]} ({money(c["cm"]/1000,0)}k)" for c in bot)}.',
        'Handling a single item is usually worth it once the pallet is bought. The loss in a losing category comes from what was paid for the pallet relative to what those items bring. Because pallet prices are split by retail value, this view is partly an accounting convention.',
        'Open the Playbook tab: it turns this into buy-more, buy-selectively and buy-less calls, and shows the most you can pay per retail dollar in each category.',
        'Medium. Direction is reliable; exact losses depend on how the pallet price is split.', None))
    return '<div style="display:flex;flex-direction:column;gap:24px">' + ''.join(L) + '</div>'

# ------------------------------------------------------------------ SCENARIO HOW-TO TEXT
HOW = {
 1: ('The share of fixed-price items that must sell for fixed-price-first to beat auction.', 'Move the first slider to the markup you would set. Move the second to how much of an item\'s value you lose by waiting (storage, interest, getting stuck with it). The large box shows the sell rate you need.', 'If the sell rate you actually see is above the number, fixed price wins. If it is below, auction wins. Example: 60% of 5 items sold, but the range is 23% to 88%, so five items cannot settle it.'),
 2: ('How much money a better list-price estimate makes, by markup.', 'Pick a markup with the buttons.', 'Gain vs incumbent is the extra net value per item compared with the old method. A range that includes zero means the gain is not proven. "Oracle" knows every item\'s true value and is an upper limit, not something you can reach.'),
 3: ('A backtest of different bid ceilings on 800 past pallets.', 'Choose a risk buffer (how much cushion you subtract) and a target margin (how much profit you require).', 'Compare profit with the status-quo numbers shown. Lots over the ceiling are the share you would have to counter or skip. The result assumes sellers always accept counters, so it is optimistic.'),
 4: ('The expected value of different selling plans for one category.', 'Choose a category.', 'Longer bars are better. The teal bars are the learned markdown schedule; the grey bars hold one price. Where a teal bar beats every grey bar, marking down on a schedule helps.'),
 5: ('A yes/no for extra photos on a single item.', 'Type the price you expect the item to sell for.', 'If the expected benefit is bigger than the labor cost, the net is positive and the answer is yes.'),
 6: ('Profit by category after paying for the pallet.', 'Nothing to set. It is a ranked list.', 'Green bars earn money, red bars lose it. The number on the right is margin per retail dollar.'),
 7: ('What a new cost line would do to total margin.', 'Choose the kind of cost (per item, percent of sale, or per day held), an amount, and which category it applies to.', 'The panel shows the added cost over 24 months and the new total margin. Copy the YAML into config/settings.yaml and run the pipeline to push it through every model.'),
 8: ('A checker for a new input variable before you add it.', 'Name it, say what type it is, when it is known, and which models should use it.', 'If it says "valid", the generated block can go into config/variables.yaml. If it says "leakage", the variable is only known after the model has to predict, so it cannot be used.'),
 9: ('A grade and a negotiating hint for each of the 34 sources.', 'Scroll the table. Click nothing; it is read-only.', 'Score is out of 100. Headroom is the price you could pay and still hit the target margin, minus what you pay now. Negative means push the price down.'),
}
def howto(i):
    w, u, r = HOW[i]
    return f'<div style="background:#f3eee4;border-radius:6px;padding:12px 16px;font-size:15px;line-height:1.5"><b>What it is.</b> {w}<br><b>How to use it.</b> {u}<br><b>How to read it.</b> {r}</div>'

# ------------------------------------------------------------------ VARIABLES / CALCS intros
def variables_intro():
    return (p('A <b>variable</b> is one column of information about an item, a lot or a source. The registry lists all 40, with when each becomes known. A model is only allowed to use variables known <i>before</i> the moment it predicts. That one rule is what keeps the results honest.') +
        table(['Role', 'Meaning'], [['feature', 'An input a model may learn from, such as category, condition or retail value.'], ['outcome', 'A result you are trying to predict or report, such as sale price or days to close. Never an input.'], ['cost', 'A cost component used in the profit arithmetic.'], ['context', 'Descriptive fields that help read results but are not model inputs.'], ['key', 'An identifier used to join tables.']]) +
        table(['Known at', 'When', 'Allowed as a model input?'], [['receipt', 'The pallet arrives', 'Yes'], ['listing', 'The item is listed', 'Yes. This is the normal prediction moment.'], ['during listing', 'While it is for sale (for example watchers)', 'Only in the daily sale-timing model'], ['sale / post sale', 'It sells / later (refunds)', 'Never. These are outcomes.']]))

def calcs_intro():
    return (p('These are the formulas the whole project shares. The first box is the arithmetic for a single item. The second is the decision rules. Below them is one item worked through with real numbers, then the 12 report numbers the engine computes, with the SQL behind each.') +
        h3('One item, worked through') +
        p('Take an item with a retail value of $200 that sells for $90 after 6 days. It is in weight class 1, takes 10 minutes to handle, and its share of the pallet price is $40 plus $1 of freight. Using the default settings (labor $0.62 a minute, 3.5% + $0.30 fee, $7 shipping subsidy, $0.06 a day shelf cost, 12% annual cost of capital):') +
        table(['Step', 'Calculation', 'Result'], [
            ['Gross recovery', '90 / 200', '0.45'],
            ['Fees', '0.035 x 90 + 0.30', '$3.45'],
            ['Net revenue', '90 - 3.45 - 7.00', '$79.55'],
            ['Net recovery', '79.55 / 200', '0.398'],
            ['Handling cost', '10 min x $0.62', '$6.20'],
            ['Holding cost', '6 days x $0.06 + $40 x 12% / 365 x 6', '$0.44'],
            ['Final net value', '79.55 - 6.20 - 0.44', '$72.91'],
            ['Contribution margin', '72.91 - 40.00 (pallet share) - 1.00 (freight)', '<b>$31.91</b>']]) +
        p('The same item that sold for $90 would have had a contribution of <i>negative</i> $5 if its pallet share had been $80. That is how a category can lose money even though every item sells.'))

# ------------------------------------------------------------------ PIPELINE
def pipeline():
    stages = table(['#', 'Stage', 'What happens', 'Command', 'Reads', 'Writes'], [
        ['1', '<b>Raw data</b>', 'The four source tables (items, lots, outcomes, sources) and an audit table. Today the simulator creates them.', '<span style="' + CODE + '">make simulate</span>', 'config/simulation.yaml', 'data/raw/*.parquet'],
        ['2', '<b>Warehouse</b>', 'Loads raw tables into DuckDB, removes duplicate rows, computes every cost and recovery column, runs 15 data checks.', '<span style="' + CODE + '">make build</span>', 'data/raw, sql/, config/settings.yaml, variables.yaml, calculations.yaml', 'data/warehouse.duckdb'],
        ['3', '<b>Models and decisions</b>', 'Fits the recovery, sale-timing, uplift, match and lot-value models; runs the channel, waiting, effort, scorecard and bid-ceiling decisions; checks drift.', '<span style="' + CODE + '">make run</span>', 'the warehouse', 'outputs/tables (45 CSVs), outputs/figures (18 PNGs), outputs/RESULTS.md'],
        ['4', '<b>Tests</b>', '33 automated tests, including one that adds a variable, a calculation and a cost line end to end.', '<span style="' + CODE + '">make test</span>', 'src/, tests/', 'pass or fail'],
        ['5', '<b>Website</b>', 'Turns the output tables and charts into this single HTML page.', '<span style="' + CODE + '">python site_builder/build_site.py</span>', 'outputs/', 'docs/site/index.html']])
    cmds = code('make all     # stages 1, 2 and 3 (about 2.5 minutes)\nmake test    # stage 4 (about 15 seconds)\npython site_builder/build_site.py   # stage 5\n\n# one-time setup on a new machine\npip install -r requirements.txt pillow\npip install -e .')
    auto = (
        p('A GitHub Actions workflow (<span style="' + CODE + '">.github/workflows/pipeline.yml</span>) runs stages 1 to 5 by itself and saves the results back into the repo. Its steps, in order:') +
        ul(['Check out the repo and install Python 3.12 and the packages.', 'Run <b>make all</b>, then <b>make test</b>. If a test fails, the job stops and nothing is committed.', 'Rebuild the website from the new outputs.', 'Commit the refreshed <span style="' + CODE + '">outputs/</span> and <span style="' + CODE + '">docs/site/</span> back to the main branch. The commit message ends with [skip ci] so it does not trigger another run.']) +
        table(['It runs when', 'Detail'], [['Every Monday', 'Cron line <span style="' + CODE + '">0 7 * * 1</span> (07:00 UTC). Edit that line in the workflow file to change the day or time.'], ['You push code', 'Any push to main, except pushes that only touch outputs/ or docs/site/ (those are the bot\'s own results).'], ['You press the button', 'Actions tab, then pipeline, then Run workflow.']]) +
        p('A green run takes about two minutes. To see what happened, open the Actions tab, click the run, then click a step. The commit it made appears in the Code tab under the name pipeline-bot.'))
    upd = table(['You want to change', 'Edit this file', 'Then run', 'What updates on the site'], [
        ['Labor cost, fees, shipping, holding cost, cost of capital', 'config/settings.yaml (economics)', 'make all, make test, build_site', 'Margins, Playbook, Scenarios, Calculations, every decision'],
        ['Target margin, risk buffer, scorecard weights, markdown steps', 'config/settings.yaml (decisions)', 'make all, build_site', 'Sources, bid ceilings, waiting rule'],
        ['Add a new input variable', 'config/variables.yaml (plus a CSV in data/user_inputs if it comes from outside)', 'make all, make test, build_site', 'Variables tab, models that use it'],
        ['Add a new calculation or report number', 'config/calculations.yaml', 'make all, build_site', 'Calculations tab'],
        ['Add a cost line (for example pallet wrap)', 'config/settings.yaml, economics.cost_components', 'make all, build_site', 'Net values, margins, Playbook'],
        ['Add or reword a report metric', 'config/metric_definitions.yaml', 'make test, make all', 'Metric layer answers'],
        ['Change how the simulated world behaves', 'config/simulation.yaml', 'make all, make test, build_site', 'Everything (new data, new results)'],
        ['<b>Use real data instead of simulated</b>', 'Put your tables in data/raw (same column names: see docs/DATA_DICTIONARY.md)', '<b>make build</b> then <b>make run</b> (never make simulate or make all: they overwrite data/raw)', 'Everything. In the workflow, change the "Run the pipeline" step to run make build and make run.'],
        ['Reword the website text', 'site_builder/content.py, gen2.py, gen3.py, logic.js', 'python site_builder/build_site.py', 'The site only'],
        ['Change when the automatic run happens', '.github/workflows/pipeline.yml (cron line)', 'commit the file', 'Nothing on the site']])
    chain = (
        p('The pipeline is a chain, and each link feeds the next:') +
        code('raw data  ->  warehouse  ->  models and decisions  ->  outputs  ->  website\n(data/raw)  (warehouse.duckdb)  (src/recovery_lab)       (outputs/)  (docs/site)') +
        p('<b>The site is only as fresh as the last link that ran.</b> If you change a config file and rebuild only the website, the site shows old numbers. If you replace the raw data and run only the models, the warehouse is stale. When in doubt, run everything from the stage you changed to the end. A change is fully applied when:') +
        ul(['<b>make all</b> finishes without error (every data check passes; the two duplicate-row warnings are expected and just report what was cleaned).', '<b>make test</b> shows all tests passing.', '<b>build_site.py</b> prints that it wrote docs/site/index.html.', 'The Start here tab shows a new "pipeline run of" date.', 'The Findings numbers changed in the direction you expected.']) +
        p('Two parts of the site are <b>typed text, not computed</b>: the wording of the Recommendations and the How it works cards. Their numbers do not move on their own. After a large change, read them and edit <span style="' + CODE + '">site_builder/gen2.py</span> if they no longer match. Never edit docs/site/index.html by hand; the next run overwrites it.'))
    trouble = table(['What you see', 'Likely cause', 'Fix'], [
        ['Push rejected, "fetch first"', 'The repo changed while the job was running.', 'Already handled: the workflow pulls before it pushes. Re-run the job.'],
        ['Push fails with 403 or permission denied', 'The job cannot write to the repo.', 'Settings, Actions, General, Workflow permissions, choose Read and write.'],
        ['The "Run the tests" step is red', 'A test failed after a code or config change.', 'Open the step, read the failing test name, fix it, push. Nothing was committed.'],
        ['The "Run the pipeline" step is red', 'A data check failed or a package version changed.', 'Read the last lines of the step. Data check names are in docs/DATA_DICTIONARY.md.'],
        ['Site looks old', 'The run did not finish, or Pages has not rebuilt.', 'Check the Actions tab for a green run; Pages updates one to two minutes after the commit.'],
        ['Numbers changed a little between runs', 'Model training is not fully seeded.', 'Expected. Small shifts (a few percent) are noise; large shifts are worth investigating.']])
    folders = code('config/        settings, simulation, variables, calculations, metric definitions (all editable)\nsql/           the warehouse: staging, marts, post-marts, data checks\nsrc/recovery_lab/\n  sim/         the simulator\n  data/        loading and the variable registry\n  models/      recovery, sale timing, uplift, match, lot value, monitoring\n  decisions/   channel, waiting, effort, scorecard, bid ceiling, impact\n  metrics/     the report-request layer\ntests/         33 tests\ndata/raw       input tables (simulated today)\noutputs/       tables, charts, RESULTS.md (written by the pipeline)\nsite_builder/  turns outputs into the website\ndocs/          documentation and docs/site/index.html (the website)\n.github/workflows/pipeline.yml   the automatic run')
    return (h3('The five stages') + stages + cmds + h3('The automatic run on GitHub') + auto + h3('How to update each thing') + upd + h3('It only works when everything is updated') + chain + h3('When something goes wrong') + trouble + h3('Where things live') + folders)
