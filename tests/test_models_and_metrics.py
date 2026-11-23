import numpy as np
import pytest

from recovery_lab.data.registry import Registry
from recovery_lab.metrics.clarify import MetricLayer, parse_period
from recovery_lab.models import recovery as R, monitor as MON
from datetime import date


@pytest.fixture(scope="module")
def fitted(warehouse, small_root):
    from conftest import SMALL
    from recovery_lab.config import Config
    cfg = Config(SMALL, root=small_root); reg = Registry(cfg)
    cfg.settings["splits"]["train_end"] = "2025-09-30"; cfg.settings["splits"]["calibration_end"] = "2025-12-31"
    df = R.load_auction_items(warehouse["con"])
    tr, ca, te = R.split_by_time(cfg, df)
    return cfg, reg, R.fit_recovery(cfg, reg, tr, ca), tr, te


def test_recovery_model_beats_category_baseline(fitted):
    cfg, reg, m, tr, te = fitted
    ev = R.evaluate(m, te, tr.groupby("category")["gross_recovery"].mean())
    assert ev["model"]["mae"] < ev["category_median_baseline"]["mae"]
    assert ev["auc_sold"] > 0.7


def test_two_part_is_less_biased_than_sold_only(fitted):
    cfg, reg, m, tr, te = fitted
    y = te["gross_recovery"].mean()
    assert abs(m.predict(te).mean() - y) < abs(m.predict_naive(te).mean() - y)


def test_interval_coverage_near_target(fitted):
    cfg, reg, m, tr, te = fitted
    iv = m.predict_interval(te)
    cov = ((te["gross_recovery"].to_numpy() >= iv.lo) & (te["gross_recovery"].to_numpy() <= iv.hi)).mean()
    assert abs(cov - 0.8) < 0.12


def test_predictions_in_range(fitted):
    cfg, reg, m, tr, te = fitted
    p = m.predict(te)
    assert p.min() >= 0 and p.max() <= 1


def test_psi_zero_for_same_distribution_and_positive_for_shift():
    import pandas as pd
    rng = np.random.default_rng(0)
    a = pd.Series(rng.normal(size=5000)); b = pd.Series(rng.normal(size=5000)); c = pd.Series(rng.normal(1.5, 1, 5000))
    assert MON.psi(a, b) < 0.05 and MON.psi(a, c) > 0.25


def test_period_parsing():
    as_of = date(2026, 10, 31)           # a Saturday
    (s, e), lab, _ = parse_period("sales last week", as_of)
    assert s.weekday() == 0 and (e - s).days == 6 and e < as_of
    (s, e), _, _ = parse_period("October 2026", as_of); assert (s, e) == (date(2026, 10, 1), date(2026, 10, 31))
    (s, e), _, _ = parse_period("Q3", as_of); assert (s, e) == (date(2026, 7, 1), date(2026, 9, 30))


def test_metric_layer_asks_when_ambiguous_and_answers_when_not(warehouse, cfg):
    ml = MetricLayer(cfg, warehouse["con"])
    r = ml.ask_question("What were sales last week?")
    assert r.status == "needs_clarification" and "gross" in r.clarifying_questions[0].lower()
    r = ml.ask_question("gross sales in October 2026")
    assert r.status == "answered"
    direct = warehouse["con"].execute("select coalesce(sum(sale_price),0) from mart_item where status='closed' and sold and close_date between date '2026-10-01' and date '2026-10-31'").fetchone()[0]
    assert (r.value or 0) == pytest.approx(direct)
    assert ml.ask_question("what is the weather").status == "unknown_metric"


def test_metric_layer_without_period_asks(warehouse, cfg):
    r = MetricLayer(cfg, warehouse["con"]).ask_question("gross sales by category")
    assert r.status == "needs_clarification"
