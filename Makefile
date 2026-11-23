PY=PYTHONPATH=src python3
simulate: ; $(PY) -m returns_decision_engine.cli simulate
build:    ; $(PY) -m returns_decision_engine.cli build
run:      ; $(PY) -m returns_decision_engine.cli run
all:      ; $(PY) -m returns_decision_engine.cli all
test:     ; PYTHONPATH=src python3 -m pytest -q
report:   ; python3 site_builder/build_report.py
explorer: ; python3 site_builder/build_site.py
