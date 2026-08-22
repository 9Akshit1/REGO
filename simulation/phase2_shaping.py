#!/usr/bin/env python3
"""
REGO Phase 2 — High-Precision Magnetic Shaping v5.0
=====================================================

v5.0 — Complete fix: transport grab+move, analytical gradients, hold stability.

ROOT CAUSE (v3.1): Co-aligned pairs at 0.8mm created B² min on-axis (not max).
  Particles were axially expelled → splitting, 200kW force spikes.
ROOT CAUSE (v4.0): Transport sep increased to 3mm but this made the trap too
  weak (only ~10W at 1.5mm) to lift particles from the floor. Combined with
  1.0s ramp, the trap moved away before grabbing the cluster → cluster left behind.

v5.0 FIXES:
  1. Transport trap: sep=1.5mm, m=0.001. Gives ~8500W at half-sep → strong grab.
     GRAD_B2_CLAMP=2000 T²/m caps near-field forces to ~9500W → safe.
  2. GRAB+MOVE protocol: trap activates at cluster position and stays stationary
     for 0.5s (GRAB_TIME) before path movement begins. Fast 0.3s ramp ensures
     full strength before any movement.
  3. Hold: co-aligned transverse pair per target (v5.2).
     Ring radius 1.5mm, m=0.0008 → B² maximum exactly at target.
     Eliminates the 0.8mm positional offset caused by single-dipole hold.
  4. Analytical ∇B² via Jacobian → eliminates 6-point finite difference.
     Each particle needs 1 analytical calc instead of 7 B_field evaluations.
     ~3-4× speedup in force computation.
  5. Explicit interlude between transports (0.6s settling).
  6. Corner moments reduced to prevent interference with transport.

PHYSICS: F = (Vp·χ_eff/2μ₀)∇(B²) — paramagnetic particles seek B² maxima.
"""

import taichi as ti
import numpy as np
import os, sys, math, time as _time, json, signal, argparse, hashlib
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    # Optional: also for stderr
    sys.stderr.reconfigure(encoding="utf-8")

# ── Architecture selection: CUDA (f64) → CPU fallback ────────────────
# Vulkan/Metal do NOT support f64 — skip them entirely.
# ti.cuda raises at ti.init() time if no CUDA driver is present,
# so the except clause correctly catches it and falls through to CPU.
_taichi_arch_name = "CPU"
try:
    ti.init(arch=ti.cuda, default_fp=ti.f64,
            fast_math=False,      # preserve f64 precision
            offline_cache=True)   # cache compiled kernels to disk
    _taichi_arch_name = "CUDA GPU"
except Exception:
    ti.init(arch=ti.cpu, default_fp=ti.f64,
            offline_cache=True)
print(f"  [Taichi] Using {_taichi_arch_name} backend")

MU0      = 4.0 * math.pi * 1e-7
PI       = math.pi
_MU0_4PI = MU0 / (4.0 * PI)

# ═══════════════════════════════════════════════════════════════════════════
# PHASE TIMING
# ═══════════════════════════════════════════════════════════════════════════
T_SETTLE_END      = 0.3        # was 0.5 — faster settle
T_CLUSTER_END     = 2.5        # was 3.5 — clustering is fast, save 1s
INTERLUDE_TIME    = 0.4        # was 0.6 — early ramp means settling faster
HOLD_TIME         = 2.5
SHAPE_TIME        = 20.0       # 5s per cluster (quasi-static shaping)
CKPT_INTERVAL     = 1.0
SIM_VERSION       = "43.0.0"
# TRANSPORT_BUDGET, ARRIVAL_THRESHOLD, GRAB_TIME (audit findings F7/F15 —
# Stage A-2 closed-loop transport controller redesign): superseded by
# EPS_X/EPS_V/ARRIVAL_DWELL/STALL_TIMEOUT, defined near the transport
# controller itself (search "CLOSED-LOOP TRANSPORT CONTROLLER") so they sit
# next to the physics that derives them. See HISTORY.md "Stage A-2".

# v19: SEQUENTIAL EXTERNAL SHAPING
#
# ROOT CAUSE OF v18 FAILURE:
#   All 4 shape dipoles activated simultaneously while all hold dipoles were OFF.
#   With no hold forces, particles from all clusters migrated to whichever shape
#   dipole had the strongest local gradient. All clusters merged into one mass
#   that orbited the scanning dipole.
#
# v19 FIXES:
#   1. SEQUENTIAL: Shape one cluster at a time (Q0 -> Q3 -> Q1 -> Q2).
#      Only ONE shape dipole is active at any instant.
#   2. HOLD FOR INACTIVE: Clusters not being shaped keep their hold dipole ON
#      at s=0.5, preventing migration. Already-shaped clusters use a slow
#      retention sweep instead (hold OFF to avoid pulling spread particles
#      back to center).
#   3. EXTERNAL OFFSET: Shape dipoles placed OUTSIDE the cylinder surface by
#      SHAPE_D_SURF (0.5mm) along the outward normal. This is physically
#      realizable (coils behind the wall). Particles are attracted toward the
#      dipole. deposition occurs through moving magnetic attractor 
#       + particle contacts + gravity, without artificial wall-force constraints.
#      v17 used external offset but failed because it combined it with
#      simultaneous activation. Sequential shaping makes cross-cluster
#      leaking negligible (0.006 W at 4.9mm vs hold restoring >> 1000 W).
#   4. CHI SCALING: --chi-scale arg reduces chi for lunar realism testing.
#   5. ENERGY TRACKING: Coil I^2*R diagnostic validates lunar power budget.
#
# CAPS (Q0 top, Q3 bottom):
#   8 fixed radial lines at angles k*2pi/8. For each line, r sweeps 0 -> cR
#   over 1/8 of the cluster's time slot. Dipole at z = cap_z + offset.
#   Moment: inward-normal (toward cap, into particle volume).
#
# WALLS (Q1 left, Q2 right):
#   8 vertical lines spanning +-pi/4 of azimuth around target_theta.
#   For each line, z sweeps z_lo -> z_hi. Dipole at r = cR + offset.
#   Moment: inward radial (-r_hat, toward cylinder axis).
# ── v22: ROTATING TRIPLET TIME-AVERAGED SHAPING ──────────────────────────
# Physics rationale:
#   Earnshaw prevents static B² maxima in free space. Solution: time-averaged
#   ⟨B²⟩ from a ROTATING TRIPLET (3 dipoles at 120° phase spacing).
#
#   Why a triplet (not pair, not single):
#   - Single dipole: particles chase the instantaneous maximum → orbit/epicycle
#   - Antipodal pair: time-average has two-fold anisotropy → two-lobe splitting risk
#   - Triplet at 120°: time-average ⟨B²(r,φ)⟩ is EXACTLY φ-independent to leading
#     order. No azimuthal anisotropy → impossible for the cluster to split into lobes.
#
#   Frequency regime:
#   ω_mechanical ≈ sqrt(Fm/(mp*R)) ≈ 25 rad/s for our particles.
#   ω_rot = 120 rad/s >> ω_mech → particles respond to time-average, not
#   instantaneous field. dt=8µs → Nyquist=62500 rad/s >> ω_rot → numerically safe.
#
#   CAP shaping (Q0 top, Q3 bottom):
#   Three dipoles orbit at radius r_orbit(t) in the cap plane, offset by SHAPE_D_SURF
#   along the cap normal (outside the domain). Moments point inward (toward cap).
#   r_orbit grows 0→cR over first half of slot (surface capture), stays at cR second half.
#   ⟨B²⟩ maximum is a RING at the cap surface at radius ~r_orbit → particles spread to ring.
#
#   WALL shaping (Q1 left, Q2 right):
#   Three dipoles orbit in the (z, azimuth) plane around the wall target at r=cR+SHAPE_D_SURF.
#   Moments point radially inward. Same r_orbit expansion logic.
#
#   Central anchor: FULLY OFF for active cluster during shaping (critical!).
#   Inactive clusters: weak anchor s=0.08 (prevents migration without point well).

SHAPE_D_SURF               = 1.5e-3    # axial/radial offset: dipoles placed this far OUTSIDE surface
                                       # NOTE: vestigial as of v29-v36 — caps use no active shape
                                       # dipole (`pass`) and the wall scan dipole uses its own
                                       # hardcoded d_wall standoff below, not this constant. Kept
                                       # only because Section 2537/3087 printouts still reference it.
# ── v29 STATIC EXTERNAL RING ARCHITECTURE ────────────────────────────────
#
# ROOT CAUSE OF ALL PREVIOUS FAILURES (v22–v28):
#   A rotating triplet at ω_rot = 15 rad/s FAILS as a time-averaged attractor
#   because ω_mech ≈ sqrt(F_m / (m_p * R)) ≈ 25 rad/s for our particles.
#   ω_rot < ω_mech → particles DO NOT see a time-average; they chase the
#   instantaneous B² maximum → one lobe orbits the dipole → NO ring forms.
#   This is the fundamental Earnshaw-circumvention failure: you need ω_rot >> ω_mech.
#   At ω_rot = 120 rad/s (v22) it worked marginally, but dt=8µs is only marginally
#   Nyquist-safe and jitter at each Python batch hop causes the averaging to fail.
#
# v29 FIX — STATIC EXTERNAL RING (Earnshaw-compliant by construction):
#
#   KEY INSIGHT: Earnshaw's theorem applies to ISOLATED magnetic sources in free
#   space. It does NOT prohibit B² maxima created by EXTERNAL sources outside
#   the simulation domain. A static ring of N external dipoles placed at radius
#   r_ring > r_particles in the cap plane creates a genuine, STATIC ⟨B²⟩ maximum
#   at ρ ≈ r_ring / sqrt(3) inside the ring — a true annular attractor. ✓
#
#   Because the dipoles are EXTERNAL to the particle cloud, Earnshaw doesn't apply
#   to the particle positions — the B² maximum is sustained by the coil currents,
#   not by the particle fields. This is physically realizable: coil array outside
#   the cylinder shell.
#
#   CAP SHAPING (Q0 top, Q3 bottom):
#   N_CAP_RING = 6 external dipoles uniformly spaced in azimuth at:
#     r_ring(t): sweeps from r_start → cR + SHAPE_D_SURF over slot time
#     z: tgt_z + SHAPE_D_SURF (Q0) or tgt_z - SHAPE_D_SURF (Q3)  [OUTSIDE domain]
#     Moments: radially inward (-r̂) in horizontal plane
#   The ring radius sweeps outward, dragging the B² maximum ring outward with it.
#   Particles are pulled outward monotonically. Gravity pins z (for Q0).
#   Hold pair (IDX_HOLD_A/B) provides supplemental z-pinning for Q3.
#
#   Physics of the static ring:
#     B(r, tgt_z) from ring = sum of N dipole fields
#     ∂B²/∂ρ < 0 for ρ > ρ_max, ∂B²/∂ρ > 0 for ρ < ρ_max
#     ρ_max ≈ 0.707 * r_ring (for large N, analytical)
#     This is a STABLE radial equilibrium ring. ✓
#
#   WALL SHAPING (Q1 left, Q2 right):
#   N_WALL_RAKE = 6 external dipoles arranged as a vertical rake at radius
#   r = cR + SHAPE_D_SURF from cylinder axis, at a given azimuthal angle θ.
#   Dipoles spaced vertically from z_lo to z_hi, moments pointing radially inward.
#   The rake is a STATIC vertical line of attractors — particles are pulled to
#   the cylinder wall at this azimuth and spread vertically along the rake.
#   The rake angle θ sweeps slowly around the cylinder (1 full revolution per slot),
#   painting the wall in stripes. Z-gravity provides ground-truth substrate.
#   The angular sweep rate is slow enough that particles settle at each stripe
#   before the rake moves on (deposition, not chasing).
#
#   BENEFIT OVER TRIPLET:
#   - No frequency assumption; works regardless of ω_mech
#   - Static field → smooth gradient, no time-varying force oscillations
#   - N=6 ring is perfectly azimuthally symmetric → no lobe splitting possible
#   - Wall rake sweeps deterministically → uniform azimuthal coverage guaranteed
#
SHAPE_ACTIVE_PLOW_STRENGTH = 0.80      # v31: increased to ensure ring force >> hold force
SHAPE_WAIT_HOLD_STRENGTH   = 0.15      # waiting-cluster radial support
SHAPE_DONE_HOLD_STRENGTH   = 0.08      # already-shaped cluster retention
# Audit findings F6/F7: same recalibration as GRAD_B2_CLAMP above — a
# numerical safety guard sitting above the ~50-100xW design ceiling
# (previously 700, which the recalibrated near-field forces would have
# saturated continuously; now a guard, not a governor).
SHAPE_MAX_GRAD_CLAMP       = 30.0      # T²/m clamp during shaping
SHAPE_BATCH_SIZE           = 500       # steps per batch during shape

# ── G3 (2026-08-19): WALL COVERAGE-FEEDBACK SLOW WELL ──────────────────────
# Replaces the v33 fast (~14mm/s) raster scan, which was deliberately fast
# enough that particles could never follow the dipole (outrun-and-deposit).
# The final pre-implementation feasibility gate (see
# analysis/SHAPING_FEASIBILITY_GATE_2026-08-19.md) tested the wait-hold
# dipole geometry (dipole AT the target, zero standoff, pure radial moment,
# SHAPE_WAIT_HOLD_STRENGTH) translated slowly in azimuth against a real
# 64-particle wall cluster: tracking error is speed-independent (dominated
# by an intrinsic ~0.13mm radial oscillation, not lag) through 5mm/s,
# degrades at 10mm/s, and catastrophically fails at 15mm/s (particles left
# behind entirely — Fmag collapses ~4e-18N, min separation jumps to ~7mm).
# This independently confirms, from direct simulation, the pre-existing
# v_tan~14mm/s "particles cannot follow" threshold the old v33 code already
# documented from a different (analytical) direction.
WELL_V_TAN         = 3.0e-3    # m/s -- 1.7x margin under the clean 5mm/s ceiling,
                                # 3.3x under the 10mm/s degradation onset, 5x under
                                # the 15mm/s catastrophic-failure point (all measured)
WELL_TRACK_ERR_MAX = 0.30e-3   # m -- ~2x the intrinsic oscillation envelope (0.13mm,
                                # measured in the perturbation test); tracking-error
                                # gate freezes the aim point above this, resumes below it
WELL_N_Z_LEVELS    = 4         # discrete z bands swept per full theta pass

# Surface confinement spring (active during shape phase only)
# Keeps particles glued to their target surface so inter-particle repulsion
# drives even spreading instead of particles drifting off the surface.
# k=0.5 N/m: equilibrium offset under gravity ≈ 3e-9 m (<<R); omega*dt=0.19 (stable)
SURF_CONF_K = 0.5      # N/m — spring constant toward target surface
CAP_RADIAL_BIAS_K = 0.0    # N/m — outward radial bias (v36: REMOVED, set to 0)
                             # v35 used k_r=0.05 to prevent center re-clustering.
                             # DIAGNOSIS: k_r=0.05 → ω_osc=√(k_r/mp)=7530 rad/s,
                             # T=0.835ms, damping τ=0.5s → 600 oscillation cycles before
                             # damping; k_r force (50μN at r=1mm) >> viscous drag (8.82pN).
                             # Particles oscillate r=0↔cR; 64 on 1D ring → Smoluchowski
                             # coagulation → two equal sub-clusters. Fix: k_r=0.
CAP_VISC_DAMP_TAU = 0.25   # s — viscous damping decay time for cap particles (v36)
                             # v35 used 0.5s. At τ=0.5s: stopping dist = v_cap×τ = 2.5mm
                             # > cR=1.667mm → wall bounce → oscillation.
                             # v36: τ=0.25s → stopping dist = 5mm/s×0.25s = 1.25mm < cR.
                             # No wall contact. Particles stop within disk; ring at r≈1.25mm.
                             # Numerical stability: b×dt/mp = dt/τ = 8e-6/0.25 = 3.2e-5 ✓

# Cap ring parameters
# v30 FIX: N=8 (not 6) for stronger azimuthal symmetry; tilt moment for intrinsic z-confinement.
# Slower sweep: start at 0.15*cR (well inside cluster), end at 1.0*cR (exact perimeter).
# No overshoot (was 1.08*cR) — overshoot pushed particles outside then gravity pulled them off.
N_CAP_RING       = 8          # number of external ring dipoles for cap shaping (8 → stronger isotropy)
CAP_RING_R_START = 0.15       # start r_ring as fraction of cR (inside cluster, not at center)
CAP_RING_R_END   = 1.00       # end r_ring as fraction of cR (exact perimeter, no overshoot)
CAP_COMPRESS_R   = 0.92       # compress r_ring to this fraction of cR (final lock)
# Moment tilt: each ring dipole has moment = m*(-rhat_horiz * cos_tilt + nhat_cap * sin_tilt)
# This gives radial spreading force PLUS intrinsic z-restoring force from ring dipoles themselves.
# sin_tilt > 0 → moment has component toward cap plane → ∂B²/∂z ≠ 0 → z-confinement.
# cos_tilt = radial spreading strength, sin_tilt = z-pinning strength.
CAP_MOMENT_COS_TILT = 0.75    # radial component of moment (spreading)
CAP_MOMENT_SIN_TILT = 0.66    # z-component of moment toward cap (z-pinning from ring itself)

# Wall belt parameters
# v30 FIX: Replace narrow-arc rake (±45°) with FULL CYLINDRICAL BELT.
# N_WALL_BELT dipoles uniformly in azimuth (full 2π) at multiple z-levels.
# This creates a COMPLETE radially-inward attractor around the entire cylinder.
# Particles are pulled to the surface regardless of their azimuthal position.
# No sweep needed — static belt at cR + SHAPE_D_SURF.
# We use ALL 8 IDX_SHAPE slots per wall cluster at 2 z-levels (4 dipoles each).
N_WALL_BELT      = 8          # number of azimuthal belt dipoles per z-level
N_WALL_Z_LEVELS  = 2          # number of z-levels for belt (lo, hi half of wall)
# Total dipoles per wall cluster: N_WALL_BELT * N_WALL_Z_LEVELS = 16 → fits in IDX_SHAPE[0..15]
# SHAPE_RING_MAP must be updated accordingly (see below).
WALL_BELT_Z_FRAC = [0.3, 0.7] # z positions as fraction of cH above z_lo (30%, 70%)

# Legacy aliases kept for compatibility with summary printout
WALL_RAKE_AZ_RATE = 1.0
WALL_RAKE_AZ_SPAN = PI / 3.0
WALL_RAKE_HALF_AZ = PI / 4.0

# ── v29 CAP SHAPING PARAMETERS ──────────────────────────────────────────
# Static N-ring of external dipoles sweeps outward — see v29 parameter block above.
# CAP_SHAPE_HOLD_S: hold pair strength during shaping (z-pinning for Q3, supplemental Q0)
CAP_R_START      = CAP_RING_R_START   # alias for compat (fraction of cR)
CAP_R_END        = CAP_RING_R_END     # alias for compat (fraction of cR)
CAP_SHAPE_HOLD_S = 0.06               # v32: further reduced — hold pair at ±2.5mm creates
                                       # lateral splitting force at higher strengths. At 0.06
                                       # it provides just enough z-bias without splitting.

# ── v30 WALL SHAPING PARAMETERS ──────────────────────────────────────────
# Full cylindrical belt (N_WALL_BELT × N_WALL_Z_LEVELS dipoles per wall cluster).
# No sweep — static belt at cR + SHAPE_D_SURF in full azimuth.

# v30: Slot map — N_CAP_RING=8 for caps, N_WALL_BELT*N_WALL_Z_LEVELS=16 for walls.
# Caps use IDX_SHAPE[0..7] (Q0) and IDX_SHAPE[8..15] (Q3) — 8 each. ✓
# Walls use all IDX_SHAPE[0..15] (full belt) — sequential, never overlap with caps.
# SHAPE_ORDER = [0,3,1,2]: caps first, then walls. ✓
SHAPE_RING_MAP = {
    0: list(range(16, 24)),   # Q0 top cap:    IDX_SHAPE[0..7]  (8 dipoles)
    3: list(range(24, 32)),   # Q3 bottom cap: IDX_SHAPE[8..15] (8 dipoles)
    1: list(range(16, 32)),   # Q1 left wall:  IDX_SHAPE[0..15] (16 dipoles, half-arc belt)
    2: list(range(16, 32)),   # Q2 right wall: IDX_SHAPE[0..15] (16 dipoles, half-arc belt)
    # NOTE: no duplicate key for 2 — the previous version had a second entry that
    # silently overwrote Q2's ring to only 6 slots (range(22,28)), causing the
    # inner loop to break early and place only 6 dipoles at z_lo, none at z_hi.
}
# v30: All 16 IDX_SHAPE slots are used (8 per cap, 16 per wall — sequential, no overlap).

# Shaping order — caps first (farther apart, less cross-talk), then walls
SHAPE_ORDER = [0, 3, 1, 2]     # Q0 top -> Q3 bottom -> Q1 left -> Q2 right

# Coil parameters for energy tracking diagnostic
# A "dipole" in the sim represents a small solenoid coil:
#   m = N_turns * I * A_coil, so I = m / (N_turns * A_coil)
#   P = I^2 * R_coil (resistive loss)
# Audit finding F6: the point-dipole approximation requires evaluation
# distance >> coil size. Old COIL_AREA=4e-6 (2mm side) was being evaluated
# at 0.3-1.5mm standoffs — inside the coil's own near field, invalidating
# the point-dipole formula used throughout compute_forces. Shrunk to a
# 0.15mm-side planar microcoil (area below) so the recalibrated 0.5mm
# standoffs (F6/F7) are a genuine >=3x far-field distance. This is an
# explicit design choice (small local coils near the surface), not a
# fitted parameter — the resulting coil currents are reported via the
# existing I^2*R energy diagnostic and should be read as a design/energy
# consequence of this choice, not tuned away.
COIL_N_TURNS  = 100
COIL_AREA     = 2.5e-8     # m^2 (0.158mm side)
COIL_R_OHM    = 0.05       # Ohms (copper at lunar temp)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
class C:
    L   = 0.010
    N   = 256
    R   = 3e-5
    rho = 7800.0
    Vp  = (4/3)*PI*R**3
    mp  = Vp*rho
    g   = 1.62
    W   = mp*g

    E_eff = 2e5;  nu = 0.25;  e_n = 0.3;  mu_f = 0.4
    E_star = E_eff/(2*(1-nu**2))
    R_star = R/2;  m_star = mp/2
    G_star = E_eff/(4*(2-nu)*(1+nu))
    _lne = math.log(max(e_n, 1e-6))
    eta  = -_lne/math.sqrt(PI**2+_lne**2)

    chi  = 0.15;  Msat = 2e5
    kelvin_pf = Vp*chi/(2*MU0)

    # DMT adhesive cohesion (F11 fix). Same W_adh as phase3_consolidation.py's
    # sulfur-wetting model, applied here as bare (unwetted) grain-grain adhesion.
    # F_adh = 2*pi*R_star*W_adh (DMT limit, rigid stiff spheres, Derjaguin 1975).
    # Source: W_adh=0.08 J/m^2 is the value already used for lunar regolith
    # simulant contacts in phase3_consolidation.py — kept consistent across phases.
    W_adh = 0.08   # J/m^2 — DMT work of adhesion

    # Audit finding F8: Rayleigh criterion (dt <= 0.2*t_Rayleigh ~ 6.4us) and
    # Hertz contact-period criterion (dt <= T_contact/20 ~ 3.8-4.5us at
    # realistic overlaps) both require dt < 8us. dt=8us gave omega*dt=0.66 at
    # delta=R -- unstable/inaccurate integration of the stiffest contacts.
    dt    = 3.0e-6
    out_dt = 0.05

    # Audit finding F1: hcell=1.2mm with MAXPC=32 silently overflowed
    # (measured 64-128 particles/cell during shaping). hcell=8R keeps the
    # 27-cell stencil valid (hcell >= 2R) while giving cells small enough
    # that a fixed MAXPC is enough headroom even in the densest shape-start
    # cluster; see MAXPC below and the runtime occupancy assertion in build_grid.
    hcell = 8.0*R;  hres = int(L/hcell)+1
    fd_h  = 3e-6

    qc = np.array([[7.5e-3,7.5e-3],[2.5e-3,7.5e-3],
                   [7.5e-3,2.5e-3],[2.5e-3,2.5e-3]], dtype=np.float64)

    cx=L/2; cy=L/2; cz=L/2
    cR=L/6; cH=4e-3
    z_lo=cz-cH/2; z_hi=cz+cH/2

    # Audit finding F3 (precursor): Q0/Q3 transport targets used to be
    # 0.2mm off the z_hi/z_lo confinement planes (7.2mm vs z_hi=7.0mm,
    # 2.8mm vs z_lo=3.0mm). At shaping start the surf_conf z-spring
    # (SURF_CONF_K=0.5 N/m) then applied F_z = -0.5*0.2e-3 = 1e-4 N to every
    # Q0 particle simultaneously -- ~70,000x gravity -- producing a violent,
    # asymmetric downward compression the instant shaping began. Targets now
    # equal the confinement planes exactly so shaping starts from rest with
    # zero z-spring force.
    targets = np.array([
        [5.0e-3, 5.0e-3, cz + cH/2],                  # Q0: top cap (= z_hi)
        [5.0e-3-L/6-0.2e-3, 5.0e-3, 5.0e-3],         # Q1: left wall (gravity-supported lower-z)
        [5.0e-3+L/6+0.2e-3, 5.0e-3, 5.0e-3],         # Q2: right wall (gravity-supported lower-z)
        [5.0e-3, 5.0e-3, cz - cH/2],                  # Q3: bottom cap (= z_lo)
    ], dtype=np.float64)

    targets_3d = targets.copy()
    qc_3d = np.array([
        [7.5e-3, 7.5e-3, R],
        [2.5e-3, 7.5e-3, R],
        [7.5e-3, 2.5e-3, R],
        [2.5e-3, 2.5e-3, R],
    ], dtype=np.float64)

    _params = f"N={N},R={R},rho={rho},g={g},chi={chi},dt={dt}"
    param_hash = hashlib.md5(_params.encode()).hexdigest()[:8]

# ── v25 ORTHOGONAL CAP PINNING (z-stable disk at exact target z)
# ── PERPLEXITY PLAN PRIORITY 4: Calibrated z-pinning ────────────────────
# Perplexity plan specifies Fz = 400W upward for Q0 (balances gravity Fg=4.5e-10 N + margin).
# Hold pair: 2 dipoles at ±3mm (ŷ), m=0.006, at separation 3mm from center.
# At target: B_z from pair ≈ 2*(mu0/(4pi)) * 2m / R_ring^3 ≈ 2*1e-7*2*0.006/27e-9 ≈ 0.089 T
# ∂B²/∂z at 0.05mm off-plane ≈ 2*0.089*0.2 T/m → very large near center. Uses GRAD_B2_CLAMP.
# CAP_SHAPE_HOLD_S = 0.25 at m=0.006 → effective m_used = 0.0015
# Fz ≈ (Vp*chi/2mu0) * ∂B²/∂z — clamped at GRAD_B2_CLAMP=800 T²/m
# → Fz ≈ 644e-11 * 800 / 2 ≈ 2.6e-6 N ≈ 600W per particle ≈ HUGE (sub-clamp works)
# Setting 0.15 gives clamped-limited z-force ~300W per particle → balanced
CAP_R_START      = 0.05
CAP_R_END        = C.cR                  # Exactly at cap perimeter — no overshoot
# CAP_SHAPE_HOLD_S already set above (v30: 0.40) — do not override here

# ═══════════════════════════════════════════════════════════════════════════
# DIPOLE SYSTEM — v4.0 CORRECTED
# ═══════════════════════════════════════════════════════════════════════════
#
# Architecture (32 dipoles):
#
#   CORNER QUADRUPOLES [0..7]:   4×2 anti-aligned pairs (far-field cancel)
#   TRANSPORT TRAP [8..11]:      2×2 co-aligned pairs, 3mm separation
#                                (leading pair + trailing pair for escort)
#   HOLD DIPOLES [12..15,32..35]: 4×2 co-aligned transverse pairs (ring per target)
#   SHAPE RING [16..31]:         16 dipoles in cylinder-surface ring
#
# Key changes from v3.1:
#   - Transport sep: 0.8mm → 3.0mm (prevents extreme near-field forces)
#   - Hold: single offset dipole → co-aligned transverse pair (v5.2 fix)
#   - Removed compensation dipoles (unnecessary with proper hold design)
#   - Moments reduced to keep |Fm| in 1-500W range

N_DIP = 36   # v5.2: +4 hold-B dipoles for transverse quadrupole hold traps

dip_p = ti.Vector.field(3, ti.f64, shape=N_DIP)
dip_m = ti.Vector.field(3, ti.f64, shape=N_DIP)
dip_s = ti.field(ti.f64, shape=N_DIP)

dip_pos_np = np.zeros((N_DIP, 3), dtype=np.float64)
dip_mom_np = np.zeros((N_DIP, 3), dtype=np.float64)
dip_str_np = np.zeros(N_DIP, dtype=np.float64)

# ── Index maps ────────────────────────────────────────────────────────
IDX_CORNER_PRIMARY    = [0, 2, 4, 6]
IDX_CORNER_COMPENSATE = [1, 3, 5, 7]
IDX_TRAP   = [8, 9, 10, 11]       # v13: ONE dipole per cluster (unified transport+hold)
IDX_HOLD_A = [12, 13, 14, 15]     # DISABLED in v13 (kept for index compat)
IDX_HOLD_B = [32, 33, 34, 35]     # DISABLED in v13 (kept for index compat)
IDX_HOLD   = IDX_HOLD_A            # backward-compat alias
IDX_SHAPE  = list(range(16, 32))   # 16 shaping ring dipoles

# v13: Map cluster index → its dedicated trap/hold dipole
# Each cluster gets ONE dipole that serves as BOTH transport and hold.
# During transport: positioned d_lead ahead of cluster, moment toward cluster.
# At arrival: positioned d_lead*normal from target, moment toward target.
# NO topology change = NO subclustering.
IDX_CLUSTER_DIP = {0: 8, 1: 9, 2: 10, 3: 11}

# ── Corner quadrupoles ───────────────────────────────────────────────
# Unchanged physics: anti-aligned pair creates far-field cancellation
_h_corner_primary    = 1.5e-3
_delta_quad          = 0.6e-3
_m_corner_primary    = 0.0006      # REDUCED from 0.001 (was too strong)
_m_corner_compensate = 0.0005      # REDUCED from 0.00085

for k in range(4):
    z_primary = -_h_corner_primary
    z_comp    = -_h_corner_primary - _delta_quad
    dip_pos_np[k*2]   = [C.qc[k,0], C.qc[k,1], z_primary]
    dip_mom_np[k*2]   = [0, 0, _m_corner_primary]
    dip_pos_np[k*2+1] = [C.qc[k,0], C.qc[k,1], z_comp]
    dip_mom_np[k*2+1] = [0, 0, -_m_corner_compensate]

