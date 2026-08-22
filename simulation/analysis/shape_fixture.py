"""
Isolated shaping diagnostic fixture — REGO.

STATUS: DIAGNOSTIC MODE ONLY. This is NOT a transport result and NOT part of
the production pipeline. `phase2_shaping.py`'s `main()` and its command-line
interface are completely untouched by this file.

What this does: initializes four real 64-particle clusters directly at the
intended shaping-start geometry (a tight, loosely-packed blob of real
particles centered on each cluster's real target position, `C.targets[k]`,
matching the kind of stochastic loose-pile initial condition
`phase2_shaping.init()` already uses for Phase 1 — not a hand-picked shape),
then runs the EXACT SAME physics kernels phase2_shaping.py uses in
production (`build_grid`, `compute_forces`, `integrate`, `update_dipoles`,
`substep_batch` — imported directly, not reimplemented) with the phase
manager's state forced to "shape" from t=0.

This changes ONLY the initial condition and starting phase. It does not:
  - disable gravity, collisions, or the real paramagnetic force law;
  - filter magnetic forces by cluster_id (compute_forces() never did to
    begin with — verified in SHAPING_HOLDING_AUDIT_2026-08-18.md);
  - add any hidden force.

The one deliberate manipulation this script offers is `--surf-conf-off`,
which overrides the module-level `surf_conf_enabled` Taichi field back to 0
immediately after each `update_dipoles()` call (which would otherwise set it
to 1 whenever `pm.state=="shape"`). This performs the surf_conf=0 ablation
requested to establish the true magnetic-only baseline, without touching
`phase2_shaping.py` itself.

Usage:
    python shape_fixture.py --surf-conf-off --duration 5.0
    python shape_fixture.py --duration 5.0   (surf_conf ON — direct comparison)
"""
import sys
import os
import argparse
import json

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phase2_shaping as sim  # noqa: E402  (real kernels, imported not reimplemented)


def pack_cluster(center, n, R, seed):
    """Tight, loosely non-overlapping real-particle pack of n spheres of
    radius R around `center`. Coarse grid + Gaussian jitter — the same
    character of stochastic loose-pile initial condition phase2_shaping's
    own init() uses for Phase 1, just scaled down to fit near one target.
    Any residual overlap is resolved by the real contact kernel
    (contact_pp, unmodified) during the first physics steps — not by this
    script."""
    rng = np.random.RandomState(seed)
    side = int(np.ceil(n ** (1.0 / 3.0)))
    sp = 2.3 * R  # center-to-center spacing: small real gap over bare contact (2R)
    pts = []
    for iz in range(side):
        for iy in range(side):
            for ix in range(side):
                if len(pts) >= n:
                    break
                jitter = rng.normal(0, 0.15 * R, size=3)
                offset = (np.array([ix, iy, iz], dtype=np.float64) * sp
                          - sp * (side - 1) / 2.0)
                pts.append(center + offset + jitter)
    return np.array(pts[:n], dtype=np.float64)


def build_fixture(seed=1234, phase_start_t=0.0):
    sim.init()  # real init(): allocates/zeros all Taichi fields, dipole arrays, etc.

    N = sim.C.N
    per_cluster = N // 4
    R = sim.C.R

    pos_np = np.zeros((N, 3), dtype=np.float64)
    cid_np = np.zeros(N, dtype=np.int32)
    idx = 0
    for k in range(4):
        center = sim.C.targets[k].copy()
        cluster_pts = pack_cluster(center, per_cluster, R, seed + k)
        pos_np[idx:idx + per_cluster] = cluster_pts
        cid_np[idx:idx + per_cluster] = k
        idx += per_cluster

    sim.pos.from_numpy(pos_np)
    sim.vel.from_numpy(np.zeros((N, 3), dtype=np.float64))
    sim.cluster_id.from_numpy(cid_np)
    sim.fixed_color.from_numpy(cid_np)
    sim.colors_fixed = True

    pm = sim.PhaseManager()
    pm.state = "shape"
    pm.completed = {0, 1, 2, 3}
    pm.phase_start_t = -phase_start_t  # so shape_elapsed = t - phase_start_t = phase_start_t at t=0
    return pm


