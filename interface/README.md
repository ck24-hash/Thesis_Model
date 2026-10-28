# interface: one page for every run

```
python interface/app.py
```

It opens http://127.0.0.1:8775 (`--port` to change it, `--no-browser` to only print the address). Keep the console
window open while you use it; Ctrl+C stops it. It needs the models' Python packages
(`elements/battery_reference/requirements.txt`).

## Steps

1. **System**: load a case file, pick a scenario preset (`common/scenarios.json`, the thesis matrix) or tick the
   blocks yourself (`common/blocks.json`). The blocks chosen pick the model that runs them (the run type). A system no
   model can run yet is shown with the reason, and cannot be run.
2. **Input data**: the workbook, its time step, and its columns. A workbook with a coarser step than 15 min (hourly,
   30 min) is converted when it is read (`common/timeseries.py`): kW, W and prices are repeated in each quarter hour,
   kWh per step is divided. The converted file goes to `interface/app_data/converted/` and the run uses it.
3. **Market**: country, region, utility and tariff year.
4. **Parameters**: one card per chosen block, then the JSON overrides, the setup check (nothing is solved) and every
   parameter used.
5. **Run**: writes `case_<tag>.json` to the output folder and runs it.
6. **Results**: the run type's results and the files.

## Run types

A run type is one module in `adapters/`, the only place that knows a model. It gives `BLOCKS_REQUIRED` and
`BLOCKS_ALLOWED`, its markets, its columns (with unit and kind), its parameters, a preview, a run, and its progress
stages. When several fit the chosen blocks, step 1 shows a choice and the case file keeps it in `system.run_type`;
the first that fits is the default. Today there are two, for the same blocks (greenhouse electricity load + grid +
battery, with or without Voltiris and existing PV) and the same case file:

- `blocks` (`system_study.py`, the default): the blocks in `elements/` and the engine in `system/`, as
  `python system/run_case.py case_<tag>.json` runs them.
- `battery_study` (`battery_study.py`): the reference model `elements/battery_reference`, exactly as
  `python elements/battery_reference/run_case.py case_<tag>.json` would. The case file's extra `system` key is
  ignored by that model; `use_existing_pv` is true when the existing PV block is chosen.

Both write the same tables, drawn by the same results panel (`battery_view.py`). A case file without `system` (an
older battery case) opens with the battery study's blocks.

The battery model has no ancillary switch of its own: "off" in the battery card writes
`{"ancillary": {"rate_per_kw_year": 0, "reserve": {"mode": "percent", "frac": 0}}}` into the case file's overrides.

## Files

```
app.py              starts the server and opens the browser
server.py           local web server (standard library), 127.0.0.1 only
api.py              generic: options, case files, workbook and time step, run state
tables.py           JSON-ready values, the workbook kept in memory
adapters/           one module per run type
web/                the page: index.html, app.js, style.css, chart.umd.js (Chart.js 4.4.1, MIT licence)
app_data/           uploads and converted workbooks (created when used)
app_runs/<tag>/     default output folders (created when used)
```