# ── Transport trap (defaults — repositioned during transport) ─────────
# v7.0 FIX: SINGLE LEADING DIPOLE ("magnetic tweezer" design)
#
# ROOT CAUSE OF v6.0 FAILURE:
#   The 4-dipole transverse ring placed dipoles at R=1.5mm from center.
#   At r < R, radial forces point OUTWARD (toward ring dipoles).
#   Once any particle drifted > 0.3mm radially, it hit strong near-field
#   and was flung further outward → runaway expansion → cluster destroyed.
#
# CORRECT DESIGN — Single leading dipole (magnetic tweezer):
#   ONE dipole placed d_lead = 0.5mm AHEAD of the cluster centroid,
#   along the transport direction. Moment points TOWARD the cluster.
#
#   Physics:
#   - B² maximum IS at the dipole (ahead of cluster).
#   - Cluster is always on the approach side → always pulled toward it.
#   - Radial force: B² drops off-axis → radial forces INWARD (no expansion) ✓
#   - Axial gradient: rear particles pulled harder than front (compression) ✓
#   - Dipole moves along path, cluster follows. When dipole stops at target,
#     cluster settles exactly there.
#
#   Audit findings F6/F7 (Stage A repair): the old m=0.0006 at d_lead=0.3mm
#   gave |B|=4.4 T from a coil declared as 100 turns x 4mm^2 at 0.3-1.5A —
#   physically that coil produces millitesla fields, not teslas — and the
#   point-dipole approximation was being evaluated at 0.3mm from a coil
#   whose own linear dimension is 2mm (inside its near field). Recalibrated
#   here to target ~50xW peak force at a standoff that is genuinely
#   far-field for the (now smaller, see COIL_AREA) coil model:
#     m = sqrt(target_gradB2 * r^7 / (24*K^2)), on-axis point-dipole estimate
#     r=0.5mm, target=50xW=1.86e-8 N -> gradB2=10.6 T^2/m -> m=1.86e-5 A.m^2
#   d_lead raised 0.3->0.5mm so it clears 3x the recalibrated coil size.
_m_trap  = 1.856e-5      # Leading dipole moment magnitude (recalibrated, F6/F7)
_d_lead  = 0.5e-3        # >= 3x coil linear dim (see COIL_AREA) — genuine far-field
for idx in IDX_TRAP:
    dip_pos_np[idx] = [C.cx, C.cy, -5e-3]   # parked below domain
    dip_mom_np[idx] = [0, 0, 0]

# v13: Hold ring dipoles are DISABLED. The transport dipole IS the hold.
# We keep them initialized but they will always have strength=0.
# This eliminates the competing-attractor topology change that caused subclustering.

# ── Hold dipoles: CO-ALIGNED TRANSVERSE PAIR per target (v5.2) ────────
#
# ROOT CAUSE FIX: A single dipole at offset d behind the target places its
# B² maximum AT the dipole position (not the target). The cluster equilibrates
# AT the dipole due to the monotonically increasing B² gradient toward it.
# With GRAD_B2_CLAMP=2000, the gradient saturates 0.35mm before the dipole,
# creating a flat-force zone where the cluster floats ~0.2mm below the dipole.
# Result: dipole at tgt+1.0mm → cluster stable at tgt+0.8mm. ✓ matches logs.
#
# PHYSICS OF THE FIX — Co-aligned transverse pair:
# Two dipoles placed symmetrically in the transverse plane around the target,
# both with moments along the transverse axis t̂:
#
#   Dipole-A at  target + R_hold * t̂   moment = +m_hold * t̂
#   Dipole-B at  target - R_hold * t̂   moment = +m_hold * t̂
#
# where t̂ ⊥ n̂ is the transverse axis (perpendicular to surface normal).
#
# WHY EQUILIBRIUM IS EXACTLY AT TARGET:
#   At the ring center (=target): both dipoles' +t̂ moments create fields
#   that add along n̂ on the normal axis through the center, because by
#   symmetry both dipoles contribute the same axial B component there.
#   Moving along n̂ away from center: distance to both dipoles increases
#   equally → B² decreases → d²B²/dn² < 0 at center = B² maximum ✓
#   By symmetry: ∇B² = 0 at target → zero net force at equilibrium ✓
#
# GRAVITY COMPENSATION:
#   For z-normal clusters (top/bottom), gravity pulls along -n̂.
#   We shift the ring center by delta_g = 0.01mm along n̂ so that the
#   upward gradient at the (unshifted) target exactly balances gravity.
#   Analytical: delta_g ≈ 0.01mm gives F_64 ≈ 145W upward >> 64W gravity,
#   placing true equilibrium ~0.005mm from target (within simulation dt).
#   For x-normal clusters (left/right), gravity is transverse → delta_g = 0.
#
# RADIAL FORCES:
#   At cluster edge (0.15mm from center), radial force ≈ 76W per particle.
#   This is comparable to inter-particle cohesion forces. The cluster
#   acts as a quasi-rigid body whose centroid locks to the B² maximum.
#   The ring radius R=1.5mm >> cluster spread (0.15mm) ensures gradients
#   are gentle within the cluster volume → no subclustering.
#
# DIPOLE COUNT: Uses IDX_HOLD_A (2 per cluster) + IDX_HOLD_B (2 per cluster)
#   = 8 total hold dipoles (N_DIP increased to 36 to accommodate).

# ── Hold dipoles: GRAVITY-BALANCED ŷ-AXIS RING per target (v11.0) ──────────
#
# v11.0 ROOT CAUSE FIXES (confirmed numerically):
#
# PROBLEM 1 — Gravity imbalance during ramp:
#   Previous m=0.005 gives Fz_max=+0.69W at full hold, but gravity = -1.0W.
#   At ramp start (hold_s=0): Fz=0 → cluster free-falls from target.
#   At hold_s=0.3: equilibrium is 1.5-2mm BELOW target → cluster bounces there
#   and inelastic collisions inject energy → cluster scatters → spread explodes.
#   FIX: m=0.006 → Fz_max=2.48W >> gravity. At hold_s=0.4: Fz=1.0W = gravity balance.
#   With early ramp start (at arrived_t), hold reaches balance before trap releases.
#
# PROBLEM 2 — Cross-cluster interference from ring axis alignment:
#   Previous t̂=x̂ for Q0/Q3 placed ring dipoles at x=5±3mm = x=2mm and x=8mm.
#   Q1 target at x=3.13mm falls BETWEEN these → up to 25W interference. BAD.
#   FIX: Use t̂=ŷ for ALL clusters. Ring dipoles at y=5±3mm = y=2mm and y=8mm.
#   Q1 is at y=5mm (equidistant from both dipoles) → dipole contributions partially
#   cancel → max cross-cluster force < 1.1W for ANY cluster pair. SAFE.
#   Verified numerically: all cross-cluster forces < 1.1W << gravity 1.0W. ✓
#
# PHYSICS:
#   Two co-aligned dipoles at ±R along ŷ, moments along ŷ:
#   - Restoring in n̂ (normal, opposes gravity for Q0/Q3) ✓
#   - Anti-restoring in ŷ (transverse): ~16W at 0.15mm vs bond 5664W → negligible ✓
#   - Restoring in n̂-transverse (e.g. x for Q0): ~2W ✓
#   - Equilibrium exactly at target by symmetry ✓
#   - Gravity balance: Fz_n = 2.48W > 1.0W → cluster supported at target ✓
#
# ALL CLUSTERS use t̂=ŷ to maximally separate ring dipoles from other targets.
# Q0 (n̂=+z): ring at (5, 5±3, 7.2)  → y=2,8  — other tgts at y=5 → safe ✓
# Q1 (n̂=-x): ring at (3.1, 5±3, 5)  → y=2,8  — other tgts at y=5 → safe ✓
# Q2 (n̂=+x): ring at (6.9, 5±3, 5)  → y=2,8  — other tgts at y=5 → safe ✓
# Q3 (n̂=-z): ring at (5, 5±3, 2.8)  → y=2,8  — other tgts at y=5 → safe ✓
#
# Note: For Q1/Q2 (n̂=x, gravity ⊥ n̂): hold provides x-restoring but NOT z-support.
# Gravity makes Q1/Q2 sag slowly in z during hold. This is physically correct —
# a side-wall cluster IS supported by the wall (contact with the target boundary),
# not by a field perpendicular to gravity. The x-restoring prevents the cluster
# from drifting AWAY from the wall. Natural behavior. ✓

_hold_ring_R  = 2.5e-3   # Hold ring radius — reduced from 3mm for tighter z-pinning
# _m_hold=0.005 independently checks out against the F6/F7 recalibration
# target (~50xW at this dipole's 2.5mm operating distance predicts
# m=5.19e-3 A.m^2, on-axis point-dipole estimate) — left unchanged.
# NOTE: this hold-ring apparatus is only ever driven at 2 of its 4 nominal
# positions (see v31 comment below) and is disabled entirely during "hold"
# as of the F4 fix further down (search "false hold ring") — kept defined
# here for index/checkpoint compatibility only.
_m_hold       = 0.005    # Hold ring moment per dipole (4-dipole ring → net ~same as before)
_delta_g      = 0.04e-3  # 0.04mm ring center shift along n̂ (gravity balance)

_target_normals = np.array([
    [0., 0., 1.], [-1., 0., 0.], [1., 0., 0.], [0., 0., -1.]
], dtype=np.float64)

# v31 FIX: REPLACE 2-DIPOLE ŷ-PAIR WITH 4-DIPOLE SQUARE RING (±x̂, ±ŷ offsets)
#
# ROOT CAUSE OF y-SPLITTING:
#   The 2-dipole hold pair along ŷ (dipoles at y=5±3mm, moments ŷ) creates a
#   B² saddle in the ŷ-direction. At high strength (CAP_SHAPE_HOLD_S=0.40),
#   the anti-restoring force along ŷ is strong enough to split the cluster
#   into two sub-clusters at y≈2mm and y≈8mm. This was masked at the old
#   strength of 0.15 but becomes a hard failure at 0.40.
#
# FIX: 4-dipole ring at (±Rx, 0) and (0, ±Ry) relative to target, all moments
# pointing toward the cap normal n̂. This creates a B² maximum exactly at the
# target center with 4-fold symmetry → NO preferential splitting axis.
# The B² profile along any radial direction is identical → no y vs x asymmetry.
#
# IDX_HOLD_A[k] ← dipole at +x offset   IDX_HOLD_B[k] ← dipole at -x offset
# We also need +y and -y dipoles — but we only have 2 slots (A and B) per cluster.
# Solution: Use ONLY IDX_HOLD_A and IDX_HOLD_B, but orient them along x̂ instead
# of ŷ. Then x-splitting is suppressed by the ring symmetry of the shape dipoles
# (which are azimuthally uniform → zero net x or y force on centroid).
# The key is that x̂ orientation does NOT place dipoles close to wall targets:
#   Q0/Q3 caps: dipoles at x=5±2.5mm → x=2.5mm and x=7.5mm
#   Q1 wall target: x=3.13mm → 0.63mm from x=2.5mm dipole → 1.3W crosstalk (OK)
#   Q2 wall target: x=6.87mm → 0.63mm from x=7.5mm dipole → 1.3W crosstalk (OK)
# MUCH BETTER than ŷ pair which caused splitting.
#
# Moment direction: n̂ (surface normal) for each cluster.
#   Q0 (+z normal): moment = +ẑ → B² maximum below dipole → z-pinning ✓
#   Q3 (-z normal): moment = -ẑ → B² maximum above dipole → z-pinning ✓
# This ensures ∂B²/∂z provides upward/downward restoring at tgt_z. ✓

_target_normals = np.array([
    [0., 0., 1.], [-1., 0., 0.], [1., 0., 0.], [0., 0., -1.]
], dtype=np.float64)

# x̂ transverse axis for ALL hold pairs (avoids y-splitting, safe crosstalk)
_target_transverse = np.array([
    [1., 0., 0.],   # Q0 cap: pair along x
    [1., 0., 0.],   # Q1 wall: pair along x (not used during shaping)
    [1., 0., 0.],   # Q2 wall: pair along x (not used during shaping)
    [1., 0., 0.],   # Q3 cap: pair along x
], dtype=np.float64)

_delta_gravity = np.array([
    _delta_g, _delta_g, _delta_g, _delta_g,
], dtype=np.float64)

# Initialize hold ring dipoles — actively used for cap z-pinning during shaping phase
# Moments now point along n̂ (normal) → creates B² maximum displaced along n̂ from dipole
# → strong z-restoring at tgt_z. Dipoles placed along x̂ → no y-splitting. ✓
for k in range(4):
    tgt   = C.targets[k]
    n_v   = _target_normals[k]
    t_v   = _target_transverse[k]
    dg    = _delta_gravity[k]
    idx_a = IDX_HOLD_A[k]
    idx_b = IDX_HOLD_B[k]
    ring_center = tgt + dg * n_v
    dip_pos_np[idx_a] = ring_center + _hold_ring_R * t_v
    dip_mom_np[idx_a] = _m_hold * n_v   # moment along NORMAL (not transverse!)
    dip_pos_np[idx_b] = ring_center - _hold_ring_R * t_v
    dip_mom_np[idx_b] = _m_hold * n_v   # moment along NORMAL (not transverse!)

# Backward-compat alias (IDX_HOLD_A is the primary hold ring index set)
IDX_HOLD = IDX_HOLD_A

# ── Shape dipoles: SCANNING SINGLE DIPOLE (v16.0) ─────────────────────
#
# v16.0 COMPLETE ARCHITECTURE REDESIGN
#
# WHY v13-v15 ALL FAILED:
#   v13: 4 static shape dipoles at 1mm, hold at s=0.08 → hold dominates
#   v14: Pure tangent moments, dipoles on surface → still too far, hold dominates
#   v15: 4 expanding ring dipoles → 4 competing B² maxima → SUBCLUSTERING
#
# ROOT CAUSE (proven numerically):
#   Multiple simultaneous shape dipoles create multiple B² maxima.
#   Paramagnetic particles seek B² maxima → cluster splits into N lobes
#   where N = number of shape dipoles. This is FUNDAMENTAL to the physics,
#   not a parameter tuning issue.
#
# v16.0 FIX: SINGLE SCANNING DIPOLE PER CLUSTER
#
#   ONE shape dipole per cluster, sweeping a SPIRAL path on the surface.
#   At any instant: ONE B² maximum → ONE attractor → IMPOSSIBLE to split.
#
#   CAPS (Q0, Q3): Dipole traces an Archimedean spiral on the cap.
#     scan_r(t) = r_start + (cR - r_start) × (t/SHAPE_TIME)
#     scan_θ(t) = ω × t  (5 revolutions)
#     Dipole starts inside the cluster (r_start=0.05mm) and expands to cR.
#     Moment: tangent (azimuthal) at current position.
#     The dipole acts as a "paddle" sweeping particles outward.
#
#   WALLS (Q1, Q2): Dipole scans a Lissajous on the cylinder wall.
#     scan_θ(t) = θ₀ + spread_θ × sin(ω_θ × t)  (3 cycles)
#     scan_z(t) = z₀ + spread_z × sin(ω_z × t)   (5 cycles)
#     spread_θ and spread_z grow with cosine ramp over SHAPE_TIME.
#     3:5 frequency ratio → incommensurate → dense coverage.
#     Moment: tangent to wall surface.
#
#   GRAVITY COMPENSATOR (transport dipole, IDX_TRAP):
#     Per-cluster transport dipole repositioned 2mm from target.
#     Caps: along ±z (provides z-lift).
#     Walls: 2mm below in z (provides z-lift against gravity).
#     m=0.0005 → ~2W uniform lift, <0.5W centering at 1mm.
#
# DIPOLE SLOT ALLOCATION:
#   IDX_SHAPE[0]:   Q0 scanning dipole (slots 1-3 disabled)
#   IDX_SHAPE[4]:   Q3 scanning dipole (slots 5-7 disabled)
#   IDX_SHAPE[8]:   Q1 scanning dipole (slots 9-11 disabled)
#   IDX_SHAPE[12]:  Q2 scanning dipole (slots 13-15 disabled)
#   IDX_TRAP[k]:    gravity compensator during shape

# Audit findings F6/F7: recalibrated the same way as _m_trap above — target
# ~50xW peak at d_wall=0.5mm standoff (see "wall scan (d_wall=0.5mm)" row).
_m_shape       = 1.856e-5  # Shape dipole moment (recalibrated, F6/F7)
_m_grav_comp   = 0.0005    # Gravity compensator moment (unused during shape in v18)
_d_grav_comp   = 2.0e-3    # Gravity compensator distance (unused during shape in v18)
# SHAPE_WALL_SPREAD_Z: legacy constant, superseded by v18 comb rake (no oscillation)

# ── Static initialization (positions overridden dynamically) ──────────
# Default positions are at targets; update_dipoles() computes the actual
# scanning positions every batch.
for i in range(16):
    dip_pos_np[IDX_SHAPE[i]] = [C.cx, C.cy, C.cz]
    dip_mom_np[IDX_SHAPE[i]] = [0, 0, _m_shape]


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-TALK ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════
def _B_dipole_at(dip_pos, dip_mom, r):
    rv = r - dip_pos
    r_mag = np.linalg.norm(rv)
    if r_mag < 1e-12:
        return np.zeros(3)
    rhat = rv / r_mag
    return (_MU0_4PI / r_mag**3) * (3.0 * np.dot(dip_mom, rhat) * rhat - dip_mom)

def analyze_cross_talk():
    print("\n  ═══ CROSS-TALK ANALYSIS ═══")
    print(f"  {'Source':>10} → {'Probe':>10}  |B_single| (T)  |B_quad| (T)  Suppression")
    print("  " + "─" * 72)

    for k_src in range(4):
        for k_probe in range(4):
            if k_probe == k_src:
                continue
            r_probe = np.array([C.qc[k_probe,0], C.qc[k_probe,1], C.R])
            B_single = _B_dipole_at(dip_pos_np[k_src*2], dip_mom_np[k_src*2], r_probe)
            B_single_mag = np.linalg.norm(B_single)
            B_comp = _B_dipole_at(dip_pos_np[k_src*2+1], dip_mom_np[k_src*2+1], r_probe)
            B_quad = B_single + B_comp
            B_quad_mag = np.linalg.norm(B_quad)
            supp = B_quad_mag / B_single_mag if B_single_mag > 1e-20 else 0
            print(f"  Corner {k_src} → Corner {k_probe}:  "
                  f"{B_single_mag:.3e}       {B_quad_mag:.3e}       "
                  f"{supp:.3f} ({(1-supp)*100:.1f}% reduced)")

        r_center = np.array([C.cx, C.cy, C.cz])
        B_s = _B_dipole_at(dip_pos_np[k_src*2], dip_mom_np[k_src*2], r_center)
        B_c = _B_dipole_at(dip_pos_np[k_src*2+1], dip_mom_np[k_src*2+1], r_center)
        supp = np.linalg.norm(B_s+B_c) / max(np.linalg.norm(B_s), 1e-20)
        print(f"  Corner {k_src} →   Center  :  "
              f"{np.linalg.norm(B_s):.3e}       {np.linalg.norm(B_s+B_c):.3e}       "
              f"{supp:.3f} ({(1-supp)*100:.1f}% reduced)")
    print()


# ═══════════════════════════════════════════════════════════════════════════
# TRANSPORT PATHS — PER-CLUSTER OPTIMIZED (unchanged from v3.1)
# ═══════════════════════════════════════════════════════════════════════════
def make_transport_path(start_pos, target_3d, n_waypoints=300,
                        clearance=0.3e-3, other_targets=None):
    """
    Generate a smooth transport path from the cluster's real starting
    position to its target position.

    v5.3 CHANGES vs v5.0:
      - clearance reduced 1.0mm → 0.3mm: clusters no longer overshoot their
        targets by ~1mm before descending. Top cluster peak is now 7.5mm
        instead of 8.2mm; left/right clusters peak at 5.3mm instead of 6.0mm.
      - Path shape changed from a 3-segment lift→plateau→descend to a single
        smooth arc that interpolates x, y, z simultaneously. This eliminates
        the abrupt direction reversal at cruise_z that was shaking clusters.
      - Collision avoidance bump reduced from 2.0mm to 0.5mm (only applied
        when another cluster's target is directly in the lateral path).

    Stage A-2 (F16): start_pos is now a real 3-D point (x,y,z), not a 2-D
    (x,y) with z hardcoded to the floor (C.R). The floor assumption was
    correct for the module-load-time reference paths (computed before any
    particle exists, when the honest assumption is "starts on the floor"),
    but wrong for the closed-loop transport controller, which rebuilds this
    path anchored at the REAL post-clustering centroid — which sits near
    the domain center (z≈5mm from the corner-quadrupole clustering B²
    maximum), not the floor. Using the stale floor-at-a-spawn-corner path
    for pure-pursuit routing made the controller chase a route that didn't
    start where the cluster actually was — see HISTORY.md "Stage A-2".
    """
    sx, sy, sz = start_pos[0], start_pos[1], start_pos[2]
    tx, ty, tz = target_3d

    # Peak z: just clearance above the destination, never below start+0.5mm
    peak_z = tz + clearance
    if tz < C.cz:
        peak_z = max(peak_z, sz + 0.5e-3)

    # Minimal collision avoidance: only bump if another cluster's target lies
    # squarely in the lateral sweep of this path (tight ±0.5mm box).
    if other_targets is not None:
        for ot in other_targets:
            in_x = min(sx, tx) - 0.5e-3 < ot[0] < max(sx, tx) + 0.5e-3
            in_y = min(sy, ty) - 0.5e-3 < ot[1] < max(sy, ty) + 0.5e-3
            if in_x and in_y:
                if tz >= C.cz and ot[2] > peak_z - 0.5e-3:
                    peak_z = max(peak_z, ot[2] + 0.5e-3)
                elif tz < C.cz and ot[2] < peak_z + 0.5e-3:
                    peak_z = min(peak_z, ot[2] - 0.5e-3)
                    peak_z = max(peak_z, sz + 0.5e-3)

    # ── TWO-SEGMENT SMOOTH ARC ──────────────────────────────────────────
    # Path is split into two half-cosine segments joined at u=0.5:
    #   Segment 1 (u=0→0.5): smoothly lift x,y,z from start to midpoint
    #   Segment 2 (u=0.5→1): smoothly descend x,y,z from midpoint to target
    # The midpoint is at (tx,ty,peak_z) — the apex of the arc.
    # Both segments have zero velocity at their endpoints (half-cosine),
    # so the join is C¹ smooth and the overall path has no abrupt changes.
    # The peak z is guaranteed to be exactly peak_z (not an approximation).

    f    = np.linspace(0.0, 1.0, n_waypoints)
    path = np.empty((n_waypoints, 3), dtype=np.float64)

    mask1 = f <= 0.5
    mask2 = f >  0.5

    # Segment 1: start → apex
    u1 = f[mask1] / 0.5           # normalised 0→1
    sm1 = 0.5 * (1.0 - np.cos(PI * u1))
    path[mask1, 0] = sx    + sm1 * (tx    - sx)
    path[mask1, 1] = sy    + sm1 * (ty    - sy)
    path[mask1, 2] = sz    + sm1 * (peak_z - sz)

    # Segment 2: apex → target
    u2 = (f[mask2] - 0.5) / 0.5   # normalised 0→1
    sm2 = 0.5 * (1.0 - np.cos(PI * u2))
    path[mask2, 0] = tx    + sm2 * (tx - tx)   # already at tx
    path[mask2, 1] = ty    + sm2 * (ty - ty)   # already at ty
    path[mask2, 2] = peak_z + sm2 * (tz - peak_z)

    # Clamp to domain (should not be needed, but defensive)
    path[:, 2] = np.clip(path[:, 2], C.R, C.L - C.R)

    return path


transport_paths = []
for k in range(4):
    already_placed = [C.targets[j] for j in range(k)]
    path = make_transport_path(
        np.array([C.qc[k, 0], C.qc[k, 1], C.R]), C.targets[k],
        clearance=0.3e-3,
        other_targets=already_placed if already_placed else None
    )
    transport_paths.append(path)

print("\n  ═══ TRANSPORT PATH ANALYSIS ═══")
_cluster_names = ["Q0(Top)", "Q1(Left)", "Q2(Right)", "Q3(Bottom)"]
for k in range(4):
    p = transport_paths[k]
    max_z = np.max(p[:, 2])
    min_z = np.min(p[:, 2])
    path_len = np.sum(np.linalg.norm(np.diff(p, axis=0), axis=1))
    print(f"  {_cluster_names[k]:>12s}: z∈[{min_z*1e3:.1f}, {max_z*1e3:.1f}]mm  "
          f"path_len={path_len*1e3:.1f}mm  "
          f"start=({p[0,0]*1e3:.1f},{p[0,1]*1e3:.1f},{p[0,2]*1e3:.1f})  "
          f"end=({p[-1,0]*1e3:.1f},{p[-1,1]*1e3:.1f},{p[-1,2]*1e3:.1f})")
print()

# Average waypoint spacing per path — used to convert a physical pure-pursuit
# lookahead distance into a waypoint-index step (see CLOSED-LOOP TRANSPORT
# CONTROLLER below).
_path_avg_spacing = []
for k in range(4):
    _p = transport_paths[k]
    _plen = float(np.sum(np.linalg.norm(np.diff(_p, axis=0), axis=1)))
    _path_avg_spacing.append(_plen / max(1, len(_p) - 1))


# ═══════════════════════════════════════════════════════════════════════════
# CLOSED-LOOP TRANSPORT CONTROLLER (Stage A-2, audit findings F7/F15)
# ═══════════════════════════════════════════════════════════════════════════
#
# ROOT CAUSE OF THE REGRESSION THIS REPLACES:
#   Stage A removed the hard velocity cap (F7) because it was a non-physical
#   numerical crutch, not a real constraint. But the transport control law
#   (previously: dipole position/strength as a pure function of ELAPSED TIME
#   via get_transport_progress(t), with zero velocity feedback and completion
#   by a 4.0s timeout regardless of actual state) has no other mechanism that
#   opposes velocity. Reconstructing a full run against the real VTU output
#   (analysis/reconstruct_run.py) showed every one of the four transports ran
#   at the clamp-saturated force ceiling (141.7xW, a=229.6 m/s^2) for large
#   fractions of its window with nothing to arrest the resulting velocity,
#   that arrived_t was None at every checkpoint sampled (no transport ever
#   detected genuine arrival), and that velocities reached 50,000-97,000 mm/s
#   by the last transport. See HISTORY.md "Stage A-2" for the full derivation.
#
# THE FIX — closed-loop position+velocity feedback, NOT a reinstated cap:
#   A static dipole field is conservative (energy-conserving); a particle
#   released into it with nonzero KE cannot come to rest on its own — it must
#   oscillate forever absent dissipation. The only physically available
#   dissipation here is real inelastic contact (weak against bulk
#   center-of-mass motion) and ACTIVELY MOVING THE SOURCE, which does real
#   work on the particle because the field becomes genuinely time-varying —
#   exactly how every real closed-loop electromagnet (maglev, magnetic
#   bearings, real magnetic-tweezer rigs) is actually driven: a controller
#   reads a position/velocity sensor and adjusts the ACTUATOR's current and
#   position; the force the particle feels remains the same physical law,
#   F=(Vp*chi_eff/2mu0)*grad(B^2), evaluated at wherever the controller
#   chose to put the real dipole. No force is ever added to a particle's
#   equation of motion; nothing is filtered by cluster_id; nothing clips
#   vel[i]. Only the dipole's own position/moment/strength (dip_p/dip_m/
#   dip_s) — already the thing update_dipoles has always controlled —
#   becomes a function of REAL sensed velocity as well as position and time.
#
# STATE MACHINE (per actively-transporting cluster): liftoff -> lift ->
#   cruise -> brake -> settle -> verify (dwell) -> hold. One-directional (no
#   reverting to an earlier zone within one transport attempt, avoiding
#   chattering); the only escape hatch is the stall safety net
#   (STALL_TIMEOUT), a diagnostic fallback that logs loudly if triggered,
#   not a normal path.
#
# Stage A-3 (finding F17): a real post-Stage-A-2 run showed all four
# transports stall without converging. Reconstruction against real VTU
# trajectory data (not code-reading) found the actual cause: clustering only
# regroups particles laterally at floor level (z stays pinned at C.R the
# whole time) — it never lifts them — so every transport genuinely starts
# needing a ~mm-scale vertical climb against gravity that the old CRUISE law
# never accounted for. Because the cluster couldn't climb, the pure-pursuit
# lookahead point (which assumed the cluster was following the path) ran
# away from the cluster's real position — measured directly: dipole-cluster
# separation grew 0.79mm -> 2.86mm -> 5.00mm over ~2.3s — collapsing the
# achievable force exactly when more was needed. See HISTORY.md "Stage A-3"
# for the full reconstruction, the real per-particle lift-off force table
# (verified against the real 64-particle cluster geometry, not a point-mass
# approximation), and the quantitative justification for every constant
# below.
#
# Stage A-4 (finding F18): implementing Stage A-3 exposed a second, distinct
# failure — LIFTOFF/LIFT genuinely worked (real z rose 0.03->0.72mm), but the
# instant CRUISE engaged, the cluster fell straight back to the floor within
# 50ms and never recovered. Fine-grained (6ms, real-control-period)
# instrumentation of real per-cluster state (DEBUG_LIFT_CRUISE=1,
# _debug_lift_cruise_snapshot()) traced the exact mechanism: CRUISE used ONE
# pull direction (path tangent) and ONE scalar throttle — a function of
# TOTAL speed — to do two independent jobs (vertical support, horizontal
# pursuit) at once. Free-fall increases total speed, so that throttle
# suppressed the very force needed to stop the fall: measured directly,
# thr_total pinned at exactly 0.0 for 10+ consecutive control steps once
# vr_tot exceeded 1 (a positive-feedback collapse, not a momentary gap —
# vr_tot climbed 1.33->1.43->2.30->3.39->4.54->4.93->6.12 as the fall itself
# kept adding speed). See HISTORY.md "Stage A-4" for the full trace and the
# design derivation (including the proof that a single on-axis dipole is
# physically sufficient for both jobs at once, with an 11x margin).
#
# LIFTOFF / LIFT: dipole tracks directly above the real-time lateral
#   centroid at a fixed 0.5mm standoff (the same safe, non-singular,
#   zero-clamp-saturation standoff used everywhere else in this controller),
#   moment pointing straight down (attractive, pulling up). Strength comes
#   from a one-step-ahead (deadbeat) predictor using the real known control
#   period (CTRL_DT_NOMINAL): a_vert_gross = g + max(0, (V_CEIL-v_z)/
#   CTRL_DT_NOMINAL) — proven (numerically) to deliver Fz/Mg >= 1.0 always
#   while active and to reach V_CEIL in exactly one control step with no
#   overshoot, replacing the old ramp+smoothstep-throttle law that let a
#   single 6ms step overshoot V_CEIL by 30-60% before the throttle reacted
#   (a real, if self-correcting — because it depends on v_z alone — bang-bang
#   oscillation; fixed here rather than ignored). LIFTOFF is verified
#   complete (not assumed) once the real z position has risen by a full
#   particle radius (Z_LIFTOFF_CONFIRM); LIFT continues the same law until
#   real floor clearance reaches LIFT_CLEARANCE, sustained for LIFT_DWELL. A
#   LIFTOFF_STALL_TIMEOUT diagnostic warns (does not silently proceed) if
#   real upward motion is never confirmed.
#
# CRUISE: two independent channels — vertical (identical deadbeat law to
#   LIFT, fed by v_z only) and horizontal (identical predictive form, fed by
#   HORIZONTAL speed only — never v_z, so free-fall cannot suppress it and it
#   cannot suppress vertical support) — composed into one 3-D acceleration
#   vector and realized by a SINGLE dipole at the fixed standoff _d_lead
#   (0.5mm, same as LIFT/BRAKE/SETTLE — not path-derived, so F17's
#   separation-runaway mechanism cannot recur: there is no longer a variable
#   separation to run away). Horizontal direction is the real pure-pursuit
#   lookahead point (nearest waypoint + lookahead on the existing, unchanged
#   collision-avoiding path arc — make_transport_path and its live
#   re-anchoring at the real position, F16, are unchanged), projected to the
#   horizontal plane. Because the vector is composed BEFORE realization, the
#   delivered vertical force component equals a_vert_gross exactly — not
#   degraded by whatever the horizontal channel needs.
#
# BRAKE (triggered at d <= D_BRAKE_TRIGGER): the dipole is placed BEHIND the
#   cluster along its actual (real, sensed) velocity direction, so the same
#   always-attractive paramagnetic force now opposes motion. The required
#   deceleration is the standard kinematic braking relation
#   a_needed = v^2 / (2*d_remaining), capped at what's actually achievable
#   at the safe (non-singular) brake standoff R_DECEL0 — see
#   solve_strength_for_accel().
#
# SETTLE/HOLD: dipole parked at target + small normal offset (not coincident
#   with the particles' own location — avoids the singular near-field right
#   where they sit), at a strength with modest headroom over the local
#   gravity component. Arrival is declared only once |x-target|<EPS_X AND
#   |v|<EPS_V simultaneously, sustained for ARRIVAL_DWELL — a real physical
#   criterion, not a timer.
#
# TOLERANCES DERIVED FROM SIMULATION SCALE (not chosen for convenience):
#   EPS_X = 5*R: sub-particle-radius position precision is meaningless.
#     (This independently reproduces the pre-existing ARRIVAL_THRESHOLD
#     value of 0.15mm exactly — a good sign that constant was reasonable
#     even though the logic that used it wasn't.)
#   EPS_V = EPS_X / CTRL_DT_NOMINAL: the speed below which a cluster cannot
#     drift outside the position tolerance even coasting UNPOWERED for one
#     full control cycle. (The a_max-derived bound -- the speed from which
#     the field could still stop within EPS_X, ~262mm/s -- is a much looser
#     sanity ceiling, not used as the arrival threshold itself, since it
#     would call a cluster "arrived" while still visibly moving.)
#
CTRL_DT_NOMINAL  = 6.0e-3        # matches existing BATCH_TRANSPORT(2000)*dt(3us)
EPS_X            = 5.0 * C.R     # position tolerance = 5 particle radii = 0.150mm
EPS_V            = EPS_X / CTRL_DT_NOMINAL   # velocity tolerance, ballistic-drift-derived
D_BRAKE_TRIGGER  = 3.0 * EPS_X   # brake-zone entry, generous margin over the physically
                                  # required stopping distance at V_CEIL (~0.14um, see below)
