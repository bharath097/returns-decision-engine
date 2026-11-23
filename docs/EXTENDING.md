# Extending Returns Decision Engine

Everything below is configuration. No Python changes are needed, and each recipe is covered by a test
(`tests/test_registry_and_extension.py`).

## 1. Add a variable you know about

**a) Derived from existing columns** (one SQL expression, no semicolons or DDL). Append to `custom_variables` in `config/variables.yaml`:

```yaml
custom_variables:
  - {name: price_per_weight, dtype: numeric, role: feature, known_at: listing,
     used_in: [recovery], derive: "retail_value / (weight_class + 1)",
     description: "Retail dollars per weight step"}
```

**b) Supplied by you** (a column your systems have and the simulator does not). Put a CSV at
`data/user_inputs/extra_item_variables.csv` with an `item_id` column and one column per variable, then declare it with `source: user_csv`:

```yaml
  - {name: pallet_zone, dtype: numeric, role: feature, known_at: receipt, used_in: [recovery, hazard], source: user_csv}
```

`known_at` is mandatory and is the leakage guard. Allowed values, in order: `receipt, listing, during_listing, sale, post_sale`.
A variable known only at or after `during_listing` cannot feed a prediction: the registry raises `LEAKAGE GUARD` the moment a model asks for it.
`used_in` picks the models: `recovery, hazard, uplift, match, lot`.

## 2. Add a calculation

`config/calculations.yaml`:

```yaml
item_calculations:          # new column on every item (can reference earlier ones)
  - {name: net_per_weight, sql: "net_revenue / (weight_class + 1)"}
aggregate_calculations:     # evaluated at each level, written to outputs/tables/calculations.csv
  - {name: my_margin_pct, sql: "sum(contribution_margin) / nullif(sum(net_revenue), 0)",
     where: "status = 'closed'", levels: [overall, category, source_type], format: pct, description: "Margin on net revenue"}
```

Levels: `overall, category, source, source_type, month, channel, lot`.

## 3. Add a cost line

`config/settings.yaml`, under `economics.cost_components`:

```yaml
  cost_components:
    - {name: pallet_wrap, kind: per_item, amount: 0.35, applies_to: "1=1"}
    - {name: oversize_handling, kind: per_item, amount: 4.0, applies_to: "weight_class >= 3"}
    - {name: payment_dispute_reserve, kind: pct_of_sale, amount: 0.004, applies_to: "1=1"}
    - {name: climate_storage, kind: per_day, amount: 0.05, applies_to: "category = 'Laptops_current'"}
    - {name: relabel_labor, kind: per_minute, amount: 0.10, applies_to: "1=1"}   # per handling minute
    - {name: lot_audit_fee, kind: per_lot, amount: 25, applies_to: "1=1"}        # spread over the lot's items
    - {name: my_column_cost, kind: column, amount: pallet_zone, applies_to: "1=1"} # cost taken from a column
```

Costs flow into `final_net_value`, `contribution_margin`, the uplift outcome, the waiting rule inputs and the bid ceiling.

## 4. Add a metric for report requests

`config/metric_definitions.yaml`: give the metric a label, synonyms, a plain-English definition, one SQL aggregate, a `where`, a `date_field`, caveats and an example. If a word is ambiguous ("sales"), add it to `ambiguous_terms` with the clarifying question.

## 5. Change economics or decision parameters

`config/settings.yaml`: labor cost per minute, fees, shipping, holding costs, cost of capital, target margin, risk buffer, scorecard weights, markdown ladder.

## 6. Use real data instead of the simulator

Place parquet or CSV-converted extracts in `data/raw/` named `raw_sources, raw_lots, raw_items, raw_outcomes` (and `raw_item_audit` if you have audited matches), with the same columns (see `docs/DATA_DICTIONARY.md` and `src/returns_decision_engine/sim/generate.py` for the exact schema). Run `make build` then `make run`. Tables named `truth_*` exist only in simulation; sections that validate against truth are skipped or must be removed for real data.

## Checks that protect you

- Variable and cost names must be `lower_snake_case`; SQL is rejected if it contains `;`, `--`, `/*` or DDL/DML keywords.
- `make test` runs 33 tests, including an end-to-end run that adds a derived variable, a CSV variable, a calculation and a cost line.
