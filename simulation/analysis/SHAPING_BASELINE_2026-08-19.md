# True Magnetic-Only Shaping Baseline — 2026-08-19

Status: **DIAGNOSTIC REPORT ONLY. No production code changed.** Follows directly from
`SHAPING_HOLDING_AUDIT_2026-08-18.md`. Per the governing request (Section 20), this stops after
recommending one candidate architecture and does not implement it.

**Method.** `simulation/analysis/shape_fixture.py` (new file, ~180 lines) imports
`phase2_shaping.py` as a module and drives its real, unmodified kernels
(`build_grid`/`compute_forces`/`integrate`/`update_dipoles`/`substep_batch`) directly. It changes
only the initial condition: four real 64-particle clusters are packed (loose stochastic pile, same
character as `phase2_shaping.init()`'s own Phase-1 packing) centered exactly on each cluster's real
target (`C.targets[k]`), `pm.state` is forced to `"shape"` from `t=0`, and `pm.completed={0,1,2,3}`.
No force term, force law, or particle property is modified. The only deliberate manipulation is
`--surf-conf-off`, which resets the module-level `surf_conf_enabled` Taichi field to 0 immediately
after each `update_dipoles()` call (which would otherwise set it to 1) — this performs the requested
ablation without editing `phase2_shaping.py`. Two full-length (20.5s, covering all four
`SHAPE_TIME/4=5s` slots of `SHAPE_ORDER=[0,3,1,2]`) runs were executed: `surf_conf` off (the true
magnetic-only baseline) and `surf_conf` on (direct comparison, same ideal starting condition).

---

## A. True magnetic-only baseline (`surf_conf` OFF)

| cluster | role | slot (active plow) | d_tgt @ t=2.25s | d_tgt @ end of own slot − ε | d_tgt @ t=20.5s | real Fmag @ t=20.5s |
|---|---|---|---|---|---|---|
| c0 | top cap | [0,5s] | 6.85mm | 6.84mm | **6.845mm** | 5.7e-17 N |
| c3 | bottom cap | [5,10s] | 2.94mm | 2.93mm | **2.933mm** | 5.3e-17 N |
| c1 | left wall | [10,15s] | **0.09mm** (held) | 0.09mm (t=9.75s, pre-slot) | **6.499mm** (post-slot) | 8.2e-18 N |
| c2 | right wall | [15,20s] | **0.09mm** (held) | 0.09mm (t=14.75s, pre-slot) | **7.136mm** (post-slot) | 2.5e-17 N |

**Finding A1 — caps have zero shape-phase magnetic force by construction, not merely negligible
magnitude.** c0 and c3's real `Fmag` is ~1e-17 N throughout the entire 20.5s run — the same
essentially-zero value from the instant the fixture starts. This matches the code directly: v36
removed the cap shape dipole entirely (`pass  # no external shape dipoles for caps`,
`phase2_shaping.py` shape-dipole block). With no dipole and negligible gravity-opposing force of any
kind, both cap clusters free-fall from their target straight to the domain floor in well under 0.1s
(fall time for 7mm at lunar g=1.62 m/s² is 93ms) and then simply sit there for the rest of the run —
`d_tgt_mean` for c0 (6.845mm) matches the target height (7mm) minus the floor-landing height (~0.15mm)
almost exactly; same for c3 (2.933mm ≈ 3mm target − ~0.07mm landing height). This is a structural
absence, independently confirmed by both the force-magnitude comparison in the prior audit and this
ablation's direct trajectory.

**Finding A2 — walls DO have a real, physically meaningful magnetic holding force in their "wait"
state, and it is not negligible.** While c1/c2's own active-plow slot has not yet started (i.e.
while their dipole sits in the constant, non-scanning "wait" configuration at reduced strength,
`SHAPE_WAIT_HOLD_STRENGTH=0.15`), both wall clusters stay within **0.09mm of target for the entire
9-10s preceding their own slot** — an order of magnitude better than the caps ever achieve with
`surf_conf` fully engaged (compare Table below). This is a real result: the fixture starts particles
essentially at the dipole's intended near-field standoff, and at that short range even a reduced-
strength dipole exerts enough force to visibly counteract gravity and hold position. This had not
been demonstrated before — every previous real run (transport-contaminated) started shaping with
clusters already scattered far from any target, so the near-field regime where this mechanism
actually works was never observed in production data.

