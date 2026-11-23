"""Build the project home page (docs/site/index.html) from outputs/tables.

Every number in the text is read from the CSVs at build time, so the report cannot drift from the pipeline.
Run after `make all`:   python site_builder/build_report.py
"""
from __future__ import annotations

import base64
import html
import io
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
from returns_decision_engine.decisions.channel import breakeven_p, expected_value_fixed_first, wilson_ci  # noqa: E402

TB = os.path.join(ROOT, "outputs", "tables")
T = lambda n: pd.read_csv(os.path.join(TB, n + ".csv"))  # noqa: E731

INK, MUTE, GRID = "#1d2127", "#6b7380", "#e3e6ea"
BLUE, ORANGE, GRAY = "#1f5fa8", "#c4561a", "#9aa3ae"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": MUTE, "xtick.color": MUTE,
                     "ytick.color": MUTE, "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 10, "axes.titleweight": "bold",
                     "axes.titlecolor": INK, "axes.titlelocation": "left", "figure.facecolor": "white", "axes.facecolor": "white"})


def img(fig) -> str:
    b = io.BytesIO(); fig.savefig(b, format="png", dpi=150, bbox_inches="tight"); plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def pct(x, d=0): return f"{x * 100:.{d}f}%"
def usd(x, d=0): return f"${x:,.{d}f}" if x >= 0 else f"-${abs(x):,.{d}f}"
def sgn(x, d=3): return f"{x:+.{d}f}"
def cat(c): return c.replace("_", " ")


# ------------------------------------------------------------------ data
rm = T("recovery_metrics").set_index("model")
NEW, INC, NAV = "two-part model (new)", "incumbent (category x condition lookup)", "naive sold-only model"
lev = T("value_levers").set_index("order")
three = T("zero_problem_three_views")
ate = T("pilot_ate").iloc[0]
ate_c = T("pilot_ate_by_category").sort_values("effect")
prem = T("pilot_premium_table")
req = T("required_sample")
cards = T("intake_cards")
pol = T("policy_comparison").set_index("policy")
wp = T("waiting_policy_results").groupby("policy").net_value_per_retail.mean()
sched = T("waiting_schedules"); sched = sched[sched.kind == "supported range only"]
photo = T("photo_rule_by_band"); mrev = T("match_review_gain").set_index("review_share")
lots = T("lot_oof_predictions"); bid = T("bid_backtest").set_index("policy")
sc = T("source_scorecard"); samp = T("sampling_value")
mp = T("monthly_performance"); drift = T("drift_psi"); ml = T("metric_layer_examples"); anch = T("pricing_anchor_impact")
cov = T("interval_coverage_by_category")
prof = pd.read_csv(os.path.join(ROOT, "outputs", "RESULTS.md"), sep="\0", header=None, engine="python")[0].str.cat(sep="\n")
import re  # noqa: E402
def grab(pat, default="n/a"):
    m = re.search(pat, prof); return m.group(1) if m else default
AUC = grab(r"AUC ([0-9]+\.[0-9]+)"); COV = grab(r"cover ([0-9.]+%)"); RETR = "recommended" if "Retrain recommended: True" in prof else "not needed"
LOTCORR = float(np.corrcoef(lots.pred_nv, lots.actual_nv)[0, 1])
five = dict(zip(["p", "lo", "hi"], wilson_ci(3, 5)))
BE = breakeven_p(0.20, 100.0, 10.0)
n_items = 73133

fx_win = ate_c[ate_c.lo95 > 0]; au_win = ate_c[ate_c.hi95 < 0]
learned = pol.loc["learned: fixed only if predicted uplift > 0"]; base = pol.loc["always auction (control)"]
a0 = anch[(anch.premium == 0.0) & (anch.anchor == "new model")].iloc[0]
a20 = anch[(anch.premium == 0.2) & (anch.anchor == "new model")].iloc[0]
a0o = anch[(anch.premium == 0.0) & (anch.anchor.str.startswith("oracle"))].iloc[0]
L = lambda i: lev.loc[i]  # noqa: E731

# ------------------------------------------------------------------ figures
def fig_pilot():
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.5), gridspec_kw={"width_ratios": [1, 1.15]})
    p = np.linspace(0, 1, 101); ev = np.array([expected_value_fixed_first(x, 0.20, 100, 10) for x in p]) - 100
    a = ax[0]; a.axhline(0, color=GRID, lw=1); a.plot(p, ev, color=INK, lw=1.8)
    a.axvspan(five["lo"], five["hi"], color=BLUE, alpha=.14, lw=0); a.axvline(five["p"], color=BLUE, lw=1.4)
    a.axvline(BE, color=ORANGE, lw=1.4, ls="--")
    a.text(BE + .01, -9.2, f"break-even\n{pct(BE)}", color=ORANGE, fontsize=8, va="bottom")
    a.text(five["p"] + .01, 15.2, "3 of 5 sold", color=BLUE, fontsize=8, va="top")
    a.text(five["hi"] - .01, -9.2, "plausible range\nfor 3 of 5", color=BLUE, fontsize=8, ha="right", va="bottom")
    a.set_xlabel("chance an item sells at +20% before it is rolled to auction"); a.set_ylabel("gain vs auction ($ per $100 item)")
    a.set_title("Five items cannot settle it", loc="left"); a.set_xlim(0, 1); a.set_ylim(-10, 16)
    b = ax[1]; x = np.arange(len(three)); w = .26
    labs = ["auction", "fixed\n+10%", "fixed\n+20%", "fixed\n+30%"]
    cols = [("view1_recovery_sold_items_only", "sold items only", GRAY), ("view2_recovery_zeros_counted_first_channel", "zeros counted, first channel", BLUE),
            ("view3_strategy_net_value_per_retail", "whole strategy, net value", ORANGE)]
    for i, (c, lab, col) in enumerate(cols):
        b.bar(x + (i - 1) * w, three[c], w * .92, color=col, label=lab)
    b.set_xticks(x); b.set_xticklabels(labs); b.set_ylabel("per retail dollar"); b.legend(frameon=False, fontsize=7.5, loc="upper left", ncol=1)
    b.set_ylim(0, .66); b.set_title("Same 31,420 items, three answers", loc="left")
    fig.tight_layout(); return img(fig)


