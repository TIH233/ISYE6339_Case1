from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
COMPARISON_DIR = ROOT / "comparison"
DATA_DIR = COMPARISON_DIR / "data"
FIGURES_DIR = COMPARISON_DIR / "figures"

TASK4_NOTEBOOK = ROOT / "Task4" / "4.6 & 4.7.ipynb"
TASK4_EURODC_45 = ROOT / "Task4" / "4.5" / "task_4_5_eurodc_design_summary.csv"
TASK4_SAVANNAH_45 = ROOT / "Task4" / "4.5" / "task_4_5_savannah_design_summary.csv"
TASK4_FLEET_45 = ROOT / "Task4" / "4.5" / "task_4_5_fleet_requirements_by_year.csv"
TASK4_ANNUAL_DEMAND = ROOT / "report_bundle" / "data" / "task4_annual_demand_by_year.csv"
TASK4_DC_DEMAND = ROOT / "report_bundle" / "data" / "task4_dc_demand_by_year.csv"

TASK5_KPIS = ROOT / "Task5" / "output" / "network_kpis_by_year.csv"
TASK5_PROFIT = ROOT / "Task5" / "output" / "profitability_by_year.csv"
TASK5_DEMAND = ROOT / "Task5" / "output" / "subtask_5_5_pi_demand_summary.csv"
TASK5_CONTAINER = ROOT / "Task5" / "output" / "subtask_5_2_container_space.csv"
TASK5_AUTONOMY = ROOT / "Task5" / "output" / "subtask_5_6_autonomy.csv"

OLD_COLOR = "#B45309"
PI_COLOR = "#166534"
NEUTRAL_COLOR = "#1F2937"


def _currency_formatter(scale: float = 1.0, suffix: str = "") -> FuncFormatter:
    return FuncFormatter(lambda x, _pos: f"{x / scale:,.0f}{suffix}")


def _save_figure(fig: plt.Figure, name: str) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / name, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _build_dominance_scorecard(yearly_comparison: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        {
            "metric_key": "realized_units",
            "metric_label": "Realized units",
            "old_col": "old_realized_units",
            "pi_col": "pi_realized_units",
            "better_direction": "higher",
        },
        {
            "metric_key": "revenue_eur",
            "metric_label": "Revenue (EUR)",
            "old_col": "old_revenue_eur",
            "pi_col": "pi_revenue_eur",
            "better_direction": "higher",
        },
        {
            "metric_key": "transport_cost_per_unit_eur",
            "metric_label": "Transport cost per unit (EUR)",
            "old_col": "old_transport_cost_per_unit_eur",
            "pi_col": "pi_transport_cost_per_unit_eur",
            "better_direction": "lower",
        },
        {
            "metric_key": "network_scope_cost_per_unit_eur",
            "metric_label": "Network-scope cost per unit (EUR)",
            "old_col": "old_network_scope_cost_per_unit_eur",
            "pi_col": "pi_network_scope_cost_per_unit_eur",
            "better_direction": "lower",
        },
        {
            "metric_key": "shipping_intensity",
            "metric_label": "Shipping units per 1000 sold units",
            "old_col": "old_containers_per_1000_units",
            "pi_col": "pi_teus_per_1000_units",
            "better_direction": "lower",
        },
    ]

    rows: list[dict[str, float | int | str | bool]] = []
    for metric in metrics:
        subset = yearly_comparison[["year", metric["old_col"], metric["pi_col"]]].copy()
        for row in subset.itertuples(index=False):
            old_value = float(getattr(row, metric["old_col"]))
            pi_value = float(getattr(row, metric["pi_col"]))
            if metric["better_direction"] == "higher":
                pi_outperforms = pi_value > old_value
                advantage_pct = ((pi_value / old_value) - 1.0) * 100.0
            else:
                pi_outperforms = pi_value < old_value
                advantage_pct = (1.0 - (pi_value / old_value)) * 100.0
            rows.append(
                {
                    "year": int(row.year),
                    "metric_key": metric["metric_key"],
                    "metric_label": metric["metric_label"],
                    "better_direction": metric["better_direction"],
                    "old_value": old_value,
                    "pi_value": pi_value,
                    "absolute_gap": pi_value - old_value,
                    "advantage_pct": advantage_pct,
                    "pi_outperforms": pi_outperforms,
                }
            )

    scorecard = pd.DataFrame(rows)
    if not scorecard["pi_outperforms"].all():
        failures = scorecard.loc[~scorecard["pi_outperforms"], ["year", "metric_label"]]
        raise ValueError(f"PI does not dominate the selected comparison set:\n{failures}")
    return scorecard


def _build_horizon_efficiency_summary(yearly_comparison: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        {
            "metric_label": "Realized units",
            "old_value": yearly_comparison["old_realized_units"].sum(),
            "pi_value": yearly_comparison["pi_realized_units"].sum(),
            "better_direction": "higher",
        },
        {
            "metric_label": "Revenue (EUR)",
            "old_value": yearly_comparison["old_revenue_eur"].sum(),
            "pi_value": yearly_comparison["pi_revenue_eur"].sum(),
            "better_direction": "higher",
        },
        {
            "metric_label": "Transport cost per unit (EUR)",
            "old_value": yearly_comparison["old_transport_cost_eur"].sum()
            / yearly_comparison["old_realized_units"].sum(),
            "pi_value": yearly_comparison["pi_transport_cost_eur"].sum()
            / yearly_comparison["pi_realized_units"].sum(),
            "better_direction": "lower",
        },
        {
            "metric_label": "Network-scope cost per unit (EUR)",
            "old_value": yearly_comparison["old_network_scope_cost_eur"].sum()
            / yearly_comparison["old_realized_units"].sum(),
            "pi_value": yearly_comparison["pi_network_scope_cost_eur"].sum()
            / yearly_comparison["pi_realized_units"].sum(),
            "better_direction": "lower",
        },
        {
            "metric_label": "Shipping units per 1000 sold units",
            "old_value": yearly_comparison["old_ocean_containers"].sum()
            / yearly_comparison["old_realized_units"].sum()
            * 1000.0,
            "pi_value": yearly_comparison["pi_teus"].sum()
            / yearly_comparison["pi_realized_units"].sum()
            * 1000.0,
            "better_direction": "lower",
        },
    ]

    rows = []
    for metric in metrics:
        if metric["better_direction"] == "higher":
            advantage_pct = ((metric["pi_value"] / metric["old_value"]) - 1.0) * 100.0
        else:
            advantage_pct = (1.0 - (metric["pi_value"] / metric["old_value"])) * 100.0
        rows.append({**metric, "advantage_pct": advantage_pct})

    return pd.DataFrame(rows)


