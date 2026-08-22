#!/usr/bin/env python3
"""
validate_phase2.py — Stage A physics-correctness validation
=============================================================
Checks a phase2_shaping.py checkpoint against the criteria set out in the
Stage A audit (see ../CONTEXT.md "Physical limits and known placeholders"
and ../HISTORY.md). This is a correctness check, NOT a "did the cylinder
form" check — Stage A's goal is a correct simulation, and per the audit a
correct simulation is still expected to fail to hold particles spread over
the target surfaces once the placeholder surf_conf spring is the only thing
attempting it (see CONTEXT.md's Earnshaw discussion). That expected outcome
is not a validation failure here.

Mirrors constants from phase2_shaping.py's class C by hand (same convention
as p2_extract.py / p2_metrics.py) so this script has no taichi dependency
and does not trigger ti.init() / GPU selection just to check a checkpoint.
If phase2_shaping.py's constants change, these must be updated to match —
this is a known duplication, same as the rest of analysis/.

Usage:
    python analysis/validate_phase2.py outputs/shape_checkpoint.pkl
    python analysis/validate_phase2.py outputs/phase2_checkpoint.pkl
    python analysis/validate_phase2.py outputs/shape_checkpoint.pkl outputs/phase2_checkpoint.pkl
"""
import sys, math, pickle
import numpy as np
from pathlib import Path

MU0 = 4.0 * math.pi * 1e-7
PI = math.pi
_MU0_4PI = MU0 / (4.0 * PI)

# ── Mirrored from phase2_shaping.py class C (post Stage-A-fix values) ─────
R = 3e-5
RHO = 7800.0
VP = (4/3) * PI * R**3
MP = VP * RHO
G = 1.62
W = MP * G
CHI = 0.15
MSAT = 2e5
E_EFF = 2e5; NU = 0.25; E_STAR = E_EFF / (2 * (1 - NU**2)); R_STAR = R / 2
W_ADH = 0.08              # J/m^2 — DMT adhesion (F11)
F_ADH = 2.0 * PI * R_STAR * W_ADH

DT = 3.0e-6                # F8
HCELL = 8.0 * R            # F1
MAXPC = 96                 # F1
GRAD_B2_CLAMP_GUARD = 30.0 # F6/F7 — numerical guard, should not saturate

# Stage A-2 (F15/F16) closed-loop transport controller constants — mirrored
# for the transport-speed regression check below.
V_CEIL_MIRROR = 8.0e-3     # m/s
TRANSPORT_SPEED_CEILING = 5.0 * V_CEIL_MIRROR   # generous margin for brake-zone dynamics

N_EXPECTED = 256
COUNTS_EXPECTED = 64