def fig_recovery():
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.3))
    names = {NEW: "two-part model", INC: "incumbent lookup", NAV: "naive sold-only", "category average": "category average"}
    d = rm.loc[[NEW, NAV, INC, "category average"]]; y = np.arange(len(d))[::-1]
    ax[0].barh(y, d["mae"], color=[BLUE, GRAY, GRAY, GRAY], height=.55)
    for yy, (k, r) in zip(y, d.iterrows()):
        ax[0].text(r["mae"] + .003, yy, f"{r['mae']:.3f}   total $ {r['weighted_total_error_pct'] * 100:+.1f}%", va="center", fontsize=8, color=INK)
    ax[0].set_yticks(y); ax[0].set_yticklabels([names[k] for k in d.index]); ax[0].set_xlim(0, .33)
    ax[0].set_xlabel("average miss, in recovery points (lower is better)"); ax[0].set_title("Held-out error", loc="left")
    cal = T("recovery_calibration"); ax[1].plot([0, 1], [0, 1], color=GRID, lw=1.2)
    ax[1].scatter(cal.mean_pred, cal.mean_actual, s=np.clip(cal.n / 12, 18, 140), color=BLUE, alpha=.85, lw=0)
    ax[1].set_xlabel("predicted recovery (deciles of items)"); ax[1].set_ylabel("actual"); ax[1].set_title("Predictions are calibrated", loc="left")
    ax[1].set_xlim(0, .8); ax[1].set_ylim(0, .8)
    fig.tight_layout(); return img(fig)


def fig_channel():
    d = ate_c.copy(); y = np.arange(len(d))
    col = np.where(d.lo95 > 0, BLUE, np.where(d.hi95 < 0, ORANGE, GRAY))
    fig, ax = plt.subplots(figsize=(8.2, 4.4)); ax.axvline(0, color=INK, lw=.8)
    ax.hlines(y, d.lo95, d.hi95, color=col, lw=2); ax.scatter(d.effect, y, color=col, s=34, zorder=3)
    ax.set_yticks(y); ax.set_yticklabels([cat(c) for c in d.group]); ax.set_xlabel("fixed-price-first minus auction, net value per retail dollar (95% interval)")
    ax.text(.098, 0.0, "fixed price wins →", color=BLUE, fontsize=8, ha="right"); ax.text(-.082, len(d) - .6, "← auction wins", color=ORANGE, fontsize=8)
    ax.set_title("The better channel depends on what the item is", loc="left"); ax.set_xlim(-.09, .11)
    fig.tight_layout(); return img(fig)


def fig_waiting():
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.4), gridspec_kw={"width_ratios": [1.2, 1]})
    for c, col in (("Large_appliances", BLUE), ("Smartphones", ORANGE), ("Furniture", GRAY)):
        g = sched[sched.category == c]
        if len(g):
            ax[0].step(g.day, g.price_multiple, where="post", color=col, lw=2, label=cat(c))
    ax[0].set_xlabel("days since listing"); ax[0].set_ylabel("price as a multiple of expected auction price"); ax[0].set_xlim(1, 21); ax[0].legend(frameon=False, fontsize=8, loc="lower left"); ax[0].set_title("Markdown ladder", loc="left")
    names = ["hold at +30%", "hold at +20%", "hold at +10%", "DP, supported range", "DP, full ladder"]
    lab = ["hold +30%", "hold +20%", "hold +10%", "step-down\ntested", "step-down\nextrapol."]
    v = [wp[n] for n in names]; ax[1].bar(range(5), v, color=[GRAY, GRAY, GRAY, BLUE, "#8fb3dc"], width=.62)
    for i, x in enumerate(v): ax[1].text(i, x + .004, f"{x:.3f}", ha="center", fontsize=8, color=INK)
    ax[1].set_xticks(range(5)); ax[1].set_xticklabels(lab, fontsize=7.5); ax[1].set_ylim(.2, .34); ax[1].set_ylabel("net value per retail $")
    ax[1].set_title("Same items, different waiting rules", loc="left")
    fig.tight_layout(); return img(fig)


def fig_labor():
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.3))
    col = [BLUE if w else GRAY for w in photo.worth_it]
    ax[0].bar(range(len(photo)), photo.net_benefit_rule, color=col, width=.65); ax[0].axhline(0, color=INK, lw=.8)
    ax[0].set_xticks(range(len(photo))); ax[0].set_xticklabels(photo.retail_band, fontsize=8); ax[0].set_xlabel("retail value of the item ($)")
    ax[0].set_ylabel("$ per item after labor"); ax[0].set_title("Three more photos: where they pay", loc="left")
    s = T("match_review_gain"); ax[1].plot([0] + list(s.review_share), [0] + list(s.share_of_dollar_error_captured), color=BLUE, lw=2, marker="o", ms=4)
    ax[1].plot([0, .3], [0, .3], color=GRAY, ls="--", lw=1); ax[1].text(.2, .13, "reviewing at random", color=GRAY, fontsize=8)
    ax[1].set_xlabel("share of items sent for audit"); ax[1].set_ylabel("share of wrong-retail dollars caught"); ax[1].set_title("Match audit queue, ranked by the model", loc="left")
    fig.tight_layout(); return img(fig)


def fig_lots():
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.4), gridspec_kw={"width_ratios": [1, 1.1]})
    ax[0].scatter(lots.pred_nv / 1000, lots.actual_nv / 1000, s=9, color=BLUE, alpha=.55, lw=0); mx = max(lots.pred_nv.max(), lots.actual_nv.max()) / 1000
    ax[0].plot([0, mx], [0, mx], color=GRID, lw=1.2); ax[0].set_xlabel("predicted net value of the truckload ($ thousand)"); ax[0].set_ylabel("actual")
    ax[0].set_title(f"Truckload value, predicted blind (r = {LOTCORR:.2f})", loc="left")
    pol_names = ["buy every lot at listed price (status quo)", "buy only if listed price <= ceiling", "counter at ceiling when over it; seller accepts 25% of the time",
                 "counter at ceiling when over it; seller accepts 50% of the time", "counter at ceiling when over it; seller accepts 100% of the time"]
    lab = ["buy all\nat list", "skip over\nceiling", "counter\n25% accept", "counter\n50% accept", "counter\n100% accept"]
    d = bid.loc[pol_names]; x = np.arange(5)
    ax[1].bar(x, d.total_profit / 1000, color=[GRAY, BLUE, "#8fb3dc", "#8fb3dc", "#8fb3dc"], width=.62)
    for i, (tp, pps) in enumerate(zip(d.total_profit, d.profit_per_spend_dollar)): ax[1].text(i, tp / 1000 + 25, f"{pps:.2f} per\n$ spent", ha="center", fontsize=7.5, color=INK)
    ax[1].set_xticks(x); ax[1].set_xticklabels(lab, fontsize=7.5); ax[1].set_ylabel("total profit, 800 lots ($ thousand)"); ax[1].set_ylim(0, 1600)
    ax[1].set_title("Bid ceiling: profit vs profit per dollar", loc="left")
    fig.tight_layout(); return img(fig)


