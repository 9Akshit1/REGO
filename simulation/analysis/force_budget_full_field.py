"""
Cluster-level vector force budget under the REAL, FULL field environment
(corner quadrupoles + all four clusters' own dipoles, exactly as
update_dipoles() would run them in production) rather than an artificially
isolated single dipole. Companion / correction to shape_feasibility.py's
`force-budget` command, which isolates one dipole for clean attribution but
therefore under-reports the true support a particle actually receives in a
real run (corner quadrupoles are always active in production and were
excluded from that isolated test).

DIAGNOSTIC ONLY.
"""
import sys
import os

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phase2_shaping as sim  # noqa: E402
from shape_fixture import build_fixture  # noqa: E402
from shape_feasibility import local_frame  # noqa: E402


def run(sample_t, cluster_k=1):
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

    sim.build_grid()
    sim.compute_forces()
    cl_np = sim.cluster_id.to_numpy()
    mask = cl_np == cluster_k
    fm_np = sim.fmag.to_numpy()[mask]
    target = C.targets[cluster_k]
    r_hat, t_hat, z_hat = local_frame(target, C)

    F_total = fm_np.sum(axis=0)
    F_r = float(np.dot(F_total, r_hat))
    F_t = float(np.dot(F_total, t_hat))
    F_z = float(np.dot(F_total, z_hat))
    W_cluster = 64 * C.mp * C.g
    mag = np.linalg.norm(fm_np, axis=1)
    print(f"t={t:.3f}s  cluster={cluster_k}")
    print(f"  F_total(vector)={F_total}")
    print(f"  F_r={F_r:.3e}N ({F_r/W_cluster:.4f}xW)  "
          f"F_t={F_t:.3e}N ({F_t/W_cluster:.4f}xW)  "
          f"F_z={F_z:.3e}N ({F_z/W_cluster:.4f}xW)")
    print(f"  W_cluster={W_cluster:.3e}N")
    print(f"  |vector_sum|={np.linalg.norm(F_total):.3e}N  "
          f"sum_of_magnitudes={mag.sum():.3e}N  "
          f"per-particle min/mean/max={mag.min():.3e}/{mag.mean():.3e}/{mag.max():.3e}N")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--t", type=float, default=2.0)
    ap.add_argument("--cluster", type=int, default=1)
    args = ap.parse_args()
    run(args.t, args.cluster)
