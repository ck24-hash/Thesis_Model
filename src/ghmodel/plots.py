"""Plots for all scenarios. Every function takes the Results object (or the input data / an analysis table) and
optionally an out_dir to save a PNG. Components that are not in the scenario (e.g. no CHP in the baseline) are
simply left out of the figures."""
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

COL = dict(heat="#D9480F", heat_light="#F4A582", elec="#1C6BC4", co2="#2F9E44", fuel="#7048E8",
           dump="#868E96", store="#F59F00", dark="#343A40", chp="#C2255C", export="#74C0FC")


def apply_style(dpi=150):
    plt.rcParams.update({
        "figure.dpi": 100, "savefig.dpi": dpi, "font.size": 10,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.labelsize": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.alpha": 0.25, "legend.frameon": False,
    })


apply_style()


def save_fig(fig, name, out_dir=None):
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_dir / f"{name}.png", bbox_inches="tight")


def roll7(s):
    """7-day rolling mean for readable yearly plots."""
    return s.rolling(24 * 7, center=True, min_periods=24).mean()


def _heat_sources(res):
    """(column, label, colour) of the heat sources present in the scenario, stacked in this order."""
    src = []
    if res.k["has_chp"]:
        src.append(("chp_heat", "CHP heat", COL["chp"]))
    src.append(("boiler_heat", "Boiler heat", COL["heat"]))
    return src


def plot_all(data, res, out_dir=None):
    plot_inputs(data, out_dir)
    for f in (plot_heat_yearly, plot_zoom_weeks, plot_storage, plot_co2, plot_fuel_grid_cost,
              plot_duration, plot_heatmaps, plot_cost_and_heat_fate):
        f(res, out_dir=out_dir)


def plot_inputs(data, out_dir=None):
    """Stacked panels: all input series, hourly (thin) and 7-day mean (thick)."""
    panels = [
        ("heat_demand_MW",     "Heat demand [MW]",           COL["heat"]),
        ("elec_demand_MW",     "Electricity demand [MW]",    COL["elec"]),
        ("co2_demand_t_h",     "CO2 demand [t/h]",           COL["co2"]),
        ("gas_price_EUR_MWh",  "Gas price [EUR/MWh]",        COL["fuel"]),
        ("elec_price_EUR_MWh", "Grid price [EUR/MWh]",       COL["elec"]),
    ]
    if "elec_export_price_EUR_MWh" in data:
        panels.append(("elec_export_price_EUR_MWh", "Export price [EUR/MWh]", COL["export"]))
    fig, axes = plt.subplots(len(panels), 1, figsize=(12, 2 * len(panels)), sharex=True)
    for ax, (c, label, color) in zip(axes, panels):
        ax.plot(data.index, data[c], color=color, lw=0.4, alpha=0.35)
        ax.plot(data.index, roll7(data[c]), color=color, lw=1.6, label="7-day mean")
        ax.set_ylabel(label)
    axes[0].legend(loc="upper right")
    axes[0].set_title("Input data: one year, hourly (thin) and 7-day mean (thick)")
    fig.tight_layout()
    save_fig(fig, "01_inputs", out_dir)
    plt.show()


def plot_heat_yearly(res, out_dir=None):
    """Daily mean heat bus balance and monthly heat totals."""
    r, monthly = res.r, res.monthly
    daily = r.resample("D").mean()
    x = daily.index
    src = _heat_sources(res)

    fig, axes = plt.subplots(2, 1, figsize=(12, 8.5), gridspec_kw={"height_ratios": [2, 1.2]})

    ax = axes[0]
    ax.stackplot(x, *[daily[c] for c, _, _ in src], daily.tes_discharge, daily.heat_unserved,
                 colors=[c for _, _, c in src] + [COL["store"], "black"],
                 labels=[lab for _, lab, _ in src] + ["Storage discharge", "Unserved heat"])
    ax.stackplot(x, -daily.tes_charge, -daily.heat_dump,
                 colors=[COL["heat_light"], COL["dump"]], labels=["Storage charge", "Heat dumped"])
    ax.plot(x, daily.heat_demand, color=COL["dark"], lw=1.2, label="Greenhouse heat demand")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_ylabel("Daily mean power [MW]")
    ax.set_title("Heat bus balance, daily mean")
    ax.legend(ncol=3, loc="upper right", fontsize=8)

    ax = axes[1]
    bars = [("heat_demand", "Heat demand", COL["dark"])] + src + [("heat_dump", "Heat dumped", COL["dump"])]
    pos = np.arange(len(monthly)); w = 0.8 / len(bars)
    for i, (c, lab, color) in enumerate(bars):
        ax.bar(pos + (i - (len(bars) - 1) / 2) * w, monthly[c], w, color=color, label=lab)
    ax.set_xticks(pos); ax.set_xticklabels(monthly.index)
    ax.set_ylabel("Monthly heat [MWh]")
    ax.set_title("Monthly heat totals")
    ax.legend(ncol=len(bars))

    fig.tight_layout()
    save_fig(fig, "02_heat_yearly", out_dir)
    plt.show()


