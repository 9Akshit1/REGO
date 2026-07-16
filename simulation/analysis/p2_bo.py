#!/usr/bin/env python3
"""
REGO Phase 2 — Bayesian Optimisation of Magnetic Control Parameters
====================================================================
Finds the globally optimal control parameter set that minimises the
5-dimensional aggregate cost function:

    Cost = w1·(E/Eref) + w2·(T/Tref) + w3·(Δshp/Δref)
         + w4·(1 − Percolation_frac) + w5·Complexity_norm

Implementation:
  1. Gaussian Process (GP) surrogate model (sklearn GaussianProcessRegressor)
  2. Upper Confidence Bound (UCB) acquisition function
  3. Latin Hypercube Sampling for initial space-filling design
  4. Full analytical physics-based evaluations (no simulation runtime needed)
  5. Convergence tracking + full progress graphs

Parameters being optimised (10 key parameters, all physically motivated):
  1.  m_trap          — transport dipole moment (A·m²)       [1e-4, 2e-3]
  2.  m_shape         — shaping dipole moment (A·m²)         [5e-4, 3e-3]
  3.  m_corner        — corner quadrupole moment (A·m²)      [1e-4, 1e-3]
  4.  d_lead          — lead distance (trap→cluster) (m)     [1e-4, 1e-3]
  5.  chi_eff_target  — target effective χ after beneficiation[1e-3, 0.15]
  6.  T_transport     — transport phase budget (s)            [1.0, 8.0]
  7.  T_shape         — shaping phase duration (s)           [2.0, 12.0]
  8.  GRAD_B2_CLAMP   — gradient clamp ceiling (T²/m)        [500, 5000]
  9.  k_hold_strength — hold spring strength (rel. to m_trap) [0.3, 1.5]
  10. n_radial_sweeps — number of shaping sweep lines         [4, 16]

Physics is evaluated analytically using the same models as rego_metrics.py.
"""

import math, json, time, warnings
import numpy as np
from pathlib import Path
from typing import Tuple, List, Dict, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as mgrid

from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import (Matern, ConstantKernel, WhiteKernel)

# ── Import from our metrics module ────────────────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent))
from p2_metrics import (
    MU0, PI, _MU0_4PI, VP, MP, G_LUNAR,
    COIL_N_TURNS, COIL_AREA, COIL_R_OHM,
    N_PARTICLES, R_PARTICLE, CHI_DEFAULT, MSAT,
    T_SETTLE, T_INTERLUDE_3x, T_HOLD,
    T_CLUSTER, N_DIPOLES,
    DEFAULT_WEIGHTS, REFS,
    coil_power_from_moment, chi_eff_scalar,
    compute_complexity
)

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════
# PARAMETER SPACE DEFINITION
# ═══════════════════════════════════════════════════════════════════════════

PARAM_BOUNDS = np.array([
    # [lower,    upper]
    [1e-4,       2e-3],    # 0: m_trap  (A·m²)
    [5e-4,       3e-3],    # 1: m_shape (A·m²)
    [1e-4,       1e-3],    # 2: m_corner (A·m²)
    [1e-4,       1e-3],    # 3: d_lead  (m)
    [1e-3,       0.15],    # 4: chi_eff_target
    [1.0,        8.0],     # 5: T_transport (s, per cluster)
    [2.0,        12.0],    # 6: T_shape (s, total)
    [500.0,      5000.0],  # 7: GRAD_B2_CLAMP (T²/m)
    [0.3,        1.5],     # 8: k_hold_strength (dimensionless)
    [4.0,        16.0],    # 9: n_radial_sweeps (rounded to int)
])

PARAM_NAMES = [
    "m_trap",
    "m_shape",
    "m_corner",
    "d_lead",
    "chi_eff_target",
    "T_transport",
    "T_shape",
    "GRAD_B2_CLAMP",
    "k_hold_strength",
    "n_radial_sweeps",
]

PARAM_UNITS = [
    "A·m²", "A·m²", "A·m²", "m", "—", "s", "s", "T²/m", "—", "—"
]

# Default (v19) parameter point for reference
PARAM_DEFAULT = np.array([
    0.0006,    # m_trap
    0.0012,    # m_shape
    0.0006,    # m_corner
    0.3e-3,    # d_lead
    0.15,      # chi_eff_target
    4.0,       # T_transport
    8.0,       # T_shape
    2000.0,    # GRAD_B2_CLAMP
    0.5,       # k_hold_strength (relative)
    8.0,       # n_radial_sweeps
])

# ═══════════════════════════════════════════════════════════════════════════
# ANALYTICAL COST FUNCTION
# ═══════════════════════════════════════════════════════════════════════════

def _B_axial_from_dipole(m: float, d: float) -> float:
    """B field along dipole axis at distance d (point dipole)."""
    return _MU0_4PI * 2.0 * m / max(d, 1e-9)**3

def _gradB2_axial(m: float, d: float) -> float:
    """|∇B²| along axis at distance d from dipole (analytical)."""
    return _MU0_4PI * 6.0 * m**2 / max(d, 1e-9)**4

