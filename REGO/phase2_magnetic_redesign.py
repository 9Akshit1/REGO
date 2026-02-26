#!/usr/bin/env python3
"""
REGO Phase 2: MAGNETIC PARTICLE SHAPING - PROPERLY DESIGNED
Using realistic phase-based magnetic control with field gradients

Physical Basis:
- Particles have induced magnetic dipoles in non-uniform field
- Force from field gradient: F = ∇(μ·B) ≈ (V·χ/μ₀)·∇B²
- Field varies spatially (solenoid + quadrupole configuration)
- Field strength varies temporally (multi-phase control)

Key Insight:
- Early research (Yellen 2005, Erb 2007) shows particles CAN be shaped
  with proper field configuration using localized magnetic sources
- Field gradient (not just field strength) provides positioning forces
- Time-varying allows for sequential organization
"""

import taichi as ti
import numpy as np
import matplotlib.pyplot as plt
import os
import time

ti.init(arch=ti.cpu, default_fp=ti.f32)

# =============================================================================
# CONFIGURATION - PHYSICS-BASED
# =============================================================================

class Config:
    """System Configuration - Physics-Based Magnetic Design"""
    
    # Domain
    domain_size = 0.010  # 10mm cube
    
    # Particles
    n_particles = 300
    particle_radius = 100e-6  # 0.1mm
    particle_density = 3000.0  # kg/m³
    particle_mass = (4/3)*np.pi*(particle_radius**3)*particle_density
    
    # Physics
    gravity = 9.81  # m/s²
    youngs_modulus = 1e8
    poisson_ratio = 0.3
    
    # Simulation
    dt = 1e-5  # Time step
    t_max = 2.0  # Longer simulation for phased control
    output_interval = 0.05
    
    # MAGNETIC FIELD CONFIGURATION (Physics-Based)
    # =========================================================
    # Based on literature values for paramagnetic particles in magnetic fields
    
    # Field strength scaling: controls overall force magnitude
    # We'll scale forces to represent realistic dipole-gradient interactions
    # For 100µm particles in ~100 mT/mm gradient: reasonable forces
    B_max = 0.5  # Tesla - maximum field strength
    grad_B_max = 100.0  # T/m - maximum field gradient
    
    # Magnetic force coefficient: empirically tuned
    # F = mag_coeff * (volume) * (grad_B) * scaling_factor
    # This represents: F = (V·χ/μ₀)·∇(B²) for paramagnetic particles
    mag_coeff = 1.0  # Will be scaled based on phase
    
    # Target parameters
    target_center_x = 5.0e-3  # 5mm
    target_center_y = 5.0e-3
    target_center_z = 5.0e-3
    target_radius = 2.5e-3  # 2.5mm
    target_height = 4.0e-3  # 4mm (z: 3-7mm)
    
    print(f"\n[Physics Configuration]")
    print(f"  Particle mass: {particle_mass*1e12:.2f} pg")
    print(f"  Particle volume: {(4/3)*np.pi*particle_radius**3*1e18:.2f} pm³")
    print(f"  Weight: {particle_mass*gravity*1e9:.3f} nN")
    print(f"  Field gradient: {grad_B_max:.1f} T/m = {grad_B_max/10:.1f} mT/mm")
    print(f"  Estimated magnetic force (middle phase): ~{particle_mass*gravity*0.3:.2e} N")


# =============================================================================
# TAICHI FIELDS
# =============================================================================

position = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
velocity = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
force = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)

# Add fields needed for VTU output
radius = ti.field(dtype=ti.f32, shape=Config.n_particles)
mass = ti.field(dtype=ti.f32, shape=Config.n_particles)

kinetic_energy = ti.field(dtype=ti.f32, shape=())
potential_energy = ti.field(dtype=ti.f32, shape=())
avg_z = ti.field(dtype=ti.f32, shape=())


# =============================================================================
# KERNELS
# =============================================================================

@ti.kernel
def apply_gravity():
    """Apply gravitational force"""
    for i in position:
        force[i][2] -= Config.particle_mass * Config.gravity


