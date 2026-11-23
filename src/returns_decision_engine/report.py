"""Charts, CSV tables, model cards and RESULTS.md from a pipeline Results object."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import Config

C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6"
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.facecolor": SURF, "figure.facecolor": SURF, "axes.grid": True,
                     "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
                     "legend.frameon": False})


def _save(fig, path):
    fig.tight_layout(); fig.savefig(path, dpi=140, facecolor=SURF); plt.close(fig)


def md_table(df: pd.DataFrame, floatfmt="{:,.3f}", max_rows=30) -> str:
    d = df.head(max_rows).copy()
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, r in d.iterrows():
        cells = []
        for v in r:
            if isinstance(v, (float, np.floating)):
                cells.append("" if pd.isna(v) else ("inf" if np.isinf(v) else floatfmt.format(v)))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def charts(res, out: Path) -> list[str]:
    fig_dir = out / "figures"; fig_dir.mkdir(parents=True, exist_ok=True)
    T, made = res.tables, []

    def done(name, fig):
        _save(fig, fig_dir / name); made.append(name)

    # 1 calibration
    c = T["recovery_calibration"]; f, ax = plt.subplots(figsize=(5.2, 4.6))
    ax.plot([0, c.mean_actual.max() * 1.05], [0, c.mean_actual.max() * 1.05], color=GRID, lw=1.5)
    ax.plot(c.mean_pred, c.mean_actual, "-o", color=C1, lw=2, ms=6, mfc=SURF, mew=2, label="model, by decile")
    ax.set_xlabel("Predicted recovery"); ax.set_ylabel("Actual recovery"); ax.set_title("Predictions track what happened (holdout)", loc="left", color=INK)
    ax.legend(); done("01_recovery_calibration.png", f)
    # 2 model comparison
    m = T["recovery_metrics"]; f, ax = plt.subplots(figsize=(7, 3.8)); y = np.arange(len(m))
    ax.barh(y, m.mae, color=[C1, GRID, GRID, GRID][:len(m)], height=0.55)
    ax.set_yticks(y); ax.set_yticklabels(m.model); ax.invert_yaxis()
    for i, v in enumerate(m.mae): ax.text(v + 0.002, i, f"{v:.3f}", va="center", color=INK2)
    ax.set_xlabel("Mean absolute error in recovery (lower is better)"); ax.set_title("Two-part model vs alternatives (holdout)", loc="left", color=INK); done("02_model_comparison.png", f)
    # 3 importance
    fi = T["recovery_feature_importance"].head(12).iloc[::-1]; f, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.barh(fi.feature, fi.importance, color=C1, height=0.6); ax.set_xlabel("Share of model gain"); ax.set_title("What the recovery model leans on", loc="left", color=INK); done("03_feature_importance.png", f)
    # 4 error by category
    e = T["recovery_error_by_category"].sort_values("mae"); f, ax = plt.subplots(figsize=(7.2, 5.4)); y = np.arange(len(e))
    ax.barh(y - 0.2, e.mae, 0.38, color=C1, label="new model"); ax.barh(y + 0.2, e.mae_production, 0.38, color=C2, label="incumbent")
    ax.set_yticks(y); ax.set_yticklabels(e.category); ax.set_xlabel("MAE (lower is better)"); ax.legend(); ax.set_title("Error by category", loc="left", color=INK); done("04_error_by_category.png", f)
    # 5 intervals
    cv = T["interval_coverage_by_category"].sort_values("coverage"); f, ax = plt.subplots(figsize=(7, 5)); ax.barh(cv.category, cv.coverage, color=C1, height=0.6)
    ax.axvline(0.8, color=C2, lw=2); ax.text(0.801, -0.9, "80% target", color=INK2, fontsize=9); ax.set_xlim(0.5, 1.0); ax.set_xlabel("Share of outcomes inside the interval")
    ax.set_title("Prediction-interval coverage by category", loc="left", color=INK); done("05_interval_coverage.png", f)
    # 6 zero problem
    z = T["zero_problem_three_views"]; f, ax = plt.subplots(figsize=(8, 4.4)); x = np.arange(len(z)); w = 0.26
    for k, (col, lab, colr) in enumerate([("view1_recovery_sold_items_only", "sold items only", C1), ("view2_recovery_zeros_counted_first_channel", "zeros counted, first channel", C2),
                                          ("view3_strategy_net_value_per_retail", "whole strategy, net value", C3)]):
        ax.bar(x + (k - 1) * w, z[col], w, color=colr, label=lab)
    ax.set_xticks(x); ax.set_xticklabels(z.strategy, fontsize=9); ax.set_ylabel("per retail dollar"); ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.12))
    ax.set_title("The same pilot, three ways: only the third compares strategies fairly", loc="left", color=INK, pad=28); done("06_zero_problem_views.png", f)
    # 7 sale curves
    sc = T["sale_curves_by_premium"]; f, ax = plt.subplots(figsize=(6.4, 4.2))
    for col, cl in zip(sc.columns[1:], [C1, C2, C3]):
        ax.plot(sc.day, sc[col], color=cl, lw=2.2, label=f"{col} premium")
    ax.set_xlabel("Days listed at fixed price"); ax.set_ylabel("Probability sold by day"); ax.legend(); ax.set_title("Higher premium, slower sale", loc="left", color=INK); done("07_sale_curves.png", f)
    # 8 uplift calibration
    u = T["uplift_calibration"]; f, ax = plt.subplots(figsize=(5.6, 4.4))
    ax.errorbar(u.predicted_uplift, u.realized_uplift, yerr=1.96 * u.se, fmt="o-", color=C1, ecolor=GRID, lw=2, label="octiles of predicted uplift")
    ax.axhline(0, color=GRID); ax.axvline(0, color=GRID); ax.set_xlabel("Predicted uplift of fixed-price-first"); ax.set_ylabel("Realized uplift (randomized)"); ax.legend()
    ax.set_title("Does the uplift model rank items correctly?", loc="left", color=INK); done("08_uplift_calibration.png", f)
    # 9 policies
    p = T["policy_comparison"]; f, ax = plt.subplots(figsize=(7.6, 3.6)); y = np.arange(len(p)); ax.barh(y, p.gain_dollars_per_item_vs_auction, color=[GRID if v == 0 else (C3 if v > 0 else C2) for v in p.gain_dollars_per_item_vs_auction], height=0.55)
    ax.set_yticks(y); ax.set_yticklabels(p.policy, fontsize=9); ax.invert_yaxis(); ax.axvline(0, color=INK2, lw=1)
    for i, v in enumerate(p.gain_dollars_per_item_vs_auction): ax.text(v + (0.1 if v >= 0 else -0.1), i, f"${v:,.2f}", va="center", ha="left" if v >= 0 else "right", color=INK2, fontsize=9)
    ax.set_xlabel("Gain per item vs always-auction (held-out, inverse-propensity weighted)"); ax.set_title("Channel policy value", loc="left", color=INK); done("09_channel_policies.png", f)
    # 10 waiting
    w_ = T["waiting_policy_results"]; w_ = w_[~w_.policy.str.startswith("model-predicted")]; mean = w_.groupby("policy").net_value_per_retail.mean().sort_values()
    f, ax = plt.subplots(figsize=(7.2, 3.8)); ax.barh(mean.index, mean.values, color=[C3 if "full" in i else (C1 if "DP" in i else GRID) for i in mean.index], height=0.55)
    for i, v in enumerate(mean.values): ax.text(v + 0.003, i, f"{v:.3f}", va="center", color=INK2)
    ax.set_xlabel("Net value per retail dollar, scored under the simulator's true mechanism"); ax.set_title("Markdown schedule vs holding one price", loc="left", color=INK); done("10_waiting_policies.png", f)
    sch = T["waiting_schedules"]; f, ax = plt.subplots(figsize=(6.4, 4))
    for cat, cl in zip(["Tools", "Smartphones", "Furniture"], [C1, C2, C3]):
        s = sch[(sch.category == cat) & (sch.kind == "full ladder")]; ax.step(s.day, s.price_multiple, where="post", color=cl, lw=2.2, label=cat)
    ax.axhspan(*res.scalars["waiting_support"], color=GRID, alpha=0.6); ax.text(1, res.scalars["waiting_support"][1] + 0.01, "price range the pilot tested", fontsize=8, color=INK2)
    ax.set_xlabel("Day listed"); ax.set_ylabel("Price as multiple of expected auction price"); ax.legend(); ax.set_title("Learned markdown schedules", loc="left", color=INK); done("11_markdown_schedules.png", f)
    # 12 photos
    pb = T["photo_rule_by_band"]; f, ax = plt.subplots(figsize=(6.8, 4)); ax.bar(pb.retail_band.astype(str), pb.net_benefit_rule, color=[C3 if v > 0 else C2 for v in pb.net_benefit_rule], width=0.6)
    ax.axhline(0, color=INK2, lw=1); ax.set_xlabel("Retail value band ($)"); ax.set_ylabel("Net benefit of extra photos per item ($)"); ax.set_title("Extra photos pay off from mid-value items up", loc="left", color=INK); done("12_photo_rule.png", f)
    # 13 scorecard
    s = T["source_scorecard"]; f, ax = plt.subplots(figsize=(7, 4.6)); tiers = {"A": C3, "B": C1, "C": C4, "D": C2}
    for t, g in s.groupby("tier"): ax.scatter(g.lots, g.profit_per_retail_dollar_shrunk, s=40 + g.score, color=tiers[t], label=f"tier {t}", edgecolor=SURF, linewidth=1.5)
    ax.set_xlabel("Lots bought from the source"); ax.set_ylabel("Profit per retail dollar (shrunk)"); ax.legend(); ax.set_title("Source scorecard: profit vs track record", loc="left", color=INK); done("13_source_scorecard.png", f)
    # 14 bid sweep
    sw = T["bid_sweep"]; f, ax = plt.subplots(figsize=(6.8, 4.2))
    for mg, cl in zip(sorted(sw.target_margin.unique()), [C1, C2, C3, C4]):
        g = sw[sw.target_margin == mg]; ax.plot(g.risk_buffer_k, g.total_profit / 1e3, "-o", color=cl, lw=2, label=f"target margin {int(mg * 100)}%")
    ax.set_xlabel("Risk buffer k (in standard deviations)"); ax.set_ylabel("Backtest profit ($ thousands)"); ax.legend(); ax.set_title("Cost of a conservative bid ceiling", loc="left", color=INK); done("14_bid_sweep.png", f)
    # 15 match
    mg = T["match_review_gain"]; f, ax = plt.subplots(figsize=(6, 4))
    ax.plot(mg.review_share * 100, mg.share_of_dollar_error_captured * 100, "-o", color=C1, lw=2.2, label="dollar error captured")
    ax.plot(mg.review_share * 100, mg.share_of_wrong_matches_found * 100, "-o", color=C3, lw=2.2, label="wrong matches found")
    ax.plot(mg.review_share * 100, mg.review_share * 100, color=GRID, lw=1.5, label="random review"); ax.set_xlabel("Share of items reviewed (%)"); ax.set_ylabel("%"); ax.legend()
    ax.set_title("Review queue: where to spend human time", loc="left", color=INK); done("15_match_review_gain.png", f)
    # 16 drift
    d = T["drift_psi"].head(12).iloc[::-1]; f, ax = plt.subplots(figsize=(6.4, 4.4)); ax.barh(d.feature, d.psi, color=[C2 if v >= 0.25 else (C4 if v >= 0.1 else C1) for v in d.psi], height=0.6)
    ax.axvline(0.1, color=INK2, lw=1, ls=":"); ax.axvline(0.25, color=INK2, lw=1, ls=":"); ax.set_xlabel("Population stability index (0.10 warn, 0.25 alert)"); ax.set_title("Input drift since training", loc="left", color=INK); done("16_drift_psi.png", f)
    # 17 monthly
    mp = T["monthly_performance"]; f, ax = plt.subplots(figsize=(7, 4)); ax.plot(mp.month, mp.mae, "-o", color=C1, lw=2.2, label="new model"); ax.plot(mp.month, mp.mae_baseline, "-o", color=C2, lw=2.2, label="category average")
    ax.set_ylabel("MAE"); ax.legend(); plt.setp(ax.get_xticklabels(), rotation=45, ha="right"); ax.set_title("Error by month after the training window", loc="left", color=INK); done("17_monthly_performance.png", f)
    # 18 impact
    im = T["pricing_anchor_impact"]; im = im[im.anchor != "incumbent"]; f, ax = plt.subplots(figsize=(7.2, 4)); prem = sorted(im.premium.unique()); x = np.arange(len(prem)); w = 0.36
    for k, (a, cl) in enumerate(zip(im.anchor.unique(), [C1, GRID])):
        g = im[im.anchor == a].sort_values("premium"); ax.bar(x + (k - .5) * w, g.gain_vs_first_per_item, w, color=cl, label=a, yerr=[g.gain_vs_first_per_item - g.lo95, g.hi95 - g.gain_vs_first_per_item], ecolor=INK2)
    ax.axhline(0, color=INK2, lw=1); ax.set_xticks(x); ax.set_xticklabels([f"+{int(p * 100)}%" if p else "no premium" for p in prem]); ax.set_ylabel("Gain per item vs incumbent ($)")
    ax.legend(fontsize=8); ax.set_title("What a better price anchor is worth depends on how it is used", loc="left", color=INK); done("18_pricing_anchor_impact.png", f)
    return made


def write_tables(res, out: Path):
    td = out / "tables"; td.mkdir(parents=True, exist_ok=True)
    for k, v in res.tables.items():
        v.to_csv(td / f"{k}.csv", index=False)
    md = out / "models"; md.mkdir(exist_ok=True, parents=True)
    for k, v in res.cards.items():
        (md / f"model_card_{k}.json").write_text(json.dumps(v, indent=2))
    (out / "metric_layer_prompt.txt").write_text(res.scalars.get("metric_prompt", ""))


def _d(x):
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def _s(x, f="{:.3f}"):
    return f.format(x)


def results_md(res, cfg: Config) -> str:
    T, S = res.tables, res.scalars
    ev = S["recovery_eval"]; m, b, p, nv = ev["model"], ev["category_median_baseline"], ev["current_production_model"], ev["naive_sold_only_model"]
    ate = T["pilot_ate"].iloc[0]; pol = T["policy_comparison"]
    _cat = T["pilot_ate_by_category"]
    _fx_win = ", ".join(_cat[_cat.lo95 > 0].sort_values("effect", ascending=False).apply(lambda r: f"{r['group']} ({r.effect:+.3f})", axis=1))
    _au_win = ", ".join(_cat[_cat.hi95 < 0].sort_values("effect").apply(lambda r: f"{r['group']} ({r.effect:+.3f})", axis=1)); wp = T["waiting_policy_results"]
    wmean = wp[~wp.policy.str.startswith("model-predicted")].groupby("policy").net_value_per_retail.mean()
    pb = T["photo_rule_by_band"]; bt = T["bid_backtest"]; sw = T["bid_sweep"]; imp = T["pricing_anchor_impact"]
    sv, hv, rd = S["scorecard_validation"], S["hazard_eval"], S["retrain_decision"]
    best_sw = sw.sort_values("total_profit", ascending=False).iloc[0]
    story = S["five_item_story"]
    imp0 = imp[(imp.anchor == "new model") & (imp.premium == 0.0)].iloc[0]
    imp2 = imp[(imp.anchor == "new model") & (imp.premium == 0.2)].iloc[0]
    orc0 = imp[(imp.anchor.str.startswith("oracle")) & (imp.premium == 0.0)].iloc[0]
    L = []
    A = L.append
    A("# Returns Decision Engine: results\n")
    A("> **All data in this project is SIMULATED** (`config/simulation.yaml`, seed fixed) with known ground truth, so every method is checked against the truth it is trying to recover. Parameters are placeholders. Nothing here describes any real company, and no number should be quoted as a real result.\n")
    A("## Headlines\n")
    A(f"1. **Recovery model.** On a holdout after the training window, the two-part model has MAE {_s(m['mae'])} vs {_s(p['mae'])} for an incumbent category x condition lookup and {_s(b['mae'])} for a category average. Total predicted dollars are within {m['weighted_total_error_pct']*100:+.1f}% of actual (incumbent {p['weighted_total_error_pct']*100:+.1f}%, naive sold-only model {nv['weighted_total_error_pct']*100:+.1f}%). Probability-of-sale AUC {_s(ev['auc_sold'])}. The 80% intervals cover {ev['interval_coverage']*100:.1f}% of outcomes.")
    A(f"2. **What the estimate is worth.** Used to anchor a fixed-price list price with no premium, the new model adds {_d(imp0.gain_vs_first_per_item)} per item over the incumbent (95% CI {_d(imp0.lo95)} to {_d(imp0.hi95)}), about ${imp0.gain_per_month:,.0f} per month at {imp0.items_per_month:,.0f} fixed-price items per month; perfect item-level knowledge would add {_d(orc0.gain_vs_first_per_item)} per item. At a +20% premium the anchor matters little ({_d(imp2.gain_vs_first_per_item)} per item, CI {_d(imp2.lo95)} to {_d(imp2.hi95)}; the new model's lower anchor lists items cheaper than the incumbent's at this premium). **A better number is worth little unless the decision using it is also right.**")
    A(f"3. **Zero problem.** Fixed-price-first at these parameters is *not* better than auction on average: effect on net value per retail dollar {ate.effect:+.3f} (95% CI {ate.lo95:+.3f} to {ate.hi95:+.3f}); it takes {ate.avg_days_fixed:.1f} days against {ate.avg_days_auction:.1f}. The three views of the same pilot disagree (see below), which is the point of measuring the strategy rather than the first channel. Choosing the channel item by item changes value by {_d(pol.loc[pol.policy.str.startswith('learned: fixed only'), 'gain_dollars_per_item_vs_auction'].iloc[0])} per item against always-auction (held-out). By category, fixed-price-first clearly wins in: {_fx_win or 'none'}; auction clearly wins in: {_au_win or 'none'}; the rest are indistinguishable from zero at this sample size.")
    A(f"4. **Waiting rule.** Scored under the simulator's true mechanism, a learned markdown schedule earns {wmean['DP, full ladder']:.3f} net value per retail dollar against {wmean[[c for c in wmean.index if c.startswith('hold')]].max():.3f} for the best single held price. Restricted to the premium range the pilot actually tested the schedule earns {wmean['DP, supported range']:.3f}; the rest of the gain is extrapolation and should be confirmed with a randomized markdown test.")
    A(f"5. **Effort.** Extra photos pay for themselves from roughly the {pb[pb.worth_it].retail_band.astype(str).iloc[0] if pb.worth_it.any() else 'n/a'} retail band up (pooled uplift {S['photo_pooled_benefit_per_dollar']*100:.1f}% of sale price after fees against about ${pb.extra_labor_cost.mean():.2f} of labor).")
    A(f"6. **Sources and lots.** The source score correlates {sv['corr_score']:.2f} with true source profitability; shrinkage did not beat raw means here (RMSE {sv['rmse_shrunk']:.4f} vs {sv['rmse_raw']:.4f}) because each source has many lots. The lot model's out-of-fold lot value correlates {S['lot_model']['corr']:.3f} with actual. The bid-ceiling backtest shows the trade-off: skipping every lot over the ceiling buys only {int(bt.iloc[1].lots_bought)} of 800 lots and halves total profit while doubling profit per dollar spent. The sweep favours the most aggressive counters ({best_sw.risk_buffer_k:.1f} buffer, {best_sw.target_margin*100:.0f}% margin) only because it assumes sellers accept a counter at the same rate however low it is; replace that with your own acceptance history before using it.")
    A(f"7. **Monitoring.** Retrain recommended: {rd['retrain_recommended']} ({rd['reason']}). Alert features: {', '.join(rd['alert_features']) or 'none'} (seasonality shows up as listing month; the new regional source shows up as source type). The sale-timing model over-predicts after the June 2026 expansion ({hv['model_p_sold_calibrated']:.3f} predicted vs {hv['km_p_sold']:.3f} actual by day 21), a drift a rolling recalibration only partly fixes ({S['hazard_rolling']['after_refresh']:.3f} vs {S['hazard_rolling']['actual_km']:.3f}).\n")
    A("## 1. Data\n")
    A("Simulated warehouse: 34 sources across five types, 800 lots, about 73,000 items over two years, 15 categories, auctions with a second-price rule and a zero that is final, a randomized fixed-price pilot (premium 10/20/30%) that starts Nov 2025, a randomized extra-photo experiment, wrong catalog matches, injected duplicates and late price revisions, and a source-mix change in June 2026.\n")
    A(md_table(T["data_profile"], "{:,.0f}")); A("\nData-quality tests (error severity must be zero):\n"); A(md_table(T["data_quality_tests"]))
    A("\nDuplicates would have overstated lot cost if left in:\n"); A(md_table(T["duplicate_reconciliation"], "{:,.2f}"))
    A("\n## 2. Recovery model\n"); A(md_table(T["recovery_metrics"])); A("\n![calibration](figures/01_recovery_calibration.png)\n![comparison](figures/02_model_comparison.png)\n")
    nd = S["naive_demo"]
    A(f"A model trained only on items that sold predicts a mean recovery of {nd['naive_sold_only_mean']:.3f} against {nd['actual_mean']:.3f} actual; the two-part model predicts {nd['two_part_mean']:.3f}.\n")
    A("![importance](figures/03_feature_importance.png)\n![category](figures/04_error_by_category.png)\n![intervals](figures/05_interval_coverage.png)\n")
    A("Lot-grouped cross-validation (3 folds):\n"); A(md_table(T["recovery_grouped_cv"]))
    A("\n## 3. What the estimate is worth\n"); A(md_table(imp[["premium", "anchor", "net_value_per_item", "gain_vs_first_per_item", "lo95", "hi95", "gain_per_month"]], "{:,.2f}")); A("\n![impact](figures/18_pricing_anchor_impact.png)\n")
    A("## 4. The zero problem\n"); A(md_table(T["zero_problem_three_views"])); A("\n![views](figures/06_zero_problem_views.png)\n![curves](figures/07_sale_curves.png)\n")
    A(f"A five-item pilot (3 sold at +20%, 2 open): observed {story['observed_rate']*100:.0f}% but the 95% Wilson range is {story['wilson_lo95']*100:.0f}% to {story['wilson_hi95']*100:.0f}%. If an unsold item were simply lost, the break-even sale probability would be {story['breakeven_p_if_unsold_is_lost']*100:.0f}%; with an auction fallback it is {story['breakeven_p_with_fallback_h']*100:.0f}%. Verdict on five items: **{story['verdict']}**.\n")
    A("Break-even sale probability by premium and cost of waiting:\n"); A(md_table(T["breakeven_table"])); A("\nItems per arm needed to detect an effect (pilot sd of net value per retail dollar):\n"); A(md_table(T["required_sample"], "{:,.0f}"))
    A("\nPilot effect by premium:\n"); A(md_table(T["pilot_premium_table"])); A("\nRandomization check (|SMD| < 0.1 is balanced):\n"); A(md_table(T["pilot_balance"].sort_values("smd", key=abs, ascending=False)))
    A("\n## 5. Channel policy by item\n"); A(md_table(T["policy_comparison"])); A("\n![policy](figures/09_channel_policies.png)\n![uplift](figures/08_uplift_calibration.png)\n")
    A("## 6. Waiting rule and markdown ladder\n"); A("Hold one more day iff q(P - A) > (1 - q)(c + d).\n"); A(md_table(wp.groupby("policy")[["net_value_per_retail", "p_sold_fixed", "avg_days"]].mean().reset_index()))
    A("\n![waiting](figures/10_waiting_policies.png)\n![schedules](figures/11_markdown_schedules.png)\n")
    A("## 7. Effort: photos and minimum item value\n"); A(md_table(pb)); A("\n![photos](figures/12_photo_rule.png)\n"); A("Smallest retail band with positive average net value, by category:\n"); A(md_table(T["min_item_value"], "{:,.1f}"))
    A("\n## 8. Sources, lots and bid ceilings\n"); A(md_table(T["source_scorecard"][["source_id", "source_type", "lots", "score", "tier", "profit_per_retail_dollar_shrunk", "avg_price_rate", "ceiling_price_rate", "headroom_price_rate", "negotiation_lever", "confidence"]], "{:,.3f}", 40))
    A("\n![scorecard](figures/13_source_scorecard.png)\n"); A("Bid ceiling backtest:\n"); A(md_table(bt, "{:,.2f}")); A("\nSweep of risk buffer and target margin (seller accepts a counter 50% of the time, an assumption):\n"); A(md_table(sw, "{:,.2f}", 16)); A("\n![sweep](figures/14_bid_sweep.png)\n")
    A("Value of inspecting items before bidding:\n"); A(md_table(T["sampling_value"], "{:,.1f}"))
    A("\n## 9. Match quality and review queue\n"); A(md_table(T["match_review_gain"])); A("\n![match](figures/15_match_review_gain.png)\n")
    A("## 10. Monitoring\n"); A(md_table(T["drift_psi"].head(12))); A("\n![drift](figures/16_drift_psi.png)\n![monthly](figures/17_monthly_performance.png)\n")
    A("## 11. Metric layer: answering report requests\n"); A(md_table(T["metric_layer_examples"][["question", "status", "metric", "period", "clarifying_question"]], "{:,.2f}", 20))
    A("\n## 12. User-defined calculations\n"); A(md_table(T["calculations"][T["calculations"].level == "overall"][["calculation", "value", "description"]], "{:,.3f}", 40))
    A("\n## Limits\n- Everything is simulated; real data will differ and every model must be re-fit and re-validated.\n- Policies are scored against the simulator's own hazard mechanism, so they validate the *method*, not the real world.\n- The waiting rule extrapolates outside the tested premium range; confirm with a randomized markdown test.\n- Seasonality is ignored in the policy evaluation because it scales every policy equally.\n- Source scorecards use up to ~23 lots per source; confidence is shown.\n")
    return "\n".join(L)


def write_all(res, cfg: Config) -> Path:
    out = cfg.outputs_dir; out.mkdir(parents=True, exist_ok=True)
    write_tables(res, out); made = charts(res, out)
    (out / "RESULTS.md").write_text(results_md(res, cfg))
    (out / "run_log.json").write_text(json.dumps({"timings_seconds": res.timings, "figures": made, "tables": list(res.tables)}, indent=2))
    return out
