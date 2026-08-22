# REGO Paper — TODO Ledger, Figure/Table Plan, Reference Audit

Companion to `bare_jrnl.tex` and `PAPER_NOTES.md`. Not part of the manuscript.

## Claim status ledger

| Claim / section | Status | Notes |
|---|---|---|
| Physical model (Sec. IV, eqs. 1-2) | **VERIFIED** | Directly transcribed from `phase2_shaping.py`'s force kernels. |
| Contact mechanics (Sec. IV-C) | **VERIFIED** | Matches `contact_pp`/`contact_wall`, Hertzian + Coulomb friction. |
| Earnshaw argument (Sec. I, IV-D) | **VERIFIED** (derivation) / **PROVISIONAL** (citations) | Math is correct and already governs `CLAUDE.md`'s constraints; the two supporting citations need real bibliographic verification. |
| Transport controller state machine (Sec. V) | **VERIFIED** | Matches current `phase2_shaping.py` (F24 state). |
| BRAKE critically-damped law + numbers (Sec. V-C, VI-B) | **VERIFIED** | From this session's F24 design + real Gate-2 run. |
| Zone-switching dead zone finding (Sec. VI-A) | **VERIFIED** | From F21/F22 diagnostic session, confirmed against real per-step data. |
| Cross-cluster dragging finding (Sec. VI-C) | **VERIFIED** | Reconstructed from real archived VTU trajectory data this session, independently confirmed live in the F24 full-transport run. |
| Shaping root causes A/B/C (Sec. VI-D) | **VERIFIED** (code + trajectory data) | Candidate-A architecture itself is **PROVISIONAL** — not yet implemented or tested. |
| Abstract "final shaping result" sentence | **TODO — NEEDS DATA** | Explicit placeholder left in text. |
| Results (Sec. VIII) | **TODO — NEEDS DATA** | All tables/figures placeholders; do not fill with anything but real run output. |
| Discussion (Sec. IX) | **TODO** | Skeleton only; expand once Sec. VIII is real. |
| Conclusion (Sec. XI) | **TODO** | Draft framing only. |
| Related Work (Sec. II) | **MOSTLY TODO** | Only 4 subsections have any real citations; A, C, E are empty placeholders — see reference audit below. |

## Reference audit

### Located and read this session (real, but need full bibliographic verification before citing)
1. Earnshaw's theorem — Wikipedia (fine for internal reasoning, **not** an acceptable final IEEE
   citation; replace with a textbook or primary source, e.g., Earnshaw's original 1842 paper or a
   standard electromagnetism text).
2. Passive magnetic bearing / time-averaging-of-periodic-field patent — found via search, title/gist
   confirmed, exact patent number/assignee/year not yet re-verified.
3. "A Moving Magnetic Trap Decelerator: A New Source for Cold Atoms and Molecules" — arXiv preprint,
   found via search (arXiv:1011.0418 per search result), author list and final venue not verified.
4. Magnetophoretic conveyor / "Device and method for particle complex handling" — patent family,
   found via search, exact patent number needs re-confirmation (several related patent numbers
   appeared in search results — need to pick the correct/primary one).
5. "Three-dimensional close-to-substrate trajectories of magnetic microparticles in dynamically
   changing magnetic field landscapes" — arXiv preprint, found via search, author list/arXiv ID not
   verified.

**Action:** before submission, re-fetch each of these directly (arXiv abstract pages, patent full
text, or a library database) to confirm exact author lists, years, venues, and DOIs/patent numbers.
Do not trust the search-snippet titles alone.

### Missing entirely — needs real literature search (do NOT let these stay empty in a real submission)
- Automated granular/particulate assembly, granular additive manufacturing (Related Work II-A)
- Magnetic tweezers, colloidal magnetic assembly, single-particle magnetic trajectory control,
  model-predictive magnetic control (Related Work II-B, II-C)
- Lunar/extraterrestrial regolith mechanics and construction concepts (Related Work II-E)
- Any DEM/granular-simulation methodology papers to justify the Hertzian contact model choice
- Any prior magnetic-manipulation-of-dry-granular-material work specifically (if it exists — this
  may itself be worth stating as a gap if a real search turns up nothing)

**This is the single largest remaining piece of work before this manuscript is submission-ready.**
It requires many additional, careful search/verify passes — deliberately not rushed in this draft
pass to avoid the cardinal sin of fabricated citations.

## Figure plan

