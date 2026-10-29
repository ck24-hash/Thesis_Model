"""Checks of the blocks and the engine: python -m pytest system/tests -q (about 10 min).

The parameters and short battery studies are compared with the reference model (elements/battery_reference); the
electricity bus must balance at every step; each block reads its own input file; the heat and CO2 buses balance (with
and without heat storage) and the gas boiler's covering test holds; the heat storage's loss models; the electricity
side's split adds up; the joint sizing is no dearer than sizing one block at a time; the site's yearly cost adds up;
a system with nothing to size runs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from system import compare, dispatch, setup  # noqa: E402  (compare puts the reference model on the path)

import parameters as reference_parameters  # noqa: E402  (elements/battery_reference/parameters.py)

EXAMPLES = ROOT / "examples" / "battery"
BLOCK_EXAMPLES = ROOT / "examples" / "blocks"
MARKETS = [{"country": "CH", "region": "GE", "utility": "SIG", "year": 2026},
           {"country": "NL", "region": "WestlandInfra", "utility": "MS", "year": 2026},
           {"country": "FR", "region": "HTA", "utility": "Reference", "year": 2025}]


def without_about(d):
    return {k: without_about(v) for k, v in d.items() if k != "_about"} if isinstance(d, dict) else d


def like(ours, ref):
    """Ours restricted to the reference's keys: our blocks add their own (boiler, gas, demand, boiler prices)."""
    if isinstance(ours, dict) and isinstance(ref, dict):
        return {k: like(ours[k], v) for k, v in ref.items() if k in ours}
    return ours


def short(case: dict) -> dict:
    """The case with one battery size, to keep the test quick."""
    sizing = {"sweep_kwh": [100], "cap_at_subsidy_size": False}
    if "blocks" in case:
        return {**case, "blocks": {**case["blocks"], "battery": {"sizing": sizing}}}
    return {**case, "sizing": sizing}


@pytest.mark.parametrize("market", MARKETS, ids=lambda m: m["country"])
@pytest.mark.parametrize("business_model", ["direct_sales", "eaas"])
def test_parameters_as_reference(market, business_model):
    overrides = {"tech": {"battery": {"c_rate": 0.4}, "module_wp": 150}, "finance": {"pv_life_yr": 20},
                 "ancillary": {"rate_per_kw_year": 0}, "tariff": {"battery_export": "any"},
                 "capex": {"pv_per_wp": {"amount": 2.0}}}
    for ov in (None, overrides):
        ours = setup.parameters(market, business_model, ov)
        ref = reference_parameters.load(market["country"], market["region"], market["utility"], market["year"],
                                        business_model=business_model, overrides=ov)
        assert without_about(like(ours, ref)) == without_about(ref)


def test_subsidy_amount_is_not_money():
    """A subsidy has an "amount" among its settings; changing it must not turn the subsidy into a money value. A real
    money value given without a currency is read in the market's currency."""
    market = MARKETS[0]   # CH: CHF
    p = setup.parameters(market, overrides={"subsidies": {"pv": {"amount": 5000}, "battery": {"amount": 300}},
                                            "ems": {"capex": {"amount": 900}}})
    assert p["subsidies"]["pv"] == {"mode": "percent", "frac": 0.0, "amount": 5000, "threshold_modules": None}
    assert p["subsidies"]["battery"]["amount"] == 300 and p["subsidies"]["battery"]["mode"] == "threshold"
    assert p["ems"]["capex"] == 900   # CHF, not converted from the file's EUR


def test_overrides_go_to_their_block():
    owners = setup.OWNERS
    split = setup.P.split_overrides({"tech": {"battery": {"c_rate": 0.4}, "module_wp": 150}, "ems": {"capex": 0},
                                     "tariff": {"export": {"per_kwh": 0.1}}, "capex": {"pv_per_wp": 2},
                                     "ancillary": {"rate_per_kw_year": 0, "reserve": {"frac": 0}},
                                     "subsidies": {"pv": {"frac": 0.3}}}, owners)
    assert split["battery"] == {"tech": {"battery": {"c_rate": 0.4}}, "ancillary": {"reserve": {"frac": 0}}}
    assert split["voltiris"] == {"tech": {"module_wp": 150}}
    assert split["grid"] == {"tariff": {"export": {"per_kwh": 0.1}}}
    assert split["commercial"] == {"capex": {"pv_per_wp": 2}, "ancillary": {"rate_per_kw_year": 0}}
    assert split["subsidies"] == {"subsidies": {"pv": {"frac": 0.3}}}
    assert split["ems"] == {"ems": {"capex": 0}}
    with pytest.raises(KeyError, match="Unknown override group"):
        setup.P.split_overrides({"heat": {}}, owners)
    with pytest.raises(KeyError, match="Unknown override tech.cop"):
        setup.P.split_overrides({"tech": {"cop": 3}}, owners)