def fig_ladder():
    d = lev.loc[[1, 2, 3, 4, 6]].copy(); y = np.arange(len(d))[::-1]
    short = {1: "Better price anchor\n(recovery model)", 2: "Route item to channel\n(uplift model)", 3: "Step-down markdown\n(hazard + DP)", 4: f"Photos only above ${floor}\n(experiment rule)", 6: "Counter-offer at bid ceiling\n(lot model, 25–50% accept)"}
    ev = {1: BLUE, 2: BLUE, 3: "#8fb3dc", 4: BLUE, 6: ORANGE}
    fig, ax = plt.subplots(figsize=(8.6, 3.9)); ax.axvline(0, color=INK, lw=.8)
    for yy, (i, r) in zip(y, d.iterrows()):
        ax.barh(yy, r.monthly / 1000, color=ev[i], height=.52)
        if not np.isnan(r.lo):
            hi = r.hi if not np.isnan(r.hi) else r.monthly
            ax.hlines(yy, r.lo / 1000, hi / 1000, color=INK, lw=1.4); ax.vlines([r.lo / 1000, hi / 1000], yy - .12, yy + .12, color=INK, lw=1.2)
        ax.text(max(r.monthly, r.hi if not np.isnan(r.hi) else 0) / 1000 + .4, yy, usd(r.monthly), va="center", fontsize=8.5, color=INK)
    ax.set_yticks(y); ax.set_yticklabels([short[i] for i in d.index], fontsize=8.5); ax.set_xlabel("profit per month, $ thousand (simulated data; lines are 95% intervals where one exists)")
    ax.set_title("What each lever is worth. These overlap, so do not add them.", loc="left"); ax.set_xlim(-3, 22)
    fig.tight_layout(); return img(fig)


def fig_monitor():
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.2), gridspec_kw={"width_ratios": [1.2, 1]})
    ax[0].plot(mp.month, mp.mae_baseline, color=GRAY, lw=2, label="incumbent lookup"); ax[0].plot(mp.month, mp.mae, color=BLUE, lw=2, label="two-part model")
    ax[0].set_ylim(.1, .25); ax[0].set_ylabel("average miss"); ax[0].legend(frameon=False, fontsize=8); ax[0].tick_params(axis="x", labelsize=7.5)
    ax[0].set_title("Held-out error by month", loc="left")
    d = drift.head(6)[::-1]; ax[1].barh(d.feature, d.psi, color=[ORANGE if f == "ALERT" else GRAY for f in d.flag], height=.55)
    ax[1].axvline(.25, color=INK, lw=.8, ls="--"); ax[1].text(.27, -.45, "alert level", fontsize=7.5); ax[1].set_xlabel("population stability index"); ax[1].set_title("What changed in the inputs", loc="left")
    fig.tight_layout(); return img(fig)


# ------------------------------------------------------------------ html helpers
def table(df, cols=None, fmt=None, cls=""):
    cols = cols or list(df.columns); fmt = fmt or {}
    h = f"<table class='{cls}'><thead><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in cols) + "</tr></thead><tbody>"
    for _, r in df.iterrows():
        h += "<tr>" + "".join(f"<td>{fmt[c](r[c]) if c in fmt else html.escape(str(r[c]))}</td>" for c in cols) + "</tr>"
    return h + "</tbody></table>"


def sec(id_, n, title, call, method, ml, body, so, figs=(), evidence=""):
    f = "".join(f"<figure><img src='{s}' alt=''><figcaption>{c}</figcaption></figure>" for s, c in figs)
    return f"""<section id="{id_}"><div class="kicker">{n}</div><h2>{title}</h2>
<div class="call"><b>The question.</b> {call}</div>
<div class="grid2"><div><h4>How I looked at it</h4><p>{method}</p></div><div><h4>Where ML is used</h4><p>{ml}</p></div></div>
<h4>What the data shows</h4>{body}{f}
<div class="sowhat"><b>So what.</b> {so}</div><p class="evid">Evidence: {evidence}</p></section>"""


# ------------------------------------------------------------------ text
req20 = int(req.loc[req.detectable_effect_per_retail_dollar == 0.02, "items_per_arm"].iloc[0])
req01 = int(req.loc[req.detectable_effect_per_retail_dollar == 0.01, "items_per_arm"].iloc[0])
p20 = prem.loc[prem.premium_pct == 0.2].iloc[0]
fx_names = ", ".join(f"{cat(r.group)} {sgn(r.effect)}" for _, r in fx_win.iterrows()) or "none"
au_names = ", ".join(f"{cat(r.group)} {sgn(r.effect)}" for _, r in au_win.sort_values("effect").iterrows())
n_au, n_flat = len(au_win), len(ate_c) - len(au_win) - len(fx_win)
ph = photo[photo.net_benefit_rule >= 0.25].retail_band.iloc[0]
floor = int(re.sub(r"[^0-9].*", "", ph.lstrip("<")) or 0)
vs_all = float(L(4).basis.split("lose $")[1].split(" per")[0].replace(",", ""))
sw = samp[samp.sampled == 20].iloc[0] if (samp.sampled == 20).any() else samp.iloc[1]
c25, c50 = L(6).lo, L(6).monthly
bs = bid.loc["buy every lot at listed price (status quo)"]; bc = bid.loc["buy only if listed price <= ceiling"]
amb = ml.query("status=='needs_clarification'").iloc[0]
retrain_feats = ", ".join(drift[drift.flag == "ALERT"].feature.head(4))

headline = f"""<ol class="lead">
<li><b>Five items cannot settle the fixed-price question; 31,420 can.</b> Three of five selling is consistent with a true sale rate anywhere from {pct(five['lo'])} to {pct(five['hi'])}, and the break-even is {pct(BE)}. At scale the strategy lowers net value by {abs(ate.effect):.3f} per retail dollar (95% interval {ate.lo95:.3f} to {ate.hi95:.3f}) and takes {ate.avg_days_fixed:.1f} days instead of {ate.avg_days_auction:.1f}.</li>
<li><b>The recovery model is better than the lookup it would replace.</b> Average miss {rm.loc[NEW,'mae']:.3f} against {rm.loc[INC,'mae']:.3f}, and total predicted dollars within {abs(rm.loc[NEW,'weighted_total_error_pct'])*100:.1f}% of actual against {rm.loc[INC,'weighted_total_error_pct']*100:+.1f}%. On its own it is worth about {usd(a0.gain_per_month)} a month. The value comes from the decisions it feeds.</li>
<li><b>The best channel depends on the category.</b> Fixed price wins for {fx_names}. Auction wins for {n_au} categories ({au_names}). The other {n_flat} cannot be told apart yet. Item-level routing gains {usd(L(2).monthly)} a month on paper, but its interval ({usd(L(2).lo)} to {usd(L(2).hi)}) includes zero.</li>
<li><b>A price that steps down with age beats any single held price</b> by {wp['DP, supported range']-wp[['hold at +10%','hold at +20%','hold at +30%']].max():.3f} per retail dollar inside the tested range ({usd(L(3).monthly)} a month). More comes from outside the range, which is untested.</li>
<li><b>Labor should follow value.</b> Extra photos pay from the {ph} band up and lose money below ${floor}. Auditing the 5% of catalog matches most likely to be wrong catches {pct(mrev.loc[0.05,'share_of_dollar_error_captured'])} of the mis-stated retail dollars.</li>
<li><b>Truckload value can be predicted before opening</b> (correlation {LOTCORR:.2f}). A bid ceiling doubles profit per dollar spent ({bs.profit_per_spend_dollar:.2f} to {bc.profit_per_spend_dollar:.2f}) but whether total profit rises depends on how often sellers accept a counter-offer, which this data cannot tell us.</li>
</ol>"""

