# REGO — Agent Rules

Persistent rules for any Claude Code session working on this repository. Read this before
touching `simulation/`. See `simulation/CONTEXT.md` for the full physics/architecture reference
and `simulation/HISTORY.md` for the version-by-version technical history.

## The one rule everything else follows from

**Do not make the simulation look correct. Make the simulation actually be correct.**

REGO is intended to be a scientifically defensible physics-based simulation, not a visualization
that merely resembles the desired result. It is being prepared for potential IEEE journal
submission — scientific rigor is the priority, ahead of getting a pretty animation.

**Correct physics > correct mathematics > correct algorithm > correct numerical behavior > visual
appearance.** If those conflict, choose the former. If the current methodology cannot physically
achieve the desired result, say so explicitly and explain why — that is a valid, useful scientific
result, not a failure to hide.

## Non-negotiable physics constraints

- **No violation of Earnshaw's theorem.** In a current-free region, `∇²(B²) = 2|∇B|² ≥ 0` — B² is
  subharmonic, so its *static* maxima occur only at the field sources. No static magnetic field
  configuration holds paramagnetic particles spread across an extended free-standing surface; they
  collapse to the nearest dipole. Any shaping mechanism that appears to hold particles on a static
  ring/belt/plane is wrong until proven otherwise — verify the claim from the field equations before
  believing it, not from the animation. Time-varying/rotating fields are not constrained by the
  static-field version of Earnshaw and remain a legitimate avenue (see "Physical limits" section of
  CONTEXT.md) — but must be verified at the correct frequency regime (ω_drive ≫ ω_mechanical), not
  asserted.
- **No physical scaffold, mandrel, cage, or mold.** The project's explicit scientific goal is to
  determine whether magnetic fields *alone* can manipulate and assemble free particles into a target
  structure. Adding a rigid structure whose purpose is to impose the target geometry defeats that
  goal and must not be done, regardless of how much easier it would make the simulation converge.
- **No arbitrary "fix" forces.** Do not add a generic wall-force, shaping-force, surface-attraction,
  anti-clumping force, or distribution force just to make particles land where you want. Every force
  must correspond to a real, physically realizable mechanism (a real dipole field, real gravity, real
  contact mechanics, real cohesion) with a defensible mathematical formulation and plausible
  parameters — not a mechanism reverse-engineered to produce a target picture.
- **Existing non-physical placeholders must stay labeled, not extended.** `surf_conf` and its
  viscous-damping term in `phase2_shaping.py` are known non-physical stand-ins for whatever a real
  control law would need to provide (see CONTEXT.md). They are kept so the rest of the simulation can
  be validated in isolation. Do not retune them to chase a shape, do not add more terms like them, and
  do not cite their presence as evidence that magnetic shaping works.
- **No invented material parameters.** Susceptibility, saturation magnetization, contact stiffness,
  adhesion energy, etc. must trace to a stated source (literature value, an existing constant already
  used elsewhere in the codebase, or an explicitly documented approximation) — never silently tuned
  until the animation looks right.

## Working method

- **Read before editing.** Read the relevant files in full — CONTEXT.md, HISTORY.md, and the actual
  code path you're about to touch — before making changes. Trace the actual equations and data flow;
  do not assume a function does what its name suggests.
- **Reconstruct the dynamics, don't just read the code statically.** When diagnosing a failure, work
  out what the equations predict at the relevant point (position, force, gradient, timing) and check
  that prediction against real checkpoint/log data before proposing a fix. `outputs/*.pkl` checkpoints
  contain real particle state (position, velocity, cluster id, dipole state) — use them.
- **Verify conclusions independently before implementing.** Form a hypothesis, derive it from the
  equations, test it against real simulation state, look for an alternative explanation, only then
  fix it. Do not trust a first-pass explanation, your own or a prior session's, without re-deriving it.
- **Distinguish parameter bugs from algorithmic bugs.** Not every failure is a constant that needs
  retuning. If the underlying approach is conceptually wrong (e.g., a static field trying to do what
  only a time-varying field can do), say so and redesign rather than preserving a broken approach
  because it's already implemented.
- **Research before fundamental changes.** Where the physics is non-obvious (magnetic manipulation,
  granular contact mechanics, cohesion, lunar regolith behavior), consult real literature. Do not
  hallucinate papers, equations, or parameter values — if a number can't be verified, say so
  explicitly rather than presenting an unverified guess as fact.
- **No hidden assumptions or silent changes.** Every scientifically meaningful assumption or
  approximation must be documented inline, at the point it's made, not just in a commit message.

## Documentation discipline

- After any substantive change to the physics, algorithm, or parameters, update `HISTORY.md` (what
  was wrong, why, what changed, why the change is physically justified, what was verified, what
  remains uncertain) and `CONTEXT.md` if it changes the current-state description. "Fixed Phase 2" is
  not an acceptable changelog entry.
- If you discover the current methodology cannot achieve the desired geometry under honest physics,
  document that as a finding — including what mechanism *would* be required — rather than quietly
  reverting to a workaround.

## Validation

Before declaring a physics/algorithm change complete, check (not just assert):
- Particle identity remains permanent after clustering (`cluster_id == fixed_color`), particle count
  is conserved, and there are no NaN/Inf states.
- Contact mechanics: no coincident/merged particles, no silent neighbor-list overflow, overlaps stay
  small relative to particle radius.
- Force magnitudes are physically plausible for the stated field sources (coil size, current,
  standoff) — not hidden behind a saturated clamp.
- Timestep is stable for the stiffest contact/field gradient actually realized in the run (check
  ω·dt), not just assumed stable from a default value.

`simulation/analysis/validate_phase2.py` implements these checks against a checkpoint file — extend
it rather than re-deriving these checks ad hoc when auditing future changes.
