"""Energy management system (EMS) costs: a fixed yearly cost, fees as a share of the ancillary revenue and of the
bill saving against the no-battery case (each split into Voltiris and an external company), and an EMS capex added to
the battery investment once (not subsidised, not bought again at battery replacements)."""
from __future__ import annotations


class Ems:
    def __init__(self, p: dict):
        self.fixed_per_year = p.get("fixed_per_year", 0.0)
        self.capex = p.get("capex", 0.0)
        self.ancillary_pct = {"voltiris": 0.0, "external": 0.0, **(p.get("ancillary_fee_pct") or {})}
        self.savings_pct = {"voltiris": 0.0, "external": 0.0, **(p.get("savings_fee_pct") or {})}

    def fees(self, ancillary_revenue: float, bill_saving: float) -> dict:
        """The yearly EMS costs for one battery: fixed, fees on ancillary revenue and on the bill saving (only when the
        saving is positive), per party, and the total."""
        saving = max(bill_saving, 0.0)
        out = {
            "fixed": self.fixed_per_year,
            "ancillary_voltiris": ancillary_revenue * self.ancillary_pct["voltiris"],
            "ancillary_external": ancillary_revenue * self.ancillary_pct["external"],
            "savings_voltiris": saving * self.savings_pct["voltiris"],
            "savings_external": saving * self.savings_pct["external"],
        }
        out["voltiris"] = out["ancillary_voltiris"] + out["savings_voltiris"]
        out["external"] = out["ancillary_external"] + out["savings_external"]
        out["total"] = out["fixed"] + out["voltiris"] + out["external"]
        return out
