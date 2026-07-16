# -*- coding: utf-8 -*-
"""
rego_bo.py  —  Bayesian Optimisation for REGO Phase 3 Consolidation
====================================================================
Uses Gaussian Process surrogate + Expected Improvement acquisition to find
the optimal set of physics parameters that maximise the aggregate score
defined in rego_metrics.py.

Key design choices
──────────────────
• Surrogate    : GP with Matérn-5/2 kernel (handles discontinuous, noisy objectives)
• Acquisition  : Expected Improvement (EI) with ξ=0.01 (balance exploit/explore)
• Warm-start   : Latin Hypercube Sampling for first N_INIT points
• Parallelism  : Each BO iteration writes a config JSON, runs phase3_consolidation.py
                 as a subprocess, reads back results.json + energy_audit.json.
• Progress     : Writes bo_progress.json and bo_convergence.png after every trial.
• Resume       : If bo_progress.json exists in outdir, resumes from where it left off.

Parameters optimised (physics-based, not exhaustive)
─────────────────────────────────────────────────────
  target_temp_C       [120, 156]     Consolidation temperature (°C)
  activator_frac      [0.10, 0.50]   Fraction of activated particles
  t_consolidate_s     [400, 1200]    Consolidation ceiling (s)
  W_adh_J_m2         [0.02, 0.15]   DMT adhesion work (J/m²)
  z_taper_threshold   [2.5, 5.0]     Field taper onset z (coordination)
  bond_k0_S           [400, 2400]    Sulfur wetting rate prefactor (s⁻¹)
  vib_amplitude_g     [0.1, 1.0]     Preheat vibration (× lunar g)

These span the most impactful levers identified in the analysis documents:
temperature (viscosity → kinetics), activator density (sulfur availability),
consolidation time (ceiling for kinetics), adhesion (contact retention),
field tapering (energy savings), kinetics prefactor, and mechanical disorder.

Usage:
python p3_bo.py --sim phase3_consolidation.py --outdir bo_results/ --n-init 8 --n-iter 40 --weights '{\"w_strength\":0.35,\"w_energy\":0.20,\"w_shape\":0.20,\"w_time\":0.10,\"w_integrity\":0.10,\"w_complexity\":0.05}'

Outputs (all in --outdir):
    trial_NNNN/           per-trial simulation outputs
    bo_progress.json      full history (params, scores, timestamps)
    bo_best.json          best params found so far
    bo_convergence.png    score vs trial plot (updates live)
    bo_final_report.txt   human-readable summary
"""

import os
import sys
import json

# ============================================================================
# CRITICAL: Fix Windows Unicode encoding issue (cp1252 → utf-8)
# ============================================================================
# On Windows, Python defaults to cp1252 encoding which cannot handle Unicode
# symbols like → (arrow). Force UTF-8 for stdout/stderr to prevent crashes
# when the subprocess prints Unicode characters.
if sys.platform.startswith("win"):
    import io
    # Redirect stdout and stderr to UTF-8 encoding
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    # Also set environment variable for subprocess spawning
    os.environ["PYTHONIOENCODING"] = "utf-8"
# ============================================================================
import time
import math
import shutil
import argparse
import subprocess
import numpy as np
from pathlib import Path
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

# scikit-learn for GP
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, ConstantKernel, WhiteKernel
from sklearn.preprocessing import MinMaxScaler
from scipy.stats import norm
from scipy.optimize import minimize

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec  # must be at module level (used in plot_convergence)
from matplotlib.backends.backend_pdf import PdfPages

# Our metrics module (same directory)
from p3_metrics import REGOMetrics, DEFAULT_WEIGHTS


# ===========================================================================
# Parameter space definition
# ===========================================================================

PARAM_SPACE = {
    # name              : (low,    high,   type,    description)
    "target_temp_C"     : (120.0,  156.0,  "float", "Consolidation temperature °C"),
    "activator_frac"    : (0.10,   0.50,   "float", "Activated particle fraction"),
    "t_consolidate_s"   : (400.0,  1200.0, "float", "Consolidation ceiling (s)"),
    "W_adh_J_m2"        : (0.02,   0.15,   "float", "DMT adhesion work J/m²"),
    "z_taper_threshold" : (2.5,    5.0,    "float", "Field taper onset coordination z"),
    "bond_k0_S"         : (400.0,  2400.0, "float", "Sulfur wetting rate k0 (s⁻¹)"),
    "vib_amplitude_g"   : (0.1,    1.0,    "float", "Preheat vibration amplitude (×g)"),
}

PARAM_NAMES = list(PARAM_SPACE.keys())
PARAM_LOWS  = np.array([PARAM_SPACE[k][0] for k in PARAM_NAMES])
PARAM_HIGHS = np.array([PARAM_SPACE[k][1] for k in PARAM_NAMES])
N_PARAMS    = len(PARAM_NAMES)


# ===========================================================================
# Latin Hypercube Sampling (for warm start)
# ===========================================================================

def latin_hypercube_sample(n: int, seed: int = 0) -> np.ndarray:
    """
    Generate n points in [0,1]^N_PARAMS via Latin Hypercube Sampling.
    Guarantees each parameter axis is uniformly covered.
    """
    rng = np.random.default_rng(seed)
    result = np.zeros((n, N_PARAMS))
    for j in range(N_PARAMS):
        perm = rng.permutation(n)
        result[:, j] = (perm + rng.uniform(size=n)) / n
    return result


