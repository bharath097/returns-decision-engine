import shutil
import pytest
import duckdb
import pandas as pd

from conftest import SMALL, make_root, ROOT
from recovery_lab.config import Config
from recovery_lab.data.registry import Registry, RegistryError, check_sql_expr, extra_cost_sql
from recovery_lab.data.warehouse import build_warehouse


def test_registry_loads_and_features_obey_leakage_guard(cfg):
    reg = Registry(cfg)
    for model in ("recovery", "hazard", "uplift", "match", "lot"):
        for name in reg.all_feature_names(model):
            if name.startswith("title_svd"):
                continue
            assert reg.by_name[name].known_at in reg.allowed_known_at


def test_leaky_variable_is_rejected(cfg):
    c = cfg.copy()
    c.variables["custom_variables"] = [{"name": "final_price_peek", "dtype": "numeric", "role": "feature", "known_at": "sale",
                                        "used_in": ["recovery"], "derive": "sale_price"}]
    reg = Registry(c)
    with pytest.raises(RegistryError, match="LEAKAGE"):
        reg.features("recovery")


@pytest.mark.parametrize("bad", ["1; drop table mart_item", "delete from x", "a -- comment", "(a + b", ""])
def test_unsafe_sql_is_rejected(bad):
    with pytest.raises(RegistryError):
        check_sql_expr(bad, "test")


def test_bad_names_and_types_rejected(cfg):
    c = cfg.copy()
    c.variables["custom_variables"] = [{"name": "Bad Name", "dtype": "numeric", "role": "feature", "known_at": "listing"}]
    with pytest.raises(RegistryError):
        Registry(c)


def test_unknown_cost_kind_rejected():
    with pytest.raises(RegistryError):
        extra_cost_sql({"name": "x", "kind": "magic", "amount": 1})


def test_custom_variable_calculation_and_cost_end_to_end(tmp_path):
    """The extension story: add a derived variable, a CSV variable, a calculation and a cost line without touching code."""
    root = make_root(tmp_path)
    shutil.copytree(ROOT / "data" / "raw", root / "data" / "raw", dirs_exist_ok=True) if (ROOT / "data" / "raw" / "raw_items.parquet").exists() else None
    from recovery_lab.sim.generate import write_raw
    cfg0 = Config(SMALL, root=root); write_raw(cfg0)
    base = build_warehouse(cfg0, verbose=False)
    cm0 = base["con"].execute("select sum(contribution_margin) from mart_item where status='closed'").fetchone()[0]
    n_closed = base["con"].execute("select count(*) from mart_item where status='closed'").fetchone()[0]
    ids = base["con"].execute("select item_id from mart_item").df()
    base["con"].close()

    pd.DataFrame({"item_id": ids.item_id, "pallet_zone": (ids.index % 3).astype(float)}).to_csv(root / "data" / "user_inputs" / "extra_item_variables.csv", index=False)
    cfg = Config(SMALL, root=root)
    cfg.variables["custom_variables"] = [
        {"name": "price_per_weight", "dtype": "numeric", "role": "feature", "known_at": "listing", "used_in": ["recovery"], "derive": "retail_value / (weight_class + 1)"},
        {"name": "pallet_zone", "dtype": "numeric", "role": "feature", "known_at": "receipt", "used_in": ["recovery"], "source": "user_csv"}]
    cfg.calculations["item_calculations"] = [{"name": "net_per_weight", "sql": "net_revenue / (weight_class + 1)"}]
    cfg.calculations["aggregate_calculations"].append({"name": "my_margin_pct", "sql": "sum(contribution_margin) / nullif(sum(net_revenue), 0)",
                                                      "where": "status = 'closed'", "levels": ["overall", "category"], "format": "pct", "description": "mine"})
    cfg.settings["economics"]["cost_components"] = [{"name": "pallet_wrap", "kind": "per_item", "amount": 0.50, "applies_to": "1=1"}]
    w = build_warehouse(cfg, verbose=False)
    con = w["con"]
    cols = {r[0] for r in con.execute("describe mart_item").fetchall()}
    assert {"price_per_weight", "pallet_zone", "net_per_weight", "extra_cost_pallet_wrap", "extra_costs"} <= cols
    cm1 = con.execute("select sum(contribution_margin) from mart_item where status='closed'").fetchone()[0]
    assert abs((cm0 - cm1) - 0.5 * n_closed) < 1.0       # the cost line flows into margin exactly
    assert "price_per_weight" in Registry(cfg).all_feature_names("recovery")
    from recovery_lab.data.registry import run_calculations
    calc = run_calculations(con, cfg)
    assert "my_margin_pct" in set(calc.calculation)
    assert (w["tests"].status == "FAIL").sum() == 0
    con.close()
