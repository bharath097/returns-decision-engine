"""The pipeline's own guarantees: the quality gate stops the run, stages are declared, bookkeeping is serialisable."""
import numpy as np
import pandas as pd
import pytest

from returns_decision_engine import pipeline as P


def test_gate_stops_the_run_on_a_failed_data_test(monkeypatch):
    bad = pd.DataFrame([{"test": "freight_allocation_ties_out", "severity": "error", "failing_rows": 3, "status": "FAIL"}])

    class FakeCon:
        def close(self): pass

    monkeypatch.setattr(P, "build_warehouse", lambda cfg, verbose=False: {"registry": None, "log": {}, "tests": bad, "con": FakeCon()})
    monkeypatch.setattr(P, "reconciliation", lambda con, cfg: pd.DataFrame())
    ctx = P.Context(cfg=None, res=P.Results())
    with pytest.raises(P.PipelineError, match="freight_allocation_ties_out"):
        P.stage_warehouse(ctx, rebuild=True)


def test_every_stage_is_declared_with_purpose_inputs_and_outputs():
    names = [s["fn"].__name__ for s in P.STAGES]
    assert names == [f.__name__ for f in P.ORDER]
    for s in P.STAGES:
        assert s["purpose"] and s["needs"] and s["makes"]


def test_manifest_values_serialise():
    out = P._jsonable({"a": np.float64(1.5), "b": np.int64(3), "_private": 1, "c": {"d": np.nan}, "e": pd.DataFrame()})
    assert out == {"a": 1.5, "b": 3, "c": {"d": None}, "e": None}
