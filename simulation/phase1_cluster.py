#!/usr/bin/env python3
"""
REGO Phase 1: Magnetic Manipulation (Taichi CPU-Optimized)
DEM with magnetic field forces using JIT compilation
Particles are attracted upward by a magnetic dipole source

LEGACY / DISCONNECTED PROTOTYPE — not part of the active pipeline.
The real "Phase 1" (clustering) that every downstream stage actually uses
is the `cluster` state inside phase2_shaping.py's own PhaseManager — see
CONTEXT.md section 16.2a. This file simulates a different particle count
(N=200 vs 256), a different config (f32, single crude overhead dipole
instead of 4 anti-aligned corner pairs), and writes to outputs/Phase1/,
which nothing downstream reads. Kept for historical reference only.
"""

import taichi as ti
import numpy as np
import matplotlib.pyplot as plt
import os
import glob
import time

# CPU backend for your machine
ti.init(arch=ti.cpu, default_fp=ti.f32)

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Simulation configuration with magnetic parameters"""
    # Domain
    domain_size = 0.010  # 10mm cube
    
    # Particles
    n_particles = 200
    particle_radius = 100e-6  # 100 micrometers
    particle_density = 3000.0  # kg/m^3 (basalt)
    
    # Physics
    gravity = np.array([0.0, 0.0, -1.62])  # Lunar gravity
    restitution = 0.5  # coefficient of restitution
    friction = 0.5  # friction coefficient
    youngs_modulus = 1e8  # Pa
    poisson_ratio = 0.3
    
    # Magnetic parameters
    chi = 0.2  # Magnetic susceptibility scaling factor
    B0 = 10.0   # Field strength at reference (Tesla)
    R0 = 2.0e-3  # Reference distance (m) - 2mm for stability
    source_height = 0.5e-3  # Magnetic source 0.5mm above domain top
    
    # Timeline
    dt = 5e-6   # 5 microsecond timestep
    t_max = 1.2  # Total simulation time (seconds)
    settle_time = 0.2  # Time to settle before activating field
    ramp_start = 0.2   # When to start ramping magnetic field
    ramp_duration = 0.4  # Duration of ramp (0.2s to 0.6s)
    output_interval = 0.05  # Output every 50ms
    
    # Output
    output_dir = "outputs/Phase1"

# =============================================================================
# TAICHI FIELDS
# =============================================================================

# Particle state
position = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
velocity = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
force = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
radius = ti.field(dtype=ti.f32, shape=Config.n_particles)
mass = ti.field(dtype=ti.f32, shape=Config.n_particles)

# Magnetic force tracking (for output analysis)
magnetic_force = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)

# Scalars
kinetic_energy = ti.field(dtype=ti.f32, shape=())

# Parameters as global scalars for kernel access
dt = Config.dt
gravity = ti.Vector(Config.gravity)
domain_size = Config.domain_size
particle_radius_scalar = Config.particle_radius
chi = Config.chi
B0 = Config.B0
R0 = Config.R0
ramp_start = Config.ramp_start
ramp_duration = Config.ramp_duration
source_height = Config.source_height
domain_center_xy = Config.domain_size / 2.0

# Contact parameters (computed at startup)
k_n = ti.field(dtype=ti.f32, shape=())
gamma_n = ti.field(dtype=ti.f32, shape=())

MU0 = 4.0 * np.pi * 1e-7  # Vacuum permeability

# =============================================================================
# TAICHI KERNELS
# =============================================================================

@ti.kernel
def compute_contact_params(youngs_modulus: ti.f32, poisson_ratio: ti.f32,
                           particle_radius: ti.f32, particle_density: ti.f32,
                           restitution: ti.f32):
    """Compute Hertz-Mindlin contact parameters"""
    E_eff = youngs_modulus / (2.0 * (1.0 - poisson_ratio**2))
    m_eff = (4.0/3.0) * 3.14159265 * particle_radius**3 * particle_density / 2.0
    k_n[None] = 4.0 / 3.0 * E_eff * ti.sqrt(particle_radius)
    
    ln_e = ti.log(restitution + 1e-10)
    pi_sq = 3.14159265**2
    gamma_n[None] = -2.0 * ln_e * ti.sqrt(m_eff * k_n[None]) / ti.sqrt(pi_sq + ln_e**2)


@ti.kernel
def initialize_particles(n_particles: ti.i32, particle_radius_val: ti.f32,
                         particle_density: ti.f32, domain_size_val: ti.f32):
    """Initialize particles in regular grid with random perturbation"""
    volume = (4.0/3.0) * 3.14159265 * particle_radius_val**3
    particle_mass = volume * particle_density
    
    # Calculate grid spacing
    n_side = ti.cast(ti.sqrt(ti.cast(n_particles, ti.f32)), ti.i32) + 1
    spacing = domain_size_val / ti.cast(n_side + 1, ti.f32)
    
    # Initialize particles
    for i in range(n_particles):
        idx = i
        ix = idx % n_side
        iy = (idx // n_side) % n_side
        iz = idx // (n_side * n_side)
        
        # Grid position with random perturbation
        x = spacing * (ti.cast(ix, ti.f32) + 1.0) + (ti.random() - 0.5) * 0.3 * spacing
        y = spacing * (ti.cast(iy, ti.f32) + 1.0) + (ti.random() - 0.5) * 0.3 * spacing
        z = spacing * (ti.cast(iz, ti.f32) + 1.0) + (ti.random() - 0.5) * 0.3 * spacing
        
        # Clamp to domain boundaries
        x = ti.max(particle_radius_val, ti.min(x, domain_size_val - particle_radius_val))
        y = ti.max(particle_radius_val, ti.min(y, domain_size_val - particle_radius_val))
        z = ti.max(particle_radius_val, ti.min(z, domain_size_val - particle_radius_val))
        
        position[i] = ti.Vector([x, y, z])
        velocity[i] = ti.Vector([0.0, 0.0, 0.0])
        force[i] = ti.Vector([0.0, 0.0, 0.0])
        magnetic_force[i] = ti.Vector([0.0, 0.0, 0.0])
        radius[i] = particle_radius_val
        mass[i] = particle_mass


@ti.kernel
def clear_forces():
    """Clear all forces"""
    for i in position:
        force[i] = ti.Vector([0.0, 0.0, 0.0])
        magnetic_force[i] = ti.Vector([0.0, 0.0, 0.0])


@ti.kernel
def apply_gravity():
    """Apply gravitational force"""
    for i in position:
        force[i] += mass[i] * gravity


@ti.kernel
def apply_magnetic_forces(sim_time: ti.f32):
    """
    Compute and apply magnetic forces from dipole source
    This kernel combines computation and application of magnetic forces
    """
    # Magnetic source position (above domain center)
    source_x = domain_center_xy
    source_y = domain_center_xy
    source_z = domain_size + source_height
    
    # Calculate ramp factor (0 to 1 over ramp duration)
    ramp = ti.f32(0.0)
    if sim_time >= ramp_start:
        if sim_time < ramp_start + ramp_duration:
            ramp = (sim_time - ramp_start) / ramp_duration
        else:
            ramp = ti.f32(1.0)
    
    # Apply magnetic force to each particle
    for i in position:
        if ramp <= 0.0:
            magnetic_force[i] = ti.Vector([0.0, 0.0, 0.0])
        else:
            # Vector from particle to source
            r_x = source_x - position[i][0]
            r_y = source_y - position[i][1]
            r_z = source_z - position[i][2]
            
            dist = ti.sqrt(r_x**2 + r_y**2 + r_z**2)
            
            # Avoid singularity at source
            if dist > particle_radius_scalar * 3.0:
                # Dipole field: B ~ B0 * (R0/r)^3
                B_mag = B0 * ramp * ti.pow(R0 / dist, 3.0)
                
                # Field gradient: simpler stable form
                # F prop to B * dB/dr, where dB/dr ~ -3*B/r
                # So F ~ chi*V*B^2/r / mu0
                # Simplified to avoid numerical blow-up
                grad_B_mag = 3.0 * B_mag / dist
                
                # Unit vector from particle toward source
                r_hat_x = r_x / dist
                r_hat_y = r_y / dist
                r_hat_z = r_z / dist
                
                # Particle volume
                V = (4.0/3.0) * 3.14159265 * particle_radius_scalar**3
                
                # Magnetic force: simplified stable form
                # F = chi * V * B^2 / (mu0 * r^2) - avoids gradient singularity
                F_mag_mag = chi * V * B_mag * B_mag / (MU0 * dist * dist + 1e-15)
                
                # Cap force to prevent instability
                max_force = mass[i] * 10.0  # Max 10x particle weight
                if F_mag_mag > max_force:
                    F_mag_mag = max_force
                
                magnetic_force[i] = ti.Vector([
                    F_mag_mag * r_hat_x,
                    F_mag_mag * r_hat_y,
                    F_mag_mag * r_hat_z
                ])
                
                force[i] += magnetic_force[i]
            else:
                magnetic_force[i] = ti.Vector([0.0, 0.0, 0.0])


@ti.kernel
def particle_collisions():
    """Detect and resolve particle-particle collisions using Hertz-Mindlin"""
    for i, j in ti.ndrange(Config.n_particles, Config.n_particles):
        if i >= j:
            continue
        
        # Relative position
        r_vec = position[j] - position[i]
        dist = ti.sqrt(r_vec[0]**2 + r_vec[1]**2 + r_vec[2]**2)
        
        # Contact distance
        contact_dist = radius[i] + radius[j]
        if dist >= contact_dist:
            continue
        
        # Overlap
        overlap = contact_dist - dist
        n = r_vec / (dist + 1e-10)
        
        # Relative velocity
        v_rel = velocity[j] - velocity[i]
        v_n = v_rel[0]*n[0] + v_rel[1]*n[1] + v_rel[2]*n[2]
        v_t = v_rel - v_n * n
        
        # Normal force (elastic + damping)
        F_n_elastic = k_n[None] * ti.pow(overlap, 1.5)
        F_n_damping = gamma_n[None] * ti.sqrt(overlap + 1e-10) * v_n
        F_n = (F_n_elastic - F_n_damping) * n
        
        # Tangential friction
        v_t_mag = ti.sqrt(v_t[0]**2 + v_t[1]**2 + v_t[2]**2)
        F_t = ti.Vector([0.0, 0.0, 0.0])
        
        if v_t_mag > 1e-10:
            mu = 0.5
            F_t_max = mu * ti.sqrt(F_n[0]**2 + F_n[1]**2 + F_n[2]**2)
            F_t_mag = ti.min(F_t_max, 0.5 * k_n[None] * v_t_mag * dt)
            F_t = -F_t_mag * (v_t / (v_t_mag + 1e-10))
        
        # Apply forces (Newton's third law)
        F_total = F_n + F_t
        force[i] -= F_total
        force[j] += F_total


@ti.kernel
def wall_collisions():
    """Handle particle-wall collisions (floor at z=0, ceiling at z=domain_size)"""
    for i in position:
        # Floor collision
        if position[i][2] < radius[i]:
            overlap = radius[i] - position[i][2]
            n = ti.Vector([0.0, 0.0, 1.0])
            
            v_n = velocity[i][2]
            F_n_elastic = k_n[None] * ti.pow(overlap, 1.5)
            F_n_damping = gamma_n[None] * ti.sqrt(overlap + 1e-10) * v_n
            F_n = (F_n_elastic - F_n_damping) * n
            
            force[i] += F_n
            
            v_t = velocity[i] - v_n * n
            v_t_mag = ti.sqrt(v_t[0]**2 + v_t[1]**2 + v_t[2]**2)
            if v_t_mag > 1e-10:
                mu = 0.5
                F_t_max = mu * ti.sqrt(F_n[0]**2 + F_n[1]**2 + F_n[2]**2)
                F_t_mag = ti.min(F_t_max, 0.5 * k_n[None] * v_t_mag * dt)
                force[i] += -F_t_mag * (v_t / (v_t_mag + 1e-10))
        
        # Ceiling collision
        if position[i][2] + radius[i] > domain_size:
            overlap = position[i][2] + radius[i] - domain_size
            n = ti.Vector([0.0, 0.0, -1.0])
            
            v_n = velocity[i][2]
            F_n_elastic = k_n[None] * ti.pow(overlap, 1.5)
            F_n_damping = gamma_n[None] * ti.sqrt(overlap + 1e-10) * v_n
            F_n = (F_n_elastic - F_n_damping) * n
            
            force[i] += F_n


@ti.kernel
def integrate_particles(dt_val: ti.f32):
    """Velocity Verlet integration"""
    for i in position:
        a = force[i] / mass[i]
        velocity[i] += 0.5 * a * dt_val
        position[i] += velocity[i] * dt_val


@ti.kernel
def compute_kinetic_energy():
    """Calculate total kinetic energy"""
    total = ti.f32(0.0)
    for i in position:
        v_sq = velocity[i][0]**2 + velocity[i][1]**2 + velocity[i][2]**2
        total += 0.5 * mass[i] * v_sq
    kinetic_energy[None] = total


# =============================================================================
# OUTPUT FUNCTIONS
# =============================================================================

def write_vtu(output_dir, time_val):
    """Write VTU file with magnetic force data"""
    filename = f"{output_dir}/particles_t{time_val:.4f}.vtu"
    
    pos_np = position.to_numpy()
    vel_np = velocity.to_numpy()
    mag_np = magnetic_force.to_numpy()
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
        
        # Cells (vertices)
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
        f.write('<PointData Scalars="kinetic_energy" Vectors="velocity">\n')
        
        # Velocity vector
        f.write('<DataArray type="Float64" Name="velocity" NumberOfComponents="3" format="ascii">\n')
        for v in vel_np:
            f.write(f'{v[0]:.10e} {v[1]:.10e} {v[2]:.10e}\n')
        f.write('</DataArray>\n')
        
        # Magnetic force vector
        f.write('<DataArray type="Float64" Name="magnetic_force" NumberOfComponents="3" format="ascii">\n')
        for m in mag_np:
            f.write(f'{m[0]:.10e} {m[1]:.10e} {m[2]:.10e}\n')
        f.write('</DataArray>\n')
        
        # Magnetic force magnitude
        f.write('<DataArray type="Float64" Name="magnetic_force_magnitude" format="ascii">\n')
        for m in mag_np:
            mag = np.sqrt(m[0]**2 + m[1]**2 + m[2]**2)
            f.write(f'{mag:.10e}\n')
        f.write('</DataArray>\n')
        
        # Kinetic energy per particle
        f.write('<DataArray type="Float64" Name="kinetic_energy" format="ascii">\n')
        for i, m in enumerate(mass_np):
            ke = 0.5 * m * (vel_np[i][0]**2 + vel_np[i][1]**2 + vel_np[i][2]**2)
            f.write(f'{ke:.10e}\n')
        f.write('</DataArray>\n')
        
        # Particle radius
        f.write('<DataArray type="Float64" Name="radius" format="ascii">\n')
        for r in rad_np:
            f.write(f'{r:.10e}\n')
        f.write('</DataArray>\n')
        
        f.write('</PointData>\n')
        f.write('</Piece>\n')
        f.write('</UnstructuredGrid>\n')
        f.write('</VTKFile>\n')


def write_pvd(output_dir):
    """Write PVD animation metadata file"""
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


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def run_magnetic_simulation():
    """Execute Phase 1 magnetic manipulation simulation"""
    cfg = Config()
    
    print(f"\n{'='*70}")
    print(f"PHASE 1: MAGNETIC MANIPULATION (TAICHI CPU-OPTIMIZED)")
    print(f"{'='*70}")
    print(f"Architecture: Taichi CPU (JIT compiled)")
    print(f"Particles: {cfg.n_particles}")
    print(f"Magnetic field strength: {cfg.B0:.1f} T")
    print(f"Susceptibility chi: {cfg.chi}")
    print(f"Timeline:")
    print(f"  Settle: 0.0 -> {cfg.settle_time:.1f}s")
    print(f"  Ramp: {cfg.ramp_start:.1f}s -> {cfg.ramp_start + cfg.ramp_duration:.1f}s")
    print(f"  Full field: {cfg.ramp_start + cfg.ramp_duration:.1f}s -> {cfg.t_max:.1f}s")
    print(f"{'='*70}\n")
    
    os.makedirs(cfg.output_dir, exist_ok=True)
    
    # Compute contact parameters
    compute_contact_params(cfg.youngs_modulus, cfg.poisson_ratio,
                           cfg.particle_radius, cfg.particle_density,
                           cfg.restitution)
    
    # Initialize particles
    initialize_particles(cfg.n_particles, cfg.particle_radius,
                         cfg.particle_density, cfg.domain_size)
    
    print(f"Particle radius: {cfg.particle_radius*1e6:.1f} um")
    print(f"Particle density: {cfg.particle_density:.0f} kg/m^3")
    print(f"Domain: {cfg.domain_size*1e3:.1f} mm cube")
    print(f"Magnetic source: {cfg.source_height*1e3:.2f} mm above domain\n")
    
    # Simulation state
    sim_time = 0.0
    step_num = 0
    initial_height = None
    energy_history = []
    time_history = []
    height_history = []
    max_mag_force_history = []
    
    last_output = 0.0
    last_print = 0.0
    start_time = time.time()
    
    # Initial output
    write_vtu(cfg.output_dir, sim_time)
    
    print(f"{'='*70}")
    print(f"RUNNING MAGNETIC SIMULATION...")
    print(f"{'='*70}\n")
    
    # Main simulation loop
    while sim_time < cfg.t_max:
        # Forces
        clear_forces()
        apply_gravity()
        apply_magnetic_forces(sim_time)
        
        # Collisions
        particle_collisions()
        wall_collisions()
        
        # Integration
        integrate_particles(dt)
        
        sim_time += cfg.dt
        step_num += 1
        
        # Output
        if sim_time - last_output >= cfg.output_interval:
            write_vtu(cfg.output_dir, sim_time)
            
            compute_kinetic_energy()
            ke = float(kinetic_energy[None])
            energy_history.append(ke)
            time_history.append(sim_time)
            
            pos_np = position.to_numpy()
            mag_np = magnetic_force.to_numpy()
            
            avg_z = np.mean(pos_np[:, 2])
            height_history.append(avg_z)
            
            max_mag_force = np.max(np.linalg.norm(mag_np, axis=1))
            max_mag_force_history.append(max_mag_force)
            
            if initial_height is None and sim_time > cfg.ramp_start - 0.01:
                initial_height = avg_z
            
            last_output = sim_time
        
        # Progress print
        if sim_time - last_print >= 0.1:
            compute_kinetic_energy()
            ke = float(kinetic_energy[None])
            pos_np = position.to_numpy()
            vel_np = velocity.to_numpy()
            mag_np = magnetic_force.to_numpy()
            
            avg_z = np.mean(pos_np[:, 2])
            avg_vz = np.mean(vel_np[:, 2])
            max_mag_force = np.max(np.linalg.norm(mag_np, axis=1))
            
            # Ramp factor
            ramp = 0.0
            if sim_time >= cfg.ramp_start:
                if sim_time < cfg.ramp_start + cfg.ramp_duration:
                    ramp = (sim_time - cfg.ramp_start) / cfg.ramp_duration
                else:
                    ramp = 1.0
            
            rise = (avg_z - initial_height) * 1e3 if initial_height else 0.0
            
            print(f"[t={sim_time:7.4f}s] Ramp={ramp*100:3.0f}% | <z>={avg_z*1e3:6.3f}mm | Rise={rise:+7.3f}mm | <vz>={avg_vz:+.4f}m/s | MaxF={max_mag_force:.2e}N")
            last_print = sim_time
    
    elapsed = time.time() - start_time
    
    print(f"\n{'='*70}")
    print(f"SIMULATION COMPLETE")
    print(f"{'='*70}")
    print(f"Wall time: {elapsed:.2f}s")
    print(f"Steps: {step_num} ({step_num/elapsed:.0f} steps/sec)")
    print(f"{'='*70}\n")
    
    # Results
    if initial_height and height_history:
        final_height = height_history[-1]
        final_rise = (final_height - initial_height) * 1e3
        
        print(f"{'='*70}")
        print(f"MAGNETIC LIFTING RESULTS:")
        print(f"{'='*70}")
        print(f"  Initial height: {initial_height*1e3:.4f} mm")
        print(f"  Final height:   {final_height*1e3:.4f} mm")
        print(f"  Net rise:       {final_rise:+.4f} mm")
        print(f"  Max mag force:  {max(max_mag_force_history):.2e} N")
        
        if final_rise > 0.001:
            print(f"\n  SUCCESS! Lifted {final_rise:.4f}mm against lunar gravity")
        else:
            print(f"\n  Check: Lift {final_rise:.4f}mm (may need stronger field)")
        print(f"{'='*70}\n")
    
    # Write animation file
    write_pvd(cfg.output_dir)
    print(f"Success! Created PVD file: {cfg.output_dir}/particles.pvd\n")
    
    # Generate analysis plots
    if energy_history:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # Energy
        ax = axes[0, 0]
        ax.plot(time_history, np.array(energy_history)*1e9, 'b-', linewidth=2)
        ax.axvline(cfg.ramp_start, color='r', linestyle='--', alpha=0.5, label='Ramp start')
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Kinetic Energy (nJ)')
        ax.set_title('Energy Evolution')
        ax.grid(True, alpha=0.3)
        ax.legend()
        
        # Height
        ax = axes[0, 1]
        height_mm = np.array(height_history) * 1e3
        ax.plot(time_history, height_mm, 'g-', linewidth=2)
        ax.axvline(cfg.ramp_start, color='r', linestyle='--', alpha=0.5)
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Height (mm)')
        ax.set_title('Average Particle Height')
        ax.grid(True, alpha=0.3)
        
        # Rise (cumulative)
        ax = axes[1, 0]
        if initial_height:
            rise = (height_mm - initial_height*1e3)
            ax.plot(time_history, rise, 'purple', linewidth=2)
            ax.axhline(0, color='k', linestyle='-', alpha=0.3)
            ax.axvline(cfg.ramp_start, color='r', linestyle='--', alpha=0.5)
            ax.set_xlabel('Time (s)')
            ax.set_ylabel('Rise (mm)')
            ax.set_title('Cumulative Rise vs Settling Height')
            ax.grid(True, alpha=0.3)
        
        # Magnetic force
        ax = axes[1, 1]
        ax.semilogy(time_history, max_mag_force_history, 'orange', linewidth=2)
        ax.axvline(cfg.ramp_start, color='r', linestyle='--', alpha=0.5)
        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Max Magnetic Force (N)')
        ax.set_title('Maximum Magnetic Force')
        ax.grid(True, alpha=0.3, which='both')
        
        plt.tight_layout()
        plt.savefig(f"{cfg.output_dir}/analysis.png", dpi=150)
        print(f"Saved analysis plots: {cfg.output_dir}/analysis.png\n")
        plt.close()
    
    print(f"All output files: {cfg.output_dir}/")
    print(f"View animation: Open particles.pvd in ParaView\n")


if __name__ == "__main__":
    run_magnetic_simulation()