def test_blocks_not_built_or_missing():
    case = setup.load_case(EXAMPLES / "case_example_CH.json")
    index, inputs, _ = setup.read_inputs(case, setup.excel_reader())
    with pytest.raises(ValueError, match="Not built yet: heat_pump"):
        setup.System(index, inputs, case["market"], {"greenhouse": {}, "grid": {}, "heat_pump": {}})
    with pytest.raises(ValueError, match="missing: grid"):
        setup.System(index, inputs, case["market"], {"greenhouse": {}})


def test_separate_files():
    """Each block reads its own file; the hourly existing PV file is brought to 15 min with its energy kept; a file
    that misses time steps of the load file is refused."""
    case = setup.load_case(BLOCK_EXAMPLES / "case_blocks_CH_existing_pv.json")
    read = setup.excel_reader()
    index, inputs, steps = setup.read_inputs(case, read)
    assert {k: v["step_minutes"] for k, v in steps.items()} == {"greenhouse": 15, "voltiris": 15, "existing_pv": 60,
                                                               "grid": 15}
    assert len(index) == 35040 and all(s.index.equals(index) for s in inputs.values())
    hourly = read(case["blocks"]["existing_pv"]["input_file"])["Current PV feed-in (kW)"]
    assert abs(inputs["existing_pv_kw"].sum() * 0.25 - hourly.sum()) < 1e-6
    short_file = case["blocks"]["voltiris"]["input_file"]

    def truncated(path):
        return read(path).iloc[:-96] if path == short_file else read(path)
    with pytest.raises(ValueError, match="misses 96 of the 35040 time steps"):
        setup.read_inputs(case, truncated)


def test_electricity_balance_every_step():
    s = setup.build(json.loads((BLOCK_EXAMPLES / "case_blocks_CH_existing_pv.json").read_text()), BLOCK_EXAMPLES)
    n = dispatch.solve(s, "B", battery_kwh=200)
    res = dispatch.results(n, s)
    residual = res["pv"] + res["grid_import"] - res["grid_export"] + res["battery_power"] - res["load"]
    assert residual.abs().max() < 1e-6
    assert (res["pv"] - s.pv_total).abs().max() < 1e-9


@pytest.mark.parametrize("path", [EXAMPLES / "case_example_CH.json", EXAMPLES / "case_example_NL.json",
                                  BLOCK_EXAMPLES / "case_blocks_CH_existing_pv.json"], ids=lambda p: p.stem)
def test_short_study_as_reference(path):
    """One battery size, the whole study: the summary and every table equal to the last digit."""
    case = short(json.loads(path.read_text()))
    ref = compare.run_reference(case, path.parent, "t")
    new = compare.blocks.run(case, path.parent, "t", log=lambda *a, **k: None)[0]["battery"]
    assert compare.differences(ref, new) == []


# -- heat side: gas supply, gas boiler, greenhouse heat and CO2 ---------------------------------------------------------
@pytest.fixture(scope="module")
def boiler_system():
    return setup.build(json.loads((BLOCK_EXAMPLES / "case_blocks_CH_boiler.json").read_text()), BLOCK_EXAMPLES)


def test_daily_gas_price_to_15_min(boiler_system):
    """The daily gas price file is repeated in each quarter hour of its day."""
    s = boiler_system
    case = setup.load_case(BLOCK_EXAMPLES / "case_blocks_CH_boiler.json")
    _, _, steps = setup.read_inputs(case, setup.excel_reader())
    assert steps["gas_supply"]["step_minutes"] == 1440 and steps["greenhouse"]["step_minutes"] == 15
    daily = s.gas.price.resample("D")
    assert len(s.gas.price) == 35040 and (daily.max() - daily.min()).abs().max() == 0


