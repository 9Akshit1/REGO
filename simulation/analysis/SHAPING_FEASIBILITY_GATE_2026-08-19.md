# Final Pre-Implementation Shaping Feasibility Tests — 2026-08-19

Status: gate report per the governing request's Section 14 format. Produced BEFORE the
production code change described at the end of this document (which was then implemented,
since the wall tests passed decisively, per the request's own instruction not to ask for another
architectural decision unless a feasibility test failed — one did: caps).

All tests use `simulation/analysis/shape_feasibility.py` (new), isolating exactly one real dipole
at a time against a real 64-particle cluster, reusing `phase2_shaping.py`'s unmodified
`build_grid`/`compute_forces`/`integrate` kernels. `surf_conf` is off throughout (either by
construction — these tests never call `update_dipoles()`, so `surf_conf_enabled` stays at
`init()`'s default 0 — or explicitly forced off in the two tests that do call it).

**Self-caught bug, disclosed for the record**: the first two full-field force-budget runs
(`force_budget_full_field.py`, `force_attribution.py`) initially forgot to force
`surf_conf_enabled=0` after `update_dipoles()`, so they unknowingly measured the wall cluster
fighting the artificial spring, producing a nonsensical 31.7×W radial force and total dispersal
(r_rms up to 2.8mm within 0.1s). Caught by cross-checking against the independent
perturbation-test results, fixed, and rerun — see "Errors" note in this file's git history / the
inline comments in both scripts.

---

## A. Wall hold perturbation (Section 1)

Real "wait" hold config reproduced exactly from `phase2_shaping.py:2556-2565`: dipole AT the
target (zero standoff), moment purely radial inward, `s=SHAPE_WAIT_HOLD_STRENGTH=0.15`. A 0.3mm
offset applied to the whole 64-particle cluster, one axis at a time, no dipole motion.

| axis | initial \|err\| | behavior | verdict |
|---|---|---|---|
| radial | 0.265mm | drops to 0.02-0.08mm within 0.2s, then persists as a bounded, **underdamped oscillation** (peak v 20-78mm/s) through t=4s — never fully quiets | genuinely restoring, stable, NOT a quiet equilibrium |
| tangential | 0.277mm | same character; couples into radial motion (broken symmetry) | stable, cross-axis coupled |
| axial | 0.276mm | z-error resolves fast (<0.01mm by t=0.2s) but couples into sustained radial oscillation | stable, cross-axis coupled |

**Verdict: genuinely dynamically stable in all three directions tested** — this is real restoring
dynamics, not "stayed still because nothing disturbed it" (directly answering the request's own
distinction in Section 1). But it is a stiff, oscillatory near-field regime, not a quiet hold —
this reframes (does not overturn) the prior session's "0.09mm hold" finding: that number was from
coarse 1s-interval sampling of what is actually a persistent, higher-frequency oscillation.

---

## B. Cluster-level vector force budget (Section 2)

Confirms the request's core warning directly: **summing force magnitudes overstates the real net
force by ~100-300×.** At the exact wait-hold configuration, freshly packed:

| quantity | value |
|---|---|
| `sum_of_magnitudes` | 1.18e-5 N |
| `\|vector_sum\|` (correct) | 3.67e-8 N (320× smaller) |

At t=2s under the real full field (all 4 clusters' real dipoles + corner quadrupoles active,
`surf_conf` correctly off): vector-decomposed in the wall's local (radial, tangential, axial)
frame: `F_r=0.178×W`, `F_t=-0.863×W`, `F_z=0.383×W` (`W`=64-particle cluster weight). Attribution
(each dipole isolated in turn) confirms this is **entirely cluster 1's own wait dipole** — cross-talk
from cluster 2's dipole and from the corner quadrupoles both measure exactly zero at this instant.
The nonzero tangential component (which a perfectly symmetric analysis would predict as zero) is
real, arising from genuine asymmetry in the dynamically-evolved particle packing — consistent with
finding A's cross-axis coupling.

**Net vertical support is only 0.38×W** — not enough to statically hover. Consistent with finding
A: the cluster is not resting in static equilibrium, it's held by a genuinely dynamic, oscillatory
balance.

---

## C. Slow translating well (Sections 3-4)

Same wait-hold geometry (zero standoff, radial moment, `s=0.15`), translated azimuthally at
constant angular speed, `strength` held constant. Tracking error = distance from real cluster
centroid to the instantaneous aim point.

| v_tan | behavior |
|---|---|
| 0.1, 0.5, 1.0, 2.0, 5.0 mm/s | **No speed-dependent degradation.** `\|err\|` stays in the same 0.01-0.15mm band at every speed, entirely explained by the intrinsic radial oscillation from test A — tangential/axial tracking error stay <0.006mm even at 5mm/s. `Fmag` and `min_sep` stay in their nominal ranges throughout. |
| 10 mm/s | Onset of real degradation: `\|err\|` occasionally reaches 0.28mm, `min_sep` grows to 0.16mm, `Fmag` dips to ~half-nominal at those moments — but the cluster stays attached (`r_rms` flat, coherent) and recovers. |
| 15 mm/s | **Catastrophic tracking loss** at t≈2.4s: `\|err\|` jumps to ~7mm, `min_sep` to ~6.9mm, `Fmag` collapses to ~4e-18N (particles left behind, out of the dipole's effective range entirely). |

**This independently confirms, from direct simulation rather than the existing back-of-envelope
comment, the pre-existing `v_tan≈14mm/s` "particles cannot follow" threshold already documented in
`phase2_shaping.py`'s v33 wall-scan section** — the old fast raster was deliberately operating just
above this same boundary to get deposition-mode spreading; a coverage-tracking well needs to stay
well below it.

**Recommended operating speed: ≤5mm/s**, giving a ≥2× margin under the onset of degradation (10mm/s)
and a ≥3× margin under catastrophic failure (15mm/s).

---

## D. Cap parked-hold feasibility (Sections 5-6)

Candidate geometry: direct analogy to the already-validated wall active-slot z-lift branch
(`phase2_shaping.py:2549-2555`) — dipole above/below the cap plane, moment along z, strength sized
via `solve_strength_for_accel` for a 3× gravity margin (same convention used throughout the
codebase's transport/hold sizing).

| standoff | strength (solved) | `F_z/W` (real vector sum, t=0) | outcome |
|---|---|---|---|
| 1.0mm | 1.0 (saturated) | **0.428** | Insufficient even at max strength — cluster free-falls to the floor within 0.2s (`err_z→-6.93mm`) |
| 0.5mm | 0.245 | **4.09** (ample) | Force budget looks fine, but dynamics are **violently unstable**: `r_rms` grows unbounded to 3-3.5mm (cluster disintegrates into a diffuse cloud), peak velocities 60-160mm/s that never decay |

**Verdict: infeasible with this geometry.** There is no standoff in the tested range where a single
on-axis point dipole delivers both (a) enough real vector-summed force to support the finite
64-particle cluster and (b) stable, non-dispersive dynamics. This is the same
vector-summing pitfall from Section B, now shown to be load-bearing: the single-particle sizing
formula (`solve_strength_for_accel`, calibrated for one on-axis particle) does not transfer to the
finite, partly-off-axis real cluster — at 1mm it under-delivers by more than 2×; the fix (moving
closer) trades the force deficit for a near-field instability instead. **This is a genuine,
demonstrated infeasibility of the "copy the wall's mechanism" approach for caps, not a tuning
problem** — consistent with (though a different, sharper mechanism than) the codebase's own
historical v13-v28 finding that a single static point-like source produces a single point
attractor, not distributed support.

---

## E-F. Dynamic shaping candidates / literature

Unchanged from the prior session (Candidate A, coverage-feedback traveling well) for walls — now
implemented (see below). For caps, no candidate geometry has passed a feasibility test; this
remains open. Candidates worth investigating in a future session (not tested here, time-budgeted
out per the request's own priority order): a laterally- or azimuthally-offset dipole (breaking the
on-axis symmetry that concentrates the instability at close range); multiple sequentially-active
near-field points visiting different parts of the cap rather than one fixed point (spreading the
support duty so no single point has to carry 100% of the cluster weight at a singular standoff);
or accepting that caps may need a materially different physical mechanism than walls.

## G. Mathematical derivations

Vector force budgets in Sections B and D are the governing new results; no closed-form derivation
was attempted this session beyond what's in the prior audit — every number here is a direct
measurement against the real 64-particle geometry and real field law, per the request's own
"actual vector sum, not sum of magnitudes" requirement.

## H. Cheap-test results

All of Sections A-D are the cheap tests (single-cluster, ≤4s duration, no full Phase 2 run). No
full 20s Phase 2 simulation was run this session, per the time-budget instruction.

## I. Recommended architecture

**Walls**: implemented (see below) — slow (≤5mm/s) coverage sweep at the validated wait-hold
geometry (zero standoff, radial moment), gated by real-time tracking error (pause/resume, never
deliberately outrunning the cluster), replacing the old fast (~14mm/s) v33 raster.

**Caps**: no implementation. No candidate has passed a feasibility test. Left honestly unsupported
in production (see below) rather than propped up by `surf_conf`.

## J. Implementation plan (executed)

In `simulation/phase2_shaping.py`:
1. `surf_conf_enabled` is no longer set to 1 anywhere — the gating in `update_dipoles()`
   (previously `if pm.state=="shape": surf_conf_enabled[None]=1`) is removed; `surf_conf`'s
   kernel code and its extensive non-physical-placeholder documentation are left in place
   (per the request's Section 12: kept as historical/ablation reference, not deleted), but it can
   no longer activate in a real run.
2. The wall active-slot branch (old v33 fast ±60° raster + 4-cycle z oscillation) is replaced with
   a closed-loop slow well: dipole tracks a (θ, z) aim point that advances at a validated-safe
   angular rate (`WELL_V_TAN=3mm/s`, 1.7× margin under the measured 5mm/s clean ceiling, 3.3×
   under the 10mm/s degradation onset) only while real tracking error stays under
   `WELL_TRACK_ERR_MAX`; otherwise the aim point freezes until the cluster catches up. z steps
   between discrete levels once each θ sweep completes.
3. Caps' shape branch is unchanged (`pass — no external shape dipoles for caps`) — still honestly
   zero mechanism, now no longer propped up by `surf_conf` either.
4. `SIM_VERSION` bumped; `HISTORY.md` updated with the full derivation and honest statement that
   caps are now a known, demonstrated open problem, not a silently-passing placeholder.

## K. Validation plan

Not yet re-run against a full Phase 2 simulation this session (time-budgeted out — the isolated
tests above are the validation for the mechanism itself). Recommended before trusting a full run:
rerun the isolated shaping fixture (`shape_fixture.py`) with the new wall code to confirm coverage
over a full slot without the tracking-error gate ever needing to freeze for more than a small
fraction of the slot budget; extend `validate_phase2.py` with an automated check that wall tracking
error never exceeds `WELL_TRACK_ERR_MAX` by more than the intrinsic oscillation envelope during an
active slot.
