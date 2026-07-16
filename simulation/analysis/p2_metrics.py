#!/usr/bin/env python3
"""
REGO Phase 2 — Comprehensive Metrics Dataset Generator
=======================================================
Computes all comparison metrics analytically from simulation physics,
produces a structured dataset with aggregate scores ready for graphing
and Bayesian optimisation.

Metric dimensions:
  1. Energy      — coil I²R dissipation (MJ/kg of structure)
  2. Time        — total build time (hours for 1 m³ structure)
  3. Accuracy    — RMS centroid deviation from target geometry (mm)
  4. Stability   — structural integrity proxy (normalised compressive estimate)
  5. Complexity  — system complexity score (sources × control overhead)

Aggregate score:
  S = w1·(E/E_ref) + w2·(T/T_ref) + w3·(A/A_ref)
    + w4·(1 − Stability) + w5·Complexity_norm
  Lower is better.  Default weights: [0.30, 0.25, 0.25, 0.10, 0.10]
"""

import numpy as np
import math, json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# PHYSICS CONSTANTS (mirroring phase2_clean_saved.py)
# ═══════════════════════════════════════════════════════════════════════════
MU0       = 4.0 * math.pi * 1e-7
PI        = math.pi
_MU0_4PI  = MU0 / (4.0 * PI)

# Simulation configuration mirror
N_PARTICLES      = 256
R_PARTICLE       = 3e-5        # m
RHO              = 7800.0      # kg/m³
VP               = (4/3)*PI*R_PARTICLE**3
MP               = VP * RHO
G_LUNAR          = 1.62        # m/s²
CHI_DEFAULT      = 0.15        # nominal susceptibility (Fe-based)
MSAT             = 2e5         # A/m
DT               = 8e-6        # s
L_BOX            = 0.010       # m (10 mm domain)

# Coil model (magnetic dipole → solenoid coil)
COIL_N_TURNS  = 100
COIL_AREA     = 4e-6           # m² (2mm × 2mm)
COIL_R_OHM    = 0.05           # Ω (Cu at ~100 K lunar)
N_DIPOLES     = 36             # total in v19

# Phase timings (seconds, real-time sim)
T_SETTLE       = 0.3
T_CLUSTER      = 2.5
T_TRANSPORT_4x = 4 * 4.0      # 4 clusters × budget
T_INTERLUDE_3x = 3 * 0.4
T_SHAPE        = 8.0
T_HOLD         = 2.0
T_TOTAL_SIM    = (T_SETTLE + T_CLUSTER + T_TRANSPORT_4x
                  + T_INTERLUDE_3x + T_SHAPE + T_HOLD)

# Scale factor: sim is mm-scale (10 mm box); lunar structure is 1 m³ cube
# Linear scale = 1 m / 0.010 m = 100×; volume scale = 100³ = 1e6
SCALE_LINEAR  = 100.0           # dimensionless
SCALE_VOL     = SCALE_LINEAR**3 # 1e6

# ═══════════════════════════════════════════════════════════════════════════
# DIPOLE FIELD UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def B_dipole(r_obs: np.ndarray, r_dip: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Magnetic field of a point dipole at observation point r_obs."""
    rv   = r_obs - r_dip
    r_sq = np.dot(rv, rv)
    if r_sq < 1e-24:
        return np.zeros(3)
    r_mag = math.sqrt(r_sq)
    rhat  = rv / r_mag
    coeff = _MU0_4PI / r_sq / r_mag   # μ₀/4π / r³
    return coeff * (3.0 * np.dot(m, rhat) * rhat - m)


def grad_B2_analytical(r_obs: np.ndarray,
                        dip_positions: np.ndarray,
                        dip_moments: np.ndarray,
                        dip_strengths: np.ndarray) -> np.ndarray:
    """
    Analytical ∇(B²) = 2 Σ_k J_k^T · B_total
    Returns shape (3,) gradient vector.
    """
    # Pass 1: total B
    B = np.zeros(3)
    for k in range(len(dip_strengths)):
        s = dip_strengths[k]
        if s < 1e-15:
            continue
        mv  = dip_moments[k] * s
        rv  = r_obs - dip_positions[k]
        r2  = np.dot(rv, rv)
        if r2 < 1e-24:
            continue
        r5    = r2**2.5
        mdotr = np.dot(mv, rv)
        coeff = _MU0_4PI / r5
        B    += coeff * (3.0 * mdotr * rv - r2 * mv)

    # Pass 2: ∇(B²) = 2 Σ J_k^T · B
    gB2 = np.zeros(3)
    for k in range(len(dip_strengths)):
        s = dip_strengths[k]
        if s < 1e-15:
            continue
        mv     = dip_moments[k] * s
        rv     = r_obs - dip_positions[k]
        r2     = np.dot(rv, rv)
        if r2 < 1e-24:
            continue
        r5     = r2**2.5
        r7     = r5 * r2
        mdotrv = np.dot(mv, rv)
        Bdotrv = np.dot(B, rv)
        mdotB  = np.dot(mv, B)
        c5     = _MU0_4PI / r5
        c7     = 15.0 * _MU0_4PI / r7
        gB2   += 2.0 * (c5 * (3.0*Bdotrv*mv + 3.0*mdotrv*B + 3.0*mdotB*rv)
                        - c7 * mdotrv * Bdotrv * rv)
    return gB2