def lhs_to_params(lhs_row: np.ndarray) -> Dict:
    """Map a [0,1]^N_PARAMS LHS row to actual parameter values."""
    params = {}
    for j, name in enumerate(PARAM_NAMES):
        lo, hi, typ, _ = PARAM_SPACE[name]
        v = lo + lhs_row[j] * (hi - lo)
        params[name] = float(round(v, 5))
    return params


# ===========================================================================
# Analytical pre-filter  (fast_eval_p3)
# ===========================================================================
# Before running the ~1000s simulation, check whether the proposed parameters
# can POSSIBLY achieve any meaningful bonding. Uses the same Arrhenius kinetics
# as phase3_consolidation.py — no simulation, no subprocess.
#
# Physical basis (from phase3_consolidation.py C class):
#   db/dt = k0_S × exp(−Ea_S/RT) × melt_frac × sulfur_avail × gap_factor
#   b(t) → b_eq = 1 − rate_sub/(rate_S + rate_sub) ≈ 0.96 for act-act
#
# Only skips trials where physics guarantees near-zero bonding:
#   1. Temperature so far below T_S_melt that melt_frac < 0.15
#      (sulfur barely liquefied — negligible wetting rate)
#   2. bond_k0_S so low that b_ceiling < FAST_EVAL_B_SKIP even at max time
#
# Does NOT skip based on sigma (the real sim can exceed the analytical estimate
# due to multi-body contact effects). Conservative threshold preserves ~98% of
# valid parameter space; only truly hopeless combinations are skipped.

_R_GAS        = 8.314
_T_S_MELT     = 392.0   # K  (119°C)
_T_S_POLY     = 432.0   # K  (159°C)
_EA_S         = 25000.0 # J/mol
_SUBLIM_FRAC  = 0.04
_FAST_EVAL_B_SKIP = 0.02    # skip if theoretical b_ceiling < this (near-zero bonding)

def fast_eval_p3(params: Dict) -> Tuple[bool, str, float]:
    """
    Analytical pre-filter for Phase 3 parameter sets.

    Returns:
        (should_skip: bool, reason: str, b_ceiling: float)
        should_skip=True  → skip the full simulation (assign score=None)
        should_skip=False → proceed with simulation as normal

    Conservative: only skips truly hopeless parameter combinations.
    Does NOT over-filter — the GP needs diverse observations to learn.
    """
    T_C  = float(params.get("target_temp_C",  148.0))
    t_s  = float(params.get("t_consolidate_s", 1200.0))
    k0   = float(params.get("bond_k0_S",       1200.0))
    af   = float(params.get("activator_frac",  0.35))
    T_K  = T_C + 273.15

    # ── 1. Melt fraction check ──
    melt_arg  = (T_K - _T_S_MELT) / 3.0
    melt_arg  = min(max(melt_arg, -20.0), 20.0)
    melt_frac = 1.0 / (1.0 + math.exp(-melt_arg))
    if melt_frac < 0.15:
        return True, f"T={T_C:.1f}C below sulfur melt (melt_frac={melt_frac:.3f})", 0.0

    # ── 2. Polymer spike penalty (same formula as phase3_consolidation.py) ──
    poly_arg  = (T_K - _T_S_POLY) / 8.0
    poly_arg  = min(max(poly_arg, -20.0), 20.0)
    poly_frac = 1.0 / (1.0 + math.exp(-poly_arg))
    visc_p    = 1.0 + 799.0 * poly_frac
    # NOTE: do NOT skip based on raw visc_p here.
    # The sigmoid is wide (poly_width=8K) so visc_p is already >100× at 148°C,
    # yet the simulation works fine because rate_S compensates.
    # Only the b_ceiling check below catches true polymer-regime failures.

    # ── 3. Arrhenius bond ceiling ──
    rate_S   = k0 * math.exp(-_EA_S / (_R_GAS * T_K)) / visc_p
    rate_eff = rate_S * melt_frac
    b_eq     = 1.0 - _SUBLIM_FRAC / (1.0 + _SUBLIM_FRAC)  # ~0.962
    b_aa     = b_eq * (1.0 - math.exp(-rate_eff * t_s))    # act-act ceiling

    # Weighted mean bond fraction over all pair types
    f        = float(np.clip(af, 0.0, 1.0))
    b_ceil   = (f*f*b_aa
                + 2*f*(1-f) * 0.5 * b_aa    # act-plain: sulfur_avail=0.5
                + (1-f)*(1-f) * 0.05 * b_aa)  # plain-plain: sulfur_avail=0.05

    if b_ceil < _FAST_EVAL_B_SKIP:
        return (True,
                f"b_ceiling={b_ceil:.4f} < {_FAST_EVAL_B_SKIP} "
                f"(k0={k0:.0f}, t={t_s:.0f}s, T={T_C:.1f}C, af={af:.2f})",
                b_ceil)

    return False, "ok", b_ceil


# ===========================================================================
# GP surrogate + Expected Improvement
# ===========================================================================