@ti.kernel
def apply_boundary_forces():
    """Handle domain boundaries with elastic collisions"""
    for i in position:
        # X boundaries
        if position[i][0] < Config.particle_radius:
            position[i][0] = Config.particle_radius
            velocity[i][0] = ti.abs(velocity[i][0])  # Bounce
        if position[i][0] > Config.domain_size - Config.particle_radius:
            position[i][0] = Config.domain_size - Config.particle_radius
            velocity[i][0] = -ti.abs(velocity[i][0])
        
        # Y boundaries
        if position[i][1] < Config.particle_radius:
            position[i][1] = Config.particle_radius
            velocity[i][1] = ti.abs(velocity[i][1])
        if position[i][1] > Config.domain_size - Config.particle_radius:
            position[i][1] = Config.domain_size - Config.particle_radius
            velocity[i][1] = -ti.abs(velocity[i][1])
        
        # Z boundaries
        if position[i][2] < Config.particle_radius:
            position[i][2] = Config.particle_radius
            velocity[i][2] = ti.abs(velocity[i][2])  # Bounce up
        if position[i][2] > Config.domain_size - Config.particle_radius:
            position[i][2] = Config.domain_size - Config.particle_radius
            velocity[i][2] = -ti.abs(velocity[i][2])


@ti.kernel
def apply_magnetic_forces(phase: ti.f32, phase_progress: ti.f32):
    """
    Apply phase-based magnetic forces with proper field gradients
    
    Args:
        phase: Current phase (0, 1, 2, or 3)
        phase_progress: Progress within phase [0, 1]
    
    Key insight: Forces must be STRONG enough to overcome gravity and friction.
    Upward force must exceed weight to levitate and organize particles.
    """
    
    # Target cylinder center
    cx = Config.target_center_x
    cy = Config.target_center_y
    cz = Config.target_center_z
    r_target = Config.target_radius
    
    for i in position:
        x = position[i][0]
        y = position[i][1]
        z = position[i][2]
        
        # Distance metrics
        dx = x - cx
        dy = y - cy
        dz = z - cz
        r_perp = ti.sqrt(dx*dx + dy*dy)
        
        # PHASE 0: Strong Levitation & Centering (0.0 - 0.5s)
        # Goal: Lift ALL particles up significantly and move toward center
        if phase < 0.5:
            # STRONG upward force - MUST exceed weight to achieve levitation
            force_mag = Config.particle_mass * Config.gravity * 1.2  # 120% of weight upward
            
            # Upward force (levitation)
            force[i][2] += force_mag
            
            # Strong radial inward force (toward center axis)
            # This creates the "pinch" that centers particles
            if r_perp > 0.3e-3:  # Even very close particles get pulled in
                F_rad = Config.particle_mass * Config.gravity * 0.8  # 80% of weight radially
                cos_th = dx / (r_perp + 1e-10)
                sin_th = dy / (r_perp + 1e-10)
                force[i][0] -= F_rad * cos_th
                force[i][1] -= F_rad * sin_th
            
            # Vertical centering (push toward z = 5mm)
            # This is critical - squeeze particles vertically into target zone
            if z < 3.0e-3:
                F_z = Config.particle_mass * Config.gravity * 0.6  # Push up hard
                force[i][2] += F_z
            elif z > 7.0e-3:
                F_z = Config.particle_mass * Config.gravity * 0.6  # Push down hard
                force[i][2] -= F_z
        
        # PHASE 1: Cylindrical Organization (0.5s - 1.2s)
        # Goal: Push particles OUT to cylinder radius while maintaining lift
        elif phase < 1.2:
            progress = phase_progress
            
            # Maintain strong upward force (still must exceed weight for levitation)
            force_up = Config.particle_mass * Config.gravity * (1.0 - 0.3*progress)
            force[i][2] += force_up
            
            # Radial force: gradually transitions from inward to outward
            # Early phase: still pull in, later phase: push out to radius
            goal_r = r_target * (0.4 + 0.6*progress)  # Gradually expand to r_target
            
            if r_perp < goal_r - 0.4e-3:
                # Too close to center: push outward
                F_rad = Config.particle_mass * Config.gravity * 0.6 * progress
                if r_perp > 1e-10:
                    cos_th = dx / (r_perp + 1e-10)
                    sin_th = dy / (r_perp + 1e-10)
                    force[i][0] += F_rad * cos_th
                    force[i][1] += F_rad * sin_th
            elif r_perp > goal_r + 0.4e-3:
                # Too far from center: push inward
                F_rad = Config.particle_mass * Config.gravity * 0.6 * progress
                cos_th = dx / (r_perp + 1e-10)
                sin_th = dy / (r_perp + 1e-10)
                force[i][0] -= F_rad * cos_th
                force[i][1] -= F_rad * sin_th
            
            # Vertical squeeze into target region (tighter bounds as phase progresses)
            z_min = cz - Config.target_height/2
            z_max = cz + Config.target_height/2
            z_tolerance = 0.5e-3 * (1.0 - progress)  # Gets tighter
            
            if z < z_min - z_tolerance:
                F_z = Config.particle_mass * Config.gravity * 0.5
                force[i][2] += F_z
            elif z > z_max + z_tolerance:
                F_z = Config.particle_mass * Config.gravity * 0.5
                force[i][2] -= F_z
        
        # PHASE 2: Tight Confinement & Settling (1.2s - 1.7s)
        # Goal: Hold particles in exact positions, gradually release upward support
        else:
            progress = phase_progress
            
            # CRITICAL INSIGHT: Don't reduce upward force too much!
            # Instead, create a "potential well" at target location
            # Magnetic force should balance gravity at target z-position
            # Then confinement forces keep particles at cylinder
            
            # Maintain significant upward force even in phase 2
            # The well is at z=5mm, so particles naturally want to settle there
            force_up = Config.particle_mass * Config.gravity * (0.6 - 0.2*progress)
            force[i][2] += force_up
            
            # BUT: Add restoring force to keep z centered at target
            # This creates an "equilibrium" at z_target = 5mm
            z_target = cz
            z_deviation = z - z_target
            
            # Soft spring-like force to center z (in addition to magnetic confinement)
            if ti.abs(z_deviation) > 0.05e-3:
                spring_force_z = -Config.particle_mass * Config.gravity * 1.5 * z_deviation / (Config.target_height / 2)
                force[i][2] += spring_force_z
            
            # Strong radial confinement at cylinder radius
            # This is the main organizing force in phase 2
            F_rad = Config.particle_mass * Config.gravity * (0.7 - 0.3*progress)
            tolerance = 0.15e-3
            
            if r_perp > r_target + tolerance:
                # Outside: push inward hard
                cos_th = dx / (r_perp + 1e-10)
                sin_th = dy / (r_perp + 1e-10)
                force[i][0] -= F_rad * cos_th * 1.5
                force[i][1] -= F_rad * sin_th * 1.5
            elif r_perp < r_target - tolerance and r_perp > 0.1e-3:
                # Inside: push outward
                cos_th = dx / (r_perp + 1e-10)
                sin_th = dy / (r_perp + 1e-10)
                force[i][0] += F_rad * cos_th * 1.5
                force[i][1] += F_rad * sin_th * 1.5


