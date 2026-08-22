# REGO Research Handoff — 2026-08-21

**Purpose.** This document transfers the scientifically important state of the REGO project to a
new Claude Code session with no access to this session's conversation history. It is a handoff, not
unquestionable truth — verify claims against the actual repository before acting on them (Section 22).

Every claim below is tagged **[VERIFIED]** (checked directly against real repo state, real
simulation data, or real code as of this writing), **[PROVISIONAL]** (a real result that has a known
caveat, confound, or limited scope — do not treat as final), or **[TODO]** (not done, explicitly
flagged as the next step).

---

## 1. Repository / Code State

**[VERIFIED]** Branch: `main`. No other branches in use this session.

**[VERIFIED]** `git status --short` at time of writing:
```
 M .gitignore
 M simulation/CONTEXT.md
 M simulation/HISTORY.md
 D simulation/data/context.txt
 D simulation/data/energy_audit.json
 D simulation/data/rego_metrics.json
 D simulation/data/rego_sim_data.json
 M simulation/phase0_baseline.py
 M simulation/phase1_cluster.py
 M simulation/phase2_shaping.py
?? CLAUDE.md
?? docs/IEEE-conference-template-062824/
?? docs/PAPER_NOTES.md
?? docs/PAPER_TODO.md
?? docs/conference-template-letter.docx
?? docs/paper.tex
?? docs/paper_draft.md
?? simulation/analysis/SHAPING_BASELINE_2026-08-19.md
?? simulation/analysis/SHAPING_FEASIBILITY_GATE_2026-08-19.md
?? simulation/analysis/SHAPING_HOLDING_AUDIT_2026-08-18.md
?? simulation/analysis/analyze_full_validation.py
?? simulation/analysis/force_attribution.py
?? simulation/analysis/force_budget_full_field.py
?? simulation/analysis/pp_dynamic_test.py
?? simulation/analysis/pp_magnetic_interaction.py
?? simulation/analysis/reconstruct_run.py
?? simulation/analysis/shape_feasibility.py
?? simulation/analysis/shape_fixture.py
?? simulation/analysis/validate_phase2.py
```
**The repository is NOT clean.** Nothing from this session has been committed. `git diff --stat` on
the modified tracked files: `phase2_shaping.py` +2060/−(part of 284) lines, `HISTORY.md` +1489 lines,
`CONTEXT.md` +451 lines, `.gitignore` +7 lines, plus small changes to `phase0_baseline.py`/
`phase1_cluster.py`. Last real commit: `058b7ac "full restructuring and fixed the crumbling cluster
issue in phase 2"` — everything described in this handoff happened AFTER that commit, uncommitted.

**[VERIFIED]** `SIM_VERSION = "43.0.0"` (`phase2_shaping.py:70`).

### ACTIVE PRODUCTION CODE (in `phase2_shaping.py`, currently live, affects any real run)
- The F17–F24 transport controller chain (Section 4) — F24's critically-damped BRAKE law is live;
  transport optimization is explicitly stopped (per a prior-session pre-committed rule), not because
  it converged.
- `surf_conf` kernel code still physically present in `compute_forces()` but **permanently inert**:
  grep confirms `surf_conf_enabled[None] = 1` does not occur anywhere in the file — the gate that used
  to fire it on `pm.state=="shape"` was removed. It is kept only as a documented historical/ablation
  reference (CLAUDE.md requires this, not deletion).
- The G3/G4 wall coverage-feedback "moving well" controller (`WELL_V_TAN`, `WELL_TRACK_ERR_MAX`,
  `_wall_well_state`, the `scan_idx` sweep logic in the wall shape branch) — **live**, four real bugs
  found and fixed in it this session (Section 8).
- The G4 retention-bookkeeping fix (`_wall_final_pos`, captures the real post-slot hold position
  instead of the original fixed target) — **live**, confirmed working (Section 8).
- Caps still have **zero** shape-phase magnetic mechanism (`pass  # no external shape dipoles for
  caps`) — this is the honest, current state, not a bug to silently fix.

### DIAGNOSTIC-ONLY / ISOLATED TEST CODE (does not affect production behavior)
All of `simulation/analysis/`:
- `shape_fixture.py` — imports `phase2_shaping` unmodified, builds 4 real 64-particle clusters at
  their real targets, forces `pm.state="shape"` from t=0. Extended this session with: `--phase-start-t`
  (diagnostic time-skip into the shaping schedule, changes no physics), `--snapshot-times`/
  `--snapshot-out` (full per-particle dumps at chosen instants), and per-step extended metrics (r95,
  min pairwise distance, min particle-dipole separation, peak velocity/acceleration, real
  vector-summed F/W).
- `shape_feasibility.py` — single-dipole-vs-single-64-particle-cluster isolated tests (perturbation,
  force budget, slow-well speed sweep, cap-hold feasibility).
- `force_budget_full_field.py`, `force_attribution.py` — full-field vector force measurement/dipole
  attribution (both had a self-caught, fixed `surf_conf_enabled` bug, disclosed in
  `SHAPING_FEASIBILITY_GATE_2026-08-19.md`).
