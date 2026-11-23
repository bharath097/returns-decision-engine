"""Command line entry point: python -m returns_decision_engine.cli <command>."""
from __future__ import annotations

import argparse
import sys
import time

from .config import Config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="returns-decision-engine")
    ap.add_argument("command", choices=["simulate", "build", "tests", "run", "all"], help="what to run")
    args = ap.parse_args(argv)
    cfg = Config()
    t = time.time()
    if args.command in ("simulate", "all"):
        from .sim.generate import write_raw
        r = write_raw(cfg)
        print({k: v.shape for k, v in r.tables.items()})
    if args.command == "build":
        from .data.warehouse import build_warehouse
        w = build_warehouse(cfg)
        print(w["tests"].to_string(index=False)); w["con"].close()
    if args.command in ("run", "all"):
        from .pipeline import PipelineError, finish, run_all
        from .report import write_all
        try:
            res = run_all(cfg, rebuild_warehouse=True)
        except PipelineError as e:
            print("PIPELINE STOPPED:", e); sys.exit(2)
        print("results written to", write_all(res, cfg))
        m = finish(res, cfg)
        print(f"manifest: {m['tables_written']} tables, {len(m['models_saved'])} models saved, data {m['raw_data_hash']}, config {m['config_hash']}")
    if args.command == "tests":
        import duckdb
        from .data.warehouse import run_tests
        con = duckdb.connect(str(cfg.warehouse_path), read_only=True)
        print(run_tests(con, cfg).to_string(index=False))
    print(f"done in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