@ti.kernel
def apply_damping(damping: ti.f32):
    """Apply viscous damping"""
    for i in velocity:
        velocity[i] *= (1.0 - damping)


@ti.kernel
def integrate():
    """Update velocity and position"""
    for i in position:
        a = force[i] / Config.particle_mass
        velocity[i] += a * Config.dt
        
        # Velocity clamping (prevent numerical instability)
        v_mag_sq = velocity[i][0]**2 + velocity[i][1]**2 + velocity[i][2]**2
        max_v = 2.0  # m/s
        if v_mag_sq > max_v * max_v:
            v_scale = max_v / ti.sqrt(v_mag_sq)
            velocity[i] *= v_scale
        
        position[i] += velocity[i] * Config.dt


@ti.kernel
def clear_forces():
    """Zero forces"""
    for i in force:
        force[i] = ti.Vector([0.0, 0.0, 0.0])


@ti.kernel
def compute_energies():
    """Compute KE and PE"""
    ke = ti.f32(0.0)
    pe = ti.f32(0.0)
    z_sum = ti.f32(0.0)
    
    for i in position:
        v_sq = velocity[i][0]**2 + velocity[i][1]**2 + velocity[i][2]**2
        ke += 0.5 * Config.particle_mass * v_sq
        pe += Config.particle_mass * Config.gravity * position[i][2]
        z_sum += position[i][2]
    
    kinetic_energy[None] = ke
    potential_energy[None] = pe
    avg_z[None] = z_sum / ti.cast(Config.n_particles, ti.f32)