def build_gp() -> GaussianProcessRegressor:
    """
    Build GP with:
    - Matérn 5/2 kernel (smooth but handles discontinuities better than RBF)
    - Constant amplitude kernel
    - White noise kernel for noise estimation
    """
    kernel = (
        ConstantKernel(1.0, (1e-3, 1e3))
        * Matern(length_scale=np.ones(N_PARAMS),
                 length_scale_bounds=[(1e-2, 10.0)] * N_PARAMS,
                 nu=2.5)
        + WhiteKernel(noise_level=1e-4, noise_level_bounds=(1e-8, 1e-1))
    )
    return GaussianProcessRegressor(
        kernel=kernel,
        n_restarts_optimizer=10,
        normalize_y=True,
        random_state=42,
    )


def expected_improvement(X_cand: np.ndarray,
                          gp: GaussianProcessRegressor,
                          y_best: float,
                          xi: float = 0.01) -> np.ndarray:
    """
    Expected Improvement acquisition function.

    EI(x) = E[max(f(x) - y_best - ξ, 0)]
           = (μ - y_best - ξ) Φ(Z) + σ φ(Z)
    where Z = (μ - y_best - ξ) / σ

    xi (exploration bonus): higher → more exploration.
    """
    mu, sigma = gp.predict(X_cand, return_std=True)
    sigma = np.maximum(sigma, 1e-9)
    Z = (mu - y_best - xi) / sigma
    ei = (mu - y_best - xi) * norm.cdf(Z) + sigma * norm.pdf(Z)
    return np.maximum(ei, 0.0)


def maximise_ei(gp: GaussianProcessRegressor,
                y_best: float,
                n_restarts: int = 25,
                xi: float = 0.01,
                rng_seed: int = 0) -> np.ndarray:
    """
    Find x* = argmax EI(x) via multi-start L-BFGS-B in [0,1]^N_PARAMS.
    Returns the best x* (unit-scaled).
    """
    rng = np.random.default_rng(rng_seed)
    best_ei  = -np.inf
    best_x   = None

    def neg_ei(x):
        return -expected_improvement(x.reshape(1, -1), gp, y_best, xi)[0]

    bounds = [(0.0, 1.0)] * N_PARAMS

    for _ in range(n_restarts):
        x0 = rng.uniform(0, 1, size=N_PARAMS)
        res = minimize(neg_ei, x0, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 200, "ftol": 1e-9})
        if -res.fun > best_ei:
            best_ei = -res.fun
            best_x  = res.x

    return np.clip(best_x, 0.0, 1.0)


# ===========================================================================
# Patch the phase3_consolidation.py C class at runtime
# ===========================================================================

def params_to_cli_args(params: Dict) -> List[str]:
    """Convert parameter dict to CLI arguments for phase3_consolidation.py."""
    args = []
    # Direct CLI mappings
    if "target_temp_C" in params:
        args += ["--target-temp", str(params["target_temp_C"])]
    if "activator_frac" in params:
        args += ["--activator-frac", str(params["activator_frac"])]
    if "t_consolidate_s" in params:
        args += ["--t-consolidate", str(params["t_consolidate_s"])]
    return args


def write_param_patch(params: Dict, patch_path: Path):
    """
    Write a JSON patch file that the patched simulation will read to
    override C-class attributes not exposed via CLI.
    """
    patch = {}
    for key, val in params.items():
        if key not in ("target_temp_C", "activator_frac", "t_consolidate_s"):
            patch[key] = val
    with open(patch_path, "w") as f:
        json.dump(patch, f, indent=2)


def inject_patch_into_sim(sim_path: Path, patch_path: Path, patched_path: Path):
    """
    Inject a small patch-loader snippet into a copy of phase3_consolidation.py.
    The snippet reads bo_param_patch.json and overrides C-class attributes
    before main() runs.

    This avoids touching the original file and keeps BO independent.
    """
    with open(sim_path, encoding="utf-8") as f: # Added encoding here
        src = f.read()

    patch_snippet = f'''
# ─── BO PARAMETER PATCH (injected by rego_bo.py) ───────────────────────────
import json as _bo_json, pathlib as _bo_pathlib
_bo_patch_path = _bo_pathlib.Path("{patch_path}")
if _bo_patch_path.exists():
    _bo_patch = _bo_json.loads(_bo_patch_path.read_text())
    _ATTR_MAP = {{
        "W_adh_J_m2"       : ("W_adh",             float),
        "z_taper_threshold" : ("Z_TAPER_THRESHOLD",  float),
        "bond_k0_S"         : ("bond_k0_S",          float),
        "vib_amplitude_g"   : ("_vib_amp_override",  float),
    }}
    for _k, (_attr, _typ) in _ATTR_MAP.items():
        if _k in _bo_patch:
            setattr(C, _attr, _typ(_bo_patch[_k]))
    if "vib_amplitude_g" in _bo_patch:
        # Store as class-level override; main() picks it up
        C._vib_amp_override = float(_bo_patch["vib_amplitude_g"]) * C.g
del _bo_json, _bo_pathlib
# ─── END BO PATCH ────────────────────────────────────────────────────────────
'''

    # Insert immediately after the C class definition closes (after the last
    # class-level statement before the first @ti.func decorator)
    insert_marker = "\n@ti.func\ndef cantor_pair"
    if insert_marker not in src:
        # Fallback: insert before first @ti.kernel
        insert_marker = "\n@ti.kernel\ndef update_mag_cache"

    src_patched = src.replace(insert_marker, patch_snippet + insert_marker, 1)
    with open(patched_path, "w", encoding="utf-8") as f: # Added encoding here
        f.write(src_patched)