def test_heat_and_co2_balance(boiler_system):
    """Every step: boiler heat + unmet = demand + released; boiler CO2 + unmet = demand + vented; gas x efficiency =
    heat. A boiler at the needed size leaves nothing unmet."""
    from elements.ng_boiler import sizing
    s = boiler_system
    size = sizing.needed_kw(s)
    res = dispatch.heat_results(dispatch.solve(s, "B", boiler_kw=size), s)
    heat = res["boiler_heat"] + res["heat_unmet"] - res["heat_demand"] - res["heat_release"]
    co2 = res["co2_from_boiler"] + res["co2_unmet"] - res["co2_demand"] - res["co2_vented"]
    assert heat.abs().max() < 1e-6 and co2.abs().max() < 1e-6
    assert (res["gas"] * s.boiler.efficiency - res["boiler_heat"]).abs().max() < 1e-6
    assert res["boiler_heat"].max() <= size + 1e-6
    assert res["heat_unmet"].sum() < 1e-6 and res["co2_unmet"].sum() < 1e-6


def test_boiler_covering(boiler_system):
    """A size under the needed one leaves heat unmet and does not cover; the needed size covers."""
    from elements.ng_boiler import sizing
    s = boiler_system
    need = sizing.needed_kw(s)
    small = sizing.evaluate_size(s, 0.8 * need, "B", log=lambda *a, **k: None)
    full = sizing.evaluate_size(s, need, "B", log=lambda *a, **k: None)
    assert not small["covers"] and small["unmet_heat_mwh"] > 0
    assert full["covers"] and full["lifetime_cost"] > full["investment"]
    assert sizing.choose(pd.DataFrame([small, full]).set_index("size"), "lifetime_cost", None) == need


# -- heat storage ---------------------------------------------------------------------------------------------------
def storage_system(mode: str = "constant", temp_file: bool = False):
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH_boiler.json").read_text())
    case["blocks"]["thermal_storage"] = ({"input_file": "outside_temperature_2026_hourly.xlsx"} if temp_file else {})
    case["overrides"] = {"thermal_storage": {"loss": {"mode": mode}}}
    return setup.build(case, BLOCK_EXAMPLES)


def test_storage_loss_models():
    """Constant: one share all year; seasonal: the season's share in each month; dynamic: the share at the reference
    when it is the reference temperature outside, more when colder, never below 0; dynamic without a temperature
    file is refused."""
    from elements.thermal_storage import block as ts
    p = storage_system().storage.params["thermal_storage"]["loss"]
    s = storage_system("seasonal")
    loss = s.storage.loss_per_hour
    assert loss[loss.index.month == 1].unique().tolist() == [p["seasonal_per_hour"]["winter"]]
    assert loss[loss.index.month == 7].unique().tolist() == [p["seasonal_per_hour"]["summer"]]
    d = p["dynamic"]
    temp = pd.Series([d["ref_outside_temp_c"], d["ref_outside_temp_c"] - 10, d["store_temp_c"] + 5],
                     index=pd.date_range("2026-01-01", periods=3, freq="h"))
    dyn = ts.loss_per_hour({**p, "mode": "dynamic"}, temp.index, temp)
    assert abs(dyn.iloc[0] - d["loss_per_hour_at_ref"]) < 1e-12 and dyn.iloc[1] > dyn.iloc[0] and dyn.iloc[2] == 0
    with pytest.raises(ValueError, match="needs the outside temperature"):
        storage_system("dynamic")
    assert storage_system("dynamic", temp_file=True).storage.loss_per_hour.nunique() > 1