# F21: hysteresis exit threshold. Real per-control-step data showed a
# genuine, worsening CRUISE/BRAKE limit cycle: with a single no-hysteresis
# threshold, the instant d ticks back above D_BRAKE_TRIGGER after a real
# near-field clamp-saturation kick (satfrac=1.07 observed; v_z jumped
# 3.5->17.4->74.8mm/s across two 6ms steps right at a zone crossing),
# CRUISE reasserts a full-authority ceiling-tracking command from scratch,
# which can trigger another kick — real excursions reached d=0.61-2.91mm
# before flipping back, with the run-length between flips shrinking over
# time (158->106->41->21->...->1 steps). Once in BRAKE, only return to
# CRUISE once d exceeds this WIDER exit threshold (a round 2x multiplicative
# margin over D_BRAKE_TRIGGER, matching this codebase's existing convention
# of round multiplicative margins elsewhere — with headroom over the
# observed 0.88mm first-chatter excursion, the case hysteresis specifically
# needs to suppress, vs. larger genuine kicks which should still legitimately
# re-trigger CRUISE).
D_BRAKE_EXIT     = 2.0 * D_BRAKE_TRIGGER
# F21 rate limiter: bounds how fast the commanded aim direction (a_hat) can
# rotate per control step, derived from real geometry (not an arbitrary
# constant): the dipole sits at FIXED standoff r=0.5mm from the centroid
# regardless of commanded strength (only orientation varies with a_hat), so
# a rotating a_hat sweeps the dipole's real position along an arc of radius
# r. Real cluster max particle-to-centroid extent, measured directly from
# VTU data (cluster 1, both its clean pre-oscillation CRUISE window and
# during the actual saturation crisis: consistently 0.256-0.270mm — a
# stable, intrinsic property of the 64-particle cluster, not something the
# oscillation itself caused): Rc=0.26mm. Worst-case real separation if a
# particle sits exactly on the aim axis: r-Rc=0.24mm (independently
# confirmed via _raw_gradB2_onaxis: at that separation, raw grad/clamp~81 —
# this cluster/standoff combination has little inherent margin). Allow the
# per-step swept arc to consume at most HALF that margin (>=2 consecutive
# worst-case-direction steps needed to fully close the gap, giving the
# control loop a chance to react — a round fractional margin matching this
# codebase's existing convention elsewhere): ell_max=0.5*0.24mm=0.12mm.
# Chord-to-angle: dtheta_max = 2*asin(ell_max/2r) = 0.2406 rad = 13.8 deg
# per 6ms control step (~40 rad/s angular slew rate).
DTHETA_MAX       = 0.2406
V_CEIL           = 8.0e-3        # m/s — cruise speed ceiling (design choice; stopping
                                  # distance at this speed is sub-micron, see HISTORY.md)

# F23 (2026-08-18): CRUISE's reference velocity was a discontinuous step function
# (v_ref = +-V_CEIL right up until the position error crossed zero, then an instant full-
# magnitude sign flip) -- diagnosed as the root cause behind the F21/F22 near-field chatter
# (F19-F22, HISTORY.md): no realization strategy downstream can cleanly execute a genuinely
# discontinuous command. Fix: taper the reference speed continuously with distance instead
# ("glideslope"), using the same kinematic relation BRAKE's own a_needed law already uses
# (v^2=2*a*d), so v_ref -> 0 continuously as the position error -> 0 (magnitude is what
# matters at the sign-flip point, not the sign itself once magnitude is negligible).
# CAPTURE_RADIUS reuses the EXISTING D_BRAKE_EXIT constant rather than inventing a new
# distance parameter; A_GLIDE is then the deceleration that brings a cluster moving at
# V_CEIL to rest exactly at d=CAPTURE_RADIUS if held constant (~6500x below a_max=229.6m/s^2
# -- a deliberately gentle design SHAPE for the reference, not a new force-authority limit;
# full deadbeat correction authority against real disturbance is untouched). Margin check:
# half the nearest real target separation (2.738mm/2=1.369mm) is 1.52x CAPTURE_RADIUS, so the
# glide zone does not reach into a neighboring target's territory. Far from target (d >> 0.9mm)
# this reduces to the old V_CEIL ceiling exactly -- validated ~1.2-1.6s transit times unchanged.
CAPTURE_RADIUS   = D_BRAKE_EXIT                        # 0.90mm, reused not invented
A_GLIDE          = (V_CEIL ** 2) / (2.0 * CAPTURE_RADIUS)   # ~0.0356 m/s^2

def _v_glide_mag(d):
    """F23: continuous distance-scaled speed cap, ceiling-matched far away, -> 0 at d=0."""
    return min(V_CEIL, math.sqrt(max(0.0, 2.0 * A_GLIDE * d)))

ARRIVAL_DWELL    = 0.15          # s — sustained-criterion dwell before declaring arrival
STALL_TIMEOUT    = 6.0           # s — diagnostic safety net only, ~4x the expected
                                  # 1.2-1.6s transit time; firing logs a loud warning
                                  # (2026-08-17: temporarily raised to 20.0 for an
                                  # extended-timeout experiment; reverted after that
                                  # run showed a persistent, non-decaying limit cycle
                                  # rather than slow convergence — see HISTORY.md)
R_DECEL0         = _d_lead       # brake-phase standoff — reuse the same safe, non-singular
                                  # far-field distance already validated for cruise (F6)
D_HOLD           = _d_lead       # settle/hold standoff — same reasoning
PURSUIT_LOOKAHEAD = _d_lead      # pure-pursuit lookahead distance along the path arc

# F24 (2026-08-18): BRAKE's law replaced. The prior law (a_needed = v^2/(2*d),
# an exact kinematic stopping-distance inversion recomputed fresh every 6ms)
# is a deadbeat/exact-match law with no damping margin -- it assumes
# continuous re-evaluation lands v=0 exactly at d_remaining, which only holds
# in continuous time. At CTRL_DT_NOMINAL=6ms sampling, combined with the F21
# rate limiter and the zero-clamp realization (a_cmd_mag=max(0,dot(F,a_hat)),
# which zeros thrust outright during a >90 deg direction swing), a velocity
# reversal at BRAKE re-entry (exactly what a prior overshoot produces)
# reliably clips thrust to zero for a step or more, degrading the "exact"
# stopping estimate and letting the cluster coast past the target -- reopening
# d beyond D_BRAKE_EXIT, handing back to CRUISE, which reaccelerates, and
# repeats. This is a persistent, non-decaying limit cycle (see extended-
# STALL_TIMEOUT experiment, HISTORY.md), not a slow-convergence/timeout issue.
#
# Fix: replace the magnitude law with a critically-damped second-order
# state-feedback (PD/spring-damper) law, a_net = -2*zeta*omega_n*v +
# omega_n^2*(target-x). Unlike the deadbeat law this commands a SMALL,
# smoothly-varying acceleration whenever both e and v are small -- it never
# needs a large sudden direction reversal near the target, which removes the
# zero-clamp dead-zone mechanism above at its root rather than patching
# around it (c.f. the F22 raised-cosine attempt, which patched the
# realization layer and made things worse; this changes what's being
# realized instead).
#
# omega_n chosen from two independent physical margins, not tuned to a
# target trajectory:
#   (1) discretization stability: standard guidance keeps omega_n*dt <~0.2
#       for a stable discrete critically-damped response. dt=CTRL_DT_NOMINAL
#       =6ms is fixed by the existing BATCH_TRANSPORT cadence, so
#       omega_n <~ 33 rad/s.
#   (2) force margin: even at the worst incoming speed observed in real F23
#       data (~280mm/s), the damping term 2*zeta*omega_n*v must stay far
#       below a_max=229.6 m/s^2 (the clamp-saturated ceiling at R_DECEL0).
# Synthetic sweep (test_f24_pd_brake.py, 8 scenarios spanning both approach
# directions, overshoot/reapproach, high/low/noisy incoming velocity, and a
# realistic post-F23 spike state) over omega_n in {15,20,25,30,33}: omega_n=30
# (omega_n*dt=0.18) is the sweep optimum -- every scenario converges, chatter
# (BRAKE<->CRUISE re-entries) on the worst case drops from 4 (old law) to 2,
# settle time drops from 1.21s to 0.33s, peak commanded accel 14.8m/s^2
# (>15x margin below a_max). omega_n=33 (ratio 0.198) begins showing
# discretization artifacts (final-position-error blowup on several
# scenarios) -- 30 is the largest value with no instability signature.
# zeta=1 (critically damped: fastest non-oscillatory linear response) is a
# standard control-theory default, not a free tuning knob; matches the same
# category of gain (Kp/Kv-style PD) reported for closed-loop electromagnetic
# microrobot steering in the literature (Tandfonline, "Electromagnetic
# Steering of a Magnetic Cylindrical Microrobot Using Optical Feedback
# Closed-Loop Control") and LQR-tuned PID maglev trajectory tracking
# (ScienceDirect) -- sliding-mode/disturbance-observer/fuzzy-PID approaches
# from that same literature were not used because those exist to handle
# unmodeled disturbance or model uncertainty, neither of which is present
# here (the field model is exact; the only non-ideality is the fixed 6ms
# ZOH discretization already accounted for in (1) above).
BRAKE_ZETA       = 1.0
BRAKE_OMEGA_N    = 30.0          # rad/s — see derivation above

def _brake_accel_pd(e_vec, v_cur):
    """F24: desired NET (total, physical) acceleration via a critically-damped
    spring-damper toward the target. This is a_desired in the same sense the
    old a_net_req was -- the caller still adds (0,0,g) separately to get the
    DIPOLE's required contribution, since integrate() applies gravity
    unconditionally every step regardless of dipole action (same convention
    as CRUISE and the pre-F24 BRAKE law; unchanged here)."""
    return -2.0 * BRAKE_ZETA * BRAKE_OMEGA_N * v_cur + (BRAKE_OMEGA_N ** 2) * e_vec

_K_ONAXIS = MU0 / (4.0 * PI)

def _raw_gradB2_onaxis(s, r):
    """On-axis |d(B^2)/dr| for a point dipole of moment s*_m_trap at distance r
    from the evaluation point -- the same closed-form estimate used throughout
    the Stage A audit's force-vs-standoff tables. This is a design-time estimate
    for CHOOSING a control input, not a substitute for the real simulation
    physics: the actual force applied to every particle still comes only from
    the real, unmodified B_and_gradB2/compute_forces kernels (full 3-D
    geometry, chi saturation, the real per-particle position)."""
    return 24.0 * _K_ONAXIS**2 * (s * _m_trap)**2 / max(r, 1e-9)**7

def _clamped_gradB2(raw, clamp):
    return raw * clamp / math.sqrt(raw*raw + clamp*clamp) if raw > 0.0 else 0.0

def _accel_at(s, r, clamp):
    """Achievable acceleration (design estimate) at strength s, standoff r."""
    clamped = _clamped_gradB2(_raw_gradB2_onaxis(s, r), clamp)
    return (C.kelvin_pf * clamped) / C.mp

_A_R_DECEL0_MAX = _accel_at(1.0, R_DECEL0, 30.0)   # achievable ceiling at the safe brake standoff

def _rate_limit_hat(a_hat_prev, a_hat_raw, dtheta_max=DTHETA_MAX):
    """F21: cap the per-control-step rotation of the commanded aim direction
    at dtheta_max (see DTHETA_MAX derivation above). Real per-control-step
    data showed the un-limited CRUISE/BRAKE laws could reverse the aim
    direction (hence the dipole's real position, at fixed 0.5mm standoff)
    by 180 degrees in a single 6ms step, sweeping close enough to a
    finite-size cluster's edge particles to spike the real near-field
    gradient (observed satfrac up to 13.8x clamp) and kick velocity hard —
    a self-sustaining resonance (transport_1 real data: v_z jumped
    3.5->17.4->74.8mm/s across two steps). Uses a Gram-Schmidt
    construction (NOT the textbook slerp coefficient formula, which is
    singular both near 0 and near 180 degrees — exactly the regime this
    must handle correctly, caught by synthetic testing before reaching the
    real controller) so it stays numerically stable at any angle."""
    if a_hat_prev is None:
        return a_hat_raw
    u = a_hat_prev
    cos_ang = min(1.0, max(-1.0, float(np.dot(u, a_hat_raw))))
    ang = math.acos(cos_ang)
    if ang <= dtheta_max:
        return a_hat_raw
    perp = a_hat_raw - cos_ang * u
    perp_norm = np.linalg.norm(perp)
    if perp_norm < 1e-6:
        # Near-exactly-antipodal: rotation plane is genuinely undefined —
        # pick an arbitrary perpendicular (real continuous dynamics almost
        # never hold an exact 180-degree tie for multiple consecutive
        # steps, so this is a rare, one-off tiebreak, not a systematic bias).
        arbitrary = np.array([1.0, 0.0, 0.0]) if abs(u[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        perp = arbitrary - np.dot(arbitrary, u) * u
        perp_norm = np.linalg.norm(perp)
    w = perp / perp_norm
    result = math.cos(dtheta_max) * u + math.sin(dtheta_max) * w
    n = np.linalg.norm(result)
    return result / n if n > 1e-12 else a_hat_raw

def _realize_command_mag(a_cmd, a_cmd_mag_raw, a_hat_raw, a_hat):
    """NOT CALLED — F22 fix designed, implemented, and REVERTED (2026-08-18) after the real
    Gate 2 transport_0 run showed it made closed-loop performance measurably WORSE than the
    original F21 clamp (peak velocity excursion 279mm/s vs 226mm/s pre-fix; final STALL
    d=2.307mm v=52.6mm/s vs 0.867mm/8.7mm/s pre-fix; BRAKE zone essentially never re-entered
    after the first ~2s). Left in place, unused, for documentation — see HISTORY.md "F22 fix:
    designed, implemented, REVERTED" for the full real-data comparison and the honest
    reassessment of why a purely-local realization-weighting change could not fix this (the
    raised-cosine weighting, unlike the original clamp, injects real force with a component
    ANTI-aligned with the true required correction for most of the 90-150deg band, which turned
    out to matter more in the real coupled 3D/multi-particle dynamics than the free-fall gaps it
    eliminated — a distinction the cheap synthetic tests, run on an admittedly-simplified
    point-mass model, could not surface). The original design rationale is preserved below
    exactly as written before implementation, since the reasoning itself is not wrong, only
    incomplete — it did not anticipate that "smoothly reduced but real" force in a
    still-badly-misaligned direction (theta up to ~150deg) could destabilize the real system
    more than the zero-force gaps it was replacing.

    ORIGINAL DESIGN RATIONALE (2026-08-17), UNCHANGED: the direction rate limiter above (F21)
    -- this only replaces how much of the raw commanded MAGNITUDE gets realized
    once the direction is capped. The original realization used a plain linear
    projection clamped at zero: a_cmd_mag = max(0, dot(a_cmd, a_hat)). Real
    per-control-step data (DEBUG_LIFT_CRUISE capture, see HISTORY.md "F22
    diagnostic") showed this collapses to EXACTLY ZERO commanded force for
    every step where the raw desired direction is >90 degrees from the
    previous realized direction (dtheta_wanted>90deg) -- not reduced, zero --
    for as many as 7 consecutive 6ms steps (up to 42ms) until the DTHETA_MAX
    rotation cap works its way back under 90 degrees. Because gravity is
    applied unconditionally every step regardless of dipole state, a zero
    command is a real free-fall window, not a conservative no-op: 19 such
    episodes were observed in a 2.5s real replay, and three of them
    compounding within 60ms produced the 226mm/s excursion at t~4.75s that
    triggered this fix (see HISTORY.md).

    Replaces the clamp with a raised-cosine (half-angle) weighting:
        weight = 0.5*(1 + cos(theta)) = cos^2(theta/2)   in [0, 1]
    where theta is the angle between the raw desired direction and the
    (unchanged, still rate-limited) realized direction a_hat. This is the
    smallest change that satisfies every constraint identified during
    diagnosis:
      - weight(0)=1: fully-aligned commands are realized exactly as before
        (no change to the validated common-case behavior).
      - weight(90deg)=0.5, not 0: this is the actual bug fix -- authority is
        reduced, not annihilated, right where the old clamp went flat.
      - weight(180deg)=0, and ONLY at that single exact-antipodal point:
        pushing along a_hat when it is EXACTLY opposite the true desired
        direction cannot possibly help (any positive force there strictly
        increases the vector error), so zero is the one point where zero is
        actually correct -- the raised-cosine reproduces that, it doesn't
        eliminate it, it just stops the old clamp's zero from being flat
        across the ENTIRE 90-180 degree band.
      - continuous (in fact C-infinity) in theta, so there's no new
        discontinuity introduced at the old 90-degree clamp boundary.
      - weight in [0,1] always -> a_cmd_mag = weight*a_cmd_mag_raw can never
        exceed the raw commanded magnitude, so the existing physical
        ceiling (downstream solve_strength_for_accel's s<=1 clamp on the
        real field) is preserved exactly as before -- nothing here can ask
        for more force than the un-rate-limited controller already could.
      - direction is always exactly a_hat (a nonnegative scalar times a
        rate-limited unit vector) -- the delivered force can never point
        anywhere other than where the unchanged direction limiter already
        allows, so it can never reverse the intended direction.

    Rejected alternatives (see HISTORY.md "F22 fix design" for the full
    derivation): abs(dot(...)) was rejected because it delivers FULL raw
    magnitude at theta=180 -- the single worst-aligned case -- reintroducing
    the "large push in a bad direction" instability the original projection
    was added to prevent (F21 design, case B). A constant additive floor was
    rejected as an invented, undocumented parameter with no physical
    derivation, discontinuous at the point it takes over, and non-vanishing
    at the true antipodal worst case.

    Verified via synthetic unit tests before implementation: weight(90)=0.5000,
    weight(120)=0.2500, weight(150)=0.0670, weight(180)=0.0000 (closed form,
    matches by construction); continuity jump across 90deg < 2e-6; direction
    rate limit itself unaffected; all 13 sampled real captured zero-force
    episodes (dtheta_wanted 106.6-177.1deg) re-score to a strictly positive,
    ceiling-respecting magnitude under this formula.
    """
    cos_th = min(1.0, max(-1.0, float(np.dot(a_hat_raw, a_hat))))
    weight = 0.5 * (1.0 + cos_th)
    return weight * a_cmd_mag_raw

def solve_strength_for_accel(a_needed, r, clamp=None):
    """Invert the soft-clamped on-axis force law: find the dipole strength s in
    [0,1] that delivers a_needed at standoff r. a_needed is first capped at what's
    actually achievable at (r, s=1) -- the field is strongest very close to the
    dipole, so the theoretical clamp-saturated ceiling a_max is only reachable
    much closer than the safe, non-singular standoffs used here; capping at the
    real (r, s=1) ceiling keeps this consistent rather than solving for an
    impossible s>1."""
    c = GRAD_B2_CLAMP[None] if clamp is None else clamp
    a_ceiling = _accel_at(1.0, r, c)
    a = min(max(a_needed, 0.0), a_ceiling)
    if a <= 0.0 or a_ceiling <= 0.0:
        return 0.0
    F_needed = a * C.mp
    clamped_needed = min(F_needed / C.kelvin_pf, 0.999 * c)
    raw_needed = clamped_needed * c / math.sqrt(max(c*c - clamped_needed*clamped_needed, 1e-30))
    raw_at_s1 = _raw_gradB2_onaxis(1.0, r)
    s = math.sqrt(max(raw_needed / max(raw_at_s1, 1e-300), 0.0))
    return min(max(s, 0.0), 1.0)


# ── Stage A-3 (F17 fix) / Stage A-4 (F18 fix): LIFTOFF/LIFT/CRUISE constants ─
# Every number below is derived and checked against the real 64-particle
# cluster geometry and the real force law, not assumed. See HISTORY.md
# "Stage A-3" and "Stage A-4" for the full derivations; summary:
#
#   Real per-particle lift force (64 real particles from an actual VTU
#   frame, dipole directly above centroid, moment down):
#     r=0.10mm: 37.6xW,  56-64/64 particles clamp-saturated (the unstable
#               near-field regime this design has avoided everywhere else)
#     r=0.50mm: 30.4xW,  0/64 saturated   <- chosen operating standoff
#     r=0.75mm:  2.3xW,  0/64 saturated
#     r=1.00mm:  0.34xW (CANNOT lift)
#   Lateral force at r=0.5mm is 0.051% of the vertical force and the
#   implied angular acceleration from net torque is ~0 (both computed from
#   the real, asymmetric 64-particle positions) — confirms the point-mass
#   approximation is fine for CHOOSING a control input even though the
#   cluster's physical extent (RMS radius 0.166mm) is not negligible next
#   to the 0.5mm standoff; lift is clean, not lopsided.
#
#   Stage A-4 (F18): LIFT's and CRUISE's vertical channel both use a one-
#   step-ahead (deadbeat) predictor, a_vert_gross = g + max(0, (V_CEIL-v_z)
#   / CTRL_DT_NOMINAL) — proven (numerically, not assumed) to deliver
#   Fz/Mg >= 1.0 always while active (1.82x at v_z=0, exactly 1.00x at/above
#   V_CEIL, never below) and to reach V_CEIL in exactly one control step
#   with no overshoot, replacing the old ramp+smoothstep-throttle law that
#   let a single 6ms step overshoot V_CEIL by 30-60% (measured directly:
#   v_z spiking to 10-13mm/s) before the throttle reacted. CRUISE's
#   horizontal channel uses the identical predictive form fed by HORIZONTAL
#   speed only (never v_z), so free-fall cannot suppress it — this is the
#   actual F18 fix, breaking the old total-speed throttle's positive-
#   feedback collapse (measured: thr_total pinned at exactly 0.0 for 10+
#   consecutive control steps once vr_tot exceeded 1, because free-fall
#   itself kept increasing total speed). Both channels are composed into
#   one 3-D acceleration vector and realized by a SINGLE dipole at the
#   fixed standoff _d_lead=0.5mm (not path-derived — the F17 separation-
#   runaway mechanism cannot recur because there is no longer a variable
#   separation to run away), proven sufficient: 30.4x cluster weight is
#   available there, an 11.1x margin over the largest combined target used
#   (6.87 m/s^2 for two independent 3x-gravity channels).
Z_LIFTOFF_CONFIRM   = C.R          # net real upward rise required to confirm genuine
                                    # motion (one full particle radius — unambiguous,
                                    # not floor jitter), checked from real position, not
                                    # assumed from the commanded strength
LIFT_CLEARANCE      = _d_lead      # 0.5mm — reuses the same safe standoff constant
                                    # used everywhere else in this controller
LIFT_DWELL          = 0.05         # s — short dwell confirming clearance is sustained,
                                    # not a single noisy sample
LIFTOFF_STALL_TIMEOUT = 1.0        # s — diagnostic only: real expected time is
                                    # ~150-330ms; firing means real upward motion was
                                    # never confirmed and is logged loudly, not hidden


# ═══════════════════════════════════════════════════════════════════════════
# TAICHI FIELDS
# ═══════════════════════════════════════════════════════════════════════════
pos  = ti.Vector.field(3, ti.f64, shape=C.N)
vel  = ti.Vector.field(3, ti.f64, shape=C.N)
frc  = ti.Vector.field(3, ti.f64, shape=C.N)
fmag = ti.Vector.field(3, ti.f64, shape=C.N)

# Audit finding F1: MAXPC=32 with the old hcell=1.2mm silently overflowed
# (measured 64-128 particles/cell during shaping) because build_grid wrote
# the true count into grid_cnt while only storing the first 32 indices, and
# compute_forces then looped over the (wrong, too-large) count, reading past
# the end of grid_buf. With hcell=8R (smaller cells) a single fully-compacted
# 64-particle cluster can still land in one cell, so MAXPC must cover the
# whole cluster; grid_overflow_count below turns any future overflow into a
# visible, counted event instead of silent data corruption.
HRES = C.hres; MAXPC = 96
grid_cnt = ti.field(ti.i32, shape=(HRES, HRES, HRES))
grid_buf = ti.field(ti.i32, shape=(HRES, HRES, HRES, MAXPC))
grid_overflow_count = ti.field(ti.i32, shape=())

cluster_id  = ti.field(ti.i32, shape=C.N)
fixed_color = ti.field(ti.i32, shape=C.N)
ncontact    = ti.field(ti.i32, shape=C.N)
qc_ti       = ti.Vector.field(2, ti.f64, shape=4)
assign_centres = ti.Vector.field(3, ti.f64, shape=4)
surf_conf_enabled = ti.field(ti.i32, shape=())   # 1 = surface confinement active (shape phase)

# ── Gradient clamp — NUMERICAL SAFETY GUARD ONLY (audit findings F6/F7) ──
# Previously GRAD_B2_CLAMP=2000 T²/m combined with a hard velocity cap
# (removed — see integrate()) to make ~9,000×W forces and ~10× per-step
# v_cap overshoot invisible: the sim "looked" stable because clipping, not
# physics, set the kinematics. With dipole moments recalibrated (below) to
# a physically-targeted ~10-100×W peak force at realistic standoffs, this
# clamp should NOT saturate during normal operation — it exists only to
# bound the true 1/r^4 divergence if a particle numerically coincides with
# a dipole position. 30 T²/m corresponds to ~140×W, comfortably above the
# ~100×W design ceiling; the validation script checks it is not saturated.
#
# Audit finding F14 (found while implementing F6/F7): this used to be a
# plain Python float, reassigned per-phase inside update_dipoles() via
# `global GRAD_B2_CLAMP`. Taichi bakes Python-scope scalars referenced
# inside a @ti.func/@ti.kernel into the compiled kernel AT ITS FIRST
# COMPILE — later Python-side reassignment has no effect on already-JIT'd
# code (verified empirically: a minimal repro kernel returns its
# first-seen value even after the Python global is changed and the kernel
# is called again). compute_forces (which inlines B_and_gradB2, which
# reads this value) is first compiled during the pre-loop diagnostic call
# while pm.state=="settle" — so in EVERY prior version of this file,
# whatever the settle/cluster branch set (2000.0) was silently the
# permanent clamp for the entire run, including "shape" phase; the
# documented SHAPE_MAX_GRAD_CLAMP=700 (and now =30) was never actually
# applied at runtime. Fixed by making this a ti.field, exactly like
# surf_conf_enabled just above and v_cap previously — the correct pattern
# for a value a kernel needs to read at its CURRENT value each call.
GRAD_B2_CLAMP = ti.field(ti.f64, shape=())
GRAD_B2_CLAMP[None] = 30.0       # default for transport/cluster


# ═══════════════════════════════════════════════════════════════════════════
# MAGNETIC FIELD KERNELS — v5.0 OPTIMIZED
# ═══════════════════════════════════════════════════════════════════════════
# Uses fused B + ∇B² via central finite differences, but computes all 7
# sample points in a single function call to avoid redundant kernel launches.
# The B_field evaluation is the inner loop; we keep it lean.

@ti.func
def B_field(r: ti.types.vector(3, ti.f64)) -> ti.types.vector(3, ti.f64):
    B = ti.Vector([0.0, 0.0, 0.0])
    for k in range(N_DIP):
        sk = dip_s[k]
        if sk > 1e-15:
            mv  = dip_m[k] * sk
            rv  = r - dip_p[k]
            r2  = rv.dot(rv)
            if r2 > 1e-22:
                rmag  = ti.sqrt(r2)
                r3    = r2 * rmag
                rhat  = rv / rmag
                mdotr = mv.dot(rhat)
                coeff = _MU0_4PI / r3
                B    += coeff * (3.0 * mdotr * rhat - mv)
    return B

@ti.func
def B2_at(r: ti.types.vector(3, ti.f64)) -> ti.f64:
    b = B_field(r)
    return b.dot(b)

@ti.func
def B_and_gradB2(r: ti.types.vector(3, ti.f64)) -> ti.types.vector(4, ti.f64):
    """
    Compute B magnitude and ∇(B²) in a SINGLE PASS using the analytical Jacobian.

    Physics: ∇(B²) = 2(B · ∇)B  (since ∇×B = 0 in free space)
    For the total field B = Σ_k B_k, by linearity:
        ∇(B²) = 2 Σ_k J_k^T · B_total
    where J_k is the 3×3 Jacobian of dipole-k's field.

    Jacobian of dipole field B_k = (μ/r⁵)[3(m·r)r - r²m]:
        J_k_{ij} = (μ/r⁵)[3(m_j r_i + m_i r_j + (m·r)δ_{ij})]
                 - (μ/r⁷)[15(m·r) r_i r_j - 5r² m_i r_j / r²... ]
    Simplified vector form of J_k^T · v for an arbitrary vector v:
        (J_k^T · v)_i = (μ/r⁵)[3(v·r)m_i + 3(m·r)v_i + 3(m·v)r_i]
                      - (μ/r⁷)[15(m·r)(v·r)r_i]

    Speedup vs finite differences: 7 B_field calls → 1 pass.
    For N=256 particles × 36 dipoles: saves ~6/7 = 86% of B_field evaluations.
    """
    # --- Pass 1: accumulate total B ---
    B = ti.Vector([0.0, 0.0, 0.0])
    for k in range(N_DIP):
        sk = dip_s[k]
        if sk > 1e-15:
            mv  = dip_m[k] * sk
            rv  = r - dip_p[k]
            r2  = rv.dot(rv)
            if r2 > 1e-22:
                r5    = r2 * r2 * ti.sqrt(r2)
                mdotr = mv.dot(rv)
                coeff = _MU0_4PI / r5
                B    += coeff * (3.0 * mdotr * rv - r2 * mv)

    Bmag = B.norm()

    # --- Pass 2: accumulate ∇(B²) = 2 Σ_k J_k^T · B ---
    # J_k^T · B = (μ/r⁵)[3(B·rv)mv + 3(mv·rv)B + 3(mv·B)rv]
    #            - (μ/r⁷)[15(mv·rv)(B·rv)rv]
    # = (μ/r⁵)[3(Bdotrv)*mv + 3*mdotrv*B + 3*mdotB*rv - (15/r²)*mdotrv*Bdotrv*rv]
    gB2 = ti.Vector([0.0, 0.0, 0.0])
    for k in range(N_DIP):
        sk = dip_s[k]
        if sk > 1e-15:
            mv     = dip_m[k] * sk
            rv     = r - dip_p[k]
            r2     = rv.dot(rv)
            if r2 > 1e-22:
                r5     = r2 * r2 * ti.sqrt(r2)
                mdotrv = mv.dot(rv)
                Bdotrv = B.dot(rv)
                mdotB  = mv.dot(B)
                coeff5 = _MU0_4PI / r5
                coeff7 = 15.0 * _MU0_4PI / (r5 * r2)
                gB2   += 2.0 * (coeff5 * (3.0*Bdotrv*mv + 3.0*mdotrv*B + 3.0*mdotB*rv)
                                - coeff7 * mdotrv * Bdotrv * rv)

    # v12: SOFT clamp replaces hard clamp.
    # During handoff, transport dipole is 0.5mm from cluster → extreme raw ∇B².
    # Hard clamp creates a force discontinuity (splitting plane).
    # Soft clamp: gB2 *= C/√(|gB2|²+C²) → smooth everywhere.
    g2 = gB2.dot(gB2)
    if g2 > 1e-30:
        _clamp = GRAD_B2_CLAMP[None]   # F14: ti.field read, current value every call
        soft_scale = _clamp / ti.sqrt(g2 + _clamp * _clamp)
        gB2 *= soft_scale

    return ti.Vector([gB2[0], gB2[1], gB2[2], Bmag])

@ti.func
def chi_eff(B_mag: ti.f64) -> ti.f64:
    alpha      = C.chi * B_mag / (MU0 * C.Msat)
    alpha_safe = ti.min(alpha, 20.0)
    cosh_alpha = 0.5 * (ti.exp(alpha_safe) + ti.exp(-alpha_safe))
    return C.chi / (cosh_alpha * cosh_alpha)


# ═══════════════════════════════════════════════════════════════════════════
# CONTACT MECHANICS
# ═══════════════════════════════════════════════════════════════════════════
@ti.func
def _degenerate_normal(i: ti.i32, j: ti.i32) -> ti.types.vector(3, ti.f64):
    """Deterministic unit vector for the d≈0 fallback in contact_pp (F2 fix).

    Two coincident particles have no defined contact normal from their
    positions. This derives one from the particle-index pair instead, using
    an irrational-multiple hash so the direction is well spread and, by
    construction (antisymmetric in i-j), n(j,i) = -n(i,j) — Newton's third
    law still holds for the pair even in this degenerate case.
    """
    diff  = i - j
    adiff = ti.abs(diff)
    h1 = ti.cast(adiff, ti.f64) * 0.6180339887498949
    h1 = h1 - ti.floor(h1)
    h2 = ti.cast(adiff, ti.f64) * 0.3247179572447458
    h2 = h2 - ti.floor(h2)
    theta = h1 * 2.0 * PI
    cz    = 2.0 * h2 - 1.0
    sz    = ti.sqrt(ti.max(0.0, 1.0 - cz * cz))
    sign  = 1.0
    if diff < 0:
        sign = -1.0
    return sign * ti.Vector([sz * ti.cos(theta), sz * ti.sin(theta), cz])

@ti.func
def contact_pp(ri, rj, vi, vj, i: ti.i32, j: ti.i32):
    F   = ti.Vector([0.0, 0.0, 0.0])
    rij = ri - rj
    d   = rij.norm()
    n = ti.Vector([0.0, 0.0, 0.0])
    d_used = d
    if d < 1e-9:
        # Audit finding F2: the old guard `d > 1e-12` made exact coincidence
        # (reachable via the F1 grid-overflow bug, or any integration
        # pathology) an absorbing state — zero force forever, so coincident
        # particles co-moved permanently instead of separating. Use a
        # deterministic direction derived from the index pair instead.
        n = _degenerate_normal(i, j)
        d_used = 1e-9
    else:
        n = rij / d
    ov = 2.0 * C.R - d_used
    if ov > 0:
        vrel = vi - vj
        vn   = vrel.dot(n)
        vt   = vrel - vn * n
        sRd  = ti.sqrt(C.R_star * ov)
        kn   = (4.0/3.0) * C.E_star * sRd
        gn   = 2.0 * C.eta * ti.sqrt(ti.max(1e-30, C.m_star * kn))
        Fn_hertz = kn * ov - gn * vn
        if Fn_hertz < 0:
            Fn_hertz = 0.0
        Ft  = ti.Vector([0.0, 0.0, 0.0])
        vtm = vt.norm()
        if vtm > 1e-12:
            kt  = 8.0 * C.G_star * sRd
            gt  = 2.0 * C.eta * ti.sqrt(ti.max(1e-30, C.m_star * kt))
            Ftm = ti.min(gt * vtm, C.mu_f * Fn_hertz)
            Ft  = -Ftm * (vt / vtm)
        # Audit finding F11: DMT adhesive pull-off, absent from all earlier
        # versions (v1-v36) despite phase3_consolidation.py already relying
        # on the same W_adh for grain-grain bonding. F_adh = 2*pi*R*_W_adh is
        # the DMT limit (Derjaguin, Muller & Toporov 1975) for rigid,
        # weakly-adhesive spheres. At R=30um this dominates lunar gravity by
        # ~5000x (see CONTEXT.md "Physical limits") — two touching grains do
        # not separate on their own, and realistic magnetic forces (~100xW
        # after the F6/F7 recalibration) cannot pull them apart either.
        F_adh = 2.0 * PI * C.R_star * C.W_adh
        Fn = Fn_hertz - F_adh
        F = Fn * n + Ft
    return F

@ti.func
def contact_wall(p, v):
    F = ti.Vector([0.0, 0.0, 0.0])
    for ax in ti.static(range(3)):
        ov_lo = C.R - p[ax]
        if ov_lo > 0:
            sRd = ti.sqrt(C.R * ov_lo)
            kn  = (4.0/3.0) * C.E_star * sRd
            gn  = 2.0 * C.eta * ti.sqrt(ti.max(1e-30, C.mp * kn))
            vn  = -v[ax]
            Fn  = kn * ov_lo - gn * vn
            if Fn < 0: Fn = 0.0
            F[ax] += Fn
            vtm2 = 0.0
            for bx in ti.static(range(3)):
                if bx != ax: vtm2 += v[bx] * v[bx]
            vtm = ti.sqrt(vtm2)
            if vtm > 1e-12:
                kt  = 8.0 * C.G_star * sRd
                gt  = 2.0 * C.eta * ti.sqrt(ti.max(1e-30, C.mp * kt))
                Ftm = ti.min(gt * vtm, C.mu_f * Fn)
                for bx in ti.static(range(3)):
                    if bx != ax: F[bx] -= Ftm * (v[bx] / vtm)
        ov_hi = p[ax] + C.R - C.L
        if ov_hi > 0:
            sRd = ti.sqrt(C.R * ov_hi)
            kn  = (4.0/3.0) * C.E_star * sRd
            gn  = 2.0 * C.eta * ti.sqrt(ti.max(1e-30, C.mp * kn))
            vn  = v[ax]
            Fn  = kn * ov_hi - gn * vn
            if Fn < 0: Fn = 0.0
            F[ax] -= Fn
            vtm2 = 0.0
            for bx in ti.static(range(3)):
                if bx != ax: vtm2 += v[bx] * v[bx]
            vtm = ti.sqrt(vtm2)
            if vtm > 1e-12:
                kt  = 8.0 * C.G_star * sRd
                gt  = 2.0 * C.eta * ti.sqrt(ti.max(1e-30, C.mp * kt))
                Ftm = ti.min(gt * vtm, C.mu_f * Fn)
                for bx in ti.static(range(3)):
                    if bx != ax: F[bx] -= Ftm * (v[bx] / vtm)
    return F


# ═══════════════════════════════════════════════════════════════════════════
# GRID BUILD + FORCE COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════
@ti.kernel
def build_grid():
    grid_overflow_count[None] = 0
    for I in ti.grouped(grid_cnt):
        grid_cnt[I] = 0
    for i in range(C.N):
        gx = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][0] / C.hcell))))
        gy = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][1] / C.hcell))))
        gz = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][2] / C.hcell))))
        s = ti.atomic_add(grid_cnt[gx, gy, gz], 1)
        if s < MAXPC:
            grid_buf[gx, gy, gz, s] = i
        else:
            # Audit finding F1: previously grid_cnt kept the true (too-large)
            # count and compute_forces read past grid_buf's end. Now the
            # stored count is capped below (grid_cnt clamp), and any particle
            # that didn't fit is counted here so overflow is visible instead
            # of silently corrupting contact forces.
            ti.atomic_add(grid_overflow_count[None], 1)
    for I in ti.grouped(grid_cnt):
        if grid_cnt[I] > MAXPC:
            grid_cnt[I] = MAXPC

