"""
fem_dem_openfdem.py

Purpose:
 - Parse FEMM text export (B_output.txt), detect coil bounding box, crop it.
 - Build an interpolator for B(x,y[,z]) and grads.
 - Example integration pattern for OpenFDEM: create 4 particles (2 magnetic, 2 non-magnetic),
   set lunar gravity, a box enclosure, register a magnetic-force callback, run a short DEM.
 - Output particle traces and simple visualizations for verification (matplotlib + CSV/VTK).

NOTE: This is a template. OpenFDEM's Python API can differ by installation/version.
Where the code uses `openfdem.*` objects, read the comments and adapt to your local API.
"""

import numpy as np
import os
import sys
import math
import logging
from pathlib import Path
import matplotlib.pyplot as plt
from scipy.interpolate import RegularGridInterpolator, LinearNDInterpolator, RBFInterpolator
from scipy.spatial import cKDTree
import h5py
import csv

# Try import OpenFDEM bindings; if not available, instruct the user:
try:
    import openfdem   # placeholder import: adapt to actual module name for your installation
    from openfdem import Model, Material, ParticleGroup  # adapt as required
    OPENFDEM_AVAILABLE = True
except Exception as e:
    OPENFDEM_AVAILABLE = False
    # We will still produce field processing and the callback skeleton.
    logging.warning("OpenFDEM Python bindings not found. Template will still generate field maps and example callback."
                    "Install OpenFDEM or adjust API usage. Error: %s", e)

# ---------------------------
# CONFIG - edit these values
# ---------------------------
CONFIG = {
    "b_output_path": "B_output.txt",    # path to FEMM export
    "save_cropped": "field_cropped.csv",
    "save_lookup": "field_lookup.npz",
    "use_precompute_lookup": True,
    "lookup_resolution": (100, 100, 5),  # (nx, ny, nz) for precomputed 3D grid (z-depth small for extrusion)
    "padding_m": 0.01,   # padding around detected coil bbox (meters)
    "threshold_multiplier": 3.0,  # times median noise for coil detection
    "min_abs_threshold": 1e-5,  # Tesla absolute lower-limit for detection
    "extrude_z": True,
    "extrude_half_thickness_m": 0.01,  # +/- in z when extruding 2D -> 3D (meters)
    # DEM params
    "dem_domain": { "xmin": -0.05, "xmax": 0.05, "ymin": -0.05, "ymax": 0.05, "zmin": 0.0, "zmax": 0.05 },
    "timestep": 1e-5,
    "duration": 0.01,
    "output_dir": "out",
    # Particle definitions (example)
    "particles": [
        # two nonmagnetic silicate particles
        {"name":"sil1","type":"silicate","pos":[-0.01, 0.03, 0.005],"r":50e-6,"density":2800,"chi":0.0},
        {"name":"sil2","type":"silicate","pos":[ 0.01, 0.03, 0.005],"r":50e-6,"density":2800,"chi":0.0},
        # two magnetic regolith particles
        {"name":"mag1","type":"magnetic","pos":[-0.005,0.04,0.005],"r":70e-6,"density":3200,"chi":5e-5},
        {"name":"mag2","type":"magnetic","pos":[ 0.005,0.04,0.005],"r":60e-6,"density":3200,"chi":5e-5},
    ],
    # material/contact defaults
    "restitution": 0.2,
    "static_friction": 0.5,
    "kinetic_friction": 0.4,
    "rolling_friction": 0.01,
    "lunar_gravity": 1.62,  # m/s^2
}

# physical constants
MU0 = 4*math.pi*1e-7

# helpers
def ensure_out_dir():
    out = Path(CONFIG["output_dir"])
    out.mkdir(parents=True, exist_ok=True)
    return out

