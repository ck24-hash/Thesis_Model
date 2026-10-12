"""Reusable building blocks. Each function adds one block of the system to a PyPSA network.

Bus convention (same in every scenario):
    gas   natural gas supply point           elec  greenhouse electricity bus
    heat  greenhouse heat bus (supply level) tes   inside of the thermal storage
    co2   CO2 stream available for enrichment
Link port convention: p0 = taken from bus0; p1, p2, p3 are negative when delivered to bus1, bus2, bus3.
"""
import warnings


def add_buses(n):
    for c in ["gas", "electricity", "heat", "co2"]:
        n.add("Carrier", c)
    n.add("Bus", "gas",  carrier="gas")
    n.add("Bus", "elec", carrier="electricity")
    n.add("Bus", "heat", carrier="heat")
    n.add("Bus", "tes",  carrier="heat")
    n.add("Bus", "co2",  carrier="co2")


def add_greenhouse_loads(n, data):
    n.add("Load", "GH heat demand", bus="heat", p_set=data.heat_demand_MW)
    n.add("Load", "GH elec demand", bus="elec", p_set=data.elec_demand_MW)
    n.add("Load", "GH CO2 demand",  bus="co2",  p_set=data.co2_demand_t_h)


def add_gas_supply(n, sizes):
    # ASSUMPTION (not drawn): gas supply is unlimited (p_nom = 1e4 MW, never binding), no connection capacity limit.
    n.add("Generator", "NG supply", bus="gas", p_nom=1e4, marginal_cost=sizes.gas_marginal)


def add_grid_import(n, sizes):
    n.add("Generator", "Grid import", bus="elec", p_nom=sizes.grid_limit, marginal_cost=sizes.grid_marginal)


def add_grid_export(n, sizes):
    """Electricity sold to the grid. Sink on the elec bus (sign=-1) whose marginal cost is minus the export price,
    so every exported MWh lowers the objective by the export price (revenue)."""
    if sizes.export_marginal is None:
        raise KeyError("Grid export needs the input column 'elec_export_price_EUR_per_MWh'.")
    if (-sizes.export_marginal > sizes.grid_marginal).any():
        warnings.warn("Export price is above the import price in some hours: the model may import and export at "
                      "the same time (arbitrage, limited only by the import limit).")
    n.add("Generator", "Grid export", bus="elec", sign=-1, p_nom=sizes.export_limit,
          marginal_cost=sizes.export_marginal)


def add_chp(n, P, sizes):
    """Gas engine CHP: gas -> electricity (bus1) + heat (bus2) + CO2 (bus3) in fixed ratios (back-pressure type,
    no extraction). Link p_nom is on the fuel side: electrical capacity / eta_el. Variable O&M is given per MWh
    electricity and converted to per MWh fuel."""
    n.add("Link", "CHP",
          bus0="gas", bus1="elec", bus2="heat", bus3="co2",
          efficiency=P.chp_eta_el, efficiency2=P.chp_eta_th,
          efficiency3=P.gas_co2_factor_t_per_MWh * P.chp_co2_usable_fraction,
          p_nom=sizes.chp_cap_el / P.chp_eta_el,
          p_nom_extendable=P.OPTIMISE_CHP,
          marginal_cost=P.chp_vom_EUR_per_MWh_el * P.chp_eta_el,
          capital_cost=sizes.chp_cost_per_MW_el * P.chp_eta_el if P.OPTIMISE_CHP else 0.0)


def add_chp_priority(n, P):
    """Merit order 'CHP first': adds priority_penalty_EUR_per_MWh to backup-boiler heat and to grid import.
    The penalty is a dispatch weight only, it is removed from every reported cost (see results.py).
    Call it after the boiler and grid blocks. No effect if chp_priority is False or there is no CHP."""
    if not P.chp_priority or "CHP" not in n.links.index:
        return
    pen = P.priority_penalty_EUR_per_MWh
    if "NG boiler" in n.links.index:
        n.links.loc["NG boiler", "marginal_cost"] += pen * P.boiler_eta     # per MWh fuel = pen per MWh heat
    if "Grid import" in n.generators.index:
        if "Grid import" in n.generators_t.marginal_cost:
            n.generators_t.marginal_cost["Grid import"] += pen
        else:
            n.generators.loc["Grid import", "marginal_cost"] += pen


