"""
Final pre-implementation shaping feasibility tests — REGO.

STATUS: DIAGNOSTIC MODE ONLY. Not part of the production pipeline. Imports
phase2_shaping.py's real, unmodified kernels (build_grid/compute_forces/
integrate) and real dipole-field model (B_and_gradB2, _B_dipole_at) and
drives them directly. Every test in this file isolates EXACTLY ONE real
dipole (all N_DIP-1 others held at strength 0) so the measured response is
attributable to a single, well-characterized field source — this is an
experimental-isolation choice for measurement clarity, not a production
architecture change: no force law is modified, no force is filtered by
cluster_id, no hidden term is added.

Four tests, run from the command line:
    wall-perturb    Section 1 — wall hold perturbation (stability check)
    force-budget    Section 2 — cluster-level vector force budget
    slow-well       Section 3/4 — translating well tracking-error vs speed
    cap-hold        Section 5/6 — cap parked-hold feasibility

Reuses `pack_cluster` from shape_fixture.py (real particle geometry, not
reimplemented).
"""
import sys
import os
import argparse
import json
import math

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phase2_shaping as sim  # noqa: E402
from shape_fixture import pack_cluster  # noqa: E402


def local_frame(target, C):
    """Cylindrical (radial, tangential, axial) unit vectors at `target`,
    relative to the cylinder axis (C.cx, C.cy, arbitrary z)."""
    rvec = np.array([target[0] - C.cx, target[1] - C.cy, 0.0])
    rnorm = np.linalg.norm(rvec)
    r_hat = rvec / rnorm if rnorm > 1e-12 else np.array([1.0, 0.0, 0.0])
    t_hat = np.array([-r_hat[1], r_hat[0], 0.0])
    z_hat = np.array([0.0, 0.0, 1.0])
    return r_hat, t_hat, z_hat


def set_single_dipole(idx, pos, mom, strength):
    """Zero every dipole, then set exactly one. Uses the real Taichi dipole
    fields (dip_p/dip_m/dip_s) that compute_forces()/B_and_gradB2() read —
    no separate/duplicated field model."""
    p = np.zeros((sim.N_DIP, 3))
    m = np.zeros((sim.N_DIP, 3))
    s = np.zeros(sim.N_DIP)
    p[idx] = pos
    m[idx] = mom
    s[idx] = strength
    sim.dip_p.from_numpy(p)
    sim.dip_m.from_numpy(m)
    sim.dip_s.from_numpy(s)


def build_single_cluster(cluster_k, center, seed=7000):
    """Real init(), then place ONE real 64-particle cluster (cluster_k) at
    `center`; the other 192 particle slots are placed far away with
    cluster_id=-1-equivalent (assigned a distinct id, zero-strength dipoles
    everywhere else anyway, so they cannot interact with the field, and are
    placed far enough apart that contact never reaches them)."""
    sim.init()
    C = sim.C
    N = C.N
    per = N // 4
    R = C.R
    pos_np = np.zeros((N, 3))
    cid_np = np.zeros(N, dtype=np.int32)
    idx = 0
    for k in range(4):
        if k == cluster_k:
            c = np.array(center, dtype=np.float64)
        else:
            # park the other 3 (unused, non-interacting) clusters far apart
            # in the corners of the domain floor, well outside contact range
            corner = np.array([0.5e-3 + 1.0e-3 * k, 0.5e-3, 0.05e-3])
            c = corner
        pts = pack_cluster(c, per, R, seed + k)
        pos_np[idx:idx + per] = pts
        cid_np[idx:idx + per] = k
        idx += per
    sim.pos.from_numpy(pos_np)
    sim.vel.from_numpy(np.zeros((N, 3)))
    sim.cluster_id.from_numpy(cid_np)
    sim.fixed_color.from_numpy(cid_np)
    sim.colors_fixed = True


def cluster_slice(cluster_k):
    cl_np = sim.cluster_id.to_numpy()
    return cl_np == cluster_k


def record_state(cluster_k, target, mask):
    p_np = sim.pos.to_numpy()[mask]
    v_np = sim.vel.to_numpy()[mask]
    fm_np = sim.fmag.to_numpy()[mask]
    centroid = p_np.mean(axis=0)
    r_rms = float(np.sqrt(np.mean(np.sum((p_np - centroid) ** 2, axis=1))))
    r_max = float(np.max(np.linalg.norm(p_np - centroid, axis=1)))
    vmag = float(np.linalg.norm(v_np, axis=1).mean())
    return dict(centroid=centroid, r_rms=r_rms, r_max=r_max, vmag=vmag,
                p=p_np, v=v_np, fm=fm_np)


