# REGO PROJECT: COMPLETE AGENT CONTEXT

**Read this entire file before touching any code. It contains everything needed to understand the project, its history, and the current problem.**

---

## 1. What Is REGO?

REGO simulates autonomous magnetic field-driven assembly of lunar regolith particles into a hollow cylinder. The idea is that on the Moon or Mars, loose granular material (regolith) could be shaped into structural components using controlled external magnetic fields, without any physical contact or traditional manufacturing.

**Headline concept:** Paramagnetic particles seek B² maxima. By shaping external field gradients, you control where they go.

**Publication goal:** An inverse-design framework — given a target geometry, compute the field sequence needed to assemble particles into it.

---

## 2. Physical System

### Particles
| Property | Value |
|----------|-------|
| Count N | 256 |
| Radius R | 30 μm |
| Density ρ | 7800 kg/m³ (iron) |
| Mass mp | 8.82 × 10⁻¹⁰ kg |
| Susceptibility χ | 0.15 |
| Saturation Msat | 2 × 10⁵ A/m |

### Target Geometry
| Property | Value |
|----------|-------|
| Cylinder radius cR | 1.667 mm (= L/6) |
| Cylinder height cH | 4 mm |
| Domain size L | 10 mm |
| Domain center | (cx, cy) = (5, 5, 5) mm |
| Top cap z | z_hi = cz + cH/2 = 7.0 mm |
| Bottom cap z | z_lo = cz - cH/2 = 3.0 mm |
| Gravity | g = 1.62 m/s² (lunar) |

### Four Clusters (64 particles each)
| ID | Cluster | Target Position |
|----|---------|----------------|
| 0 (Q0) | Top cap | (5, 5, 7.2) mm |
| 1 (Q1) | Left wall | (3.13, 5, 5) mm |
| 2 (Q2) | Right wall | (6.87, 5, 5) mm |
| 3 (Q3) | Bottom cap | (5, 5, 2.8) mm |

**FIXED (Stage A audit, see Section 18):** Q0/Q3 transport targets used to be offset 0.2mm from the
z-spring equilibrium (7.2mm vs z_hi=7.0mm; 2.8mm vs z_lo=3.0mm), producing a ~70,000×gravity impulse
at shaping start. Targets now equal `z_hi`/`z_lo` exactly. The table above still shows the
historical (pre-fix) values for the record — see Section 18 for current values.

---

## 3. Core Physics

### Paramagnetic Force
```
F = (Vp · χ_eff / 2μ₀) · ∇B²
```
Particles seek B² maxima. The field is created by external dipoles (magnetic tweezers).

### Earnshaw's Theorem (Critical Constraint)
**∇²(B²) = 2|∇B|² ≥ 0 everywhere in a current-free region** (corrected — a Stage A audit found this
inequality stated backwards in earlier revisions of this file; the conclusion drawn from it was
still correct). B² is subharmonic, so its *static* maxima occur only at the field sources — there is
no static B² maximum in free space. Therefore:
- Static rings of dipoles create lobes, not rings
- Time-averaged rotating fields require ω_rot >> ω_mechanical (Nyquist)
- All previous "clever" cap shaping approaches violated Earnshaw

### Hertz-Mindlin Contact (HM)
Normal repulsion when two particles overlap by δ = (r_i + r_j) - r_ij:
```
F_n = (4/3) · E* · √R* · δ^1.5 − damping
F_t = Coulomb-limited tangential
E* = E_eff/(2(1-ν²)) = 1.067 × 10⁵ Pa
R* = R/2 = 15 μm
```
Contact force with δ = R (50% overlap): ~9 × 10⁻⁵ N per pair = 63,000 × gravity.

### Numerical Parameters
| Parameter | Value | Status |
|-----------|-------|--------|
| Timestep dt | 3 μs (was 8 μs) | Stage A: dt=8μs violated both the Rayleigh (≤6.4μs) and Hertz-contact-period (≤3.8μs) stability criteria; see Section 18 |
| Output interval | 50 ms | unchanged |
| v_cap (shape) | REMOVED | Stage A: hard velocity clip removed — see Section 18 |
| v_cap (transport) | REMOVED | Stage A: hard velocity clip removed — see Section 18 |
| Taichi backend | CUDA (f64) → CPU fallback | unchanged |

---

## 4. Simulation Architecture

### File: `phase2_shaping.py` (~2930 lines)

**Taichi fields (GPU):**
- `pos`, `vel`, `frc`, `fmag`: particle state (N=256 vectors)
- `dip_p`, `dip_m`, `dip_s`: dipole positions, moments, strengths (36 dipoles)
- `cluster_id`: which cluster each particle belongs to (fixed after initial assignment)
- `surf_conf_enabled`: flag (0/1) activating the surface confinement spring
- `v_cap`: current velocity cap (phase-dependent)
- `grid_cnt`, `grid_buf`: spatial hash grid for O(N) contact search

**Dipole Index Map (36 total):**
```
[0..7]   : CORNER QUADRUPOLES  (4 anti-aligned pairs, clustering/initial phases)
[8..11]  : TRANSPORT TRAPS     (IDX_CLUSTER_DIP = {0:8, 1:9, 2:10, 3:11})
[12..15] : HOLD_A              (hold ring, 4 dipoles)
[16..31] : SHAPE RING          (IDX_SHAPE, 16 shaping dipoles)
[32..35] : HOLD_B              (hold ring, 4 more dipoles)
```

**Each simulation batch:**
1. `build_grid()` — spatial hash
2. `compute_forces()` — gravity + magnetic + HM contact + wall contact + surf_conf spring
3. `integrate()` — semi-explicit Euler + v_cap clip + domain boundary bounce

---

## 5. Assembly Phases

### Phase 1: Clustering (t = 0 → 2.5s)
- 4 corner quadrupoles (anti-aligned pairs at corners of 10mm domain, z=-1.5mm)
- Far-field cancellation: B ∝ 1/r³ → 1/r⁵ with compensation dipole
- Creates B² maximum at domain center: all 256 particles cluster there
- Status: ✓ WORKING

### Phase 2: Transport (t = 2.5s → ~12s)
**Protocol:** Sequential (Q0 → Q1 → Q2 → Q3). One cluster at a time.

Each transport: single "magnetic tweezer" dipole (IDX_CLUSTER_DIP[k]) placed d_lead=0.3mm ahead of cluster along path, moment pointing toward cluster. v_cap=12mm/s.

Path: cosine arc from domain center to target position.

**Hold for completed clusters:** dipole at target position, s=0.5, moment along surface normal. Prevents gravity collapse during subsequent transports.

Status: ✓ WORKING (all 4 clusters transported to targets)

### Phase 3: Shaping Caps (Q0, Q3) — CURRENTLY BROKEN
See Section 7–9 for full analysis.

**Shape order:** `SHAPE_ORDER = [0, 3, 1, 2]` (caps first)
**Shape time:** 20s total, 5s per cluster slot

### Phase 4: Shaping Walls (Q1, Q2) — WORKING
Single scanning dipole on outer surface of cylinder:
- φ: ±60° triangle wave, 10 complete oscillations per slot
- z: cosine 4 cycles per slot
- r = cR + 0.3mm (just outside wall)
- Moment: radially inward + 45° upward tilt
- Speed >> v_cap → deposition mode (particles cannot follow)
Status: ✓ WORKING (v33)

### Phase 5: Hold
- 4-dipole square ring per cap cluster (IDX_HOLD_A/B)
- ONLY active during "hold" state (NOT during shape)
- OFF during shaping prevents azimuthal symmetry breaking
Status: ✓ DESIGNED (not yet validated in current context)

### Phase 6: Consolidation
- Separate file: `phase3_consolidation.py`
- Not the current focus

---

## 6. Key Constants (in phase2_shaping.py)

```python
# Surface confinement during shape phase
SURF_CONF_K       = 0.5       # N/m — z-spring to z_hi or z_lo
CAP_RADIAL_BIAS_K = 0.0       # N/m — outward radial bias (v36: REMOVED)
CAP_VISC_DAMP_TAU = 0.25      # s   — viscous damping time (xy AND z)

# Shaping strength parameters
SHAPE_ACTIVE_PLOW_STRENGTH = 0.80
SHAPE_WAIT_HOLD_STRENGTH   = 0.15
SHAPE_DONE_HOLD_STRENGTH   = 0.08

# Cap shape parameters (mostly legacy, not used in v36)
N_CAP_RING       = 8
CAP_RING_R_START = 0.15       # fraction of cR
CAP_RING_R_END   = 1.00       # fraction of cR

# Timing
SHAPE_TIME = 20.0             # total (5s per slot)
HOLD_TIME  = 2.5
v_cap during shape = 0.005 m/s = 5 mm/s
```

---

## 7. Cap Shaping — Full Failure History

**Status note (Stage A audit — see Section 18 for full detail):** the v36 failure signature
described below (Section 9) turned out to have four independent, verifiable causes beyond the
radial-bias oscillator analysis in this section — a broken contact-neighbor buffer that silently
disabled Hertz-Mindlin repulsion above 32 particles/cell, an absorbing zero-force state for
exactly-coincident particles, unphysical field magnitudes (up to 11 T from coil parameters that
physically produce millitesla fields), and a genuinely non-symmetric 2-dipole "hold ring." All four
are fixed as of Stage A. The geometric analysis in this section (2.1% 2D packing fraction, the
k_r anti-harmonic result, DBSCAN sub-clustering) remains valid background physics and is unaffected
by those fixes.

The top cap (Q0, z=7.2mm) and bottom cap (Q3, z=2.8mm) are the hardest to shape. 64 particles must spread from a dense 3D ball (r ≈ 0.15mm) to a monolayer covering the cap face (cR = 1.667mm).

**Geometry facts:**
- 3D packing at arrival: ~51% → dense ball, huge HM contacts
- 2D packing fraction on cap face: 64 × π×(30μm)² / π×(1.667mm)² = **2.1%**
- Once spread, particles rarely contact each other
- Contact is only spreading mechanism → fails after initial burst

