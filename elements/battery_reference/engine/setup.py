"""Everything one study needs, in one object: the time series, the market parameters as blocks, and the masks and
prices that follow from them. The engine functions take a Setup and the regime explicitly, so nothing is global."""
from __future__ import annotations

import pandas as pd

from blocks import subsidies as subsidies_block
from blocks.business_model import BusinessModel
from blocks.ems import Ems
from blocks.tariffs import Tariff
from blocks.tech import Battery
from engine.inputs import Study


class Setup:
    def __init__(self, study: Study, params: dict, grid: dict | None = None, one_meter: bool = True):
        self.study = study
        self.params = params
        self.dt = study.dt
        self.tariff = Tariff(params["tariff"])
        self.ancillary = params["ancillary"]
        self.battery = Battery(params["tech"], self.ancillary.get("reserve"))
        self.capex = params["capex"]
        self.subsidies = params["subsidies"]
        self.finance = params["finance"]
        self.ems = Ems(params["ems"])
        self.module_wp = params["tech"]["module_wp"]
        self.currency = self.tariff.currency
        da = study.da_price if self.uses_day_ahead else None
        if self.uses_day_ahead and da is None:
            raise ValueError("This tariff prices on the day-ahead price, but the input has no day-ahead column "
                             "('Day ahead kWh', or the name given under 'columns' in the case file).")
        if da is not None and da.isna().any():
            raise ValueError(f"The day-ahead price is missing at {int(da.isna().sum())} steps; this tariff needs it "
                             f"at every step.")
        self.da = da
        self.bm = BusinessModel(params["business_model"], study.modules, study.volt_pv, study.pv_total,
                                self.tariff.export_price(study.index, da), study.dt)
        grid = grid or {}
        self.grid_import_max_kw = grid.get("import_max_kw")
        self.grid_export_max_kw = grid.get("export_max_kw")
        self.one_meter = one_meter   # no import and export in the same step, exact where it could pay (see dispatch)
        self.battery_export = self.tariff.p.get("battery_export", "any")
        if self.battery_export not in ("any", "pv_only"):
            raise ValueError(f"battery_export must be 'any' or 'pv_only', not {self.battery_export!r}")
        self.hp_mask = self.tariff.hp_mask(study.index)
        self.winter_mask = self.tariff.winter_mask(study.index)
        self._prices: dict[str, pd.Series] = {}
        self.subsidy_threshold_kwh = subsidies_block.battery_threshold_kwh(self.subsidies, study.yearly_load_kwh)

    @property
    def uses_day_ahead(self) -> bool:
        return (any(c["by"] == "day_ahead" for _, c in self.tariff.components)
                or self.tariff.export["basis"] == "day_ahead")

    def import_price(self, regime: str) -> pd.Series:
        if regime not in self._prices:
            self._prices[regime] = self.tariff.import_price(self.study.index, regime, self.da)
        return self._prices[regime]

    def battery_net_capex(self, size_kwh: float) -> float:
        """Net price of the battery's first purchase after its subsidy (without the EMS capex)."""
        return subsidies_block.battery_net(size_kwh, self.capex, self.subsidies, self.subsidy_threshold_kwh)

    def battery_investment(self, size_kwh: float) -> float:
        """What the grower pays up front for the battery: net battery price + EMS capex."""
        return self.battery_net_capex(size_kwh) + self.ems.capex

    def ancillary_revenue(self, size_kwh: float) -> float:
        return self.battery.ancillary_revenue(size_kwh, self.ancillary.get("rate_per_kw_year", 0.0))

    @property
    def cap_sweep_at_subsidy(self) -> bool:
        """The sweep is capped at the subsidised maximum only for a threshold subsidy (CH's OCAN rule)."""
        b = self.subsidies["battery"]
        return b["mode"] == "threshold" and b.get("frac", 0) > 0