def evaluate_cost(params: np.ndarray, weights: np.ndarray = DEFAULT_WEIGHTS) -> Tuple[float, Dict]:
    """
    Full analytical cost evaluation for a parameter vector.

    Returns:
        cost   — scalar, lower is better
        detail — dict with all metric values and intermediate quantities
    """
    m_trap, m_shape, m_corner, d_lead, chi, T_transport, T_shape, \
        grad_clamp, k_hold, n_sweeps = params

    n_sweeps = int(round(n_sweeps))
    n_sweeps = max(1, n_sweeps)
    T_transport = max(0.1, T_transport)
    T_shape     = max(0.1, T_shape)
    chi         = float(np.clip(chi, 1e-5, 1.0))

    # ── 1. Trap force viability ────────────────────────────────────────────
    gradB2_trap = min(_gradB2_axial(m_trap, d_lead), grad_clamp)
    chi_e       = chi_eff_scalar(_B_axial_from_dipole(m_trap, d_lead), chi, MSAT)
    kelvin_pf   = VP * chi_e / (2 * MU0)
    F_single    = kelvin_pf * gradB2_trap          # force on 1 particle
    N_cluster   = N_PARTICLES // 4
    F_cluster   = F_single * N_cluster
    W_cluster   = MP * G_LUNAR * N_cluster
    F_over_W    = F_cluster / max(W_cluster, 1e-30)
    viable      = F_over_W >= 1.0

    # Hard fast-return for deeply non-viable configurations.
    # When F/W < 0.05 the trap cannot even hold a stationary particle
    # against lunar gravity — no amount of other parameter tuning fixes this.
    # Returning a large sentinel cost (20.0) immediately:
    #   1. Avoids computing the rest of evaluate_cost unnecessarily
    #   2. Gives the GP a clear, consistent signal about the hard boundary
    #      (the continuous penalty alone is sometimes too smooth for the GP
    #       to learn that chi < min_viable is a cliff, not a slope)
    # Threshold 0.05: conservative — chi sweep in p2_metrics shows
    # F/W < 0.05 means chi is at least 20× below the minimum needed.
    if F_over_W < 0.05:
        detail_non_viable = dict(
            cost=20.0, energy_MJ_per_kg=0.0, time_hours=0.0,
            rms_mm=99.0, stability_norm=0.0, complexity_norm=1.0,
            viable=False, F_over_W=F_over_W,
            viability_penalty=20.0,
            total_energy_J=0.0, T_total_sim=0.0,
            k_spring=0.0, F_single=F_single,
            e_term=0.0, t_term=0.0, a_term=0.0,
            s_term=weights[3], c_term=weights[4],
        )
        return 20.0, detail_non_viable

    # Penalty if not viable (particle won't lift off floor)
    viability_penalty = max(0.0, 1.0 - F_over_W) * 5.0   # steep penalty

    # ── 2. Energy ─────────────────────────────────────────────────────────
    T_transport_4x = 4 * T_transport
    T_total = T_SETTLE + T_CLUSTER + T_transport_4x + T_INTERLUDE_3x + T_shape + T_HOLD

    # Active dipole counts per phase
    P_corner = coil_power_from_moment(m_corner)
    P_trap   = coil_power_from_moment(m_trap)
    P_shape  = coil_power_from_moment(m_shape)

    # Hold dipoles: proportional to k_hold × m_trap
    m_hold   = k_hold * m_trap
    P_hold   = coil_power_from_moment(m_hold)

    phases_energy = {
        "settle":    T_SETTLE        * (8 * P_corner + 0),
        "cluster":   T_CLUSTER       * (8 * P_corner + 4 * P_trap),
        "transport": T_transport_4x  * (8 * P_corner + 4 * P_trap),
        "interlude": T_INTERLUDE_3x  * (8 * P_corner + 4 * P_trap),
        "shape":     T_shape         * (4 * P_shape + 4 * P_hold),
        "hold":      T_HOLD          * (4 * P_hold),
    }
    total_E_J    = sum(phases_energy.values())

    # Scale to 1 m³ structure
    STRUCTURE_MASS = 0.60 * 3100.0
    n_real = STRUCTURE_MASS / MP
    n_sim  = N_PARTICLES
    E_scaled_J     = total_E_J * (n_real / n_sim)
    energy_MJ_per_kg = E_scaled_J / STRUCTURE_MASS / 1e6

    # ── 3. Build time ──────────────────────────────────────────────────────
    # Realistic parallel: 100 domains simultaneously
    P_parallel   = 100
    t_sequential = T_total * (100**3)    # 100x scale, cubic
    t_parallel_s = T_total * math.ceil(100**3 / P_parallel)
    t_setup_s    = 600.0
    time_hours   = (t_parallel_s + t_setup_s) / 3600.0

    # ── 4. Shape accuracy ─────────────────────────────────────────────────
    # Trap stiffness ∝ chi × gradient
    # RMS single-particle thermal deviation from residual KE
    # Residual KE depends on damping (via e_n), here use fixed estimate
    # scaled by chi and gradient clamp ratio
    # k_spring = kelvin_pf × d²B²/dr² at trap
    d2B2_dr2    = _MU0_4PI * 12 * m_trap**2 / max(d_lead, 1e-9)**5   # approx
    k_spring    = kelvin_pf * abs(d2B2_dr2)
    KE_residual = 1e-15    # J per particle (from simulation)
    sigma_single = math.sqrt(2 * KE_residual / max(k_spring, 1e-15)) * 1e3  # mm
    rms_mm       = sigma_single / math.sqrt(N_cluster)

    # Accuracy bonus/penalty from shaping sweep density
    # More sweeps → better coverage → lower RMS by ~1/sqrt(n_sweeps)
    rms_mm = rms_mm / math.sqrt(n_sweeps / 8.0)  # normalised to 8 sweeps baseline
    rms_mm = max(rms_mm, 1e-4)   # physical floor

    # ── 5. Stability ──────────────────────────────────────────────────────
    E_eff  = 2e5; nu = 0.25
    E_star = E_eff / (2*(1 - nu**2))
    R_star = R_PARTICLE / 2
    W_p    = MP * G_LUNAR
    delta  = (3 * W_p / (4 * E_star * math.sqrt(R_star)))**(2/3)
    k_hertz = (4/3) * E_star * math.sqrt(R_star * max(delta, 1e-15))

    # Magnetic cohesion with actual chi
    B_inter   = 1e-3
    chi_inter = chi_eff_scalar(B_inter, chi, MSAT)
    M_ind     = chi_inter * B_inter / MU0
    F_cohesion = (3*MU0/(4*PI)) * M_ind**2 * VP / (2*R_PARTICLE)**4
    Z_coord    = 6.0
    Ap         = PI * R_PARTICLE**2
    F_contact  = k_hertz * delta + F_cohesion
    sigma_comp = Z_coord * F_contact / Ap
    stability_norm = sigma_comp / (sigma_comp + 200e3)
    stability_norm = float(np.clip(stability_norm, 0.0, 1.0))

    # ── 6. Complexity ─────────────────────────────────────────────────────
    # n_sources = effective number of independent dipole control channels
    # n_sweeps linearly scales control complexity
    n_src_eff   = N_DIPOLES * (n_sweeps / 8.0)
    C_raw       = n_src_eff * math.log2(6) * 0.7   # 6 phases, 0.7 precision
    C_robot_ref = 50 * math.log2(10) * 1.0
    complexity_norm = min(C_raw / C_robot_ref, 1.0)

    # ── Aggregate cost ─────────────────────────────────────────────────────
    w1, w2, w3, w4, w5 = weights
    e_term  = w1 * (energy_MJ_per_kg / REFS["energy_MJ_per_kg"])
    t_term  = w2 * (time_hours        / REFS["time_hours"])
    a_term  = w3 * (rms_mm            / REFS["rms_mm"])
    s_term  = w4 * (1.0 - stability_norm)
    c_term  = w5 * complexity_norm

    cost = e_term + t_term + a_term + s_term + c_term + viability_penalty

    detail = dict(
        cost=cost,
        energy_MJ_per_kg=energy_MJ_per_kg,
        time_hours=time_hours,
        rms_mm=rms_mm,
        stability_norm=stability_norm,
        complexity_norm=complexity_norm,
        viable=viable,
        F_over_W=F_over_W,
        viability_penalty=viability_penalty,
        total_energy_J=total_E_J,
        T_total_sim=T_total,
        k_spring=k_spring,
        F_single=F_single,
        e_term=e_term, t_term=t_term, a_term=a_term,
        s_term=s_term, c_term=c_term,
    )
    return cost, detail