@ti.kernel
def compute_forces():
    for i in range(C.N):
        F  = ti.Vector([0.0, 0.0, 0.0])
        nc = 0
        F[2] -= C.mp * C.g
        # Analytical B + ∇B² in one pass (v5.0 optimization)
        bg = B_and_gradB2(pos[i])
        gB2 = ti.Vector([bg[0], bg[1], bg[2]])
        bm  = bg[3]
        ce  = chi_eff(bm)
        Fm  = (C.Vp * ce / (2.0 * MU0)) * gB2
        F  += Fm
        fmag[i] = Fm
        F  += contact_wall(pos[i], vel[i])

        # ── NON-PHYSICAL PLACEHOLDER: "surface confinement" (audit F9) ────
        # ⚠ NOT A REAL FORCE. This spring has no physical source — vacuum
        # exerts no restoring force, and there is no real surface for a
        # particle to be "confined" to; the target cylinder is the thing
        # this simulation is trying to demonstrate can be assembled, not a
        # boundary condition it is permitted to assume. It stands in for
        # whatever a Stage B magnetic-control law would need to actually
        # provide (see CONTEXT.md "Physical limits and known placeholders").
        # Per the Stage A audit decision this is *kept, not removed*, so the
        # rest of the fixed simulation can be validated in isolation, but it
        # must not be extended, retuned, or built upon — and must not be
        # read as evidence that magnetic shaping works.
        if surf_conf_enabled[None] == 1:
            cid = cluster_id[i]
            rx  = pos[i][0] - C.cx
            ry  = pos[i][1] - C.cy
            r_xy = ti.sqrt(rx*rx + ry*ry)
            if cid == 0:
                # Q0 top cap: pin to z = z_hi; confine radially within cR
                F[2] -= SURF_CONF_K * (pos[i][2] - C.z_hi)
                if r_xy > 1e-12:
                    # Weak outward radial bias — breaks r=0 symmetry, prevents
                    # re-clustering at center; contact repulsion is primary driver.
                    _bias = CAP_RADIAL_BIAS_K * r_xy
                    F[0] += _bias * rx / r_xy
                    F[1] += _bias * ry / r_xy
                if r_xy > C.cR and r_xy > 1e-12:
                    push = SURF_CONF_K * (r_xy - C.cR)
                    F[0] -= push * rx / r_xy
                    F[1] -= push * ry / r_xy
                # Also part of the F9 placeholder above: vacuum has no drag.
                # Stands in for whatever real dissipation (granular
                # collisions, a real substrate) a Stage B design would need.
                _db = C.mp / CAP_VISC_DAMP_TAU
                F[0] -= _db * vel[i][0]
                F[1] -= _db * vel[i][1]
                F[2] -= _db * vel[i][2]
            elif cid == 3:
                # Q3 bottom cap: pin to z = z_lo; confine radially within cR
                F[2] -= SURF_CONF_K * (pos[i][2] - C.z_lo)
                if r_xy > 1e-12:
                    _bias = CAP_RADIAL_BIAS_K * r_xy
                    F[0] += _bias * rx / r_xy
                    F[1] += _bias * ry / r_xy
                if r_xy > C.cR and r_xy > 1e-12:
                    push = SURF_CONF_K * (r_xy - C.cR)
                    F[0] -= push * rx / r_xy
                    F[1] -= push * ry / r_xy
                _db = C.mp / CAP_VISC_DAMP_TAU
                F[0] -= _db * vel[i][0]
                F[1] -= _db * vel[i][1]
                F[2] -= _db * vel[i][2]
            else:
                # Q1/Q2 wall clusters: pin to r = cR (radial only — z handled by gravity + scan)
                if r_xy > 1e-12:
                    dr = r_xy - C.cR
                    F[0] -= SURF_CONF_K * dr * rx / r_xy
                    F[1] -= SURF_CONF_K * dr * ry / r_xy

        gx = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][0] / C.hcell))))
        gy = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][1] / C.hcell))))
        gz = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][2] / C.hcell))))
        for dx in ti.static(range(-1, 2)):
            for dy in ti.static(range(-1, 2)):
                for dz in ti.static(range(-1, 2)):
                    nx = gx + dx; ny = gy + dy; nz = gz + dz
                    if 0 <= nx < HRES and 0 <= ny < HRES and 0 <= nz < HRES:
                        cnt = grid_cnt[nx, ny, nz]
                        for s in range(cnt):
                            j = grid_buf[nx, ny, nz, s]
                            if j != i:
                                Fc = contact_pp(pos[i], pos[j], vel[i], vel[j], i, j)
                                F += Fc
                                if Fc.norm() > 1e-15: nc += 1
        frc[i]      = F
        ncontact[i] = nc


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATOR
# ═══════════════════════════════════════════════════════════════════════════
@ti.kernel
def integrate():
    # Audit findings F6/F7: the hard velocity clip previously here made the
    # simulation's kinematics set by the clipping rule rather than by F=ma —
    # a single 8us step at the old GRAD_B2_CLAMP produced ~10x the transport
    # v_cap in one step, so the clip was saturated essentially continuously.
    # Removed. Stability now comes from the dt=3us timestep (F8) and the
    # F6/F7 moment recalibration keeping forces in a physically bounded
    # range, not from clipping the result after the fact.
    for i in range(C.N):
        a     = frc[i] / C.mp
        vel[i] += a * C.dt
        pos[i] += vel[i] * C.dt
        for ax in ti.static(range(3)):
            if pos[i][ax] < C.R:
                pos[i][ax] = C.R
                if vel[i][ax] < 0: vel[i][ax] *= -C.e_n
            if pos[i][ax] > C.L - C.R:
                pos[i][ax] = C.L - C.R
                if vel[i][ax] > 0: vel[i][ax] *= -C.e_n

# ── Taichi reduction fields for efficient stat computation ─────────────
_ke_field  = ti.field(ti.f64, shape=())
_fm_field  = ti.field(ti.f64, shape=())
_vm_field  = ti.field(ti.f64, shape=())

@ti.kernel
def compute_stats():
    """Compute KE, max |Fmag|, max |vel| entirely on-device — no to_numpy()."""
    ke = 0.0; fm = 0.0; vm = 0.0
    for i in range(C.N):
        vsq = vel[i].dot(vel[i])
        ti.atomic_add(ke, vsq)
        fn = fmag[i].norm()
        ti.atomic_max(fm, fn)
        ti.atomic_max(vm, ti.sqrt(vsq))
    _ke_field[None] = 0.5 * C.mp * ke
    _fm_field[None] = fm
    _vm_field[None] = vm

def substep_batch(n_sub: int):
    """Run n_sub physics steps with a tight Python loop.

    Taichi 1.7 prohibits struct_for (ti.grouped) nested inside a kernel loop,
    so we cannot inline build_grid inside a batched @ti.kernel.
    Instead we call the three kernels from a plain Python loop — the loop body
    is still almost entirely GPU/JIT work, so Python overhead is small relative
    to compute.  We still reduce Python→Taichi dispatch calls by batching:
    one dipole upload per batch instead of one per step.
    """
    for _ in range(n_sub):
        build_grid()
        compute_forces()
        integrate()


# ═══════════════════════════════════════════════════════════════════════════
# CLUSTER DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════════
@ti.kernel
def assign_clusters_initial():
    for i in range(C.N):
        best = 0; bd = 1e18
        for k in ti.static(range(4)):
            dx = pos[i][0] - assign_centres[k][0]
            dy = pos[i][1] - assign_centres[k][1]
            dz = pos[i][2] - assign_centres[k][2]
            d2 = dx*dx + dy*dy + dz*dz
            if d2 < bd: bd = d2; best = k
        cluster_id[i] = best

@ti.kernel
def fix_colors():
    for i in range(C.N): fixed_color[i] = cluster_id[i]

@ti.kernel
def apply_fixed_colors():
    for i in range(C.N): cluster_id[i] = fixed_color[i]

colors_fixed = False

def get_cluster_centroid_np(p_np, cl_np, cluster_idx):
    mask = cl_np == cluster_idx
    return np.mean(p_np[mask], axis=0) if np.any(mask) else C.qc_3d[cluster_idx].copy()

def get_cluster_velocity_np(v_np, cl_np, cluster_idx):
    """Real mean centroid velocity for a cluster (Stage A-2: closed-loop transport control
    needs real velocity feedback, not just position — see CONTEXT.md sec 19)."""
    mask = cl_np == cluster_idx
    return np.mean(v_np[mask], axis=0) if np.any(mask) else np.zeros(3)

_cluster_baseline = {}   # F21 Stage B: captured once per transport attempt

def cluster_integrity(k):
    """F21 Stage B: per-cluster integrity diagnostic. Mean/centroid position
    alone can't distinguish "centroid reached the target" from "particles
    stayed physically clustered and were transported coherently" -- this
    reuses the same pos/cluster_id read pattern as cluster_stats() (no
    redundant infrastructure) but reports per-axis spread and real extent,
    not just the RMS scalar cluster_stats() already gives."""
    if colors_fixed:
        apply_fixed_colors()
    else:
        assign_clusters_initial()
    p = pos.to_numpy()
    cl = cluster_id.to_numpy()
    mask = cl == k
    n = int(mask.sum())
    if n == 0:
        return dict(n=0)
    pp = p[mask]
    cent = pp.mean(axis=0)
    dv = pp - cent
    sigma = dv.std(axis=0)
    dist = np.linalg.norm(dv, axis=1)
    rms = math.sqrt(np.mean(dist**2))
    bbox = pp.max(axis=0) - pp.min(axis=0)
    return dict(n=n, centroid=cent, sigma=sigma, rms=rms, max_dist=float(dist.max()), bbox=bbox)

def report_cluster_integrity(k, label):
    """Print a compact integrity line, with ratios vs. the pre-transport
    baseline (captured lazily on first call per cluster) so expansion/
    dispersal can be quantified relative to the cluster's own starting size."""
    cs = cluster_integrity(k)
    if cs['n'] == 0:
        print(f"  [integrity {label}] cluster {k}: EMPTY (0 particles)")
        return
    base = _cluster_baseline.get(k)
    if base is None:
        _cluster_baseline[k] = cs
        base = cs
    rms_ratio = cs['rms'] / base['rms'] if base['rms'] > 1e-12 else float('nan')
    max_ratio = cs['max_dist'] / base['max_dist'] if base['max_dist'] > 1e-12 else float('nan')
    print(f"  [integrity {label}] cluster {k}: n={cs['n']}  "
          f"sigma(xyz)=({cs['sigma'][0]*1e3:.4f},{cs['sigma'][1]*1e3:.4f},{cs['sigma'][2]*1e3:.4f})mm  "
          f"RMS={cs['rms']*1e3:.4f}mm (x{rms_ratio:.2f} vs pre-transport)  "
          f"max_r={cs['max_dist']*1e3:.4f}mm (x{max_ratio:.2f} vs pre-transport)  "
          f"bbox=({cs['bbox'][0]*1e3:.3f},{cs['bbox'][1]*1e3:.3f},{cs['bbox'][2]*1e3:.3f})mm")

def cluster_stats():
    if colors_fixed:
        apply_fixed_colors()
    else:
        assign_clusters_initial()
    p  = pos.to_numpy()
    cl = cluster_id.to_numpy()
    counts = np.bincount(cl, minlength=4)
    out = []
    for k in range(4):
        n = int(counts[k])
        if n > 0:
            pp   = p[cl == k]
            cx_m = pp[:,0].mean(); cy_m = pp[:,1].mean(); cz_m = pp[:,2].mean()
            spread = math.sqrt(np.mean((pp[:,0]-cx_m)**2+(pp[:,1]-cy_m)**2+(pp[:,2]-cz_m)**2))
            out.append((n, cx_m*1e3, cy_m*1e3, cz_m*1e3, spread*1e3))
        else:
            out.append((0, 0., 0., 0., 0.))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# PHASE MANAGER — v4.0 WITH EXPLICIT INTERLUDE
# ═══════════════════════════════════════════════════════════════════════════
#
# Phase sequence:
#   settle → cluster → transport_0 → interlude_0 → transport_1 → interlude_1
#   → transport_2 → interlude_2 → transport_3 → shape → hold → done
#
# The interlude phase allows:
#   - Transport trap to fully deactivate (no residual forces)
#   - Hold dipoles for completed cluster(s) to stabilize at full strength
#   - Next cluster's corner field to release smoothly
#   - Kinetic energy from transport to dissipate

class PhaseManager:
    def __init__(self):
        self.state                = "settle"
        self.transport_order      = [0, 1, 2, 3]
        self.current_transport_idx = 0
        self.phase_start_t        = 0.0
        self.arrived_t            = None
        self.completed            = set()
        self.t_max                = 50.0
        self.handoff_t            = None
        # Stage A-3 (F17): per-transport-attempt liftoff/lift tracking.
        self.liftoff_start_z      = None   # real z captured once, at transport start
        self.liftoff_confirmed_t  = None   # set once real net rise >= Z_LIFTOFF_CONFIRM
        self.lift_cleared_t       = None   # set while real clearance >= LIFT_CLEARANCE
        self.lift_done            = False  # latched true once LIFT_DWELL is satisfied
        self._liftoff_stall_warned = False
        self.transport_subphase   = ""     # diagnostic label set by update_dipoles()
        # Stage A-4 (F18) failure-condition diagnostics — one-shot per
        # transport attempt, see design doc §10 / HISTORY.md "Stage A-4".
        self._cruise_sat_warned      = False  # solve_strength_for_accel clipped to s=1
        self._cruise_clearance_warned = False  # real clearance regressed back near the floor
        self._brake_sat_warned       = False  # F20: BRAKE's solve_strength_for_accel clipped to s=1
        self._a_hat_prev             = None   # F21: previous step's realized aim direction (rate limit)

    def get_active_cluster(self):
        if self.state.startswith("transport_"):
            idx = int(self.state.split("_")[1])
            return self.transport_order[idx]
        return -1

    def update(self, t, cluster_centroids, cluster_velocities=None):
        if self.state == "settle":
            if t >= T_SETTLE_END:
                self.state = "cluster"; self.phase_start_t = t

        elif self.state == "cluster":
            if t >= T_CLUSTER_END:
                self.state = "transport_0"; self.phase_start_t = t
                self.arrived_t = None; self.handoff_t = None
                self.current_transport_idx = 0
                self._reset_liftoff_tracking()

        elif self.state.startswith("transport_"):
            # Stage A-2: closed-loop arrival — BOTH position AND velocity must
            # satisfy tolerance, continuously, for ARRIVAL_DWELL. Replaces the
            # position-only check whose 4.0s TRANSPORT_BUDGET timeout was the
            # PRIMARY completion path in every prior version (arrived_t was
            # None at every checkpoint in the audited run — see HISTORY.md
            # "Stage A-2"). TRANSPORT_BUDGET is gone; STALL_TIMEOUT is a
            # diagnostic-only safety net that logs loudly if it ever fires.
            idx       = int(self.state.split("_")[1])
            cluster_k = self.transport_order[idx]
            target    = C.targets[cluster_k]
            centroid  = cluster_centroids[cluster_k]
            dist      = np.linalg.norm(centroid - target)
            vmag      = (np.linalg.norm(cluster_velocities[cluster_k])
                         if cluster_velocities is not None else 0.0)
            elapsed   = t - self.phase_start_t

            # Stage A-3 (F17): liftoff/lift tracking — verified from real
            # sensed position, never assumed from the commanded strength.
            if self.liftoff_start_z is None:
                self.liftoff_start_z = centroid[2]
            if self.liftoff_confirmed_t is None:
                if centroid[2] - self.liftoff_start_z >= Z_LIFTOFF_CONFIRM:
                    self.liftoff_confirmed_t = t
                elif elapsed > LIFTOFF_STALL_TIMEOUT and not self._liftoff_stall_warned:
                    print(f"  !!! LIFTOFF STALL: transport_{idx} (cluster {cluster_k}) never "
                          f"confirmed real upward motion within LIFTOFF_STALL_TIMEOUT="
                          f"{LIFTOFF_STALL_TIMEOUT}s (expected ~150-330ms) — z has risen only "
                          f"{(centroid[2]-self.liftoff_start_z)*1e3:.4f}mm of the "
                          f"{Z_LIFTOFF_CONFIRM*1e3:.4f}mm required. Investigate; the outer "
                          f"STALL_TIMEOUT will still force completion if this persists. !!!")
                    self._liftoff_stall_warned = True
            if not self.lift_done and self.liftoff_confirmed_t is not None:
                clearance = centroid[2] - C.R
                if clearance >= LIFT_CLEARANCE:
                    if self.lift_cleared_t is None:
                        self.lift_cleared_t = t
                    if t - self.lift_cleared_t >= LIFT_DWELL:
                        self.lift_done = True
                else:
                    self.lift_cleared_t = None

            # Stage A-4 failure condition (design §10): once lift_done is
            # true, real clearance regressing back near the floor is the
            # direct F18 regression signature (CRUISE dropping the cluster).
            # A loud, one-shot diagnostic — not a silent recovery attempt.
            if self.lift_done and self.arrived_t is None and not self._cruise_clearance_warned:
                clearance_now = centroid[2] - C.R
                if clearance_now < 0.5 * LIFT_CLEARANCE:
                    print(f"  !!! CRUISE CLEARANCE REGRESSION: transport_{idx} (cluster "
                          f"{cluster_k}) real floor clearance dropped to {clearance_now*1e3:.4f}mm "
                          f"(< half of LIFT_CLEARANCE={LIFT_CLEARANCE*1e3:.2f}mm) after LIFT had "
                          f"already cleared it — this is the F18 regression signature. "
                          f"Investigate before trusting downstream phases. !!!")
                    self._cruise_clearance_warned = True

            if dist < EPS_X and vmag < EPS_V:
                if self.arrived_t is None:
                    self.arrived_t = t
                    self.handoff_t = t
                if t - self.arrived_t >= ARRIVAL_DWELL:
                    report_cluster_integrity(cluster_k, f"ARRIVAL transport_{idx}")
                    self.completed.add(cluster_k)
                    self._advance_to_interlude(idx, t)
            else:
                self.arrived_t = None
                self.handoff_t = None

            if elapsed > STALL_TIMEOUT:
                print(f"  !!! STALL: transport_{idx} (cluster {cluster_k}) did not converge "
                      f"within STALL_TIMEOUT={STALL_TIMEOUT}s — forcing completion at "
                      f"t={t:.3f}s  d={dist*1e3:.3f}mm  v={vmag*1e3:.1f}mm/s. "
                      f"This is an abnormal event: the closed-loop controller failed to "
                      f"bring the cluster to rest at its target. Investigate before trusting "
                      f"downstream phases. !!!")
                report_cluster_integrity(cluster_k, f"STALL transport_{idx}")
                self.completed.add(cluster_k)
                self._advance_to_interlude(idx, t)

        elif self.state.startswith("interlude_"):
            elapsed = t - self.phase_start_t
            if elapsed >= INTERLUDE_TIME:
                idx = int(self.state.split("_")[1])
                self._advance_from_interlude(idx, t)

        elif self.state == "shape":
            if t - self.phase_start_t >= SHAPE_TIME:
                self.state = "hold"; self.phase_start_t = t

        elif self.state == "hold":
            if t - self.phase_start_t >= HOLD_TIME:
                self.t_max = t

    def _advance_to_interlude(self, transport_idx, t):
        """After transport completes, enter interlude for settling."""
        next_transport = transport_idx + 1
        if next_transport < 4:
            self.state = f"interlude_{transport_idx}"
            self.phase_start_t = t
            self.arrived_t = None
            self.handoff_t = None
        else:
            # All transports done → go to shape
            self.state = "shape"; self.phase_start_t = t

    def _advance_from_interlude(self, interlude_idx, t):
        """After interlude, start next transport."""
        next_idx = interlude_idx + 1
        if next_idx < 4:
            self.state = f"transport_{next_idx}"
            self.phase_start_t = t
            self.arrived_t = None
            self.handoff_t = None
            self.current_transport_idx = next_idx
            self._reset_liftoff_tracking()
        else:
            self.state = "shape"; self.phase_start_t = t

    def _reset_liftoff_tracking(self):
        """Stage A-3 (F17): re-arm liftoff/lift tracking for a new transport
        attempt. liftoff_start_z is re-captured from the real centroid on the
        first update() call of the new transport_k state (see above)."""
        self.liftoff_start_z       = None
        self.liftoff_confirmed_t   = None
        self.lift_cleared_t        = None
        self.lift_done             = False
        self._liftoff_stall_warned = False
        self._cruise_sat_warned       = False
        self._cruise_clearance_warned = False
        self._brake_sat_warned        = False
        self._a_hat_prev              = None

    def is_done(self, t):
        return self.state == "hold" and (t - self.phase_start_t >= HOLD_TIME)

    def get_phase_label(self):
        if self.state == "settle":   return "Settle"
        if self.state == "cluster":  return "Cluster"
        if self.state.startswith("transport_"):
            base = ["Mv→Top","Mv→Lft","Mv→Rgt","Mv→Bot"][int(self.state.split("_")[1])]
            sub = f":{self.transport_subphase}" if self.transport_subphase else ""
            return base + sub
        if self.state.startswith("interlude_"):
            return "Intrlde"
        if self.state == "shape":    return "Shape"
        return "Hold"

    def to_dict(self):
        return {
            'state': self.state,
            'transport_order': self.transport_order,
            'current_transport_idx': self.current_transport_idx,
            'phase_start_t': self.phase_start_t,
            'arrived_t': self.arrived_t,
            'handoff_t': self.handoff_t,
            'completed': list(self.completed),
            't_max': self.t_max,
            'liftoff_start_z': self.liftoff_start_z,
            'liftoff_confirmed_t': self.liftoff_confirmed_t,
            'lift_cleared_t': self.lift_cleared_t,
            'lift_done': self.lift_done,
        }

    def from_dict(self, d):
        self.state                = d['state']
        self.transport_order      = d['transport_order']
        self.current_transport_idx = d['current_transport_idx']
        self.phase_start_t        = d['phase_start_t']
        self.arrived_t            = d['arrived_t']
        self.handoff_t            = d.get('handoff_t', None)
        self.completed            = set(d['completed'])
        self.t_max                = d['t_max']
        self.liftoff_start_z      = d.get('liftoff_start_z', None)
        self.liftoff_confirmed_t  = d.get('liftoff_confirmed_t', None)
        self.lift_cleared_t       = d.get('lift_cleared_t', None)
        self.lift_done            = d.get('lift_done', False)
        self._liftoff_stall_warned = False
        self._cruise_sat_warned       = False
        self._cruise_clearance_warned = False
        self._brake_sat_warned        = False
        self._a_hat_prev              = None
        self.transport_subphase   = ""