def plot_zoom_weeks(res, zoom_winter_start=None, zoom_summer_start=None, zoom_storage_start=None, out_dir=None):
    """Three hourly weeks: coldest, lowest heat demand, highest storage use (start dates can be fixed)."""
    r, tes_cap = res.r, res.k["tes_cap_final"]
    src = _heat_sources(res)

    def week_start(manual, series, pick):
        # start of the 168 h window chosen by `pick` ('max' or 'min') of the rolling weekly sum
        if manual:
            return pd.Timestamp(manual)
        weekly = series.rolling(168).sum().dropna()
        end = weekly.idxmax() if pick == "max" else weekly.idxmin()
        return end - pd.Timedelta(hours=167)

    weeks = {
        "Coldest week":             week_start(zoom_winter_start,  r.heat_demand,   "max"),
        "Lowest heat demand week":  week_start(zoom_summer_start,  r.heat_demand,   "min"),
        "Highest storage use week": week_start(zoom_storage_start, r.tes_discharge, "max"),
    }

    fig, axes = plt.subplots(5, 3, figsize=(17, 13.5), sharex="col", sharey="row")
    for j, (title, t0) in enumerate(weeks.items()):
        s = r.loc[t0: t0 + pd.Timedelta(hours=167)]
        xx = s.index

        ax = axes[0, j]                                            # heat
        ax.stackplot(xx, *[s[c] for c, _, _ in src], s.tes_discharge, s.heat_unserved,
                     colors=[c for _, _, c in src] + [COL["store"], "black"])
        ax.stackplot(xx, -s.tes_charge, -s.heat_dump, colors=[COL["heat_light"], COL["dump"]])
        ax.plot(xx, s.heat_demand, color=COL["dark"], lw=1.3)
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(f"{title} (from {t0:%d %b %Y})")
        if j == 0: ax.set_ylabel("Heat [MW]")

        ax = axes[1, j]                                            # storage
        soc_pct = 100 * s.tes_soc / tes_cap if tes_cap else s.tes_soc * 0
        ax.fill_between(xx, soc_pct, color=COL["store"], alpha=0.35)
        ax.plot(xx, soc_pct, color=COL["store"], lw=1.3)
        ax.set_ylim(0, 105)
        if j == 0: ax.set_ylabel("Storage SoC [%]")

        ax = axes[2, j]                                            # electricity
        ax.stackplot(xx, s.chp_elec, s.grid_import, colors=[COL["chp"], COL["elec"]])
        ax.stackplot(xx, -s.grid_export, colors=[COL["export"]])
        ax.plot(xx, s.elec_demand, color=COL["dark"], lw=1.1)
        ax.axhline(0, color="k", lw=0.5)
        if j == 0: ax.set_ylabel("Electricity [MW]")

        ax = axes[3, j]                                            # CO2
        delivered = s.co2_demand - s.co2_unserved
        ax.stackplot(xx, delivered * 1e3, s.co2_vent * 1e3, colors=[COL["co2"], COL["dump"]], alpha=0.85)
        ax.plot(xx, s.co2_demand * 1e3, color=COL["dark"], lw=1.1, ls="--")
        if j == 0: ax.set_ylabel("CO2 [kg/h]")

        ax = axes[4, j]                                            # prices
        ax.plot(xx, s.gas_price, color=COL["fuel"], lw=1.3)
        ax.plot(xx, s.elec_price, color=COL["elec"], lw=1.3)
        if res.k["has_export"]:
            ax.plot(xx, s.export_price, color=COL["export"], lw=1.3)
        if j == 0: ax.set_ylabel("Price [EUR/MWh]")
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))

    rect = lambda c: plt.Rectangle((0, 0), 1, 1, color=c)
    axes[0, 0].legend([rect(c) for _, _, c in src] + [rect(COL["store"]), rect(COL["heat_light"]), rect(COL["dump"])],
                      [lab for _, lab, _ in src] + ["Storage discharge", "Storage charge", "Heat dumped"],
                      ncol=2, fontsize=8, loc="lower left")
    axes[2, 0].legend([rect(COL["chp"]), rect(COL["elec"]), rect(COL["export"]), plt.Line2D([], [], color=COL["dark"])],
                      ["CHP", "Grid import", "Grid export", "Demand"], ncol=2, fontsize=8, loc="lower left")
    axes[3, 0].legend([rect(COL["co2"]), rect(COL["dump"]), plt.Line2D([], [], color=COL["dark"], ls="--")],
                      ["Delivered to greenhouse", "Vented", "CO2 demand"], ncol=1, fontsize=8, loc="upper left")
    price_lines = [plt.Line2D([], [], color=COL["fuel"]), plt.Line2D([], [], color=COL["elec"])]
    price_labels = ["Gas", "Grid import"]
    if res.k["has_export"]:
        price_lines.append(plt.Line2D([], [], color=COL["export"])); price_labels.append("Grid export")
    axes[4, 0].legend(price_lines, price_labels, ncol=3, fontsize=8, loc="upper left")

    fig.tight_layout()
    save_fig(fig, "03_zoom_weeks", out_dir)
    plt.show()


