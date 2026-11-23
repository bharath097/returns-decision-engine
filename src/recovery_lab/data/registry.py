"""Variable registry and calculation engine.

This is what makes the project extensible without code changes:

* ``config/variables.yaml``  - every variable, its type, role, when it becomes known
  (leakage guard) and which models may use it.  Rows may carry a SQL ``derive``
  expression, or point at a column supplied in ``data/user_inputs/extra_item_variables.csv``.
* ``config/calculations.yaml`` - item-level calculations (new columns) and aggregate
  KPIs evaluated at several levels.
* ``settings.yaml: economics.cost_components`` - extra cost lines that flow into
  net value, contribution margin and every downstream decision.

All user-supplied SQL is validated before it is executed.  It is trusted
*configuration* written by the analyst, not end-user input, but the guard keeps a
typo from dropping a table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from ..config import Config

DTYPES = {"numeric", "categorical", "text", "boolean", "date"}
ROLES = {"feature", "target", "cost", "key", "context", "outcome"}
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
FORBIDDEN = re.compile(
    r"\b(drop|delete|insert|update|create|alter|attach|detach|copy|pragma|install|load|export|import|call|truncate|grant)\b|;|--|/\*",
    re.IGNORECASE)


class RegistryError(ValueError):
    pass


def check_sql_expr(expr: str, where: str) -> str:
    """Reject anything that is not a plain SQL expression."""
    if not isinstance(expr, str) or not expr.strip():
        raise RegistryError(f"{where}: empty SQL expression")
    if FORBIDDEN.search(expr):
        raise RegistryError(f"{where}: forbidden token in SQL expression: {expr!r}")
    if expr.count("(") != expr.count(")"):
        raise RegistryError(f"{where}: unbalanced parentheses: {expr!r}")
    return expr.strip()


def check_ident(name: str, where: str) -> str:
    if not isinstance(name, str) or not IDENT.match(name):
        raise RegistryError(f"{where}: invalid identifier {name!r} (use lower_snake_case)")
    return name


@dataclass
class Variable:
    name: str
    dtype: str
    role: str
    known_at: str
    status: str = "observable"
    used_in: list = field(default_factory=list)
    description: str = ""
    derive: str | None = None
    source: str | None = None


class Registry:
    """Parsed, validated view of ``variables.yaml``."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        v = cfg.variables
        self.order: list[str] = v.get("leakage_order", ["receipt", "listing", "during_listing", "sale", "post_sale"])
        self.allowed_known_at: list[str] = v.get("prediction_allowed_known_at", ["receipt", "listing"])
        rows = list(v.get("variables", [])) + list(v.get("custom_variables", []) or [])
        self.variables: list[Variable] = []
        seen = set()
        for r in rows:
            name = check_ident(r.get("name"), "variables")
            if name in seen:
                raise RegistryError(f"duplicate variable {name!r}")
            seen.add(name)
            if r.get("dtype") not in DTYPES:
                raise RegistryError(f"{name}: dtype must be one of {sorted(DTYPES)}")
            if r.get("role") not in ROLES:
                raise RegistryError(f"{name}: role must be one of {sorted(ROLES)}")
            if r.get("known_at") not in self.order:
                raise RegistryError(f"{name}: known_at must be one of {self.order}")
            var = Variable(name=name, dtype=r["dtype"], role=r["role"], known_at=r["known_at"],
                           status=r.get("status", "observable"), used_in=list(r.get("used_in", []) or []),
                           description=r.get("description", ""), derive=r.get("derive"), source=r.get("source"))
            if var.derive:
                check_sql_expr(var.derive, f"variable {name} derive")
            if var.source not in (None, "user_csv"):
                raise RegistryError(f"{name}: source must be omitted or 'user_csv'")
            if var.role in ("outcome", "cost") and var.used_in:
                raise RegistryError(f"{name}: outcome/cost variables may not be listed in used_in")
            self.variables.append(var)
        self.by_name = {x.name: x for x in self.variables}

    # ------------------------------------------------------------------ feature selection
    def features(self, model: str) -> dict:
        """Feature names for ``model`` grouped by dtype, with the leakage guard enforced."""
        out = {"numeric": [], "categorical": [], "text": [], "boolean": []}
        for v in self.variables:
            if v.role != "feature" or model not in v.used_in:
                continue
            if v.known_at not in self.allowed_known_at:
                raise RegistryError(
                    f"LEAKAGE GUARD: {v.name!r} is known_at={v.known_at!r} but feeds the {model!r} model; "
                    f"only {self.allowed_known_at} are allowed")
            out[v.dtype if v.dtype in out else "numeric"].append(v.name)
        return out

    def all_feature_names(self, model: str) -> list:
        f = self.features(model)
        return f["numeric"] + f["categorical"] + f["boolean"] + f["text"]

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([v.__dict__ for v in self.variables])

    def custom_names(self) -> list:
        return [x["name"] for x in (self.cfg.variables.get("custom_variables") or [])]


# --------------------------------------------------------------------------- engine
def _weight_class_table(cfg: Config) -> pd.DataFrame:
    hold = cfg.econ("holding_cost_per_day_by_weight_class")
    fr = cfg.simulation["costs"]["inbound_freight_per_item_by_weight"]
    return pd.DataFrame({"weight_class": list(range(len(hold))), "holding_cost_per_day": hold, "freight_weight": fr})


