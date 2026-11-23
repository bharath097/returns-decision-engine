"""Effort rule: where extra photos (and handling at all) pay for themselves.

The photo experiment randomized an 'extra photos' arm within a subset of items, so the effect is causal. Rule:
    take extra photos iff   uplift_c x E[net revenue] + avoided_refund_value  >  extra_minutes x labor_cost
which gives a minimum item value  V*_c = cost / uplift_c.  Small items never clear it, large ones always do.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config
from .utils import eb_shrink

BANDS = [0, 25, 50, 100, 250, 500, 1000, 1e9]
LABELS = ["<25", "25-50", "50-100", "100-250", "250-500", "500-1000", "1000+"]


def photo_experiment_frame(con) -> pd.DataFrame:
    d = con.execute("""select item_id, category, retail_value, sale_price, photo_arm, photo_count, net_revenue, sale_price, sold, refund_flag,
                              handling_minutes, final_net_value, channel
                       from mart_item where status = 'closed' and photo_arm in ('extra','control')""").df()
    d["T"] = (d["photo_arm"] == "extra").astype(int)
    d["band"] = pd.cut(d["retail_value"], BANDS, labels=LABELS, right=False)
    return d


def _ratio_ci(y1, y0, B=300, seed=1):
    rng = np.random.default_rng(seed)
    est = y1.mean() / y0.mean() - 1
    bs = []
    for _ in range(B):
        a = y1[rng.integers(0, len(y1), len(y1))].mean(); b = y0[rng.integers(0, len(y0), len(y0))].mean()
        bs.append(a / b - 1)
    return est, float(np.std(bs))


def photo_effects(d: pd.DataFrame, labor_per_minute: float, fee_pct: float, by: str = "category") -> pd.DataFrame:
    """Uplift in gross sale price (ratio of means, bootstrap SE), shrunk across groups, converted to dollars of benefit.

    benefit(item) = uplift x E[sale price] x (1 - fee) + (refund_rate_control - refund_rate_extra) x E[sale price]
    """
    rows = []
    for k, g in d.groupby(by, observed=True):
        t, c = g[g["T"] == 1], g[g["T"] == 0]
        if len(t) < 60 or len(c) < 60:
            continue
        u, se = _ratio_ci(t["sale_price"].to_numpy(), c["sale_price"].to_numpy())
        dmin = t["handling_minutes"].mean() - c["handling_minutes"].mean()
        rows.append({by: k, "n_extra": len(t), "n_control": len(c), "uplift_sale_price": u, "se": se,
                     "extra_minutes": dmin, "extra_cost": dmin * labor_per_minute,
                     "mean_sale_price_control": c["sale_price"].mean(),
                     "refund_rate_extra": t["refund_flag"].mean(), "refund_rate_control": c["refund_flag"].mean()})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    sh = eb_shrink(out["uplift_sale_price"], out["se"])
    out["uplift_shrunk"] = sh["shrunk"].to_numpy()
    out["pooled_uplift"] = sh["pooled"].to_numpy()
    rd = (out["refund_rate_control"] - out["refund_rate_extra"]).clip(lower=-0.05)
    per_dollar = out["uplift_shrunk"] * (1 - fee_pct) + 0.5 * rd          # benefit per expected sale-price dollar (refund diff damped)
    out["benefit_per_sale_dollar"] = per_dollar
    out["min_expected_sale_price_worth_extra_photos"] = np.where(per_dollar > 0, out["extra_cost"] / per_dollar, np.inf)
    return out


def photo_rule_by_band(d: pd.DataFrame, pooled_benefit_per_dollar: float, labor_per_minute: float) -> pd.DataFrame:
    """Structural rule by retail band: benefit = pooled uplift x band's mean sale price; observed gain shown for reference."""
    rows = []
    for k, g in d.groupby("band", observed=True):
        t, c = g[g["T"] == 1], g[g["T"] == 0]
        if len(t) < 60 or len(c) < 60:
            continue
        cost = (t["handling_minutes"].mean() - c["handling_minutes"].mean()) * labor_per_minute
        gain_obs = t["sale_price"].mean() - c["sale_price"].mean()
        se = np.sqrt(t["sale_price"].var() / len(t) + c["sale_price"].var() / len(c))
        gain_rule = pooled_benefit_per_dollar * c["sale_price"].mean()
        rows.append({"retail_band": k, "n": len(g), "mean_sale_price": c["sale_price"].mean(), "extra_labor_cost": cost,
                     "observed_gain_sale_price": gain_obs, "observed_gain_se": se,
                     "rule_benefit_per_item": gain_rule, "net_benefit_rule": gain_rule - cost, "worth_it": bool(gain_rule > cost)})
    return pd.DataFrame(rows)


def min_item_value(con, cfg: Config) -> pd.DataFrame:
    """Smallest retail band whose items earn a positive average final net value, by category (auction items)."""
    d = con.execute("select category, retail_value, final_net_value from mart_item where status='closed' and channel='auction'").df()
    d["band"] = pd.cut(d["retail_value"], BANDS, labels=LABELS, right=False)
    g = d.groupby(["category", "band"], observed=True).agg(n=("final_net_value", "size"), mean_net_value=("final_net_value", "mean"),
                                                         mean_retail=("retail_value", "mean")).reset_index()
    g["worth_handling"] = g["mean_net_value"] > 0
    first = (g[g.worth_handling & (g.n >= 30)].sort_values("mean_retail").groupby("category").head(1)[["category", "band", "mean_retail"]]
             .rename(columns={"band": "smallest_profitable_band", "mean_retail": "typical_retail_in_band"}))
    return g, first
