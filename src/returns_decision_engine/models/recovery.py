"""Recovery-rate model.

Target: gross recovery = sale price / retail value for AUCTION-listed items (a zero is a zero).

Two-part (hurdle) model so zeros are modelled, not averaged away:
    E[recovery] = P(sold) * E[recovery | sold]
with a calibration step on a held-out window, lot-grouped cross-validation, and split-conformal
prediction intervals (conformalized quantile regression) so every prediction carries a range.
A naive sold-only model is trained alongside to show how much it overstates.
"""
from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score, log_loss

from ..config import Config
from ..data.registry import Registry
from .features import FeatureBuilder


def load_auction_items(con) -> pd.DataFrame:
    df = con.execute("""
        select m.*, t.x_true, t.p_sell_true, t.e_rec_sold_true, t.expected_net_value as expected_net_value_true
        from mart_item m left join truth_items t using (item_id)
        where m.channel = 'auction' and m.status = 'closed'
    """).df()
    df["listing_date"] = pd.to_datetime(df["listing_date"])
    return df


def split_by_time(cfg: Config, df: pd.DataFrame, date_col="listing_date"):
    s = cfg.settings["splits"]
    d = pd.to_datetime(df[date_col])
    tr = d <= pd.Timestamp(s["train_end"])
    ca = (d > pd.Timestamp(s["train_end"])) & (d <= pd.Timestamp(s["calibration_end"]))
    te = d > pd.Timestamp(s["calibration_end"])
    return df[tr], df[ca], df[te]


def _params(cfg, key):
    p = dict(cfg.model("recovery")[key]); p["random_state"] = cfg.settings["models"]["random_state"]; p["n_jobs"] = 4
    return p


@dataclass
class RecoveryModel:
    cfg: Config
    fb: FeatureBuilder
    clf: lgb.LGBMClassifier
    reg: lgb.LGBMRegressor
    q_lo: lgb.LGBMRegressor
    q_hi: lgb.LGBMRegressor
    iso: IsotonicRegression | None
    q_hat: float
    naive: lgb.LGBMRegressor

    # --------------------------------------------------------------- inference
    def predict_parts(self, df: pd.DataFrame) -> pd.DataFrame:
        X = self.fb.transform(df)
        lo, hi = self.cfg.model("recovery")["clip_low"], self.cfg.model("recovery")["clip_high"]
        p = self.clf.predict_proba(X)[:, 1]
        e = np.clip(self.reg.predict(X), lo, hi)
        out = pd.DataFrame({"p_sell": p, "e_given_sold": e}, index=df.index)
        out["pred_raw"] = p * e
        out["pred"] = np.clip(self.iso.predict(out["pred_raw"]) if self.iso is not None else out["pred_raw"], 0, hi)
        return out

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.predict_parts(df)["pred"].to_numpy()

    def predict_interval(self, df: pd.DataFrame) -> pd.DataFrame:
        X = self.fb.transform(df)
        lo = self.q_lo.predict(X) - self.q_hat
        hi = self.q_hi.predict(X) + self.q_hat
        pred = self.predict(df)
        out = pd.DataFrame({"pred": pred, "lo": np.clip(np.minimum(lo, pred), 0, 1), "hi": np.clip(np.maximum(hi, pred), 0, 1)},
                           index=df.index)
        return out

    def predict_naive(self, df: pd.DataFrame) -> np.ndarray:
        return np.clip(self.naive.predict(self.fb.transform(df)), 0, 1)

    def feature_importance(self) -> pd.DataFrame:
        names = self.fb.names
        imp_c = pd.Series(self.clf.booster_.feature_importance("gain"), index=names)
        imp_r = pd.Series(self.reg.booster_.feature_importance("gain"), index=names)
        df = pd.DataFrame({"gain_sell_model": imp_c / imp_c.sum(), "gain_price_model": imp_r / imp_r.sum()})
        df["importance"] = 0.5 * (df.gain_sell_model + df.gain_price_model)
        return df.sort_values("importance", ascending=False)


def fit_recovery(cfg: Config, reg: Registry, train: pd.DataFrame, calib: pd.DataFrame) -> RecoveryModel:
    alpha = cfg.model("recovery")["interval_alpha"]
    fb = FeatureBuilder(cfg, reg, "recovery").fit(train)
    Xtr, ytr = fb.transform(train), train["gross_recovery"].to_numpy()
    sold = train["sold"].astype(bool).to_numpy()
    clf = lgb.LGBMClassifier(**_params(cfg, "lgbm_classifier")).fit(Xtr, sold.astype(int))
    regr = lgb.LGBMRegressor(**_params(cfg, "lgbm_regressor")).fit(Xtr[sold], ytr[sold])
    naive = lgb.LGBMRegressor(**_params(cfg, "lgbm_regressor")).fit(Xtr[sold], ytr[sold])
    qp = _params(cfg, "lgbm_quantile")
    q_lo = lgb.LGBMRegressor(objective="quantile", alpha=alpha / 2, **qp).fit(Xtr, ytr)
    q_hi = lgb.LGBMRegressor(objective="quantile", alpha=1 - alpha / 2, **qp).fit(Xtr, ytr)
    m = RecoveryModel(cfg, fb, clf, regr, q_lo, q_hi, None, 0.0, naive)
    # calibration window: isotonic recalibration of the point prediction, then CQR conformal width
    parts = m.predict_parts(calib)
    iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(parts["pred_raw"], calib["gross_recovery"])
    m.iso = iso
    Xc = fb.transform(calib)
    yc = calib["gross_recovery"].to_numpy()
    score = np.maximum(q_lo.predict(Xc) - yc, yc - q_hi.predict(Xc))
    n = len(score)
    level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    m.q_hat = float(np.quantile(score, level))
    return m