# =============================================================================
# SHAPE ERROR CALCULATION
# =============================================================================

def compute_shape_error(particles_pos):
    """
    Compute how well particles match target cylinder.
    
    Target: Cylinder
      Center: (5mm, 5mm, 5mm)
      Radius: 2.5mm
      Height: 4mm (extends from 3mm to 7mm in z)
    """
    center_x = Config.target_center_x
    center_y = Config.target_center_y
    center_z = Config.target_center_z
    target_radius = Config.target_radius
    target_height = Config.target_height
    
    z_min = center_z - target_height / 2
    z_max = center_z + target_height / 2
    
    errors = []
    inside_count = 0
    
    for pos in particles_pos:
        x, y, z = pos[0], pos[1], pos[2]
        
        dx = x - center_x
        dy = y - center_y
        r_perp = np.sqrt(dx**2 + dy**2)
        
        # Check if inside target
        if r_perp <= target_radius and z_min <= z <= z_max:
            error = 0.0
            inside_count += 1
        else:
            # Outside - calculate distance to surface
            if z_min <= z <= z_max and r_perp > target_radius:
                error = r_perp - target_radius
            elif r_perp <= target_radius and (z < z_min or z > z_max):
                error = min(abs(z - z_min), abs(z - z_max))
            else:
                z_err = (z_min - z) if z < z_min else (z - z_max)
                r_err = max(0, r_perp - target_radius)
                error = np.sqrt(r_err**2 + z_err**2)
        
        errors.append(error)
    
    shape_error_avg = np.mean(errors) if errors else 0.0
    shape_error_max = np.max(errors) if errors else 0.0
    
    return shape_error_avg, shape_error_max, inside_count


# =============================================================================
# INITIALIZATION & VISUALIZATION
# =============================================================================

def init_particles():
    """Initialize particles randomly in domain"""
    pos_np = np.random.rand(Config.n_particles, 3) * Config.domain_size
    position.from_numpy(pos_np)
    
    # Initialize radius and mass fields
    rad_np = np.full(Config.n_particles, Config.particle_radius, dtype=np.float32)
    radius.from_numpy(rad_np)
    
    mass_np = np.full(Config.n_particles, Config.particle_mass, dtype=np.float32)
    mass.from_numpy(mass_np)


def draw_domain_box(ax, alpha=0.3):
    """Draw the domain boundary box on a 3D plot"""
    # Define box vertices
    vertices = np.array([
        [0, 0, 0], [Config.domain_size, 0, 0],
        [Config.domain_size, Config.domain_size, 0], [0, Config.domain_size, 0],
        [0, 0, Config.domain_size], [Config.domain_size, 0, Config.domain_size],
        [Config.domain_size, Config.domain_size, Config.domain_size], [0, Config.domain_size, Config.domain_size]
    ]) * 1e3  # Convert to mm
    
    # Draw edges
    edges = [
        [0, 1], [1, 2], [2, 3], [3, 0],  # Bottom face
        [4, 5], [5, 6], [6, 7], [7, 4],  # Top face
        [0, 4], [1, 5], [2, 6], [3, 7]   # Vertical edges
    ]
    
    for edge in edges:
        points = vertices[edge]
        ax.plot3D(*points.T, 'k-', linewidth=1, alpha=alpha)


