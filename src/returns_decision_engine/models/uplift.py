"""Price-response / channel uplift on the randomized fixed-price pilot.

Because assignment to fixed-price-first vs auction was randomized (with the premium also randomized),
treatment effects are identified without modelling selection. Outcome is the item's final net value
per retail dollar (after fees, shipping, refunds, handling, holding, rollover fallback) so channels are compared on
the same footing. Heterogeneity is learned with a T-learner (one boosted model per arm), cross-fitted by lot, and
policies are valued with inverse-propensity weighting on held-out folds. Items whose full window has not elapsed
are excluded so censoring cannot bias the channel comparison.
"""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from ..config import Config
from ..data.registry import Registry
from .features import FeatureBuilder


def load_pilot(con, cfg: Config) -> pd.DataFrame:
    df = con.execute("""
        select * from mart_item
        where pilot_arm in ('fixed','auction') and status = 'closed'
    """).df()
    df["listing_date"] = pd.to_datetime(df["listing_date"])
    cutoff = pd.Timestamp(cfg.settings["splits"]["data_cutoff"])
    minh = cfg.model("uplift")["min_horizon_complete_days"]
    df = df[(cutoff - df["listing_date"]).dt.days >= minh].copy()
    df["T"] = (df["pilot_arm"] == "fixed").astype(int)
    df["y"] = df["final_net_value"] / df["retail_value"]
    return df


def _ci(x: np.ndarray, z=1.96):
    m, se = x.mean(), x.std(ddof=1) / np.sqrt(len(x))
    return m, m - z * se, m + z * se


def ate_table(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    rows = []
    groups = [("ALL", df)] if by is None else list(df.groupby(by, observed=True))
    for k, g in groups:
        a, f = g[g["T"] == 0], g[g["T"] == 1]
        if len(a) < 50 or len(f) < 50:
            continue
        d = f["y"].mean() - a["y"].mean()
        se = np.sqrt(f["y"].var(ddof=1) / len(f) + a["y"].var(ddof=1) / len(a))
        rows.append({"group": k, "n_auction": len(a), "n_fixed": len(f), "net_value_per_retail_auction": a["y"].mean(),
                     "net_value_per_retail_fixed": f["y"].mean(), "effect": d, "lo95": d - 1.96 * se, "hi95": d + 1.96 * se,
                     "sold_rate_auction": a["sold"].astype(float).mean(), "sold_rate_fixed": f["sold"].astype(float).mean(),
                     "avg_days_auction": a["days_listed"].mean(), "avg_days_fixed": f["days_listed"].mean()})
    return pd.DataFrame(rows)


def premium_table(df: pd.DataFrame) -> pd.DataFrame:
    a = df[df["T"] == 0]["y"].mean()
    rows = []
    for p, g in df[df["T"] == 1].groupby("premium_pct"):
        se = g["y"].std(ddof=1) / np.sqrt(len(g))
        rows.append({"premium_pct": p, "n": len(g), "net_value_per_retail": g["y"].mean(), "se": se,
                     "auction_control": a, "effect_vs_auction": g["y"].mean() - a,
                     "sold_at_fixed_price_rate": float((g["sale_channel"] == "fixed").mean()),
                     "avg_days_listed": g["days_listed"].mean()})
    return pd.DataFrame(rows)


class UpliftModel:
    """T-learner with grouped cross-fitting; also reports out-of-fold CATEs and IPW policy values."""

    def __init__(self, cfg: Config, reg: Registry):
        self.cfg, self.reg = cfg, reg

    def cross_fit(self, df: pd.DataFrame) -> pd.DataFrame:
        p = dict(self.cfg.model("uplift")["lgbm"]); p.update(random_state=self.cfg.settings["models"]["random_state"], n_jobs=4)
        out = np.full(len(df), np.nan)
        m1_hat = np.full(len(df), np.nan); m0_hat = np.full(len(df), np.nan)
        for a, b in GroupKFold(4).split(df, groups=df["lot_id"]):
            tr, te = df.iloc[a], df.iloc[b]
            fb = FeatureBuilder(self.cfg, self.reg, "uplift", n_text=0).fit(tr)
            m1 = lgb.LGBMRegressor(**p).fit(fb.transform(tr[tr["T"] == 1]), tr[tr["T"] == 1]["y"])
            m0 = lgb.LGBMRegressor(**p).fit(fb.transform(tr[tr["T"] == 0]), tr[tr["T"] == 0]["y"])
            X = fb.transform(te)
            m1_hat[b], m0_hat[b] = m1.predict(X), m0.predict(X)
        res = df.copy()
        res["mu_fixed"], res["mu_auction"] = m1_hat, m0_hat
        res["cate"] = m1_hat - m0_hat
        return res


def policy_value(res: pd.DataFrame, choose_fixed: np.ndarray, p_treat: float) -> dict:
    """IPW value of a policy (net value per retail dollar) using the randomization probability."""
    T, y = res["T"].to_numpy(), res["y"].to_numpy()
    pi = choose_fixed.astype(int)
    w = np.where(T == 1, 1 / p_treat, 1 / (1 - p_treat)) * (T == pi)
    v = (w * y)
    dollars = (w * y * res["retail_value"].to_numpy())
    se = v.std(ddof=1) / np.sqrt(len(v))
    return {"value_per_retail": float(v.mean()), "se": float(se), "dollars_per_item": float(dollars.mean()),
            "share_fixed": float(pi.mean())}


def compare_policies(res: pd.DataFrame, p_treat: float) -> pd.DataFrame:
    n = len(res)
    pols = {"always auction (control)": np.zeros(n, bool), "always fixed-price first": np.ones(n, bool),
            "learned: fixed only if predicted uplift > 0": (res["cate"] > 0).to_numpy(),
            "learned, requires uplift > 0.02": (res["cate"] > 0.02).to_numpy()}
    rows = []
    for name, pi in pols.items():
        r = policy_value(res, pi, p_treat); r["policy"] = name; rows.append(r)
    df = pd.DataFrame(rows)[["policy", "share_fixed", "value_per_retail", "se", "dollars_per_item"]]
    base = df.loc[df.policy == "always auction (control)", "dollars_per_item"].iloc[0]
    df["gain_dollars_per_item_vs_auction"] = df["dollars_per_item"] - base
    return df


def cate_by_decile(res: pd.DataFrame) -> pd.DataFrame:
    """Does predicted uplift line up with realized uplift? (qini-style check, out of fold)"""
    d = res.copy()
    d["bin"] = pd.qcut(d["cate"], 8, duplicates="drop")
    rows = []
    for k, g in d.groupby("bin", observed=True):
        a, f = g[g["T"] == 0]["y"], g[g["T"] == 1]["y"]
        rows.append({"decile": str(k), "n": len(g), "predicted_uplift": g["cate"].mean(),
                     "realized_uplift": f.mean() - a.mean(),
                     "se": np.sqrt(f.var(ddof=1) / len(f) + a.var(ddof=1) / len(a))})
    return pd.DataFrame(rows)