def load(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def B_field(r, dip_p, dip_m, dip_s):
    """r: (3,), dip_p/dip_m: (N_DIP,3), dip_s: (N_DIP,) -> (3,)"""
    B = np.zeros(3)
    for k in range(len(dip_s)):
        sk = dip_s[k]
        if sk > 1e-15:
            mv = dip_m[k] * sk
            rv = r - dip_p[k]
            r2 = rv @ rv
            if r2 > 1e-22:
                rmag = math.sqrt(r2)
                rhat = rv / rmag
                coeff = _MU0_4PI / (r2 * rmag)
                B += coeff * (3.0 * (mv @ rhat) * rhat - mv)
    return B


def gradB2_fd(r, dip_p, dip_m, dip_s, h=1e-8):
    g = np.zeros(3)
    for a in range(3):
        e = np.zeros(3); e[a] = h
        Bp = B_field(r + e, dip_p, dip_m, dip_s)
        Bm = B_field(r - e, dip_p, dip_m, dip_s)
        g[a] = (Bp @ Bp - Bm @ Bm) / (2 * h)
    return g


def chi_eff(Bmag):
    alpha = min(CHI * Bmag / (MU0 * MSAT), 20.0)
    return CHI / math.cosh(alpha)**2


def check(path):
    print(f"\n{'='*72}\n  VALIDATING: {path}\n{'='*72}")
    d = load(path)
    ok_all = True

    def report(name, passed, detail=""):
        nonlocal ok_all
        ok_all = ok_all and passed
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))

    pos = d['pos']; vel = d['vel']
    cl = d['cluster_id']; fc = d['fixed_color']

    # ── Identity (F5) ──────────────────────────────────────────────────
    report("particle count == 256", len(pos) == N_EXPECTED, f"got {len(pos)}")
    report("cluster_id == fixed_color for all particles",
           np.array_equal(cl, fc))
    counts = np.bincount(cl, minlength=4)
    report("cluster counts == [64,64,64,64]",
           bool(np.all(counts == COUNTS_EXPECTED)), f"got {counts.tolist()}")

    # ── Conservation ───────────────────────────────────────────────────
    report("no NaN/Inf in position", bool(np.all(np.isfinite(pos))))
    report("no NaN/Inf in velocity", bool(np.all(np.isfinite(vel))))

    # ── Contact integrity (F1, F2) ────────────────────────────────────
    idx = np.floor(pos / HCELL).astype(int)
    from collections import Counter
    occ = Counter(map(tuple, idx))
    peak_occ = max(occ.values()) if occ else 0
    report(f"peak grid-cell occupancy <= MAXPC={MAXPC}", peak_occ <= MAXPC,
           f"peak={peak_occ}")

    D = np.linalg.norm(pos[:, None, :] - pos[None, :, :], axis=2)
    np.fill_diagonal(D, np.inf)
    min_d = D.min()
    report("minimum pair distance > 0", min_d > 0, f"min_d={min_d:.3e} m")
    ov = 2*R - D
    ov = ov[ov > 0]
    max_ov_frac = (ov.max() / R) if len(ov) else 0.0
    report("maximum overlap < 0.1R (contact stiffness resolves properly)",
           max_ov_frac < 0.1, f"max_overlap={max_ov_frac:.3f}R  n_pairs={len(ov)//2}")

    # ── Timestep stability (F8) — omega*dt for the stiffest realised contact
    ov_m = (2*R - D); ov_m = ov_m[ov_m > 0]
    if len(ov_m):
        worst_delta = ov_m.max()
        kn = (4.0/3.0) * E_STAR * math.sqrt(R_STAR * worst_delta)
        m_star = MP / 2
        omega = math.sqrt(kn / m_star)
        omega_dt = omega * DT
        report("omega*dt < 0.2 for stiffest realised contact", omega_dt < 0.2,
               f"omega*dt={omega_dt:.4f}  (delta={worst_delta/R:.3f}R)")
    else:
        print("  [INFO] no particle-particle contacts in this checkpoint — omega*dt check skipped")

    # ── Force sanity (F6/F7) — live dipole state in this checkpoint ───
    dip_p = d['dip_pos_np']; dip_m = d['dip_mom_np']; dip_s = d['dip_str_np']
    n_active = int(np.sum(dip_s > 1e-6))
    fmags = np.zeros(len(pos))
    n_saturated = 0
    for i in range(len(pos)):
        g = gradB2_fd(pos[i], dip_p, dip_m, dip_s)
        gn = np.linalg.norm(g)
        if gn > 0.98 * GRAD_B2_CLAMP_GUARD:
            n_saturated += 1
        Bmag = np.linalg.norm(B_field(pos[i], dip_p, dip_m, dip_s))
        ce = chi_eff(Bmag)
        Fm = (VP * ce / (2 * MU0)) * g
        fmags[i] = np.linalg.norm(Fm)
    peak_xW = fmags.max() / W
    report(f"active dipoles: {n_active}", True)
    report("peak |F_mag|/W within design ceiling (<200x)", peak_xW < 200,
           f"peak={peak_xW:.1f}xW  mean={fmags.mean()/W:.2f}xW")
    report("gradient soft-clamp NOT saturated for >5% of particles",
           n_saturated < 0.05 * len(pos),
           f"{n_saturated}/{len(pos)} particles within 2% of clamp")

    # ── Cross-talk onto caps from currently-active dipoles (F3) ────────
    for cid, name, in ((0, "Q0/top"), (3, "Q3/bottom")):
        mask = cl == cid
        if not np.any(mask):
            continue
        cap_pos = pos[mask]
        cap_f = np.array([np.linalg.norm(
            (VP * chi_eff(np.linalg.norm(B_field(p, dip_p, dip_m, dip_s))) / (2*MU0))
            * gradB2_fd(p, dip_p, dip_m, dip_s)) for p in cap_pos])
        report(f"{name} cap: max cross-talk force < 20xW",
               cap_f.max()/W < 20, f"max={cap_f.max()/W:.2f}xW mean={cap_f.mean()/W:.3f}xW")

    # ── Cohesion sanity (F11/F12) ──────────────────────────────────────
    report("F_adh/W matches audit figure (~5000x, R=30um)",
           abs(F_ADH/W - 5275.9) < 50, f"F_adh/W={F_ADH/W:.1f}")

    # ── Phase machine ──────────────────────────────────────────────────
    pm = d['phase_manager']
    print(f"  [INFO] phase_manager: state={pm['state']}  t={d['t']:.3f}s  "
          f"completed={pm['completed']}")

    # ── Transport speed regression check (Stage A-2, F15/F16) ───────────
    # If this checkpoint is mid-transport/interlude, real cluster speed
    # should already be governed by the closed-loop controller's V_CEIL,
    # not running away as it did pre-Stage-A-2 (50,000-97,000 mm/s observed
    # in the pre-fix run). A single checkpoint only samples one instant —
    # analysis/reconstruct_run.py's full-history scan is the authoritative
    # check across an entire transport; this is a cheap single-point guard.
    if pm['state'].startswith('transport_') or pm['state'].startswith('interlude_'):
        for k in range(4):
            mask = cl == k
            if not np.any(mask):
                continue
            speed = np.linalg.norm(vel[mask], axis=1)
            report(f"Q{k} speed < {TRANSPORT_SPEED_CEILING*1e3:.0f}mm/s during {pm['state']}",
                   speed.max() < TRANSPORT_SPEED_CEILING,
                   f"max={speed.max()*1e3:.1f}mm/s mean={speed.mean()*1e3:.2f}mm/s")

    # ── LIFTOFF/CRUISE dipole-separation regression guard (Stage A-3, F17) ──
    # F17's root cause was the CRUISE pursuit dipole running arbitrarily far
    # from the real cluster (measured 0.79->5.00mm in the pre-fix run). A
    # single checkpoint only samples one instant — reconstruct_run.py's
    # per-frame scan is the authoritative full-transport check — but this is
    # a cheap guard against the same regression reappearing. Design bounds:
    # LIFT/BRAKE/SETTLE hold the dipole at a fixed 0.5mm standoff; CRUISE is
    # explicitly capped at MAX_CRUISE_STANDOFF=0.75mm. 1.5mm is a generous
    # (2x) margin over the largest of those, not a re-derivation.
    if pm['state'].startswith('transport_'):
        k_active = int(pm['state'].split('_')[1])
        IDX_CLUSTER_DIP = {0: 8, 1: 9, 2: 10, 3: 11}   # mirrored from phase2_shaping.py
        MAX_SEP_GUARD = 1.5e-3
        mask = cl == k_active
        if np.any(mask):
            centroid = pos[mask].mean(axis=0)
            dip_idx = IDX_CLUSTER_DIP[k_active]
            sep = float(np.linalg.norm(dip_pos[dip_idx] - centroid))
            report(f"Q{k_active} active-transport dipole-cluster separation < {MAX_SEP_GUARD*1e3:.1f}mm",
                   sep < MAX_SEP_GUARD, f"sep={sep*1e3:.3f}mm")

    print(f"\n  {'ALL CHECKS PASSED' if ok_all else 'SOME CHECKS FAILED'} for {path}")
    return ok_all


def main():
    paths = sys.argv[1:]
    if not paths:
        paths = ["outputs/shape_checkpoint.pkl", "outputs/phase2_checkpoint.pkl"]
    results = {}
    for p in paths:
        if not Path(p).exists():
            print(f"\n  [SKIP] {p} does not exist")
            continue
        results[p] = check(p)
    print(f"\n{'='*72}")
    for p, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {p}")
    print("="*72)
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