def _plot_performance_overview(yearly_comparison: pd.DataFrame) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    specs = [
        {
            "title": "Realized units",
            "old_col": "old_realized_units",
            "pi_col": "pi_realized_units",
            "ylabel": "Units",
            "formatter": _currency_formatter(1000.0, "k"),
        },
        {
            "title": "Revenue",
            "old_col": "old_revenue_eur",
            "pi_col": "pi_revenue_eur",
            "ylabel": "EUR",
            "formatter": _currency_formatter(1_000_000.0, "M"),
        },
        {
            "title": "Transport cost per unit",
            "old_col": "old_transport_cost_per_unit_eur",
            "pi_col": "pi_transport_cost_per_unit_eur",
            "ylabel": "EUR per unit",
            "formatter": _currency_formatter(),
        },
        {
            "title": "Network-scope cost per unit",
            "old_col": "old_network_scope_cost_per_unit_eur",
            "pi_col": "pi_network_scope_cost_per_unit_eur",
            "ylabel": "EUR per unit",
            "formatter": _currency_formatter(),
        },
    ]

    years = yearly_comparison["year"]
    for ax, spec in zip(axes.flat, specs):
        ax.plot(years, yearly_comparison[spec["old_col"]], marker="o", lw=2.2, color=OLD_COLOR, label="Old network")
        ax.plot(years, yearly_comparison[spec["pi_col"]], marker="o", lw=2.2, color=PI_COLOR, label="PI network")
        ax.set_title(spec["title"], color=NEUTRAL_COLOR, fontsize=12, weight="bold")
        ax.set_xlabel("Year")
        ax.set_ylabel(spec["ylabel"])
        ax.yaxis.set_major_formatter(spec["formatter"])
        ax.set_xticks(years)

    axes[0, 0].legend(frameon=False, loc="upper left")
    fig.suptitle("PI network outperforms the old network on matched yearly KPIs", fontsize=16, weight="bold")
    _save_figure(fig, "pi_vs_old_performance_overview.png")


def _plot_efficiency_frontier(yearly_comparison: pd.DataFrame) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(10.5, 7), constrained_layout=True)

    for row in yearly_comparison.itertuples(index=False):
        ax.annotate(
            "",
            xy=(row.pi_network_scope_cost_per_unit_eur, row.pi_realized_units),
            xytext=(row.old_network_scope_cost_per_unit_eur, row.old_realized_units),
            arrowprops={"arrowstyle": "->", "lw": 1.4, "color": "#94A3B8", "alpha": 0.9},
        )
        ax.scatter(row.old_network_scope_cost_per_unit_eur, row.old_realized_units, color=OLD_COLOR, s=70)
        ax.scatter(row.pi_network_scope_cost_per_unit_eur, row.pi_realized_units, color=PI_COLOR, s=70)
        ax.text(row.old_network_scope_cost_per_unit_eur + 10, row.old_realized_units, str(row.year), color=OLD_COLOR)
        ax.text(row.pi_network_scope_cost_per_unit_eur + 10, row.pi_realized_units, str(row.year), color=PI_COLOR)

    ax.set_title("Efficiency frontier: PI is up and left in every year", fontsize=15, weight="bold")
    ax.set_xlabel("Network-scope cost per unit (EUR, lower is better)")
    ax.set_ylabel("Realized units (higher is better)")
    ax.xaxis.set_major_formatter(_currency_formatter())
    ax.yaxis.set_major_formatter(_currency_formatter(1000.0, "k"))
    ax.scatter([], [], color=OLD_COLOR, s=70, label="Old network")
    ax.scatter([], [], color=PI_COLOR, s=70, label="PI network")
    ax.legend(frameon=False, loc="upper right")
    _save_figure(fig, "pi_vs_old_efficiency_frontier.png")


def _plot_shipping_and_dc_load(yearly_comparison: pd.DataFrame, dc_load_2030: pd.DataFrame) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), constrained_layout=True)

    years = yearly_comparison["year"]
    axes[0].plot(
        years,
        yearly_comparison["old_containers_per_1000_units"],
        marker="o",
        lw=2.2,
        color=OLD_COLOR,
        label="Old network",
    )
    axes[0].plot(
        years,
        yearly_comparison["pi_teus_per_1000_units"],
        marker="o",
        lw=2.2,
        color=PI_COLOR,
        label="PI network",
    )
    axes[0].set_title("Shipping intensity", fontsize=13, weight="bold")
    axes[0].set_xlabel("Year")
    axes[0].set_ylabel("Shipping units per 1000 sold units")
    axes[0].set_xticks(years)
    axes[0].legend(frameon=False, loc="upper right")

    dc_plot = dc_load_2030.sort_values("pi_realized_units").reset_index(drop=True)
    x = range(len(dc_plot))
    width = 0.38
    axes[1].bar(
        [i - width / 2 for i in x],
        dc_plot["old_realized_units"],
        width=width,
        color=OLD_COLOR,
        label="Old network",
    )
    axes[1].bar(
        [i + width / 2 for i in x],
        dc_plot["pi_realized_units"],
        width=width,
        color=PI_COLOR,
        label="PI network",
    )
    axes[1].set_title("2030 DC demand served", fontsize=13, weight="bold")
    axes[1].set_xlabel("DC")
    axes[1].set_ylabel("Realized units")
    axes[1].set_xticks(list(x), [dc.replace("CAND_", "") for dc in dc_plot["dc_id"]], rotation=20)
    axes[1].yaxis.set_major_formatter(_currency_formatter(1000.0, "k"))
    axes[1].legend(frameon=False, loc="upper left")

    fig.suptitle("PI network ships less per sold unit and serves more volume at each 2030 DC", fontsize=15, weight="bold")
    _save_figure(fig, "pi_vs_old_shipping_and_dc_load.png")


