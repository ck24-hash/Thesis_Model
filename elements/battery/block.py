"""Battery: a store with a charge and a discharge link on the site's electricity bus, sized in kWh bought. The
dispatch uses the state-of-charge window minus the ancillary reserve (tech.py). The block also holds the battery's
money: price by size (tiers), subsidy (percent, fixed, or up to a threshold size such as CH's OCAN rule),
replacements, EMS costs (ems.py) and the ancillary revenue (rate per country). From elements/battery_reference:
blocks/tech.py, capex.py, subsidies.py, ems.py, engine/setup.py and the battery part of engine/dispatch.py.

The size sweep and the payback study are in sizing.py and study.py."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pypsa

from common import parameters as P
from common.money import apply_subsidy, subsidy_label
from common.network import BUS
from elements.battery.ems import Ems
from elements.battery.tech import Battery as Tech

ID = "battery"
CARRIERS = {"in": ["electricity"], "out": ["electricity"]}
COLUMNS: list = []
OWNS = {"tech": ["battery"], "capex": ["battery_tiers_per_kwh", "battery_replacement_frac"],
        "finance": ["battery_life_yr", "peak_shaving_realisation"], "subsidies": ["battery", "replacements_subsidised"],
        "ems": None, "ancillary": None}
PARAMS_DIR = Path(__file__).resolve().parent / "params"
STORE, CHARGER, DISCHARGER = "battery_store", "bat_charger", "bat_discharger"   # the battery model's names


def load_params(market: dict, currency: str, overrides: dict | None = None, fx: dict | None = None) -> dict:
    c, r = market["country"], market["region"]
    params = {
        "subsidies": P.by_place(PARAMS_DIR / "subsidies", c, r),
        "ancillary": P.required(PARAMS_DIR / "ancillary" / f"{c}.json", "ancillary"),
        "capex": P.shared(PARAMS_DIR / "capex", c),
        "finance": P.shared(PARAMS_DIR / "finance", c),
        "tech": P.shared(PARAMS_DIR / "tech", c),
        "ems": P.shared(PARAMS_DIR / "ems", c),
    }
    return P.finish(params, overrides, currency, fx)


class Battery:
    def __init__(self, params: dict, yearly_load_kwh: float):
        """yearly_load_kwh: the site's load, for a subsidy threshold that depends on it (OCAN)."""
        self.params = params
        self.ancillary = params["ancillary"]
        self.tech = Tech(params["tech"], self.ancillary.get("reserve"))
        self.capex = params["capex"]
        self.subsidies = params["subsidies"]
        self.ems = Ems(params["ems"])
        self.life_yr = params["finance"]["battery_life_yr"]
        b = self.subsidies["battery"]
        # OCAN rule: the largest subsidised battery = yearly load / 365 x factor (rounded), or the typed threshold
        self.subsidy_threshold_kwh = (round(yearly_load_kwh / 365 * b["ocan_factor"])
                                      if b.get("threshold_mode") == "ocan" else b["threshold_kwh"])

    # -- network -------------------------------------------------------------------------------------------------------
    def add_to(self, n: pypsa.Network, size_kwh: float) -> None:
        """The battery the dispatch may use: size_kwh is the bought size; the ancillary reserve is left out."""
        t = self.tech
        n.add("Bus", "battery_bus", carrier="electricity")
        n.add("Store", STORE, bus="battery_bus", e_nom=t.dispatch_kwh(size_kwh), e_cyclic=True,
              standing_loss=t.self_discharge_per_hour, marginal_cost=0)
        n.add("Link", CHARGER, bus0=BUS, bus1="battery_bus", p_nom=t.dispatch_kw(size_kwh),
              efficiency=t.eff_store, marginal_cost=0)
        n.add("Link", DISCHARGER, bus0="battery_bus", bus1=BUS, p_nom=t.dispatch_kw(size_kwh),
              efficiency=t.eff_dispatch, marginal_cost=0)

    @staticmethod
    def results(n: pypsa.Network) -> dict:
        """battery_power (positive = discharging, negative = charging) and battery_soc (kWh in the dispatch window)."""
        return {"battery_power": -n.links_t.p1[DISCHARGER] - n.links_t.p0[CHARGER],
                "battery_soc": n.stores_t.e[STORE]}

    # -- money ---------------------------------------------------------------------------------------------------------
    def price_per_kwh(self, size_kwh: float) -> float:
        """Price per kWh at this size, linear between the tiers (and flat beyond the first and last)."""
        tiers = self.capex["battery_tiers_per_kwh"]
        return float(np.interp(size_kwh, [t[0] for t in tiers], [t[1] for t in tiers]))

    def gross(self, size_kwh: float) -> float:
        return size_kwh * self.price_per_kwh(size_kwh)

    def replacement_cost(self, size_kwh: float, horizon_yr: float) -> float:
        """All replacements within the horizon (the PV life), each at battery_replacement_frac of the gross price,
        unsubsidised; the number of replacements may be fractional."""
        return ((horizon_yr / self.life_yr - 1) * self.capex["battery_replacement_frac"] * self.gross(size_kwh))

    def net_capex(self, size_kwh: float) -> float:
        """Net price of the first purchase after the subsidy (without the EMS capex)."""
        b = self.subsidies["battery"]
        gross = self.gross(size_kwh)
        cost_thr = self.gross(self.subsidy_threshold_kwh) if b["mode"] == "threshold" else None
        return apply_subsidy(gross, b["mode"], b["frac"], b["amount"],
                             size=size_kwh, threshold=self.subsidy_threshold_kwh, cost_at_threshold=cost_thr)

    def investment(self, size_kwh: float) -> float:
        """What the grower pays up front: net battery price + EMS capex."""
        return self.net_capex(size_kwh) + self.ems.capex

    def ancillary_revenue(self, size_kwh: float) -> float:
        return self.tech.ancillary_revenue(size_kwh, self.ancillary.get("rate_per_kw_year", 0.0))

    @property
    def cap_sweep_at_subsidy(self) -> bool:
        """The sweep is capped at the subsidised maximum only for a threshold subsidy (CH's OCAN rule)."""
        b = self.subsidies["battery"]
        return b["mode"] == "threshold" and b.get("frac", 0) > 0

    def subsidy_label(self, currency: str) -> str:
        b = self.subsidies["battery"]
        return subsidy_label(b["mode"], b["frac"], b["amount"], currency, threshold=self.subsidy_threshold_kwh)