# ═══════════════════════════════════════════════════════════════════════════
# DIPOLE CONTROL — v4.0 CORRECTED
# ═══════════════════════════════════════════════════════════════════════════

def ramp(t, t0, t1):
    if t <= t0: return 0.0
    if t >= t1: return 1.0
    return 0.5 * (1 - math.cos(PI * (t - t0) / (t1 - t0)))

_dip_s_buf = np.zeros(N_DIP, dtype=np.float64)
_dip_p_buf = np.zeros((N_DIP, 3), dtype=np.float64)
_dip_m_buf = np.zeros((N_DIP, 3), dtype=np.float64)

# Stage A-2 (F16): cache for the live, real-position-anchored transport path
# rebuilt once per transport attempt — see the CRUISE branch in
# update_dipoles(). Keyed by pm.state so a new transport_k triggers a rebuild.
_live_path_cache = {"state": None, "path": None, "avg_spacing": None}

# G3 (2026-08-19): persistent slow-well sweep progress for the wall
# coverage-feedback controller, keyed by cluster index -- see the "WALL
# SHAPING G3" block in update_dipoles(). Same pattern as _live_path_cache:
# real, physically realizable actuator/controller state (a stored setpoint),
# not a hidden force or a target-position filter.
_wall_well_state = {}
# G4 (2026-08-21): real captured post-slot hold position per wall cluster
# (the actual sensed centroid at the moment the cluster entered its done
# state), used instead of the original fixed target so the done/hold anchor
# holds the cluster where the sweep actually left it. See the retention-
# bookkeeping fix in update_dipoles()'s wall branch and HISTORY.md.
_wall_final_pos = {}


# ── F18 diagnostic instrumentation (Stage A-3) ──────────────────────────────
# Debug-only: captures REAL per-control-step (6ms cadence, matching
# CTRL_DT_NOMINAL) state for cluster 0 through the LIFT->CRUISE boundary, to
# test the F18 hypothesis (LIFT reaches V_CEIL -> CRUISE throttles on TOTAL
# speed -> throttle collapses -> vertical support disappears) against real
# data rather than the 50ms print-log cadence or the whole-domain vm
# diagnostic. Gated behind DEBUG_LIFT_CRUISE=1 so normal runs are unaffected.
# Not part of the control law; reads state only, changes nothing.
_dbg_lift_cruise = os.environ.get("DEBUG_LIFT_CRUISE", "0") == "1"
_dbg_ring = []           # rolling buffer of recent LIFT-zone snapshots
_dbg_cruise_count = [0]  # steps printed since first CRUISE snapshot
_dbg_done = [False]
_DBG_RING_MAX = 8
_DBG_CRUISE_MAX = int(os.environ.get("DEBUG_CRUISE_MAX", "15"))
_DBG_CLUSTER = int(os.environ.get("DEBUG_CLUSTER", "0"))  # F21 follow-up: which cluster to trace

# F22 diagnostic (2026-08-17): the F21 extended-STALL_TIMEOUT experiment showed a
# non-decaying near-arrival/excursion limit cycle rather than slow convergence.
# Distinguishing H1 (CRUISE deadbeat too aggressive near target) / H2 (BRAKE late
# or weak) / H3 (rate limiter bounds direction but not magnitude) / H4 (arrival
# dwell broken by one bad step) requires the REAL commanded-acceleration vector
# and rate-limiter behavior at the exact control step, not just the state
# _debug_lift_cruise_snapshot already re-derives independently. update_dipoles
# stashes its own real local a_cmd/a_hat/a_hat_raw here, at the exact point of
# computation, so the snapshot function below can report them without
# duplicating (and risking drifting from) the actual control law.
_last_cmd_dbg = {}

def _smoothstep(x):
    x = min(max(x, 0.0), 1.0)
    return 3.0*x*x - 2.0*x*x*x

def _debug_lift_cruise_snapshot(t, pm, x_cur, v_cur, pos_np, cl_np):
    if _dbg_done[0] or pm.state != f"transport_{_DBG_CLUSTER}":
        return
    sub = pm.transport_subphase
    if sub not in ("LIFT", "LIFTOFF", "CRUISE", "BRAKE"):
        return
    mask0 = cl_np == _DBG_CLUSTER
    n0 = int(mask0.sum())
    if n0 == 0:
        return
    cluster_pos = pos_np[mask0]
    dip_idx = IDX_CLUSTER_DIP[_DBG_CLUSTER]
    dip_p = dip_pos_np[dip_idx].copy()
    dip_m = dip_mom_np[dip_idx].copy()
    dip_s = float(dip_str_np[dip_idx])
    sep = float(np.linalg.norm(dip_p - x_cur))

    # Real per-particle force from the FULL current active-dipole set (not
    # just this one dipole) at the REAL current particle positions -- an
    # independent numpy re-derivation of the exact live force law (same
    # dipole-field Jacobian + soft vector clamp as B_and_gradB2), so this
    # cross-checks the kernel rather than trusting it blindly.
    clamp = float(GRAD_B2_CLAMP[None])
    F_vert_total = 0.0
    F_lat_total = np.zeros(2)
    gmag_max = 0.0
    for pi in cluster_pos:
        B = np.zeros(3)
        for kk in range(N_DIP):
            sk = dip_str_np[kk]
            if sk <= 1e-15: continue
            mv = dip_mom_np[kk]*sk; rv = pi - dip_pos_np[kk]; r2 = rv@rv
            if r2 <= 1e-22: continue
            r5 = r2*r2*math.sqrt(r2); mdotr = mv@rv
            B += (_MU0_4PI/r5) * (3.0*mdotr*rv - r2*mv)
        Bmag = np.linalg.norm(B)
        gB2 = np.zeros(3)
        for kk in range(N_DIP):
            sk = dip_str_np[kk]
            if sk <= 1e-15: continue
            mv = dip_mom_np[kk]*sk; rv = pi - dip_pos_np[kk]; r2 = rv@rv
            if r2 <= 1e-22: continue
            r5 = r2*r2*math.sqrt(r2); mdotrv = mv@rv; Bdotrv = B@rv; mdotB = mv@B
            c5 = _MU0_4PI/r5; c7 = 15.0*_MU0_4PI/(r5*r2)
            gB2 += 2.0*(c5*(3.0*Bdotrv*mv + 3.0*mdotrv*B + 3.0*mdotB*rv) - c7*mdotrv*Bdotrv*rv)
        raw_gmag = np.linalg.norm(gB2)
        gmag_max = max(gmag_max, raw_gmag)
        g2 = gB2@gB2
        if g2 > 1e-30:
            gB2 = gB2 * (clamp/math.sqrt(g2+clamp*clamp))
        ce = C.chi / math.cosh(min(C.chi*Bmag/(MU0*C.Msat), 20.0))**2
        Fp = (C.Vp*ce/(2*MU0)) * gB2
        F_vert_total += Fp[2]
        F_lat_total += Fp[:2]

    W = C.mp * C.g
    W_cluster = n0 * W
    net_a_z = (F_vert_total - W_cluster) / (n0*C.mp)
    vmag_total = float(np.linalg.norm(v_cur))
    v_z = float(v_cur[2])
    thr_vert  = 1.0 - _smoothstep(max(v_z, 0.0)/V_CEIL) if V_CEIL > 0 else 1.0
    thr_total = 1.0 - _smoothstep(vmag_total/V_CEIL) if V_CEIL > 0 else 1.0
    sat_frac = gmag_max / clamp if clamp > 0 else 0.0

    d_to_target = float(np.linalg.norm(C.targets[_DBG_CLUSTER] - x_cur))
    v_horiz = float(math.hypot(v_cur[0], v_cur[1]))
    cmd = _last_cmd_dbg.get(_DBG_CLUSTER, {})
    # arrival-dwell state (F22 diagnostic, H4): pm.arrived_t is set the instant
    # d<EPS_X and v<EPS_V both hold, and reset to None the instant either fails
    # (no hysteresis on the dwell itself) -- read directly, not re-derived.
    in_dwell = pm.arrived_t is not None
    dwell_elapsed = (t - pm.arrived_t) if in_dwell else float('nan')
    row = dict(t=t, sub=sub, x=x_cur.copy(), v=v_cur.copy(), vmag=vmag_total, v_z=v_z,
               v_horiz=v_horiz,
               Fz=F_vert_total, Flat=np.linalg.norm(F_lat_total), W_cluster=W_cluster,
               net_a_z=net_a_z, s=dip_s, thr_vert=thr_vert, thr_total=thr_total,
               vratio_vert=max(v_z,0.0)/V_CEIL, vratio_total=vmag_total/V_CEIL,
               dip_p=dip_p.copy(), dip_m_hat=(dip_m/max(np.linalg.norm(dip_m),1e-30)),
               sep=sep, sat_frac=sat_frac, n0=n0, d=d_to_target,
               zone=cmd.get("zone", "?"), e_vec=cmd.get("e_vec", np.full(3, float('nan'))),
               a_cmd=cmd.get("a_cmd", np.full(3, float('nan'))),
               a_cmd_mag_raw=cmd.get("a_cmd_mag_raw", float('nan')),
               a_cmd_mag=cmd.get("a_cmd_mag", float('nan')),
               a_hat_raw=cmd.get("a_hat_raw", np.full(3, float('nan'))),
               a_hat=cmd.get("a_hat", np.full(3, float('nan'))),
               dtheta_wanted=cmd.get("dtheta_wanted", float('nan')),
               dtheta_realized=cmd.get("dtheta_realized", float('nan')),
               a_needed=cmd.get("a_needed", float('nan')),
               in_dwell=in_dwell, dwell_elapsed=dwell_elapsed,
               eps_x_pass=d_to_target < EPS_X, eps_v_pass=vmag_total < EPS_V)

    if sub in ("LIFT", "LIFTOFF"):
        _dbg_ring.append(row)
        if len(_dbg_ring) > _DBG_RING_MAX:
            _dbg_ring.pop(0)
    else:  # CRUISE / BRAKE (F19/F20 diagnostic extension: was CRUISE-only)
        if _dbg_cruise_count[0] == 0:
            print("\n" + "="*140)
            print("F19/F20 DIAGNOSTIC: real per-control-step state, last LIFT steps -> LIFT/CRUISE boundary -> CRUISE/BRAKE")
            print("="*140)
            hdr = (f"{'t(s)':>8} {'sub':>7} {'zone':>10} {'z(mm)':>8} {'d(mm)':>7} {'ex,ey,ez(mm)':>22} "
                   f"{'vz(mm/s)':>9} {'vh(mm/s)':>9} {'|v|(mm/s)':>10} "
                   f"{'Fz(xW)':>8} {'Flat(xW)':>8} {'net_az':>8} {'s':>6} "
                   f"{'sep(mm)':>8} {'satfrac':>8} {'a_cmd_raw':>10} {'a_cmd':>8} {'a_needed':>9} "
                   f"{'dth_want':>9} {'dth_real':>9} {'dwell':>10} {'pass(x,v)':>10}")
            print(hdr)
            for r in _dbg_ring:
                _print_dbg_row(r)
        _print_dbg_row(row)
        _dbg_cruise_count[0] += 1
        if _dbg_cruise_count[0] >= _DBG_CRUISE_MAX:
            _dbg_done[0] = True
            print("="*140)
            print("F19/F20 DIAGNOSTIC: capture window complete.\n")

def _print_dbg_row(r):
    ev = r.get('e_vec', np.full(3, float('nan')))
    ev_str = f"{ev[0]*1e3:6.3f},{ev[1]*1e3:6.3f},{ev[2]*1e3:6.3f}"
    dwell_str = (f"{r['dwell_elapsed']*1e3:7.1f}ms" if r.get('in_dwell') else "  --  ")
    pass_str = f"{'X' if r.get('eps_x_pass') else '.'}{'V' if r.get('eps_v_pass') else '.'}"
    print(f"{r['t']:8.4f} {r['sub']:>7} {r.get('zone','?'):>10} {r['x'][2]*1e3:8.4f} {r.get('d',float('nan'))*1e3:7.3f} "
          f"{ev_str:>22} "
          f"{r['v_z']*1e3:9.3f} {r.get('v_horiz',float('nan'))*1e3:9.3f} {r['vmag']*1e3:10.3f} "
          f"{r['Fz']/r['W_cluster']:8.3f} {r['Flat']/r['W_cluster']:8.3f} {r['net_a_z']:8.3f} "
          f"{r['s']:6.4f} {r['sep']*1e3:8.4f} {r['sat_frac']:8.4f} "
          f"{r.get('a_cmd_mag_raw',float('nan')):10.3f} {r.get('a_cmd_mag',float('nan')):8.3f} "
          f"{r.get('a_needed',float('nan')):9.3f} "
          f"{math.degrees(r.get('dtheta_wanted',float('nan'))):9.3f} "
          f"{math.degrees(r.get('dtheta_realized',float('nan'))):9.3f} "
          f"{dwell_str:>10} {pass_str:>10}")


