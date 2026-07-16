# REGO Project History

Magnetic field-driven autonomous assembly of lunar regolith particles into a hollow cylinder.
This document tracks the technical evolution of the simulation, including all major approaches, failures, and fixes.

---

## Project Overview

**Goal:** Simulate magnetic field-gradient-driven self-assembly of paramagnetic lunar regolith particles (N=256, R=30 μm, ρ=7800 kg/m³, χ=0.15) into a hollow cylinder (radius cR=1.667 mm, height cH=4 mm) under lunar gravity (g=1.62 m/s²).

**Physics:** F = (V_p·χ_eff/2μ₀)·∇(B²) — particles seek B² maxima.

**Phases:**
1. Clustering → 2. Transport (×4 clusters) → 3. Shaping (caps + walls) → 4. Hold → 5. Consolidation

**Files:**
- `phase2_clean_okay.py` — Main simulation (active)
- `phase3_consolidation.py` — Bonding/consolidation
- `phase0_baseline.py` / `phase1_magnetic.py` — Early prototypes

---

## Git Commit Log

| Commit | Summary |
|--------|---------|
| `c8b016e` | Initial commit |
| `e86bfdb` | First draft: FEM output + LIGGGHTS DEM input |
| `2f4e662` | Added magnetic field visualization through particles |
| `c29b0e8` | Type 5 particles made paramagnetic for field reaction |
| `54209c2` | Tried Altair; discovered/fixed LIGGGHTS issue; added cropping |
| `b5fcd5f` | LIGGGHTS failed; ANSYS DEM worked |
| `a61dcc5` | Added `phase2_clean_realistic.py` with first-principles physics |
| `882b52a` | `.gitignore` updated to exclude test outputs |
| `b4e036e` | Code review: clarified phase count, removed misleading comment |
| `1604737` | Merged PR #1: physics model rewrite |
| `4790256` | Python version update |
| `79c6621` | Rewrote `phase2_clean_realistic.py`: 41-dipole architecture, all 6 issue fixes |

---

## Technical Evolution Log

### Phase 0–1: LIGGGHTS / ANSYS DEM Baseline (early commits)

**Approach:** Used commercial DEM software (LIGGGHTS, ANSYS) to simulate granular particle dynamics.

**Outcome:** LIGGGHTS encountered compatibility issues. ANSYS DEM worked for basic DEM but lacked magnetic field-gradient force capability.

**Key lesson:** Commercial tools insufficient for paramagnetic force physics → need custom simulation.

---

### Phase 2: Custom Taichi Simulation — Clustering

**Version:** v1–v5 (phase2_clean_okay.py early)

**Architecture:** 8 corner quadrupoles (4 anti-aligned pairs) create far-field cancellation. Field minimum at domain center attracts all particles.

**Physics validated:**
- Single dipole: B ∝ 1/r³
- Quadrupole (anti-aligned pair): far field ∝ 1/r⁵ (90% crosstalk reduction)
- Center field: ~0.0003 T per quadrupole corner

**Result:** ✓ All 256 particles cluster at domain center within 2.5s.

---

### Phase 3: Transport (v5–v13)

**v5.0 — Lead dipole grab+move protocol:**
- Single dipole per cluster, positioned d_lead=0.3mm ahead of centroid
- GRAB_TIME=0.3s stationary at cluster before moving
- Force at cluster: F_z ≈ 6916 W (saturates v_cap)
- Radial force at 0.15mm: -2680 W (inward, prevents expansion)

**v13.1 — Lead distance reduction:**
- d_lead reduced 0.5→0.3mm: gentler pull, less overshoot

**Key insight:** Single dipole = single B² maximum. Particles cannot split around single moving attractor.

**Result:** ✓ All 4 clusters transported to target positions on smooth cosine arc paths.

---

### Phase 4: Shaping — Cap Clusters (Q0 top, Q3 bottom)

This phase has undergone the most iteration.

#### v18: Simultaneous Radial Lines
**Approach:** N=8 radial dipole arms sweeping outward simultaneously for all clusters.
**Failure:** All 4 clusters active → cross-cluster interference → clusters merged.
**Fix:** Sequential shaping (one cluster at a time).