# ─────────────────────────────────────────────────────────────────────────
# TEST 1 — wall hold perturbation
# ─────────────────────────────────────────────────────────────────────────
def wall_perturbation_test(axis, offset_mm, duration, record_dt, cluster_k=1):
    C = sim.C
    target = C.targets[cluster_k]
    r_hat, t_hat, z_hat = local_frame(target, C)
    axis_vec = {"radial": r_hat, "tangential": t_hat, "axial": z_hat}[axis]
    center = target + axis_vec * (offset_mm * 1e-3)

    build_single_cluster(cluster_k, center)
    mask = cluster_slice(cluster_k)

    # Real, unmodified "wait" hold config from phase2_shaping.py:2513-2522,
    # 2556-2565 (SHAPE_WAIT_HOLD_STRENGTH branch) — reproduced exactly, not
    # approximated: dipole AT target, moment purely radial inward.
    dip_idx = sim.IDX_CLUSTER_DIP[cluster_k]
    m_dir = np.array([-1., 0., 0.]) if cluster_k == 1 else np.array([1., 0., 0.])
    mom = sim._m_trap * m_dir
    strength = sim.SHAPE_WAIT_HOLD_STRENGTH
    set_single_dipole(dip_idx, target, mom, strength)

    t = 0.0
    dt = C.dt
    batch = max(1, int(round(0.001 / dt)))
    record = []
    next_t = 0.0
    while t < duration:
        sim.substep_batch(batch)
        t += batch * dt
        if t >= next_t:
            st = record_state(cluster_k, target, mask)
            err_vec = st["centroid"] - target
            row = dict(t=t,
                       err_r=float(np.dot(err_vec, r_hat)) * 1e3,
                       err_t=float(np.dot(err_vec, t_hat)) * 1e3,
                       err_z=float(np.dot(err_vec, z_hat)) * 1e3,
                       err_mag=float(np.linalg.norm(err_vec)) * 1e3,
                       vmag=st["vmag"] * 1e3, r_rms=st["r_rms"] * 1e3)
            record.append(row)
            next_t += record_dt
    return record


# ─────────────────────────────────────────────────────────────────────────
# TEST 2 — cluster-level vector force budget
# ─────────────────────────────────────────────────────────────────────────
def cluster_force_budget(cluster_k=1):
    C = sim.C
    target = C.targets[cluster_k]
    r_hat, t_hat, z_hat = local_frame(target, C)
    build_single_cluster(cluster_k, target)
    mask = cluster_slice(cluster_k)

    dip_idx = sim.IDX_CLUSTER_DIP[cluster_k]
    m_dir = np.array([-1., 0., 0.]) if cluster_k == 1 else np.array([1., 0., 0.])
    mom = sim._m_trap * m_dir
    strength = sim.SHAPE_WAIT_HOLD_STRENGTH
    set_single_dipole(dip_idx, target, mom, strength)

    sim.build_grid()
    sim.compute_forces()
    fm_np = sim.fmag.to_numpy()[mask]           # per-particle real magnetic force vectors
    p_np = sim.pos.to_numpy()[mask]

    F_total = fm_np.sum(axis=0)                  # TRUE vector sum, not sum of magnitudes
    F_r = float(np.dot(F_total, r_hat))
    F_t = float(np.dot(F_total, t_hat))
    F_z = float(np.dot(F_total, z_hat))

    per_particle_mag = np.linalg.norm(fm_np, axis=1)
    W_cluster = 64 * C.mp * C.g
    return dict(
        cluster_k=cluster_k, target=target.tolist(),
        F_total=F_total.tolist(), F_r=F_r, F_t=F_t, F_z=F_z,
        F_r_over_W=F_r / W_cluster, F_t_over_W=F_t / W_cluster, F_z_over_W=F_z / W_cluster,
        W_cluster=W_cluster,
        per_particle_min=float(per_particle_mag.min()),
        per_particle_max=float(per_particle_mag.max()),
        per_particle_mean=float(per_particle_mag.mean()),
        sum_of_magnitudes=float(per_particle_mag.sum()),   # reported for contrast only
        vector_sum_magnitude=float(np.linalg.norm(F_total)),
    )