- `analyze_full_validation.py` — new, post-processes `shape_fixture.py`'s snapshot/JSON output into
  coverage/density/retention metrics. Used once (Section 9's failing full-validation result).
- `pp_magnetic_interaction.py`, `pp_dynamic_test.py` — new, isolated numpy/Taichi harness for the
  particle-particle magnetic interaction research (Section 10–11). **Not wired into production.**
- `reconstruct_run.py`, `validate_phase2.py` — pre-existing from earlier transport-debugging sessions;
  `validate_phase2.py` implements the CLAUDE.md-required validation checklist against a checkpoint
  file; has NOT yet been extended with the wall-tracking-error or shaping-coverage checks (flagged
  repeatedly, still not done).
- `simulation/analysis/runs/` — gitignored scratch directory, ~55 files, raw logs/JSON from this
  session's diagnostic runs. Regenerable, not part of the scientific record itself (the `.md` reports
  and this handoff are the record); kept locally for reference.

### REVERTED EXPERIMENTS
- None this session at the `phase2_shaping.py` level beyond the in-place bug fixes described in
  Section 8 (each fix replaced a previous broken version of the SAME mechanism; nothing was tried and
  fully reverted back to a prior design).
- From the transport work (prior session, referenced in HISTORY.md): **F22 fix was implemented then
  reverted** after a real Gate-2 regression (see Section 4) — this is the one clear "tried and
  reverted" case in the current history and is already documented in `HISTORY.md`.

**[TODO]** Nothing has been committed. The next session should decide, with the user, what subset of
this work is commit-worthy before continuing — this handoff does not make that call.

---

## 2. Required Files The Next Session Should Read

Mandatory, in rough priority order:
1. `CLAUDE.md` (repo root) — the governing rules. Read this first; it overrides default behavior.
2. This file, `simulation/RESEARCH_HANDOFF.md`.
3. `simulation/HISTORY.md` — the full chronological technical history (long; the G1–G5 entries at the
   end are most relevant to current work, but F17–F24 near the middle explain transport status).
4. `simulation/CONTEXT.md` — **[PROVISIONAL/STALE]**: describes a v36-era architecture and does not
   reflect the G1–G5 findings from this session (surf_conf discovery, wall coverage controller,
   particle-particle interaction research). Still useful for foundational physics/architecture
   background (force laws, contact mechanics, coordinate conventions) but its "current failure root
   cause" and "correct fix" sections (¶9–10) are now superseded by HISTORY.md's G1 finding. **The next
   session should update CONTEXT.md** to reflect current reality — not yet done.
5. `simulation/phase2_shaping.py` — read the actual code, especially: `update_dipoles()` (all
   transport/hold/shape dipole logic), `compute_forces()` (real force law + `surf_conf` placeholder,
   both fully commented), `PhaseManager` class, and the constants block near the top (`SIM_VERSION`,
   `WELL_V_TAN`, `WELL_TRACK_ERR_MAX`, `SHAPE_WAIT_HOLD_STRENGTH`, `SHAPE_DONE_HOLD_STRENGTH`).
6. `simulation/analysis/SHAPING_HOLDING_AUDIT_2026-08-18.md` (G1 detail), `SHAPING_BASELINE_2026-08-19.md`
   (G2 detail, the true magnetic-only baseline), `SHAPING_FEASIBILITY_GATE_2026-08-19.md` (the four
   feasibility tests that gated the G3 implementation).
7. `simulation/analysis/shape_fixture.py`, `pp_magnetic_interaction.py`, `pp_dynamic_test.py` — the
   live diagnostic tooling; read before writing new diagnostic scripts, since most needed
   functionality (phase-skip, snapshots, coverage metrics, pp-force harness) already exists.
8. `docs/PAPER_NOTES.md`, `docs/PAPER_TODO.md`, `docs/paper.tex` — the paper is being drafted in
   `docs/paper.tex` (there is also `docs/IEEE-conference-template-062824/` with a separate template
   `.tex` — **[VERIFIED]** no `bare_jrnl.tex` exists anywhere in the repo; `docs/paper.tex` is the
   actual current manuscript file, not the template).
9. `simulation/analysis/reconstruct_run.py`, `validate_phase2.py` — transport-analysis and validation
   tooling.
10. `plans/vivid-bubbling-iverson.md` (at `C:\Users\eruku\.claude\plans\vivid-bubbling-iverson.md`,
    outside the repo proper — a DESIGN-ONLY plan for a closed-loop transport controller redesign,
    superseded in practice by the F17–F24 work which took a similar but distinct approach; read for
    context on transport control-law reasoning, not as a pending action item).

**[VERIFIED]** Keyword search across the repo for the terms requested (shaping, transport, F17–F24,
surf_conf, particle-particle magnetic interaction, Candidate A/B/C, coverage, wall, cap,
disaggregation, hold, retention) — all substantive hits are inside `phase2_shaping.py`, `HISTORY.md`,
`CONTEXT.md`, and the `simulation/analysis/*.md` reports already listed above; no additional
undiscovered planning documents were found elsewhere in the repo.

---

## 3. Project Goal

