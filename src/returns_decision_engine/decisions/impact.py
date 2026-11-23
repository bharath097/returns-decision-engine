"""Shadow impact: what does a better recovery estimate earn?

The estimate sets the list price of fixed-price items (anchor x retail x (1 + premium)). Each anchor is scored by running the same
random shocks through the simulator's TRUE fixed-price mechanism (common random numbers), holding the item for the window then
rolling to auction. Dollars per month = per-item gain x monthly volume; the interval comes from a bootstrap over items.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config
from .waiting import evaluate_under_truth


def pricing_impact(truth: pd.DataFrame, anchors: dict, category_inputs: pd.DataFrame, cfg: Config, premium: float = 0.20,
                   n_draws: int = 60, boot: int = 200) -> pd.DataFrame:
    """truth: item rows with h0, elast, kappa, decay_d, market_value, retail_value, category and one anchor column per entry of `anchors`
    (anchor = predicted recovery given sold). Returns per-anchor net value per item and gain vs the first anchor with a bootstrap CI."""
    H = cfg.econ("rollover_days"); fee, ff = cfg.econ("fee_pct"), cfg.econ("fee_fixed")
    inp = category_inputs.set_index("category")
    R = truth["retail_value"].to_numpy()
    per = pd.DataFrame({"holding_per_day": truth["category"].map(inp["holding_frac_per_day"]).to_numpy() * R,
                        "terminal_value": truth["category"].map(inp["terminal_frac"]).to_numpy() * R})
    vals = {}
    for name, col in anchors.items():
        per["base_value"] = truth[col].to_numpy() * R
        v = _per_item(truth, np.full(H, 1 + premium), per, H, fee, ff, n_draws)
        vals[name] = v
    names = list(anchors); base = vals[names[0]]
    rng = np.random.default_rng(5); idx = rng.integers(0, len(truth), (boot, len(truth)))
    rows = []
    for n in names:
        d = vals[n] - base
        bs = d[idx].mean(axis=1)
        rows.append({"anchor": n, "net_value_per_item": vals[n].mean(), "gain_vs_first_per_item": d.mean(),
                     "lo95": np.quantile(bs, 0.025), "hi95": np.quantile(bs, 0.975), "items": len(truth)})
    return pd.DataFrame(rows)


def _per_item(truth, mult, per, H, fee, ff, n_draws, seed=11):
    rng = np.random.default_rng(seed)
    n = len(truth); t = np.arange(1, H + 1)[None, :].astype(float)
    h0, el, ka, dd = (truth[c].to_numpy()[:, None] for c in ("h0", "elast", "kappa", "decay_d"))
    M = truth["market_value"].to_numpy()[:, None] * np.exp(-dd * t)
    price = per["base_value"].to_numpy()[:, None] * mult[None, :]
    ratio = np.clip(price / M, 0.3, 4.0)
    tot = np.zeros(n); hold = per["holding_per_day"].to_numpy(); term = per["terminal_value"].to_numpy()
    for _ in range(n_draws):
        fr = np.exp(rng.normal(0, 0.30, n))[:, None]
        hz = np.clip(h0 * ratio ** (-el) * np.exp(-ka * t) * fr, 0, 0.9)
        hit = rng.random(hz.shape) < (1 - np.exp(-hz)); sold = hit.any(axis=1)
        day = np.where(sold, hit.argmax(axis=1) + 1, H)
        pr = price[np.arange(n), np.clip(day - 1, 0, H - 1)]
        tot += np.where(sold, pr * (1 - fee) - ff - hold * day, term - hold * H)
    return tot / n_draws