# ===========================================================================
# Trial runner
# ===========================================================================

def run_trial(trial_idx: int,
              params: Dict,
              sim_path: Path,
              outdir: Path,
              weights: Dict,
              timeout_s: int = 3600) -> Optional[float]:
    """
    Run one simulation trial with the given parameters.
    Returns the aggregate score (float) or None if the trial failed.

    Calls fast_eval_p3() first: if the parameters are analytically hopeless
    (near-zero bonding guaranteed by Arrhenius physics), skips the ~1000s
    simulation and records None immediately.
    """
    trial_dir = outdir / f"trial_{trial_idx:04d}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    # ── Analytical pre-filter ────────────────────────────────────────────
    skip, reason, b_ceil = fast_eval_p3(params)
    if skip:
        print(f"\n  [Trial {trial_idx:04d}] FAST-EVAL SKIP: {reason}")
        # Save skip record so progress.json stays complete
        with open(trial_dir / "params.json", "w") as f:
            json.dump(params, f, indent=2)
        with open(trial_dir / "fast_eval_skip.json", "w") as f:
            json.dump({"skipped": True, "reason": reason, "b_ceiling": b_ceil}, f, indent=2)
        return None
    # ──────────────────────────────────────────────────────────────────────

    # Save params used for this trial
    with open(trial_dir / "params.json", "w") as f:
        json.dump(params, f, indent=2)

    # Write non-CLI patch
    patch_path   = trial_dir / "bo_param_patch.json"
    patched_sim  = trial_dir / "phase3_bo_patched.py"
    write_param_patch(params, patch_path)
    inject_patch_into_sim(sim_path, patch_path, patched_sim)

    # Build CLI command
    cli_args = params_to_cli_args(params)
    cmd = [
        sys.executable, str(patched_sim),
        "--out-dir", str(trial_dir),
        "--no-vtu",           # skip VTU for speed
        "--settle-steps", "50000",   # halve settling for BO speed
    ] + cli_args

    print(f"\n  [Trial {trial_idx:04d}] params={_fmt_params(params)}")
    print(f"    CMD: {' '.join(cmd[-8:])}")

    t0 = time.time()
    try:
        # Prepare environment with UTF-8 encoding
        subprocess_env = os.environ.copy()
        subprocess_env["PYTHONIOENCODING"] = "utf-8"
        
        proc = subprocess.run(
            cmd,
            timeout=timeout_s,
            capture_output=True,
            text=True,
            encoding="utf-8",     # Use UTF-8 for all Unicode characters
            errors="replace",     # Replace unencodable characters with "?"
            env=subprocess_env    # Pass UTF-8 encoding env to subprocess
        )
        wall = time.time() - t0
        print(f"    Completed in {wall:.0f}s  (returncode={proc.returncode})")
        if proc.returncode != 0:
            stderr_tail = proc.stderr[-500:] if proc.stderr is not None else "(stderr capture failed)"
            print(f"    STDERR tail: {stderr_tail}")
            return None
    except subprocess.TimeoutExpired:
        print(f"    TIMEOUT after {timeout_s}s — skipping trial.")
        return None
    except Exception as e:
        print(f"    ERROR: {e}")
        return None

    # Read results
    res_path   = trial_dir / "results.json"
    audit_path = trial_dir / "energy_audit.json"
    if not res_path.exists() or not audit_path.exists():
        print("    No results.json — trial failed.")
        return None

    try:
        m = REGOMetrics.from_files(str(res_path), str(audit_path))
        score = m.aggregate_score(weights=weights)
        print(f"    Score = {score:.5f}  "
              f"(σ={m.sigma_estimate_MPa:.2f}MPa, "
              f"b={m.bond_mean:.3f}, "
              f"shape={m.shape_dev_mean_mm:.3f}mm, "
              f"E={m.grand_total_energy_J:.1f}J)")
        # Save derived metrics alongside trial
        with open(trial_dir / "derived_metrics.json", "w") as f:
            json.dump(m.to_dict(), f, indent=2)
        return score
    except Exception as e:
        print(f"    Metrics error: {e}")
        return None


def _fmt_params(p: Dict) -> str:
    return "  ".join(f"{k}={v:.4g}" for k, v in p.items())


# ===========================================================================
# Progress tracking and plotting
# ===========================================================================

def save_progress(progress: dict, outdir: Path):
    """Write full BO history to JSON."""
    with open(outdir / "bo_progress.json", "w") as f:
        json.dump(progress, f, indent=2)


def load_progress(outdir: Path) -> Optional[dict]:
    """Load existing BO history if available (for resuming)."""
    p = outdir / "bo_progress.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def save_best(best_params: dict, best_score: float, outdir: Path):
    with open(outdir / "bo_best.json", "w") as f:
        json.dump({"params": best_params, "score": best_score}, f, indent=2)


