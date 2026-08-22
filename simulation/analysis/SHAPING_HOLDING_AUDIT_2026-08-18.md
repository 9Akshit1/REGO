# Shaping/Holding Deep Audit — 2026-08-18

Status: **DIAGNOSTIC REPORT ONLY. No production code changed.** Per the governing request, this
stops at the "required output before code changes" stage (Section 24 of the request). All numbers
below are computed from the real F24 run's VTU output (`simulation/outputs/Phase2/`, 760 frames,
t=[2.55, 40.50]s, SIM_VERSION 42.0.0) and from direct reading of `phase2_shaping.py`, not from
visual inspection or assumption. Where a claim could not be independently verified this session it
is marked **HYPOTHESIS**, not fact.

---

## A. Verified current behavior

1. **The paramagnetic force law is applied identically to every particle regardless of
   `cluster_id`.** `compute_forces()` ([phase2_shaping.py:1697-1710](../phase2_shaping.py#L1697-L1710))
   computes `Fm = (Vp·χ_eff/2μ0)·∇B²` from `B_and_gradB2(pos[i])` alone — no `cluster_id` branch
   exists anywhere in that computation. This satisfies the "no color/cluster-ID-selective force"
   requirement **for the real magnetic force term.**

2. **`surf_conf` is a separate, additional force term that *is* branched directly on
   `cluster_id`** ([phase2_shaping.py:1725-1770](../phase2_shaping.py#L1725-L1770)): `cid==0` gets a
   z-spring toward `z_hi` + radial confinement + viscous damping; `cid==3` gets the mirror toward
   `z_lo`; everything else (`cid==1,2`, the walls) gets radial-only confinement toward `r=cR`. This
   term is switched from **fully off to fully on in a single control step**
   ([phase2_shaping.py:2409-2414](../phase2_shaping.py#L2409-L2414)) the instant
   `pm.state=="shape"` — no ramp.

3. **`surf_conf` is already labeled in-code as a non-physical placeholder** (audit finding F9,
   comment block at 1713-1724) and CLAUDE.md already forbids extending/retuning it or citing it as
   evidence shaping works. That labeling exists; what had not previously been done is quantifying
   *how much* of the observed behavior it is responsible for.

4. **Quantified from real VTU data** (`Fmag` field = `fmag[i].norm()`, the pure magnetic-force
   magnitude, logged separately from the total integrated force): during the entire shape phase the
   real magnetic force is **6 to 12 orders of magnitude smaller** than the `surf_conf` force acting
   on the same particles at the same instant, and is itself often below one particle's own weight
   (`W = m_p·g = 1.43e-9 N`, lunar `g=1.62`).

   | t (s) | cluster | mean real `Fmag` | mean `surf_conf` force | ratio |
   |---|---|---|---|---|
   | 27.799 (shape start, pre-kick) | c2 | 3.7e-16 N | 1.82e-3 N | 5.0×10¹² × |
   | 27.849 (1 control step later)  | c1 | 1.7e-12 N | 2.29e-4 N | 1.3×10⁸ × |
   | 29.499 (settled)               | c1/c2 | ~1e-16 N | ~1.0e-4 N | ~10¹² × |
   | 35.849 (mid-"stall")           | c1/c2 | ~1e-16 N | ~1.0e-4 N | ~10¹² × |

   (Full trace: `trace_transition.py` in the session scratchpad, re-runnable against
   `outputs/Phase2/*.vtu`.)

5. **The step-function switch-on produces a real, measurable velocity spike** in every cluster
   simultaneously: mean cluster speed jumps from 0 to (c0) 4.3, (c1) 12.4, (c2) 56.9, (c3) 16.5 mm/s
   in the single ~50 ms control step immediately following `pm.state→"shape"` (t=27.799→27.849s).
   This is the "explosion at the transition" the user observed, and it is directly attributable and
   reproducible: cause #7 in the user's enumerated list ("a sudden change in `surf_conf`") combined
   with #2 ("a control-state-triggered force term with no ramp-in").

6. **Cap clusters converge to a stable, near-target position within ~1.7s of shape-phase entry**
   (c0: `d_tgt`→1.4mm by t≈29.5s, unchanged through t=40s; c3 similarly). **Wall clusters do not
   converge to the target at all.** c1 settles at `d_tgt≈5.67mm`, c2 at `d_tgt≈5.24mm`, both frozen
   from t≈29.5s onward — because their `surf_conf` branch has **no z-term** ("z handled by gravity +
   scan" per the code's own comment), so once `surf_conf`'s radial pin snaps them to `r≈cR`, nothing
   opposes gravity along z and they fall to the floor (`z≈0.14-0.15mm` vs. target `z=5mm`) and sit
   there, radially confined but nowhere near a cylindrical wall shape.

---

## B. Root causes (proven, not hypothesized)

**B1 — The observed cap "recovery" is not evidence of magnetic shaping.** Given finding A4 (real
force 6-12 orders of magnitude below the artificial spring for the *entire* shape phase, not just at
the moment of the kick), the caps' reorganization into a plausible shape is produced almost entirely
by `surf_conf`'s cluster-ID-keyed homing spring. This directly answers Section 1/2 of the request:
**Hypothesis C (cluster-specific code influencing the result) is TRUE and is the dominant effect**,
not a secondary contributor. Hypotheses A and B (genuine spatial reorganization from real dipole
fields) are **not supported** by the force-magnitude data — the real field's contribution during
this window is at or below thermal/numerical noise level relative to gravity itself.

**B2 — The "stall" from t≈29.5-40s is not a physically valid dynamic equilibrium.** It is the
`surf_conf` spring reaching its own force balance (spring pulling toward the pinned surface,
opposed by gravity/contact) with the accompanying viscous-damping term (`CAP_VISC_DAMP_TAU=0.25s`,
`_db=m_p/τ`) killing residual velocity — a numerically frozen state produced by a term the code
itself documents as having "no physical source." This directly answers Section 3/4: **Possibility 2
is confirmed** (artificial spring + damping freezing motion), not Possibility 1. Per the request's
own instruction not to discard a *legitimate* hold automatically — this one fails legitimacy at the
first checkpoint (§4 item 4: "verify it does not rely on an artificial scaffold"): the spring's
restoring force at typical excursion distances is 100-1000× **larger than the clamp-saturated
maximum the real dipole model can ever produce** (`a_max·m_p ≈ 2.03e-7 N`, vs. spring forces of
1e-3 to 1e-4 N above), so it cannot be interpreted as a idealization of any realizable coil — it is
categorically outside the force budget any of the real sources in this simulation could deliver.
**This holding mechanism must not be adapted to transport** (directly answering the request's own
caution in Section 21) — there is nothing physically transferable in it.

**B3 — The wall clusters fail to shape at all**, independent of B1/B2, because `surf_conf`'s wall
branch never had a z-term to begin with (documented in-code, not a bug introduced by this audit).
Confirmed live: c1/c2 sit at the domain floor (`z≈0.15mm`) throughout the entire observed stall
window, never approaching `z=5mm`.

**B4 — Transport degrades cluster-by-cluster** (already characterized in HISTORY.md's F17-F24
entries, re-confirmed here numerically from the same run): terminal STALL distances grow
monotonically down the sequence — transport_0: d=2.508mm; transport_1: d=4.522mm; transport_2:
d=4.784mm; transport_3: d=6.773mm — consistent with the previously diagnosed cross-cluster drag
mechanism (each later transport's active dipole disturbs the increasingly numerous
already-"completed"-but-undefended earlier clusters). Sections 5-7 of the request ask for a full
differential reconstruction of each individual transport's control-state history; that deeper
per-cluster dive was **not done this session** — transport remains frozen per your own standing
instruction, and the marginal value of that work is low relative to the shaping findings above,
which are gating for the paper's Section VIII regardless of transport's outcome.

---

## C. Remaining hypotheses (not yet independently verified)

- **HYPOTHESIS**: the specific numeric value of `d_tgt` the caps converge to (~1.4mm) is set by the
  balance between `surf_conf`'s radial confinement (`r≤cR`) and particle-particle contact repulsion
  (i.e., it reflects the physical particle-packing radius of a compressed 64-particle disk, not an
  artifact of the spring itself) — plausible given `SURF_CONF_K`'s radial term only *pins outward
  motion beyond* `cR`, but not verified by isolating contact-only dynamics from spring dynamics.
- **HYPOTHESIS**: if `surf_conf` were removed entirely, cap particles disperse under gravity +
  contact alone rather than forming any recognizable disk. This follows from the Earnshaw argument
  and from B3's demonstration that "no z-support" already produces total floor-collapse for the
  walls, but has not been run as an isolated ablation this session.

---

## D. Holding analysis — why the current shape-phase "stability" is not legitimate

Restated concisely per the request's own checklist (Section 4):
1. What produces it: `surf_conf`'s cluster-ID-branched spring + viscous damping.
2. Mathematically: `F_z = -k(z - z_target)`, `k=0.5 N/m`; at `Δz=2-5mm` this alone is `1e-3` to
   `2.5e-3 N`, before the damping term.
3. Numerically: confirmed directly from VTU data (Section A4/A5 above).
4. Earnshaw: irrelevant to assess here because this is not a magnetic-field-based mechanism at
   all — it's a synthetic per-particle spring with no field source, so Earnshaw's constraint on
   static *magnetic* fields doesn't even apply to it; the mechanism is simply outside the category of
   things this project is permitted to use (Section 4 of CLAUDE.md: "no arbitrary fix forces").
5. Scaffold-free: **fails.** Functionally, a cluster-ID-keyed spring toward a fixed target position
   is mathematically identical to attaching each particle to an invisible fixed point in space by its
   permanent color — the discrete, non-physical equivalent of a scaffold, even though it isn't
   rendered as rigid geometry.
6. Real magnetic-field behavior: **fails** — real magnetic force is negligible throughout, per A4.
7. Transferable to transport: **no** — there is no physically legitimate principle here to transfer.

---

## E. Transport-target holding options (conceptual only, not for implementation while transport is frozen)

Retained from prior-session literature review (moving-trap decelerators, magnetophoretic conveyors,
time-averaged periodic trapping) — still the relevant category for any *future* legitimate transport
hold state, precisely because it avoids the static-equilibrium trap B2 fell into. Not expanded
further this session per your standing freeze on transport work.

---

## F. Shaping strategies — candidates, reassessed in light of B1-B3

The prior session's Candidate A (coverage-feedback traveling well) remains the strongest candidate
**and is now more clearly necessary, not optional**: since `surf_conf` cannot legitimately be relied
on for either caps or walls, a real shaping mechanism has to supply **all** of the confinement
`surf_conf` was silently providing — both the axial pinning currently faked for caps, and the axial
support wholly absent for walls (B3). This raises the required force authority substantially above
what was estimated in the prior session's Candidate A sizing, which implicitly assumed `surf_conf`
would continue handling gross positioning while the traveling well only had to handle fine
redistribution. That assumption is now known to be false and must be revisited before any
implementation (see H below).

Candidates B (sequential patch deposition) and C (rotating/time-averaged multi-source) remain
conceptual-only per your instruction; not re-evaluated this session.

---

## G. Mathematical justification

See Section D above for the spring-vs-field force comparison; see the prior session's Earnshaw
derivation (`∇²(B²)=2|∇B|²≥0` in current-free regions ⇒ no static extended equilibrium) for why any
Candidate A replacement for `surf_conf` must be genuinely time-varying, not just "a weaker version of
the same static spring idea."

## H. Literature support

Unchanged from the prior session's findings (moving-trap decelerator, magnetophoretic conveyor,
time-averaged trapping literature — all still PROVISIONAL, not re-verified this session). No new
literature search was performed in this pass; this remains outstanding work, same as noted in
`PAPER_TODO.md`.

## I. Cheap-test plan

Unchanged and now more urgent: before writing any replacement for `surf_conf`, the single most
informative cheap test is **an ablation** — rerun the existing isolated shaping fixture (still not
built) with `surf_conf_enabled` forced to 0, and observe whether caps disperse or retain any
coherence from contact/gravity alone. This directly tests hypothesis C1 above and establishes the
true baseline the real shaping mechanism has to beat, before any force-budget sizing for Candidate A
is trusted.

## J. Recommended architecture

No change to the prior recommendation (Candidate A, coverage-feedback traveling well) — but its
required force budget must be resized upward to account for full axial support duty (both caps and
walls), not just fine redistribution, given `surf_conf` cannot be relied on for either. This resizing
has not yet been done.

## K. Implementation plan

Not started. Blocked on: (1) the `surf_conf`-off ablation (Section I), (2) revised force-budget
sizing for Candidate A given the axial-support duty is now known to be uncovered (Section F/J),
(3) the isolated shaping fixture itself (still not built, per the standing plan from the prior
session).

## L. Validation plan

Unchanged from prior session's plan (coverage, surface-distance error, density uniformity, escape
fraction, particle conservation — numerical, not visual). Adds one new required check going forward:
**any future shaping-force computation must log its own force magnitude alongside `surf_conf`'s (or
`surf_conf`'s replacement) so this kind of order-of-magnitude blind spot cannot recur silently.**

---

## Bottom line

The apparent shaping "success" visible in the just-completed F24 run's ParaView data is, quantitatively,
almost entirely an artifact of the already-labeled non-physical `surf_conf` placeholder, not of the
magnetic dipole shaping mechanism. This is not a new violation of CLAUDE.md's rules (the term was
already flagged, and the paramagnetic force law itself is correctly cluster-ID-blind) — but it does
mean **no result from the current shape phase should be read as validating the shaping approach**,
and the walls in particular are not shaping at all, just collapsing to the floor under an admittedly
non-physical radial-only pin. A real shaping mechanism (Candidate A or otherwise) has strictly more
work to do than previously scoped, because it must replace 100% of `surf_conf`'s axial/radial holding
duty, not merely supplement it.
