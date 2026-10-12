# Project context for Claude Code

Master thesis at EPFL with Voltiris: **"A Path to Greenhouse Self-Sufficiency: Heat and CO2"**.
Techno-economic model (PyPSA, hourly, one year, LP) of a commercial greenhouse that becomes more self-sufficient in heat, CO2 and electricity.
Keep answers focused on this system (greenhouse, Voltiris PV, data center waste heat, heat pump, SOFC, thermal storage, backup boiler, grid, CO2 supply). Countries: Switzerland, France, Netherlands.

## Scenarios (from `docs/Scenarios.png`)
- **Baseline**: NG boiler + thermal storage + grid import. (implemented)
- **S1**: CHP (NG) with heat, CO2 and electricity, export to grid; backup boiler; CHP has dispatch priority over boiler and grid import. (implemented)
- **S2**: Voltiris + heat pump + thermal storage, NG boiler kept as backup and CO2 source. Variants: + battery; + battery + external liquid CO2 (boiler removed).
- **S3**: S2 plus data center powered by Voltiris; DC waste heat is the heat pump source. Same three variants.
- **S4**: Voltiris x data center x SOFC (ethanol fuel), heat pump with DC heat source, thermal storage, battery, grid. SOFC supplies electricity, heat and CO2.
- Fuels: natural gas (boiler, CHP) and ethanol (SOFC), each with its own price and emission factor.

## Flow rules
- DC heat reaches the greenhouse **only through the heat pump**.
- Where no boiler is drawn, heat must still be fully covered: state the backup assumption explicitly.
- Any flow not drawn in the figure (heat dump, CO2 vent, ...) is an **assumption**: flag it in code comments and in text.
- When information is uncertain, state the assumption and what data would confirm it.

## Conventions
- Units: MW, MWh, t CO2, EUR. Prices EUR/MWh and EUR/t. Gas price is LHV, all-in except the carbon levy, which is added separately.
- Emissions: all CO2 from burning gas counts as emitted, including the CO2 dosed into the greenhouse.
- `Params.country` (CH/FR/NL) sets default carbon levy and grid emission factor (`COUNTRY_DEFAULTS`, placeholders); explicit values override.
- Heat dump and CO2 vent are free by default; costs can be set (`heat_dump_cost_EUR_per_MWh`, `co2_vent_cost_EUR_per_t`).
- Every modelling assumption is also listed in README "Main assumptions" (copied into the thesis).
- Open (not decided yet): ethanol CO2 accounting for S4; backup heat for the variants without a boiler.
- Buses: `gas`, `elec`, `heat`, `tes`, `co2` (see `src/ghmodel/blocks.py`). Link ports: `p0` taken from bus0, `p1`/`p2`/`p3` negative when delivered. Sinks are Generators with `sign=-1`.
- Grid export is a revenue (Generator sign=-1 with marginal cost = − export price, input column `elec_export_price_EUR_per_MWh`).
- CHP priority (`chp_priority`) is an internal dispatch penalty on boiler heat and grid import; it is never part of a reported cost.
- Financial analysis (`analysis.financial_analysis`): equipment of a scenario vs a reference run (S1 vs Baseline; in the Baseline the storage vs no storage). 20-year horizon, replacements, salvage, IRR only if the investment pays back.
- Results table `r` has all flows positive. Hourly balances must close (`check_balances`), unserved heat/CO2 must be 0.
- Link `p_nom` is on the bus0 side (fuel side for boiler), so thermal capacity is divided by efficiency.
- Parameters live in `Params` (`config.py`), `None` means automatic sizing. Placeholders are marked `[placeholder]`.
- Capex is annualised (annuity + fixed O&M share). It only enters the objective if the size is optimised (`OPTIMISE_BOILER`, `OPTIMISE_TES`, `OPTIMISE_CHP`), but is always reported in the total annualised cost.

## Code structure and workflow
- Logic in `src/ghmodel/` (config, data, sizing, blocks, scenarios/, workflow, results, analysis, plots). Notebooks in `notebooks/` only call it. Repository map: `docs/repository/README.md`.
- New scenario: add blocks in `blocks.py` + one page per block in `docs/blocks/`, compose them in `scenarios/<name>.py` with `build(data, P, sizes)`, add the components to `results.py` (zero if absent, same KPI rows) and `analysis.investments`, add a test file and a notebook (structure of `02_s1_chp.ipynb`), run with `run_scenario`.
- When a block or parameter changes, update its page in `docs/blocks/`.
- Run tests with `pytest` (about 2 min). Keep them passing.
- Do not commit real input data (`data/*.xlsx` is git-ignored).

## Environment and commands (Windows, Python 3.14, `.venv`)
- Setup: `py -3.14 -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt` and `.venv\Scripts\pip install -e .`. Exact tested versions: `requirements-lock.txt`.
- Tests: `.venv\Scripts\python.exe -m pytest -q`. If pytest cannot access its temp dir, add `--basetemp=<some temp dir>`.
- Headless notebook: the notebook finds the project root by searching for `src/ghmodel`, so copy `src/` and the notebook into a temp project folder (`<tmp>/proj/src`, `<tmp>/proj/notebooks`), then run `jupyter nbconvert --to notebook --execute --output executed.ipynb 01_baseline.ipynb` there (same for `02_s1_chp.ipynb`). Running in place writes `data/<scenario>_input_data.xlsx` (dummy if missing) and `results/<scenario>/`.
- Set `PYTHONIOENCODING=utf-8` when printing notebook content (CO₂ characters).

## Current limitations
- Pure LP: no minimum load or start-up cost (CHP and boiler can cycle hourly at any part load).
- Heat and CO2 self-sufficiency are 0 until non-fossil sources exist (S2+); electricity self-sufficiency = on-site generation used on site / demand.
- Financial sensitivity is first order (dispatch not re-optimised).
- `data/*_input_data.xlsx` may be the generated dummy: check its README sheet before trusting results.

## Outputs the thesis needs (keep in every scenario)
Heat, CO2 and electricity self-sufficiency; total annualised cost; annual savings and payback / IRR vs baseline; grid import/export; fuel use; CO2 emissions or avoided emissions; storage size and use; heat pump electricity; data center heat utilisation; required SOFC and data center capacity; required backup heating.

## Style
Clear, technical, practical engineering language. Explain assumptions before equations or code. Compact, student-like text for the literature review. Do not drift into generic sustainability or unrelated topics.
