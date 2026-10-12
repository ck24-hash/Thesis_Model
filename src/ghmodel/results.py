"""Extract hourly results from a solved network, check balances, compute KPIs, export to Excel.

Works for every scenario: a component that is not in the network gives zero flows, so the hourly table `r`
and the KPI table always have the same columns / rows (comparable between scenarios).
"""
import warnings
from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class Results:
    r: pd.DataFrame            # hourly results, all flows positive (MW, t/h, MWh, EUR)
    monthly: pd.DataFrame      # monthly sums
    summary: pd.DataFrame      # annual KPI table (Group, Indicator, Value, Unit)
    heat_balance: pd.Series    # annual fate of the produced heat
    k: dict                    # scalar annual quantities (used by the plots and the analysis)
    params: object


def _zeros(n):
    return pd.Series(0.0, index=n.snapshots)


def _link(n, name, port):
    """Positive flow at a Link port (p0 = taken from bus0, p1/p2/p3 = delivered); zeros if the link does not exist."""
    if name not in n.links.index:
        return _zeros(n)
    p = getattr(n.links_t, port)[name]
    return p if port == "p0" else -p


def _gen(n, name):
    return n.generators_t.p[name] if name in n.generators.index else _zeros(n)


def priority_active(n, P):
    """True if the CHP merit-order penalty was added to the network (blocks.add_chp_priority)."""
    return P.chp_priority and "CHP" in n.links.index


def extract_results(n, data, P):
    """Hourly flows from the solved network. PyPSA link ports p1/p2/p3 are negative when delivering,
    so they are flipped here and every flow in `r` is positive."""
    r = pd.DataFrame(index=n.snapshots)

    r["heat_demand"] = n.loads_t.p["GH heat demand"]
    r["elec_demand"] = n.loads_t.p["GH elec demand"]
    r["co2_demand"] = n.loads_t.p["GH CO2 demand"]

    r["boiler_gas"] = _link(n, "NG boiler", "p0")          # MW fuel
    r["boiler_heat"] = _link(n, "NG boiler", "p1")         # MW heat to the heat bus
    r["boiler_co2"] = _link(n, "NG boiler", "p2")          # t/h CO2 to the CO2 bus
    r["chp_gas"] = _link(n, "CHP", "p0")                   # MW fuel
    r["chp_elec"] = _link(n, "CHP", "p1")                  # MW electricity to the elec bus
    r["chp_heat"] = _link(n, "CHP", "p2")                  # MW heat to the heat bus
    r["chp_co2"] = _link(n, "CHP", "p3")                   # t/h CO2 to the CO2 bus
    r["gas_use"] = r.boiler_gas + r.chp_gas                # MW fuel, all units

    r["tes_charge"] = _link(n, "TES charge", "p0")         # MW taken from the heat bus
    r["tes_discharge"] = _link(n, "TES discharge", "p1")   # MW delivered to the heat bus
    r["tes_soc"] = n.stores_t.e["TES"] if "TES" in n.stores.index else _zeros(n)   # MWh

    r["grid_import"] = _gen(n, "Grid import")
    r["grid_export"] = _gen(n, "Grid export")
    r["heat_dump"] = _gen(n, "Heat dump")
    r["co2_vent"] = _gen(n, "CO2 vent")
    r["heat_unserved"] = _gen(n, "Unserved heat")
    r["co2_unserved"] = _gen(n, "Unserved CO2")

    r["gas_price"] = data.gas_price_EUR_MWh
    r["elec_price"] = data.elec_price_EUR_MWh + P.grid_tariff_adder_EUR_per_MWh
    r["export_price"] = data.elec_export_price_EUR_MWh if "elec_export_price_EUR_MWh" in data else 0.0
    r["gas_cost_EUR"] = r.gas_use * r.gas_price
    r["co2_levy_EUR"] = r.gas_use * P.gas_co2_factor_t_per_MWh * P.co2_levy()
    r["elec_cost_EUR"] = r.grid_import * r.elec_price
    r["export_revenue_EUR"] = r.grid_export * r.export_price
    r["chp_vom_EUR"] = r.chp_elec * P.chp_vom_EUR_per_MWh_el
    r["sink_cost_EUR"] = r.heat_dump * P.heat_dump_cost_EUR_per_MWh + r.co2_vent * P.co2_vent_cost_EUR_per_t
    # dispatch weight only (CHP merit order), never part of a reported cost
    pen = P.priority_penalty_EUR_per_MWh if priority_active(n, P) else 0.0
    r["priority_penalty_EUR"] = pen * (r.boiler_heat + r.grid_import)
    r["emissions_gas_t"] = r.gas_use * P.gas_co2_factor_t_per_MWh
    r["emissions_grid_t"] = r.grid_import * data.grid_ef_t_MWh
    r["export_co2_credit_t"] = r.grid_export * data.grid_ef_t_MWh     # information only, not subtracted

    return r.mask(r.abs() < 1e-9, 0.0)                     # remove numerical noise / -0.0


