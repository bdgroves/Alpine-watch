#!/usr/bin/env python3
"""
alpine-watch / render_charts.py
================================
Generates static PNG sparkline charts and summary visuals
from the JSON data produced by fetch_lakes.py.

Outputs to docs/charts/ for embedding in the dashboard.

Brooks Groves · bdgroves/alpine-watch
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Aesthetic constants ────────────────────────────────────────
BG_DARK = "#0a0f1a"
BG_CARD = "#111827"
ACCENT_TEAL = "#00d4c8"
ACCENT_AMBER = "#f59e0b"
ACCENT_RED = "#ef4444"
ACCENT_GREEN = "#10b981"
TEXT_PRIMARY = "#e2e8f0"
TEXT_DIM = "#64748b"

ALERT_COLORS = {
    0: ACCENT_GREEN,   # WATCH
    1: ACCENT_AMBER,   # CAUTION
    2: "#f97316",      # ELEVATED
    3: ACCENT_RED,     # CRITICAL
}

plt.rcParams.update({
    "figure.facecolor": BG_DARK,
    "axes.facecolor": BG_CARD,
    "axes.edgecolor": "#1e293b",
    "axes.labelcolor": TEXT_DIM,
    "xtick.color": TEXT_DIM,
    "ytick.color": TEXT_DIM,
    "text.color": TEXT_PRIMARY,
    "grid.color": "#1e293b",
    "grid.linewidth": 0.5,
    "font.family": "monospace",
})


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def sparkline(values: list[float], color: str, path: str,
              label: str = "", unit: str = ""):
    """
    Render a compact sparkline PNG (240×60px) for embedding.
    """
    if not values or len(values) < 2:
        return

    fig, ax = plt.subplots(figsize=(2.4, 0.6), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")

    x = np.arange(len(values))
    ax.fill_between(x, values, alpha=0.15, color=color)
    ax.plot(x, values, color=color, linewidth=1.5, solid_capstyle="round")

    # Highlight last point
    ax.scatter([x[-1]], [values[-1]], color=color, s=20, zorder=5)

    ax.set_xlim(0, len(values) - 1)
    ax.axis("off")
    plt.tight_layout(pad=0)
    plt.savefig(path, dpi=100, bbox_inches="tight", transparent=True)
    plt.close()


def status_grid(summaries: list[dict], path: str):
    """
    Render a compact grid showing alert status for all lakes.
    """
    n = len(summaries)
    cols = 3
    rows = (n + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(12, rows * 2.2))
    fig.patch.set_facecolor(BG_DARK)
    axes_flat = axes.flatten() if hasattr(axes, "flatten") else [axes]

    for i, ax in enumerate(axes_flat):
        ax.set_facecolor(BG_CARD)
        for spine in ax.spines.values():
            spine.set_color("#1e293b")

        if i < n:
            lake = summaries[i]
            alert = lake.get("alert_level", 0)
            color = ALERT_COLORS[alert]
            label = lake.get("alert_label", "WATCH")

            # Lake name
            ax.text(0.5, 0.75, lake["name"], transform=ax.transAxes,
                    ha="center", va="center", fontsize=9,
                    color=TEXT_PRIMARY, fontweight="bold", wrap=True)

            # Range / state
            ax.text(0.5, 0.52, f"{lake['range']} · {lake['state']} · {lake['elevation_ft']:,} ft",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=7, color=TEXT_DIM)

            # Alert badge
            ax.text(0.5, 0.28, f"● {label}",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=9, color=color, fontweight="bold")

            # Chlorophyll value
            chl = lake.get("chlorophyll_latest")
            chl_str = f"Chl-a: {chl:.1f} µg/L" if chl is not None else "Chl-a: —"
            ax.text(0.5, 0.12, chl_str,
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=7.5, color=TEXT_DIM)

            # Border highlight on elevated/critical
            if alert >= 2:
                for spine in ax.spines.values():
                    spine.set_color(color)
                    spine.set_linewidth(1.5)
        else:
            ax.set_visible(False)

        ax.set_xticks([])
        ax.set_yticks([])

    fig.suptitle("ALPINE-WATCH  //  STATUS GRID", fontsize=11,
                 color=ACCENT_TEAL, fontfamily="monospace",
                 y=0.98, fontweight="bold")
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.98, 0.01, f"Updated: {updated}", ha="right",
             fontsize=7, color=TEXT_DIM)

    plt.tight_layout(rect=[0, 0.02, 1, 0.96], pad=0.5)
    plt.savefig(path, dpi=120, bbox_inches="tight", facecolor=BG_DARK)
    plt.close()
    print(f"✓ Wrote {path}")


def chlorophyll_comparison(summaries: list[dict], path: str):
    """
    Horizontal bar chart comparing latest chlorophyll-a values.
    Color-coded by alert level.
    """
    lakes_with_data = [
        s for s in summaries if s.get("chlorophyll_latest") is not None
    ]
    if not lakes_with_data:
        print("  No chlorophyll data for comparison chart — skipping")
        return

    lakes_with_data.sort(key=lambda x: x["chlorophyll_latest"], reverse=True)
    names = [s["name"] for s in lakes_with_data]
    values = [s["chlorophyll_latest"] for s in lakes_with_data]
    colors = [ALERT_COLORS[s.get("alert_level", 0)] for s in lakes_with_data]

    fig, ax = plt.subplots(figsize=(10, max(4, len(names) * 0.55)))
    fig.patch.set_facecolor(BG_DARK)
    ax.set_facecolor(BG_CARD)

    y = np.arange(len(names))
    bars = ax.barh(y, values, color=colors, height=0.6, alpha=0.85)

    # Threshold lines
    ax.axvline(2.5, color=ACCENT_AMBER, linewidth=0.8, linestyle="--", alpha=0.6, label="Mesotrophic (2.5)")
    ax.axvline(10, color=ACCENT_RED, linewidth=0.8, linestyle="--", alpha=0.6, label="Eutrophic (10)")

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel("Chlorophyll-a (µg/L)", fontsize=9)
    ax.set_title("CHLOROPHYLL-a COMPARISON  //  Latest Observations",
                 fontsize=11, color=ACCENT_TEAL, fontfamily="monospace",
                 fontweight="bold", pad=12)

    ax.legend(fontsize=8, loc="lower right",
              facecolor=BG_CARD, edgecolor="#1e293b", labelcolor=TEXT_DIM)
    ax.grid(axis="x", alpha=0.3)

    for spine in ax.spines.values():
        spine.set_color("#1e293b")

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.98, 0.01, f"ALPINE-WATCH · {updated}",
             ha="right", fontsize=7, color=TEXT_DIM)

    plt.tight_layout()
    plt.savefig(path, dpi=120, bbox_inches="tight", facecolor=BG_DARK)
    plt.close()
    print(f"✓ Wrote {path}")


def main():
    print(f"\n{'='*60}")
    print(f"  ALPINE-WATCH  //  render_charts.py")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    os.makedirs("docs/charts", exist_ok=True)

    data_path = "docs/data/lakes.json"
    if not os.path.exists(data_path):
        print("ERROR: docs/data/lakes.json not found. Run fetch_lakes.py first.")
        return

    payload = load_json(data_path)
    summaries = payload["lakes"]

    # Status grid
    status_grid(summaries, "docs/charts/status_grid.png")

    # Chlorophyll comparison
    chlorophyll_comparison(summaries, "docs/charts/chlorophyll_comparison.png")

    # Per-lake sparklines
    for lake in summaries:
        lake_id = lake["id"]
        detail_path = f"docs/data/{lake_id}.json"
        if not os.path.exists(detail_path):
            continue
        detail = load_json(detail_path)
        ts = detail.get("chlorophyll_timeseries", [])
        if len(ts) >= 3:
            values = [t["chl"] for t in ts]
            alert = lake.get("alert_level", 0)
            color = ALERT_COLORS[alert]
            sparkline(values, color,
                      f"docs/charts/spark_{lake_id}.png",
                      label=lake["name"])
            print(f"✓ Sparkline: {lake_id}")

    print("\nDONE.\n")


if __name__ == "__main__":
    main()
