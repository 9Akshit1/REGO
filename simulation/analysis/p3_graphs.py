"""
rego_graphs.py  —  REGO Phase 3 Comprehensive Graphing Suite
=============================================================
Produces 13 publication-quality figures comparing REGO to SLM, microwave
sintering, and MICP.  All data is derived from simulation output — no
hard-coded REGO values.

Usage:
    python p3_graphs.py outputs/Phase3_v35_default/results.json outputs/Phase3_v35_default/energy_audit.json --outdir figs

Outputs one PDF per figure + a combined multi-page PDF, all in --outdir.
"""

import json
import sys
import math
import argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.ticker import AutoMinorLocator
from pathlib import Path
from typing import Optional, List

# Our metrics module (same directory)
from p3_metrics import (REGOMetrics, get_technology_comparison,
                          inject_rego_into_comparison, TARGETS, DEFAULT_WEIGHTS)

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------
STYLE = dict(
    fig_dpi     = 150,
    font_family = "DejaVu Sans",
    title_size  = 13,
    label_size  = 11,
    tick_size   = 9,
    legend_size = 9,
    spine_color = "#2d2d2d",
    grid_alpha  = 0.25,
)

PALETTE = {
    "REGO\n(this sim)": "#1a73e8",
    "SLM\n(Laser PBF)": "#e84b1a",
    "Microwave\nSintering": "#e8a41a",
    "MICP\n(Bio-binding)": "#2eb87a",
    # time-series colors
    "Preheat":    "#f0a500",
    "Consolidate":"#1a73e8",
    "Cool":       "#2eb87a",
}

REGO_COLOR  = "#1a73e8"
TARGET_COLOR= "#e84b1a"


def _setup():
    plt.rcParams.update({
        "font.family":       STYLE["font_family"],
        "font.size":         STYLE["tick_size"],
        "axes.titlesize":    STYLE["title_size"],
        "axes.labelsize":    STYLE["label_size"],
        "legend.fontsize":   STYLE["legend_size"],
        "axes.spines.top":   False,
        "axes.spines.right": False,
        "axes.grid":         True,
        "grid.alpha":        STYLE["grid_alpha"],
        "grid.linestyle":    "--",
        "figure.dpi":        STYLE["fig_dpi"],
    })


def _save(fig, name: str, outdir: Path, pdf_pages=None):
    p = outdir / f"{name}.png"
    fig.savefig(p, bbox_inches="tight", dpi=STYLE["fig_dpi"])
    if pdf_pages is not None:
        pdf_pages.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {p.name}")


def _tech_labels(comp: dict):
    return list(comp.keys())


def _bar_with_errors(ax, labels, values, errs, colors, ylabel, title,
                     highlight_idx=0, lower_better=False, ylim=None,
                     hline=None, hline_label=None):
    """Shared helper for clean bar charts with error bars."""
    x = np.arange(len(labels))
    bars = ax.bar(x, values, color=colors, width=0.55, zorder=3,
                  edgecolor="white", linewidth=0.8)
    ax.errorbar(x, values, yerr=errs, fmt="none", color="#333",
                capsize=4, linewidth=1.2, zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=STYLE["tick_size"])
    ax.set_ylabel(ylabel, fontsize=STYLE["label_size"])
    ax.set_title(title, fontsize=STYLE["title_size"], pad=8)
    if ylim:
        ax.set_ylim(*ylim)
    if hline is not None:
        ax.axhline(hline, color=TARGET_COLOR, linestyle="--",
                   linewidth=1.2, label=hline_label, zorder=2)
        ax.legend(fontsize=STYLE["legend_size"])
    # Highlight REGO bar
    bars[highlight_idx].set_edgecolor("#333")
    bars[highlight_idx].set_linewidth(1.5)
    # Value labels on bars
    for bar, v in zip(bars, values):
        if v is None or not math.isfinite(v):
            continue
        ypos = bar.get_height()
        va = "bottom"
        offset = ypos * 0.03 if ypos != 0 else 0.01
        ax.text(bar.get_x() + bar.get_width()/2,
                ypos + offset,
                f"{v:.3g}",
                ha="center", va=va, fontsize=7.5, color="#222")
    if lower_better:
        ax.text(0.97, 0.97, "↓ lower is better",
                transform=ax.transAxes, ha="right", va="top",
                fontsize=8, color="#888", style="italic")


