# REGO: Magnetic-Field-Mediated Assembly of Free Lunar Regolith Particles — Draft

**Status: DRAFT IN PROGRESS. Results/Discussion/Conclusion are provisional pending the Phase 2
transport-controller validation gate (see `simulation/HISTORY.md`, "F21 rate limiter" and later
entries, for current status). Do not cite numerical results from this draft until that section is
updated post-validation.**

---

## 1. Introduction

*[TBD — motivation: in-situ lunar construction/consolidation without a physical mold or scaffold;
why magnetic manipulation of paramagnetic regolith simulant is attractive (no consumables, no
moving mechanical parts in contact with regolith, reconfigurable); statement of contribution
(closed-loop magnetic transport + assembly of free granular particles, physics-validated
simulation); roadmap.]*

## 2. Related Work

*[TBD — magnetic tweezers / colloidal manipulation literature; granular DEM simulation; lunar ISRU
and regolith handling approaches; prior magnetic-levitation/positioning control work; where this
work's real-particle-scale coupled EM+DEM simulation sits relative to point-mass or continuum
treatments elsewhere.]*

## 3. Problem Formulation

We consider whether a controlled, time-varying magnetic field — realized by repositionable and
re-strengthenable dipole sources external to the granular bed — can (a) transport discrete clusters
of paramagnetic regolith-simulant particles from an initial distribution to prescribed target
locations, and (b) subsequently shape those clusters into a target geometry, using **only** the
paramagnetic force acting on free particles, with no physical mold, cage, mandrel, or scaffold.

This is constrained by Earnshaw's theorem: in a current-free region, `∇²(B²) = 2|∇B|² ≥ 0`, so `B²`
is subharmonic and its static maxima occur only at the field sources. No static magnetic field
configuration can hold paramagnetic particles distributed across an extended free-standing surface —
they collapse toward the nearest dipole. Any effective shaping or holding mechanism must therefore
either (i) be genuinely time-varying/rotating (not constrained by the static-field form of the
theorem, provided the drive frequency is verified to be far above the mechanical response frequency
of the particles), or (ii) rely on a real, physically justified secondary mechanism (granular contact
mechanics, cohesion, gravity) working alongside the field, rather than an idealized static trap. This
paper reports what a real closed-loop controller, subject to this constraint and to the real
force-vs-standoff behavior of a dipole source, can and cannot achieve.

## 4. System / Simulation Model

### 4.1 Particle and material model

Individual particles are modeled as spheres of radius `R` (lunar regolith simulant scale), density
`ρ=7800 kg/m³`, volume `Vp=(4/3)πR³`, mass `mp=Vpρ`. Particle count per cluster: `N=64`, four
clusters (`N_total=256`) targeting a four-quadrant assembly geometry. Gravity is lunar,
`g=1.62 m/s²`, applied as a constant, unconditional force `F_z -= mp·g` every integration step,
independent of any magnetic actuation — this separation (gravity always acts; the controller's job is
to command a magnetic force that combines with it to produce the desired net motion) is central to
several controller-design corrections described in §6.

### 4.2 Paramagnetic force law

Each particle experiences `F = (Vp·χ_eff / 2μ₀) · ∇(B²)`, where `χ_eff` is a field-dependent
effective susceptibility (`χ_eff = χ / cosh²(χ·B/(μ₀·M_sat))`, saturating at high field) and `B` is
the field from all active dipole sources, computed from the analytical on-axis dipole field and its
exact Jacobian (not a finite-difference approximation). A soft vector clamp (`GRAD_B2_CLAMP`) limits
`|∇(B²)|` to a fixed ceiling to keep the near-field numerically and physically bounded, with the
clamp value chosen so that it is reached only within the design near-field standoff, not at the
operating standoffs used by the controller (verified quantitatively, §6).

### 4.3 Contact mechanics

Particle-particle and particle-wall contacts use a Hertzian/DMT-adhesive normal contact model with a
tangential friction term; the timestep (`dt=3μs`) is chosen so that `ω·dt` for the stiffest realized
contact stays well below the stability boundary (checked, not assumed, per run).

### 4.4 Simulation phases