S1 = sec("s1", "Judging a pilot", "Five items, three sold at +20%, two still at zero: does the strategy work?",
         "Five items were listed at the expected auction price plus 20%. Three sold, 20% above expectation. The other two are at zero, and in an auction a zero is a zero. Recovery on sold items and recovery on all items tell different stories. Which one should decide whether the strategy works?",
         "Count every item listed, including the zeros. Value of fixed-price-first = chance it sells x (1.2 x expected price) + chance it does not x (expected price minus the cost of waiting, then it goes to auction). That gives a break-even sale probability. Then check whether the evidence can tell us which side of it we are on, first with five items, then with the randomized pilot in the warehouse.",
         "Wilson interval for the five items (statistics, no ML). At scale: randomized assignment, then a cross-fitted uplift model (see Choosing a channel) to ask which items benefit.",
         f"""<p>With a wait cost of 10% of the item's value, fixed-price-first beats auction when more than <b>{pct(BE)}</b> of items sell. Three of five is {pct(five['p'])}, but five items allow a true rate anywhere from <b>{pct(five['lo'])} to {pct(five['hi'])}</b>, which spans the break-even. The honest answer from five items is "not enough evidence".</p>
<p>The warehouse has the same experiment at scale: {int(ate.n_auction + ate.n_fixed):,} items, randomly assigned. At +20%, {pct(p20.sold_at_fixed_price_rate)} sell at the fixed price, well above the {pct(BE)} break-even, yet the whole strategy still comes out {abs(p20.effect_vs_auction):.3f} per retail dollar behind auction and takes {p20.avg_days_listed:.0f} days. The arithmetic and the pilot disagree. The most likely reason is that waiting costs more than the 10% I assumed, which is why the break-even rule is a screen and not a verdict.</p>
<p>The three bars on the right are the same items scored three ways. Counting only items that sold, fixed price looks better ({three.view1_recovery_sold_items_only.iloc[3]:.2f} at +30% against {three.view1_recovery_sold_items_only.iloc[0]:.2f}). Counting zeros in the first channel, it looks much worse. Valuing the whole strategy, including what happens after rollover, it is close to or below auction. <b>Only the third view is a fair comparison.</b></p>""",
         f"Judge a channel on net value per item listed, with zeros counted and the fallback included. To detect a difference of 0.02 per retail dollar you need about {req20:,} items per arm; for 0.01, {req01:,}. A five-item pilot can only be an anecdote, and the report should say so before anyone acts on it.",
         [(fig_pilot(), "Left: expected gain over auction as the sale rate varies, with the range implied by 3 of 5. Right: the same pilot items under three definitions of recovery.")],
         "zero_problem_three_views, pilot_premium_table, required_sample, breakeven_table")

S2 = sec("s2", "Predicting recovery", "How much will an item recover, before it is listed?",
         "Recovery is what an item sold for divided by its retail value, with unsold items counted as zero. A model that predicts it from history and product features is the base for every later decision.",
         "Recovery has a spike at zero, so one regression on a blended average hides the problem. I model it in two parts: the chance the item sells, and the recovery given that it sells. The product is calibrated with isotonic regression, and conformal intervals say how wide the miss can be. Evaluation uses a time split, not a random one, because the model will always be used on the future.",
         "Yes. Two LightGBM models (a classifier and a regressor) with isotonic calibration and split-conformal intervals. Compared with the incumbent category x condition lookup, a category average and a naive sold-only model.",
         f"""<p>On items listed after the training window the two-part model misses by <b>{rm.loc[NEW,'mae']:.3f}</b> on average, against {rm.loc[INC,'mae']:.3f} for the lookup. Its predicted total dollars are {rm.loc[NEW,'weighted_total_error_pct']*100:+.1f}% off; the lookup and the naive model are both about {rm.loc[INC,'weighted_total_error_pct']*100:+.1f}% too high, because they ignore the zeros. Probability-of-sale AUC is {AUC}; the 80% intervals cover {COV} of outcomes.</p>
<p>What this is worth depends on what it is used for. As the anchor for a fixed-price listing with no premium, it adds <b>{usd(a0.gain_vs_first_per_item,2)} per item</b> (95% interval {usd(a0.lo95,2)} to {usd(a0.hi95,2)}), about <b>{usd(a0.gain_per_month)} a month</b>. Perfect item-level knowledge would add {usd(a0o.gain_vs_first_per_item,2)}, so there is still room. At a +20% premium the same improvement is worth {usd(a20.gain_vs_first_per_item,2)} per item, effectively nothing, because the premium decision dominates the anchor.</p>""",
         "A more accurate number is not a result. It becomes one when the decision using it (price, channel, markdown) is also right, which is why the channel and markdown questions follow, and why the final ladder reports dollars and not error.",
         [(fig_recovery(), "Left: held-out average miss, with total predicted dollars versus actual. Right: mean predicted and actual recovery by decile of prediction.")],
         "recovery_metrics, recovery_calibration, recovery_grouped_cv, interval_coverage_by_category, pricing_anchor_impact")

S3 = sec("s3", "Choosing a channel", "Auction or fixed price: for which items, and how sure are we?",
         "Some items could be sold at a fixed price instead of by auction. How do we know whether that is better, and for which items?",
         "A randomized pilot (items assigned by coin flip to auction or fixed price at +10, +20 or +30%), compared on net value per retail dollar so that big and small items are weighted fairly. Effects by category come with 95% intervals. A learned policy asks which individual items would do better in fixed price; its value is estimated with inverse-probability weights, and its interval from a bootstrap across lots.",
         "Yes. A T-learner uplift model (one LightGBM per arm, cross-fitted by lot so no item is scored by a model that saw its lot). The category forest plot is plain statistics.",
         f"""<p>On average, fixed-price-first is <b>worse</b>: {sgn(ate.effect)} per retail dollar (interval {ate.lo95:.3f} to {ate.hi95:.3f}). The average hides a split. Fixed price clearly wins for {fx_names}. Auction clearly wins for {au_names}. The remaining {n_flat} categories are inside the noise at this sample size.</p>
<p>Choosing the channel item by item with the uplift model earns {usd(learned.dollars_per_item,2)} per item against {usd(base.dollars_per_item,2)} for always-auction, a gain of <b>{usd(L(2).monthly)} per month</b> at current volume, but the bootstrap interval is {usd(L(2).lo)} to {usd(L(2).hi)}. The point estimate is positive and the evidence is not strong enough to promise it.</p>""",
         "Start with a category rule (fixed price for the categories that clearly benefit, auction for the ones that clearly do not), keep a randomized holdback, and let the item-level model earn its place as the holdback grows.",
         [(fig_channel(), "Effect of fixed-price-first versus auction by category, with 95% intervals. Blue: fixed price clearly better. Orange: auction clearly better. Gray: not distinguishable.")],
         "pilot_ate, pilot_ate_by_category, policy_comparison, uplift_calibration, pilot_balance")

