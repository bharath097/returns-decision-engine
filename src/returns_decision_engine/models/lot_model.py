"""Lot recovery model: expected net value per retail dollar from receipt-time features.

Trained at the item level (so it can price any manifest) and rolled up to lots. Net value here is
before the lot's purchase price, so ``expected lot net value - lot price`` is the expected profit.
Evaluated on later lots (time split by receipt date).
"""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..config import Config
from ..data.registry import Registry
from .features import FeatureBuilder


def load_items(con) -> pd.DataFrame:
    df = con.execute("select * from mart_item where status = 'closed'").df()
    df["receipt_date"] = pd.to_datetime(df["receipt_date"])
    df["v"] = df["final_net_value"] / df["retail_value"]
    return df


class LotModel:
    def __init__(self, cfg: Config, reg: Registry):
        self.cfg, self.fb, self.m = cfg, FeatureBuilder(cfg, reg, "lot", n_text=0), None

    def fit(self, items: pd.DataFrame):
        self.fb.fit(items)
        p = dict(self.cfg.model("recovery")["lgbm_regressor"]); p.update(n_estimators=300, random_state=1, n_jobs=4)
        self.m = lgb.LGBMRegressor(**p).fit(self.fb.transform(items), items["v"], sample_weight=np.sqrt(items["retail_value"]))
        return self

    def predict_item(self, items: pd.DataFrame) -> np.ndarray:
        return self.m.predict(self.fb.transform(items))

    def predict_lot(self, items: pd.DataFrame) -> pd.DataFrame:
        d = items[["lot_id", "retail_value"]].copy()
        d["pred_value"] = self.predict_item(items) * d["retail_value"]
        return d.groupby("lot_id").agg(pred_net_value=("pred_value", "sum"), lot_retail=("retail_value", "sum")).reset_index()


def lot_actuals(items: pd.DataFrame) -> pd.DataFrame:
    g = items.groupby("lot_id").agg(actual_net_value=("final_net_value", "sum"), lot_retail=("retail_value", "sum"),
                                    lot_price=("lot_price", "first"), inbound_freight=("inbound_freight", "first"),
                                    source_id=("source_id", "first"), source_type=("source_type", "first"),
                                    receipt_date=("receipt_date", "min")).reset_index()
    return g