def plot_storage(res, out_dir=None):
    """Storage state of charge over the year and monthly discharge."""
    r, monthly = res.r, res.monthly
    tes_cap, tes_out = res.k["tes_cap_final"], res.k["tes_out"]
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [1.6, 1]})

    ax = axes[0]
    soc_pct = 100 * r.tes_soc / tes_cap if tes_cap else r.tes_soc * 0
    ax.plot(r.index, soc_pct, color=COL["store"], lw=0.4, alpha=0.5)
    ax.plot(r.index, soc_pct.rolling(24, center=True, min_periods=1).mean(), color=COL["store"], lw=1.5, label="24 h mean")
    ax.set_ylim(0, 105); ax.set_ylabel("State of charge [%]")
    ax.set_title(f"Thermal storage state of charge ({tes_cap:,.1f} MWh capacity)")
    ax.legend(loc="lower right")

    ax = axes[1]
    ax.bar(np.arange(len(monthly)), monthly.tes_discharge, color=COL["store"])
    ax.set_xticks(np.arange(len(monthly))); ax.set_xticklabels(monthly.index)
    ax.set_ylabel("Discharged [MWh/month]")
    ax.set_title(f"Monthly energy delivered by the storage ({tes_out / tes_cap:,.0f} equivalent full cycles per year)"
                 if tes_cap else "Monthly energy delivered by the storage")

    fig.tight_layout()
    save_fig(fig, "04_storage", out_dir)
    plt.show()