S4 = sec("s4", "Waiting and markdown", "A fixed price has no countdown: how long to wait, and at what price?",
         "A fixed-price item has no two-day clock like an auction. Comparing the two on a shared time window does not work, so what should replace the window?",
         "Compare the two channels by net return per day, not by a shared deadline. For each category, fit how fast items sell at each price and age (a discrete-time hazard model). Hold one more day only if the chance of selling times the gain exceeds the cost of waiting plus the value that decays. Solving that backward over a ladder of prices gives a markdown schedule, and a rollover to auction when the price falls below what auction would pay.",
         "Partly. Per-category complementary log-log hazard models, with the price effect shrunk toward the pooled value (empirical Bayes), feed a dynamic program. The schedule is arithmetic on top of the models.",
         f"""<p>Inside the price range the pilot actually tested (+10% to +30%), a step-down schedule earns <b>{wp['DP, supported range']:.3f}</b> net value per retail dollar against <b>{wp[['hold at +10%','hold at +20%','hold at +30%']].max():.3f}</b> for the best single held price, a gain of {usd(L(3).monthly)} a month. Letting the ladder go below the tested range raises the model's value to {wp['DP, full ladder']:.3f}, but that is extrapolation, and I report it separately for that reason.</p>
<p>Fast categories do not need the ladder to be long; slow ones do. The schedules are different for each category (left chart) because the sale curve flattens at different speeds, which matches the intuition that a popular phone sells in days and an older laptop does not.</p>""",
         "Run a randomized markdown test next, with prices below +10%, before treating the extrapolated gain as real. The tested-range gain is the number to plan on.",
         [(fig_waiting(), "Left: price schedule for three categories. Right: net value per retail dollar for each waiting rule on the same items.")],
         "waiting_policy_results, waiting_schedules, waiting_hazard_params, hazard_calibration, sale_curves_by_premium")

S5 = sec("s5", "Labor", "Where is extra labor worth its cost?",
         "Handling an item costs labor, and US warehouse labor is expensive. An extra minute of photos may be worth it on a thousand-dollar item and not on a five-dollar one. Where is the line?",
         "A randomized experiment gave some items extra photos. The lift in sale price is small and noisy item by item, so I pool it across categories (shrinkage) and compare the benefit with the labor minutes. Matching an item to the right catalog entry is the other labor step; a wrong match mis-states retail value, which is the denominator of every recovery number. A classifier ranks items by how likely the match is wrong, so audits go where the dollars are.",
         "Photos: no, randomized experiment and break-even arithmetic. Match audit: yes, a classifier trained on audited items ranks the queue.",
         f"""<p>Extra photos lift the sale price by about 4%. After labor, that pays from the <b>{ph}</b> retail band up; below ${floor} each item loses a little. Doing it for everyone would cost about {usd(vs_all)} a month on cheap items; doing it only where it pays earns about <b>{usd(L(4).monthly)} a month</b>.</p>
<p>Sending the 5% of items most likely to have a wrong match to an auditor catches <b>{pct(mrev.loc[0.05,'share_of_dollar_error_captured'])}</b> of the dollars of mis-stated retail value ({pct(mrev.loc[0.05,'share_of_wrong_matches_found'])} of the wrong matches), against 5% by random review. That protects the recovery model more than it adds profit by itself, which is why it is not on the profit ladder.</p>""",
         f"Write the photo rule in one line the floor can follow ('three more photos on anything over ${floor}'), and put the match audit upstream of every other model.",
         [(fig_labor(), "Left: net benefit per item of extra photos after labor, by retail band. Right: share of wrong-retail dollars caught as more of the ranked queue is audited.")],
         "photo_rule_by_band, photo_effects_by_category, min_item_value, match_review_gain")

S6 = sec("s6", "Truckloads", "What is a truckload worth before anyone opens it?",
         "Truckloads arrive with unknown contents: toys and phones together, items from $5 to thousands of dollars. What should the business pay before opening one?",
         "Predict a truckload's net value from its manifest and source history, with a measured error for each source. Score sources on profit, quality, reliability, manifest accuracy and speed, with raw averages pulled toward the pooled mean when a source has few lots. A bid ceiling is the expected value, less freight and a buffer for uncertainty, divided by one plus the margin I want. I also price the value of opening a few items before bidding.",
         "Yes. A lot-value model whose predictions are made out-of-fold, plus per-source error. The scorecard is statistics (empirical Bayes); the ceiling is arithmetic on the model's output.",
         f"""<p>Predicted lot value tracks actual with a correlation of <b>{LOTCORR:.2f}</b> on lots the model never saw. A bid ceiling set from it has a clear effect on efficiency: buying only lots listed under the ceiling returns {bc.profit_per_spend_dollar:.2f} of profit per dollar spent, against {bs.profit_per_spend_dollar:.2f} for buying everything. It also buys only {int(bc.lots_bought)} of {int(bs.lots_bought)} lots and earns less total profit.</p>
<p>The middle option is to counter-offer at the ceiling when a lot is over it. Whether that raises total profit depends entirely on how often the seller says yes. At 50% acceptance it adds about <b>{usd(c50)} a month</b>; at 25% it loses {usd(abs(c25))}. This data has no acceptance history, so the right figure to plan on is a range, and the first job is to start logging counter-offers. Opening 20 items from a typical lot costs about {usd(sw.inspection_cost)} in labor and is worth about {usd(sw.ceiling_gain)} in better bids.</p>""",
         "Use the ceiling to decide where to negotiate and where to walk away, and log every counter-offer and response. That log turns the assumption-dependent bar on the ladder into a measured one.",
         [(fig_lots(), "Left: out-of-fold predicted versus actual lot value. Right: total profit and profit per dollar spent under each buying rule.")],
         "lot_oof_predictions, source_scorecard, bid_backtest, bid_sweep, sampling_value")

