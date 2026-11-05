"""Checks of the blocks and the engine: python -m pytest system/tests -q (about 10 min).

The parameters and short battery studies are compared with the reference model (elements/battery_reference); the
electricity bus must balance at every step; each block reads its own input file; the heat and CO2 buses balance (with
and without heat storage) and the gas boiler's covering test holds; the heat storage's loss models; the electricity
side's split adds up; the joint sizing is no dearer than sizing one block at a time; the site's yearly cost adds up;
a system with nothing to size runs; the effect of each technology matches its own study; the heat pump's COP, its
heat and electricity balances, and its joint size."""
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
    with pytest.raises(ValueError, match="Not built yet: data_center"):
        setup.System(index, inputs, case["market"], {"greenhouse": {}, "grid": {}, "data_center": {}})
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
    """One battery size, the blocks' battery sweep (the run's battery check): the summary and every table equal to
    the last digit."""
    case = short(json.loads(path.read_text()))
    ref = compare.run_reference(case, path.parent, "t")
    new = compare.sweep(case, path.parent, "t")
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
    """A size under the needed one leaves heat unmet and does not cover; the needed size covers, and its lifetime cost
    is its investment plus its yearly cost over its life."""
    from elements.ng_boiler import sizing
    s = boiler_system
    need = sizing.needed_kw(s)
    small = sizing.evaluate_size(s, 0.8 * need, "B", log=lambda *a, **k: None)
    full = sizing.evaluate_size(s, need, "B", log=lambda *a, **k: None)
    assert not small["covers"] and small["unmet_heat_mwh"] > 0
    assert full["covers"] and full["lifetime_cost"] > full["investment"]


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
    grid_net = sp["grid_to_load"] + sp["grid_to_battery"] - sp["pv_exported"] - sp["battery_to_grid"]
    assert (grid_net - (res["grid_import"] - res["grid_export"])).abs().max() < 1e-6
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
    base, _ = dispatch.choose_regime(s)
    alone = joint.optimise(s, base, {"ng_boiler": None}, 0.0, log=lambda *a, **k: None)   # the boiler without storage
    assert alone["sizes"]["ng_boiler"] >= sizes["ng_boiler"]
    assert c["total"] <= alone["cost"]["total"] + 1e-6


def test_plain_run():
    """A system with nothing to size: the electricity side and the site's yearly cost, the Voltiris modules spread
    over the PV life, the technical summary; no battery check."""
    from system import run_case
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH.json").read_text())
    case["blocks"].pop("battery")
    case["system"] = {"sensitivity": False}
    out, s = run_case.run(case, BLOCK_EXAMPLES, "t", log=lambda *a, **k: None)
    assert out["mode"] == "joint" and out["battery"] is None and out["boiler"] is None
    assert out["sensitivity"] is None and out["battery_check"] is None
    assert [r["block"] for r in out["technical"]["equipment"]] == ["voltiris"]
    c, k = out["costs"], out["electricity"]["cases"]["no_battery"]["kpi"]
    assert abs(c["running"]["Grid: energy and network"] - k["import_cost"]) < 1e-6
    assert "Voltiris modules" in c["investment"] and c["total"] > 0


# -- links between blocks, with and without each technology --------------------------------------------------------------------------------
def test_block_links():
    """A heat storage needs a heat source; leaving the boiler out takes the heat storage and the gas supply with it;
    greenhouse and grid always stay."""
    assert setup.link_problems(["greenhouse", "grid", "thermal_storage"])
    assert not setup.link_problems(["greenhouse", "grid", "gas_supply", "ng_boiler", "thermal_storage"])
    blocks = ["greenhouse", "voltiris", "grid", "gas_supply", "ng_boiler", "thermal_storage", "battery"]
    assert setup.leave_out(blocks, ["ng_boiler"]) == (["greenhouse", "voltiris", "grid", "battery"],
                                                     ["gas_supply", "thermal_storage"])
    assert setup.leave_out(blocks, ["grid", "battery"])[0] == ["greenhouse", "voltiris", "grid", "gas_supply",
                                                               "ng_boiler", "thermal_storage"]


def test_battery_joint_check_and_sensitivity():
    """The battery sized together (at most the largest size of its list), checked against the reference sweep, then
    each size -10 % and +10 %: the sweep keeps a size of its list; the year at the chosen sizes costs the site's yearly
    cost; the battery lowers the site's yearly cost by about its yearly value minus its cost per year over the PV
    life (the joint sizing's battery terms are linear)."""
    from system import costs, run_case
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH.json").read_text())
    case["blocks"]["battery"] = {"sizing": {"sweep_kwh": [500, 1000], "cap_at_subsidy_size": False}}
    out, s = run_case.run(case, BLOCK_EXAMPLES, "t", log=lambda *a, **k: None)
    size, bc, sens = out["joint"]["sizes"]["battery"], out["battery_check"], out["sensitivity"]["table"]
    assert 0 < size <= 1000 and bc["sweep"]["size"] in (500, 1000) and bc["joint"]["size"] == size
    base = sens[sens["block"].isna()].iloc[0]
    assert abs(base["yearly_cost"] - out["costs"]["total"]) < 1e-3 * out["costs"]["total"]
    assert set(sens["block"].dropna()) == {"voltiris", "battery"} and sens["solved"].all()
    e, sm = out["effects"]["battery"], out["battery"]["summary"]
    assert e["evaluated"] and e["also"] == [] and out["effects"]["voltiris"]["evaluated"]
    expected = sm["battery_value_yr"] - costs.battery_per_year(s, sm["battery_kwh"])
    assert abs(e["difference"] - expected) < 0.02 * sm["battery_value_yr"]


