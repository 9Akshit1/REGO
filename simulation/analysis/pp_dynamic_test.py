"""
Dynamic (rotating-field) particle-particle magnetic interaction test — REGO.

STATUS: ISOLATED RESEARCH HARNESS. Does NOT modify phase2_shaping.py.
Reuses the real, unmodified build_grid()/compute_forces()/integrate()
kernels for a small number of real particles (real mass, real Hertz-Mindlin
contact, real gravity), and adds ONE new Taichi kernel (`add_pp_force`,
defined here, not in production) that computes the candidate particle-
particle induced-dipole force validated in pp_magnetic_interaction.py and
adds it into `frc` between compute_forces() and integrate() -- i.e. exactly
the physics compute_forces() would apply if this term were added there,
without actually editing that shared production function yet.

A single "manipulation dipole" (production's own IDX_CLUSTER_DIP[1] slot,
reused, not a new special-cased mechanism) sits at the validated n_R=3
standoff from the test cluster and its MOMENT DIRECTION rotates over time in
the y-z plane at a settable angular frequency -- this is what makes the
local field, and therefore the particle-particle interaction character
(chaining vs. repulsive), time-varying, exactly the mechanism the
literature describes, expressed as a real rotating source rather than a
hidden per-particle force.

Usage:
    python pp_dynamic_test.py --n 3   --omega 0 --duration 0.5   (static, qualitative)
    python pp_dynamic_test.py --n 12  --omega 50 --duration 1.0  (rotating, disaggregation test)
    python pp_dynamic_test.py --n 12  --omega 0  --duration 1.0  (control: no rotation)
    python pp_dynamic_test.py --wall-hold-check                 (Step 10: effect on existing hold)
"""
import sys
import os
import math
import argparse
import json

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phase2_shaping as sim  # noqa: E402

C = sim.C
ti = sim.ti
MU0 = sim.MU0
R = C.R
Vp = (4.0 / 3.0) * math.pi * R ** 3

# ── New kernel: particle-particle induced-dipole force ──────────────────
# NOT added to phase2_shaping.py. Reuses the same grid (grid_cnt/grid_buf)
# compute_forces() already builds each step via build_grid(), so neighbor
# search is unmodified/reused, not reimplemented.
pp_force_enabled = ti.field(ti.f64, shape=())
B_ext_vec = ti.Vector.field(3, ti.f64, shape=C.N)  # scratch: external B vector per particle


@ti.kernel
def compute_B_ext_vec():
    """External B VECTOR at each particle (production's B_and_gradB2 only
    returns |B| and grad(B^2), not the vector -- needed here for moment
    direction). Identical dipole-sum formula, read-only w.r.t. dip_p/m/s."""
    for i in range(C.N):
        r = sim.pos[i]
        B = ti.Vector([0.0, 0.0, 0.0])
        for k in range(sim.N_DIP):
            sk = sim.dip_s[k]
            if sk > 1e-15:
                mv = sim.dip_m[k] * sk
                rv = r - sim.dip_p[k]
                r2 = rv.dot(rv)
                if r2 > 1e-22:
                    r5 = r2 * r2 * ti.sqrt(r2)
                    mdotr = mv.dot(rv)
                    B += (sim._MU0_4PI / r5) * (3.0 * mdotr * rv - r2 * mv)
        B_ext_vec[i] = B