# ═══════════════════════════════════════════════════════════════════════════
# LATIN HYPERCUBE SAMPLING
# ═══════════════════════════════════════════════════════════════════════════

def latin_hypercube_sample(n_samples: int, bounds: np.ndarray,
                            seed: int = 42) -> np.ndarray:
    """
    Generate n_samples points via Latin Hypercube Sampling.
    Provides much better space coverage than random sampling.
    """
    rng = np.random.RandomState(seed)
    n_params = bounds.shape[0]
    samples  = np.zeros((n_samples, n_params))
    for j in range(n_params):
        lo, hi = bounds[j]
        # Partition [lo, hi] into n_samples equal strata, pick one point each
        cuts = np.linspace(lo, hi, n_samples + 1)
        points = rng.uniform(cuts[:-1], cuts[1:])
        samples[:, j] = rng.permutation(points)
    return samples


# ═══════════════════════════════════════════════════════════════════════════
# ACQUISITION FUNCTION — Upper Confidence Bound
# ═══════════════════════════════════════════════════════════════════════════

def acquisition_ucb(X_cand: np.ndarray, gp: GaussianProcessRegressor,
                     kappa: float = 2.0) -> np.ndarray:
    """
    UCB acquisition: a(x) = μ(x) - κ·σ(x)   [minimising, so subtract σ]
    Lower values are more promising (we minimise cost).
    κ controls exploration/exploitation trade-off.
    """
    mu, sigma = gp.predict(X_cand, return_std=True)
    return mu - kappa * sigma


# ═══════════════════════════════════════════════════════════════════════════
# NORMALISATION / DENORMALISATION
# ═══════════════════════════════════════════════════════════════════════════

