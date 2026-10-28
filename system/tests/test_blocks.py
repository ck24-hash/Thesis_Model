"""Checks of the blocks and the engine: python -m pytest system/tests -q (about 1 min).

The parameters and one short battery study are compared with the reference model (elements/battery_reference); the
electricity bus must balance at every step."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from system import compare, dispatch, setup  # noqa: E402  (compare puts the reference model on the path)

import parameters as reference_parameters  # noqa: E402  (elements/battery_reference/parameters.py)

EXAMPLES = ROOT / "examples" / "battery"
MARKETS = [{"country": "CH", "region": "GE", "utility": "SIG", "year": 2026},
           {"country": "NL", "region": "WestlandInfra", "utility": "MS", "year": 2026},
           {"country": "FR", "region": "HTA", "utility": "Reference", "year": 2025}]


def without_about(d):
    return {k: without_about(v) for k, v in d.items() if k != "_about"} if isinstance(d, dict) else d


@pytest.mark.parametrize("market", MARKETS, ids=lambda m: m["country"])
@pytest.mark.parametrize("business_model", ["direct_sales", "eaas"])
def test_parameters_as_reference(market, business_model):
    overrides = {"tech": {"battery": {"c_rate": 0.4}, "module_wp": 150}, "finance": {"pv_life_yr": 20},
                 "ancillary": {"rate_per_kw_year": 0}, "tariff": {"battery_export": "any"},
                 "capex": {"pv_per_wp": {"amount": 2.0}}}
    for ov in (None, overrides):
        ours = setup.parameters(market, business_model, ov)
        ref = reference_parameters.load(market["country"], market["region"], market["utility"], market["year"],
                                        business_model=business_model, overrides=ov)
        assert without_about(ours) == without_about(ref)


def test_overrides_go_to_their_block():
    owners = {key: m.OWNS for key, m in setup.BLOCKS.items()}
    split = setup.P.split_overrides({"tech": {"battery": {"c_rate": 0.4}, "module_wp": 150}, "ems": {"capex": 0},
                                     "tariff": {"export": {"per_kwh": 0.1}}}, owners)
    assert split["battery"] == {"tech": {"battery": {"c_rate": 0.4}}, "ems": {"capex": 0}}
    assert split["voltiris"] == {"tech": {"module_wp": 150}}
    assert split["grid"] == {"tariff": {"export": {"per_kwh": 0.1}}}
    with pytest.raises(KeyError, match="Unknown override group"):
        setup.P.split_overrides({"heat": {}}, owners)
    with pytest.raises(KeyError, match="Unknown override tech.cop"):
        setup.P.split_overrides({"tech": {"cop": 3}}, owners)


def test_blocks_not_built_or_missing():
    case = json.loads((EXAMPLES / "case_example_CH.json").read_text())
    frame, columns = setup.read_frame(setup.pd.read_excel(EXAMPLES / case["input_file"]), 2026)
    with pytest.raises(ValueError, match="Not built yet: heat_pump"):
        setup.System(frame, columns, case["market"], {"greenhouse": {}, "grid": {}, "heat_pump": {}})
    with pytest.raises(ValueError, match="missing: grid"):
        setup.System(frame, columns, case["market"], {"greenhouse": {}})


def test_electricity_balance_every_step():
    case = json.loads((EXAMPLES / "case_example_CH.json").read_text())
    s = setup.build(setup.as_system_case(case), EXAMPLES)
    n = dispatch.solve(s, "B", battery_kwh=200)
    res = dispatch.results(n, s)
    residual = res["pv"] + res["grid_import"] - res["grid_export"] + res["battery_power"] - res["load"]
    assert residual.abs().max() < 1e-6


@pytest.mark.parametrize("country", ["CH", "NL"])
def test_short_study_as_reference(country, tmp_path):
    """One battery size, the whole study: the summary and every table equal to the last digit."""
    case = json.loads((EXAMPLES / f"case_example_{country}.json").read_text())
    case["sizing"] = {"sweep_kwh": [100], "cap_at_subsidy_size": False}
    case["input_file"] = str(EXAMPLES / case["input_file"])
    ref = compare.run_reference(case, EXAMPLES, "t")
    new, _ = compare.blocks.run(case, EXAMPLES, "t", log=lambda *a, **k: None)
    assert compare.differences(ref, new) == []