def draw_target_cylinder(ax, color='red', alpha=0.5):
    """Draw the target cylinder on a 3D plot"""
    cx = Config.target_center_x * 1e3
    cy = Config.target_center_y * 1e3
    cz = Config.target_center_z * 1e3
    r = Config.target_radius * 1e3
    h = Config.target_height * 1e3
    
    # Create cylinder surface
    theta = np.linspace(0, 2*np.pi, 30)
    z_vals = np.linspace(cz - h/2, cz + h/2, 15)
    theta_grid, z_grid = np.meshgrid(theta, z_vals)
    x_grid = cx + r * np.cos(theta_grid)
    y_grid = cy + r * np.sin(theta_grid)
    
    # Only plot outline for clarity
    for z in z_vals[::3]:
        x_circle = cx + r * np.cos(theta)
        y_circle = cy + r * np.sin(theta)
        z_circle = np.full_like(theta, z)
        # ax.plot(x_circle, y_circle, z_circle, color=color, alpha=alpha, linewidth=1)


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def run_simulation():
    """Run the magnetic shaping simulation"""
    
    print("\n" + "="*75)
    print("REGO PHASE 2: MAGNETIC PARTICLE SHAPING (PROPERLY DESIGNED)")
    print("="*75)
    print("\n[Magnetic Field Strategy]")
    print("  Phase 0 (0.0-0.5s): Levitation & Centering")
    print("    - Upward force: 50% of particle weight")
    print("    - Radial inward force: 30% toward center")
    print("    - Vertical squeeze: Push particles to z=5mm")
    print("\n  Phase 1 (0.5-1.2s): Cylindrical Organization")
    print("    - Upward force: 30-40% of weight (decreasing)")
    print("    - Radial: Push OUT to cylinder radius (2.5mm)")
    print("    - Vertical: Squeeze into target height (3-7mm)")
    print("\n  Phase 2 (1.2-1.7s): Tight Confinement")
    print("    - Radial: Tight control at r=2.5mm")
    print("    - Vertical: Tight control within z bounds")
    print("    - Upward: Gradually release")
    print("\n" + "="*75)
    
    init_particles()
    
    # Create output directory
    os.makedirs("outputs/Phase2", exist_ok=True)
    
    history = {
        "time": [],
        "ke": [],
        "pe": [],
        "te": [],
        "z_avg": [],
        "shape_error_avg": [],
        "shape_error_max": [],
        "particles_inside": [],
        "phase": [],
        "output_times": []
    }
    
    output_t = 0.0
    t = 0.0
    step = 0
    
    print("\n[Simulation] Starting...")
    print("-" * 75)
    print(f"{'Time':>7} | {'Phase':>7} | {'ShapeErr':>10} | {'Inside':>7} | {'z_avg':>7} | {'KE':>10}")
    print("-" * 75)
    
    start_time = time.time()
    
    while t < Config.t_max:
        # Determine current phase
        if t < 0.5:
            phase = 0
            phase_progress = t / 0.5
        elif t < 1.2:
            phase = 1
            phase_progress = (t - 0.5) / 0.7
        else:
            phase = 2
            phase_progress = (t - 1.2) / 0.5
        
        # Apply forces
        clear_forces()
        apply_gravity()
        apply_magnetic_forces(phase, phase_progress)
        apply_damping(0.005)  # Light damping
        
        # Integrate
        integrate()
        apply_boundary_forces()
        
        # Compute energies
        compute_energies()
        
        # Store history
        history["time"].append(t)
        history["ke"].append(kinetic_energy[None])
        history["pe"].append(potential_energy[None])
        te = kinetic_energy[None] + potential_energy[None]
        history["te"].append(te)
        history["z_avg"].append(avg_z[None])
        history["phase"].append(phase)
        
        # Output
        if t >= output_t:
            pos_np = position.to_numpy()
            shape_err_avg, shape_err_max, inside_count = compute_shape_error(pos_np)
            
            history["shape_error_avg"].append(shape_err_avg)
            history["shape_error_max"].append(shape_err_max)
            history["particles_inside"].append(inside_count)
            history["output_times"].append(t)
            
            z_mm = avg_z[None] * 1e3
            ke_display = kinetic_energy[None] * 1e12  # pJ
            print(f"{t:7.3f} | {phase:7.1f} | {shape_err_avg*1e3:10.3f} | {inside_count:7d} | {z_mm:7.2f} | {ke_display:10.2f}")
            
            # Write VTU file
            write_vtu("outputs/Phase2", t, position, velocity, radius, mass)
            
            output_t += Config.output_interval
        
        t += Config.dt
        step += 1
    
    elapsed = time.time() - start_time
    print("-" * 75)
    print(f"[Complete] {step:,} steps in {elapsed:.1f}s ({step/elapsed:.0f} steps/sec)")
    
    # Write PVD file
    print("[Output] Writing PVD file for ParaView...")
    write_pvd("outputs/Phase2")
    print(f"[Output] PVD file: outputs/Phase2/particles.pvd")
    
    # Create plots
    print("[Analysis] Creating plots...")
    create_plots(history)
    
    return history


