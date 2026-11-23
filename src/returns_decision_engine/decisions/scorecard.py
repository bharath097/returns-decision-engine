"""Source scorecard: points, tiers and negotiation headroom per source.

Each lot is one noisy observation of its source's quality, so raw source means are shrunk toward the pooled mean
(empirical Bayes) before they become points. Sources with few lots move less than sources with many.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config
from .utils import eb_shrink, percentile_points


def lot_frame(con) -> pd.DataFrame:
    d = con.execute("""
        select l.lot_id, l.source_id, l.source_type, l.receipt_date, l.lot_price, l.inbound_freight, l.lot_retail_total, l.acquisition_rate,
               l.net_revenue, l.final_net_value, l.lot_profit, l.profit_per_retail_dollar,
               m.manifest_flag, m.manifest_retail_total_recorded, m.avg_days
        from mart_lot l
        join (select lot_id, any_value(manifest_flag) as manifest_flag,
                     avg(days_listed) as avg_days,
                     any_value(lot_retail_total) as manifest_retail_total_recorded
              from mart_item group by 1) m using (lot_id)
        where l.lot_complete""").df()
    man = con.execute("select lot_id, manifest_retail_total from stg_lots").df()
    d = d.merge(man, on="lot_id", how="left")
    d["nv_rate"] = d["final_net_value"] / d["lot_retail_total"]
    d["freight_rate"] = d["inbound_freight"] / d["lot_retail_total"]
    d["manifest_abs_error"] = (d["manifest_retail_total"] - d["lot_retail_total"]).abs() / d["lot_retail_total"]
    return d


def _src_stat(d: pd.DataFrame, col: str) -> pd.DataFrame:
    g = d.groupby("source_id")[col].agg(["mean", "std", "count"])
    pooled_sd = np.sqrt((g["std"].fillna(g["std"].median()) ** 2 * (g["count"] - 1)).sum() / (g["count"] - 1).sum())
    se = (g["std"].fillna(pooled_sd).clip(lower=pooled_sd * 0.5)) / np.sqrt(g["count"])
    return eb_shrink(g["mean"], se).rename(columns=lambda c: f"{col}_{c}")


def scorecard(lots: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    w = cfg.decision("scorecard_weights")
    assert abs(sum(w.values()) - 1) < 1e-6, "scorecard_weights must sum to 1"
    profit = _src_stat(lots, "profit_per_retail_dollar")
    nv = _src_stat(lots, "nv_rate")
    meta = lots.groupby("source_id").agg(source_type=("source_type", "first"), lots=("lot_id", "size"),
                                         retail_bought=("lot_retail_total", "sum"), raw_profit=("lot_profit", "sum"),
                                         avg_price_rate=("acquisition_rate", "mean"), avg_freight_rate=("freight_rate", "mean"),
                                         spread=("profit_per_retail_dollar", "std"), avg_days=("avg_days", "mean"),
                                         manifest_error=("manifest_abs_error", "mean"))
    s = meta.join(profit).join(nv)
    s["manifest_error"] = s["manifest_error"].fillna(s["manifest_error"].median())
    pts = pd.DataFrame({
        "profitability": percentile_points(s["profit_per_retail_dollar_shrunk"]),
        "goods_quality": percentile_points(s["nv_rate_shrunk"]),
        "reliability": percentile_points(s["spread"].fillna(s["spread"].median()), higher_is_better=False),
        "manifest_accuracy": percentile_points(s["manifest_error"], higher_is_better=False),
        "speed": percentile_points(s["avg_days"], higher_is_better=False)})
    s = s.join(pts.add_prefix("pts_"))
    s["score"] = sum(w[k] * pts[k] for k in w)
    t = cfg.decision("scorecard_tiers")
    s["tier"] = np.select([s.score >= t["A"], s.score >= t["B"], s.score >= t["C"]], ["A", "B", "C"], "D")
    # negotiation headroom: the price rate that still hits the target margin, versus what we pay today
    m, k = cfg.decision("lot_target_margin"), cfg.decision("risk_buffer_k")
    sd_nv = lots.groupby("source_id")["nv_rate"].std().reindex(s.index).fillna(lots["nv_rate"].std())
    s["ceiling_price_rate"] = (s["nv_rate_shrunk"] - s["avg_freight_rate"] - k * sd_nv) / (1 + m)
    s["headroom_price_rate"] = s["ceiling_price_rate"] - s["avg_price_rate"]
    s["negotiation_lever"] = np.where(s["headroom_price_rate"] < 0, "push price down", "room to pay more / volume deal")
    s["confidence"] = np.where(s["lots"] >= 25, "high", np.where(s["lots"] >= 12, "medium", "low"))
    return s.reset_index().sort_values("score", ascending=False)