| # | Content | Status |
|---|---|---|
| Fig. 1 | System overview: granular bed → clustering → transport → shaping → hold | Not created |
| Fig. 2 | Physical model schematic: particle, dipole source, field, force, gravity, contact | Not created |
| Fig. 3 | Transport state machine (LIFTOFF→LIFT→CRUISE→BRAKE→SETTLE, hysteresis, stall net) | Not created |
| Fig. 4 | Representative real transport trajectory ($z$, $d$, $v$ vs. $t$) showing the zone-switching event | Data exists (this session's archived VTU/log traces) — figure not yet generated |
| Fig. 5 | Cluster-integrity metric (RMS spread ratio) vs. time | Data partially exists — not yet plotted |
| Fig. 6 | Shaping concept: cylindrical parameterization, cap/wall target surfaces, traveling well | Not created — depends on Sec. VI-D design being finalized first |
| Fig. 7 | Shaping coverage/density results | Not created — no shaping run exists yet |
| Fig. 8 | Force-vs-standoff design curve, showing the clamp ceiling and operating standoffs | Data exists in code constants — not yet plotted |

## Table plan

| # | Content | Status |
|---|---|---|
| Table I | Simulation parameters (particle, magnetic, gravity, timestep) | Values all known/verified — table not yet built |
| Table II | Controller parameters ($\varepsilon_x$, $\varepsilon_v$, $V_{\mathrm{CEIL}}$, $\omega_n$, $\zeta$, thresholds) | Values all known/verified — table not yet built |
| Table III | Per-cluster transport metrics | **NEEDS DATA** from a clean validation run |
| Table IV | Shaping metrics | **NEEDS DATA** — shaping not yet implemented |
| Table V | Ablation (old deadbeat BRAKE vs. critically-damped BRAKE) | Partial data exists (this session's synthetic sweep) — not yet tabulated |

## Reviewer-risk report (abbreviated — top concerns a skeptical T-ASE reviewer would raise)

1. **Transport does not converge.** The paper must not undersell this; Sections VI-B/IX already
   frame it as a characterized finding, but a reviewer will press on whether this undermines the
   paper's central claim. Mitigation: lean on the diagnostic rigor (real per-step data, not
   guesswork) as the contribution, not "we solved transport."
2. **Related Work is currently mostly placeholders.** This must be filled with real, verified
   citations before submission — an empty or thin Related Work section is an immediate desk-reject
   risk.
3. **No shaping results yet.** The paper currently has a strong transport-diagnosis story and a
   *proposed* shaping redesign with no validation. Consider whether this paper should scope itself
   as "transport controller diagnosis" alone (stronger, complete) with shaping as explicit future
   work, vs. waiting for shaping data to include it as a full result.
4. **Small particle count (256 total).** Reviewers will ask about scalability; Limitations already
   flags this, but Discussion should address it more directly once real data exist.
5. **No baseline/ablation against prior published methods** — only internal ablation (old vs. new
   controller law) exists. May need to justify why no external baseline is comparable.
6. **No physical hardware validation.** Simulation-only; already flagged in Limitations, keep it
   prominent rather than buried.
7. **On-axis dipole approximation used for control design vs. full off-axis force in the physics
   engine** — a careful reviewer will ask for a quantified discrepancy, not just an acknowledgment.
8. **AI-assisted drafting disclosure** — must be handled correctly per `PAPER_NOTES.md` §3 or risks
   a policy violation, not just a scientific critique.
9. **Softened/numerical contact stiffness** — if the real particle-particle stiffness had to be
   numerically softened for timestep feasibility, this needs its own explicit justification/
   sensitivity discussion (not yet drafted in Sec. IV-C).
10. **Optimization framing (Section 14 of original planning notes) is not actually used anywhere in
    the current manuscript** — if you want the paper to make an optimization contribution claim, that
    needs to be real (implemented and validated), not aspirational.

## Immediate next actions, in order

1. Decide paper scope: transport-only (complete, publishable now with placeholders removed) vs.
   transport+shaping (stronger, but blocked on Section VI-D implementation/validation).
2. Real literature search pass for Related Work II-A, II-B/C, II-E (the largest remaining gap).
3. Verify the 5 "provisional" citations already located (arXiv IDs, patent numbers, exact titles).
4. Generate Figures 3, 4, 5, 8 from data that already exists (no new simulation needed).
5. Build Tables I and II from already-known parameter values (no new simulation needed).
6. Only after shaping Candidate A is implemented and gated (per the shaping-fixture plan already in
   progress): fill Table III/IV, Figures 6/7, and the Results/Discussion/Conclusion placeholders.