### v18: Simultaneous radial lines
8 radial dipole arms for all clusters → all 4 clusters merged. Fixed by sequential shaping.

### v19: Sequential radial lines
One cluster at a time. But particles chased dipole → circular orbiting (chase behavior).

### v22–v28: Rotating triplet (time-averaged B²)
3 dipoles at 120° phase, rotating. Time-average is azimuthally symmetric.
**Failed:** ω_rot ≈ 15 rad/s < ω_mech ≈ 25 rad/s → particles see instantaneous max → epicyclic orbit.

### v29–v31: Static external ring
N=6 or 8 external dipoles in azimuth → ring attractor at ~0.7×r_ring.
**Failed:** Each static dipole IS its own attractor (Earnshaw). N dipoles → N B² maxima → N-lobe splitting.

### v32–v33: Single scanning dipole (plow)
One dipole sweeps Archimedean spiral over cap face, r = cR × local_frac, θ = 8 revolutions.
**Failed:** Particles chased the dipole. At outer radius, v_tan >> v_cap, so deposition mode should work, but non-uniform deposition.

### v34: Contact-repulsion only (no active dipoles)
Remove ALL cap shape dipoles. Rely on z-spring + HM contact burst.
**Observed:** Burst uneven, particles keep moving randomly, 2 sub-clusters form.
**Root cause:** No potential energy landscape → sub-clustering. Low 2D packing (2.1%) → no damping after burst.

### v35: Contact + weak radial bias + damping
Added CAP_RADIAL_BIAS_K = 0.05 N/m, CAP_VISC_DAMP_TAU = 0.5s.
**Failed:** k_r=0.05 creates ω_osc = √(k_r/mp) = 7,530 rad/s. Period T = 0.835ms. With τ=0.5s → 600 undamped oscillation cycles.
**The real mechanism:** With F_r = k_r × r (outward), the equation is m×r̈ = k_r×r. This is an ANTI-harmonic (unstable equilibrium). Solution: r(t) = r₀ × cosh(ω×t) × exp(-t/2τ). λ₁ ≈ +7528 s⁻¹. All particles fly to r=cR in < 0.4ms. 64 particles on ring → Smoluchowski coagulation → **two equal sub-clusters**.
**Note:** ANY positive k_r (no matter how small) drives ALL particles to the wall ring → Smoluchowski → 2 sub-clusters. This is fundamental mathematics, not a tuning issue.

### v36: Contact + damping, NO radial bias (CURRENT)
CAP_RADIAL_BIAS_K = 0.0, CAP_VISC_DAMP_TAU = 0.25s.
**Observed (current failure):** Still violent burst, still 2 sub-clusters, particles don't settle → see Section 9 for root cause.

---

## 8. Current Code State (v36) — compute_forces for caps

```python
# In compute_forces() kernel, for cid == 0 (Q0 top cap):
F[2] -= SURF_CONF_K * (pos[i][2] - C.z_hi)    # z-spring to z=7.0mm
if r_xy > 1e-12:
    _bias = CAP_RADIAL_BIAS_K * r_xy             # = 0.0 (k_r=0)
    F[0] += _bias * rx / r_xy
    F[1] += _bias * ry / r_xy
if r_xy > C.cR and r_xy > 1e-12:
    push = SURF_CONF_K * (r_xy - C.cR)           # inward spring at wall
    F[0] -= push * rx / r_xy
    F[1] -= push * ry / r_xy
_db = C.mp / CAP_VISC_DAMP_TAU                   # same τ for x, y, z
F[0] -= _db * vel[i][0]
F[1] -= _db * vel[i][1]
F[2] -= _db * vel[i][2]
```

**Active dipoles during Q0 shape slot:**
- Q0 cluster dipole: PARKED at (5,5,-5mm), s=0 → zero force ✓
- Q3 cluster dipole: PARKED at (5,5,-5mm), s=0 → zero force ✓
- Q1 wall anchor: at (3.13,5,5mm), m=(-x), s=0.15 → force on Q0 ≈ 0.023% gravity → negligible ✓
- Q2 wall anchor: at (6.87,5,5mm), m=(+x), s=0.15 → negligible ✓
- Corner dipoles: ALL OFF (pm.completed = {0,1,2,3}) ✓
- Hold rings (IDX_HOLD_A/B): s=0 (only active in "hold" state) ✓
- Shape ring (IDX_SHAPE): s=0 for all (cap uses `pass`) ✓

**Net magnetic force on Q0 particles during shape: ZERO.**

---

## 9. CURRENT FAILURE ROOT CAUSE ANALYSIS (v36)

### Root Cause 1: Transport-Target / z-Spring Mismatch (PRIMARY)

**The transport target for Q0 is z = 7.2mm. The z-spring equilibrium is z_hi = 7.0mm. This 0.2mm gap is the primary source of the violent burst.**

At shaping start, ALL 64 Q0 particles are at z ≈ 7.2mm. The z-spring immediately applies:
```
F_z = -SURF_CONF_K × (7.2mm - 7.0mm) = -0.5 × 0.0002 = -1 × 10⁻⁴ N downward
```
This is **70,000× lunar gravity** per particle. All 64 particles experience this simultaneously.

With v_cap = 5mm/s: particles rush downward from z=7.2mm to z=7.0mm in:
```
t = 0.2mm / 5mm/s = 0.04s
```
During this 0.04s, ALL particles move purely downward (v_z = v_cap = 5mm/s, v_xy = 0 because speed limit is saturated).

At z=7.0mm, they collide. 64 particles in a disk of r=0.15mm: 2D packing fraction = **2.56** (impossible, massive overlap). HM contact forces are ~9×10⁻⁵ N per pair. This creates a chaotic explosion in the xy plane.

**Why this is worse than a clean 2D burst:** Because the z-compression is asymmetric (all particles above z_hi pushed DOWN), the cluster has net downward momentum before hitting z_hi. The impact dynamics are NOT radially symmetric. Some fraction of particles receive net INWARD xy velocity from the collision geometry. These particles move toward center at v_cap = 5mm/s and stop near r = 0.

**The identical mismatch exists for Q3:** target z = 2.8mm, but z_lo = 3.0mm. Q3 particles at z=2.8mm < z_lo are pushed UP by z-spring with force +1×10⁻⁴ N.

### Root Cause 2: z-Spring Severely Underdamped

The viscous damping τ = 0.25s is applied uniformly to x, y, z directions. But the z-spring creates a resonance:
```
ω = √(SURF_CONF_K / mp) = √(0.5 / 8.82×10⁻¹⁰) = 23,810 rad/s
ζ = 1 / (2ω τ) = 1 / (2 × 23,810 × 0.25) = 8.4 × 10⁻⁵
```
This is **massively underdamped** (ζ << 1). Particles oscillate vertically at 23,810 rad/s for ~1,893 cycles before significant decay. The z-oscillation amplitude from v_z_burst = 5mm/s:
```
A_z = v_z / ω = 5×10⁻³ / 23810 = 2.1 × 10⁻⁷ m = 0.21 μm
```
This is tiny (0.7% of particle radius), so z-oscillations don't cause 3D contact coupling. But they DO mean the z-motion is essentially undamped → energy stored in z-oscillation is not removed → particles continue "jiggling" in z throughout the shape slot.

For critical damping of the z-oscillation: τ_z_crit = 1/(2ω) = 1/(2×23810) = **21 μs**. The current τ=0.25s is 12,000× too large for z-critical-damping.

### Root Cause 3: Sub-Clustering is Geometrically Inevitable

After the burst, particles land roughly on a circle at r ≈ 1.0–1.4mm. 64 particles on a circumference of 2π×1.25mm = 7.85mm:
```
Average arc spacing = 7.85mm / 64 = 0.123mm
DBSCAN epsilon = 4 × R = 0.12mm
```
Average spacing ≈ epsilon. Small random fluctuations in burst direction determine whether adjacent particles are "connected" in DBSCAN. Result: 2–4 random sub-clusters (arc segments). This is a geometric consequence of 2.1% packing, not a physical failure.

### Root Cause 4: No Mechanism to Spread Particles After Burst

After the burst, 2D packing = 2.1%. Particles rarely contact each other. No force acts on them in the xy plane (k_r=0, no magnetic forces). They stop wherever damping stops them (stopping distance = v_cap × τ = 1.25mm from burst origin).

With no spreading mechanism, the distribution is determined entirely by the chaotic burst geometry. Particles that happen to get inward velocity during the burst stay at small r permanently.

### Root Cause 5: Why "Collapse Back to Center"

After the burst:
1. Particles at outer r (≈1.25mm) have small residual z-oscillations
2. These cause tiny xy perturbations through contact geometry
3. The z-compression burst also leaves some particles with small inward velocity not yet fully damped
4. Over 5–10 simulation seconds, these particles drift inward (no outward force to stop them)
5. Result: particles at large r slowly migrate toward center

