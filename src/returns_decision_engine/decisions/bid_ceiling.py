"""Lot bid ceiling and value of inspecting before bidding.

    ceiling = ( E[net value of lot] - inbound freight - k * sigma_lot ) / (1 + target margin)

E[net value] comes from the item-level lot model summed over the manifest (before the lot's price, which is sunk
at item level but is exactly what the ceiling decides). sigma_lot is the out-of-fold error of that prediction,
shrunk by source. Backtest: apply the ceiling to lots that were actually bought and compare outcomes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

from ..config import Config
from ..data.registry import Registry
from ..models import lot_model as L
from .utils import eb_shrink


def oof_lot_predictions(cfg: Config, reg: Registry, items: pd.DataFrame, folds: int = 5) -> pd.DataFrame:
    """Out-of-fold item predictions summed to lots, so every lot is scored by a model that never saw it."""
    pred = np.zeros(len(items))
    for a, b in GroupKFold(folds).split(items, groups=items["lot_id"]):
        m = L.LotModel(cfg, reg).fit(items.iloc[a])
        pred[b] = m.predict_item(items.iloc[b])
    d = items[["lot_id", "retail_value", "final_net_value"]].copy()
    d["pred"] = pred * d["retail_value"]
    lots = d.groupby("lot_id").agg(pred_nv=("pred", "sum"), actual_nv=("final_net_value", "sum"), lot_retail=("retail_value", "sum")).reset_index()
    meta = items.groupby("lot_id").agg(source_id=("source_id", "first"), source_type=("source_type", "first"), lot_price=("lot_price", "first"),
                                       inbound_freight=("inbound_freight", "first"), receipt_date=("receipt_date", "min"),
                                       n_items=("item_id", "size")).reset_index()
    out = lots.merge(meta, on="lot_id")
    out["err_rate"] = (out["actual_nv"] - out["pred_nv"]) / out["lot_retail"]
    return out


def sigma_by_source(lots: pd.DataFrame) -> pd.Series:
    g = lots.groupby("source_id")["err_rate"].agg(["std", "count"])
    pooled = lots["err_rate"].std()
    se = g["std"].fillna(pooled) / np.sqrt(g["count"].clip(lower=2))
    sh = eb_shrink(g["std"].fillna(pooled), se)
    return sh["shrunk"].clip(lower=pooled * 0.3)


def ceiling(expected_nv: float, freight: float, sigma_dollars: float, k: float, margin: float) -> float:
    return max(0.0, (expected_nv - freight - k * sigma_dollars) / (1 + margin))


def backtest(lots: pd.DataFrame, sig: pd.Series, cfg: Config) -> pd.DataFrame:
    k, m = cfg.decision("risk_buffer_k"), cfg.decision("lot_target_margin")
    d = lots.copy()
    d["sigma_rate"] = d["source_id"].map(sig).fillna(sig.median())
    d["ceiling"] = [ceiling(a, f, s * r, k, m) for a, f, s, r in zip(d.pred_nv, d.inbound_freight, d.sigma_rate, d.lot_retail)]
    d["actual_profit_at_listed_price"] = d["actual_nv"] - d["lot_price"] - d["inbound_freight"]
    rows = []

    def add(name, buy, price):
        profit = (d["actual_nv"] - price - d["inbound_freight"])[buy].sum()
        spend = price[buy].sum()
        rows.append({"policy": name, "lots_bought": int(buy.sum()), "lots_skipped": int((~buy).sum()),
                     "total_profit": float(profit), "spend": float(spend), "profit_per_spend_dollar": float(profit / spend) if spend else np.nan,
                     "profit_per_retail_dollar": float(profit / d.loc[buy, "lot_retail"].sum()) if buy.any() else np.nan})
    add("buy every lot at listed price (status quo)", pd.Series(True, index=d.index), d["lot_price"])
    add("buy only if listed price <= ceiling", d["lot_price"] <= d["ceiling"], d["lot_price"])
    for a in (0.25, 0.5, 1.0):
        rng = np.random.default_rng(7)
        accept = pd.Series(rng.random(len(d)) < a, index=d.index)
        over = d["lot_price"] > d["ceiling"]
        buy = (~over) | accept
        price = d["lot_price"].where(~over, d["ceiling"])
        add(f"counter at ceiling when over it; seller accepts {int(a * 100)}% of the time", buy, price)
    return pd.DataFrame(rows).assign(sample_lots=len(d))


def value_of_sampling(lot_items: int, lot_retail: float, sigma_rate: float, k: float, margin: float, minutes_per_item: float,
                      labor_per_minute: float, sample_sizes=(5, 10, 20, 40)) -> pd.DataFrame:
    """Opening n items removes their uncertainty: remainder sd scales with sqrt((N - n) / N)."""
    sd0 = sigma_rate * lot_retail
    rows = []
    for n in sample_sizes:
        if n >= lot_items:
            continue
        sd1 = sd0 * np.sqrt((lot_items - n) / lot_items)
        gain = k * (sd0 - sd1) / (1 + margin)
        cost = n * minutes_per_item * labor_per_minute
        rows.append({"lot_items": lot_items, "lot_retail": lot_retail, "sampled": n, "sigma_before": sd0, "sigma_after": sd1,
                     "ceiling_gain": gain, "inspection_cost": cost, "net_value_of_sampling": gain - cost, "worth_it": gain > cost})
    return pd.DataFrame(rows)


def ceiling_sweep(lots: pd.DataFrame, sig: pd.Series, ks=(0.0, 0.4, 0.8, 1.2), margins=(0.0, 0.06, 0.12, 0.20), accept: float = 0.5, seed: int = 7) -> pd.DataFrame:
    """Profit and capital efficiency across risk-buffer k and target margin: shows the cost of being conservative.

    Policy: buy at the listed price when it is at or under the ceiling; otherwise counter at the ceiling and the seller
    accepts with probability `accept` (an assumption - replace it with your own negotiation history).
    """
    rng = np.random.default_rng(seed)
    acc = rng.random(len(lots)) < accept
    rows = []
    sr = lots["source_id"].map(sig).fillna(sig.median())
    for k in ks:
        for m in margins:
            ceil = np.array([ceiling(a, f, s * r, k, m) for a, f, s, r in zip(lots.pred_nv, lots.inbound_freight, sr, lots.lot_retail)])
            over = lots["lot_price"].to_numpy() > ceil
            buy = (~over) | acc
            price = np.where(over, ceil, lots["lot_price"].to_numpy())
            profit = (lots["actual_nv"].to_numpy() - price - lots["inbound_freight"].to_numpy())[buy].sum()
            spend = price[buy].sum()
            rows.append({"risk_buffer_k": k, "target_margin": m, "lots_bought": int(buy.sum()), "spend": float(spend),
                         "total_profit": float(profit), "profit_per_spend": float(profit / spend) if spend else np.nan,
                         "share_of_lots_over_ceiling": float(over.mean())})
    return pd.DataFrame(rows)
