#!/usr/bin/env python3
"""
reconstruct_run.py — deep post-hoc reconstruction of a phase2_shaping.py run
==============================================================================
Parses every VTU frame from outputs/Phase2/simulation.pvd (real particle
positions/velocities/forces/cluster IDs, ground truth, no assumptions),
replays the REAL PhaseManager state machine against the REAL centroid
trajectory to reconstruct which phase/sub-phase was active at any timestamp,
then calls the REAL update_dipoles() (imported directly from
phase2_shaping.py, not re-implemented) to get the real dipole configuration
at that instant, and finally computes real magnetic forces at real particle
positions from that real dipole state.

This exists to answer "what was actually happening at time t" from data,
not from re-reading the code and guessing.

Usage:
    python analysis/reconstruct_run.py 4.447 4.497 7.097 8.847 11.497 13.247 15.897 17.997 19.848 39.847
"""
import sys, os, re, math, glob
import numpy as np
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = SIM_DIR / "outputs" / "Phase2"
PVD = OUT_DIR / "simulation.pvd"

CLUSTER_NAMES = {0: "Q0/blue(top)", 1: "Q1/yellow(left)", 2: "Q2/orange(right)", 3: "Q3/red(bottom)"}


def parse_pvd():
    txt = PVD.read_text()
    entries = re.findall(r'timestep="([\d.]+)" file="([^"]+)"', txt)
    return [(float(t), OUT_DIR / f) for t, f in entries]


def parse_vtu(path, n_particles=256):
    txt = path.read_text()
    def block(name, n):
        m = re.search(rf'Name="{name}"[^>]*>\n(.*?)\n</DataArray>', txt, re.S)
        vals = m.group(1).split()
        return vals[:n]
    pts_block = re.search(r'<DataArray type="Float64" NumberOfComponents="3"[^>]*>\n(.*?)\n</DataArray>', txt, re.S).group(1).split('\n')
    pos = np.array([[float(x) for x in row.split()] for row in pts_block[:n_particles]])
    cl = np.array([int(x) for x in block("ClusterID", n_particles)])
    fm = np.array([float(x) for x in block("Fmag", n_particles)])
    vm = np.array([float(x) for x in block("Vmag", n_particles)])
    nc = np.array([int(x) for x in block("Ncontact", n_particles)])
    return pos, cl, fm, vm, nc


def load_all_frames():
    entries = parse_pvd()
    frames = []
    for t, path in entries:
        pos, cl, fm, vm, nc = parse_vtu(path)
        frames.append(dict(t=t, pos=pos, cl=cl, fm=fm, vm=vm, nc=nc, file=path.name))
    return frames


def centroids_per_cluster(pos, cl):
    out = {}
    for k in range(4):
        mask = cl == k
        out[k] = pos[mask].mean(axis=0) if np.any(mask) else np.array([np.nan]*3)
    return out


def nearest_frame(frames, t_query):
    idx = min(range(len(frames)), key=lambda i: abs(frames[i]['t'] - t_query))
    return frames[idx]


