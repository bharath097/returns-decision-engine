"""Model monitoring: input drift (PSI), performance by segment, retrain rule, model card."""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd


def psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    e, a = expected.dropna(), actual.dropna()
    if e.nunique() <= 1 or len(a) == 0:
        return 0.0
    if e.dtype.kind in "OUb" or str(e.dtype) == "category":
        cats = sorted(set(e.astype(str)) | set(a.astype(str)))
        pe = e.astype(str).value_counts(normalize=True).reindex(cats).fillna(0) + 1e-4
        pa = a.astype(str).value_counts(normalize=True).reindex(cats).fillna(0) + 1e-4
    else:
        qs = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
        qs[0], qs[-1] = -np.inf, np.inf
        pe = pd.Series(np.histogram(e, qs)[0] / len(e)) + 1e-4
        pa = pd.Series(np.histogram(a, qs)[0] / len(a)) + 1e-4
    return float(((pa - pe) * np.log(pa / pe)).sum())


def drift_table(train: pd.DataFrame, recent: pd.DataFrame, features: list, warn: float, alert: float) -> pd.DataFrame:
    rows = [{"feature": f, "psi": psi(train[f], recent[f])} for f in features if f in train and f in recent]
    df = pd.DataFrame(rows).sort_values("psi", ascending=False)
    df["flag"] = np.where(df.psi >= alert, "ALERT", np.where(df.psi >= warn, "warn", "ok"))
    return df.reset_index(drop=True)


def monthly_performance(df: pd.DataFrame, pred: np.ndarray, baseline: np.ndarray, month_col="listing_ym") -> pd.DataFrame:
    d = pd.DataFrame({"month": df[month_col].to_numpy(), "y": df["gross_recovery"].to_numpy(), "pred": pred, "base": baseline})
    d["ae"], d["ae_base"] = (d.pred - d.y).abs(), (d.base - d.y).abs()
    return d.groupby("month").agg(n=("y", "size"), actual=("y", "mean"), predicted=("pred", "mean"),
                                  mae=("ae", "mean"), mae_baseline=("ae_base", "mean")).reset_index()


def retrain_decision(monthly: pd.DataFrame, drift: pd.DataFrame, degradation_alert: float, min_months: int = 2) -> dict:
    ref = monthly.head(max(3, len(monthly) // 4))["mae"].mean()
    recent = monthly.tail(min_months)["mae"].mean()
    degr = recent / ref - 1
    alerts = drift[drift.flag == "ALERT"]["feature"].tolist()
    retrain = bool(degr > degradation_alert or len(alerts) > 0)
    return {"reference_mae": float(ref), "recent_mae": float(recent), "degradation_pct": float(degr),
            "alert_features": alerts, "retrain_recommended": retrain,
            "reason": ("MAE degraded beyond threshold" if degr > degradation_alert else
                       ("input drift above alert level" if alerts else "stable"))}


def model_card(name: str, intended_use: str, data: dict, metrics: dict, limits: list, extra: dict | None = None) -> dict:
    card = {"model": name, "generated": datetime.now().strftime("%Y-%m-%d %H:%M"), "intended_use": intended_use,
            "training_data": data, "metrics": metrics, "known_limitations": limits}
    if extra:
        card.update(extra)
    return json.loads(json.dumps(card, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o)))
