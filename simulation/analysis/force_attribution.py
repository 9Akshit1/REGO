"""
Attribution follow-up: force_budget_full_field.py measured F_r=31.7xW on
cluster 1 at t=2s under the full real field -- 1400x larger than the
isolated single-dipole test's F_r=0.022xW, and inconsistent with the
observed 0.09mm stability from the surf_conf=0 ablation. This script
isolates which real dipole(s) are responsible by zeroing candidate groups
(corner quadrupoles; cluster 2's own wait-hold dipole) one at a time,
immediately before compute_forces(), at the same real (t=2s, dynamically
evolved) particle positions -- not a fresh symmetric pack.

DIAGNOSTIC ONLY.
"""
import sys
import os

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phase2_shaping as sim  # noqa: E402
from shape_fixture import build_fixture  # noqa: E402
from shape_feasibility import local_frame  # noqa: E402


def measure(label, mask, target, C):
    sim.build_grid()
    sim.compute_forces()
    fm_np = sim.fmag.to_numpy()[mask]
    r_hat, t_hat, z_hat = local_frame(target, C)
    F_total = fm_np.sum(axis=0)
    W = 64 * C.mp * C.g
    print(f"  [{label}] F_r={np.dot(F_total,r_hat)/W:8.3f}xW  "
          f"F_t={np.dot(F_total,t_hat)/W:8.3f}xW  "
          f"F_z={np.dot(F_total,z_hat)/W:8.3f}xW  "
          f"|F|={np.linalg.norm(F_total):.3e}N")


def run(sample_t=2.0, cluster_k=1):
    pm = build_fixture(seed=1234)
    C = sim.C
    dt = C.dt
    t = 0.0
    batch = max(1, int(round(0.001 / dt)))
    while t < sample_t:
        p_np = sim.pos.to_numpy()
        v_np = sim.vel.to_numpy()
        cl_np = sim.cluster_id.to_numpy()
        centroids = {k: sim.get_cluster_centroid_np(p_np, cl_np, k) for k in range(4)}
        velocities = {k: sim.get_cluster_velocity_np(v_np, cl_np, k) for k in range(4)}
        sim.update_dipoles(t, pm, centroids, velocities)
        sim.surf_conf_enabled[None] = 0  # true magnetic-only baseline (see SHAPING_BASELINE_2026-08-19.md)
        sim.substep_batch(batch)
        t += batch * dt

    cl_np = sim.cluster_id.to_numpy()
    mask = cl_np == cluster_k
    target = C.targets[cluster_k]

    # Baseline: real field exactly as production would run it
    s_full = sim.dip_s.to_numpy().copy()
    p_full = sim.dip_p.to_numpy().copy()
    m_full = sim.dip_m.to_numpy().copy()
    measure("FULL (all real dipoles)", mask, target, C)

    # Isolate ONLY cluster 1's own wait-hold dipole (index IDX_CLUSTER_DIP[1])
    idx1 = sim.IDX_CLUSTER_DIP[1]
    s_only1 = np.zeros_like(s_full)
    s_only1[idx1] = s_full[idx1]
    sim.dip_s.from_numpy(s_only1)
    measure("ONLY c1's own wait dipole", mask, target, C)
    print(f"       (c1 dipole: pos={p_full[idx1]}, mom={m_full[idx1]}, s={s_full[idx1]})")

    # Isolate ONLY cluster 2's own dipole (candidate cross-talk source)
    idx2 = sim.IDX_CLUSTER_DIP[2]
    s_only2 = np.zeros_like(s_full)
    s_only2[idx2] = s_full[idx2]
    sim.dip_s.from_numpy(s_only2)
    measure("ONLY c2's dipole (cross-talk candidate)", mask, target, C)
    print(f"       (c2 dipole: pos={p_full[idx2]}, mom={m_full[idx2]}, s={s_full[idx2]})")

    # Isolate ONLY corner quadrupoles (indices 0-7, per N_DIP layout comment)
    s_corners = np.zeros_like(s_full)
    s_corners[0:8] = s_full[0:8]
    sim.dip_s.from_numpy(s_corners)
    measure("ONLY corner quadrupoles (idx 0-7)", mask, target, C)

    # Isolate ONLY cluster 0 and cluster 3's dipoles (should be off per v36, sanity check)
    idx0 = sim.IDX_CLUSTER_DIP[0]
    idx3 = sim.IDX_CLUSTER_DIP[3]
    s_caps = np.zeros_like(s_full)
    s_caps[idx0] = s_full[idx0]
    s_caps[idx3] = s_full[idx3]
    sim.dip_s.from_numpy(s_caps)
    measure("ONLY cap dipoles (idx0,idx3 -- sanity, should be s=0)", mask, target, C)
    print(f"       (c0 s={s_full[idx0]}, c3 s={s_full[idx3]})")

    # restore full field for reference
    sim.dip_s.from_numpy(s_full)
    print(f"\n  Full dip_s array: {s_full}")
    print(f"  (nonzero indices: {np.nonzero(s_full)[0].tolist()})")


if __name__ == "__main__":
    run()