def update_dipoles(t, pm, cluster_centroids, cluster_velocities=None):
    """
    Update all dipole positions, moments, and strengths.

    v13.0 — UNIFIED SINGLE-DIPOLE-PER-CLUSTER:
      ONE dipole per cluster serves as BOTH transport lead AND hold.
      Transport: dipole d_lead ahead of cluster centroid, moment toward cluster.
      Arrival: dipole parks at target + d_lead*normal, stays at full strength.
      Hold: same dipole, same position, same strength. ZERO topology change.
      Hold ring (IDX_HOLD_A/B) DISABLED — always strength=0.

    cluster_velocities: dict {k: real mean velocity of cluster k's particles},
      or None. Only used by the active-transport branch (Stage A-2 closed-loop
      controller); None is safe for all other call sites (diagnostics,
      skip-to-shape) where transport isn't active. See "CLOSED-LOOP TRANSPORT
      CONTROLLER" below.
    """
    global dip_str_np
    s = _dip_s_buf
    p = _dip_p_buf
    m = _dip_m_buf
    np.copyto(p, dip_pos_np)
    np.copyto(m, dip_mom_np)
    s[:] = 0.0

    active_cluster = pm.get_active_cluster()
    is_transporting = pm.state.startswith("transport_")
    is_interlude    = pm.state.startswith("interlude_")

    # Phase-specific gradient clamp guard (F14: GRAD_B2_CLAMP is a ti.field —
    # see its declaration for why a plain Python global silently never took
    # effect at runtime in every prior version of this file).
    if pm.state == "shape":
        GRAD_B2_CLAMP[None] = SHAPE_MAX_GRAD_CLAMP
    else:
        GRAD_B2_CLAMP[None] = 30.0   # matches the module-level default (F6/F7)
    # G3 (2026-08-19): surf_conf is NEVER enabled in production anymore. The
    # feasibility gate (analysis/SHAPING_FEASIBILITY_GATE_2026-08-19.md)
    # showed it is 6-12 orders of magnitude stronger than any real force in
    # this simulation and was actively disrupting the wall's real near-field
    # hold (surf_conf ON left walls WORSE off than surf_conf OFF, same
    # ideal-start test). It remains in compute_forces(), fully documented,
    # as a non-physical historical/ablation reference only (CLAUDE.md: kept,
    # not extended) — surf_conf_enabled simply never gets set to 1 again, so
    # it is permanently inert in any real run. Caps therefore have zero
    # shape-phase support (see cap-hold feasibility failure, same report) —
    # this is the honest state of the current methodology, not a bug.

    # ── CORNER QUADRUPOLES ────────────────────────────────────────────
    corner_strength = ramp(t, T_SETTLE_END, T_SETTLE_END + 1.5)

    for k in range(4):
        idx_p = k * 2
        idx_c = k * 2 + 1

        if k in pm.completed:
            # Completed clusters: corners OFF (held by hold dipole)
            s[idx_p] = 0.0
            s[idx_c] = 0.0
        elif active_cluster == k:
            # Currently being transported: fade out over 1.5s from phase start.
            # FIX v10.0: Once cluster arrives (handoff_t set), force corners OFF
            # immediately. Previously corners could still be at 10-30% during handoff
            # (if cluster arrived before 1.5s fade complete), creating a competing
            # upward force that interfered with the hold ring handoff.
            if pm.handoff_t is not None:
                fade = 0.0  # IMMEDIATE OFF once arrival confirmed
            else:
                fade = 1.0 - ramp(t, pm.phase_start_t, pm.phase_start_t + 1.5)
            s[idx_p] = corner_strength * fade
            s[idx_c] = corner_strength * fade
        else:
            # Waiting: corners ON at full strength (keeps cluster together)
            s[idx_p] = corner_strength
            s[idx_c] = corner_strength

    # Shape/hold phase: all corners OFF
    if pm.state in ("shape", "hold"):
        for k in range(4):
            s[k*2] = 0.0
            s[k*2+1] = 0.0

    # ── UNIFIED TRANSPORT+HOLD — v13.2 (path-leading + exact targeting) ────
    #
    # v13.0: One dipole per cluster, same topology throughout.
    #   Eliminated subclustering by removing hold ring (competing attractors).
    #
    # v13.1: Smoothly slide dipole to EXACT target during arrival phase.
    #   Fixed hold offset (dipole at target, not target+d_lead*normal).
    #
    # v13.2 FIXES — TRANSPORT TARGETING + SHAPE ACTIVATION:
    #
    #   Problem 1: Transport dipole was placed at centroid + d_lead * dir.
    #     The B² maximum is AT the dipole, so the cluster equilibrated 0.3mm
    #     from its own centroid in the direction of the path target — chasing
    #     its own tail. The cluster trailed the path target by ~d_lead.
    #
    #   Fix 1: Lead from PATH WAYPOINT, not cluster centroid.
    #     Dipole placed at path_target + d_lead * path_tangent.
    #     The B² max is now AT or slightly ahead of the path waypoint.
    #     Cluster is pulled directly toward the path target, not toward itself.
    #     As progress → 1.0: d_lead smoothly reduces to 0 → dipole converges
    #     to exact final target. Uses cosine ramp from progress=0.8 to 1.0.
    #
    #   Problem 2: Transport/hold dipoles were still at 0.5 during shape phase.
    #     With m_trap=0.0006 at strength 0.5, these dominated shape dipoles
    #     (m_shape=0.0008 at strength ~1.0 but at 0.8mm offset → weaker ∇B²).
    #     Clusters were locked in transport wells, shaping did nothing.
    #
    #   Fix 2: ZERO transport/hold dipoles during shape phase.
    #     Shape dipoles are now the ONLY active field → full control of
    #     particle distribution on cylinder surfaces.
    #
    #   Problem 3: Vibration from high v_cap during hold/interlude.
    #
    #   Fix 3: Ultra-low v_cap during hold (5e-5) and interlude (2e-4).
    #
    #   WHY NO SUBCLUSTERING: Still one dipole per cluster at all times.
    #     During transport: one dipole at path waypoint. Smooth position change.
    #     During hold: one dipole at exact target. No topology change.
    #     During shape: transport dipoles OFF, shape dipoles are surface
    #     attractors (not competing with transport). No splitting risk.
    #
    #   WHY EXACT TARGETING: As transport progress → 1.0:
    #     - path_target → final target (last path waypoint = C.targets[k])
    #     - d_lead → 0 (cosine ramp from 0.8 to 1.0)
    #     - dipole → exact target position
    #     - B² max = at dipole = at target
    #     Arrival slide then smoothly parks dipole at exact target over 0.5s.
    #     (Stage A-2: this comment describes the pre-redesign behavior; the
    #     "arrival slide" is now the SETTLE zone of the closed-loop
    #     controller below, driven by real position+velocity feedback.)

    # Start with all transport/hold dipoles OFF
    for idx in IDX_TRAP:
        s[idx] = 0.0

    for k in range(4):
        dip_idx = IDX_CLUSTER_DIP[k]

        if k in pm.completed:
            target = C.targets[k]

            # v21: keep one coherent weak anchor for non-active clusters.
            # Active cluster anchor is handled separately in shape logic below.
            p[dip_idx] = target
            # Choose normal-oriented moment for caps, radial-x for walls
            if k == 0:
                m[dip_idx] = _m_trap * np.array([0., 0., 1.])   # top cap support
            elif k == 3:
                m[dip_idx] = _m_trap * np.array([0., 0., -1.])  # bottom cap support
            elif k == 1:
                m[dip_idx] = _m_trap * np.array([-1., 0., 0.])  # left wall inward
            else:
                m[dip_idx] = _m_trap * np.array([1., 0., 0.])   # right wall inward

            if pm.state == "shape":
                shape_elapsed = t - pm.phase_start_t
                t_frac = min(shape_elapsed / SHAPE_TIME, 1.0)
                shape_slot = min(int(t_frac * 4), 3)
                active_shape_k = SHAPE_ORDER[shape_slot]
                k_order_idx = SHAPE_ORDER.index(k)

                if k in (0, 3):
                    # CAP cluster during ANY shaping slot:
                    # Hold pair (IDX_HOLD_A/B) handles ALL z-pinning — set in hold-ring block.
                    # Cluster dipole MUST be parked at floor (s=0) — any active cluster dipole
                    # near the target would create a competing B² point-well that pulls ring
                    # particles back to center, collapsing the ring geometry.
                    p[dip_idx] = np.array([C.cx, C.cy, -5.0e-3])
                    s[dip_idx] = 0.0

                elif k in (1, 2):
                    # WALL cluster during shaping:
                    # v31 FIX: Anchor at TARGET position (not below target).
                    # Old code: dipole at target_z-2mm, moment +z → B² max AT
                    # the dipole (z-2mm) → cluster pulled DOWN toward z-2mm. BUG.
                    # New code: dipole at target position, moment = inward radial
                    # (-x for Q1, +x for Q2) → B² max displaced toward wall.
                    #
                    # G3 (2026-08-19) FIX #1: this branch used to switch to a
                    # z-lift-only config (no radial component) while k was the
                    # active cluster, on the assumption that surf_conf would
                    # carry radial confinement during the active slot ("surface
                    # confinement spring handles r=cR" — the old comment, now
                    # false: surf_conf is permanently disabled, see G3 in
                    # HISTORY.md). With surf_conf gone that switch left the
                    # active cluster with ZERO radial holding from this dipole
                    # at exactly the moment it needed it most — confirmed via a
                    # real full-cycle validation run: cluster 1 was thrown to
                    # d_tgt=8.05mm within 2s of its slot starting.
                    #
                    # G3 FIX #2 (2026-08-20, supersedes the first attempt at
                    # fix #1 above): making this anchor stay on, unconditionally,
                    # during the active slot re-broke coverage a different way.
                    # A full-cycle validation run (g3_wall_validation3.json)
                    # showed the active cluster's real centroid never leaving
                    # a ~30um neighborhood of the ORIGINAL fixed target for the
                    # entire 5s active slot, while its velocity climbed to
                    # 20-35mm/s (energy pumped in, no net coverage motion) —
                    # i.e. exactly the signature of two competing near-field
                    # attractors, not one. Root cause: this anchor sits at
                    # the target with ZERO standoff while scan_idx (below)
                    # tries to translate away from that same point; near-field
                    # force ~1/r^4, so the instant scan_idx moves even
                    # slightly the anchor (still at r=0) dominates and the
                    # cluster stays pinned to the anchor instead of following
                    # the sweep. scan_idx is deliberately built to replicate
                    # this exact hold config at slot start (same position,
                    # moment, strength — see analysis/SHAPING_FEASIBILITY_
                    # GATE_2026-08-19.md, which validated this geometry ALONE,
                    # with no second competing dipole present), so it can carry
                    # sole responsibility once active — matching the
                    # already-documented design principle above ("with anchor
                    # OFF, the scan dipole is the only attractor -> works").
                    # Anchor is therefore OFF only during the active slot;
                    # wait/done states are unaffected (still hold at s>0 below).
                    #
                    # G4 retention-bookkeeping fix (2026-08-21): the done-state
                    # anchor used to hold at the ORIGINAL fixed `target`
                    # unconditionally. But the sweep controller (scan_idx)
                    # displaces the real cluster away from that exact point by
                    # design (that is its whole job) -- confirmed by the full
                    # 4-cluster validation (g5_full_validation.json): cluster 1
                    # drifted from 0.95mm to 6.03mm off target, LEAVING its
                    # radial envelope entirely, during the ~5.5s after its own
                    # slot ended, because the done anchor kept pulling it back
                    # toward the original center point instead of holding it
                    # where the sweep actually left it. Fixed: capture the real
                    # sensed centroid ONCE, the first control step the cluster
                    # is seen in the done state, and hold at that realized
                    # position (with a matching realized radial moment
                    # direction) instead of the original target. This is
                    # real captured controller/actuator state (same category as
                    # `_wall_well_state`'s stored setpoint), not a hidden force
                    # or a cluster-ID-filtered force -- the field law and its
                    # dependence on dipole position/moment/strength are
                    # unchanged; only the recorded aim point differs from
                    # ORIGINAL-target to ACTUALLY-realized-position.
                    if k == active_shape_k:
                        p[dip_idx] = np.array([target[0], target[1], target[2]])
                        if k == 1:
                            m[dip_idx] = _m_trap * np.array([-1., 0., 0.])
                        else:
                            m[dip_idx] = _m_trap * np.array([1., 0., 0.])
                        s[dip_idx] = 0.0   # scan_idx is sole attractor while active
                    elif k_order_idx < shape_slot:
                        if k not in _wall_final_pos:
                            _wall_final_pos[k] = np.array(cluster_centroids[k], dtype=np.float64)
                        hold_pos = _wall_final_pos[k]
                        dxr, dyr = hold_pos[0] - C.cx, hold_pos[1] - C.cy
                        rr = math.hypot(dxr, dyr)
                        p[dip_idx] = hold_pos
                        if rr > 1e-9:
                            m[dip_idx] = _m_trap * np.array([-dxr / rr, -dyr / rr, 0.0])
                        elif k == 1:
                            m[dip_idx] = _m_trap * np.array([-1., 0., 0.])
                        else:
                            m[dip_idx] = _m_trap * np.array([1., 0., 0.])
                        s[dip_idx] = SHAPE_DONE_HOLD_STRENGTH * 1.5
                    else:
                        p[dip_idx] = np.array([target[0], target[1], target[2]])
                        if k == 1:
                            m[dip_idx] = _m_trap * np.array([-1., 0., 0.])
                        else:
                            m[dip_idx] = _m_trap * np.array([1., 0., 0.])
                        s[dip_idx] = SHAPE_WAIT_HOLD_STRENGTH

            elif pm.state == "hold":
                # HOLD PHASE: maintain shaped geometry without collapsing it.
                # Caps: cluster dipole parked (hold pair handles z-pinning).
                # Walls: radial anchor at target (NOT below — see v31 fix above).
                if k in (0, 3):
                    p[dip_idx] = np.array([C.cx, C.cy, -5.0e-3])
                    s[dip_idx] = 0.0
                else:  # walls
                    # G4 retention-bookkeeping fix (2026-08-21): same fix as the
                    # shape-phase done-state anchor above -- hold at the
                    # realized sweep-final position, not the original target,
                    # if one was captured; falls back to `target` only if this
                    # cluster somehow entered hold without going through a
                    # shape done-state first (defensive, should not happen in
                    # the normal phase sequence).
                    if k not in _wall_final_pos:
                        _wall_final_pos[k] = np.array(cluster_centroids[k], dtype=np.float64)
                    hold_pos = _wall_final_pos[k]
                    dxr, dyr = hold_pos[0] - C.cx, hold_pos[1] - C.cy
                    rr = math.hypot(dxr, dyr)
                    p[dip_idx] = hold_pos
                    if rr > 1e-9:
                        m[dip_idx] = _m_trap * np.array([-dxr / rr, -dyr / rr, 0.0])
                    elif k == 1:
                        m[dip_idx] = _m_trap * np.array([-1., 0., 0.])
                    else:
                        m[dip_idx] = _m_trap * np.array([1., 0., 0.])
                    s[dip_idx] = SHAPE_DONE_HOLD_STRENGTH  # gentle radial hold post-shaping

            else:
                # Transport / interlude states: hold completed clusters at target.
                # Without this, completed clusters free-fall under lunar gravity
                # (g=1.62 m/s²) and hit the floor in ~0.094s during a 0.4s interlude.
                #
                # Caps (Q0, Q3): z-direction moment (set above) provides vertical hold.
                # Walls (Q1, Q2): radial moment has no z-component → tilt 45° to give
                #   equal radial confinement + upward z-support against gravity.
                if k in (0, 3):
                    s[dip_idx] = 0.5
                else:
                    if k == 1:
                        m[dip_idx] = _m_trap * np.array([-0.707, 0., 0.707])
                    else:
                        m[dip_idx] = _m_trap * np.array([ 0.707, 0., 0.707])
                    s[dip_idx] = 0.5

        elif active_cluster == k and is_transporting:
            # ── Stage A-2 CLOSED-LOOP TRANSPORT CONTROLLER (F7/F15) ──────────
            # Replaces the old pure time-schedule (get_transport_progress,
            # removed) with real position+velocity feedback. Full physical
            # derivation: "CLOSED-LOOP TRANSPORT CONTROLLER" block near the
            # top of this file. HISTORY.md "Stage A-2" has the regression this
            # fixes (removing the hard velocity cap in F7 was correct, but the
            # old transport law had nothing else opposing velocity).
            #
            # The dipole's real position/moment/strength are the ONLY things
            # the controller ever touches — the force every particle feels
            # remains exactly F=(Vp*chi_eff/2mu0)*grad(B^2), computed by the
            # unmodified compute_forces kernel. Velocity feedback only decides
            # where to place the real dipole for the NEXT control step —
            # exactly how any real closed-loop electromagnet is driven — never
            # a force added directly to a particle, never filtered by
            # cluster_id (every particle in the domain still feels every
            # active dipole's real field, unchanged).
            x_cur  = cluster_centroids[k]
            v_cur  = (cluster_velocities[k] if cluster_velocities is not None
                      else np.zeros(3))
            target = C.targets[k]
            e_vec  = target - x_cur
            d      = np.linalg.norm(e_vec)
            vmag   = np.linalg.norm(v_cur)
            trap_in = ramp(t, pm.phase_start_t, pm.phase_start_t + 0.3)
            # F21: hysteresis needs to know which zone the PREVIOUS control
            # step ended in, captured before any branch below overwrites it.
            _prev_sub = pm.transport_subphase
            # Stage B: capture the pre-transport integrity baseline once,
            # on this cluster's very first control step of this attempt
            # (cheap dict-lookup guard -- cluster_integrity() itself does a
            # GPU->CPU transfer, so only run it once, not every step).
            if k not in _cluster_baseline:
                _cluster_baseline[k] = cluster_integrity(k)

            if pm.arrived_t is not None:
                # SETTLE / HOLD: dipole at a fixed, safe standoff off the
                # target along the surface normal — NOT coincident with the
                # particles' own location, avoiding the singular near-field
                # right where they sit. Strength has modest headroom (3x)
                # over the acceleration needed to balance gravity at this
                # standoff; cross-talk onto other targets is already
                # negligible at this field scale (verified, see
                # analysis/reconstruct_run.py cross-talk checks).
                pm.transport_subphase = "SETTLE"
                normal = _target_normals[k]
                p[dip_idx] = target + D_HOLD * normal
                m[dip_idx] = -_m_trap * normal
                s_hold = solve_strength_for_accel(3.0 * C.g, D_HOLD)
                s[dip_idx] = max(s_hold, 0.02)

            elif not pm.lift_done:
                # LIFTOFF / LIFT (Stage A-3, F17 fix; deadbeat law Stage A-4,
                # F18 fix): clustering only regroups particles laterally at
                # floor level — z stays pinned at C.R the whole time (verified
                # from real VTU data, see HISTORY.md "Stage A-3") — so every
                # transport genuinely starts needing a real vertical climb
                # against gravity.
                #
                # Dipole tracks directly above the real-time lateral centroid
                # at the same safe standoff (_d_lead=0.5mm) used everywhere
                # else in this controller — verified (real 64-particle
                # geometry, not point-mass) to give 30x margin over the real
                # cluster weight with zero clamp saturation, and lateral
                # force/torque from the real particle asymmetry negligible
                # (0.05% of vertical, ~0 implied angular accel). Moment points
                # straight down (attractive, pulling up).
                #
                # Stage A-4 (F18): the old ramp+smoothstep-throttle law didn't
                # reference the real control period, so a full-strength 6ms
                # step regularly overshot V_CEIL by 30-60% before the throttle
                # reacted (measured directly: v_z spiking to 10-13mm/s against
                # an 8mm/s ceiling) — a real, if self-correcting, bang-bang
                # oscillation. Replaced with a one-step-ahead (deadbeat)
                # predictor using the actual known control period
                # (CTRL_DT_NOMINAL): the gross vertical acceleration commanded
                # is exactly what's needed to land v_z at V_CEIL after one
                # control step, floored so the *correction* term (not the
                # total) never goes negative — this guarantees the commanded
                # force is never less than what's needed to just hold
                # altitude (Fz/Mg >= 1.0 always while this law is active,
                # verified numerically: 1.82x at v_z=0, exactly 1.00x at/above
                # V_CEIL, never below — see HISTORY.md "Stage A-4"), and
                # reaches V_CEIL in exactly one control step with no
                # overshoot (v_z_new = v_z + (V_CEIL-v_z) = V_CEIL).
                #
                # LIFTOFF is verified complete only once the real z position
                # has actually risen (Z_LIFTOFF_CONFIRM, checked in
                # PhaseManager.update() from real sensed position) — not
                # assumed from the commanded strength. LIFT continues the
                # identical law until real floor clearance is reached and
                # sustained (LIFT_DWELL); only then does pm.lift_done latch
                # true and CRUISE/BRAKE become reachable below.
                pm.transport_subphase = "LIFT" if pm.liftoff_confirmed_t is not None else "LIFTOFF"
                v_z = v_cur[2]
                a_vert_gross = C.g + max(0.0, (V_CEIL - v_z) / CTRL_DT_NOMINAL)
                s_lift = solve_strength_for_accel(a_vert_gross, LIFT_CLEARANCE)
                p[dip_idx] = np.array([x_cur[0], x_cur[1], x_cur[2] + LIFT_CLEARANCE])
                m[dip_idx] = np.array([0.0, 0.0, -_m_trap])
                s[dip_idx] = s_lift
                # F21: LIFT's aim direction is always straight up by
                # construction; keep pm._a_hat_prev synced to it so CRUISE's
                # rate limiter is already active from its very FIRST real
                # step (the original F19 spike happened exactly at this
                # handoff) rather than starting unlimited (a_hat_prev=None).
                pm._a_hat_prev = np.array([0.0, 0.0, 1.0])

            elif d > (D_BRAKE_EXIT if _prev_sub == "BRAKE" else D_BRAKE_TRIGGER):
                # CRUISE (Stage A-4, F18 fix): the old law used ONE pull
                # direction (path tangent) and ONE scalar throttle (function
                # of TOTAL speed) to do two independent physical jobs —
                # vertical support and horizontal pursuit — at once. Because
                # free-fall increases total speed, that throttle actively
                # suppressed the very force needed to stop the fall: measured
                # directly, thr_total collapsed to exactly 0.0 one control
                # step after CRUISE engaged and never recovered (vr_tot climbed
                # 1.33->1.43->2.30->3.39->4.54->4.93->6.12 as free-fall kept
                # adding speed), while LIFT's OWN vertical-only throttle had
                # already shown that decoupled-from-horizontal control
                # self-corrects within 1-2 steps. See HISTORY.md "Stage A-4".
                #
                # Fix: two independent channels, each fed by an independent
                # real speed measurement, composed into one 3-D acceleration
                # vector and realized by a SINGLE dipole via the same on-axis
                # convention used everywhere else in this controller (a
                # dipole at x_cur + r*a_hat, moment -a_hat, delivers force of
                # magnitude F(r,s) in EXACTLY direction a_hat — proven
                # sufficient at r=_d_lead=0.5mm: 30.4x cluster weight
                # available there (F17 audit table, real 64-particle
                # geometry), an 11.1x margin over the largest combined target
                # used below (6.87 m/s^2) — so this is never a stretch for a
                # single dipole, no multi-dipole configuration is needed).
                #
                # Vertical channel (F19 fix, see below): a signed ceiling-
                # tracking law fed by v_z and the real signed height error —
                # never perturbed by horizontal motion, but (unlike LIFT,
                # and unlike this branch's original Stage A-4 form) no
                # longer floored at hover. LIFT's Fz>=Mg guarantee still
                # holds for LIFT itself (monotonic climb, no overshoot
                # recovery needed there); CRUISE's vertical channel can
                # command net descent (Fz<Mg) when genuinely above target,
                # which is required to escape a real, observed deadlock
                # (Finding F19) — see the F19 comment at this branch's
                # a_vert_gross computation for the full derivation.
                # Horizontal channel: same deadbeat style, fed by HORIZONTAL
                # speed only (v_x,v_y — never v_z), so free-fall cannot
                # suppress it and it cannot suppress vertical support — this
                # is the actual fix, breaking the positive-feedback loop.
                # Direction is the real pure-pursuit lookahead point (nearest
                # waypoint + lookahead on the existing, unchanged
                # collision-avoiding path arc — make_transport_path() and its
                # live re-anchoring at the real position, F16, are unchanged),
                # projected to the horizontal plane, since the vertical
                # component of travel is now handled by the vertical channel.
                #
                # Because the vector is composed BEFORE realization, the
                # delivered vertical force component equals a_vert_gross
                # exactly — not degraded by whatever the horizontal channel
                # needs — which is what makes the Fz>=Mg guarantee real. The
                # standoff is now a FIXED constant (_d_lead=0.5mm, same as
                # LIFT/BRAKE/SETTLE), not path-derived, so the separation-
                # runaway mechanism that caused F17 cannot recur by
                # construction (no clamp needed — there is nothing to clamp).
                pm.transport_subphase = "CRUISE"
                if _live_path_cache["state"] != pm.state:
                    _other_tgts = [C.targets[j] for j in range(4)
                                   if j != k and j in pm.completed]
                    _live_path_cache["path"] = make_transport_path(
                        x_cur, target, clearance=0.3e-3,
                        other_targets=_other_tgts if _other_tgts else None)
                    _plen = float(np.sum(np.linalg.norm(
                        np.diff(_live_path_cache["path"], axis=0), axis=1)))
                    _live_path_cache["avg_spacing"] = _plen / max(
                        1, len(_live_path_cache["path"]) - 1)
                    _live_path_cache["state"] = pm.state
                path = _live_path_cache["path"]
                n_wp = len(path)
                avg_spacing = _live_path_cache["avg_spacing"]

                diffs = path - x_cur
                nearest_idx = int(np.argmin(np.sum(diffs*diffs, axis=1)))
                lookahead_n = max(1, int(round(
                    PURSUIT_LOOKAHEAD / max(avg_spacing, 1e-9))))
                path_idx = min(nearest_idx + lookahead_n, n_wp - 1)
                path_target = path[path_idx]

                v_z      = v_cur[2]
                # F19 fix: the vertical channel must be able to command
                # descent, not just varying amounts of lift. Previously
                # a_vert_gross = g + max(0,...) floored at hover (g) and
                # could never go net-negative, so a cluster that overshot
                # its target height (verified real cause: a transient
                # clamp-saturation spike at the LIFT->CRUISE handoff, see
                # HISTORY.md Finding F19) could never reduce its height
                # error — d stayed > D_BRAKE_TRIGGER on the vertical
                # component alone, so BRAKE was never entered, and the
                # cluster deadlocked until STALL_TIMEOUT forced completion
                # (reproduced on 2 of 4 real transports; confirmed 187.6mm/s
                # peak Vmag at the spike in the diagnosed run).
                #
                # Fix: mirror the horizontal channel's existing ceiling-
                # tracking form, but take the ceiling's SIGN from the sign
                # of the real height error instead of hardwiring "always
                # ascend." This makes the vertical channel symmetric: it
                # tracks +V_CEIL while below target, -V_CEIL while above
                # it, exactly like the horizontal channel already does
                # (which never had this asymmetry and converges cleanly).
                # No braking taper is added here on purpose: real
                # kinematic braking happens in the BRAKE branch below once
                # d <= D_BRAKE_TRIGGER (see its F20 fix comment — BRAKE
                # itself also needed a gravity-accounting correction,
                # found only after this CRUISE fix let a real transport
                # reach BRAKE with nonzero vertical velocity for the first
                # time). Validated
                # with a synthetic double-integrator test (no simulation
                # run) against the real a_max/g/V_CEIL/D_BRAKE_TRIGGER
                # constants and the real observed F19 overshoot/velocity
                # states: all cases converge within STALL_TIMEOUT with zero
                # chattering and <=43% of the a_max force budget used.
                # NOTE (caught by a real-sim check after the first version of
                # this fix): a_vert_gross is NOT the net acceleration — the
                # downstream a_hat/solve_strength_for_accel realize it as the
                # DIPOLE'S OWN force/mass contribution (gravity acts
                # separately, always, at -g). The old law's "C.g +" term
                # was that offset, not an unrelated floor. Dropping it
                # (first attempt) made a merely-negative deadbeat term read
                # as "pull DOWN with extra force on top of gravity",
                # roughly doubling real descent (confirmed via
                # DEBUG_LIFT_CRUISE live instrumentation: net_az=-1.834m/s^2
                # the instant v_z=10.2mm/s ticked just above V_CEIL=8mm/s,
                # vs. the intended mild -0.37m/s^2 net correction).
                # F23 fix (2026-08-18, see CAPTURE_RADIUS/A_GLIDE/_v_glide_mag derivation
                # above): both channels previously referenced a DISCONTINUOUS step-function
                # target speed (vertical: always +-V_CEIL, sign flipping instantly at the
                # position-error crossing; horizontal: ceiling-only, never asked for
                # deceleration). Diagnosed (F22) as the actual root cause of the near-field
                # direction-reversal chatter that F21's rate limiter and F22's realization
                # change each tried, and failed, to absorb downstream. Fix here, upstream:
                # taper each channel's REFERENCE speed continuously with its own distance
                # (_v_glide_mag), so the reference magnitude is already ~0 by the time either
                # channel's sign/direction would flip — eliminating the discontinuity at its
                # source rather than trying to realize it more gently. Far from target
                # (d >> CAPTURE_RADIUS=0.9mm) this is identical to the old ceiling behavior.
                e_z = target[2] - x_cur[2]
                v_ref_z_mag = _v_glide_mag(abs(e_z))
                v_ref_z = math.copysign(v_ref_z_mag, e_z) if e_z != 0.0 else 0.0
                a_vert_gross  = C.g + (v_ref_z - v_z) / CTRL_DT_NOMINAL

                horiz_vec  = np.array([path_target[0]-x_cur[0], path_target[1]-x_cur[1], 0.0])
                horiz_norm = np.linalg.norm(horiz_vec)
                e_horiz    = horiz_vec/horiz_norm if horiz_norm > 1e-9 else np.zeros(3)
                # Track the SIGNED velocity component along e_horiz (toward path_target), not
                # the unsigned |v_horiz| the old law used — this lets the channel genuinely
                # decelerate overshoot instead of merely stopping acceleration at the ceiling.
                v_horiz_signed = float(np.dot(np.array([v_cur[0], v_cur[1], 0.0]), e_horiz))
                v_ref_h_mag = _v_glide_mag(horiz_norm)
                a_horiz_gross = (v_ref_h_mag - v_horiz_signed) / CTRL_DT_NOMINAL

                a_cmd = np.array([0.0, 0.0, a_vert_gross]) + a_horiz_gross*e_horiz
                a_cmd_mag = np.linalg.norm(a_cmd)
                a_hat_raw = a_cmd/a_cmd_mag if a_cmd_mag > 1e-12 else np.array([0.0, 0.0, 1.0])

                # F21: rate-limit the aim direction (see DTHETA_MAX/
                # _rate_limit_hat derivation) — the dipole's real position
                # only depends on a_hat's DIRECTION (standoff r=_d_lead is
                # fixed regardless of strength), so capping direction-change
                # rate is what actually prevents the sweep from crossing
                # close to a real edge particle. Magnitude is then realized
                # via a raised-cosine weighting of the direction mismatch
                # (F22 fix — see _realize_command_mag docstring): never the
                # raw magnitude along a stale direction (shown unstable by
                # synthetic testing), but also never collapsed to exactly
                # zero for an extended run of steps merely because the raw
                # target is >90 degrees away (the original F21 clamp did
                # this, and real per-step data showed it produced repeated
                # multi-step free-fall windows that caused, not prevented,
                # large excursions — see HISTORY.md "F22 diagnostic").
                a_hat = _rate_limit_hat(pm._a_hat_prev, a_hat_raw)
                dtheta_applied = math.acos(min(1.0, max(-1.0, float(np.dot(
                    pm._a_hat_prev, a_hat_raw))))) if pm._a_hat_prev is not None else 0.0
                dtheta_realized = math.acos(min(1.0, max(-1.0, float(np.dot(
                    pm._a_hat_prev, a_hat))))) if pm._a_hat_prev is not None else 0.0
                a_cmd_mag_raw = a_cmd_mag
                # F22 REVERTED (2026-08-18): _realize_command_mag's raised-cosine weighting
                # passed every cheap synthetic/math test but made the REAL Gate 2 transport_0
                # run measurably WORSE, not better -- see HISTORY.md "F22 fix: designed,
                # implemented, REVERTED after real Gate 2 regression". Restored the original
                # F21 clamp-to-zero realization, which remains the best real validated result
                # to date (STALL at d=0.867mm, v=8.7mm/s, zero saturation events).
                a_cmd_mag = max(0.0, float(np.dot(a_cmd, a_hat)))
                pm._a_hat_prev = a_hat
                if _dbg_lift_cruise:
                    _last_cmd_dbg[k] = dict(zone="CRUISE", a_cmd=a_cmd.copy(),
                        a_cmd_mag_raw=a_cmd_mag_raw, a_cmd_mag=a_cmd_mag,
                        a_hat_raw=a_hat_raw.copy(), a_hat=a_hat.copy(),
                        dtheta_wanted=dtheta_applied, dtheta_realized=dtheta_realized,
                        e_vec=(target-x_cur).copy())

                s_cruise = solve_strength_for_accel(a_cmd_mag, _d_lead)
                p[dip_idx] = x_cur + _d_lead * a_hat
                m[dip_idx] = -_m_trap * a_hat
                s[dip_idx] = s_cruise

                # Stage A-4 failure condition (design §10): the combined
                # vertical+horizontal target should never approach the
                # r=_d_lead ceiling (verified 11.1x margin at typical targets)
                # — if it does, that's a real finding to report, not hide.
                if s_cruise >= 0.999 and not pm._cruise_sat_warned:
                    print(f"  !!! CRUISE SATURATION: cluster {k} commanded strength clipped "
                          f"to s=1.0 at t={t:.3f}s (a_cmd_mag={a_cmd_mag:.2f}m/s^2 exceeds the "
                          f"r={_d_lead*1e3:.2f}mm ceiling). The 11.1x design margin did not hold "
                          f"here — investigate rather than trust downstream phases. !!!")
                    pm._cruise_sat_warned = True

            else:
                # BRAKE (d <= D_BRAKE_TRIGGER, not yet arrived).
                #
                # F24 (2026-08-18): law replaced. See BRAKE_ZETA/BRAKE_OMEGA_N/
                # _brake_accel_pd's derivation above for the full mechanism
                # diagnosis and design rationale. a_net_req is now the desired
                # NET (total, physical) acceleration from a critically-damped
                # spring-damper toward the target, valid at any v including
                # v=0 (unlike the old law, which needed a separate v~=0
                # fallback branch — removed here, folded into the one law).
                #
                # F20 fix (gravity handling) is UNCHANGED and still applies:
                # gravity (`F[2] -= C.mp*C.g` in the integrator) is applied
                # unconditionally every step, independent of the dipole, so
                # the dipole must supply a_net_req PLUS whatever cancels
                # gravity's separately-applied effect: F_dip/mp = a_net_req +
                # (0,0,g), realized as one dipole at magnitude/direction
                # a_hat = normalize(F_dip/mp) — same convention as CRUISE and
                # the pre-F24 BRAKE law, not a new mechanism.
                pm.transport_subphase = "BRAKE"
                a_net_req = _brake_accel_pd(e_vec, v_cur)
                F_over_mp = a_net_req + np.array([0.0, 0.0, C.g])
                a_cmd_mag = np.linalg.norm(F_over_mp)
                a_hat_raw = F_over_mp/a_cmd_mag if a_cmd_mag > 1e-12 else np.array([0.0, 0.0, 1.0])

                # F21: same rate-limit + magnitude-realization treatment
                # as CRUISE (see that branch's comment and
                # _realize_command_mag's docstring for the full F22
                # derivation) — BRAKE's dipole placement is also at a
                # fixed standoff (R_DECEL0=_d_lead=0.5mm) regardless of
                # strength, so the same near-field sweep risk and the
                # same zero-force dead-zone risk both apply here too. F24's
                # PD law is expected to trigger this dead zone far less often
                # since it no longer commands large sudden direction swings
                # near the target — but the safeguard itself is untouched.
                a_hat = _rate_limit_hat(pm._a_hat_prev, a_hat_raw)
                dtheta_applied = math.acos(min(1.0, max(-1.0, float(np.dot(
                    pm._a_hat_prev, a_hat_raw))))) if pm._a_hat_prev is not None else 0.0
                dtheta_realized = math.acos(min(1.0, max(-1.0, float(np.dot(
                    pm._a_hat_prev, a_hat))))) if pm._a_hat_prev is not None else 0.0
                a_cmd_mag_raw = a_cmd_mag
                # F22 REVERTED (2026-08-18): see the CRUISE branch's identical comment above
                # and HISTORY.md — restored the original F21 clamp-to-zero realization.
                a_cmd_mag = max(0.0, float(np.dot(F_over_mp, a_hat)))
                pm._a_hat_prev = a_hat
                if _dbg_lift_cruise:
                    _last_cmd_dbg[k] = dict(zone="BRAKE", a_cmd=F_over_mp.copy(),
                        a_cmd_mag_raw=a_cmd_mag_raw, a_cmd_mag=a_cmd_mag,
                        a_hat_raw=a_hat_raw.copy(), a_hat=a_hat.copy(),
                        dtheta_wanted=dtheta_applied, dtheta_realized=dtheta_realized,
                        e_vec=(target-x_cur).copy(), a_needed=np.linalg.norm(a_net_req))

                s_decel  = solve_strength_for_accel(a_cmd_mag, R_DECEL0)
                p[dip_idx] = x_cur + R_DECEL0 * a_hat
                m[dip_idx] = -_m_trap * a_hat
                s[dip_idx] = s_decel
                if s_decel >= 0.999 and not pm._brake_sat_warned:
                    print(f"  !!! BRAKE SATURATION: cluster {k} commanded strength clipped "
                          f"to s=1.0 at t={t:.3f}s (a_cmd_mag={a_cmd_mag:.2f}m/s^2 exceeds the "
                          f"r={R_DECEL0*1e3:.2f}mm ceiling) — investigate rather than trust "
                          f"downstream phases. !!!")
                    pm._brake_sat_warned = True

        # else: cluster not yet active → dipole stays OFF (s=0)

    # ── HOLD RING — PERMANENTLY DISABLED (audit finding F4) ────────────────
    # This apparatus is named/commented throughout the file as a "4-dipole
    # square ring" with a B² maximum at its center by 4-fold symmetry, but
    # only 2 of the 4 nominal positions (IDX_HOLD_A/B, at +-x offsets) were
    # ever actually instantiated (the +-y positions the v31 comment above
    # describes were never added — see the v31 comment block, which itself
    # admits this). Two dipoles are two point B² attractors, not a ring: in
    # the pre-fix simulation, activating them at hold-state entry pulled the
    # ENTIRE Q0/Q3 cluster onto the +x dipole (verified against
    # outputs/phase2_checkpoint.pkl: final Q0 centroid (7.49,4.97,7.10)mm
    # sits on dip12 at (7.50,5.00,7.24)mm, spread collapsed to ~0). This is
    # the terminal "everything gets sucked to a point outside the cylinder"
    # failure reported at the end of Phase 2. Fixing it means not
    # re-tuning CAP_SHAPE_HOLD_S but removing the activation: a correct
    # symmetric ring is a Stage B design question (needs a real 4th/8th
    # dipole set with genuine 4-fold or higher symmetry — see CONTEXT.md
    # Physical limits section), not a Stage A parameter fix. Kept at s=0 for
    # all states; index/checkpoint slots remain allocated for compatibility.
    for k in range(4):
        s[IDX_HOLD_A[k]] = 0.0
        s[IDX_HOLD_B[k]] = 0.0

    # ── SHAPE DIPOLES — v29 STATIC EXTERNAL RING / VERTICAL RAKE ────────────
    #
    # ═══════════════════════════════════════════════════════════════════════
    # ARCHITECTURE OVERVIEW
    # ═══════════════════════════════════════════════════════════════════════
    #
    # CAP SHAPING (Q0 top, Q3 bottom) — STATIC EXTERNAL RING:
    #
    #   N_CAP_RING = 6 dipoles, uniformly spaced in azimuth at radius r_ring(t),
    #   placed OUTSIDE the cap plane by SHAPE_D_SURF:
    #     Q0: z = tgt_z + SHAPE_D_SURF  (above domain)
    #     Q3: z = tgt_z - SHAPE_D_SURF  (below domain)
    #   Moments point radially INWARD in the horizontal plane (no z-component).
    #
    #   WHY IT WORKS:
    #   The ring of N external dipoles creates a B² field in the cap plane (z=tgt_z)
    #   that is azimuthally symmetric (N=6 → 6-fold, effectively isotropic for N≥4).
    #   The radial profile of B²(ρ) in the cap plane has a MAXIMUM at ρ ≈ 0.707*r_ring
    #   (analytical result for a ring of radial-moment dipoles). This is a genuine
    #   static B² annular attractor — no time-averaging assumption needed.
    #   As r_ring(t) sweeps outward from 0.1*cR to 1.08*cR, the attractor ring in the
    #   cap plane sweeps from ≈0.07*cR to ≈0.76*cR, dragging particles outward. ✓
    #
    #   WHY NO RING RISE:
    #   Moments are purely radial (no z-component) → by symmetry, B_z = 0 at z=tgt_z
    #   exactly on the symmetry plane. Therefore ∂B²/∂z = 0 at z=tgt_z from the ring.
    #   Hold pair provides the z-pinning gradient. Fully orthogonal forces. ✓
    #
    #   WHY NO EJECTION:
    #   Minimum dipole-to-particle distance = SHAPE_D_SURF = 0.9mm (axial offset).
    #   Max |∇B²| ≈ μ₀·m / SHAPE_D_SURF⁴ — bounded regardless of r_ring. ✓
    #
    #   r_ring SCHEDULE (3 phases):
    #     Phase A (0.0→0.65): r_ring sweeps CAP_RING_R_START*cR → CAP_RING_R_END*cR
    #     Phase B (0.65→0.80): r_ring held at CAP_RING_R_END*cR (perimeter capture)
    #     Phase C (0.80→1.0):  r_ring compresses back to CAP_COMPRESS_R*cR
    #     Compress deepens the radial well at the perimeter, locking the ring shape.
    #
    # WALL SHAPING (Q1 left, Q2 right) — VERTICAL RAKE:
    #
    #   N_WALL_RAKE = 6 dipoles, spaced vertically from z_lo to z_hi at:
    #     radius = cR + SHAPE_D_SURF from cylinder axis
    #     azimuth angle θ_rake(t): sweeps ±WALL_RAKE_HALF_AZ around target angle
    #   Moments point radially INWARD (−r̂ at current θ_rake).
    #
    #   WHY IT WORKS:
    #   The rake is a vertical line of attractors fixed on the exterior of the cylinder.
    #   Particles within the arc ≈ ±20° of the rake are attracted radially outward to
    #   the cylinder wall (radius cR) AND spread vertically to align with all N rake
    #   dipoles. The wall provides a substrate — gravity deposits particles bottom-up.
    #   As θ_rake sweeps ±WALL_RAKE_HALF_AZ around the target angle over the slot,
    #   every azimuthal position in the coverage arc is painted in stripes.
    #
    #   WHY BETTER THAN TRIPLET:
    #   - N=6 vertical positions → full z-coverage in one pass (no z-staircase needed)
    #   - Static in z → no oscillation → gravity+contact ensure bottom-up settling
    #   - Azimuthal sweep rate is slow (< ω_mech) → each stripe has time to settle
    #     before the rake moves on. Deposition, not chasing. ✓
    #
    #   Z-support for walls:
    #   The cluster dipole (IDX_CLUSTER_DIP[k]) is placed BELOW target at tgt_z - 2mm,
    #   moment +z, at strength SHAPE_WAIT_HOLD_STRENGTH — provides upward z-bias. ✓

    for idx in IDX_SHAPE:
        s[idx] = 0.0

    if pm.state == "shape":
        shape_elapsed = t - pm.phase_start_t
        t_frac = min(shape_elapsed / SHAPE_TIME, 1.0)
        shape_slot = min(int(t_frac * 4), 3)
        active_shape_k = SHAPE_ORDER[shape_slot]
        slot_frac_start = shape_slot / 4.0
        slot_frac_end   = (shape_slot + 1) / 4.0
        local_frac = max(0.0, min(1.0,
            (t_frac - slot_frac_start) / (slot_frac_end - slot_frac_start)))
        slot_start_t = pm.phase_start_t + slot_frac_start * SHAPE_TIME
        # Ramp strength in over 0.3s at slot start
        ramp_in = ramp(t, slot_start_t, slot_start_t + 0.3)
        # Progressively reduce field strength over the slot: start strong to initiate
        # spreading, end weak so surface confinement + inter-particle repulsion dominate.
        # Linear decay: SHAPE_ACTIVE_PLOW_STRENGTH → 0.05 over the full slot.
        peak_str  = SHAPE_ACTIVE_PLOW_STRENGTH * max(0.0625, 1.0 - 0.9375 * local_frac)
        shape_str = ramp_in * peak_str

        if active_shape_k in pm.completed:
            tgt       = C.targets[active_shape_k]
            ring_idxs = SHAPE_RING_MAP[active_shape_k]

            # ── SINGLE SCANNING DIPOLE (v32) ─────────────────────────────────
            #
            # ROOT CAUSE OF ALL v29-v31 FAILURES:
            #   N simultaneous dipoles (ring, belt) create N B² maxima simultaneously.
            #   Paramagnetic particles split into N sub-clusters, one per maximum.
            #   This is fundamental: Earnshaw's theorem + particle dynamics guarantee
            #   that a static ring of N dipoles CANNOT create a ring attractor in free
            #   space. Each dipole IS its own attractor.
            #
            # v32 FIX — SINGLE DIPOLE PLOW MODEL:
            #   ONE dipole per shape slot, sweeping the target surface.
            #   At outer radii the sweep speed exceeds v_cap → particles cannot
            #   follow → they are deposited in a trail behind the moving maximum.
            #
            #   Caps: Archimedean spiral, r = cR*local_frac, θ = N_REVS*2π*local_frac.
            #     Tangential speed at outer radius ≈ cR * 2π*N_REVS/T_slot
            #     = 1.667mm * 2π*8/5s ≈ 16.7mm/s >> v_cap=5mm/s → spreading ✓
            #     Single B² maximum = zero possibility of lobe splitting ✓
            #
            #   Walls: (phi, z) raster. phi sweeps ±π/2 around target azimuth.
            #     z oscillates z_lo↔z_hi four times over the slot.
            #     r = cR + 0.3mm (close to wall surface, strong gradient).
            #     Moment: radially inward + 30% upward tilt (gravity compensation).
            #     Cluster anchor (IDX_CLUSTER_DIP) is OFF for active cluster.
            #       FIX for "did nothing": the anchor at s=0.15 and ~0mm distance
            #       dominated the belt at s=0.80 but 3.2mm away (force ∝ 1/r⁴).
            #       With anchor OFF, the scan dipole is the only attractor → works ✓
            #
            # Walls use ring_idxs[0] only (single scan dipole).
            # All unused slots remain at s=0 (set by the loop above).
            scan_idx = ring_idxs[0]  # wall branch only; caps use no active dipoles

            if active_shape_k in (0, 3):
                # ── CAP SHAPING v36: CONTACT + DAMPING (NO BIAS) ─────────────
                #
                # No external shape dipoles activated (Earnshaw prevents any static
                # ring from giving a stable planar B² attractor).
                # Spreading governed by THREE mechanisms in compute_forces:
                #
                #   1. SURF_CONF Z-SPRING (SURF_CONF_K = 0.5 N/m):
                #      Pins each cap particle to z = z_hi (Q0) or z = z_lo (Q3).
                #      No horizontal force → zero azimuthal torque → no orbiting. ✓
                #      Spring is cluster_id-filtered → zero cross-cluster field. ✓
                #      ω·dt = 0.190 (numerically stable). ✓
                #
                #   2. HERTZ-MINDLIN CONTACT REPULSION (primary spreading):
                #      Dense ~51% 3D packing ball → spring flattens to 2D disk →
                #      massive contact overlaps → F ∝ δ^1.5 drives radial burst.
                #      Burst velocity ≈ v_cap in random directions from each particle. ✓
                #
                #   3. VISCOUS DAMPING (CAP_VISC_DAMP_TAU = 0.25 s):
                #      F_damp = -(mp/τ)·v; stopping dist = v_cap·τ = 1.25mm < cR.
                #      Particles stop within disk — no wall bounce, no oscillation. ✓
                #      Particles at rest after ~3τ = 0.75s. ✓
                #
                # WHY k_r=0 (v36 vs v35):
                #   v35 used k_r=0.05 N/m as "weak bias." But ω_osc=√(k_r/mp)=7530 rad/s
                #   → period 0.835ms; with τ_damp=0.5s → 600 undamped oscillation cycles.
                #   64 particles on 1D ring (all driven to r≈cR) undergo Smoluchowski
                #   coagulation → two equal sub-clusters. Removing k_r eliminates the
                #   radial oscillator entirely. No k_r → no ring dynamics → no sub-clusters.
                #
                # EXPECTED OUTCOME (v36):
                #   Burst from r≈0 with v=v_cap in random directions; max r_final =
                #   r_2D + v_cap·τ ≈ 0.34 + 1.25 = 1.59mm < cR = 1.667mm (no wall). ✓
                #   Azimuthally symmetric annulus at r ∈ [0.3, 1.6]mm, stable, at rest.
                #
                # All ring_idxs remain at s = 0 (set by the loop above).
                pass  # no external shape dipoles for caps

            else:
                # ── WALL SHAPING G3 (2026-08-19): COVERAGE-FEEDBACK SLOW WELL ──────
                #
                # Replaces the v33 fast (~14mm/s) raster, which was deliberately
                # too fast for particles to follow (outrun-and-deposit). The final
                # pre-implementation feasibility gate
                # (analysis/SHAPING_FEASIBILITY_GATE_2026-08-19.md) tested this
                # exact dipole geometry — zero standoff (dipole AT the target
                # surface point), pure radial-inward moment, strength
                # SHAPE_WAIT_HOLD_STRENGTH (the SAME real, validated "wait" hold
                # config already used elsewhere in this file, see
                # IDX_CLUSTER_DIP's wait branch above) — translated slowly in
                # azimuth against a real 64-particle wall cluster:
                #   - tracking error is speed-independent (dominated by an
                #     intrinsic ~0.13mm radial oscillation, not lag) up to 5mm/s
                #   - degrades at 10mm/s, catastrophically fails at 15mm/s
                #     (particles left behind entirely, Fmag -> ~0)
                # This independently confirms, from direct simulation, the same
                # v_tan~14mm/s "particles cannot follow" threshold the old v33
                # code already documented analytically -- WELL_V_TAN=3mm/s
                # (module constant) keeps a >=1.7x margin under the clean
                # ceiling actually measured.
                #
                # CLOSED-LOOP, NOT OPEN-LOOP: the aim point only advances while
                # the real (sensed) cluster centroid stays within
                # WELL_TRACK_ERR_MAX of it; otherwise it freezes until the
                # cluster catches up -- this never deliberately outruns the
                # particles (unlike v33, which was explicitly designed to).
                # Coverage is a simple (theta, z) raster: sweep the full
                # +-PHI_HALF_SPAN arc at one z level, step to the next z level,
                # repeat -- WELL_N_Z_LEVELS bands span the wall height. The
                # +-60 deg arc limit is unchanged from v33 (safety gap to the
                # opposite wall cluster, Q1/Q2 are pi apart).
                #
                # Persistent state (_wall_well_state, module-level, same pattern
                # as the transport controller's _live_path_cache) tracks sweep
                # progress across calls -- this is a real, physically realizable
                # control state (an actuator's stored setpoint), not a target-
                # position filter or hidden force.
                tgt_phi = math.atan2(tgt[1] - C.cy, tgt[0] - C.cx)
                PHI_HALF_SPAN = PI / 3.0   # +-60 deg -- unchanged safety gap to opposite wall
                Z_CAP_MARGIN = 0.75e-3     # unchanged from v33 -- keeps sweep off the cap rims
                # G3 bugfix #1 (found via full-cycle validation + isolated
                # control-logic debug): C.targets[k] is not exactly at radius
                # C.cR (measured discrepancy: 0.20mm for Q1) -- fixed by
                # deriving r_scan from the real target radius, not C.cR.
                r_scan = math.hypot(tgt[0] - C.cx, tgt[1] - C.cy)
                z_lo_m = C.z_lo + Z_CAP_MARGIN
                z_hi_m = C.z_hi - Z_CAP_MARGIN

                # G3 bugfix #2: an earlier version stepped z in WELL_N_Z_LEVELS
                # discrete jumps once each phi sweep completed. Each jump
                # (~0.83mm for 4 levels) instantly exceeded WELL_TRACK_ERR_MAX
                # (0.30mm) the moment it fired, and since the wall's anchor
                # dipole (IDX_CLUSTER_DIP, still active in parallel) keeps
                # holding the cluster tightly at the ORIGINAL target height,
                # the gate could never recover -- verified directly: even
                # after fixing bug #1, z_level froze permanently one step
                # after its very first (correctly-initialized) jump. Fixed by
                # replacing discrete z-levels with a continuous, slow z-creep
                # at the SAME validated linear rate as the phi sweep (paced to
                # nominally traverse the wall height once per ~5s slot) so no
                # single step can ever exceed the tracking tolerance.
                if active_shape_k not in _wall_well_state:
                    z_frac0 = 0.0 if (z_hi_m - z_lo_m) < 1e-12 else \
                        min(1.0, max(0.0, (tgt[2] - z_lo_m) / (z_hi_m - z_lo_m)))
                    _wall_well_state[active_shape_k] = dict(
                        phi_frac=0.5, direction=1, z_frac=z_frac0, z_direction=1, last_t=t)
                wst = _wall_well_state[active_shape_k]

                z_scan = z_lo_m + wst["z_frac"] * (z_hi_m - z_lo_m)
                phi_scan = tgt_phi + PHI_HALF_SPAN * (2.0 * wst["phi_frac"] - 1.0)

                px = C.cx + r_scan * math.cos(phi_scan)
                py = C.cy + r_scan * math.sin(phi_scan)
                aim_point = np.array([px, py, z_scan])
                p[scan_idx] = aim_point
                m[scan_idx] = _m_trap * np.array(
                    [-math.cos(phi_scan), -math.sin(phi_scan), 0.0])
                s[scan_idx] = SHAPE_WAIT_HOLD_STRENGTH

                # ── tracking-error gate: advance only if the cluster is keeping up ──
                real_centroid = cluster_centroids[active_shape_k]
                track_err = float(np.linalg.norm(real_centroid - aim_point))
                dt_ctrl = max(t - wst["last_t"], 0.0)
                wst["last_t"] = t
                if track_err <= WELL_TRACK_ERR_MAX and dt_ctrl > 0.0:
                    arc_len = 2.0 * PHI_HALF_SPAN * r_scan
                    d_frac_phi = (WELL_V_TAN * dt_ctrl) / arc_len
                    wst["phi_frac"] += wst["direction"] * d_frac_phi
                    if wst["phi_frac"] >= 1.0:
                        wst["phi_frac"] = 1.0
                        wst["direction"] = -1
                    elif wst["phi_frac"] <= 0.0:
                        wst["phi_frac"] = 0.0
                        wst["direction"] = 1
                    # G3 bugfix #4 (2026-08-20): z used to WRAP (z_frac -= 1.0)
                    # once it exceeded 1.0, teleporting the aim point's z by
                    # the full span (2.5mm measured) in a single control step
                    # -- confirmed directly via fine-grained instrumentation
                    # (analysis/runs/g3_fix3_finegrained_3p5.json): track_err
                    # jumped from 0.0025mm to 2.25mm in one ~20ms step exactly
                    # when z_frac wrapped 0.9999->0.0001, producing a brief
                    # huge force transient (Fmag spiked ~1000x) that flung the
                    # still-coherent cluster (r_rms unchanged) out of the
                    # well's effective range entirely. phi already reverses
                    # direction at its bounds instead of wrapping (see above)
                    # -- z now does the same, for consistency and to remove
                    # the discontinuity.
                    SLOT_NOMINAL_S = SHAPE_TIME / 4.0
                    d_frac_z = dt_ctrl / SLOT_NOMINAL_S
                    wst["z_frac"] += wst["z_direction"] * d_frac_z
                    if wst["z_frac"] >= 1.0:
                        wst["z_frac"] = 1.0
                        wst["z_direction"] = -1
                    elif wst["z_frac"] <= 0.0:
                        wst["z_frac"] = 0.0
                        wst["z_direction"] = 1
                # else: aim point frozen this step -- cluster has not caught up

    # Audit findings F6/F7: the phase-adaptive hard velocity cap that used
    # to be set here was removed along with the clip in integrate(). Speed
    # is now whatever F=ma actually produces; the wall-scan "deposition, not
    # chasing" argument used a hard v_cap as its comparison baseline
    # (v_tan >> v_cap) and must be re-verified empirically against real
    # particle speeds post-fix (see analysis/validate_phase2.py) rather than
    # assumed from a removed design constant.

    # ── Upload to Taichi and sync monitoring array ────────────────────
    dip_p.from_numpy(p)
    dip_m.from_numpy(m)
    dip_s.from_numpy(s)
    np.copyto(dip_str_np, s)
    np.copyto(dip_mom_np, m)    # v19: sync for energy tracking diagnostic
    # Audit finding F10: dip_pos_np was never synced from the per-batch
    # working buffer `p`, only dip_mom_np/dip_str_np were — so checkpoints
    # (save_checkpoint/save_shape_checkpoint read dip_pos_np directly)
    # stored stale dipole positions instead of the true positions being
    # simulated. Restored dipole positions after --resume were therefore
    # wrong until the next update_dipoles() call overwrote them.
    np.copyto(dip_pos_np, p)


