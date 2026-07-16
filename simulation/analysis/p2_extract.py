#!/usr/bin/env python3
"""
rego_extract.py — REGO Simulation Data Extractor
=================================================
Reads real output files produced by phase2_clean_saved.py and extracts
all metrics. This is the data bridge between the simulation and the
metrics / graphing / BO pipeline.

Outputs:
  rego_sim_data.json   — all extracted metrics, ready for rego_metrics.py,
                         rego_graphs.py, and rego_bayesopt.py

Data sources parsed (in order of priority):
  1. outputs/phase2_checkpoint.pkl   — latest auto-checkpoint (full state)
  2. outputs/shape_checkpoint.pkl    — shape-phase-start checkpoint
  3. outputs/Phase2_v4_Fixed/diagnostics.png  — (presence check only)
  4. Simulation stdout captured to   outputs/sim_log.txt (if you redirect)
  5. Fallback: analytical estimates  (same as before, clearly flagged)

Usage:
python phase2_clean_saved.py --no-checkpoint | tee outputs/sim_log.txt
python p2_extract.py --dir outputs/
python p2_metrics.py --sim-data rego_sim_data.json
python p2_graphs.py --sim-data rego_sim_data.json
python p2_bo.py --sim-data rego_sim_data.json --n-iter 80
"""

import pickle, json, math, re, sys, argparse
import numpy as np
from pathlib import Path

# ── Mirror constants from phase2 (no taichi import needed) ────────────────
MU0      = 4.0 * math.pi * 1e-7
PI       = math.pi
_MU0_4PI = MU0 / (4.0 * PI)

# Particle & domain config (must match phase2_clean_saved.py class C)
N_PARTICLES = 256
R_PARTICLE  = 3e-5
RHO         = 7800.0
VP          = (4/3)*PI*R_PARTICLE**3
MP          = VP * RHO
G_LUNAR     = 1.62

TARGETS = np.array([
    [5.0e-3, 5.0e-3, 7.2e-3],
    [5.0e-3 - 0.010/6 - 0.2e-3, 5.0e-3, 5.0e-3],
    [5.0e-3 + 0.010/6 + 0.2e-3, 5.0e-3, 5.0e-3],
    [5.0e-3, 5.0e-3, 2.8e-3],
], dtype=np.float64)

COIL_N_TURNS = 100
COIL_AREA    = 4e-6
COIL_R_OHM   = 0.05

# ═══════════════════════════════════════════════════════════════════════════
# CHECKPOINT PARSER
# ═══════════════════════════════════════════════════════════════════════════

def load_checkpoint_file(path: Path) -> dict:
    with open(path, 'rb') as f:
        return pickle.load(f)