Additionally: after the initial burst, when particles stop, some have near-zero velocity in random directions. The z-underdamping gives them a constant small v_z → small v_xy through occasional contact → slow random walk → re-agglomeration at center (the "attractor" that's lowest entropy in the absence of any force field).

---

## 10. The Correct Fix (Not Yet Implemented)

### Fix 1: Align transport targets with z-spring equilibrium

Change `C.targets[0]` and `C.targets[3]` so the transport target z matches the z-spring equilibrium:
```python
# In C.targets:
[5.0e-3, 5.0e-3, C.z_hi],   # Q0: 7.0mm not 7.2mm
...
[5.0e-3, 5.0e-3, C.z_lo],   # Q3: 3.0mm not 2.8mm
```
Or, alternatively, ramp the z-spring from 0 → SURF_CONF_K over 0.3s at shaping start (smooth transition).

**Effect:** Symmetric 3D ball compression (top half pushed down, bottom half pushed up) → radially outward burst instead of downward-then-lateral chaos.

### Fix 2: Separate z and xy damping

Apply z-critical-damping separately from xy spreading damping:
```python
# z direction: critical damping (kills z-oscillation instantly)
_tau_z  = 2.1e-5   # s — τ for z: critically damps ω=23810 rad/s spring
_db_z   = C.mp / _tau_z
F[2]   -= _db_z * vel[i][2]

# xy direction: allow spreading (stop within disk)
_tau_xy = 0.25     # s — stop dist = v_cap × τ = 1.25mm < cR ✓
_db_xy  = C.mp / _tau_xy
F[0]   -= _db_xy * vel[i][0]
F[1]   -= _db_xy * vel[i][1]
```

### Fix 3: Accept 2D packing reality

64 particles in a 1.667mm disk = 2.1% packing. A true "monolayer" is geometrically impossible. The achievable goal is:
- Particles spread across the cap face (not all at center)
- Approximately uniform azimuthal distribution
- Particles at rest

Adjust DBSCAN epsilon to ε = 10R = 0.3mm to better reflect physical connectivity.

---

## 11. CLAUDE.md Rules (Must Follow)

The project has a `CLAUDE.md` with strict guidelines:
- **No magical forces** — every force must come from realistic physics
- **No artificial boundaries** — particles confined only by real forces
- **No violation of Earnshaw** — no static B² max in free space
- **External magnetic sources only** — all field sources OUTSIDE container
- **Calculate before coding** — work through physics analytically first
- **No patches** — fix root causes, not symptoms

---

## 12. Key Files

| File | Purpose |
|------|---------|
| `phase2_shaping.py` | Main simulation (~2930 lines) |
| `HISTORY.md` | Technical evolution log — update after every significant code change |
| `PAPER.md` | Research paper draft — update after every significant code change |
| `CLAUDE.md` | Agent guidelines and physics constraints |
| `CONTEXT.md` | This file |
| `phase3_consolidation.py` | Bonding/consolidation (separate) |

**Recurring task:** After EVERY significant code change, update both HISTORY.md and PAPER.md.

---

## 13. Diagnostics (Every 2 sim-seconds during shape)

The code prints diagnostics for cap clusters every 2s:
```
[TOP] r∈[min,max]mm μ=mean σ=std  z∈[min,max]mm tgt=7.00  v_μ=mm/s  subclusters=N
[BOT] r∈[min,max]mm ...
```

**Success criteria:**
- `subclusters = 1` — no sub-clustering
- `v_μ → 0` — particles at rest
- `r∈[0.3, 1.6]mm` — spread across cap face
- `z∈[6.99, 7.01]mm` — at cap face (±0.01mm)

**Current failure signature:**
```
[TOP] r∈[0.01, 1.60]mm μ≈0.3mm σ≈0.5mm  z∈[6.95, 7.05]mm  v_μ≈4mm/s  subclusters=2
```
(burst, chaotic, two sub-clusters, high velocities)

---

## 14. Mathematical Reference

### z-spring oscillation
```
ω = √(SURF_CONF_K / mp) = √(0.5 / 8.82×10⁻¹⁰) = 23,810 rad/s
T = 2π/ω = 0.264 ms
ζ = (mp/τ) / (2 × mp × ω) = 1/(2ωτ) = 1/(2×23810×0.25) = 8.4×10⁻⁵  ← massively underdamped
τ_crit = 1/(2ω) = 21 μs  ← τ needed for critical z-damping
```

### Radial bias (anti-harmonic)
```
F_r = k_r × r (any k_r > 0, outward)
m r̈ = k_r r
r(t) = r₀ cosh(ωt) exp(-t/2τ)
λ₁ ≈ √(k_r/m) >> 0  → exponential outward growth
```
ALL particles reach r = cR regardless of how small k_r is → ring → Smoluchowski → 2 sub-clusters. **k_r must stay at exactly 0.**

### Stopping distance (xy)
```
x(∞) = v₀ × τ = 5mm/s × 0.25s = 1.25mm  (≤ cR = 1.667mm ✓)
```

### 2D packing fraction
```
ρ_2D = N × πR² / (πcR²) = 64 × (30μm)² / (1667μm)² = 2.1%  ← sparse
```

### Initial z-compression force at shaping start
```
F_z = SURF_CONF_K × (z_target - z_hi) = 0.5 × 0.2mm = 1×10⁻⁴ N = 70,000 × gravity
```

---

## 15. Version Numbering Convention

The file is `phase2_shaping.py`. Changes are tracked by version labels in comments (v34, v35, v36...). The current cap shaping approach is **v36** (k_r=0, τ=0.25s). All previous approaches (v18–v35) failed. See HISTORY.md for full per-version details.

---

## 16. System Architecture — What Runs Where, and How Data Flows

REGO is not one program — it's a pipeline of independent Python processes that hand data to each other through files on disk (checkpoints, JSON, VTU/VTK). Nothing is orchestrated by a single "run everything" entrypoint; each stage is invoked by hand, in order, and reads whatever the previous stage left behind. This section describes that pipeline as it actually exists in the repo today (not how it should ideally work — see Section 17 for the redesign of the weakest link, Phase 4).

### 16.1 The five stages

```
phase0_baseline.py        phase1_cluster.py         phase2_shaping.py          phase3_consolidation.py
(early prototype,   →     (Phase 1: cluster   →     (Phase 2-5: transport, →   (Phase 6: sinter/bond
 not part of the           N=200 test particles      shape, hold — the          the assembled structure
 real pipeline)            at domain center;          MAIN simulation, ~3000     into a rigid part via
                           N=256 in the real run)     lines, N=256 particles,    thermal sulfur-wetting
                                                       36 dipoles)                kinetics)
                                                            │
                                                            ▼
                                                  outputs/phase2_checkpoint.pkl
                                                  outputs/shape_checkpoint.pkl
                                                  outputs/Phase2_v5_Fixed/*.vtu + .pvd
                                                            │
                              ┌─────────────────────────────┼─────────────────────────────┐
                              ▼                              ▼                             ▼
                    analysis/p2_extract.py          ParaView (open .pvd            analysis/jacobian_visual.py
                    (reads the .pkl checkpoints,      manually to inspect           analysis/dipoles_visualization.py
                     writes rego_sim_data.json)        particle trajectories)        (one-off diagnostic plots)
                              │
                              ▼
                    analysis/p2_metrics.py  ──▶  rego_metrics.json
                    (analytical energy/time/accuracy/stability/complexity
                     scoring, mirrors the physics constants in phase2_shaping.py
                     by hand — it does NOT import phase2_shaping.py)
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
          analysis/p2_graphs.py   analysis/p2_bo.py
          (plots from the JSON)   (Bayesian optimization over 10 phase-2
                                   control parameters — see 16.3)
```

`phase3_consolidation.py` runs independently of `phase2_shaping.py` — there is no automatic hand-off of the actual assembled particle positions from Phase 2 into Phase 3's initial condition. `analysis/p3_metrics.py`, `analysis/p3_graphs.py`, and `analysis/p3_bo.py` mirror the p2 analysis stack but for consolidation parameters (temperature, activator fraction, adhesion, etc.) using `results.json`/`energy_audit.json` written by `phase3_consolidation.py`.

`phase4_adaptive.py` is **not chained to this pipeline at all**. It's a standalone script with its own particle system, its own gravity/contact model, and its own hand-designed field sources — it doesn't read a Phase-2 checkpoint or feed Phase 3. See Section 17 for why, and what it should become.

`hardware/FourSolenoid/` and `hardware/SingleSolenoid/` are Arduino sketches for driving physical solenoids. They are **not currently connected to the simulation** — no script exports a dipole-moment schedule in a format the Arduino code consumes. That's the actual "sim → real hardware" link this project would eventually need, and today it doesn't exist.

`simulation/vendor/GeoTaichi/` is a vendored copy of a third-party DEM/MPM library. Grep confirms none of `phase0`–`phase4` import it — it's reference material / an unused dependency sitting in the tree, not part of the running system.

### 16.2 Execution model — what actually executes where

- **Taichi kernels (`@ti.kernel` / `@ti.func`)** — the inner physics loop (`build_grid`, `compute_forces`, `integrate` in Phase 2; analogous functions in Phase 0/1/4). These get JIT-compiled by Taichi to either CUDA (GPU) or CPU code at first call. `phase2_shaping.py` requests CUDA with f64 and falls back to CPU; `phase0_baseline.py`/`phase1_cluster.py`/`phase4_adaptive.py` are hardcoded to `ti.cpu`. This is the only part of the codebase doing "real work" at the µs-timestep (dt=8µs) granularity — everything else operates on the aggregated output of many of these steps.
- **Python host code** — owns the outer time loop, phase-state machine (clustering → transport → shape → hold), checkpoint save/load, VTU/PVD writing, and CLI argument parsing (`argparse`, e.g. `--resume`, `--skip-to-shape` in `phase2_shaping.py`). This runs single-threaded on CPU regardless of where the kernels execute.
- **Analysis scripts (`analysis/*.py`)** — run as separate, later invocations, entirely on CPU, with no Taichi dependency (they only touch pickled/JSON numbers). They are batch tools, not part of the simulation process.
- **`p3_bo.py` specifically launches subprocesses** — each BO trial does `subprocess` out to a fresh `phase3_consolidation.py` run with a trial's parameter set, then parses that run's `results.json`/`energy_audit.json` back in. This means Phase-3 BO trials are as slow as a real consolidation simulation (minutes), unlike Phase-2 BO (see below).

### 16.2a IMPORTANT — "Phase 1" the narrative concept vs. `phase1_cluster.py` the file are NOT the same code

This is a real, non-obvious source of confusion in the repo. The physics narrative in Section 5 ("Phase 1: Clustering, t=0→2.5s, 4 corner quadrupoles") describes the **`"cluster"` state inside `phase2_shaping.py`'s own `PhaseManager`** (Section 16.3 below) — the corner-quadrupole clustering that all 256 particles actually go through in a real run. The standalone file `phase1_cluster.py` is a **disconnected, earlier prototype**: it simulates a different particle count (N=200), a different config class, a single crude dipole source above the domain (not 4 anti-aligned corner pairs), and writes to `outputs/Phase1/` — a directory nothing else ever reads. Likewise `phase0_baseline.py` (`outputs/Phase0/`) is a legacy prototype, not stage 0 of a pipeline. **The real, currently-used pipeline is entirely inside `phase2_shaping.py` (clustering → transport → shape → hold) followed by the separate `phase3_consolidation.py`.** `phase0_baseline.py` and `phase1_cluster.py` are historical artifacts kept for reference, not inputs to anything downstream.

### 16.3 Phase 2 mechanics — the actual physics and control logic, literally

**Field model.** Every one of the 36 dipoles is a point magnetic dipole. The field at any point `r` is the exact superposition of the standard point-dipole formula for each active dipole `k` (`dip_s[k] > 0`):
```
B(r) = Σ_k (μ0/4π) / |r - p_k|³ · [3·(m_k·r̂_k)·r̂_k - m_k]      (B_field(), line 851)
```
where `p_k` is the dipole's position, `m_k = dip_m[k]·dip_s[k]` is its moment scaled by a 0-1 "strength" knob (this strength is how the control logic turns dipoles on/off/partially on smoothly). The force on a particle is the paramagnetic force `F = (Vp·χ_eff/2μ0)·∇(B²)`, which needs `∇(B²)`, not `B` — computed by `B_and_gradB2()` (line 874) using the analytical identity `∇(B²) = 2(B·∇)B = 2·Σ_k J_k^T·B`, where `J_k` is dipole `k`'s field Jacobian. This is a genuine engineering optimization: computing `∇(B²)` by finite differences would need 7 evaluations of `B_field` per particle (center + 6 perturbed points); the closed-form Jacobian contraction gets it in one pass over the 36 dipoles — for 256 particles × 36 dipoles × every 8µs step, this is the difference between a workable and unworkable simulation. The resulting gradient is then **soft-clamped** (`gB2 *= C/√(|gB2|²+C²)`) rather than hard-clamped, specifically so the force field stays continuous even very close to a dipole (a hard clamp would create a force discontinuity — literally a plane in space where force jumps — that acted as a hidden splitting mechanism in earlier versions).

**Saturation.** Real paramagnetic response saturates at high field (finite `Msat`). This is modeled as `χ_eff(B) = χ / cosh²(α)`, `α = χ·B/(μ0·Msat)` (line 942) — a smooth saturating function (equivalent to the derivative of a tanh-based Langevin-style saturation curve), so `χ_eff → χ` at low field and softens toward zero as `B` grows, rather than the paramagnetic force growing without bound near a dipole.

**Contact mechanics.** Particle-particle and particle-wall contact use Hertz-Mindlin: normal force is a nonlinear spring-dashpot, `Fn = kn·δ^1 - gn·vn` with `kn = (4/3)·E*·√(R*·δ)` (Hertzian stiffness scales with the square root of overlap `δ`) and dashpot `gn` derived from the restitution coefficient `e_n`; tangential force is a **Coulomb-limited** dashpot, `Ft = min(gt·|vt|, μf·Fn)` — i.e. tangential resistance grows linearly with slip velocity until it hits the friction cone, then clips (line 953-977). Contacts are found in O(N) per step via a uniform spatial hash grid (`build_grid`/`grid_cnt`/`grid_buf`, line 1027): each particle is binned into one of `HRES³` cells by `floor(pos/hcell)`, and `compute_forces` only checks the 3×3×3 = 27 neighboring cells instead of all 256 particles — this is what makes 8µs-resolution contact detection tractable at all.

**Integration.** Semi-implicit (symplectic) Euler: `vel += (F/mp)·dt`, then clip speed to a phase-dependent `v_cap`, then `pos += vel·dt` (line 1127). Domain-boundary contact is handled separately from Hertz-Mindlin wall contact as a simple hard reflection with restitution (`vel[ax] *= -e_n`) if a particle's position clips past `[R, L-R]` — a safety net under the softer `contact_wall` spring-dashpot.

**The phase state machine** (`PhaseManager`, line 1243) is a plain string-state FSM, ticked once per macro-step by `update(t, cluster_centroids)`: `settle → cluster → transport_0 → interlude_0 → transport_1 → interlude_1 → transport_2 → interlude_2 → transport_3 → shape → hold`. Transitions are time-gated (fixed durations like `T_CLUSTER_END`, `SHAPE_TIME`, `HOLD_TIME`) **except** the `transport_k` → `interlude_k` transition, which is event-gated: it fires when the cluster's centroid gets within `ARRIVAL_THRESHOLD` of its target **and stays there for 0.5s** (`arrived_t`/`handoff_t`), or unconditionally once a `TRANSPORT_BUDGET` timeout elapses — a real (if simple) feedback condition, not pure open-loop timing.

**Dipole control during transport** (`update_dipoles`, line 1395) uses one dipole per cluster for both leading and holding — a deliberate simplification versus earlier versions that used separate transport and hold dipoles (documented in HISTORY.md as the fix for a subclustering bug caused by competing attractors during handoff). Mechanically: the active cluster's dipole is placed at `path_waypoint + d_lead·tangent` (lead distance ahead of the cluster along the path's local tangent direction, **not** ahead of the cluster's own centroid — an earlier version leading from the centroid caused the cluster to chase its own induced attractor and permanently trail the path by `d_lead`). As transport progress passes 0.8, `d_lead` is smoothly cosine-ramped to zero so the dipole converges exactly onto the final target by progress=1.0. On arrival, the dipole's position and moment are interpolated (`slide_frac`) from the transport configuration to the hold configuration over a fixed 0.5s window, rather than snapping — avoiding a force discontinuity at the handoff instant.

**Dipole control during shaping** is different per cluster type and is where most of the documented failure history (Section 7-9, versions v18-v36) lives. Mechanically today: cap clusters (Q0/Q3) get **zero active magnetic shaping force** — their own cluster dipole is parked off-domain at `s=0`, and spreading is driven entirely by the `surf_conf` z-spring (pins the cluster to its target z-plane) plus Hertz-Mindlin contact repulsion plus explicit viscous damping (`F -= (mp/τ)·vel`), i.e. controlled collision-driven spreading, not field-driven spreading (`compute_forces`, line ~1059-1096). Wall clusters (Q1/Q2) instead get an active **scanning dipole** mechanism: a single dipole sweeps in position/azimuth faster than `v_cap`, so particles physically cannot follow it (`v_tan >> v_cap`) and are left behind in a trail as it passes — "deposition," not "chasing" (this specific failure/fix pattern, chasing vs. depositing, recurs across v19, v29-31, and v32-33 in HISTORY.md, and is the single biggest lesson in the whole codebase: **any dipole moving slower than the particles it's supposed to be positioning will just be chased in a circle, never left behind**).

### 16.4 Phase 3 mechanics — consolidation/bonding, literally

`phase3_consolidation.py` is a completely different physical regime: no active magnetic shaping, just holding the already-assembled structure together with a light confinement field while a **thermally-driven bonding process** runs. The literal mechanism: particles are coated with elemental sulfur (present in mare basalt at 0.1-0.3 wt%); heating past sulfur's melting point (119°C) lets it wet silicate grain contacts (low contact angle after Fe-oxide surface activation); cooling back below ~113°C re-solidifies the sulfur necks between grains, and those solid necks are the structural bond. Four coupled mechanisms make this actually happen in the sim:
1. **DMT contact adhesion** (`F_adh = 2π·R*·W_adh`, `W_adh=0.08 J/m²`) — keeps grains pressed together roughly 50% longer per collision than they otherwise would be, giving the sulfur meniscus time to start wetting instead of grains bouncing apart on contact.
2. **Arrhenius sulfur-wetting kinetics** — bond strength grows over time following a temperature-dependent rate (`bond_k0_S`, activation energy in the rate exponent); this is why `target_temp_C` matters so much: viscosity of molten sulfur drops sharply with temperature, so a few degrees materially changes how fast bonds mature within the fixed consolidation time budget.
3. **Electrostatic repulsion** (`F_Coulomb = k_e·Q²/d²`, from UV-photoelectric surface charging, `V_surface=5V`) — a small repulsive regularizer that prevents unphysical over-packing during confinement, independent of the bonding process itself.
4. **Bond strength estimate** — a corrected 2D thin-shell Rumpf/Kendall formula (`σ ∝ φ_areal·z·F_bond·⟨cos²θ_z⟩/(πR²)`, with `⟨cos²θ_z⟩=0.5` for a 2D in-plane bond network rather than the 3D-bulk value of 1/3) converts the simulated bond network into a predicted tensile strength (MPa) — this is the number `p3_bo.py` is ultimately trying to maximize.
5. **Z-based field tapering** — once the bond network's mean coordination number `z` (bonds per particle) crosses a percolation threshold (`Z_TAPER_THRESHOLD=3.0`, physically the rigidity-percolation point for a 2D network per Kantor & Webman 1984), the confinement field is gradually reduced toward a residual "standby" fraction — the physical analogy given in-code is reducing coil current once the sintered frame is self-supporting, which is also where most of the run's energy budget is spent or saved.

### 16.5 The two Bayesian Optimization loops — and why they're built differently, mechanically

There are **two separate BO systems** in `analysis/`, tuning two different phases, and they make opposite engineering trade-offs because the thing they're optimizing has different evaluation cost:

**`p2_bo.py` — analytical surrogate, no simulation runtime.**
Phase 2 (transport + shaping) is expensive to actually simulate (a full run is the ~3000-line, 36-dipole, µs-timestep sim). Instead of running it, `p2_bo.py` evaluates a **closed-form analytical cost function** — the same physics formulas used in `p2_metrics.py` (dipole field/gradient equations, coil I²R power, Hertz-Mindlin-derived stability proxy), just evaluated directly in Python/NumPy with no Taichi involved:

```
Cost = w1·(E/E_ref) + w2·(T/T_ref) + w3·(Δshape/Δ_ref) + w4·(1 − Percolation_frac) + w5·Complexity_norm
```

over a 10-D physically-motivated parameter space (dipole moments `m_trap`/`m_shape`/`m_corner`, `d_lead`, `chi_eff_target`, phase durations `T_transport`/`T_shape`, `GRAD_B2_CLAMP`, `k_hold_strength`, `n_radial_sweeps`). Because each evaluation is a closed-form calculation (microseconds), it can afford a real GP surrogate. Literally, the loop (`REGOBayesianOptimiser`, line 344) is:
1. **Initial design:** 20 points via Latin Hypercube Sampling — each of the 10 parameter axes is cut into 20 equal strata, one uniform-random sample is drawn per stratum per axis, and the per-axis samples are independently permuted before pairing up (`latin_hypercube_sample`, line 294) — this guarantees even 1-D coverage on every axis individually, unlike pure random sampling. The known-good v19 parameter set is force-inserted as point 0.
2. **Surrogate fit:** a `GaussianProcessRegressor` with kernel `Constant × Matérn(ν=2.5) + WhiteKernel` is fit to all `(params, cost)` pairs observed so far, in **normalized** `[0,1]^10` space (`normalise`/`denormalise`) so the 10 very differently-scaled axes (A·m² vs. seconds vs. T²/m) share one length-scale prior.
3. **Acquisition:** Upper Confidence Bound, `a(x) = μ(x) − κ·σ(x)` with `κ=2.0` (line 316) — since this is a *minimization*, the algorithm picks the point with the most optimistic (lowest) lower confidence bound, balancing "predicted low cost" against "high uncertainty, might be even better."
4. **Acquisition optimization:** not gradient-based — it draws 5000 random candidate points in normalized space and takes the `argmin` of `a(x)` over that dense set (`_next_candidate`, line 410). This is only viable because `a(x)` (a GP predict call) is cheap; a black-box-evaluation BO could not afford this.
5. **Loop:** evaluate the real cost at the chosen point, append to the observed set, refit the GP, repeat for `n_iter=80` iterations by default, tracking `best_cost`/`best_params` throughout.

This is standard "cheap analytical objective" BO — the GP is there to be sample-efficient over the *search*, not because each *evaluation* is expensive.

**The catch:** this cost function is a hand-maintained mirror of the real physics constants in `phase2_shaping.py` (duplicated, not imported), and it evaluates a static analytical approximation of behavior that Section 9 of this document shows is in practice chaotic and contact-dominated (bursts, sub-clustering). So `p2_bo.py` can tell you which parameter region is analytically favorable (low energy, fast, geometrically consistent) — it **cannot** tell you whether that parameter set actually avoids the v18–v36 cap-shaping failure modes, because burst/sub-clustering dynamics aren't in the analytical model at all. Its output is a reasonable starting point for a real run, not a validated one.

**`p3_bo.py` — real simulation-in-the-loop, black-box.**
Phase 3 (consolidation) is a bonding/sintering kinetics problem (sulfur wetting, DMT adhesion, Arrhenius rate laws) where the outcome genuinely depends on running the actual per-contact simulation — there's no cheap closed form that captures bond-network percolation. So each BO trial really does spawn `phase3_consolidation.py` as a subprocess with a candidate parameter set (`target_temp_C`, `activator_frac`, `t_consolidate_s`, `W_adh_J_m2`, `z_taper_threshold`, `bond_k0_S`, `vib_amplitude_g`) and reads back the real result. Because each trial costs real wall-clock simulation time (minutes, not microseconds), the algorithm optimizes for **evaluation efficiency** instead of search convenience:
- **Acquisition:** Expected Improvement, `EI(x) = (μ(x) − y_best − ξ)·Φ(Z) + σ(x)·φ(Z)` where `Z = (μ(x) − y_best − ξ)/σ(x)`, `Φ`/`φ` the standard normal CDF/PDF (`expected_improvement`, line ~250) — this is being *maximized* (unlike p2's UCB minimization), because p3's objective is a bond-strength *score* to maximize, not a cost to minimize. The `ξ` exploration-bonus term is **annealed**: it starts at `4ξ` on the first BO iteration and linearly decays to `1ξ` by the last (line 830) — explore broadly early, exploit narrowly late, exactly the opposite of a fixed exploration constant.
- **Acquisition optimization:** unlike p2_bo's dense-random-candidate search, `maximise_ei` runs **30 real local-optimizer restarts** (gradient-based, from 30 different starting points) to find the actual EI maximum — worth the extra compute here because a bad choice of next point wastes a multi-minute simulation run, whereas p2_bo can afford to be sloppy since evaluations are free.
- **Kernel:** Matérn-5/2, chosen (per the file's own comment) specifically for being more robust than a smoother RBF kernel to the noisier, sometimes-discontinuous black-box objective a real simulation produces.
- **Resumability:** every trial's parameters/score are appended to `bo_progress.json`; `bo_best.json` tracks the running best — a multi-hour sweep can be killed and resumed without losing progress, unlike p2_bo which is fast enough to just rerun from scratch.

**Neither BO loop closes the loop automatically.** Both write their best parameter set to a JSON file; a human still has to read that file and hand-edit the corresponding constants inside `phase2_shaping.py` / `phase3_consolidation.py`. There's no code path where "run BO" → "next simulation run uses the winning parameters" happens without a person in between.

### 16.6 Data interchange formats, summarized

| Format | Written by | Read by | Contents |
|---|---|---|---|
| `.pkl` (pickle) | `phase2_shaping.py` (auto-checkpoint every ~1s + one-time shape checkpoint) | `phase2_shaping.py --resume`, `analysis/p2_extract.py` | Full particle state (position/velocity/cluster id) + phase-machine state |
| `.vtu` + `.pvd` | `phase2_shaping.py`, `phase4_adaptive.py` | ParaView (external, manual) | Per-frame particle point clouds for visual playback |
| `rego_sim_data.json` | `p2_extract.py` | `p2_metrics.py` | Extracted scalar metrics parsed out of checkpoints/logs |
| `rego_metrics.json` | `p2_metrics.py` | `p2_graphs.py`, `p2_bo.py` | Scored dataset (energy/time/accuracy/stability/complexity + aggregate) |
| `results.json` / `energy_audit.json` | `phase3_consolidation.py` | `p3_metrics.py`, `p3_bo.py` | Consolidation outcome (bond strength estimate, energy spent, timing) |
| `bo_progress.json` / `bo_best.json` | `p2_bo.py` / `p3_bo.py` | themselves (resume), a human (read the winner) | Full trial history + current best parameter set |

---

## 17. Phase 4 replacement — Differentiable Shape-Matching MPC (one method, chosen and justified)

*Revision note: an earlier draft of this section proposed a 6-layer hedge (classical decomposition + contextual BO + differentiable trajectory optimization + a separate RL residual controller + a learned warm-start network). That was overcomplicated. This revision picks the single cleanest mechanism that actually solves the problem, explains why it subsumes what the RL layer was for, and says plainly where the project's existing BO infrastructure still fits — as a small outer tuner, not a core method.*

### 17.1 Why `phase4_adaptive.py` isn't inverse design, in one sentence

`get_force_at_particle` (line 673) hands every particle `self.target.get_target_position(particle_pos)` — its own exact analytical answer — and blends it with a heuristic field gradient using hardcoded per-phase weights (0.7/0.3 → 0.5/0.5 → 0.2/0.8) that were hand-tuned for cylinder-like geometry. A real external magnetic source never knows which particle is "supposed to" go where; it only ever produces a field, and particles respond to *that field's* gradient. This file is a coverage demo, not a solved inverse problem, and it doesn't generalize past the shapes someone has already hand-tuned it for.

### 17.2 The chosen method: Model Predictive Control through a differentiable Taichi simulator, against an optimal-transport shape loss

**One line:** at every control step, re-solve "what should the dipoles do for the next ~0.5-1s to move the current (real, sensed) particle distribution closer to the target shape," using gradients obtained by literally differentiating the physics simulator, then execute only the first slice of that plan and re-solve from the new real state. This is receding-horizon trajectory optimization (MPC) with the simulator itself as the internal model — not a separate learned policy, not a separate reactive controller bolted on afterward. Concretely:

**1. Target representation — a point cloud, not a hand-coded `ShapeTarget` subclass.**
Sample `N` points (`N`=256, matching the particle count) evenly over the target shape's surface (and interior, if it's meant to be filled solid) via farthest-point sampling. This works identically for a cylinder, an L-bracket, or a mesh someone hands you — there is no shape-specific code at all, which is exactly the generality `phase4_adaptive.py`'s per-shape sector logic doesn't have. This replaces Layer 1 ("shape decomposition") from the earlier draft entirely: you don't need to segment the shape into patches by hand, because the loss below is defined over the whole point set at once.

**2. The loss — entropic optimal transport (Sinkhorn distance) between current particle positions and the target point cloud**, not raw per-particle target assignment. Concretely: `L = Σ_ij π_ij·|pos_i − target_j|²` minimized over the transport plan `π` (a doubly-stochastic matrix, computed by a few Sinkhorn iterations with entropic regularization `ε`), which is the standard differentiable relaxation of the assignment problem. This is the mathematically correct replacement for phase4's `get_target_position()` hack: instead of a human/heuristic deciding which particle goes to which point up front, the optimal-transport loss lets the *optimizer* discover the best correspondence, and it's smooth everywhere (unlike nearest-neighbor Chamfer distance, which has gradient discontinuities exactly where two target points are equidistant — precisely the kind of discontinuity this project's history shows causes splitting behavior). One loss function, defined once, replaces every shape-specific weight in `phase4_adaptive.py`.

**3. The control representation** — the same physical objects `phase2_shaping.py` already manipulates: dipole positions, moments, and strengths, parameterized as a short piecewise-linear/spline tape over the MPC horizon (a handful of waypoints per active dipole, not a value per 8µs timestep — the physics integrator fills in the fast dynamics between control waypoints, exactly as `update_dipoles` already does with cosine ramps and lead/tangent geometry).

**4. Making it differentiable.** Taichi has built-in reverse-mode automatic differentiation (`ti.ad`) for exactly this purpose — fields marked `needs_grad=True` let `ti.Tape()` backpropagate through a sequence of kernel calls. `compute_forces`/`integrate` become one differentiable rollout; the OT loss at the horizon's end is also computed as a (small, N×N) differentiable kernel; gradients flow from loss → final positions → forces → dipole tape parameters in one `Tape` context.

**5. The optimization loop, literally:**
```
loop forever (real time, every ~50ms — matching the existing output cadence):
    read the TRUE current particle state from the running simulation
    initialize a candidate control tape (warm-started from last step's plan, shifted forward)
    repeat ~20-50 times (this inner loop is cheap — short rollout, same GPU kernels):
        roll the differentiable simulator forward through the horizon using the candidate tape
        compute OT loss against the target point cloud at the horizon's end
        backprop (ti.Tape) to get ∂loss/∂tape
        Adam step on the tape parameters
    commit only the FIRST control waypoint of the optimized tape to the real dipoles
    advance the real simulation by one control step
    (repeat — the next iteration re-senses reality, including whatever the physics
     actually did, not what was predicted)
```

**Why this single mechanism replaces the whole "Layer 5 RL controller" from the earlier draft:** the reason a feedforward plan (any of v18-v36, or a one-shot BO/NN-predicted parameter set) fails is that contact bursts and sub-clustering make the real particle distribution diverge from the plan, and a feedforward plan has no way to notice. MPC's replanning-from-true-state *is* the closed-loop correction — every ~50ms it looks at what the physics actually did (including a burst it didn't fully predict) and re-optimizes from there. You get the "learned residual policy reacting to reality" property for free, from the control architecture, without training a second system, a reward function, or a domain-randomization curriculum.

**Why gradient-based MPC over training an RL policy here specifically:** a real precedent exists for RL controlling magnetic particles (curriculum-based RL for 3D magnetic-microrobot-swarm position control, published in *Nature Machine Intelligence*), so RL is not a wrong idea in general — but it solves a different problem than the one here. That work controls a handful of discrete robots toward explicit positions via a shared field-free point; this project needs to move 256 particles into an arbitrary target shape using 36 dipoles under Earnshaw's constraint, and — critically — it already has a fully differentiable physics model of the exact system being controlled. When you have real gradients of the true dynamics, gradient-based trajectory optimization finds a good control tape in tens of iterations of a *simulator you already trust*, with zero training data, zero episodes, zero reward shaping. Training an RL policy instead would mean learning, through indirect trial-and-error reward signal, an approximation of what the gradients already tell you directly — strictly more expensive for no accuracy benefit, in a setting where a good differentiable model already exists. RL earns its keep when you *don't* have a differentiable/trustworthy model, or when the action space/decision problem doesn't reduce cleanly to trajectory optimization (e.g. discrete combinatorial choices). Neither is true here.

**Where the existing BO infrastructure (`p2_bo.py`/`p3_bo.py`) still fits — as a small outer tuner, not the core method:** the MPC loop itself has a handful of hyperparameters (horizon length, replanning period, Sinkhorn `ε`, inner-loop iteration count and Adam learning rate). Tuning those is a perfect job for exactly the black-box BO pattern `p3_bo.py` already implements: run the whole MPC-controlled assembly as one black-box trial, score it (final OT loss, energy, time — the same metric categories `p2_metrics.py` already computes), and let GP+EI search the handful of MPC hyperparameters. No new optimization infrastructure needs to be built for this — it's the same `p3_bo.py` pattern pointed at a new set of ~5 scalars.

### 17.3 The one honest caveat, and its fallback

Section 9's failure history (v18-v36) is full of genuinely chaotic events — contact bursts, DBSCAN-sensitive sub-clustering — and gradients backpropagated through a stiff contact model across a burst can be noisy or explode, which is a known failure mode of gradient-based control through contact-rich physics generally (documented in the differentiable-simulation literature for granular/deformable-object manipulation, not specific to this project). Two mitigations, both cheap and already consistent with this architecture:
- **Keep horizons short** (the MPC loop already replans every ~50ms, so no single optimization needs to reason across an entire multi-second burst-and-settle sequence — it only needs to be right for the next fraction of a second, then it gets to look again).
- **If gradients through a specific burst sub-phase prove unusable in practice**, fall back to a zeroth-order/gradient-free local search (e.g. CMA-ES, or literally reuse `p2_bo.py`'s GP+UCB machinery) for *that* control step only, using the same OT loss as the black-box objective. This is a fallback within the same architecture — swap the inner optimizer for one horizon-step when gradients misbehave, not a parallel system that has to be built, trained, and validated separately.

### 17.4 Build order

1. Finish Section 10's Fix 1/Fix 2 for the single fixed cylinder shape first (align transport targets with the z-spring equilibrium; separate z/xy damping) — no point building a generalized controller on top of a per-shape control law that doesn't reliably converge yet even once.
2. Get `ti.ad`/`Tape` working through `compute_forces`/`integrate` for a short rollout in isolation (a few hundred steps), independent of MPC — confirm gradients are well-behaved for the smooth transport regime before trusting them near a burst.
3. Wire up the receding-horizon loop exactly as in 17.2, against the existing cylinder target first (as a regression test against the known-good v36 result) before trying an arbitrary new shape.
4. Only then try a genuinely different target shape (e.g. a cone or an L-bracket) end to end, since that's the actual point of this whole redesign — and only then decide whether the CMA-ES/`p2_bo.py` fallback (17.3) is actually needed in practice, rather than building it preemptively.

Sources consulted for this section: Taichi's differentiable-simulation ecosystem is confirmed to extend to granular materials specifically ([arxiv.org/html/2412.16750v1](https://arxiv.org/html/2412.16750v1)-adjacent work; DiffTaichi-family results), differentiable-simulation MPC for shape control of deformable/granular media has direct precedent (e.g. the DDBot granular-digging controller, [arxiv.org/pdf/2510.17335](https://arxiv.org/pdf/2510.17335); differentiable-sim shape control of deformable linear objects via MPC, [ROBOMECH Journal](https://robomechjournal.springeropen.com/articles/10.1186/s40648-024-00283-1)), inverse design of field-driven colloidal assembly generally follows the "loss over target structure + optimize tunable control parameters" pattern used here ([arxiv.org/pdf/1905.11061](https://arxiv.org/pdf/1905.11061)), and RL for magnetic-particle position control has real precedent but at a different scale/problem shape ([Nature Machine Intelligence, 2023](https://www.nature.com/articles/s42256-023-00779-2)).

---

## 18. Physical limits and known non-physical placeholders (Stage A audit)

This section records a full physics/correctness audit of `phase2_shaping.py` (all findings verified
against `outputs/shape_checkpoint.pkl` and `outputs/phase2_checkpoint.pkl` — real particle state, not
inferred from the animation) and the Stage A repair that followed. See `HISTORY.md` for the
change-by-change log; this section is the standing reference for current status.

### 18.1 Findings

| ID | Finding | Status |
|----|---------|--------|
| F1 | `build_grid` stored the true (too-large) particle count per cell into `grid_cnt` while only writing the first `MAXPC=32` indices into `grid_buf`; `compute_forces` then read past the buffer's end. Measured occupancy: 64/cell at shape start, 128/cell in the final state. Real overlapping neighbours beyond the 32nd received no contact force at all. | **Fixed** — `hcell=8R`, `MAXPC=96`, stored count clamped, overflow counted (`grid_overflow_count`) instead of silently corrupting data. |
| F2 | `contact_pp`'s `d > 1e-12` guard made exact particle coincidence (reachable via F1) an absorbing state — zero force forever. Measured: minimum pair distance exactly 0.0 in the final checkpoint. | **Fixed** — deterministic index-derived separation direction (`_degenerate_normal`), antisymmetric so Newton's third law still holds. |
| F3 | The wall-scan shaping dipole swept its z-range all the way to `z_hi`/`z_lo` — the cap planes — producing up to 3306×gravity on cap particles at the moments corresponding to the user-observed t≈30s/t≈35s cross-cluster drag. | **Fixed** — sweep inset by `Z_CAP_MARGIN=0.75mm`; combined with the F6/F7 moment recalibration, worst-case residual cross-talk on the nearest cap-rim particle is ≈0.5×W (was 3306×W). |
| F4 | The "hold ring" is documented throughout the file as a 4-dipole square ring with a B² maximum at its center by 4-fold symmetry, but only 2 of the 4 nominal positions were ever instantiated. Two dipoles are two point attractors, not a ring — this is the mechanism behind "everything gets sucked to a point outside the cylinder" at the end of Phase 2 (final Q0 centroid measured sitting exactly on the +x hold dipole). | **Fixed** — permanently disabled (s=0 in all states). A correct symmetric ring is a Stage B design question, not a Stage A retune. |
| F5 | Particle color/identity. | **Verified correct**, not a bug — `cluster_id == fixed_color` held at every checkpoint checked; apparent yellow/orange "disappearance" is real spatial migration (via F3), not recoloring or deletion. |
| F6 | Field magnitudes were physically impossible: `_m_trap`/`_m_shape` at their operating standoffs implied fields of 4.4–11.1 T from a coil declared as 100 turns × 4mm² carrying 1.5–3.75A (which physically produces millitesla fields), evaluated at 0.3–1.5mm from a coil whose own linear dimension is 2mm — inside its own near field, invalidating the point-dipole approximation used everywhere in `compute_forces`. | **Fixed** — moments recalibrated to target ≈50×W at standoffs ≥3× the (now smaller, 0.158mm-side) coil dimension. |
| F7 | The velocity cap, not the magnetic force, set transport kinematics: a single 8μs step at the old clamp produced Δv=122mm/s against a 12mm/s cap (10× over-cap every step, saturated continuously). Non-conservative clipping also prevented contacts from separating overlapping particles (feeding F2). | **Fixed** — hard clip removed from `integrate()`; kinematics now come from F=ma with the F6 recalibration and F8 timestep providing stability. |
| F8 | Timestep too large for the contact model: dt=8μs gave ω·dt=0.66 at δ=R against a Rayleigh limit of ≤6.4μs and a Hertz-contact-period limit of ≤3.8–4.5μs. | **Fixed** — dt=3μs. |
| F9 | `surf_conf` (a spring to a mathematical plane/cylinder) and its viscous damping term have no physical source. | **Kept, explicitly labeled** in code and here — see 18.2. Not removed because Stage A's scope was correctness of the existing model, not a redesign; must not be extended or retuned. |
| F10 | Minor: `dip_pos_np` was never synced in `update_dipoles` (checkpoints stored stale dipole positions); this file stated `∇²(B²) ≤ 0` (backwards sign, correct conclusion); `phase1_cluster.py`/`phase0_baseline.py` are disconnected legacy prototypes, not pipeline stages. | **Fixed / corrected / labeled.** |
| F11 | Cohesion (van der Waals / DMT adhesion) was entirely absent from `phase2_shaping.py`'s contact model despite `phase3_consolidation.py` already relying on the same physics (`W_adh=0.08 J/m²`). At R=30μm this dominates lunar gravity by ~5000× (DMT) — two touching grains do not separate on their own. | **Fixed** — DMT pull-off force `F_adh = 2π·R*·W_adh` added to `contact_pp`, same `W_adh` as Phase 3. |
| F12 | Consequence of F11: at realistic (F6-corrected) field magnitudes, F_mag/F_vdW ≈ 0.23 at R=30μm — magnetism cannot pull apart two touching grains. The v34–v36 "dense ball bursts into a spread monolayer under contact repulsion" premise is not physically achievable at this grain size once cohesion is modeled. | **Documented finding**, not something to patch around — see 18.3. |
| F13 | Ponderomotive (time-averaged dynamic) trapping (HISTORY.md v22–v28) was tested at ω_rot=15–120 rad/s against ω_mech≈25 rad/s — a factor of 0.6–5×, nowhere near the ω_drive≫ω_mech separation the method requires. At the F6-corrected force scale, ω_mech≈735–2324 rad/s; a drive at 10× that (7.3–23 kHz) is resolvable at dt=3μs (ω·dt≈0.02–0.07). This has never actually been tried at the correct operating point. | **Documented as the leading Stage B candidate** — see 18.3. |
| F14 | `GRAD_B2_CLAMP` was a plain Python global, reassigned per-phase via `global GRAD_B2_CLAMP` inside `update_dipoles()`. Taichi bakes Python-scope scalars referenced inside a `@ti.func`/`@ti.kernel` into the compiled kernel **at its first compile** — verified empirically with a minimal repro kernel (a changed Python global has zero effect on subsequent calls to an already-compiled kernel). `compute_forces` (which inlines `B_and_gradB2`, which reads this value) is first compiled during the pre-loop diagnostic call while `pm.state=="settle"` — so in every prior version of this file, whatever the settle/cluster branch set (2000.0) was silently the permanent clamp for the *entire run*, including "shape" phase. The documented `SHAPE_MAX_GRAD_CLAMP` (700 historically, 30 post-F6/F7) was never actually applied at runtime — every HISTORY.md discussion of a "shape gradient clamp" was describing a value that wasn't in effect in the running kernel. | **Fixed** — `GRAD_B2_CLAMP` converted to a `ti.field`, the correct pattern already used for `surf_conf_enabled` and previously `v_cap` for exactly this reason. |

### 18.2 Known non-physical placeholders — do not extend

`surf_conf` (`compute_forces`, guarded by `surf_conf_enabled`) and its per-axis viscous damping term
remain in the code, clearly labeled at the point of definition. They have no physical source: vacuum
exerts no drag, and there is no real surface for a particle to be confined to — the target cylinder
is the structure this project is trying to demonstrate can be *assembled*, not a boundary condition
it is entitled to assume. They are kept so the rest of the fixed simulation (contact mechanics, field
magnitudes, phase timing) could be validated in isolation. **Any future work must not retune, extend,
or build on these terms**, and their presence in a run must not be read as evidence that magnetic
shaping works — see CLAUDE.md.

### 18.3 The physical limit, and what remains open (Stage B)

In a current-free region `∇²(B²) = 2|∇B|² ≥ 0`: B² is subharmonic, so its **static** maxima occur
only at the sources. No static field configuration holds paramagnetic particles spread across an
extended free surface — every static architecture tried (v18–v36) hits this wall for the same
underlying reason, and the terminal collapse onto the hold-ring dipole (F4) is a direct, measured
instance of it.

**This does not mean the REGO concept is impossible — it means no *static* field can do it.** Per
explicit project direction, a physical scaffold/mandrel/cage is not an acceptable resolution: the
scientific question is specifically whether magnetic fields *alone*, potentially time-varying, can
manipulate free particles into the target structure without a physical form imposing the geometry.
Earnshaw constrains static fields; it says nothing about a field that is itself a function of time —
a genuinely time-varying/rotating multi-dipole field can produce a stable time-averaged potential
with no static counterpart (the textbook precedent is the RF Paul trap for charged particles).

Two findings from this audit bear directly on what a Stage B control strategy should attempt:

- **F12** rules out "let a dense ball burst apart under its own contact repulsion" as a spreading
  mechanism at R=30μm — cohesion wins. Any Stage B mechanism needs to either move cohesive
  aggregates as units (not try to pull individual grains apart from their neighbors) or operate at a
  particle size where the Bond number favors separation (see the R-vs-Bond-number table produced
  during the audit: Bo_vdW=1 at R≈0.63mm, Bo_DMT=1 at R≈2.18mm).
- **F13** is the most promising untested candidate: genuine ponderomotive dynamic trapping, correctly
  implemented at ω_drive≫ω_mech (kHz range at the F6-corrected force scale, confirmed numerically
  resolvable at dt=3μs), never actually attempted at the right operating point in this codebase's
  history. Section 17's differentiable-MPC proposal and a sequential single-aggregate deposition
  strategy (informed by F12) remain on the table and should be weighed against it with real numbers
  before committing — this document does not pre-select one.

**Expected honest outcome of Stage A alone:** with F1–F10 fixed, the simulation is numerically and
mechanically correct, but static-field shaping (the only mechanism Stage A implements) is still
expected to fail to hold particles spread across the target surfaces once `surf_conf` is the only
thing attempting it — exactly as the Earnshaw argument predicts. That is the expected result of this
stage, not a regression, and it is the evidence base for choosing the Stage B mechanism above.

**Confirmed, not just predicted (2026-08-13 full run, see HISTORY.md "Stage A" entry for the
complete numbers):** an end-to-end run through settle→cluster→transport→shape→hold completed with
zero crashes/NaN and F3's cross-talk fix measured at 0.00×gravity in the live run, but at t=42.3s
("hold") all four clusters had free-fallen to the domain floor (z_mean 0.04-0.07mm vs. targets of
7.0/5.0/5.0/3.0mm) — because nothing opposes gravity once `surf_conf` turns off at shape's end and
the false hold ring (F4) is no longer there to (incorrectly) paper over the gap. This is the Stage A
audit's central deliverable: not a formed cylinder, but proof that the current static-field
mechanism cannot hold one together, demonstrated rather than argued.

---

## 19. Stage A-2 — Closed-loop transport controller (finding F15)

**Finding F15.** Stage A's F7 fix (removing the hard velocity cap) was physically correct, but the
transport control law had no other mechanism opposing velocity. A full reconstruction of the Stage A
run against its real VTU output (`analysis/reconstruct_run.py` — parses every frame and replays the
real `PhaseManager`/`update_dipoles` logic against the real centroid trajectory) showed `arrived_t`
was `None` at every checkpoint sampled (every transport was actually completed by the
`TRANSPORT_BUDGET` timeout, not genuine arrival), that transport ran at the clamp-saturated force
ceiling (141.7×gravity, a=229.6 m/s²) for large fractions of its window, and that velocity reached
50,000–97,000 mm/s by the last transport — the direct cause of the "falls after arriving,"
"chaotic corner-to-corner motion," and "explosion at the shape transition" reported from watching
the actual animation. Cross-checking `cluster_id` at every checkpoint, including the chaotic ones,
confirmed no real cluster merging ever occurred (counts stayed 64/64/64/64) and that forces are not
cluster-ID-filtered (reconstructed forces from real dipole state matched the VTU's own recorded
forces at the calmer checkpoints).

**The fix** is a closed-loop, position-and-velocity-feedback transport controller
(cruise → brake → settle → verify → hold), designed and quantitatively justified before
implementation. It decelerates clusters using only the real paramagnetic force law acting through a
real, repositionable/re-strengthable dipole — never a force added directly to a particle, never a
reinstated velocity cap, never filtered by cluster ID. The physical basis: a static field is
conservative (a moving particle released into it cannot come to rest on its own — it will oscillate
forever absent dissipation), so genuine braking requires either real contact dissipation (too weak
against bulk motion here) or actively moving the source, which does real work on the particle exactly
as any real closed-loop electromagnet (maglev, magnetic bearings, real magnetic-tweezer rigs) is
actually driven. Full design and the HISTORY.md "Stage A-2" entry have the equations, tolerance
derivations (`EPS_X=5R`, `EPS_V` from ballistic drift over one control cycle), and verification.

### 19.1 Stage A-3/A-4/F19-fix — the transport controller's real remaining gaps (findings F16-F19)

Implementing Stage A-2 surfaced four further, real findings, each confirmed against real simulation
data (VTU frames or fine-grained live instrumentation) rather than inferred from code reading. Full
narratives, equations, and numbers are in HISTORY.md's "Stage A-2" (F16), "Stage A-3" (F17),
"Stage A-4" (F18), and "F19 fix" entries; summarized here for the current-state picture:

- **F16 (stale path anchor)**: the pure-pursuit lookahead path was precomputed at module load time,
  anchored at the cluster's original spawn corner on the floor — stale by the time transport actually
  begins. Fixed by rebuilding the path live, anchored at the real current position, once per transport
  attempt.
- **F17 (CRUISE standoff collapse)**: clustering only regroups particles laterally at floor level — it
  never lifts them (real z stays pinned at `C.R` through clustering and the start of transport,
  confirmed directly from VTU data) — so every transport genuinely starts needing a real vertical climb
  the old CRUISE law never accounted for. Because the cluster couldn't climb, the lookahead point ran
  away from it (measured: dipole-cluster separation grew 0.79→5.00mm over ~2.3s), collapsing the
  achievable force. Fixed (Stage A-3) by adding explicit `LIFTOFF`/`LIFT` sub-phases before CRUISE
  (dipole tracks directly above the real centroid at the established 0.5mm standoff, verified via real
  64-particle geometry to give 30× margin with zero clamp saturation) and bounding CRUISE's dipole to
  within `MAX_CRUISE_STANDOFF` of the real cluster regardless of path geometry.
- **F18 (CRUISE vertical support collapse)**: LIFTOFF/LIFT genuinely worked (real z rose 0.03→0.72mm),
  but the instant CRUISE engaged, the cluster fell straight back to the floor and never recovered.
  Root cause, confirmed via new per-control-step (6ms) instrumentation reading real cluster-0 state
  directly (`DEBUG_LIFT_CRUISE=1`, see `_debug_lift_cruise_snapshot()`): CRUISE used one pull direction
  (path tangent) and one scalar throttle computed from *total* speed to do two independent jobs
  (vertical support, horizontal pursuit) at once — because free-fall increases total speed, the
  throttle actively suppressed the force needed to stop the fall, a self-reinforcing (not momentary)
  collapse. Fixed (Stage A-4, implemented and verified from real data): decoupled into an independent
  vertical channel (deadbeat predictor on `v_z` only) and an independent horizontal channel (same
  predictive style, gated on horizontal speed only, never `v_z`), composed into one vector and realized
  by a single dipole at the fixed 0.5mm standoff (proven sufficient: 11× margin between the combined
  target and the standoff's force ceiling). The same deadbeat law also replaced LIFT's throttle, fixing
  its own real (if self-correcting) overshoot/bang-bang pattern found during the same diagnosis.
  Real-run verification after implementation showed horizontal convergence to <0.05mm — excellent — but
  surfaced a new finding, F19.
- **F19 (CRUISE vertical channel could never command descent)**: the Stage A-4 vertical law,
  `a_vert=g+max(0,(V_CEIL-v_z)/CTRL_DT_NOMINAL)`, floors at hover and can only add lift, never subtract
  it. A transient clamp-saturation spike at the LIFT→CRUISE handoff (`Fmag` hit 140.76× cluster weight,
  matching the independently-computed clamp ceiling of 141.7×W — genuine physical near-field saturation,
  not a bug) drove real overshoot past the target height on multiple clusters (real residual errors of
  2.86mm and 7.11mm, forced-completed by `STALL_TIMEOUT` rather than reaching genuine `arrived_t`;
  reproduced on 2 of 4 real transports, a 3rd observed live entering the same pattern). Root cause: with
  the vertical channel unable to reduce a height error once above target, `d` (3D distance to target)
  could never shrink below `D_BRAKE_TRIGGER`, so the already-correct, already-bidirectional BRAKE branch
  was simply never reached on the vertical axis — a deadlock, not slow convergence. Fixed: CRUISE's
  vertical throttle now mirrors the horizontal channel's ceiling-tracking form but takes the ceiling's
  sign from the real signed height error (`v_ref_z=copysign(V_CEIL, target_z-z_cur)`) instead of
  hardwiring ascent-only; SETTLE, LIFT, and the horizontal channel are unchanged. **First implementation
  attempt was wrong** (caught by a real-sim check, not assumed correct): `a_vert_gross` is realized
  downstream as the dipole's own force/mass contribution, not the net acceleration — gravity is always
  applied separately — so dropping the old law's `C.g +` offset made a merely-negative correction read as
  "pull down on top of gravity," roughly doubling real descent. Corrected to
  `a_vert_gross = C.g + (v_ref_z-v_z)/CTRL_DT_NOMINAL`. Re-validated (isolated CRUISE-only synthetic test):
  all real overshoot/velocity states now reach the BRAKE handoff boundary cleanly, no chatter.
- **F20 (BRAKE branch has the same gravity-decoupling bug, never previously exercised)**: found while
  synthetic-testing the corrected F19 fix through a full CRUISE+BRAKE trajectory. BRAKE
  (`elif d<=D_BRAKE_TRIGGER`, unmodified by F19) computes a pure kinematic deceleration magnitude and
  realizes it fully along `-v̂` with no gravity term — the same class of bug as F19's first attempt, but
  pre-existing since Stage A-2 and never caught because no real run had ever reached BRAKE with nonzero
  vertical velocity before the F19 fix. Consequence: over-brakes an ascent or under-brakes a descent by
  `g`; a purely horizontal brake previously got zero vertical support (free-fall during the brake). Fixed
  by mirroring CRUISE's own realization convention: `F_dip/mp = a_net_req + (0,0,C.g)` where
  `a_net_req = -a_needed·v̂`, realized as one dipole via the same `p=x_cur+R_DECEL0·a_hat`,
  `m=-m_trap·a_hat` convention already used elsewhere (replacing the old velocity-aligned placement). The
  near-zero-total-velocity fallback branch (pre-dates this engagement) was left unchanged as out of scope.
  Validated by a combined CRUISE+BRAKE synthetic test (6 cases: real overshoot/stuck states, regression
  check, pure-horizontal brake, combined horiz+vert velocity) — all converged within `STALL_TIMEOUT`, no
  chattering, no saturation.
- **F21 (CRUISE/BRAKE zone-switching chatter, no hysteresis)**: found running the F19+F20-fixed controller
  against real per-control-step data (extended the existing `DEBUG_LIFT_CRUISE` instrumentation to cover
  BRAKE too, via a new `DEBUG_CRUISE_MAX` env var). transport_0 made clean initial progress then entered a
  genuine, worsening CRUISE/BRAKE limit cycle (run-lengths shrinking 106→41→21→...→1 steps), driven by a
  real near-field clamp-saturation kick (`satfrac=1.07`, `v_z` jumping 3.5→17.4→74.8mm/s across two 6ms
  steps) each time `d` ticked back above the single, no-hysteresis `D_BRAKE_TRIGGER` and CRUISE reasserted
  a full-authority command from scratch. Real post-kick excursions reached d=0.61-2.91mm. Fixed (user chose
  this option over rate-limiting the deadbeat or investigating the near-field trigger first): a hysteresis
  band — `D_BRAKE_EXIT=2×D_BRAKE_TRIGGER=0.90mm`; once in BRAKE, only return to CRUISE once `d` exceeds the
  wider exit threshold (a round multiplicative margin, headroom over the observed 0.88mm first-chatter
  excursion). The point-mass synthetic harness used for F19/F20 could not reproduce the real trigger
  (a finite-cluster-geometry near-field effect) — synthetic testing only confirmed the hysteresis logic
  doesn't break normal convergence; real-world efficacy is unconfirmed pending a real run.

**Update: hysteresis alone was insufficient.** A real targeted run showed transport_1's velocity blowing up
to 200.4mm/s with `BRAKE SATURATION` (demanded force exceeding the standoff's physical ceiling by up to
56%) even with hysteresis active. Generalized the `DEBUG_LIFT_CRUISE` instrumentation (any cluster, via
`DEBUG_CLUSTER`; also covers BRAKE) and found the real mechanism: CRUISE's/BRAKE's aim direction can flip
180° in a single 6ms step (no zone change involved), sweeping the fixed-standoff dipole across the real,
finite-size cluster and occasionally passing close to an edge particle (`satfrac` up to 13.8×) — a
self-sustaining resonance. Fixed with a rate limiter (`DTHETA_MAX=13.8°/step`, derived from real standoff
`r=0.5mm` and real measured cluster extent `Rc=0.26mm`, not an arbitrary constant) capping how fast the aim
direction can rotate, with magnitude then projected onto the direction actually realizable that step (not
applied raw along a stale direction — synthetic testing caught that combination diverging on its own).
Implemented across LIFT→CRUISE→BRAKE. Full derivation, the two real bugs synthetic testing caught before
implementation, and the one known-unresolved synthetic edge case are in HISTORY.md's "F21 rate limiter"
entry. Cluster-integrity diagnostics (`cluster_integrity()`/`report_cluster_integrity()` — per-axis σ, RMS
spread, max particle extent, bbox, vs. a pre-transport baseline) were added to distinguish "centroid
reached target" from "particles stayed physically clustered," called at genuine arrival and at STALL.

**As of this writing: F19, F20, and F21 have all passed available cheap validation but NONE has been
confirmed end-to-end against a real simulation run culminating in genuine arrival.** Do not treat the
transport controller as validated until a real run passes — per the current staged validation gate,
transport_0 alone first; only run all four transports if transport_0 passes with genuine arrival and
maintained cluster integrity (see HISTORY.md's "F21 rate limiter" entry and this session's validation-gate
acceptance criteria).