def plot_co2(res, out_dir=None):
    """Monthly CO2 supply / demand / vent and share of the produced heat that is rejected."""
    monthly = res.monthly
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))
    pos = np.arange(len(monthly)); w = 0.27

    ax = axes[0]
    ax.bar(pos - w, monthly.co2_demand, w, color=COL["dark"], label="CO2 demand")
    if res.k["has_chp"]:
        ax.bar(pos, monthly.chp_co2, w, color=COL["chp"], label="CO2 from CHP")
        ax.bar(pos, monthly.boiler_co2, w, bottom=monthly.chp_co2, color=COL["co2"], label="CO2 from boiler")
    else:
        ax.bar(pos, monthly.boiler_co2, w, color=COL["co2"], label="CO2 from boiler")
    ax.bar(pos + w, monthly.co2_vent, w, color=COL["dump"], label="CO2 vented")
    ax.set_xticks(pos); ax.set_xticklabels(monthly.index)
    ax.set_ylabel("CO2 [t/month]"); ax.set_title("Monthly CO2 balance"); ax.legend()

    ax = axes[1]
    produced = (monthly.boiler_heat + monthly.chp_heat).replace(0, np.nan)
    ax.bar(pos, (100 * monthly.heat_dump / produced).fillna(0), color=COL["heat"])
    ax.set_xticks(pos); ax.set_xticklabels(monthly.index)
    ax.set_ylabel("Heat dumped / heat produced [%]"); ax.set_ylim(0, 100)
    ax.set_title("Share of produced heat that is rejected")

    fig.tight_layout()
    save_fig(fig, "05_co2", out_dir)
    plt.show()


def plot_fuel_grid_cost(res, out_dir=None):
    """Monthly gas use per unit, grid import/export and operating cost (export revenue as negative bar)."""
    monthly = res.monthly
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    pos = np.arange(len(monthly))

    axes[0].bar(pos, monthly.boiler_gas, color=COL["heat"], label="Boiler")
    if res.k["has_chp"]:
        axes[0].bar(pos, monthly.chp_gas, bottom=monthly.boiler_gas, color=COL["chp"], label="CHP")
        axes[0].legend()
    axes[0].set_title("Gas consumption"); axes[0].set_ylabel("[MWh/month]")

    axes[1].bar(pos, monthly.grid_import, color=COL["elec"], label="Import")
    if res.k["has_export"]:
        axes[1].bar(pos, -monthly.grid_export, color=COL["export"], label="Export")
        axes[1].axhline(0, color="k", lw=0.5); axes[1].legend()
    axes[1].set_title("Grid electricity"); axes[1].set_ylabel("[MWh/month]")

    bottom = np.zeros(len(monthly))
    for c, label, color in [("gas_cost_EUR", "Gas", COL["fuel"]), ("co2_levy_EUR", "CO2 levy", COL["dump"]),
                            ("elec_cost_EUR", "Electricity", COL["elec"]), ("chp_vom_EUR", "CHP variable O&M", COL["chp"]),
                            ("sink_cost_EUR", "Heat dump + CO2 vent", COL["co2"])]:
        if not monthly[c].any():
            continue
        axes[2].bar(pos, monthly[c] / 1e3, bottom=bottom, color=color, label=label)
        bottom += monthly[c].to_numpy() / 1e3
    if monthly.export_revenue_EUR.any():
        axes[2].bar(pos, -monthly.export_revenue_EUR / 1e3, color=COL["export"], label="Export revenue")
        net = bottom - monthly.export_revenue_EUR.to_numpy() / 1e3
        axes[2].plot(pos, net, "o-", color=COL["dark"], ms=3, lw=1, label="Net")
        axes[2].axhline(0, color="k", lw=0.5)
    axes[2].set_title("Operating cost"); axes[2].set_ylabel("[kEUR/month]"); axes[2].legend(fontsize=8)

    for ax in axes:
        ax.set_xticks(pos); ax.set_xticklabels(monthly.index, rotation=45)
    fig.tight_layout()
    save_fig(fig, "06_fuel_grid_cost", out_dir)
    plt.show()


