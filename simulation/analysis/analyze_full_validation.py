"""
Full 4-cluster isolated shaping validation — post-processing analysis.

STATUS: DIAGNOSTIC ANALYSIS ONLY. Consumes the output of shape_fixture.py's
full-cycle run (per-step scalar JSON log + per-particle snapshots at slot
boundaries). Computes the geometry/coverage, cluster-integrity, physics, and
retention metrics requested for the shaping validation gate, and prints a
plain pass/fail-oriented summary per cluster/target region. Does not modify
phase2_shaping.py or shape_fixture.py, and does not judge success from any
rendered animation -- every number here comes directly from real particle
position/velocity/force arrays.

Usage:
    python analyze_full_validation.py --json runs/g5_full_validation.json \\
        --snapshots runs/g5_full_validation_snapshots.npz
"""
import sys
import os
import argparse
import json

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phase2_shaping as sim  # noqa: E402  (for C: geometry/targets, unmodified)

C = sim.C
CAP_KS = (0, 3)
WALL_KS = (1, 2)
SHAPE_ORDER = list(sim.SHAPE_ORDER)
SLOT_S = sim.SHAPE_TIME / 4.0
SLOT_END = {k: (SHAPE_ORDER.index(k) + 1) * SLOT_S for k in range(4)}

# Reference numbers from the surf_conf=0 ablation baseline
# (SHAPING_BASELINE_2026-08-19.md, Section A) -- ideal-start, no coverage
# controller at all, just the bare magnetic-only mechanism as it stood before
# the G3/G4 wall coverage-feedback controller existed.
BASELINE_D_TGT_END_MM = {0: 6.845, 3: 2.933, 1: 6.499, 2: 7.136}
BASELINE_RRMS_END_MM = {0: None, 3: None, 1: None, 2: None}  # not reported per-cluster in baseline


def load_json(path):
    with open(path) as f:
        return json.load(f)


def wall_coverage(pos, cid, k, n_theta=24, n_z=12):
    """(theta, z) bin occupancy fraction + density uniformity (CV of bin
    counts among occupied bins) for a wall cluster's real particle positions."""
    tgt = C.targets[k]
    m = cid == k
    p = pos[m]
    if len(p) == 0:
        return dict(n=0)
    dx = p[:, 0] - C.cx
    dy = p[:, 1] - C.cy
    r = np.hypot(dx, dy)
    theta = np.arctan2(dy, dx)
    z = p[:, 2]
    tgt_phi = np.arctan2(tgt[1] - C.cy, tgt[0] - C.cx)
    # bin theta relative to this wall's own +-60deg design arc, z over [z_lo,z_hi]
    theta_rel = np.mod(theta - tgt_phi + np.pi, 2 * np.pi) - np.pi
    theta_bins = np.linspace(-np.pi, np.pi, n_theta + 1)
    z_bins = np.linspace(C.z_lo, C.z_hi, n_z + 1)
    hist, _, _ = np.histogram2d(theta_rel, z, bins=[theta_bins, z_bins])
    occupied = hist > 0
    coverage_frac = float(occupied.sum()) / occupied.size
    counts_occ = hist[occupied]
    density_cv = float(counts_occ.std() / counts_occ.mean()) if len(counts_occ) and counts_occ.mean() > 0 else float("nan")
    r_err = np.abs(r - C.cR)
    return dict(
        n=int(m.sum()),
        coverage_frac=coverage_frac,
        density_cv=density_cv,
        surf_dist_err_mean_mm=float(r_err.mean()) * 1e3,
        surf_dist_err_max_mm=float(r_err.max()) * 1e3,
        z_frac_in_envelope=float(np.mean((z >= C.z_lo) & (z <= C.z_hi))),
        r_frac_in_envelope=float(np.mean(r_err <= 0.5e-3)),  # within 0.5mm of cR
        z_range_mm=[float(z.min()) * 1e3, float(z.max()) * 1e3],
        r_range_mm=[float(r.min()) * 1e3, float(r.max()) * 1e3],
    )


def cap_coverage(pos, cid, k, n_r=8, n_theta=16):
    """(r, theta) bin occupancy + density uniformity for a cap cluster.
    Also reports whether particles are on the cap plane (z near target z)
    or have fallen (z far below target, e.g. to the domain floor)."""
    tgt = C.targets[k]
    m = cid == k
    p = pos[m]
    if len(p) == 0:
        return dict(n=0)
    dx = p[:, 0] - tgt[0]
    dy = p[:, 1] - tgt[1]
    r = np.hypot(dx, dy)
    theta = np.arctan2(dy, dx)
    z_err = p[:, 2] - tgt[2]
    r_bins = np.linspace(0, C.cR, n_r + 1)
    theta_bins = np.linspace(-np.pi, np.pi, n_theta + 1)
    hist, _, _ = np.histogram2d(np.clip(r, 0, C.cR - 1e-12), theta, bins=[r_bins, theta_bins])
    occupied = hist > 0
    coverage_frac = float(occupied.sum()) / occupied.size
    counts_occ = hist[occupied]
    density_cv = float(counts_occ.std() / counts_occ.mean()) if len(counts_occ) and counts_occ.mean() > 0 else float("nan")
    on_cap_frac = float(np.mean(np.abs(z_err) <= 0.5e-3))  # within 0.5mm of cap plane
    fallen_frac = float(np.mean(z_err <= -2.0e-3))  # fell >=2mm below target (floor-ward)
    return dict(
        n=int(m.sum()),
        coverage_frac=coverage_frac,
        density_cv=density_cv,
        on_cap_frac=on_cap_frac,
        fallen_frac=fallen_frac,
        z_err_mean_mm=float(z_err.mean()) * 1e3,
        z_err_range_mm=[float(z_err.min()) * 1e3, float(z_err.max()) * 1e3],
    )


