# system: the engine for the blocks

```
python system/run_case.py case.json            run a case with the blocks
python system/compare.py case.json [more]      run reference cases with both models and compare
python -m pytest system/tests -q               checks (about 2 min)
```

## Files

```
setup.py       the case (both formats), the System: the chosen blocks built on one time index
dispatch.py    the network from the blocks, the rules that join two blocks, the solve, the dispatch table
flows.py       bills, self-consumption and self-sufficiency, monthly table, value split (the reference's flows.py)
run_case.py    the command line: the battery study of a case, written as summary_<tag>.json and results_<tag>.xlsx
compare.py     the same reference case files through elements/battery_reference and through the blocks
tests/         parameters as the reference, overrides routing, electricity balance, short studies as the reference
```

The battery study itself (regime, size sweep, chosen size, payback) is in `elements/battery/study.py` and
`sizing.py`: it is the battery block on its own, with the rest of the system fixed.

## Case file

The system format (`setup.py`):

```json
{
  "input_file": "Example_input_PV_synthetic_2026.xlsx", "year": 2026, "tag": "example_CH",
  "market": {"country": "CH", "region": "GE", "utility": "SIG", "year": 2026},
  "blocks": {
    "greenhouse": {},
    "voltiris": {"modules": 500, "business_model": "direct_sales"},
    "existing_pv": {},
    "grid": {"import_max_kw": 750, "export_max_kw": 750, "regime": {"auto": true}},
    "battery": {"sizing": {"objective": "profit", "sweep_kwh": [100, 200]}}
  },
  "overrides": {"tech": {"battery": {"c_rate": 0.4}}}
}
```

A block not listed is not in the system; greenhouse and grid are required. `overrides` keep the reference layout and
each value goes to the block that owns it (`OWNS` in each block). A reference case file (no `blocks`) is read as the
same system: greenhouse, Voltiris (`pv_modules`, 0 included), grid, battery, and existing PV when `use_existing_pv` is
true; the interface adds `system.blocks` when the blocks are chosen by hand.

## Check against the reference (28 Oct 2026)

`compare.py` runs both models and compares the summary and every table cell by cell.

| Case | Result |
|---|---|
| CH, NL, FR examples (`examples/battery`) | identical to the last digit |
| CH EaaS; CH 0 modules; CH custom size with a fine grid; NL with ancillary off and overrides (C-rate, price tiers, module Wp, PV life); FR manual regime CU with `battery_export: any` and payback objective; FR EaaS | identical to the last digit |
| CH with a nonzero existing PV | same chosen size and regime; largest difference 7e-10 in absolute terms, 2e-11 relative |

The existing PV case differs in the last digits because the reference has one PV generator for Voltiris and existing
PV together, and the blocks have one each: the same LP, with the PV added in a different order. The interface was also
checked: the CH, NL and FR examples run through the page with the blocks give the same files as the reference.

## Not built yet

A plain run of any system (no sizing) with its KPIs, money and emissions, and buses for heat and CO2: `PLAN.md`
section 4. Today the engine runs the battery study only.