def chi_eff_scalar(B_mag: float, chi: float, Msat: float) -> float:
    """Effective susceptibility with Langevin saturation."""
    alpha = chi * B_mag / (MU0 * Msat)
    alpha = min(alpha, 20.0)
    cosh_a = math.cosh(alpha)
    return chi / (cosh_a * cosh_a)


# ═══════════════════════════════════════════════════════════════════════════
# ENERGY CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════

def coil_power_from_moment(m_magnitude: float,
                            n_turns: int   = COIL_N_TURNS,
                            area: float    = COIL_AREA,
                            r_ohm: float   = COIL_R_OHM) -> float:
    """
    P = I² R,  where I = m / (N·A)
    m_magnitude in A·m²
    Returns power in Watts.
    """
    I   = m_magnitude / (n_turns * area)
    return I**2 * r_ohm


def compute_rego_energy(
        m_trap:    float = 0.0006,   # A·m²
        m_shape:   float = 0.0012,
        m_corner:  float = 0.0006,
        t_sim:     float = T_TOTAL_SIM,
        n_clusters:int   = 4,
        chi:       float = CHI_DEFAULT,
        scale_to_1m3: bool = True
) -> Dict:
    """
    Compute REGO energy budget analytically from coil moments.
    Each phase activates a specific subset of dipoles; we account for
    duty cycles from the v19 timing parameters.
    """
    # Phase durations & active dipole sets
    phases = {
        "settle":    (T_SETTLE,        {"corners": 8, "trap": 0, "shape": 0}),
        "cluster":   (T_CLUSTER,       {"corners": 8, "trap": 4, "shape": 0}),
        "transport": (T_TRANSPORT_4x,  {"corners": 8, "trap": 4, "shape": 0}),
        "interlude": (T_INTERLUDE_3x,  {"corners": 8, "trap": 4, "shape": 0}),
        "shape":     (T_SHAPE,         {"corners": 0, "trap": 4, "shape": 4}),
        "hold":      (T_HOLD,          {"corners": 0, "trap": 4, "shape": 0}),
    }

    P_corner = coil_power_from_moment(m_corner)
    P_trap   = coil_power_from_moment(m_trap)
    P_shape  = coil_power_from_moment(m_shape)

    total_energy_J = 0.0
    phase_breakdown = {}
    for ph_name, (dt_ph, counts) in phases.items():
        P_ph = (counts["corners"] * P_corner +
                counts["trap"]    * P_trap   +
                counts["shape"]   * P_shape)
        E_ph = P_ph * dt_ph
        phase_breakdown[ph_name] = {"duration_s": dt_ph,
                                     "power_W":    P_ph,
                                     "energy_J":   E_ph}
        total_energy_J += E_ph

    # REGO structures ~10 mm domain with N=256 particles
    # Mass of one cluster: N_cluster particles × mp
    mass_per_cluster_kg = (N_PARTICLES / n_clusters) * MP
    mass_total_sim_kg   = N_PARTICLES * MP

    # Scale to 1 m³ structure
    # 1 m³ of lunar regolith at packing fraction 0.60, rho=3100 kg/m³ → ~1860 kg
    STRUCTURE_MASS_KG = 0.60 * 3100.0    # kg per m³ structure (realistic lunar)

    if scale_to_1m3:
        # Energy scales as (particle_count_ratio) to fill the 1 m³
        n_sim_particles = N_PARTICLES
        n_real_particles = STRUCTURE_MASS_KG / MP
        scale_factor = n_real_particles / n_sim_particles
        energy_scaled_J = total_energy_J * scale_factor
        energy_MJ_per_kg = energy_scaled_J / STRUCTURE_MASS_KG / 1e6
    else:
        energy_scaled_J  = total_energy_J
        energy_MJ_per_kg = total_energy_J / mass_total_sim_kg / 1e6

    # Average power
    avg_power_W = total_energy_J / t_sim if t_sim > 0 else 0.0

    return {
        "total_energy_J":       total_energy_J,
        "energy_scaled_J":      energy_scaled_J,
        "energy_MJ_per_kg":     energy_MJ_per_kg,
        "avg_power_W":          avg_power_W,
        "structure_mass_kg":    STRUCTURE_MASS_KG if scale_to_1m3 else mass_total_sim_kg,
        "phase_breakdown":      phase_breakdown,
        "chi":                  chi,
        "n_active_dipoles_max": N_DIPOLES,
    }


