"""Decision engine: one place where the separate models become one decision per item and one dollar figure per lever.

Two outputs
  1. intake_cards  - for a sample of held-out items: what every model says, and the single action it leads to.
  2. value_levers  - what each lever is worth per month at current volume, how that number was obtained
                     (randomized pilot / back-test / model-based / assumption-dependent) and how much to trust it.

Levers overlap (channel routing and markdown both act on the same fixed-price items), so the table is a ladder, not a sum.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BANDS = [0, 25, 50, 100, 250, 500, 1000, 1e9]
BAND_LABELS = ["<25", "25-50", "50-100", "100-250", "250-500", "500-1000", "1000+"]


def policy_gain_ci(ups: pd.DataFrame, p_treat: float, rule: np.ndarray, B: int = 400, seed: int = 7) -> tuple[float, float, float]:
    """Bootstrap (by lot, since items in a lot are correlated) of  value(rule) - value(always auction)  in $ per item, IPW."""
    rng = np.random.default_rng(seed)
    T, y, rv = ups["T"].to_numpy(), ups["y"].to_numpy(), ups["retail_value"].to_numpy()
    pi = rule.astype(int)
    w = np.where(T == 1, 1 / p_treat, 1 / (1 - p_treat))
    d = w * y * rv * ((T == pi).astype(float) - (T == 0).astype(float))
    lots = ups["lot_id"].to_numpy()
    codes, uniq = pd.factorize(lots)
    sums = np.bincount(codes, weights=d, minlength=len(uniq)); cnt = np.bincount(codes, minlength=len(uniq))
    est = d.mean(); boots = []
    for _ in range(B):
        idx = rng.integers(0, len(uniq), len(uniq))
        boots.append(sums[idx].sum() / cnt[idx].sum())
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(est), float(lo), float(hi)


def value_levers(res, con, cfg) -> pd.DataFrame:
    T = res.tables
    rows = []
    months_all = con.execute("select count(distinct date_trunc('month', listing_date)) from mart_item").fetchone()[0]
    pilot_items_pm = float(con.execute("""select count(*)/12.0 from mart_item where pilot_arm in ('fixed','auction') and status='closed'
                                          and listing_date > date '2025-10-31'""").fetchone()[0])
    fixed_retail_pm = float(con.execute("select sum(retail_value)/12.0 from mart_item where channel='fixed_price'").fetchone()[0])

    # 1 ---- a better recovery estimate used as the fixed-price anchor (ML: two-part model)
    a = T["pricing_anchor_impact"]; a = a[(a.premium == 0.0) & (a.anchor == "new model")].iloc[0]
    rows.append(dict(order=1, lever="Better recovery estimate as the price anchor", stage="List", ml="Yes: two-part LightGBM + calibration",
                     monthly=a.gain_per_month, lo=a.lo95_month, hi=a.hi95_month, evidence="back-test on held-out fixed-price listings",
                     basis=f"+${a.gain_vs_first_per_item:.2f} per item x {a.items_per_month:,.0f} fixed-price items per month",
                     caveat="Upper bound if the model were perfect is about 3x this (oracle row in pricing_anchor_impact)."))

    # 2 ---- learned channel routing (ML: uplift T-learner), randomized pilot, bootstrap by lot
    ups, p_treat = res.scalars["_ups"], res.scalars["_p_treat"]
    est, lo, hi = policy_gain_ci(ups, p_treat, (ups["cate"] > 0).to_numpy())
    rows.append(dict(order=2, lever="Route each item to auction or fixed-price first", stage="List", ml="Yes: uplift T-learner, cross-fitted",
                     monthly=est * pilot_items_pm, lo=lo * pilot_items_pm, hi=hi * pilot_items_pm, evidence="randomized pilot, IPW policy value, bootstrap by lot",
                     basis=f"+${est:.2f} per item (95% {lo:.2f} to {hi:.2f}) x {pilot_items_pm:,.0f} pilot-eligible items per month",
                     caveat="Gain comes from a few categories; blanket fixed-price is worse than auction (see the channel analysis)."))

    # 3 ---- markdown ladder (model-based, hazards from the randomized grid)
    w = T["waiting_policy_results"].groupby("policy").net_value_per_retail.mean()
    g = float(w["DP, supported range"] - w[["hold at +10%", "hold at +20%", "hold at +30%"]].max())
    rows.append(dict(order=3, lever="Step the fixed price down by age instead of holding one price", stage="Sell", ml="Partly: per-category hazard models feed a dynamic program",
                     monthly=g * fixed_retail_pm, lo=np.nan, hi=np.nan, evidence="model-based (hazards fitted on the randomized price grid)",
                     basis=f"+{g:.3f} per retail $ x ${fixed_retail_pm:,.0f} fixed-price retail per month, inside the tested price range",
                     caveat="Not randomized. Extending below the tested range would add more but is extrapolation."))

    # 4 ---- extra photos only where they pay
    pr = T["photo_rule_by_band"].copy()
    band_n = con.execute(f"""select case when retail_value<25 then '<25' when retail_value<50 then '25-50' when retail_value<100 then '50-100'
        when retail_value<250 then '100-250' when retail_value<500 then '250-500' when retail_value<1000 then '500-1000' else '1000+' end b,
        count(*)/{months_all}.0 n from mart_item where status='closed' group by 1""").df().set_index("b")["n"]
    pr["n_pm"] = pr["retail_band"].map(band_n).fillna(0)
    vs_none = float((pr[pr.worth_it]["n_pm"] * pr[pr.worth_it]["net_benefit_rule"]).sum())
    vs_all = float((pr[~pr.worth_it]["n_pm"] * -pr[~pr.worth_it]["net_benefit_rule"]).sum())
    rows.append(dict(order=4, lever="Take extra photos only on items worth the minutes", stage="List", ml="No: randomized experiment + break-even arithmetic",
                     monthly=vs_none, lo=np.nan, hi=np.nan, evidence="randomized photo experiment, pooled lift 3.9%",
                     basis=f"net of labor, bands from {pr[pr.net_benefit_rule >= 0.25].retail_band.iloc[0]} retail up; extra photos on everything would instead lose ${vs_all:,.0f} per month on cheap items",
                     caveat="Uses the pooled lift for every band because per-band lifts are too noisy to trust."))

    # 5 ---- match review queue (risk lever, not profit)
    mr = T["match_review_gain"].set_index("review_share").loc[0.05]
    ia = con.execute("select abs(m.retail_value - t.retail_true) e from mart_item m join truth_items t using(item_id) where m.status='closed'").df()["e"]
    exp_pm = float(ia.sum() / months_all)
    rows.append(dict(order=5, lever="Review the 5% of matches most likely to be wrong", stage="List", ml="Yes: match classifier ranks the review queue",
                     monthly=exp_pm * float(mr.share_of_dollar_error_captured), lo=np.nan, hi=np.nan, evidence="audit sample + simulated truth",
                     basis=f"retail value mis-stated per month ${exp_pm:,.0f}; the top 5% queue catches {mr.share_of_dollar_error_captured:.0%} of it",
                     caveat="Retail value that stops being wrong, not profit. It protects every other model, because retail is the denominator of recovery."))

    # 6 ---- bid ceiling, assumption-dependent (seller acceptance)
    b = T["bid_backtest"].set_index("policy")
    base = float(b.loc["buy every lot at listed price (status quo)", "total_profit"])
    c50 = float(b.loc["counter at ceiling when over it; seller accepts 50% of the time", "total_profit"])
    c25 = float(b.loc["counter at ceiling when over it; seller accepts 25% of the time", "total_profit"])
    rows.append(dict(order=6, lever="Counter-offer at the model's bid ceiling on over-priced truckloads", stage="Buy", ml="Yes: lot-value model + per-source uncertainty",
                     monthly=(c50 - base) / months_all, lo=(c25 - base) / months_all, hi=np.nan, evidence="back-test on 800 lots; depends on how often sellers accept",
                     basis=f"counter-offer scenarios vs buying every lot at list price, spread over {months_all} months (low = 25% accept, point = 50%)",
                     caveat="The low end is negative: if sellers rarely accept, skipping lots loses profit. Profit per dollar spent rises in every scenario."))
    df = pd.DataFrame(rows)
    df["unit"] = np.where(df["order"] == 5, "retail $ made correct per month (risk, not profit)", "profit $ per month")
    return df.sort_values("order").reset_index(drop=True)


def intake_cards(res, m, ups, mm, hm, schedules, photo_rule, n_cards: int = 12, seed: int = 11) -> pd.DataFrame:
    """For held-out pilot items, run every model and state the action. One row per item."""
    from .models import match as M
    te = ups[ups["listing_date"] > pd.Timestamp(res.scalars["_calib_end"])].copy()
    if len(te) < n_cards:
        te = ups.copy()
    parts = m.predict_parts(te); iv = m.predict_interval(te)
    te["pred_recovery"] = parts["pred"].to_numpy(); te["p_sell_auction"] = parts["p_sell"].to_numpy()
    te["lo80"] = iv["lo"].to_numpy(); te["hi80"] = iv["hi"].to_numpy()
    te["p_sold_14d_fixed"] = 1 - hm.survival(te, 14, premium=0.20)[:, -1]
    te["p_match_wrong"] = mm.predict_proba(M.match_features(te))[:, 1]
    thr = np.quantile(te["p_match_wrong"], 0.95)
    te["band"] = pd.cut(te["retail_value"], BANDS, labels=BAND_LABELS, right=False).astype(str)
    ok = photo_rule.set_index("retail_band")["worth_it"].to_dict()
    sch = schedules[schedules.kind == "supported range only"]
    first = sch[sch.day == 1].set_index("category")["price_multiple"].to_dict()
    last = sch[sch.day == sch.day.max()].set_index("category")["price_multiple"].to_dict()
    te["route"] = np.where(te["cate"] > 0, "fixed-price first", "auction")
    te["list_at"] = te.apply(lambda r: f"start at {first.get(r.category, np.nan):.2f}x expected auction price, step down to {last.get(r.category, np.nan):.2f}x by day {sch.day.max()}" if r.route != "auction" else "auction, normal start bid", axis=1)
    te["extra_photos"] = te["band"].map(ok).map({True: "yes", False: "no"})
    te["review_match"] = np.where(te["p_match_wrong"] >= min(thr, 0.5), "yes, send to audit", "no")
    rng = np.random.default_rng(seed)
    pick = []
    for _, g in te.groupby("category"):
        pick.append(g.sample(1, random_state=int(rng.integers(1e6))).index[0])
    pick = pick[: n_cards - 1]
    top = te["p_match_wrong"].idxmax()
    if top not in pick:
        pick.append(top)
    cols = ["item_id", "category", "condition", "retail_value", "pred_recovery", "lo80", "hi80", "p_sell_auction", "cate", "route", "list_at",
            "p_sold_14d_fixed", "extra_photos", "p_match_wrong", "review_match", "gross_recovery"]
    out = te.loc[pick, cols].rename(columns={"cate": "uplift_fixed_vs_auction_per_retail", "gross_recovery": "actual_gross_recovery"})
    return out.sort_values("retail_value", ascending=False).reset_index(drop=True)