def main():
    query_times = [float(x) for x in sys.argv[1:]]
    if not query_times:
        query_times = [4.447, 4.497, 7.097, 8.847, 11.497, 13.247, 15.897, 17.997, 19.848, 39.847]

    print(f"Loading {PVD}...")
    frames = load_all_frames()
    print(f"Loaded {len(frames)} frames, t in [{frames[0]['t']:.3f}, {frames[-1]['t']:.3f}]")

    # ── Import the REAL simulation module for its REAL control logic ──────
    sys.path.insert(0, str(SIM_DIR))
    import importlib
    os.chdir(SIM_DIR)
    import phase2_shaping as sim

    pm = sim.PhaseManager()

    # Replay pm.update() across every real output frame using REAL centroids
    # (best resolution available post-hoc: 50ms output cadence; the real run
    # called pm.update() at ~6ms batch granularity during transport, so
    # arrived_t/handoff_t timing reconstructed here can be off by up to ~50ms
    # relative to the true run -- noted wherever it matters below).
    timeline = []  # (t, pm_state, pm_dict, centroids)
    for fr in frames:
        cents = centroids_per_cluster(fr['pos'], fr['cl'])
        # Approximate per-cluster velocity MAGNITUDE from the real per-particle
        # Vmag column (VTU stores speed, not the velocity vector, so this is
        # an approximation of the true |mean velocity| -- reasonable for
        # replaying the Stage A-2 arrival gate, which only uses the norm).
        vels = {}
        for kk in range(4):
            mask = fr['cl'] == kk
            speed_mean = float(fr['vm'][mask].mean()) if np.any(mask) else 0.0
            vels[kk] = np.array([speed_mean, 0.0, 0.0])
        pm.update(fr['t'], cents, vels)
        timeline.append((fr['t'], pm.state, pm.to_dict().copy(), cents))

    # ── Stage A-3 (F17) LIFTOFF/LIFT/CRUISE diagnostic, per cluster ────────
    # Replays the REAL update_dipoles() at every real frame (not just the
    # query timestamps) to recover the real commanded dipole position, so
    # dipole-cluster separation and force-vs-weight can be checked across
    # the WHOLE transport, not just hand-picked instants.
    print("\n" + "="*100)
    print("STAGE A-3 (F17) LIFTOFF / LIFT / CRUISE DIAGNOSTIC (per cluster, from real VTU data)")
    print("="*100)
    W = sim.C.mp * sim.C.g
    for k in range(4):
        rows = [(fr, tl) for fr, tl in zip(frames, timeline) if tl[1] == f"transport_{k}"]
        if not rows:
            print(f"  Q{k}: no transport_{k} frames found — skipped")
            continue
        t_start = rows[0][0]['t']
        z0 = rows[0][1][3][k][2]
        clearances, seps, speeds_z = [], [], []
        liftoff_t = None
        prev_t, prev_z = None, None
        for fr, (t, state, pmd, cents) in rows:
            z = cents[k][2]
            clearance = z - sim.C.R
            clearances.append(clearance)
            if liftoff_t is None and (z - z0) >= sim.Z_LIFTOFF_CONFIRM:
                liftoff_t = t - t_start
            if prev_t is not None and t > prev_t:
                speeds_z.append((z - prev_z) / (t - prev_t))
            prev_t, prev_z = t, z

            pm_snap = sim.PhaseManager(); pm_snap.from_dict(pmd)
            sim.update_dipoles(t, pm_snap, cents)
            dip_idx = sim.IDX_CLUSTER_DIP[k]
            dip_pos = sim.dip_pos_np[dip_idx].copy()
            sep = float(np.linalg.norm(dip_pos - cents[k]))
            seps.append(sep)

        last_fr, last_tl = rows[-1]
        d_final = float(np.linalg.norm(last_tl[3][k] - sim.C.targets[k]))
        v_final = float(last_fr['vm'][last_fr['cl'] == k].mean()) if np.any(last_fr['cl']==k) else float('nan')
        clearances = np.array(clearances); seps = np.array(seps)
        speeds_z = np.array(speeds_z) if speeds_z else np.array([0.0])
        print(f"\n  Q{k}: transport_{k} spans t=[{t_start:.3f}, {last_fr['t']:.3f}]s "
              f"({last_fr['t']-t_start:.3f}s)")
        print(f"    liftoff confirmed (z rose >= {sim.Z_LIFTOFF_CONFIRM*1e3:.4f}mm): "
              f"{'at t+%.3fs' % liftoff_t if liftoff_t is not None else 'NEVER within this transport'}")
        print(f"    floor clearance: min={clearances.min()*1e3:.4f}mm  max={clearances.max()*1e3:.4f}mm  "
              f"(LIFT_CLEARANCE target={sim.LIFT_CLEARANCE*1e3:.2f}mm)")
        print(f"    vertical speed (finite-diff, 50ms cadence): max={speeds_z.max()*1e3:.2f}mm/s  "
              f"min={speeds_z.min()*1e3:.2f}mm/s")
        print(f"    dipole-cluster separation: min={seps.min()*1e3:.3f}mm  max={seps.max()*1e3:.3f}mm  "
              f"mean={seps.mean()*1e3:.3f}mm  (design bound: LIFT/BRAKE/SETTLE=0.5mm, CRUISE cap="
              f"{sim.MAX_CRUISE_STANDOFF*1e3:.2f}mm)")
        print(f"    at end of transport_{k}: d_to_target={d_final*1e3:.4f}mm "
              f"(EPS_X={sim.EPS_X*1e3:.3f}mm)  v~{v_final*1e3:.2f}mm/s (EPS_V={sim.EPS_V*1e3:.1f}mm/s)  "
              f"arrived_t={'set' if last_tl[2]['arrived_t'] is not None else 'None (STALL path)'}")

    # ── Full-history transport-speed regression scan (Stage A-2, F15/F16) ──
    print("\n" + "="*100)
    print("TRANSPORT SPEED SCAN (per state, from real VTU Vmag data)")
    print("="*100)
    from collections import defaultdict
    speed_by_state = defaultdict(list)
    for fr, (t, state, d, cents) in zip(frames, timeline):
        if state.startswith("transport_") or state.startswith("interlude_"):
            speed_by_state[state].append(fr['vm'].max())
    V_CEIL_MIRROR = 8.0e-3
    ceiling = 5.0 * V_CEIL_MIRROR
    for state in sorted(speed_by_state):
        speeds = np.array(speed_by_state[state])
        flag = "OK" if speeds.max() < ceiling else "!! EXCEEDS CEILING !!"
        print(f"  {state:16s}  n_frames={len(speeds):4d}  max_speed={speeds.max()*1e3:9.2f}mm/s  "
              f"mean_of_max={speeds.mean()*1e3:7.2f}mm/s  ceiling={ceiling*1e3:.0f}mm/s  [{flag}]")

    print("\n" + "="*100)
    print("PHASE TIMELINE (state transitions only)")
    print("="*100)
    last_state = None
    for t, state, d, cents in timeline:
        if state != last_state:
            print(f"  t={t:7.3f}s  -> state={state:16s}  completed={sorted(d['completed'])}")
            last_state = state

    print("\n" + "="*100)
    print("PER-CHECKPOINT RECONSTRUCTION")
    print("="*100)

    for tq in query_times:
        fr = nearest_frame(frames, tq)
        t = fr['t']
        # Find the pm state as of this frame from the replayed timeline
        idx = min(range(len(timeline)), key=lambda i: abs(timeline[i][0] - t))
        _, state, pmd, cents = timeline[idx]

        # Rebuild a PhaseManager snapshot matching this instant so we can
        # call the REAL update_dipoles() with the REAL state.
        pm_snap = sim.PhaseManager()
        pm_snap.from_dict(pmd)

        # Call the REAL dipole control logic.
        sim.update_dipoles(t, pm_snap, cents)
        dip_p = sim.dip_pos_np.copy()
        dip_m = sim.dip_mom_np.copy()
        dip_s = sim.dip_str_np.copy()

        print(f"\n{'-'*100}")
        print(f"  QUERY t={tq:.3f}s  ->  nearest real frame t={t:.4f}s ({fr['file']})")
        print(f"{'-'*100}")
        print(f"  Phase state (reconstructed): {state}")
        print(f"  phase_start_t={pmd['phase_start_t']:.3f}  arrived_t={pmd['arrived_t']}  "
              f"handoff_t={pmd['handoff_t']}  completed={sorted(pmd['completed'])}")

        active_dips = np.where(dip_s > 1e-6)[0]
        print(f"  Active dipoles ({len(active_dips)}): ", end="")
        for di in active_dips:
            print(f"\n    dip[{di:2d}] pos=({dip_p[di,0]*1e3:6.2f},{dip_p[di,1]*1e3:6.2f},{dip_p[di,2]*1e3:6.2f})mm "
                  f"m=({dip_m[di,0]:.2e},{dip_m[di,1]:.2e},{dip_m[di,2]:.2e}) s={dip_s[di]:.3f} "
                  f"|m*s|={np.linalg.norm(dip_m[di])*dip_s[di]:.3e} A.m2", end="")
        print()

        # Real per-cluster centroid, velocity, force (ground truth from VTU)
        print(f"  Real cluster state (from VTU, ground truth):")
        R = sim.C.R; MP = sim.C.mp; G = sim.C.g; W = MP*G
        for k in range(4):
            mask = fr['cl'] == k
            n = int(mask.sum())
            if n == 0:
                print(f"    {CLUSTER_NAMES[k]:16s} n=0 (no particles with this cluster_id!)")
                continue
            c = cents[k]
            tgt = sim.C.targets[k]
            d_to_tgt = np.linalg.norm(c - tgt) * 1e3
            fm_mean = fr['fm'][mask].mean(); fm_max = fr['fm'][mask].max()
            vm_mean = fr['vm'][mask].mean(); vm_max = fr['vm'][mask].max()
            nc_mean = fr['nc'][mask].mean()
            print(f"    {CLUSTER_NAMES[k]:16s} n={n:3d} centroid=({c[0]*1e3:6.2f},{c[1]*1e3:6.2f},{c[2]*1e3:6.2f})mm "
                  f"d_to_tgt={d_to_tgt:7.2f}mm  |Fmag|/W: mean={fm_mean/W:8.1f} max={fm_max/W:8.1f}  "
                  f"|v|: mean={vm_mean*1e3:7.2f} max={vm_max*1e3:7.2f} mm/s  ncontact_mean={nc_mean:.1f}")

        # Independent recompute of magnetic force at each cluster's centroid
        # using the reconstructed dipole state, as a cross-check against the
        # VTU's own Fmag column (computed by the real kernel at the time).
        def B_field(r):
            Bv = np.zeros(3)
            for kk in range(len(dip_s)):
                if dip_s[kk] > 1e-15:
                    mv = dip_m[kk]*dip_s[kk]
                    rv = r - dip_p[kk]
                    r2 = rv@rv
                    if r2 > 1e-22:
                        rmag = math.sqrt(r2); rhat = rv/rmag
                        Bv += (sim._MU0_4PI/r2/rmag) * (3*(mv@rhat)*rhat - mv)
            return Bv
        def gradB2_fd(r, h=1e-8):
            g = np.zeros(3)
            for a in range(3):
                e = np.zeros(3); e[a] = h
                Bp = B_field(r+e); Bm = B_field(r-e)
                g[a] = (Bp@Bp - Bm@Bm)/(2*h)
            return g
        print(f"  Cross-check: magnetic force AT CENTROID from reconstructed dipole state:")
        for k in range(4):
            if int((fr['cl']==k).sum()) == 0: continue
            c = cents[k]
            g = gradB2_fd(c)
            Bmag = np.linalg.norm(B_field(c))
            ce = sim.C.chi / math.cosh(min(sim.C.chi*Bmag/(sim.MU0*sim.C.Msat),20.0))**2
            Fm = (sim.C.Vp*ce/(2*sim.MU0)) * g
            print(f"    {CLUSTER_NAMES[k]:16s} F_recon=({Fm[0]/W:8.1f},{Fm[1]/W:8.1f},{Fm[2]/W:8.1f})xW  "
                  f"|F_recon|/W={np.linalg.norm(Fm)/W:8.1f}  (VTU mean |Fmag|/W above should roughly match)")

    print("\nDone.")


if __name__ == "__main__":
    main()
