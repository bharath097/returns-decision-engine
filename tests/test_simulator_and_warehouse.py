import numpy as np

from returns_decision_engine.data.warehouse import reconciliation


def test_sql_data_quality_tests_pass(warehouse):
    t = warehouse["tests"]
    assert (t.status == "FAIL").sum() == 0, t[t.status == "FAIL"]


def test_staging_removes_injected_duplicates(warehouse):
    con = warehouse["con"]
    raw = con.execute("select count(*) from raw_items").fetchone()[0]
    stg = con.execute("select count(*) from stg_items").fetchone()[0]
    assert raw > stg
    assert con.execute("select count(*) from (select item_id from stg_items group by 1 having count(*)>1)").fetchone()[0] == 0
    assert con.execute("select count(*) from (select lot_id from stg_lots group by 1 having count(*)>1)").fetchone()[0] == 0


def test_a_zero_is_final_for_auctions(warehouse):
    con = warehouse["con"]
    bad = con.execute("select count(*) from mart_item where channel='auction' and status='closed' and not sold and sale_price<>0").fetchone()[0]
    assert bad == 0
    open_auction = con.execute("select count(*) from mart_item where channel='auction' and status='open' and sold").fetchone()[0]
    assert open_auction == 0


def test_fixed_price_sale_probability_falls_with_premium(warehouse):
    d = warehouse["con"].execute("select premium_pct p, avg((sale_channel='fixed')::int) r from mart_item where channel='fixed_price' and status='closed' group by 1 order by 1").df()
    assert len(d) == 3 and d.r.is_monotonic_decreasing


def test_lot_cost_allocation_ties_out(warehouse):
    con = warehouse["con"]
    a = con.execute("select sum(allocated_lot_cost) from mart_item").fetchone()[0]
    b = con.execute("select sum(lot_price) from stg_lots").fetchone()[0]
    assert abs(a - b) < 1.0


def test_duplicates_would_overstate_cost(warehouse):
    r = reconciliation(warehouse["con"], warehouse["con"] and None)  # cfg unused by the query
    assert r.iloc[-1].value > 0


def test_truth_expected_recovery_matches_realized(warehouse):
    d = warehouse["con"].execute("select avg(x_true) x, avg(gross_recovery) y from truth_items t join mart_item m using(item_id) where m.channel='auction' and m.status='closed' and m.retail_value<2000").df()
    assert abs(d.x[0] - d.y[0]) / d.y[0] < 0.15
