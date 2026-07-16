#!/usr/bin/env python3
"""
REGO Phase 2 — Shaping Phase Sensitivity Analysis  (v29 architecture)
=======================================================================

DESIGN PRINCIPLE — FAST WITHOUT RUNNING THE FULL SIMULATION:
  The full simulation runs ~45s of sim-time at dt=8µs = 5.6M steps.
  95% of that time is settle + cluster + transport (before shaping).
  This script analyses ONLY the shaping phase by:

    1. LOADING the shape checkpoint (outputs/shape_checkpoint.pkl) saved
       automatically by the main sim when it first enters shaping.
       This gives us real particle positions at the start of shaping.

    2. If no checkpoint exists, synthetically generating a compact-cluster
       initial condition at each target (analytically, not via sim).

    3. Running a SHORT shaping sub-simulation (~0.5–2 s per parameter set)
       that starts from the shape-start state and evaluates METRICS directly.

  For N=256 particles, each 2s shaping sub-sim takes ~5–15 s wall time
  (CPU) or ~1–3 s (GPU). A full parameter sweep of 3 params × 5 levels
  (125 combos) finishes in < 30 min on CPU, < 5 min on GPU.

METRICS COMPUTED PER PARAMETER SET:
  For caps (Q0, Q3):
    - ring_fraction:   fraction of particles within ±2R of target z AND
                       |r - cR| < 4R  (on the ring at the right z)
    - radial_spread:   std-dev of particle radii (ρ from cylinder axis)
    - z_stability:     std-dev of z-positions (how tightly z is pinned)
    - ring_uniformity: circular variance of azimuthal angles (0=uniform, 1=bunched)
  For walls (Q1, Q2):
    - wall_fraction:   fraction within ±4R of cylinder wall (r ≈ cR)
    - z_coverage:      fraction of z-span [z_lo, z_hi] that has at least 1 particle
    - az_coverage:     azimuthal arc spanned by particles (radians)
    - centroid_dist:   distance of cluster centroid from target (mm)

  OVERALL SCORE = weighted sum:  higher is better.

PARAMETERS SWEPT:
  CAP parameters:
    N_CAP_RING:       [4, 6, 8, 10, 12]       number of ring dipoles
    CAP_RING_R_END:   [1.00, 1.05, 1.10, 1.15, 1.20]  end radius / cR
    CAP_SHAPE_HOLD_S: [0.05, 0.10, 0.15, 0.20, 0.25]  z-pinning strength
    SHAPE_D_SURF:     [0.5, 0.7, 0.9, 1.1, 1.3] mm     axial offset
  WALL parameters:
    N_WALL_RAKE:      [4, 6, 8, 10, 12]        number of rake dipoles
    WALL_RAKE_HALF_AZ:[PI/6, PI/4, PI/3, PI/2.5, PI/2]  sweep half-angle

USAGE:
  # Run full 1-D sweep of each parameter (others fixed at default):
  python shaping_sensitivity.py

  # Full 2-D grid search (expensive, use --mode grid):
  python shaping_sensitivity.py --mode grid --params N_CAP_RING CAP_RING_R_END

  # Use shape checkpoint for exact initial conditions:
  python shaping_sensitivity.py --use-checkpoint

  # Set sub-sim duration (shorter = faster, noisier):
  python shaping_sensitivity.py --sub-sim-time 1.0

  # Output CSV for analysis:
  python shaping_sensitivity.py --csv results.csv
"""

import sys, os, math, argparse, itertools, time as _time, json
import numpy as np
from pathlib import Path

PI    = math.pi
MU0   = 4.0 * PI * 1e-7
_M4PI = MU0 / (4.0 * PI)

# ── Default shaping parameters (v29 defaults) ──────────────────────────────
DEFAULTS = dict(
    # Physical
    N                 = 256,
    R                 = 3e-5,
    rho               = 7800.0,
    g                 = 1.62,
    chi               = 0.15,
    Msat              = 2e5,
    dt                = 8e-6,

    # Geometry
    L                 = 0.010,
    cR                = 0.010 / 6,
    cH                = 4e-3,

    # Shaping parameters (v29)
    N_CAP_RING        = 6,
    N_WALL_RAKE       = 6,
    CAP_RING_R_START  = 0.10,
    CAP_RING_R_END    = 1.08,
    CAP_COMPRESS_R    = 0.95,
    SHAPE_D_SURF      = 0.9e-3,
    CAP_SHAPE_HOLD_S  = 0.15,
    SHAPE_ACTIVE_STR  = 0.70,
    SHAPE_MAX_CLAMP   = 800.0,
    WALL_RAKE_HALF_AZ = PI / 4.0,
    _m_shape          = 0.0010,
    _m_hold           = 0.006,
    _hold_ring_R      = 3.0e-3,
    _delta_g          = 0.05e-3,
)