def normalise(X: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    lo, hi = bounds[:, 0], bounds[:, 1]
    return (X - lo) / (hi - lo)

def denormalise(X_norm: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    lo, hi = bounds[:, 0], bounds[:, 1]
    return X_norm * (hi - lo) + lo


# ═══════════════════════════════════════════════════════════════════════════
# BAYESIAN OPTIMISATION
# ═══════════════════════════════════════════════════════════════════════════

class REGOBayesianOptimiser:
    """
    Full Bayesian Optimisation loop for REGO magnetic control parameters.

    Algorithm:
      1. LHS initial design (n_init points)
      2. Fit GP surrogate
      3. Optimise UCB acquisition over dense random candidates
      4. Evaluate cost at next point
      5. Update GP, repeat for n_iter iterations
      6. Track and report convergence
    """

    def __init__(self,
                 n_init:   int   = 20,
                 n_iter:   int   = 80,
                 n_cand:   int   = 5000,
                 kappa:    float = 2.0,
                 weights:  np.ndarray = DEFAULT_WEIGHTS,
                 seed:     int   = 42,
                 verbose:  bool  = True):
        self.n_init  = n_init
        self.n_iter  = n_iter
        self.n_cand  = n_cand
        self.kappa   = kappa
        self.weights = weights
        self.seed    = seed
        self.verbose = verbose
        self.rng     = np.random.RandomState(seed)

        # History
        self.X_obs       : List[np.ndarray] = []
        self.y_obs       : List[float]       = []
        self.detail_obs  : List[Dict]        = []
        self.best_cost   : float             = np.inf
        self.best_params : Optional[np.ndarray] = None
        self.best_detail : Optional[Dict]    = None

        # Convergence tracking
        self.iter_costs     : List[float] = []
        self.iter_best      : List[float] = []
        self.iter_acq_values: List[float] = []
        self.iter_stds      : List[float] = []

        # Build GP: Matérn 5/2 kernel (smooth, well-suited for physical responses)
        kernel = (ConstantKernel(1.0, (0.01, 10.0)) *
                  Matern(length_scale=np.ones(PARAM_BOUNDS.shape[0]),
                          length_scale_bounds=(0.01, 10.0),
                          nu=2.5) +
                  WhiteKernel(noise_level=1e-4, noise_level_bounds=(1e-6, 0.1)))
        self.gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=1e-6,
            normalize_y=True,
            n_restarts_optimizer=5,
        )

    def _evaluate(self, params: np.ndarray) -> Tuple[float, Dict]:
        cost, detail = evaluate_cost(params, self.weights)
        return cost, detail

    def _fit_gp(self):
        X_norm = normalise(np.array(self.X_obs), PARAM_BOUNDS)
        y      = np.array(self.y_obs)
        self.gp.fit(X_norm, y)

    def _next_candidate(self, kappa: float = None) -> np.ndarray:
        """Optimise acquisition: dense random search over normalised space.
        kappa overrides self.kappa when provided (used for kappa annealing)."""
        kappa_use   = kappa if kappa is not None else self.kappa
        X_cand_norm = self.rng.uniform(0, 1, size=(self.n_cand, PARAM_BOUNDS.shape[0]))
        acq_vals    = acquisition_ucb(X_cand_norm, self.gp, kappa=kappa_use)
        best_idx    = np.argmin(acq_vals)
        best_acq    = acq_vals[best_idx]
        x_next_norm = X_cand_norm[best_idx]
        x_next      = denormalise(x_next_norm.reshape(1, -1), PARAM_BOUNDS).flatten()
        x_next      = np.clip(x_next, PARAM_BOUNDS[:, 0], PARAM_BOUNDS[:, 1])
        return x_next, best_acq

    def run(self):
        t0 = time.time()
        if self.verbose:
            print("=" * 76)
            print("  REGO Bayesian Optimisation")
            print(f"  Params: {PARAM_NAMES}")
            print(f"  n_init={self.n_init}  n_iter={self.n_iter}  "
                  f"n_cand={self.n_cand}  κ={self.kappa}")
            print(f"  Weights: E={self.weights[0]:.2f} T={self.weights[1]:.2f} "
                  f"A={self.weights[2]:.2f} S={self.weights[3]:.2f} "
                  f"Cx={self.weights[4]:.2f}")
            print("=" * 76)

        # ── Phase 1: Initial LHS design ───────────────────────────────────
        if self.verbose:
            print(f"\n  Phase 1: Latin Hypercube Initial Design ({self.n_init} points)")
        lhs_samples = latin_hypercube_sample(self.n_init, PARAM_BOUNDS, seed=self.seed)

        # Always include the v19 default point
        lhs_samples[0] = PARAM_DEFAULT.copy()

        for i, x in enumerate(lhs_samples):
            cost, detail = self._evaluate(x)
            self.X_obs.append(x)
            self.y_obs.append(cost)
            self.detail_obs.append(detail)
            if cost < self.best_cost:
                self.best_cost   = cost
                self.best_params = x.copy()
                self.best_detail = detail
            if self.verbose and (i % 5 == 0 or i == len(lhs_samples)-1):
                viable_str = "✓" if detail["viable"] else "✗"
                print(f"    LHS {i+1:3d}/{self.n_init}  cost={cost:.4f}  "
                      f"E={detail['energy_MJ_per_kg']:.2f}  "
                      f"T={detail['time_hours']:.1f}h  "
                      f"RMS={detail['rms_mm']:.4f}mm  {viable_str}")

        if self.verbose:
            print(f"\n  Best after LHS: cost={self.best_cost:.4f}")

        # ── Phase 2: Bayesian Optimisation loop ───────────────────────────
        if self.verbose:
            print(f"\n  Phase 2: GP-UCB Optimisation ({self.n_iter} iterations)")
            print(f"  {'Iter':>4}  {'Cost':>8}  {'Best':>8}  "
                  f"{'E(MJ/kg)':>10}  {'T(h)':>7}  {'RMS(mm)':>9}  "
                  f"{'Stab':>6}  {'Cx':>6}  {'Viable':>6}  {'Acq':>8}")
            print("  " + "-" * 82)

        for it in range(self.n_iter):
            # Fit GP
            self._fit_gp()

            # Kappa annealing: start explorative (κ=3.0), finish exploitative (κ=0.5)
            # kappa_it is now correctly passed to _next_candidate (was computed but ignored)
            kappa_it = self.kappa * max(0.3, 1.0 - it / self.n_iter)

            # Next candidate via acquisition
            x_next, acq_val = self._next_candidate(kappa=kappa_it)

            # Evaluate
            cost, detail = self._evaluate(x_next)
            self.X_obs.append(x_next)
            self.y_obs.append(cost)
            self.detail_obs.append(detail)

            if cost < self.best_cost:
                self.best_cost   = cost
                self.best_params = x_next.copy()
                self.best_detail = detail
                improved = "★"
            else:
                improved = " "

            # Track convergence
            self.iter_costs.append(cost)
            self.iter_best.append(self.best_cost)
            self.iter_acq_values.append(acq_val)
            # GP posterior std at best point
            x_best_norm = normalise(self.best_params.reshape(1, -1), PARAM_BOUNDS)
            _, std_best = self.gp.predict(x_best_norm, return_std=True)
            self.iter_stds.append(float(std_best[0]))

            if self.verbose and (it % 5 == 0 or it == self.n_iter - 1 or improved == "★"):
                viable_str = "✓" if detail["viable"] else "✗"
                print(f"  {it+1:4d}  {cost:8.4f}  {self.best_cost:8.4f}  "
                      f"{detail['energy_MJ_per_kg']:10.2f}  "
                      f"{detail['time_hours']:7.2f}  "
                      f"{detail['rms_mm']:9.5f}  "
                      f"{detail['stability_norm']:6.3f}  "
                      f"{detail['complexity_norm']:6.3f}  "
                      f"{viable_str:>6}  "
                      f"{acq_val:8.4f} {improved}")

        elapsed = time.time() - t0
        if self.verbose:
            self._print_results(elapsed)

        return self.best_params, self.best_cost, self.best_detail

    def _print_results(self, elapsed: float):
        print("\n" + "=" * 76)
        print("  OPTIMISATION COMPLETE")
        print("=" * 76)
        print(f"\n  Total time: {elapsed:.1f} s  "
              f"({(self.n_init + self.n_iter)} evaluations)")
        print(f"  Best cost:   {self.best_cost:.6f}")
        v19_cost, v19_detail = evaluate_cost(PARAM_DEFAULT, self.weights)
        improvement = (v19_cost - self.best_cost) / v19_cost * 100
        print(f"  v19 default: {v19_cost:.6f}")
        print(f"  Improvement: {improvement:.1f}%\n")

        print(f"  {'Parameter':<22} {'v19 Default':>14} {'Optimal':>14}  {'Units'}")
        print("  " + "─" * 70)
        for i, (name, unit) in enumerate(zip(PARAM_NAMES, PARAM_UNITS)):
            v_def = PARAM_DEFAULT[i]
            v_opt = self.best_params[i]
            if name == "n_radial_sweeps":
                v_opt = int(round(v_opt))
            delta = (v_opt - v_def) / max(abs(v_def), 1e-15) * 100
            arrow = "▲" if v_opt > v_def else "▼"
            print(f"  {name:<22} {v_def:>14.4e}  {v_opt:>12.4e}  {unit}  "
                  f"  {arrow}{abs(delta):.1f}%")

        print(f"\n  Optimal Metric Breakdown:")
        d = self.best_detail
        print(f"    Energy:      {d['energy_MJ_per_kg']:.4f} MJ/kg")
        print(f"    Time:        {d['time_hours']:.2f} h")
        print(f"    Accuracy:    {d['rms_mm']:.6f} mm RMS")
        print(f"    Stability:   {d['stability_norm']:.4f} (norm)")
        print(f"    Complexity:  {d['complexity_norm']:.4f} (norm)")
        print(f"    F/W:         {d['F_over_W']:.3f}  ({'✓ viable' if d['viable'] else '✗ NOT VIABLE'})")
        print(f"    Score terms: E={d['e_term']:.4f}  T={d['t_term']:.4f}  "
              f"A={d['a_term']:.4f}  S={d['s_term']:.4f}  Cx={d['c_term']:.4f}")
        print("=" * 76)

    def get_results_dict(self) -> Dict:
        """Return full results as a serialisable dictionary."""
        return {
            "best_cost":    self.best_cost,
            "best_params":  self.best_params.tolist(),
            "best_detail":  self.best_detail,
            "param_names":  PARAM_NAMES,
            "param_units":  PARAM_UNITS,
            "param_default": PARAM_DEFAULT.tolist(),
            "weights":       self.weights.tolist(),
            "iter_costs":    self.iter_costs,
            "iter_best":     self.iter_best,
            "iter_stds":     self.iter_stds,
            "n_init":        self.n_init,
            "n_iter":        self.n_iter,
            "n_evaluations": len(self.y_obs),
            "all_costs":     self.y_obs,
            "all_params":    [x.tolist() for x in self.X_obs],
            "all_details":   [d for d in self.detail_obs],
        }


# ═══════════════════════════════════════════════════════════════════════════
# RESULT PLOTTING
# ═══════════════════════════════════════════════════════════════════════════

def plot_pareto_energy_vs_accuracy_p2(results: Dict, out_dir: Path):
    """Pareto front: Energy Consumption (x) vs Shape Accuracy MSE (y) — Phase 2 only."""
    out_dir.mkdir(parents=True, exist_ok=True)
    details = results.get("all_details", [])
    
    energies = []
    mse_values = []

    for d in details:
        if d.get("viable", False) and d.get("F_over_W", 0.0) >= 1.0:
            energies.append(d["energy_MJ_per_kg"])
            mse_values.append(d["rms_mm"] ** 2)   # MSE = RMS² as requested

    if len(energies) < 2:
        print("  ⚠ Not enough viable points for Pareto front (Energy vs Shape Accuracy)")
        return

    energies = np.array(energies)
    mse = np.array(mse_values)

    # Simple Pareto front (minimise both energy and MSE)
    is_pareto = np.ones(len(energies), dtype=bool)
    for i in range(len(energies)):
        for j in range(len(energies)):
            if i != j and energies[j] <= energies[i] and mse[j] <= mse[i] and (energies[j] < energies[i] or mse[j] < mse[i]):
                is_pareto[i] = False
                break

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(energies, mse, c="#94A3B8", s=25, alpha=0.7, label="All viable runs")
    ax.scatter(energies[is_pareto], mse[is_pareto], c="#10B981", s=90, edgecolors="black", 
               linewidth=1.5, label="Pareto Front")
    
    ax.set_xlabel("Energy Consumption (MJ/kg)", fontsize=12)
    ax.set_ylabel("Shape Accuracy (MSE = RMS²) [mm²]", fontsize=12)
    ax.set_title("REGO Phase 2 — Pareto Front: Energy vs Shape Accuracy", fontweight="bold", fontsize=13)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "BO_F_pareto_energy_vs_accuracy.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ BO_F_pareto_energy_vs_accuracy.png")