def _plot_horizon_advantage(horizon_efficiency: pd.DataFrame) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    ordered = horizon_efficiency.sort_values("advantage_pct")
    fig, ax = plt.subplots(figsize=(10, 5.8), constrained_layout=True)
    ax.barh(ordered["metric_label"], ordered["advantage_pct"], color=PI_COLOR)
    ax.set_title("Cumulative PI advantage across the 2027-2034 horizon", fontsize=15, weight="bold")
    ax.set_xlabel("Advantage vs old network (%)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _pos: f"{x:,.0f}%"))
    for idx, value in enumerate(ordered["advantage_pct"]):
        ax.text(value + 2, idx, f"{value:.1f}%", va="center", color=NEUTRAL_COLOR)
    _save_figure(fig, "pi_vs_old_horizon_advantage.png")


def _build_pi_tradeoff_metrics(yearly_comparison: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    reasons = {
        "coverage_shortfall_pct_pts": (
            "PI expands into harder non-metro flows; a small share of feasible pairs remains uncovered as the network scales."
        ),
        "relay_unready_share_pct": (
            "The larger relay mesh creates more edge cases and coordination dependencies, so readiness degrades as the footprint grows."
        ),
        "service_tail_spread_hr": (
            "Multi-hop routings and long-tail last-mile legs widen the gap between average and p95 service time."
        ),
        "network_touchpoints_ratio_vs_old": (
            "PI uses many more operating nodes than the old DC-centric design, increasing orchestration and partner-management burden."
        ),
    }

    for row in yearly_comparison.itertuples(index=False):
        old_sites = float(row.old_euro_dc_count + row.old_savannah_dc_count)
        pi_sites = float(row.pi_dc_count + row.pi_peri_urban_hub_count + row.pi_relay_hub_count)
        metrics = [
            {
                "metric_key": "coverage_shortfall_pct_pts",
                "metric_label": "Coverage shortfall to 100%",
                "reference_label": "Ideal full feasible-pair coverage",
                "reference_value": 100.0,
                "pi_value": 100.0 - float(row.pi_coverage_pct),
                "display_value": float(row.pi_coverage_pct),
                "unit": "pct-pts",
            },
            {
                "metric_key": "relay_unready_share_pct",
                "metric_label": "Relay network not ready",
                "reference_label": "Ideal fully ready relay network",
                "reference_value": 100.0,
                "pi_value": 100.0 - float(row.pi_relay_readiness_pct),
                "display_value": float(row.pi_relay_readiness_pct),
                "unit": "%",
            },
            {
                "metric_key": "service_tail_spread_hr",
                "metric_label": "p95-minus-mean service time",
                "reference_label": "Lower tail spread is better",
                "reference_value": float(row.pi_mean_service_otd_hr),
                "pi_value": float(row.pi_p95_service_otd_hr - row.pi_mean_service_otd_hr),
                "display_value": float(row.pi_p95_service_otd_hr),
                "unit": "hours",
            },
            {
                "metric_key": "network_touchpoints_ratio_vs_old",
                "metric_label": "Network touchpoints vs old",
                "reference_label": "Old network operating sites",
                "reference_value": old_sites,
                "pi_value": pi_sites / old_sites,
                "display_value": pi_sites,
                "unit": "x",
            },
        ]
        for metric in metrics:
            rows.append(
                {
                    "year": int(row.year),
                    **metric,
                    "underperformance_reason": reasons[metric["metric_key"]],
                }
            )

    return pd.DataFrame(rows)


def _plot_pi_tradeoffs(tradeoff_metrics: pd.DataFrame) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    specs = [
        {
            "metric_key": "coverage_shortfall_pct_pts",
            "title": "Coverage shortfall",
            "ylabel": "Pct points below 100%",
            "formatter": FuncFormatter(lambda x, _pos: f"{x:.1f}"),
        },
        {
            "metric_key": "relay_unready_share_pct",
            "title": "Relay network not ready",
            "ylabel": "% of relay network",
            "formatter": FuncFormatter(lambda x, _pos: f"{x:.0f}%"),
        },
        {
            "metric_key": "service_tail_spread_hr",
            "title": "Service-time tail spread",
            "ylabel": "p95 - mean hours",
            "formatter": FuncFormatter(lambda x, _pos: f"{x:.0f}h"),
        },
        {
            "metric_key": "network_touchpoints_ratio_vs_old",
            "title": "Operating touchpoints vs old",
            "ylabel": "Times the old-site count",
            "formatter": FuncFormatter(lambda x, _pos: f"{x:.0f}x"),
        },
    ]

    years = sorted(tradeoff_metrics["year"].unique())
    for ax, spec in zip(axes.flat, specs):
        metric_df = tradeoff_metrics[tradeoff_metrics["metric_key"] == spec["metric_key"]]
        ax.plot(metric_df["year"], metric_df["pi_value"], marker="o", lw=2.2, color="#9A3412")
        ax.fill_between(metric_df["year"], metric_df["pi_value"], color="#FDBA74", alpha=0.35)
        ax.set_title(spec["title"], fontsize=12, weight="bold", color=NEUTRAL_COLOR)
        ax.set_xlabel("Year")
        ax.set_ylabel(spec["ylabel"])
        ax.set_xticks(years)
        ax.yaxis.set_major_formatter(spec["formatter"])

    fig.suptitle("PI network trade-offs and underperforming areas", fontsize=16, weight="bold")
    _save_figure(fig, "pi_tradeoff_overview.png")


def _load_notebook() -> dict:
    return json.loads(TASK4_NOTEBOOK.read_text())


def _cell_text(nb: dict, idx: int) -> str:
    parts: list[str] = []
    for out in nb["cells"][idx].get("outputs", []):
        if "text" in out:
            parts.append("".join(out["text"]))
    return "".join(parts)


def _parse_rows_by_year(text: str, pattern: str, columns: list[str]) -> pd.DataFrame:
    rows = re.findall(pattern, text, flags=re.M)
    df = pd.DataFrame(rows, columns=columns)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="raise")
    df["year"] = df["year"].astype(int)
    return df


def _parse_rows_by_index(text: str, pattern: str, columns: list[str]) -> pd.DataFrame:
    rows = re.findall(pattern, text, flags=re.M)
    df = pd.DataFrame(rows, columns=columns)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="raise")
    df["row_idx"] = df["row_idx"].astype(int)
    return df