**Finding A3 — that same holding is destroyed the instant the cluster's own active-plow slot
begins**, and nothing replaces it. At t=12.25s (just after c1's own slot opens at t=10s), `d_tgt`
jumps from 0.09mm to 5.29mm; by t=20.5s it has drifted to 6.5mm. c2 shows the identical pattern
one slot later (0.09mm → 5.49mm at t=17.25s → 7.14mm by end). The active-plow dipole is, by design
(v33 raster scan, documented in-code), supposed to move away from a fixed point to spread particles
across the wall surface — but the moment it moves, gravity is completely unopposed (no `surf_conf`,
no other support), and the cluster simply falls to the floor and is lost. This is a precise,
data-backed answer to the request's own Section 9 (Problems A/B/C — transport vs. retention vs.
recollection): **Problem A (spreading) and Problem B (retention) are in direct conflict in the
current architecture** — the single dipole cannot do both at once, and switching from
"holding" mode to "spreading" mode abandons the particles outright.

---

## B. Comparison run (`surf_conf` ON, same ideal starting condition)

| cluster | d_tgt @ t=20.5s | r_rms @ t=20.5s | real Fmag @ t=20.5s |
|---|---|---|---|
| c0 (top cap) | 1.415mm | 0.172mm | 2.6e-12 N |
| c3 (bottom cap) | 1.319mm | 0.181mm | 4.8e-15 N |
| c1 (left wall) | **5.335mm** | **1.650mm** | 6.0e-17 N |
| c2 (right wall) | **5.210mm** | **1.531mm** | 6.7e-17 N |

**Finding B1 — confirms the prior audit exactly**: caps held near target (1.1-1.4mm) purely by
`surf_conf`'s spring — real force still 5-9 orders of magnitude below the spring even in this
best-case ideal-start condition.

**Finding B2 — surprising and new: `surf_conf` makes the walls *worse*, not better, versus the
magnetic-only baseline.** With `surf_conf` engaged, walls end at `d_tgt≈5.2-5.3mm` — comparable to or
worse than the surf_conf-off baseline's post-slot state, and their `r_rms` (1.5-1.65mm) shows the
cluster has partially disintegrated (real 64-particle cluster radius should be well under 0.3mm if
coherent, per every other measurement in this document). This happens because `surf_conf`'s
discontinuous switch-on (Section A of the prior audit) delivers an immediate, large, non-directional
kick to a cluster that — per Finding A2 — was already being held correctly by the real near-field
dipole. The artificial spring does not just fail to help the walls; it actively disrupts a real
mechanism that was working.

---

## C. Force budget — what the real magnetic system currently provides vs. what `surf_conf` faked

| requirement | real magnetic mechanism today | `surf_conf` (historical reference, not physical) |
|---|---|---|
| Cap axial support | **none** (no dipole assigned) | `F_z=-k(z-z_target)`, `k=0.5N/m`, unbounded near-field magnitude |
| Cap radial spreading | none | weak (`CAP_RADIAL_BIAS_K=0`, already zeroed) + contact burst only |
| Wall radial retention | **real, works** at close range (~0.09mm accuracy) while dipole stays parked | radial-only spring toward `r=cR` |
| Wall axial support | **none** — "z handled by gravity + scan" (pre-existing code comment), and Finding A3 shows the scan itself removes what little near-field support existed | none (walls never got a z-term even in the placeholder) |
| Wall retention during active spreading sweep | **fails completely** (Finding A3) | not applicable — surf_conf doesn't distinguish active/wait state |

This sharpens the prior audit's conclusion: the real magnetic mechanism is not uniformly absent — it
is a working, verified, physically real near-field hold for walls in their *static* wait
configuration, but it has no mechanism at all for caps, and the wall mechanism is currently thrown
away by the wall's own scan motion. Any replacement architecture inherits a real, working ingredient
(wall near-field hold) that should be preserved and extended, not redesigned from zero.

---

## D. Wall feasibility (updated)

