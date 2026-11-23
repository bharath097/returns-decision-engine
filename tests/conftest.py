import shutil
from pathlib import Path

import pytest
import yaml

from returns_decision_engine.config import Config

ROOT = Path(__file__).resolve().parents[1]


def make_root(tmp: Path) -> Path:
    for d in ("config", "sql"):
        shutil.copytree(ROOT / d, tmp / d)
    (tmp / "data" / "raw").mkdir(parents=True)
    (tmp / "data" / "user_inputs").mkdir(parents=True)
    return tmp


SMALL = {"simulation.scale.n_lots": 140, "simulation.scale.items_per_lot_median": 45, "simulation.scale.mc_draws_truth": 40}


@pytest.fixture(scope="session")
def small_root(tmp_path_factory):
    from returns_decision_engine.sim.generate import write_raw
    root = make_root(tmp_path_factory.mktemp("rl"))
    cfg = Config(SMALL, root=root)
    write_raw(cfg)
    return root


@pytest.fixture()
def cfg(small_root):
    return Config(SMALL, root=small_root)


@pytest.fixture(scope="session")
def warehouse(small_root):
    from returns_decision_engine.data.warehouse import build_warehouse
    cfg = Config(SMALL, root=small_root)
    w = build_warehouse(cfg, verbose=False)
    yield w
    w["con"].close()