@ti.kernel
def add_pp_force():
    """Adds the validated frozen-induced-dipole pairwise force to frc[i],
    using the SAME grid contact_pp() already built this step. chi_eff/Vp/mu0
    reused from production (sim.chi_eff, not reimplemented)."""
    if pp_force_enabled[None] > 0.5:
        for i in range(C.N):
            Bext = B_ext_vec[i]
            Bmag = Bext.norm()
            ce = sim.chi_eff(Bmag)
            mi = (Vp * ce / MU0) * Bext
            gx = ti.max(0, ti.min(sim.HRES - 1, int(ti.floor(sim.pos[i][0] / C.hcell))))
            gy = ti.max(0, ti.min(sim.HRES - 1, int(ti.floor(sim.pos[i][1] / C.hcell))))
            gz = ti.max(0, ti.min(sim.HRES - 1, int(ti.floor(sim.pos[i][2] / C.hcell))))
            Fpp = ti.Vector([0.0, 0.0, 0.0])
            for dx in ti.static(range(-1, 2)):
                for dy in ti.static(range(-1, 2)):
                    for dz in ti.static(range(-1, 2)):
                        nx = gx + dx; ny = gy + dy; nz = gz + dz
                        if 0 <= nx < sim.HRES and 0 <= ny < sim.HRES and 0 <= nz < sim.HRES:
                            cnt = sim.grid_cnt[nx, ny, nz]
                            for s in range(cnt):
                                j = sim.grid_buf[nx, ny, nz, s]
                                if j != i:
                                    Bext_j = B_ext_vec[j]
                                    ce_j = sim.chi_eff(Bext_j.norm())
                                    mj = (Vp * ce_j / MU0) * Bext_j
                                    rv = sim.pos[j] - sim.pos[i]
                                    d2 = rv.dot(rv)
                                    if d2 > 1e-22:
                                        d = ti.sqrt(d2)
                                        n = rv / d
                                        mi_n = mi.dot(n)
                                        mj_n = mj.dot(n)
                                        mi_mj = mi.dot(mj)
                                        pref = 3.0 * MU0 / (4.0 * math.pi * d2 * d2)
                                        # force ON i FROM j = -(force on j from i); using
                                        # the symmetric formula directly for the pair as seen from i:
                                        Fij = pref * (mi_n * mj + mj_n * mi + (mi_mj - 5.0 * mi_n * mj_n) * n)
                                        Fpp -= Fij  # Newton's 3rd law: force on i is -[force on j from this pair term]
            sim.frc[i] += Fpp


def substep_with_pp(n_sub, rotate_omega=0.0, t0=0.0, dip_idx=None, standoff=None, tgt_center=None):
    """Same loop structure as production substep_batch(), plus the new
    force kernel inserted between compute_forces() and integrate(), plus
    optional per-step rotation of the manipulation dipole's moment."""
    dt = C.dt
    t = t0
    for _ in range(n_sub):
        if rotate_omega != 0.0 and dip_idx is not None:
            ang = rotate_omega * t
            p_np = sim.dip_p.to_numpy(); m_np = sim.dip_m.to_numpy()
            p_np[dip_idx] = tgt_center + standoff * np.array([1.0, 0.0, 0.0])
            m_np[dip_idx] = sim._m_trap * np.array([0.0, math.cos(ang), math.sin(ang)])
            sim.dip_p.from_numpy(p_np); sim.dip_m.from_numpy(m_np)
        sim.build_grid()
        sim.compute_forces()
        compute_B_ext_vec()
        add_pp_force()
        sim.integrate()
        t += dt
    return t


def pack_tiny_cluster(center, n, seed=99):
    rng = np.random.RandomState(seed)
    side = int(np.ceil(n ** (1.0 / 3.0)))
    sp = 2.3 * R
    pts = []
    for iz in range(side):
        for iy in range(side):
            for ix in range(side):
                if len(pts) >= n:
                    break
                jitter = rng.normal(0, 0.15 * R, size=3)
                offset = (np.array([ix, iy, iz], dtype=np.float64) * sp - sp * (side - 1) / 2.0)
                pts.append(center + offset + jitter)
    return np.array(pts[:n], dtype=np.float64)