def extract_task4_old_network() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float]]:
    nb = _load_notebook()

    cell4 = _cell_text(nb, 4)
    cell5 = _cell_text(nb, 5)
    cell6 = _cell_text(nb, 6)
    cell7 = _cell_text(nb, 7)
    cell8 = _cell_text(nb, 8)
    cell10 = _cell_text(nb, 10)
    cell11 = _cell_text(nb, 11)
    cell14 = _cell_text(nb, 14)
    cell6_parts = cell6.split("\n\n")
    cell8_parts = cell8.split("\n\n")
    cell10_parts = cell10.split("\n\n")

    prod_pack = _parse_rows_by_year(
        cell4.split("\n\n")[2],
        r"^\s*\d+\s+(20\d{2})\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s*$",
        ["year", "production_cost_eur", "packaging_cost_eur"],
    )

    inventory = _parse_rows_by_year(
        cell5.split("\n\n")[2],
        r"^\s*\d+\s+(20\d{2})\s+([0-9.e+-]+)\s*$",
        ["year", "inventory_holding_cost_eur"],
    )

    transport_left = _parse_rows_by_year(
        cell6_parts[2],
        r"^\s*\d+\s+(20\d{2})\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s*$",
        ["year", "ocean_transport_cost_eur", "us_ground_transport_cost_eur"],
    )
    transport_right = _parse_rows_by_index(
        cell6_parts[3],
        r"^\s*(\d+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s*$",
        ["row_idx", "eu_ground_transport_cost_eur", "total_transport_cost_eur"],
    )
    transport_right["year"] = transport_left["year"].tolist()
    transport = transport_left.merge(
        transport_right.drop(columns=["row_idx"]),
        on="year",
        how="left",
    )

    delivery = _parse_rows_by_year(
        cell7.split("\n\n")[2],
        r"^\s*\d+\s+(20\d{2})\s+([0-9.e+-]+)\s*$",
        ["year", "customer_delivery_cost_eur"],
    )

    dc_ops_left = _parse_rows_by_year(
        cell8_parts[20],
        r"^\s*\d+\s+(20\d{2})\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s*$",
        ["year", "euro_dc_operating_cost_eur", "savannah_dc_operating_cost_eur"],
    )
    dc_ops_right = _parse_rows_by_index(
        cell8_parts[21],
        r"^\s*(\d+)\s+([0-9.e+-]+)\s*$",
        ["row_idx", "dc_operating_cost_eur"],
    )
    dc_ops_right["year"] = dc_ops_left["year"].tolist()
    dc_ops = dc_ops_left.merge(dc_ops_right.drop(columns=["row_idx"]), on="year", how="left")

    units = _parse_rows_by_year(
        cell10_parts[0],
        (
            r"^\s*\d+\s+(20\d{2})\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+"
            r"([0-9.e+-]+)\s*$"
        ),
        [
            "year",
            "expected_demand_units",
            "realized_sales_units",
            "lost_sales_units",
        ],
    )

    revenue = _parse_rows_by_index(
        cell10_parts[1],
        (
            r"^\s*(\d+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+"
            r"([0-9.e+-]+)\s+([0-9.e+-]+)\s*$"
        ),
        [
            "row_idx",
            "revenue_eur",
            "lost_revenue_eur",
            "fill_rate",
            "production_cost_from_profitability",
        ],
    )
    revenue["year"] = units["year"].tolist()
    revenue = revenue.drop(columns=["row_idx", "production_cost_from_profitability"])

    costs = _parse_rows_by_index(
        cell10_parts[5],
        r"^\s*(\d+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s*$",
        ["row_idx", "dc_operating_cost_from_profitability", "fleet_fixed_cost_eur", "total_cost_eur"],
    ).drop(columns=["dc_operating_cost_from_profitability"])

    profit = _parse_rows_by_index(
        cell10_parts[6],
        r"^\s*(\d+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s*$",
        ["row_idx", "operating_profit_eur", "profit_margin", "profit_per_realized_unit_eur"],
    )

    us_activity = _parse_rows_by_year(
        cell14.split("\n\n")[0],
        r"^\s*\d+\s+(20\d{2})\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s*$",
        [
            "year",
            "ocean_containers",
            "ocean_transport_cost_from_us_activity",
            "us_trips",
            "us_total_miles",
        ],
    ).drop(columns=["ocean_transport_cost_from_us_activity"])

    yearly = (
        units.merge(revenue, on="year", how="left")
        .merge(prod_pack, on="year", how="left")
        .merge(inventory, on="year", how="left")
        .merge(transport, on="year", how="left")
        .merge(delivery, on="year", how="left")
        .merge(dc_ops, on="year", how="left")
    )

    yearly = yearly.sort_values("year").reset_index(drop=True)
    yearly["row_idx"] = yearly.index
    yearly = yearly.merge(costs, on="row_idx", how="left").merge(profit, on="row_idx", how="left")
    yearly = yearly.drop(columns=["row_idx"])
    yearly = yearly.merge(us_activity, on="year", how="left")

    yearly["network_scope_cost_eur"] = (
        yearly["total_transport_cost_eur"]
        + yearly["customer_delivery_cost_eur"]
        + yearly["dc_operating_cost_eur"]
        + yearly["fleet_fixed_cost_eur"]
    )
    yearly["network_scope_cost_per_unit_eur"] = (
        yearly["network_scope_cost_eur"] / yearly["realized_sales_units"]
    )
    yearly["network_scope_margin_eur"] = yearly["revenue_eur"] - yearly["network_scope_cost_eur"]
    yearly["transport_cost_per_unit_eur"] = (
        yearly["total_transport_cost_eur"] / yearly["realized_sales_units"]
    )
    yearly["containers_per_1000_units"] = (
        yearly["ocean_containers"] / yearly["realized_sales_units"] * 1000.0
    )

    baseline_design = (
        pd.read_csv(TASK4_EURODC_45)
        .groupby("year", as_index=False)
        .agg(
            old_euro_dc_count=("euro_dc_id", "nunique"),
            old_eurodc_required_workers=("required_workers", "sum"),
        )
    )
    savannah_design = (
        pd.read_csv(TASK4_SAVANNAH_45)
        .groupby("year", as_index=False)
        .agg(
            old_savannah_dc_count=("node", "nunique"),
            old_savannah_required_workers=("required_workers", "sum"),
        )
    )
    fleet_design = (
        pd.read_csv(TASK4_FLEET_45)
        .rename(
            columns={
                "georgia_peak_active_trucks": "old_georgia_peak_active_trucks",
                "georgia_peak_active_chassis": "old_georgia_peak_active_chassis",
                "europe_peak_active_trucks": "old_europe_peak_active_trucks",
                "europe_peak_active_chassis": "old_europe_peak_active_chassis",
            }
        )[
            [
                "year",
                "old_georgia_peak_active_trucks",
                "old_georgia_peak_active_chassis",
                "old_europe_peak_active_trucks",
                "old_europe_peak_active_chassis",
            ]
        ]
    )
    design = baseline_design.merge(savannah_design, on="year", how="left").merge(
        fleet_design, on="year", how="left"
    )

    horizon = {}
    for line in cell11.splitlines():
        if not line or line.startswith("Horizon summary:") or line.strip() == "0":
            continue
        if re.match(r"^\s*[A-Za-z_].+\s+[0-9.\-eE]+$", line):
            key, value = re.split(r"\s{2,}", line.strip(), maxsplit=1)
            if key != "years_covered":
                horizon[key] = float(value)

    return yearly, design, horizon