#### v19: Sequential Radial Lines
**Approach:** Shape one cluster at a time. Each slot: radial dipole sweeps r from center → cR while others held with anchor dipole.
**Failure:** Particles followed the instantaneous dipole position → circular orbiting (chase behavior).

#### v22–v28: Rotating Triplet (Time-Averaged B²)
**Rationale:** Earnshaw's theorem prevents static B² maximum in free space. Time-averaged ⟨B²⟩ from 3 dipoles at 120° phase is azimuthally symmetric.
**Failure:** ω_rot ≈ 15 rad/s < ω_mech ≈ 25 rad/s. Particles can follow the rotating maximum → epicyclic orbiting (Nyquist violation).

#### v29–v30: Static External Ring
**Approach:** N=6 or 8 external dipoles uniformly in azimuth at r_ring, moments radially inward. Sweep r_ring from 0.15*cR → 1.0*cR over slot time.
**Physics:** B² profile in cap plane has annular maximum at ~0.7*r_ring.
**Failure:** Discrete N-fold symmetry → N-lobe particle splitting. N=6 → 6-lobe clusters.

#### v30: Hold Pair y-Splitting Bug
**Problem:** 2-dipole hold pair along ŷ created B² saddle in ŷ → at CAP_SHAPE_HOLD_S=0.40, cluster split into 2 sub-clusters at y≈±3mm.
**Fix (v31):** 4-dipole square ring (±x̂, ±ŷ) → 4-fold symmetry → no preferential splitting axis.

#### v31: Anti-Helmholtz Axial Pair
**Approach:** Two opposing z-moment dipoles on the cylinder axis: +z at z_hi+d, −z at z_hi−d.
**Physics:** B² maximum at r = d_z/2 (analytical result for anti-Helmholtz pair).
**Failure:** ALL particles converge to the specific ring radius → unstable ring → oscillatory collapse. Classic Earnshaw: ring is saddle point, not stable maximum.

#### v32–v33: IDX_HOLD_A/B Disabled During Shaping
**Problem:** Hold pair (±x offset from target) during shaping broke azimuthal symmetry → 2-lobe splitting.
**Fix:** Hold pair OFF during shape state; ON only during hold state.

#### v34: Contact-Repulsion Only (No Active Dipoles)
**Approach:** Remove ALL external cap shape dipoles. Rely entirely on surf_conf z-spring + Hertz-Mindlin contact repulsion.
**Rationale:** Dense cluster (51% 3D packing) bursts under contact forces (F ≈ 60,000×g). Z-spring converts 3D expansion to 2D radial spread.
**Observed behavior:**
- ✓ Particles burst and spread across cap face
- ✗ Burst is uneven
- ✗ Particles keep moving randomly after burst
- ✗ Two distinct sub-clusters form while moving
**Root cause of failures:**
1. 64 particles in disk of r=1.667mm → 2.1% area packing fraction → particles rarely contact after spread → no Hertz-Mindlin damping
2. No potential energy landscape → particles random-walk → accidentally aggregate
3. v_cap limits speed but doesn't remove KE from free-flying particles

#### v35: Contact + Weak Radial Bias + Viscous Damping (SUPERSEDED by v36)
**Date:** 2026-06-24

**Changes:** Added CAP_RADIAL_BIAS_K=0.05, CAP_VISC_DAMP_TAU=0.5s, diagnostics.

**Failure:** Observed two sub-clusters, random motion, never stabilizing.

**Root cause (diagnosed in v36):**
k_r=0.05 N/m creates a radial harmonic oscillator:
- ω_osc = √(k_r/mp) = √(0.05/8.82e-10) = 7,530 rad/s → period T = 0.835 ms
- Damping time τ=0.5s → 600 undamped oscillation cycles before significant decay
- k_r force at r=1mm: F=50 μN; viscous drag at v=5mm/s: F=8.82 pN → ratio = 5,700×
- Particles oscillate between r=0 and r=cR elastically (wall spring + outward bias)
- 64 particles on 1D ring undergo Smoluchowski coagulation → two equal sub-clusters

---

#### v36: Contact + Damping, No Radial Bias (Current)
**Date:** 2026-06-24

**Changes to constants:**
1. `CAP_RADIAL_BIAS_K = 0.0` (from 0.05): removes radial oscillator; eliminates ring dynamics
2. `CAP_VISC_DAMP_TAU = 0.25s` (from 0.5s): stopping distance = v_cap·τ = 1.25mm < cR=1.667mm → no wall bounce