# ------------------------------------------------------------------------------- evaluation
def calibration_table(pred: np.ndarray, y: np.ndarray, bins: int = 10) -> pd.DataFrame:
    q = pd.qcut(pred, bins, duplicates="drop")
    d = pd.DataFrame({"pred": pred, "y": y, "bin": q})
    return d.groupby("bin", observed=True).agg(n=("y", "size"), mean_pred=("pred", "mean"), mean_actual=("y", "mean")).reset_index(drop=True)


def evaluate(m: RecoveryModel, test: pd.DataFrame, baseline_by_cat: pd.Series) -> dict:
    y = test["gross_recovery"].to_numpy()
    parts = m.predict_parts(test)
    iv = m.predict_interval(test)
    base = test["category"].map(baseline_by_cat).fillna(baseline_by_cat.mean()).to_numpy()
    prod = test["prod_pred_expected_auction_recovery"].to_numpy()
    naive = m.predict_naive(test)
    rv = test["retail_value"].to_numpy()

    def block(p):
        return {"mae": float(np.mean(np.abs(p - y))), "rmse": float(np.sqrt(np.mean((p - y) ** 2))),
                "bias": float(np.mean(p - y)),
                "dollar_mae_per_item": float(np.mean(np.abs(p - y) * rv)),
                "weighted_total_error_pct": float((p * rv).sum() / (y * rv).sum() - 1)}
    res = {"n_test": int(len(test)),
           "model": block(parts["pred"].to_numpy()),
           "category_median_baseline": block(base),
           "current_production_model": block(prod),
           "naive_sold_only_model": block(naive),
           "auc_sold": float(roc_auc_score(test["sold"].astype(int), parts["p_sell"])),
           "logloss_sold": float(log_loss(test["sold"].astype(int), np.clip(parts["p_sell"], 1e-6, 1 - 1e-6))),
           "interval_coverage": float(np.mean((y >= iv["lo"]) & (y <= iv["hi"]))),
           "interval_target": 1 - m.cfg.model("recovery")["interval_alpha"],
           "interval_mean_width": float((iv["hi"] - iv["lo"]).mean())}
    if "x_true" in test and test["x_true"].notna().all():
        xt = test["x_true"].to_numpy()
        res["vs_truth_expected_recovery"] = {
            "model_mae": float(np.mean(np.abs(parts["pred"] - xt))),
            "baseline_mae": float(np.mean(np.abs(base - xt))),
            "production_mae": float(np.mean(np.abs(prod - xt))),
            "model_corr": float(np.corrcoef(parts["pred"], xt)[0, 1])}
    return res


def segment_errors(m: RecoveryModel, test: pd.DataFrame, by: str, min_n: int = 100) -> pd.DataFrame:
    d = test[[by, "gross_recovery", "retail_value"]].copy()
    d["pred"] = m.predict(test)
    d["prod"] = test["prod_pred_expected_auction_recovery"].to_numpy()
    d["ae"] = (d.pred - d.gross_recovery).abs()
    d["ae_prod"] = (d["prod"] - d.gross_recovery).abs()
    g = d.groupby(by, observed=True).agg(n=("ae", "size"), actual=("gross_recovery", "mean"), pred=("pred", "mean"),
                                         mae=("ae", "mean"), mae_production=("ae_prod", "mean"))
    return g[g.n >= min_n].reset_index()


def grouped_cv(cfg: Config, reg: Registry, train: pd.DataFrame, folds: int | None = None) -> pd.DataFrame:
    """Lot-grouped K-fold: items of a lot never straddle train/validation (they share condition and price)."""
    folds = folds or cfg.settings["splits"]["grouped_cv_folds"]
    rows = []
    for k, (a, b) in enumerate(GroupKFold(folds).split(train, groups=train["lot_id"])):
        tr, va = train.iloc[a], train.iloc[b]
        half = int(len(tr) * 0.85)
        tr = tr.sort_values("listing_date"); fit_part, cal_part = tr.iloc[:half], tr.iloc[half:]
        m = fit_recovery(cfg, reg, fit_part, cal_part)
        p = m.predict(va)
        y = va["gross_recovery"].to_numpy()
        rows.append({"fold": k, "n": len(va), "mae": float(np.mean(np.abs(p - y))),
                     "baseline_mae": float(np.mean(np.abs(va["category"].map(fit_part.groupby("category")["gross_recovery"].mean()).fillna(y.mean()) - y)))})
    return pd.DataFrame(rows)


def naive_leakage_demo(cfg: Config, reg: Registry, train: pd.DataFrame, test: pd.DataFrame) -> dict:
    """How wrong is a model trained on sold items only? (The usual silent failure.)"""
    m = fit_recovery(cfg, reg, train, train.sort_values("listing_date").iloc[-3000:])
    y = test["gross_recovery"].mean()
    return {"actual_mean_recovery_all_listed": float(y),
            "naive_sold_only_mean_prediction": float(m.predict_naive(test).mean()),
            "two_part_mean_prediction": float(m.predict(test).mean()),
            "naive_overstatement_pct": float(m.predict_naive(test).mean() / y - 1)}