def add_ng_boiler(n, P, sizes):
    """Gas -> heat (+ CO2 stream). Link p_nom is on the fuel side, so thermal capacity / efficiency.
    efficiency2 = t CO2 delivered to bus2 per MWh of fuel.
    Ramp limit: output may change by at most boiler_ramp_limit_per_h x capacity from one hour to the next."""
    ramp = P.boiler_ramp_limit_per_h if P.boiler_ramp_limit_per_h is not None else float("nan")   # NaN = no limit
    n.add("Link", "NG boiler",
          ramp_limit_up=ramp, ramp_limit_down=ramp,
          bus0="gas", bus1="heat", bus2="co2",
          efficiency=P.boiler_eta,
          efficiency2=P.gas_co2_factor_t_per_MWh * P.boiler_co2_usable_fraction,
          p_nom=sizes.boiler_cap_th / P.boiler_eta,
          p_nom_extendable=P.OPTIMISE_BOILER,
          capital_cost=sizes.boiler_cost_per_MW * P.boiler_eta if P.OPTIMISE_BOILER else 0.0)


def add_thermal_storage(n, P, sizes):
    """heat bus <-> tes bus with a Store in the middle. Charging power is limited on the heat-bus
    side, discharging power on the delivered heat. Both are <= capacity / tes_hours_at_full_power
    (fixed sizes: in sizing.py; OPTIMISE_TES: in add_custom_constraints).
    Reserve: stored energy stays >= tes_min_soc_frac x capacity (that part is never usable).
    ASSUMPTION (not drawn): discharge goes to the shared heat bus, so stored heat could also reach the heat dump.
    This only wastes heat (never optimal unless forced), so it is accepted as a modelling simplification."""
    n.add("Link", "TES charge", bus0="heat", bus1="tes", efficiency=P.tes_eta_charge,
          p_nom=sizes.tes_power, p_nom_extendable=P.OPTIMISE_TES)
    n.add("Link", "TES discharge", bus0="tes", bus1="heat", efficiency=P.tes_eta_discharge,
          p_nom=sizes.tes_power / P.tes_eta_discharge, p_nom_extendable=P.OPTIMISE_TES)
    n.add("Store", "TES", bus="tes",
          e_nom=sizes.tes_cap, e_nom_extendable=P.OPTIMISE_TES, e_cyclic=True, e_min_pu=P.tes_min_soc_frac,
          e_nom_max=P.tes_capacity_max_MWh if P.tes_capacity_max_MWh is not None else float("inf"),
          standing_loss=P.tes_standing_loss_per_h,
          capital_cost=sizes.tes_cost_per_MWh if P.OPTIMISE_TES else 0.0)


def add_custom_constraints(n, P):
    """Constraints PyPSA has no attribute for. Called by workflow.solve() after the model is built,
    each one only if its components exist in the network."""
    m = n.model
    # storage power linked to capacity when the storage size is a decision variable
    if ("TES" in n.stores.index and n.stores.at["TES", "e_nom_extendable"]
            and P.tes_hours_at_full_power is not None):
        h = P.tes_hours_at_full_power
        e_nom, p_nom = m["Store-e_nom"].loc["TES"], m["Link-p_nom"]
        m.add_constraints(h * p_nom.loc["TES charge"] <= e_nom, name="TES-charge-power-per-capacity")
        m.add_constraints(h * P.tes_eta_discharge * p_nom.loc["TES discharge"] <= e_nom,   # delivered heat side
                          name="TES-discharge-power-per-capacity")


def add_sinks_and_slack(n, P):
    """Assumed sinks (not in the scenario figure) and slack generators (should stay at zero).
    Generator with sign=-1 absorbs energy: p > 0 means energy leaves the bus."""
    n.add("Generator", "Heat dump", bus="heat", p_nom=1e4, sign=-1, marginal_cost=P.heat_dump_cost_EUR_per_MWh)
    n.add("Generator", "CO2 vent",  bus="co2",  p_nom=1e4, sign=-1, marginal_cost=P.co2_vent_cost_EUR_per_t)
    n.add("Generator", "Unserved heat", bus="heat", p_nom=1e4, marginal_cost=P.voll_heat_EUR_per_MWh)
    n.add("Generator", "Unserved CO2",  bus="co2",  p_nom=1e4, marginal_cost=P.voll_co2_EUR_per_t)