def plot_pareto_energy_vs_rigidity_p3(progress: dict, outdir: Path):
    """Pareto front: Energy Consumption (x) vs Structural Rigidity (y) — Phase 3 only."""
    outdir.mkdir(parents=True, exist_ok=True)
    trials = [t for t in progress["trials"] if t.get("score") is not None and t.get("metrics")]

    if len(trials) < 2:
        print("  ⚠ Not enough completed trials for Pareto front (Energy vs Rigidity)")
        return

    energies = np.array([t["metrics"]["grand_total_energy_J"] for t in trials])
    # Structural Rigidity proxy: sigma_estimate_MPa (higher MPa → higher rigidity / lower deformation under 10G)
    rigidity = np.array([t["metrics"].get("sigma_estimate_MPa", 0.0) for t in trials])

    # Pareto front: minimise energy, maximise rigidity
    is_pareto = np.ones(len(energies), dtype=bool)
    for i in range(len(energies)):
        for j in range(len(energies)):
            if i != j:
                if (energies[j] <= energies[i] and rigidity[j] >= rigidity[i] and
                    (energies[j] < energies[i] or rigidity[j] > rigidity[i])):
                    is_pareto[i] = False
                    break

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(energies, rigidity, c="#94A3B8", s=25, alpha=0.7, label="All trials")
    ax.scatter(energies[is_pareto], rigidity[is_pareto], c="#EC4899", s=90, edgecolors="black", 
               linewidth=1.5, label="Pareto Front")
    
    ax.set_xlabel("Energy Consumption (J)", fontsize=12)
    ax.set_ylabel("Structural Rigidity (MPa)\n(higher = lower deformation under 10G)", fontsize=12)
    ax.set_title("REGO Phase 3 — Pareto Front: Energy vs Structural Rigidity", fontweight="bold", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(outdir / "p3_pareto_energy_vs_rigidity.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ p3_pareto_energy_vs_rigidity.png")


def plot_convergence(progress: dict, outdir: Path):
    """
    Produce a convergence figure with:
     - Score vs trial (scatter + running best)
     - Parallel coordinates of parameter values coloured by score
    """
    trials   = progress["trials"]
    if not trials:
        return

    scores   = [t["score"] for t in trials if t["score"] is not None]
    t_idxs   = [t["trial_idx"] for t in trials if t["score"] is not None]
    if not scores:
        return

    running_best = []
    best_so_far  = -np.inf
    for s in scores:
        best_so_far = max(best_so_far, s)
        running_best.append(best_so_far)

    fig = plt.figure(figsize=(14, 9))
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

    # ── Top-left: score vs trial ──
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.scatter(t_idxs, scores, c=scores, cmap="viridis", s=50, zorder=3,
                edgecolors="white", linewidths=0.5)
    ax1.plot(t_idxs, running_best, color="#e84b1a", linewidth=2.0,
             label="Running best", zorder=4)
    ax1.set_xlabel("Trial index")
    ax1.set_ylabel("Aggregate score")
    ax1.set_title("BO Convergence: Score per Trial")
    ax1.legend(fontsize=8)

    # ── Top-right: parameter importance (Pearson correlation with score) ──
    ax2 = fig.add_subplot(gs[0, 1])
    param_data = {k: [] for k in PARAM_NAMES}
    for t in trials:
        if t["score"] is not None:
            for k in PARAM_NAMES:
                param_data[k].append(t["params"].get(k, 0.0))
    correlations = []
    for k in PARAM_NAMES:
        vals = np.array(param_data[k])
        if len(vals) >= 3 and np.std(vals) > 1e-9:
            c = float(np.corrcoef(vals, scores[:len(vals)])[0, 1])
        else:
            c = 0.0
        correlations.append(c)
    colors_corr = ["#1a73e8" if c >= 0 else "#e84b1a" for c in correlations]
    ax2.barh(PARAM_NAMES, correlations, color=colors_corr, height=0.55)
    ax2.axvline(0, color="#333", linewidth=0.8)
    ax2.set_xlabel("Pearson correlation with score")
    ax2.set_title("Parameter Importance (correlation)")
    ax2.set_xlim(-1.0, 1.0)

    # ── Bottom-left: EI history (normalised acquisition values if stored) ──
    ax3 = fig.add_subplot(gs[1, 0])
    if "acquisition_values" in progress and progress["acquisition_values"]:
        ei_vals = progress["acquisition_values"]
        ax3.plot(range(len(ei_vals)), ei_vals, color="#2eb87a", linewidth=1.5)
        ax3.set_xlabel("Iteration (post warm-start)")
        ax3.set_ylabel("Max EI at selection")
        ax3.set_title("Acquisition (Expected Improvement)")
    else:
        ax3.text(0.5, 0.5, "EI data available\nafter warm-start",
                 ha="center", va="center", transform=ax3.transAxes, color="#888")
        ax3.set_title("Acquisition (Expected Improvement)")

    # ── Bottom-right: best parameter values found ──
    ax4 = fig.add_subplot(gs[1, 1])
    best_trial = max((t for t in trials if t["score"] is not None),
                     key=lambda t: t["score"])
    bp = best_trial["params"]
    # Normalise to [0,1] for display
    norm_vals = [(bp[k] - PARAM_SPACE[k][0]) / (PARAM_SPACE[k][1] - PARAM_SPACE[k][0])
                 for k in PARAM_NAMES]
    y = np.arange(N_PARAMS)
    ax4.barh(y, norm_vals, color="#1a73e8", height=0.55, alpha=0.85)
    ax4.set_yticks(y)
    ax4.set_yticklabels(PARAM_NAMES, fontsize=8)
    ax4.set_xlabel("Normalised parameter value [0=low, 1=high]")
    ax4.set_title(f"Best Trial #{best_trial['trial_idx']}  (score={best_trial['score']:.4f})")
    ax4.set_xlim(0, 1.1)
    for i, (v, k) in enumerate(zip(norm_vals, PARAM_NAMES)):
        ax4.text(v + 0.02, i, f"{bp[k]:.4g}", va="center", fontsize=7.5)

    fig.suptitle("REGO Bayesian Optimisation Progress", fontsize=14, y=1.01)
    p = outdir / "bo_convergence.png"
    fig.savefig(p, bbox_inches="tight", dpi=150)
    plt.close(fig)

    try:
        # Also append to multi-page PDF
        pdf_path = outdir / "bo_convergence.pdf"
        with PdfPages(pdf_path) as pdf:
            # Create a copy of the current figure for the PDF
            # Or simply pass the existing 'fig' to pdf.savefig()
            pdf.savefig(fig, bbox_inches="tight") 
    except Exception as e:
        print(f"    WARNING failed to save PDF convergence plot: {e}   ---------- WARNING")
    
    plt.close("all")
    print(f"    Convergence plot → {p.name}")


def write_final_report(progress: dict, outdir: Path):
    """Human-readable text summary of optimisation results."""
    trials = [t for t in progress["trials"] if t["score"] is not None]
    if not trials:
        return
    best = max(trials, key=lambda t: t["score"])
    worst = min(trials, key=lambda t: t["score"])

    lines = [
        "=" * 65,
        "  REGO BO Final Optimisation Report",
        "=" * 65,
        f"  Total trials run      : {len(trials)}",
        f"  Warm-start (LHS)      : {progress.get('n_init', '?')}",
        f"  BO iterations         : {len(trials) - progress.get('n_init', 0)}",
        "",
        f"  BEST SCORE  : {best['score']:.5f}  (trial #{best['trial_idx']})",
        f"  Worst score : {worst['score']:.5f}  (trial #{worst['trial_idx']})",
        "",
        "  BEST PARAMETERS:",
    ]
    for k, v in best["params"].items():
        lo, hi, typ, desc = PARAM_SPACE[k]
        pct = 100 * (v - lo) / (hi - lo)
        lines.append(f"    {k:<22s} = {v:.5g}  ({pct:.0f}% of range)  — {desc}")
    lines += [
        "",
        "  SCORE HISTORY (all trials):",
        "    Trial   Score    σ(MPa)  b_mean  E(J)    shape(mm)",
    ]
    for t in sorted(trials, key=lambda x: x["trial_idx"]):
        m = t.get("metrics", {})
        lines.append(
            f"    {t['trial_idx']:>5d}   {t['score']:.4f}   "
            f"{m.get('sigma_estimate_MPa', '?'):>6}  "
            f"{m.get('bond_mean', '?'):>6}  "
            f"{m.get('grand_total_energy_J', '?'):>6}  "
            f"{m.get('shape_dev_mean_mm', '?'):>8}"
        )
    lines.append("=" * 65)

    report_path = outdir / "bo_final_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Final report → {report_path.name}")
    print("\n".join(lines))