def check_balances(r, tol=1e-5, verbose=True):
    """Energy in = energy out at every hour on the heat, CO2 and electricity bus."""
    heat_err = (r.boiler_heat + r.chp_heat + r.tes_discharge + r.heat_unserved
                - r.heat_demand - r.tes_charge - r.heat_dump).abs().max()
    co2_err = (r.boiler_co2 + r.chp_co2 + r.co2_unserved - r.co2_demand - r.co2_vent).abs().max()
    elec_err = (r.grid_import + r.chp_elec - r.elec_demand - r.grid_export).abs().max()
    if verbose:
        print(f"Max hourly imbalance  heat: {heat_err:.2e} MW | CO2: {co2_err:.2e} t/h | electricity: {elec_err:.2e} MW")
    assert max(heat_err, co2_err, elec_err) < tol, "Balance check failed"

    unsrv_h, unsrv_c = r.heat_unserved.sum(), r.co2_unserved.sum()
    if unsrv_h > 1e-6 or unsrv_c > 1e-6:
        warnings.warn(f"Unserved heat = {unsrv_h:.1f} MWh, unserved CO2 = {unsrv_c:.2f} t "
                      "-> increase boiler/CHP size (or check CO2 data).")
    elif verbose:
        print("All heat and CO2 demand is covered (no slack used).")


