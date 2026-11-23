"""Waiting rule and markdown ladder.

An item listed at a fixed price either sells today (probability q_t at the current price) or is held another day at a cost.
Hold one more day iff   q * (P - A)  >  (1 - q) * (c + d)
 P = price if sold now, A = value of the next-best alternative (auction now), c = daily holding cost, d = daily value decay.
Because q depends on price and age, the best price changes over time; backward induction over a price ladder gives the schedule.

Hazards come from a per-category complementary-log-log regression on the pilot's person-period data:
   cloglog h(t) = a_c + b_c * log(price_multiple) + g_c * t
The randomized premium grid identifies b_c only inside its support; the ladder outside that range is flagged as
extrapolated, and the fitted policy is also reported restricted to the supported range.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from ..config import Config


def hold_one_more_day(q: float, price_now: float, alt_value: float, holding_cost: float, decay: float) -> bool:
    return q * (price_now - alt_value) > (1 - q) * (holding_cost + decay)


def fit_category_hazards(person_period: pd.DataFrame, min_rows: int = 400) -> pd.DataFrame:
    """One cloglog GLM per category. Returns a, b (price elasticity on log multiple), g (age slope)."""
    rows = []
    for cat, g in person_period.groupby("category"):
        if len(g) < min_rows or g["y"].sum() < 20:
            continue
        X = pd.DataFrame({"const": 1.0, "log_mult": np.log1p(g["premium_pct"].to_numpy()), "day": g["day"].to_numpy().astype(float)})
        try:
            m = sm.GLM(g["y"].to_numpy(), X, family=sm.families.Binomial(link=sm.families.links.CLogLog())).fit()
        except Exception:
            continue
        rows.append({"category": cat, "a": m.params["const"], "b": m.params["log_mult"], "g": m.params["day"],
                     "se_b": float(m.bse["log_mult"]), "n_rows": len(g), "n_events": int(g["y"].sum())})
    out = pd.DataFrame(rows)
    if len(out) >= 3:                       # empirical-Bayes shrinkage of the price elasticity toward the pooled value
        w = 1 / out["se_b"] ** 2
        bbar = (w * out["b"]).sum() / w.sum()
        Q = (w * (out["b"] - bbar) ** 2).sum()
        tau2 = max(0.0, (Q - (len(out) - 1)) / (w.sum() - (w ** 2).sum() / w.sum()))
        shrink = tau2 / (tau2 + out["se_b"] ** 2)
        out["b_pooled"] = bbar
        out["b_use"] = bbar + shrink * (out["b"] - bbar)
        out["tau2"] = tau2
    else:
        out["b_use"] = out["b"]
    return out


def hazard_at(par: pd.Series, mult: float, day: int) -> float:
    eta = par["a"] + par.get("b_use", par["b"]) * np.log(mult) + par["g"] * day
    return float(1 - np.exp(-np.exp(eta)))


@dataclass
class Economics:
    """Per-item inputs to the DP, in dollars."""
    base_value: float          # price anchor P_hat * retail (the model's expected auction sale price)
    terminal_value: float      # net value if it rolls to auction after the window
    fee_pct: float
    fee_fixed: float
    holding_per_day: float     # shelf + capital + decay cost per day while held
    labor_relist: float = 0.0  # cost of changing a price


def optimal_markdown(par: pd.Series, eco: Economics, ladder: list, horizon: int, support: tuple | None = None,
                     restrict_to_support: bool = False) -> dict:
    """Backward induction. State = day (the price can be reset daily). Returns value, schedule, and extrapolation flags."""
    grid = [r for r in ladder if (not restrict_to_support or support is None or support[0] <= r <= support[1])]
    V = np.zeros(horizon + 2)
    V[horizon + 1] = eco.terminal_value
    best = np.zeros(horizon + 1, dtype=float)
    for t in range(horizon, 0, -1):
        vals = []
        for r in grid:
            q = hazard_at(par, r, t)
            price = eco.base_value * r
            sale = price * (1 - eco.fee_pct) - eco.fee_fixed
            vals.append(q * sale + (1 - q) * (V[t + 1] - eco.holding_per_day))
        k = int(np.argmax(vals)); V[t] = vals[k]; best[t] = grid[k]
    sched = pd.DataFrame({"day": range(1, horizon + 1), "price_multiple": best[1:horizon + 1]})
    sched["extrapolated"] = [support is not None and not (support[0] <= r <= support[1]) for r in sched.price_multiple]
    return {"value": float(V[1]), "schedule": sched}


def static_policy_value(par: pd.Series, eco: Economics, mult: float, horizon: int) -> float:
    """Hold at one price for the whole window, then roll to auction."""
    V = eco.terminal_value
    for t in range(horizon, 0, -1):
        q = hazard_at(par, mult, t)
        V = q * (eco.base_value * mult * (1 - eco.fee_pct) - eco.fee_fixed) + (1 - q) * (V - eco.holding_per_day)
    return float(V)


def exit_day(par: pd.Series, eco: Economics, mult: float, horizon: int) -> int | None:
    """First day on which holding stops being worth it (hold rule fails), if any."""
    for t in range(1, horizon + 1):
        q = hazard_at(par, mult, t)
        if not hold_one_more_day(q, eco.base_value * mult * (1 - eco.fee_pct) - eco.fee_fixed, eco.terminal_value, eco.holding_per_day, 0.0):
            return t
    return None


def evaluate_under_truth(truth: pd.DataFrame, schedule_mult: np.ndarray, eco_per_item: pd.DataFrame, horizon: int,
                         fee_pct: float, fee_fixed: float, n_draws: int = 40, seed: int = 1, frailty_sigma: float = 0.30) -> dict:
    """Run a price schedule through the simulator's TRUE fixed-price mechanism (Monte Carlo) and return mean net value per item.

    truth needs: h0, elast, kappa, decay_d, market_value, base_value (P_hat*retail) and terminal_value, holding_per_day.
    Seasonality is ignored (it multiplies hazards identically under every policy).
    """
    rng = np.random.default_rng(seed)
    n = len(truth)
    t = np.arange(1, horizon + 1)[None, :].astype(float)
    mult = np.asarray(schedule_mult)[None, :]
    h0, el, ka, dd = (truth[c].to_numpy()[:, None] for c in ("h0", "elast", "kappa", "decay_d"))
    M = truth["market_value"].to_numpy()[:, None] * np.exp(-dd * t)
    price = eco_per_item["base_value"].to_numpy()[:, None] * mult
    ratio = np.clip(price / M, 0.3, 4.0)
    total = np.zeros(n); psold = np.zeros(n); days = np.zeros(n)
    for _ in range(n_draws):
        fr = np.exp(rng.normal(0, frailty_sigma, n))[:, None]
        hz = np.clip(h0 * ratio ** (-el) * np.exp(-ka * t) * fr, 0, 0.9)
        hit = rng.random(hz.shape) < (1 - np.exp(-hz))
        sold = hit.any(axis=1)
        day = np.where(sold, hit.argmax(axis=1) + 1, horizon)
        pr = price[np.arange(n), np.clip(day - 1, 0, horizon - 1)]
        val = np.where(sold, pr * (1 - fee_pct) - fee_fixed - eco_per_item["holding_per_day"].to_numpy() * day,
                       eco_per_item["terminal_value"].to_numpy() - eco_per_item["holding_per_day"].to_numpy() * horizon)
        total += val; psold += sold; days += day
    return {"net_value_per_item": float(total.mean() / n_draws), "p_sold_fixed": float(psold.mean() / n_draws), "avg_days": float(days.mean() / n_draws)}


def category_inputs(con, cfg: Config) -> pd.DataFrame:
    """Per-category economics for the DP, estimated from the pilot (no truth used)."""
    w = cfg.econ("rollover_days")
    q = f"""
    select category,
           avg(prod_pred_expected_auction_recovery) as pred_recovery,
           avg(case when sale_channel <> 'fixed' and channel = 'fixed_price' then final_net_value / retail_value end) as terminal_frac,
           avg(case when channel = 'fixed_price' then holding_cost / nullif(holding_days, 0) / retail_value end) as holding_frac_per_day,
           median(retail_value) as median_retail
    from mart_item where status = 'closed' and channel = 'fixed_price'
    group by 1"""
    return con.execute(q).df()


def run_waiting_analysis(con, cfg: Config, fixed_items: pd.DataFrame, n_per_cat: int = 600) -> dict:
    """Fit hazards, solve the DP per category, and score every policy under the simulator's TRUE mechanism."""
    H = cfg.econ("rollover_days")
    from ..models.hazard import person_period
    pp = person_period(fixed_items[fixed_items["status"] == "closed"], cfg.model("hazard")["max_person_period_rows"])
    par = fit_category_hazards(pp).set_index("category")
    inp = category_inputs(con, cfg).set_index("category")
    ladder = list(cfg.decision("markdown_price_grid"))
    prem = sorted(fixed_items["premium_pct"].round(2).unique())
    support = (1 + min(prem), 1 + max(prem))
    fee, ffix = cfg.econ("fee_pct"), cfg.econ("fee_fixed")
    truth = con.execute("""select m.item_id, m.category, m.retail_value, m.prod_pred_expected_auction_recovery as pred,
                                  t.h0, t.elast, t.kappa, t.decay_d, t.market_value
                           from mart_item m join truth_items t using(item_id) where m.channel = 'fixed_price'""").df()
    rows, scheds = [], []
    for cat, p in par.iterrows():
        sub = truth[truth.category == cat]
        if len(sub) < 50 or cat not in inp.index:
            continue
        sub = sub.sample(min(n_per_cat, len(sub)), random_state=3)
        R = float(inp.loc[cat, "median_retail"]); P = float(inp.loc[cat, "pred_recovery"])
        eco = Economics(base_value=P * R, terminal_value=float(inp.loc[cat, "terminal_frac"]) * R, fee_pct=fee, fee_fixed=ffix,
                        holding_per_day=float(inp.loc[cat, "holding_frac_per_day"]) * R)
        full = optimal_markdown(p, eco, ladder, H, support, False)
        supp = optimal_markdown(p, eco, ladder, H, support, True)
        scheds.append(full["schedule"].assign(category=cat, kind="full ladder"))
        scheds.append(supp["schedule"].assign(category=cat, kind="supported range only"))
        per_item = pd.DataFrame({"base_value": sub["pred"] * sub["retail_value"], "holding_per_day": inp.loc[cat, "holding_frac_per_day"] * sub["retail_value"],
                                 "terminal_value": inp.loc[cat, "terminal_frac"] * sub["retail_value"]})
        policies = {f"hold at +{int(round((m) * 100))}%": np.full(H, 1 + m) for m in prem}
        policies["DP, supported range"] = supp["schedule"]["price_multiple"].to_numpy()
        policies["DP, full ladder"] = full["schedule"]["price_multiple"].to_numpy()
        res = {}
        for name, mult in policies.items():
            r = evaluate_under_truth(sub, mult, per_item, H, fee, ffix)
            res[name] = r["net_value_per_item"] / R
            rows.append({"category": cat, "policy": name, "net_value_per_retail": r["net_value_per_item"] / sub["retail_value"].mean(),
                         "p_sold_fixed": r["p_sold_fixed"], "avg_days": r["avg_days"], "model_value_per_retail": np.nan})
        rows.append({"category": cat, "policy": "model-predicted value of DP (supported)", "net_value_per_retail": supp["value"] / R,
                     "p_sold_fixed": np.nan, "avg_days": np.nan, "model_value_per_retail": supp["value"] / R})
    res_df = pd.DataFrame(rows)
    return {"hazard_params": par.reset_index(), "category_inputs": inp.reset_index(), "policy_results": res_df,
            "schedules": pd.concat(scheds, ignore_index=True), "support": support}
