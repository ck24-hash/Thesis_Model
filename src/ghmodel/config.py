"""Default parameters and Excel column mapping.

Units used everywhere in the package: MW, MWh, t CO2, EUR (prices in EUR/MWh, EUR/t).
Values marked [placeholder] are typical orders of magnitude, replace them with sourced data.
"""
from dataclasses import dataclass, field

# internal column name : (Excel column header, factor to internal unit)
INPUT_COLUMNS = {
    "heat_demand_MW":     ("heat_demand_kW",         1e-3),   # kW   -> MW
    "elec_demand_MW":     ("elec_demand_kW",         1e-3),   # kW   -> MW
    "co2_demand_t_h":     ("co2_demand_kg_h",        1e-3),   # kg/h -> t/h
    "gas_price_EUR_MWh":  ("gas_price_EUR_per_MWh",  1.0),    # EUR/MWh fuel (LHV, all-in)
    "elec_price_EUR_MWh": ("elec_price_EUR_per_MWh", 1.0),    # EUR/MWh (all-in import price)
}
# optional columns, used only if present in the sheet
OPTIONAL_COLUMNS = {
    "grid_ef_t_MWh": ("grid_emission_factor_kg_per_kWh", 1.0),   # kg/kWh = t/MWh
    "elec_export_price_EUR_MWh": ("elec_export_price_EUR_per_MWh", 1.0),   # EUR/MWh paid for exported electricity (S1+)
}
# Daily input (one row per day): these columns hold daily TOTALS (kWh/day, kg/day) and are spread evenly over
# the 24 hours. All other columns (prices, emission factors) are repeated for each hour of the day.
DAILY_TOTAL_COLUMNS = ["heat_demand_MW", "elec_demand_MW", "co2_demand_t_h"]

# Country defaults, used when the matching Params field is None. All values [placeholder], replace with sourced data.
COUNTRY_DEFAULTS = {
    #       carbon levy on gas burnt (EUR/t CO2)      annual average grid emission factor (t CO2/MWh)
    "CH": {"co2_levy_EUR_per_t": 125.0,             "grid_ef_t_per_MWh": 0.10},   # levy 120 CHF/t; exemption?
    "FR": {"co2_levy_EUR_per_t": 44.6,              "grid_ef_t_per_MWh": 0.05},   # carbon part of the gas excise
    "NL": {"co2_levy_EUR_per_t": 0.0,               "grid_ef_t_per_MWh": 0.30},   # check CO2 scheme for greenhouses
}