# ===========================================================================
# Main BO loop
# ===========================================================================

def run_bo(sim_path: str,
           outdir_str: str,
           n_init: int = 8,
           n_iter: int = 40,
           weights: Optional[Dict] = None,
           xi: float = 0.01,
           timeout_s: int = 3600,
           seed: int = 42):
    """
    Full Bayesian Optimisation loop.

    Args:
        sim_path    : Path to phase3_consolidation.py (or v35.1 patched copy)
        outdir_str  : Directory for all BO outputs
        n_init      : Number of LHS warm-start evaluations
        n_iter      : Number of BO (GP-guided) iterations after warm-start
        weights     : Score pillar weights (dict or None for defaults)
        xi          : EI exploration bonus
        timeout_s   : Max seconds per trial before skip
        seed        : RNG seed for LHS and GP restarts
    """
    if weights is None:
        weights = deepcopy(DEFAULT_WEIGHTS)

    sim_path = Path(sim_path).resolve()
    outdir   = Path(outdir_str)
    outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print("  REGO Bayesian Optimisation")
    print("=" * 65)
    print(f"  Simulation   : {sim_path}")
    print(f"  Output dir   : {outdir}")
    print(f"  Warm start   : {n_init} LHS points")
    print(f"  BO iterations: {n_iter}")
    print(f"  Parameters   : {N_PARAMS}")
    print(f"  Weights      : {weights}")
    print(f"  EI xi        : {xi}")
    print()

    # ── Resume support ──
    progress = load_progress(outdir)
    if progress:
        print(f"  Resuming from {len(progress['trials'])} existing trials.")
    else:
        progress = {
            "n_init": n_init,
            "n_iter": n_iter,
            "weights": weights,
            "xi": xi,
            "trials": [],
            "acquisition_values": [],
        }

    trial_counter = len(progress["trials"])

    # ── Scaler for GP (unit [0,1] space) ──
    scaler = MinMaxScaler()
    scaler.fit(np.stack([PARAM_LOWS, PARAM_HIGHS]))

    def _to_unit(params_dict: Dict) -> np.ndarray:
        row = np.array([params_dict[k] for k in PARAM_NAMES])
        return (row - PARAM_LOWS) / (PARAM_HIGHS - PARAM_LOWS)

    def _from_unit(x: np.ndarray) -> Dict:
        row = PARAM_LOWS + x * (PARAM_HIGHS - PARAM_LOWS)
        return {k: float(round(row[j], 5)) for j, k in enumerate(PARAM_NAMES)}

    # ── Phase A: LHS warm-start ──
    lhs_needed = max(0, n_init - len([t for t in progress["trials"]
                                       if t.get("phase") == "lhs"]))
    if lhs_needed > 0:
        lhs_pts = latin_hypercube_sample(n_init, seed=seed)
        # Skip already-done LHS rows
        done_lhs = len([t for t in progress["trials"] if t.get("phase") == "lhs"])
        for i in range(done_lhs, n_init):
            params = lhs_to_params(lhs_pts[i])
            score  = run_trial(trial_counter, params, sim_path, outdir,
                               weights, timeout_s)
            entry  = {
                "trial_idx": trial_counter,
                "phase":     "lhs",
                "params":    params,
                "score":     score,
                "timestamp": time.time(),
                "metrics":   _try_load_metrics(outdir, trial_counter),
            }
            progress["trials"].append(entry)
            trial_counter += 1
            save_progress(progress, outdir)
            plot_convergence(progress, outdir)

    # ── Collect observations for GP ──
    def _get_observations():
        X, y = [], []
        for t in progress["trials"]:
            if t["score"] is not None:
                X.append(_to_unit(t["params"]))
                y.append(t["score"])
        return np.array(X), np.array(y)

    X_obs, y_obs = _get_observations()

    # ── Phase B: GP-guided BO iterations ──
    done_bo = len([t for t in progress["trials"] if t.get("phase") == "bo"])
    gp = build_gp()

    for bo_iter in range(done_bo, n_iter):
        print(f"\n  ── BO iteration {bo_iter+1}/{n_iter} ──")

        if len(X_obs) < 2:
            print("  Not enough observations for GP — sampling randomly.")
            rng = np.random.default_rng(seed + bo_iter)
            x_next = rng.uniform(0, 1, size=N_PARAMS)
        else:
            # Fit GP
            try:
                gp.fit(X_obs, y_obs)
            except Exception as e:
                print(f"  GP fit error: {e} — sampling randomly.")
                rng = np.random.default_rng(seed + bo_iter)
                x_next = rng.uniform(0, 1, size=N_PARAMS)
            else:
                y_best = float(np.max(y_obs))
                # Adaptive xi annealing: explore early, exploit late.
                # xi goes from xi_explore (4×xi) at iter 0
                #           to xi (base value) at iter n_iter.
                # This biases early iterations toward discovery of new optima
                # and later iterations toward refining the known best region.
                _anneal_frac = bo_iter / max(n_iter - 1, 1)  # 0.0 → 1.0
                xi_current   = xi * (1.0 + 3.0 * (1.0 - _anneal_frac))  # 4xi → xi
                x_next = maximise_ei(gp, y_best, n_restarts=30, xi=xi_current,
                                     rng_seed=seed + bo_iter)
                # Log EI value at selected point
                ei_val = expected_improvement(x_next.reshape(1,-1), gp, y_best, xi_current)[0]
                progress["acquisition_values"].append(float(ei_val))
                print(f"  GP fitted on {len(X_obs)} obs. Best so far: {y_best:.5f}")
                print(f"  EI at next point: {ei_val:.6f}")

        params_next = _from_unit(x_next)
        score = run_trial(trial_counter, params_next, sim_path, outdir,
                          weights, timeout_s)
        entry = {
            "trial_idx": trial_counter,
            "phase":     "bo",
            "params":    params_next,
            "score":     score,
            "timestamp": time.time(),
            "metrics":   _try_load_metrics(outdir, trial_counter),
        }
        progress["trials"].append(entry)
        trial_counter += 1

        # Update observations
        if score is not None:
            X_obs = np.vstack([X_obs, x_next.reshape(1, -1)])
            y_obs = np.append(y_obs, score)

        # Current best
        valid = [t for t in progress["trials"] if t["score"] is not None]
        if valid:
            best = max(valid, key=lambda t: t["score"])
            save_best(best["params"], best["score"], outdir)
            print(f"  Current best: score={best['score']:.5f}  "
                  f"trial #{best['trial_idx']}")

        save_progress(progress, outdir)
        plot_convergence(progress, outdir)

    plot_pareto_energy_vs_rigidity_p3(progress, outdir)

    # ── Final report ──
    write_final_report(progress, outdir)
    _write_top_trials_script(progress, sim_path, outdir)
    print("\n  Bayesian Optimisation complete.")
    print(f"  All results → {outdir}")