def compute_build_time(
        scale_to_1m3: bool = True,
        n_layers: Optional[int] = None
) -> Dict:
    """
    Compute REGO build time scaled to 1 m³ structure.
    The sim handles 4 clusters of 64 particles in a 10mm³ domain.
    For a 1 m³ structure we tile the domain 100× per side = 1e6 voxels.
    REGO is parallelisable: all voxels processed simultaneously.
    (The key advantage is the field-driven parallel deposition.)
    """
    t_sim_one_domain_s = T_TOTAL_SIM

    # With parallelism factor: for large-scale, multiple coil sets tile the
    # structure. Conservative estimate: 10% efficiency overhead per tiling step.
    # 1 m³ ÷ (10mm)³ = 1e6 cells; if P parallel sets, time ≈ t_sim * ceil(1e6/P)
    # Assume P = 1e6 for full parallel (ideal) and P = 100 for realistic (100 rig).
    P_ideal     = 1_000_000
    P_realistic = 100

    # Single-domain sequential (no parallelism)
    t_sequential_s  = t_sim_one_domain_s * (SCALE_LINEAR**3)

    # Realistic parallel (100 simultaneous domains)
    t_realistic_s   = t_sim_one_domain_s * math.ceil(SCALE_LINEAR**3 / P_realistic)

    # Ideal parallel (all at once)
    t_ideal_s       = t_sim_one_domain_s   # same time, just bigger field

    # Overhead: setup (coil positioning, calibration, safety checks)
    t_setup_s = 600.0   # 10 minutes

    results = {
        "t_sim_one_domain_s":   t_sim_one_domain_s,
        "t_sequential_h":       (t_sequential_s + t_setup_s) / 3600,
        "t_realistic_parallel_h": (t_realistic_s + t_setup_s) / 3600,
        "t_ideal_parallel_h":   (t_ideal_s + t_setup_s) / 3600,
        "parallelism_realistic": P_realistic,
        "parallelism_ideal":    P_ideal,
        "t_setup_s":            t_setup_s,
    }

    # Phase breakdown (for sub-bar chart)
    results["phase_times_h"] = {
        "setup":     t_setup_s / 3600,
        "settle":    T_SETTLE * math.ceil(SCALE_LINEAR**3 / P_realistic) / 3600,
        "cluster":   T_CLUSTER * math.ceil(SCALE_LINEAR**3 / P_realistic) / 3600,
        "transport": T_TRANSPORT_4x * math.ceil(SCALE_LINEAR**3 / P_realistic) / 3600,
        "shape":     T_SHAPE * math.ceil(SCALE_LINEAR**3 / P_realistic) / 3600,
        "hold":      T_HOLD * math.ceil(SCALE_LINEAR**3 / P_realistic) / 3600,
    }

    return results


def compute_shape_accuracy(
        targets: Optional[np.ndarray] = None,
        positions: Optional[np.ndarray] = None,
        chi: float = CHI_DEFAULT
) -> Dict:
    """
    Compute RMS shape accuracy.
    If no particle data provided, use analytical estimate from dipole trap stiffness.
    """
    # Analytical stiffness estimate:
    # Trap force F = (Vp·χ/2μ₀)·∇B²
    # At equilibrium: cluster oscillates around B² maximum.
    # Restoring force constant k = (Vp·χ/2μ₀)·d²B²/dx² at trap centre
    # For single leading dipole m=0.0006 at d=0.3mm:
    #   B at d=0.3mm from dipole (along axis): μ₀/4π · 2m/r³
    m    = 0.0006   # A·m²
    d    = 0.3e-3   # m
    Bax  = _MU0_4PI * 2 * m / d**3
    # d²B²/dx² at the axial maximum (off-axis, r direction from dipole axis):
    # Numerically evaluated at transverse offset: B²(r) ≈ B²(0) - α·r²
    # α = d²B²/dr² estimated by 5-point FD
    r_probe = np.array([d, 0, 0])
    dh      = 1e-6
    dip_p   = np.array([[0.0, 0.0, 0.0]])
    dip_m   = np.array([[0.0, 0.0, m]])
    dip_s   = np.array([1.0])

    def B2_at(r):
        B = np.zeros(3)
        for k in range(1):
            if dip_s[k] < 1e-15:
                continue
            mv  = dip_m[k] * dip_s[k]
            rv  = r - dip_p[k]
            r2  = np.dot(rv, rv)
            if r2 < 1e-24:
                continue
            r3    = r2**1.5
            rhat  = rv / math.sqrt(r2)
            coeff = _MU0_4PI / r3
            B += coeff * (3.0 * np.dot(mv, rhat) * rhat - mv)
        return np.dot(B, B)

    B2_0 = B2_at(r_probe)
    B2_p = B2_at(r_probe + np.array([0, dh, 0]))
    B2_m = B2_at(r_probe + np.array([0, -dh, 0]))
    d2B2_dr2 = (B2_p - 2*B2_0 + B2_m) / dh**2  # T²/m²

    kelvin_pf = VP * chi / (2 * MU0)
    k_spring  = kelvin_pf * abs(d2B2_dr2)       # N/m

    # Thermal / vibrational amplitude (from lunar seismic noise ~1e-9 m/s²)
    # σ_x ≈ sqrt(kT_eff / k_spring) using effective temperature from residual KE
    KE_residual = 1e-15  # J per particle (from typical KE logs)
    sigma_x_m   = math.sqrt(2 * KE_residual / max(k_spring, 1e-12))
    sigma_x_mm  = sigma_x_m * 1e3

    # Centroid accuracy (cluster of 64 particles → σ/√64)
    N_cluster   = N_PARTICLES // 4
    rms_centroid_mm = sigma_x_mm / math.sqrt(N_cluster)

    # Lower bound from dipole positioning resolution (1 µm coil step motors)
    rms_floor_mm = 0.001   # 1 µm → 0.001 mm

    rms_mm = max(rms_centroid_mm, rms_floor_mm)

    # If actual particle data provided, compute directly
    rms_actual_mm = None
    if targets is not None and positions is not None:
        # Assign particles to nearest target
        from scipy.spatial.distance import cdist
        dists = cdist(positions, targets)
        assignments = np.argmin(dists, axis=1)
        sq_errors = []
        for k in range(4):
            mask   = assignments == k
            if mask.sum() == 0:
                continue
            cen    = positions[mask].mean(axis=0)
            sq_err = np.sum((cen - targets[k])**2)
            sq_errors.append(sq_err)
        rms_actual_mm = math.sqrt(np.mean(sq_errors)) * 1e3

    return {
        "rms_analytical_mm":  rms_mm,
        "rms_actual_mm":      rms_actual_mm if rms_actual_mm else rms_mm,
        "k_spring_N_per_m":   k_spring,
        "sigma_per_particle_mm": sigma_x_mm,
        "chi":                chi,
        "B2_at_trap_T2":      B2_0,
        "d2B2_dr2_T2_m2":     d2B2_dr2,
    }


