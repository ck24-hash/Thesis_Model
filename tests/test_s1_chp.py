import matplotlib
matplotlib.use("Agg")

from dataclasses import replace

import pytest

from ghmodel import Params
from ghmodel.analysis import compare_scenarios, financial_analysis
from ghmodel.data import load_inputs, make_dummy_input
from ghmodel.scenarios import baseline, s1_chp
from ghmodel.workflow import run_scenario

TOL = 1e-6


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    f = tmp_path_factory.mktemp("input") / "dummy_s1.xlsx"
    make_dummy_input(f, export_price=True)
    return load_inputs(f)


@pytest.fixture(scope="module")
def s1(data):
    return run_scenario(s1_chp.build, data, Params(), verbose=False)


def kpi(res):
    return res.summary.set_index("Indicator").Value


def test_s1_demand_met_and_chp_conversion(s1):
    _, res = s1
    P, r, k = res.params, res.r, kpi(res)
    assert k["Unserved heat"] == 0 and k["Unserved CO2"] == 0
    assert k["CO2 delivered to greenhouse"] == pytest.approx(k["CO2 demand"], rel=1e-6)
    assert (r.chp_elec - P.chp_eta_el * r.chp_gas).abs().max() < TOL
    assert (r.chp_heat - P.chp_eta_th * r.chp_gas).abs().max() < TOL
    assert (r.chp_co2 - P.gas_co2_factor_t_per_MWh * P.chp_co2_usable_fraction * r.chp_gas).abs().max() < TOL
    assert k["Gas consumption"] == pytest.approx(k["Gas to CHP"] + k["Gas to boiler"])


def test_s1_export_is_revenue(s1):
    _, res = s1
    r, k = res.r, kpi(res)
    assert k["Grid export"] > 0
    assert k["Electricity export revenue (income)"] == pytest.approx((r.grid_export * r.export_price).sum())
    opex_parts = (k["Gas cost"] + k["CO2 levy on gas"] + k["Electricity purchase"] + k["CHP variable O&M"]
                  + k["Heat dump + CO2 vent cost"] - k["Electricity export revenue (income)"])
    assert k["Operating cost (OPEX, net of export revenue)"] == pytest.approx(opex_parts)


def test_s1_chp_has_priority(s1):
    # backup boiler and grid import are only used when the CHP is at full capacity
    n, res = s1
    r, cap_fuel = res.r, n.links.at["CHP", "p_nom_opt"]
    chp_full = r.chp_gas >= cap_fuel - 1e-6
    assert chp_full[r.boiler_heat > 1e-6].all()
    assert chp_full[r.grid_import > 1e-6].all()


def test_s1_priority_off_is_cheaper_or_equal(data, s1):
    # the priority only restricts the dispatch, so cost-optimal dispatch cannot be more expensive
    _, res_prio = s1
    _, res_free = run_scenario(s1_chp.build, data, replace(Params(), chp_priority=False), verbose=False)
    assert res_free.k["total_cost"] <= res_prio.k["total_cost"] * (1 + 1e-6)


def test_s1_needs_export_price(tmp_path):
    f = tmp_path / "no_export.xlsx"
    make_dummy_input(f)
    with pytest.raises(KeyError, match="elec_export_price"):
        run_scenario(s1_chp.build, load_inputs(f), Params(), verbose=False)


def test_s1_financials_vs_baseline(data, s1):
    _, res = s1
    _, res_base = run_scenario(baseline.build, data, Params(), verbose=False)
    P = res.params
    fin = financial_analysis(res, res_base, P, name="S1", ref_name="Baseline")
    ind = fin["indicators"].Value
    # same boiler and storage in both: the additional investment is the CHP
    assert ind["Additional investment"] == pytest.approx(res.k["chp_cap_final"] * P.chp_capex_EUR_per_kW_el * 1e3)
    assert ind["Operating cost saving (incl. export revenue)"] == pytest.approx(res_base.k["opex"] - res.k["opex"])
    table = compare_scenarios({"Baseline": res_base, "S1": res})
    assert list(table.columns) == ["Baseline", "S1", "Unit"] and len(table) == len(res.summary)
