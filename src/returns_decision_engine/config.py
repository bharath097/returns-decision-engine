"""Configuration loading.

All behavior is driven by YAML files in ``config/``.  A project root is found by
walking up from this file until ``config/settings.yaml`` is located, or can be
forced with the ``RETURNS_DECISION_ENGINE_ROOT`` environment variable.  Settings can be
overridden at runtime by passing a dict of dotted-path overrides, which is what
the tests and the "extend it yourself" examples use.
"""
from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    env = os.environ.get("RETURNS_DECISION_ENGINE_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "config" / "settings.yaml").exists():
            return parent
    raise FileNotFoundError("Could not locate project root (config/settings.yaml)")


def _read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _set_dotted(d: dict, dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


class Config:
    """Container for settings, simulation parameters, variables and calculations."""

    def __init__(self, overrides: dict | None = None, root: Path | None = None):
        self.root = Path(root) if root else project_root()
        cfg = self.root / "config"
        self.settings: dict = _read_yaml(cfg / "settings.yaml")
        self.simulation: dict = _read_yaml(cfg / "simulation.yaml")
        self.variables: dict = _read_yaml(cfg / "variables.yaml")
        self.calculations: dict = _read_yaml(cfg / "calculations.yaml")
        self.metric_definitions: dict = _read_yaml(cfg / "metric_definitions.yaml") \
            if (cfg / "metric_definitions.yaml").exists() else {}
        for dotted, value in (overrides or {}).items():
            target = self.settings
            if dotted.startswith("simulation."):
                target, dotted = self.simulation, dotted[len("simulation."):]
            _set_dotted(target, dotted, value)

    # -- path helpers -----------------------------------------------------
    def path(self, key: str) -> Path:
        p = self.root / self.settings["paths"][key]
        return p

    @property
    def raw_dir(self) -> Path:
        return self.path("raw_dir")

    @property
    def warehouse_path(self) -> Path:
        return self.path("warehouse")

    @property
    def outputs_dir(self) -> Path:
        p = self.path("outputs")
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def sql_dir(self) -> Path:
        return self.path("sql_dir")

    @property
    def user_inputs_dir(self) -> Path:
        return self.path("user_inputs")

    # -- convenience ------------------------------------------------------
    def econ(self, key: str) -> Any:
        return self.settings["economics"][key]

    def model(self, key: str) -> dict:
        return self.settings["models"][key]

    def decision(self, key: str) -> Any:
        return self.settings["decisions"][key]

    def copy(self) -> "Config":
        return copy.deepcopy(self)


@lru_cache(maxsize=1)
def default_config() -> Config:
    return Config()