def run(duration, record_dt, surf_conf_off, seed=1234, out_json=None, verbose=True,
        phase_start_t=0.0, snapshot_times=None, snapshot_out=None):
    """snapshot_times: optional list of sim times at which to dump full per-particle
    (position, velocity, cluster_id) arrays into snapshot_out (.npz) — needed for
    coverage/density/retention analysis that can't be done from per-step scalar summaries
    alone, without bloating the main per-step JSON log with full particle data every step."""
    pm = build_fixture(seed, phase_start_t=phase_start_t)
    C = sim.C
    dt = C.dt
    t = 0.0
    record = []
    next_record_t = 0.0
    batch = max(1, int(round(0.001 / dt)))  # ~1ms physics batches between recordings
    snap_times_sorted = sorted(snapshot_times) if snapshot_times else []
    snap_idx = 0
    snapshots = {}

    while t < duration:
        p_np = sim.pos.to_numpy()
        v_np = sim.vel.to_numpy()
        cl_np = sim.cluster_id.to_numpy()
        centroids = {k: sim.get_cluster_centroid_np(p_np, cl_np, k) for k in range(4)}
        velocities = {k: sim.get_cluster_velocity_np(v_np, cl_np, k) for k in range(4)}

        sim.update_dipoles(t, pm, centroids, velocities)
        if surf_conf_off:
            sim.surf_conf_enabled[None] = 0  # ablation override, applied AFTER update_dipoles

        sim.substep_batch(batch)
        t += batch * dt

        if t >= next_record_t:
            fm_np = sim.fmag.to_numpy()
            frc_np = sim.frc.to_numpy()
            dip_p_np = sim.dip_p.to_numpy()
            row = {"t": t}
            for wk in (1, 2):
                wst = sim._wall_well_state.get(wk)
                if wst is None:
                    continue
                scan_idxk = sim.SHAPE_RING_MAP[wk][0]
                aimk = dip_p_np[scan_idxk]
                mk = cl_np == wk
                cpk = p_np[mk]
                sepk = np.linalg.norm(cpk - aimk, axis=1)
                row[f"wst{wk}"] = dict(
                    phi_frac=wst["phi_frac"], z_frac=wst["z_frac"],
                    direction=wst["direction"], z_direction=wst.get("z_direction"),
                    aim=aimk.tolist(), centroid=centroids[wk].tolist(),
                    track_err_mm=float(np.linalg.norm(centroids[wk] - aimk)) * 1e3,
                    min_particle_dipole_sep_mm=float(sepk.min()) * 1e3,
                )
            for k in range(4):
                m = cl_np == k
                cp = p_np[m]
                cv = v_np[m]
                cf = frc_np[m]
                cfm = fm_np[m]
                tgt = C.targets[k]
                d = np.linalg.norm(cp - tgt, axis=1)
                centroid = cp.mean(axis=0)
                r_all = np.linalg.norm(cp - centroid, axis=1)
                r_rms = float(np.sqrt(np.mean(r_all ** 2)))
                r95 = float(np.percentile(r_all, 95))
                r_max = float(np.max(r_all))
                vnorm = np.linalg.norm(cv, axis=1)
                vmag = float(vnorm.mean())
                vmax = float(vnorm.max())
                amax = float(np.linalg.norm(cf, axis=1).max() / C.mp)  # peak accel, F=ma
                # real vector sum of the magnetic force on this cluster (not sum of magnitudes)
                fvec_sum = cfm.sum(axis=0)
                fmag_mean = float(np.linalg.norm(cfm, axis=1).mean())
                W = m.sum() * C.mp * C.g
                # min pairwise separation within the cluster (cheap: n<=64, n^2/2 pairs)
                if len(cp) > 1:
                    diffs = cp[:, None, :] - cp[None, :, :]
                    dmat = np.linalg.norm(diffs, axis=2)
                    np.fill_diagonal(dmat, np.inf)
                    min_pair_dist = float(dmat.min())
                else:
                    min_pair_dist = float("nan")
                row[f"c{k}"] = dict(
                    d_tgt_mean=float(d.mean()), d_tgt_max=float(d.max()),
                    r_rms=r_rms, r95=r95, r_max=r_max, vmag=vmag, vmax=vmax,
                    amax=amax, fmag_mean=fmag_mean,
                    fvec_sum_over_W=(fvec_sum / W).tolist() if W > 0 else None,
                    fvec_mag_over_W=float(np.linalg.norm(fvec_sum) / W) if W > 0 else None,
                    min_pair_dist_mm=min_pair_dist * 1e3,
                    n=int(m.sum()), centroid=centroid.tolist(),
                )
            record.append(row)
            if verbose and (len(record) % 10 == 0 or t >= duration):
                print(f"  t={t:6.3f}s  " + "  ".join(
                    f"c{k}:d={row[f'c{k}']['d_tgt_mean']*1e3:5.2f}mm "
                    f"v={row[f'c{k}']['vmag']*1e3:6.2f}mm/s"
                    for k in range(4)))
            next_record_t += record_dt

        while snap_idx < len(snap_times_sorted) and t >= snap_times_sorted[snap_idx]:
            key = f"t{snap_times_sorted[snap_idx]:.3f}"
            snapshots[f"pos_{key}"] = sim.pos.to_numpy()
            snapshots[f"vel_{key}"] = sim.vel.to_numpy()
            snapshots[f"cid_{key}"] = sim.cluster_id.to_numpy()
            snapshots[f"actual_t_{key}"] = np.array([t])
            snap_idx += 1

    if out_json:
        with open(out_json, "w") as f:
            json.dump(record, f, indent=1)
    if snapshot_out and snapshots:
        np.savez(snapshot_out, **snapshots)
    return record


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surf-conf-off", action="store_true",
                     help="Ablation: force surf_conf_enabled=0 every step (true magnetic-only baseline).")
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--record-dt", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--phase-start-t", type=float, default=0.0,
                     help="shape_elapsed value at t=0 (diagnostic time-skip to reach a "
                          "later shaping slot quickly, e.g. 9.5 to reach cluster 1's "
                          "active slot almost immediately instead of waiting ~10s of "
                          "sim time). Does not change any physics, only which point in "
                          "the pre-existing schedule pm reports at t=0.")
    ap.add_argument("--snapshot-times", type=str, default=None,
                     help="Comma-separated sim times at which to dump full per-particle "
                          "pos/vel/cluster_id arrays (e.g. '5,10,15,20,20.5') for "
                          "coverage/density/retention analysis. Requires --snapshot-out.")
    ap.add_argument("--snapshot-out", type=str, default=None)
    args = ap.parse_args()

    print("=" * 72)
    print("  SHAPE FIXTURE — DIAGNOSTIC MODE ONLY, NOT A TRANSPORT RESULT")
    print(f"  surf_conf_off={args.surf_conf_off}  duration={args.duration}s  seed={args.seed}"
          f"  phase_start_t={args.phase_start_t}")
    print("=" * 72)
    snap_times = ([float(x) for x in args.snapshot_times.split(",")]
                  if args.snapshot_times else None)
    rec = run(args.duration, args.record_dt, args.surf_conf_off, args.seed, args.out,
              phase_start_t=args.phase_start_t,
              snapshot_times=snap_times, snapshot_out=args.snapshot_out)
    last = rec[-1]
    print(f"\nFinal state at t={last['t']:.3f}s:")
    for k in range(4):
        r = last[f"c{k}"]
        print(f"  c{k}: d_tgt_mean={r['d_tgt_mean']*1e3:6.3f}mm  d_tgt_max={r['d_tgt_max']*1e3:6.3f}mm  "
              f"r_rms={r['r_rms']*1e3:6.4f}mm  r_max={r['r_max']*1e3:6.4f}mm  "
              f"v={r['vmag']*1e3:7.3f}mm/s  Fmag={r['fmag_mean']:.3e}N  n={r['n']}")