def extract_from_checkpoint(ckpt: dict) -> dict:
    """
    Extract all metrics from a phase2 checkpoint dictionary.
    The checkpoint contains full particle state + history arrays.
    """
    out = {"source": "checkpoint", "checkpoint_label": ckpt.get("label", "?"),
           "sim_version": ckpt.get("version", "?"), "t": ckpt["t"],
           "step": ckpt["step"]}

    pos_np  = ckpt["pos"]          # (N,3) float64 particle positions
    vel_np  = ckpt["vel"]          # (N,3) float64 particle velocities
    cl_np   = ckpt["cluster_id"]   # (N,)  int32   cluster assignments
    nc_np   = ckpt.get("ncontact", np.zeros(N_PARTICLES, dtype=np.int32))

    hist_t  = np.array(ckpt.get("hist_t",  []))
    hist_ke = np.array(ckpt.get("hist_ke", []))
    hist_fm = np.array(ckpt.get("hist_fm", []))
    hist_sp = np.array(ckpt.get("hist_sp", []))

    pm_dict = ckpt["phase_manager"]
    out["phase"] = pm_dict["state"]
    out["completed_clusters"] = list(pm_dict.get("completed", []))

    # ── Kinetic energy history ──────────────────────────────────────────────
    out["hist_t"]  = hist_t.tolist()
    out["hist_ke"] = hist_ke.tolist()
    out["hist_fm"] = hist_fm.tolist()
    out["hist_sp"] = hist_sp.tolist()

    # Final KE, max force
    out["final_KE_J"]   = float(0.5 * MP * np.sum(np.sum(vel_np**2, axis=1)))
    out["final_KE_per_particle_J"] = out["final_KE_J"] / max(N_PARTICLES, 1)
    W = MP * G_LUNAR
    fm_np = np.array(ckpt.get("hist_fm", [0]))
    out["max_Fm_over_W"] = float(np.max(fm_np) / W) if len(fm_np) > 0 else 0.0
    out["final_avg_speed_mm_s"] = float(np.mean(np.linalg.norm(vel_np, axis=1)) * 1e3)

    # ── Cluster centroids & shape accuracy ────────────────────────────────
    centroids  = []
    spreads    = []
    distances  = []
    total_sq   = 0.0
    for k in range(4):
        mask = cl_np == k
        n    = int(mask.sum())
        if n > 0:
            pp   = pos_np[mask]
            cen  = pp.mean(axis=0)
            sp   = float(np.sqrt(np.mean(np.sum((pp - cen)**2, axis=1)))) * 1e3
        else:
            cen = TARGETS[k].copy()
            sp  = 0.0
        dist = float(np.linalg.norm(cen - TARGETS[k])) * 1e3
        centroids.append(cen.tolist())
        spreads.append(sp)
        distances.append(dist)
        total_sq += dist**2

    out["cluster_centroids_mm"] = centroids
    out["cluster_spreads_mm"]   = spreads
    out["cluster_distances_mm"] = distances
    out["rms_distance_mm"]      = float(math.sqrt(total_sq / 4))
    out["max_distance_mm"]      = float(max(distances))
    out["all_within_1mm"]       = all(d < 1.0 for d in distances)

    # ── Cylinder conformity ────────────────────────────────────────────────
    cx = cy = 5e-3; cR = 0.010/6; cH = 4e-3
    cz = 5e-3; z_lo = cz - cH/2; z_hi = cz + cH/2
    conformity = {}
    roles = ["top_cap", "left_wall", "right_wall", "bottom_cap"]
    for k in range(4):
        mask = cl_np == k
        if not np.any(mask):
            conformity[roles[k]] = {}
            continue
        pp = pos_np[mask]
        r_from_axis = np.sqrt((pp[:,0]-cx)**2 + (pp[:,1]-cy)**2)
        z_vals = pp[:,2]
        in_z   = int(np.sum((z_vals >= z_lo - 2*R_PARTICLE) &
                             (z_vals <= z_hi + 2*R_PARTICLE)))
        on_wall = int(np.sum((np.abs(r_from_axis - cR) < 5*R_PARTICLE) &
                              (z_vals >= z_lo) & (z_vals <= z_hi)))
        on_cap  = int(np.sum((r_from_axis < cR + 3*R_PARTICLE) &
                              ((np.abs(z_vals - z_lo) < 5*R_PARTICLE) |
                               (np.abs(z_vals - z_hi) < 5*R_PARTICLE))))
        n_k = int(np.sum(mask))
        conformity[roles[k]] = {
            "n_particles": n_k,
            "in_z_range":  in_z,
            "on_wall":     on_wall,
            "on_cap":      on_cap,
            "r_mean_mm":   float(np.mean(r_from_axis) * 1e3),
            "z_mean_mm":   float(np.mean(z_vals) * 1e3),
            "conformity_frac": float((on_wall + on_cap) / max(n_k, 1)),
        }
    out["cylinder_conformity"] = conformity
    out["mean_conformity_frac"] = float(np.mean(
        [v["conformity_frac"] for v in conformity.values() if "conformity_frac" in v]))

    # ── Contact statistics ─────────────────────────────────────────────────
    out["mean_contacts_per_particle"] = float(nc_np.mean())
    out["max_contacts_per_particle"]  = int(nc_np.max())
    out["particles_with_contacts"]    = int((nc_np > 0).sum())

    # ── Dipole state ───────────────────────────────────────────────────────
    dip_str = ckpt.get("dip_str_np", np.zeros(36))
    out["n_active_dipoles"]  = int((dip_str > 0.01).sum())
    out["dip_moments"]       = ckpt.get("dip_mom_np", np.zeros((36,3))).tolist()
    out["dip_strengths"]     = dip_str.tolist()

    # Active dipole moments (for energy calculation)
    dip_mom = ckpt.get("dip_mom_np", np.zeros((36,3)))
    active_mask = dip_str > 0.01
    if active_mask.any():
        mags = np.linalg.norm(dip_mom[active_mask] * dip_str[active_mask, None], axis=1)
        out["mean_active_moment"] = float(mags.mean())
        out["max_active_moment"]  = float(mags.max())
    else:
        out["mean_active_moment"] = 0.0
        out["max_active_moment"]  = 0.0

    # Simulation real-time elapsed (estimated from step count and dt)
    dt_sim = 8e-6
    out["sim_time_s"]   = float(ckpt["step"] * dt_sim)
    out["wall_time_s"]  = None   # only available from log

    return out


