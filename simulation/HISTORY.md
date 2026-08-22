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

## Stage A: Physics-Correctness Repair (2026-08-13)

**Trigger:** user-reported failures — blue/red caps splitting into sub-clusters during shaping, the
yellow/orange wall-shaping slots visibly dragging the caps sideways, yellow particles appearing to
vanish, and everything collapsing onto a point outside the cylinder at the end of Phase 2. A full
audit was requested before any code changes: read CONTEXT.md/HISTORY.md/phase1/phase2 in full, trace
the actual equations and data flow, and verify every conclusion against real checkpoint data
(`outputs/shape_checkpoint.pkl`, `outputs/phase2_checkpoint.pkl`) rather than the animation.

**What was wrong (all independently verified, not inferred):**

1. **F1 — contact neighbor list silently broken.** `build_grid` wrote the true (too-large) per-cell
   particle count into `grid_cnt` while only storing the first `MAXPC=32` indices in `grid_buf`;
   `compute_forces` then read past the buffer's end. Measured: 64 particles/cell at shape start, 128
   in the final checkpoint (`hcell` was 1.2mm). Real overlapping neighbours beyond the 32nd received
   zero contact force — contact mechanics was broken exactly where v34-v36's "burst-driven spreading"
   needed it most.
2. **F2 — coincident-particle absorbing state.** `contact_pp`'s `d > 1e-12` guard made exact
   coincidence (reachable via F1) permanent: zero force, particles co-move forever. Verified:
   minimum pair distance was exactly 0.0 in the final checkpoint; Q2 (orange)'s 64 particles had
   spread = 0.000mm — a single point.
3. **F3 — wall scan dipole was driving the caps.** The wall-shaping scan dipole swept z all the way
   to `z_hi`/`z_lo` — the cap planes. Direct computation at that geometry (pre-fix moments) gave up
   to 3306×gravity on Q0 (top cap) particles, all directed toward the currently-shaping wall cluster
   — exactly the t≈30s (Q1/yellow slot) and t≈35s (Q2/orange slot) events the user reported. Wall
   clusters also had no z-confinement, so they rode the scan up to the cap plane and interleaved with
   cap particles — the "disappearance" was real spatial migration, not deletion or recoloring.
4. **F4 — the "hold ring" was two point attractors, not a ring.** Comments describe a 4-dipole square
   ring with a B² maximum at its center by symmetry; only 2 of the 4 positions were ever
   instantiated (the code comment introducing the design admits this). Verified: final Q0 centroid
   (7.49, 4.97, 7.10)mm sat essentially on top of hold dipole 12 at (7.50, 5.00, 7.24)mm, spread
   collapsed. This is the terminal "everything sucked to a point outside the cylinder" failure.
5. **F5 — particle identity was already correct.** `cluster_id == fixed_color` held at every
   checkpoint checked, counts stayed 64/64/64/64. No recoloring, no deletion — verified, not fixed.
6. **F6 — field magnitudes were physically impossible.** `_m_trap`/`_m_shape` at their operating
   standoffs implied 4.4-11.1 T fields from a coil declared as 100 turns × 4mm² at 1.5-3.75A (which
   physically produces millitesla fields), evaluated 0.3-1.5mm from a coil whose own linear
   dimension is 2mm — inside its own near field, invalidating the point-dipole approximation used
   throughout `compute_forces`.
7. **F7 — the velocity cap set the kinematics, not the physics.** A single 8µs step at the old
   `GRAD_B2_CLAMP=2000` produced Δv=122mm/s against a 12mm/s transport cap — 10× over-cap every
   step, saturated continuously. Non-conservative clipping also prevented contacts from separating
   overlapping particles, feeding F2.
8. **F8 — timestep too large for the contact model.** dt=8µs gave ω·dt=0.66 at δ=R; Rayleigh
   criterion requires ≤6.4µs, Hertz contact period requires ≤3.8-4.5µs at realistic overlaps.
9. **F9 — invented forces.** `surf_conf` (a spring to a mathematical plane/cylinder) and its viscous
   damping term have no physical source.
10. **F10 (minor) — `dip_pos_np` never synced** in `update_dipoles` (checkpoints stored stale dipole
    positions); CONTEXT.md stated `∇²(B²) ≤ 0` (sign backwards; conclusion was still correct);
    `phase1_cluster.py`/`phase0_baseline.py` are disconnected legacy prototypes, not pipeline stages.
11. **F11 — cohesion was completely absent** from `phase2_shaping.py`'s contact model, despite
    `phase3_consolidation.py` already relying on the same physics (`W_adh=0.08 J/m²`). At R=30µm,
    DMT adhesion dominates lunar gravity by ~5000× — two touching grains do not separate on their
    own. This is a missing real physical interaction, not an invented one.
12. **F12 — consequence of F11:** at realistic (F6-corrected) field magnitudes, F_mag/F_vdW≈0.23 at
    R=30µm. The v34-v36 premise (dense ball bursts apart under its own contact repulsion into a
    spread monolayer) is not physically achievable at this grain size once cohesion is modeled.
13. **F13 — ponderomotive dynamic trapping (v22-v28) was never tested at the required frequency
    ratio.** ω_rot=15-120 rad/s vs ω_mech≈25 rad/s (0.6-5×) is nowhere near ω_drive≫ω_mech. At the
    F6-corrected force scale, ω_mech≈735-2324 rad/s; a 10× drive (7.3-23 kHz) is numerically
    resolvable at dt=3µs. This failure mode says nothing about whether the mechanism itself works.
14. **F14 — discovered while implementing F6/F7: `GRAD_B2_CLAMP` never actually updated at
    runtime, in any prior version of this file.** It was a plain Python global reassigned per-phase
    via `global GRAD_B2_CLAMP` inside `update_dipoles()`. Taichi bakes Python-scope scalars read
    inside a `@ti.func`/`@ti.kernel` into the compiled kernel at its *first compile* — verified with
    a minimal repro (changing the Python global after a kernel is compiled has zero effect on later
    calls). `compute_forces` is first compiled during the pre-loop diagnostic while
    `pm.state=="settle"`, so the settle/cluster branch's value (2000.0) was silently the permanent
    clamp for the entire run, including "shape" phase — every HISTORY.md discussion of a "shape
    gradient clamp=700" (or my own initial =30 fix) was describing a value that was never actually
    applied in the running kernel.

**What changed (all in `phase2_shaping.py` unless noted):**

- `build_grid`/`compute_forces`: `hcell` 1.2mm→8R, `MAXPC` 32→96, overflow now counted
  (`grid_overflow_count`) instead of silently corrupting the neighbor list (F1).
- `contact_pp`: added a deterministic, antisymmetric fallback normal (`_degenerate_normal`) for
  exactly-coincident particles (F2); added DMT adhesive pull-off `F_adh=2π·R*·W_adh`,
  `W_adh=0.08 J/m²` matching `phase3_consolidation.py` (F11).
- `integrate()`: removed the hard velocity clip entirely; kinematics now come from F=ma (F7).
- Dipole moments recalibrated (`_m_trap`, `_m_shape`) to target ≈50×gravity peak force at standoffs
  ≥3× the coil's own linear dimension; `COIL_AREA` reduced 4mm²→0.158mm² side so the recalibrated
  standoffs (`d_lead`, `d_wall`: 0.3mm→0.5mm) are genuinely far-field for the coil model used (F6).
  `GRAD_B2_CLAMP`/`SHAPE_MAX_GRAD_CLAMP`: 2000/700→30 T²/m — now a numerical safety guard that
  should not saturate in normal operation, not a governor of normal-operation force (F6/F7).
- `dt`: 8µs→3µs, satisfying both the Rayleigh and Hertz-contact-period criteria (F8).
- `C.targets[0]`/`C.targets[3]` z: 7.2mm/2.8mm → exactly `z_hi`/`z_lo`, removing the 0.2mm step that
  produced a ~70,000×gravity impulse at shaping start (F3 precursor).
- Wall-scan z-sweep inset by `Z_CAP_MARGIN=0.75mm` from `z_lo`/`z_hi` (F3); combined with the F6
  recalibration, worst-case residual cross-talk on the nearest cap-rim particle dropped from
  3306×gravity to ≈0.5×gravity (verified numerically both before and after).
- Hold-ring activation in the `hold` phase state removed entirely; `IDX_HOLD_A/B` strengths stay 0
  in all states (F4). A correct symmetric ring is deferred to a Stage B design decision.
- `surf_conf` and its damping term relabeled in-code as explicit non-physical placeholders, with a
  pointer to CONTEXT.md §18 and an instruction not to extend/retune them (F9).
- `dip_pos_np` now synced every `update_dipoles` call (F10).
- `GRAD_B2_CLAMP` converted from a plain Python global to a `ti.field(ti.f64, shape=())`, the
  pattern already correctly used for `surf_conf_enabled` (and previously `v_cap`) — the phase-
  specific clamp switch now actually takes effect at runtime, which it silently never did before
  (F14).
- Output directory `outputs/Phase2_v5_Fixed` → `outputs/Phase2`.
- `phase1_cluster.py`/`phase0_baseline.py` docstrings updated to state plainly they are legacy,
  disconnected prototypes.
- New `analysis/validate_phase2.py`: checks identity, conservation, contact integrity (grid
  occupancy, overlap, coincidence), force sanity (peak ×gravity, clamp saturation), cap cross-talk,
  and timestep stability (ω·dt) against a checkpoint. Run against the pre-fix baseline checkpoints
  first to confirm it correctly flags every finding above (it did: F1/F2/F6/F7/F3 all triggered
  FAIL on the old `outputs/phase2_checkpoint.pkl`).
- `CLAUDE.md` created at the repo root with the persistent project rules (no scaffold, no invented
  forces, Earnshaw compliance, verification discipline).
- `CONTEXT.md` §3 sign correction (`∇²(B²)` was stated backwards), stale filename references fixed,
  and a new §18 "Physical limits and known non-physical placeholders" added as the standing
  reference for current status.

**Physically justified, not tuned to a picture:** every numeric change above traces to either a
verified bug (F1-F5, F10) or a first-principles recalibration against a stated physical constraint
(F6: coil far-field validity; F7/F8: contact/Rayleigh stability criteria; F3: direct force
recomputation at the new geometry; F11: an existing constant already used elsewhere in this
codebase). None were chosen by re-running the simulation and adjusting until the animation looked
right.

**Explicitly NOT done, per project direction:** no physical scaffold, mandrel, cage, or mold was
added. `surf_conf` was not removed (Stage A's scope is correctness of the existing model, not a
redesign) but is not to be extended either.

**Expected honest outcome:** with F1-F10 fixed, the simulation should be numerically and mechanically
correct, but static-field shaping (the only mechanism Stage A implements — `surf_conf` plus contact
repulsion plus, now, cohesion) is still expected to fail to hold particles spread across the target
surfaces on its own, per the Earnshaw argument in CONTEXT.md §18.3. That is the expected result of
this stage and the evidence base for a Stage B magnetic-control redesign — F13 (ponderomotive
trapping, correctly implemented at the frequencies computed above) is the leading untested candidate,
not yet implemented.

**Confirmed by a full end-to-end run (2026-08-13, CPU backend, ~8 wall-hours for the 42.3
sim-second run — settle→cluster→4×transport→shape→hold, `outputs/phase2_checkpoint.pkl`,
`outputs/shape_checkpoint.pkl`):**

- **Numerically stable throughout.** Zero NaN/Inf, zero crashes, particle count/identity correct
  at every checkpoint sampled (t=1.0, 2.5, 12.1, 19.8, 28.6, 42.3s). Grid occupancy stayed within
  `MAXPC` (peak 67/96), coincident-particle count stayed 0.
- **F3 confirmed fixed in the live run, not just analytically:** cross-talk from the active
  wall-scan dipole onto the cap clusters measured **0.00×gravity** at the t=19.8s and t=28.6s
  checkpoints (was up to 3915×gravity pre-fix on the same checkpoints).
- **F12's prediction materialized:** particle-particle overlap grew over the shape phase (0.20R at
  shape start → 0.34–0.43R mid-shape) rather than shrinking as v34-v36 assumed — consistent with
  cohesion (F11) preventing the "burst apart into a monolayer" mechanism from working once it's
  modeled honestly. ω·dt briefly touched 0.20 (my chosen accuracy bound, not a divergence
  threshold) at the densest sampled moment; KE stayed bounded throughout, no runaway.
- **The predicted hold-phase gap happened exactly as anticipated, and it is the headline result of
  this run:** final state at t=42.3s (`Hold`) has all four clusters sitting on the domain floor
  (z_mean=0.04-0.07mm for all of Q0/Q1/Q2/Q3) instead of at their targets (7.0/5.0/5.0/3.0mm) —
  total distance error 22.77mm, all four marked ✗ in the final report. This is not a bug: `surf_conf`
  only activates during `pm.state=="shape"`, and the false hold ring (F4) is now permanently
  disabled rather than patched — so the instant shaping ends, nothing opposes lunar gravity for the
  cap clusters, and the wall clusters' hold-phase anchor (`SHAPE_DONE_HOLD_STRENGTH`, radial-only,
  no z-component) provides no vertical support either. Everything free-falls to the floor. This is
  the honest, load-bearing conclusion of Stage A: **no static field held the assembled structure
  together once active shaping stopped**, which is exactly the Earnshaw argument in CONTEXT.md
  §18.3 predicted, now demonstrated end-to-end rather than argued analytically.
- **A real cost this run exposed:** total coil energy 165,714 J (avg 3915 W) over the run, vs. a
  10 J "lunar budget" reference in the code's own diagnostic — a direct consequence of the F6 coil
  shrink (COIL_AREA 4mm²→0.158mm² side) trading field-model validity (genuine far-field standoffs)
  for much higher required current (and thus I²R power) at the same moment. This trade-off was
  flagged as a design choice, not tuned away, at the point it was made (see F6 above) — this is
  that choice's measured consequence and should inform any Stage B coil-geometry decision.
- Stage B (the actual shaping mechanism) remains unimplemented. F13's frequency arithmetic has been
  verified analytically but the ponderomotive controller itself does not exist yet, and this run's
  hold-phase collapse is now the concrete evidence for why it — or some other genuinely
  time-varying / substrate-free mechanism — is necessary, not optional polish.

---

## Stage A-2: Closed-Loop Transport Controller (2026-08-15/16)

**Trigger:** a deep, checkpoint-by-checkpoint audit of the Stage A end-to-end run (user-supplied
timestamps 4.447s–39.847s, cross-referenced against the real animation) reported clusters "falling"
immediately after appearing to reach their targets, clusters seeming to merge with each other, wildly
non-intuitive corner-to-corner trajectories, and a "massive explosion" at t≈19.8s.

**Root cause (finding F15), found by reconstructing the real run, not by re-reading the code:**
`analysis/reconstruct_run.py` was written to parse all 846 real VTU frames (position, velocity,
force magnitude, and permanent `cluster_id` per particle) and replay the real `PhaseManager`/
`update_dipoles` logic against the real centroid trajectory, recovering the exact dipole
configuration active at each requested timestamp. That reconstruction showed:

- `arrived_t` was `None` at **every single checkpoint sampled** — no transport ever detected genuine
  arrival (`dist < ARRIVAL_THRESHOLD`); all four transports were completed by the unconditional
  `TRANSPORT_BUDGET=4.0s` timeout instead, regardless of actual cluster state.
- Every transport ran at or near the clamp-saturated force ceiling (141.7×gravity, a=229.6 m/s²,
  confirmed directly — the VTU's own recorded `Fmag` reads ~140.x repeatedly) for large fractions of
  its window, because the trap dipole's lead distance collapses toward the cluster late in every
  transport by design.
- With Stage A's F7 fix (hard velocity cap removed — correctly, since it was a non-physical
  numerical crutch) and **no other mechanism opposing velocity during transport** (the viscous
  damping term only activates during `shape`; inelastic contact is too weak against bulk
  center-of-mass motion), velocity was free to accumulate for the full 4-second window: measured
  387mm/s by t=4.447s, escalating to **50,000–97,000 mm/s by t=19.848s** (the reported "explosion,"
  which sits exactly at the transport_3→shape boundary — four clusters' worth of accumulated
  momentum released as their driving fields switch off).
- Cross-checking `cluster_id` at every chaotic checkpoint confirmed **no real merging occurred** —
  counts stayed 64/64/64/64 throughout. The apparent "merging" is independently-tracked,
  high-velocity clusters' trajectories spatially overlapping, not an identity violation. Comparing
  reconstructed forces (computed purely from real dipole state and real particle position, no
  cluster-ID logic) against the VTU's own recorded force at the calmer checkpoints also confirmed the
  field is not cluster-ID-filtered.

**The physical constraint this fix had to respect:** a static dipole field is conservative — a
particle released into it with nonzero kinetic energy cannot come to rest at a potential extremum on
its own; it will oscillate through the target forever absent dissipation. The only physically
available dissipation here is real inelastic contact (weak against bulk motion) or **actively moving
the source**, which does real work on the particle because the field becomes genuinely time-varying —
exactly how every real closed-loop electromagnet (maglev, magnetic bearings, real magnetic-tweezer
rigs) is actually driven: a controller reads a position/velocity sensor and adjusts the actuator's
current and position; the force the particle feels remains the same physical law. No force may be
added directly to a particle's equation of motion, and nothing may be filtered by `cluster_id`.

**Design process:** per explicit project direction, the fix was designed and quantitatively justified
*before* implementation (see the approved plan; summarized here). Three controller designs were
compared: (A) the broken position-only, time-scheduled lead (baseline); (B) position+velocity
feedback with a cruise/brake/settle zone law — recommended; (C) a smoother open-loop time schedule,
which removes one discontinuity but still can't detect or correct a cluster running hot, and was
folded into B as a smoothness ingredient rather than adopted standalone.

**What changed (all in `phase2_shaping.py`):**

- New `get_cluster_velocity_np()` — real per-cluster mean velocity from the existing `vel` Taichi
  field, read every transport batch exactly like the existing centroid readback.
- New closed-loop transport controller constants, all derived from simulation scale rather than
  chosen for convenience: `EPS_X=5R=0.150mm` (position tolerance — independently reproduces the old
  `ARRIVAL_THRESHOLD` exactly), `EPS_V=EPS_X/CTRL_DT_NOMINAL=25mm/s` (velocity tolerance — the speed
  below which a cluster can't drift outside `EPS_X` even coasting unpowered for one control cycle),
  `D_BRAKE_TRIGGER=3×EPS_X`, `V_CEIL=8mm/s`, `ARRIVAL_DWELL=0.15s`, `STALL_TIMEOUT=6.0s` (diagnostic
  safety net only — replaces `TRANSPORT_BUDGET` as the *primary* completion path; firing now prints
  a loud, explicit warning instead of silently completing).
- New `solve_strength_for_accel()` — inverts the existing soft-clamp formula (the same one already
  used in `B_and_gradB2`) to find the dipole strength that delivers a requested acceleration at a
  given standoff, capped at what's actually achievable at that standoff (not the theoretical
  clamp-saturated ceiling, which is only reachable much closer than the safe standoffs used here).
- `PhaseManager.update()`: arrival now requires `dist<EPS_X AND speed<EPS_V`, sustained for
  `ARRIVAL_DWELL` — a real physical criterion, replacing the position-only check whose timeout was
  the actual primary path. `get_transport_progress()` removed (superseded).
- `update_dipoles()`'s active-transport branch rewritten as a three-zone closed-loop law:
  **cruise** (pure-pursuit lookahead on the existing collision-avoiding path arc, strength throttled
  by a smoothstep function of real speed relative to `V_CEIL` — a real coil-current throttle, not a
  particle force), **brake** (`d<=D_BRAKE_TRIGGER`: dipole repositioned *behind* the cluster along
  its real sensed velocity direction, so the same always-attractive force opposes motion, strength
  set via `solve_strength_for_accel` to the standard kinematic braking requirement
  `v²/(2·d_remaining)`), **settle/hold** (dipole at target + small normal offset — not coincident
  with the particles themselves, avoiding the singular near-field — at ~3× the strength needed to
  balance local gravity, gentle headroom, cross-talk onto other targets independently confirmed
  negligible at real target separations, <0.0002×gravity at full strength).
- `make_transport_path()` and the collision-avoiding waypoint arc are **unchanged** — reused for
  routing; only the lead-distance/strength logic downstream of path-following changed.

**Verified before implementation (design-time, all numbers checked against the recalibrated F6
moment):** achievable acceleration at the safe brake standoff (0.5mm, s=1) is 76.4 m/s² — well above
what's needed to stop from `V_CEIL=8mm/s` (stopping distance ≈0.14μm, ~3200× margin under
`D_BRAKE_TRIGGER`). Target-pair cross-talk at real separations (nearest 2.738mm) is already
negligible (<0.0002×gravity) at any tested hold strength — a side effect of the F6 recalibration, not
something this controller has to work hard to achieve.

**Verified after implementation — finding F17 (CRUISE-zone standoff collapse, transport does not
converge):** A first full run (post-F16 fix, `rego_run4.log` + real VTU output) showed the velocity
runaway from F15 is genuinely gone — `vm` during transport stayed in the low tens of mm/s (vs.
50,000–97,000 mm/s pre-Stage-A-2) — but a new, real failure replaced it: **all four transports timed
out via the `STALL_TIMEOUT` safety net without ever converging**, each forced to complete far from its
target:

| Transport | forced-completion t | d (mm, should be <0.15mm) | v (mm/s) |
|---|---|---|---|
| transport_0 | 8.530s | 7.895 | 17.5 |
| transport_1 | 14.949s | 5.499 | 46.5 |
| transport_2 | 21.379s | 5.723 | 1.5 |
| transport_3 | 27.799s | 6.204 | 0.4 |

This is the diagnostic safety net working exactly as designed — surfacing an honest failure instead of
silently forcing completion unlogged (the old F15 behavior) — but it means the controller as designed
does not actually work. Root cause, reconstructed from real VTU centroid data (not guessed from code),
via a standalone replay of the exact CRUISE-zone nearest-waypoint/lookahead logic against transport_0's
real recorded trajectory (`t=2.5-5.0s`):

1. **The cluster never leaves the floor.** Its centroid z stayed pinned at `z=0.030mm` (=`C.R`,
   literal particle-radius contact with the floor) for the *entire* observed window, while `x,y`
   swung erratically over several mm (e.g. `(7.5,7.5)→(2.3,7.5)→(3.1,7.1)→...`, never settling). The
   design's own written assumption — "clustering has already pulled the cluster to the domain center
   (z≈5mm)" — used to justify the F16 fix, is **wrong for the z-component**: clustering only
   regroups particles by lateral (x,y) proximity at floor level; it does not lift them. Transport
   therefore starts needing a genuine ~7mm vertical climb against lunar gravity, sustained
   continuously — a requirement the CRUISE law's control law never explicitly verifies at any step.
2. **This breaks the CRUISE law's core distance assumption.** The law places the dipole at
   `path_target + d_lead·tangent`, with `d_lead=0.5mm` — implicitly assuming the dipole stays within
   about the design standoff of the *actual* cluster, because a working pure-pursuit loop keeps the
   lookahead point near the vehicle. Since the cluster can't climb, it falls further and further
   behind the path's rising z, so the real dipole-to-cluster separation grows unbounded instead of
   staying near 0.5mm: **measured directly from the real trajectory, `r` = 0.79mm at t=2.55s → 2.86mm
   at t=4.15s → 5.00mm at t=4.85s.** Per this design's own force-vs-standoff table (see the Stage A-2
   plan), force is already negligible beyond ~1.5mm — so the achievable pull keeps weakening exactly
   as it's needed most, a self-reinforcing collapse (weak pull → cluster falls further behind → dipole
   drifts even farther → pull weakens further). The nearest-waypoint index visibly jumps
   discontinuously once the cluster is dragged sideways past different parts of the unreached arc
   (confirmed directly in the replay), which is the proximate cause of the observed d/KE oscillation,
   but the index jumping is a *symptom* of the standoff collapse, not an independent bug.
3. **Not a re-emergence of F15.** Velocity stayed bounded throughout (peak ~46.5mm/s at forced
   completion, nowhere near the old 50-97 m/s runaway) — this is a convergence failure, not a
   stability failure. The stall safety net fired correctly and did not mask the problem.

**Conclusion:** the Stage A-2 CRUISE law's implicit assumption (dipole tracks close to the real
cluster because pursuit "just works") does not hold once genuine vertical lift-off is required, and
the law has no explicit check or mechanism ensuring the resultant force's vertical component exceeds
gravity at the current geometry. This is a **design gap**, not an implementation bug in the sense of
F1-F16 — the control law needs to be redesigned to either (a) bound dipole-to-cluster separation
explicitly (re-anchor the lookahead to a point near the cluster's real projection onto the path rather
than a fixed arc-length lookahead that can run away), or (b) treat vertical lift-off as its own
explicit sub-phase with a lift-authority check before pursuit begins, or another approach — this
requires a design decision, not a quick patch, per the standing "design before implementation"
practice for this controller. Reported to the user with the real numbers above rather than patched
ad hoc.

### Stage A-3: LIFTOFF/LIFT sub-phase (2026-08-16)

Design approved: explicit LIFTOFF → LIFT → CRUISE → BRAKE → SETTLE state machine, replacing the
direct CRUISE engagement that caused F17. Before implementing, two physics checks were run against
real data (not assumed):

**Lift-off force, real 64-particle geometry** (not point-mass): dipole placed directly above the real
centroid (from an actual VTU frame at transport start), force computed per real particle with the
exact live dipole-field + soft-clamp formula. At the standoff already used elsewhere in this
controller (0.5mm): **30.4× the real cluster weight, 0/64 particles clamp-saturated.** Below ~0.3mm
the same table shows the force is dominated by saturated particles (56-64/64) — confirms 0.5mm, not a
closer/stronger standoff, is the right operating point. Lateral force from the real (imperfectly
symmetric) particle arrangement is 0.051% of the vertical force; implied angular acceleration from net
torque ≈0 — liftoff is clean, not lopsided, without assuming symmetry.

**3×g strength target**, independently re-derived rather than assumed from the existing SETTLE
convention: a full time-integration of the real accel-vs-strength law (ramp + `V_CEIL`-throttle, the
same mechanism CRUISE already uses) shows a smooth, self-limiting rise — peak net accel <1 m/s², peak
speed ~3.6mm/s (well under `V_CEIL=8mm/s`), reaching the 0.5mm clearance target in ~150-330ms depending
on ramp width. Not max-force.

**CRUISE standoff cap (`MAX_CRUISE_STANDOFF=0.75mm`)**, the direct fix for F17's unbounded pursuit
lookahead: 2.92× margin over gravity at max strength (the worst case), decisively below the r=1.0mm
point where lift capability vanishes entirely (0.34×, cannot lift). Time to reach `V_CEIL` from rest at
this standoff is ~2.6ms — negligible against the path's mm-scale curvature, so steering authority is
not a binding constraint. Chosen as option (B), state-dependent bounded lookahead, over (A) the old
unbounded fixed arc-length scheme: the dipole cannot advance past `MAX_CRUISE_STANDOFF` from the real
cluster regardless of path geometry, so a cluster that can't keep pace makes the effective trajectory
wait rather than running away from it.

Implemented in `phase2_shaping.py`: new `PhaseManager` fields (`liftoff_start_z`,
`liftoff_confirmed_t`, `lift_cleared_t`, `lift_done`) gate a new `elif not pm.lift_done:` zone before
CRUISE; LIFTOFF is verified complete only from real sensed z-rise (`Z_LIFTOFF_CONFIRM = C.R`), never
assumed from commanded strength; a `LIFTOFF_STALL_TIMEOUT` diagnostic warns (not silently proceeds) if
real upward motion is never confirmed. CRUISE's commanded dipole position is now clamped to within
`MAX_CRUISE_STANDOFF` of the real cluster position. A synthetic unit test confirmed all five sub-phases
produce the expected standoffs (LIFT/BRAKE/SETTLE=0.5mm exactly, CRUISE correctly clamped to 0.75mm
when the geometric pursuit point would otherwise be farther).

**Verified after implementation — finding F18 (LIFT succeeds; CRUISE immediately drops the cluster
back to the floor):** A real run (`rego_run5.log`) confirms LIFTOFF/LIFT genuinely work — this is new,
real, measured behavior, not a repeat of F17: cluster-0's real z (read directly from the live
simulation's own per-cluster centroid, not inferred) rose from `0.0300mm` (floor) to `0.7183mm` over
`t=2.55→2.90s`, comfortably exceeding `LIFT_CLEARANCE=0.5mm`, triggering the designed transition to
CRUISE at `t=2.95s`. But at the very next print (`t=3.00s`, 50ms later), z had already crashed back to
`0.0mm` and **stayed pinned there for the remaining ~5.5s of the transport**, with `d` oscillating in
the same 7.1-7.9mm sawtooth pattern seen in F17, ending in the same kind of forced `STALL_TIMEOUT`
completion (`t=8.530s, d=7.905mm, v=29.2mm/s`) as before the fix — all four transports failed the same
way.

Root cause is not yet confirmed (deliberately not patched blindly): the most likely mechanism, pending
verification against real per-cluster velocity data, is a **LIFT→CRUISE throttle handoff mismatch**.
LIFT's ODE was designed to self-limit near `V_CEIL` (verified above), so the cluster plausibly enters
CRUISE already near `V_CEIL`; CRUISE's own throttle (`1-smoothstep(vmag/V_CEIL)`) uses *total* speed
magnitude for the *same* ceiling, so a cluster arriving with vertical speed already near `V_CEIL` could
have its CRUISE strength driven toward zero on the very first control step — removing vertical support
outright and reproducing free fall. This is a hypothesis, not yet confirmed: the simulation's printed
`vm` diagnostic is a **whole-domain max speed** (`ti.atomic_max` over all 256 particles, not a
per-cluster quantity — checked directly in `compute_stats()`), so it cannot be used to confirm or deny
this without instrumenting the real per-cluster velocity at the LIFT→CRUISE boundary. Reported to the
user with the real z-trajectory numbers above; further diagnosis and any fix are pending direction.