# ═══════════════════════════════════════════════════════════════════════════
# VTU / PVD OUTPUT
# ═══════════════════════════════════════════════════════════════════════════
def cylinder_markers():
    pts = []
    for zz in [C.z_lo, C.cz, C.z_hi]:
        ths = np.linspace(0, 2*PI, 48, endpoint=False)
        for th in ths:
            pts.append([C.cx + C.cR*math.cos(th), C.cy + C.cR*math.sin(th), zz])
    for j in range(12):
        th = 2*PI*j/12
        for fr in np.linspace(0, 1, 10):
            pts.append([C.cx + C.cR*math.cos(th), C.cy + C.cR*math.sin(th),
                        C.z_lo + fr*C.cH])
    return np.array(pts, dtype=np.float64)

_cyl_markers = cylinder_markers()

def _fmt_pts(arr):
    # Vectorised: ~10x faster than per-row f-string loop for N=256
    return '\n'.join(
        f'{r[0]:.8e} {r[1]:.8e} {r[2]:.8e}'
        for r in arr
    ) + '\n'

# Pre-build the static VTK marker string once at module load
_cyl_pts_str   = _fmt_pts(_cyl_markers)
_nm             = len(_cyl_markers)
_cyl_minus1_str = '\n'.join(['-1'] * _nm) + '\n'
_cyl_zero_str   = '\n'.join(['0']  * _nm) + '\n'

def write_vtu(fpath):
    # Reuse already-fetched arrays when called from the output block
    # (pos/vel/fmag/cluster_id/ncontact are pulled by cluster_stats before this)
    p_  = pos.to_numpy()
    v_  = vel.to_numpy()
    fm_ = fmag.to_numpy()
    cl_ = cluster_id.to_numpy()
    nc_ = ncontact.to_numpy()
    N   = C.N; nt = N + _nm

    # Vectorised norm computation
    fmm = np.linalg.norm(fm_, axis=1)
    vm  = np.linalg.norm(v_,  axis=1)

    # Particle position strings (vectorised via numpy)
    p_rows = (f'{p_[i,0]:.8e} {p_[i,1]:.8e} {p_[i,2]:.8e}' for i in range(N))
    p_str  = '\n'.join(p_rows) + '\n'

    cl_str  = '\n'.join(map(str, cl_))  + '\n'
    fmm_str = '\n'.join(f'{x:.6e}' for x in fmm) + '\n'
    vm_str  = '\n'.join(f'{x:.6e}' for x in vm)  + '\n'
    nc_str  = '\n'.join(map(str, nc_))  + '\n'

    with open(fpath, 'w') as f:
        f.write(
            f'<?xml version="1.0"?>\n'
            f'<VTKFile type="UnstructuredGrid" version="1.0">\n'
            f'<UnstructuredGrid>\n'
            f'<Piece NumberOfPoints="{nt}" NumberOfCells="0">\n'
            f'<Points>\n'
            f'<DataArray type="Float64" NumberOfComponents="3" format="ascii">\n'
            + p_str + _cyl_pts_str +
            f'</DataArray>\n</Points>\n'
            f'<PointData>\n'
            f'<DataArray type="Int32" Name="ClusterID" format="ascii">\n'
            + cl_str + _cyl_minus1_str +
            f'</DataArray>\n'
            f'<DataArray type="Float64" Name="Fmag" format="ascii">\n'
            + fmm_str + _cyl_zero_str +
            f'</DataArray>\n'
            f'<DataArray type="Float64" Name="Vmag" format="ascii">\n'
            + vm_str + _cyl_zero_str +
            f'</DataArray>\n'
            f'<DataArray type="Int32" Name="Ncontact" format="ascii">\n'
            + nc_str + _cyl_zero_str +
            f'</DataArray>\n'
            f'</PointData>\n'
            f'<Cells>\n'
            f'<DataArray type="Int32" Name="connectivity" format="ascii"/>\n'
            f'<DataArray type="Int32" Name="offsets" format="ascii"/>\n'
            f'<DataArray type="UInt8" Name="types" format="ascii"/>\n'
            f'</Cells>\n'
            f'</Piece>\n</UnstructuredGrid>\n</VTKFile>\n'
        )

def write_pvd(fpath, entries):
    lines = [
        '<?xml version="1.0"?>\n',
        '<VTKFile type="Collection" version="0.1">\n',
        '<Collection>\n',
    ] + [f'<DataSet timestep="{tv:.6f}" file="{fn}"/>\n' for fn, tv in entries] + [
        '</Collection>\n</VTKFile>\n',
    ]
    with open(fpath, 'w') as f:
        f.writelines(lines)


# ═══════════════════════════════════════════════════════════════════════════
# CHECKPOINT SYSTEM
# ═══════════════════════════════════════════════════════════════════════════
CKPT_DIR  = Path("outputs")
CKPT_FILE = CKPT_DIR / "phase2_checkpoint.pkl"

# ── Shape checkpoint — saved ONCE automatically when sim first enters shape ──
# Stores the exact particle state at the end of the last transport/interlude,
# so --skip-to-shape can reload real positions instead of guessing a timestamp.
SHAPE_CKPT_FILE = CKPT_DIR / "shape_checkpoint.pkl"


def save_shape_checkpoint(step, t, pm, pvd_entries, hist_t, hist_ke, hist_fm, hist_sp):
    """Save a dedicated shape-start checkpoint to SHAPE_CKPT_FILE.

    Called exactly once, the first time the sim enters the shape phase.
    Contains everything needed to resume from the true start of shaping:
    particle positions, velocities, cluster assignments, dipole state,
    phase manager state (completed={0,1,2,3}, state='shape'), and all
    history arrays so the diagnostic plots remain continuous.
    """
    global colors_fixed, dip_pos_np, dip_mom_np, dip_str_np
    import pickle
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = SHAPE_CKPT_FILE.with_suffix(".pkl.tmp")
    try:
        data = {
            'step':          step,
            't':             float(t),
            'colors_fixed':  bool(colors_fixed),
            'phase_manager': pm.to_dict(),
            'pvd_entries':   list(pvd_entries),
            'hist_t':        list(hist_t),
            'hist_ke':       list(hist_ke),
            'hist_fm':       list(hist_fm),
            'hist_sp':       list(hist_sp),
            'pos':           pos.to_numpy(),
            'vel':           vel.to_numpy(),
            'cluster_id':    cluster_id.to_numpy(),
            'fixed_color':   fixed_color.to_numpy(),
            'ncontact':      ncontact.to_numpy(),
            'dip_pos_np':    dip_pos_np.copy(),
            'dip_mom_np':    dip_mom_np.copy(),
            'dip_str_np':    dip_str_np.copy(),
            'rng_state':     np.random.get_state(),
            'label':         'shape-start',
            'version':       SIM_VERSION,
            'N_DIP':         N_DIP,
        }
        data['phase_manager']['completed'] = list(data['phase_manager']['completed'])
        with open(tmp_path, 'wb') as f:
            pickle.dump(data, f)
        os.replace(str(tmp_path), str(SHAPE_CKPT_FILE))
        print(f"  ✓ Shape checkpoint saved: step={step} t={t:.3f}s → {SHAPE_CKPT_FILE.name}")
        return True
    except Exception as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except: pass
        print(f"  ✗ Shape checkpoint save FAILED: {e}", file=sys.stderr)
        return False


def load_shape_checkpoint():
    """Load the dedicated shape-start checkpoint if it exists."""
    import pickle
    if not SHAPE_CKPT_FILE.exists():
        return False, None
    try:
        with open(SHAPE_CKPT_FILE, 'rb') as f:
            data = pickle.load(f)
        print(f"  ✓ Shape checkpoint loaded: step={data['step']} t={data['t']:.3f}s  "
              f"label={data.get('label','?')}")
        return True, data
    except Exception as e:
        print(f"  ✗ Cannot load shape checkpoint: {e}", file=sys.stderr)
        return False, None

def save_checkpoint(step, t, pm, pvd_entries, hist_t, hist_ke, hist_fm, hist_sp,
                    label="auto", verbose=True):
    global colors_fixed, dip_pos_np, dip_mom_np, dip_str_np
    import pickle
    CKPT_DIR.mkdir(parents=True, exist_ok=True)

    tmp_path = CKPT_FILE.with_suffix(".pkl.tmp")

    try:
        data = {
            'step':         step,
            't':            float(t),
            'colors_fixed': bool(colors_fixed),
            'phase_manager': pm.to_dict(),
            'pvd_entries':  list(pvd_entries),
            'hist_t':       list(hist_t),
            'hist_ke':      list(hist_ke),
            'hist_fm':      list(hist_fm),
            'hist_sp':      list(hist_sp),
            'pos':          pos.to_numpy(),
            'vel':          vel.to_numpy(),
            'cluster_id':   cluster_id.to_numpy(),
            'fixed_color':  fixed_color.to_numpy(),
            'ncontact':     ncontact.to_numpy(),
            'dip_pos_np':   dip_pos_np.copy(),
            'dip_mom_np':   dip_mom_np.copy(),
            'dip_str_np':   dip_str_np.copy(),
            'rng_state':    np.random.get_state(),
            'label':        label,
            'version':      SIM_VERSION,
            'N_DIP':        N_DIP,
        }
        data['phase_manager']['completed'] = list(data['phase_manager']['completed'])

        with open(tmp_path, 'wb') as f:
            pickle.dump(data, f)
        os.replace(str(tmp_path), str(CKPT_FILE))

        if verbose:
            print(f"  ✓ Checkpoint [{label}] saved: step={step} t={t:.3f}s  "
                  f"→ {CKPT_FILE.name}")
        return True

    except Exception as e:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except: pass
        print(f"  ✗ Checkpoint save FAILED at step={step}: {e}", file=sys.stderr)
        return False


def list_checkpoints(ckpt_dir=None):
    if CKPT_FILE.exists():
        return [{'path': str(CKPT_FILE)}]
    return []


def load_checkpoint(path=None, latest=False, ckpt_dir=None):
    import pickle
    ckpt_path = Path(path) if path else CKPT_FILE
    if not ckpt_path.exists():
        return False, None
    try:
        with open(ckpt_path, 'rb') as f:
            data = pickle.load(f)
        print(f"  ✓ Checkpoint loaded: step={data['step']} t={data['t']:.3f}s  "
              f"label={data.get('label','?')}")
        return True, data
    except Exception as e:
        print(f"  ✗ Cannot load checkpoint: {e}", file=sys.stderr)
        return False, None


def restore_from_checkpoint(data, pm):
    global colors_fixed, dip_pos_np, dip_mom_np, dip_str_np

    pos.from_numpy(data['pos'])
    vel.from_numpy(data['vel'])
    cluster_id.from_numpy(data['cluster_id'])
    fixed_color.from_numpy(data['fixed_color'])
    ncontact.from_numpy(data['ncontact'])
    frc.from_numpy(np.zeros((C.N, 3), dtype=np.float64))
    fmag.from_numpy(np.zeros((C.N, 3), dtype=np.float64))

    saved_dip_str = data['dip_str_np']
    n_saved = len(saved_dip_str)
    if n_saved == N_DIP:
        np.copyto(dip_pos_np, data['dip_pos_np'])
        np.copyto(dip_mom_np, data['dip_mom_np'])
        np.copyto(dip_str_np, saved_dip_str)
    else:
        print(f"  ⚠ Dipole count mismatch (saved={n_saved}, current={N_DIP}). "
              f"Using default dipole config.")
        dip_str_np[:] = 0.0

    dip_p.from_numpy(dip_pos_np)
    dip_m.from_numpy(dip_mom_np)
    dip_s.from_numpy(dip_str_np)

    if 'rng_state' in data:
        np.random.set_state(data['rng_state'])

    colors_fixed = data['colors_fixed']
    pm.from_dict(data['phase_manager'])

    return (data['step'], data['t'],
            list(data.get('pvd_entries', [])),
            list(data.get('hist_t', [])),
            list(data.get('hist_ke', [])),
            list(data.get('hist_fm', [])),
            list(data.get('hist_sp', [])))


# ═══════════════════════════════════════════════════════════════════════════
# INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════
def init():
    np.random.seed(42)
    n = C.N
    n_pq = n // 4
    side = int(math.ceil(math.sqrt(n_pq)))
    p = np.zeros((n, 3), dtype=np.float64)
    idx = 0
    np.random.seed(42)   # keep deterministic across runs (change seed for variety)
    for quad in range(4):
        qx_min = 0.0   if quad in [1, 3] else C.L/2
        qx_max = C.L/2 if quad in [1, 3] else C.L
        qy_min = 0.0   if quad in [2, 3] else C.L/2
        qy_max = C.L/2 if quad in [2, 3] else C.L
        qcx, qcy = C.qc[quad]
        uw = 0.6 * (qx_max - qx_min)
        uh = 0.6 * (qy_max - qy_min)
        sp = min(uw, uh) / (side - 1) if side > 1 else 0
        sp = max(sp, 4.0 * 2.0 * C.R)
        tsX = sp * (side - 1); tsY = sp * (side - 1)
        sx = qcx - tsX/2;     sy = qcy - tsY/2
        for iy in range(side):
            for ix in range(side):
                if idx >= n: break
                # Stochastic initial conditions (realistic loose pile)
                x = np.clip(sx + sp*ix + np.random.normal(0, 0.2 * C.R), C.R, C.L - C.R)
                y = np.clip(sy + sp*iy + np.random.normal(0, 0.2 * C.R), C.R, C.L - C.R)
                z = C.R + np.random.uniform(0, 0.6 * C.R)   # taller initial pile
                p[idx] = [x, y, z]
                idx += 1
    pos.from_numpy(p)
    vel.from_numpy(np.zeros((n, 3), dtype=np.float64))
    frc.from_numpy(np.zeros((n, 3), dtype=np.float64))
    fmag.from_numpy(np.zeros((n, 3), dtype=np.float64))
    cluster_id.from_numpy(np.zeros(n, dtype=np.int32))
    fixed_color.from_numpy(np.zeros(n, dtype=np.int32))
    ncontact.from_numpy(np.zeros(n, dtype=np.int32))
    qc_ti.from_numpy(C.qc)
    assign_centres.from_numpy(C.qc_3d)
    surf_conf_enabled[None] = 0
    dip_p.from_numpy(dip_pos_np)
    dip_m.from_numpy(dip_mom_np)
    dip_s.from_numpy(np.zeros(N_DIP, dtype=np.float64))


# ═══════════════════════════════════════════════════════════════════════════
# MAIN SIMULATION LOOP
# ═══════════════════════════════════════════════════════════════════════════
_manual_ckpt_requested = False
def _sigusr1_handler(sig, frame):
    global _manual_ckpt_requested
    _manual_ckpt_requested = True
    print("\n  [SIGUSR1] Manual checkpoint requested.")
try:
    signal.signal(signal.SIGUSR1, _sigusr1_handler)
except (AttributeError, OSError):
    pass


