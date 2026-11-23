"""The pipeline: named stages that run in order, each declaring what it needs and what it produces.

    raw data -> warehouse (+ quality gate) -> models -> decisions -> decision engine -> monitoring -> metric layer -> outputs

Design rules
  * A stage is a function of a shared Context. It writes tables/scalars into `ctx.res` and anything later stages need into `ctx.s`.
  * The warehouse stage is a gate: if any error-severity data test fails, nothing downstream runs.
  * After the stages, `finish()` saves trained models, writes `run_manifest.json` (what data and config produced these numbers),
    `scalars.json` (headline numbers for the report builder) and appends one row to `run_history.csv`.
Run:  python -m returns_decision_engine.cli run     (or `make run`)
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import engine as ENG
from .config import Config
from .data.registry import Registry, run_calculations
from .data.warehouse import build_warehouse, reconciliation
from .decisions import bid_ceiling as B, channel as C, effort as E, impact as I, scorecard as S, waiting as W
from .metrics.clarify import MetricLayer
from .models import hazard as H, lot_model as L, match as M, monitor as MON, recovery as R, uplift as U


class PipelineError(RuntimeError):
    """Raised when a gate fails; nothing downstream is trusted."""


@dataclass
class Results:
    tables: dict = field(default_factory=dict)
    scalars: dict = field(default_factory=dict)
    cards: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    stages: list = field(default_factory=list)
    models: dict = field(default_factory=dict)

    def t(self, name, df):
        self.tables[name] = df
        return df


@dataclass
class Context:
    cfg: Config
    res: Results
    reg: Registry | None = None
    con: duckdb.DuckDBPyConnection | None = None
    s: dict = field(default_factory=dict)      # state handed from one stage to the next
    log: callable = print


STAGES: list = []


def stage(name: str, purpose: str, needs: str, makes: str):
    def deco(fn):
        STAGES.append(dict(name=name, purpose=purpose, needs=needs, makes=makes, fn=fn)); return fn
    return deco


# ============================================================================================ warehouse + gate
def stage_warehouse(c: Context, rebuild: bool):
    cfg, res = c.cfg, c.res
    if rebuild:
        w = build_warehouse(cfg, verbose=False)
        c.reg = w["registry"]
        res.t("data_quality_tests", w["tests"]); res.t("duplicate_reconciliation", reconciliation(w["con"], cfg))
        res.scalars["warehouse_log"] = w["log"]; w["con"].close()
        bad = w["tests"][w["tests"]["status"] == "FAIL"]
        if len(bad):
            raise PipelineError("data-quality gate failed: " + ", ".join(f"{r.test} ({r.failing_rows} rows)" for r in bad.itertuples()))
    else:
        c.reg = Registry(cfg)
    c.con = duckdb.connect(str(cfg.warehouse_path), read_only=True)
    res.t("variable_registry", c.reg.to_frame().drop(columns=["derive", "source"], errors="ignore"))
    res.t("data_profile", c.con.execute("""select 'items' as table_name, count(*) as rows, count(*) filter (where status='closed') as closed, count(*) filter (where status='open') as open from mart_item
        union all select 'lots', count(*), count(*) filter (where lot_complete), count(*) filter (where not lot_complete) from mart_lot""").df())
    res.t("calculations", run_calculations(c.con, cfg))


# ============================================================================================ stages
@stage("recovery_model", "Predict recovery (sale price / retail value, zeros included) for an item before it is listed",
       "mart_item (auction items)", "recovery_metrics, recovery_calibration, interval_coverage_by_category, ...")
def recovery_model(c: Context):
    cfg, res, con, reg = c.cfg, c.res, c.con, c.reg
    df = R.load_auction_items(con)
    tr, ca, te = R.split_by_time(cfg, df)
    m = R.fit_recovery(cfg, reg, tr, ca)
    base = tr.groupby("category")["gross_recovery"].mean()
    ev = R.evaluate(m, te, base)
    res.scalars["recovery_eval"] = ev
    rows = [{"model": k, **ev[k]} for k in ("model", "category_median_baseline", "current_production_model", "naive_sold_only_model")]
    res.t("recovery_metrics", pd.DataFrame(rows).replace({"model": {"model": "two-part model (new)", "category_median_baseline": "category average",
                                                                      "current_production_model": "incumbent (category x condition lookup)", "naive_sold_only_model": "naive sold-only model"}}))
    res.t("recovery_feature_importance", m.feature_importance().reset_index().rename(columns={"index": "feature"}))
    pred_te = m.predict(te)
    res.t("recovery_calibration", R.calibration_table(pred_te, te["gross_recovery"].to_numpy()))
    for by in ("category", "condition", "source_type"):
        res.t(f"recovery_error_by_{by}", R.segment_errors(m, te, by, cfg.model("monitoring")["min_segment_items"]))
    res.t("recovery_grouped_cv", R.grouped_cv(cfg, reg, tr, 3))
    res.scalars["naive_demo"] = {"actual_mean": float(te["gross_recovery"].mean()), "naive_sold_only_mean": float(m.predict_naive(te).mean()), "two_part_mean": float(pred_te.mean())}
    iv = m.predict_interval(te)
    res.t("recovery_intervals_sample", pd.concat([te[["item_id", "category", "retail_value", "gross_recovery"]].reset_index(drop=True), iv.reset_index(drop=True)], axis=1).head(300))
    te_iv = pd.concat([te[["category", "retail_value", "gross_recovery"]].reset_index(drop=True), iv.reset_index(drop=True)], axis=1)
    te_iv["covered"] = (te_iv.gross_recovery >= te_iv.lo) & (te_iv.gross_recovery <= te_iv.hi)
    res.t("interval_coverage_by_category", te_iv.groupby("category").agg(n=("covered", "size"), coverage=("covered", "mean"), width=("hi", "mean")).reset_index())
    c.s.update(df=df, tr=tr, ca=ca, te=te, m=m, base=base, ev=ev, pred_te=pred_te)
    res.models["recovery"] = m


@stage("anchor_impact", "Turn the recovery estimate into dollars: what is a better price anchor worth?",
       "recovery model, fixed-price items with hidden truth", "pricing_anchor_impact")
def anchor_impact(c: Context):
    cfg, res, con, m = c.cfg, c.res, c.con, c.s["m"]
    ci = W.category_inputs(con, cfg)
    fx_truth = con.execute("""select m.*, t.h0, t.elast, t.kappa, t.decay_d, t.market_value, t.e_rec_sold_true from mart_item m join truth_items t using(item_id)
        where m.channel = 'fixed_price' and m.listing_date > date '%s'""" % cfg.settings["splits"]["calibration_end"]).df()
    fx_truth["anchor_new"] = m.predict_parts(fx_truth)["e_given_sold"].to_numpy()
    fx_truth["anchor_old"] = fx_truth["prod_pred_expected_auction_recovery"]
    fx_truth["anchor_oracle"] = fx_truth["e_rec_sold_true"].clip(lower=0.02)
    imp = []
    for prem in (0.0, 0.10, 0.20, 0.30):
        r = I.pricing_impact(fx_truth, {"incumbent": "anchor_old", "new model": "anchor_new", "oracle (item-level truth, upper bound)": "anchor_oracle"}, ci, cfg, premium=prem)
        imp.append(r.assign(premium=prem))
    imp = pd.concat(imp, ignore_index=True)
    months = fx_truth["listing_date"].astype("datetime64[ns]").dt.to_period("M").nunique()
    imp["items_per_month"] = len(fx_truth) / months
    imp["gain_per_month"] = imp["gain_vs_first_per_item"] * imp["items_per_month"]
    imp["lo95_month"] = imp["lo95"] * imp["items_per_month"]; imp["hi95_month"] = imp["hi95"] * imp["items_per_month"]
    res.t("pricing_anchor_impact", imp)


@stage("sale_timing", "How fast does a fixed-price item sell at each price? (discrete-time hazard model)",
       "fixed-price items from the randomized pilot", "hazard_calibration, sale_curves_by_premium")
def sale_timing(c: Context):
    cfg, res, con, reg = c.cfg, c.res, c.con, c.reg
    fx = H.load_fixed_items(con, cfg)
    ps = cfg.settings["pilot_splits"]
    ftr = fx[fx.listing_date <= ps["train_end"]]; fca = fx[(fx.listing_date > ps["train_end"]) & (fx.listing_date <= ps["calibration_end"])]
    fte = fx[fx.listing_date > ps["calibration_end"]]
    hm = H.HazardModel(cfg, reg).fit(ftr)
    raw = H.evaluate_hazard(hm, fte); hm.calibrate(fca); cal = H.evaluate_hazard(hm, fte)
    res.scalars["hazard_eval"] = {"km_p_sold": cal["km_p_sold_by_window"], "model_p_sold_calibrated": cal["model_p_sold_by_window"],
                                  "model_p_sold_raw": raw["model_p_sold_by_window"], "brier": cal["brier"], "brier_constant": cal["brier_constant"], "n": cal["n"]}
    res.t("hazard_calibration", cal["calibration"])
    res.t("km_by_premium", H.km_by(fx, "premium_pct", cfg.econ("rollover_days")))
    H_ = cfg.econ("rollover_days")
    curves = {f"+{int(p * 100)}%": 1 - hm.survival(fte.head(2500), H_, premium=p).mean(axis=0) for p in (0.1, 0.2, 0.3)}
    res.t("sale_curves_by_premium", pd.DataFrame({"day": range(1, H_ + 1), **curves}))
    mid = fte.listing_date.quantile(0.5)
    hm2 = H.HazardModel(cfg, reg); hm2.fb, hm2.model = hm.fb, hm.model
    hm2.calibrate(pd.concat([fca, fte[fte.listing_date <= mid]]))
    late = fte[fte.listing_date > mid]
    res.scalars["hazard_rolling"] = {"before_refresh": H.evaluate_hazard(hm, late)["model_p_sold_by_window"], "after_refresh": H.evaluate_hazard(hm2, late)["model_p_sold_by_window"],
                                     "actual_km": H.evaluate_hazard(hm, late)["km_p_sold_by_window"]}
    c.s.update(fx=fx, hm=hm); res.models["sale_timing"] = hm


@stage("channel_and_waiting", "Auction or fixed price? Which items? How long to wait and at what price?",
       "randomized pilot, hazard model", "pilot_ate*, policy_comparison, waiting_*")
def channel_and_waiting(c: Context):
    cfg, res, con, reg, fx = c.cfg, c.res, c.con, c.reg, c.s["fx"]
    pil = U.load_pilot(con, cfg)
    p_treat = float(pil["T"].mean())
    res.t("zero_problem_three_views", C.three_views(pil))
    res.t("pilot_ate", U.ate_table(pil)); res.t("pilot_ate_by_category", U.ate_table(pil, "category")); res.t("pilot_premium_table", U.premium_table(pil))
    res.t("pilot_balance", C.balance_table(pil, "T", ["retail_value", "product_age_years", "match_confidence"], ["category", "condition", "source_type"]))
    sd = float(pil["y"].std()); res.scalars["pilot_sd"] = sd
    res.t("required_sample", pd.DataFrame([{"detectable_effect_per_retail_dollar": d, "items_per_arm": C.required_n_two_means(sd, d)} for d in (0.005, 0.01, 0.02, 0.03)]))
    res.t("breakeven_table", C.breakeven_table([0.1, 0.2, 0.3], 100.0, [0, 5, 10, 20]))
    res.scalars["five_item_story"] = C.story_five_items()
    um = U.UpliftModel(cfg, reg); ups = um.cross_fit(pil)
    res.scalars["_ups"], res.scalars["_p_treat"], res.scalars["_calib_end"] = ups, p_treat, cfg.settings["splits"]["calibration_end"]
    res.t("policy_comparison", U.compare_policies(ups, p_treat)); res.t("uplift_calibration", U.cate_by_decile(ups))
    wa = W.run_waiting_analysis(con, cfg, fx[fx["status"] == "closed"])
    res.t("waiting_hazard_params", wa["hazard_params"]); res.t("waiting_category_inputs", wa["category_inputs"])
    res.t("waiting_policy_results", wa["policy_results"]); res.t("waiting_schedules", wa["schedules"])
    res.scalars["waiting_support"] = wa["support"]
    c.s.update(ups=ups)


@stage("effort_rule", "Where is extra labor (photos) worth the minutes?",
       "randomized photo experiment", "photo_effects_by_category, photo_rule_by_band, min_item_value")
def effort_rule(c: Context):
    cfg, res, con = c.cfg, c.res, c.con
    lab, fee = cfg.econ("labor_cost_per_minute"), cfg.econ("fee_pct")
    pe = E.photo_experiment_frame(con)
    ef = E.photo_effects(pe, lab, fee); res.t("photo_effects_by_category", ef)
    pooled = float(ef["pooled_uplift"].iloc[0] * (1 - fee)); res.scalars["photo_pooled_benefit_per_dollar"] = pooled
    res.t("photo_rule_by_band", E.photo_rule_by_band(pe, pooled, lab))
    g, first = E.min_item_value(con, cfg); res.t("net_value_by_category_band", g); res.t("min_item_value", first)


@stage("sources_and_lots", "Score sources, predict a truckload's value before opening it, set a bid ceiling",
       "lot-level mart, items by lot", "source_scorecard, lot_oof_predictions, bid_backtest, sampling_value")
def sources_and_lots(c: Context):
    cfg, res, con, reg = c.cfg, c.res, c.con, c.reg
    lab = cfg.econ("labor_cost_per_minute")
    lots = S.lot_frame(con); sc = S.scorecard(lots, cfg); res.t("source_scorecard", sc)
    ts = con.execute("""select l.source_id, sum(t.true_expected_value - l.lot_price - l.inbound_freight) / sum(l.lot_retail_total) as true_profit_rate
                        from truth_lots t join mart_lot l using(lot_id) where l.lot_complete group by 1""").df().set_index("source_id")
    v = sc.set_index("source_id").join(ts)
    res.scalars["scorecard_validation"] = {"corr_raw": float(np.corrcoef(v["profit_per_retail_dollar_est"], v["true_profit_rate"])[0, 1]),
                                           "corr_shrunk": float(np.corrcoef(v["profit_per_retail_dollar_shrunk"], v["true_profit_rate"])[0, 1]),
                                           "corr_score": float(np.corrcoef(v["score"], v["true_profit_rate"])[0, 1]),
                                           "rmse_raw": float(np.sqrt(((v["profit_per_retail_dollar_est"] - v["true_profit_rate"]) ** 2).mean())),
                                           "rmse_shrunk": float(np.sqrt(((v["profit_per_retail_dollar_shrunk"] - v["true_profit_rate"]) ** 2).mean()))}
    items_cl = L.load_items(con)
    oof = B.oof_lot_predictions(cfg, reg, items_cl); sig = B.sigma_by_source(oof)
    res.t("lot_oof_predictions", oof)
    res.scalars["lot_model"] = {"corr": float(np.corrcoef(oof.pred_nv, oof.actual_nv)[0, 1]), "bias_pct": float(oof.pred_nv.sum() / oof.actual_nv.sum() - 1), "median_sigma_rate": float(sig.median())}
    res.t("bid_backtest", B.backtest(oof, sig, cfg)); res.t("bid_sweep", B.ceiling_sweep(oof, sig, accept=0.5))
    med = oof.median(numeric_only=True)
    res.t("sampling_value", B.value_of_sampling(int(med["n_items"]), float(med["lot_retail"]), float(sig.median()), cfg.decision("risk_buffer_k"),
                                                cfg.decision("lot_target_margin"), cfg.decision("sampling_minutes_per_item"), lab, (5, 10, 20, 40, 80)))


@stage("match_quality", "Which catalog matches are probably wrong? (ranks the audit queue)",
       "audited items", "match_review_gain")
def match_quality(c: Context):
    cfg, res, con = c.cfg, c.res, c.con
    aud = M.load_audited(con); res.scalars["match_cv"] = M.cv_report(cfg, aud)
    mm = M.fit_match(cfg, aud)
    ia = con.execute("select m.*, t.retail_true, t.match_correct as truth_ok from mart_item m join truth_items t using(item_id) where m.status='closed'").df()
    pw = mm.predict_proba(M.match_features(ia))[:, 1]
    res.t("match_review_gain", M.review_queue_gain(ia, pw, ia["retail_true"].to_numpy(), ~ia["truth_ok"].to_numpy()))
    res.scalars["match_exposure"] = {"expected_wrong_share": float(pw.mean()), "true_wrong_share": float((~ia["truth_ok"]).mean())}
    c.s["mm"] = mm; res.models["match"] = mm


@stage("decision_engine", "Run every model on an item and price each lever in dollars per month",
       "all models above", "intake_cards, value_levers")
def decision_engine(c: Context):
    s, res = c.s, c.res
    res.t("intake_cards", ENG.intake_cards(res, s["m"], s["ups"], s["mm"], s["hm"], res.tables["waiting_schedules"], res.tables["photo_rule_by_band"]))
    res.t("value_levers", ENG.value_levers(res, c.con, c.cfg))


@stage("monitoring", "Has the world moved? Drift in inputs, error by month, retrain rule, model card",
       "recovery model, recent items", "drift_psi, monthly_performance")
def monitoring(c: Context):
    cfg, res, reg, s = c.cfg, c.res, c.reg, c.s
    df, tr, ca, te, base, ev, pred_te = (s[k] for k in ("df", "tr", "ca", "te", "base", "ev", "pred_te"))
    feats = reg.all_feature_names("recovery")
    recent = df[df.listing_date >= pd.Timestamp(cfg.settings["splits"]["calibration_end"]) + pd.Timedelta(days=90)]
    drift = MON.drift_table(tr, recent, [f for f in feats if f != "title"], cfg.model("monitoring")["psi_warn"], cfg.model("monitoring")["psi_alert"])
    res.t("drift_psi", drift)
    mp = MON.monthly_performance(te, pred_te, te["category"].map(base).fillna(base.mean()).to_numpy()); res.t("monthly_performance", mp)
    res.scalars["retrain_decision"] = MON.retrain_decision(mp, drift, cfg.model("monitoring")["mae_degradation_alert"])
    res.cards["recovery_model"] = MON.model_card("Recovery rate (two-part LightGBM + conformal intervals)",
        "Predict gross recovery (sale price / retail) for items about to be listed; zeros included.",
        {"train_rows": len(tr), "calibration_rows": len(ca), "test_rows": len(te), "train_window": f"to {cfg.settings['splits']['train_end']}", "features": feats},
        {k: ev[k] for k in ("model", "category_median_baseline", "current_production_model", "auc_sold", "interval_coverage", "interval_target")},
        ["Trained on SIMULATED data with known truth; real performance must be re-measured.", "Auction items only; fixed-price items use the sale-timing model.",
         "Interval coverage drifts down after the June 2026 expansion (new source type)."])


@stage("metric_layer", "Answer report requests from governed metric definitions; ask before guessing",
       "metric_definitions.yaml, warehouse", "metric_layer_examples, ambiguity_log")
def metric_layer(c: Context):
    res = c.res
    ml = MetricLayer(c.cfg, c.con)
    qs = ["What were sales last week?", "What were gross sales last week by category?", "net sales in October 2026", "What was recovery by category last month?",
          "recovery on sold items by source type in Q3", "profit by source last month", "How many items sold yesterday?", "Show me revenue",
          "sell-through by channel last month", "average days to close by category in September 2026", "what is the weather?", "net revenue by month in Q3"]
    rows = []
    for q in qs:
        r = ml.ask_question(q)
        rows.append({"question": q, "status": r.status, "metric": r.metric, "period": f"{r.period[0]} to {r.period[1]}" if r.period else "", "level": r.level or "",
                     "value": r.value if r.level is None else "(table)", "clarifying_question": " | ".join(r.clarifying_questions), "assumptions": " | ".join(r.assumptions)})
    res.t("metric_layer_examples", pd.DataFrame(rows)); res.t("ambiguity_log", pd.DataFrame(ml.log))
    res.scalars["metric_prompt"] = ml.to_prompt_context()


ORDER = [recovery_model, anchor_impact, sale_timing, channel_and_waiting, effort_rule, sources_and_lots, match_quality, decision_engine, monitoring, metric_layer]


# ============================================================================================ run + bookkeeping
def run_all(cfg: Config | None = None, rebuild_warehouse: bool = True, verbose: bool = True) -> Results:
    cfg = cfg or Config()
    res = Results()
    log = (lambda *a: print(*a, flush=True)) if verbose else (lambda *a: None)
    c = Context(cfg=cfg, res=res, log=log)
    t0 = time.time()
    log("warehouse + data-quality gate")
    before = set(res.tables)
    stage_warehouse(c, rebuild_warehouse)
    res.timings["warehouse"] = round(time.time() - t0, 1)
    res.stages.append(dict(name="warehouse", seconds=res.timings["warehouse"], tables=sorted(set(res.tables) - before),
                           purpose="Build the warehouse from raw files, run the data tests, stop if any error-severity test fails"))
    meta = {s["fn"].__name__: s for s in STAGES}
    for fn in ORDER:
        info = meta[fn.__name__]; log(info["name"]); t = time.time(); before = set(res.tables)
        fn(c)
        sec = round(time.time() - t, 1); res.timings[info["name"]] = sec
        res.stages.append(dict(name=info["name"], seconds=sec, tables=sorted(set(res.tables) - before), purpose=info["purpose"], needs=info["needs"]))
    c.con.close()
    return res


def _hash_files(paths) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        p = Path(p)
        if p.suffix == ".parquet":   # hash the content: parquet bytes carry writer metadata that changes between identical writes
            df = pd.read_parquet(p)
            h.update(p.name.encode()); h.update(str(list(df.columns)).encode()); h.update(pd.util.hash_pandas_object(df, index=False).values.tobytes())
        else:
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (pd.DataFrame,)):
        return None
    if isinstance(o, (pd.Timestamp, datetime)):
        return str(o)
    return o


def finish(res: Results, cfg: Config) -> dict:
    """Save trained models, write the run manifest and scalars, append to run history."""
    import joblib
    out = cfg.outputs_dir; out.mkdir(parents=True, exist_ok=True)
    mdir = cfg.root / "models"; mdir.mkdir(exist_ok=True)
    saved = {}
    for name, obj in res.models.items():
        p = mdir / f"{name}.joblib"
        try:
            joblib.dump(obj, p); saved[name] = {"file": f"models/{p.name}", "bytes": p.stat().st_size}
        except Exception as e:  # a model that cannot be pickled should not sink the run
            saved[name] = {"error": str(e)[:120]}
    raw_files = sorted(cfg.raw_dir.glob("*.parquet"))
    cfg_files = sorted((cfg.root / "config").glob("*.yaml"))
    con = duckdb.connect(str(cfg.warehouse_path), read_only=True)
    counts = {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("mart_item", "mart_lot")}
    dq = res.tables.get("data_quality_tests", pd.DataFrame())
    con.close()
    ev = res.scalars["recovery_eval"]; lv = res.tables["value_levers"].set_index("order")
    headline = {
        "recovery_mae": ev["model"]["mae"], "incumbent_mae": ev["current_production_model"]["mae"],
        "recovery_total_error_pct": ev["model"]["weighted_total_error_pct"], "auc_sold": ev["auc_sold"], "interval_coverage": ev["interval_coverage"],
        "pilot_effect_per_retail_dollar": float(res.tables["pilot_ate"]["effect"].iloc[0]),
        "lever_anchor_per_month": float(lv.loc[1, "monthly"]), "lever_routing_per_month": float(lv.loc[2, "monthly"]),
        "lever_markdown_per_month": float(lv.loc[3, "monthly"]), "lever_photo_per_month": float(lv.loc[4, "monthly"]),
        "retrain_recommended": bool(res.scalars["retrain_decision"]["retrain_recommended"]),
        "dq_errors": int((dq["status"] == "FAIL").sum()) if len(dq) else None, "dq_warnings": int((dq["status"] == "warn").sum()) if len(dq) else None,
    }
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {"run_at_utc": now, "git_sha": os.environ.get("GITHUB_SHA", "local"), "config_hash": _hash_files(cfg_files), "raw_data_hash": _hash_files(raw_files),
                "warehouse_rows": counts, "stages": res.stages, "models_saved": saved, "headline": headline,
                "tables_written": len(res.tables), "total_seconds": round(sum(res.timings.values()), 1)}
    (out / "run_manifest.json").write_text(json.dumps(_jsonable(manifest), indent=2))
    (out / "scalars.json").write_text(json.dumps(_jsonable(res.scalars), indent=2, default=str))
    hist = out / "run_history.csv"
    row = pd.DataFrame([{"run_at_utc": now, "git_sha": manifest["git_sha"][:8], "config_hash": manifest["config_hash"], "raw_data_hash": manifest["raw_data_hash"], **headline}])
    if hist.exists():
        row = pd.concat([pd.read_csv(hist), row], ignore_index=True)
    row.to_csv(hist, index=False)
    return manifest