### Stage A-4: F18 confirmation and CRUISE vertical/horizontal decoupling design (2026-08-16)

**F18 confirmed** via new instrumentation (`DEBUG_LIFT_CRUISE=1`, gated behind an env var, reads real
per-control-step — 6ms cadence, matching `CTRL_DT_NOMINAL` — state for cluster 0 directly from the
live simulation, not the 50ms print log or the whole-domain `vm` diagnostic; see
`_debug_lift_cruise_snapshot()` in `phase2_shaping.py`). Real captured data, `rego_run6.log`:

- **LIFT has a real bang-bang oscillation but is self-correcting.** Every other 6ms control step, `v_z`
  overshoots `V_CEIL=8mm/s` by 30-60% (observed 10-13mm/s) because the old throttle
  (`1-smoothstep(v/V_CEIL)`) doesn't reference the real control period, so a full-strength 6ms step
  regularly overshoots before the throttle reacts. When overshot, `thr_vert` correctly snaps to
  `0.0000` for one step (`net_az=-1.62`=`-g` exactly, pure free-fall) — but recovers within 1-2 steps
  because gravity decelerates a purely-vertical overshoot quickly. This is why LIFT still succeeded
  (real z climbed 0.03→0.72mm) despite the oscillation.
- **The instant CRUISE engages, force direction pivots hard away from vertical**: `Flat/W` jumps from
  ~0.06 (LIFT) to **0.773** at CRUISE's very first, fully-throttled step (`Fz/W=0.934`, already under
  1) — confirms CRUISE's chosen pull direction (path tangent) is not vertical-dominant even before any
  throttle issue.
- **One step later, `thr_total` (computed from TOTAL speed) collapses to exactly `0.0000` and never
  recovers**: `vr_tot` climbs continuously (1.33→1.43→2.30→3.39→4.54→4.93→6.12) because free-fall
  itself keeps adding downward velocity on top of the lateral velocity CRUISE just introduced — unlike
  LIFT's vertical-only throttle, this criterion cannot self-correct: zero force → free-fall accelerates
  → total speed grows further → throttle stays pinned at zero. `s=0.0000`, `net_az≈-1.62` persist for
  10+ consecutive control steps (~60ms) until the cluster hits the floor at ~48mm/s.
- Ruled out: no dipole-position/strength discontinuity at the boundary itself (`sep` goes 0.5→0.73mm
  as designed; first CRUISE `s=0.52` is comparable to LIFT's own thrust steps), no path/coordinate bug,
  no contact-model anomaly.

**Root cause, precisely:** CRUISE used one pull direction (path tangent) and one scalar throttle
(function of *total* speed) to do two physically independent jobs (vertical support, horizontal
pursuit) at once. Because free-fall increases total speed, the throttle criterion actively suppresses
the very force needed to stop the fall — a positive-feedback failure, not a momentary gap.

**Design (approved for implementation, not yet implemented as of this entry):**

1. **A single dipole is physically sufficient for both jobs simultaneously**, proven from the on-axis
   dipole relation (`B²∝1/r⁶` on-axis, so a dipole placed at `x_cur + r·â` with moment `-â` delivers
   force of magnitude `F(r,s)` in exactly direction `â` — any desired 3-D direction is realizable by
   choosing where to place it, not by inventing a force). Quantitatively: at the standoff already used
   everywhere else in this controller (`r=0.5mm`), available force is 30.4× cluster weight (F17-era
   real-particle-geometry table); a combined vertical+horizontal target of `3g` each needs only 6.87
   m/s² against a 76.36 m/s² ceiling — **11.1× margin**. No multi-dipole configuration is needed.
2. **Vertical channel — replaces the smoothstep throttle with a one-step-ahead (deadbeat) predictor**
   using the real known control period: `a_vert_gross(v_z) = g + max(0, (V_CEIL-v_z)/CTRL_DT_NOMINAL)`.
   Verified numerically: `Fz/Mg` = 1.82× at `v_z=0` down to **exactly 1.00× at/above `V_CEIL`, never
   below** — reaches `V_CEIL` in exactly one control step with no overshoot (`v_z_new = v_z +
   (V_CEIL-v_z) = V_CEIL`), then holds at a controlled hover rather than cutting to zero. Directly
   satisfies "never command `Fz<Mg` while airborne" as a hard floor on the *correction* term, not the
   total. The same law replaces LIFT's throttle too (same mechanism, strictly better — no more
   bang-bang), per the user's explicit request not to ignore that finding.
3. **Horizontal channel — same predictive style, independent speed measurement**: `v_horiz =
   ‖(v_x,v_y)‖` (never includes `v_z`), `a_horiz_gross = max(0, (V_CEIL-v_horiz)/CTRL_DT_NOMINAL)`,
   direction from the existing unchanged pure-pursuit lookahead. This is the actual fix: free-fall no
   longer appears anywhere in the horizontal channel's throttle, breaking the self-reinforcing chain.
4. **Composition**: `a_cmd = a_vert·ẑ + a_horiz·ê_pursuit`, realized as ONE dipole at
   `p=x_cur+0.5mm·â_cmd`, `m=-m_trap·â_cmd`, `s=solve_strength_for_accel(|a_cmd|, 0.5mm)`. Because the
   vector is composed explicitly before realization, the delivered vertical component equals
   `a_vert_gross` exactly — not degraded by whatever the horizontal piece needs — which is what makes
   the guarantee real rather than aspirational (backed by the 11.1× combined-magnitude margin above).
   This also fixes F17 as a side effect: standoff is now a fixed 0.5mm constant, not path-derived, so
   the separation-runaway mechanism cannot recur.