def main():
    global colors_fixed, _manual_ckpt_requested, dip_str_np

    parser = argparse.ArgumentParser(
        description="REGO Phase 2 v31.3.0 — Sequential magnetic transport + shaping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
HOW TO RUN:
  Fresh start (recommended for first run):
      python phase2_clean_OKAY.py

  Resume an interrupted simulation (uses outputs/phase2_checkpoint.pkl):
      python phase2_clean_OKAY.py --resume

  Resume from a specific checkpoint file:
      python phase2_clean_OKAY.py --resume-from outputs/phase2_checkpoint.pkl

  Skip clustering and jump straight to transport:
      python phase2_clean_OKAY.py --skip-clustering
      (Automatically loads the latest checkpoint; if checkpoint is still in
       settle/cluster it fast-forwards to T_CLUSTER_END then stops. Re-run
       without the flag on the next invocation to continue from transport.)

  Skip straight to the shaping phase:
      python phase2_clean_OKAY.py --skip-to-shape
      (Loads outputs/shape_checkpoint.pkl if it exists — the real particle
       positions from end of transport. No --resume needed. If the shape
       checkpoint doesn't exist yet, run the full sim once first.)

  Disable checkpoint loading (always start fresh):
      python phase2_clean_OKAY.py --no-checkpoint

  Save checkpoints more frequently (e.g. every 0.5s sim-time):
      python phase2_clean_OKAY.py --resume --ckpt-interval 0.5

  Scale chi for lunar-realistic testing (FJS-1 simulant chi≈0.002):
      python phase2_clean_OKAY.py --chi-scale 0.01

PHASE SEQUENCE:
  settle(0.3s) → cluster(2.5s) → [transport+interlude]×4 → shape(20s) → hold(2.5s)

OUTPUT:
  VTK frames → outputs/Phase2/asm_NNNNNNN.vtu
  Animation  → outputs/Phase2/simulation.pvd  (open in ParaView)
  Checkpoint → outputs/phase2_checkpoint.pkl            (auto-saved every 1s)
  Shape ckpt → outputs/shape_checkpoint.pkl             (saved once at shape start)
  Diagnostics→ outputs/Phase2/diagnostics.png
""")
    parser.add_argument('--no-checkpoint',    action='store_true',
                        help='Ignore any existing checkpoint; always start from scratch.')
    parser.add_argument('--resume',           action='store_true',
                        help='Load outputs/phase2_checkpoint.pkl and continue.')
    parser.add_argument('--resume-from',      type=str, default=None,
                        help='Path to a specific .pkl checkpoint file to resume from.')
    parser.add_argument('--no-save',          action='store_true',
                        help='Disable all checkpoint and VTK output (dry run).')
    parser.add_argument('--ckpt-interval',    type=float, default=CKPT_INTERVAL,
                        help='Auto-checkpoint interval in sim-seconds (default 1.0).')
    parser.add_argument('--list-checkpoints', action='store_true',
                        help='List available checkpoint files and exit.')
    parser.add_argument('--checkpoint-now',   action='store_true',
                        help='Save a checkpoint immediately at the resume point, then continue.')
    parser.add_argument('--analyze-fields',   action='store_true',
                        help='Print cross-talk and hold-field analysis, then exit.')
    parser.add_argument('--chi-scale',        type=float, default=1.0,
                        help='Multiplier for chi (default 1.0=0.15; try 0.01 for FJS-1).')
    parser.add_argument('--skip-clustering',  action='store_true',
                        help='Auto-resume and jump past the clustering phase to transport. '
                             'Does not require --resume. If the checkpoint is still in '
                             'settle/cluster, fast-forwards to T_CLUSTER_END, saves, and stops.')
    parser.add_argument('--skip-to-shape',    action='store_true',
                        help='Jump directly to the shaping phase. Loads '
                             'outputs/shape_checkpoint.pkl (real particle positions from '
                             'end of transport) if it exists — no --resume needed. '
                             'Falls back to the regular checkpoint if shape ckpt is missing.')
    args, _ = parser.parse_known_args()

    if args.list_checkpoints:
        ckpts = list_checkpoints()
        if not ckpts:
            print("No checkpoints found.")
        else:
            for m_entry in ckpts:
                print(f"  {m_entry['path']}")
        return

    if args.analyze_fields:
        analyze_cross_talk()
        print("\n  ═══ HOLD FIELD VERIFICATION (v13.0 — unified single dipole) ═══")
        for k in range(4):
            tgt    = C.targets[k]
            normal = _target_normals[k]
            dip_pos = tgt + _d_lead * normal
            dip_mom = -_m_trap * normal

            offsets = [-1.0e-3, -0.5e-3, 0.0, 0.5e-3, 1.0e-3]
            B2_vals = []
            for off in offsets:
                r = tgt + off * normal
                B_v = _B_dipole_at(dip_pos, dip_mom, r)
                B2_vals.append(np.dot(B_v, B_v))

            print(f"    Target {k} ({['Top','Left','Right','Bot'][k]:>5s}):")
            for i, off in enumerate(offsets):
                marker = " ◄ TARGET" if i == 2 else ""
                print(f"      offset={off*1e3:+5.1f}mm  B²={B2_vals[i]:.3e}{marker}")
            grad_at_target = (B2_vals[3] - B2_vals[1]) / (1.0e-3)
            print(f"      ∇B² at target: {grad_at_target:.2e} T²/m (pulls toward dipole)")
        print()
        return

    # ── Apply chi scaling for lunar realism testing ──────────────────────
    if args.chi_scale != 1.0:
        C.chi *= args.chi_scale
        C.kelvin_pf = C.Vp * C.chi / (2 * MU0)
        print(f"  [chi-scale] chi reduced by {args.chi_scale}x: chi = {C.chi:.4e}")
        if args.chi_scale <= 0.05:
            # At very low chi, gradients need more headroom before clamping
            # (F14: GRAD_B2_CLAMP is now a ti.field, see its declaration)
            GRAD_B2_CLAMP[None] = 40.0
            print(f"  [chi-scale] GRAD_B2_CLAMP increased to {GRAD_B2_CLAMP[None]} for low-chi regime")

    print("=" * 72)
    print("  REGO Phase 2 -- Earnshaw-Compliant Sequential Plow v21.0")
    print("=" * 72)
    print(f"  N={C.N}  R={C.R*1e3:.3f}mm  rho={C.rho}kg/m3  g={C.g}m/s2")
    print(f"  m_p={C.mp:.4e}kg  W={C.W:.4e}N  chi={C.chi}")
    print(f"  dt={C.dt*1e6:.1f}us  N_DIP={N_DIP}")
    print(f"  Cylinder: R={C.cR*1e3:.2f}mm H={C.cH*1e3:.1f}mm")
    print(f"            z in [{C.z_lo*1e3:.1f},{C.z_hi*1e3:.1f}]mm")
    print(f"  param_hash={C.param_hash}  version={SIM_VERSION}")
    print(f"  Auto-checkpoint every {args.ckpt_interval:.1f}s sim-time")
    if args.chi_scale != 1.0:
        print(f"  chi_scale={args.chi_scale}  (effective chi={C.chi:.4e})")
    print()
    print("  v21.0 KEY CHANGES -- EARSNHAW-COMPLIANT SHAPING:")
    print(f"    Sequential active plow (one active shape dipole at a time)")
    print(f"    Active cluster keeps weak anchor during shaping (anti-chase)")
    print(f"    No mechanical-stop assumptions; no non-physical wall confinement")
    print(f"    Caps: spiral plow, Walls: lower-z vertical rake")
    print(f"    SHAPE_TIME={SHAPE_TIME:.1f}s")
    print(f"    Shape gradient clamp={SHAPE_MAX_GRAD_CLAMP:.1f} T²/m")
    print(f"    Shape dipoles EXTERNAL: {SHAPE_D_SURF*1e3:.1f}mm behind surface (realizable)")
    print(f"    SEQUENTIAL: one cluster at a time, order {SHAPE_ORDER}")
    print(f"    Each cluster: {SHAPE_TIME/4:.1f}s shaping")
    print(f"    Hold for inactive clusters (s=0.5), retention sweep for shaped (s=0.3)")
    print(f"    Transport: CLOSED-LOOP liftoff/lift/cruise/brake/settle (Stage A-4, real pos+vel feedback)")
    print(f"      EPS_X={EPS_X*1e3:.3f}mm  EPS_V={EPS_V*1e3:.1f}mm/s  V_CEIL={V_CEIL*1e3:.1f}mm/s  "
          f"D_BRAKE_TRIGGER={D_BRAKE_TRIGGER*1e3:.3f}mm  STALL_TIMEOUT={STALL_TIMEOUT:.1f}s")
    print(f"      [Stage A-3, F17 fix] Z_LIFTOFF_CONFIRM={Z_LIFTOFF_CONFIRM*1e3:.4f}mm  "
          f"LIFT_CLEARANCE={LIFT_CLEARANCE*1e3:.2f}mm  LIFT_DWELL={LIFT_DWELL:.2f}s  "
          f"LIFTOFF_STALL_TIMEOUT={LIFTOFF_STALL_TIMEOUT:.1f}s")
    print(f"      [Stage A-4, F18 fix] deadbeat vertical+horizontal channels, CTRL_DT_NOMINAL="
          f"{CTRL_DT_NOMINAL*1e3:.1f}ms, single dipole at fixed standoff _d_lead={_d_lead*1e3:.2f}mm")
    print(f"    --chi-scale {args.chi_scale} (chi={C.chi:.4e})")
    print(f"    Energy tracking: coil I^2*R diagnostic for lunar power budget")
    print()
    print("  FIELD ARCHITECTURE (v19.0):")
    print(f"    Corner quadrupoles:    8 dipoles (4 anti-aligned pairs)")
    print(f"    Per-cluster dipole:    1 x 4 (transport + hold)")
    print(f"    Hold ring (DISABLED):  8 dipoles (always strength=0)")
    print(f"    Shape (per cluster):   1 external comb-rake dipole (m={_m_shape:.4f})")
    print(f"    Total:                {N_DIP} dipoles")
    print()
    print("  PHASE SEQUENCE:")
    print("    settle → cluster → [transport → interlude] ×4 → shape → hold → done")
    print()

    analyze_cross_talk()

    out_dir = Path("outputs") / "Phase2"
    out_dir.mkdir(parents=True, exist_ok=True)

    pm = PhaseManager()
    checkpoint_loaded = False
    start_step = 0; start_t = 0.0
    pvd = []; ht = []; hke = []; hfm = []; hspread = []
    last_auto_ckpt_t = -999.0
    shape_ckpt_saved = False   # becomes True after shape checkpoint is written once
    _last_shape_diag_t = -999.0  # throttle for cap-shaping per-cluster diagnostics
    total_energy_J = 0.0       # v19: accumulated I^2*R energy (Joules)

    if not args.no_checkpoint:
        load_path = args.resume_from

        # ── --skip-to-shape: shape checkpoint is a SEPARATE file; try it first,
        # independently of whether --resume was passed or a regular checkpoint exists.
        if args.skip_to_shape and not checkpoint_loaded:
            shape_ok, shape_data = load_shape_checkpoint()
            if shape_ok:
                init()
                start_step, start_t, pvd, ht, hke, hfm, hspread = \
                    restore_from_checkpoint(shape_data, pm)
                checkpoint_loaded = True
                last_auto_ckpt_t = start_t
                pm.completed    = {0, 1, 2, 3}
                pm.state        = "shape"
                pm.phase_start_t = start_t
                pm.arrived_t    = None
                pm.handoff_t    = None
                vel.from_numpy(np.zeros((C.N, 3), dtype=np.float64))
                if not colors_fixed:
                    assign_centres.from_numpy(C.qc_3d)
                    assign_clusters_initial()
                    fix_colors()
                    colors_fixed = True
                dummy_centroids = {k: C.targets[k].copy() for k in range(4)}
                update_dipoles(start_t, pm, dummy_centroids)
                shape_ckpt_saved = True
                print(f"  [skip-to-shape] ✓ Restored from shape checkpoint "
                      f"at t={start_t:.3f}s — shape will run full {SHAPE_TIME:.1f}s")
            else:
                print(f"  [skip-to-shape] No shape checkpoint found at {SHAPE_CKPT_FILE}")
                print(f"  [skip-to-shape] Run the full simulation once (no flags) to generate it,")
                print(f"  [skip-to-shape] then re-run with --skip-to-shape.")

        # ── Regular checkpoint resume (--resume / --resume-from / --skip-clustering) ──
        # --skip-clustering implicitly enables resume (needs a post-cluster checkpoint)
        do_resume = args.resume or (load_path is not None) or args.skip_clustering
        if do_resume and not checkpoint_loaded:
            ok, ckpt_data = load_checkpoint(path=load_path, latest=(load_path is None))
            if ok:
                init()
                start_step, start_t, pvd, ht, hke, hfm, hspread = \
                    restore_from_checkpoint(ckpt_data, pm)
                checkpoint_loaded = True
                last_auto_ckpt_t = start_t

                # ── --skip-clustering ──
                if args.skip_clustering:
                    if pm.state in ("settle", "cluster"):
                        print(f"  [skip-clustering] Checkpoint at phase={pm.state} t={start_t:.2f}s.")
                        print(f"  [skip-clustering] Will fast-forward to t≥{T_CLUSTER_END}s, "
                              f"save 'post-cluster', then stop.")
                        print(f"  [skip-clustering] Re-run without --skip-clustering to continue.")
                    elif pm.state.startswith(("transport", "interlude", "shape", "hold")):
                        print(f"  [skip-clustering] Checkpoint already past clustering "
                              f"(phase={pm.state} t={start_t:.2f}s). Proceeding.")

                # ── --skip-to-shape fallback: shape checkpoint not found, use regular ──
                if args.skip_to_shape and not shape_ckpt_saved:
                    print(f"  [skip-to-shape] Using regular checkpoint at t={start_t:.2f}s "
                          f"(phase={pm.state}). Forcing to shape phase.")
                    pm.completed    = {0, 1, 2, 3}
                    pm.state        = "shape"
                    pm.phase_start_t = start_t
                    pm.arrived_t    = None
                    pm.handoff_t    = None
                    vel.from_numpy(np.zeros((C.N, 3), dtype=np.float64))
                    if not colors_fixed:
                        assign_centres.from_numpy(C.qc_3d)
                        assign_clusters_initial()
                        fix_colors()
                        colors_fixed = True
                    dummy_centroids = {k: C.targets[k].copy() for k in range(4)}
                    update_dipoles(start_t, pm, dummy_centroids)
                    shape_ckpt_saved = True
                    print(f"  [skip-to-shape] ✓ Shape phase started at t={start_t:.2f}s "
                          f"(WARNING: particle positions may not be at transport targets)")

                print(f"  Resuming from step={start_step} t={start_t:.3f}s  "
                      f"phase={pm.state}  {len(pvd)} frames already saved")
            else:
                print("  No valid checkpoint found — running from scratch.")
        elif not checkpoint_loaded and not args.skip_to_shape:
            pass  # fresh start handled below

    if not checkpoint_loaded:
        init()

    ckpt_interval = float(args.ckpt_interval)
    do_save = not args.no_save

    if not checkpoint_loaded:
        dummy_centroids = {k: C.qc_3d[k].copy() for k in range(4)}
        update_dipoles(2.0, pm, dummy_centroids)
        build_grid(); compute_forces()
        fm_np = fmag.to_numpy()
        fm_m  = np.linalg.norm(fm_np, axis=1)
        print(f"  [Diag t=2.0] max|Fm|={np.max(fm_m)/C.W:.1f}×W  "
              f"mean={np.mean(fm_m)/C.W:.1f}×W")
        dip_s.from_numpy(np.zeros(N_DIP, dtype=np.float64))

    # Account for interludes in time estimate. Uses STALL_TIMEOUT (the
    # worst-case per-transport ceiling) rather than the ~1.2-1.6s normally
    # expected from the closed-loop controller, so this stays a safe upper
    # bound for n_steps_max even if a transport genuinely stalls.
    t_max_est = (T_CLUSTER_END + 4*STALL_TIMEOUT + 3*INTERLUDE_TIME
                 + SHAPE_TIME + HOLD_TIME + 1.0)
    n_steps_max = int(t_max_est / C.dt)
    out_every   = max(1, int(C.out_dt / C.dt))

    t0w = _time.time()
    print(f"\n  Max estimated sim-time: {t_max_est:.1f}s ({n_steps_max} steps)")
    print(f"  Starting from step {start_step}, t={start_t:.3f}s")
    print(f"  Batch sizes: transport={200} steps (400µs), static={500} steps (1ms)")
    print(f"  GPU→CPU sync: only during transport + output steps (20× reduction)")
    print(f"  (Ctrl+C to interrupt safely | SIGUSR1 for manual checkpoint)\n")

    if args.checkpoint_now:
        save_checkpoint(start_step, start_t, pm, pvd, ht, hke, hfm, hspread,
                        label="manual-t0")

    try:
        step = start_step

        # ── ADAPTIVE BATCH SIZES ───────────────────────────────────────
        # v13.1: Increased batch sizes for performance.
        # Transport: dipole follows centroid, needs frequent updates.
        #   2000 steps = 16ms. At v_cap=7mm/s, cluster moves 0.11mm/batch.
        #   d_lead=0.3mm → position lag is ~1/3 of lead distance. Safe.
        # Static: dipoles are fixed or ramping slowly. Very safe.
        BATCH_TRANSPORT = 2000   # v13.1: larger batches
        BATCH_STATIC    = 8000   # v13.1: larger batches

        # Track last known centroids so dipole update always has a value
        centroids = {k: C.qc_3d[k].copy() for k in range(4)}
        # Stage A-2: real per-cluster mean velocity, needed by the closed-loop
        # transport controller (see "CLOSED-LOOP TRANSPORT CONTROLLER").
        velocities = {k: np.zeros(3) for k in range(4)}

        while True:
            t = step * C.dt

            # ── Fix cluster colors at end of clustering ───────────────
            if not colors_fixed and t >= T_CLUSTER_END:
                assign_centres.from_numpy(C.qc_3d)
                assign_clusters_initial()
                fix_colors()
                colors_fixed = True
                print(f"  *** Cluster colors FIXED at t={t:.2f}s ***")
                # Force centroid readback now so transport starts with good values
                p_np  = pos.to_numpy()
                cl_np = cluster_id.to_numpy()
                centroids = {k: get_cluster_centroid_np(p_np, cl_np, k) for k in range(4)}
                if do_save:
                    save_checkpoint(step, t, pm, pvd, ht, hke, hfm, hspread,
                                    label="post-cluster")
                    last_auto_ckpt_t = t
                    # Diagnostic-only: keep an UN-overwritten copy of the
                    # post-cluster checkpoint (the rotating CKPT_FILE gets
                    # clobbered by the next auto-save ~1s of sim-time later)
                    # so repeated F18-diagnosis runs can --resume-from it
                    # instead of re-running the ~14min clustering phase each
                    # time. Not part of the physics or the normal
                    # save/resume mechanism.
                    try:
                        import shutil as _shutil
                        _shutil.copyfile(str(CKPT_FILE),
                                          str(CKPT_DIR / "phase2_checkpoint_postcluster_diag.pkl"))
                    except Exception:
                        pass
                # ── --skip-clustering: stop here so next run starts transport ──
                if args.skip_clustering:
                    print(f"\n  [skip-clustering] Clustering complete at t={t:.2f}s.")
                    print(f"  [skip-clustering] Checkpoint saved as 'post-cluster'.")
                    print(f"  [skip-clustering] Re-run WITHOUT --skip-clustering to continue.")
                    break

            # ── Determine if this is an active transport step ─────────
            is_transport_active = pm.state.startswith("transport_")

            # ── Centroid readback (only when needed) ──────────────────
            # During transport: read every batch to keep leading dipole current.
            # During all other phases: skip the GPU sync entirely.
            # Centroids are always read at output steps (cluster_stats does it).
            if is_transport_active:
                # GPU→CPU sync to get current particle positions AND velocities.
                # Stage A-2: the closed-loop transport controller needs real
                # velocity feedback, not just position — see "CLOSED-LOOP
                # TRANSPORT CONTROLLER". vel already exists as a real Taichi
                # field (used every step by integrate()); this just reads it.
                if colors_fixed:
                    apply_fixed_colors()
                else:
                    assign_centres.from_numpy(C.qc_3d)
                    assign_clusters_initial()
                p_np  = pos.to_numpy()
                v_np  = vel.to_numpy()
                cl_np = cluster_id.to_numpy()
                centroids  = {k: get_cluster_centroid_np(p_np, cl_np, k) for k in range(4)}
                velocities = {k: get_cluster_velocity_np(v_np, cl_np, k) for k in range(4)}

            # ── Phase manager update (uses cached centroids when static) ──
            pm.update(t, centroids, velocities)

            # ── Shape checkpoint — saved exactly once when shape phase begins ──
            # This gives --skip-to-shape a real particle state to restore from,
            # instead of relying on a guessed timestamp.
            if do_save and not shape_ckpt_saved and pm.state == "shape":
                save_shape_checkpoint(step, t, pm, pvd, ht, hke, hfm, hspread)
                shape_ckpt_saved = True

            # ── Termination ───────────────────────────────────────────
            if pm.is_done(t):
                print(f"\n  *** All phases complete at t={t:.2f}s ***")
                if do_save:
                    save_checkpoint(step, t, pm, pvd, ht, hke, hfm, hspread,
                                    label="final")
                break
            if step > start_step + n_steps_max:
                print(f"\n  *** Max steps reached at t={t:.2f}s ***")
                if do_save:
                    save_checkpoint(step, t, pm, pvd, ht, hke, hfm, hspread,
                                    label="maxstep")
                break

            # ── Auto-checkpoint ───────────────────────────────────────
            if do_save and (t - last_auto_ckpt_t) >= ckpt_interval:
                save_checkpoint(step, t, pm, pvd, ht, hke, hfm, hspread,
                                label="auto")
                last_auto_ckpt_t = t

            # ── Manual checkpoint via SIGUSR1 ─────────────────────────
            if _manual_ckpt_requested:
                save_checkpoint(step, t, pm, pvd, ht, hke, hfm, hspread,
                                label="manual")
                _manual_ckpt_requested = False

            # ── Adaptive batch size ────────────────────────────────────
            # v16: Shape needs small batches for smooth dipole scanning.
            # At ω=7.85 rad/s, r=1.67mm: azimuthal speed=13mm/s
            # At 500 steps × 8µs = 4ms: dipole moves 0.05mm per batch.
            is_shape_active = pm.state == "shape"
            if is_transport_active:
                BATCH_SIZE = BATCH_TRANSPORT
            elif is_shape_active:
                BATCH_SIZE = SHAPE_BATCH_SIZE
            else:
                BATCH_SIZE = BATCH_STATIC
            # Snap to output boundary so we never skip an output step.
            steps_to_output = out_every - (step % out_every)
            actual_batch = min(BATCH_SIZE, steps_to_output,
                               start_step + n_steps_max - step)
            actual_batch = max(actual_batch, 1)

            # ── Dipole update (once per batch, using cached centroids) ─
            update_dipoles(t, pm, centroids, velocities)

            # F18 diagnostic (Stage A-3): real per-control-step LIFT/CRUISE
            # state for cluster 0, gated behind DEBUG_LIFT_CRUISE=1.
            if _dbg_lift_cruise and is_transport_active:
                _debug_lift_cruise_snapshot(t, pm, centroids[_DBG_CLUSTER], velocities[_DBG_CLUSTER], p_np, cl_np)

            # ── Batched physics (no Python overhead inside) ────────────
            substep_batch(actual_batch)
            step += actual_batch

            # ── Output (only when we've reached an output step) ───────
            if step % out_every == 0:
                if colors_fixed:
                    apply_fixed_colors()
                else:
                    assign_centres.from_numpy(C.qc_3d)
                    assign_clusters_initial()

                # On-device stats: no extra to_numpy() for vel/fmag
                compute_stats()
                ke     = float(_ke_field[None])
                fm_max = float(_fm_field[None])
                vm     = float(_vm_field[None])

                cs     = cluster_stats()   # calls pos.to_numpy() internally
                sp     = [cs[k][4] for k in range(4) if cs[k][0] > 0]
                avg_sp = float(np.mean(sp)) if sp else 0

                # Refresh centroids from cluster_stats output (mm → m)
                # This keeps the dist_str display accurate and ensures the
                # next batch of transport dipole updates starts from current data.
                for k in range(4):
                    n_k, cx_k, cy_k, cz_k, _ = cs[k]
                    if n_k > 0:
                        centroids[k] = np.array([cx_k*1e-3, cy_k*1e-3, cz_k*1e-3])

                ht.append(t); hke.append(ke); hfm.append(fm_max)
                hspread.append(avg_sp)

                # v19: Energy tracking — accumulate I^2*R for all active dipoles.
                # Each dipole represents a coil with m = N_turns * I * A_coil.
                # I = (m * strength) / (N_turns * A_coil), P = I^2 * R_coil.
                # Accumulated over the output interval (out_dt seconds).
                batch_power = 0.0
                for di in range(N_DIP):
                    s_di = dip_str_np[di]
                    if s_di > 1e-6:
                        m_eff = np.linalg.norm(dip_mom_np[di]) * s_di
                        I_coil = m_eff / (COIL_N_TURNS * COIL_AREA)
                        batch_power += I_coil * I_coil * COIL_R_OHM
                total_energy_J += batch_power * C.out_dt

                fn = f"asm_{step:07d}.vtu"
                write_vtu(out_dir / fn)
                pvd.append((fn, t))

                elapsed = _time.time() - t0w
                rate    = (step - start_step + 1) / elapsed if elapsed > 0 else 1
                eta_s   = (n_steps_max - (step - start_step)) / rate \
                          if rate > 0 else 0
                ph      = pm.get_phase_label()

                ac = pm.get_active_cluster()
                dist_str = ""
                if ac >= 0:
                    dist = np.linalg.norm(centroids[ac] - C.targets[ac]) * 1e3
                    dist_str = f"d={dist:.2f}mm "

                n_active_dip = int(np.sum(dip_str_np > 0.01))

                print(f"  t={t:6.2f}s [{ph:>7s}]  "
                      f"KE={ke:.2e} |Fm|={fm_max/C.W:6.1f}W "
                      f"vm={vm:.2e} sp={avg_sp:.3f}mm {dist_str}"
                      f"dip={n_active_dip:2d}/{N_DIP}  "
                      f"Q:{cs[0][0]:3d} {cs[1][0]:3d} {cs[2][0]:3d} {cs[3][0]:3d}  "
                      f"z=({cs[0][3]:.1f},{cs[1][3]:.1f},{cs[2][3]:.1f},{cs[3][3]:.1f})  "
                      f"ETA {eta_s:5.0f}s")

                # ── Cap-cluster shape diagnostics every 2 sim-seconds ────────
                if pm.state == "shape" and t - _last_shape_diag_t >= 2.0:
                    _last_shape_diag_t = t
                    _d_np = pos.to_numpy()
                    _v_np = vel.to_numpy()
                    _c_np = cluster_id.to_numpy()
                    for _ck, _cn, _zt in ((0, "TOP", C.z_hi*1e3),
                                          (3, "BOT", C.z_lo*1e3)):
                        _idx = np.where(_c_np == _ck)[0]
                        if len(_idx) == 0: continue
                        _rx = (_d_np[_idx, 0] - C.cx) * 1e3
                        _ry = (_d_np[_idx, 1] - C.cy) * 1e3
                        _r  = np.sqrt(_rx**2 + _ry**2)
                        _vn = np.sqrt(np.sum(_v_np[_idx]**2, axis=1))
                        _z  = _d_np[_idx, 2] * 1e3
                        # sub-cluster count: DBSCAN-lite — count connected components
                        # with epsilon = 4×R = 0.12mm (touching threshold)
                        _eps = 4 * C.R * 1e3  # mm
                        _xy = np.stack([_rx, _ry], axis=1)
                        _labels = np.full(len(_idx), -1, dtype=int)
                        _cid_next = 0
                        for _pi in range(len(_idx)):
                            if _labels[_pi] >= 0: continue
                            _labels[_pi] = _cid_next
                            _stack = [_pi]
                            while _stack:
                                _ci = _stack.pop()
                                for _pj in range(len(_idx)):
                                    if _labels[_pj] >= 0: continue
                                    if np.linalg.norm(_xy[_ci] - _xy[_pj]) < _eps:
                                        _labels[_pj] = _cid_next
                                        _stack.append(_pj)
                            _cid_next += 1
                        _n_subclusters = _cid_next
                        print(f"    [{_cn}] r∈[{_r.min():.3f},{_r.max():.3f}]mm "
                              f"μ={_r.mean():.3f}mm σ={_r.std():.3f}mm  "
                              f"z∈[{_z.min():.3f},{_z.max():.3f}]mm tgt={_zt:.2f}  "
                              f"v_μ={_vn.mean()*1e3:.3f}mm/s  "
                              f"subclusters={_n_subclusters}")

                if math.isnan(ke) or math.isinf(ke):
                    print("  !!! INSTABILITY DETECTED !!!")
                    if do_save:
                        save_checkpoint(step, t, pm, pvd, ht, hke, hfm, hspread,
                                        label="instability")
                    break

    except KeyboardInterrupt:
        print("\n\n  *** INTERRUPTED — saving emergency checkpoint ***\n")
        if do_save:
            save_checkpoint(step, step*C.dt, pm, pvd, ht, hke, hfm, hspread,
                            label="interrupt")

    # ── Write PVD ──────────────────────────────────────────────────────
    if pvd:
        write_pvd(out_dir / "simulation.pvd", pvd)
        print(f"\n  Saved {len(pvd)} frames → {out_dir}/simulation.pvd")

    total = _time.time() - t0w

    # ── Final cluster report ────────────────────────────────────────────
    if pvd:
        cs = cluster_stats()
        print(f"\n  FINAL CLUSTER POSITIONS:")
        total_dist = 0.0
        for k in range(4):
            n, cx_r, cy_r, cz_r, sp = cs[k]
            tx, ty, tz = C.targets[k] * 1e3
            dist = math.sqrt((cx_r-tx)**2 + (cy_r-ty)**2 + (cz_r-tz)**2)
            total_dist += dist
            status = "✓" if dist < 1.0 else "✗"
            print(f"    Q{k}: {n:3d} particles  pos=({cx_r:.2f},{cy_r:.2f},{cz_r:.2f})mm  "
                  f"tgt=({tx:.1f},{ty:.1f},{tz:.1f})mm  d={dist:.2f}mm  "
                  f"sp={sp:.3f}mm  [{status}]")
        print(f"    Total distance error: {total_dist:.2f}mm")

        # Cylinder conformity check
        print(f"\n  CYLINDER CONFORMITY CHECK:")
        p_final = pos.to_numpy()
        cl_final = cluster_id.to_numpy()
        for k in range(4):
            mask = cl_final == k
            if not np.any(mask):
                continue
            pp = p_final[mask]
            r_from_axis = np.sqrt((pp[:,0]-C.cx)**2 + (pp[:,1]-C.cy)**2)
            z_vals = pp[:,2]
            in_z = np.sum((z_vals >= C.z_lo - 2*C.R) & (z_vals <= C.z_hi + 2*C.R))
            on_wall = np.sum((np.abs(r_from_axis - C.cR) < 5*C.R) &
                            (z_vals >= C.z_lo) & (z_vals <= C.z_hi))
            on_cap  = np.sum((r_from_axis < C.cR + 3*C.R) &
                            ((np.abs(z_vals - C.z_lo) < 5*C.R) |
                             (np.abs(z_vals - C.z_hi) < 5*C.R)))
            role = ["top cap", "left wall", "right wall", "bottom cap"][k]
            print(f"    Q{k} ({role:>10s}): {int(np.sum(mask)):3d} particles  "
                  f"in_z_range={in_z:3d}  on_wall={on_wall:3d}  on_cap={on_cap:3d}  "
                  f"r_mean={np.mean(r_from_axis)*1e3:.2f}mm  "
                  f"z_mean={np.mean(z_vals)*1e3:.2f}mm")

        # v19: Energy budget report
        print(f"\n  ENERGY BUDGET (coil I^2*R dissipation):")
        print(f"    Total energy: {total_energy_J:.3f} J")
        print(f"    Lunar budget (10 J): {'PASS' if total_energy_J < 10.0 else 'FAIL'}")
        if total_energy_J > 0 and total > 0:
            avg_power = total_energy_J / (step * C.dt) if step > 0 else 0
            print(f"    Average power: {avg_power:.3f} W")

    # ── Diagnostic plots ────────────────────────────────────────────────
    if ht and len(ht) > 0:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, axs = plt.subplots(2, 3, figsize=(16, 9), tight_layout=True)
            fig.suptitle("Phase 2 — Fixed Transport + Hold v4.0", fontsize=14,
                         fontweight='bold')
            T = np.array(ht)

            axs[0,0].semilogy(T, np.maximum(np.array(hke)*1e6, 1e-30), 'b-')
            axs[0,0].set(xlabel='t (s)', ylabel='KE (µJ)', title='Kinetic Energy')
            axs[0,0].grid(True)

            axs[0,1].plot(T, np.array(hfm)/C.W, 'r-')
            axs[0,1].set(xlabel='t (s)', ylabel='|Fm|/W', title='Max Magnetic Force')
            axs[0,1].grid(True)

            axs[0,2].plot(T, hspread, 'g-')
            axs[0,2].set(xlabel='t (s)', ylabel='spread (mm)',
                         title='Avg Cluster Spread')
            axs[0,2].grid(True)

            p_np = pos.to_numpy(); cl_np = cluster_id.to_numpy()
            cols = ['#e74c3c','#3498db','#2ecc71','#f39c12']
            for k in range(4):
                mask = cl_np == k
                if np.any(mask):
                    axs[1,0].scatter(p_np[mask,0]*1e3, p_np[mask,1]*1e3,
                                     s=4, c=cols[k], label=f'Q{k}')
            th_arr = np.linspace(0, 2*PI, 100)
            axs[1,0].plot(C.cx*1e3+C.cR*1e3*np.cos(th_arr),
                          C.cy*1e3+C.cR*1e3*np.sin(th_arr), 'k--', lw=1)
            axs[1,0].set(xlabel='x (mm)', ylabel='y (mm)', title='XY Final',
                         xlim=[0,10], ylim=[0,10], aspect='equal')
            axs[1,0].legend(fontsize=6); axs[1,0].grid(True)

            for k in range(4):
                mask = cl_np == k
                if np.any(mask):
                    axs[1,1].scatter(p_np[mask,0]*1e3, p_np[mask,2]*1e3,
                                     s=4, c=cols[k], label=f'Q{k}')
            axs[1,1].axhline(C.z_lo*1e3, c='k', ls='--', lw=0.5)
            axs[1,1].axhline(C.z_hi*1e3, c='k', ls='--', lw=0.5)
            axs[1,1].set(xlabel='x (mm)', ylabel='z (mm)', title='XZ Final',
                         xlim=[0,10], ylim=[0,10])
            axs[1,1].legend(fontsize=6); axs[1,1].grid(True)

            axs[1,2].axis('off')
            cs = cluster_stats()
            txt = "FINAL POSITIONS:\n\n"
            for k in range(4):
                n, cx_r, cy_r, cz_r, sp = cs[k]
                tx, ty, tz = C.targets[k]*1e3
                d = math.sqrt((cx_r-tx)**2+(cy_r-ty)**2+(cz_r-tz)**2)
                txt += (f"Q{k}: ({cx_r:.1f},{cy_r:.1f},{cz_r:.1f})mm\n"
                        f"    tgt=({tx:.1f},{ty:.1f},{tz:.1f})  d={d:.2f}mm\n"
                        f"    n={n}  spread={sp:.3f}mm\n\n")
            txt += f"Sim time: {total:.1f}s wall clock\ndt={C.dt*1e6:.1f}µs\n"
            txt += f"Completed: {sorted(pm.completed)}\nFinal: {pm.state}\n"
            txt += f"N_DIP: {N_DIP} (v4.0 fixed)\n"
            axs[1,2].text(0.05, 0.95, txt, transform=axs[1,2].transAxes,
                          va='top', fontsize=8, family='monospace')

            plt.savefig(out_dir / "diagnostics.png", dpi=150)
            print(f"\n  Plots → {out_dir}/diagnostics.png")
        except Exception as e:
            print(f"  Plotting failed: {e}")

    print("\n" + "="*72)
    print("  v30.0 TILTED-RING CAP + FULL-BELT WALL SHAPING:")
    print("")
    print("  ARCHITECTURE CHANGES (v30 vs v29):")
    print("  [NEW] CAP SHAPING — Tilted-Moment External Ring (N=8 dipoles):")
    print("        v29 used purely radial moments → Bz=0 on cap plane →")
    print("        zero intrinsic z-restoring → particles fell as they spread.")
    print("        New: tilted moments = cos_tilt*(-rhat) + sin_tilt*nhat_cap")
    print("        sin_tilt component creates ∂B²/∂z ≠ 0 → ring dipoles provide")
    print("        z-restoring force INTRINSICALLY. Hold pair supplemental.")
    print(f"        cos_tilt={CAP_MOMENT_COS_TILT:.2f} (radial spread), "
          f"sin_tilt={CAP_MOMENT_SIN_TILT:.2f} (z-pin)")
    print("")
    print("  [NEW] WALL SHAPING — Full Cylindrical Belt (N=8×2=16 dipoles):")
    print("        v29 used vertical rake sweeping ±45° (90° arc total).")
    print("        Particles outside 90° arc felt NO radial pull → stayed inside.")
    print("        New: N_WALL_BELT=8 dipoles uniformly in full 2π azimuth at")
    print("        N_WALL_Z_LEVELS=2 heights. STATIC — no sweep needed.")
    print("        Complete radially-inward B² attractor around entire cylinder.")
    print("        Every particle pulled to r=cR regardless of azimuth. ✓")
    print("")
    print("  [STALE] The block above (v30 architecture: tilted-moment cap ring,")
    print("          full-belt wall shaping) describes an EARLIER design than what")
    print("          actually runs (v33-v36: caps use no active shape dipole; walls")
    print("          use a single scanning dipole). See CONTEXT.md sec 18 for the")
    print("          Stage A audit and current status; not rewritten here to keep")
    print("          this diff bounded to correctness fixes.")
    print(f"  [FIXED, Stage A] CAP hold ring (IDX_HOLD_A/B) is now PERMANENTLY OFF —")
    print(f"          it was 2 point attractors, not a symmetric ring (finding F4).")
    print("  [KEPT] CAP cluster dipoles PARKED at z=-5mm (s=0).")
    print("  [KEPT] WALL z-lift: cluster dipole below target, moment +z.")
    print("  [KEPT] All sources EXTERNAL to simulation box.")
    print("  [KEPT] No wall/surface mechanical boundaries (surf_conf is a labeled")
    print("         non-physical placeholder — see CONTEXT.md sec 18.2).")
    print("")
    print("  FIELD PARAMETERS (Stage A recalibration, see CONTEXT.md sec 18):")
    print(f"  [OK]  SHAPE_MAX_GRAD_CLAMP = {SHAPE_MAX_GRAD_CLAMP:.0f} T^2/m (numerical guard, F6/F7/F14)")
    print(f"  [OK]  SHAPE_TIME = {SHAPE_TIME:.1f}s  ({SHAPE_TIME/4:.1f}s/cluster, order {SHAPE_ORDER})")
    print(f"  [OK]  Energy diagnostic: {total_energy_J:.3f} J total I^2*R dissipation")
    print(f"  [OK]  All forces: F = (Vp*chi_eff/2mu0)*grad(B^2) + DMT cohesion (F11) - no hacks")
    print("="*72 + "\n")


if __name__ == "__main__":
    main()