**Changes to cap shaping comment block (compute_forces):** Updated from v35 to v36, documenting the oscillator root cause and three-mechanism (z-spring, HM contact, damping) approach.

**Changes to diagnostics:** Added sub-cluster count via DBSCAN-lite (ε=4R=0.12mm) to directly verify whether sub-clustering has been eliminated.

**Physical analysis:**
- Dense 3D cluster (51% packing) bursts under contact forces → 2D expansion at v≈v_cap
- Burst starting from r≈0.34mm (2D compressed radius): max r_final = 0.34+1.25 = 1.59mm < cR ✓
- No wall contact → no elastic bounce → no oscillation
- Particles reach rest after ~3τ = 0.75s (well within 5s slot)
- Azimuthally symmetric annulus at r ∈ [0.3, 1.6]mm; stable distribution
- `subclusters=1` expected in diagnostics (vs old `subclusters=2`)

**Numerical stability:**
- b×dt/mp = dt/τ = 8e-6/0.25 = 3.2e-5 << 1 ✓ (stable explicit damping)
- z-spring: ω·dt = 0.190 ✓ (unchanged)

**Pending validation:** Whether annulus distribution is sufficiently uniform or requires further intervention.

---

### Phase 5: Shaping — Wall Clusters (Q1 left, Q2 right)

#### v33: Fast Oscillating Scan (Current, Unchanged)
**Approach:** Single scanning dipole does raster scan:
- φ: ±60° triangle wave, N_PHI_SWEEPS=10 complete oscillations per slot
- z: cosine oscillation z_lo↔z_hi, 4 cycles per slot
- r: cR + 0.3mm (just outside cylinder wall)
- Moment: inward radial + 45% upward tilt

**Why ±60° not ±90°:** v_tan = ω·cR ≈ 14 mm/s >> v_cap = 5 mm/s → deposition mode (particles can't follow dipole).

**Result:** ✓ Wall clusters deposit in stripes across ±60° arc, covering cylinder wall.

---

### Phase 6: Hold

**Architecture:** 4-dipole square ring per cap cluster (IDX_HOLD_A/B), ON only during hold state.
**Geometry:** Dipoles at ±x and ±y from target center, all moments along surface normal n̂.
**Physics:** B² maximum exactly at ring center (target) by 4-fold symmetry → zero gradient at equilibrium.

---

## Key Physics Constraints (Earnshaw Compliance)

| What | Why |
|------|-----|
| No static ring of N dipoles for spreading | N static dipoles = N B² maxima (Earnshaw) → N-lobe splitting |
| No anti-Helmholtz pair for spreading | Creates ring attractor at specific r → all particles converge → ring collapse |
| No time-averaged rotating field | ω_rot must >> ω_mech (Nyquist); not achievable at 8μs dt |
| Single moving attractor (plow) | Single maximum = no splitting possible |
| Contact repulsion as primary spreading | No Earnshaw constraint on mechanical forces |

---

## Parameter Reference

| Parameter | Value | Notes |
|-----------|-------|-------|
| N | 256 | Total particles |
| R | 30 μm | Particle radius |
| ρ | 7800 kg/m³ | Iron density |
| mp | 8.82×10⁻¹⁰ kg | Particle mass |
| g | 1.62 m/s² | Lunar gravity |
| χ | 0.15 | Magnetic susceptibility |
| Msat | 2×10⁵ A/m | Saturation magnetization |
| dt | 8 μs | Timestep |
| v_cap | 5 mm/s (shape) | Velocity limit |
| cR | 1.667 mm | Cylinder radius |
| cH | 4 mm | Cylinder height |
| SURF_CONF_K | 0.5 N/m | z-spring strength |
| CAP_RADIAL_BIAS_K | 0.0 N/m | Radial outward bias (v36: REMOVED — creates oscillator) |
| CAP_VISC_DAMP_TAU | 0.25 s | Viscous damping time (v36; stopping dist = 1.25mm < cR) |
| e_n | 0.3 | Restitution coefficient (HM) |
| μ_f | 0.4 | Friction coefficient (HM) |
| E_eff | 2×10⁵ Pa | Particle Young's modulus |