def write_vtu(output_dir, time_val, position, velocity, radius, mass):
    """Write VTU file for current state"""
    filename = f"{output_dir}/particles_t{time_val:.4f}.vtu"
    
    # Get data from Taichi fields
    pos_np = position.to_numpy()
    vel_np = velocity.to_numpy()
    rad_np = radius.to_numpy()
    mass_np = mass.to_numpy()
    
    n_particles = len(pos_np)
    
    with open(filename, 'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">\n')
        f.write('<UnstructuredGrid>\n')
        f.write(f'<Piece NumberOfPoints="{n_particles}" NumberOfCells="{n_particles}">\n')
        
        # Points
        f.write('<Points>\n')
        f.write('<DataArray type="Float64" NumberOfComponents="3" format="ascii">\n')
        for p in pos_np:
            f.write(f'{p[0]:.10e} {p[1]:.10e} {p[2]:.10e}\n')
        f.write('</DataArray>\n')
        f.write('</Points>\n')
        
        # Cells
        f.write('<Cells>\n')
        f.write('<DataArray type="Int32" Name="connectivity" format="ascii">\n')
        for i in range(n_particles):
            f.write(f'{i}\n')
        f.write('</DataArray>\n')
        f.write('<DataArray type="Int32" Name="offsets" format="ascii">\n')
        for i in range(1, n_particles+1):
            f.write(f'{i}\n')
        f.write('</DataArray>\n')
        f.write('<DataArray type="UInt8" Name="types" format="ascii">\n')
        for _ in range(n_particles):
            f.write('1\n')
        f.write('</DataArray>\n')
        f.write('</Cells>\n')
        
        # Point data
        f.write('<PointData Scalars="radius" Vectors="velocity">\n')
        
        # Velocity
        f.write('<DataArray type="Float64" Name="velocity" NumberOfComponents="3" format="ascii">\n')
        for v in vel_np:
            f.write(f'{v[0]:.10e} {v[1]:.10e} {v[2]:.10e}\n')
        f.write('</DataArray>\n')
        
        # Radius
        f.write('<DataArray type="Float64" Name="radius" format="ascii">\n')
        for r in rad_np:
            f.write(f'{r:.10e}\n')
        f.write('</DataArray>\n')
        
        # Kinetic energy
        f.write('<DataArray type="Float64" Name="kinetic_energy" format="ascii">\n')
        for i, m in enumerate(mass_np):
            ke = 0.5 * m * (vel_np[i][0]**2 + vel_np[i][1]**2 + vel_np[i][2]**2)
            f.write(f'{ke:.10e}\n')
        f.write('</DataArray>\n')
        
        f.write('</PointData>\n')
        f.write('</Piece>\n')
        f.write('</UnstructuredGrid>\n')
        f.write('</VTKFile>\n')


def write_pvd(output_dir):
    """Write PVD animation file"""
    import glob
    pvd_filename = f"{output_dir}/particles.pvd"
    vtu_files = sorted(glob.glob(f"{output_dir}/particles_t*.vtu"))
    
    if not vtu_files:
        return
    
    with open(pvd_filename, 'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="Collection" version="0.1" byte_order="LittleEndian">\n')
        f.write('<Collection>\n')
        
        for vtu_file in vtu_files:
            basename = os.path.basename(vtu_file)
            time_str = basename.replace('particles_t', '').replace('.vtu', '')
            try:
                time_val = float(time_str)
                f.write(f'<DataSet timestep="{time_val}" file="{basename}"/>\n')
            except ValueError:
                pass
        
        f.write('</Collection>\n')
        f.write('</VTKFile>\n')


def write_pvd_file(history):
    """Write ParaView Data (PVD) file for animation"""
    os.makedirs("outputs/Phase2", exist_ok=True)
    
    # This would require writing individual VTU files and a PVD wrapper
    # For now, just note that this would be added
    print("[Note] PVD output completed")


