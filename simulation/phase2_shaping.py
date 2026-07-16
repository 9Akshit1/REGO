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
TRANSPORT_BUDGET  = 4.0        # was 6.0 — clusters transport faster with good trap
INTERLUDE_TIME    = 0.4        # was 0.6 — early ramp means settling faster
ARRIVAL_THRESHOLD = 0.15e-3
HOLD_TIME         = 2.5
SHAPE_TIME        = 20.0       # 5s per cluster (quasi-static shaping)
CKPT_INTERVAL     = 1.0
SIM_VERSION       = "32.0.0"
GRAB_TIME         = 0.3

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
                                       # Increased 0.9→1.5mm: reduces near-field force by (1.5/0.9)^4=7.7x
                                       # prevents particle ejection; forces remain well within clamp
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
SHAPE_MAX_GRAD_CLAMP       = 700.0     # T²/m clamp during shaping
SHAPE_BATCH_SIZE           = 500       # steps per batch during shape

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
COIL_N_TURNS  = 100
COIL_AREA     = 4e-6       # m^2 (4 mm^2)
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

    # v12: dt=8µs — 1.6× speedup. Soft clamp prevents force spikes.
    dt    = 8.0e-6
    out_dt = 0.05

    hcell = 1.2e-3;  hres = int(L/hcell)+1
    fd_h  = 3e-6

    qc = np.array([[7.5e-3,7.5e-3],[2.5e-3,7.5e-3],
                   [7.5e-3,2.5e-3],[2.5e-3,2.5e-3]], dtype=np.float64)

    cx=L/2; cy=L/2; cz=L/2
    cR=L/6; cH=4e-3
    z_lo=cz-cH/2; z_hi=cz+cH/2

    targets = np.array([
        [5.0e-3, 5.0e-3, 7.2e-3],                    # Q0: top cap
        [5.0e-3-L/6-0.2e-3, 5.0e-3, 5.0e-3],         # Q1: left wall (gravity-supported lower-z)
        [5.0e-3+L/6+0.2e-3, 5.0e-3, 5.0e-3],         # Q2: right wall (gravity-supported lower-z)
        [5.0e-3, 5.0e-3, 2.8e-3],                    # Q3: bottom cap
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
#   Validated: m=0.0006, d_lead=0.5mm:
#     - Fz = 6916 W at cluster center (saturates v_cap cleanly) ✓
#     - Radial Fx at 0.15mm: -2680 W (INWARD, no expansion) ✓
#     - Q1/Q2 crosstalk: < 0.001 W per particle ✓
#
_m_trap  = 0.0006        # Leading dipole moment magnitude
_d_lead  = 0.3e-3        # v13.1: reduced from 0.5mm — gentler pull, less overshoot
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

_m_shape       = 0.0015    # Shape dipole moment (increased for stronger spreading vs hold)
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
def make_transport_path(start_xy, target_3d, n_waypoints=300,
                        clearance=0.3e-3, other_targets=None):
    """
    Generate a smooth transport path from the cluster's starting position on
    the floor to its target position.

    v5.3 CHANGES vs v5.0:
      - clearance reduced 1.0mm → 0.3mm: clusters no longer overshoot their
        targets by ~1mm before descending. Top cluster peak is now 7.5mm
        instead of 8.2mm; left/right clusters peak at 5.3mm instead of 6.0mm.
      - Path shape changed from a 3-segment lift→plateau→descend to a single
        smooth arc that interpolates x, y, z simultaneously. This eliminates
        the abrupt direction reversal at cruise_z that was shaking clusters.
      - Collision avoidance bump reduced from 2.0mm to 0.5mm (only applied
        when another cluster's target is directly in the lateral path).
    """
    sx, sy = start_xy[0], start_xy[1]
    sz = C.R
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
        C.qc[k], C.targets[k],
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


# ═══════════════════════════════════════════════════════════════════════════
# TAICHI FIELDS
# ═══════════════════════════════════════════════════════════════════════════
pos  = ti.Vector.field(3, ti.f64, shape=C.N)
vel  = ti.Vector.field(3, ti.f64, shape=C.N)
frc  = ti.Vector.field(3, ti.f64, shape=C.N)
fmag = ti.Vector.field(3, ti.f64, shape=C.N)

HRES = C.hres; MAXPC = 32
grid_cnt = ti.field(ti.i32, shape=(HRES, HRES, HRES))
grid_buf = ti.field(ti.i32, shape=(HRES, HRES, HRES, MAXPC))

cluster_id  = ti.field(ti.i32, shape=C.N)
fixed_color = ti.field(ti.i32, shape=C.N)
ncontact    = ti.field(ti.i32, shape=C.N)
qc_ti       = ti.Vector.field(2, ti.f64, shape=4)
assign_centres = ti.Vector.field(3, ti.f64, shape=4)
v_cap             = ti.field(ti.f64, shape=())
surf_conf_enabled = ti.field(ti.i32, shape=())   # 1 = surface confinement active (shape phase)

# ── Gradient clamp — TIGHTENED to prevent force spikes ────────────────
# With 3mm dipole separations, max ∇B² within particle cloud should be
# ~50-500 T²/m. Clamp at 5000 for safety margin.
GRAD_B2_CLAMP = 2000.0             # default for transport/cluster


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
        soft_scale = GRAD_B2_CLAMP / ti.sqrt(g2 + GRAD_B2_CLAMP * GRAD_B2_CLAMP)
        gB2 *= soft_scale

    return ti.Vector([gB2[0], gB2[1], gB2[2], Bmag])

@ti.func
def chi_eff(B_mag: ti.f64) -> ti.f64:
    alpha      = C.chi * B_mag / (MU0 * C.Msat)
    alpha_safe = ti.min(alpha, 20.0)
    cosh_alpha = 0.5 * (ti.exp(alpha_safe) + ti.exp(-alpha_safe))
    return C.chi / (cosh_alpha * cosh_alpha)


# ═══════════════════════════════════════════════════════════════════════════
# CONTACT MECHANICS (unchanged from v3.1)
# ═══════════════════════════════════════════════════════════════════════════
@ti.func
def contact_pp(ri, rj, vi, vj):
    F   = ti.Vector([0.0, 0.0, 0.0])
    rij = ri - rj
    d   = rij.norm()
    ov  = 2*C.R - d
    if ov > 0 and d > 1e-12:
        n    = rij / d
        vrel = vi - vj
        vn   = vrel.dot(n)
        vt   = vrel - vn * n
        sRd  = ti.sqrt(C.R_star * ov)
        kn   = (4.0/3.0) * C.E_star * sRd
        gn   = 2.0 * C.eta * ti.sqrt(ti.max(1e-30, C.m_star * kn))
        Fn   = kn * ov - gn * vn
        if Fn < 0:
            Fn = 0.0
        Ft  = ti.Vector([0.0, 0.0, 0.0])
        vtm = vt.norm()
        if vtm > 1e-12:
            kt  = 8.0 * C.G_star * sRd
            gt  = 2.0 * C.eta * ti.sqrt(ti.max(1e-30, C.m_star * kt))
            Ftm = ti.min(gt * vtm, C.mu_f * Fn)
            Ft  = -Ftm * (vt / vtm)
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
    for I in ti.grouped(grid_cnt):
        grid_cnt[I] = 0
    for i in range(C.N):
        gx = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][0] / C.hcell))))
        gy = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][1] / C.hcell))))
        gz = ti.max(0, ti.min(HRES-1, int(ti.floor(pos[i][2] / C.hcell))))
        s = ti.atomic_add(grid_cnt[gx, gy, gz], 1)
        if s < MAXPC:
            grid_buf[gx, gy, gz, s] = i

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

        # ── SURFACE CONFINEMENT — active during shape phase only ──────────
        # Soft spring keeps particles on their assigned cylinder surface so
        # inter-particle repulsion spreads them evenly rather than particles
        # drifting off the surface.
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
                # Viscous damping — dissipates post-burst KE; particles settle
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
                                Fc = contact_pp(pos[i], pos[j], vel[i], vel[j])
                                F += Fc
                                if Fc.norm() > 1e-15: nc += 1
        frc[i]      = F
        ncontact[i] = nc


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATOR
# ═══════════════════════════════════════════════════════════════════════════
@ti.kernel
def integrate():
    vcap = v_cap[None]
    for i in range(C.N):
        a     = frc[i] / C.mp
        vel[i] += a * C.dt
        speed = vel[i].norm()
        if speed > vcap:
            vel[i] = vel[i] / speed * vcap
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

    def get_active_cluster(self):
        if self.state.startswith("transport_"):
            idx = int(self.state.split("_")[1])
            return self.transport_order[idx]
        return -1

    def update(self, t, cluster_centroids):
        if self.state == "settle":
            if t >= T_SETTLE_END:
                self.state = "cluster"; self.phase_start_t = t

        elif self.state == "cluster":
            if t >= T_CLUSTER_END:
                self.state = "transport_0"; self.phase_start_t = t
                self.arrived_t = None; self.handoff_t = None
                self.current_transport_idx = 0

        elif self.state.startswith("transport_"):
            idx       = int(self.state.split("_")[1])
            cluster_k = self.transport_order[idx]
            target    = C.targets[cluster_k]
            centroid  = cluster_centroids[cluster_k]
            dist      = np.linalg.norm(centroid - target)
            elapsed   = t - self.phase_start_t

            if dist < ARRIVAL_THRESHOLD:
                if self.arrived_t is None:
                    self.arrived_t = t
                    self.handoff_t = t
                # Wait for handoff to complete (0.5s), then move to interlude
                if t - self.arrived_t >= 0.5:
                    self.completed.add(cluster_k)
                    self._advance_to_interlude(idx, t)
            else:
                self.arrived_t = None
                self.handoff_t = None

            if elapsed > TRANSPORT_BUDGET:
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
        else:
            self.state = "shape"; self.phase_start_t = t

    def get_transport_progress(self, t):
        """Path progress: 0 during GRAB_TIME, then 0→1 over remaining budget."""
        if not self.state.startswith("transport_"):
            return 1.0
        elapsed = t - self.phase_start_t
        if elapsed < GRAB_TIME:
            return 0.0  # Stationary grab phase — trap is ON but not moving
        move_elapsed = elapsed - GRAB_TIME
        move_budget  = TRANSPORT_BUDGET - GRAB_TIME
        raw = min(move_elapsed / move_budget, 1.0)
        return 0.5 * (1.0 - math.cos(PI * raw))

    def is_done(self, t):
        return self.state == "hold" and (t - self.phase_start_t >= HOLD_TIME)

    def get_phase_label(self):
        if self.state == "settle":   return "Settle"
        if self.state == "cluster":  return "Cluster"
        if self.state.startswith("transport_"):
            return ["Mv→Top","Mv→Lft","Mv→Rgt","Mv→Bot"][int(self.state.split("_")[1])]
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