def build_isolated(n_test, seed=99):
    sim.init()
    N = C.N
    pos_np = np.full((N, 3), -1.0, dtype=np.float64)  # park everyone far away by default
    cid_np = np.zeros(N, dtype=np.int32)
    center = np.array([C.cx, C.cy, C.cz])
    pts = pack_tiny_cluster(center, n_test, seed)
    pos_np[:n_test] = pts
    cid_np[:n_test] = 1
    # park the rest far outside the domain, non-interacting, distinct cluster ids (unused)
    far = np.array([-0.05, -0.05, -0.05])
    for k in range(n_test, N):
        pos_np[k] = far + np.array([0.001 * (k % 50), 0.001 * ((k // 50) % 50), 0.0])
        cid_np[k] = 2 if k % 2 else 3
    sim.pos.from_numpy(pos_np)
    sim.vel.from_numpy(np.zeros((N, 3), dtype=np.float64))
    sim.cluster_id.from_numpy(cid_np)
    sim.fixed_color.from_numpy(cid_np)
    sim.colors_fixed = True
    sim.dip_s.fill(0.0)
    return center


def cluster_metrics(pos_np, n_test, center):
    p = pos_np[:n_test]
    centroid = p.mean(axis=0)
    r = np.linalg.norm(p - centroid, axis=1)
    r_rms = float(np.sqrt(np.mean(r ** 2)))
    r95 = float(np.percentile(r, 95))
    r_max = float(np.max(r))
    diffs = p[:, None, :] - p[None, :, :]
    dmat = np.linalg.norm(diffs, axis=2)
    np.fill_diagonal(dmat, np.inf)
    min_pair = float(dmat.min())
    mean_pair = float(dmat[dmat < np.inf].mean())
    # crude coherent-subgroup count: union-find on pairs within 3*(2R)
    thresh = 3.0 * 2.0 * R
    parent = list(range(n_test))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for a in range(n_test):
        for b in range(a + 1, n_test):
            if dmat[a, b] < thresh:
                union(a, b)
    n_groups = len(set(find(x) for x in range(n_test)))
    return dict(r_rms=r_rms, r95=r95, r_max=r_max, min_pair_mm=min_pair * 1e3,
                mean_pair_mm=mean_pair * 1e3, n_groups=n_groups, centroid=centroid.tolist())


def run(n_test, omega, duration, seed=99, record_dt=0.02, out=None, strength=1.0):
    center = build_isolated(n_test, seed)
    dip_idx = sim.IDX_CLUSTER_DIP[1]
    standoff = 3.0 * R
    p_np = sim.dip_p.to_numpy(); m_np = sim.dip_m.to_numpy(); s_np = sim.dip_s.to_numpy()
    p_np[dip_idx] = center + standoff * np.array([1.0, 0.0, 0.0])
    m_np[dip_idx] = sim._m_trap * np.array([0.0, 1.0, 0.0])
    s_np[dip_idx] = strength
    sim.dip_p.from_numpy(p_np); sim.dip_m.from_numpy(m_np); sim.dip_s.from_numpy(s_np)
    pp_force_enabled[None] = 1.0

    dt = C.dt
    t = 0.0
    batch = max(1, int(round(record_dt / dt)))
    record = []
    while t < duration:
        t = substep_with_pp(batch, rotate_omega=omega, t0=t, dip_idx=dip_idx,
                             standoff=standoff, tgt_center=center)
        pos_np = sim.pos.to_numpy()
        vel_np = sim.vel.to_numpy()
        m = cluster_metrics(pos_np, n_test, center)
        vmax = float(np.linalg.norm(vel_np[:n_test], axis=1).max())
        m["t"] = t; m["vmax_mms"] = vmax * 1e3
        record.append(m)
        print(f"  t={t:6.3f}s  r_rms={m['r_rms']*1e3:.4f}mm  r95={m['r95']*1e3:.4f}mm  "
              f"r_max={m['r_max']*1e3:.4f}mm  min_pair={m['min_pair_mm']:.4f}mm  "
              f"n_groups={m['n_groups']}  vmax={vmax*1e3:.3f}mm/s")
    if out:
        with open(out, "w") as f:
            json.dump(record, f, indent=1)
    return record


def wall_hold_check(duration=2.0, record_dt=0.05, out=None):
    """Step 10: does adding the pp force change the ALREADY-VALIDATED
    stationary wall wait-hold's behavior? Reuses the real 64-particle wall
    cluster 1 in its exact validated wait-hold config, real physics,
    pp force ON."""
    sim.init()
    N = C.N
    per_cluster = N // 4
    pos_np = np.zeros((N, 3), dtype=np.float64)
    cid_np = np.zeros(N, dtype=np.int32)
    idx = 0
    for k in range(4):
        c = sim.C.targets[k].copy()
        pts = pack_tiny_cluster(c, per_cluster, seed=1234 + k)
        pos_np[idx:idx + per_cluster] = pts
        cid_np[idx:idx + per_cluster] = k
        idx += per_cluster
    sim.pos.from_numpy(pos_np)
    sim.vel.from_numpy(np.zeros((N, 3), dtype=np.float64))
    sim.cluster_id.from_numpy(cid_np)
    sim.fixed_color.from_numpy(cid_np)
    sim.colors_fixed = True
    sim.dip_s.fill(0.0)
    IDX = sim.IDX_CLUSTER_DIP[1]
    tgt = sim.C.targets[1].copy()
    p_np = sim.dip_p.to_numpy(); m_np = sim.dip_m.to_numpy(); s_np = sim.dip_s.to_numpy()
    p_np[IDX] = tgt
    m_np[IDX] = sim._m_trap * np.array([-1., 0., 0.])
    s_np[IDX] = sim.SHAPE_WAIT_HOLD_STRENGTH
    sim.dip_p.from_numpy(p_np); sim.dip_m.from_numpy(m_np); sim.dip_s.from_numpy(s_np)
    pp_force_enabled[None] = 1.0

    dt = C.dt
    t = 0.0
    batch = max(1, int(round(record_dt / dt)))
    record = []
    while t < duration:
        t = substep_with_pp(batch, rotate_omega=0.0, t0=t)
        pos_np = sim.pos.to_numpy()
        cl_np = sim.cluster_id.to_numpy()
        p1 = pos_np[cl_np == 1]
        d = np.linalg.norm(p1 - tgt, axis=1)
        centroid = p1.mean(axis=0)
        r_rms = float(np.sqrt(np.mean(np.sum((p1 - centroid) ** 2, axis=1))))
        diffs = p1[:, None, :] - p1[None, :, :]
        dmat = np.linalg.norm(diffs, axis=2)
        np.fill_diagonal(dmat, np.inf)
        row = dict(t=t, d_tgt_mean=float(d.mean()) * 1e3, r_rms_mm=r_rms * 1e3,
                   min_pair_mm=float(dmat.min()) * 1e3)
        record.append(row)
        print(f"  t={t:6.3f}s  d_tgt_mean={row['d_tgt_mean']:.4f}mm  r_rms={row['r_rms_mm']:.4f}mm  "
              f"min_pair={row['min_pair_mm']:.4f}mm")
    if out:
        with open(out, "w") as f:
            json.dump(record, f, indent=1)
    return record


def sweep(n_test, omegas, duration, record_dt=0.02, seed=99, out=None, strength=1.0):
    """Runs several omega values sequentially in ONE process (kernels JIT-
    compile once, reused across all omegas -- avoids repeated ~1min Taichi
    startup/compile overhead per launch)."""
    results = {}
    for om in omegas:
        print(f"\n{'='*70}\nomega = {om} rad/s (period={2*math.pi/om:.4f}s) strength={strength}" if om > 0 else f"\n{'='*70}\nomega = 0 (static control) strength={strength}")
        print('='*70)
        rec = run(n_test, om, duration, seed, record_dt, out=None, strength=strength)
        results[str(om)] = rec
    if out:
        with open(out, "w") as f:
            json.dump(results, f, indent=1)
    print(f"\n{'='*70}\nSUMMARY (final state per omega)\n{'='*70}")
    for om_s, rec in results.items():
        last = rec[-1]
        print(f"  omega={om_s:>8}  r_rms={last['r_rms']*1e3:.4f}mm  r95={last['r95']*1e3:.4f}mm  "
              f"r_max={last['r_max']*1e3:.4f}mm  min_pair={last['min_pair_mm']:.4f}mm  "
              f"n_groups={last['n_groups']}  vmax={last['vmax_mms']:.2f}mm/s")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--omega", type=float, default=0.0, help="rad/s, field rotation rate")
    ap.add_argument("--duration", type=float, default=0.5)
    ap.add_argument("--record-dt", type=float, default=0.02)
    ap.add_argument("--seed", type=int, default=99)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--wall-hold-check", action="store_true")
    ap.add_argument("--sweep", type=str, default=None,
                     help="Comma-separated omega values (rad/s) to sweep in one process, e.g. '0,50,150,400'")
    ap.add_argument("--strength", type=float, default=1.0,
                     help="Manipulation dipole strength (0-1), e.g. 0.15 = SHAPE_WAIT_HOLD_STRENGTH")
    args = ap.parse_args()
    if args.wall_hold_check:
        wall_hold_check(duration=args.duration if args.duration != 0.5 else 2.0,
                         record_dt=args.record_dt, out=args.out)
    elif args.sweep:
        omegas = [float(x) for x in args.sweep.split(",")]
        sweep(args.n, omegas, args.duration, args.record_dt, args.seed, args.out, strength=args.strength)
    else:
        run(args.n, args.omega, args.duration, args.seed, args.record_dt, args.out, strength=args.strength)
