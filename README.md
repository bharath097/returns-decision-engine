# Returns Decision Engine

A decision system for a business that buys returned and overstock goods by the truckload and sells them by auction or at a fixed price.
It predicts what each item will recover, decides how to list it, where labor is worth spending and which truckloads to bid on, answers report
requests from governed definitions, and prices each of those decisions in dollars per month.

**All data is simulated** with known ground truth. Every parameter is a placeholder. The project demonstrates method, not any real company's results.

## What this project is

The business opens pallets, matches each item to a catalog entry, photographs and grades it, and lists it. The number that matters is **recovery**:
what an item sold for divided by what it would have cost new, with unsold items counted as zero.

Five things make that hard, and the project is organised around them:

1. **A zero is a zero.** Averages over items that sold overstate performance. Every comparison here counts the unsold items.
2. **Two channels, two clocks.** An auction ends in two days. A fixed price never ends. They cannot share a time window.
3. **Unknown contents.** A truckload can hold toys and phones together. Items run from $5 to thousands of dollars.
4. **Labor is the main variable cost.** Every extra minute of handling has to earn its place.
5. **Definitions drift.** "Sales last week" needs a governed meaning, for people and for the assistants that answer for them.

## What it does

The pipeline turns raw files into decisions in eleven steps. One of them is a gate: if any error-level data test fails, the run stops.

| Stage | Question it answers | Method |
|---|---|---|
| warehouse | Is the data fit to use? | SQL models and data tests; **stops the run on failure** |
| recovery model | How much will an item recover before it is listed? | ML: two LightGBM models, calibration, conformal intervals |
| anchor impact | What is a better estimate worth in dollars? | Arithmetic on model output, bootstrap intervals |
| sale timing | How fast does a fixed-price item sell at each price? | ML: discrete-time hazard model |
| channel and waiting | Auction or fixed price, for which items, and when to mark down? | ML: uplift T-learner; randomized-pilot statistics; dynamic program |
| effort rule | Where are extra photos worth the minutes? | Statistics: randomized experiment, break-even arithmetic |
| sources and lots | What is a truckload worth before opening, and what is the bid ceiling? | ML: lot-value model; empirical-Bayes source scorecard |
| match quality | Which catalog matches are probably wrong? | ML: classifier ranks the audit queue |
| decision engine | What does every model say about one item, and what is each lever worth? | Combines the above (`engine.py`) |
| monitoring | Has the world moved? When to retrain? | Statistics: drift index, error by month, threshold rule |
| metric layer | What does this report request mean? | Governed definitions; asks a clarifying question when a word is ambiguous |

## What comes out

- `outputs/RESULTS.md`: the findings with their numbers, 18 charts and 47 tables.
- `outputs/tables/intake_cards.csv`: for sample items, every model's output and the single action it implies.
- `outputs/tables/value_levers.csv`: what each lever is worth per month, and how that number was obtained (randomized, back-tested, model-based or assumption-dependent). Levers overlap, so they are not added.
- `docs/site/index.html`: the project's home page: what it is, how the pipeline works, what it found. `docs/site/explorer.html`: interactive scenarios, playbook and variable registry.
- `models/`: the trained models. `outputs/run_manifest.json` and `outputs/run_history.csv`: what data and configuration produced each run.

## How it is checked

- **Simulation with truth.** The simulator knows each item's real value and each truckload's real contents, so methods are graded against the answer they try to recover. It injects the defects real data has: duplicates, wrong matches, a mid-period expansion.
- **Gate and tests.** SQL data tests guard the warehouse; 36 code tests cover the simulator, warehouse, models, decisions, metric layer and the pipeline gate itself.
- **Reproducible and traceable.** Two runs on the same data and configuration give the same numbers. Each run records fingerprints of the data and configuration, rows per table, time and tables per stage, and the models saved.
- **Honest intervals.** Wherever a number has an interval that includes zero, the report says so and does not call it an effect.

## Run it

```bash
pip install -r requirements.txt && pip install -e .
make all        # simulate -> warehouse + gate -> models -> decisions -> outputs/  (about 2.5 minutes)
make test       # 36 tests
make report     # docs/site/index.html from outputs/
make explorer   # docs/site/explorer.html
```
`make run` re-runs the pipeline on the existing raw files (use this with your own data). A weekly GitHub Actions workflow runs all of the above and commits refreshed outputs.

## Where things are

```
config/      settings, simulation, variable registry, calculations, metric definitions
sql/         staging -> marts -> post marts, and data tests (error / warn severity)
src/returns_decision_engine/
  pipeline.py   stages, the gate, manifest and run history
  engine.py     decision engine: per-item decisions and the dollar ladder
  sim/ data/ models/ decisions/ metrics/ report.py cli.py
tests/       simulator, warehouse, models, decisions, metric layer, pipeline
docs/        report (site/), EXTENDING.md, DATA_DICTIONARY.md
site_builder/  builds the report and the explorer from outputs/
```

To add variables, calculations, cost lines or metrics in YAML, see `docs/EXTENDING.md`.

## What it cannot tell you

Everything is simulated, so the numbers say nothing about a real business. Within the simulation, the markdown gain below the tested price range, the item-level routing gain and the counter-offer gain are not established, and the report labels them as such.