5. **BRAKE**: unchanged (already direct kinematic deceleration, not a throttle — no runaway risk), but
   flagged a latent same-shaped risk (if velocity at brake-entry is mostly horizontal, the brake
   dipole's direction along `-v̂` could under-support vertically) as a validation check, not an assumed
   problem, since CRUISE now actively holding `Fz≥Mg` throughout should leave little residual vertical
   error by then.
6. **Cross-talk re-verified for the new fixed 0.5mm CRUISE standoff**: worst-case strength (`s=0.29`
   for the `6.87 m/s²` combined target) at the nearest other target (2.738mm) gives **2.9e-5×gravity**
   — more negligible than the old design, since far less strength is ever needed at a closer, fixed
   standoff.
7. **Per-cluster vertical climb differs (Q0: 6.97mm, Q1/Q2: 4.97mm, Q3: 2.97mm)** but the control law
   is identical across clusters — only transit duration differs.

**Failure conditions to add**: `solve_strength_for_accel` clipping to `s=1` for `|a_cmd|` (should
never fire given the 11× margin — a real finding if it does); real floor clearance dropping back near
`C.R` during CRUISE (the direct F18 regression signature) → loud diagnostic, same style as
`STALL:`/`LIFTOFF STALL:`.

**Not yet implemented.** Awaiting approval before touching `phase2_shaping.py`. Validation plan (once
implemented): re-run the F18 instrumentation across all four clusters' LIFT→CRUISE boundaries
confirming `Fz/W` never drops below ~1.0; re-run `reconstruct_run.py`'s per-cluster diagnostic
confirming dipole separation is now a flat 0.5mm line; confirm all four transports reach real
`arrived_t`; explicit BRAKE vertical-force sampling per point 5 above; re-confirm cross-talk in a real
run; confirm the LIFT bang-bang pattern is gone from the velocity profile.

**Implemented and re-validated (2026-08-16, `rego_run7.log`).** Unit test across all five sub-phases
confirmed correct decoupled behavior before the full run (notably: LIFT at `v_z=15mm/s`, an overshoot,
commands the *same* strength as at exactly `v_z=8mm/s=V_CEIL` — the floor holds, never zero; CRUISE
with both channels near ceiling correctly zeroes only the saturated one). Real per-cluster horizontal
convergence is excellent: at the point transport_0 was forced to complete, real `(x,y)=(4.991,
5.043)mm` against target `(5,5)mm` — within 0.05mm. **However, transport_0 still did not reach real
`arrived_t`** — it hit `STALL_TIMEOUT` at `t=8.530s`, `d=2.860mm`, `v=4.0mm/s`. This is real, substantial
improvement over F18 (`d` was 7.9mm, `v` up to 46.5mm/s pre-fix) but not full convergence — a new,
distinct finding (F19), diagnosed from existing VTU data with no new simulation runs (per the
efficiency requirement now in force for this project).

### Finding F19 — transient clamp-saturation spike at the LIFT→CRUISE handoff overshoots the vertical
### target, and CRUISE's vertical channel cannot command descent to recover

Diagnosed entirely by replaying the real, already-captured VTU frames from `rego_run7.log` (no new
simulation launched):

1. **A real, brief clamp-saturation spike occurs exactly at the LIFT→CRUISE handoff.** Real VTU `Fmag`
   at `t=2.898s`: mean `76.40×W`, max `140.76×W`, `Vmag` mean `187.55mm/s` (up from `7.82mm/s` just one
   50ms frame earlier). `140.76×W` matches the theoretical clamp-saturation ceiling almost exactly
   (`kelvin_pf·GRAD_B2_CLAMP/mp = 141.7×W`, independently computed) — this is genuine near-field
   saturation, not a bug in force computation or a units error.
2. **Mechanism (consistent with, not yet independently re-derived beyond, the available evidence):**
   the control loop recomputes the dipole position once per `CTRL_DT_NOMINAL≈6ms` and holds it fixed
   for the whole interval between updates. At the LIFT→CRUISE handoff the commanded direction changes
   abruptly (from straight up to a combined vertical+horizontal vector), and if the cluster carries
   residual velocity aligned toward the newly-repositioned dipole, real closing distance within a
   single held-fixed interval can significantly undercut the intended `_d_lead=0.5mm` standoff before
   the next control update repositions it — driving the real per-particle gradient into the clamp.
   This is a real property of discretized position-only-at-update-time control, not unique to this
   controller, but not previously stress-tested at this standoff/acceleration combination.
3. **Consequence: the cluster overshoots past its target height.** Real centroid at the moment of
   forced completion: `(4.991, 5.043, 9.859)mm` against target `(5, 5, 7)mm` — horizontal error
   `<0.05mm` (CRUISE's horizontal channel converged essentially perfectly), but `z` overshot to
   `9.86mm`, `2.86mm` **past** the `7.00mm` target (matches the reported stall distance almost exactly,
   confirming the entire residual error is vertical).
4. **Root cause of the deadlock (not just the overshoot): CRUISE's vertical channel structurally
   cannot command descent.** Verified directly: `a_vert_gross = g + max(0, (V_CEIL-v_z)/CTRL_DT_NOMINAL)`
   floors at exactly `g` (hover) regardless of how large `v_z` is, and — critically — **even when
   `v_z` is already negative (descending)**, e.g. `v_z=-5mm/s` still commands `a_gross=3.787 m/s²`, a
   **positive** net upward push of `2.167 m/s²` actively resisting the descent. The law was derived
   (Stage A-4 design) purely from velocity, with the explicit intent "CRUISE only runs while `d>
   D_BRAKE_TRIGGER`, i.e., far from target, so climbing is always appropriate there" — this assumption
   holds for the intended monotonic-climb case but was never checked against an overshoot, where `d`
   stays `>D_BRAKE_TRIGGER` (2.86mm, still an in-plane-large 3D distance) purely from a *vertical*
   error whose *sign* has flipped. The result is a genuine deadlock, not an oscillation or slow
   convergence: horizontal error is already resolved, vertical channel can only push up or hover, so
   `d` cannot shrink further, and the transport can only ever be resolved by `STALL_TIMEOUT`.
5. **Not yet re-checked:** whether transports 1-3 exhibit the same spike (the background run continued
   past transport_0's forced completion into transport_1 at the time of this diagnosis; not yet
   analyzed, to avoid running/re-running simulation time beyond what's needed to establish this
   finding, per the efficiency requirement).

**This is a design gap in the Stage A-4 vertical channel, not an implementation bug** — the code matches
the approved design exactly; the design's implicit assumption (CRUISE is always in a monotonic-climb
regime) was incomplete. Reported to the user with the real numbers above; no patch applied pending
their direction, per their explicit instruction not to patch before diagnosing and reporting.

**Confirmed to reproduce, not a one-off:** the background validation run (`rego_run7.log`) was continued
under the user's watch after this finding was written. `transport_1` also stalled — forced completion at
t=14.949s, d=7.112mm, v=9.3mm/s (worse residual error than transport_0's 2.860mm) — and `transport_2` was
observed live to enter the identical pattern (z climbing to 9.7mm against a 5.0mm target, `d` oscillating
in a 7.1-7.4mm band with no net progress for 30+ control steps) before the run was deliberately stopped
per the efficiency directive (it was no longer providing new decision-relevant information — the pattern
was already established).

### F19 fix — CRUISE vertical channel made genuinely bidirectional (2026-08-16)

**Design pass (required and completed before any code change, per explicit instruction).** Two candidate
designs were considered:

- *Full custom braking law inside CRUISE's vertical channel* (a trapezoidal/deadbeat law using
  `v_ref = sign(e_z)*min(V_CEIL, sqrt(2*a_budget*|e_z|))`, `a_budget=a_max`). Built and tested first via a
  synthetic double-integrator unit test (`test_f19_vertical.py`, no Taichi/no simulation run, using the
  real `a_max`, `g`, `V_CEIL`, `EPS_X`, `EPS_V`, `D_BRAKE_TRIGGER`, `STALL_TIMEOUT` constants pulled
  directly from the live module). **Rejected by its own test**: because `a_max` (76.36 m/s² at the real
  `_d_lead=0.5mm` CRUISE standoff, s=1, clamp=30 T²/m — 47.1x gravity) is so much larger than what's
  needed to arrest an 8mm/s cruise velocity, `sqrt(2*a_max*|e_z|)` only drops below `V_CEIL` in the final
  ~0.4 micron of approach — i.e. the "braking" term never actually engages in practice, so the cluster
  sails through the target at ±`V_CEIL` and chatters back and forth (20-22 vertical-force sign flips per
  test case, final `v_z` still pinned at `V_CEIL` at nominal "convergence").
- **Adopted: minimal signed-ceiling law, reusing the existing BRAKE branch for the actual stop.** Re-
  reading the BRAKE branch (`update_dipoles`, `elif d <= D_BRAKE_TRIGGER`, lines ~2443-2469) showed it was
  *already* a correct, real-velocity-opposing kinematic brake (`a_needed = v²/(2·d_remaining)`, dipole
  placed behind the actual velocity vector in any direction) — it was never asymmetric or broken. F19's
  actual defect was narrower than first modeled: CRUISE's vertical channel alone floored at `g` and so
  could never shrink the vertical component of `d` below `D_BRAKE_TRIGGER`, so BRAKE was simply never
  *reached* on the vertical axis. The fix therefore only needs to make CRUISE's vertical throttle
  symmetric — mirror the horizontal channel's existing ceiling-tracking form
  (`a = (v_ref - v)/dt_ctrl`), but take `v_ref`'s sign from the real signed height error
  (`v_ref_z = copysign(V_CEIL, target_z - z_cur)`) instead of hardwiring "always ascend". No new taper,
  no new mechanism — CRUISE now just gets the cluster's vertical component moving in the right direction
  at up to `V_CEIL`, and hands off to the already-correct BRAKE branch once `d < D_BRAKE_TRIGGER=0.45mm`.

**Synthetic validation (re-run against the revised, adopted law, before any implementation):** 5 cases —
(A) the real `transport_0` stall state (z=9.859mm, target=7.0mm, v_z=0), (B) the worst real observed
post-spike velocity (v_z=+187.6mm/s, matching the 187.55mm/s `Vmag` jump measured in the F19 diagnosis),
(C) the real `transport_2` live-observed stuck state (z=9.7mm, target=5.0mm), (D) a normal ascent with no
overshoot (regression check against the previously-working case), (E) a tiny sub-millimeter overshoot at
the tolerance boundary (chatter check). All 5 converged within `STALL_TIMEOUT` (144-948ms, well under the
6s budget), with **zero to one vertical-force sign flips** (no chatter) and a peak commanded acceleration
of 32.60 m/s² (42.7% of the real 76.36 m/s² ceiling, case B) — comfortable margin, no saturation in any
case. Case D (regression check) converged with negligible force use (0.1% of `a_max`), confirming no
change to the already-working ascend-only behavior.

**Implemented** in `update_dipoles`'s CRUISE branch (`phase2_shaping.py`, `elif d > D_BRAKE_TRIGGER`):
`a_vert_gross` is now computed from `e_z = target[2] - x_cur[2]` and `v_ref_z = copysign(V_CEIL, e_z)`
rather than the old `C.g + max(0.0, (V_CEIL - v_z)/CTRL_DT_NOMINAL)` (which could only ever add
non-negative terms to `g`). LIFT, BRAKE, SETTLE, the horizontal channel, and the single-dipole vector-
composition/realization mechanism are all unchanged. `SIM_VERSION` bumped `35.0.0` → `36.0.0`.

**First implementation attempt was itself wrong — caught by a real-sim check, not assumed correct.** A
short resumed run (from an existing post-cluster checkpoint, skipping the ~14min clustering phase) showed
transport_0 falling straight back toward the floor the instant CRUISE engaged — the exact F18 signature
recurring. Live `DEBUG_LIFT_CRUISE=1` instrumentation pinned the cause precisely: `a_vert_gross` is not
the net acceleration in this codebase's convention — the downstream `a_hat`/`solve_strength_for_accel`
realize it as the **dipole's own force/mass contribution**, with gravity applied separately and
unconditionally (`F[2] -= C.mp*C.g` in the integrator, independent of any dipole). The original law had
`C.g +` baked into that offset; the first fix attempt dropped it, so a merely-negative deadbeat term (a
momentary `v_z` tick above `V_CEIL`) was realized as "pull down with extra force **on top of** gravity,"
roughly doubling real descent — confirmed directly: `net_az=-1.834 m/s²` the instant `v_z=10.2mm/s` ticked
just above `V_CEIL=8mm/s`, versus the intended mild `-0.37 m/s²` correction. **Corrected**: restored
`a_vert_gross = C.g + (v_ref_z - v_z)/CTRL_DT_NOMINAL`. Re-validated with an isolated CRUISE-only synthetic
test (analytical, no simulation): all four real overshoot/velocity states now reach the BRAKE handoff
boundary cleanly in 300-760ms, descending/ascending correctly with no chatter.

### Finding F20 — the pre-existing BRAKE branch has the same gravity-decoupling bug, never previously
### exercised with real vertical velocity (2026-08-16)

Running the corrected F19 fix through a full CRUISE+BRAKE synthetic test (not yet a real simulation —
established analytically, per the efficiency directive) revealed a **second, independent, pre-existing**
bug: the BRAKE branch (`update_dipoles`, `elif d <= D_BRAKE_TRIGGER`, unmodified by the F19 fix) computes
a pure kinematic deceleration magnitude `a_needed = vmag²/(2·d_remaining)` and realizes it **fully along
`-v_hat`** with no gravity term at all — but gravity is always separately applied, exactly the same fact
that drove the F19 fix. Consequence: any BRAKE maneuver with a vertical velocity component over-brakes an
ascent or under-brakes a descent by `g`, and a **purely horizontal** brake gets **zero** vertical support
(free-fall during the brake). This was never caught before because no real run had ever reached BRAKE with
nonzero vertical velocity — every prior run (F17, F18, F19) stalled inside CRUISE first. The bug has been
latent in the BRAKE branch since it was written (Stage A-2) and is unrelated to the F19 fix except that
F19's fix is what first lets a real transport reach BRAKE with real vertical velocity, exposing it.

**Design (approved by the user before implementation, matching the CRUISE/F19 realization convention
exactly — no new mechanism):** the dipole must supply the pure kinematic deceleration vector *plus*
whatever cancels gravity's separately-applied effect: `F_dip/mp = a_net_req + (0,0,C.g)` where
`a_net_req = -a_needed·v̂`, realized as one dipole at magnitude/direction `a_hat = normalize(F_dip/mp)` —
replacing the old `p = x_cur - R_DECEL0·v̂`, `m = m_trap·v̂` placement with the same
`p = x_cur + R_DECEL0·a_hat`, `m = -m_trap·a_hat` convention already used by LIFT and CRUISE.

**Synthetic validation (before implementation):** combined CRUISE(F19-fixed)+BRAKE(F20-fix) test,
6 cases — the 3 real overshoot/stuck states (A, B, C), a no-overshoot regression check (D), a pure
horizontal brake at target height (E, specifically checking the previously-zero vertical support case),
and a combined horizontal+vertical residual-velocity case at the CRUISE/BRAKE boundary (F). All 6
converged within `STALL_TIMEOUT` (186-954ms), zero excessive sign flips or CRUISE/BRAKE zone chatter, no
saturation, peak force 40.6% of the `R_DECEL0` budget (case B, the worst real spike velocity) — comfortable
margin.

**Implemented** in `update_dipoles`'s BRAKE branch (`elif d <= D_BRAKE_TRIGGER`, moving-cluster case only —
the separate near-zero-total-velocity fallback branch, whose strength law (`trap_in*0.3`) pre-dates this
engagement, was left unchanged as out of scope for F20). Added a `BRAKE SATURATION` diagnostic print
(mirroring the existing `CRUISE SATURATION` pattern) and a dedicated `pm._brake_sat_warned` flag (kept
separate from `_cruise_sat_warned` so the two warnings don't cross-suppress each other).
`SIM_VERSION` bumped `36.0.0` → `37.0.0`.

**Real-simulation check (targeted, resumed from the post-cluster checkpoint) revealed a third, distinct
issue** before either F19 or F20 could be declared complete — see Finding F21 below.

### Finding F21 — CRUISE/BRAKE zone-switching chatter, a hard threshold with no hysteresis (2026-08-17)

Running the F19+F20-fixed controller against real data (extending the existing `DEBUG_LIFT_CRUISE`
instrumentation to also cover BRAKE and to run for the whole transport instead of just the LIFT/CRUISE
handoff, via a new `DEBUG_CRUISE_MAX` env var — reused/extended existing tooling rather than writing new
instrumentation) showed transport_0 making clean initial progress (158 straight CRUISE control steps,
~0.95s, `d` shrinking steadily to the BRAKE boundary), then entering a genuine, worsening limit cycle
between CRUISE and BRAKE — consecutive same-zone run-lengths shrinking over time (106→41→21→18→9→6→4→3→1
steps). Real per-step data pinpointed the trigger: at one crossing, `v_z` jumped 3.5→17.4→74.8 mm/s across
two consecutive 6ms control steps, with `satfrac` (real gradient / clamp) hitting 1.07 — genuine near-field
clamp saturation, not a diagnostic artifact. Root cause: `D_BRAKE_TRIGGER` is a single, no-hysteresis
threshold — the instant `d` ticks back above 0.45mm after a real kick, CRUISE reasserts a full-authority
one-step-deadbeat command from scratch (as if starting fresh), which can itself trigger another kick if the
abrupt dipole reposition happens to bring it close to an off-centroid particle in the real, finite-size
64-particle cluster (a geometry effect a centroid-only design analysis doesn't capture). Real post-kick
excursions reached d=0.61-2.91mm before flipping back.

**User selected the fix** (of several architecturally distinct options presented: hysteresis band,
rate-limiting the deadbeat command, or investigating the near-field spike mechanism first): a hysteresis
band on the zone switch. **Design**: add `D_BRAKE_EXIT = 2.0*D_BRAKE_TRIGGER = 0.90mm` — once in BRAKE,
only return to CRUISE once `d` exceeds this wider threshold (entering BRAKE is unchanged, at
`D_BRAKE_TRIGGER=0.45mm`). Requires one bit of memory (the previous control step's subphase, captured as
`_prev_sub` before the zone-selection branch runs) — no new persistent state beyond what `PhaseManager`
already tracks. `D_BRAKE_EXIT`'s value is a round 2x multiplicative margin (matching this codebase's
existing convention of round multiplicative margins — `D_BRAKE_TRIGGER` itself is 3x `EPS_X`, hold
strength is 3x gravity, etc.), chosen with headroom over the real observed 0.88mm first-chatter excursion.

**Synthetic validation limitation, reported honestly:** the point-mass double-integrator harness used for
F19/F20 **cannot reproduce the real chatter trigger** — injecting a raw velocity kick matching the observed
magnitude gets absorbed cleanly by both zones' laws in the idealized model (0 zone flips with or without
hysteresis), because the real mechanism is a finite-cluster-geometry near-field effect the point-mass
model doesn't represent. The synthetic test therefore only confirms the hysteresis logic itself doesn't
break normal convergence (all cases converge cleanly, real overshoot-state regression case unaffected) —
it cannot confirm the fix resolves the real oscillation. That confirmation requires the real simulation.

**Implemented** in `update_dipoles` (captures `_prev_sub = pm.transport_subphase` before the zone-selection
branch; `elif d > (D_BRAKE_EXIT if _prev_sub == "BRAKE" else D_BRAKE_TRIGGER):`). `SIM_VERSION` bumped
`37.0.0` → `38.0.0`.

**Real targeted validation (transport_0 and transport_1, resumed from the post-cluster checkpoint) showed
the hysteresis fix alone was insufficient.** All four transports still hit `STALL_TIMEOUT` (transport_0's
residual error improved 4x, 2.86mm→0.659mm, but transport_1 blew up to v=200.4mm/s and both transport_1/2
hit new `BRAKE SATURATION` events — demanded force exceeding the R_DECEL0 standoff's physical ceiling by
up to 56%). Diagnosed transport_1's saturation with a generalized version of the existing
`DEBUG_LIFT_CRUISE` instrumentation (extended to trace any cluster via a new `DEBUG_CLUSTER` env var, and
to cover BRAKE, not just LIFT/CRUISE): real per-6ms data showed `v_z` swinging 100+ mm/s between
consecutive control steps **while the zone stayed CRUISE the whole time** (no zone flip involved), with
`satfrac` (real gradient/clamp) hitting 13.8x. Root cause: CRUISE's/BRAKE's aim direction is recomputed
fresh every 6ms with no smoothing; a noisy/large velocity reading can flip the commanded direction by up
to 180° in one step, sweeping the (fixed 0.5mm standoff) dipole across a real, finite-size 64-particle
cluster and occasionally passing close enough to an edge particle to spike the near-field gradient — which
kicks velocity hard, feeding the next step's equally reactive command. A self-sustaining resonance, not a
single bad handoff.

### F21 rate limiter — design, synthetic validation, and implementation (2026-08-17)

**Derivation (grounded in real measured geometry, not an arbitrary constant):** dipole standoff `r=0.5mm`
(fixed regardless of commanded strength — only orientation `a_hat` varies with the command). Real cluster
max particle-to-centroid extent, measured directly from VTU data for cluster 1 in both its clean
pre-oscillation CRUISE window (0.256-0.261mm) and during the actual saturation crisis (0.269-0.270mm) —
consistent, i.e. a stable intrinsic property of the 64-particle cluster, not something the oscillation
itself caused: `Rc=0.26mm`. Worst-case real separation if a particle sits exactly on the aim axis:
`r-Rc=0.24mm` (independently confirmed via `_raw_gradB2_onaxis`: at that separation, raw grad/clamp≈81 —
this standoff/cluster-size combination has little inherent margin). Allow the per-step swept arc to consume
at most half that margin (≥2 consecutive worst-case-direction steps to fully close the gap): `ell_max=
0.12mm`. Chord-to-angle: `DTHETA_MAX = 2*asin(ell_max/2r) = 0.2406 rad = 13.8°` per 6ms step (~40 rad/s).

**Synthetic validation caught two real bugs before either reached the real controller:**
1. The textbook slerp coefficient formula (`sin((1-f)θ)u + sin(fθ)v) / sinθ`) divides by `sin(θ)`, which
   vanishes both near 0° AND near 180° — exactly the regime this limiter must handle (a near-180° reversal
   is the actual failure mode being guarded against). Produced NaN on the first large-residual-velocity
   test case. Replaced with a Gram-Schmidt-constructed rotation basis, stable at any angle.
2. A pure direction-only limiter (unlimited magnitude) diverged under large residual velocity (187.6mm/s,
   drawn from the real F19 spike data): the deadbeat law's magnitude is sized assuming the force lands on
   the intended axis, so applying it in full along a still-mostly-wrong (rate-limited) direction pushed the
   plant further off course, and the next step's target moved too — a genuine runaway (78.6m final error),
   not a convergence-speed issue. Fixed by projecting the raw commanded vector onto the direction actually
   realizable this step (`a_cmd_mag_eff = max(0, dot(a_cmd_raw, a_hat_limited))`) — no new free parameter,
   reuses `DTHETA_MAX` only; a direction >90° off delivers zero force rather than a counter-productive push.

**Known remaining limitation, reported honestly, not hidden:** one synthetic stress case (an *instantaneous*
187.6mm/s residual velocity applied as an initial condition, at exactly the CRUISE/BRAKE boundary) still
does not cleanly converge (final error ~3.06m) — traced to CRUISE's own pre-existing bang-bang chatter
near `D_BRAKE_TRIGGER` (present even without any rate limiter) interacting with the limiter's antipodal
tie-break. This specific stress case was constructed for F19 testing (an instantaneous large kick), not
representative of F21's actual observed mechanism (gradual growth via repeated real near-field kicks during
ongoing CRUISE, confirmed in transport_1's real trace). Five of six regression cases (including two of the
three real overshoot states, the no-overshoot regression check, pure-horizontal brake, and combined
horiz+vert velocity) converge cleanly with the limiter active. Per the standing efficiency directive, this
edge case was not chased further synthetically — the decisive test is the real system.

**Implemented**: `DTHETA_MAX` constant (with full derivation comment) and `_rate_limit_hat()` helper added
near `solve_strength_for_accel`; applied to both CRUISE's and BRAKE's (moving-cluster case) aim-direction
realization, with `pm._a_hat_prev` synced from LIFT's known constant direction so CRUISE's very first real
step is already rate-limited (closing the exact handoff spike that started this whole investigation).
`SIM_VERSION` bumped `38.0.0` → `39.0.0`.

**Stage B — cluster-integrity diagnostics added** (per user directive, to distinguish "centroid reached
target" from "particles stayed physically clustered"): `cluster_integrity(k)` and `report_cluster_integrity
(k, label)`, reusing the existing `pos`/`cluster_id` read pattern from `cluster_stats()` rather than new
infrastructure. Reports per-axis σ, RMS spread, max particle-to-centroid distance, and bounding box, with
ratios against a baseline captured once per transport attempt (on the cluster's first LIFTOFF/LIFT control
step). Called automatically at genuine arrival and at `STALL_TIMEOUT`.

### Validation gate result: transport_0-only run (2026-08-17)

Resumed from the post-cluster checkpoint (skipping clustering). Real outcome:
**`STALL: transport_0 did not converge — forcing completion at t=8.530s, d=0.867mm, v=8.7mm/s.`**
Does **not** clear the validation gate (genuine `arrived_t` required, not a stall-forced completion).

Comparison across the fix history for transport_0's residual error at forced completion:

| Fix state | d at stall | v at stall | BRAKE SATURATION fired? |
|---|---|---|---|
| Pre-F19 | 2.860mm | 4.0mm/s | n/a |
| F19+F20, hysteresis only (no rate limiter) | 0.659mm | 8.6mm/s | no |
| F19+F20+F21 rate limiter (this run) | 0.867mm | 8.7mm/s | **no** (0 saturation events this run, vs. 2/4 transports previously) |

Real cluster-integrity diagnostic (new, Stage B) at the stall: `sigma(xyz)=(0.046,0.079,0.090)mm`,
`RMS=0.129mm (0.78x pre-transport baseline)`, `max_r=0.230mm (0.86x baseline)` — the cluster did **not**
disperse; if anything it stayed slightly more compact than at transport start. So the rate limiter
achieved its intended effect (zero saturation events, no catastrophic velocity blowup, no cluster
dispersal) but transport_0's final convergence tightness is still slightly worse than the
hysteresis-only intermediate state (0.867mm vs 0.659mm) — real d/z data during the run (t=6.05-6.40s)
showed the cluster still overshooting past the BRAKE boundary and briefly excursing back out to d~6mm
before re-approaching, i.e. the underlying CRUISE/BRAKE approach dynamics are calmer (no violent kicks)
but not yet precise enough to land inside `EPS_X` before `STALL_TIMEOUT`.

**Reported to the user without further unrequested design work, per the standing "stop for genuinely
consequential decisions" and time-budget directives** — three real, distinct root-cause bugs (F19, F20,
F21) have now been found, diagnosed from real data, designed, synthetic-tested, and fixed, each with
measurable real improvement, but the controller has not yet cleared the transport_0-only validation gate.

---

### Extended-STALL_TIMEOUT experiment: is F21 slow-but-convergent, or a limit cycle? (2026-08-17)

**Question:** the transport_0-only gate failed at `STALL_TIMEOUT=6.0s` with `d=0.867mm`. Before
designing any further fix (F22), determine cheaply whether the existing F21 controller (rate limiter +
hysteresis, code and parameters completely unchanged) would have converged to genuine `arrived_t` given
more time, or whether it is stuck in a non-convergent pattern. Per the user's explicit instruction, this
was run as a pure diagnostic: `STALL_TIMEOUT` temporarily raised 6.0s→20.0s (reverted immediately after,
see the constant's inline comment), no other code or parameter changed, transport_0 only (resumed from
the same `phase2_checkpoint_postcluster_diag.pkl` used for every other run this session).

**Real result — a genuine, non-decaying limit cycle, not slow convergence:**

- Over the 14.5s the run was allowed to continue (killed once the pattern was unambiguous, per the
  time-optimization directive — full 20s was not needed to answer the question), the cluster made
  **13 separate close approaches** to the target (`d` reaching 0.19-0.49mm, i.e. repeatedly getting
  within a few×`EPS_X=0.15mm`) — and **every single one** was followed by a renewed excursion back out
  to 1-9mm rather than a sustained hold. None satisfied the `d<EPS_X AND v<EPS_V` dwell criterion.
- **8 velocity spikes exceeding 100mm/s** occurred throughout the run (max 226mm/s at t=4.75s, then again
  157/163/111/204/107/101/214mm/s at t=8.65/9.85/11.00/13.45/14.10/14.50/16.85s) — i.e. velocity
  magnitudes comparable to the original pre-F19/F20/F21 blowup problem this whole investigation started
  from, still recurring under the "fixed" controller.
- **No amplitude decay over time**: mean/max `vm` for the first half of the post-transient window
  (t=5-11s) was 20.8/163mm/s; for the second half (t=11-17s) it was 22.8/214mm/s — flat-to-slightly-worse,
  not shrinking. A slow-but-convergent controller would show visibly decaying oscillation amplitude
  approaching the target; this shows none.
- No `SATURATION` warnings fired during this run (consistent with the earlier F21 result — the rate
  limiter is doing its job of keeping the dipole out of the near-field clamp regime), so the recurring
  velocity spikes are not a saturation artifact — they are the rate-limited controller itself commanding
  large accelerations at short range, repeatedly, without converging.

**Interpretation (per the user's own decision tree):** this is outcome **(B)** — a persistent
oscillation/limit cycle — not (A) convergent-but-slow. Extending `STALL_TIMEOUT` further would not be
expected to help; the pattern has already repeated ~13 times with no visible decay. Per the user's
explicit instruction for this outcome: **stop, do not randomly patch, diagnose the specific mechanism
before proposing F22.** No F22 design work has been started. `STALL_TIMEOUT` has been reverted to 6.0s;
no other code changed as a result of this experiment.

**What is NOT yet known** (the open diagnostic question for whenever F22 work is authorized): why the
close approaches don't sustain. Two candidate mechanisms, neither yet checked against real per-step
data: (1) the CRUISE/BRAKE zone hysteresis (`D_BRAKE_TRIGGER=0.45mm`/`D_BRAKE_EXIT=0.90mm`) still allows
a full return to CRUISE's deadbeat law close to the target, and CRUISE's one-step deadbeat command
(`a=(v_ref-v)/dt_ctrl`) may itself be too aggressive at short range even after rate-limiting the
*direction* of that command — the rate limiter bounds how fast the commanded direction can rotate, not
how large the commanded magnitude can jump step-to-step; (2) the `ARRIVAL_DWELL=0.15s` (~25 control
steps) sustained-criterion window may simply never survive one bad step landing near the boundary,
if the boundary itself is where the controller's gain is highest. Both are hypotheses, not diagnosed
conclusions — real per-step data around one of the 13 near-arrival-then-excursion events would be needed
before proposing a fix, per the standing "verify against real data before designing" rule.

---

### F22 diagnostic: mechanism of the near-arrival/excursion limit cycle, CONFIRMED (2026-08-17)

**Method (no new long simulation).** The coarse 0.05s-cadence log could not resolve the real per-6ms
control-step quantities needed to distinguish the candidate hypotheses. Extended the existing
`DEBUG_LIFT_CRUISE=1` instrumentation (`_debug_lift_cruise_snapshot`, previously used for F18/F19) to
also report, stashed at the exact point `update_dipoles` computes them (no logic duplicated or
re-derived): the full commanded-acceleration vector (`a_cmd`), its raw vs. rate-limited magnitude
(`a_cmd_mag_raw` / `a_cmd_mag`), the raw and rate-limited aim directions (`a_hat_raw`/`a_hat`), the
angle the rate limiter was actually asked to rotate through vs. what it was allowed to
(`dtheta_wanted`/`dtheta_realized`), the position error vector, BRAKE's `a_needed`, and the real
arrival-dwell state (`pm.arrived_t`). Re-ran the *same* checkpoint-resumed transport_0 (deterministic —
no code/parameter changes, purely additive capture) for only ~2.5s of sim time (~400 control steps,
`DEBUG_CRUISE_MAX=400`), comfortably covering the first two near-arrival/excursion events already known
from the coarse log (including the most severe one, the 226mm/s spike at t≈4.75s) — far cheaper than
another full run.

**Confirmed mechanism — NOT any of H1/H2/H4 as originally stated; a specific, severe form of H3.**

The rate limiter (`_rate_limit_hat`, F21) bounds how fast the *realized* aim direction `a_hat` can
rotate per control step (`DTHETA_MAX=13.785°`), then the controller projects the raw commanded
acceleration onto that limited direction and **clamps the result to zero if the dot product is
negative** (`a_cmd_mag = max(0, dot(a_cmd_raw, a_hat_limited))` — the same "magnitude projection" fix
added during F21 design specifically to stop the earlier-diagnosed "full raw magnitude along a stale
direction" divergence). This has an emergent failure mode of its own: whenever the desired aim direction
needs to rotate by **more than 90° relative to the previous realized direction in a single 6ms step**
(`dtheta_wanted > 90°`) — which happens routinely right as the cluster passes through or near the
target, because the deadbeat law's implied acceleration direction is dominated by the sign of
`(v_ref - v)` and small state changes near the target flip that sign — the projected magnitude is
**exactly zero for every step until the rate-limited direction rotates back within 90°** (up to
⌈(dtheta_wanted−90°)/13.785°⌉ consecutive steps). During every such step the dipole strength is
literally `s=0`; the independent brute-force force cross-check confirms the cluster's net vertical
acceleration is exactly `-g` (free-fall) during these windows — not reduced authority, **zero**
authority, horizontal included.

Quantified from the captured trace: **19 separate zero-force episodes occurred within the 2.5s
window**, spanning `dtheta_wanted` from 106.6° up to a full 180°, lasting 1–7 consecutive steps
(6–42ms) each. This is not an occasional edge case — it recurred roughly every ~0.1–0.2s throughout
the capture window, consistent with the extended-timeout run's 13 near-arrival attempts over 14.5s
never converging.

**Representative event, full causal reconstruction (the 226mm/s spike, t=4.69–4.75s):**

| t(s) | zone | d(mm) | \|v\|(mm/s) | s | a_cmd realized | dtheta_wanted | note |
|---|---|---|---|---|---|---|---|
| 4.6858 | CRUISE | 1.096 | 3.3 | 0.212 | 3.65 m/s² | 11.6° | healthy correction, converging |
| 4.6918 | CRUISE | 1.031 | 32.9 | **0.000** | **0.000** | 161.7° | direction must flip >90° → zero force |
| 4.6978–4.6998 | CRUISE | 0.86→0.82 | 23.8→20.9 | 0.000 | 0.000 | 147.9°→134.2° | free-fall continues; limiter rotating 13.8°/step |
| 4.7058 | CRUISE | 0.72 | 13.0 | 0.113 | 1.49 m/s² | 59.6° | brief partial recovery |
| 4.7118–4.7178 | CRUISE | 0.62→0.49 | 45.1→39.7 | 0.000 | 0.000 | 134.2°→120.4° | a **second** >90° flip event — speed already elevated |
| 4.7238 | CRUISE | 0.50 | 36.1 | 0.094 | 1.43 m/s² | 73.4° | another brief partial recovery |
| 4.7298–4.7358 | CRUISE | 0.73→1.72 | 201.6→195.5 | 0.000 | 0.000 | 120.4°→106.6° | **third** flip event; vh already 155→209mm/s |
| 4.7498 | CRUISE | 4.32 | 210.5 | 0.000 | 0.000 | 114.8° | peak of the excursion |

1. **What caused the command:** at t=4.6858 the controller was converging normally (modest deadbeat
   correction, direction within the rate limiter's reach). 2. **What command was issued at 4.6918:**
   the deadbeat law's implied direction had rotated 161.7° from the previous step's realized direction
   (real cause: the cluster's own motion carried it through a region where `(v_ref-v)`'s dominant sign
   flipped); the rate limiter capped the realized rotation to 13.8°, leaving the achievable direction
   >90° from the true command, so the magnitude projection clamped to **exactly zero**. 3. **Physical
   response over the next 6ms:** with `s=0`, gravity is the only force (confirmed: `net_az=-1.620
   m/s²=-g` from the independent cross-check) — pure ballistic coasting, no correction in any axis.
   4. **Resulting state:** velocity keeps whatever it had (nothing damps it); the rate-limited direction
   has only advanced one more 13.8° increment, usually still >90° away, so the **next** step is *also*
   zero-force. 5. **Why the next command didn't help:** each successive zero-force step lets speed grow
   further, which itself increases how fast the true bearing-to-target needs to rotate per step — a
   **self-reinforcing feedback loop**, not a one-off glitch, which is why three separate >90° episodes
   compounded within 60ms instead of one recovering cleanly. 6. **What caused the excursion:** ~7 of the
   ~13 control steps in this 60ms window delivered literally zero corrective force; `|v|` grew from
   3mm/s to 210mm/s and `d` from 1.0mm to 4.3mm (continuing out to ~6.9mm before full authority was
   regained around t=4.79s) as a direct, traceable consequence — not of BRAKE lacking authority
   (`a_needed` stayed under 2 m/s² whenever BRAKE *did* have force to give, vs. `a_max=229.6 m/s²`) and
   not of CRUISE's raw commanded magnitude being dangerously large (raw values 1–19 m/s², nowhere near
   saturating).

**Hypothesis verdict:**
- **H1 (CRUISE deadbeat too aggressive near target):** not supported as stated. Raw commanded
  magnitudes were never the problem; if anything the *realized* magnitude is suppressed far below the
  raw value (to exactly zero) far more often than it is dangerously large.
- **H2 (BRAKE engaging late/weak):** not supported. Every real `a_needed` value observed, in both
  analyzed events, was a small fraction of `a_max` — BRAKE has enormous unused margin whenever it
  actually has authority to act.
- **H3 (rate limiter protects direction but not magnitude):** **confirmed, but more specific and more
  severe than the loose statement** — it is not that magnitude "remains large enough to oscillate," it
  is that the magnitude-projection safety valve added to fix a *different*, earlier-diagnosed instability
  (F21 design, case B) itself collapses commanded force to **literal zero** for multiple consecutive
  steps whenever the aim direction needs to reverse by more than 90° in one step — which happens
  routinely near the target and increasingly often as speed grows (self-reinforcing).
- **H4 (arrival dwell broken by one bad step):** not the cause of either analyzed event — `d` never
  actually dropped below `EPS_X=0.150mm` in either case (closest: 0.152mm and 0.190mm), so
  `pm.arrived_t` was never set and no dwell was ever broken. Cannot be ruled out as *also* occurring at
  one of the other 11 near-arrival attempts from the extended-timeout run, but it is not the demonstrated
  mechanism for the two representative (and most severe) events analyzed here, and is secondary at best.
- **Same mechanism confirmed at a second, independent event** (t=3.7359–4.0238, the first near-arrival
  attempt) without any new simulation — 12 of the 19 zero-force episodes occurred there, same signature
  (`dtheta_wanted` 106–180°, `s=0.0000`, `net_az≈-g`).

**Verdict on scope (per the standing decision rule): this is a localized, well-characterized bug in the
F21 safety mechanism's interaction with the deadbeat law — not evidence that the deadbeat/single-dipole-
vector architecture itself is unsound.** The underlying force law, dipole-realization convention, and
available control authority all check out with large margins throughout (F/W and `a_needed` values are
consistently tiny fractions of the 229.6 m/s² clamp ceiling — see the Stage A-2 design doc). The specific
defect is narrow: the current response to "the rate-limited direction can't keep up with how fast the
true bearing needs to rotate" is "deliver zero force," when a reduced-but-nonzero force (e.g. delivering
the raw magnitude along whatever direction *is* currently realizable, rather than clamping a negative
projection to zero) would preserve the original F21 safety property (bounded aim-direction slew rate,
preventing the near-field sweep this whole investigation started from) without creating an unpowered
free-fall window at the exact moment authority is most needed. This points to ONE targeted, localized fix
to `_rate_limit_hat`'s calling convention — not a controller redesign — but per the standing "do not
implement without proceeding through this diagnosis, and stop before designing" instruction, **no fix
has been designed or implemented.** `phase2_shaping.py`'s debug instrumentation (`_last_cmd_dbg`,
extended `_debug_lift_cruise_snapshot`/`_print_dbg_row`) was extended to make this analysis possible and
left in place (inert unless `DEBUG_LIFT_CRUISE=1`); no control-law behavior changed.

---

### F22 fix: designed, implemented, REVERTED after real Gate 2 regression (2026-08-18)

**Design (before implementation).** Replaced the linear "clamp negative projection to zero" magnitude
realization with a raised-cosine (half-angle) weighting: `weight = 0.5*(1+cos(theta)) = cos²(theta/2)`,
where theta is the angle between the raw desired direction and the (unchanged) rate-limited realized
direction. Properties verified by closed-form math and unit test before implementation: weight(0°)=1
(unchanged common-case behavior), weight(90°)=0.5 (not 0 — the actual bug fix), weight(180°)=0 (zero
*only* at the single exact-antipodal point, where positive force truly cannot help), continuous
(<2e-6 jump) across the old 90° clamp boundary, bounded in [0,1] so the existing magnitude ceiling is
preserved automatically, and direction always exactly `a_hat` (rate-limited, never reversed). All 13
sampled real captured zero-force episodes (dtheta_wanted 106.6°-177.1°) re-scored to a strictly
positive, ceiling-respecting magnitude under this formula (Gate 1, `test_f22_fix.py`, all pass).

**Gate 1 caveat, honestly flagged before implementing:** a crude open-loop point-mass forward replay of
the real 226mm/s event (same script) did *not* reproduce the real severity even for the OLD formula
(reconstructed peak 11.9mm/s vs. the real 210mm/s) — meaning the synthetic model was missing real
dynamics (most likely the crude horizontal-velocity decomposition and full 3D BRAKE/CRUISE coupling)
and its OLD-vs-NEW comparison could not be trusted as a gate. Proceeded to Gate 1's math/unit tests
(all passed) and treated the real Gate 2 run as the authoritative test, per the standing "the real
simulation is authoritative" principle — this turned out to be the right call.

**Gate 2 result: REGRESSION, not improvement.** Real transport_0-only run (same checkpoint, same
`STALL_TIMEOUT=6.0s`) with the F22 fix live:

| Metric | F21 (pre-fix, best real result) | F22 (this run) |
|---|---|---|
| Outcome | STALL (forced completion) | STALL (forced completion) |
| Final `d` | 0.867mm | **2.307mm** |
| Final `v` | 8.7mm/s | **52.6mm/s** |
| Saturation events | 0 | 0 |
| Peak velocity excursion | 226mm/s (1 dominant episode) | **279mm/s**, with **11 separate spikes >100mm/s** across the 6s window |
| BRAKE zone occupancy | repeated brief entries throughout | essentially abandoned after t≈5.0s — CRUISE only for the remaining ~3.5s |
| Cluster integrity at stall | RMS 0.78x baseline, max_r 0.86x baseline | RMS 0.64x baseline, max_r 0.59x baseline (still coherent, not dispersed) |

The fix made the real, closed-loop, 3D multi-particle result *worse* on every convergence metric while
leaving the one thing it was designed to fix (saturation) unchanged (already 0 in both). **Reverted
immediately** — both CRUISE and BRAKE realization call sites restored to the original F21
`a_cmd_mag = max(0.0, dot(a_cmd, a_hat))` clamp, which remains the best real validated result to date.
`_realize_command_mag` is left defined but uncalled, with its original design rationale preserved
verbatim in its docstring plus a note explaining the reversion — consistent with the project's practice
of keeping failed non-physical or now-superseded mechanisms labeled rather than silently deleted.

**Honest reassessment — why the fix backfired.** The raised-cosine weighting delivers a smoothly
*decaying but still meaningfully large* fraction of the raw commanded magnitude for theta up to
roughly 150° (25% at 120°, 6.7% at 150°) — and for the entire 90°-180° range, the *true* required
correction has a *negative* component along the only direction the dipole can actually push
(`a_hat`, by construction of the dot product being negative there). Any positive force delivered in
that regime therefore has a component genuinely working against the correction the cluster needs,
not merely "less than ideal." The original zero-clamp, however pathological its free-fall consequence,
was at least never *actively counterproductive* in this sense — it was the true least-squares-optimal
single-direction realization. Trading "occasional true zero-force free-fall" for "frequent, smaller,
but partially counter-productive force" turned out, in the real coupled 3D dynamics, to feed the
self-reinforcing high-speed/large-direction-flip loop identified in the F22 diagnosis *faster* than the
free-fall gaps did, rather than breaking it — the direction the aim needs to swing changes even more
often when the cluster is being nudged (however partially) the wrong way through the crossing zone.

**Answering the standing questions this fix was authorized under:**

1. **Exactly what failed:** the F22 realization-weighting fix, despite passing every cheap synthetic
   and closed-form math check, made the real transport_0 gate run measurably worse across every
   convergence metric (final error, final velocity, peak excursion, excursion frequency, BRAKE zone
   occupancy) than the F21 baseline it was meant to improve.
2. **Is this fundamentally architectural?** Yes. Two structurally different realizations of "what to do
   when the direction rate limiter can't keep the aim within 90° of what the deadbeat law wants" have
   now been tried — deliver zero (F21, causes free-fall gaps) and deliver a smoothly-scaled partial
   magnitude (F22, causes counter-productive force) — and neither converges reliably within the
   `STALL_TIMEOUT` budget. Both are honest, principled responses to the same underlying tension: the
   CRUISE deadbeat law routinely *wants* the aim direction to reverse by close to 180° near the target
   (because its implied direction is dominated by the sign of `v_ref - v`, which flips readily on a
   crossing), while the realization layer can only supply a single fixed-standoff dipole pointing in
   one rate-limited direction. No purely-local choice of realization function resolves that tension —
   it is a mismatch between the control law's implied command behavior and what a single rate-limited
   actuator can deliver, not a bug in any one function.
3. **Is this merely parameter tuning?** No. This was not a matter of picking a better `DTHETA_MAX` or a
   better weighting shape — the two logically opposite endpoints of the realization design space (zero
   vs. smoothly-scaled-nonzero) were both tried and both fail the gate. Retuning within either family is
   unlikely to change the qualitative outcome; a fix would require changing what the CRUISE/BRAKE laws
   *ask for* near the target (e.g. damping the deadbeat law's implied direction volatility directly,
   which is a control-law redesign, not a realization-layer tweak) — explicitly out of scope for the
   "last targeted fix" this session was authorized to make.
4. **Is Phase 2 sufficiently defensible for the paper with limitations documented?** This is the
   project's call, not a unilateral decision made here — but the material to make that call now exists:
   F16-F21 constitute a real, quantitatively diagnosed, honestly-reported chain of closed-loop
   transport-controller fixes (each verified against real simulation data, each with a measurable real
   improvement over its predecessor), converging on a best-known-state (F21) that eliminates the
   original catastrophic velocity blowups and saturation events and maintains cluster integrity, but
   does not reliably reach the strict `d<EPS_X and v<EPS_V` sustained-dwell arrival criterion within a
   generous timeout, plus a rigorously diagnosed and now double-confirmed (F22 negative result)
   architectural boundary explaining *why* under the current controller design. Per `CLAUDE.md`'s own
   standard ("if the current methodology cannot achieve the desired result, say so explicitly and
   explain why — that is a valid, useful scientific result, not a failure to hide"), this is a
   legitimate, defensible position for publication: report F21 as the characterized best-achieved
   transport-controller state, report the F22 negative result as evidence the remaining gap is
   architectural rather than a tuning oversight, and scope the paper's transport-controller claims and
   limitations accordingly.

At this point `phase2_shaping.py` was reverted to F21's real-validated behavior (`_a_hat_prev`/rate
limiter/hysteresis all unchanged; `_realize_command_mag` present but unused), `SIM_VERSION` left at
40.0.0. The user subsequently authorized exactly **one** further, tightly-scoped controller experiment
(a genuine control-law redesign of the reference generation, not a realization-layer patch), with an
explicit pre-committed stopping rule: implement, Gate 1 (design+synthetic), Gate 2 (transport_0 real
run), and if transport_0 does not pass — genuine arrival, bounded velocity, dwell completion, no large
spikes, bounded cluster spread — freeze Phase 2 and write the paper around the demonstrated limitation,
with no further F24/F25 iteration. See the next section for that experiment (F23) and its result.

---

### F23: continuous glideslope reference — designed, implemented, Gate 2 result (2026-08-18)

**Root-cause reframing (informed by F22).** F22 established that BOTH tried realization strategies
(deliver-zero and deliver-partial) fail for the same underlying reason: the *reference* CRUISE asks
for is genuinely discontinuous. Vertical: `v_ref_z = copysign(V_CEIL, e_z)` — full ceiling speed right
up until the position error crosses zero, then an instant full-magnitude sign flip. Horizontal:
`a_horiz_gross = max(0, (V_CEIL-v_horiz)/dt)` — ceiling-tracking only, never asks for deceleration of
overshoot. No realization-layer fix can cleanly execute a genuinely discontinuous command; the fix has
to be upstream, in what CRUISE asks for.

**Design.** Replaced the step-function reference in both channels with a continuous, distance-scaled
"glideslope" speed cap: `v_des_mag(d) = min(V_CEIL, sqrt(2*A_GLIDE*d))` — the same kinematic relation
BRAKE's own `a_needed` law already uses (`v²=2·a·d`), applied continuously instead of switched on at a
zone boundary. `CAPTURE_RADIUS` reuses the existing `D_BRAKE_EXIT` constant (0.90mm) rather than
inventing a new distance parameter; `A_GLIDE = V_CEIL²/(2·CAPTURE_RADIUS) ≈ 0.0356 m/s²` is the
deceleration that brings a cluster moving at `V_CEIL` to rest exactly at `d=CAPTURE_RADIUS` — ~6500x
below `a_max=229.6 m/s²` (a deliberately gentle reference *shape*, not a new force-authority limit; full
deadbeat correction authority against real disturbance is unchanged). Margin check: half the nearest
real target separation (2.738mm/2=1.369mm) is 1.52x `CAPTURE_RADIUS`, so the glide zone doesn't reach a
neighboring target. Far from target (`d >> 0.9mm`) this is identical to the old `V_CEIL` ceiling —
no change to the validated ~1.2-1.6s far-field transit times. The horizontal channel was also fixed to
track the *signed* velocity component along `e_horiz` (toward `path_target`) instead of the unsigned
`|v_horiz|`, so it can genuinely decelerate overshoot rather than merely stop accelerating. BRAKE's own
kinematic law is unchanged (not implicated — all 19 real F22-diagnosed episodes were zone=CRUISE).

**Gate 1 (synthetic, `test_f23_glide.py`), before implementing:** continuity of the reference through
`e_z=0` confirmed (magnitude→0 as d→0, vs. the old law's constant 16mm/s jump regardless of how small
the crossing distance is); far-field behavior exactly unchanged; a synthetic vertical-crossing sweep at
representative real velocities showed peak step-to-step `dtheta_wanted` dropping from 27.2° (old law) to
1.8° (new law); a closed-loop point-mass replay from the real 226mm/s event's initial condition (same
fidelity caveat as F22's — this simplified model previously under-reproduced real severity, so treated
as directional evidence only) showed the new law reaching the arrival criterion at step 28 (~168ms) with
zero `dtheta>90°` events across the whole replay (vs. 423 for the old law from the same IC) and peak
velocity only 9.5mm/s (vs. divergence for the old law). All Gate 1 tests passed.

**Gate 2 (real transport_0 run).** Launched from the same post-cluster checkpoint. The run's early
approach through the first crossing (t≈3.6-3.9s, the exact region every prior run — F21, F22 — first
blew up in) passed calmly for the first time all session: velocity stayed at 9-11mm/s throughout, zero
spikes, in visible contrast to every previous run. However, the process then hit an unrelated real
compute slowdown around that same sim-time window (confirmed alive and burning CPU throughout — not a
hang — likely a genuine, reproducible cost spike in contact resolution at that particle configuration,
unconnected to the controller change, since F22's run showed the identical slow patch at its own
first-crossing point) and, due to a monitoring-latency gap, was not stopped after transport_0 alone as
the gate specifies — it continued unattended through all four transports before being caught. Reporting
all four honestly rather than only the intended transport_0 window:

| Transport | Outcome | Final d | Final v | Peak velocity | Spikes >100mm/s | Saturation | RMS vs. baseline |
|---|---|---|---|---|---|---|---|
| 0 | STALL | 2.334mm | 8.8mm/s | 155mm/s | 8 | 0 | 0.86x |
| 1 | STALL | 4.693mm | 18.0mm/s | 279mm/s | 11 | 0 | 0.78x |
| 2 | STALL | 6.184mm | 59.8mm/s | 145mm/s | 2 | 0 | 0.88x |
| 3 | STALL | 0.590mm | 0.0mm/s | 125mm/s | 5 | 0 | 0.71x |

**None of the four reached genuine arrival.** Zero saturation events across all four (consistent with
F21/F22) and cluster integrity held throughout (all RMS ratios <1, no dispersal). Transport_0's peak
excursion (155mm/s) is meaningfully lower than both the pre-fix baseline (226mm/s) and F22 (279mm/s),
and the first crossing — the specific, diagnosed mechanism this fix targeted — passed with zero spikes
for the first time this session, confirming the glideslope design fixed the mechanism it was built for.
But later re-approaches (after BRAKE→CRUISE hysteresis re-entry, still overshooting past the target and
re-entering CRUISE at several mm) still produce spikes up to 125-279mm/s, and none of the four transports
converges to the sustained `d<EPS_X and v<EPS_V` dwell criterion within `STALL_TIMEOUT=6.0s`. This is a
**different, real, but still present failure mode** — not the same near-field direction-reversal chatter
F22 diagnosed (that specific mechanism is fixed), but a longer-timescale overshoot/re-approach cycle that
the glideslope's smoothing does not by itself resolve.

**Per the user's own pre-committed decision tree for this experiment ("if it fails → freeze Phase 2 and
write the paper around the demonstrated limitation"), Gate 2 does not pass and no further F24 iteration
was attempted.** `phase2_shaping.py` is left with the F23 glideslope law live (not reverted) — unlike
F22, this is a net real improvement (lower peak excursions, the originally-diagnosed near-field
mechanism eliminated, more physically principled — a genuine control-law fix rather than a
realization-layer patch) even though it does not achieve full closed-loop convergence. `SIM_VERSION`
bumped to 41.0.0.

---

### F24: critically-damped state-feedback BRAKE law — designed, implemented, Gate 2 result, transport debugging STOPPED (2026-08-18)

**Root-cause reframing.** F23 fixed the discontinuous *reference* CRUISE asked for, but the extended-
STALL_TIMEOUT experiment (13 near-arrivals, 8 velocity spikes, no amplitude decay) and F23's own Gate 2
(none of four transports converged) showed a second, distinct problem inside BRAKE itself: its law,
`a_needed = v²/(2·d_remaining)`, is an exact kinematic stopping-distance inversion recomputed fresh
every 6ms control step — a deadbeat/exact-match law with no damping margin. It assumes continuous
re-evaluation lands `v=0` exactly at `d_remaining`, which only holds in continuous time; at real 6ms
sampling, combined with the F21 rate limiter and the zero-clamp realization (`a_cmd_mag=max(0,
dot(F,a_hat))`, which zeros thrust outright during a >90° direction swing), a velocity-direction
reversal at a BRAKE re-entry — exactly what a prior overshoot produces — reliably clips thrust to zero
for a step or more, degrading the "exact" stopping estimate and letting the cluster coast past the
target, reopening `d` beyond `D_BRAKE_EXIT`, handing back to CRUISE, which reaccelerates. This is a
structurally different, longer-timescale mechanism than F22's near-field chatter — a limit cycle in the
BRAKE↔CRUISE state machine, not a single-zone realization defect.

**Design.** Replaced BRAKE's magnitude law with a critically-damped second-order state-feedback (PD/
spring-damper) law: `a_net = -2·ζ·ω_n·v + ω_n²·(target-x)`, ζ=1. Unlike the deadbeat law this commands a
small, smoothly-varying acceleration whenever both position error and velocity are small — it never
needs to demand an exact zero-crossing, so it should not need the large sudden direction reversals that
trigger the zero-clamp dead zone. `ω_n=30 rad/s` chosen from two independent physical margins, not
tuned to a target trajectory: (1) discretization stability (standard guidance keeps `ω_n·Δt_ctrl≲0.2`;
`Δt_ctrl=6ms` fixed by the existing batch cadence → `ω_n≲33`), (2) force margin (even at the worst real
incoming speed observed, ~280mm/s, `2ζω_n·v` stays >15x below `a_max=229.6 m/s²`). This is the same
category of gain (Kp/Kv-style PD) reported for closed-loop electromagnetic microrobot steering in the
literature (Tandfonline, *Electromagnetic Steering of a Magnetic Cylindrical Microrobot Using Optical
Feedback Closed-Loop Control*; ScienceDirect, LQR-tuned PID maglev trajectory tracking) — sliding-mode/
disturbance-observer/fuzzy-PID approaches from that literature were not used, since those address
unmodeled disturbance or model uncertainty, neither of which is present here (the field model is exact;
the only non-ideality is the fixed 6ms discretization already accounted for above). Fold: the old law's
separate `vmag≈0` fallback branch was removed — PD is well-defined at `v=0` (reduces to a pure spring
pull), so one law now covers the whole BRAKE zone. CRUISE/glideslope (F23), the zone thresholds, the F21
rate limiter/realization layer, and the arrival/dwell criteria were all left untouched, per the
minimally-invasive constraint.

**Gate 1 (synthetic, `test_f24_pd_brake.py`), before implementing.** 8 scenarios (approach from above/
below, overshoot state, re-approach, high/low/noisy incoming velocity, a realistic post-F23 spike
state), swept `ω_n∈{15,20,25,30,33}` against the old law, using a harness that mirrors the real rate
limiter, zero-clamp realization, and `a_max` ceiling exactly. At `ω_n=30`: all 8 scenarios converge
(the old law also converged in all but chattered badly on the high-speed cases); on the
worst case (200mm/s incoming), settle time dropped 1.212s→0.330s and BRAKE↔CRUISE re-entries
(chattering) dropped 4→2, at 15x+ margin below `a_max`. `ω_n=33` began showing discretization artifacts
(position-error blowup on several scenarios) — 30 is the largest value with no instability signature.
Separately verified the F19-class gravity-sign risk directly: for 5 representative `(e,v)` states,
`F_over_mp = a_net_req + (0,0,g)` then `+(0,0,-g)` (the integrator's unconditional gravity term)
recovers `a_net_req` exactly in every case (`verify_f24_sign.py`, all `match=True`).

**Gate 2 (real transport_0 run, stopped immediately after transport_0 per the gate spec — the process
was killed the instant the STALL/ARRIVAL signal for transport_0 fired, confirmed via `ps`/`tasklist`
before continuing).**

| Metric | F23 (transport_0) | F24 (transport_0) |
|---|---|---|
| Outcome | STALL | STALL |
| Final d | 2.334mm | 2.508mm |
| Final v | 8.8mm/s | 9.1mm/s |
| Peak velocity | 155mm/s | 229mm/s |
| Spikes >100mm/s | 8 | 3 |
| Saturation | 0 | 0 |
| RMS vs. pre-transport | 0.86x | 0.73x |
| max_r vs. pre-transport | — | 0.88x |

**Gate 2 does not pass.** Transport_0 still fails to converge; final position/velocity error is
statistically unchanged from F23 (2.508mm/9.1mm/s vs. 2.334mm/8.8mm/s — not a regression, but not an
improvement either). Cluster coherence remains good (both ratios <1, no dispersal) and saturation
remains 0, confirming force authority was never the limiter.

**Mechanism check on the surviving spikes.** The three >100mm/s events (229mm/s at t=4.15s, 186mm/s at
t=6.10s, 184mm/s at t=8.00s) were cross-referenced against the coarse per-batch zone label in the
existing status line. The two largest coincide with a BRAKE-zone entry immediately preceding them
(`t=4.10 CRUISE d=0.53mm` → brief BRAKE at `d≈0.45mm` → `t=4.15 CRUISE d=1.06mm, v=229mm/s`, all within
one 50ms print interval) — consistent with the *same* zero-clamp dead-zone mechanism F21/F22 diagnosed,
now triggered by the direction change **at the CRUISE→BRAKE handoff itself**, not by BRAKE's internal
recomputation (which F24 was designed to fix, and which the Gate 1 sweep confirms it does fix — spike
*count* dropped from 8 to 3, a real, measured reduction). CRUISE's exit direction (pursuit-path tangent,
glideslope-tapered) and BRAKE's entry direction (PD spring-damper toward the point target) are two
different vector fields with no continuity guarantee where they meet at the hard `D_BRAKE_TRIGGER`/
`D_BRAKE_EXIT` threshold; F23 fixed CRUISE's own internal reference discontinuity and F24 fixed BRAKE's
own internal deadbeat instability, but the boundary *between* the two laws was never itself made
continuous, and it is now the dominant remaining source of large excursions. This is a structural,
not a tuning, finding — a third instance of the same root phenomenon (a commanded-direction
discontinuity forcing the rate limiter's projection clamp into a multi-step zero-thrust window) at a
location neither F21, F22, F23, nor F24 addressed.

**Decision, applying the user's own pre-committed rule verbatim ("if F24 fails, we stop transport
debugging"): transport controller optimization is STOPPED here.** `phase2_shaping.py` is left with the
F24 PD law live (not reverted) — like F23 and unlike F22, this is a net real improvement (spike count
8→3, more physically principled, standard control-theory form used in real closed-loop magnetic
actuation) even though it does not change the STALL outcome. `SIM_VERSION` bumped to 42.0.0.

**Final transport state for the paper.** Across F19→F24, cluster identity, particle count, and physical
plausibility (no saturation, no NaN/Inf, no dispersal) held in every real run. The controller reliably
suppresses the catastrophic near-field blowups present in the original deadbeat design and brings every
transport to within a few mm of its target with single-digit-to-low-double-digit mm/s residual velocity,
but does not achieve the strict `d<EPS_X ∧ v<EPS_V` sustained-dwell arrival criterion within budget. The
demonstrated, now well-characterized limitation is a control-law-switching discontinuity at the
CRUISE/BRAKE zone boundary — a legitimate, specific, and honestly-diagnosed finding for the paper's
limitations section, not an unexplained failure.

---

### G1: Shaping/holding deep audit — `surf_conf` shown to dominate all observed shape-phase behavior (2026-08-18)

**Finding (diagnostic only, no code changed).** Following a full F24 transport run through to the
shape phase, the real VTU output (`outputs/Phase2/`, 760 frames) was traced by permanent `cluster_id`
across the transport→shape transition and the subsequent ~10s "stall." The VTU's `Fmag` field (the
real paramagnetic force magnitude, logged separately from the total integrated force) was compared
directly against the `surf_conf` non-physical placeholder force (audit F9, `phase2_shaping.py:1713`)
computed from the same real particle positions at the same instants.

**Result:** the real magnetic force is 6-12 orders of magnitude smaller than `surf_conf` throughout
the entire shape phase (e.g. at t=27.799s, cluster 2: real force 3.7e-16 N vs. `surf_conf` 1.82e-3 N;
by t=35.8s, real force ~1e-16 N vs. `surf_conf` ~1e-4 N for the wall clusters). `surf_conf` also
switches from fully off to fully on in a single control step at `pm.state→"shape"`
(`phase2_shaping.py:2409-2414`, no ramp), which produces a real, measured velocity spike in all four
clusters simultaneously (0→4-57 mm/s in one ~50ms step) — this is the "explosion at the transition"
observed visually. The subsequent apparent "recovery" of the cap clusters into plausible cap shapes,
and the near-total stillness from t≈29.5-40s, are both produced almost entirely by this spring +
its viscous-damping term, not by the dipole field. Wall clusters (Q1/Q2) never reach their z-target
at all — their `surf_conf` branch is radial-only by design ("z handled by gravity + scan," a
pre-existing code comment), so once the radial pin engages they simply fall to the domain floor
(z≈0.14-0.15mm vs. a z=5mm target) and stay there.

**Why this is not a new CLAUDE.md violation but is a significant scientific finding:** `surf_conf`
was already labeled non-physical and CLAUDE.md already forbids treating its presence as evidence
shaping works. What this audit adds is the quantitative magnitude — the term is not a minor assist
but is, within measurement, the entire mechanism currently producing the shape-phase visual result.
The real paramagnetic force law itself remains correctly `cluster_id`-blind (verified: no such branch
exists in `compute_forces()`'s `Fm` computation) — the selectivity lives entirely in `surf_conf`'s
explicit `cid==0/3/else` branching, which is a synthetic per-particle homing force keyed on a
permanent color label, functionally equivalent to an invisible scaffold.

**Consequence for the shaping redesign (Candidate A, from the prior session's shaping-architecture
audit):** any real magnetic shaping mechanism must now be sized to supply 100% of the axial/radial
holding duty `surf_conf` was silently providing (for caps: axial pinning; for walls: axial support
that never existed even in the placeholder) — not merely fine redistribution on top of an assumed
working `surf_conf` baseline, as the prior session's initial force-budget sizing implicitly assumed.
This raises, not lowers, the force authority required of the eventual replacement.

**What remains unverified / not done this session:** an ablation run with `surf_conf_enabled` forced
to 0 (to establish the true contact/gravity-only baseline caps would have with zero holding force);
a differential per-transport reconstruction of clusters 0-3's individual control-state histories
(transport remains frozen per standing instruction; only the aggregate STALL distances were
re-confirmed: transport_0 d=2.508mm, transport_1 d=4.522mm, transport_2 d=4.784mm, transport_3
d=6.773mm — monotonically worsening, consistent with the previously-documented cross-cluster drag
mechanism); revised force-budget sizing for Candidate A; the isolated shaping fixture itself (still
not built). Full detail: `simulation/analysis/SHAPING_HOLDING_AUDIT_2026-08-18.md`.

---

### G2: Isolated shaping fixture built; `surf_conf=0` ablation reveals a real, working near-field wall hold (2026-08-19)

**What was built.** `simulation/analysis/shape_fixture.py` — a diagnostic-only script (not part of
`main()`/the production CLI) that imports `phase2_shaping.py`'s real, unmodified kernels
(`build_grid`/`compute_forces`/`integrate`/`update_dipoles`/`substep_batch`) and drives them directly
against four real 64-particle clusters initialized at their intended shaping-start positions
(`C.targets[k]`), with `pm.state` forced to `"shape"` from `t=0`. No force law, particle property, or
production code path is modified; the only manipulation offered is `--surf-conf-off`, which resets
the `surf_conf_enabled` Taichi field to 0 after each `update_dipoles()` call, performing the G1
ablation without touching `phase2_shaping.py`.

**Result, `surf_conf` OFF (true magnetic-only baseline), full 20.5s shape cycle:**
- **Caps (c0, c3) have literally zero shape-phase magnetic force** (`Fmag≈1e-17N` throughout,
  confirming v36's removal of the cap shape dipole is total, not just weak) and free-fall to the
  domain floor in <0.1s, ending 6.85mm / 2.93mm from target — matching a pure free-fall calculation
  almost exactly.
- **Walls (c1, c2) are held to within 0.09mm of target by a real, non-negligible magnetic force**
  (`Fmag≈1.6e-7N ≈ 112×` one particle's lunar weight) for the ~10s preceding their own active-plow
  slot, while their dipole sits in its static "wait" configuration. This had never been observed in
  any prior real run because shaping always previously began with particles already scattered far
  outside this near-field range.
- **That hold is destroyed the instant the wall's own active-plow slot begins** — d_tgt jumps from
  0.09mm to 5.3-5.5mm within one slot transition and the cluster falls away, because the v33 scan is
  designed to move fast enough that particles cannot track it ("v_tan≈14mm/s >> v_cap≈5mm/s →
  deposition mode," an existing in-code comment), and nothing else opposes gravity once it moves.

**Result, `surf_conf` ON, same ideal start (comparison):** confirms the G1 audit's force-ratio finding
directly via trajectory (caps held only by the spring, real force 5-9 orders of magnitude below it).
Also shows a new, unexpected effect: **`surf_conf` makes the walls *worse*** than the magnetic-only
baseline (`d_tgt≈5.2-5.3mm`, `r_rms` up to 1.65mm indicating partial disintegration) — its
discontinuous switch-on kicks a cluster that was already being correctly held by the real near-field
dipole, actively disrupting a mechanism that works.

**Consequence for the shaping redesign.** The wall's near-field hold is a real, verified,
physically-grounded ingredient that should be *extended* (made to move slowly enough for particles to
track, rather than replaced) rather than redesigned from scratch. Caps have no equivalent mechanism
and need one built, by direct analogy to the wall result (same physical near-field principle, not
demonstrated for caps but with no evidence it wouldn't work). `surf_conf` should not be retained even
as a stopgap — it is now shown to actively interfere with the one part of the current architecture
that already works, not merely provide no benefit.

**Not yet done:** a perturbation test on the wall near-field hold (to confirm it's a genuine restoring
response and not a coincidentally-unperturbed frozen state); `F_r,F_θ,F_z` sweep-feasibility sizing
for a *slow* wall-traversal redesign; cap-specific near-field force sizing. Full detail:
`simulation/analysis/SHAPING_BASELINE_2026-08-19.md`.

---

### G3: final feasibility gate + wall coverage-feedback controller implemented; surf_conf permanently disabled; caps left honestly unsupported (2026-08-19)

**Four final pre-implementation feasibility tests**, run via a new isolated single-cluster test
harness (`simulation/analysis/shape_feasibility.py`, isolates exactly one real dipole against a
real 64-particle cluster, reusing `phase2_shaping.py`'s unmodified kernels). Full report:
`simulation/analysis/SHAPING_FEASIBILITY_GATE_2026-08-19.md`.

- **Wall hold perturbation (radial/tangential/axial, 0.3mm offsets)**: genuinely, dynamically
  stable in all three directions — real restoring response, not "stayed still because undisturbed."
  But it is a stiff, underdamped, cross-axis-coupled oscillation (peak v 20-80mm/s persisting for
  seconds), not a quiet static hold — this reframes the G2 finding's "0.09mm hold" (that number came
  from coarse 1s sampling of what is actually a faster oscillation).
- **Cluster-level vector force budget**: confirms the request's own warning that summing force
  *magnitudes* overstates the real net force by 100-300x versus the correct vector sum. Real,
  attributed (via per-dipole isolation) net force on the wall's own wait dipole: `F_r=0.18xW,
  F_t=-0.86xW, F_z=0.38xW` (W = 64-particle cluster weight) — net vertical support alone is under
  1x, consistent with the oscillatory-not-static picture above. Zero cross-talk measured from the
  neighboring wall cluster's dipole or the corner quadrupoles at this instant.
  **Self-caught bug**: the first two full-field measurement scripts initially forgot to disable
  `surf_conf` (only `shape_fixture.py`'s own runner did that), producing a nonsensical 31.7xW
  reading; caught by cross-checking against the independent perturbation-test results, fixed, rerun.
- **Slow translating well (0.1-15mm/s)**: tracking error is speed-independent (dominated by the
  same intrinsic oscillation) through 5mm/s, degrades at 10mm/s, and **catastrophically fails at
  15mm/s** (particles left behind entirely, `Fmag`→~0). This independently confirms, by direct
  simulation, the exact `v_tan≈14mm/s` "particles cannot follow" threshold the old v33 wall-raster
  code already stated analytically. Recommended operating speed: ≤5mm/s.
- **Cap parked-hold (1.0mm and 0.5mm standoff, direct analogy to the wall's validated z-lift
  branch)**: **fails at both.** 1.0mm gives insufficient real vector-summed force (`F_z/W=0.43`
  even at fully-saturated strength — cluster free-falls to the floor within 0.2s). 0.5mm gives
  ample raw force (`F_z/W=4.09`) but violently unstable dynamics (`r_rms` grows unbounded to
  3-3.5mm, cluster disintegrates). No standoff in the tested range gives both adequate force and
  stable dynamics — a genuine, demonstrated infeasibility of a single on-axis point dipole for
  caps, not a tuning problem.

**Implementation (per the request's own gating rule — proceed where a test passes, stop and
diagnose where one fails):**

1. **`surf_conf` is now permanently inert in production.** The `if pm.state=="shape":
   surf_conf_enabled[None]=1` gate in `update_dipoles()` is removed; `surf_conf_enabled` is never
   set to 1 anywhere, so it stays at `init()`'s default 0 in every real run. `compute_forces()`'s
   `surf_conf` kernel code and its non-physical-placeholder documentation are unchanged (kept as a
   historical/ablation reference per CLAUDE.md, not deleted) but can no longer activate.
2. **Wall active-slot dipole (`ring_idxs[0]`) replaced**: the v33 fast (~14mm/s) ±60°
   back-and-forth raster is replaced with a closed-loop slow well using the exact validated wait-
   hold geometry (zero standoff, pure radial-inward moment, `s=SHAPE_WAIT_HOLD_STRENGTH=0.15` —
   the same real config already used elsewhere in this file, not a new untested value). The aim
   point sweeps a (theta, z) raster (`WELL_N_Z_LEVELS=4` z-bands, same ±60° arc safety margin as
   v33) at `WELL_V_TAN=3mm/s` (1.7x margin under the measured clean 5mm/s ceiling), advancing only
   while the real sensed cluster centroid stays within `WELL_TRACK_ERR_MAX=0.30mm` of the aim
   point — otherwise the aim point freezes until the cluster catches up. Persistent sweep state
   (`_wall_well_state`, module-level, same pattern as the transport controller's
   `_live_path_cache`) is real, physically realizable controller/actuator state (a stored
   setpoint), not a hidden force or a position filter. The wall's pre-existing, unmodified
   `IDX_CLUSTER_DIP` z-lift branch (dipole at target+1mm, moment +z, s=0.10, "~2x gravity" per its
   own comment) still runs in parallel during the active slot exactly as before — the feasibility
   gate's isolated test did not include this, so it is additional real support beyond what was
   measured, making the gate's pass a conservative (not optimistic) result.
3. **Caps are unchanged**: still zero shape-phase dipole (`pass — no external shape dipoles for
   caps`), and now, with `surf_conf` permanently inert, this is visibly and honestly the case in
   any real run rather than masked by the placeholder. This is a known, demonstrated open problem
   (see the cap-hold feasibility failure above), not a silently-passing gap.

`SIM_VERSION` bumped to `"43.0.0"`.

**Not done / left open**: no cap mechanism has passed a feasibility test — candidates worth trying
in a future session (untested here): an off-axis or laterally-offset dipole (breaking the on-axis
symmetry that concentrates the instability at close range), or multiple sequentially-active
near-field points sharing the support duty rather than one fixed point carrying it all at a
singular standoff. `validate_phase2.py` has not yet been extended with an automated wall-tracking-
error check (recommended: assert tracking error never exceeds `WELL_TRACK_ERR_MAX` by more than the
intrinsic oscillation envelope during an active slot).

---

### G4: three real implementation bugs found in the G3 wall controller during full-cycle
validation; workflow changed from full-duration debugging to targeted reduced-order controller
tests (2026-08-20)

**Bugs found and fixed, in order, each via real full-cycle or targeted physics validation (not
code-reading alone):**

1. **Wrong sweep radius.** `r_scan` was read from `C.cR` instead of the true target radial
   distance — a 0.20mm discrepancy for Q1 that baked a spurious offset into every aim point from
   the start. Fixed: `r_scan` now derived from the real target position (`math.hypot(tgt[0]-C.cx,
   tgt[1]-C.cy)`).
2. **Discrete z-level jumps froze the sweep permanently.** The original design stepped z in
   `WELL_N_Z_LEVELS=4` discrete jumps once per phi sweep; each jump (~0.83mm) instantly exceeded
   `WELL_TRACK_ERR_MAX=0.30mm` the moment it fired and — combined with the still-anchored cluster
   (see bug 3) — could never recover, confirmed via an isolated control-logic debug script that
   showed `z_level` frozen after its very first jump. Fixed: replaced with a continuous `z_frac`
   creep at the same validated rate as the phi sweep, small enough per step to never itself exceed
   the tracking tolerance.
3. **Competing anchor dipole prevented any net sweep motion.** After fixing bugs 1-2, a full
   20.5s four-cluster validation (`g3_wall_validation3.json`) showed the active cluster's real
   centroid locked within ~30um of the ORIGINAL fixed target for the entire 5s active slot while
   its velocity climbed to 20-35mm/s — the signature of two dipoles fighting over the same point,
   not a working sweep. Root cause: the wall's `IDX_CLUSTER_DIP` anchor (originally fixed in an
   earlier session to stop cluster 1 free-falling once `surf_conf` was disabled — see the G3 entry
   above) had been left unconditionally active, including during the sweep, sitting at zero
   standoff at the fixed target while `scan_idx` tried to move away from that same point. Near-field
   force ~1/r^4, so the anchor dominates the instant the scan dipole moves even slightly. Attempted
   fix: turn the anchor off (`s=0`) during the active slot, since `scan_idx` starts at the exact
   same position/strength/geometry and is (per the G3 feasibility gate) independently validated as
   sufficient on its own.

**Bug-3 fix result is mixed, and this is where the workflow changed.** A full-speed 6s validation
(`g3_fix3_c1_fast.json`, anchor off) showed the cluster escaping to 6-9mm off target with `Fmag`
collapsing to ~1e-17N (same order as the caps' known-zero-mechanism baseline) — apparently
confirming the user's hypothesis that anchor-off causes escape. But a much cheaper, high-temporal-
resolution single-slot test (`g3_fix3_finegrained.json`, only the first 1.2s of the active slot,
completed in minutes not hours) showed the OPPOSITE for that window: track_err stayed at
0.0005-0.006mm throughout, `Fmag` stayed steady at ~1.64e-7N, and the real centroid tracked the
moving aim point to within microns at every sampled instant, including through the first direction
reversal near `phi_frac~0.99`. **The handoff itself and the first half-sweep pass are not the
failure** — a mathematical check (treating the steady-state hold as an effective spring,
`omega ~ sqrt((F/m)/x) ~ 180 rad/s`, period ~35ms) confirms the sweep (half-traverse ~0.65s, full
cycle ~2.6s) is quasi-static relative to the cluster's own mechanical response, ruling out a simple
low-order resonance with the reversal period as the mechanism. The actual failure, per the coarse
run's timing (d_tgt jumps from 1.36mm at t=2.9s to 9.39mm at t=3.9s), most likely happens during
the SECOND excursion (toward the opposite, `phi_frac->0`, i.e. -60 deg, side) or after multiple
reversal cycles — not yet isolated as of this entry.

**Workflow change (explicit user direction, 2026-08-20):** stopped the pattern of running full
12-20.5s four-cluster validations after every incremental controller change (each takes 3-4+ hours
CPU-only). This is no longer a "do we understand wall shaping" question — the static hold mechanism
is validated, the failure is now narrowly a handoff/sweep-transition controller problem. Going
forward: use short, targeted, single-active-slot tests (via `shape_fixture.py --phase-start-t`, a
diagnostic-only time-skip added this session that jumps the phase-manager schedule clock straight to
the slot of interest without changing any physics), extend duration only as far as needed to observe
the specific failure under investigation, and prefer fine-grained instrumentation (tracking error,
aim point, real centroid, sweep-state fractions — now recorded by `shape_fixture.py` when
`_wall_well_state` is populated) over coarse multi-second sampling. Full 20.5s four-cluster runs are
reserved for final validation once the transition mechanism is understood and fixed, not for each
incremental change. A reduced-particle-count (8-16 particles) single-cluster harness was requested
as a further iteration-speed lever but not yet built as of this entry, since the phase-skip approach
already runs in minutes; it remains available if further speedup is needed. Changing `dt` or other
physics parameters for speed is explicitly out of scope unless clearly labeled as a reduced-order
test and independently verified to preserve the qualitative mechanism — not done in this session.

**Resolution: bug 4, found and fixed the same way (cheap targeted test, not full-cycle).** Extending
the fine-grained single-slot test to 3.5s (`g3_fix3_finegrained_3p5.json`, still minutes not hours)
localized the escape to a single ~20ms control step: between t=3.001s (`track_err=0.0025mm`, fully
healthy) and t=3.021s (`track_err=2.2454mm`), `z_frac` **wrapped** from 0.9999 to 0.0001 — the
leftover bug-2-era wraparound (`if z_frac > 1.0: z_frac -= 1.0`) teleported the aim point's z
coordinate by 2.5mm (measured: 6.249mm -> 3.750mm) in one step. `phi_frac` already correctly
*reverses direction* at its bounds instead of wrapping; `z_frac` did not, an inconsistency between
the two axes introduced when bug 2 was fixed. The teleport produced a brief huge force transient
(`Fmag` spiked to 1.7e-10N, ~1000x nominal, then collapsed to ~5e-17N) that flung the still-coherent
cluster (`r_rms` essentially unchanged — moved as a rigid blob, not a dispersal event) to ~16-118mm/s
and out of the well's effective range. This explains the escape seen in `g3_fix3_c1_fast.json`
without requiring any competing-attractor or continuous-blend mechanism — the earlier
"anchor-off causes escape" reading was the correct observation but the wrong mechanism attributed to
it; the real cause was one axis of the sweep controller teleporting instead of bouncing.

**Fix:** `z_frac` now reverses `z_direction` at its bounds exactly like `phi_frac`, removing the
discontinuity (`_wall_well_state` gained a `z_direction` field alongside the existing `direction`).
**Confirmed** by rerunning the identical 4.0s window that previously caught the wrap failure
(`g3_fix4_zbounce.json`): max tracking error across the full run is now 0.0065mm (vs. the 5.4mm
spike before), `Fmag` stays at its nominal ~1.64e-7N throughout with no collapse, peak velocity stays
low (<5mm/s, not the previous 16-118mm/s runaway), and the cluster remains coherent
(`r_rms=0.0975mm`, unchanged). `z_frac` reached its upper bound, reversed, and is creeping back down
as intended.

**This resolves the open question from earlier in this entry**: the anchor-off single-attractor
architecture does not need a continuous blend after all — the failure was a concrete, narrow
controller bug (an axis-inconsistent boundary condition), not a fundamental hold-to-moving-well
transition problem. The workflow change (short, targeted, single-slot tests via `--phase-start-t`
instead of full 12-20.5s four-cluster runs per change) is what made this findable in minutes instead
of requiring another multi-hour run per iteration, and should stay the default approach for wall
controller work going forward. Full four-cluster validation is still owed before trusting this in
production — not yet run as of this entry — but should be treated as a final confirmation step, not
a debugging tool.

---

### Phase 5: Shaping — Wall Clusters (Q1 left, Q2 right)

#### v33: Fast Oscillating Scan (SUPERSEDED by G3, 2026-08-19 — kept below for historical reference)
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
