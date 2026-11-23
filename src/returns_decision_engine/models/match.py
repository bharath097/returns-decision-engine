"""Retail-match quality model.

Recovery is measured against the recorded retail value, so a wrong catalog match corrupts the
target and the price the production model recommends. A small audited sample (human-verified
matches) trains a classifier for P(match is wrong); flagged items go to a review queue, ranked
by expected dollars at risk.
"""
from __future__ import annotations

import re

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.model_selection import GroupKFold

from ..config import Config

_tok = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set:
    return set(_tok.findall((s or "").lower()))


def match_features(df: pd.DataFrame) -> pd.DataFrame:
    a = df["title"].fillna("").map(_tokens)
    b = df["matched_title"].fillna("").map(_tokens)
    inter = np.array([len(x & y) for x, y in zip(a, b)], float)
    union = np.array([len(x | y) for x, y in zip(a, b)], float)
    # the listing title carries an extra colour word the catalog title does not: drop one token of slack
    ta = df["title"].fillna("").str.split().str[:-1].str.join(" ")
    exact_prefix = (ta.values == df["matched_title"].fillna("").values).astype(float)
    brand_a = df["title"].fillna("").str.split().str[0]
    brand_b = df["matched_title"].fillna("").str.split().str[0]
    X = pd.DataFrame({
        "jaccard": inter / np.maximum(union, 1), "overlap_a": inter / np.maximum(np.array([len(x) for x in a]), 1),
        "exact_prefix": exact_prefix, "same_first_token": (brand_a.values == brand_b.values).astype(float),
        "match_confidence": df["match_confidence"].astype(float).values,
        "log_retail": np.log(df["retail_value"].astype(float).values),
        "manifest": df["manifest_flag"].astype(float).values}, index=df.index)
    return X


def load_audited(con) -> pd.DataFrame:
    return con.execute("""select m.*, a.match_correct as audited_correct
                          from mart_item m join raw_item_audit a using (item_id)""").df()


def fit_match(cfg: Config, audited: pd.DataFrame):
    X = match_features(audited)
    y = (~audited["audited_correct"].astype(bool)).astype(int)        # 1 = WRONG match
    p = dict(cfg.model("match")["lgbm"]); p.update(random_state=cfg.settings["models"]["random_state"], n_jobs=4)
    return lgb.LGBMClassifier(**p).fit(X, y)


def cv_report(cfg: Config, audited: pd.DataFrame) -> dict:
    X = match_features(audited); y = (~audited["audited_correct"].astype(bool)).astype(int).to_numpy()
    p = np.zeros(len(y))
    for a, b in GroupKFold(5).split(X, y, groups=audited["lot_id"]):
        m = lgb.LGBMClassifier(**{**cfg.model("match")["lgbm"], "random_state": 1, "n_jobs": 4}).fit(X.iloc[a], y[a])
        p[b] = m.predict_proba(X.iloc[b])[:, 1]
    base_conf = 1 - audited["match_confidence"].to_numpy()
    return {"n_audited": int(len(y)), "wrong_rate": float(y.mean()), "auc_model": float(roc_auc_score(y, p)),
            "auc_confidence_only": float(roc_auc_score(y, base_conf)), "avg_precision_model": float(average_precision_score(y, p)),
            "avg_precision_confidence_only": float(average_precision_score(y, base_conf))}


def review_queue_gain(items: pd.DataFrame, p_wrong: np.ndarray, truth_retail: np.ndarray, is_wrong: np.ndarray) -> pd.DataFrame:
    """Share of the total mis-recorded dollar error captured by reviewing the top-k% of items (ranked by risk x retail).

    Dollar error counts only genuinely wrong matches (|recorded - true retail|); ordinary price noise is not a match error.
    """
    wrong = np.asarray(is_wrong, bool)
    err = np.abs(items["retail_value"].to_numpy() - truth_retail) * wrong
    risk = p_wrong * items["retail_value"].to_numpy()
    order = np.argsort(-risk)
    cum = np.cumsum(err[order]) / max(err.sum(), 1e-9)
    cumw = np.cumsum(wrong[order]) / max(wrong.sum(), 1)
    n = len(items)
    rows = []
    for k in [0.01, 0.02, 0.05, 0.10, 0.20, 0.30]:
        i = max(int(n * k), 1)
        rows.append({"review_share": k, "items_reviewed": i, "share_of_dollar_error_captured": float(cum[i - 1]),
                     "share_of_wrong_matches_found": float(cumw[i - 1]), "random_review_would_find": k})
    return pd.DataFrame(rows)