# ── Parameter sweep ranges ───────────────────────────────────────────────────
PARAM_RANGES = {
    'N_CAP_RING':        [4, 6, 8, 10, 12],
    'CAP_RING_R_END':    [1.00, 1.05, 1.10, 1.15, 1.20],
    'CAP_SHAPE_HOLD_S':  [0.05, 0.10, 0.15, 0.20, 0.25],
    'SHAPE_D_SURF_mm':   [0.5e-3, 0.7e-3, 0.9e-3, 1.1e-3, 1.3e-3],
    'N_WALL_RAKE':       [4, 6, 8, 10, 12],
    'WALL_RAKE_HALF_AZ': [PI/6, PI/4, PI/3, PI/2.5, PI/2],
    'SHAPE_ACTIVE_STR':  [0.40, 0.55, 0.70, 0.85, 1.00],
}

# ── Targets (same as main sim) ───────────────────────────────────────────────
def get_targets(cfg):
    L  = cfg['L']
    cx = L / 2; cy = L / 2; cz = L / 2
    cR = cfg['cR']
    return np.array([
        [5.0e-3, 5.0e-3, 7.2e-3],
        [5.0e-3 - cR - 0.2e-3, 5.0e-3, 5.0e-3],
        [5.0e-3 + cR + 0.2e-3, 5.0e-3, 5.0e-3],
        [5.0e-3, 5.0e-3, 2.8e-3],
    ], dtype=np.float64)