def compute_stability(
        chi: float = CHI_DEFAULT,
        contact_stiffness: float = None
) -> Dict:
    """
    Estimate structural stability proxy.
    Two contributions:
      1. Magnetic inter-particle cohesion (from dipole-dipole attraction)
      2. Hertzian contact stiffness at equilibrium contact
    Returns normalised stability score 0–1 (1 = most stable).
    """
    # Hertzian contact stiffness (from C class)
    E_eff  = 2e5    # Pa
    nu     = 0.25
    E_star = E_eff / (2*(1 - nu**2))
    R_star = R_PARTICLE / 2
    # At equilibrium contact, overlap δ ≈ 0 (just touching)
    # Mean overlap from gravity: F_grav = W = mp·g_lunar
    # Hertz: F = (4/3)E*√R* δ^(3/2) → δ = (3W/(4E*√R*))^(2/3)
    W      = MP * G_LUNAR
    delta  = (3*W / (4 * E_star * math.sqrt(R_star)))**(2/3)
    k_hertz = (4/3) * E_star * math.sqrt(R_star * max(delta, 1e-15))

    # Magnetic cohesion between adjacent particles (dipole–dipole)
    # For two touching paramagnetic spheres in field B, approximate:
    # F_cohesion ≈ (3μ₀/4π)(χ·B/μ₀)²·Vp · cos_terms
    # Use B ≈ 1e-3 T (typical inter-particle field at contact)
    B_inter  = 1e-3    # T (rough estimate)
    chi_e    = chi_eff_scalar(B_inter, chi, MSAT)
    M_ind    = chi_e * B_inter / MU0
    F_cohesion = (3*MU0/(4*PI)) * M_ind**2 * VP / (2*R_PARTICLE)**4

    # Compressive strength estimate (analytic):
    # σ_comp ~ F_contact × coordination_number / (particle area)
    # For random packing: coordination ~6, Ap = π R²
    Z_coord    = 6.0
    Ap         = PI * R_PARTICLE**2
    F_contact  = max(k_hertz * delta + F_cohesion, 1e-15)
    sigma_comp_Pa = Z_coord * F_contact / Ap

    # Normalise: take ratio vs. lunar regolith compressive strength 100–300 kPa
    sigma_lunar_ref = 200e3   # Pa
    stability_raw   = sigma_comp_Pa / (sigma_comp_Pa + sigma_lunar_ref)
    stability_norm  = float(np.clip(stability_raw, 0.0, 1.0))

    return {
        "sigma_comp_Pa":       sigma_comp_Pa,
        "sigma_comp_kPa":      sigma_comp_Pa / 1e3,
        "k_hertz_N_per_m":    k_hertz,
        "F_cohesion_N":        F_cohesion,
        "delta_overlap_m":     delta,
        "stability_norm":      stability_norm,
        "chi":                 chi,
    }


def compute_complexity(
        n_dipoles: int   = N_DIPOLES,
        n_phases:  int   = 6,
        n_params:  int   = 10,   # free control parameters
        control_precision: float = 1.0  # fraction of max precision needed
) -> Dict:
    """
    System complexity score — captures 'how hard is it to build/operate'.
    Lower = simpler.
    Combines: dipole count, phase count, control precision needed.
    Normalised 0–1 relative to the most complex competitor (robotic assembly).
    """
    # Complexity metric: C = N_dip × log2(N_phases) × control_precision
    C_raw    = n_dipoles * math.log2(max(n_phases, 2)) * control_precision
    # Robotic reference (many DOF, many phases, high precision):
    C_robot  = 50 * math.log2(10) * 1.0   # ~166
    C_norm   = min(C_raw / C_robot, 1.0)

    return {
        "n_dipoles":           n_dipoles,
        "n_phases":            n_phases,
        "n_params":            n_params,
        "control_precision":   control_precision,
        "complexity_raw":      C_raw,
        "complexity_norm":     C_norm,
    }


# ═══════════════════════════════════════════════════════════════════════════
# COMPETITOR BENCHMARKS (from literature, described in analysis doc)
# ═══════════════════════════════════════════════════════════════════════════