# ===========================================================================
# Individual figure functions
# ===========================================================================

def fig_energy_vs_tech(comp: dict, outdir: Path, pdf=None):
    """Fig 1: Energy intensity (kWh/kg) — bar chart vs competitors."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals = [comp[l]["energy_kWh_kg"] for l in labels]
    errs = [comp[l]["energy_kWh_kg"] * comp[l]["uncertainty_pct"]/100 for l in labels]
    colors = [PALETTE.get(l, "#999") for l in labels]
    _bar_with_errors(ax, labels, vals, errs, colors,
                     ylabel="Energy intensity (kWh / kg shell)",
                     title="Fig 1 — Energy Intensity by Manufacturing Method",
                     lower_better=True)
    fig.tight_layout()
    _save(fig, "fig01_energy_kWh_kg", outdir, pdf)


def fig_throughput_vs_tech(comp: dict, outdir: Path, pdf=None):
    """Fig 2: Throughput (g/hr) — log scale."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals_kg = [comp[l]["throughput_kg_hr"] for l in labels]
    vals    = [v * 1000 for v in vals_kg]  # convert to g/hr
    errs    = [v * comp[l]["uncertainty_pct"]/100 for v, l in zip(vals, labels)]
    colors  = [PALETTE.get(l, "#999") for l in labels]
    ax.bar(np.arange(len(labels)), vals, color=colors, width=0.55, zorder=3,
           edgecolor="white", linewidth=0.8)
    ax.errorbar(np.arange(len(labels)), vals, yerr=errs, fmt="none",
                color="#333", capsize=4, linewidth=1.2, zorder=4)
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, fontsize=STYLE["tick_size"])
    ax.set_ylabel("Throughput (g / hr)", fontsize=STYLE["label_size"])
    ax.set_title("Fig 2 — Manufacturing Throughput", fontsize=STYLE["title_size"], pad=8)
    ax.set_yscale("log")
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    for i, (v, l) in enumerate(zip(vals, labels)):
        ax.text(i, v * 1.15, f"{v:.3g}", ha="center", fontsize=7.5)
    fig.tight_layout()
    _save(fig, "fig02_throughput", outdir, pdf)


def fig_shape_accuracy(comp: dict, outdir: Path, pdf=None):
    """Fig 3: Shape deviation (mm) — lower is better."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals   = [comp[l]["shape_dev_mm"] for l in labels]
    errs   = [v * comp[l]["uncertainty_pct"]/100 for v, l in zip(vals, labels)]
    colors = [PALETTE.get(l, "#999") for l in labels]
    _bar_with_errors(ax, labels, vals, errs, colors,
                     ylabel="Mean surface deviation (mm)",
                     title="Fig 3 — Shape Accuracy  (lower = better)",
                     lower_better=True,
                     hline=TARGETS["shape_dev_mm"],
                     hline_label=f'Target ≤ {TARGETS["shape_dev_mm"]} mm')
    ax.set_yscale("log")
    fig.tight_layout()
    _save(fig, "fig03_shape_accuracy", outdir, pdf)


def fig_strength(comp: dict, outdir: Path, pdf=None):
    """Fig 4: Compressive strength (MPa)."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals   = [comp[l]["sigma_MPa"] for l in labels]
    errs   = [v * comp[l]["uncertainty_pct"]/100 for v, l in zip(vals, labels)]
    colors = [PALETTE.get(l, "#999") for l in labels]
    _bar_with_errors(ax, labels, vals, errs, colors,
                     ylabel="Estimated compressive strength (MPa)",
                     title="Fig 4 — Structural Strength",
                     hline=TARGETS["sigma_MPa"],
                     hline_label=f'REGO target {TARGETS["sigma_MPa"]:.0f} MPa')
    fig.tight_layout()
    _save(fig, "fig04_strength_MPa", outdir, pdf)