def summarise(n, r, data, P, sizes):
    def cap(component, name, attr, factor=1.0):
        df = getattr(n, component)
        return df.at[name, attr] * factor if name in df.index else 0.0

    boiler_cap = cap("links", "NG boiler", "p_nom_opt", P.boiler_eta)       # MW thermal
    chp_cap = cap("links", "CHP", "p_nom_opt", P.chp_eta_el)                # MW electric
    chp_cap_th = chp_cap * P.chp_eta_th / P.chp_eta_el                      # MW thermal
    tes_cap = cap("stores", "TES", "e_nom_opt")                             # MWh

    s = r.sum()
    heat_dem, elec_dem, co2_dem = s.heat_demand, s.elec_demand, s.co2_demand
    boiler_Q, chp_Q = s.boiler_heat, s.chp_heat
    heat_prod = boiler_Q + chp_Q
    tes_in, tes_out = s.tes_charge, s.tes_discharge
    dump, unsrv_h = s.heat_dump, s.heat_unserved
    direct = heat_dem - tes_out - unsrv_h                  # produced heat -> greenhouse without storage
    co2_prod = s.boiler_co2 + s.chp_co2
    co2_vent, co2_unsrv = s.co2_vent, s.co2_unserved
    grid_in, grid_out, chp_el = s.grid_import, s.grid_export, s.chp_elec

    gas_cost, levy_cost, elec_cost = s.gas_cost_EUR, s.co2_levy_EUR, s.elec_cost_EUR
    export_rev, chp_vom, sink_cost = s.export_revenue_EUR, s.chp_vom_EUR, s.sink_cost_EUR
    opex = gas_cost + levy_cost + elec_cost + chp_vom + sink_cost - export_rev
    capex_boiler = boiler_cap * sizes.boiler_cost_per_MW      # annualised (incl. fixed O&M)
    capex_tes = tes_cap * sizes.tes_cost_per_MWh
    capex_chp = chp_cap * sizes.chp_cost_per_MW_el
    total_cost = opex + capex_boiler + capex_tes + capex_chp

    # the optimiser objective must equal what we recompute from the flows (+ dispatch-only terms)
    expected = (opex + (capex_boiler if P.OPTIMISE_BOILER else 0.0) + (capex_tes if P.OPTIMISE_TES else 0.0)
                + (capex_chp if P.OPTIMISE_CHP else 0.0))
    expected += unsrv_h * P.voll_heat_EUR_per_MWh + co2_unsrv * P.voll_co2_EUR_per_t + s.priority_penalty_EUR
    assert abs(n.objective - expected) < 1e-4 * max(1, abs(n.objective)), \
        f"Objective mismatch: {n.objective:,.0f} vs {expected:,.0f}"

    gas_for_dump_MWh = (r.heat_dump / P.boiler_eta).sum()           # gas a boiler would burn for the dumped heat
    gas_for_dump_cost = (r.heat_dump / P.boiler_eta * r.gas_price).sum()
    em_gas, em_grid = s.emissions_gas_t, s.emissions_grid_t
    pct = lambda a, b: 100 * a / b if b else 0.0

    rows = [
        ("Demand", "Heat demand", heat_dem, "MWh/y"),
        ("Demand", "Electricity demand", elec_dem, "MWh/y"),
        ("Demand", "CO2 demand", co2_dem, "t/y"),
        ("Sizes", "Boiler thermal capacity", boiler_cap, "MW"),
        ("Sizes", "CHP electrical capacity", chp_cap, "MW"),
        ("Sizes", "CHP thermal capacity", chp_cap_th, "MW"),
        ("Sizes", "Thermal storage capacity", tes_cap, "MWh"),
        ("Fuel and grid", "Gas consumption", s.gas_use, "MWh/y"),
        ("Fuel and grid", "Gas to CHP", s.chp_gas, "MWh/y"),
        ("Fuel and grid", "Gas to boiler", s.boiler_gas, "MWh/y"),
        ("Fuel and grid", "Grid import", grid_in, "MWh/y"),
        ("Fuel and grid", "Grid export", grid_out, "MWh/y"),
        ("Electricity", "CHP electricity output", chp_el, "MWh/y"),
        ("Electricity", "CHP full-load hours", chp_el / chp_cap if chp_cap else 0.0, "h/y"),
        ("Electricity", "CHP electricity used on site", elec_dem - grid_in, "MWh/y"),
        ("Heat", "CHP heat output", chp_Q, "MWh/y"),
        ("Heat", "Boiler heat output", boiler_Q, "MWh/y"),
        ("Heat", "Heat dumped (rejected)", dump, "MWh/y"),
        ("Heat", "Heat dumped / heat produced", pct(dump, heat_prod), "%"),
        ("Heat", "Unserved heat", unsrv_h, "MWh/y"),
        ("Storage", "Energy discharged from storage", tes_out, "MWh/y"),
        ("Storage", "Equivalent full cycles", tes_out / tes_cap if tes_cap else 0, "cycles/y"),
        ("Storage", "Storage losses (charge + standing + discharge)", tes_in - tes_out, "MWh/y"),
        ("CO2", "CO2 delivered to greenhouse", co2_prod - co2_vent, "t/y"),
        ("CO2", "CO2 from CHP", s.chp_co2, "t/y"),
        ("CO2", "CO2 from boiler", s.boiler_co2, "t/y"),
        ("CO2", "CO2 vented (excess)", co2_vent, "t/y"),
        ("CO2", "Unserved CO2", co2_unsrv, "t/y"),
        ("CO2", "Gas equivalent of dumped heat (boiler efficiency)", gas_for_dump_MWh, "MWh/y"),
        ("Self-sufficiency", "Heat (local non-fuel heat / demand)", 0.0, "%"),
        ("Self-sufficiency", "CO2 (non-fossil CO2 / demand)", 0.0, "%"),
        ("Self-sufficiency", "Electricity (on-site generation used on site / demand)", pct(elec_dem - grid_in, elec_dem), "%"),
        ("Cost", "Gas cost", gas_cost, "EUR/y"),
        ("Cost", "CO2 levy on gas", levy_cost, "EUR/y"),
        ("Cost", "Electricity purchase", elec_cost, "EUR/y"),
        ("Cost", "Electricity export revenue (income)", export_rev, "EUR/y"),
        ("Cost", "CHP variable O&M", chp_vom, "EUR/y"),
        ("Cost", "Heat dump + CO2 vent cost", sink_cost, "EUR/y"),
        ("Cost", "Operating cost (OPEX, net of export revenue)", opex, "EUR/y"),
        ("Cost", "Annualised capex + fixed O&M: boiler", capex_boiler, "EUR/y"),
        ("Cost", "Annualised capex + fixed O&M: storage", capex_tes, "EUR/y"),
        ("Cost", "Annualised capex + fixed O&M: CHP", capex_chp, "EUR/y"),
        ("Cost", "Total annualised cost", total_cost, "EUR/y"),
        ("Cost", "Cost of gas for dumped heat (boiler efficiency)", gas_for_dump_cost, "EUR/y"),
        ("Specific", "Total annualised cost per m2", total_cost / P.greenhouse_area_m2, "EUR/m2/y"),
        ("Specific", "Gas + levy cost per MWh heat delivered", (gas_cost + levy_cost) / heat_dem if heat_dem else 0, "EUR/MWh"),
        ("Emissions", "Direct CO2 (gas combustion)", em_gas, "t/y"),
        ("Emissions", "Indirect CO2 (grid import)", em_grid, "t/y"),
        ("Emissions", "Total CO2", em_gas + em_grid, "t/y"),
        ("Emissions", "Grid CO2 displaced by export (info, not subtracted)", s.export_co2_credit_t, "t/y"),
    ]
    summary = pd.DataFrame(rows, columns=["Group", "Indicator", "Value", "Unit"])

    heat_balance = pd.Series({
        "Heat produced (CHP + boiler)": heat_prod,
        "  from CHP": chp_Q,
        "  from boiler": boiler_Q,
        "  direct to greenhouse": direct,
        "  into storage": tes_in,
        "  dumped": dump,
        "Storage delivered to greenhouse": tes_out,
        "Storage losses": tes_in - tes_out,
    }, name="MWh/y")

    monthly = r[["heat_demand", "boiler_heat", "chp_heat", "heat_dump", "tes_discharge", "gas_use", "boiler_gas",
                 "chp_gas", "chp_elec", "grid_import", "grid_export", "co2_demand", "boiler_co2", "chp_co2",
                 "co2_vent", "gas_cost_EUR", "co2_levy_EUR", "elec_cost_EUR", "export_revenue_EUR", "chp_vom_EUR",
                 "sink_cost_EUR", "emissions_gas_t", "emissions_grid_t"]].resample("MS").sum()
    monthly.index = monthly.index.strftime("%b")

    k = dict(boiler_cap_final=boiler_cap, chp_cap_final=chp_cap, chp_cap_th=chp_cap_th, tes_cap_final=tes_cap,
             boiler_Q=boiler_Q, chp_Q=chp_Q, heat_prod=heat_prod, tes_in=tes_in, tes_out=tes_out, dump=dump,
             direct=direct, gas_cost=gas_cost, levy_cost=levy_cost, elec_cost=elec_cost, export_rev=export_rev,
             chp_vom=chp_vom, sink_cost=sink_cost, opex=opex, capex_boiler=capex_boiler, capex_tes=capex_tes,
             capex_chp=capex_chp, total_cost=total_cost, emissions=em_gas + em_grid,
             has_chp="CHP" in n.links.index, has_export="Grid export" in n.generators.index)
    return Results(r=r, monthly=monthly, summary=summary, heat_balance=heat_balance, k=k, params=P)


def export_results(res, n, out_dir, name="baseline"):
    """Write hourly results, monthly and annual tables and parameters to one Excel file."""
    from pathlib import Path
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    params_table = pd.Series(asdict(res.params), name="value").astype(str).to_frame()

    out_file = out_dir / f"{name}_results.xlsx"
    with pd.ExcelWriter(out_file) as xw:
        res.summary.to_excel(xw, sheet_name="annual_summary", index=False)
        res.heat_balance.to_frame().to_excel(xw, sheet_name="heat_balance")
        res.monthly.to_excel(xw, sheet_name="monthly")
        res.r.to_excel(xw, sheet_name="hourly")
        params_table.to_excel(xw, sheet_name="parameters")
    print("Saved:", out_file)

    try:
        n.export_to_netcdf(out_dir / f"{name}_network.nc")
        print("Saved:", out_dir / f"{name}_network.nc")
    except Exception as e:                       # needs netcdf4 / h5netcdf, optional
        print("Network file not saved (optional):", type(e).__name__)
    return out_file