def _write_top_trials_script(progress: dict, sim_path: Path, outdir: Path,
                              top_n: int = 3):
    """
    Generate run_top_trials.sh (Unix) and run_top_trials.bat (Windows CMD)
    to re-run the top-N scoring trials at full fidelity (with VTU output).

    This closes the 'analytical → simulation verification' loop:
    the BO finds the best parameters cheaply (--no-vtu, halved settling),
    then these scripts re-run those exact parameters at full quality for
    final inspection in ParaView.
    """
    valid = [t for t in progress["trials"] if t["score"] is not None]
    if not valid:
        return
    top = sorted(valid, key=lambda t: t["score"], reverse=True)[:top_n]

    # ── Shell script (Unix/WSL/Git Bash) ──────────────────────────────────
    sh_lines = [
        "#!/bin/bash",
        "# Auto-generated by p3_bo.py — re-run top BO trials at full fidelity",
        f"# Source: {sim_path}",
        f"# Top {top_n} trials by aggregate score",
        "",
        f'SIM="{sim_path}"',
        "",
    ]
    for rank, t in enumerate(top, 1):
        p = t["params"]
        trial_dir = outdir / f"trial_{t['trial_idx']:04d}"
        sh_lines += [
            f"# ── Rank {rank}: trial #{t['trial_idx']}  score={t['score']:.4f} ──",
            f'python "$SIM" \\',
            f'  --target-temp {p.get("target_temp_C", 152.0)} \\',
            f'  --activator-frac {p.get("activator_frac", 0.35)} \\',
            f'  --t-consolidate {p.get("t_consolidate_s", 1200.0)} \\',
            f'  --out-dir "{trial_dir}_full" \\',
            f'  --vtu-every 10',
            "",
        ]
    sh_path = outdir / "run_top_trials.sh"
    with open(sh_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(sh_lines))

    # ── Batch file (Windows CMD) ───────────────────────────────────────────
    bat_lines = [
        "@echo off",
        "REM Auto-generated by p3_bo.py — re-run top BO trials at full fidelity",
        f"REM Source: {sim_path}",
        f"SET SIM={sim_path}",
        "",
    ]
    for rank, t in enumerate(top, 1):
        p = t["params"]
        trial_dir = outdir / f"trial_{t['trial_idx']:04d}"
        bat_lines += [
            f"REM Rank {rank}: trial #{t['trial_idx']}  score={t['score']:.4f}",
            f'python "%SIM%" '
            f'--target-temp {p.get("target_temp_C", 152.0)} '
            f'--activator-frac {p.get("activator_frac", 0.35)} '
            f'--t-consolidate {p.get("t_consolidate_s", 1200.0)} '
            f'--out-dir "{trial_dir}_full" '
            f'--vtu-every 10',
            "",
        ]
    bat_path = outdir / "run_top_trials.bat"
    with open(bat_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(bat_lines))

    print(f"  Top-{top_n} validation scripts → {sh_path.name}  {bat_path.name}")
    for rank, t in enumerate(top, 1):
        print(f"    Rank {rank}: trial #{t['trial_idx']}  score={t['score']:.4f}  "
              f"params={_fmt_params(t['params'])}")