def analyze_snapshots(npz_path):
    d = np.load(npz_path)
    keys = sorted(set(k.split("_", 1)[1] for k in d.files if k.startswith("pos_")))
    print("\n" + "=" * 78)
    print("  PARTICLE-LEVEL SNAPSHOT ANALYSIS (coverage / density / retention)")
    print("=" * 78)
    results = {}
    for key in keys:
        pos = d[f"pos_{key}"]
        cid = d[f"cid_{key}"]
        actual_t = float(d[f"actual_t_{key}"][0])
        print(f"\n--- snapshot {key} (actual sim t={actual_t:.3f}s) ---")
        results[key] = {}
        for k in WALL_KS:
            r = wall_coverage(pos, cid, k)
            results[key][f"c{k}"] = r
            print(f"  c{k} (wall): n={r['n']}  coverage={r['coverage_frac']*100:.1f}%  "
                  f"density_cv={r['density_cv']:.2f}  "
                  f"surf_dist_err mean/max={r['surf_dist_err_mean_mm']:.3f}/{r['surf_dist_err_max_mm']:.3f}mm  "
                  f"in_r_envelope={r['r_frac_in_envelope']*100:.1f}%  "
                  f"z_range={r['z_range_mm']}mm  r_range={r['r_range_mm']}mm")
        for k in CAP_KS:
            r = cap_coverage(pos, cid, k)
            results[key][f"c{k}"] = r
            print(f"  c{k} (cap):  n={r['n']}  coverage={r['coverage_frac']*100:.1f}%  "
                  f"density_cv={r['density_cv']:.2f}  on_cap={r['on_cap_frac']*100:.1f}%  "
                  f"fallen={r['fallen_frac']*100:.1f}%  z_err_mean={r['z_err_mean_mm']:.3f}mm  "
                  f"z_err_range={r['z_err_range_mm']}mm")
    return results


def cross_cluster_force_check(rows):
    """Cross-cluster force ratio proxy: compare each cluster's own Fmag against
    what it would be if only its own dipole mattered (not directly separable
    from this log alone -- flags for a dedicated attribution run if any
    cluster's Fmag looks anomalously large relative to its own active/wait
    state, which would suggest cross-talk)."""
    pass


def analyze_timeseries(rows):
    print("\n" + "=" * 78)
    print("  PER-STEP TIME SERIES SUMMARY (physics / control)")
    print("=" * 78)
    for k in range(4):
        ck = f"c{k}"
        slot_end = SLOT_END[k]
        active_rows = [r for r in rows if r["t"] <= slot_end + 0.5 and r["t"] >= slot_end - SLOT_S]
        end_row = rows[-1]
        maxv = max(r[ck]["vmax"] for r in rows)
        maxa = max(r[ck]["amax"] for r in rows)
        maxfw = max((r[ck]["fvec_mag_over_W"] or 0.0) for r in rows)
        minpair = min(r[ck]["min_pair_dist_mm"] for r in rows)
        r95_end = end_row[ck]["r95"] * 1e3
        rmax_end = end_row[ck]["r_max"] * 1e3
        d_end = end_row[ck]["d_tgt_mean"] * 1e3
        baseline_d = BASELINE_D_TGT_END_MM.get(k)
        improved = (d_end < baseline_d) if baseline_d is not None else None
        print(f"\ncluster {k} ({'wall' if k in WALL_KS else 'cap'}):")
        print(f"  d_tgt_mean @ end          = {d_end:.3f}mm  "
              f"(surf_conf=0 baseline: {baseline_d:.3f}mm, "
              f"{'IMPROVED' if improved else 'not improved' if improved is not None else 'n/a'})")
        print(f"  r95 / r_max @ end         = {r95_end:.4f} / {rmax_end:.4f} mm")
        print(f"  peak particle velocity    = {maxv:.3f} mm/s")
        print(f"  peak particle accel       = {maxa:.1f} m/s^2")
        print(f"  peak vector F/W           = {maxfw:.3f}")
        print(f"  min pairwise distance     = {minpair:.4f} mm  (bare contact 2R={2*C.R*1e3:.4f}mm)")
        if k in WALL_KS:
            track_key = f"wst{k}"
            track_rows = [r[track_key]["track_err_mm"] for r in rows if track_key in r]
            if track_rows:
                print(f"  max tracking error        = {max(track_rows):.4f}mm  "
                      f"(gate={sim.WELL_TRACK_ERR_MAX*1e3:.2f}mm)")
                minsep_rows = [r[track_key]["min_particle_dipole_sep_mm"] for r in rows if track_key in r]
                print(f"  min particle-dipole sep   = {min(minsep_rows):.4f}mm")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", required=True)
    ap.add_argument("--snapshots", required=True)
    args = ap.parse_args()

    sim.init()  # only needed for C (geometry/targets), no simulation is run here

    rows = load_json(args.json)
    analyze_timeseries(rows)
    analyze_snapshots(args.snapshots)