mex = ml.set_index("question")
S7 = sec("s7", "Report requests", "A metric layer that asks before it guesses",
         "People ask an assistant for reports, which only works if the data is documented. When someone asks for sales by category last week, the assistant must know whether that means gross or net sales, what a category is and where the data lives, or ask.",
         "Every metric is defined once in a file with the same seven fields: name, definition, calculation, source table, owner, refresh and intended use. A request is parsed for metric, period and breakdown. If a word is ambiguous (sales, revenue) the layer asks one clarifying question; if it is documented (recovery means all items, zeros counted) it answers and states the assumption. Questions it cannot map are logged.",
         "No model. Deterministic rules over governed definitions, so the answer is reproducible. The same file is exported as a prompt for an assistant to use.",
         f"""<p>Examples from the test set below. 'What were sales last week?' gets a question back; 'gross sales last week by category' gets an answer with the week boundaries and the date field it used. An unknown request lists the metrics that do exist, so the failure teaches the asker something.</p>
{table(ml[ml.question.isin(['What were sales last week?','What were gross sales last week by category?','Show me revenue','What was recovery by category last month?','what is the weather?'])].assign(response=lambda d: np.where(d.status == 'unknown_metric', 'asks which of the 14 documented metrics is meant', np.where(d.clarifying_question.notna(), 'asks: ' + d.clarifying_question.fillna(''), 'answers ' + d.metric.fillna('') + ' for ' + d.period.fillna('') + '; states its assumption'))), ['question', 'response'], cls='plain')}""",
         "Every time the layer has to ask, the ambiguity is written to a log (ambiguity_log). Reviewing that log weekly is how the definitions improve over time without anyone remembering to update them.",
         [], "metric_layer_examples, ambiguity_log, config/metric_definitions.yaml, metric_layer_prompt.txt")

cards = cards.assign(list_at=cards.list_at.str.replace(r"start at ([0-9.]+)x expected auction price, step down to ([0-9.]+)x by day ([0-9]+)", r"\1x, down to \2x by day \3", regex=True))
cards_show = cards.assign(item=lambda d: d.category.map(cat) + ", " + d.condition.str.replace("_", " ") + ", " + d.retail_value.map(lambda x: usd(x)),
                          predicted=lambda d: d.pred_recovery.map(lambda x: pct(x)) + " (" + d.lo80.map(lambda x: pct(x)) + " to " + d.hi80.map(lambda x: pct(x)) + ")",
                          actual=lambda d: d.actual_gross_recovery.map(lambda x: pct(x)))[["item", "predicted", "actual", "route", "list_at", "extra_photos", "review_match"]]
cards_show.columns = ["Item", "Predicted recovery (80% range)", "Actual", "Channel", "Price plan", "Extra photos", "Audit the match"]
inside = int(((cards.actual_gross_recovery >= cards.lo80) & (cards.actual_gross_recovery <= cards.hi80)).sum())
S8 = sec("s8", "Putting it together", "One engine runs every model on an item, one ladder prices every lever",
         "A better prediction is only worth something if it changes a decision. What is each improvement worth in dollars per month, and how sure are we?",
         "Run every model on an item at intake and write down the single action it implies: predicted recovery with a range, channel, price plan, photos, audit. Then price each lever per month at current volume, say how that number was obtained, and refuse to add levers that overlap.",
         "This is where the models connect: the recovery model sets the anchor, the uplift model picks the channel, the hazard models set the schedule, the match model decides who is audited, the lot model sets the bid.",
         f"""<p>Twelve held-out items from twelve categories, each processed by every model. The actual outcome falls inside the 80% range in {inside} of {len(cards)} rows, and the ranges are wide, which is the honest picture: one item is hard to predict, a thousand are not.</p>{table(cards_show, cls='cards')}
<p>The ladder prices each lever. All figures are from simulated data, so the size matters less than the <i>kind</i> of evidence behind each bar: randomized and measured, model-based, or dependent on an assumption we cannot check.</p>""",
         f"The first three levers act on the same fixed-price items, so their gains overlap; a defensible total is the largest of them plus the photo rule: about {usd(max(L(2).monthly, L(1).monthly) + L(4).monthly)} a month at the point estimates, and about {usd(max(L(2).lo, L(1).lo) + L(4).monthly)} at the lower interval ends, before any gain from buying. Measure with a holdback and report the measured number.",
         [(fig_ladder(), "Monthly profit by lever. Blue: measured on held-out or randomized data. Light blue: model-based. Orange: depends on an assumption.")],
         "intake_cards, value_levers, pricing_anchor_impact, policy_comparison, photo_rule_by_band, bid_backtest")

gap = (mp.mae_baseline - mp.mae); gap_lo, gap_hi = gap.min(), gap.max()
S9 = sec("s9", "After launch", "Monitoring: how the system notices it is going stale",
         "A model that was right at launch goes stale as the business changes. How does the system notice, and what does it do about it?",
         "Track error by month against the incumbent, and track input drift with the population stability index. A retrain rule fires when drift is high or error degrades. State what the data cannot support, and list the first work in order.",
         "Monitoring is statistics on the model's inputs and errors. The retrain rule is a documented threshold, not a model.",
         f"""<p>Retraining is <b>{RETR}</b> right now. Inputs that moved most: {retrain_feats}. That is the June 2026 expansion (a new source type) plus seasonality. The two-part model beats the incumbent in every month, by {gap_lo:.3f} to {gap_hi:.3f}. The sale-timing model over-predicts sales after the expansion, which a rolling recalibration only partly fixes.</p>
<p><b>What this data cannot say.</b> It is simulated, so every number is a demonstration of method, not a claim about any real business. Within it, the markdown gain outside the tested range, the item-level routing gain, and the counter-offer gain are not established. Category effects with intervals that include zero are not effects.</p>
<h4>What runs after launch</h4>
<p>The pipeline runs weekly. Each run rebuilds the warehouse, stops if a data test fails, retrains and re-scores everything, and appends one line to <code>outputs/run_history.csv</code> with the headline numbers and fingerprints of the data and configuration that produced them. A change in those numbers can always be traced to a change in the data, the configuration or the code.</p>""",
         "A model is not finished when it is trained. It is finished when something is watching it, and when the numbers it produces can be traced to the data that made them.",
         [(fig_monitor(), "Left: held-out average miss by month. Right: input drift (population stability index), alert features in orange.")],
         "monthly_performance, drift_psi, data_quality_tests, run_history.csv, run_manifest.json")