def test_storage_balance():
    """With a heat storage: boiler heat + unmet + given back = demand + released + stored, at every step; the tank
    stays within its size and power; what goes in after the charge loss minus what comes out before the discharge
    loss is the heat lost, and it is positive."""
    s = storage_system()
    s.boiler_kw = 1350
    size = 2700
    res = dispatch.heat_results(dispatch.solve(s, "B", storage_kwh=size), s)
    heat = (res["boiler_heat"] + res["heat_unmet"] + res["storage_discharge"] - res["heat_demand"]
            - res["heat_release"] - res["storage_charge"])
    assert heat.abs().max() < 1e-6
    t = s.storage
    assert res["storage_soc"].max() <= size + 1e-6
    assert res["storage_charge"].max() <= t.power_kw(size) + 1e-6
    assert res["storage_discharge"].max() <= t.power_kw(size) + 1e-6
    lost = (res["storage_charge"] * t.eff_charge - res["storage_discharge"] / t.eff_discharge).sum() * s.dt
    assert lost > 0 and res["storage_charge"].sum() > 0


# -- electricity side -------------------------------------------------------------------------------------------------
def test_electricity_split_adds_up():
    """Every step: Voltiris + existing PV + battery + grid to the load = load; PV to the load, the battery and the
    grid = PV. The saving against no PV is the bill without PV minus the bill."""
    from system import electricity
    s = setup.build(json.loads((BLOCK_EXAMPLES / "case_blocks_CH_existing_pv.json").read_text()), BLOCK_EXAMPLES)
    res = dispatch.results(dispatch.solve(s, "B", battery_kwh=200), s)
    c = electricity.case(res, s, "B", "B", "test")
    sp, k = c["split"], c["kpi"]
    supply = sp["voltiris_to_load"] + sp["existing_to_load"] + sp["battery_to_load"] + sp["grid_to_load"]
    assert (supply - sp["load"]).abs().max() < 1e-6
    pv = sp["voltiris_to_load"] + sp["existing_to_load"] + sp["pv_to_battery"] + sp["pv_exported"]
    assert (pv - res["pv"]).abs().max() < 1e-6
    assert (sp["voltiris"] + sp["existing"] - res["pv"]).abs().max() < 1e-9
    assert abs(k["saving_vs_no_pv"] - (k["bill_no_pv"] - k["bill"])) < 1e-6
    assert abs(c["bills"].loc["Total", "test"] - k["bill"]) < 1e-6


# -- joint sizing and the site's yearly cost --------------------------------------------------------------------------
def test_joint_sizing():
    """Boiler and heat storage sized together: the heat balance holds, the boiler gives at most its size, and the
    site's yearly cost is no higher than with the boiler sized alone (no storage), counted the same way. The yearly
    cost adds up."""
    from system import costs, joint
    s = storage_system()
    blocks = {"ng_boiler": {}, "thermal_storage": {}}
    out = joint.run(s, blocks, log=lambda *a, **k: None)
    h, sizes = out["heat"], out["sizes"]
    heat = (h["boiler_heat"] + h["heat_unmet"] + h["storage_discharge"] - h["heat_demand"] - h["heat_release"]
            - h["storage_charge"])
    assert heat.abs().max() < 1e-6 and h["heat_unmet"].sum() == 0
    assert h["boiler_heat"].max() <= sizes["ng_boiler"] + 1e-6
    c = out["cost"]
    assert abs(c["total"] - c["running_total"] - c["investment_total"]) < 1e-6
    assert abs(c["running_total"] - sum(c["running"].values())) < 1e-6
    alone = out["without"]["thermal_storage"]
    assert alone["sizes"]["ng_boiler"] >= sizes["ng_boiler"]
    assert c["total"] <= alone["cost"]["total"] + 1e-6
    assert abs(out["value"]["thermal_storage"] - (alone["cost"]["total"] - c["total"])) < 1e-6


def test_plain_run():
    """A system with nothing to size: the electricity side and the site's yearly cost, the Voltiris modules spread
    over the PV life."""
    from system import run_case
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH.json").read_text())
    case["blocks"].pop("battery")
    out, s = run_case.run(case, BLOCK_EXAMPLES, "t", log=lambda *a, **k: None)
    assert out["mode"] == "sequential" and out["battery"] is None and out["boiler"] is None
    c, k = out["costs"], out["electricity"]["cases"]["no_battery"]["kpi"]
    assert abs(c["running"]["Grid: energy and network"] - k["import_cost"]) < 1e-6
    assert "Voltiris modules" in c["investment"] and c["total"] > 0
