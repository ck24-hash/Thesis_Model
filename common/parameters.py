"""Parameter files shared by every block: reading, merging, money in the market's currency, overrides.

Each block keeps its numbers in its own params/ folder, in groups (tech, capex, finance, subsidies, ...):

    params/<group>/default.json, <country>.json              the same everywhere; the country file overrides
    params/<group>/<country>/_country.json, <region>.json    per country and region (subsidies)
    params/<group>/<country>.json                            per country only (ancillary)
    params/<group>/<name>.json                               named variants (business models)

The more specific file wins. A money value written {"amount": x, "currency": "CHF"} (or {"tiers": [[kWh, price], ...],
"currency": ...}) is converted into the market's currency with common/fx.json, so a shared price is the same real
price in every country. Overrides change single values for one run, in the market's currency. The functions are the
ones of elements/battery_reference/parameters.py, with the folder as an argument.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

FX_FILE = Path(__file__).resolve().parent / "fx.json"


def read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_optional(path: Path) -> dict:
    return read(path) if path.is_file() else {}


def required(path: Path, what: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"No {what} parameters: {path.as_posix()} does not exist.")
    return read(path)


def deep_merge(base: dict, extra: dict) -> dict:
    """A copy of base with extra merged in; nested dicts merge, everything else is replaced."""
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# -- the files of one group -------------------------------------------------------------------------------------------
def shared(folder: Path, country: str) -> dict:
    """<folder>/default.json with <folder>/<country>.json merged over it."""
    out = deep_merge(read_optional(folder / "default.json"), read_optional(folder / f"{country}.json"))
    if not out:
        raise FileNotFoundError(f"No parameters in {folder.as_posix()}: default.json or {country}.json.")
    return out


def by_place(folder: Path, country: str, region: str | None) -> dict:
    """<folder>/<country>/_country.json with <folder>/<country>/<region>.json merged over it."""
    out = read_optional(folder / country / "_country.json")
    if region:
        out = deep_merge(out, read_optional(folder / country / f"{region}.json"))
    if not out:
        raise FileNotFoundError(f"No parameters for {country}/{region} under {folder.as_posix()}.")
    return out


# -- money ------------------------------------------------------------------------------------------------------------
def fx_rates() -> dict:
    return read(FX_FILE)


def convert(amount: float, from_currency: str, to_currency: str, fx: dict | None = None) -> float:
    """Amount in from_currency expressed in to_currency (EUR and CHF). The same currency returns the amount as is."""
    if from_currency == to_currency:
        return amount
    rate = (fx or fx_rates())["EUR_per_CHF"]
    if (from_currency, to_currency) == ("CHF", "EUR"):
        return round(amount * rate, 9)
    if (from_currency, to_currency) == ("EUR", "CHF"):
        return round(amount / rate, 9)
    raise ValueError(f"No exchange rate from {from_currency} to {to_currency} in common/fx.json.")


def eur_to_local(currency: str, fx: dict | None = None) -> float:
    """Factor turning an EUR price (the day-ahead series) into the market's currency."""
    return convert(1.0, "EUR", currency, fx) if currency != "EUR" else 1.0


def is_money(obj) -> bool:
    """A money object: {"amount": x, "currency": c} or {"tiers": [...], "currency": c}, nothing else. A group of
    settings that only has an "amount" among other keys (a subsidy) is not one."""
    return (isinstance(obj, dict) and "currency" in obj and ("amount" in obj or "tiers" in obj)
            and set(obj) <= {"amount", "tiers", "currency"})


def resolve_money(obj, currency: str, fx: dict):
    """Replace every money object in obj by its value in `currency`."""
    if is_money(obj):
        if "amount" in obj:
            return convert(obj["amount"], obj["currency"], currency, fx)
        return [[size, convert(price, obj["currency"], currency, fx)] for size, price in obj["tiers"]]
    if isinstance(obj, dict):
        return {k: resolve_money(v, currency, fx) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_money(v, currency, fx) for v in obj]
    return obj


def in_currency(obj, currency: str, base=None):
    """Overrides are in the market's currency: an override of a money object given without a currency gets it, so it
    is not read in the currency of the default it is merged into. base: the defaults at the same place, to tell a
    money object ({"amount", "currency"}) from a group of settings that has an "amount" key (a subsidy)."""
    if isinstance(obj, dict):
        b = base if isinstance(base, dict) else {}
        out = {k: in_currency(v, currency, b.get(k)) for k, v in obj.items()}
        if is_money(b) and ("amount" in obj or "tiers" in obj) and "currency" not in obj:
            out["currency"] = currency
        return out
    return obj


def finish(params: dict, overrides: dict | None, currency: str, fx: dict | None = None) -> dict:
    """The block's parameters with its overrides merged in and every money value in the market's currency."""
    fx = fx or fx_rates()
    return resolve_money(deep_merge(params, in_currency(overrides or {}, currency, params)), currency, fx)


# -- overrides: one dict for the whole run, each value to the block that owns it ---------------------------------------
def split_overrides(overrides: dict | None, owners: dict[str, dict]) -> dict[str, dict]:
    """Route a run's overrides ({"tech": {"battery": {...}, "module_wp": 150}, "tariff": {...}}) to the blocks.
    owners: block -> {group: None (the block owns the whole group) or [keys it owns in the group]}."""
    out: dict[str, dict] = {block: {} for block in owners}
    for group, value in (overrides or {}).items():
        whole = [b for b, own in owners.items() if group in own and own[group] is None]
        if whole:
            out[whole[0]][group] = value
            continue
        parts = {b: own[group] for b, own in owners.items() if own.get(group)}
        if not parts:
            raise KeyError(f"Unknown override group {group!r}; the groups are "
                           f"{sorted({g for own in owners.values() for g in own})}.")
        for key, v in (value or {}).items():
            block = next((b for b, keys in parts.items() if key in keys), None)
            if block is None:
                raise KeyError(f"Unknown override {group}.{key}; {group} holds "
                               f"{sorted(k for keys in parts.values() for k in keys)}.")
            out[block].setdefault(group, {})[key] = v
    return out
