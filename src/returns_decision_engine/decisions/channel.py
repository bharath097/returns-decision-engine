"""The zero problem: auction vs fixed-price, measured honestly.

An auction always clears (a zero is a final zero). A fixed-price listing can stay open, and "open" must
not be read as either a success or a zero. Value channels per item:

    E_fixed = p * (1 + m) * X  +  (1 - p) * (X - h)

p = probability it sells at the fixed price, m = premium over the expected auction value X, h = value
lost by waiting (holding cost, decay, fallback shortfall). Fixed-price-first wins when
p > h / (m*X + h).  If an unsold item is simply lost (X - h = 0), this collapses to p > 1/(1+m): 83% at m = 20%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


# ------------------------------------------------------------------------ formulas
def wilson_ci(k: int, n: int, conf: float = 0.95) -> tuple[float, float, float]:
    if n == 0:
        return (np.nan, np.nan, np.nan)
    z = stats.norm.ppf(1 - (1 - conf) / 2)
    ph = k / n
    den = 1 + z * z / n
    centre = (ph + z * z / (2 * n)) / den
    half = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return ph, max(0.0, centre - half), min(1.0, centre + half)


def expected_value_fixed_first(p: float, m: float, X: float, h: float) -> float:
    return p * (1 + m) * X + (1 - p) * (X - h)


def breakeven_p(m: float, X: float, h: float) -> float:
    """Fixed-price-first beats listing straight to auction when p exceeds this."""
    return h / (m * X + h)


def breakeven_table(premiums, X: float, h_values) -> pd.DataFrame:
    rows = [{"premium": m, "wait_cost_h_as_share_of_X": hv / X, "breakeven_sale_probability": breakeven_p(m, X, hv)}
            for m in premiums for hv in h_values]
    return pd.DataFrame(rows)


def required_n_two_means(sd: float, delta: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Items per arm to detect a difference `delta` in mean net value per item."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return int(np.ceil(2 * (z * sd / delta) ** 2))


def balance_table(df: pd.DataFrame, treat_col: str, numeric: list, categorical: list) -> pd.DataFrame:
    """Standardised mean differences between arms (randomization check; |SMD| < 0.1 is good)."""
    rows = []
    t, c = df[df[treat_col] == 1], df[df[treat_col] == 0]
    for v in numeric:
        sd = np.sqrt((t[v].var() + c[v].var()) / 2)
        rows.append({"variable": v, "treated_mean": t[v].mean(), "control_mean": c[v].mean(), "smd": (t[v].mean() - c[v].mean()) / sd if sd else 0.0})
    for v in categorical:
        for lvl in sorted(df[v].astype(str).unique()):
            a, b = (t[v].astype(str) == lvl).mean(), (c[v].astype(str) == lvl).mean()
            sd = np.sqrt((a * (1 - a) + b * (1 - b)) / 2)
            rows.append({"variable": f"{v}={lvl}", "treated_mean": a, "control_mean": b, "smd": (a - b) / sd if sd else 0.0})
    out = pd.DataFrame(rows)
    out["flag"] = np.where(out.smd.abs() >= 0.1, "imbalanced", "ok")
    return out


# ------------------------------------------------------------------------ the three views
def three_views(pilot: pd.DataFrame) -> pd.DataFrame:
    """The same pilot read three ways. Only the last is a fair comparison of strategies.

    1. 'sold items only'   : average recovery of items that sold (flattering; ignores the open ones)
    2. 'zeros counted'     : sale price / retail over ALL listed items in the channel, open = 0 (too harsh for fixed-price-first,
                              because unsold items later sell by rollover)
    3. 'strategy'          : net value per retail dollar of the whole strategy, including rollover and fallback
    """
    rows = []
    for name, g in [("auction (control)", pilot[pilot["T"] == 0])] + \
                   [(f"fixed-price first, +{int(round(p * 100))}%", pilot[(pilot["T"] == 1) & (pilot["premium_pct"].round(2) == round(p, 2))])
                    for p in sorted(pilot.loc[pilot["T"] == 1, "premium_pct"].round(2).unique())]:
        sold_first = g[g["sale_channel"].isin(["auction", "fixed"])]
        n = len(g)
        k_first = int(((g["sale_channel"] == "fixed") | ((g["T"] == 0) & g["sold"].astype(bool))).sum())
        p, lo, hi = wilson_ci(k_first, n)
        rows.append({
            "strategy": name, "items": n,
            "view1_recovery_sold_items_only": (sold_first["sale_price"] / sold_first["retail_value"]).mean(),
            "view2_recovery_zeros_counted_first_channel": (g.loc[g["sale_channel"].isin(["auction", "fixed"]), "sale_price"].sum()) / g["retail_value"].sum(),
            "view3_strategy_net_value_per_retail": g["final_net_value"].sum() / g["retail_value"].sum(),
            "sold_in_first_channel_rate": p, "sold_in_first_channel_lo95": lo, "sold_in_first_channel_hi95": hi,
            "ultimately_sold_rate": g["sold"].astype(float).mean(), "avg_days_to_close": g["days_listed"].mean()})
    return pd.DataFrame(rows)


def story_five_items(sold: int = 3, open_: int = 2, premium: float = 0.20, X: float = 100.0, h_share: float = 0.10,
                     fixed_floor: float = 0.0) -> dict:
    """A five-item pilot: 3 sold at +20%, 2 still open, an unknown zero risk."""
    n = sold + open_
    p, lo, hi = wilson_ci(sold, n)
    h = h_share * X
    return {
        "n_items": n, "sold_at_premium": sold, "still_open": open_, "observed_rate": p, "wilson_lo95": lo, "wilson_hi95": hi,
        "breakeven_p_if_unsold_is_lost": 1 / (1 + premium),
        "breakeven_p_with_fallback_h": breakeven_p(premium, X, h),
        "ev_fixed_first_at_observed_p": expected_value_fixed_first(p, premium, X, h),
        "ev_fixed_first_at_wilson_lo": expected_value_fixed_first(lo, premium, X, h),
        "ev_fixed_first_at_wilson_hi": expected_value_fixed_first(hi, premium, X, h),
        "ev_auction_baseline": X,
        "verdict": ("not enough evidence either way" if lo < breakeven_p(premium, X, h) < hi else
                    ("fixed-price-first wins" if lo > breakeven_p(premium, X, h) else "auction wins")),
        "sample_needed_to_resolve": "see required_n_two_means with pilot net-value sd"}
