"""Loads the parameters of a market: country, region (canton in CH) and utility.

Each block has its own folder under params/:

    params/tariffs/<country>/_country.json                what holds in the whole country (currency, national levies)
    params/tariffs/<country>/<region>/_canton.json        what holds in the region (_region.json works too)
    params/tariffs/<country>/<region>/<utility>_<year>.json   the utility's or grid operator's tariff
    params/subsidies/<country>/_country.json, <country>/<region>.json
    params/ancillary/<country>.json                       allowed to differ per country
    params/capex/default.json, finance/default.json, tech/default.json, ems/default.json
                                                          the same everywhere; params/<block>/<country>.json overrides
    params/business_models/<name>.json
    params/fx.json                                        the exchange rate for shared money values

The more specific file wins: region over country, utility over region, country over default. A money value written as
{"amount": x, "currency": "CHF"} (or {"tiers": [[kWh, price], ...], "currency": "CHF"}) is converted into the
market's currency, so shared prices are the same real price everywhere. `overrides` changes single values for one
study, in the market's currency, for example {"tariff": {"export": {"per_kwh": 0.066}}}.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

PARAMS_DIR = Path(__file__).resolve().parent / "params"
BLOCKS = ("tariff", "subsidies", "ancillary", "capex", "finance", "tech", "ems", "business_model")


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_optional(path: Path) -> dict:
    return _read(path) if path.is_file() else {}


def deep_merge(base: dict, extra: dict) -> dict:
    """A copy of base with extra merged in; nested dicts merge, everything else is replaced."""
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _required(path: Path, what: str) -> dict:
    if not path.is_file():
        rel = path.relative_to(PARAMS_DIR)
        raise FileNotFoundError(f"No {what} parameters: params/{rel.as_posix()} does not exist.")
    return _read(path)


# -- money ------------------------------------------------------------------------------------------------------------
def fx_rates() -> dict:
    return _read(PARAMS_DIR / "fx.json")


def convert(amount: float, from_currency: str, to_currency: str, fx: dict | None = None) -> float:
    """Amount in from_currency expressed in to_currency (EUR and CHF). The same currency returns the amount as is."""
    if from_currency == to_currency:
        return amount
    rate = (fx or fx_rates())["EUR_per_CHF"]
    if (from_currency, to_currency) == ("CHF", "EUR"):
        return round(amount * rate, 9)
    if (from_currency, to_currency) == ("EUR", "CHF"):
        return round(amount / rate, 9)
    raise ValueError(f"No exchange rate from {from_currency} to {to_currency} in params/fx.json.")


def eur_to_local(currency: str, fx: dict | None = None) -> float:
    """Factor turning an EUR price (the day-ahead series) into the market's currency."""
    return convert(1.0, "EUR", currency, fx) if currency != "EUR" else 1.0


def resolve_money(obj, currency: str, fx: dict):
    """Replace every money object in obj by its value in `currency`."""
    if isinstance(obj, dict):
        if "currency" in obj and "amount" in obj:
            return convert(obj["amount"], obj["currency"], currency, fx)
        if "currency" in obj and "tiers" in obj:
            return [[size, convert(price, obj["currency"], currency, fx)] for size, price in obj["tiers"]]
        return {k: resolve_money(v, currency, fx) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_money(v, currency, fx) for v in obj]
    return obj


def _in_currency(obj, currency: str):
    """Overrides are in the market's currency: a money object given without a currency gets it, so it is not read in
    the currency of the default it is merged into."""
    if isinstance(obj, dict):
        out = {k: _in_currency(v, currency) for k, v in obj.items()}
        if ("amount" in obj or "tiers" in obj) and "currency" not in obj:
            out["currency"] = currency
        return out
    return obj


# -- blocks -------------------------------------------------------------------------------------------------------------
def load_tariff(country: str, region: str, utility: str, year: int) -> dict:
    base = PARAMS_DIR / "tariffs" / country
    tariff = _read_optional(base / "_country.json")
    tariff = deep_merge(tariff, _read_optional(base / region / "_canton.json"))
    tariff = deep_merge(tariff, _read_optional(base / region / "_region.json"))
    tariff = deep_merge(tariff, _required(base / region / f"{utility}_{year}.json", "tariff"))
    tariff.update(country=country, region=region)
    if "currency" not in tariff:
        raise KeyError(f"params/tariffs/{country}/_country.json has no currency.")
    return tariff


def load_subsidies(country: str, region: str | None) -> dict:
    base = PARAMS_DIR / "subsidies" / country
    subsidies = _read_optional(base / "_country.json")
    if region:
        subsidies = deep_merge(subsidies, _read_optional(base / f"{region}.json"))
    if not subsidies:
        raise FileNotFoundError(f"No subsidy parameters for {country}/{region} under params/subsidies/.")
    return subsidies


def load_shared(block: str, country: str) -> dict:
    """params/<block>/default.json with params/<block>/<country>.json merged over it."""
    base = PARAMS_DIR / block
    out = deep_merge(_read_optional(base / "default.json"), _read_optional(base / f"{country}.json"))
    if not out:
        raise FileNotFoundError(f"No {block} parameters: params/{block}/default.json or {country}.json.")
    return out


def load(country: str, region: str, utility: str, year: int,
         business_model: str = "direct_sales", overrides: dict | None = None) -> dict:
    """All parameters of one market, as one dict with a key per block, money in the market's currency."""
    tariff = load_tariff(country, region, utility, year)
    currency = tariff["currency"]
    fx = fx_rates()
    params = {
        "tariff": tariff,
        "subsidies": load_subsidies(country, region),
        "ancillary": _required(PARAMS_DIR / "ancillary" / f"{country}.json", "ancillary"),
        "capex": load_shared("capex", country),
        "finance": load_shared("finance", country),
        "tech": load_shared("tech", country),
        "ems": load_shared("ems", country),
        "business_model": _required(PARAMS_DIR / "business_models" / f"{business_model}.json", "business model"),
    }
    unknown = set(overrides or {}) - set(params)
    if unknown:
        raise KeyError(f"Unknown override block(s) {sorted(unknown)}; the blocks are {sorted(params)}.")
    params = resolve_money(deep_merge(params, _in_currency(overrides or {}, currency)), currency, fx)
    params["tariff"].setdefault("eur_to_local", eur_to_local(currency, fx))
    return params