def test_quick_ems_check(monkeypatch):
    """The battery's EMS check in the systems without a technology (quick): with the battery at its limit, its least
    saving beyond its own cost (size x the limit's shadow price) is at most the saving found against the year without
    it, covers its EMS costs here, and no year without it is solved; the site's yearly cost is the full check's. When
    that does not decide, the year without it with the other sizes kept gives the same cost (none to size here)."""
    from system import costs, joint
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH.json").read_text())
    case["blocks"]["battery"] = {"sizing": {"sweep_kwh": [500, 1000], "cap_at_subsidy_size": False}}
    s = setup.build(case, BLOCK_EXAMPLES)
    base, _ = dispatch.choose_regime(s)
    plan, quiet = joint.plan_of(s, case["blocks"]), lambda *a, **k: None
    full, without, _ = joint.optimise_with_ems(s, base, plan, 1000.0, quiet)
    quick, none, _ = joint.optimise_with_ems(s, base, plan, 1000.0, quiet, quick=True)
    size, total = full["sizes"]["battery"], full["cost"]["total"]
    assert none is None and quick["sizes"]["battery"] == size == 1000 and quick["limit_gain"] > 0
    assert abs(quick["cost"]["total"] - total) < 1e-6 * total
    hw = costs.battery_per_year(s, size) - costs.battery_per_year(s, size, ems_hardware=False)
    saving = without["cost"]["total"] - (total - full["cost"]["running"]["Battery: EMS"] - hw)
    assert quick["limit_gain"] <= saving + 1e-6 * total
    monkeypatch.setattr(joint, "_pays_at_limit", lambda *a: False)
    kept, without_kept, _ = joint.optimise_with_ems(s, base, plan, 1000.0, quiet, quick=True)
    assert without_kept is not None and abs(kept["cost"]["total"] - total) < 1e-6 * total


# -- external CO2 ---------------------------------------------------------------------------------------------------
def test_external_co2():
    """Buying CO2 or burning gas for it: the CO2 balance holds, the demand is met, CO2 is bought in summer (cheap in
    the example) and not in winter (the boiler runs for heat, its flue gas CO2 is free). Without a boiler all the CO2
    is bought."""
    from system import run_case
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH_boiler_co2.json").read_text())
    s = setup.build(case, BLOCK_EXAMPLES)
    s.boiler_kw = 1350
    res = dispatch.heat_results(dispatch.solve(s, "B"), s)
    co2 = res["co2_from_boiler"] + res["co2_bought"] + res["co2_unmet"] - res["co2_demand"] - res["co2_vented"]
    assert co2.abs().max() < 1e-6 and res["co2_unmet"].sum() < 1e-6
    by_month = res["co2_bought"].groupby(res.index.month).sum()
    assert by_month[7] > 0 and by_month[1] == 0
    alone = {**case, "blocks": {k: v for k, v in case["blocks"].items() if k in ("greenhouse", "grid", "external_co2")},
             "system": {"sensitivity": False}}
    out, s2 = run_case.run(alone, BLOCK_EXAMPLES, "t", log=lambda *a, **k: None)
    assert abs(out["costs"]["other"]["CO2 bought (t)"] - (s2.greenhouse.co2 * s2.dt).sum() / 1000) < 1e-6
    assert out["costs"]["running"]["CO2 bought"] > 0


def test_effects_keep_a_source():
    """The gas boiler, the only heat source, is not evaluated; the external CO2 is (the boiler remains a CO2 source)."""
    from system import effects
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH_boiler_co2.json").read_text())
    blocks = list(case["blocks"])
    assert set(effects.removable(blocks)) == {"voltiris", "ng_boiler", "external_co2"}
    assert effects.lost_demand(blocks, setup.leave_out(blocks, ["ng_boiler"])[0])
    assert effects.lost_demand(blocks, setup.leave_out(blocks, ["external_co2"])[0]) is None