`settle → cluster → transport_0..3 (each: LIFTOFF → LIFT → CRUISE → BRAKE → SETTLE) → interlude_0..3
→ shape → hold`. This paper's controller contribution and validation focus on the transport phase;
clustering and shaping are described for completeness but are outside this paper's controller-design
scope.

## 5. Phase 2 Controller Architecture

### 5.1 Design principle: feedback control of the source, not a force on the particle

Every controller decision changes only the real dipole's position, orientation, and strength — the
force law in §4.2 is never modified, filtered by particle/cluster identity, or supplemented by an
artificial term. This is the same category of thing every real closed-loop electromagnet (maglev,
magnetic bearings, magnetic tweezers) does: a controller reads position/velocity and adjusts the
actuator's current and position; the physics the particle feels is unchanged.

### 5.2 Single-dipole vector realization

A single on-axis dipole can deliver a force of any desired 3-D direction and magnitude (up to the
standoff's ceiling) by choosing where to place it (`x_cluster + r·â`) and orienting its moment along
`-â`. This is the mechanism the entire transport controller composes: every phase computes a desired
acceleration **vector**, then realizes it as one dipole at a fixed standoff `r`, aim direction
`â = a_cmd / |a_cmd|`.

### 5.3 State machine

- **LIFTOFF/LIFT**: dipole held directly above the cluster centroid at a fixed clearance standoff,
  moment straight down; strength from a deadbeat law on vertical velocity only
  (`a_vert = g + (v_ref_z - v_z)/Δt_ctrl`, `v_ref_z=V_CEIL`). Confirmed genuinely lifts particles off
  the floor (real z-trajectory data).
- **CRUISE**: independent vertical and horizontal deadbeat channels (vertical: signed ceiling-tracking
  toward `±V_CEIL` based on the real signed height error, not hardwired ascent-only; horizontal:
  pure-pursuit toward a precomputed, collision-avoiding waypoint path), composed into one 3-D vector
  and realized by the single-dipole mechanism of §5.2.
- **BRAKE** (entered once distance-to-target `d` crosses a threshold, exited only once `d` exceeds a
  wider threshold — hysteresis, §6.3): real kinematic deceleration
  (`a_needed = v²/(2·d_remaining)`) opposing the cluster's actual velocity vector, plus a separately
  accounted gravity-compensation term (§6.2).
- **SETTLE**: dipole parked at a fixed, non-singular standoff off the target along the surface normal,
  modest strength headroom over gravity; arrival is declared only once both position error `<ε_x` and
  speed `<ε_v` hold for a sustained dwell — not a fixed timer.
- A **stall safety net** (diagnostic, not a primary control path) force-completes a transport that
  fails to converge within a generous multiple of the expected transit time, logging the event loudly
  rather than silently treating it as normal completion.

### 5.4 Control cadence and tolerances

Control period `Δt_ctrl=6ms` (matches the physics-substep batch cadence). Position tolerance
`ε_x=5R=0.150mm`; velocity tolerance `ε_v=ε_x/Δt_ctrl=25mm/s` (ballistic-drift-derived: a cluster
below this speed cannot leave the position tolerance even coasting unpowered for one control cycle).

## 6. Controller Design Corrections (Findings F16–F21)

This section documents, as findings, the real bugs and design gaps discovered and corrected during
development — each diagnosed from real simulation data (not code inspection alone) before any fix was
designed, and each fix synthetic-tested before implementation. This is reported for scientific honesty
and because the failure modes themselves are informative about the physical constraints on this class
of controller.

*[F16–F18 summary, F19 vertical-channel gravity-convention correction, F20 BRAKE's analogous
correction, F21 near-field rate limiter with its real-geometry derivation (`DTHETA_MAX=13.8°` per 6ms
step from standoff `r=0.5mm` and measured cluster extent `Rc=0.26mm`) — full technical detail already
written up in `simulation/HISTORY.md`; to be condensed into paper form once the validation gate result
is known, so the writeup reflects the FINAL architecture rather than needing revision after every
subsequent fix.]*

## 7. Evaluation Methodology

### 7.1 Per-transport acceptance criteria (validation gate)

A transport attempt is judged successful only if it passes through the full LIFTOFF → LIFT → CRUISE →
BRAKE → SETTLE → ARRIVAL sequence with a genuine `arrived_t` (position and velocity criteria met and
sustained), not a `STALL_TIMEOUT`-forced completion, AND maintains cluster integrity throughout
(quantified below) — reaching the target centroid position is necessary but not sufficient.

### 7.2 Metrics recorded per transport

Arrival position error; final velocity; transport duration; maximum velocity; maximum acceleration;
force/weight ratio; maximum saturation/clamp ratio; minimum dipole-particle separation; cluster
spread/compactness (RMS radius, per-axis σ, max particle-to-centroid distance, bounding box) and its
ratio to the pre-transport baseline; phase-transition timestamps (LIFTOFF/LIFT/CRUISE/BRAKE/SETTLE);
whether any particles became detached or catastrophically dispersed.

### 7.3 Cluster-integrity diagnostic

Centroid position alone cannot distinguish "the centroid reached the target" from "the particles
remained physically clustered and were transported coherently." We report per-axis standard deviation,
RMS radial spread, and maximum particle-to-centroid distance, each normalized against a baseline
captured at the start of that cluster's transport attempt, to make cluster dispersal a directly
measurable, reportable quantity rather than an animation-only judgment call.

## 8. Results

*[PENDING — table with columns Q0/Q1/Q2/Q3 × {arrival error, final speed, transport time, max speed,
max accel, max F/W, min separation, max saturation, final RMS spread, spread ratio vs. initial,
pass/fail}, plus mean/std across the four cases. To be filled in once the transport_0 validation gate
passes and, if it does, the four-cluster run completes. If the current controller does not clear the
gate, this section will report that honestly, with the specific failure mode and the metrics at the
point of failure, per the same table.]*

## 9. Discussion

*[PENDING — interpretation of results; how close the controller comes to the theoretical force/margin
budget derived in §5-6; whether observed failure modes (if any remain) are fundamental to this
actuator geometry/timestep or addressable with further engineering; comparison of the controller's
real closed-loop behavior against the idealized point-mass design assumptions.]*

## 10. Limitations and Assumptions

- Single-dipole-per-cluster actuation; no investigation of whether a multi-dipole configuration could
  relax the standoff/near-field tradeoff identified in F21.
- The paramagnetic force model uses on-axis dipole approximations for control-law derivation
  (`_raw_gradB2_onaxis`, `solve_strength_for_accel`); the real force computation used by the physics
  engine itself is the full off-axis analytical Jacobian, cross-checked against the on-axis design
  estimates but not identical to them in general geometry.
- Near-zero-total-velocity BRAKE fallback branch (`trap_in*0.3` strength law) pre-dates this
  controller-design pass and was left untuned/unvalidated to the same standard as the primary
  velocity-driven branches — out of scope for findings F19–F21, documented as a known gap.
- The shaping and holding phases (post-transport) are outside this paper's validated scope; see
  `simulation/CONTEXT.md` for their current, separately-tracked state.
- Simulation-only validation; no physical hardware demonstration.
- *[Add: any limitation surfaced by the final validation-gate outcome once known.]*

## 11. Conclusion

*[PENDING — final framing once §8/§9 are complete: either "a physically defensible, reproducible Phase
2 controller achieving X" or an honest negative/partial result characterizing exactly what magnetic-only
transport of free granular clusters can and cannot achieve under this actuator model, per the project's
standing principle that a well-characterized negative result is a valid scientific outcome.]*

---

## Figure list (can be prepared before final results)

- F1: System schematic (dipole actuator, granular bed, four target quadrants).
- F2: Force-vs-standoff curve for the design dipole (from `_accel_at`/`_raw_gradB2_onaxis`), showing
  the clamp ceiling and the operating standoffs used by LIFT/CRUISE/BRAKE.
- F3: State-machine diagram (LIFTOFF→LIFT→CRUISE→BRAKE→SETTLE→ARRIVAL, with the hysteresis band and
  stall safety net).
- F4: Example real transport trajectory (z, d, v vs. t) — to be regenerated from the final validated
  run, not an earlier failed attempt.
- F5 (if applicable): cluster-integrity metric (RMS spread ratio) vs. time, showing coherence
  maintained through transport.
- F6: Four-cluster summary table (§8) rendered as a figure/table.