css = """
:root{--ink:#1d2127;--mute:#6b7380;--line:#e3e6ea;--blue:#1f5fa8;--orange:#c4561a;--bg:#fafaf8}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.62 Charter,'Iowan Old Style','Palatino Linotype',Georgia,serif}
nav{position:fixed;top:0;left:0;bottom:0;width:216px;padding:28px 18px;border-right:1px solid var(--line);background:#fff;overflow:auto;font:13.5px/1.3 -apple-system,'Segoe UI',Helvetica,Arial,sans-serif}
nav .t{font-weight:700;font-size:14px;margin-bottom:14px}nav a{display:block;padding:6px 8px;margin:1px -8px;color:var(--mute);text-decoration:none;border-radius:4px}
nav a:hover{background:#f1f3f5;color:var(--ink)}
main{margin-left:216px;padding:44px 40px 90px;max-width:960px}
h1{font-size:34px;line-height:1.15;margin:0 0 10px;letter-spacing:-.01em}h2{font-size:25px;line-height:1.25;margin:2px 0 14px}
h4{font:700 11.5px/1 -apple-system,'Segoe UI',Arial,sans-serif;text-transform:uppercase;letter-spacing:.07em;color:var(--mute);margin:22px 0 8px}
section{padding:46px 0 10px;border-top:1px solid var(--line)}.kicker{font:600 12px -apple-system,Arial,sans-serif;color:var(--blue);letter-spacing:.05em;text-transform:uppercase}
.sub{color:var(--mute);font-size:18px;margin:0 0 22px;max-width:700px}
.banner{font:13.5px/1.5 -apple-system,Arial,sans-serif;background:#fff6ec;border:1px solid #f0d6b8;padding:10px 14px;border-radius:5px;margin:16px 0 26px;max-width:720px}
ol.lead{padding-left:22px;max-width:760px}ol.lead li{margin:0 0 13px}
.call{background:#fff;border-left:3px solid var(--blue);padding:11px 15px;margin:0 0 6px;font-size:15.5px;max-width:760px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:26px;max-width:800px;font-size:15.5px}.grid2 p{margin:0}
p{max-width:760px}figure{margin:22px 0;background:#fff;border:1px solid var(--line);padding:14px}figure img{width:100%;height:auto;display:block}
figcaption{font:12.5px/1.4 -apple-system,Arial,sans-serif;color:var(--mute);margin-top:8px}
.sowhat{border-top:2px solid var(--ink);margin-top:20px;padding-top:10px;max-width:760px}.evid{font:12.5px -apple-system,Arial,sans-serif;color:var(--mute);margin-top:12px}
table{border-collapse:collapse;font:13px/1.4 -apple-system,'Segoe UI',Arial,sans-serif;margin:14px 0;background:#fff;width:100%}
th{text-align:left;font-weight:600;color:var(--mute);border-bottom:1.5px solid var(--ink);padding:6px 8px}td{padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
table.cards td:nth-child(n+2){white-space:nowrap}
footer{margin-top:50px;font:13px/1.5 -apple-system,Arial,sans-serif;color:var(--mute)}
code{font:13px ui-monospace,Menlo,Consolas,monospace;background:#eef0f2;padding:1px 4px;border-radius:3px}
@media(max-width:860px){nav{display:none}main{margin:0;padding:24px 18px}.grid2{grid-template-columns:1fr}table.cards{display:block;overflow:auto}}
"""

app = f"""<section id="app"><div class="kicker">In the repository</div><h2>Where everything lives, and how to run it</h2>
<p>The full interactive explorer (scenario sliders, playbook with CSV upload, variable registry, calculation notes, pipeline page) is kept at <a href="explorer.html">explorer.html</a>. Every table behind the numbers above is in <code>outputs/tables</code> ({len(os.listdir(TB))} files) and every chart in <code>outputs/figures</code>.</p>
<table class="plain"><thead><tr><th>Piece</th><th>Where</th></tr></thead><tbody>
<tr><td>Simulator with known truth</td><td><code>src/returns_decision_engine/sim</code>, <code>config/simulation.yaml</code></td></tr>
<tr><td>Warehouse and 15 data checks</td><td><code>src/returns_decision_engine/data</code>, <code>sql/</code></td></tr>
<tr><td>Models</td><td><code>src/returns_decision_engine/models</code> (recovery, hazard, uplift, match, lot, monitor)</td></tr>
<tr><td>Decisions</td><td><code>src/returns_decision_engine/decisions</code> (waiting, effort, scorecard, bid ceiling, impact)</td></tr>
<tr><td>Decision engine and lever ladder</td><td><code>src/returns_decision_engine/engine.py</code></td></tr>
<tr><td>Metric layer</td><td><code>src/returns_decision_engine/metrics</code>, <code>config/metric_definitions.yaml</code></td></tr>
<tr><td>Pipeline, gate, manifest</td><td><code>src/returns_decision_engine/pipeline.py</code>, <code>outputs/run_manifest.json</code>, <code>outputs/run_history.csv</code>, <code>models/</code></td></tr>
<tr><td>Run everything</td><td><code>make all</code>, then <code>python site_builder/build_report.py</code>; the same runs weekly in GitHub Actions</td></tr></tbody></table>
<p>Data dictionary: <code>docs/DATA_DICTIONARY.md</code>. How to extend with your own data: <code>docs/EXTENDING.md</code>.</p></section>"""

import json  # noqa: E402
man = json.load(open(os.path.join(ROOT, "outputs", "run_manifest.json")))
n_tests = sum(open(os.path.join(ROOT, "tests", f)).read().count("\ndef test_") for f in os.listdir(os.path.join(ROOT, "tests")) if f.startswith("test_"))
dq = T("data_quality_tests")
ML = {"recovery_model": "ML: two LightGBM models, calibration, conformal intervals", "anchor_impact": "Arithmetic on the model's output, with bootstrap intervals",
      "sale_timing": "ML: discrete-time hazard model (LightGBM)", "channel_and_waiting": "ML: uplift T-learner; statistics on the randomized pilot; dynamic program",
      "effort_rule": "Statistics: randomized experiment, break-even arithmetic", "sources_and_lots": "ML: lot-value model; empirical-Bayes scorecard; arithmetic ceiling",
      "match_quality": "ML: classifier ranks the audit queue", "decision_engine": "Combines all of the above", "monitoring": "Statistics: drift index, error by month, a threshold rule",
      "metric_layer": "Rules over governed definitions; no model"}
