from __future__ import annotations

import numpy as np
import pandas as pd


def eb_shrink(est: pd.Series, se: pd.Series) -> pd.DataFrame:
    """Normal-normal empirical-Bayes shrinkage (DerSimonian-Laird tau^2). Returns pooled, shrunk and the shrink weight."""
    est, se = est.astype(float), se.astype(float).clip(lower=1e-9)
    w = 1 / se ** 2
    pooled = (w * est).sum() / w.sum()
    k = len(est)
    Q = (w * (est - pooled) ** 2).sum()
    denom = w.sum() - (w ** 2).sum() / w.sum()
    tau2 = max(0.0, (Q - (k - 1)) / denom) if k > 1 and denom > 0 else 0.0
    b = tau2 / (tau2 + se ** 2)
    return pd.DataFrame({"est": est, "se": se, "pooled": pooled, "tau2": tau2, "weight_on_own": b,
                         "shrunk": pooled + b * (est - pooled)}, index=est.index)


def percentile_points(x: pd.Series, higher_is_better: bool = True) -> pd.Series:
    r = x.rank(pct=True, method="average")
    return (r if higher_is_better else (1 - r + 1 / len(x))) * 100