# ═══════════════════════════════════════════════════════════════════════════
# LOG FILE PARSER
# ═══════════════════════════════════════════════════════════════════════════

def parse_log_file(log_path: Path) -> dict:
    """
    Parse the terminal output of phase2_clean_saved.py captured to a file.
    Extracts: total_energy_J, avg_power_W, wall_time, final cluster positions.
    """
    text = log_path.read_text(errors="replace")
    result = {}

    # Total energy
    m = re.search(r"Total energy:\s*([\d.]+)\s*J", text)
    if m:
        result["total_energy_J_log"] = float(m.group(1))

    # Average power
    m = re.search(r"Average power:\s*([\d.]+)\s*W", text)
    if m:
        result["avg_power_W_log"] = float(m.group(1))

    # Wall clock time (look for "X.Xs wall clock" or "total = X.Xs")
    m = re.search(r"Sim time:\s*([\d.]+)s wall clock", text)
    if m:
        result["wall_time_s"] = float(m.group(1))

    # Final cluster positions from the FINAL CLUSTER POSITIONS block
    # Format: Q0: 256 particles  pos=(5.00,5.00,7.20)mm  tgt=(5.0,5.0,7.2)mm  d=0.05mm
    cluster_data = {}
    for line in text.splitlines():
        m = re.search(r"Q(\d):\s*(\d+)\s*particles\s+pos=\(([\d.,-]+)\)mm\s+"
                      r"tgt=\(([\d.,-]+)\)mm\s+d=([\d.]+)mm", line)
        if m:
            k = int(m.group(1))
            n = int(m.group(2))
            pos_vals = [float(x) for x in m.group(3).split(",")]
            tgt_vals = [float(x) for x in m.group(4).split(",")]
            d = float(m.group(5))
            cluster_data[k] = {"n": n, "pos_mm": pos_vals,
                                "tgt_mm": tgt_vals, "dist_mm": d}
    if cluster_data:
        result["cluster_data_log"] = cluster_data
        dists = [v["dist_mm"] for v in cluster_data.values()]
        result["rms_distance_mm_log"] = float(math.sqrt(sum(d**2 for d in dists)/len(dists)))

    # Energy budget pass/fail
    result["lunar_budget_pass"] = "PASS" in text and "Lunar budget" in text

    # Chi scaling used
    m = re.search(r"chi_scale=([\d.e+-]+)", text)
    if m:
        result["chi_scale_used"] = float(m.group(1))

    return result


# ═══════════════════════════════════════════════════════════════════════════
# ENERGY COMPUTATION FROM REAL CHECKPOINT DATA
# ═══════════════════════════════════════════════════════════════════════════