REGO investigates whether **physically realizable magnetic-field-driven manipulation** can assemble
free paramagnetic granular particles into a prescribed 3-D structure — **without** a physical mandrel,
scaffold, mold, artificial wall, arbitrary surface force, cluster-ID-specific magnetic force, fake
damping, anti-gravity, or other invented physics. This is a scientific correctness question, not an
animation-quality question (CLAUDE.md's governing rule: "Do not make the simulation look correct.
Make the simulation actually be correct.").

Intended Phase 2 pipeline:
```
compact cluster → controlled magnetic manipulation → spatial redistribution/shaping → stable
surface-conforming structure
```

Target geometry: a cylinder, built from 4 initial particle clusters (**[VERIFIED]**, from
`phase2_shaping.py`'s `SHAPE_ORDER = [0, 3, 1, 2]` and target definitions):
- **Q0 (cluster 0, "Blue")** — top cap
- **Q3 (cluster 3, "Red")** — bottom cap
- **Q1 (cluster 1, "Yellow")** — one curved wall region (left)
- **Q2 (cluster 2, "Orange")** — opposite curved wall region (right)

---

## 4. Transport Status

**[VERIFIED]** Findings F17–F24 are extensively documented in-code (`phase2_shaping.py`, search for
`F1[7-9]|F2[0-4]`) and narratively in `HISTORY.md`. Summary:

| Finding | Symptom | Root cause | Fix | Active? |
|---|---|---|---|---|
| F17 | Cluster never physically lifted from floor; lookahead ran away | Liftoff/lift tracking logic gap | Stage A-3 liftoff/lift tracking added | Yes |
| F18 | Vertical support lost mid-transport | Total-speed CRUISE throttle zeroed vertical component along with horizontal | Stage A-4: vertical channel made a separate, genuinely bidirectional one-sided controller | Yes |
| F19 | CRUISE vertical channel could not recover from overshoot | (see F18 fix title — F19 is the CRUISE vertical-channel fix itself, 2026-08-16) | Bidirectional vertical CRUISE | Yes |
| F20 | BRAKE zone sign error | Gravity-convention bug in BRAKE's acceleration solve | Sign corrected | Yes |
| F21 | Violent direction changes / near-field saturation | Unlimited deadbeat command changes per control step | Rate limiter on commanded aim-direction rotation | Yes |
| F22 | Near-arrival limit cycle | Diagnosed via `DEBUG_LIFT_CRUISE` capture; raised-cosine projection response **made real convergence worse** | Designed, implemented, **REVERTED** after real Gate-2 regression (peak velocity excursion worsened 226→279mm/s) | **No — reverted** |
| F23 | CRUISE's own reference velocity was a discontinuous step function | Continuous glideslope reference replaces it | Implemented; reduced first-crossing direction-flip chatter but did not eliminate longer terminal oscillation | Yes |
| F24 | BRAKE's deadbeat law (`a=v²/2d`, recomputed every 6ms) had no damping margin, causing a longer-timescale BRAKE↔CRUISE limit cycle | Replaced with critically-damped PD/spring-damper law (`ζ=1, ω_n=30 rad/s`, chosen from discretization-stability and force-margin bounds, not trajectory tuning) | **Gate 2 (real transport_0 run) did NOT pass**: spike count dropped 8→3 (real improvement) but transport_0 still ended in STALL, final `d=2.508mm, v=9.1mm/s` — statistically unchanged from F23's `d=2.334mm, v=8.8mm/s` | Yes — kept live as a net improvement even though it didn't fix STALL |

**[VERIFIED] Current transport status: NOT converged.** Per the user's own pre-committed rule ("if
F24 fails, we stop transport debugging"), transport controller optimization was **explicitly stopped**
after F24's Gate-2 result. Do not describe transport as "successful." The demonstrated, well-
characterized remaining limitation: a **control-law-switching discontinuity at the CRUISE/BRAKE zone
boundary** — CRUISE's exit direction (pursuit-path tangent) and BRAKE's entry direction (PD
spring-damper toward the point target) are two different vector fields with no continuity guarantee
where they meet, and this is now the dominant source of the remaining large velocity excursions
(three >100mm/s spikes in the F24 Gate-2 run, cross-referenced to CRUISE→BRAKE handoffs). Across
F19→F24, cluster identity, particle count, and physical plausibility (no saturation, no NaN/Inf, no
dispersal) held in every real run; every transport gets to within a few mm at single-digit-to-low-
double-digit mm/s, but never satisfies the strict `d<EPS_X ∧ v<EPS_V` sustained-dwell arrival
criterion within budget.

**[VERIFIED — do not reopen without cause]**: per the user's own standing instruction, do not reopen
transport debugging automatically in the new session unless a later result directly requires it.

---

## 5. Critical Transport Cross-Cluster Issue

**[VERIFIED, from HISTORY.md's G1 audit]**: real archived transport run data (STALL distances across
all four clusters: transport_0 `d=2.508mm`, transport_1 `d=4.522mm`, transport_2 `d=4.784mm`,
transport_3 `d=6.773mm` — **monotonically worsening** across the sequence) is consistent with a
"cross-cluster drag" mechanism: a transport can stall far from its target; the hold field is only
effective near its calibrated standoff; a waiting cluster may have no individually-active dipole at
that moment; later active magnetic fields from OTHER clusters' transports can therefore physically
pull on supposedly-completed/waiting clusters, causing cross-cluster collapse before shaping even
begins. **This is real physics under the current controller, not cluster-ID force filtering** — the
paramagnetic force law itself has no `cluster_id` dependence anywhere (verified directly by reading
`compute_forces()`'s `Fm` computation). Record this as an unresolved limitation. **[TODO]**: not
further diagnosed or fixed this session — flagged, not solved.

---

## 6. `surf_conf` Discovery — CRITICAL

**[VERIFIED]**, this is the single most important finding underlying everything that followed.
`surf_conf` (`phase2_shaping.py`'s `compute_forces()`, `SURF_CONF_K=0.5 N/m`) is a pre-existing,
already-labeled non-physical placeholder spring force, explicitly `cluster_id`-branched (`cid==0/3`
get a z-spring toward cap targets + radial confinement + viscous damping; `cid==1/2` get a radial-only
spring toward `r=cR`).

Measured directly against real VTU data and later against the isolated fixture: **`surf_conf` was
6–12 orders of magnitude stronger than the real magnetic force (`fmag`) throughout the entire shape
phase** (e.g. real force ~1e-16N vs. `surf_conf` ~1e-3 to 1e-4N at various points in a real run). It
switches from off to full strength in a single control step at `pm.state→"shape"` with no ramp,
producing the visually-observed "explosion at the transition" (a real, measured 0→4-57mm/s velocity
spike across all four clusters simultaneously). The apparent cap "recovery" into plausible shapes and
the ~10s of near-total stillness previously observed were **produced almost entirely by this spring
and its damping term, not by the dipole field.**

**Consequence, now permanently enforced in production**: the `if pm.state=="shape":
surf_conf_enabled[None]=1` gate has been **removed** from `update_dipoles()`. `surf_conf_enabled` is
never set to 1 anywhere in the file (verified by grep) — it stays at `init()`'s default 0 in every
real run. The kernel code and its extensive non-physical-placeholder documentation remain in
`compute_forces()`, per CLAUDE.md ("kept, not extended, not deleted, not read as evidence shaping
works").

**`surf_conf` MUST NOT be**: tuned, weakened, extended, used in any final shaping result, or cited as
evidence magnetic shaping works. The old apparent shaping "success" from before this session was not
a valid magnetic result — it was a spring holding particles in place.

---

## 7. True Magnetic-Only Shaping Baseline

**[VERIFIED]**, `simulation/analysis/shape_fixture.py` + `SHAPING_BASELINE_2026-08-19.md`. Real
production kernels, four real 64-particle clusters initialized at their real intended targets,
`surf_conf` forced off, full 20.5s cycle:

**Caps (Q0/Q3):** essentially **zero** shape-phase magnetic mechanism — `Fmag≈1e-17N` throughout, a
structural absence (no cap shape dipole exists at all in the code — `pass  # no external shape
dipoles for caps`), not merely a weak force. Starting exactly at target, cap particles free-fall to
the domain floor in well under 0.1s and stay there for the rest of the run.

**Walls (Q1/Q2):** a **real, physically legitimate near-field magnetic hold** exists in the "wait"
(pre-active-slot) dipole configuration — zero standoff, pure radial-inward moment,
`s=SHAPE_WAIT_HOLD_STRENGTH=0.15`. Starting at the intended target, a wall cluster stays within
**~0.09mm of target for ~9–10s** (the time before its own active slot begins). This is a genuine
magnetic effect (`Fmag≈1.6e-7N ≈ 112×` one particle's lunar weight), independently confirmed later
via a real vector-summed force budget (not force-magnitude summing, which was shown to overstate the
true force by ~100–300×): `F_r=0.18×W, F_t=-0.86×W, F_z=0.38×W` (W = 64-particle cluster weight). A
perturbation test (0.3mm offsets, radial/tangential/axial) confirmed this is **genuinely dynamically
stable** (real restoring response, underdamped oscillation, not "stayed still because undisturbed")
— but it is a stiff, oscillatory near-field regime, not a quiet static hold.

**But**: when the OLD fast v33 raster scan (`v_tan≈14mm/s`, deliberately faster than particles can
track — "deposition, not chasing" by design) starts moving, the hold is destroyed; particles fall
or escape; the old raster produces essentially no real surface coverage. This is the foundational
result that motivated the entire wall coverage-feedback controller rebuild (Section 8).

---

## 8. Wall Moving-Well Development History (Candidate A)

**[VERIFIED]** The v33 fast raster was replaced with a closed-loop "coverage-feedback slow well": the
same validated wait-hold geometry (zero standoff, radial-inward moment, `s=SHAPE_WAIT_HOLD_STRENGTH`),
translated slowly (`WELL_V_TAN=3mm/s`, chosen with margin under a directly-measured 5mm/s clean
tracking ceiling / 15mm/s catastrophic-failure point), advancing only while the real sensed cluster
centroid stays within `WELL_TRACK_ERR_MAX=0.30mm` of the aim point (otherwise freezes).

**Four real implementation bugs found and fixed, each via real physics validation, not code-reading:**
1. **Wrong sweep radius** — `r_scan` read from `C.cR` instead of the true target radial distance
   (0.20mm discrepancy for Q1). Fixed: derive `r_scan` from the real target position.
2. **Discrete z-level jumps froze the sweep permanently** — each jump instantly exceeded
   `WELL_TRACK_ERR_MAX`, and the gate could never recover. Fixed: continuous `z_frac` creep.
3. **Competing stationary anchor dipole active during the sweep** — the wall's `IDX_CLUSTER_DIP`
   anchor was left on (same position, same strength) simultaneously with the moving `scan_idx` well;
   near-field (~1/r⁴) meant the stationary anchor always dominated, pinning the cluster in place
   (velocity climbed to 20–35mm/s with **zero** net displacement). Fixed: anchor turns off (`s=0`)
   during the active slot; `scan_idx` alone carries the hold (it starts at the identical
   position/strength, so no support gap is created).
4. **`z_frac` wrapped (teleported) instead of bouncing at its bound** — `phi_frac` correctly reverses
   direction at 0/1; `z_frac` used `-=1.0` (an instantaneous 2.5mm aim-point teleport), producing a
   ~1000× force transient that flung the (still-coherent) cluster to 16–118mm/s and out of the well's
   range. Found via fine-grained (20ms-resolution) instrumentation on a **cheap, targeted, single-slot
   test** (not a full run), pinpointed to the exact control step. Fixed: `z_frac` now bounces like
   `phi_frac`.
5. **Post-slot retention target bookkeeping bug** — the "done" hold anchor pointed at the ORIGINAL
   fixed target, not wherever the sweep actually left the cluster, causing already-shaped material to
   drift away (0.95mm→6.03mm over ~5.5s) after its own slot completed. Fixed: `_wall_final_pos{}`
   captures the real sensed centroid once, the first control step the cluster enters "done" state, and
   the hold anchor (both in "shape"-done state and later "hold" phase) uses that captured position —
   confirmed via a cheap targeted test: distance stabilizes at 1.48mm (was drifting past 6mm before).

**[VERIFIED]** After all five fixes, a **single-wall, single-slot, cheap targeted test** demonstrated:
real 64-particle tracking, max tracking error **0.0065mm**, healthy magnetic force throughout, no
escape, no pinning, no force collapse, preserved cluster integrity (`r_rms` unchanged). A cluster-2
spot-check (the other wall, same code path, previously untested) passed the same criteria (max
tracking error 0.0071mm, peak velocity 9.88mm/s, F/W range 0.22–8.08×, no saturation).

**[VERIFIED — but see Section 9] The full four-cluster shaping validation FAILED at the actual
shaping objective**, even though every individual controller bug above was genuinely fixed.

---

## 9. Current Shaping Architecture Failure — the Central Finding

**[VERIFIED]**, from `g5_full_validation.json`/`analyze_full_validation.py` (a real full 20.5s,
4-cluster, real-physics run — the "expensive" validation, run exactly once after the cheap fixes
above were confirmed):

- **Wall coverage stayed at 0.7–1.4%** of the (θ,z) grid at every sampled instant (t=5,10,15,20,20.5s)
  — the 64-particle cluster remained one tight clump (z-spread ~0.2mm, r-spread ~0.2mm) throughout,
  never a distributed layer.
- **Density stayed source-concentrated** (`density_cv` up to 0.84, not uniform).
- **Cluster 1 failed post-slot retention before the bookkeeping fix was in place** for this
  particular run (r grew from ~1.9mm to 2.9–3.5mm, leaving the target radial envelope entirely,
  during cluster 2's subsequent active slot) — note: **this specific full run predates fix #5 above**;
  the retention fix was validated separately afterward via a cheap targeted test (Section 8), not yet
  re-confirmed inside another full 4-cluster run. **[TODO]**: rerun the full validation with the
  retention fix included, once shaping strategy itself is settled (do not rerun just for this alone —
  expensive, low information value on its own).
- Caps: confirmed unchanged, 100% fallen to floor at every snapshot, 0% on-cap.

**The central conclusion, stated precisely**: the coverage-feedback controller (Candidate A)
**successfully solves "move a coherent cluster around the wall without losing it," but does not solve
"deposit/spread the cluster across the wall surface."** It relocates a single compact clump; it does
not leave material behind as it goes (the pre-existing v33 raster's own design principle was
"deposition, not chasing" — the new controller chases without depositing). This is a structural,
architectural gap, not a boundary/sweep-logic bug — **do not attempt to fix this with more sweep-
boundary patches.**

---

## 10. Particle-Particle Magnetic Interaction — New Major Development

**[VERIFIED]** Production `compute_forces()` currently computes particle force from EXTERNAL source
dipoles only (`B_and_gradB2()` sums over `N_DIP` controller-owned dipoles, never over other
particles) — there is **no particle-particle magnetic interaction in the model at all.**

Literature search (via WebSearch, sources below) found a real, applicable mechanism: rotating/
alternating external fields induce time-varying particle-particle dipole-dipole interactions
(attractive along the instantaneous field direction, repulsive perpendicular to it — from
`U=(μ0 m1m2/4πr³)(1−3cos²θ)`), used in real experiments to disaggregate colloidal magnetic clusters
and increase surface coverage.
- [Disaggregation of microparticle clusters by induced magnetic dipole-dipole repulsion near a surface](https://pubmed.ncbi.nlm.nih.gov/23400503/)
- [Dynamics of magnetic particles near a surface: model and experiments on field-induced disaggregation (Phys. Rev. E)](https://link.aps.org/doi/10.1103/PhysRevE.89.042306)
- [Disassembly and spreading of magnetic nanoparticle clusters on uneven surfaces](https://www.sciencedirect.com/science/article/pii/S2352940719306080)
- [Locomotion and disaggregation control of paramagnetic nanoclusters using wireless electromagnetic fields](https://www.nature.com/articles/s41598-021-94446-4)
- [Transport and selective chaining of bidisperse particles in a travelling wave potential](https://arxiv.org/pdf/1607.01131)

**Applicability caveat, explicitly noted**: this literature is largely wet/colloidal/substrate-based
(fluid drag, Brownian motion, different particle scale). REGO is dry, gravity-loaded, contact-
dominated, 64 finite particles, no scaffold. Which principles transfer is exactly what the isolated
tests below started to check.

**[VERIFIED] Formulation validated in an isolated harness (`pp_magnetic_interaction.py`), NOT added
to production `compute_forces()`:**
- Induced moment: `m_i = (Vp·χ_eff(|B_ext(pos_i)|)/μ0)·B_ext(pos_i)` — reuses production's existing
  implicit definition (same one production's external force already uses), computed from the
  EXTERNAL field only (independent-moment / first-order approximation, not full self-consistent
  mutual induction).
- Pairwise force: standard frozen-dipole dipole-dipole formula, Newton's third law by construction.
- **Double-counting**: verified false by construction (external-source field and particle-induced
  field are disjoint contributions; `B_and_gradB2` never sums over particles).
- **Mutual-induction check**: at the representative n_R=3 standoff (see below), one induced
  neighbor's own field at a touching particle is only **~1.02%** of the external field there — the
  independent-moment approximation's error is small and quantified, not merely assumed.
- **Two-particle tests, ALL PASSED**: aligned/chain (attractive) and side-by-side (repulsive) match
  prediction exactly; a 9-angle continuity sweep (0°–90°) confirms a smooth sign change at the
  analytic "magic angle" (54.7356°, where `1-3cos²θ=0`); Newton's third law exact to floating point
  (`0.00e+00` relative error); direct force matches the numerically-differentiated interaction energy
  to `~1e-10` relative error (the real correctness check, not just qualitative direction).
- **Analytical-vs-coded magnitude check**: the coded implementation reproduces the earlier hand-
  derived standoff sweep (n_R=2,3,5,8,12) almost exactly — no implementation bugs.

**[VERIFIED] Standoff sweep, real production `B_and_gradB2`/`χ_eff` kernels (n_R = standoff in
particle radii, W1 = one particle's lunar weight):**

| n_R | B (T) | χ_eff | F_ext/W1 | F_dd,⊥/W1 (repulsive) | F_dd,∥/W1 (attractive) |
|---|---|---|---|---|---|
| 1 | 20.6 | 1.2e-11 (saturated) | ~0 | ~0 | ~0 |
| 2 | 2.58 | 0.025 | 23.9 | 557 | 1114 |
| **3** | **0.76** | **0.123** | **115.9** | **1152** | **2304** |
| 5 | 0.17 | 0.149 | 140.3 | 78.8 | 157.6 |
| 8 | 0.04 | 0.150 | 113.9 | 4.8 | 9.6 |
| 12 | 0.012 | 0.150 | 11.2 | 0.42 | 0.84 |

At **n_R≈3** (standoff=0.09mm), `F_ext/W1=115.9` matches the independently-measured "~112×W" real
wall-hold force almost exactly — a strong internal consistency check that this is the standoff regime
the existing validated hold already operates in. At that same standoff, the dipole-dipole force is
**~10–20× stronger than the external holding force itself.** Important note: raw `B` at n_R=1
(20.6T) is a genuine point-dipole-model near-singularity, not a bug — production's own `χ_eff`
saturation calc uses this same unclamped `B` (only the gradient is soft-clamped), so this
characteristic already exists in the currently-validated hold physics, not something newly introduced.

---

## 11. Dynamic Disaggregation Results — Current Caveat

**[VERIFIED, real dry-contact physics, isolated harness `pp_dynamic_test.py`]** 12 real particles
(real mass, gravity, Hertz-Mindlin contact), a rotating manipulation dipole (moment rotating in a
plane, standoff = 3R), the new pp-force layered in via a non-production kernel:

At full strength (`s=1.0`):

| ω (rad/s) | r_rms final | n_groups | vmax | behavior |
|---|---|---|---|---|
| 0 (control) | 0.055mm | 1 | 48mm/s | stays compact, as expected |
| 50 | 1.89mm | 2 | 212mm/s | disaggregates within ~50ms, then **plateaus** (bounded, not runaway — confirmed from the full time series, not just the endpoint) |
| **150** | 0.057mm | 1 | 188mm/s | stays **fully compact the entire run** despite high velocity — a genuine, reproducible frequency-dependent resistance to disaggregation, not noise |
| 400 | 3.84mm | 3 | 127mm/s | disaggregates into 3 groups, also plateaus |

This is a real, qualitatively meaningful result: rotation genuinely disaggregates a real dry-contact
cluster into multiple bounded coherent subgroups, with non-trivial, non-monotonic frequency
dependence. But at `s=1.0` the spread scale (4–7mm max radius) **overshoots the actual target
geometry** (cylinder radius `cR=1.667mm`) — too violent to be directly useful as-is.

**[PROVISIONAL — CONFOUNDED, DO NOT TRUST]** A follow-up sweep at the production-realistic strength
(`s=0.15`, matching `SHAPE_WAIT_HOLD_STRENGTH`) showed even the ω=0 static control dispersing
(r_rms=2.3mm) — which contradicts the analytical table above (`F_ext/W1=115.9` at this exact
strength/standoff should easily hold the cluster). **Root cause identified but not yet fixed**: the
dynamic-test harness set the manipulation dipole's moment **perpendicular** to the standoff direction
(`m=[0,1,0]`, standoff along `[1,0,0]`), not the radially-inward convention (`m ∥ standoff direction`)
that the actual validated wall hold uses everywhere else in this project. This is a harness geometry
bug, not a real physical finding about hold strength at realistic field levels. **The `s=0.15` sweep
result must not be used for any conclusion.** The `s=1.0` qualitative disaggregation-exists finding is
still credible (methodology was consistent within that sweep), but absolute strength/scale numbers at
realistic field strength are unverified.

---

## 12. Current Best Scientific Hypothesis

```
dynamic external magnetic field
    + induced particle-particle magnetic interactions
    → controlled cluster disaggregation
    → spatial redistribution
    → deposition / retention
    → surface shaping
```

This is qualitatively different from — and should replace, not extend — the failed:
```
moving magnetic well → move coherent clump (Section 9's failure)
```

**[TODO]** open questions for the next session, in the order the user specified: fix the geometry
mismatch (Section 11) and rerun the strength/frequency comparison with the correct radial-inward
convention; determine whether controlled (not explosive) disaggregation survives at realistic
strength; if yes, design the smallest deposition/retention experiment; if no, diagnose why before
implementing anything new.

---

## 13. Physical Rules — Absolute

Preserve, without exception:
- No physical mandrel, scaffold, artificial wall, or arbitrary surface force.
- No fake anti-gravity, no hidden damping added solely to force a "success."
- No cluster-ID-filtered or particle-ID-specific magnetic force. `cluster_id` may be used for
  diagnostics, visualization, tracking, and phase bookkeeping ONLY — never to alter physical forces.
  (Verified currently true: the real `Fm` force law has zero `cluster_id` dependence; `surf_conf`,
  which did have such branching, is permanently disabled, not deleted, kept only as a labeled
  historical reference.)
- No teleportation, fake target-snapping, or changing gravity to improve behavior, in production code.
- No hiding failures or fabricating results — Section 9's failure is reported as a failure, not
  reframed as partial success.
- Any NEW force term must: (1) correspond to a real physical mechanism, (2) have a derivable
  equation, (3) apply whenever the physical conditions imply it should exist (not "only during
  shaping because shaping needs it" — that would be a hidden shaping force), (4) be validated
  independently before production integration, (5) be documented (why, how derived, what was
  checked).

---

## 14. Earnshaw / Static-Equilibrium Context

**[VERIFIED, established in earlier sessions, still governing]**: `∇²(B²)=2|∇B|²≥0` in current-free
regions means B² is subharmonic — no STATIC magnetic field configuration holds paramagnetic particles
spread across an extended free-standing surface; they collapse to the nearest dipole. This is why the
project's shaping mechanisms are inherently dynamic/time-varying (the moving well, and now the
rotating-field pp-interaction hypothesis) rather than attempts at a static ring/belt/plane attractor.
**Do not claim to "overcome Earnshaw's theorem"** — the dynamic mechanisms under investigation are
not constrained by the static-field version of the theorem in the first place; state precisely which
assumption (time-invariance) is being relaxed and why, each time this is discussed in the paper or in
code comments.

---

## 15. Target Geometries

- **Caps**: Q0 (Blue, top), Q3 (Red, bottom) — evaluate in `(r, θ)` relative to the cap plane.
- **Walls**: Q1 (Yellow), Q2 (Orange) — evaluate in cylindrical `(r, θ, z)`.

The desired output is NOT low centroid error alone. Required: surface coverage, density uniformity,
surface-distance error, particle retention, particle conservation (count never changes), cluster
integrity (no merging/coincident particles, bounded overlap).

---

## 16. Evaluation Metrics

Standard, already in use:
- Centroid: `x̄ = mean(x_i)`; RMS radial spread: `R_rms = sqrt(mean(‖x_i − x̄‖²))`.
- r95, max radius, min/max pairwise distance, particle count.
- Surface-distance error, coverage fraction (binned occupancy), density coefficient of variation.
- Escape fraction, force/weight ratio (real **vector sum**, not magnitude sum — a ~100–300×
  overstatement pitfall confirmed directly this session), gradient/force saturation, minimum
  source-particle separation, cross-cluster force ratio.

Shaping-specific, implemented in `analyze_full_validation.py`:
- **Wall**: radial envelope compliance, θ coverage, z coverage, density uniformity (θ,z binned).
- **Cap**: radial/angular coverage (r,θ binned), on-cap fraction, distance-to-target-plane, fallen
  fraction.

---

## 17. Paper Status

**[VERIFIED]** `docs/paper.tex` is the current manuscript (untracked, not yet committed).
`docs/IEEE-conference-template-062824/` contains a separate, unmodified template file — do not
confuse the two. `docs/PAPER_NOTES.md`, `docs/PAPER_TODO.md` also present, untracked. No
`bare_jrnl.tex` exists in this repo (that filename was a guess in the request that prompted this
handoff — corrected here). Target venue per prior context: IEEE T-ASE. The draft must not invent
shaping success, transport convergence, numerical results, or citations — it can contain verified
methodology and explicit placeholders. **[TODO]**: Related Work section remains a major gap needing
verified references (the literature found in Section 10 of this document is a real, usable start for
a disaggregation-mechanism citation, but has not yet been integrated into the manuscript).

---

## 18. File / Artifact Inventory

**Source code**: `simulation/phase2_shaping.py` (production), `phase0_baseline.py`,
`phase1_cluster.py` (earlier phases, both lightly modified this session — verify via `git diff` what
changed before assuming untouched).

**Analysis scripts**: see Section 1's full listing of `simulation/analysis/*.py`.

**Reports** (all in `simulation/analysis/`, untracked): `SHAPING_HOLDING_AUDIT_2026-08-18.md` (G1,
valid, foundational), `SHAPING_BASELINE_2026-08-19.md` (G2, valid, the magnetic-only baseline),
`SHAPING_FEASIBILITY_GATE_2026-08-19.md` (the four feasibility tests gating G3 — valid, though its
"Implementation plan (executed)" section (J) describes the PRE-bugfix design; the actual final design
is only accurately described in `HISTORY.md`'s G4 entry).

**Checkpoints/VTU/archived runs**: `simulation/old_results/` (gitignored) contains `data/`, `outputs/`,
`post/` subdirectories from prior sessions' real transport/shaping runs — **[TODO]** not inventoried
in detail this session; check contents before assuming any particular file exists.

**Scratch diagnostic output**: `simulation/analysis/runs/` (gitignored, ~55 files) — regenerable logs/
JSON from this session's tests. Notable ones if reuse is useful: `g5_full_validation.json` +
`g5_full_validation_snapshots.npz` (the failing full 4-cluster validation, Section 9),
`pp_n12_omega_sweep.json` (valid, s=1.0 disaggregation sweep), `pp_n12_omega_sweep_s015.json`
(**confounded, do not reuse without the harness fix**), `pp_interaction_validation.log` (the
two-particle physics validation, Section 10).

**Plans**: `C:\Users\eruku\.claude\plans\vivid-bubbling-iverson.md` (transport redesign, design-only,
context/superseded — see Section 2).

For each major experiment: valid/reusable results are Sections 7, 8 (the five bug fixes), 10 (physics
validation); confounded/do-not-reuse is Section 11's `s=0.15` sweep; failed-as-designed (informative,
not a bug) is Section 9's full validation.

---

## 19. What Must NOT Be Repeated

- Using `surf_conf` as a shaping mechanism, or citing its presence as evidence shaping works.
- The fast v33-style raster as a deposition method (explicitly too fast for particles to track, by
  original design intent).
- Assuming a static extended magnetic equilibrium can hold a spread-out surface layer (Earnshaw).
- Arbitrary wall forces, cluster-ID-specific force filtering, particle-ID pinning.
- Blindly adding velocity caps (a prior-session numerical crutch, already removed and shown to be the
  right call — do not reinstate without new justification).
- Running full 20.5s four-cluster simulations for every small controller change — this session's own
  workflow initially fell into exactly this trap (multi-hour runs per bugfix) before an explicit
  user-directed pivot to targeted, cheap, single-slot tests (`--phase-start-t`, fine-grained
  instrumentation) — the pivot is what actually found bugs 3 and 4 in Section 8, in minutes instead of
  hours. **Keep using the cheap-test workflow.**
- Treating centroid tracking / low tracking-error alone as evidence of successful shaping — Section 8
  passed exactly this criterion while Section 9 showed it still fails the actual shaping objective
  (coverage).
- Treating unvalidated visual/animation output as proof of anything.
- Reusing the confounded `s=0.15` pp-interaction sweep (Section 11) for any conclusion.

---

## 20. Computational Performance / Workflow

**[VERIFIED]** CPU-only (no CUDA device available — Taichi falls back to `arch=x64` every run, logged
warning each time). A full 20.5s four-cluster shaping fixture run takes **multiple hours** (observed
directly this session, ~4 hours for one such run). A single-slot, phase-skipped, fine-grained
diagnostic run (a few simulated seconds) completes in **minutes**.

**Established, working iteration order** (validated this session, not theoretical): existing logs/
JSON/snapshots → analytical calculations (numpy, instant) → isolated single/two-particle checks →
small (8–16 particle) reduced tests → one real 64-particle cluster, phase-skipped to the relevant
moment → only then a full 4-cluster run, and only once per real architectural milestone, not per
incremental change.

Practical notes: stdout is block-buffered when redirected to a log file in this environment (no
`flush=True` in the diagnostic scripts) — a running-but-silent log does not mean a hang; check process
CPU usage (`Get-Process`) to confirm it's still active before assuming failure. Taichi JIT-compiles
new/changed kernels on first use each process launch (can take 1–2 minutes for a complex kernel) —
running multiple parameter variations inside ONE process (see `pp_dynamic_test.py`'s `sweep()`
function) avoids repeated JIT overhead and is markedly faster than relaunching per variation.

**Do not** change the production timestep or physics parameters solely for speed. Any reduced-order
experiment (fewer particles, shorter duration, phase-skip) must be clearly labeled as such and used
only for mechanism discovery — final validation still needs the real timestep and real 64-particle
system.

---

## 21. Current Immediate Next Step

Do **not** immediately modify production code. In order:
1. Inspect the repository directly; verify this handoff's claims against actual current file state
   (git status will have changed if any further work happens after this document is written).
2. Read the required files (Section 2).
3. Fix the geometry mismatch in `pp_dynamic_test.py`'s dynamic-test harness (Section 11) — the
   manipulation dipole's moment should be aligned with (radially inward along) the standoff direction,
   matching the validated production convention (`IDX_CLUSTER_DIP`'s wait-hold config), with rotation
   applied as a precession/transverse modulation around that dominant axis rather than an arbitrary
   perpendicular moment.
4. Rerun the realistic-strength (`s=0.15`) frequency comparison with the corrected geometry.
5. Determine whether controlled (bounded, non-explosive, appropriately-scaled) disaggregation survives
   at realistic strength.
6. If yes: design the smallest deposition/retention experiment (per Section 12's open questions) —
   the goal is moving from "does dynamic pp-interaction physically work" (largely answered: yes, at
   full strength, Section 11) to "can it be controlled to produce actual surface coverage" (not yet
   answered).
7. If no: diagnose precisely why before implementing anything further — do not add compensating
   arbitrary forces to force a result.

---

## 22. Final Handoff Rule

Treat this document as a handoff, not unquestionable truth. Verify important claims against the
actual repository. Distinguish current code from historical code. Challenge assumptions. Update this
handoff if contradictions are found. Never assume an experiment succeeded simply because it is
described here as a candidate or as validated — re-check the underlying data file if a conclusion
matters for a production decision.

**Objective for the next session**: solve the remaining Phase 2 shaping problem (real surface
coverage, not clump relocation) in the shortest scientifically defensible path, preserving physical
realism (Section 13) and producing reproducible evidence suitable for an IEEE T-ASE manuscript.
