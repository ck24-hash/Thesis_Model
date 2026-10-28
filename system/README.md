# system: the engine for the blocks

```
python system/run_case.py case.json            run a case with the blocks
python system/compare.py case.json [more]      run cases with both models and compare
python -m pytest system/tests -q               checks (about 2 min)
```

## Files

```
setup.py       the case (both formats), each block's input file read and aligned, the System of the chosen blocks,
               and the reference model's view of a case (one workbook, its case format)
dispatch.py    the network from the blocks, the rules that join two blocks, the solve, the dispatch table
flows.py       bills, self-consumption and self-sufficiency, monthly table, value split (the reference's flows.py)
run_case.py    the command line: the battery study of a case, written as summary_<tag>.json and results_<tag>.xlsx
compare.py     the same case files through elements/battery_reference and through the blocks
tests/         parameters as the reference, overrides routing, separate input files, electricity balance, short
               studies as the reference
```

The battery study itself (regime, size sweep, chosen size, payback) is in `elements/battery/study.py` and
`sizing.py`: it is the battery block on its own, with the rest of the system fixed.

## Case file

The system format (`setup.py`), one input file per block:

```json
{
  "year": 2026, "tag": "blocks_CH",
  "market": {"country": "CH", "region": "GE", "utility": "SIG", "year": 2026},
  "blocks": {
    "greenhouse": {"input_file": "greenhouse_load_2026.xlsx"},
    "voltiris": {"input_file": "voltiris_yield_2026.xlsx", "modules": 500},
    "existing_pv": {"input_file": "existing_pv_2026_hourly.xlsx"},
    "grid": {"input_file": "grid_day_ahead_2026.xlsx", "import_max_kw": 750, "export_max_kw": 750,
             "regime": {"auto": true}},
    "battery": {"sizing": {"objective": "profit", "sweep_kwh": [100, 200]}}
  },
  "general": {"commercial": {"business_model": "direct_sales"}},
  "overrides": {"tech": {"battery": {"c_rate": 0.4}}}
}
```

- `general` holds the general items' settings (`general/README.md`); commercial, subsidies and EMS are always part of
  the system, and the `System` joins them with the blocks (battery net price, investment, ancillary revenue).

- A block not listed is not in the system; greenhouse and grid are required. Blocks may share a file.
- `input_file` is relative to the case file or absolute; `columns` under a block renames its columns.
- The greenhouse load file sets the run's time steps; a coarser file (hourly, 30 min) is brought to 15 min, and every
  file must cover the load file's time steps. What each block reads: `examples/blocks/README.md`.
- `overrides` keep the reference layout and each value goes to the block or general item that owns it (`OWNS`).
- A reference case file (one `input_file`, no `blocks`) is read as the same system: every block reads that workbook.
- For the reference model, a system case becomes one workbook in its format (`reference_frame`) and its case format
  (`to_battery_case`): that is how `compare.py` and the interface's reference run type run it.

## Check against the reference (28 Oct 2026)

`compare.py` runs both models and compares the summary and every table cell by cell. All identical to the last digit:

| Cases | |
|---|---|
| `examples/battery`: CH, NL, FR, one workbook | identical |
| `examples/blocks`: CH, NL, FR and CH with existing PV (hourly file), one file per block | identical |
| variants: CH EaaS, CH with existing PV, CH 0 modules, CH custom size with a fine grid, NL with ancillary off and overrides (C-rate, price tiers, module Wp, PV life), FR manual regime CU with `battery_export: any` and payback objective, FR EaaS | identical |

The interface was checked too: the examples run through the page with either model give the same files.

## Not built yet

A plain run of any system (no sizing) with its KPIs, money and emissions, and buses for heat and CO2: `PLAN.md`
section 4. Today the engine runs the battery study only.
