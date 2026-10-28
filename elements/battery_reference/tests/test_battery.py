"""Checks of each block and of the engine on invented numbers (no grower data).

    python -m pytest models/battery/tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import parameters  # noqa: E402
from blocks import capex, finance, subsidies  # noqa: E402
from blocks.ems import Ems  # noqa: E402
from blocks.tariffs import Tariff  # noqa: E402
from blocks.tech import Battery  # noqa: E402
from engine import dispatch, flows, inputs, pipeline  # noqa: E402
from engine.setup import Setup  # noqa: E402

CH = dict(country="CH", region="GE", utility="SIG", year=2026)
NL = dict(country="NL", region="WestlandInfra", utility="MS", year=2026)
FR = dict(country="FR", region="HTA", utility="Reference", year=2025)
QUIET = dict(log=lambda *a, **k: None)


@pytest.fixture(scope="module")
def ch():
    return parameters.load(**CH)


# -- parameters ---------------------------------------------------------------------------------------------------
def test_market_files_merge_country_region_utility(ch):
    t = ch["tariff"]
    assert t["currency"] == "CHF"                                  # country file
    assert t["network_levy_pct"] == 0.132                          # canton file
    assert t["utility"] == "SIG"                                   # utility file
    assert t["import_price"]["federal"]["per_kwh"] == 0.0276       # country component kept beside the utility's
    assert set(t["import_price"]) == {"energy", "network", "federal"}


def test_shared_money_is_the_same_real_price_everywhere(ch):
    nl = parameters.load(**NL, business_model="eaas")
    assert ch["capex"]["battery_tiers_per_kwh"] == [[100, 400], [2000, 400]]   # CH unchanged
    assert nl["capex"]["battery_tiers_per_kwh"] == [[100, 436.0], [2000, 436.0]]
    assert nl["capex"]["pv_per_wp"] == pytest.approx(1.962)
    assert ch["ems"]["fixed_per_year"] == 2500 and nl["ems"]["fixed_per_year"] == pytest.approx(2725)
    assert ch["ems"]["capex"] == pytest.approx(1000 / 1.09) and nl["ems"]["capex"] == 1000
    assert nl["business_model"]["price_per_mwh"] == pytest.approx(196.2)
    assert ch["ancillary"]["rate_per_kw_year"] == 90 and nl["ancillary"]["rate_per_kw_year"] == 98.1
    assert ch["tariff"]["eur_to_local"] == pytest.approx(1 / 1.09) and nl["tariff"]["eur_to_local"] == 1.0
    assert ch["tech"] == nl["tech"]                                            # tech the same everywhere


def test_overrides_change_one_value_only():
    p = parameters.load(**CH, overrides={"tariff": {"export": {"per_kwh": 0.066}}})
    assert p["tariff"]["export"]["per_kwh"] == 0.066
    assert p["tariff"]["export"]["basis"] == "fixed"


def test_an_override_is_in_the_market_currency():
    nl = parameters.load(**NL, overrides={"ems": {"fixed_per_year": {"amount": 3000}}, "capex": {"pv_per_wp": 2.0}})
    assert nl["ems"]["fixed_per_year"] == 3000 and nl["capex"]["pv_per_wp"] == 2.0
    ch = parameters.load(**CH, overrides={"ems": {"capex": {"amount": 900}}})
    assert ch["ems"]["capex"] == 900


def test_a_peak_window_past_midnight_is_refused():
    with pytest.raises(ValueError):
        Tariff(parameters.load(**FR, overrides={"tariff": {"calendar": {"peak_hours": {"mon": [17, 2]}}}})["tariff"])


def test_unknown_market_or_block_is_refused():
    with pytest.raises(FileNotFoundError):
        parameters.load("CH", "GE", "SIG", 1999)
    with pytest.raises(KeyError):
        parameters.load(**CH, overrides={"tarif": {}})


# -- tariffs: CH ----------------------------------------------------------------------------------------------------
def test_ch_price_is_energy_plus_network_with_levy_plus_federal(ch):
    t = Tariff(ch["tariff"])
    idx = pd.DatetimeIndex(["2026-01-05 12:00", "2026-07-05 03:00"])   # winter weekday HP, summer Sunday night HD
    a = t.import_price(idx, "A").tolist()
    b = t.import_price(idx, "B").tolist()
    assert a[0] == pytest.approx(0.1130 + 0.0685 * 1.132 + 0.0276)
    assert b[1] == pytest.approx(0.0720 + 0.0275 * 1.132 + 0.0276)


def test_ch_peak_hours_weekday_and_weekend(ch):
    t = Tariff(ch["tariff"])
    idx = pd.DatetimeIndex(["2026-01-05 06:45", "2026-01-05 07:00", "2026-01-05 21:45", "2026-01-05 22:00",
                            "2026-01-10 16:45", "2026-01-10 17:00"])   # Monday x4, Saturday x2
    assert t.hp_mask(idx).tolist() == [False, True, True, False, False, True]
    assert all(t.is_hp(ts) == hp for ts, hp in zip(idx, t.hp_mask(idx)))


def test_ch_regime_from_dup(ch):
    t = Tariff(ch["tariff"])
    assert t.regime_of(3000) == "A" and t.regime_of(3001) == "B"
    assert t.other_regime("A") == "B"


def test_ch_demand_charge_ratchets_over_the_year(ch):
    t = Tariff(ch["tariff"])
    idx = pd.date_range("2026-01-05 12:00", periods=3, freq="31D")   # three weekday noons, Jan to Mar
    imp = pd.Series([100.0, 50.0, 80.0], index=idx)
    assert t.billed_peaks(t.main_monthly_charge, imp).tolist()[:4] == [100.0, 100.0, 100.0, 100.0]
    assert t.yearly_capacity_charge(imp, "A") == pytest.approx(12 * 100 * 6.40 * 1.132)


# -- tariffs: NL ----------------------------------------------------------------------------------------------------
def test_nl_price_is_day_ahead_plus_tax_and_transport():
    t = Tariff(parameters.load(**NL)["tariff"])
    idx = pd.date_range("2026-01-01", periods=3, freq="15min")
    assert t.import_price(idx, "default", da=[0.05, -0.10, 0.20]).tolist() == pytest.approx(
        [0.05 + 0.06155, -0.10 + 0.06155, 0.20 + 0.06155])
    assert t.export_price(idx, da=[0.05, -0.10, 0.20]).tolist() == [0.05, -0.10, 0.20]


def test_nl_capacity_fee_is_year_peak_plus_each_month_peak():
    t = Tariff(parameters.load(**NL)["tariff"])
    idx = pd.DatetimeIndex(["2026-01-10 03:00", "2026-01-20 12:00", "2026-02-10 12:00"])
    imp = pd.Series([300.0, 200.0, 250.0], index=idx)   # all hours count, no ratchet
    assert t.yearly_capacity_charge(imp, "default") == pytest.approx(300 * 24.4839 + (300 + 250) * 3.0860)


# -- tariffs: FR ----------------------------------------------------------------------------------------------------
def test_fr_slots_follow_turpe_7():
    t = Tariff(parameters.load(**FR)["tariff"])
    idx = pd.DatetimeIndex(["2025-01-04 08:15",   # Saturday in January, morning pointe window
                            "2025-01-05 12:00",   # Sunday: all off-peak
                            "2025-03-03 08:30",   # March: winter but no pointe
                            "2025-01-06 05:45",   # before 06:00: off-peak
                            "2025-07-05 12:00",   # summer Saturday noon
                            "2025-07-06 12:00"])  # summer Sunday
    assert t.slots(idx).tolist() == ["pointe", "HCH", "HPH", "HCH", "HPB", "HCB"]


def test_fr_price_is_supplier_plus_turpe_plus_gc_plus_accise():
    t = Tariff(parameters.load(**FR)["tariff"])
    idx = pd.DatetimeIndex(["2025-01-04 08:15", "2025-01-04 12:00", "2025-07-06 12:00"])
    assert (t.import_price(idx, "LU") * 1000).tolist() == pytest.approx(
        [104.04 + 26.5 + 8.765095 + 30.85, 104.04 + 21.0 + 8.765095 + 30.85, 47.80 + 6.8 + 30.85])


def test_fr_staircase_charge():
    t = Tariff(parameters.load(**FR)["tariff"])
    c = t.charges[0][1]
    idx = pd.DatetimeIndex(["2025-01-06 08:30", "2025-01-06 12:00", "2025-07-07 12:00"])   # pointe, HPH, HPB
    imp = pd.Series([100.0, 150.0, 120.0], index=idx)
    p = t.subscribed_powers(c, imp)
    assert [p[s] for s in ("pointe", "HPH", "HCH", "HPB", "HCB")] == [100, 150, 150, 150, 150]
    assert t.yearly_capacity_charge(imp, "LU") == pytest.approx(35.33 * 100 + 32.30 * 50)


def test_staircase_rates_must_not_rise():
    bad = parameters.load(**FR, overrides={"tariff": {"capacity_charges": {"turpe_cs": {
        "per_kw_year_by_regime": {"LU": {"pointe": 10.0, "HPH": 20.0}}}}}})
    with pytest.raises(ValueError):
        Tariff(bad["tariff"])


# -- tech, ancillary, capex, subsidies, EMS, finance ----------------------------------------------------------------
def test_battery_window_and_ancillary_reserve(ch):
    b = Battery(ch["tech"], ch["ancillary"]["reserve"])
    assert b.soc_window_kwh(1000) == pytest.approx(800)
    assert b.reserved_kwh(1000) == pytest.approx(200)        # 25% of the window
    assert b.dispatch_kwh(1000) == pytest.approx(600)
    assert b.dispatch_kw(1000) == pytest.approx(500 * 0.75)  # the same share of the 0.5C power
    assert b.ancillary_revenue(1000, 90) == pytest.approx(125 * 90)


def test_capex_tiers_and_replacements(ch):
    c = ch["capex"]
    assert capex.battery_gross(500, c) == pytest.approx(500 * 400)
    assert capex.battery_price_per_kwh(50, {"battery_tiers_per_kwh": [[100, 500], [1000, 300]]}) == 500
    assert capex.battery_price_per_kwh(550, {"battery_tiers_per_kwh": [[100, 500], [1000, 300]]}) == 400
    # 1 full purchase, then 1.5 more battery lives at 60%: 25 years of battery
    assert capex.battery_replacement_cost(500, c, 25, 10) == pytest.approx(1.5 * 0.6 * 200_000)


def test_threshold_subsidy_caps_the_discount():
    assert subsidies.apply_subsidy(1000, "percent", 0.75, 0) == pytest.approx(250)
    assert subsidies.apply_subsidy(1000, "fixed", 0, 300) == 700
    # 75% up to 400 kWh (cost 160,000), so 600 kWh at 240,000 gets 120,000 off
    assert subsidies.apply_subsidy(240_000, "threshold", 0.75, 0, size=600, threshold=400,
                                   cost_at_threshold=160_000) == pytest.approx(120_000)
    assert subsidies.ocan_max_kwh(365_000, 0.6) == pytest.approx(600)


def test_ems_fees_split_and_only_on_a_positive_saving():
    e = Ems({"fixed_per_year": 2500, "capex": 1000,
             "ancillary_fee_pct": {"voltiris": 0.10, "external": 0.20},
             "savings_fee_pct": {"voltiris": 0.05, "external": 0.0}})
    f = e.fees(ancillary_revenue=10_000, bill_saving=40_000)
    assert (f["ancillary_voltiris"], f["ancillary_external"], f["savings_voltiris"]) == (1000, 2000, 2000)
    assert f["voltiris"] == 3000 and f["external"] == 2000 and f["total"] == 2500 + 5000
    assert e.fees(ancillary_revenue=0, bill_saving=-5000)["savings_voltiris"] == 0


def test_payback_and_lifetime_profit():
    assert finance.payback_years(100_000, 20_000) == 5
    assert finance.payback_years(100_000, 0) == float("inf")
    assert finance.lifetime_profit(20_000, 10, 100_000) == 100_000


# -- engine on an invented week -------------------------------------------------------------------------------------
def invented_week(start: str = "2026-01-05", da=None) -> pd.DataFrame:
    """One week, 15 minutes: a flat 100 kW load with an evening peak, a midday PV bell of up to 200 W per module, an
    existing PV of up to 30 kW, and a day-ahead price (default a flat 0.08 EUR/kWh)."""
    idx = pd.date_range(start, periods=7 * 96, freq="15min")
    hour = idx.hour + idx.minute / 60
    bell = np.clip(np.cos((hour - 12.5) / 4 * np.pi / 2), 0, None)
    return pd.DataFrame({
        "Month": idx.month, "Day": idx.day, "Hour": idx.hour, "Minute": idx.minute,
        "Loadcurve (kW)": 100 + 80 * ((hour >= 17) & (hour < 20)),
        "Production voltiron (W)": 200 * bell,
        "Current PV feed-in (kW)": 30 * bell,
        "Day ahead kWh": 0.08 if da is None else da(hour, idx),
    })


def volatile_da(hour, idx):
    """Negative at midday on weekends, high in the evening: exporting is worth more than importing at times."""
    weekend = idx.weekday >= 5
    return np.where((hour >= 11) & (hour < 15) & weekend, -0.05,
                    np.where((hour >= 18) & (hour < 20), 0.30, 0.07))


def make_setup(market: dict, modules: int = 1000, business_model: str = "direct_sales", da=None,
               start: str = "2026-01-05", overrides: dict | None = None) -> Setup:
    params = parameters.load(**market, business_model=business_model, overrides=overrides)
    study = inputs.from_frame(invented_week(start, da), year=int(start[:4]), modules=modules, use_existing_pv=True,
                              eur_to_local=params["tariff"]["eur_to_local"])
    return Setup(study, params, grid={"import_max_kw": 400, "export_max_kw": 400})


@pytest.fixture(scope="module")
def setup():
    return make_setup(CH)


def test_no_battery_dispatch_balances(setup):
    res = dispatch.results(dispatch.solve(setup, "A"), setup)
    balance = res["pv"] + res["grid_import"] - res["grid_export"] - res["load"]
    assert balance.abs().max() < 1e-6
    sc = flows.sc_ss(res, setup)
    assert 0 < sc["sc_pct"] <= 100 and 0 < sc["ss_pct"] <= 100


def test_ch_stays_a_pure_lp(setup):
    both, negative = dispatch.exclusive_steps(setup, "A")
    assert len(both) == 0 and len(negative) == 0


def test_battery_lowers_the_bill_and_stays_in_its_window(setup):
    res_nb = dispatch.results(dispatch.solve(setup, "A"), setup)
    res_b = dispatch.results(dispatch.solve(setup, "A", battery_kwh=200), setup)
    assert flows.economics(res_b, setup, "A")["total_cost"] < flows.economics(res_nb, setup, "A")["total_cost"]
    assert res_b["battery_soc"].min() >= -1e-6
    assert res_b["battery_soc"].max() <= setup.battery.dispatch_kwh(200) + 1e-6
    assert res_b["battery_power"].abs().max() <= setup.battery.dispatch_kw(200) + 1e-6


def test_whole_study_adds_up_with_ems_fees_and_capex():
    s = make_setup(CH, overrides={"ems": {"ancillary_fee_pct": {"voltiris": 0.1, "external": 0.2},
                                          "savings_fee_pct": {"voltiris": 0.05, "external": 0.05}}})
    out = pipeline.run(s, sizing_settings={"sweep_kwh": [50, 100, 200], "cap_at_subsidy_size": False}, **QUIET)
    sm = out["summary"]
    assert sm["battery_kwh"] in (50, 100, 200)
    saving = sm["battery_energy_savings_yr"] + sm["battery_peak_shaving_yr"]
    fees = (0.3 * sm["battery_ancillary_yr"] + 0.1 * max(saving, 0))
    assert sm["ems_fees_voltiris_yr"] + sm["ems_fees_external_yr"] == pytest.approx(fees)
    assert sm["battery_value_yr"] == pytest.approx(saving + sm["battery_ancillary_yr"] - 2500 - fees)
    assert sm["battery_sc_saving_yr"] + sm["battery_arbitrage_yr"] == pytest.approx(sm["battery_energy_savings_yr"])
    assert sm["battery_investment"] == pytest.approx(sm["battery_net_capex"] + 1000 / 1.09)
    assert sm["battery_payback_yr"] == pytest.approx(sm["battery_investment"] / sm["battery_value_yr"])
    assert len(out["monthly_battery"]) == 12 and len(out["sweep"]) == 3


def battery_flows(n):
    return n.links_t.p0["bat_charger"], n.links_t.p0["bat_discharger"]


def test_nl_battery_power_is_shared_at_negative_prices():
    s = make_setup(NL, da=volatile_da, start="2026-06-01")
    both, negative = dispatch.exclusive_steps(s, "default")
    assert len(both) == 0 and len(negative) > 0                     # NL import is always day-ahead + 6.2 ct
    n = dispatch.solve(s, "default", battery_kwh=300)
    charge, discharge = battery_flows(n)
    power = s.battery.dispatch_kw(300)
    assert ((charge + discharge)[negative] <= power + 1e-6).all()   # time sharing, never both at full power
    res = dispatch.results(n, s)
    assert (res["pv"] - s.study.pv_total).abs().max() < 1e-6        # PV must run, as in CH


def one_meter_limits(s, n, kwh):
    """The exact time-sharing limits of one meter: import <= D + max(1 - S/P, 0) x charge,
    export <= S + max(eta - D/P, 0) x discharge."""
    charge, discharge = battery_flows(n)
    net = s.study.load - s.study.pv_total
    shortfall, surplus = net.clip(lower=0), (-net).clip(lower=0)
    power, eta = s.battery.dispatch_kw(kwh), s.battery.eff_dispatch
    imp_max = shortfall + (1 - surplus / power).clip(lower=0) * charge
    exp_max = surplus + (eta - shortfall / power).clip(lower=0) * discharge
    return imp_max, exp_max, charge + discharge, power


def test_fr_one_meter():
    s = make_setup(FR, da=volatile_da, start="2025-06-02")
    both, _ = dispatch.exclusive_steps(s, "LU")
    assert len(both) > 0                                               # evenings: 0.30 export against ~0.09 import
    res = dispatch.results(dispatch.solve(s, "LU"), s)                 # no battery: never import and export at once
    assert (np.minimum(res["grid_import"], res["grid_export"]) < 1e-6).all()
    n = dispatch.solve(s, "LU", battery_kwh=300)
    res = dispatch.results(n, s)
    imp_max, exp_max, throughput, power = one_meter_limits(s, n, 300)
    assert (res["grid_import"] <= imp_max + 1e-6)[both].all()          # nothing from grid to grid
    assert (res["grid_export"] <= exp_max + 1e-6)[both].all()
    assert (throughput[both] <= power + 1e-6).all()


def test_fr_with_the_cu_option_stays_on_cu():
    s = make_setup(FR, da=volatile_da, start="2025-01-06")
    out = pipeline.run(s, regime_auto=False, regime_manual="CU", sizing_settings={"sweep_kwh": [100, 300]}, **QUIET)
    sm = out["summary"]
    assert sm["regime_no_battery"] == "CU" and sm["regime_battery"] == "CU"
    assert set(out["sweep"]["regime"]) == {"CU"}


def test_a_day_ahead_market_needs_the_day_ahead_column():
    params = parameters.load(**NL)
    frame = invented_week().drop(columns=["Day ahead kWh"])
    study = inputs.from_frame(frame, year=2026, modules=100, use_existing_pv=True, eur_to_local=1.0)
    with pytest.raises(ValueError):
        Setup(study, params)


def test_eaas_keeps_the_battery_rule_at_negative_prices():
    def very_negative(hour, idx):
        return np.where((hour >= 9) & (hour < 16) & (idx.weekday >= 5), -0.30, 0.07)
    s = make_setup(NL, business_model="eaas", modules=600, da=very_negative, start="2026-06-01")
    _, negative = dispatch.exclusive_steps(s, "default")
    n = dispatch.solve(s, "default", battery_kwh=100)
    charge, discharge = battery_flows(n)
    assert len(negative) and ((charge + discharge)[negative] <= s.battery.dispatch_kw(100) + 1e-6).all()


def test_fr_battery_exports_only_pv_energy():
    s = make_setup(FR, da=volatile_da, start="2025-06-02")
    assert s.battery_export == "pv_only"
    n = dispatch.solve(s, "LU", battery_kwh=300)
    res = dispatch.results(n, s)
    charge, discharge = battery_flows(n)
    surplus = (s.study.pv_total - s.study.load).clip(lower=0)
    charge_pv = n.model.variables["battery_charge_from_pv"].solution.values
    discharge_pv = n.model.variables["battery_discharge_of_pv_energy"].solution.values
    eta = s.battery.eff_dispatch
    assert (charge_pv <= surplus.values + 1e-6).all()                          # the PV account charges from PV
    pv_energy = n.model.variables["battery_pv_energy"].solution.values
    assert (pv_energy <= res["battery_soc"].values + 1e-6).all()                # the PV account is inside the battery
    assert (res["grid_export"].values <= surplus.values - charge_pv + eta * discharge_pv + 1e-6).all()
    assert res["grid_export"].sum() <= surplus.sum() + 1e-6                     # only PV energy ever leaves
    # grid charging is booked only where the PV surplus does not cover the charging
    assert np.allclose(res["battery_charge_from_grid"], (charge - surplus).clip(lower=0), atol=1e-3)


def test_fr_trades_through_the_battery_when_the_contract_allows_it():
    # 100 modules: the load is always above the PV, so there is no PV surplus and any export is bought energy.
    # Day-ahead 0.30 EUR/kWh at 02-04, when the load is 100 kW and a 1000 kWh battery delivers up to ~364 kW.
    def night_peak(hour, idx):
        return np.where((hour >= 2) & (hour < 4), 0.30, 0.07)
    any_export = {"tariff": {"battery_export": "any"}}
    trading = make_setup(FR, modules=100, da=night_peak, start="2025-06-02", overrides=any_export)
    pv_only = make_setup(FR, modules=100, da=night_peak, start="2025-06-02")
    assert ((trading.study.pv_total - trading.study.load) <= 0).all()
    n_any = dispatch.solve(trading, "LU", battery_kwh=1000)
    n_pv = dispatch.solve(pv_only, "LU", battery_kwh=1000)
    assert dispatch.results(n_any, trading)["grid_export"].sum() > 100      # buys at the contract price, sells at 0.30
    assert dispatch.results(n_pv, pv_only)["grid_export"].max() < 1e-6     # nothing bought is ever sold
    assert n_pv.objective > n_any.objective


def test_ch_and_nl_export_rule_is_off():
    assert make_setup(CH).battery_export == "any" and make_setup(NL).battery_export == "any"


def test_fr_lp_capacity_charge_matches_the_bill():
    s = make_setup(FR, da=volatile_da, start="2025-01-06")
    n = dispatch.solve(s, "LU", battery_kwh=300)
    res = dispatch.results(n, s)
    energy = (res["grid_import"] * s.import_price("LU") * s.dt).sum() - (res["grid_export"] * s.bm.export_value
                                                                           * s.dt).sum()
    cs = s.tariff.yearly_capacity_charge(res["grid_import"], "LU")
    assert n.objective == pytest.approx(energy + cs, rel=1e-6)


def test_eaas_runs_on_a_day_ahead_market():
    s = make_setup(NL, business_model="eaas", da=volatile_da, start="2026-06-01")
    out = pipeline.run(s, sizing_settings={"sweep_kwh": [100, 200]}, **QUIET)
    sm = out["summary"]
    assert sm["voltiris_model"] == "eaas" and sm["eaas_price_per_mwh"] == pytest.approx(196.2)
    assert sm["eaas_fee_battery"] > 0 and sm["currency"] == "EUR"