def compute_energy_from_checkpoint(ckpt: dict, sim_data: dict) -> dict:
    """
    Compute energy metrics using actual dipole moments from the checkpoint.
    This is more accurate than the analytical estimate because it uses
    the real moment magnitudes that were active during the simulation.
    """
    dip_mom = np.array(ckpt.get("dip_mom_np", np.zeros((36, 3))))
    dip_str = np.array(ckpt.get("dip_str_np", np.zeros(36)))

    # Compute power for each active dipole
    total_power_W = 0.0
    for k in range(len(dip_str)):
        s = dip_str[k]
        if s > 0.01:
            m_mag = float(np.linalg.norm(dip_mom[k])) * s
            if m_mag > 0:
                I = m_mag / (COIL_N_TURNS * COIL_AREA)
                total_power_W += I**2 * COIL_R_OHM

    t_sim = sim_data.get("sim_time_s", 0.0)

    # Instantaneous energy at this checkpoint snapshot
    E_instant_J = total_power_W * 8e-6   # one timestep worth

    # For full run: use history-informed estimate
    # We know phase timings from phase manager state; use the actual moments
    # as representative of what was active during each phase
    phase = sim_data.get("phase", "unknown")
    t_snap = sim_data.get("t", 0.0)

    # If we have the full sim time (hold phase complete), estimate total energy
    # by integrating phases. Use actual moment magnitudes as average.
    from p2_metrics import (T_SETTLE, T_CLUSTER, T_INTERLUDE_3x, T_HOLD,
                               compute_rego_energy, CHI_DEFAULT)

    # Get actual m_trap from the checkpoint dipole moments
    # IDX_TRAP = [8,9,10,11], IDX_SHAPE = [16..31], IDX_CORNER = [0..7]
    idx_trap   = [8, 9, 10, 11]
    idx_shape  = list(range(16, 32))
    idx_corner = list(range(0, 8))

    def avg_moment(indices):
        mags = [np.linalg.norm(dip_mom[i]) for i in indices if np.linalg.norm(dip_mom[i]) > 1e-12]
        return float(np.mean(mags)) if mags else 0.0

    m_trap_actual   = avg_moment(idx_trap)   or 0.0006
    m_shape_actual  = avg_moment(idx_shape)  or 0.0012
    m_corner_actual = avg_moment(idx_corner) or 0.0006

    # Use actual chi from sim (might have been scaled)
    chi_actual = CHI_DEFAULT * sim_data.get("chi_scale_used", 1.0) if "chi_scale_used" in sim_data else CHI_DEFAULT

    # Recompute energy with actual parameters
    T_transport_budget = 4.0   # from phase2 constant
    T_shape_budget     = 8.0

    E_computed = compute_rego_energy(
        m_trap    = m_trap_actual if m_trap_actual > 0 else 0.0006,
        m_shape   = m_shape_actual if m_shape_actual > 0 else 0.0012,
        m_corner  = m_corner_actual if m_corner_actual > 0 else 0.0006,
        chi       = chi_actual,
        scale_to_1m3 = True,
    )

    return {
        "m_trap_actual":    m_trap_actual,
        "m_shape_actual":   m_shape_actual,
        "m_corner_actual":  m_corner_actual,
        "chi_actual":       chi_actual,
        "total_power_snapshot_W": total_power_W,
        "energy_computed":  E_computed,
        "energy_MJ_per_kg_from_checkpoint": E_computed["energy_MJ_per_kg"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# STABILITY FROM REAL PARTICLE POSITIONS
# ═══════════════════════════════════════════════════════════════════════════

def compute_stability_from_positions(ckpt: dict) -> dict:
    """
    Compute structural stability from real particle positions.
    Uses actual contact counts and packing fraction.
    """
    pos_np = ckpt["pos"]
    nc_np  = ckpt.get("ncontact", np.zeros(N_PARTICLES, dtype=np.int32))

    # Packing fraction within cylinder volume
    cx = cy = 5e-3; cR = 0.010/6; cH = 4e-3; cz = 5e-3
    V_cylinder = PI * cR**2 * cH
    # Particles near cylinder surface (wall or cap)
    r_from_axis = np.sqrt((pos_np[:,0]-cx)**2 + (pos_np[:,1]-cy)**2)
    z_vals = pos_np[:,2]
    z_lo = cz - cH/2; z_hi = cz + cH/2
    in_cylinder = ((r_from_axis < cR + 5*R_PARTICLE) &
                   (z_vals >= z_lo - 5*R_PARTICLE) &
                   (z_vals <= z_hi + 5*R_PARTICLE))
    n_in_cyl = int(in_cylinder.sum())
    V_particles_in_cyl = n_in_cyl * VP
    packing_frac = min(V_particles_in_cyl / V_cylinder, 0.74)  # max random packing

    # Mean coordination number from contact data
    mean_coord = float(nc_np.mean())

    # Percolation fraction: fraction of particles with ≥ 2 contacts
    # (connected to load-bearing network)
    percolation_frac = float((nc_np >= 2).sum() / N_PARTICLES)

    # Hertz-based strength (same model, but use actual packing fraction)
    E_eff  = 2e5; nu = 0.25
    E_star = E_eff / (2*(1 - nu**2))
    R_star = R_PARTICLE / 2
    W_p    = MP * G_LUNAR
    delta  = (3 * W_p / (4 * E_star * math.sqrt(R_star)))**(2/3)
    k_hertz = (4/3) * E_star * math.sqrt(R_star * max(delta, 1e-15))
    Ap = PI * R_PARTICLE**2
    F_contact = k_hertz * delta
    sigma_comp = mean_coord * F_contact / Ap

    sigma_comp_ref = 200e3
    stability_norm = sigma_comp / (sigma_comp + sigma_comp_ref)

    return {
        "packing_fraction":     packing_frac,
        "mean_coordination":    mean_coord,
        "percolation_frac":     percolation_frac,
        "sigma_comp_Pa":        sigma_comp,
        "stability_norm":       float(np.clip(stability_norm, 0, 1)),
        "n_in_cylinder":        n_in_cyl,
    }


# ═══════════════════════════════════════════════════════════════════════════
# MAIN EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════

def extract_all(outputs_dir: Path,
                ckpt_path: Path = None,
                log_path:  Path = None,
                verbose:   bool = True) -> dict:
    """
    Full extraction pipeline. Returns merged dict with all real sim data.
    Falls back to analytical estimates for anything not found.
    """
    result = {
        "data_sources": [],
        "has_real_data": False,
    }

    # ── 1. Try checkpoint ─────────────────────────────────────────────────
    ckpt = None
    if ckpt_path and ckpt_path.exists():
        ckpt_file = ckpt_path
    else:
        # Auto-search outputs_dir
        candidates = [
            outputs_dir / "phase2_checkpoint.pkl",
            outputs_dir / "shape_checkpoint.pkl",
            outputs_dir / "Phase2_v4_Fixed" / "phase2_checkpoint.pkl",
        ]
        ckpt_file = next((p for p in candidates if p.exists()), None)

    if ckpt_file:
        if verbose:
            print(f"  [extract] Loading checkpoint: {ckpt_file}")
        try:
            ckpt = load_checkpoint_file(ckpt_file)
            sim_data = extract_from_checkpoint(ckpt)
            result.update(sim_data)
            result["data_sources"].append(str(ckpt_file))
            result["has_real_data"] = True
            if verbose:
                print(f"  [extract] ✓ Checkpoint: phase={sim_data['phase']}  "
                      f"t={sim_data['t']:.2f}s  "
                      f"RMS={sim_data['rms_distance_mm']:.3f}mm")
        except Exception as e:
            if verbose:
                print(f"  [extract] ✗ Checkpoint parse failed: {e}")

    # ── 2. Try log file ───────────────────────────────────────────────────
    if log_path and log_path.exists():
        log_file = log_path
    else:
        candidates = [
            outputs_dir / "sim_log.txt",
            outputs_dir / "Phase2_v4_Fixed" / "sim_log.txt",
            Path("sim_log.txt"),
        ]
        log_file = next((p for p in candidates if p.exists()), None)

    if log_file:
        if verbose:
            print(f"  [extract] Parsing log: {log_file}")
        try:
            log_data = parse_log_file(log_file)
            result.update(log_data)
            result["data_sources"].append(str(log_file))
            if verbose and "total_energy_J_log" in log_data:
                print(f"  [extract] ✓ Log: energy={log_data['total_energy_J_log']:.3f}J  "
                      f"budget={'PASS' if log_data.get('lunar_budget_pass') else 'FAIL/unknown'}")
        except Exception as e:
            if verbose:
                print(f"  [extract] ✗ Log parse failed: {e}")

    # ── 3. Energy from checkpoint dipole data ─────────────────────────────
    if ckpt is not None:
        try:
            E_data = compute_energy_from_checkpoint(ckpt, result)
            result["energy_from_checkpoint"] = E_data
            result["energy_MJ_per_kg"] = E_data["energy_MJ_per_kg_from_checkpoint"]
            if verbose:
                print(f"  [extract] ✓ Energy from checkpoint: "
                      f"{result['energy_MJ_per_kg']:.4f} MJ/kg")
        except Exception as e:
            if verbose:
                print(f"  [extract] ✗ Energy extraction failed: {e}")

    # ── 4. Stability from particle positions ──────────────────────────────
    if ckpt is not None:
        try:
            S_data = compute_stability_from_positions(ckpt)
            result["stability_from_positions"] = S_data
            result["stability_norm"] = S_data["stability_norm"]
            result["percolation_frac"] = S_data["percolation_frac"]
            if verbose:
                print(f"  [extract] ✓ Stability: norm={S_data['stability_norm']:.3f}  "
                      f"percolation={S_data['percolation_frac']:.3f}  "
                      f"packing={S_data['packing_fraction']:.3f}")
        except Exception as e:
            if verbose:
                print(f"  [extract] ✗ Stability extraction failed: {e}")

    # ── 5. Build time (always computed, refined with real timing if log) ───
    from p2_metrics import compute_build_time
    T_data = compute_build_time()
    result["time_data"] = T_data
    result["time_hours"] = T_data["t_realistic_parallel_h"]

    # If log has wall_time_s, we can refine the per-domain sim time
    if "wall_time_s" in result and result.get("wall_time_s"):
        # wall_time_s = actual CPU time, not sim time
        # The sim_time_s is what matters for scaling
        result["wall_clock_s"] = result["wall_time_s"]

    # ── 6. Final fallbacks for missing fields ─────────────────────────────
    if "rms_distance_mm" not in result:
        from p2_metrics import compute_shape_accuracy
        A_data = compute_shape_accuracy()
        result["rms_distance_mm"] = A_data["rms_analytical_mm"]
        result["accuracy_source"] = "analytical"
    else:
        result["accuracy_source"] = "checkpoint"

    if "energy_MJ_per_kg" not in result:
        from p2_metrics import compute_rego_energy
        E_data = compute_rego_energy()
        result["energy_MJ_per_kg"] = E_data["energy_MJ_per_kg"]
        result["energy_source"] = "analytical"
    else:
        result["energy_source"] = "checkpoint"

    if "stability_norm" not in result:
        from p2_metrics import compute_stability
        S_data = compute_stability()
        result["stability_norm"] = S_data["stability_norm"]
        result["stability_source"] = "analytical"
    else:
        result["stability_source"] = "checkpoint"

    # ── 7. Summary ────────────────────────────────────────────────────────
    result["summary"] = {
        "has_real_data":     result["has_real_data"],
        "energy_MJ_per_kg":  result.get("energy_MJ_per_kg", None),
        "time_hours":        result.get("time_hours", None),
        "rms_mm":            result.get("rms_distance_mm", None),
        "stability_norm":    result.get("stability_norm", None),
        "data_sources":      result["data_sources"],
        "accuracy_source":   result.get("accuracy_source", "unknown"),
        "energy_source":     result.get("energy_source", "unknown"),
        "stability_source":  result.get("stability_source", "unknown"),
    }

    return result


def main():
    parser = argparse.ArgumentParser(description="REGO Simulation Data Extractor")
    parser.add_argument("--dir",    default="outputs",
                        help="Simulation outputs directory (default: outputs/)")
    parser.add_argument("--ckpt",   default=None,
                        help="Explicit checkpoint .pkl path")
    parser.add_argument("--log",    default=None,
                        help="Explicit sim log .txt path")
    parser.add_argument("--output", default="rego_sim_data.json",
                        help="Output JSON path (default: rego_sim_data.json)")
    args = parser.parse_args()

    print("=" * 68)
    print("  REGO Simulation Data Extractor")
    print("=" * 68)

    data = extract_all(
        outputs_dir = Path(args.dir),
        ckpt_path   = Path(args.ckpt) if args.ckpt else None,
        log_path    = Path(args.log)  if args.log  else None,
        verbose     = True,
    )

    out_path = Path(args.output)
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    print(f"\n  ✓ Extracted data → {out_path}")
    print(f"\n  Summary:")
    s = data["summary"]
    src = "REAL SIM" if s["has_real_data"] else "ANALYTICAL FALLBACK"
    print(f"    Data source:   {src}")
    print(f"    Energy:        {s['energy_MJ_per_kg']:.4f} MJ/kg  [{s['energy_source']}]")
    print(f"    Time:          {s['time_hours']:.2f} h")
    print(f"    RMS accuracy:  {s['rms_mm']:.4f} mm  [{s['accuracy_source']}]")
    print(f"    Stability:     {s['stability_norm']:.3f}  [{s['stability_source']}]")
    if data.get("has_real_data"):
        print(f"    Phase at ckpt: {data.get('phase', '?')}")
        print(f"    Sim time:      {data.get('t', 0):.2f} s")
        print(f"    Conformity:    {data.get('mean_conformity_frac', 0):.2f}")

    if not data["has_real_data"]:
        print("\n  ⚠  No checkpoint found — using analytical estimates.")
        print("  Run the simulation first:")
        print("    python3 phase2_clean_saved.py")
        print("  Then re-run this extractor.")


if __name__ == "__main__":
    main()