def test_savings_add_up():
    """What the PV and the battery save, flow by flow, adds up to the bill differences."""
    from system import electricity
    s = setup.build(json.loads((BLOCK_EXAMPLES / "case_blocks_CH_existing_pv.json").read_text()), BLOCK_EXAMPLES)
    res_nb = dispatch.results(dispatch.solve(s, "B"), s)
    res_b = dispatch.results(dispatch.solve(s, "B", battery_kwh=500), s)
    fake = {"summary": {"regime_battery": "B", "battery_kwh": 500}, "dispatch": res_b, "dispatch_no_battery": res_nb}
    e = electricity.run(s, battery=fake, log=lambda *a, **k: None)
    nb, b = e["cases"]["no_battery"], e["cases"]["battery"]
    pv = nb["pv_savings"]["parts"]
    assert abs(pv["Total"] - nb["kpi"]["saving_vs_no_pv"]) < 1e-6
    assert abs(sum(v for k, v in pv.items() if k != "Total") - pv["Total"]) < 1e-6
    bs = b["battery_savings"]["parts"]
    assert abs(bs["Total"] - (nb["kpi"]["bill"] - b["kpi"]["bill"])) < 1e-6
    assert abs(bs["Other (regime, EaaS fee)"]) < 1e-6   # same regime, direct sales: the flows explain it all


def test_heat_pump():
    """The heat pump: its dynamic COP follows the formula; with fixed sizes the heat bus balances with its heat, its
    heat is COP x electricity and at most its size, and its draw is part of the site's load on a balanced electricity
    bus. With a carbon levy that makes gas dearer, the joint sizing gives it a size and the heat demand is met; with
    the example prices (no levy) its heat costs more than the boiler's and it gets none."""
    from elements.heat_pump import block as heat_pump
    from system import joint
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH_heat_pump.json").read_text())
    levy = {**case, "overrides": {"gas": {"co2_levy_per_kg": 0.12}}}
    s = setup.build(levy, BLOCK_EXAMPLES)
    hp = s.heat_pump
    t = hp.outside_temp.reindex(s.index)
    assert (hp.cop - 3.0 * (60 - 7) / (60 - t)).abs().max() < 1e-12
    assert abs(heat_pump.cop_series({"cop": {"mode": "constant", "nominal": 2.5}}, s.index).mean() - 2.5) < 1e-12
    s.boiler_kw, s.heat_pump_kw = 1350.0, 400.0
    n = dispatch.solve(s, "B")
    heat, res = dispatch.heat_results(n, s), dispatch.results(n, s)
    balance = (heat["boiler_heat"] + heat["hp_heat"] + heat["heat_unmet"] - heat["heat_demand"]
               - heat["heat_release"])
    assert balance.abs().max() < 1e-6
    assert (heat["hp_heat"] - hp.cop * heat["hp_electricity"]).abs().max() < 1e-6
    assert heat["hp_heat"].max() <= 400.0 + 1e-6 and heat["hp_heat"].sum() > 0
    assert (res["load"] - res["greenhouse_load"] - res["heat_pump"]).abs().max() < 1e-9
    assert (res["pv"] + res["grid_import"] - res["grid_export"] - res["load"]).abs().max() < 1e-6
    j = joint.run(setup.build(levy, BLOCK_EXAMPLES), levy["blocks"], log=lambda *a, **k: None)
    assert j["sizes"]["heat_pump"] > 0 and j["heat"]["heat_unmet"].sum() < 1e-6
    j0 = joint.run(setup.build(case, BLOCK_EXAMPLES), case["blocks"], log=lambda *a, **k: None)
    assert j0["sizes"]["heat_pump"] == 0


def test_heat_pump_eaas():
    """Under EaaS the PV surplus runs the heat pump first: during a surplus the site imports at most what the heat pump
    draws beyond it (time sharing within the step), nothing where the surplus runs it whole; the heat pump as the only
    heat source can be sized."""
    from system import joint
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH_heat_pump.json").read_text())
    for b in ("ng_boiler", "gas_supply"):
        case["blocks"].pop(b)
    case["general"]["commercial"]["business_model"] = "eaas"
    case["blocks"]["voltiris"]["modules"] = 6000
    s = setup.build(case, BLOCK_EXAMPLES)
    s.heat_pump_kw = float(s.greenhouse.heat.max())
    res = dispatch.results(dispatch.solve(s, "B"), s)
    surplus = (s.pv_total - s.load).clip(lower=0)
    on = surplus > 0
    p_max = s.heat_pump_kw / s.heat_pump.cop
    bound = (1 - surplus / p_max).clip(lower=0) * res["heat_pump"]
    assert on.sum() > 0 and (res["grid_import"] - bound)[on].max() < 1e-6
    assert res["grid_import"][on & (p_max <= surplus)].max() < 1e-6
    j = joint.run(setup.build(case, BLOCK_EXAMPLES), case["blocks"], log=lambda *a, **k: None)
    assert j["sizes"]["heat_pump"] > 0 and j["heat"]["heat_unmet"].sum() < 1e-6


def test_custom_size_zero():
    """A size fixed at 0 is a fixed size (the block is left out), not a free one."""
    from system import joint
    case = json.loads((BLOCK_EXAMPLES / "case_blocks_CH_heat_pump.json").read_text())
    case["blocks"]["ng_boiler"]["sizing"] = {"objective": "custom", "custom_kw": 0}
    plan = joint.plan_of(setup.build(case, BLOCK_EXAMPLES), case["blocks"])
    assert plan == {"ng_boiler": 0.0, "heat_pump": None}