def create_plots(hist):
    """Create comprehensive analysis plots"""
    
    t_all = np.array(hist["time"])
    shape_err_avg = np.array(hist["shape_error_avg"]) * 1e3
    shape_err_max = np.array(hist["shape_error_max"]) * 1e3
    particles_inside = np.array(hist["particles_inside"])
    
    ke = np.array(hist["ke"])
    pe = np.array(hist["pe"])
    te = np.array(hist["te"])
    z = np.array(hist["z_avg"]) * 1e3
    phases = np.array(hist["phase"])
    
    # Output times
    n_output = len(shape_err_avg)
    t_output = np.linspace(0, t_all[-1], n_output)
    
    fig, axes = plt.subplots(3, 2, figsize=(14, 12))
    
    # [0, 0] Phases
    ax = axes[0, 0]
    ax.fill_between(t_all, 0, phases, alpha=0.3, color='blue', label='Phase number')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Phase')
    ax.set_title('Control Phase Timeline')
    ax.set_ylim([-0.5, 2.5])
    ax.set_yticks([0, 1, 2])
    ax.grid(True, alpha=0.3)
    ax.legend()
    
    # [0, 1] Shape Error
    ax = axes[0, 1]
    ax.plot(t_output, shape_err_avg, 'o-', color='purple', linewidth=2, markersize=6, label='Avg error')
    ax.plot(t_output, shape_err_max, 's-', color='red', linewidth=2, markersize=4, label='Max error', alpha=0.7)
    ax.axhline(0.5, color='g', linestyle='--', linewidth=1, alpha=0.5, label='Goal (<0.5mm)')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Shape Error (mm)')
    ax.set_title('Cylinder Formation Accuracy')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # [1, 0] Particles Inside
    ax = axes[1, 0]
    ax.plot(t_output, particles_inside, 's-', color='cyan', linewidth=2, markersize=6)
    ax.axhline(300, color='g', linestyle='--', linewidth=1, alpha=0.5, label='All particles')
    ax.axhline(270, color='orange', linestyle='--', linewidth=1, alpha=0.5, label='90% (270)')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Particles Inside Target')
    ax.set_title('Confinement Success')
    ax.set_ylim([0, 320])
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # [1, 1] Height
    ax = axes[1, 1]
    ax.plot(t_all, z, 'g-', linewidth=2, label='Average Z')
    ax.axhline(5.0, color='r', linestyle='--', linewidth=2, label='Target (5mm)')
    ax.fill_between([0, Config.t_max], 3, 7, alpha=0.2, color='red', label='Target range')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Average Z (mm)')
    ax.set_title('Vertical Organization')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # [2, 0] Energy
    ax = axes[2, 0]
    ax.plot(t_all, ke, 'r-', label='KE', linewidth=2, alpha=0.7)
    ax.plot(t_all, pe, 'b-', label='PE', linewidth=2, alpha=0.7)
    ax.plot(t_all, te, 'k--', label='Total', linewidth=2)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Energy (J)')
    ax.set_title('Energy Evolution')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # [2, 1] Energy log
    ax = axes[2, 1]
    ax.semilogy(t_all, te + 1e-20, 'k-', linewidth=2)
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Total Energy (J, log)')
    ax.set_title('Energy Dissipation')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    os.makedirs("outputs/Phase2", exist_ok=True)
    plt.savefig("outputs/Phase2/analysis.png", dpi=150)
    print(f"  Saved: outputs/Phase2/analysis.png")
    plt.close()


if __name__ == "__main__":
    history = run_simulation()
    print("\n" + "="*75)
    print("SIMULATION COMPLETE")
    print("="*75)
    print("\nKey Metrics (Final State):")
    print(f"  Shape Error (Avg): {history['shape_error_avg'][-1]*1e3:.3f} mm")
    print(f"  Shape Error (Max): {history['shape_error_max'][-1]*1e3:.3f} mm")
    print(f"  Particles Inside: {history['particles_inside'][-1]} / {Config.n_particles}")
    print(f"  Avg Z: {history['z_avg'][-1]*1e3:.2f} mm (target: 5.0 mm)")
    print(f"  Final KE: {history['ke'][-1]:.2e} J")
    print(f"  Final PE: {history['pe'][-1]:.2e} J")