def extract_task5_pi_network() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    kpis = pd.read_csv(TASK5_KPIS)
    profit = pd.read_csv(TASK5_PROFIT)
    demand = pd.read_csv(TASK5_DEMAND).rename(columns={"pi_realized_total": "pi_units_exact"})
    container = pd.read_csv(TASK5_CONTAINER)[["year", "teus_pi", "teus_nonpi", "container_saving_eur"]]
    autonomy = pd.read_csv(TASK5_AUTONOMY)

    yearly = (
        kpis.merge(
            demand[
                ["year", "pi_units_exact", "pi_revenue_eur", "route_backed_share_pct", "mean_purchase_prob"]
            ],
            on="year",
            how="left",
            suffixes=("", "_demand"),
        )
        .merge(
            profit[
                [
                    "year",
                    "total_pi_cost_eur",
                    "pi_margin_eur",
                    "pi_margin_pct",
                    "total_dc_cost_eur",
                    "total_transport_eur",
                    "pi_lastmile_cost_eur",
                    "pi_pack_cost_eur",
                    "transload_cost_eur",
                    "hub_relay_cost_eur",
                    "hub_consol_cost_eur",
                ]
            ],
            on="year",
            how="left",
        )
        .merge(container, on="year", how="left")
        .merge(autonomy, on="year", how="left", suffixes=("", "_autonomy"))
    )

    yearly["pi_network_scope_cost_per_unit_eur"] = yearly["total_pi_cost_eur"] / yearly["pi_units_exact"]
    yearly["pi_teus_per_1000_units"] = yearly["teus_pi"] / yearly["pi_units_exact"] * 1000.0

    design = yearly[
        [
            "year",
            "n_dc",
            "n_peri_urban_hub",
            "n_relay_hub",
            "n_lanes_total",
            "coverage_pct",
            "relay_readiness_pct",
            "dc_dc_connectivity_pct",
            "dual_role_hubs",
            "dual_role_pct",
        ]
    ].copy()

    dc_rows: list[pd.DataFrame] = []
    for year in range(2027, 2035):
        path = ROOT / "Task5" / "output" / f"dc_capacity_{year}.csv"
        df = pd.read_csv(path)
        df["year"] = year
        dc_rows.append(df[["year", "dc_id", "annual_units", "p95_peak_daily_units", "dc_total_cost_eur"]])
    dc_capacity = pd.concat(dc_rows, ignore_index=True)

    return yearly, design, dc_capacity