# ═══════════════════════════════════════════════════════════════════════════
# SYNTHETIC INITIAL CONDITION
# ═══════════════════════════════════════════════════════════════════════════
def make_compact_cluster(target, n_particles, R_particle, seed=42):
    """
    Place n_particles in a compact sphere around target.
    Uses random packing within radius 1.5 * n^(1/3) * 2R_particle.
    """
    rng = np.random.default_rng(seed)
    r_max = 1.8 * (n_particles ** (1.0/3.0)) * 2.0 * R_particle
    pos = []
    attempts = 0
    while len(pos) < n_particles and attempts < n_particles * 2000:
        p = target + rng.uniform(-r_max, r_max, 3)
        if np.linalg.norm(p - target) < r_max:
            # Check no overlap with existing
            ok = True
            for q in pos:
                if np.linalg.norm(p - q) < 2.0 * R_particle:
                    ok = False
                    break
            if ok:
                pos.append(p.copy())
        attempts += 1
    if len(pos) < n_particles:
        # Fall back: jitter around target on a grid
        side = int(math.ceil(n_particles ** (1.0/3.0)))
        sp = 2.2 * R_particle
        pos = []
        for ix in range(side):
            for iy in range(side):
                for iz in range(side):
                    if len(pos) >= n_particles: break
                    p = target + sp * np.array([ix - side//2, iy - side//2, iz - side//2], dtype=float)
                    pos.append(p)
    return np.array(pos[:n_particles], dtype=np.float64)


def make_initial_state(cfg, ckpt_data=None):
    """
    Returns (pos_np, vel_np, cluster_id_np) for all 4 clusters at their targets.
    Uses checkpoint data if provided, otherwise synthesizes compact clusters.
    """
    N  = cfg['N']
    n_per = N // 4
    R  = cfg['R']
    L  = cfg['L']
    targets = get_targets(cfg)

    if ckpt_data is not None:
        pos_np = ckpt_data['pos'].copy()
        vel_np = np.zeros_like(ckpt_data['vel'])   # zero vel for clean shaping start
        cl_np  = ckpt_data['cluster_id'].copy()
        return pos_np, vel_np, cl_np

    # Synthetic: compact cluster at each target
    pos_all = []
    cl_all  = []
    for k in range(4):
        cluster_pos = make_compact_cluster(targets[k], n_per, R, seed=42 + k)
        # Clip to domain
        cluster_pos = np.clip(cluster_pos, R, L - R)
        pos_all.append(cluster_pos)
        cl_all.append(np.full(n_per, k, dtype=np.int32))

    pos_np = np.vstack(pos_all)
    vel_np = np.zeros((N, 3), dtype=np.float64)
    cl_np  = np.concatenate(cl_all)
    return pos_np, vel_np, cl_np


# ═══════════════════════════════════════════════════════════════════════════
# MAGNETIC FIELD (NumPy-only, for sensitivity analysis)
# ═══════════════════════════════════════════════════════════════════════════

def B_dipole_batch(dip_pos, dip_mom, dip_str, r_arr):
    """
    Compute total B field at each of N points in r_arr (N,3).
    dip_pos: (M,3), dip_mom: (M,3), dip_str: (M,) scalar strength.
    Returns B: (N,3)
    """
    B = np.zeros_like(r_arr)
    for k in range(len(dip_pos)):
        s = dip_str[k]
        if s < 1e-15: continue
        mv  = dip_mom[k] * s
        rv  = r_arr - dip_pos[k]          # (N,3)
        r2  = np.sum(rv**2, axis=1)       # (N,)
        mask = r2 > 1e-22
        if not np.any(mask): continue
        r5   = (r2[mask] ** 2) * np.sqrt(r2[mask])
        mdotr = rv[mask] @ mv             # (N_m,)
        coeff = _M4PI / r5
        B[mask] += coeff[:, None] * (3.0 * mdotr[:, None] * rv[mask] - r2[mask, None] * mv)
    return B


def grad_B2_batch(dip_pos, dip_mom, dip_str, r_arr, clamp=800.0):
    """
    Compute ∇(B²) = 2(B·∇)B analytically at each point.
    Uses the Jacobian method from the main sim.
    Returns gB2: (N,3)
    """
    # Pass 1: total B
    B = B_dipole_batch(dip_pos, dip_mom, dip_str, r_arr)

    # Pass 2: ∇(B²) = 2 Σ_k J_k^T · B
    gB2 = np.zeros_like(r_arr)
    for k in range(len(dip_pos)):
        s = dip_str[k]
        if s < 1e-15: continue
        mv    = dip_mom[k] * s
        rv    = r_arr - dip_pos[k]
        r2    = np.sum(rv**2, axis=1)
        mask  = r2 > 1e-22
        if not np.any(mask): continue
        r5    = (r2[mask]**2) * np.sqrt(r2[mask])
        mdotrv = rv[mask] @ mv
        Bdotrv = np.sum(B[mask] * rv[mask], axis=1)
        mdotB  = B[mask] @ mv
        c5     = _M4PI / r5
        c7     = 15.0 * _M4PI / (r5 * r2[mask])
        gB2[mask] += 2.0 * (
            c5[:, None] * (3.0 * Bdotrv[:, None] * mv
                           + 3.0 * mdotrv[:, None] * B[mask]
                           + 3.0 * mdotB[:, None] * rv[mask])
            - c7[:, None] * mdotrv[:, None] * Bdotrv[:, None] * rv[mask]
        )

    # Soft clamp
    g2 = np.sum(gB2**2, axis=1, keepdims=True)
    scale = clamp / np.sqrt(g2 + clamp**2)
    gB2 *= scale
    return gB2


# ═══════════════════════════════════════════════════════════════════════════
# DIPOLE PLACEMENT FUNCTIONS (mirror of main sim, NumPy-only)
# ═══════════════════════════════════════════════════════════════════════════

def place_cap_ring(cfg, tgt, local_frac, normal_z, active_str):
    """Place cap ring dipoles for the given local_frac progress."""
    n  = cfg['N_CAP_RING']
    d  = cfg['SHAPE_D_SURF']
    r_s = cfg['CAP_RING_R_START'] * cfg['cR']
    r_e = cfg['CAP_RING_R_END']   * cfg['cR']
    r_c = cfg['CAP_COMPRESS_R']   * cfg['cR']
    m   = cfg['_m_shape']

    if local_frac <= 0.65:
        r_ring = r_s + (local_frac / 0.65) * (r_e - r_s)
    elif local_frac <= 0.80:
        r_ring = r_e
    else:
        r_ring = r_e + ((local_frac - 0.80) / 0.20) * (r_c - r_e)
    r_ring = max(r_ring, r_s)

    dip_z = tgt[2] + normal_z * d
    pos_arr = []
    mom_arr = []
    str_arr = []
    for j in range(n):
        phi = 2.0 * PI * j / n
        px = tgt[0] + r_ring * math.cos(phi)
        py = tgt[1] + r_ring * math.sin(phi)
        pos_arr.append([px, py, dip_z])
        mom_arr.append([-math.cos(phi) * m, -math.sin(phi) * m, 0.0])
        str_arr.append(active_str)
    return np.array(pos_arr), np.array(mom_arr), np.array(str_arr)


def place_hold_pair(cfg, tgt, normal, strength):
    """Place the z-pinning hold pair for a cap cluster."""
    rH   = cfg['_hold_ring_R']
    mH   = cfg['_m_hold']
    dg   = cfg['_delta_g']
    t_v  = np.array([0., 1., 0.])  # transverse axis = ŷ (same as main sim)
    s    = strength
    center = tgt + dg * normal
    pA = center + rH * t_v
    pB = center - rH * t_v
    mV = mH * t_v
    return (np.array([pA, pB]),
            np.array([mV, mV]),
            np.array([s, s]))


def place_wall_rake(cfg, tgt, local_frac, active_str, cluster_k):
    """Place wall rake dipoles for the given local_frac progress."""
    n   = cfg['N_WALL_RAKE']
    d   = cfg['SHAPE_D_SURF']
    ha  = cfg['WALL_RAKE_HALF_AZ']
    m   = cfg['_m_shape']
    cR  = cfg['cR']
    L   = cfg['L']
    cH  = cfg['cH']
    cx  = L / 2; cy = L / 2
    z_lo = L/2 - cH/2; z_hi = L/2 + cH/2
    R   = cfg['R']

    base_angle = PI if cluster_k == 1 else 0.0
    theta_rake = base_angle - ha + 2.0 * ha * local_frac
    rad_r = cR + d
    rhat  = np.array([math.cos(theta_rake), math.sin(theta_rake), 0.0])
    rake_px = cx + rad_r * math.cos(theta_rake)
    rake_py = cy + rad_r * math.sin(theta_rake)

    z_positions = np.linspace(z_lo + R, z_hi - R, n)
    pos_arr = [[rake_px, rake_py, z] for z in z_positions]
    mom_arr = [(-rhat * m).tolist() for _ in range(n)]
    str_arr = [active_str] * n
    return np.array(pos_arr), np.array(mom_arr), np.array(str_arr)


# ═══════════════════════════════════════════════════════════════════════════
# MINI-SIMULATION (NumPy only, no Taichi)
# ═══════════════════════════════════════════════════════════════════════════

def run_mini_sim(pos0, vel0, cl0, cfg, cluster_k, sub_sim_time=1.0, eval_only=False):
    """
    Run a short shaping sub-simulation for one cluster.
    Returns a metrics dict.

    If eval_only=True, skip integration and just evaluate metrics at t=0
    (for fast B-field-only analysis).
    """
    N   = cfg['N']
    R   = cfg['R']
    dt  = cfg['dt']
    mp  = (4.0/3.0) * PI * R**3 * cfg['rho']
    L   = cfg['L']
    g   = cfg['g']
    chi = cfg['chi']
    Msat= cfg['Msat']
    Vp  = (4.0/3.0) * PI * R**3
    kelvin_pf = Vp * chi / (2.0 * MU0)

    cR  = cfg['cR']
    cH  = cfg['cH']
    z_lo = L/2 - cH/2; z_hi = L/2 + cH/2
    cx = cy = L/2
    clamp = cfg['SHAPE_MAX_CLAMP']

    targets = get_targets(cfg)
    tgt = targets[cluster_k]

    # Isolate this cluster's particles
    mask_k = cl0 == cluster_k
    pos = pos0[mask_k].copy()
    vel = vel0[mask_k].copy()
    n_k = len(pos)
    if n_k == 0:
        return _null_metrics()

    n_steps = int(sub_sim_time / dt)
    BATCH   = 50   # steps per dipole update (dipoles are near-static: fine)
    n_batch = max(n_steps // BATCH, 1)
    n_eval  = n_steps // BATCH * BATCH

    is_cap  = cluster_k in (0, 3)
    normal_z = 1.0 if cluster_k == 0 else (-1.0 if cluster_k == 3 else 0.0)
    normal   = np.array([0.,0.,normal_z]) if is_cap else (
               np.array([-1.,0.,0.]) if cluster_k==1 else np.array([1.,0.,0.]))

    # Simple contact force (penalty spring, no tangential)
    def contact_walls(p, v):
        F = np.zeros_like(p)
        E_eff = 2e5; nu = 0.25
        E_star = E_eff / (2*(1-nu**2))
        for ax in range(3):
            ov_lo = R - p[:, ax]
            m_lo  = ov_lo > 0
            if np.any(m_lo):
                sRd = np.sqrt(R * ov_lo[m_lo])
                kn  = (4.0/3.0) * E_star * sRd
                F[m_lo, ax] += kn * ov_lo[m_lo]
            ov_hi = p[:, ax] + R - L
            m_hi  = ov_hi > 0
            if np.any(m_hi):
                sRd = np.sqrt(R * ov_hi[m_hi])
                kn  = (4.0/3.0) * E_star * sRd
                F[m_hi, ax] -= kn * ov_hi[m_hi]
        return F

    v_cap = 0.005  # 5 mm/s

    if eval_only:
        n_batch = 1; BATCH = 1

    for batch_i in range(n_batch):
        local_frac = min(batch_i / max(n_batch - 1, 1), 1.0)

        # Build dipole arrays for this cluster and time
        active_str = cfg['SHAPE_ACTIVE_STR']
        # Ramp in: ~30% of slot
        ramp_frac  = min(batch_i / max(n_batch * 0.30, 1), 1.0)
        s_eff = active_str * (0.5 * (1 - math.cos(PI * ramp_frac)))
        if local_frac > 0.80:
            s_eff *= 1.35

        if is_cap:
            p_ring, m_ring, s_ring = place_cap_ring(
                cfg, tgt, local_frac, normal_z, s_eff)
            p_hold, m_hold, s_hold = place_hold_pair(
                cfg, tgt, normal, cfg['CAP_SHAPE_HOLD_S'])
            dip_pos = np.vstack([p_ring, p_hold])
            dip_mom = np.vstack([m_ring, m_hold])
            dip_str = np.concatenate([s_ring, s_hold])
        else:
            p_rake, m_rake, s_rake = place_wall_rake(
                cfg, tgt, local_frac, s_eff, cluster_k)
            # z-lift from anchor below target
            m_trap = 0.0006
            anchor_pos = np.array([[tgt[0], tgt[1], tgt[2] - 2.0e-3]])
            anchor_mom = np.array([[0., 0., m_trap]])
            anchor_str = np.array([cfg['SHAPE_ACTIVE_STR'] * 0.12 / 0.70])
            dip_pos = np.vstack([p_rake, anchor_pos])
            dip_mom = np.vstack([m_rake, anchor_mom])
            dip_str = np.concatenate([s_rake, anchor_str])

        # Sub-batch integration
        for _ in range(BATCH):
            # Gravity
            F = np.zeros_like(pos)
            F[:, 2] -= mp * g

            # Magnetic force
            gB2 = grad_B2_batch(dip_pos, dip_mom, dip_str, pos, clamp)
            B   = B_dipole_batch(dip_pos, dip_mom, dip_str, pos)
            Bm  = np.linalg.norm(B, axis=1)
            # Langevin chi_eff
            alpha = chi * Bm / (MU0 * Msat)
            alpha_s = np.minimum(alpha, 20.0)
            cosh_a  = 0.5 * (np.exp(alpha_s) + np.exp(-alpha_s))
            chi_e   = chi / (cosh_a**2)
            Fm = kelvin_pf * chi_e[:, None] * gB2
            F += Fm

            # Wall contact
            F += contact_walls(pos, vel)

            # Integrate
            a    = F / mp
            vel += a * dt
            spd  = np.linalg.norm(vel, axis=1, keepdims=True)
            mask_fast = spd[:, 0] > v_cap
            vel[mask_fast] = vel[mask_fast] / spd[mask_fast] * v_cap
            pos += vel * dt

            # Reflect off walls
            for ax in range(3):
                lo = pos[:, ax] < R
                pos[lo, ax] = R; vel[lo, ax] = np.abs(vel[lo, ax]) * 0.3
                hi = pos[:, ax] > L - R
                pos[hi, ax] = L - R; vel[hi, ax] = -np.abs(vel[hi, ax]) * 0.3

    return compute_metrics(pos, tgt, cfg, cluster_k)


def compute_metrics(pos, tgt, cfg, cluster_k):
    """Compute shaping quality metrics for a cluster's final positions."""
    cR   = cfg['cR']
    R    = cfg['R']
    L    = cfg['L']
    cH   = cfg['cH']
    z_lo = L/2 - cH/2; z_hi = L/2 + cH/2
    cx   = cy = L/2
    n    = len(pos)
    if n == 0:
        return _null_metrics()

    r_from_axis = np.sqrt((pos[:, 0] - cx)**2 + (pos[:, 1] - cy)**2)
    z_vals      = pos[:, 2]
    az_angles   = np.arctan2(pos[:, 1] - cy, pos[:, 0] - cx)

    if cluster_k in (0, 3):
        # Cap metrics
        at_z     = np.abs(z_vals - tgt[2]) < 4 * R
        at_ring  = (np.abs(r_from_axis - cR) < 6 * R) & at_z
        ring_frac = float(np.mean(at_ring))

        r_spread  = float(np.std(r_from_axis))
        z_spread  = float(np.std(z_vals))

        # Azimuthal uniformity (circular variance)
        sin_mean  = float(np.mean(np.sin(az_angles)))
        cos_mean  = float(np.mean(np.cos(az_angles)))
        R_vec     = math.sqrt(sin_mean**2 + cos_mean**2)
        circ_var  = 1.0 - R_vec  # 0=perfectly uniform, 1=all bunched at one point

        centroid  = np.mean(pos, axis=0)
        cen_dist  = float(np.linalg.norm(centroid - tgt) * 1e3)  # mm

        score = (0.40 * ring_frac
                 + 0.20 * max(0, 1 - z_spread / (3*R))
                 + 0.20 * max(0, 1 - circ_var)
                 + 0.20 * max(0, 1 - cen_dist / 2.0))

        return dict(
            cluster_k    = cluster_k,
            ring_frac    = ring_frac,
            r_spread_mm  = r_spread * 1e3,
            z_spread_mm  = z_spread * 1e3,
            circ_var     = circ_var,
            centroid_mm  = cen_dist,
            wall_frac    = float('nan'),
            z_coverage   = float('nan'),
            az_arc_deg   = float('nan'),
            score        = score,
        )

    else:
        # Wall metrics
        at_wall   = np.abs(r_from_axis - cR) < 6 * R
        in_z      = (z_vals >= z_lo - 2*R) & (z_vals <= z_hi + 2*R)
        wall_frac = float(np.mean(at_wall & in_z))

        # Z coverage: how much of [z_lo, z_hi] is covered (by any particle within ±4R of wall)
        wall_mask = at_wall & in_z
        if np.any(wall_mask):
            z_covered = np.clip(z_vals[wall_mask], z_lo, z_hi)
            n_bins    = 20
            bins      = np.linspace(z_lo, z_hi, n_bins + 1)
            counts, _ = np.histogram(z_covered, bins=bins)
            z_cov = float(np.mean(counts > 0))
        else:
            z_cov = 0.0

        # Azimuthal arc spanned by wall particles
        if np.any(at_wall):
            azs = az_angles[at_wall]
            az_arc = float(np.max(azs) - np.min(azs)) * 180.0 / PI
        else:
            az_arc = 0.0

        centroid  = np.mean(pos, axis=0)
        cen_dist  = float(np.linalg.norm(centroid - tgt) * 1e3)

        score = (0.35 * wall_frac
                 + 0.30 * z_cov
                 + 0.15 * min(az_arc / 60.0, 1.0)
                 + 0.20 * max(0, 1 - cen_dist / 3.0))

        return dict(
            cluster_k   = cluster_k,
            ring_frac   = float('nan'),
            r_spread_mm = float('nan'),
            z_spread_mm = float('nan'),
            circ_var    = float('nan'),
            centroid_mm = cen_dist,
            wall_frac   = wall_frac,
            z_coverage  = z_cov,
            az_arc_deg  = az_arc,
            score       = score,
        )


def _null_metrics():
    return dict(cluster_k=-1, ring_frac=0., r_spread_mm=999., z_spread_mm=999.,
                circ_var=1., centroid_mm=999., wall_frac=0., z_coverage=0.,
                az_arc_deg=0., score=0.)


# ═══════════════════════════════════════════════════════════════════════════
# SENSITIVITY RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def load_checkpoint(ckpt_path='outputs/shape_checkpoint.pkl'):
    try:
        import pickle
        with open(ckpt_path, 'rb') as f:
            data = pickle.load(f)
        print(f"  ✓ Shape checkpoint loaded: t={data['t']:.3f}s, step={data['step']}")
        return data
    except Exception as e:
        print(f"  ✗ Cannot load checkpoint ({ckpt_path}): {e}")
        return None


def run_sweep_1d(pos0, vel0, cl0, base_cfg, sub_sim_time, csv_path=None):
    """Run 1-D sensitivity sweep: one parameter at a time, all others default."""
    results = []
    all_params = list(PARAM_RANGES.keys())

    print(f"\n{'='*72}")
    print(f"  1-D SENSITIVITY SWEEP  (sub_sim_time={sub_sim_time:.1f}s per run)")
    print(f"{'='*72}")

    for param_name in all_params:
        values = PARAM_RANGES[param_name]
        print(f"\n  Parameter: {param_name}  (default={base_cfg.get(param_name, base_cfg.get('SHAPE_D_SURF'))})")
        print(f"  {'Value':>12s}  {'Score_Q0':>9s}  {'Score_Q3':>9s}  {'Score_Q1':>9s}  {'Score_Q2':>9s}  {'Avg':>9s}  {'Time':>6s}")
        print(f"  {'-'*75}")

        for val in values:
            cfg = base_cfg.copy()
            if param_name == 'SHAPE_D_SURF_mm':
                cfg['SHAPE_D_SURF'] = val
                display_val = f"{val*1e3:.2f}mm"
            else:
                cfg[param_name] = val
                display_val = f"{val:.4g}"

            t0 = _time.time()
            scores = []
            for cluster_k in range(4):
                m = run_mini_sim(pos0, vel0, cl0, cfg, cluster_k,
                                 sub_sim_time=sub_sim_time)
                scores.append(m['score'])
            elapsed = _time.time() - t0

            avg_score = float(np.mean(scores))
            print(f"  {display_val:>12s}  "
                  + "  ".join(f"{s:9.4f}" for s in scores)
                  + f"  {avg_score:9.4f}  {elapsed:5.1f}s")

            for k, s in enumerate(scores):
                results.append({
                    'param': param_name,
                    'value': val,
                    'cluster_k': k,
                    'score': s,
                    'avg_score': avg_score,
                })

    if csv_path:
        import csv
        with open(csv_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['param','value','cluster_k','score','avg_score'])
            w.writeheader()
            w.writerows(results)
        print(f"\n  Results written to {csv_path}")

    return results


def run_sweep_grid(pos0, vel0, cl0, base_cfg, param_names, sub_sim_time, csv_path=None):
    """Run 2-D (or N-D) grid sensitivity sweep."""
    ranges = [PARAM_RANGES[p] for p in param_names]
    combos = list(itertools.product(*ranges))
    n_combos = len(combos)

    print(f"\n{'='*72}")
    print(f"  {len(param_names)}-D GRID SWEEP over: {param_names}")
    print(f"  {n_combos} combinations × 4 clusters × {sub_sim_time:.1f}s sub-sim")
    est_time = n_combos * 4 * sub_sim_time * 3  # rough wall-time multiplier
    print(f"  Estimated wall time: ~{est_time:.0f}s  ({est_time/60:.1f} min)")
    print(f"{'='*72}\n")

    results = []
    t_start = _time.time()

    for i, combo in enumerate(combos):
        cfg = base_cfg.copy()
        for pname, val in zip(param_names, combo):
            if pname == 'SHAPE_D_SURF_mm':
                cfg['SHAPE_D_SURF'] = val
            else:
                cfg[pname] = val

        scores = []
        for cluster_k in range(4):
            m = run_mini_sim(pos0, vel0, cl0, cfg, cluster_k,
                             sub_sim_time=sub_sim_time)
            scores.append(m['score'])
        avg = float(np.mean(scores))
        elapsed = _time.time() - t_start

        row = {p: v for p, v in zip(param_names, combo)}
        row.update({'score_Q0': scores[0], 'score_Q3': scores[3],
                    'score_Q1': scores[1], 'score_Q2': scores[2],
                    'avg_score': avg})
        results.append(row)

        eta = elapsed / (i+1) * (n_combos - i - 1)
        combo_str = "  ".join(f"{p}={v:.4g}" for p, v in zip(param_names, combo))
        print(f"  [{i+1:4d}/{n_combos}] {combo_str}  → avg={avg:.4f}  ETA {eta:.0f}s")

    # Sort by avg_score descending
    results.sort(key=lambda r: r['avg_score'], reverse=True)
    print(f"\n  TOP 10 CONFIGURATIONS:")
    print(f"  {'Rank':>4s}  {'avg_score':>9s}  " + "  ".join(f"{p:>14s}" for p in param_names))
    for rank, r in enumerate(results[:10], 1):
        param_str = "  ".join(f"{r[p]:>14.4g}" for p in param_names)
        print(f"  {rank:4d}  {r['avg_score']:9.4f}  {param_str}")

    if csv_path:
        import csv
        with open(csv_path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            w.writerows(results)
        print(f"\n  Results written to {csv_path}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# B-FIELD PROFILE ANALYSIS (fast, no integration)
# ═══════════════════════════════════════════════════════════════════════════

def analyze_b2_profile(cfg, cluster_k, n_pts=200):
    """
    Compute B²(ρ) at mid-slot (local_frac=0.5) in the cap plane or at wall.
    Returns (r_arr, B2_arr) for plotting.
    No particle integration needed — pure field analysis.
    """
    targets = get_targets(cfg)
    tgt     = targets[cluster_k]
    cR      = cfg['cR']

    if cluster_k in (0, 3):
        normal_z = 1.0 if cluster_k == 0 else -1.0
        p_ring, m_ring, s_ring = place_cap_ring(cfg, tgt, 0.5, normal_z, 1.0)
        p_hold, m_hold, s_hold = place_hold_pair(cfg, tgt,
                                                  np.array([0.,0.,normal_z]), 1.0)
        dip_pos = np.vstack([p_ring, p_hold])
        dip_mom = np.vstack([m_ring, m_hold])
        dip_str = np.concatenate([s_ring, s_hold])

        # Radial sweep at z=tgt_z
        r_vals = np.linspace(0, cR * 1.5, n_pts)
        probe  = np.array([[tgt[0] + r, tgt[1], tgt[2]] for r in r_vals])
        B      = B_dipole_batch(dip_pos, dip_mom, dip_str, probe)
        B2     = np.sum(B**2, axis=1)
        return r_vals * 1e3, B2, 'Radial distance from axis (mm)', 'B² (T²)'

    else:
        # Azimuthal sweep at z=tgt_z, r=cR
        base_angle = PI if cluster_k == 1 else 0.0
        ha = cfg['WALL_RAKE_HALF_AZ']
        p_rake, m_rake, s_rake = place_wall_rake(cfg, tgt, 0.5, 1.0, cluster_k)
        anchor_pos = np.array([[tgt[0], tgt[1], tgt[2] - 2.0e-3]])
        anchor_mom = np.array([[0., 0., 0.0006]])
        anchor_str = np.array([0.12])
        dip_pos = np.vstack([p_rake, anchor_pos])
        dip_mom = np.vstack([m_rake, anchor_mom])
        dip_str = np.concatenate([s_rake, anchor_str])

        angles = np.linspace(base_angle - PI/2, base_angle + PI/2, n_pts)
        cx = cy = cfg['L'] / 2
        probe = np.array([[cx + cR * math.cos(a), cy + cR * math.sin(a), tgt[2]]
                          for a in angles])
        B  = B_dipole_batch(dip_pos, dip_mom, dip_str, probe)
        B2 = np.sum(B**2, axis=1)
        return (angles - base_angle) * 180.0 / PI, B2, 'Angle from target (deg)', 'B² (T²)'


def plot_b2_profiles(cfg, out_dir='.'):
    """Plot B²(r) profiles for all 4 clusters at mid-slot."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axs = plt.subplots(2, 2, figsize=(12, 9), tight_layout=True)
        fig.suptitle('B² Profile at mid-slot (v29 static ring/rake)', fontsize=13)
        names = ['Q0 (Top Cap)', 'Q1 (Left Wall)', 'Q2 (Right Wall)', 'Q3 (Bot Cap)']
        ax_order = [axs[0,0], axs[1,0], axs[1,1], axs[0,1]]
        for k, ax in enumerate(ax_order):
            x, B2, xlabel, ylabel = analyze_b2_profile(cfg, k)
            ax.plot(x, B2, 'b-', lw=1.5)
            ax.set(xlabel=xlabel, ylabel=ylabel, title=names[k])
            ax.grid(True)
            peak_x = x[np.argmax(B2)]
            ax.axvline(peak_x, color='r', ls='--', lw=1, label=f'peak={peak_x:.2f}')
            if k in (0, 3):
                cR_mm = cfg['cR'] * 1e3
                ax.axvline(cR_mm, color='g', ls=':', lw=1, label=f'cR={cR_mm:.2f}mm')
            ax.legend(fontsize=8)
        out = os.path.join(out_dir, 'b2_profiles.png')
        plt.savefig(out, dpi=150)
        print(f"  B² profiles → {out}")
    except Exception as e:
        print(f"  Plotting failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='REGO Shaping Phase Sensitivity Analysis v29')
    parser.add_argument('--mode', choices=['1d', 'grid', 'profile'], default='1d',
                        help='1d: sweep each param separately; grid: full N-D grid; '
                             'profile: B² field-only analysis (instant)')
    parser.add_argument('--params', nargs='+', default=None,
                        help='Parameters for grid mode (e.g. N_CAP_RING CAP_RING_R_END)')
    parser.add_argument('--sub-sim-time', type=float, default=1.0,
                        help='Duration of each shaping sub-simulation (seconds). '
                             'Shorter=faster/noisier, longer=accurate/slower.')
    parser.add_argument('--use-checkpoint', action='store_true',
                        help='Load outputs/shape_checkpoint.pkl for initial conditions '
                             '(recommended; falls back to synthetic if not found)')
    parser.add_argument('--checkpoint-path', type=str,
                        default='outputs/shape_checkpoint.pkl')
    parser.add_argument('--csv', type=str, default=None,
                        help='Save results to this CSV file')
    parser.add_argument('--out-dir', type=str, default='outputs/sensitivity',
                        help='Directory for output files')
    parser.add_argument('--plot-profiles', action='store_true',
                        help='Generate B² profile plots (fast, no integration)')
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build base config
    cfg = DEFAULTS.copy()

    print("=" * 72)
    print("  REGO Shaping Phase Sensitivity Analysis — v29 Static Ring/Rake")
    print("=" * 72)
    print(f"  Mode:           {args.mode}")
    print(f"  Sub-sim time:   {args.sub_sim_time:.1f}s per run")
    print(f"  Use checkpoint: {args.use_checkpoint}")
    print(f"  Output dir:     {out_dir}")
    print()

    # Plot B² profiles (field-only, instant)
    if args.plot_profiles or args.mode == 'profile':
        print("  Generating B² profiles (no integration)...")
        plot_b2_profiles(cfg, str(out_dir))
        print("\n  Profile analysis:")
        names = ['Q0 cap', 'Q1 wall', 'Q2 wall', 'Q3 cap']
        for k in range(4):
            x, B2, xl, _ = analyze_b2_profile(cfg, k)
            peak_idx = np.argmax(B2)
            B2_max   = B2[peak_idx]
            B2_on_cR = B2[len(x)//2] if k in (0,3) else B2[np.argmin(np.abs(x))]
            print(f"    {names[k]:12s}: peak B²={B2_max:.4e} T²  at {xl.split('(')[0].strip()}={x[peak_idx]:.2f}")
        if args.mode == 'profile':
            return

    # Load initial conditions
    ckpt_data = None
    if args.use_checkpoint:
        ckpt_data = load_checkpoint(args.checkpoint_path)

    pos0, vel0, cl0 = make_initial_state(cfg, ckpt_data)
    n_per_cluster = [int(np.sum(cl0 == k)) for k in range(4)]
    print(f"  Initial state: {sum(n_per_cluster)} particles  "
          f"per-cluster: {n_per_cluster}")
    print()

    csv_path = str(out_dir / args.csv) if args.csv else str(out_dir / 'sensitivity.csv')

    if args.mode == '1d':
        results = run_sweep_1d(pos0, vel0, cl0, cfg, args.sub_sim_time, csv_path)

        # Print best value per parameter
        print(f"\n  BEST VALUE PER PARAMETER (max avg_score):")
        seen = {}
        for r in results:
            p = r['param']
            if p not in seen or r['avg_score'] > seen[p]['avg_score']:
                seen[p] = r
        for p, r in seen.items():
            val = r['value']
            if p == 'SHAPE_D_SURF_mm':
                val_str = f"{val*1e3:.2f}mm"
            else:
                val_str = f"{val:.4g}"
            print(f"    {p:25s}: best value = {val_str:>10s}  score = {r['avg_score']:.4f}")

    elif args.mode == 'grid':
        params = args.params or ['N_CAP_RING', 'CAP_RING_R_END']
        for p in params:
            if p not in PARAM_RANGES:
                print(f"  ERROR: unknown parameter {p!r}. Choose from {list(PARAM_RANGES)}")
                return
        run_sweep_grid(pos0, vel0, cl0, cfg, params, args.sub_sim_time, csv_path)

    print("\n  Done.")


if __name__ == '__main__':
    main()