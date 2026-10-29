"""Commercial: what the system's parts cost and earn, apart from the grid tariff (elements/grid), the gas price
(elements/gas_supply) and the subsidies (general/subsidies): the Voltiris business model (direct sales or EaaS,
business_model.py), the investment prices (PV per Wp, battery price tiers, battery replacements, gas boiler per kW and
its O&M, heat storage per kWh and its O&M), the lifetimes, and the revenue rate of the battery's ancillary reserve. From elements/battery_reference: blocks/capex.py, blocks/business_model.py and the money parts of
engine/setup.py."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from common import parameters as P
from general.commercial.business_model import BusinessModel

ID = "commercial"
OWNS = {"business_model": None, "capex": None, "finance": None, "ancillary": ["rate_per_kw_year", "rate_note"]}
PARAMS_DIR = Path(__file__).resolve().parent / "params"


def business_models() -> list[str]:
    return sorted(p.stem for p in (PARAMS_DIR / "business_models").glob("*.json"))


def load_params(market: dict, currency: str, business_model: str = "direct_sales", overrides: dict | None = None,
                fx: dict | None = None) -> dict:
    c = market["country"]
    params = {
        "ancillary": P.required(PARAMS_DIR / "ancillary" / f"{c}.json", "ancillary rate"),
        "capex": P.shared(PARAMS_DIR / "capex", c),
        "finance": P.shared(PARAMS_DIR / "finance", c),
        "business_model": P.required(PARAMS_DIR / "business_models" / f"{business_model}.json", "business model"),
    }
    return P.finish(params, overrides, currency, fx)


class Commercial:
    def __init__(self, params: dict):
        self.params = params
        self.capex = params["capex"]
        self.pv_life_yr = params["finance"]["pv_life_yr"]          # also the horizon of the battery study
        self.battery_life_yr = params["finance"]["battery_life_yr"]
        self.ancillary_rate = params["ancillary"].get("rate_per_kw_year", 0.0)

    def business_model(self, modules: int, volt_pv_kw: pd.Series, pv_total_kw: pd.Series, feed_in,
                       dt: float) -> BusinessModel:
        """The business model applied to the site: EaaS only counts with Voltiris modules installed."""
        return BusinessModel(self.params["business_model"], modules, volt_pv_kw, pv_total_kw, feed_in, dt)

    def pv_capex(self, modules: int, module_wp: float) -> float:
        return modules * module_wp * self.capex["pv_per_wp"]

    def battery_price_per_kwh(self, size_kwh: float) -> float:
        """Price per kWh at this size, linear between the tiers (and flat beyond the first and last)."""
        tiers = self.capex["battery_tiers_per_kwh"]
        return float(np.interp(size_kwh, [t[0] for t in tiers], [t[1] for t in tiers]))

    def battery_gross(self, size_kwh: float) -> float:
        return size_kwh * self.battery_price_per_kwh(size_kwh)

    # -- gas boiler ---------------------------------------------------------------------------------------------------
    @property
    def boiler_life_yr(self) -> float:
        return self.params["finance"]["boiler_life_yr"]

    def boiler_capex(self, size_kw_th: float) -> float:
        return size_kw_th * self.capex["boiler_per_kw_th"]

    def boiler_fixed_om(self, size_kw_th: float) -> float:
        """Yearly fixed operation and maintenance."""
        return size_kw_th * self.capex["boiler_fixed_om_per_kw_year"]

    @property
    def boiler_var_om_per_kwh(self) -> float:
        """Variable operation and maintenance per kWh of heat."""
        return self.capex["boiler_var_om_per_mwh_heat"] / 1000

    # -- heat storage -------------------------------------------------------------------------------------------------
    @property
    def thermal_storage_life_yr(self) -> float:
        return self.params["finance"]["thermal_storage_life_yr"]

    def thermal_storage_capex(self, size_kwh: float) -> float:
        return size_kwh * self.capex["thermal_storage_per_kwh"]

    def thermal_storage_fixed_om(self, size_kwh: float) -> float:
        """Yearly fixed operation and maintenance."""
        return size_kwh * self.capex["thermal_storage_fixed_om_per_kwh_year"]

    def battery_replacement_cost(self, size_kwh: float, horizon_yr: float) -> float:
        """All replacements within the horizon (the PV life), each at battery_replacement_frac of the gross price,
        unsubsidised; the number of replacements may be fractional."""
        return ((horizon_yr / self.battery_life_yr - 1) * self.capex["battery_replacement_frac"]
                * self.battery_gross(size_kwh))