def fig_isru(comp: dict, outdir: Path, pdf=None):
    """Fig 5: ISRU fraction — horizontal bar chart."""
    fig, ax = plt.subplots(figsize=(7, 4))
    labels = _tech_labels(comp)
    vals   = [comp[l]["isru_pct"] for l in labels]
    colors = [PALETTE.get(l, "#999") for l in labels]
    y = np.arange(len(labels))
    bars = ax.barh(y, vals, color=colors, height=0.55,
                   edgecolor="white", linewidth=0.8, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=STYLE["tick_size"])
    ax.set_xlabel("In-Situ Resource Utilisation (%)", fontsize=STYLE["label_size"])
    ax.set_title("Fig 5 — ISRU Fraction (higher = more lunar-native)",
                 fontsize=STYLE["title_size"], pad=8)
    ax.set_xlim(0, 115)
    ax.axvline(100, color=TARGET_COLOR, linestyle="--", linewidth=1.1)
    for bar, v in zip(bars, vals):
        ax.text(v + 2, bar.get_y() + bar.get_height()/2,
                f"{v:.0f}%", va="center", fontsize=8)
    fig.tight_layout()
    _save(fig, "fig05_isru", outdir, pdf)


def fig_reversibility(comp: dict, outdir: Path, pdf=None):
    """Fig 6: Reversibility / mass recovery %."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals   = [comp[l]["reversibility_pct"] for l in labels]
    errs   = [v * 0.10 for v in vals]
    colors = [PALETTE.get(l, "#999") for l in labels]
    _bar_with_errors(ax, labels, vals, errs, colors,
                     ylabel="Reversibility / Mass Recovery (%)",
                     title="Fig 6 — Reversibility (% mass recoverable per cycle)")
    fig.tight_layout()
    _save(fig, "fig06_reversibility", outdir, pdf)


def fig_feature_size(comp: dict, outdir: Path, pdf=None):
    """Fig 7: Minimum feature size (µm) — lower is better (finer detail)."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals   = [comp[l]["feature_size_um"] for l in labels]
    errs   = [v * 0.15 for v in vals]
    colors = [PALETTE.get(l, "#999") for l in labels]
    _bar_with_errors(ax, labels, vals, errs, colors,
                     ylabel="Minimum feature size (µm)",
                     title="Fig 7 — Particle-Level Precision  (lower = finer)",
                     lower_better=True)
    ax.set_yscale("log")
    fig.tight_layout()
    _save(fig, "fig07_feature_size", outdir, pdf)


def fig_energy_per_mpa(comp: dict, outdir: Path, pdf=None):
    """Fig 8: Energy efficiency ratio — J per MPa of strength achieved."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals   = [comp[l]["energy_per_MPa_J"] for l in labels]
    # Convert kWh/kg cost to J/MPa consistent units if needed
    errs   = [v * comp[l]["uncertainty_pct"]/100 for v, l in zip(vals, labels)]
    colors = [PALETTE.get(l, "#999") for l in labels]
    _bar_with_errors(ax, labels, vals, errs, colors,
                     ylabel="Energy cost (J per MPa strength)",
                     title="Fig 8 — Energy-to-Strength Ratio  (lower = more efficient)",
                     lower_better=True)
    ax.set_yscale("log")
    fig.tight_layout()
    _save(fig, "fig08_energy_per_MPa", outdir, pdf)


def fig_complexity(comp: dict, outdir: Path, pdf=None):
    """Fig 9: System complexity proxy — 1/n_subsystems (higher = simpler)."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals   = [comp[l]["complexity_score"] for l in labels]
    n_subs = [round(1/v) for v in vals]
    errs   = [0] * len(vals)
    colors = [PALETTE.get(l, "#999") for l in labels]
    _bar_with_errors(ax, labels, vals, errs, colors,
                     ylabel="Simplicity score  (1 / n_subsystems)",
                     title="Fig 9 — System Complexity  (higher = simpler)")
    # Annotate with subsystem counts
    for i, (v, n) in enumerate(zip(vals, n_subs)):
        ax.text(i, v + 0.01, f"n={n}", ha="center", fontsize=8, color="#555")
    fig.tight_layout()
    _save(fig, "fig09_complexity", outdir, pdf)


