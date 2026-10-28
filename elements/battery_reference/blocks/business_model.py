"""The Voltiris business model: direct sales or energy as a service (EaaS).

Under EaaS the grower pays a price per MWh for Voltiris energy used on site and Voltiris keeps its exports. Voltiris
and an existing PV share one meter, so on-site use is split pro rata to production: s_t = Voltiris share of PV at t.
The grower's PV cash flow at t is
    FiT on existing-PV exports (1-s)*FiT*exp  -  EaaS fee s*price*(pv - exp)
    = export_value_t * exp  -  price * s * pv,   export_value_t = (1-s)*FiT + s*price
so the dispatch only needs a time-varying export value; the constant goes back into the bills.
"""
from __future__ import annotations

import pandas as pd


class BusinessModel:
    def __init__(self, p: dict, modules: int, volt_pv_kw: pd.Series, pv_total_kw: pd.Series,
                 feed_in: float | pd.Series, dt: float):
        """feed_in: the export price per kWh, a number (fixed feed-in) or a series on the study's index (day-ahead)."""
        assert p["type"] in ("direct_sales", "eaas"), f"unknown business model {p['type']!r}"
        self.type = p["type"]
        self.price_per_mwh = p.get("price_per_mwh")
        self.price = (self.price_per_mwh or 0) / 1000
        self.feed_in = feed_in
        self.dt = dt
        self.pv_total = pv_total_kw
        self.volt_share = (volt_pv_kw / pv_total_kw).where(pv_total_kw > 0, 0.0).clip(0, 1)
        self.eaas = self.type == "eaas" and modules > 0   # EaaS only applies with Voltiris modules installed

    @property
    def export_value(self) -> pd.Series:
        """The grower's value of 1 kWh exported, per step."""
        if self.eaas:
            return self.feed_in * (1 - self.volt_share) + self.price * self.volt_share
        if isinstance(self.feed_in, pd.Series):
            return self.feed_in
        return pd.Series(self.feed_in, index=self.pv_total.index)

    @property
    def feed_in_is_fixed(self) -> bool:
        return not isinstance(self.feed_in, pd.Series)

    def _feed_in_on(self, index: pd.Index):
        return self.feed_in if self.feed_in_is_fixed else self.feed_in.reindex(index)

    def grower_export_revenue(self, export_kw: pd.Series, volt: bool = True) -> pd.Series:
        """What the grower earns on exports per step: FiT on all exports, or on the existing-PV share under EaaS.
        volt=False: a case without Voltiris."""
        s = self.volt_share.reindex(export_kw.index) if (self.eaas and volt) else 0.0
        return export_kw * self._feed_in_on(export_kw.index) * (1 - s) * self.dt

    def eaas_fee(self, export_kw: pd.Series, volt: bool = True) -> pd.Series:
        """What the grower pays Voltiris per step under EaaS; zero for direct sales."""
        if not (self.eaas and volt):
            return pd.Series(0.0, index=export_kw.index)
        s = self.volt_share.reindex(export_kw.index)
        return s * (self.pv_total.reindex(export_kw.index) - export_kw).clip(lower=0) * self.price * self.dt

    def pv_net_revenue(self, export_kw: pd.Series, volt: bool = True) -> pd.Series:
        """The grower's PV cash flow per step: FiT received minus the EaaS fee."""
        return self.grower_export_revenue(export_kw, volt) - self.eaas_fee(export_kw, volt)