# ─────────────────────────────────────────────────────────────────────────
# TEST 3 — slow translating well
# ─────────────────────────────────────────────────────────────────────────
def slow_well_test(v_tan_mm_s, duration, record_dt, cluster_k=1, strength=None):
    C = sim.C
    target = C.targets[cluster_k]
    tgt_phi0 = math.atan2(target[1] - C.cy, target[0] - C.cx)
    cR = C.cR
    z0 = target[2]
    strength = sim.SHAPE_WAIT_HOLD_STRENGTH if strength is None else strength
    omega = (v_tan_mm_s * 1e-3) / cR   # rad/s

    build_single_cluster(cluster_k, target)
    mask = cluster_slice(cluster_k)
    dip_idx = sim.IDX_CLUSTER_DIP[cluster_k]

    def aim_point(t):
        phi = tgt_phi0 + omega * t
        pos = np.array([C.cx + cR * math.cos(phi), C.cy + cR * math.sin(phi), z0])
        mom = sim._m_trap * np.array([-math.cos(phi), -math.sin(phi), 0.0])
        return pos, mom

    t = 0.0
    dt = C.dt
    batch = max(1, int(round(0.001 / dt)))
    record = []
    next_t = 0.0
    prev_v = None
    while t < duration:
        pos, mom = aim_point(t)
        set_single_dipole(dip_idx, pos, mom, strength)
        sim.substep_batch(batch)
        t += batch * dt

        if t >= next_t:
            st = record_state(cluster_k, target, mask)
            aim_now, _ = aim_point(t)
            err_vec = st["centroid"] - aim_now
            r_hat, t_hat, z_hat = local_frame(aim_now, C)
            min_sep = float(np.min(np.linalg.norm(st["p"] - pos, axis=1)))
            fm_mean = float(np.linalg.norm(st["fm"], axis=1).mean())
            row = dict(t=t, v_tan_mm_s=v_tan_mm_s,
                       err_r=float(np.dot(err_vec, r_hat)) * 1e3,
                       err_t=float(np.dot(err_vec, t_hat)) * 1e3,
                       err_z=float(np.dot(err_vec, z_hat)) * 1e3,
                       err_mag=float(np.linalg.norm(err_vec)) * 1e3,
                       vmag=st["vmag"] * 1e3, r_rms=st["r_rms"] * 1e3,
                       r_max=st["r_max"] * 1e3, min_sep_mm=min_sep * 1e3,
                       fmag_mean=fm_mean)
            record.append(row)
            next_t += record_dt

    return record


# ─────────────────────────────────────────────────────────────────────────
# TEST 4 — cap parked-hold feasibility
# ─────────────────────────────────────────────────────────────────────────
def cap_hold_test(cluster_k, standoff_mm, duration, record_dt):
    """Candidate cap dipole, by direct analogy to the ALREADY-VALIDATED wall
    active-slot z-lift branch (phase2_shaping.py:2549-2555: dipole 1mm above
    target, moment +z, s=0.10 -> ~2x gravity, documented and used in
    production for walls). For a top cap (k=0) the same geometry is applied
    verbatim: dipole above the cap plane, moment +z. For the bottom cap
    (k=3) it is mirrored: dipole below, moment -z."""
    C = sim.C
    target = C.targets[cluster_k]
    sign = 1.0 if cluster_k == 0 else -1.0
    standoff = standoff_mm * 1e-3
    dip_pos = target + sign * standoff * np.array([0., 0., 1.])
    mom = sim._m_trap * sign * np.array([0., 0., 1.])
    # size strength from the real single-particle inversion so the ceiling
    # acceleration has a stated margin over gravity, same method used
    # throughout phase2_shaping.py's own transport/hold sizing
    a_target = 3.0 * C.g   # 3x margin, same convention as SETTLE (D_HOLD, 3.0*C.g)
    strength = sim.solve_strength_for_accel(a_target, standoff)

    build_single_cluster(cluster_k, target)
    mask = cluster_slice(cluster_k)
    dip_idx = sim.IDX_CLUSTER_DIP[cluster_k]
    set_single_dipole(dip_idx, dip_pos, mom, strength)

    # cluster-level vector force budget at t=0 (before any motion)
    sim.build_grid()
    sim.compute_forces()
    fm_np = sim.fmag.to_numpy()[mask]
    F_total0 = fm_np.sum(axis=0)
    W_cluster = 64 * C.mp * C.g
    budget = dict(standoff_mm=standoff_mm, strength=strength,
                  F_z_total=float(F_total0[2]), W_cluster=W_cluster,
                  F_z_over_W=float(F_total0[2]) / W_cluster,
                  per_particle_min=float(np.linalg.norm(fm_np, axis=1).min()),
                  per_particle_max=float(np.linalg.norm(fm_np, axis=1).max()))

    t = 0.0
    dt = C.dt
    batch = max(1, int(round(0.001 / dt)))
    record = []
    next_t = 0.0
    while t < duration:
        sim.substep_batch(batch)
        t += batch * dt
        if t >= next_t:
            st = record_state(cluster_k, target, mask)
            err_vec = st["centroid"] - target
            row = dict(t=t,
                       err_z=float(err_vec[2]) * 1e3,
                       err_xy=float(np.linalg.norm(err_vec[:2])) * 1e3,
                       r_rms=st["r_rms"] * 1e3, r_max=st["r_max"] * 1e3,
                       vmag=st["vmag"] * 1e3)
            record.append(row)
            next_t += record_dt

    return budget, record