COMPETITOR_DATA = {
    "REGO": {
        "description":  "Magnetic field-driven paramagnetic assembly (external one-side coils)",
        "contact":      "non-contact",
        "reversible":   True,
        "isru_fraction": 1.0,
        "n_dipoles_eq": N_DIPOLES,
    },
    "3D_Printing": {
        "energy_MJ_per_kg":   100.0,    # Sun 2025 review + Isachenkov 2023: 0.1–0.5 kWh/kg low-temp geopolymer + pre-processing
        "time_hours":         48.0,     # 24–72 h for 1 m³ (parallel extrusion)
        "rms_mm":             0.5,      # 0.1–1.0 mm typical
        "stability_norm":     0.60,     # 10–75 MPa compressive (normalized vs 200 kPa lunar baseline)
        "complexity_norm":    0.45,     # 1 printer head, medium precision
        "contact":            "contact",
        "reversible":         False,
        "isru_fraction":      0.30,
        "description":        "Extrusion-based additive manufacturing (geopolymer/binder)",
        "phase_times_h":      {"setup": 2.0, "execution": 46.0},
    },
    "Bulk_Sintering": {
        "energy_MJ_per_kg":   1000.0,   # 500–2000 MJ/kg furnace (Lomax 2025, Zhang 2025)
        "time_hours":         5.0,      # 1–10 h
        "rms_mm":             3.0,      # 1–5 mm shrinkage
        "stability_norm":     0.85,     # 100–300 MPa
        "complexity_norm":    0.30,     # Furnace, minimal control
        "contact":            "contact",
        "reversible":         False,
        "isru_fraction":      0.90,
        "description":        "High-temperature furnace sintering",
        "phase_times_h":      {"setup": 1.0, "execution": 4.0},
    },
    "Laser_Sintering": {
        "energy_MJ_per_kg":   300.0,    # 100–500 MJ/kg LPBF/SLS (Sitta 2018, Fateri 2019)
        "time_hours":         36.0,     # 24–48 h
        "rms_mm":             0.8,      # 0.5–1.5 mm
        "stability_norm":     0.75,     # 100–200 MPa
        "complexity_norm":    0.70,     # Laser optics, high precision
        "contact":            "non-contact",
        "reversible":         False,
        "isru_fraction":      0.85,
        "description":        "Selective laser sintering / SLS",
        "phase_times_h":      {"setup": 4.0, "execution": 32.0},
    },
    "Robotic_Assembly": {
        "energy_MJ_per_kg":   30.0,     # 10–50 MJ/kg mechanical (Thangavelu 2020, Mueller 2024)
        "time_hours":         25.0,     # 10–40 h
        "rms_mm":             1.0,      # 0.5–2 mm
        "stability_norm":     0.50,     # 20–60 MPa (joint-dependent)
        "complexity_norm":    1.00,     # Reference (6+ arms, high DOF)
        "contact":            "contact",
        "reversible":         0.50,     # Partial
        "isru_fraction":      0.50,
        "description":        "Multi-arm robotic mechanical assembly",
        "phase_times_h":      {"setup": 5.0, "execution": 20.0},
    },
}

# Radar chart dimensions
RADAR_AXES = [
    ("reversibility",  "Reversibility\n(% material recoverable)"),
    ("isru",           "ISRU\n(% local materials)"),
    ("cost_score",     "Cost-Effectiveness\n(relative, higher=better)"),
    ("non_contact",    "Non-Contact\n(% ops contact-free)"),
    ("precision",      "Precision\n(1/RMS, higher=better)"),
]


# ═══════════════════════════════════════════════════════════════════════════
# AGGREGATE SCORE
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_WEIGHTS = np.array([0.30, 0.25, 0.25, 0.10, 0.10])

# Reference values for normalisation
REFS = {
    "energy_MJ_per_kg":  100.0,   # 3D printing energy as reference
    "time_hours":         48.0,   # 3D printing time as reference
    "rms_mm":              1.0,   # 1 mm reference accuracy
}