def plot_optimisation_results(results: Dict, out_dir: Path):
    """
    Produce 4 comprehensive plots from the BO run:
      A. Convergence: cost vs iteration + best-so-far
      B. GP posterior uncertainty (σ at best) vs iteration
      C. Parameter importance: mean |shift| from v19 default
      D. Metric breakdown: optimal vs v19 comparison bars
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    n_init   = results["n_init"]
    n_iter   = results["n_iter"]
    iter_costs = results["iter_costs"]
    iter_best  = results["iter_best"]
    iter_stds  = results["iter_stds"]
    all_costs  = results["all_costs"]
    all_params = np.array(results["all_params"])
    best_params = np.array(results["best_params"])
    v19_params  = np.array(results["param_default"])
    names       = results["param_names"]
    best_detail = results["best_detail"]
    weights     = results["weights"]

    REGO_CLR  = "#2563EB"
    BEST_CLR  = "#10B981"
    REF_CLR   = "#F59E0B"

    # ── Figure A: Convergence ────────────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=False)
    fig.suptitle("Bayesian Optimisation — Convergence Tracking", fontweight="bold", fontsize=13)

    # All observed costs (LHS + BO iterations)
    x_lhs = np.arange(n_init)
    x_bo  = np.arange(n_init, n_init + len(iter_costs))

    ax1.scatter(x_lhs, all_costs[:n_init], s=30, color="#94A3B8", alpha=0.6,
                label="LHS initial design", zorder=3)
    ax1.scatter(x_bo, all_costs[n_init:n_init+len(iter_costs)],
                s=25, color=REGO_CLR, alpha=0.5, label="BO evaluations", zorder=3)
    ax1.plot(x_bo, iter_best, color=BEST_CLR, lw=2.5, label="Best-so-far", zorder=4)
    ax1.axvline(n_init, ls="--", lw=1.5, color="gray", alpha=0.6, label="LHS → BO boundary")
    ax1.axhline(results["best_cost"], ls=":", lw=2, color=BEST_CLR, alpha=0.7,
                label=f"Global best = {results['best_cost']:.4f}")

    # v19 reference
    v19_cost, _ = evaluate_cost(v19_params)
    ax1.axhline(v19_cost, ls="--", lw=1.5, color=REF_CLR, alpha=0.8,
                label=f"v19 default = {v19_cost:.4f}")
    ax1.fill_between(x_bo, iter_best, v19_cost, where=np.array(iter_best) < v19_cost,
                     alpha=0.15, color=BEST_CLR, label="Improvement region")

    ax1.set_ylabel("Aggregate Cost Score", fontsize=10)
    ax1.set_title("Cost per Evaluation + Best-so-Far", fontweight="bold")
    ax1.legend(fontsize=8.5, loc="upper right", ncol=2)
    ax1.grid(True, alpha=0.3)
    ax1.set_axisbelow(True)

    # GP uncertainty at best point
    ax2.plot(x_bo, iter_stds, color="#8B5CF6", lw=2, marker="o", ms=3,
             label="GP σ at current best")
    ax2.set_xlabel("Evaluation index", fontsize=10)
    ax2.set_ylabel("GP Posterior Std (uncertainty)", fontsize=10)
    ax2.set_title("GP Uncertainty at Best Point (→ 0 = converged)", fontweight="bold")
    ax2.fill_between(x_bo, 0, iter_stds, alpha=0.2, color="#8B5CF6")
    ax2.grid(True, alpha=0.3)
    ax2.set_axisbelow(True)
    ax2.legend(fontsize=9)

    fig.tight_layout()
    fig.savefig(out_dir / "BO_A_convergence.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ BO_A_convergence.png")

    # ── Figure B: Parameter shifts ───────────────────────────────────────
    fig, axes = plt.subplots(2, 5, figsize=(16, 7))
    fig.suptitle("Bayesian Optimisation — Optimal Parameters vs v19 Default",
                 fontweight="bold", fontsize=13)

    axes_flat = axes.flatten()
    for i, (name, unit) in enumerate(zip(names, PARAM_UNITS)):
        ax = axes_flat[i]
        v_def = v19_params[i]
        v_opt = best_params[i]
        if name == "n_radial_sweeps":
            v_opt = int(round(v_opt))

        # Distribution of all sampled values for this parameter
        all_vals = all_params[:, i]
        ax.hist(all_vals, bins=20, color="#CBD5E1", edgecolor="white", density=True, zorder=2)
        ax.axvline(v_def, color=REF_CLR, lw=2.5, label="v19 default")
        ax.axvline(v_opt, color=BEST_CLR, lw=2.5, label="Optimal")

        # Format axis
        ax.set_title(f"{name}\n[{unit}]", fontsize=8.5, fontweight="bold")
        ax.set_xlabel("Value", fontsize=8)
        ax.set_ylabel("Density", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)
        ax.set_axisbelow(True)

        # Annotation
        pct = (v_opt - v_def) / max(abs(v_def), 1e-15) * 100
        sign = "+" if pct >= 0 else ""
        ax.set_title(f"{name}\n{sign}{pct:.1f}%", fontsize=9, fontweight="bold",
                     color=BEST_CLR if abs(pct) > 5 else "black")

    fig.tight_layout()
    fig.savefig(out_dir / "BO_B_parameters.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ BO_B_parameters.png")

    # ── Figure C: Metric comparison bar (optimal vs v19) ─────────────────
    v19_cost, v19_detail = evaluate_cost(v19_params)
    metrics = ["energy_MJ_per_kg", "time_hours", "rms_mm", "stability_norm", "complexity_norm"]
    labels  = ["Energy\n(MJ/kg)", "Time\n(h)", "RMS\n(mm)", "Stability\n(norm)", "Complexity\n(norm)"]
    v19_vals = [v19_detail[m] for m in metrics]
    opt_vals = [best_detail[m] for m in metrics]

    # Invert stability for display (higher = better → plot 1-stab for "lower is better")
    # Keep original values but annotate
    fig, axes = plt.subplots(1, 5, figsize=(16, 5))
    fig.suptitle("Optimised vs v19 Default — Metric Comparison",
                 fontweight="bold", fontsize=13)

    for ax, metric, lbl, v19, opt in zip(axes, metrics, labels, v19_vals, opt_vals):
        x      = np.array([0, 1])
        vals   = [v19, opt]
        colors = [REF_CLR, BEST_CLR]
        bars   = ax.bar(x, vals, 0.6, color=colors, edgecolor="white", linewidth=2)
        ax.set_xticks(x)
        ax.set_xticklabels(["v19\nDefault", "Optimised"], fontsize=9)
        ax.set_title(lbl, fontweight="bold", fontsize=10)
        ax.grid(True, alpha=0.3, axis="y")
        ax.set_axisbelow(True)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()*1.02,
                    f"{v:.4g}", ha="center", va="bottom", fontsize=9, fontweight="bold")
        # Improvement arrow
        if metric in ["stability_norm"]:
            imp = (opt - v19) / max(abs(v19), 1e-12) * 100
            sign = "+" if imp >= 0 else ""
            col  = BEST_CLR if imp > 0 else "red"
        else:
            imp = (v19 - opt) / max(abs(v19), 1e-12) * 100
            sign = "+" if imp >= 0 else ""
            col  = BEST_CLR if imp > 0 else "red"
        ax.set_xlabel(f"{sign}{imp:.1f}% improvement", fontsize=9, color=col,
                      fontweight="bold")

    fig.tight_layout()
    fig.savefig(out_dir / "BO_C_metrics.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ BO_C_metrics.png")

    # ── Figure D: Score breakdown (stacked bar) ───────────────────────────
    fig, ax = plt.subplots(figsize=(9, 6))
    fig.suptitle("Aggregate Score Breakdown: v19 Default vs Optimised",
                 fontweight="bold", fontsize=12)

    term_names  = ["e_term",  "t_term",  "a_term",  "s_term",  "c_term"]
    term_labels = ["Energy",  "Time",    "Accuracy","Stability","Complexity"]
    term_clrs   = ["#EF4444","#F59E0B","#10B981","#6366F1","#EC4899"]

    x = np.array([0, 1.5])
    bottom = np.zeros(2)
    for tname, tlbl, tclr in zip(term_names, term_labels, term_clrs):
        v19_t = v19_detail.get(tname, 0)
        opt_t = best_detail.get(tname, 0)
        vals  = [v19_t, opt_t]
        ax.bar(x, vals, 0.8, bottom=bottom, color=tclr, label=tlbl,
               edgecolor="white", linewidth=1, zorder=3)
        # Annotate non-trivial segments
        for xi, b, v in zip(x, bottom, vals):
            if v > 0.01:
                ax.text(xi, b + v/2, f"{v:.3f}", ha="center", va="center",
                        fontsize=8, color="white", fontweight="bold")
        bottom += vals

    totals = [sum(v19_detail.get(t, 0) for t in term_names),
              sum(best_detail.get(t, 0) for t in term_names)]
    for xi, tot in zip(x, totals):
        ax.text(xi, tot + 0.02, f"Total\n{tot:.4f}", ha="center", va="bottom",
                fontsize=10, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(["v19 Default", "Optimised"], fontsize=12)
    ax.set_ylabel("Score Contribution (lower = better)", fontsize=11)
    ax.legend(fontsize=10, loc="upper right")
    ax.yaxis.grid(True, alpha=0.3, zorder=0)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(out_dir / "BO_D_score_breakdown.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ BO_D_score_breakdown.png")

    # ── Figure E: Acquisition landscape (2D slices) ───────────────────────
    # Show 2D cost landscape for (m_trap, chi_eff_target) at best other params
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("Cost Landscape: 2D Slices at Optimal Point",
                 fontweight="bold", fontsize=12)

    def landscape_slice(ax, i_param, j_param, n_grid=50):
        lo_i, hi_i = PARAM_BOUNDS[i_param]
        lo_j, hi_j = PARAM_BOUNDS[j_param]
        grid_i = np.linspace(lo_i, hi_i, n_grid)
        grid_j = np.linspace(lo_j, hi_j, n_grid)
        Z = np.zeros((n_grid, n_grid))
        x_base = best_params.copy()
        for ii, vi in enumerate(grid_i):
            for jj, vj in enumerate(grid_j):
                x_tmp          = x_base.copy()
                x_tmp[i_param] = vi
                x_tmp[j_param] = vj
                Z[jj, ii], _   = evaluate_cost(x_tmp, weights)
        im = ax.contourf(grid_i, grid_j, Z, levels=30, cmap="RdYlGn_r", alpha=0.85)
        ax.contour(grid_i, grid_j, Z, levels=10, colors="white", linewidths=0.5, alpha=0.5)
        plt.colorbar(im, ax=ax, label="Cost")
        ax.scatter([best_params[i_param]], [best_params[j_param]],
                   s=300, color="white", marker="*", edgecolors="black", lw=1.5,
                   zorder=5, label="Optimal")
        ax.scatter([v19_params[i_param]], [v19_params[j_param]],
                   s=150, color=REF_CLR, marker="o", edgecolors="black", lw=1.5,
                   zorder=5, label="v19 default")
        ax.set_xlabel(f"{PARAM_NAMES[i_param]} ({PARAM_UNITS[i_param]})", fontsize=10)
        ax.set_ylabel(f"{PARAM_NAMES[j_param]} ({PARAM_UNITS[j_param]})", fontsize=10)
        ax.set_title(f"{PARAM_NAMES[i_param]} vs {PARAM_NAMES[j_param]}", fontweight="bold")
        ax.legend(fontsize=9)

    landscape_slice(axes[0], i_param=0, j_param=4)   # m_trap vs chi
    landscape_slice(axes[1], i_param=5, j_param=6)   # T_transport vs T_shape

    fig.tight_layout()
    fig.savefig(out_dir / "BO_E_landscape.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    plot_pareto_energy_vs_accuracy_p2(results, out_dir)
    print("  ✓ BO_E_landscape.png")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="REGO Bayesian Optimisation")
    parser.add_argument("--n-init",    type=int,   default=20,
                        help="LHS initial design points (default: 20)")
    parser.add_argument("--n-iter",    type=int,   default=80,
                        help="BO iterations (default: 80)")
    parser.add_argument("--n-cand",    type=int,   default=5000,
                        help="Candidate points for acquisition (default: 5000)")
    parser.add_argument("--kappa",     type=float, default=2.0,
                        help="UCB exploration constant κ (default: 2.0)")
    parser.add_argument("--w1",        type=float, default=0.30, help="Energy weight")
    parser.add_argument("--w2",        type=float, default=0.25, help="Time weight")
    parser.add_argument("--w3",        type=float, default=0.25, help="Accuracy weight")
    parser.add_argument("--w4",        type=float, default=0.10, help="Stability weight")
    parser.add_argument("--w5",        type=float, default=0.10, help="Complexity weight")
    parser.add_argument("--seed",      type=int,   default=42)
    parser.add_argument("--output-dir",type=str,   default="rego_bo_results",
                        help="Output directory for results and plots")
    parser.add_argument("--no-plots",  action="store_true",
                        help="Skip plot generation (faster)")
    parser.add_argument("--sim-data",  default=None,
                        help="Path to rego_sim_data.json (from rego_extract.py). "
                             "If given, extracts real m_trap/m_shape/chi from the "
                             "checkpoint and uses them to seed the BO initial design "
                             "with the actual simulation parameters.")
    args = parser.parse_args()

    weights = np.array([args.w1, args.w2, args.w3, args.w4, args.w5])
    weights /= weights.sum()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # If real sim data provided, extract actual parameter values and use them
    # to override the default seed point in the initial LHS design
    if args.sim_data:
        from pathlib import Path as _Path
        import json as _json
        sim_path = _Path(args.sim_data)
        if sim_path.exists():
            with open(sim_path) as _f:
                _sim = _json.load(_f)
            if _sim.get("has_real_data"):
                _efc = _sim.get("energy_from_checkpoint", {})
                _ec  = _efc.get("energy_computed", {})
                # Extract actual moments from checkpoint
                m_trap_real   = _efc.get("m_trap_actual",  PARAM_DEFAULT[0])
                m_shape_real  = _efc.get("m_shape_actual", PARAM_DEFAULT[1])
                m_corner_real = _efc.get("m_corner_actual",PARAM_DEFAULT[2])
                chi_real      = _efc.get("chi_actual",     PARAM_DEFAULT[4])
                # Override the default seed with real values (within bounds)
                for i, val in enumerate([m_trap_real, m_shape_real, m_corner_real,
                                         None, chi_real]):
                    if val is not None:
                        PARAM_DEFAULT[i] = float(np.clip(val,
                            PARAM_BOUNDS[i,0], PARAM_BOUNDS[i,1]))
                print(f"  [BO] Seeded from real checkpoint:")
                print(f"       m_trap={PARAM_DEFAULT[0]:.4e}  "
                      f"m_shape={PARAM_DEFAULT[1]:.4e}  "
                      f"chi={PARAM_DEFAULT[4]:.4e}")
            else:
                print(f"  [BO] sim_data loaded but no real checkpoint found, using defaults")
        else:
            print(f"  [BO] --sim-data path not found: {sim_path}")

    # Run optimisation
    opt = REGOBayesianOptimiser(
        n_init   = args.n_init,
        n_iter   = args.n_iter,
        n_cand   = args.n_cand,
        kappa    = args.kappa,
        weights  = weights,
        seed     = args.seed,
        verbose  = True,
    )
    best_params, best_cost, best_detail = opt.run()
    results = opt.get_results_dict()

    # Save results JSON
    json_out = out_dir / "bo_results.json"
    with open(json_out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  ✓ Results saved → {json_out}")

    # Generate plots
    if not args.no_plots:
        print("\n  Generating optimisation plots...")
        plot_optimisation_results(results, out_dir)
        print(f"  ✓ All plots saved → {out_dir}/")

    # Final summary
    print("\n" + "=" * 76)
    print("  RECOMMENDED PARAMETER UPDATES FOR phase2_clean_saved.py:")
    print("=" * 76)
    pnames = results["param_names"]
    popt   = results["best_params"]
    pdef   = results["param_default"]
    for name, opt_v, def_v in zip(pnames, popt, pdef):
        if name == "n_radial_sweeps":
            opt_v = int(round(opt_v))
        pct = (opt_v - def_v) / max(abs(def_v), 1e-15) * 100
        sign = "+" if pct >= 0 else ""
        print(f"  {name:<22} = {opt_v:.4e}   (was {def_v:.4e}, {sign}{pct:.1f}%)")
    print()
    print(f"  Cost:   {best_cost:.5f}  (v19: {evaluate_cost(np.array(pdef))[0]:.5f})")
    print(f"  Energy: {best_detail['energy_MJ_per_kg']:.3f} MJ/kg")
    print(f"  Time:   {best_detail['time_hours']:.2f} h")
    print(f"  RMS:    {best_detail['rms_mm']:.5f} mm")
    print(f"  F/W:    {best_detail['F_over_W']:.2f} {'✓' if best_detail['viable'] else '✗ NOT VIABLE'}")
    print("=" * 76)

    # ── Top-5 configs JSON (for verification in phase2_clean_saved.py) ────
    # Rank all evaluated points by cost and write the top 5 with full details.
    # Use this to pick which parameter sets to verify in the full simulation.
    all_params_arr = np.array(results["all_params"])
    all_costs_arr  = np.array(results["all_costs"])
    top5_indices   = np.argsort(all_costs_arr)[:5]

    top5_configs = []
    for rank, idx in enumerate(top5_indices, 1):
        p_vec  = all_params_arr[idx]
        c, d   = evaluate_cost(p_vec, weights)
        entry  = {
            "rank":       rank,
            "cost":       round(float(c), 6),
            "params":     {n: float(p_vec[i]) for i, n in enumerate(PARAM_NAMES)},
            "metrics": {
                "energy_MJ_per_kg":  round(d["energy_MJ_per_kg"], 4),
                "time_hours":        round(d["time_hours"], 3),
                "rms_mm":            round(d["rms_mm"], 6),
                "stability_norm":    round(d["stability_norm"], 4),
                "complexity_norm":   round(d["complexity_norm"], 4),
                "F_over_W":          round(d["F_over_W"], 4),
                "viable":            bool(d["viable"]),
            },
        }
        top5_configs.append(entry)

    top5_path = out_dir / "top_5_configs.json"
    with open(top5_path, "w") as f:
        json.dump(top5_configs, f, indent=2)
    print(f"\n  ✓ Top-5 configs saved → {top5_path}")
    print(f"    Use these in phase2_clean_saved.py to verify the best parameter sets.")
    print()
    for entry in top5_configs:
        p = entry["params"]
        m = entry["metrics"]
        print(f"  Rank {entry['rank']}  cost={entry['cost']:.4f}  "
              f"F/W={m['F_over_W']:.2f}{'✓' if m['viable'] else '✗'}  "
              f"E={m['energy_MJ_per_kg']:.3f}MJ/kg  "
              f"RMS={m['rms_mm']:.5f}mm")
        print(f"    chi={p['chi_eff_target']:.4f}  m_trap={p['m_trap']:.4e}  "
              f"m_shape={p['m_shape']:.4e}  T_shape={p['T_shape']:.1f}s")

    # ── Chi viability summary (minimum viable χ for ISEF susceptibility analysis) ──
    print("\n" + "=" * 76)
    print("  MINIMUM VIABLE χ ANALYSIS  (for magnetic beneficiation sizing)")
    print("=" * 76)
    # Sweep chi at optimised m_trap to find the minimum chi that keeps F/W >= 1
    opt_m_trap = best_params[0]   # index 0 = m_trap
    opt_d_lead = best_params[3]   # index 3 = d_lead
    opt_gc     = best_params[7]   # index 7 = GRAD_B2_CLAMP
    chi_sweep_vals = list(np.logspace(-3, math.log10(0.15), 30))
    print(f"  Using optimised m_trap={opt_m_trap:.4e}  d_lead={opt_d_lead:.4e}")
    min_viable_chi = None
    for chi_test in chi_sweep_vals:
        gradB2_t = min(_gradB2_axial(opt_m_trap, opt_d_lead), opt_gc)
        B_ax     = _B_axial_from_dipole(opt_m_trap, opt_d_lead)
        chi_e    = chi_eff_scalar(B_ax, chi_test, MSAT)
        kpf      = VP * chi_e / (2 * MU0)
        F_s      = kpf * gradB2_t
        FoW      = F_s / max(MP * G_LUNAR, 1e-30)
        if FoW >= 1.0 and min_viable_chi is None:
            min_viable_chi = chi_test
    if min_viable_chi is not None:
        print(f"  Minimum viable χ ≈ {min_viable_chi:.2e}  "
              f"(lunar regolith baseline: χ≈1e-3 to 5e-3 after beneficiation)")
        if min_viable_chi <= 5e-3:
            print(f"  ✓ REGO works on REAL lunar regolith after standard magnetic beneficiation")
        elif min_viable_chi <= 0.05:
            print(f"  ~ Requires moderate Fe-oxide enrichment (χ={min_viable_chi:.2e})")
        else:
            print(f"  ✗ Requires substantial Fe-oxide coating (χ={min_viable_chi:.2e})")
    print("=" * 76)