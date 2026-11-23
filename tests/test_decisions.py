import numpy as np
import pandas as pd

from returns_decision_engine.decisions import channel as C, waiting as W
from returns_decision_engine.decisions.utils import eb_shrink


def test_wilson_five_item_example():
    p, lo, hi = C.wilson_ci(3, 5)
    assert p == 0.6 and abs(lo - 0.2307) < 1e-3 and abs(hi - 0.8824) < 1e-3


def test_breakeven_formulas():
    assert abs(C.breakeven_p(0.2, 100, 100) - 1 / 1.2) < 1e-12      # unsold item lost entirely (h = X): 83.3%
    assert C.breakeven_p(0.2, 100, 0) == 0.0                         # waiting is free: fixed-price-first always wins
    assert C.breakeven_p(0.2, 100, 10) < 1 / 1.2                     # a fallback lowers the bar
    p = C.breakeven_p(0.2, 100, 10)
    assert abs(C.expected_value_fixed_first(p, 0.2, 100, 10) - 100) < 1e-9   # at break-even it equals the auction value


def test_story_verdict_is_inconclusive_on_five_items():
    assert C.story_five_items()["verdict"] == "not enough evidence either way"


def test_required_n_scales_with_effect_squared():
    assert C.required_n_two_means(0.3, 0.01) > 3.9 * C.required_n_two_means(0.3, 0.02)


def test_hold_rule_matches_algebra():
    q, P, A, c, d = 0.1, 150.0, 100.0, 1.0, 0.5
    assert W.hold_one_more_day(q, P, A, c, d) == (q * (P - A) > (1 - q) * (c + d))


def test_dp_beats_static_hold():
    par = pd.Series({"a": -2.0, "b": -3.0, "b_use": -3.0, "g": -0.08})
    eco = W.Economics(base_value=100, terminal_value=20, fee_pct=0.035, fee_fixed=0.3, holding_per_day=0.5)
    dp = W.optimal_markdown(par, eco, [0.7, 0.8, 0.9, 1.0, 1.1, 1.2], 21)
    for m in (1.1, 1.2):
        assert dp["value"] >= W.static_policy_value(par, eco, m, 21) - 1e-9


def test_eb_shrink_moves_toward_pool():
    est = pd.Series([0.0, 1.0, 2.0, 10.0]); se = pd.Series([1.0, 1.0, 1.0, 3.0])
    r = eb_shrink(est, se)
    assert ((r.shrunk - r.pooled).abs() <= (r.est - r.pooled).abs() + 1e-12).all()
    assert r.loc[3, "weight_on_own"] < r.loc[0, "weight_on_own"] or r.tau2.iloc[0] == 0


def test_sampling_value_gain_grows_with_sample():
    from returns_decision_engine.decisions.bid_ceiling import value_of_sampling
    v = value_of_sampling(100, 10000, 0.05, 0.8, 0.12, 3.0, 0.62, (5, 20, 50))
    assert v.ceiling_gain.is_monotonic_increasing