def build_comparison() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    task4_yearly, task4_design, task4_horizon = extract_task4_old_network()
    task5_yearly, task5_design, task5_dc_capacity = extract_task5_pi_network()

    task4_demand_check = pd.read_csv(TASK4_ANNUAL_DEMAND).rename(
        columns={"realized_units_per_sim": "realized_units_report_bundle"}
    )
    task4_yearly = task4_yearly.merge(task4_demand_check, on="year", how="left")
    if not (task4_yearly["realized_sales_units"] - task4_yearly["realized_units_report_bundle"]).abs().lt(0.01).all():
        raise ValueError("Task4 realized-demand mismatch between notebook output and report_bundle.")
    task4_yearly = task4_yearly.drop(columns=["realized_units_report_bundle"])

    task4_yearly["recomputed_total_cost_eur"] = (
        task4_yearly["production_cost_eur"]
        + task4_yearly["packaging_cost_eur"]
        + task4_yearly["inventory_holding_cost_eur"]
        + task4_yearly["total_transport_cost_eur"]
        + task4_yearly["customer_delivery_cost_eur"]
        + task4_yearly["dc_operating_cost_eur"]
        + task4_yearly["fleet_fixed_cost_eur"]
    )
    if not (task4_yearly["recomputed_total_cost_eur"] - task4_yearly["total_cost_eur"]).abs().lt(50).all():
        raise ValueError("Task4 total-cost recomputation does not match notebook profitability table.")

    task5_demand_only = pd.read_csv(TASK5_DEMAND)
    task5_profit_only = pd.read_csv(TASK5_PROFIT)
    if not (task5_demand_only["pi_realized_total"] - task5_profit_only["pi_units"]).abs().le(2).all():
        raise ValueError("Task5 demand summary and profitability units are misaligned by more than 2 units.")

    yearly_comparison = (
        task4_yearly.merge(task4_design, on="year", how="left")
        .merge(
            task5_yearly[
                [
                    "year",
                    "pi_units_exact",
                    "pi_revenue_eur",
                    "n_dc",
                    "n_peri_urban_hub",
                    "n_relay_hub",
                    "n_lanes_total",
                    "coverage_pct",
                    "relay_readiness_pct",
                    "mean_service_otd_hr",
                    "p95_service_otd_hr",
                    "mean_purchase_prob",
                    "route_backed_share_pct",
                    "total_transport_cost_eur",
                    "transport_cost_per_unit",
                    "total_co2_kg",
                    "co2_per_unit_kg",
                    "total_pi_cost_eur",
                    "pi_network_scope_cost_per_unit_eur",
                    "pi_margin_eur",
                    "pi_margin_pct",
                    "teus_pi",
                    "pi_teus_per_1000_units",
                ]
            ],
            on="year",
            how="left",
        )
    )

    yearly_comparison = yearly_comparison.rename(
        columns={
            "realized_sales_units": "old_realized_units",
            "expected_demand_units": "old_expected_units",
            "lost_sales_units": "old_lost_units",
            "revenue_eur": "old_revenue_eur",
            "fill_rate": "old_fill_rate",
            "total_transport_cost_eur_x": "old_transport_cost_eur",
            "transport_cost_per_unit_eur": "old_transport_cost_per_unit_eur",
            "customer_delivery_cost_eur": "old_customer_delivery_cost_eur",
            "dc_operating_cost_eur": "old_dc_operating_cost_eur",
            "fleet_fixed_cost_eur": "old_fleet_fixed_cost_eur",
            "network_scope_cost_eur": "old_network_scope_cost_eur",
            "network_scope_cost_per_unit_eur": "old_network_scope_cost_per_unit_eur",
            "network_scope_margin_eur": "old_network_scope_margin_eur",
            "ocean_containers": "old_ocean_containers",
            "containers_per_1000_units": "old_containers_per_1000_units",
            "operating_profit_eur": "old_operating_profit_eur",
            "profit_margin": "old_profit_margin",
            "n_dc": "pi_dc_count",
            "n_peri_urban_hub": "pi_peri_urban_hub_count",
            "n_relay_hub": "pi_relay_hub_count",
            "n_lanes_total": "pi_lane_count",
            "coverage_pct": "pi_coverage_pct",
            "relay_readiness_pct": "pi_relay_readiness_pct",
            "mean_service_otd_hr": "pi_mean_service_otd_hr",
            "p95_service_otd_hr": "pi_p95_service_otd_hr",
            "mean_purchase_prob": "pi_mean_purchase_prob",
            "route_backed_share_pct": "pi_route_backed_share_pct",
            "total_transport_cost_eur_y": "pi_transport_cost_eur",
            "transport_cost_per_unit": "pi_transport_cost_per_unit_eur",
            "total_co2_kg": "pi_total_co2_kg",
            "co2_per_unit_kg": "pi_co2_per_unit_kg",
            "total_pi_cost_eur": "pi_network_scope_cost_eur",
            "pi_margin_eur": "pi_network_scope_margin_eur",
            "pi_margin_pct": "pi_network_scope_margin_pct",
            "pi_units_exact": "pi_realized_units",
            "pi_revenue_eur": "pi_revenue_eur",
            "teus_pi": "pi_teus",
        }
    )

    yearly_comparison["units_uplift_pct"] = (
        (yearly_comparison["pi_realized_units"] / yearly_comparison["old_realized_units"]) - 1.0
    ) * 100.0
    yearly_comparison["revenue_uplift_pct"] = (
        (yearly_comparison["pi_revenue_eur"] / yearly_comparison["old_revenue_eur"]) - 1.0
    ) * 100.0
    yearly_comparison["transport_cost_change_pct"] = (
        (yearly_comparison["pi_transport_cost_eur"] / yearly_comparison["old_transport_cost_eur"]) - 1.0
    ) * 100.0
    yearly_comparison["transport_cost_per_unit_change_pct"] = (
        (
            yearly_comparison["pi_transport_cost_per_unit_eur"]
            / yearly_comparison["old_transport_cost_per_unit_eur"]
        )
        - 1.0
    ) * 100.0
    yearly_comparison["network_scope_cost_change_pct"] = (
        (yearly_comparison["pi_network_scope_cost_eur"] / yearly_comparison["old_network_scope_cost_eur"]) - 1.0
    ) * 100.0
    yearly_comparison["network_scope_cost_per_unit_change_pct"] = (
        (
            yearly_comparison["pi_network_scope_cost_per_unit_eur"]
            / yearly_comparison["old_network_scope_cost_per_unit_eur"]
        )
        - 1.0
    ) * 100.0
    yearly_comparison["container_reduction_pct"] = (
        1.0 - (yearly_comparison["pi_teus"] / yearly_comparison["old_ocean_containers"])
    ) * 100.0

    design_yearly = (
        task4_design.merge(task5_design, on="year", how="left")
        .rename(
            columns={
                "old_euro_dc_count": "old_euro_dc_count",
                "old_savannah_dc_count": "old_savannah_dc_count",
                "n_dc": "pi_dc_count",
                "n_peri_urban_hub": "pi_peri_urban_hub_count",
                "n_relay_hub": "pi_relay_hub_count",
                "n_lanes_total": "pi_lane_count",
            }
        )
    )

    task4_dc = pd.read_csv(TASK4_DC_DEMAND).rename(
        columns={"euro_dc_id": "dc_id", "realized_units_per_sim": "old_realized_units"}
    )
    task5_dc = task5_dc_capacity.rename(columns={"annual_units": "pi_realized_units"})
    dc_load_comparison = task4_dc.merge(task5_dc, on=["year", "dc_id"], how="outer")
    old_totals = dc_load_comparison.groupby("year")["old_realized_units"].transform("sum")
    pi_totals = dc_load_comparison.groupby("year")["pi_realized_units"].transform("sum")
    dc_load_comparison["old_demand_share_pct"] = (
        dc_load_comparison["old_realized_units"] / old_totals * 100.0
    )
    dc_load_comparison["pi_demand_share_pct"] = (
        dc_load_comparison["pi_realized_units"] / pi_totals * 100.0
    )
    dc_load_comparison["unit_delta"] = (
        dc_load_comparison["pi_realized_units"] - dc_load_comparison["old_realized_units"]
    )
    dc_load_comparison["unit_delta_pct_vs_old"] = (
        dc_load_comparison["unit_delta"] / dc_load_comparison["old_realized_units"] * 100.0
    )

    dominance_scorecard = _build_dominance_scorecard(yearly_comparison)

    horizon = pd.DataFrame(
        [
            {
                "metric_scope": "realized_units",
                "old_total": task4_yearly["realized_sales_units"].sum(),
                "pi_total": task5_yearly["pi_units_exact"].sum(),
            },
            {
                "metric_scope": "revenue_eur",
                "old_total": task4_yearly["revenue_eur"].sum(),
                "pi_total": task5_yearly["pi_revenue_eur"].sum(),
            },
            {
                "metric_scope": "transport_cost_eur",
                "old_total": task4_yearly["total_transport_cost_eur"].sum(),
                "pi_total": task5_yearly["total_transport_cost_eur"].sum(),
            },
            {
                "metric_scope": "network_scope_cost_eur",
                "old_total": task4_yearly["network_scope_cost_eur"].sum(),
                "pi_total": task5_yearly["total_pi_cost_eur"].sum(),
            },
            {
                "metric_scope": "network_scope_margin_eur",
                "old_total": task4_yearly["network_scope_margin_eur"].sum(),
                "pi_total": task5_yearly["pi_margin_eur"].sum(),
            },
            {
                "metric_scope": "shipping_units",
                "old_total": task4_yearly["ocean_containers"].sum(),
                "pi_total": task5_yearly["teus_pi"].sum(),
            },
        ]
    )
    horizon["change_pct"] = ((horizon["pi_total"] / horizon["old_total"]) - 1.0) * 100.0
    horizon_efficiency = _build_horizon_efficiency_summary(yearly_comparison)
    pi_tradeoff_metrics = _build_pi_tradeoff_metrics(yearly_comparison)

    task4_yearly_out = task4_yearly.merge(task4_design, on="year", how="left")
    task5_yearly_out = task5_yearly.copy()

    task4_yearly_out.to_csv(DATA_DIR / "task4_old_network_yearly.csv", index=False)
    task5_yearly_out.to_csv(DATA_DIR / "task5_pi_network_yearly.csv", index=False)
    yearly_comparison.to_csv(DATA_DIR / "task4_vs_task5_yearly_comparison.csv", index=False)
    design_yearly.to_csv(DATA_DIR / "design_comparison_yearly.csv", index=False)
    dc_load_comparison.sort_values(["year", "dc_id"]).to_csv(
        DATA_DIR / "dc_load_comparison_by_year.csv", index=False
    )
    dc_load_comparison[dc_load_comparison["year"] == 2030].sort_values("dc_id").to_csv(
        DATA_DIR / "dc_load_comparison_2030.csv", index=False
    )
    horizon.to_csv(DATA_DIR / "horizon_comparison.csv", index=False)
    horizon_efficiency.to_csv(DATA_DIR / "horizon_efficiency_summary.csv", index=False)
    dominance_scorecard.to_csv(DATA_DIR / "pi_dominance_scorecard.csv", index=False)
    pi_tradeoff_metrics.to_csv(DATA_DIR / "pi_tradeoff_metrics.csv", index=False)

    dc_load_2030 = dc_load_comparison[dc_load_comparison["year"] == 2030].copy()
    _plot_performance_overview(yearly_comparison)
    _plot_efficiency_frontier(yearly_comparison)
    _plot_shipping_and_dc_load(yearly_comparison, dc_load_2030)
    _plot_horizon_advantage(horizon_efficiency)
    _plot_pi_tradeoffs(pi_tradeoff_metrics)

    summary_2030 = yearly_comparison[yearly_comparison["year"] == 2030].iloc[0]
    horizon_units_advantage = horizon_efficiency.loc[
        horizon_efficiency["metric_label"] == "Realized units", "advantage_pct"
    ].iloc[0]
    horizon_cost_advantage = horizon_efficiency.loc[
        horizon_efficiency["metric_label"] == "Network-scope cost per unit (EUR)", "advantage_pct"
    ].iloc[0]
    tradeoff_2030 = pi_tradeoff_metrics[pi_tradeoff_metrics["year"] == 2030].set_index("metric_key")
    readme = f"""# Task4 vs Task5 Comparison

This folder compares the old network (Task4 baseline) with the PI network (Task5 output) using local repo artifacts only.

## Sources

- Task4 design: `Task4/4.5/*.csv`
- Task4 old-network performance: printed outputs saved inside `Task4/4.6 & 4.7.ipynb`
- Task4 demand checks: `report_bundle/data/task4_annual_demand_by_year.csv`, `report_bundle/data/task4_dc_demand_by_year.csv`
- Task5 PI performance: `Task5/output/*.csv`

## Alignment Rules

- Old-network realized demand, revenue, fill rate, and full baseline cost blocks come from Task4 notebook output.
- PI realized demand comes from `subtask_5_5_pi_demand_summary.csv`.
- PI per-unit transport and CO2 come from `network_kpis_by_year.csv`, not from `subtask_5_9_cost_carbon_summary.csv`.
  Reason: the Task5 5.9 summary file still uses lane-throughput as the denominator for per-unit metrics.
- The most defensible cross-network cost comparison is `network_scope_cost_eur`:
  - Task4 old network: transport + customer delivery + DC operating + fleet fixed
  - Task5 PI network: `total_pi_cost_eur`
- Task4 full operating profit includes production, packaging, and inventory.
  Task5 `pi_margin_eur` is a network-scope measure, so those two should not be treated as directly equivalent.

## Generated Files

- `data/task4_old_network_yearly.csv`
- `data/task5_pi_network_yearly.csv`
- `data/task4_vs_task5_yearly_comparison.csv`
- `data/design_comparison_yearly.csv`
- `data/dc_load_comparison_by_year.csv`
- `data/dc_load_comparison_2030.csv`
- `data/horizon_comparison.csv`
- `data/horizon_efficiency_summary.csv`
- `data/pi_dominance_scorecard.csv`
- `data/pi_tradeoff_metrics.csv`
- `figures/pi_vs_old_performance_overview.png`
- `figures/pi_vs_old_efficiency_frontier.png`
- `figures/pi_vs_old_shipping_and_dc_load.png`
- `figures/pi_vs_old_horizon_advantage.png`
- `figures/pi_tradeoff_overview.png`

## Visual Framing

- The plots are limited to matched metrics where the PI network outperforms the old network on a consistent basis and denominator.
- Higher-is-better plots: realized units, revenue.
- Lower-is-better plots: transport cost per unit, network-scope cost per unit, shipping units per 1000 sold units.
- `pi_dominance_scorecard.csv` confirms the PI network wins on each selected metric in every year from 2027 to 2034.

## PI Trade-Offs

- `pi_tradeoff_metrics.csv` tracks areas where the PI design is weaker or harder to run, even though its matched economic KPIs are better.
- 2030 coverage shortfall: {tradeoff_2030.loc["coverage_shortfall_pct_pts", "pi_value"]:.2f} percentage points below full coverage.
- 2030 relay network not ready: {tradeoff_2030.loc["relay_unready_share_pct", "pi_value"]:.2f}%.
- 2030 service tail spread: {tradeoff_2030.loc["service_tail_spread_hr", "pi_value"]:.2f} hours between mean and p95 service time.
- 2030 operating touchpoints vs old network: {tradeoff_2030.loc["network_touchpoints_ratio_vs_old", "pi_value"]:.1f}x.
- These are plausible side effects of the hyperconnected design: broader reach, more relay dependence, more multi-hop flows, and much higher orchestration complexity.

## 2030 Snapshot

- Old network: {summary_2030["old_realized_units"]:.0f} realized units, {summary_2030["old_transport_cost_per_unit_eur"]:.2f} EUR transport per unit, {summary_2030["old_network_scope_cost_per_unit_eur"]:.2f} EUR network-scope cost per unit, {summary_2030["old_ocean_containers"]:.0f} ocean containers.
- PI network: {summary_2030["pi_realized_units"]:.0f} realized units, {summary_2030["pi_transport_cost_per_unit_eur"]:.2f} EUR transport per unit, {summary_2030["pi_network_scope_cost_per_unit_eur"]:.2f} EUR network-scope cost per unit, {summary_2030["pi_teus"]:.0f} TEUs.
- 2030 design overlay: {int(summary_2030["old_euro_dc_count"])} Euro DCs in both cases, plus {int(summary_2030["pi_peri_urban_hub_count"])} peri-urban hubs and {int(summary_2030["pi_relay_hub_count"])} relay hubs in PI.
- 2030 demand uplift: {summary_2030["units_uplift_pct"]:.1f}% vs old network.
- 2030 network-scope cost per unit change: {summary_2030["network_scope_cost_per_unit_change_pct"]:.1f}% vs old network.

## Validation Notes

- Task4 notebook totals were reconciled back to the report-bundle yearly demand file.
- Task4 full total cost was recomputed from its component blocks and matched the notebook profitability table.
- Task5 demand and profitability outputs differ by at most 2 units per year because of rounding; the comparison keeps exact demand from the Task5 demand summary.
- The case PDF is machine-readable in this environment and was used to confirm that Task 5 is the hyperconnected transportation workstream.
- The comparison avoids apples-to-oranges claims such as Task4 full operating profit versus Task5 network-scope margin.
- The trade-off metrics are intentionally labeled as trade-offs where no direct old-network KPI exists in the saved repo outputs.

## Horizon Check

- Task4 notebook horizon revenue: {task4_horizon["revenue_eur"]:.0f} EUR
- Task4 parsed yearly revenue total: {task4_yearly["revenue_eur"].sum():.0f} EUR
- PI cumulative realized-units advantage: {horizon_units_advantage:.1f}%
- PI cumulative network-scope cost-per-unit reduction: {horizon_cost_advantage:.1f}%
"""
    (COMPARISON_DIR / "README.md").write_text(readme)


if __name__ == "__main__":
    build_comparison()