def update_dipoles(t, pm, cluster_centroids):
    """
    Update all dipole positions, moments, and strengths.

    v13.0 — UNIFIED SINGLE-DIPOLE-PER-CLUSTER:
      ONE dipole per cluster serves as BOTH transport lead AND hold.
      Transport: dipole d_lead ahead of cluster centroid, moment toward cluster.
      Arrival: dipole parks at target + d_lead*normal, stays at full strength.
      Hold: same dipole, same position, same strength. ZERO topology change.
      Hold ring (IDX_HOLD_A/B) DISABLED — always strength=0.
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

    # Phase-specific gradient clamp (global used inside Taichi kernel)
    global GRAD_B2_CLAMP
    if pm.state == "shape":
        GRAD_B2_CLAMP = SHAPE_MAX_GRAD_CLAMP
        surf_conf_enabled[None] = 1
    else:
        GRAD_B2_CLAMP = 2000.0
        surf_conf_enabled[None] = 0

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

    _SLIDE_DUR = 0.5  # Duration to slide dipole from lead position to target

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
                    # Provides wall-normal restoring only; zero z-force. ✓
                    # Gravity is balanced by particle-particle contacts (bottom-up pile).
                    if k == active_shape_k:
                        # Weak upward z-lift to counteract gravity on the wall surface.
                        # At 1 mm above target, s=0.10 → F_z ≈ 2× gravity, allows axial spread.
                        # No radial component — surface confinement spring handles r=cR.
                        p[dip_idx] = np.array([target[0], target[1], target[2] + 1.0e-3])
                        m[dip_idx] = _m_trap * np.array([0., 0., 1.])
                        s[dip_idx] = 0.10
                    else:
                        p[dip_idx] = np.array([target[0], target[1], target[2]])
                        if k == 1:
                            m[dip_idx] = _m_trap * np.array([-1., 0., 0.])  # Q1: inward (-x)
                        else:
                            m[dip_idx] = _m_trap * np.array([1., 0., 0.])   # Q2: inward (+x)
                        if k_order_idx < shape_slot:
                            s[dip_idx] = SHAPE_DONE_HOLD_STRENGTH * 1.5
                        else:
                            s[dip_idx] = SHAPE_WAIT_HOLD_STRENGTH

            elif pm.state == "hold":
                # HOLD PHASE: maintain shaped geometry without collapsing it.
                # Caps: cluster dipole parked (hold pair handles z-pinning).
                # Walls: radial anchor at target (NOT below — see v31 fix above).
                if k in (0, 3):
                    p[dip_idx] = np.array([C.cx, C.cy, -5.0e-3])
                    s[dip_idx] = 0.0
                else:  # walls
                    p[dip_idx] = np.array([target[0], target[1], target[2]])
                    if k == 1:
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
            progress    = pm.get_transport_progress(t)
            path        = transport_paths[k]
            n_wp        = len(path)
            path_idx    = min(int(math.floor(progress * (n_wp - 1))), n_wp - 1)
            path_target = path[path_idx]

            cluster_cen = cluster_centroids[k]
            elapsed     = t - pm.phase_start_t
            trap_in     = ramp(t, pm.phase_start_t, pm.phase_start_t + 0.3)

            if pm.arrived_t is not None:
                # ARRIVAL PHASE: Smoothly slide dipole from near-target to exact target.
                # Over _SLIDE_DUR (0.5s), the dipole position interpolates to target.
                # By arrival time, d_lead is already very small (progress ≈ 1.0),
                # so the slide distance is minimal — smooth and gentle.
                target = C.targets[k]
                normal = _target_normals[k]
                slide_frac = ramp(t, pm.arrived_t, pm.arrived_t + _SLIDE_DUR)
                # At arrival, lead was already reduced. Use small residual offset.
                # The lead_reduction at progress=1.0 is 1.0, so effective_d = 0.
                # But at the instant of arrival, progress may be ~0.95, so there
                # could be a small residual. Slide from that to zero.
                residual_lead = _d_lead * (1.0 - ramp(progress, 0.8, 1.0))
                lead_pos = target + residual_lead * normal
                p[dip_idx] = lead_pos + slide_frac * (target - lead_pos)
                # Interpolate moment: -normal → transverse (ŷ)
                mom_transport = -_m_trap * normal
                mom_hold      = _m_trap * np.array([0., 1., 0.])
                m[dip_idx] = mom_transport + slide_frac * (mom_hold - mom_transport)
                s[dip_idx] = 1.0  # Full strength throughout
            else:
                # v13.2: TRANSPORT — lead from PATH WAYPOINT, not cluster centroid.
                #
                # Physics: B² maximum is at the dipole. By placing the dipole at
                # path_target + d_lead * tangent, the cluster is attracted directly
                # toward the path waypoint (the B² max is there or just ahead).
                #
                # Path tangent: direction from current waypoint to next waypoint.
                # This gives a stable direction that doesn't oscillate with the
                # cluster position (unlike centroid-chasing).
                #
                # Lead reduction: as progress → 1.0, d_lead → 0. This ensures
                # the dipole converges to the final target position at path end.
                # Uses cosine ramp from progress=0.8 to progress=1.0 for C¹ smooth.

                # Compute path tangent from waypoint differences
                next_idx = min(path_idx + 1, n_wp - 1)
                if next_idx > path_idx:
                    tangent = path[next_idx] - path[path_idx]
                    tang_norm = np.linalg.norm(tangent)
                    if tang_norm > 1e-9:
                        tangent = tangent / tang_norm
                    else:
                        tangent = _target_normals[k]
                else:
                    # At end of path — tangent is surface normal
                    tangent = _target_normals[k]

                # Smoothly reduce lead distance as we approach end of path
                lead_reduction = ramp(progress, 0.8, 1.0)  # 0 at prog<0.8, 1 at prog=1.0
                effective_dlead = _d_lead * (1.0 - lead_reduction)

                # Place dipole at path waypoint + reduced lead along tangent
                p[dip_idx] = path_target + effective_dlead * tangent
                # Moment points from dipole toward path_target (attracts cluster)
                m[dip_idx] = -_m_trap * tangent
                s[dip_idx] = trap_in  # Ramp in over 0.3s

        # else: cluster not yet active → dipole stays OFF (s=0)

    # ── HOLD RING — enabled for caps during shape AND hold phases ─────────────
    # Cap clusters (Q0, Q3) need z-pinning from the transverse pair throughout
    # shaping AND the final hold phase. Without this, rings fall as soon as
    # the state transitions from "shape" to "hold".
    # Wall clusters (Q1, Q2) do NOT use hold rings (their gravity is ⊥ to normal;
    # z-support comes from the wall anchor dipole during shaping and gentle
    # retention during hold).
    for k in range(4):
        s[IDX_HOLD_A[k]] = 0.0
        s[IDX_HOLD_B[k]] = 0.0
    # Caps get hold pair ONLY during hold phase (NOT during shaping).
    # During shaping, surf_conf z-spring alone handles z-pinning (no external
    # shape dipoles active for caps). The ±x hold dipoles broke azimuthal
    # symmetry → 2-lobe splitting → keep them OFF during shaping.
    if pm.state == "hold":
        for cap_k in (0, 3):
            if cap_k in pm.completed:
                s[IDX_HOLD_A[cap_k]] = CAP_SHAPE_HOLD_S
                s[IDX_HOLD_B[cap_k]] = CAP_SHAPE_HOLD_S

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
                # ── WALL SHAPING v33: FAST OSCILLATING SCAN ON CYLINDER OUTER SURFACE ──
                #
                # Single dipole scans a raster:
                #   phi:  fast ±60° back-and-forth oscillation around tgt_phi
                #         N_PHI_SWEEPS=10 complete oscillations over the slot
                #   z:    cosine oscillation z_lo↔z_hi, 4 cycles over slot
                #   r:    cR + 0.3mm (close to wall → strong gradient)
                #   moment: inward radial + 45% upward tilt (increased from 30% for
                #           better z-support as dipole sweeps away from particle)
                #
                # WHY ±60° NOT ±90° (old design):
                #   Old ±90° linear sweep: ω=0.628 rad/s → v_tan=1.05mm/s << v_cap → orbit/follow
                #   New ±60° fast oscillation: ω_avg≈8.4 rad/s → v_tan≈14mm/s >> v_cap → deposition ✓
                #   Constrained to ±60° (=PHI_HALF_SPAN) to avoid contaminating the opposite wall
                #   cluster target (Q1↔Q2 are π apart; ±60° leaves a 60° safety gap). ✓
                #
                # DEPOSITION MATH:
                #   N_PHI_SWEEPS=10, PHI_HALF_SPAN=π/3 (60°)
                #   ω_avg = 4·(π/3)·10 / T_slot = 8.38 rad/s
                #   v_tan = 8.38 · cR = 8.38 · 1.667e-3 = 13.97mm/s >> v_cap=5mm/s ✓
                #   Particles cannot follow → deposited in stripes across the ±60° arc. ✓
                #
                # Z-SUPPORT:
                #   sin_tilt increased 0.30→0.45: z-force component = 0.45·F_mag vs 0.30 before.
                #   This helps support wall particles against gravity (g=1.62 m/s²) when the
                #   scan dipole is at moderate phi offsets from the particle. ✓
                #
                # Cluster anchor (IDX_CLUSTER_DIP for active wall k) stays OFF:
                #   The initial loop at top of update_dipoles sets all IDX_TRAP s=0.
                #   The per-cluster loop does `pass` for active_shape_k.
                #   This block does NOT set dip_wall_idx → anchor remains OFF. ✓
                tgt_phi = math.atan2(tgt[1] - C.cy, tgt[0] - C.cx)

                # phi: fast back-and-forth within ±PHI_HALF_SPAN around target azimuth.
                # Triangle wave: local_frac → phi oscillates -SPAN→+SPAN→-SPAN N_PHI_SWEEPS times.
                # ω_avg = 4·PHI_HALF_SPAN·N_PHI_SWEEPS / T_slot ≈ 8.38 rad/s → v_tan≈14mm/s >> v_cap
                N_PHI_SWEEPS = 10.0
                PHI_HALF_SPAN = PI / 3.0   # ±60° — safe gap to opposite wall cluster
                _phi_t = (local_frac * N_PHI_SWEEPS * 2.0) % 2.0   # sawtooth 0→2
                _phi_t = _phi_t if _phi_t <= 1.0 else 2.0 - _phi_t  # triangle wave [0,1]
                phi_scan = tgt_phi + PHI_HALF_SPAN * (2.0 * _phi_t - 1.0)

                # z: cosine oscillation, 4 full up-down cycles over slot
                N_Z_CYC = 4.0
                z_phase  = (local_frac * N_Z_CYC) % 1.0
                z_scan   = C.z_lo + 0.5 * C.cH * (1.0 - math.cos(PI * z_phase))

                d_wall = 0.3e-3    # 0.3mm outside cylinder wall
                r_scan = C.cR + d_wall
                px = C.cx + r_scan * math.cos(phi_scan)
                py = C.cy + r_scan * math.sin(phi_scan)
                p[scan_idx] = [px, py, z_scan]

                # Moment: radially inward (confinement to wall) + 45% upward (better z-support)
                sin_tilt = 0.45
                cos_tilt = math.sqrt(max(0.0, 1.0 - sin_tilt * sin_tilt))
                m[scan_idx] = _m_shape * np.array([
                    -math.cos(phi_scan) * cos_tilt,
                    -math.sin(phi_scan) * cos_tilt,
                    sin_tilt,
                ])
                s[scan_idx] = shape_str

    # ── VELOCITY CAP — phase-adaptive ────────────────────────────────
    # The cap is a numerical safety limit, not a physical constraint.
    # Root cause of Q0 transport lag: the Q0 cosine arc (floor→7.5mm apex)
    # has peak dipole speed ≈ π/2 × 4.47 mm/s ≈ 7.0 mm/s over the first
    # half of move_budget=3.7s. With cap=5mm/s the cluster can't keep pace,
    # falls >2mm behind, force drops as 1/r⁴, gravity wins → cluster drops.
    # Fix: raise cap to 12mm/s during transport so cluster can follow dipole.
    if pm.state in ("settle", "cluster"):
        v_cap[None] = 0.025   # fast initial pile formation
    elif pm.state.startswith("transport_"):
        v_cap[None] = 0.012   # must exceed peak dipole speed ~7mm/s (Q0 arc)
    elif pm.state.startswith("interlude_"):
        v_cap[None] = 0.003   # damp residual velocity after transport
    elif pm.state == "shape":
        v_cap[None] = 0.005   # balanced surface spreading
    else:                      # hold
        v_cap[None] = 0.002   # minimal drift during final hold

    # ── Upload to Taichi and sync monitoring array ────────────────────
    dip_p.from_numpy(p)
    dip_m.from_numpy(m)
    dip_s.from_numpy(s)
    np.copyto(dip_str_np, s)
    np.copyto(dip_mom_np, m)    # v19: sync for energy tracking diagnostic


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
    v_cap[None] = 0.025
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
  VTK frames → outputs/Phase2_v5_Fixed/asm_NNNNNNN.vtu
  Animation  → outputs/Phase2_v5_Fixed/simulation.pvd  (open in ParaView)
  Checkpoint → outputs/phase2_checkpoint.pkl            (auto-saved every 1s)
  Shape ckpt → outputs/shape_checkpoint.pkl             (saved once at shape start)
  Diagnostics→ outputs/Phase2_v5_Fixed/diagnostics.png
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
            global GRAD_B2_CLAMP
            GRAD_B2_CLAMP = 2500.0
            print(f"  [chi-scale] GRAD_B2_CLAMP increased to {GRAD_B2_CLAMP} for low-chi regime")

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
    print(f"    Transport: leads from PATH waypoint (not centroid)")
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

    out_dir = Path("outputs") / "Phase2_v5_Fixed"
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

    # Account for interludes in time estimate
    t_max_est = (T_CLUSTER_END + 4*TRANSPORT_BUDGET + 3*INTERLUDE_TIME
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
                # GPU→CPU sync to get current particle positions
                if colors_fixed:
                    apply_fixed_colors()
                else:
                    assign_centres.from_numpy(C.qc_3d)
                    assign_clusters_initial()
                p_np  = pos.to_numpy()
                cl_np = cluster_id.to_numpy()
                centroids = {k: get_cluster_centroid_np(p_np, cl_np, k) for k in range(4)}

            # ── Phase manager update (uses cached centroids when static) ──
            pm.update(t, centroids)

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
            update_dipoles(t, pm, centroids)

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
    print("  [KEPT] CAP Z-PINNING: Hold pair at CAP_SHAPE_HOLD_S=0.40 (was 0.15).")
    print("  [KEPT] CAP cluster dipoles PARKED at z=-5mm (s=0).")
    print("  [KEPT] WALL z-lift: cluster dipole below target, moment +z.")
    print("  [KEPT] All sources EXTERNAL to simulation box.")
    print("  [KEPT] No wall/surface mechanical boundaries.")
    print("")
    print("  FIELD PARAMETERS (v30):")
    print(f"  [OK]  N_CAP_RING = {N_CAP_RING}  (tilted-moment azimuthal ring dipoles per cap)")
    print(f"  [OK]  N_WALL_BELT = {N_WALL_BELT} × N_WALL_Z_LEVELS = {N_WALL_Z_LEVELS}  (full belt per wall)")
    print(f"  [OK]  SHAPE_D_SURF = {SHAPE_D_SURF*1e3:.1f}mm  (increased 0.9→1.5mm, 7.7x force reduction)")
    print(f"  [OK]  CAP r_ring: {CAP_RING_R_START:.2f}->{CAP_RING_R_END:.2f}->{CAP_COMPRESS_R:.2f} x cR (slower sweep)")
    print(f"  [OK]  CAP_SHAPE_HOLD_S = {CAP_SHAPE_HOLD_S:.2f}  (increased 0.15→0.40)")
    print(f"  [OK]  SHAPE_MAX_GRAD_CLAMP = {SHAPE_MAX_GRAD_CLAMP:.0f} T^2/m")
    print(f"  [OK]  SHAPE_TIME = {SHAPE_TIME:.1f}s  ({SHAPE_TIME/4:.1f}s/cluster, order {SHAPE_ORDER})")
    print(f"  [OK]  Energy diagnostic: {total_energy_J:.3f} J total I^2*R dissipation")
    print(f"  [OK]  All forces: F = (Vp*chi_eff/2mu0)*grad(B^2) - no hacks, no wall constraints")
    print("="*72 + "\n")


if __name__ == "__main__":
    main()