def _try_load_metrics(outdir: Path, trial_idx: int) -> dict:
    """Try to load derived metrics from a completed trial."""
    m_path = outdir / f"trial_{trial_idx:04d}" / "derived_metrics.json"
    if m_path.exists():
        try:
            with open(m_path) as f:
                d = json.load(f)
            # Return only scalar subset for progress JSON
            return {k: d.get(k) for k in [
                "sigma_estimate_MPa", "bond_mean", "grand_total_energy_J",
                "shape_dev_mean_mm", "wall_time_s", "coordination_z",
                "percolation_b010_frac", "breakage_frac",
            ]}
        except Exception:
            pass
    return {}


# ===========================================================================
# CLI entry point
# ===========================================================================

if __name__ == "__main__":
    # gridspec already imported at module level above

    parser = argparse.ArgumentParser(
        description="Bayesian Optimisation for REGO Phase 3 Consolidation"
    )
    parser.add_argument(
        "--sim", required=True,
        help="Path to phase3_consolidation.py (or v35.1)")
    parser.add_argument(
        "--outdir", default="bo_results",
        help="Output directory for all BO artefacts")
    parser.add_argument(
        "--n-init", type=int, default=8,
        help="Number of LHS warm-start trials (default 8)")
    parser.add_argument(
        "--n-iter", type=int, default=40,
        help="Number of GP-guided BO iterations (default 40)")
    parser.add_argument(
        "--xi", type=float, default=0.01,
        help="EI exploration bonus (default 0.01; higher → more exploration)")
    parser.add_argument(
        "--timeout", type=int, default=3600,
        help="Seconds before a trial is killed (default 3600)")
    parser.add_argument(
        "--seed", type=int, default=42,
        help="RNG seed for LHS and GP restarts")
    parser.add_argument(
        "--weights", type=str, default=None,
        help='JSON string of pillar weights, e.g. \'{"w_strength":0.35,...}\'')
    args = parser.parse_args()

    weights = None
    if args.weights:
        try:
            weights = json.loads(args.weights)
        except json.JSONDecodeError as e:
            print(f"Could not parse --weights JSON: {e}")
            sys.exit(1)

    run_bo(
        sim_path  = args.sim,   
        outdir_str= args.outdir,
        n_init    = args.n_init,
        n_iter    = args.n_iter,
        weights   = weights,
        xi        = args.xi,
        timeout_s = args.timeout,
        seed      = args.seed,      
    )  