# ─────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("wall-perturb")
    p1.add_argument("--axis", choices=["radial", "tangential", "axial"], required=True)
    p1.add_argument("--offset-mm", type=float, default=0.3)
    p1.add_argument("--duration", type=float, default=4.0)
    p1.add_argument("--record-dt", type=float, default=0.05)
    p1.add_argument("--cluster", type=int, default=1)
    p1.add_argument("--out", type=str, default=None)

    p2 = sub.add_parser("force-budget")
    p2.add_argument("--cluster", type=int, default=1)
    p2.add_argument("--out", type=str, default=None)

    p3 = sub.add_parser("slow-well")
    p3.add_argument("--speeds", type=float, nargs="+", default=[0.1, 0.3, 1.0, 2.0, 5.0])
    p3.add_argument("--duration", type=float, default=3.0)
    p3.add_argument("--record-dt", type=float, default=0.1)
    p3.add_argument("--cluster", type=int, default=1)
    p3.add_argument("--out", type=str, default=None)

    p4 = sub.add_parser("cap-hold")
    p4.add_argument("--cluster", type=int, default=0)
    p4.add_argument("--standoff-mm", type=float, default=1.0)
    p4.add_argument("--duration", type=float, default=4.0)
    p4.add_argument("--record-dt", type=float, default=0.1)
    p4.add_argument("--out", type=str, default=None)

    args = ap.parse_args()

    if args.cmd == "wall-perturb":
        print(f"=== WALL PERTURBATION: axis={args.axis} offset={args.offset_mm}mm "
              f"cluster={args.cluster} ===")
        rec = wall_perturbation_test(args.axis, args.offset_mm, args.duration,
                                      args.record_dt, args.cluster)
        for row in rec[::max(1, len(rec) // 20)]:
            print(f"  t={row['t']:5.2f}s  err_r={row['err_r']:+7.4f}mm  "
                  f"err_t={row['err_t']:+7.4f}mm  err_z={row['err_z']:+7.4f}mm  "
                  f"|err|={row['err_mag']:7.4f}mm  v={row['vmag']:7.3f}mm/s  "
                  f"r_rms={row['r_rms']:6.4f}mm")
        if args.out:
            json.dump(rec, open(args.out, "w"), indent=1)

    elif args.cmd == "force-budget":
        print(f"=== CLUSTER-LEVEL VECTOR FORCE BUDGET: cluster={args.cluster} ===")
        res = cluster_force_budget(args.cluster)
        for k_, v_ in res.items():
            print(f"  {k_}: {v_}")
        if args.out:
            json.dump(res, open(args.out, "w"), indent=1)

    elif args.cmd == "slow-well":
        all_rec = {}
        for v in args.speeds:
            print(f"=== SLOW WELL: v_tan={v}mm/s cluster={args.cluster} ===")
            rec = slow_well_test(v, args.duration, args.record_dt, args.cluster)
            all_rec[v] = rec
            for row in rec[::max(1, len(rec) // 10)]:
                print(f"  t={row['t']:5.2f}s  |err|={row['err_mag']:7.4f}mm  "
                      f"err_r={row['err_r']:+7.4f}  err_t={row['err_t']:+7.4f}  "
                      f"err_z={row['err_z']:+7.4f}  v={row['vmag']:7.3f}mm/s  "
                      f"r_rms={row['r_rms']:6.4f}mm  min_sep={row['min_sep_mm']:6.4f}mm  "
                      f"Fmag={row['fmag_mean']:.3e}N")
            final = rec[-1]
            print(f"  --> FINAL @ v={v}mm/s: |err|={final['err_mag']:.4f}mm  "
                  f"r_rms={final['r_rms']:.4f}mm")
        if args.out:
            json.dump(all_rec, open(args.out, "w"), indent=1)

    elif args.cmd == "cap-hold":
        print(f"=== CAP HOLD: cluster={args.cluster} standoff={args.standoff_mm}mm ===")
        budget, rec = cap_hold_test(args.cluster, args.standoff_mm, args.duration, args.record_dt)
        print("  Force budget (t=0):")
        for k_, v_ in budget.items():
            print(f"    {k_}: {v_}")
        for row in rec[::max(1, len(rec) // 20)]:
            print(f"  t={row['t']:5.2f}s  err_z={row['err_z']:+7.4f}mm  "
                  f"err_xy={row['err_xy']:7.4f}mm  r_rms={row['r_rms']:6.4f}mm  "
                  f"v={row['vmag']:7.3f}mm/s")
        if args.out:
            json.dump(dict(budget=budget, record=rec), open(args.out, "w"), indent=1)