def fig_non_contact(comp: dict, outdir: Path, pdf=None):
    """Fig 10: Non-contact process fraction (%)."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    labels = _tech_labels(comp)
    vals   = [comp[l]["non_contact_pct"] for l in labels]
    contact= [100 - v for v in vals]
    x = np.arange(len(labels))
    ax.bar(x, vals,     color=[PALETTE.get(l,"#999") for l in labels],
           width=0.55, zorder=3, label="Non-contact (%)")
    ax.bar(x, contact, bottom=vals, color="#ddd",
           width=0.55, zorder=3, label="Contact (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=STYLE["tick_size"])
    ax.set_ylabel("Process fraction (%)", fontsize=STYLE["label_size"])
    ax.set_title("Fig 10 — Non-Contact vs Contact Process Fraction",
                 fontsize=STYLE["title_size"], pad=8)
    ax.legend(fontsize=STYLE["legend_size"])
    ax.set_ylim(0, 115)
    fig.tight_layout()
    _save(fig, "fig10_non_contact", outdir, pdf)


# ---------------------------------------------------------------------------
# REGO-internal time-series figures
# ---------------------------------------------------------------------------

def fig_bond_growth_timeline(m: REGOMetrics, outdir: Path, pdf=None):
    """Fig 11: b_mean and coordination z vs sim time, phase-shaded."""
    if not m.audit_times:
        print("  [skip] No audit time series available.")
        return
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    t = np.array(m.audit_times)
    b = np.array(m.audit_b_mean)
    z = np.array(m.audit_coord)
    phases = m.audit_phase

    # Phase shading
    _shade_phases(ax1, t, phases)
    _shade_phases(ax2, t, phases)

    ax1.plot(t, b, color=REGO_COLOR, linewidth=1.6, label="⟨b⟩ mean bond fraction")
    ax1.axhline(TARGETS["bond_mean"], color=TARGET_COLOR, linestyle="--",
                linewidth=1.1, label=f'Target ⟨b⟩ = {TARGETS["bond_mean"]}')
    ax1.set_ylabel("Mean bond fraction ⟨b⟩", fontsize=STYLE["label_size"])
    ax1.set_ylim(0, 1.05)
    ax1.legend(fontsize=STYLE["legend_size"])
    ax1.set_title("Fig 11 — Bond Growth & Coordination Timeline",
                  fontsize=STYLE["title_size"])

    ax2.plot(t, z, color="#e84b1a", linewidth=1.6, label="Coordination z̄")
    ax2.axhline(TARGETS["coord_z"], color=TARGET_COLOR, linestyle="--",
                linewidth=1.1, label=f'Rigidity threshold z = {TARGETS["coord_z"]}')
    ax2.set_ylabel("Mean coordination z̄", fontsize=STYLE["label_size"])
    ax2.set_xlabel("Simulation time (s)", fontsize=STYLE["label_size"])
    ax2.legend(fontsize=STYLE["legend_size"])

    fig.tight_layout()
    _save(fig, "fig11_bond_growth_timeline", outdir, pdf)


def fig_energy_accumulation(m: REGOMetrics, outdir: Path, pdf=None):
    """Fig 12: Cumulative energy and instantaneous power vs time."""
    if not m.audit_times or not m.audit_energy_cum:
        print("  [skip] No energy audit data.")
        return
    fig, ax1 = plt.subplots(figsize=(9, 4.5))
    t = np.array(m.audit_times)
    E = np.array(m.audit_energy_cum)
    phases = m.audit_phase

    _shade_phases(ax1, t, phases)

    ax1.plot(t, E, color=REGO_COLOR, linewidth=1.8, label="Cumulative heater energy (J)")
    ax1.axhline(TARGETS["energy_J"], color=TARGET_COLOR, linestyle="--",
                linewidth=1.1, label=f'Budget {TARGETS["energy_J"]:.0f} J')
    ax1.set_xlabel("Simulation time (s)", fontsize=STYLE["label_size"])
    ax1.set_ylabel("Cumulative energy (J)", fontsize=STYLE["label_size"])
    ax1.set_title("Fig 12 — Cumulative Energy Accumulation by Phase",
                  fontsize=STYLE["title_size"])
    ax1.legend(fontsize=STYLE["legend_size"])

    # Instantaneous power on twin axis
    ax2 = ax1.twinx()
    dt = np.diff(t, prepend=t[0])
    dE = np.diff(E, prepend=0.0)
    P  = np.where(dt > 0, dE / dt, 0.0)
    # Smooth with 5-point rolling average
    P_smooth = np.convolve(P, np.ones(5)/5, mode="same")
    ax2.plot(t, P_smooth, color="#e8a41a", linewidth=1.0,
             alpha=0.7, label="Heater power (W, smoothed)")
    ax2.set_ylabel("Heater power (W)", fontsize=STYLE["label_size"], color="#e8a41a")
    ax2.tick_params(axis="y", labelcolor="#e8a41a")
    ax2.legend(loc="upper right", fontsize=STYLE["legend_size"])

    fig.tight_layout()
    _save(fig, "fig12_energy_accumulation", outdir, pdf)


def fig_strength_evolution(m: REGOMetrics, outdir: Path, pdf=None):
    """Fig 13: Estimated σ and shape deviation vs time (dual axis)."""
    if not m.audit_times or not m.audit_sigma:
        print("  [skip] No sigma audit data.")
        return
    fig, ax1 = plt.subplots(figsize=(9, 4.5))
    t = np.array(m.audit_times)
    σ = np.array(m.audit_sigma)
    s = np.array(m.audit_shape)
    phases = m.audit_phase

    _shade_phases(ax1, t, phases)

    ax1.plot(t, σ, color=REGO_COLOR, linewidth=1.8, label="σ_est (MPa)")
    ax1.axhline(TARGETS["sigma_MPa"], color=TARGET_COLOR, linestyle="--",
                linewidth=1.1, label=f'Target {TARGETS["sigma_MPa"]} MPa')
    ax1.set_xlabel("Simulation time (s)", fontsize=STYLE["label_size"])
    ax1.set_ylabel("Estimated strength σ (MPa)", fontsize=STYLE["label_size"])
    ax1.set_title("Fig 13 — Strength & Shape Evolution", fontsize=STYLE["title_size"])
    ax1.legend(loc="upper left", fontsize=STYLE["legend_size"])

    ax2 = ax1.twinx()
    ax2.plot(t, s, color="#e84b1a", linewidth=1.2, linestyle="-.",
             alpha=0.85, label="Shape dev (mm)")
    ax2.axhline(TARGETS["shape_dev_mm"], color="#e84b1a", linestyle=":",
                linewidth=0.9, alpha=0.6)
    ax2.set_ylabel("Shape deviation (mm)", fontsize=STYLE["label_size"], color="#e84b1a")
    ax2.tick_params(axis="y", labelcolor="#e84b1a")
    ax2.legend(loc="upper right", fontsize=STYLE["legend_size"])

    fig.tight_layout()
    _save(fig, "fig13_strength_shape_evolution", outdir, pdf)


def fig_aggregate_score_radar(m: REGOMetrics, outdir: Path, pdf=None):
    """Fig 14: Radar/spider chart of all score pillars for REGO."""
    pillars = m.pillar_breakdown()
    labels  = list(pillars.keys())
    # Un-weight: divide each weighted pillar by its weight to get raw [0,1] pillar value
    values  = [pillars[k] / DEFAULT_WEIGHTS[f"w_{k}"] for k in labels]
    values  = list(np.clip(values, 0, 1.5))
    N = len(labels)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    # Close the loop: append first element to end
    values_closed = values + [values[0]]
    angles_closed = angles + [angles[0]]
    labels_display = [l.replace("_", " ").capitalize() for l in labels]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    ax.plot(angles_closed, values_closed, color=REGO_COLOR, linewidth=2.0)
    ax.fill(angles_closed, values_closed, color=REGO_COLOR, alpha=0.20)
    # Target ring at 1.0
    ax.plot(angles_closed, [1.0]*len(angles_closed), color=TARGET_COLOR,
            linewidth=1.0, linestyle="--", alpha=0.6, label="Target = 1.0")
    ax.set_thetagrids(np.degrees(angles), labels_display, fontsize=10)
    ax.set_ylim(0, 1.5)
    ax.set_title("Fig 14 — Aggregate Score Pillar Breakdown (REGO)",
                 fontsize=STYLE["title_size"], pad=18)
    ax.legend(loc="lower right", fontsize=STYLE["legend_size"])
    fig.tight_layout()
    _save(fig, "fig14_radar_pillars", outdir, pdf)


def fig_percolation_breakdown(m: REGOMetrics, outdir: Path, pdf=None):
    """Fig 15: Percolation at multiple bond thresholds — stacked horizontal."""
    thresholds  = ["b>0.001", "b>0.050", "b>0.100", "b>0.300"]
    fracs = [
        m.percolation_all_frac,
        m.percolation_strong_frac,
        m.percolation_b010_frac,
        m.percolation_b030_frac,
    ]
    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ["#1a73e8", "#4a90e8", "#7db3f0", "#b3d4f8"]
    y = np.arange(len(thresholds))
    bars = ax.barh(y, [f*100 for f in fracs], color=colors,
                   height=0.5, edgecolor="white", linewidth=0.8, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(thresholds, fontsize=STYLE["tick_size"])
    ax.set_xlabel("Largest connected cluster (% of N particles)",
                  fontsize=STYLE["label_size"])
    ax.set_title("Fig 15 — Multi-Threshold Percolation (REGO)",
                 fontsize=STYLE["title_size"])
    ax.set_xlim(0, 110)
    ax.axvline(85, color=TARGET_COLOR, linestyle="--", linewidth=1.1,
               label="85% gate (BO criterion)")
    for bar, v in zip(bars, fracs):
        ax.text(v*100 + 1.5, bar.get_y() + bar.get_height()/2,
                f"{v*100:.1f}%", va="center", fontsize=9)
    ax.legend(fontsize=STYLE["legend_size"])
    fig.tight_layout()
    _save(fig, "fig15_percolation_breakdown", outdir, pdf)


# ---------------------------------------------------------------------------
# Helper: phase background shading
# ---------------------------------------------------------------------------
def _shade_phases(ax, t, phases):
    if not phases:
        return
    current = phases[0]
    start   = t[0]
    for i in range(1, len(t)):
        if phases[i] != current or i == len(t) - 1:
            end = t[i]
            c = {"Preheat": "#fff5d6", "Consolidate": "#dceeff",
                 "Cool": "#d6f5e3"}.get(current, "#f0f0f0")
            ax.axvspan(start, end, alpha=0.35, color=c, zorder=0)
            ax.text((start + end)/2, ax.get_ylim()[1] * 0.97,
                    current, ha="center", va="top", fontsize=7,
                    color="#888", style="italic")
            current = phases[i]
            start   = t[i]


# ===========================================================================
# Master runner
# ===========================================================================

def run_all(results_path: str, audit_path: str, outdir_str: str = "rego_figs"):
    from matplotlib.backends.backend_pdf import PdfPages

    _setup()
    outdir = Path(outdir_str)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"\n  Loading metrics from:\n    {results_path}\n    {audit_path}")
    m = REGOMetrics.from_files(results_path, audit_path)
    print(m.summary())

    # Build comparison table, inject live REGO values
    comp = get_technology_comparison()
    comp = inject_rego_into_comparison(comp, m)

    combined_pdf = outdir / "REGO_figures_combined.pdf"
    print(f"\n  Generating figures → {outdir}/")
    with PdfPages(combined_pdf) as pdf:
        fig_energy_vs_tech(comp,        outdir, pdf)
        fig_throughput_vs_tech(comp,    outdir, pdf)
        fig_shape_accuracy(comp,        outdir, pdf)
        fig_strength(comp,              outdir, pdf)
        fig_isru(comp,                  outdir, pdf)
        fig_reversibility(comp,         outdir, pdf)
        fig_feature_size(comp,          outdir, pdf)
        fig_energy_per_mpa(comp,        outdir, pdf)
        fig_complexity(comp,            outdir, pdf)
        fig_non_contact(comp,           outdir, pdf)
        fig_bond_growth_timeline(m,     outdir, pdf)
        fig_energy_accumulation(m,      outdir, pdf)
        fig_strength_evolution(m,       outdir, pdf)
        fig_aggregate_score_radar(m,    outdir, pdf)
        fig_percolation_breakdown(m,    outdir, pdf)

    print(f"\n  Combined PDF → {combined_pdf}")
    print(f"  Done.  {len(list(outdir.glob('*.png')))} PNGs + 1 PDF written.")
    return m, comp


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="REGO graphing suite")
    parser.add_argument("results_json", help="Path to results.json")
    parser.add_argument("audit_json",   help="Path to energy_audit.json")
    parser.add_argument("--outdir",     default="rego_figs", help="Output directory")
    args = parser.parse_args()
    run_all(args.results_json, args.audit_json, args.outdir)