def extra_cost_sql(comp: dict) -> str:
    name = check_ident(comp.get("name"), "cost_components")
    kind = comp.get("kind")
    applies = check_sql_expr(comp.get("applies_to", "1=1"), f"cost component {name} applies_to")
    amount = comp.get("amount")
    if kind == "column":
        col = check_ident(str(amount), f"cost component {name} amount")
        return f"case when ({applies}) then coalesce({col}, 0) else 0 end"
    if not isinstance(amount, (int, float)):
        raise RegistryError(f"cost component {name}: amount must be a number")
    a = float(amount)
    templates = {
        "per_item": f"case when ({applies}) then {a} else 0 end",
        "per_minute": f"case when ({applies}) then {a} * handling_minutes else 0 end",
        "pct_of_sale": f"case when ({applies}) then {a} * sale_price else 0 end",
        "per_day": f"case when ({applies}) then {a} * holding_days else 0 end",
        "per_lot": f"case when ({applies}) then {a} / nullif(lot_items, 0) else 0 end",
    }
    if kind not in templates:
        raise RegistryError(f"cost component {name}: kind must be one of {sorted(templates) + ['column']}")
    return templates[kind]


def build_mart_item(con: duckdb.DuckDBPyConnection, cfg: Config, reg: Registry) -> dict:
    """Create ``mart_item`` = mart_item_base + user columns + derived variables + custom costs + item calcs.

    Returns a log dict describing what was added (written to the run report).
    """
    log = {"user_csv_columns": [], "derived": [], "extra_costs": [], "item_calcs": []}
    con.execute("create or replace table _mi as select * from mart_item_base")
    existing = {r[0] for r in con.execute("describe _mi").fetchall()}

    uvars = [v for v in reg.variables if v.source == "user_csv"]
    if uvars:
        path = cfg.user_inputs_dir / "extra_item_variables.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"variables {[v.name for v in uvars]} declare source=user_csv but {path} does not exist")
        con.execute(f"create or replace table _user as select * from read_csv_auto('{path.as_posix()}')")
        ucols = {r[0] for r in con.execute("describe _user").fetchall()}
        if "item_id" not in ucols:
            raise RegistryError(f"{path.name} must contain an item_id column")
        missing = [v.name for v in uvars if v.name not in ucols]
        if missing:
            raise RegistryError(f"{path.name} is missing columns: {missing}")
        names = [v.name for v in uvars if v.name not in existing]
        sel = ", ".join(f"u.{n}" for n in names)
        con.execute(f"create or replace table _mi as select m.*, {sel} from _mi m left join _user u using (item_id)")
        existing |= set(names)
        log["user_csv_columns"] = names

    for v in reg.variables:
        if v.derive and v.name not in existing:
            con.execute(f"create or replace table _mi as select *, ({v.derive}) as {v.name} from _mi")
            existing.add(v.name)
            log["derived"].append(v.name)

    comps = cfg.econ("cost_components") or []
    extra_names = []
    for comp in comps:
        sql = extra_cost_sql(comp)
        nm = f"extra_cost_{comp['name']}"
        con.execute(f"create or replace table _mi as select *, ({sql}) as {nm} from _mi")
        extra_names.append(nm)
        log["extra_costs"].append(comp["name"])
    total = " + ".join(extra_names) if extra_names else "0.0"
    con.execute(f"create or replace table _mi as select *, ({total}) as extra_costs from _mi")

    for calc in (cfg.calculations.get("item_calculations") or []):
        nm = check_ident(calc.get("name"), "item_calculations")
        expr = check_sql_expr(calc.get("sql"), f"item calculation {nm}")
        con.execute(f"create or replace table _mi as select *, ({expr}) as {nm} from _mi")
        log["item_calcs"].append(nm)

    con.execute("""
        create or replace table mart_item as
        select * exclude (final_net_value_base, contribution_margin_base),
               final_net_value_base - extra_costs as final_net_value,
               contribution_margin_base - extra_costs as contribution_margin
        from _mi
    """)
    con.execute("drop table if exists _mi")
    return log


LEVELS = {"overall": "'ALL'", "category": "category", "source": "source_id", "source_type": "source_type",
          "month": "listing_ym", "channel": "channel", "lot": "lot_id"}


def run_calculations(con: duckdb.DuckDBPyConnection, cfg: Config) -> pd.DataFrame:
    """Evaluate every aggregate calculation at each of its levels -> tidy frame."""
    rows = []
    for calc in (cfg.calculations.get("aggregate_calculations") or []):
        nm = check_ident(calc["name"], "aggregate_calculations")
        expr = check_sql_expr(calc["sql"], f"calculation {nm}")
        where = check_sql_expr(calc["where"], f"calculation {nm} where") if calc.get("where") else None
        for lvl in calc.get("levels", ["overall"]):
            if lvl not in LEVELS:
                raise RegistryError(f"calculation {nm}: unknown level {lvl!r}; choose from {sorted(LEVELS)}")
            q = f"select {LEVELS[lvl]} as grp, ({expr}) as value from mart_item"
            if where:
                q += f" where {where}"
            q += " group by 1"
            df = con.execute(q).df()
            df.insert(0, "calculation", nm)
            df.insert(0, "level", lvl)
            df["format"] = calc.get("format", "num")
            df["description"] = calc.get("description", "")
            rows.append(df)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
