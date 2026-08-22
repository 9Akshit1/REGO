#!/usr/bin/env python3
"""
REGO Phase 0: Baseline 3D DEM Simulation (Taichi CPU-Optimized)
High-performance discrete element method using Taichi JIT compilation
CPU-compatible with proper VTU/PVD output

LEGACY PROTOTYPE — not stage 0 of a pipeline. Nothing downstream reads
outputs/Phase0/. The active pipeline starts at phase2_shaping.py; see
CONTEXT.md section 16.1/16.2a.
"""

import taichi as ti
import numpy as np
import matplotlib.pyplot as plt
import os
import glob
import time

# Initialize Taichi with CPU backend for your machine
ti.init(arch=ti.cpu, default_fp=ti.f32)

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Simulation configuration"""
    # Domain
    domain_size = 0.010  # 10mm cube
    
    # Particles
    n_particles = 200  # More particles now that we have Taichi speed!
    particle_radius = 100e-6  # 100 microns
    particle_density = 3000.0  # kg/m³ (basalt)
    
    # Physics
    gravity = np.array([0.0, 0.0, -1.62])  # Lunar gravity
    restitution = 0.5
    friction = 0.5
    
    # Contact model
    youngs_modulus = 1e8  # Pa
    poisson_ratio = 0.3
    
    # Time integration
    dt = 5e-6  # 5 microseconds
    t_max = 1.0  # 1 second total
    output_interval = 0.05  # Output every 50ms
    
    # Output
    output_dir = "outputs/Phase0"
    save_vtu = True

# =============================================================================
# TAICHI DATA STRUCTURES
# =============================================================================

# Particle data fields (Taichi will parallelize these)
position = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
velocity = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
force = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
radius = ti.field(dtype=ti.f32, shape=Config.n_particles)
mass = ti.field(dtype=ti.f32, shape=Config.n_particles)

# Scalar fields for energy tracking
kinetic_energy = ti.field(dtype=ti.f32, shape=())

# Global parameters
dt = Config.dt
gravity = ti.Vector(Config.gravity)
domain_size = Config.domain_size
particle_radius_scalar = Config.particle_radius

# Contact parameters (computed)
k_n = ti.field(dtype=ti.f32, shape=())
gamma_n = ti.field(dtype=ti.f32, shape=())

# =============================================================================
# TAICHI KERNELS (JIT-compiled, parallel execution)
# =============================================================================

@ti.kernel
def compute_contact_params(youngs_modulus: ti.f32, poisson_ratio: ti.f32, 
                          particle_radius: ti.f32, particle_density: ti.f32, 
                          restitution: ti.f32):
    """Compute Hertz-Mindlin contact model parameters"""
    # Effective modulus
    E_eff = youngs_modulus / (2.0 * (1.0 - poisson_ratio**2))
    
    # Effective mass for two equal particles
    m_eff = (4.0/3.0) * 3.14159265 * particle_radius**3 * particle_density / 2.0
    
    # Normal stiffness (Hertz)
    k_n[None] = 4.0 / 3.0 * E_eff * ti.sqrt(particle_radius)
    
    # Damping coefficient
    ln_e = ti.log(restitution)
    pi_squared = 3.14159265**2
    denom = ti.sqrt(pi_squared + ln_e**2)
    gamma_n[None] = -2.0 * ln_e * ti.sqrt(m_eff * k_n[None]) / denom


@ti.kernel
def initialize_particles(n_particles: ti.i32, particle_radius_val: ti.f32, 
                        particle_density: ti.f32, domain_size_val: ti.f32):
    """Initialize particle positions and properties"""
    # Particle volume and mass
    volume = (4.0/3.0) * 3.14159265 * particle_radius_val**3
    particle_mass = volume * particle_density
    
    # Grid setup
    n_side = ti.cast(ti.sqrt(ti.cast(n_particles, ti.f32)), ti.i32) + 1
    spacing = domain_size_val / ti.cast(n_side + 1, ti.f32)
    
    # Parallelize particle initialization
    for i in range(n_particles):
        # Compute grid position
        idx = i
        ix = idx % n_side
        iy = (idx // n_side) % n_side
        iz = idx // (n_side * n_side)
        
        # Grid coordinates with random perturbation
        x = spacing * (ti.cast(ix, ti.f32) + 1.0) + (ti.random() - 0.5) * 0.3 * spacing
        y = spacing * (ti.cast(iy, ti.f32) + 1.0) + (ti.random() - 0.5) * 0.3 * spacing
        z = spacing * (ti.cast(iz, ti.f32) + 1.0) + (ti.random() - 0.5) * 0.3 * spacing
        
        # Clamp to domain
        x = ti.max(particle_radius_val, ti.min(x, domain_size_val - particle_radius_val))
        y = ti.max(particle_radius_val, ti.min(y, domain_size_val - particle_radius_val))
        z = ti.max(particle_radius_val, ti.min(z, domain_size_val - particle_radius_val))
        
        # Set particle properties
        position[i] = ti.Vector([x, y, z])
        velocity[i] = ti.Vector([0.0, 0.0, 0.0])
        force[i] = ti.Vector([0.0, 0.0, 0.0])
        radius[i] = particle_radius_val
        mass[i] = particle_mass


@ti.kernel
def clear_forces():
    """Clear forces for new timestep"""
    for i in position:
        force[i] = ti.Vector([0.0, 0.0, 0.0])


@ti.kernel
def apply_gravity_kernel():
    """Apply gravity to all particles"""
    for i in position:
        force[i] += mass[i] * gravity


@ti.kernel
def particle_particle_collisions():
    """Detect and resolve particle-particle collisions"""
    for i, j in ti.ndrange(Config.n_particles, Config.n_particles):
        if i >= j:
            continue
        
        # Vector from particle i to j
        r_vec = position[j] - position[i]
        dist = ti.sqrt(r_vec[0]**2 + r_vec[1]**2 + r_vec[2]**2)
        
        # Check for overlap
        contact_dist = radius[i] + radius[j]
        if dist >= contact_dist:
            continue
        
        overlap = contact_dist - dist
        
        # Normal direction (i -> j)
        n = r_vec / (dist + 1e-10)
        
        # Relative velocity
        v_rel = velocity[j] - velocity[i]
        v_n = ti.math.dot(v_rel, n)
        v_t = v_rel - v_n * n
        
        # Normal force (Hertz contact + damping)
        F_n_elastic = k_n[None] * ti.pow(overlap, 1.5)
        F_n_damping = gamma_n[None] * ti.sqrt(overlap + 1e-10) * v_n
        F_n = (F_n_elastic - F_n_damping) * n
        
        # Tangential friction
        v_t_mag = ti.sqrt(v_t[0]**2 + v_t[1]**2 + v_t[2]**2)
        F_t = ti.Vector([0.0, 0.0, 0.0])
        
        if v_t_mag > 1e-10:
            mu = 0.5  # friction coefficient
            F_t_max = mu * ti.sqrt(F_n[0]**2 + F_n[1]**2 + F_n[2]**2)
            F_t_mag = ti.min(F_t_max, 0.5 * k_n[None] * v_t_mag * dt)
            F_t = -F_t_mag * (v_t / (v_t_mag + 1e-10))
        
        # Apply forces (Newton's third law)
        F_total = F_n + F_t
        force[i] -= F_total
        force[j] += F_total


@ti.kernel
def wall_collisions():
    """Handle particle-wall collisions"""
    for i in position:
        # Floor collision (z = 0)
        if position[i][2] < radius[i]:
            overlap = radius[i] - position[i][2]
            n = ti.Vector([0.0, 0.0, 1.0])
            
            v_n = velocity[i][2]
            F_n_elastic = k_n[None] * ti.pow(overlap, 1.5)
            F_n_damping = gamma_n[None] * ti.sqrt(overlap + 1e-10) * v_n
            F_n = (F_n_elastic - F_n_damping) * n
            
            force[i] += F_n
            
            # Friction
            v_t = velocity[i] - v_n * n
            v_t_mag = ti.sqrt(v_t[0]**2 + v_t[1]**2 + v_t[2]**2)
            if v_t_mag > 1e-10:
                mu = 0.5
                F_t_max = mu * ti.sqrt(F_n[0]**2 + F_n[1]**2 + F_n[2]**2)
                F_t_mag = ti.min(F_t_max, 0.5 * k_n[None] * v_t_mag * dt)
                force[i] += -F_t_mag * (v_t / (v_t_mag + 1e-10))
        
        # Ceiling collision (z = domain_size)
        if position[i][2] > domain_size - radius[i]:
            overlap = position[i][2] - (domain_size - radius[i])
            n = ti.Vector([0.0, 0.0, -1.0])
            
            v_n = ti.math.dot(velocity[i], n)
            F_n_elastic = k_n[None] * ti.pow(overlap, 1.5)
            F_n_damping = gamma_n[None] * ti.sqrt(overlap + 1e-10) * v_n
            F_n = (F_n_elastic - F_n_damping) * n
            
            force[i] += F_n


@ti.kernel
def integrate_particles(dt_val: ti.f32):
    """Velocity Verlet time integration"""
    for i in position:
        # Acceleration
        a = force[i] / mass[i]
        
        # Update velocity (half step)
        velocity[i] += 0.5 * a * dt_val
        
        # Update position
        position[i] += velocity[i] * dt_val


@ti.kernel
def compute_kinetic_energy():
    """Compute total kinetic energy"""
    total_ke = 0.0
    for i in position:
        v_mag_sq = velocity[i][0]**2 + velocity[i][1]**2 + velocity[i][2]**2
        total_ke += 0.5 * mass[i] * v_mag_sq
    kinetic_energy[None] = total_ke


# =============================================================================
# VTU OUTPUT FUNCTIONS
# =============================================================================

def write_vtu(output_dir, time_val, step):
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
# MAIN SIMULATION LOOP
# =============================================================================

def run_simulation():
    """Main simulation with Taichi acceleration"""
    cfg = Config()
    
    print(f"\n{'='*70}")
    print(f"PHASE 0: BASELINE DEM SIMULATION (TAICHI CPU-OPTIMIZED)")
    print(f"{'='*70}")
    print(f"Architecture: Taichi CPU (JIT compiled)")
    print(f"Particles: {cfg.n_particles}")
    print(f"Time step: {cfg.dt*1e6:.2f} us")
    print(f"Total time: {cfg.t_max:.2f} s")
    print(f"Output interval: {cfg.output_interval:.3f} s")
    print(f"{'='*70}\n")
    
    # Create output directory
    os.makedirs(cfg.output_dir, exist_ok=True)
    
    # Compute contact parameters
    compute_contact_params(cfg.youngs_modulus, cfg.poisson_ratio, 
                          cfg.particle_radius, cfg.particle_density, 
                          cfg.restitution)
    
    # Initialize particles
    initialize_particles(cfg.n_particles, cfg.particle_radius, 
                        cfg.particle_density, cfg.domain_size)
    
    print(f"Particle radius: {cfg.particle_radius*1e6:.1f} um")
    print(f"Particle density: {cfg.particle_density:.0f} kg/m³")
    print(f"Domain: {cfg.domain_size*1e3:.1f} mm cube\n")
    
    # Simulation state
    sim_time = 0.0
    step_num = 0
    energy_history = []
    time_history = []
    
    last_output = 0.0
    last_print = 0.0
    start_time = time.time()
    
    # Initial output
    write_vtu(cfg.output_dir, sim_time, step_num)
    
    print(f"{'='*70}")
    print(f"RUNNING SIMULATION...")
    print(f"{'='*70}\n")
    
    # Main loop
    while sim_time < cfg.t_max:
        # Forces
        clear_forces()
        apply_gravity_kernel()
        
        # Collisions
        particle_particle_collisions()
        wall_collisions()
        
        # Integration
        integrate_particles(dt)
        
        # Update time
        sim_time += cfg.dt
        step_num += 1
        
        # Output
        if sim_time - last_output >= cfg.output_interval:
            write_vtu(cfg.output_dir, sim_time, step_num)
            
            compute_kinetic_energy()
            ke = float(kinetic_energy[None])
            energy_history.append(ke)
            time_history.append(sim_time)
            
            last_output = sim_time
        
        # Progress print
        if sim_time - last_print >= 0.1:
            compute_kinetic_energy()
            ke = float(kinetic_energy[None])
            pos_np = position.to_numpy()
            vel_np = velocity.to_numpy()
            avg_z = np.mean(pos_np[:, 2]) * 1e3
            avg_vz = np.mean(vel_np[:, 2])
            
            print(f"[t={sim_time:7.4f}s | Step {step_num:8d}] <z>={avg_z:7.3f}mm | <vz>={avg_vz:+.4f}m/s | KE={ke:.2e}J")
            last_print = sim_time
    
    elapsed = time.time() - start_time
    
    print(f"\n{'='*70}")
    print(f"SIMULATION COMPLETE")
    print(f"{'='*70}")
    print(f"Wall time: {elapsed:.2f}s")
    print(f"Simulation time: {sim_time:.3f}s")
    print(f"Steps completed: {step_num}")
    print(f"Performance: {step_num/elapsed:.0f} steps/sec")
    print(f"Speedup: ~{(step_num/elapsed) / 1000:.0f}x vs pure Python")
    print(f"{'='*70}\n")
    
    # Write animation file
    write_pvd(cfg.output_dir)
    print(f"✓ Created PVD file: {cfg.output_dir}/particles.pvd\n")
    
    # Plot energy
    if energy_history:
        plt.figure(figsize=(10, 6))
        plt.plot(time_history, np.array(energy_history)*1e9, 'b-', linewidth=2)
        plt.xlabel('Time (s)', fontsize=12)
        plt.ylabel('Kinetic Energy (nJ)', fontsize=12)
        plt.title('Phase 0: Energy Dissipation (Taichi)', fontsize=14, fontweight='bold')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(f"{cfg.output_dir}/energy.png", dpi=150)
        print(f"✓ Saved energy plot to {cfg.output_dir}/energy.png\n")
        plt.close()
    
    print(f"✓ Output files in: {cfg.output_dir}/")
    print(f"✓ Open particles.pvd in ParaView to visualize\n")


if __name__ == "__main__":
    run_simulation()