def plot_duration(res, out_dir=None):
    """Heat and electricity duration curves."""
    r, k = res.r, res.k
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    hours = np.arange(1, len(r) + 1)
    sorted_ = lambda c: r[c].sort_values(ascending=False).to_numpy()

    ax = axes[0]
    curves = [("heat_demand", "Heat demand", COL["dark"], "-")]
    if k["has_chp"]:
        curves.append(("chp_heat", "CHP heat", COL["chp"], "-"))
    curves += [("boiler_heat", "Boiler output", COL["heat"], "-"), ("heat_dump", "Heat dumped", COL["dump"], "--")]
    for c, label, color, ls in curves:
        ax.plot(hours, sorted_(c), label=label, color=color, ls=ls, lw=1.6)
    ax.axhline(k["boiler_cap_final"], color=COL["heat"], lw=0.8, ls=":")
    ax.text(len(r) * 0.98, k["boiler_cap_final"], " boiler capacity", ha="right", va="bottom", fontsize=8, color=COL["heat"])
    if k["has_chp"]:
        ax.axhline(k["chp_cap_th"], color=COL["chp"], lw=0.8, ls=":")
        ax.text(len(r) * 0.98, k["chp_cap_th"], " CHP thermal capacity", ha="right", va="bottom", fontsize=8, color=COL["chp"])
    ax.set_xlabel("Hours of the year (sorted)"); ax.set_ylabel("Heat [MW]")
    ax.set_title("Heat duration curves"); ax.legend()

    ax = axes[1]
    ax.plot(hours, sorted_("elec_demand"), color=COL["dark"], lw=1.6, label="Electricity demand")
    ax.plot(hours, sorted_("grid_import"), color=COL["elec"], lw=1.4, ls="--", label="Grid import")
    if k["has_chp"]:
        ax.plot(hours, sorted_("chp_elec"), color=COL["chp"], lw=1.4, label="CHP output")
    if k["has_export"]:
        ax.plot(hours, sorted_("grid_export"), color=COL["export"], lw=1.4, label="Grid export")
    ax.set_xlabel("Hours of the year (sorted)"); ax.set_ylabel("Electricity [MW]")
    ax.set_title("Electricity duration curves"); ax.legend()

    fig.tight_layout()
    save_fig(fig, "07_duration_curves", out_dir)
    plt.show()