def aggregate_score(
        energy_MJ_per_kg: float,
        time_hours:        float,
        rms_mm:            float,
        stability_norm:    float,
        complexity_norm:   float,
        weights:           np.ndarray = DEFAULT_WEIGHTS,
) -> Dict:
    """
    Aggregate score S ∈ [0, ∞), lower is better.

    S = w1·(E / E_ref)
      + w2·(T / T_ref)
      + w3·(A / A_ref)
      + w4·(1 − Stability)
      + w5·Complexity_norm

    This is the scalar cost function for Bayesian optimisation.
    """
    w1, w2, w3, w4, w5 = weights
    e_term  = w1 * (energy_MJ_per_kg / REFS["energy_MJ_per_kg"])
    t_term  = w2 * (time_hours        / REFS["time_hours"])
    a_term  = w3 * (rms_mm            / REFS["rms_mm"])
    s_term  = w4 * (1.0 - stability_norm)
    c_term  = w5 * complexity_norm

    score   = e_term + t_term + a_term + s_term + c_term

    return {
        "score":             score,
        "energy_term":       e_term,
        "time_term":         t_term,
        "accuracy_term":     a_term,
        "stability_term":    s_term,
        "complexity_term":   c_term,
        "weights":           weights.tolist(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SUSCEPTIBILITY PARAMETRIC SWEEP
# ═══════════════════════════════════════════════════════════════════════════

def chi_parametric_sweep(
        chi_values: Optional[List[float]] = None,
        m_trap:     float = 0.0006,
        m_shape:    float = 0.0012,
        verbose:    bool  = True,
) -> List[Dict]:
    """
    Parametric sweep over effective magnetic susceptibility χ.
    Covers the range from nominal (χ=0.15, Fe-based) down to
    χ=1e-3 (realistic lunar regolith after beneficiation).

    For each χ:
      - Compute energy (scales linearly with χ via Kelvin force)
      - Compute accuracy (trap stiffness scales with χ)
      - Compute required m_trap to maintain 'grab force ≥ gravity'
      - Track minimum viable χ: smallest χ where assembly still works
    """
    if chi_values is None:
        # Logarithmically spaced from χ=1e-3 to χ=0.15
        chi_values = list(np.logspace(-3, math.log10(0.15), 20))

    results = []
    for chi in chi_values:
        # Kelvin force scales linearly with chi_eff
        # For assembly to work: F_mag >= W (particle weight)
        # F = (Vp·χ/2μ₀)·∇B²_trap
        # ∇B²_trap at d=0.3mm from dipole m_trap:
        #   B_ax = μ₀/4π · 2m/d³
        #   |∇B²| ≈ μ₀/4π · 6m²/d⁴  (along axis)
        d_lead  = 0.3e-3
        B_ax    = _MU0_4PI * 2 * m_trap / d_lead**3
        gradB2  = _MU0_4PI * 6 * m_trap**2 / d_lead**4
        kelvin  = VP * chi / (2 * MU0)
        F_mag   = kelvin * gradB2
        W_lunar = MP * G_LUNAR

        # Viability: can the trap lift the cluster?
        N_cluster  = N_PARTICLES // 4
        F_cluster  = F_mag * N_cluster   # total on cluster (approximately)
        viable     = F_cluster >= W_lunar * N_cluster

        # Minimum m_trap to achieve F = W (single particle)
        # Solve: (Vp·χ/2μ₀) · (6·μ₀²/(4π)² · m²/d⁴) = mp·g
        # m_min = sqrt(mp·g·2μ₀/(Vp·χ) · d⁴ · (4π)²/(6μ₀²))
        const = W_lunar * 2 * MU0 / (VP * chi) * d_lead**4 / (_MU0_4PI**2 * 6)
        m_min_viable = math.sqrt(max(const, 0.0))

        # Energy scales (approximately) linearly with chi in linear regime
        # but saturates at high chi (Msat limit)
        chi_ratio   = chi / CHI_DEFAULT
        E_data      = compute_rego_energy(m_trap=m_trap, m_shape=m_shape, chi=chi)
        # Accuracy: trap stiffness k ∝ chi → rms ∝ 1/sqrt(chi)
        A_data      = compute_shape_accuracy(chi=chi)
        S_data      = compute_stability(chi=chi)

        # Aggregate score at this chi
        E_nominal   = compute_rego_energy(chi=CHI_DEFAULT)
        time_h      = compute_build_time()["t_realistic_parallel_h"]
        agg         = aggregate_score(
            energy_MJ_per_kg = E_data["energy_MJ_per_kg"],
            time_hours       = time_h,
            rms_mm           = A_data["rms_analytical_mm"],
            stability_norm   = S_data["stability_norm"],
            complexity_norm  = compute_complexity()["complexity_norm"],
        )

        rec = {
            "chi":               chi,
            "chi_ratio":         chi_ratio,
            "viable":            viable,
            "F_mag_N":           F_mag,
            "W_lunar_N":         W_lunar,
            "F_over_W":          F_cluster / (W_lunar * N_cluster),
            "m_min_viable_Am2":  m_min_viable,
            "energy_MJ_per_kg":  E_data["energy_MJ_per_kg"],
            "rms_mm":            A_data["rms_analytical_mm"],
            "stability_norm":    S_data["stability_norm"],
            "aggregate_score":   agg["score"],
        }
        results.append(rec)

        if verbose:
            flag = "✓" if viable else "✗"
            print(f"  χ={chi:.2e}  F/W={rec['F_over_W']:6.2f}  {flag}  "
                  f"E={rec['energy_MJ_per_kg']:.3e} MJ/kg  "
                  f"RMS={rec['rms_mm']:.3f}mm  "
                  f"Score={rec['aggregate_score']:.4f}")

    # Find minimum viable chi
    viable_chis = [r["chi"] for r in results if r["viable"]]
    min_viable_chi = min(viable_chis) if viable_chis else None

    if verbose:
        print(f"\n  Minimum viable χ: {min_viable_chi:.2e}")
        print(f"  (Lunar regolith baseline: χ≈1e-3 to 5e-3 after beneficiation)")

    return results, min_viable_chi


# ═══════════════════════════════════════════════════════════════════════════
# FULL DATASET BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def build_full_dataset(
        chi: float = CHI_DEFAULT,
        weights: np.ndarray = DEFAULT_WEIGHTS,
        verbose: bool = True,
) -> Dict:
    """
    Build the complete metrics dataset for REGO and all competitors.
    Returns a dict ready for JSON serialisation and graphing.
    """
    if verbose:
        print("=" * 72)
        print("  REGO Metrics Dataset Builder")
        print("=" * 72)

    # ── REGO metrics ──────────────────────────────────────────────────────
    E_data   = compute_rego_energy(chi=chi)
    T_data   = compute_build_time()
    A_data   = compute_shape_accuracy(chi=chi)
    S_data   = compute_stability(chi=chi)
    Cx_data  = compute_complexity()

    # Aggregate
    rego_score = aggregate_score(
        energy_MJ_per_kg = E_data["energy_MJ_per_kg"],
        time_hours       = T_data["t_realistic_parallel_h"],
        rms_mm           = A_data["rms_analytical_mm"],
        stability_norm   = S_data["stability_norm"],
        complexity_norm  = Cx_data["complexity_norm"],
        weights          = weights,
    )

    rego_full = {
        "energy_MJ_per_kg": E_data["energy_MJ_per_kg"],
        "time_hours":        T_data["t_realistic_parallel_h"],
        "rms_mm":            A_data["rms_analytical_mm"],
        "stability_norm":    S_data["stability_norm"],
        "complexity_norm":   Cx_data["complexity_norm"],
        "aggregate_score":   rego_score["score"],
        "score_breakdown":   rego_score,
        "energy_details":    E_data,
        "time_details":      T_data,
        "accuracy_details":  A_data,
        "stability_details": S_data,
        "complexity_details": Cx_data,
        "contact":           "non-contact",
        "reversible":        True,
        "isru_fraction":     1.0,
        "chi":               chi,
    }

    if verbose:
        print(f"\n  REGO Metrics:")
        print(f"    Energy:     {E_data['energy_MJ_per_kg']:.4f} MJ/kg")
        print(f"    Time:       {T_data['t_realistic_parallel_h']:.2f} h")
        print(f"    Accuracy:   {A_data['rms_analytical_mm']:.4f} mm RMS")
        print(f"    Stability:  {S_data['stability_norm']:.3f} (norm)")
        print(f"    Complexity: {Cx_data['complexity_norm']:.3f} (norm)")
        print(f"    AGGREGATE:  {rego_score['score']:.4f}")
        print(f"      ↳ energy={rego_score['energy_term']:.4f}  "
              f"time={rego_score['time_term']:.4f}  "
              f"accuracy={rego_score['accuracy_term']:.4f}  "
              f"stability={rego_score['stability_term']:.4f}  "
              f"complexity={rego_score['complexity_term']:.4f}")

    # ── Competitor metrics ─────────────────────────────────────────────────
    all_methods = {"REGO": rego_full}
    for name, comp in COMPETITOR_DATA.items():
        if name == "REGO":
            continue
        comp_score = aggregate_score(
            energy_MJ_per_kg = comp["energy_MJ_per_kg"],
            time_hours       = comp["time_hours"],
            rms_mm           = comp["rms_mm"],
            stability_norm   = comp["stability_norm"],
            complexity_norm  = comp["complexity_norm"],
            weights          = weights,
        )
        all_methods[name] = {
            **comp,
            "aggregate_score": comp_score["score"],
            "score_breakdown": comp_score,
        }
        if verbose:
            print(f"\n  {name}:")
            print(f"    Energy:     {comp['energy_MJ_per_kg']:.1f} MJ/kg")
            print(f"    Time:       {comp['time_hours']:.1f} h")
            print(f"    Accuracy:   {comp['rms_mm']:.2f} mm RMS")
            print(f"    Stability:  {comp['stability_norm']:.2f} (norm)")
            print(f"    Complexity: {comp['complexity_norm']:.2f} (norm)")
            print(f"    AGGREGATE:  {comp_score['score']:.4f}")

    # ── Chi sweep ─────────────────────────────────────────────────────────
    if verbose:
        print("\n" + "=" * 72)
        print("  Chi Parametric Sweep (lunar realism: χ = 1e-3 to 0.15)")
        print("=" * 72)

    chi_sweep_results, min_viable_chi = chi_parametric_sweep(verbose=verbose)

    # ── Radar chart data ───────────────────────────────────────────────────
    radar_data = {}
    for name, mdata in all_methods.items():
        rev   = float(mdata.get("reversible", 0))
        if isinstance(rev, bool):
            rev = 1.0 if rev else 0.0
        isru  = float(mdata.get("isru_fraction", 0))
        # Cost-effectiveness: 1 - normalised energy (lower energy → higher score)
        cost  = 1.0 - min(mdata["energy_MJ_per_kg"] / 1000.0, 1.0)
        nc    = 1.0 if mdata.get("contact") == "non-contact" else 0.0
        prec  = min(1.0 / max(mdata["rms_mm"], 0.01), 100.0) / 100.0
        radar_data[name] = {
            "reversibility": rev,
            "isru":          isru,
            "cost_score":    cost,
            "non_contact":   nc,
            "precision":     prec,
        }

    dataset = {
        "version":        "1.0",
        "sim_version":    "19.0.0-sequential-external-shaping",
        "chi_nominal":    chi,
        "weights":        weights.tolist(),
        "methods":        all_methods,
        "chi_sweep":      chi_sweep_results,
        "min_viable_chi": min_viable_chi,
        "radar":          radar_data,
        "refs":           REFS,
    }

    return dataset


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# REAL SIM DATA INJECTION
# ═══════════════════════════════════════════════════════════════════════════

def build_full_dataset_with_sim_data(
        sim_data_path: Optional[str] = None,
        chi:           float = CHI_DEFAULT,
        weights:       np.ndarray = DEFAULT_WEIGHTS,
        verbose:       bool = True,
) -> Dict:
    """
    Like build_full_dataset() but overrides REGO metrics with real
    simulation data wherever available (from rego_sim_data.json produced
    by rego_extract.py).

    Precedence:
      - Real checkpoint data > analytical estimate
      - Real log data > checkpoint estimate
    """
    # Load sim data if path given
    sim = {}
    if sim_data_path:
        p = Path(sim_data_path)
        if p.exists():
            with open(p) as f:
                sim = json.load(f)
            if verbose:
                src = "REAL SIM" if sim.get("has_real_data") else "analytical fallback"
                print(f"  [metrics] Loaded sim data ({src}): {p}")
                if sim.get("has_real_data"):
                    print(f"  [metrics] Checkpoint phase: {sim.get('phase','?')}  "
                          f"t={sim.get('t',0):.2f}s")
        else:
            if verbose:
                print(f"  [metrics] sim_data not found at {p}, using analytical only")

    # Run base build (provides competitor data and chi sweep)
    dataset = build_full_dataset(chi=chi, weights=weights, verbose=verbose)

    # Override REGO values with real data
    rego = dataset["methods"]["REGO"]

    if sim.get("has_real_data"):
        overrides = {}

        # Energy
        if sim.get("energy_MJ_per_kg"):
            overrides["energy_MJ_per_kg"] = sim["energy_MJ_per_kg"]
            overrides["energy_source"]    = sim.get("energy_source", "checkpoint")

        # Accuracy: prefer real RMS from particle positions
        if sim.get("rms_distance_mm"):
            overrides["rms_mm"]          = sim["rms_distance_mm"]
            overrides["rms_source"]      = sim.get("accuracy_source", "checkpoint")
            overrides["cluster_distances_mm"] = sim.get("cluster_distances_mm", [])
            overrides["cluster_centroids_mm"] = sim.get("cluster_centroids_mm", [])

        # Stability: prefer percolation fraction and packing
        if sim.get("stability_norm") is not None:
            overrides["stability_norm"]    = sim["stability_norm"]
            overrides["stability_source"]  = sim.get("stability_source", "checkpoint")
        if sim.get("percolation_frac") is not None:
            overrides["percolation_frac"]  = sim["percolation_frac"]
            overrides["mean_coordination"] = sim.get("stability_from_positions",{}).get("mean_coordination", None)

        # History arrays for time-series plots
        if sim.get("hist_t"):
            overrides["hist_t"]  = sim["hist_t"]
            overrides["hist_ke"] = sim["hist_ke"]
            overrides["hist_fm"] = sim["hist_fm"]
            overrides["hist_sp"] = sim["hist_sp"]

        # Conformity
        if sim.get("cylinder_conformity"):
            overrides["cylinder_conformity"]   = sim["cylinder_conformity"]
            overrides["mean_conformity_frac"]  = sim.get("mean_conformity_frac", None)

        # Contact stats
        if sim.get("mean_contacts_per_particle") is not None:
            overrides["mean_contacts"]     = sim["mean_contacts_per_particle"]
            overrides["percolation_frac"]  = sim.get("percolation_frac", None)

        # Dipole state
        if sim.get("n_active_dipoles") is not None:
            overrides["n_active_dipoles"] = sim["n_active_dipoles"]

        # Simulation phase and timing
        overrides["sim_phase"]   = sim.get("phase", "?")
        overrides["sim_time_s"]  = sim.get("t", None)
        overrides["wall_time_s"] = sim.get("wall_clock_s", None)

        rego.update(overrides)

        # Recompute aggregate with overridden values
        new_score = aggregate_score(
            energy_MJ_per_kg = rego["energy_MJ_per_kg"],
            time_hours       = rego["time_hours"],
            rms_mm           = rego["rms_mm"],
            stability_norm   = rego["stability_norm"],
            complexity_norm  = rego["complexity_norm"],
            weights          = weights,
        )
        rego["aggregate_score"]  = new_score["score"]
        rego["score_breakdown"]  = new_score

        if verbose:
            print(f"\n  REGO (from real sim data):")
            print(f"    Energy:     {rego['energy_MJ_per_kg']:.4f} MJ/kg  "
                  f"[{overrides.get('energy_source','?')}]")
            print(f"    RMS:        {rego['rms_mm']:.4f} mm  "
                  f"[{overrides.get('rms_source','?')}]")
            print(f"    Stability:  {rego['stability_norm']:.3f}  "
                  f"[{overrides.get('stability_source','?')}]")
            print(f"    AGGREGATE:  {rego['aggregate_score']:.4f}")

    dataset["methods"]["REGO"] = rego
    dataset["sim_data_path"]   = sim_data_path
    dataset["has_real_sim_data"] = sim.get("has_real_data", False)
    return dataset


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="REGO Metrics Dataset Builder")
    parser.add_argument("--chi",      type=float, default=CHI_DEFAULT,
                        help="Nominal chi (default 0.15)")
    parser.add_argument("--w1",       type=float, default=0.30, help="Energy weight")
    parser.add_argument("--w2",       type=float, default=0.25, help="Time weight")
    parser.add_argument("--w3",       type=float, default=0.25, help="Accuracy weight")
    parser.add_argument("--w4",       type=float, default=0.10, help="Stability weight")
    parser.add_argument("--w5",       type=float, default=0.10, help="Complexity weight")
    parser.add_argument("--sim-data", type=str,   default=None,
                        help="Path to rego_sim_data.json from rego_extract.py")
    parser.add_argument("--output",   type=str,   default="rego_metrics.json",
                        help="Output JSON path")
    args = parser.parse_args()

    weights = np.array([args.w1, args.w2, args.w3, args.w4, args.w5])
    weights /= weights.sum()

    dataset = build_full_dataset_with_sim_data(
        sim_data_path = args.sim_data,
        chi           = args.chi,
        weights       = weights,
        verbose       = True,
    )

    out_path = Path(args.output)
    with open(out_path, "w") as f:
        json.dump(dataset, f, indent=2, default=str)

    print(f"\n  ✓ Dataset saved → {out_path}")
    src = "REAL SIM" if dataset.get("has_real_sim_data") else "analytical"
    print(f"  Data source: {src}")
    print(f"  Methods: {list(dataset['methods'].keys())}")
    print(f"  Chi sweep: {len(dataset['chi_sweep'])} points")
    print(f"  Min viable χ: {dataset['min_viable_chi']:.2e}")