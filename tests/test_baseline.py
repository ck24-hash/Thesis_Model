import matplotlib
matplotlib.use("Agg")

from dataclasses import replace

import pandas as pd
import pytest

from ghmodel import Params
from ghmodel.data import load_inputs, make_dummy_input
from ghmodel.scenarios import baseline
from ghmodel.workflow import run_scenario


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    f = tmp_path_factory.mktemp("input") / "dummy.xlsx"
    make_dummy_input(f)
    return load_inputs(f)


@pytest.fixture(scope="module")
def base(data):
    return run_scenario(baseline.build, data, Params(), verbose=False)


def kpi(res):
    return res.summary.set_index("Indicator").Value


def test_all_demand_is_met(base):
    _, res = base
    k = kpi(res)
    assert k["Unserved heat"] == 0
    assert k["Unserved CO2"] == 0
    assert k["CO2 delivered to greenhouse"] == pytest.approx(k["CO2 demand"], rel=1e-6)


def test_gas_and_heat_are_consistent(base):
    _, res = base
    P = res.params
    k = kpi(res)
    assert k["Boiler heat output"] == pytest.approx(P.boiler_eta * k["Gas consumption"], rel=1e-6)
    # electricity demand is fixed and only served by the grid in the baseline
    assert k["Grid import"] == pytest.approx(k["Electricity demand"], rel=1e-6)


def test_heat_is_dumped_only_when_needed_for_co2(base):
    # heat is never dumped in hours where the boiler output is below demand
    _, res = base
    r = res.r
    assert (r.heat_dump[r.boiler_heat < r.heat_demand - 1e-9] < 1e-6).all()


def test_undersized_boiler_gives_unserved_demand_and_warning(data):
    with pytest.warns(UserWarning):
        _, res = run_scenario(baseline.build, data, replace(Params(), boiler_capacity_MW_th=0.6), verbose=False)
    assert kpi(res)["Unserved heat"] > 0


def test_storage_optimisation_is_not_worse_than_fixed_size(data, base):
    _, res_fixed = base
    n_opt, res_opt = run_scenario(baseline.build, data, replace(Params(), OPTIMISE_TES=True), verbose=False)
    # the fixed design is feasible for the optimised problem, so total cost cannot be higher
    assert res_opt.k["total_cost"] <= res_fixed.k["total_cost"] * (1 + 1e-6)
    # storage power linked to the optimised capacity (custom constraint)
    P = res_opt.params
    e_max_power = res_opt.k["tes_cap_final"] / P.tes_hours_at_full_power
    assert n_opt.links.at["TES charge", "p_nom_opt"] <= e_max_power + 1e-6
    assert n_opt.links.at["TES discharge", "p_nom_opt"] * P.tes_eta_discharge <= e_max_power + 1e-6


def test_storage_value_comparison(data, base):
    from ghmodel.analysis import storage_value
    _, res = base
    table, ind, res0 = storage_value(baseline.build, data, res.params, res)
    assert res0.k["tes_cap_final"] == 0 and kpi(res0)["Energy discharged from storage"] == 0
    saved = table["Saved by storage"]
    # cost items add up to the total, storage capex appears as a negative saving
    parts = ["Operating cost (OPEX)", "Annualised capex + O&M: boiler", "Annualised capex + O&M: storage",
             "Annualised capex + O&M: CHP"]
    assert saved[parts].sum() == pytest.approx(saved["Total annualised cost"])
    assert saved["Annualised capex + O&M: storage"] == pytest.approx(-res.k["capex_tes"])
    # storage can only lower the operating cost (no storage is a feasible operation of the same system)
    assert saved["Operating cost (OPEX)"] >= -1e-6

    # financial analysis of the storage (reference = same scenario without storage)
    from ghmodel.analysis import _npv, financial_analysis
    P = res.params
    fin = financial_analysis(res, res0, P, name="Baseline", ref_name="Baseline without storage")
    ind = fin["indicators"].Value
    assert ind["Additional investment"] == pytest.approx(res.k["tes_cap_final"] * P.tes_capex_EUR_per_kWh * 1e3)
    assert ind["Operating cost saving (incl. export revenue)"] == pytest.approx(saved["Operating cost (OPEX)"])
    assert _npv(fin["cash_flows"]["Net cash flow"].to_numpy(), fin["irr"]) == pytest.approx(0, abs=1e-3)   # IRR: NPV = 0
    # with the storage lifetime >= horizon, simple payback = investment / net yearly saving
    assert ind["Simple payback"] == pytest.approx(ind["Additional investment"] / ind["Net yearly cash saving"])


def test_ramp_limit_and_storage_reserve_hold(base):
    n, res = base
    P = res.params
    cap_fuel = n.links.at["NG boiler", "p_nom_opt"]
    assert n.links_t.p0["NG boiler"].diff().abs().max() <= P.boiler_ramp_limit_per_h * cap_fuel + 1e-6
    assert res.r.tes_soc.min() >= P.tes_min_soc_frac * res.k["tes_cap_final"] - 1e-6


