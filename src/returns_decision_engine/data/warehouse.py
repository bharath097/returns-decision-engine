"""DuckDB warehouse builder: a small, portable, dbt-style runner.

SQL models live in ``sql/``:  staging -> marts -> (custom variables / costs) -> post marts -> tests.
Models use ``{{ ref('name') }}`` and ``{{ var('key') }}``; each file materializes a table named
after the file.  The SQL is ANSI-leaning so it moves to Snowflake or BigQuery with small edits,
and the layout maps one-to-one onto a dbt project (models/, tests/).
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from ..config import Config
from .registry import Registry, build_mart_item, run_calculations, _weight_class_table

REF = re.compile(r"\{\{\s*ref\(\s*'([a-zA-Z0-9_]+)'\s*\)\s*\}\}")
VAR = re.compile(r"\{\{\s*var\(\s*'([a-zA-Z0-9_]+)'\s*\)\s*\}\}")


def _vars(cfg: Config) -> dict:
    out = {}
    for block in ("economics", "splits"):
        for k, v in cfg.settings.get(block, {}).items():
            if isinstance(v, (int, float, str)):
                out[k] = v
    return out


def render(sql: str, variables: dict) -> str:
    sql = REF.sub(lambda m: m.group(1), sql)

    def _v(m):
        key = m.group(1)
        if key not in variables:
            raise KeyError(f"SQL var('{key}') not found in settings economics/splits")
        val = variables[key]
        return f"'{val}'" if isinstance(val, str) else repr(float(val))
    return VAR.sub(_v, sql)


def _model_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.sql"))


def _order_by_refs(files: list[Path]) -> list[Path]:
    """Topologically order model files by their ref() dependencies."""
    names = {f.stem: f for f in files}
    deps = {n: {d for d in REF.findall(f.read_text()) if d in names and d != n} for n, f in names.items()}
    ordered, done = [], set()
    while len(ordered) < len(names):
        progressed = False
        for n in sorted(names):
            if n in done:
                continue
            if deps[n] <= done:
                ordered.append(names[n]); done.add(n); progressed = True
        if not progressed:
            raise RuntimeError(f"circular ref() dependency among {sorted(set(names) - done)}")
    return ordered


def _materialize(con, f: Path, variables: dict) -> int:
    sql = render(f.read_text(), variables)
    con.execute(f"create or replace table {f.stem} as {sql}")
    return con.execute(f"select count(*) from {f.stem}").fetchone()[0]


def load_raw(con, cfg: Config, include_truth: bool = True) -> list[str]:
    loaded = []
    for p in sorted(cfg.raw_dir.glob("*.parquet")):
        name = p.stem
        if name.startswith("truth_") and not include_truth:
            continue
        con.execute(f"create or replace table {name} as select * from read_parquet('{p.as_posix()}')")
        loaded.append(name)
    return loaded


def build_warehouse(cfg: Config, include_truth: bool = True, verbose: bool = True) -> dict:
    """Build the warehouse from raw parquet. Returns {con, registry, log, tests}."""
    cfg.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    if cfg.warehouse_path.exists():
        cfg.warehouse_path.unlink()
    con = duckdb.connect(str(cfg.warehouse_path))
    variables = _vars(cfg)
    reg = Registry(cfg)
    loaded = load_raw(con, cfg, include_truth)
    if "raw_items" not in loaded:
        raise FileNotFoundError(f"No raw tables found in {cfg.raw_dir}; run `simulate` first or place real extracts there")
    wc = _weight_class_table(cfg)
    con.register("_wc", wc)
    con.execute("create or replace table econ_weight_class as select * from _wc")
    con.unregister("_wc")

    log = {"models": {}, "custom": {}}
    sql_dir = cfg.sql_dir
    for f in _order_by_refs(_model_files(sql_dir / "staging")):
        log["models"][f.stem] = _materialize(con, f, variables)
    pre = [f for f in _model_files(sql_dir / "marts")]
    for f in _order_by_refs(pre):
        log["models"][f.stem] = _materialize(con, f, variables)
    log["custom"] = build_mart_item(con, cfg, reg)
    log["models"]["mart_item"] = con.execute("select count(*) from mart_item").fetchone()[0]
    for f in _order_by_refs(_model_files(sql_dir / "post")):
        log["models"][f.stem] = _materialize(con, f, variables)
    # Row order from a parallel engine is not guaranteed; models are sensitive to it, so fix the order (reproducible runs).
    for t_, k_ in (("mart_item", "item_id"), ("mart_lot", "lot_id")):
        try:
            con.execute(f"create or replace table {t_} as select * from {t_} order by {k_}")
        except Exception:
            pass
    tests = run_tests(con, cfg, variables)
    if verbose:
        for n, c in log["models"].items():
            print(f"  built {n:<22} {c:>9,} rows")
    return {"con": con, "registry": reg, "log": log, "tests": tests}


def run_tests(con, cfg: Config, variables: dict | None = None) -> pd.DataFrame:
    variables = variables or _vars(cfg)
    rows = []
    for f in sorted((cfg.sql_dir / "tests").glob("*.sql")):
        raw = f.read_text()
        m = re.search(r"--\s*severity:\s*(\w+)", raw)
        sev = m.group(1) if m else "error"
        n = con.execute(f"select count(*) from ({render(raw, variables)})").fetchone()[0]
        status = "pass" if n == 0 else ("warn" if sev == "warn" else "FAIL")
        rows.append({"test": f.stem, "severity": sev, "failing_rows": int(n), "status": status})
    return pd.DataFrame(rows)


def reconciliation(con, cfg: Config) -> pd.DataFrame:
    """A naive join over duplicated rows overstates totals; this shows by how much."""
    q = """
    select 'raw lot rows' as measure, count(*)::double as value from raw_lots
    union all select 'distinct lots', count(distinct lot_id) from raw_lots
    union all select 'raw item rows', count(*) from raw_items
    union all select 'distinct items', count(distinct item_id) from raw_items
    union all select 'lot price total, raw (every duplicate row)', sum(lot_price) from raw_lots
    union all select 'lot price total, de-duplicated (used)', sum(lot_price) from stg_lots
    """
    df = con.execute(q).df()
    raw_total = float(df.loc[df.measure == "lot price total, raw (every duplicate row)", "value"].iloc[0])
    used = float(df.loc[df.measure == "lot price total, de-duplicated (used)", "value"].iloc[0])
    df.loc[len(df)] = ["overstatement of lot cost if duplicates are not removed (%)", (raw_total / used - 1) * 100]
    return df