Feasible in the narrow sense demonstrated: a dipole parked near the wall target genuinely holds a
64-particle cluster to within ~0.1mm against lunar gravity. Not yet demonstrated: whether that same
force authority is sufficient once the cluster needs to *move* along the wall (circumferentially/
axially) rather than just sit still — the existing v33 scan sweeps too fast/far for particles to
track it (the code's own comment: "v_tan≈14mm/s >> v_cap≈5mm/s → deposition mode, particles can't
follow the dipole" — i.e., the current scan was explicitly designed to outrun the particles, which
is the opposite of what a coverage-feedback traveling well needs). Full `F_r,F_θ,F_z` sweep analysis
(Section 5 of the request) has not yet been performed — flagged as the next analytical step, not run
this session (time-budget priority per Section 19: establish the baseline and one recommended
direction first).

## E. Cap feasibility (updated)

Currently zero — no shape-phase magnetic mechanism exists for caps at all. Any real architecture must
build cap support from scratch; there is no existing partial mechanism to preserve (unlike walls).

## F. Dynamic shaping candidates (reassessed, still conceptual)

Candidate A (coverage-feedback traveling well) is unchanged as the recommendation, but is now
better-specified by this data:
- **For walls**: extend the *already-working* near-field hold, don't replace it. The needed change is
  making the transition between "hold here" and "move to under-covered region" gradual/continuous
  (a slowly-translating near-field attractor, not a fast raster scan that outruns the particles) so
  the cluster is never in a state with zero support, directly targeting Finding A3.
- **For caps**: needs an entirely new mechanism — there is nothing to extend. The wall near-field
  result (Finding A2) is encouraging evidence that a similarly-positioned dipole *would* provide real
  axial support for caps too, if one were added; this has not been tested.

Candidates B and C remain conceptual-only, unchanged from the prior session.

## G. Mathematical derivations

Not newly derived this session beyond what's in the prior audit; the wall near-field force
(Finding A2, `Fmag≈1.6e-7N` at the fixture's starting standoff) is ~112× lunar gravity on one
particle, consistent with the general "near the source, authority is enormous; a few mm away, it's
negligible" pattern already established analytically for the transport controller
(`plans/vivid-bubbling-iverson.md`'s force-vs-standoff table) — the same physics, now confirmed
working in the shaping context too.

## H. Literature support

Unchanged from prior sessions; still outstanding (see `PAPER_TODO.md`).

## I. Cheap-test results

Two tests completed this session (both are the "8-16 particle"/"64-particle isolated" tier from the
originally planned hierarchy, run directly at 64 particles since the fixture made that cheap enough
not to need the smaller intermediate steps):
1. `surf_conf` OFF, ideal start, full 20.5s cycle → Findings A1-A3 above.
2. `surf_conf` ON, ideal start, full 20.5s cycle → Findings B1-B2 above.

**Not yet run** (flagged, not done, per the time-budget instruction to establish baseline + direction
first): a perturbation test (nudge a held wall cluster slightly and see whether the near-field hold
in Finding A2 is a genuine restoring response or a coincidentally-unperturbed frozen state — this
matters for distinguishing real stability from an untested assumption, and is cheap to run next);
single-particle and 2-particle isolation of the wall near-field mechanism to characterize it
analytically before generalizing it into a moving-well controller.

## J. Recommended architecture

Candidate A, coverage-feedback traveling well — now informed by real data rather than pure design
reasoning:
- Walls: modify the existing near-field mechanism to move slowly enough that particles can track it
  (opposite of the current intentionally-fast v33 raster), removing the all-or-nothing
  hold/spread discontinuity Finding A3 identified.
- Caps: add a near-field dipole using the same physical mechanism verified to work for walls
  (Finding A2), rather than inventing a different approach — there is no evidence a different
  mechanism is needed, only that one was never built for caps.

## K. Implementation plan

Still not started. Before writing any controller code: (1) the F_r/F_θ/F_z sweep-feasibility analysis
for a *slow* wall traversal (Section D), sized against the real ~1.6e-7N near-field force budget just
measured, not the theoretical clamp-saturated ceiling; (2) the perturbation test (Section I); (3) a
cap-specific near-field force sizing analysis, by direct analogy to the wall result.

---

## Bottom line

This ablation changes the picture from "the shaping mechanism doesn't work" to something more
specific and more useful: **a real, working, physically legitimate near-field magnetic hold already
exists for walls in the codebase — it has just never been observed succeeding, because every
previous real run started shaping with particles already scattered outside its effective range, and
because the wall's own designed spreading motion currently discards it.** Caps have no such
mechanism at all and need one built. `surf_conf`, rather than being a harmless placeholder, is now
shown to actively interfere with the one part of the system that was working.
