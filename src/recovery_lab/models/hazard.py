"""Sale-timing model for fixed-price listings (discrete-time survival).

Each fixed-price item becomes one row per day listed (person-period format); a boosted classifier
learns the daily probability of a sale given features, the listing premium and the day index.
Items still unsold when the window ends (or when the data ends) are right-censored, not dropped.
"""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter
from sklearn.isotonic import IsotonicRegression

from ..config import Config
from ..data.registry import Registry
from .features import FeatureBuilder


def load_fixed_items(con, cfg: Config) -> pd.DataFrame:
    w = cfg.econ("rollover_days")
    df = con.execute("select * from mart_item where channel = 'fixed_price'").df()
    df["listing_date"] = pd.to_datetime(df["listing_date"])
    df["event"] = (df["sale_channel"] == "fixed").astype(int)
    # duration observed up to the rollover window; open items are censored at the data cutoff
    cutoff = pd.Timestamp(cfg.settings["splits"]["data_cutoff"])
    observed = (cutoff - df["listing_date"]).dt.days.clip(lower=0)
    df["duration"] = np.where(df["status"] == "closed", np.minimum(df["days_listed"], w), np.minimum(observed, w))
    df["duration"] = np.maximum(df["duration"].round().astype(int), 1)
    df.loc[(df["status"] == "open") & (df["duration"] >= w), "status"] = "closed"   # window complete even if rollover open
    return df


def person_period(df: pd.DataFrame, max_rows: int) -> pd.DataFrame:
    reps = df["duration"].to_numpy()
    idx = np.repeat(np.arange(len(df)), reps)
    pp = df.iloc[idx].copy()
    day = np.concatenate([np.arange(1, r + 1) for r in reps])
    pp["day"] = day
    last = np.repeat(reps, reps) == day
    pp["y"] = (last & (np.repeat(df["event"].to_numpy(), reps) == 1)).astype(int)
    if len(pp) > max_rows:
        raise MemoryError(f"person-period table has {len(pp):,} rows > max {max_rows:,}; raise models.hazard.max_person_period_rows")
    return pp


class HazardModel:
    def __init__(self, cfg: Config, reg: Registry):
        self.cfg = cfg
        self.fb = FeatureBuilder(cfg, reg, "hazard")
        self.model = None
        self.iso = None

    def _X(self, pp: pd.DataFrame) -> pd.DataFrame:
        X = self.fb.transform(pp)
        X["premium_pct"] = pp["premium_pct"].to_numpy()
        X["day"] = pp["day"].to_numpy().astype(float)
        X["log_day"] = np.log(X["day"])
        return X

    def fit(self, items: pd.DataFrame):
        self.fb.fit(items)
        pp = person_period(items, self.cfg.model("hazard")["max_person_period_rows"])
        p = dict(self.cfg.model("hazard")["lgbm"]); p.update(random_state=self.cfg.settings["models"]["random_state"], n_jobs=4)
        self.model = lgb.LGBMClassifier(**p).fit(self._X(pp), pp["y"])
        return self

    def _raw_survival(self, base: pd.DataFrame, H: int) -> np.ndarray:
        S = np.ones((len(base), H))
        surv = np.ones(len(base))
        for d in range(1, H + 1):
            b = base.copy(); b["day"] = d
            surv = surv * (1 - self.model.predict_proba(self._X(b))[:, 1])
            S[:, d - 1] = surv
        return S

    def survival(self, items: pd.DataFrame, horizon: int | None = None, premium: float | None = None,
                 calibrated: bool = True) -> np.ndarray:
        """P(still unsold after day t) for t = 1..horizon; shape (n_items, horizon).

        Chaining boosted daily hazards over-states late-window sales because late-day hazards for
        high-propensity items are learned from few survivors. A proportional-hazards recalibration,
        S_cal(t) = S(t)^gamma, with gamma fitted so the window-end probability matches an isotonic
        map learned on a held-out calibration window, keeps the curve's shape and fixes its level.
        """
        H = horizon or self.cfg.econ("rollover_days")
        base = items.copy()
        if premium is not None:
            base["premium_pct"] = premium
        S = self._raw_survival(base, H)
        if calibrated and self.iso is not None:
            full = S if H == self.cfg.econ("rollover_days") else self._raw_survival(base, self.cfg.econ("rollover_days"))
            p = np.clip(1 - full[:, -1], 1e-4, 1 - 1e-4)
            pc = np.clip(self.iso.predict(p), 1e-3, 1 - 1e-3)
            gamma = np.log(1 - pc) / np.log(1 - p)
            S = np.power(S, gamma[:, None])
        return S

    def calibrate(self, calib: pd.DataFrame):
        """Fit the window-end calibration map on complete items from a held-out window."""
        c = calib[calib["status"] == "closed"]
        self.iso = None
        p = 1 - self._raw_survival(c, self.cfg.econ("rollover_days"))[:, -1]
        self.iso = IsotonicRegression(y_min=1e-3, y_max=1 - 1e-3, out_of_bounds="clip").fit(p, c["event"].to_numpy())
        return self

    def p_sold_within(self, items: pd.DataFrame, horizon: int | None = None, premium: float | None = None) -> np.ndarray:
        return 1 - self.survival(items, horizon, premium)[:, -1]


def evaluate_hazard(model: HazardModel, test: pd.DataFrame) -> dict:
    """Calibration of P(sold within window) on items whose window has fully elapsed, plus KM comparison."""
    H = model.cfg.econ("rollover_days")
    full = test[(test["duration"] >= H) | (test["event"] == 1)].copy()
    complete = test[test["status"] == "closed"]
    p = model.p_sold_within(complete)
    y = complete["event"].to_numpy()
    d = pd.DataFrame({"p": p, "y": y}); d["bin"] = pd.qcut(d.p, 8, duplicates="drop")
    cal = d.groupby("bin", observed=True).agg(n=("y", "size"), mean_pred=("p", "mean"), mean_actual=("y", "mean")).reset_index(drop=True)
    km = KaplanMeierFitter().fit(test["duration"], test["event"])
    S_km = float(km.predict(H))
    S_model = float(model.survival(test, H)[:, -1].mean())
    return {"calibration": cal, "km_p_sold_by_window": 1 - S_km, "model_p_sold_by_window": 1 - S_model,
            "brier": float(np.mean((p - y) ** 2)), "brier_constant": float(np.mean((y.mean() - y) ** 2)),
            "n": int(len(complete))}


def km_by(items: pd.DataFrame, col: str, horizon: int) -> pd.DataFrame:
    rows = []
    for k, g in items.groupby(col, observed=True):
        if len(g) < 100:
            continue
        km = KaplanMeierFitter().fit(g["duration"], g["event"])
        rows.append({col: k, "n": len(g), "p_sold_by_window": 1 - float(km.predict(horizon)),
                     "median_days": float(km.median_survival_time_) if np.isfinite(km.median_survival_time_) else np.nan})
    return pd.DataFrame(rows)