def plot_heatmaps(res, out_dir=None):
    """Day-of-year x hour-of-day heatmaps."""
    r = res.r

    def to_heatmap(s):
        return s.groupby([s.index.dayofyear, s.index.hour]).sum().unstack(0)      # rows: hour, columns: day

    maps = [("Heat demand [MW]", to_heatmap(r.heat_demand), "Oranges")]
    if res.k["has_chp"]:
        maps.append(("CHP heat output [MW]", to_heatmap(r.chp_heat), "RdPu"))
    maps += [("Boiler heat output [MW]", to_heatmap(r.boiler_heat), "Reds"),
             ("Heat dumped [MW]",        to_heatmap(r.heat_dump),   "Greys"),
             ("CO2 demand [kg/h]",       to_heatmap(r.co2_demand) * 1e3, "Greens")]
    if res.k["has_export"]:
        maps.append(("Grid export [MW]", to_heatmap(r.grid_export), "Blues"))
    ncols = 2 if len(maps) <= 4 else 3
    nrows = int(np.ceil(len(maps) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(7 * ncols, 3.75 * nrows), sharex=True, sharey=True, squeeze=False)
    for ax, (title, hm, cmap) in zip(axes.flat, maps):
        im = ax.imshow(hm.to_numpy(), aspect="auto", origin="lower", cmap=cmap, interpolation="nearest",
                       extent=[hm.columns.min(), hm.columns.max(), 0, 24])
        ax.set_title(title); ax.grid(False)
        fig.colorbar(im, ax=ax, pad=0.01)
    for ax in axes.flat[len(maps):]:
        ax.set_visible(False)
    for ax in axes[-1, :]: ax.set_xlabel("Day of year")
    for ax in axes[:, 0]: ax.set_ylabel("Hour of day")
    fig.tight_layout()
    save_fig(fig, "08_heatmaps", out_dir)
    plt.show()


def plot_cost_and_heat_fate(res, out_dir=None):
    """Annual cost breakdown (export revenue as negative bar) and what happens to the produced heat."""
    k = res.k
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8))

    ax = axes[0]
    items = [("Gas", k["gas_cost"], COL["fuel"]), ("CO2 levy", k["levy_cost"], COL["dump"]),
             ("Electricity purchase", k["elec_cost"], COL["elec"]), ("CHP variable O&M", k["chp_vom"], COL["chp"]),
             ("Heat dump + CO2 vent", k["sink_cost"], COL["co2"]),
             ("Boiler (annualised capex + O&M)", k["capex_boiler"], COL["heat"]),
             ("Storage (annualised capex + O&M)", k["capex_tes"], COL["store"]),
             ("CHP (annualised capex + O&M)", k["capex_chp"], COL["chp"]),
             ("Electricity export revenue", -k["export_rev"], COL["export"])]
    items = [i for i in items if abs(i[1]) > 0]
    labels = [i[0] for i in items]; vals = [i[1] / 1e3 for i in items]; cols = [i[2] for i in items]
    bars = ax.barh(labels[::-1], vals[::-1], color=cols[::-1])
    for b, v in zip(bars, vals[::-1]):
        ax.text(v, b.get_y() + b.get_height() / 2, f" {v:,.1f} ", va="center", ha="left" if v >= 0 else "right", fontsize=9)
    lo = min(0, min(vals)) * 1.3
    ax.set_xlabel("[kEUR/year]"); ax.set_xlim(lo, max(vals) * 1.2)
    ax.axvline(0, color="k", lw=0.5)
    ax.set_title(f"Total annualised cost: {k['total_cost'] / 1e3:,.1f} kEUR/y  (OPEX {k['opex'] / 1e3:,.1f})")

    ax = axes[1]
    parts = [("Direct to greenhouse", k["direct"], COL["heat"]),
             ("Delivered via storage", k["tes_out"], COL["store"]),
             ("Storage losses", k["tes_in"] - k["tes_out"], COL["heat_light"]),
             ("Dumped", k["dump"], COL["dump"])]
    bars = ax.bar([p[0] for p in parts], [p[1] for p in parts], color=[p[2] for p in parts])
    for b, p in zip(bars, parts):
        share = 100 * p[1] / k["heat_prod"] if k["heat_prod"] else 0
        ax.text(b.get_x() + b.get_width() / 2, p[1], f"{p[1]:,.0f}\n({share:.0f}%)", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("[MWh/year]"); ax.set_ylim(0, max(p[1] for p in parts) * 1.2)
    who = "CHP + boiler" if k["has_chp"] else "boiler"
    ax.set_title(f"Where the {k['heat_prod']:,.0f} MWh of {who} heat goes")
    ax.tick_params(axis="x", labelrotation=15)

    fig.tight_layout()
    save_fig(fig, "09_cost_and_heat_fate", out_dir)
    plt.show()


def plot_storage_savings(table, indicators, out_dir=None):
    """Savings thanks to the storage (output of analysis.storage_value): cost items and physical changes."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8), gridspec_kw={"width_ratios": [1.6, 1]})

    ax = axes[0]   # positive = saved by the storage, negative = extra cost (e.g. storage capex)
    items = [("Gas", "Gas cost", COL["fuel"]), ("CO2 levy", "CO2 levy on gas", COL["dump"]),
             ("Electricity purchase", "Electricity purchase", COL["elec"]),
             ("Export revenue", "Electricity export (- revenue)", COL["export"]),
             ("CHP variable O&M", "CHP variable O&M", COL["chp"]),
             ("Heat dump + CO2 vent", "Heat dump + CO2 vent cost", COL["co2"]),
             ("Boiler capex + O&M", "Annualised capex + O&M: boiler", COL["heat"]),
             ("CHP capex + O&M", "Annualised capex + O&M: CHP", COL["chp"]),
             ("Storage capex + O&M", "Annualised capex + O&M: storage", COL["store"])]
    items = [(lab, table.at[row, "Saved by storage"] / 1e3, c) for lab, row, c in items
             if abs(table.at[row, "Saved by storage"]) > 1e-6]
    net = table.at["Total annualised cost", "Saved by storage"] / 1e3
    items.append(("NET SAVING", net, COL["dark"]))
    labels = [i[0] for i in items]; vals = [i[1] for i in items]
    bars = ax.barh(labels[::-1], vals[::-1], color=[i[2] for i in items][::-1])
    for b, v in zip(bars, vals[::-1]):
        ax.text(v, b.get_y() + b.get_height() / 2, f" {v:,.1f} ", va="center", ha="left" if v >= 0 else "right", fontsize=9)
    ax.axvline(0, color=COL["dark"], lw=0.8)
    lim = max(abs(v) for v in vals) * 1.3
    ax.set_xlim(-lim, lim); ax.set_xlabel("[kEUR/year]  (positive = saved by the storage)")
    payback = indicators.at["Simple payback (no discounting)", "Value"]
    ax.set_title(f"Yearly savings thanks to the storage: net {net:,.1f} kEUR/y, "
                 f"simple payback {payback:,.1f} y" if np.isfinite(payback) else "Yearly savings thanks to the storage")

    ax = axes[1]
    phys = [("Gas saved\n[MWh/y]", table.at["Gas consumption", "Saved by storage"], COL["fuel"]),
            ("Heat dump avoided\n[MWh/y]", table.at["Heat dumped", "Saved by storage"], COL["dump"]),
            ("CO2 avoided\n[t/y]", table.at["Direct CO2 (gas)", "Saved by storage"], COL["co2"])]
    bars = ax.bar([p[0] for p in phys], [p[1] for p in phys], color=[p[2] for p in phys])
    for b, p in zip(bars, phys):
        ax.text(b.get_x() + b.get_width() / 2, p[1], f"{p[1]:,.0f}", ha="center",
                va="bottom" if p[1] >= 0 else "top", fontsize=9)
    ax.axhline(0, color=COL["dark"], lw=0.8)
    ax.set_title("Physical effect of the storage")

    fig.tight_layout()
    save_fig(fig, "10_storage_savings", out_dir)
    plt.show()


def plot_financials(fin, out_dir=None):
    """Cumulative cash flow against the reference (with payback) and NPV sensitivity (tornado)."""
    cf, sens = fin["cash_flows"], fin["sensitivity"]
    ind = fin["indicators"].Value
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.8), gridspec_kw={"width_ratios": [1.5, 1]})

    ax = axes[0]
    ax.bar(cf.index, cf["Net cash flow"] / 1e3, color=COL["dump"], alpha=0.6, label="Net cash flow of the year")
    ax.plot(cf.index, cf["Cumulative"] / 1e3, "o-", color=COL["elec"], ms=3, label="Cumulative")
    ax.plot(cf.index, cf["Cumulative discounted"] / 1e3, "o-", color=COL["dark"], ms=3, label="Cumulative discounted")
    ax.axhline(0, color="k", lw=0.6)
    pb = ind["Discounted payback"]
    if np.isfinite(pb):
        ax.axvline(pb, color=COL["co2"], ls="--", lw=1)
        ax.text(pb, ax.get_ylim()[1] * 0.9, f" discounted payback {pb:.1f} y", color=COL["co2"], fontsize=9)
    irr_txt = f"{fin['irr'] * 100:.1f} %" if np.isfinite(fin["irr"]) else "n/a"
    ax.set_title(f"{fin['name']} vs {fin['ref_name']}: NPV {fin['npv'] / 1e3:,.0f} kEUR, IRR {irr_txt}")
    ax.set_xlabel("Year"); ax.set_ylabel("[kEUR]"); ax.legend(fontsize=8)

    ax = axes[1]
    lo, hi = sens.columns
    order = (sens[hi] - sens[lo]).abs().sort_values().index
    base = fin["npv"] / 1e3
    for i, p in enumerate(order):
        a, b = sens.at[p, lo] / 1e3 - base, sens.at[p, hi] / 1e3 - base
        ax.barh(i, a, left=base, color=COL["heat_light"]); ax.barh(i, b, left=base, color=COL["elec"])
    ax.set_yticks(range(len(order))); ax.set_yticklabels(order)
    ax.axvline(base, color="k", lw=0.8)
    ax.set_xlabel("NPV [kEUR]")
    ax.set_title(f"NPV sensitivity to ±{hi.split()[-2].lstrip('+')} % (first order)")
    ax.legend([plt.Rectangle((0, 0), 1, 1, color=COL["heat_light"]), plt.Rectangle((0, 0), 1, 1, color=COL["elec"])],
              [lo, hi], fontsize=8, loc="lower right")

    fig.tight_layout()
    save_fig(fig, "11_financials", out_dir)
    plt.show()