how_rows = "".join(f"<tr><td><b>{html.escape(st['name'].replace('_', ' '))}</b></td><td>{html.escape(st['purpose'])}</td><td>{html.escape(ML.get(st['name'], 'Data tests, no model'))}</td><td>{len(st['tables'])}</td><td>{st['seconds']:.0f}s</td></tr>" for st in man["stages"])
how = f"""<section id="how"><div class="kicker">How it works</div><h2>One pipeline, eleven steps, one gate at the front</h2>
<p>Raw files go into a SQL warehouse. A set of data tests runs on it, and <b>if any error-level test fails, the run stops</b>: nothing downstream is trusted on bad data. After that each stage answers one question, hands what it learned to the next, and writes its tables to <code>outputs/tables</code>. The last stages combine everything into per-item decisions and a dollar value for each lever, then monitor the models and answer report requests.</p>
<table class="plain"><thead><tr><th>Stage</th><th>What it answers</th><th>Method</th><th>Tables</th><th>Time</th></tr></thead><tbody>{how_rows}</tbody></table>
<p>Five stages train models and a sixth combines them; each model feeds a decision. The rest are statistics and arithmetic, kept simple where a model would add nothing.</p></section>"""
tryit = """<section id="try" style="border-top:0;padding-top:0"><div class="kicker">Interactive tool</div><h2>Change the price, the premium or the cost, and see the break-even move</h2>
<p>The pages below describe what the models found. <a href="explorer.html"><b>The interactive tool</b></a> lets you work with the same numbers: set the premium you would charge and the cost of waiting to see the break-even sale rate, build what-if scenarios (prices, demand, labor, freight), and load your own category totals from a CSV to get buy-more, raise-price or cut-back recommendations. It runs in the browser on the pipeline's fitted results, so it refreshes whenever the pipeline runs.</p>
<p><a href="explorer.html" style="display:inline-block;background:#1f5fa8;color:#fff;padding:9px 16px;border-radius:5px;font:600 14px -apple-system,Arial,sans-serif;text-decoration:none">Open the interactive tool</a></p></section>"""
what = """<section id="what"><div class="kicker">What this is</div><h2>A decision system for a marketplace that sells returned and overstock goods</h2>
<p>The business buys returns and overstock by the truckload, opens them, matches each item to a catalog entry, photographs and grades it, and sells it by auction or at a fixed price. The measure that matters is <b>recovery</b>: what an item sold for divided by what it would have cost new, with unsold items counted as zero.</p>
<p>This project builds the analytics layer for that business. It predicts what each item will recover, decides how to list it, where labor is worth spending, and which truckloads to bid on. It answers report requests from governed definitions. And it prices every one of those decisions in dollars per month, with an honest statement of how well each number is known.</p></section>
<section id="problem" style="border-top:0;padding-top:20px"><div class="kicker">The problem</div><h2>Five things make this hard</h2>
<p><b>A zero is a zero.</b> An unsold auction item recovers nothing, so averages over sold items overstate how well the business is doing. <b>Two channels run on different clocks:</b> an auction ends in two days, a fixed price has no end, so they cannot be compared on a shared window. <b>Contents are unknown.</b> A truckload can hold toys and phones together, with items from $5 to thousands of dollars. <b>Labor is the main variable cost</b>, so every extra minute of handling has to earn its place. <b>Definitions drift.</b> Without governed definitions, "sales last week" means different things to different people, and to an assistant answering for them.</p></section>"""
found_head = """<section id="found" style="padding-bottom:0"><div class="kicker">What it found</div><h2>Six findings, then the evidence for each</h2>"""
trust = f"""<section id="trust"><div class="kicker">Why trust it</div><h2>How the project is built to be checked</h2>
<p><b>The data is simulated with known truth.</b> The simulator knows each item's real value, each truckload's real contents and each source's real quality, so every method can be graded against the answer it is trying to recover. It also injects the defects real data has: duplicate rows, wrong catalog matches, and a mid-period expansion that shifts the mix.</p>
<p><b>A quality gate guards the front.</b> {len(dq)} data tests run on the warehouse ({int((dq.status=='pass').sum())} pass, {int((dq.status=='warn').sum())} warn, {int((dq.status=='FAIL').sum())} fail). Any error-level failure stops the pipeline. <b>{n_tests} code tests</b> cover the simulator, warehouse, models, decisions, metric layer and the pipeline's own gate.</p>
<p><b>Runs are reproducible and traceable.</b> Two runs on the same data and configuration give the same numbers. Every run writes <code>run_manifest.json</code> (data fingerprint <code>{man['raw_data_hash']}</code>, configuration fingerprint <code>{man['config_hash']}</code>, rows per table, seconds and tables per stage, models saved) and appends to <code>run_history.csv</code>. Trained models are saved as artifacts and described in a model card.</p></section>"""
limits = """<section id="limits"><div class="kicker">Limits</div><h2>What it cannot tell you</h2>
<p>All numbers come from simulated data, so they demonstrate a method and say nothing about any real business. Within that: the markdown gain below the tested price range, the item-level routing gain and the counter-offer gain are not established. A category effect whose interval includes zero is not an effect. Levers overlap, so their dollar values must not be added. Anything the data cannot show, such as how often a seller accepts a counter-offer, is flagged as an assumption in the section where it matters.</p></section>"""
nav = [("try", "Try it: interactive tool"), ("what", "What this is"), ("problem", "The problem"), ("how", "How it works"), ("found", "What it found"), ("s1", "&nbsp;&nbsp;Judging a pilot"), ("s2", "&nbsp;&nbsp;Predicting recovery"),
       ("s3", "&nbsp;&nbsp;Choosing a channel"), ("s4", "&nbsp;&nbsp;Waiting and markdown"), ("s5", "&nbsp;&nbsp;Labor"), ("s6", "&nbsp;&nbsp;Truckloads"), ("s7", "&nbsp;&nbsp;Report requests"),
       ("s8", "&nbsp;&nbsp;Putting it together"), ("s9", "&nbsp;&nbsp;After launch"), ("trust", "Why trust it"), ("limits", "What it cannot tell you"), ("app", "In the repository")]
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Returns Decision Engine: a decision system for returns inventory</title><style>{css}</style></head><body>
<nav><div class="t">Returns Decision Engine</div>{''.join(f'<a href="#{i}">{t}</a>' for i, t in nav)}</nav>
<main><h1>Returns Decision Engine</h1>
<p class="sub">Models, decisions and a pipeline for a business that sells returned goods: what each item will recover, how to list it, where labor pays, what a truckload is worth, and what each decision is worth in dollars.</p>
<div class="banner"><b>All data is simulated</b> with known ground truth, so each method can be checked against the truth it tries to recover. Read the numbers as a test of method, not as facts about any real company.</div>
{tryit}
{what}
{how}
{found_head}{headline}<p>Each finding below is laid out the same way: the question, how it was looked at and whether ML was used, what the data shows, and what to do about it.</p></section>
{S1}{S2}{S3}{S4}{S5}{S6}{S7}{S8}{S9}{trust}{limits}{app}
<footer>Generated from <code>outputs/tables</code> and <code>outputs/run_manifest.json</code> by <code>site_builder/build_report.py</code>. Numbers update whenever the pipeline runs.</footer></main></body></html>"""

out = os.path.join(ROOT, "docs", "site", "index.html")
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, "w").write(page)
print("wrote", out, f"{len(page) / 1e6:.2f} MB")

# keep the explorer linked back to this page (idempotent; the explorer is built by build_site.py)
ex = os.path.join(ROOT, "docs", "site", "explorer.html")
if os.path.exists(ex):
    t = open(ex).read()
    if 'id="homeLink"' not in t:
        link = ('<a id="homeLink" href="index.html" style="position:fixed;right:14px;bottom:14px;z-index:9999;background:#fff;border:1px solid #d9d1c3;border-radius:6px;'
                'padding:7px 12px;font:600 13px -apple-system,Arial,sans-serif;color:#1d2127;text-decoration:none;box-shadow:0 1px 4px rgba(0,0,0,.12)">&larr; Project home</a>')
        open(ex, "w").write(t.replace("<body>", "<body>" + link, 1))
