"""
Extract greenhouse heat, electricity and CO2 demand from a KasEnergieWijzer
'GetResults' response (JSON) and plot them.

Usage:
    python kew_extract_demand.py getresults.json
    python kew_extract_demand.py getresults.json --area 100000 --out results_baseline

Outputs (in --out folder):
    daily_demand.csv        daily heat, electricity and CO2 demand
    duration_curves.csv     heat, electricity and CO2 duration curves
    heat_demand.png, electricity_demand.png, co2_demand.png
    summary.txt             annual totals and peaks, checked against the tool's tables

Units in the KasEnergieWijzer response (checked against the annual tables):
    dailyHeatUse   MJ/m2/day       heatingPowerFreq  W/m2   vs cumulative hours
    dailyElecUse   kWh/m2/day      elecPowerFreq     W/m2   vs cumulative hours
    dailyCO2dose   kg/ha/day       CO2doseFreq       kg/ha/h vs cumulative hours (assumed)
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# =====================================================================
# SETTINGS - edit these, then press Run (▶) in VS Code
# =====================================================================
# Use r"..." on Windows so backslashes are read correctly
INPUT_FILE = r"C:\Users\Charbel\Downloads\test.txt"
AREA_M2 = None          # e.g. 100000 for a 10 ha greenhouse; None = results per m2
OUT_DIR = None          # None = folder next to the input file, named after it
# =====================================================================

MONTH_START = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COLORS = {"heat": "#D84315", "elec": "#1565C0", "co2": "#2E7D32"}


# ---------------------------------------------------------------- reading
def load(path):
    """Read the response from a .txt or .json file (content is JSON either way)."""
    raw_bytes = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            start = text.find("{")          # skip anything pasted before the JSON
            raw = json.loads(text[start:text.rfind("}") + 1])
            return raw.get("data", raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            continue
    raise SystemExit(f"Could not read {path} as a KasEnergieWijzer response.")


def current_index(obj, n_series):
    """Index of the 'current scenario' series (works with 1 or 2 scenarios)."""
    legend = obj.get("legend") or obj.get("legx") or []
    if "current scenario" in legend:
        return legend.index("current scenario")
    return n_series - 1


def get_series(data, key):
    """Return (x, y) for the current scenario of a chart object, or None."""
    obj = data.get(key)
    if not obj or not obj.get("x") or not obj.get("y"):
        return None
    x, y = obj["x"], obj["y"]
    if isinstance(y[0], list):
        i = current_index(obj, len(y))
        y = y[i]
        if isinstance(x[0], list):
            x = x[min(i, len(x) - 1)]
    elif isinstance(x[0], list):
        x = x[-1]
    if not y:
        return None
    return list(x), list(y)


def get_stacked(data, key):
    """Return {source: daily series} for stacked charts, skipping all-zero sources."""
    obj = data.get(key)
    if not obj or not obj.get("x") or not obj.get("y"):
        return {}
    names = obj.get("legend") or [f"s{i}" for i in range(len(obj["y"]))]
    return {n: v for n, v in zip(names, obj["y"]) if any(abs(a) > 0 for a in v)}


def table_value(data, table, label):
    """Read the current-scenario value of one row in a tool table."""
    for row in data.get(table, [])[1:]:
        if row and row[0] == label:
            try:
                return float(row[-2])
            except (ValueError, TypeError):
                return None
    return None


# ---------------------------------------------------------------- plotting
def month_axis(ax):
    ax.set_xticks(MONTH_START)
    ax.set_xticklabels(MONTH_NAMES)
    ax.set_xlim(1, 365)


def plot_flow(daily, duration, stacked, color, title, ylab_daily, ylab_peak, fname):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.5),
                                   gridspec_kw={"width_ratios": [2, 1]})
    days, values = daily
    s = pd.Series(values, index=days)

    if stacked:
        ax1.stackplot(days, *stacked.values(),
                      labels=[f"production: {k}" for k in stacked], alpha=0.35)
    else:
        ax1.fill_between(days, values, color=color, alpha=0.25, linewidth=0)
    ax1.plot(days, values, color=color, linewidth=0.8, label="daily use")
    ax1.plot(s.index, s.rolling(7, center=True, min_periods=1).mean(),
             color="black", linewidth=1.2, label="7-day mean")
    ax1.legend(loc="upper center", fontsize=8, frameon=False, ncol=3)
    month_axis(ax1)
    ax1.set_ylabel(ylab_daily)
    ax1.set_title("Daily profile", fontsize=11)
    ax1.set_ylim(bottom=0)

    if duration:
        hours, power = duration
        ax2.step(hours, power, where="post", color=color, linewidth=1.5)
        ax2.set_xlim(0, 8760)
        ax2.set_ylim(bottom=0)
        ax2.set_xlabel("Hours per year (cumulative)")
        ax2.set_ylabel(ylab_peak)
        ax2.set_title(f"Duration curve (peak {max(power):,.1f})", fontsize=11)
    else:
        ax2.text(0.5, 0.5, "no duration curve in file", ha="center", va="center")
        ax2.set_axis_off()

    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(alpha=0.3)

    fig.suptitle(title, fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(fname, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("json_file", nargs="?", default=INPUT_FILE,
                   help="response file (.txt or .json); default = INPUT_FILE in the script")
    p.add_argument("--area", type=float, default=AREA_M2,
                   help="greenhouse area in m2; if given, results are scaled to the whole greenhouse")
    p.add_argument("--out", default=OUT_DIR)
    args = p.parse_args()

    in_path = Path(args.json_file)
    if not in_path.is_file():
        sys.exit(f"Input file not found: {in_path}\n"
                 f"Edit INPUT_FILE at the top of the script.")
    if args.out is None:
        args.out = in_path.parent / f"{in_path.stem}_output"

    data = load(in_path)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    heat = get_series(data, "dailyHeatUse")
    elec = get_series(data, "dailyElecUse")
    co2 = get_series(data, "dailyCO2dose")
    missing = [k for k, v in [("dailyHeatUse", heat), ("dailyElecUse", elec),
                              ("dailyCO2dose", co2)] if v is None]
    if missing:
        raise SystemExit(f"Missing or empty series in file: {missing}")

    heat_dur = get_series(data, "heatingPowerFreq")
    elec_dur = get_series(data, "elecPowerFreq")
    co2_dur = get_series(data, "CO2doseFreq")

    # ---- unit conversion: per m2, or whole greenhouse if --area is given
    A = args.area
    if A:
        f_heat, u_heat = A / 3.6 / 1000, "MWh/day"     # MJ/m2 -> MWh
        f_elec, u_elec = A / 1000, "MWh/day"           # kWh/m2 -> MWh
        f_co2, u_co2 = A / 1e4 / 1000, "t/day"         # kg/ha -> t
        f_hp, u_hp = A / 1e6, "MW"                     # W/m2 -> MW
        f_cp, u_cp = A / 1e4 / 1000, "t/h"             # kg/ha/h -> t/h
        scope = f"{A:,.0f} m2"
    else:
        f_heat, u_heat = 1 / 3.6, "kWh/m2/day"         # MJ -> kWh
        f_elec, u_elec = 1, "kWh/m2/day"
        f_co2, u_co2 = 1 / 1e4, "kg/m2/day"
        f_hp, u_hp = 1, "W/m2"
        f_cp, u_cp = 1, "kg/ha/h"
        scope = "per m2"

    def scale(series, f):
        return (series[0], [v * f for v in series[1]]) if series else None

    heat_s, elec_s, co2_s = scale(heat, f_heat), scale(elec, f_elec), scale(co2, f_co2)
    heat_d, elec_d, co2_d = scale(heat_dur, f_hp), scale(elec_dur, f_hp), scale(co2_dur, f_cp)

    # ---- stacked sources (only filled when the tool reports them)
    heat_src = {k: [v * f_heat for v in vals]
                for k, vals in get_stacked(data, "heatProdStacked").items()}
    elec_src = {k: [v * f_elec for v in vals]
                for k, vals in get_stacked(data, "dailyElecUseStacked").items()}

    # ---- CSV exports
    # day of year -> calendar date (non-leap reference year, 365 days)
    dates = pd.to_datetime("2023-01-01") + pd.to_timedelta(
        [int(d) - 1 for d in heat[0]], unit="D")
    daily = pd.DataFrame({
        "day_of_year": heat[0],
        "month": dates.month,
        "day": dates.day,
        f"heat_{u_heat}": heat_s[1],
        f"elec_{u_elec}": elec_s[1],
        f"co2_{u_co2}": co2_s[1],
    })
    for k, v in heat_src.items():
        daily[f"heat_prod_{k}_{u_heat}"] = v
    daily.to_csv(out / "daily_demand.csv", index=False)

    dur_frames = []
    for name, d, u in [("heat", heat_d, u_hp), ("elec", elec_d, u_hp), ("co2", co2_d, u_cp)]:
        if d:
            dur_frames.append(pd.DataFrame({"flow": name, "hours": d[0], f"value": d[1], "unit": u}))
    if dur_frames:
        pd.concat(dur_frames).to_csv(out / "duration_curves.csv", index=False)

    # ---- plots
    plot_flow(heat_s, heat_d, heat_src, COLORS["heat"],
              f"Greenhouse heat demand ({scope})", f"Heat [{u_heat}]",
              f"Heat power [{u_hp}]", out / "heat_demand.png")
    plot_flow(elec_s, elec_d, elec_src, COLORS["elec"],
              f"Greenhouse electricity demand ({scope})", f"Electricity [{u_elec}]",
              f"Electric power [{u_hp}]", out / "electricity_demand.png")
    plot_flow(co2_s, co2_d, None, COLORS["co2"],
              f"Greenhouse CO2 dosing ({scope})", f"CO2 [{u_co2}]",
              f"CO2 dosing rate [{u_cp}]", out / "co2_demand.png")

    # ---- summary with check against the tool's annual tables (per m2)
    heat_tot = sum(heat[1])                 # MJ/m2
    elec_tot = sum(elec[1])                 # kWh/m2
    co2_tot = sum(co2[1]) / 1e4             # kg/m2
    heat_tab = sum(filter(None, [table_value(data, "tableHeat", r) for r in
                   ["Ketel", "WKK", "Warmtepomp/chiller", "Geothermie", "Biomassa"]]))
    lines = [
        f"File: {args.json_file}",
        "Annual totals per m2 (sum of daily series | tool table)",
        f"  Heat use         {heat_tot:8.1f} MJ/m2  ({heat_tot/3.6:6.1f} kWh/m2) | heat production {heat_tab:.0f} MJ/m2",
        f"  Electricity      {elec_tot:8.1f} kWh/m2 | Belichting {table_value(data, 'tableElectricity', 'Belichting')}",
        f"  CO2 dosed        {co2_tot:8.2f} kg/m2  | Totale gift {table_value(data, 'tableCO2', 'Totale gift')}",
        f"  Natural gas      {table_value(data, 'tableSources', 'Aardgas')} m3/m2",
        f"  CO2 emissions    {table_value(data, 'tablePerformance', 'CO2 emissie')} kg/m2",
        "Peaks (duration curves)",
        f"  Heat             {max(heat_dur[1]) if heat_dur else float('nan'):.1f} W/m2",
        f"  Electricity      {max(elec_dur[1]) if elec_dur else float('nan'):.1f} W/m2",
        f"  CO2              {max(co2_dur[1]) if co2_dur else float('nan'):.1f} kg/ha/h (unit assumed)",
    ]
    if A:
        lines += [
            f"Scaled to {A:,.0f} m2",
            f"  Heat             {heat_tot*A/3.6e6:8.2f} GWh/yr, peak {max(heat_d[1]):.2f} MW",
            f"  Electricity      {elec_tot*A/1e6:8.2f} GWh/yr, peak {max(elec_d[1]):.2f} MW",
            f"  CO2              {co2_tot*A/1000:8.1f} t/yr",
        ]
    if heat_tab and abs(heat_tot - heat_tab) / heat_tab > 0.02:
        lines.append("Note: heat use differs from heat production by more than 2% "
                     "(storage losses or heat dumped). Use heat USE as greenhouse demand.")
    text = "\n".join(lines)
    (out / "summary.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"\nFiles written to {out.resolve()}")


if __name__ == "__main__":
    main()