"""Battery technology: the usable state-of-charge window, the power, and the share kept for ancillary services
(the reserve comes from the ancillary block, which may differ per country)."""
from __future__ import annotations


class Battery:
    def __init__(self, tech: dict, reserve: dict | None = None):
        b = tech["battery"]
        self.c_rate = b["c_rate"]
        self.eff_store = b["efficiency_store"]
        self.eff_dispatch = b["efficiency_dispatch"]
        self.soc_min = b["soc_min"]
        self.soc_max = b["soc_max"]
        self.self_discharge_per_hour = b["self_discharge_per_day"] / 24
        r = reserve or {"mode": "percent", "frac": 0.0}
        self.reserve_mode = r["mode"]
        self.reserve_frac = r.get("frac", 0.0)
        self.reserve_kwh = r.get("kwh", 0.0)

    @property
    def eta2(self) -> float:
        """Round-trip efficiency."""
        return self.eff_store * self.eff_dispatch

    def power_kw(self, size_kwh: float) -> float:
        return size_kwh * self.c_rate

    def soc_window_kwh(self, size_kwh: float) -> float:
        """Usable energy inside the SoC window."""
        return size_kwh * (self.soc_max - self.soc_min)

    def reserved_kwh(self, size_kwh: float) -> float:
        """kWh of the SoC window kept out of the dispatch for ancillary services."""
        if self.reserve_mode == "fixed_kwh":
            return min(self.reserve_kwh, self.soc_window_kwh(size_kwh))
        return self.soc_window_kwh(size_kwh) * self.reserve_frac

    def dispatch_kwh(self, size_kwh: float) -> float:
        """kWh of the SoC window the dispatch may use for self-consumption and arbitrage."""
        return self.soc_window_kwh(size_kwh) - self.reserved_kwh(size_kwh)

    def reserved_kw(self, size_kwh: float) -> float:
        """Inverter power reserved for ancillary services: the same share as the energy reserve, of nameplate power."""
        share = self.reserved_kwh(size_kwh) / self.soc_window_kwh(size_kwh) if size_kwh > 0 else 0.0
        return size_kwh * self.c_rate * share

    def dispatch_kw(self, size_kwh: float) -> float:
        """Charge and discharge power the dispatch may use."""
        return size_kwh * self.c_rate - self.reserved_kw(size_kwh)

    def ancillary_revenue(self, size_kwh: float, rate_per_kw_year: float) -> float:
        """Yearly revenue of the reserved power."""
        return self.reserved_kw(size_kwh) * rate_per_kw_year
