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

**IMPORTANT DISCREPANCY:** Q0 transport target z = 7.2 mm, but z-spring equilibrium is z_hi = 7.0 mm. This 0.2 mm offset is a major source of the current cap shaping failure (see Section 9).

---

## 3. Core Physics

### Paramagnetic Force
```
F = (Vp · χ_eff / 2μ₀) · ∇B²
```
Particles seek B² maxima. The field is created by external dipoles (magnetic tweezers).

### Earnshaw's Theorem (Critical Constraint)
**∇²(B²) ≤ 0 everywhere in free space.** There is no static B² maximum in free space. Therefore:
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
| Parameter | Value |
|-----------|-------|
| Timestep dt | 8 μs |
| Output interval | 50 ms |
| v_cap (shape) | 5 mm/s |
| v_cap (transport) | 12 mm/s |
| Taichi backend | CUDA (f64) → CPU fallback |

---

## 4. Simulation Architecture

### File: `phase2_clean_OKAY.py` (~2930 lines)

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

## 6. Key Constants (in phase2_clean_OKAY.py)

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
| `phase2_clean_OKAY.py` | Main simulation (~2930 lines) |
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

The file is `phase2_clean_OKAY.py`. Changes are tracked by version labels in comments (v34, v35, v36...). The current cap shaping approach is **v36** (k_r=0, τ=0.25s). All previous approaches (v18–v35) failed. See HISTORY.md for full per-version details.