# ---------------------------
# PART 1: PARSE FEMM B_OUTPUT
# ---------------------------
def parse_femm_b_output(path):
    """
    Parse FEMM output text (with '#' comment lines). Return structured numpy array/dict
    Columns expected (best-effort): X Y Bx By (optionally Bz or gradients)
    Units are assumed cm (for X,Y) and Tesla for B; gradients in Tesla/cm.
    We convert to SI (m, T, T/m) on return.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    data_lines = []
    header_cols = None
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if len(line)==0:
                continue
            if line.startswith("#"):
                continue
            # detect header line (contains X Y Bx)
            if header_cols is None and ("X" in line and "Y" in line and "Bx" in line):
                # split by whitespace or tab
                header_cols = line.split()
                continue
            # otherwise numeric line
            # split preserving potential trailing region string
            parts = line.split()
            if len(parts) < 5:
                continue
            data_lines.append(parts)
    if header_cols is None:
        raise ValueError("No header with X Y Bx found in file")
    # convert to numpy structured array
    # map header names to indices
    # Try to parse numeric columns; last columns may be non-numeric (Region)
    header = header_cols
    ncols = len(header)
    arr = []
    for parts in data_lines:
        # handle lines with extra trailing text by truncating/padding
        if len(parts) < ncols:
            # pad with zeros
            parts = parts + ["0"]*(ncols - len(parts))
        row = parts[:ncols]
        arr.append(row)
    arr = np.array(arr)
    # build dictionary of floats for numeric headers; others as str
    data = {}
    for i,h in enumerate(header):
        col = arr[:,i]
        # try convert to float
        try:
            colf = col.astype(float)
            data[h] = colf
        except Exception:
            data[h] = col  # keep strings
    # Convert units:
    # X,Y in cm -> m
    for coord in ("X","Y","Z"):
        if coord in data:
            data[coord] = data[coord].astype(float) * 0.01
    # Bx,By,Bz in T (assume correct). Gradients in Tesla/cm -> T/m
    for g in list(data.keys()):
        if g.startswith("d") and "_d" in g:  # rough detection like dBx_dx
            try:
                data[g] = data[g].astype(float) * 100.0  # T/cm -> T/m
            except Exception:
                pass
    # B_mag correction if present (already in T)
    if "B_mag" in data:
        data["B_mag"] = data["B_mag"].astype(float)
    # ensure Bx,By exist as floats
    for comp in ("Bx","By","Bz"):
        if comp in data:
            data[comp] = data[comp].astype(float)
    return header, data

# ---------------------------
# PART 2: COIL REGION DETECTION
# ---------------------------
def detect_coil_bbox(data, threshold_multiplier=3.0, min_abs_threshold=1e-5, padding_m=0.01):
    """
    Determine bounding rectangle of coil region based on B_mag (or computed sqrt(Bx^2+By^2)).
    Returns bbox = (xmin,xmax,ymin,ymax) in meters (before padding applied).
    """
    # compute Bmag if not present:
    if "B_mag" in data:
        Bmag = data["B_mag"]
    else:
        bx = data.get("Bx", np.zeros_like(next(iter(data.values()))))
        by = data.get("By", np.zeros_like(bx))
        Bmag = np.sqrt(np.array(bx)**2 + np.array(by)**2)
    X = data["X"]
    Y = data["Y"]
    # noise floor estimate: median of points near zero (use 30th percentile)
    p30 = np.percentile(Bmag, 30)
    noise_floor = max(p30, 1e-12)
    threshold = max(threshold_multiplier * noise_floor, min_abs_threshold)
    # select indices above threshold
    mask = Bmag > threshold
    if np.sum(mask) == 0:
        # fallback: use top percentile (e.g., top 1%)
        p99 = np.percentile(Bmag, 99)
        mask = Bmag >= p99
        if np.sum(mask) == 0:
            raise ValueError("No high-field region found with thresholds; try lowering threshold_multiplier or min_abs_threshold")
    # compute largest connected component in 2D by grid projection if structured, else just bbox of mask
    xmin = np.min(X[mask])
    xmax = np.max(X[mask])
    ymin = np.min(Y[mask])
    ymax = np.max(Y[mask])
    # apply padding
    xmin -= padding_m
    xmax += padding_m
    ymin -= padding_m
    ymax += padding_m
    return (xmin,xmax,ymin,ymax), threshold

# ---------------------------
# PART 3: CROPPING & INTERPOLATOR
# ---------------------------
def crop_and_build_interpolator(header, data, bbox, prefer_regular=True):
    """
    Crop the field to bbox and create an interpolator object.
    Returns a dict with interpolator function(s), grid info, and a query function.
    If data is structured, create RegularGridInterpolator; otherwise use LinearND or RBF.
    """
    xmin,xmax,ymin,ymax = bbox
    X = data["X"]
    Y = data["Y"]
    mask = (X >= xmin) & (X <= xmax) & (Y >= ymin) & (Y <= ymax)
    if mask.sum() == 0:
        raise ValueError("After cropping, no points remain. Check bbox/padding.")
    # produce cropped arrays
    xc = X[mask]; yc = Y[mask]
    bx = data.get("Bx", np.zeros_like(xc))[mask]
    by = data.get("By", np.zeros_like(xc))[mask]
    # determine if regular grid: check unique sorted X and Y counts
    ux = np.unique(np.round(xc, 12))
    uy = np.unique(np.round(yc, 12))
    is_regular = (len(ux) * len(uy) == len(xc))
    interp = {}
    if is_regular and prefer_regular:
        # reshape into 2D grid
        ux_sorted = np.sort(ux)
        uy_sorted = np.sort(uy)
        # create meshgrid such that data can be reshaped
        xi_idx = {val:i for i,val in enumerate(ux_sorted)}
        yi_idx = {val:i for i,val in enumerate(uy_sorted)}
        grid_bx = np.zeros((len(ux_sorted), len(uy_sorted)))
        grid_by = np.zeros_like(grid_bx)
        for xval,yval,bxval,byval in zip(xc,yc,bx,by):
            i = xi_idx[np.round(xval,12)]
            j = yi_idx[np.round(yval,12)]
            grid_bx[i,j] = bxval
            grid_by[i,j] = byval
        # regular grid interpolator expects axes in (x,y) order
        rg_bx = RegularGridInterpolator((ux_sorted, uy_sorted), grid_bx.T, bounds_error=False, fill_value=None)
        rg_by = RegularGridInterpolator((ux_sorted, uy_sorted), grid_by.T, bounds_error=False, fill_value=None)
        interp['type'] = 'regular'
        interp['bx_func'] = lambda pts: rg_bx(pts[:, :2])
        interp['by_func'] = lambda pts: rg_by(pts[:, :2])
        interp['grid'] = (ux_sorted, uy_sorted)
    else:
        # scattered data -> use LinearNDInterpolator (faster) or RBF if sparse
        pts = np.vstack([xc, yc]).T
        try:
            linear_bx = LinearNDInterpolator(pts, bx, fill_value=0.0)
            linear_by = LinearNDInterpolator(pts, by, fill_value=0.0)
            interp['type'] = 'linear_nd'
            interp['bx_func'] = lambda pts: linear_bx(pts[:, :2])
            interp['by_func'] = lambda pts: linear_by(pts[:, :2])
        except Exception:
            rbf_bx = RBFInterpolator(pts, bx, neighbors=12, smoothing=0.001)
            rbf_by = RBFInterpolator(pts, by, neighbors=12, smoothing=0.001)
            interp['type'] = 'rbf'
            interp['bx_func'] = lambda pts: rbf_bx(pts[:, :2])
            interp['by_func'] = lambda pts: rbf_by(pts[:, :2])
    # Return also bounding box and original cropped points for plotting
    interp['bbox'] = bbox
    interp['cropped_pts'] = (xc, yc, bx, by)
    return interp

# ---------------------------
# PART 4: QUERY API
# ---------------------------
def build_query_functions(interp, extrude_z=True, z_half=0.01):
    """
    Build functions B_vector(pos_array) and gradB (optional).
    - pos_array shape (N,3) in meters
    - return B (N,3) in T
    """
    def query_B(pos):
        # pos: Nx3
        pts2 = np.array(pos)[:, :2]
        bx = interp['bx_func'](pts2)
        by = interp['by_func'](pts2)
        # handle shape if scalar
        bx = np.array(bx).reshape(-1)
        by = np.array(by).reshape(-1)
        # extrude to z if requested: simple uniform or gaussian falloff
        if extrude_z:
            z = np.array(pos)[:, 2]
            # gaussian falloff with sigma = z_half
            sigma = max(z_half, 1e-9)
            falloff = np.exp(- (z**2) / (2 * sigma**2))
            bx = bx * falloff
            by = by * falloff
        B = np.vstack([bx, by, np.zeros_like(bx)]).T
        return B
    # gradient estimation: finite differences using small dx step
    def query_gradB(pos, eps=1e-4):
        pos = np.array(pos)
        N = pos.shape[0]
        grad = np.zeros((N,3,3))  # grad[i] is 3x3 Jacobian dBi/dxj
        # central differences along x,y,z
        for dim in range(3):
            shift = np.zeros(3)
            shift[dim] = eps
            Bp = query_B(pos + shift)
            Bm = query_B(pos - shift)
            dB = (Bp - Bm) / (2*eps)
            grad[:, :, dim] = dB  # columns are derivatives wrt dim
        return grad
    return query_B, query_gradB

# ---------------------------
# PART 5: MAGNETIC FORCE MODELS
# ---------------------------
def susceptibility_force(B, gradB, radius, chi, mu0=MU0):
    """
    F = V * (chi/mu0) * (B · ∇)B
    Input:
     - B: (N,3) array (T)
     - gradB: (N,3,3) array, gradB[i,j,k] = dB_j / dx_k
     - radius: scalar or array (m)
     - chi: scalar susceptibility (dimensionless)
    Returns:
     - F: (N,3)
    """
    V = (4.0/3.0) * np.pi * (radius**3)
    # compute (B · ∇) B : component i is sum_j B_j * dB_i/dx_j
    # dB_i/dx_j is gradB[:, i, j]
    Bcol = B.reshape(-1,3)
    F = np.zeros_like(Bcol)
    for i in range(3):
        # compute sum_j B_j * dB_i/dx_j
        comp = np.sum(Bcol * gradB[:, i, :], axis=1)
        F[:, i] = (V * chi / mu0) * comp
    return F

def dipole_force_and_torque(mvec, B, gradB):
    """
    F = grad(m · B)
    Torque tau = m x B
    Input:
      - mvec: (N,3) magnetic dipole vector (A·m^2)
      - B: (N,3)
      - gradB: (N,3,3)
    Returns:
      - F: (N,3), Tau: (N,3)
    """
    # m·B is scalar per particle; grad of that = sum_j m_j * gradB[:, :, j]
    m = np.array(mvec).reshape(-1,3)
    N = m.shape[0]
    F = np.zeros((N,3))
    for j in range(3):
        F += m[:, j].reshape(-1,1) * gradB[:, :, j]
    tau = np.cross(m, B)
    return F, tau

# ---------------------------
# PART 6: PRECOMPUTE LOOKUP (optional)
# ---------------------------
def precompute_lookup(interp, bbox, resolution=(100,100,5), z_half=0.01, outpath=None):
    """
    Create a regular 3D grid and store Bx,By,Bz for fast lookup.
    resolution = (nx, ny, nz)
    bbox is (xmin,xmax,ymin,ymax)
    extrude z from -z_half..+z_half
    """
    xmin,xmax,ymin,ymax = bbox
    nx, ny, nz = resolution
    xs = np.linspace(xmin, xmax, nx)
    ys = np.linspace(ymin, ymax, ny)
    zs = np.linspace(-z_half, z_half, nz)
    Xg, Yg, Zg = np.meshgrid(xs, ys, zs, indexing='xy')
    pts = np.vstack([Xg.ravel(), Yg.ravel(), Zg.ravel()]).T
    query_B, _ = build_query_functions(interp, extrude_z=True, z_half=z_half)
    B = query_B(pts)
    Bx = B[:,0].reshape(nx, ny, nz)
    By = B[:,1].reshape(nx, ny, nz)
    Bz = B[:,2].reshape(nx, ny, nz)
    if outpath:
        np.savez_compressed(outpath, xs=xs, ys=ys, zs=zs, Bx=Bx, By=By, Bz=Bz)
    return (xs,ys,zs,Bx,By,Bz)

# ---------------------------
# PART 7: DEM & OpenFDEM integration skeleton
# ---------------------------
def build_and_run_dem(interp_query_B, interp_query_gradB):
    """
    Build a minimal OpenFDEM model with 4 particles and attach the magnetic force.
    This function demonstrates the integration pattern. You must adapt names to your OpenFDEM API.
    """
    outdir = ensure_out_dir()
    # check OpenFDEM availability
    if not OPENFDEM_AVAILABLE:
        print("OpenFDEM bindings not found. This function will only produce a pseudo-run and output sample CSVs.")
    # create model
    if OPENFDEM_AVAILABLE:
        model = Model()   # adapt as necessary
        # set gravity (assume OpenFDEM expects a 3-vector; adjust axis if needed)
        model.set_gravity([0.0, -CONFIG["lunar_gravity"], 0.0])  # example: negative y gravity
        # create container geometry: box boundaries - usually by rigid walls or boundary elements
        # adapt to API: model.add_wall(...) or model.add_boundary(...)
        # create materials
        mat_sil = Material("silicate", density=CONFIG["particles"][0]["density"])
        mat_mag = Material("magnetic", density=CONFIG["particles"][2]["density"])
        model.add_material(mat_sil)
        model.add_material(mat_mag)
    else:
        model = None  # for pseudo-run

    # create particle list for output (for pseudo-run)
    particle_states = []
    # prepare callback function that OpenFDEM will call per timestep or per particle
    def magnetic_force_callback(particle):
        """
        Example expected signature: particle has attributes .position (3), .radius, .props (dict)
        You must adapt to the actual signature in your OpenFDEM installation.
        Returns force vector [Fx,Fy,Fz] (N) and optionally torque.
        """
        pos = np.array(particle.position).reshape(1,3)
        B = interp_query_B(pos)   # (1,3)
        gradB = interp_query_gradB(pos)  # (1,3,3)
        # read particle properties
        r = particle.radius if hasattr(particle, 'radius') else particle['r']
        chi = particle.props.get('chi', 0.0) if hasattr(particle, 'props') else particle.get('chi', 0.0)
        if chi is not None and chi != 0.0:
            F = susceptibility_force(B, gradB, r, chi)
            return F[0], np.zeros(3)
        # else no magnetic force
        return np.zeros(3), np.zeros(3)

    # Register callback - adapt to actual API call name
    if OPENFDEM_AVAILABLE:
        model.add_userforce(magnetic_force_callback)  # likely name; adapt as needed

    # create the 4 particles and add them (both in model if available, and record states for pseudo-run)
    for pconf in CONFIG["particles"]:
        if OPENFDEM_AVAILABLE:
            # adapt to API: model.add_particle(...) or Particle(...) then model.add(...)
            p = model.add_particle(position=pconf["pos"], radius=pconf["r"], material=(mat_mag if pconf["chi"]>0 else mat_sil))
            # set properties like susceptibility if particle object supports user properties
            p.props['chi'] = pconf["chi"]
            p.props['name'] = pconf["name"]
            # set contact / friction / restitution using model or particle API
            p.set_restitution(CONFIG["restitution"])
            p.set_friction(static=CONFIG["static_friction"], kinetic=CONFIG["kinetic_friction"], rolling=CONFIG["rolling_friction"])
        else:
            # pseudo particle for offline testing
            p = {"name":pconf["name"], "position":np.array(pconf["pos"]), "radius":pconf["r"], "chi":pconf["chi"],
                 "velocity":np.zeros(3)}
            particle_states.append(p)

    # Run the simulation
    if OPENFDEM_AVAILABLE:
        # adapt to API: model.run(dt, duration, output_path=...)
        model.run(dt=CONFIG["timestep"], duration=CONFIG["duration"], output_dir=str(outdir))
    else:
        # Very simple pseudo-time integration to demonstrate force application & output
        dt = CONFIG["timestep"]
        steps = int(CONFIG["duration"] / dt)
        traj = {p['name']: [] for p in particle_states}
        for step in range(steps):
            for p in particle_states:
                pos = p["position"].reshape(1,3)
                B = interp_query_B(pos)
                gradB = interp_query_gradB(pos)
                if p["chi"] != 0.0:
                    F = susceptibility_force(B, gradB, p["radius"], p["chi"])[0]
                else:
                    F = np.zeros(3)
                # gravity
                Fg = np.array([0.0, -p.get("density", 3000)* (4/3)*np.pi*p["radius"]**3 * CONFIG["lunar_gravity"], 0.0])
                totalF = F + Fg
                # simple explicit Euler (not stable for real DEM; just demo)
                mass = p.get("density",3000) * (4/3)*np.pi*p["radius"]**3
                acc = totalF / mass
                p["velocity"] = p["velocity"] + acc * dt
                p["position"] = p["position"] + p["velocity"] * dt
                traj[p["name"]].append(p["position"].copy())
        # save trajectories
        for name, pts in traj.items():
            pts = np.array(pts)
            np.savetxt(outdir / f"traj_{name}.csv", pts, delimiter=",")
        print("Pseudo-run finished; trajectories saved in", outdir)

# ---------------------------
# PART 8: VISUALIZATION HELPERS
# ---------------------------
def plot_cropped_field(interp):
    xc,yc,bx,by = interp['cropped_pts']
    bbox = interp['bbox']
    plt.figure(figsize=(6,5))
    sc = plt.scatter(xc, yc, c=np.sqrt(np.array(bx)**2 + np.array(by)**2), s=8, cmap='inferno')
    plt.colorbar(sc, label='|B| (T)')
    xmin,xmax,ymin,ymax = bbox
    plt.gca().add_patch(plt.Rectangle((xmin,ymin), xmax-xmin, ymax-ymin, fill=False, edgecolor='cyan', linewidth=1.5))
    plt.title("Cropped B magnitude (T) with bounding box")
    plt.xlabel("X (m)")
    plt.ylabel("Y (m)")
    plt.axis('equal')
    outdir = ensure_out_dir()
    plt.savefig(outdir / "cropped_Bfield.png", dpi=200)
    plt.close()

# ---------------------------
# MAIN: RUN PROCESS
# ---------------------------
def main():
    outdir = ensure_out_dir()
    header, data = parse_femm_b_output(CONFIG["b_output_path"])
    print("Parsed columns:", header)
    bbox, threshold = detect_coil_bbox(data, threshold_multiplier=CONFIG["threshold_multiplier"],
                                      min_abs_threshold=CONFIG["min_abs_threshold"], padding_m=CONFIG["padding_m"])
    print("Detected coil bbox (m):", bbox, "threshold (T):", threshold)
    interp = crop_and_build_interpolator(header, data, bbox)
    plot_cropped_field(interp)
    query_B, query_gradB = build_query_functions(interp, extrude_z=CONFIG["extrude_z"], z_half=CONFIG["extrude_half_thickness_m"])
    # optional precompute
    if CONFIG["use_precompute_lookup"]:
        precompute_lookup(interp, bbox, resolution=CONFIG["lookup_resolution"], z_half=CONFIG["extrude_half_thickness_m"], outpath=CONFIG["save_lookup"])
    # run DEM (or pseudo-run if OpenFDEM not available)
    build_and_run_dem(query_B, query_gradB)
    print("Done. Outputs (plots, trajectories) in:", outdir)

if __name__ == "__main__":
    main()