def test_technical_constraints_can_be_switched_off(data):
    from ghmodel.sizing import resolve_sizes
    P = replace(Params(), boiler_ramp_limit_per_h=None, tes_min_soc_frac=0.0, tes_hours_at_full_power=None)
    n = baseline.build(data, P, resolve_sizes(data, P))
    assert pd.isna(n.links.at["NG boiler", "ramp_limit_up"])
    assert n.stores.at["TES", "e_min_pu"] == 0.0
    assert n.links.at["TES charge", "p_nom"] == pytest.approx(resolve_sizes(data, P).boiler_cap_th)


def test_missing_column_raises(tmp_path):
    import pandas as pd
    f = tmp_path / "in.xlsx"
    df = make_dummy_input(f)
    df.drop(columns=["co2_demand_kg_h"]).to_excel(f, sheet_name="hourly", index=False)
    with pytest.raises(KeyError):
        load_inputs(f)


def test_country_defaults_and_override():
    from ghmodel.config import COUNTRY_DEFAULTS
    P = Params(country="FR")
    assert P.co2_levy() == COUNTRY_DEFAULTS["FR"]["co2_levy_EUR_per_t"]
    assert P.grid_ef() == COUNTRY_DEFAULTS["FR"]["grid_ef_t_per_MWh"]
    P = Params(country="FR", co2_price_EUR_per_t=0.0, grid_co2_factor_t_per_MWh=0.2)   # explicit values win
    assert P.co2_levy() == 0.0 and P.grid_ef() == 0.2
    with pytest.raises(ValueError):
        Params(country="DE")


def test_dump_cost_enters_objective_and_reduces_dump(data, base):
    _, res_free = base
    # summarise() asserts that the objective equals the recomputed cost, incl. the dump/vent cost
    _, res_cost = run_scenario(baseline.build, data, replace(Params(), heat_dump_cost_EUR_per_MWh=20.0), verbose=False)
    assert kpi(res_cost)["Heat dump + CO2 vent cost"] > 0
    assert kpi(res_cost)["Heat dumped (rejected)"] <= kpi(res_free)["Heat dumped (rejected)"] + 1e-6


def test_daily_input_is_spread_over_24h(tmp_path):
    hourly = make_dummy_input(tmp_path / "h.xlsx").set_index("timestamp")
    demand = ["heat_demand_kW", "elec_demand_kW", "co2_demand_kg_h"]
    daily = hourly[demand].resample("D").sum()                              # daily totals: kWh/day, kg/day
    daily[["gas_price_EUR_per_MWh", "elec_price_EUR_per_MWh"]] = (
        hourly[["gas_price_EUR_per_MWh", "elec_price_EUR_per_MWh"]].resample("D").mean())
    f = tmp_path / "d.xlsx"
    daily.reset_index().to_excel(f, sheet_name="hourly", index=False)
    with pytest.warns(UserWarning, match="Daily input detected"):
        d = load_inputs(f)
    assert len(d) == 8760 and d.index.freq == "h"
    assert d.heat_demand_MW.sum() == pytest.approx(hourly.heat_demand_kW.sum() * 1e-3)      # annual energy kept
    assert d.co2_demand_t_h.sum() == pytest.approx(hourly.co2_demand_kg_h.sum() * 1e-3)
    day1 = d.loc["2023-01-01"]
    assert (day1.heat_demand_MW == daily.heat_demand_kW.iloc[0] * 1e-3 / 24).all()         # flat within the day
    assert (day1.gas_price_EUR_MWh == daily.gas_price_EUR_per_MWh.iloc[0]).all()           # prices repeated, not divided
    # same file without a timestamp column: 365 rows are read as days
    daily.reset_index(drop=True).to_excel(f, sheet_name="hourly", index=False)
    with pytest.warns(UserWarning, match="Daily input detected"):
        assert len(load_inputs(f)) == 8760


def test_resolution_from_row_count_and_leap_years(tmp_path):
    import warnings
    base = make_dummy_input(tmp_path / "h.xlsx").drop(columns="timestamp")
    f = tmp_path / "in.xlsx"

    def load(df, **kw):
        df.to_excel(f, sheet_name="hourly", index=False)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            d = load_inputs(f, **kw)
        return d, [str(x.message) for x in w]

    leap_daily = pd.concat([base.iloc[:365], base.iloc[:1]], ignore_index=True)          # 366 rows
    d, w = load(leap_daily.assign(timestamp=pd.date_range("2024-01-01", periods=366, freq="D")))
    assert len(d) == 8784 and not any("calendar year" in m for m in w)                    # leap year, daily
    d, w = load(leap_daily, start_timestamp="2023-01-01")                                 # no time column, wrong year
    assert len(d) == 8784 and any("not one calendar year" in m for m in w)
    leap_hourly = pd.concat([base, base.iloc[:24]], ignore_index=True)                    # 8784 rows
    d, w = load(leap_hourly, start_timestamp="2024-01-01")
    assert len(d) == 8784 and not any("Daily" in m or "calendar year" in m for m in w)
    with pytest.raises(ValueError, match="365 rows means daily"):                         # count and timestamps disagree
        load(base.iloc[:365].assign(timestamp=pd.date_range("2023-01-01", periods=365, freq="h")))


def test_partial_year_warns(tmp_path):
    f = tmp_path / "in.xlsx"
    df = make_dummy_input(f)
    df.iloc[:-1].to_excel(f, sheet_name="hourly", index=False)      # 8759 h, still strictly hourly
    with pytest.warns(UserWarning, match="not a full year"):
        load_inputs(f)