@dataclass
class Params:
    # ---- Greenhouse ----------------------------------------------------------
    greenhouse_area_m2: float = 10_000        # only for specific KPIs (EUR/m2, kWh/m2)
    country: str = "CH"                       # CH / FR / NL, selects COUNTRY_DEFAULTS

    # ---- Natural gas ---------------------------------------------------------
    gas_co2_factor_t_per_MWh: float = 0.202   # t CO2 per MWh fuel (LHV)
    co2_price_EUR_per_t: float | None = None  # carbon levy on gas burnt (not inside the gas price); None -> country default

    # ---- Conventional boiler -------------------------------------------------
    boiler_eta: float = 0.92                  # heat out / fuel in (LHV)             [placeholder]
    boiler_capacity_MW_th: float | None = None    # None -> boiler_sizing_margin x peak heat demand
    boiler_sizing_margin: float = 1.2
    boiler_co2_usable_fraction: float = 1.0   # share of flue-gas CO2 reaching the greenhouse [placeholder]
    boiler_capex_EUR_per_kW_th: float = 80    # [placeholder]
    boiler_lifetime_y: float = 20
    boiler_fom_frac: float = 0.02             # fixed O&M, share of capex per year
    boiler_ramp_limit_per_h: float | None = 0.5   # max change of output per hour, share of capacity; None = off [placeholder]

    # ---- Thermal storage (hot water buffer) ----------------------------------
    tes_capacity_MWh: float | None = None     # None -> tes_hours_of_peak x peak heat demand
    tes_hours_of_peak: float = 6
    tes_power_MW_th: float | None = None      # None -> same as boiler thermal capacity
    tes_hours_at_full_power: float | None = 4.0   # charge/discharge power <= capacity / these hours; None = off [placeholder]
    tes_min_soc_frac: float = 0.1             # reserve: stored energy never below this share of capacity; 0 = off [placeholder]
    tes_eta_charge: float = 0.98              # [placeholder]
    tes_eta_discharge: float = 0.98           # [placeholder]
    tes_standing_loss_per_h: float = 0.001    # fraction of stored energy lost per hour [placeholder]
    tes_capex_EUR_per_kWh: float = 10         # [placeholder]
    tes_lifetime_y: float = 25
    tes_fom_frac: float = 0.01

    # ---- CHP: gas engine, Scenario 1 -------------------------------------------
    chp_capacity_MW_el: float | None = None   # None -> chp_heat_share_of_peak x peak heat demand, as MW electric
    chp_heat_share_of_peak: float = 0.5       # CHP thermal capacity / peak heat demand when sized automatically [placeholder]
    chp_eta_el: float = 0.42                  # electricity out / fuel in (LHV) [placeholder]
    chp_eta_th: float = 0.45                  # useful heat out / fuel in (LHV) [placeholder]
    chp_co2_usable_fraction: float = 1.0      # share of exhaust CO2 usable for dosing after cleaning [placeholder]
    chp_capex_EUR_per_kW_el: float = 900      # [placeholder]
    chp_lifetime_y: float = 15                # [placeholder]
    chp_fom_frac: float = 0.02                # fixed O&M, share of capex per year [placeholder]
    chp_vom_EUR_per_MWh_el: float = 12.0      # variable maintenance per MWh electricity [placeholder]
    # Merit order: CHP before backup boiler and grid import. Implemented as an internal penalty on boiler heat and
    # grid import (EUR/MWh). It steers the dispatch only and is NOT included in any reported cost.
    chp_priority: bool = True
    priority_penalty_EUR_per_MWh: float = 200.0   # must stay below voll_heat_EUR_per_MWh

    # ---- Electricity grid ------------------------------------------------------
    grid_import_limit_MW: float | None = None     # None -> 10 x peak electricity demand (not binding)
    grid_export_limit_MW: float | None = None     # None -> no export limit (S1+, export price column needed)
    grid_tariff_adder_EUR_per_MWh: float = 0.0    # extra tariff on top of the price column
    grid_co2_factor_t_per_MWh: float | None = None    # None -> country default; an hourly input column overrides both

    # ---- Economics -----------------------------------------------------------
    discount_rate: float = 0.05
    project_lifetime_y: int = 20              # horizon of the financial analysis (replacements and salvage value inside)

    # ---- Optimisation switches -----------------------------------------------
    # False = size is a fixed INPUT, only dispatch is optimised.
    # True  = size is a DECISION VARIABLE (operating cost + annualised capex minimised).
    OPTIMISE_BOILER: bool = False
    OPTIMISE_TES: bool = False
    OPTIMISE_CHP: bool = False
    tes_capacity_max_MWh: float | None = None     # optional upper bound when OPTIMISE_TES = True

    # ---- Assumed sinks (not drawn in the scenario figure) ---------------------
    heat_dump_cost_EUR_per_MWh: float = 0.0   # 0 = free heat rejection (current assumption)
    co2_vent_cost_EUR_per_t: float = 0.0      # 0 = free CO2 venting (current assumption)

    # ---- Slack (numerical safety, should stay at 0) --------------------------
    voll_heat_EUR_per_MWh: float = 1_000
    voll_co2_EUR_per_t: float = 5_000

    # ---- Solver --------------------------------------------------------------
    solver_name: str = "highs"
    # HiGHS defaults written out explicitly (reproducibility), plus a 1 h time limit instead of none
    solver_options: dict = field(default_factory=lambda: {
        "solver": "choose",                       # simplex / IPM chosen by HiGHS
        "presolve": "choose",
        "run_crossover": "on",
        "primal_feasibility_tolerance": 1e-7,
        "dual_feasibility_tolerance": 1e-7,
        "random_seed": 0,
        "time_limit": 3600,                       # s
    })

    def __post_init__(self):
        if self.country not in COUNTRY_DEFAULTS:
            raise ValueError(f"country must be one of {list(COUNTRY_DEFAULTS)}, got {self.country!r}")
        if self.priority_penalty_EUR_per_MWh >= self.voll_heat_EUR_per_MWh:
            raise ValueError("priority_penalty_EUR_per_MWh must be below voll_heat_EUR_per_MWh, "
                             "otherwise unserved heat would be preferred to the backup boiler")

    def co2_levy(self):
        """EUR per t CO2 from burning gas: explicit value, else country default."""
        if self.co2_price_EUR_per_t is not None:
            return self.co2_price_EUR_per_t
        return COUNTRY_DEFAULTS[self.country]["co2_levy_EUR_per_t"]

    def grid_ef(self):
        """Constant grid emission factor, t CO2 per MWh: explicit value, else country default."""
        if self.grid_co2_factor_t_per_MWh is not None:
            return self.grid_co2_factor_t_per_MWh
        return COUNTRY_DEFAULTS[self.country]["grid_ef_t_per_MWh"]
