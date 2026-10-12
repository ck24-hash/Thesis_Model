"""Resolve component sizes (None -> automatic) and cost factors from the parameters and the data."""
from dataclasses import dataclass

import pandas as pd


def annuity(rate, years):
    """Annuity factor: share of the investment paid every year."""
    return rate / (1 - (1 + rate) ** -years) if rate > 0 else 1 / years


@dataclass
class Sizes:
    boiler_cap_th: float          # MW thermal
    tes_cap: float                # MWh thermal
    tes_power: float              # MW thermal
    grid_limit: float             # MW electric, import
    boiler_cost_per_MW: float     # EUR per MW_th per year (annualised capex + fixed O&M)
    tes_cost_per_MWh: float       # EUR per MWh per year
    gas_marginal: pd.Series       # EUR per MWh fuel, hourly (gas price + carbon levy)
    grid_marginal: pd.Series      # EUR per MWh electricity, hourly (price + tariff adder)
    chp_cap_el: float = 0.0       # MW electric (used only by scenarios with a CHP)
    chp_cost_per_MW_el: float = 0.0   # EUR per MW_el per year
    export_limit: float = 1e4     # MW electric
    export_marginal: pd.Series | None = None   # EUR per MWh, hourly = - export price (negative cost = revenue)

    def table(self, include_chp=False):
        rows = [("Boiler capacity", self.boiler_cap_th, "MW thermal"),
                ("Thermal storage capacity", self.tes_cap, "MWh thermal"),
                ("Thermal storage power", self.tes_power, "MW thermal"),
                ("Grid import limit", self.grid_limit, "MW electric")]
        if include_chp:
            rows += [("CHP electrical capacity", self.chp_cap_el, "MW electric"),
                     ("Grid export limit", self.export_limit, "MW electric")]
        return pd.DataFrame(rows, columns=["", "Value", "Unit"]).set_index("")


def resolve_sizes(data, P):
    peak_heat = data.heat_demand_MW.max()
    peak_elec = data.elec_demand_MW.max()

    boiler_cap_th = (P.boiler_capacity_MW_th if P.boiler_capacity_MW_th is not None
                     else P.boiler_sizing_margin * peak_heat)
    tes_cap = (P.tes_capacity_MWh if P.tes_capacity_MWh is not None
               else P.tes_hours_of_peak * peak_heat)
    tes_power = P.tes_power_MW_th if P.tes_power_MW_th is not None else boiler_cap_th
    if P.tes_hours_at_full_power is not None:
        tes_power = min(tes_power, tes_cap / P.tes_hours_at_full_power)   # power linked to capacity (fixed sizes)
    grid_limit = (P.grid_import_limit_MW if P.grid_import_limit_MW is not None else 10 * peak_elec)
    chp_cap_el = (P.chp_capacity_MW_el if P.chp_capacity_MW_el is not None
                  else P.chp_heat_share_of_peak * peak_heat * P.chp_eta_el / P.chp_eta_th)
    export_limit = P.grid_export_limit_MW if P.grid_export_limit_MW is not None else 1e4

    boiler_cost = P.boiler_capex_EUR_per_kW_th * 1e3 * (annuity(P.discount_rate, P.boiler_lifetime_y) + P.boiler_fom_frac)
    tes_cost = P.tes_capex_EUR_per_kWh * 1e3 * (annuity(P.discount_rate, P.tes_lifetime_y) + P.tes_fom_frac)
    chp_cost = P.chp_capex_EUR_per_kW_el * 1e3 * (annuity(P.discount_rate, P.chp_lifetime_y) + P.chp_fom_frac)

    gas_marginal = data.gas_price_EUR_MWh + P.co2_levy() * P.gas_co2_factor_t_per_MWh
    grid_marginal = data.elec_price_EUR_MWh + P.grid_tariff_adder_EUR_per_MWh
    export_marginal = -data.elec_export_price_EUR_MWh if "elec_export_price_EUR_MWh" in data else None

    return Sizes(boiler_cap_th, tes_cap, tes_power, grid_limit, boiler_cost, tes_cost, gas_marginal, grid_marginal,
                 chp_cap_el, chp_cost, export_limit, export_marginal)
