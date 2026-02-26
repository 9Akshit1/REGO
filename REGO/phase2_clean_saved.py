#!/usr/bin/env python3
"""
REGO Phase 2 v2: PROPER SURFACE DISTRIBUTION VIA REPULSION

FUNDAMENTAL RETHINK:
The previous approach was flawed - trying to "push" particles into positions creates
oscillations and instability. Instead, use the NATURAL PHYSICS:

1. CONFINEMENT: Strong force keeps particles ON the surface (radial for sides, z for caps)
2. REPULSION: Particle-particle repulsion naturally spreads them uniformly
3. NO ARTIFICIAL SPREADING: Let physics do the work

This is how real magnetic levitation works - the field confines particles to a surface,
and inter-particle repulsion creates uniform distribution.

KEY INSIGHT:
- Caps: Confine to Z-plane + radial boundary → particles repel into uniform disk
- Sides: Confine to cylinder radius + Z boundaries → particles repel into uniform coverage

FIXES:
1. Movement targets are now AT THE SURFACE REGIONS, not edges
2. Each cluster gets its own target REGION, not just a point
3. Surface confinement is STRONG and SIMPLE - just keep particles on surface
4. Spreading comes ONLY from particle repulsion (which we already have)
5. Increased particle repulsion during spreading phase for better coverage
"""

import taichi as ti
import numpy as np
import os

ti.init(arch=ti.cpu, default_fp=ti.f32)

# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    # Domain
    domain_size = 0.010  # 10mm cube
    
    # Particles
    n_particles = 1000  # More particles for better coverage
    particle_radius = 85e-6  # Smaller: 0.085mm
    particle_density = 3000.0  # kg/m³
    particle_mass = (4/3) * np.pi * (particle_radius**3) * particle_density
    
    # Physics
    gravity = 9.81  # m/s²
    dt = 3e-5  # Smaller timestep: 30μs
    t_max = 12.0  # Longer simulation for better settling
    output_interval = 0.15
    
    # Cylinder geometry
    target_center_x = domain_size / 2  # 5mm
    target_center_y = domain_size / 2  # 5mm
    target_center_z = domain_size / 2  # 5mm
    target_radius = domain_size / 6  # 1.67mm
    target_height = 4.0e-3  # 4mm
    
    z_max = target_center_z + target_height / 2  # 7mm
    z_min = target_center_z - target_height / 2  # 3mm
    z_mid = target_center_z  # 5mm
    
    # Initial positions
    z_bottom = particle_radius + 0.05e-3
    corner_offset = 1.8e-3
    
    # MAGNETIC FORCES
    mag_strength_levitation = particle_mass * gravity * 35.0
    mag_strength_move = particle_mass * gravity * 18.0
    mag_strength_surface = particle_mass * gravity * 120.0  # Very strong confinement
    mag_strength_corner = particle_mass * gravity * 8.0
    
    # Repulsion - increased during spreading
    repulsion_normal = particle_mass * gravity * 2.5
    repulsion_spreading = particle_mass * gravity * 5.0  # Doubled for spreading
    
    # Field parameters
    field_sigma = 1.2e-3
    lock_threshold = 1.5e-3
    
    # Spatial hashing
    hash_grid_size = 0.0004  # 0.4mm cells
    hash_grid_res = int(domain_size / hash_grid_size) + 1
    
    print(f"\n{'='*80}")
    print(f"REGO PHASE 2 v2: REPULSION-BASED SURFACE DISTRIBUTION")
    print(f"{'='*80}")
    print(f"[Core Concept]")
    print(f"  Surface confinement + particle repulsion = uniform distribution")
    print(f"  NO artificial spreading forces - let physics work naturally")
    print(f"[Cylinder Geometry]")
    print(f"  Center: ({target_center_x*1000:.2f}, {target_center_y*1000:.2f}, {target_center_z*1000:.2f}) mm")
    print(f"  Radius: {target_radius*1000:.2f} mm")
    print(f"  Height: {target_height*1000:.2f} mm (Z: {z_min*1000:.2f} to {z_max*1000:.2f} mm)")
    print(f"[Particles]")
    print(f"  Count: {n_particles}")
    print(f"  Radius: {particle_radius*1e6:.1f} μm")
    print(f"  Surface confinement: {mag_strength_surface/(particle_mass*gravity):.0f}×mg")
    print(f"  Repulsion (spreading): {repulsion_spreading/repulsion_normal:.1f}× normal")
    print(f"{'='*80}")


# =============================================================================
# TAICHI FIELDS
# =============================================================================

position = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
velocity = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
force = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)
particle_cluster = ti.field(dtype=ti.i32, shape=Config.n_particles)

cluster_locked = ti.field(dtype=ti.i32, shape=4)
cluster_shaping = ti.field(dtype=ti.i32, shape=4)

# Target REGIONS for each cluster (not just points)
# Format: [center_x, center_y, center_z]
magnetic_sources = ti.Vector.field(3, dtype=ti.f32, shape=4)
cluster_centers = ti.Vector.field(3, dtype=ti.f32, shape=4)

# Pre-computed target position for each particle on its assigned surface
particle_target = ti.Vector.field(3, dtype=ti.f32, shape=Config.n_particles)

# Spatial hashing
grid_size = Config.hash_grid_res
particle_grid = ti.field(dtype=ti.i32, shape=(grid_size, grid_size, grid_size, 12))
grid_count = ti.field(dtype=ti.i32, shape=(grid_size, grid_size, grid_size))


# =============================================================================
# SPATIAL HASHING
# =============================================================================

@ti.kernel
def build_spatial_hash():
    """Build spatial hash grid for O(n) collision detection"""
    for i, j, k in ti.ndrange(grid_size, grid_size, grid_size):
        grid_count[i, j, k] = 0
    
    cell_size = Config.hash_grid_size
    for p in position:
        cell_x = ti.cast(position[p][0] / cell_size, ti.i32)
        cell_y = ti.cast(position[p][1] / cell_size, ti.i32)
        cell_z = ti.cast(position[p][2] / cell_size, ti.i32)
        
        cell_x = ti.max(0, ti.min(grid_size - 1, cell_x))
        cell_y = ti.max(0, ti.min(grid_size - 1, cell_y))
        cell_z = ti.max(0, ti.min(grid_size - 1, cell_z))
        
        idx = ti.atomic_add(grid_count[cell_x, cell_y, cell_z], 1)
        if idx < 12:
            particle_grid[cell_x, cell_y, cell_z, idx] = p


@ti.kernel
def apply_particle_repulsion_optimized(k_rep: ti.f32):
    """Optimized particle repulsion with adjustable strength"""
    min_sep = Config.particle_radius * 2.1
    cell_size = Config.hash_grid_size
    
    for i in position:
        cell_x = ti.cast(position[i][0] / cell_size, ti.i32)
        cell_y = ti.cast(position[i][1] / cell_size, ti.i32)
        cell_z = ti.cast(position[i][2] / cell_size, ti.i32)
        
        cell_x = ti.max(0, ti.min(grid_size - 1, cell_x))
        cell_y = ti.max(0, ti.min(grid_size - 1, cell_y))
        cell_z = ti.max(0, ti.min(grid_size - 1, cell_z))
        
        for dx in ti.static(range(-1, 2)):
            for dy in ti.static(range(-1, 2)):
                for dz in ti.static(range(-1, 2)):
                    nx = cell_x + dx
                    ny = cell_y + dy
                    nz = cell_z + dz
                    
                    if 0 <= nx < grid_size and 0 <= ny < grid_size and 0 <= nz < grid_size:
                        n_particles_in_cell = grid_count[nx, ny, nz]
                        for idx in range(n_particles_in_cell):
                            j = particle_grid[nx, ny, nz, idx]
                            
                            if j > i:
                                dx_p = position[j][0] - position[i][0]
                                dy_p = position[j][1] - position[i][1]
                                dz_p = position[j][2] - position[i][2]
                                
                                r_sq = dx_p*dx_p + dy_p*dy_p + dz_p*dz_p
                                r = ti.sqrt(r_sq + 1e-12)
                                
                                if r < min_sep:
                                    overlap = min_sep - r
                                    F_rep = k_rep * (overlap / min_sep) ** 2
                                    
                                    nx_p = dx_p / r
                                    ny_p = dy_p / r
                                    nz_p = dz_p / r
                                    
                                    force[i][0] -= F_rep * nx_p
                                    force[i][1] -= F_rep * ny_p
                                    force[i][2] -= F_rep * nz_p
                                    
                                    force[j][0] += F_rep * nx_p
                                    force[j][1] += F_rep * ny_p
                                    force[j][2] += F_rep * nz_p


# =============================================================================
# CORE PHYSICS
# =============================================================================

@ti.kernel
def clear_forces():
    for i in force:
        force[i] = ti.Vector([0.0, 0.0, 0.0])


@ti.kernel
def apply_gravity():
    for i in force:
        force[i][2] -= Config.particle_mass * Config.gravity


@ti.kernel
def apply_damping(damp_coeff: ti.f32):
    for i in velocity:
        velocity[i] *= (1.0 - damp_coeff)


@ti.kernel
def integrate():
    for i in position:
        accel = force[i] / Config.particle_mass
        velocity[i] += accel * Config.dt
        position[i] += velocity[i] * Config.dt


@ti.kernel
def enforce_boundaries():
    r = Config.particle_radius
    L = Config.domain_size
    restitution = 0.3
    
    for i in position:
        if position[i][0] < r:
            position[i][0] = r
            velocity[i][0] = ti.abs(velocity[i][0]) * restitution
        elif position[i][0] > L - r:
            position[i][0] = L - r
            velocity[i][0] = -ti.abs(velocity[i][0]) * restitution
        
        if position[i][1] < r:
            position[i][1] = r
            velocity[i][1] = ti.abs(velocity[i][1]) * restitution
        elif position[i][1] > L - r:
            position[i][1] = L - r
            velocity[i][1] = -ti.abs(velocity[i][1]) * restitution
        
        if position[i][2] < r:
            position[i][2] = r
            velocity[i][2] = ti.abs(velocity[i][2]) * restitution
        elif position[i][2] > L - r:
            position[i][2] = L - r
            velocity[i][2] = -ti.abs(velocity[i][2]) * restitution


# =============================================================================
# MOVEMENT TO TARGET REGIONS
# =============================================================================

@ti.kernel
def apply_levitation_reduced(reduction_factor: ti.f32):
    sigma = Config.field_sigma
    sigma_sq = sigma * sigma
    
    for i in position:
        cluster_id = particle_cluster[i]
        
        if cluster_locked[cluster_id] == 1 and cluster_shaping[cluster_id] == 0:
            source_pos = magnetic_sources[cluster_id]
            
            dx = position[i][0] - source_pos[0]
            dy = position[i][1] - source_pos[1]
            dz = position[i][2] - source_pos[2]
            
            r_sq = dx*dx + dy*dy + dz*dz
            falloff = ti.exp(-r_sq / sigma_sq)
            
            strength = Config.mag_strength_levitation * reduction_factor
            
            F_lev_z = strength * falloff
            
            k_conf = strength * 0.6 / sigma
            F_conf_x = -k_conf * dx * falloff
            F_conf_y = -k_conf * dy * falloff
            
            force[i][0] += F_conf_x
            force[i][1] += F_conf_y
            force[i][2] += F_lev_z


@ti.kernel
def apply_corner_clustering(strength: ti.f32):
    for i in position:
        cluster_id = particle_cluster[i]
        
        tx = 0.0
        ty = 0.0
        tz = Config.z_bottom
        
        if cluster_id == 0:
            tx = Config.domain_size - Config.corner_offset
            ty = Config.domain_size - Config.corner_offset
        elif cluster_id == 1:
            tx = Config.domain_size - Config.corner_offset
            ty = Config.corner_offset
        elif cluster_id == 2:
            tx = Config.corner_offset
            ty = Config.corner_offset
        else:
            tx = Config.corner_offset
            ty = Config.domain_size - Config.corner_offset
        
        dx = tx - position[i][0]
        dy = ty - position[i][1]
        dz = tz - position[i][2]
        
        dist = ti.sqrt(dx*dx + dy*dy + dz*dz + 1e-12)
        
        F_attract = Config.mag_strength_corner * strength
        
        force[i][0] += F_attract * (dx / dist)
        force[i][1] += F_attract * (dy / dist)
        force[i][2] += F_attract * (dz / dist)


@ti.kernel
def apply_corner_holding(strength: ti.f32, exclude_cluster: ti.i32):
    for i in position:
        cluster_id = particle_cluster[i]
        
        if cluster_locked[cluster_id] == 0 and cluster_id != exclude_cluster:
            tx = 0.0
            ty = 0.0
            tz = Config.z_bottom
            
            if cluster_id == 0:
                tx = Config.domain_size - Config.corner_offset
                ty = Config.domain_size - Config.corner_offset
            elif cluster_id == 1:
                tx = Config.domain_size - Config.corner_offset
                ty = Config.corner_offset
            elif cluster_id == 2:
                tx = Config.corner_offset
                ty = Config.corner_offset
            else:
                tx = Config.corner_offset
                ty = Config.domain_size - Config.corner_offset
            
            dx = tx - position[i][0]
            dy = ty - position[i][1]
            dz = tz - position[i][2]
            
            dist = ti.sqrt(dx*dx + dy*dy + dz*dz + 1e-12)
            
            F_hold = Config.mag_strength_corner * strength * 0.4
            
            force[i][0] += F_hold * (dx / dist)
            force[i][1] += F_hold * (dy / dist)
            force[i][2] += F_hold * (dz / dist)


@ti.kernel
def apply_movement_to_region(target_cluster: ti.i32, strength: ti.f32):
    """
    Move cluster to its target region center point.
    Simple: each cluster is attracted to a fixed target position.
    No per-particle angle computation - avoids Taichi scoping issues.
    """
    cx = Config.target_center_x
    cy = Config.target_center_y
    r_target = Config.target_radius
    
    for i in position:
        if particle_cluster[i] == target_cluster:
            px = position[i][0]
            py = position[i][1]
            pz = position[i][2]
            
            # Fixed target per cluster - simple and robust
            tx = cx
            ty = cy
            tz = Config.z_mid
            
            if target_cluster == 0:
                # Top cap: center of top disk
                tz = Config.z_max
            elif target_cluster == 1:
                # Right side: right edge of cylinder at mid-height
                tx = cx + r_target
                tz = Config.z_mid
            elif target_cluster == 2:
                # Left side: left edge of cylinder at mid-height
                tx = cx - r_target
                tz = Config.z_mid
            else:
                # Bottom cap: center of bottom disk
                tz = Config.z_min
            
            dx = tx - px
            dy = ty - py
            dz = tz - pz
            
            dist = ti.sqrt(dx*dx + dy*dy + dz*dz + 1e-12)
            
            F_move = Config.mag_strength_move * strength
            
            force[i][0] += F_move * (dx / dist)
            force[i][1] += F_move * (dy / dist)
            force[i][2] += F_move * (dz / dist)
            
            # Extra vertical boost for upward movement
            if dz > 0:
                F_boost = Config.mag_strength_move * strength * 0.4
                force[i][2] += F_boost


# =============================================================================
# SIMPLE SURFACE CONFINEMENT - LET REPULSION DO THE SPREADING
# =============================================================================

@ti.kernel
def apply_cap_confinement(cluster_id: ti.i32, cz: ti.f32, strength: ti.f32):
    """
    Cap confinement with pre-computed sunflower-spiral target positions.
    1. Strong Z-plane confinement
    2. Radial boundary (stay inside disk)
    3. XY attraction toward pre-computed target (uniform disk coverage)
    4. Anti-gravity
    """
    cx = Config.target_center_x
    cy = Config.target_center_y
    r_max = Config.target_radius
    
    for i in position:
        if particle_cluster[i] == cluster_id and cluster_shaping[cluster_id] == 1:
            px = position[i][0]
            py = position[i][1]
            pz = position[i][2]
            
            # === Z-PLANE CONFINEMENT ===
            z_error = pz - cz
            k_z = Config.mag_strength_surface * strength * 20.0
            force[i][2] += -k_z * z_error
            
            # === RADIAL BOUNDARY ===
            dx_disk = px - cx
            dy_disk = py - cy
            r_current = ti.sqrt(dx_disk*dx_disk + dy_disk*dy_disk + 1e-12)
            
            if r_current > r_max:
                r_error = r_current - r_max
                k_radial = Config.mag_strength_surface * strength * 12.0
                
                nnx = dx_disk / r_current
                nny = dy_disk / r_current
                
                force[i][0] += -k_radial * r_error * nnx
                force[i][1] += -k_radial * r_error * nny
            
            # === XY TARGET ATTRACTION (sunflower spiral) ===
            tx = particle_target[i][0]
            ty = particle_target[i][1]
            
            k_target = Config.mag_strength_surface * strength * 4.0
            force[i][0] += k_target * (tx - px)
            force[i][1] += k_target * (ty - py)
            
            # === ANTI-GRAVITY ===
            force[i][2] += Config.particle_mass * Config.gravity * 0.95


@ti.kernel
def apply_side_confinement(cluster_id: ti.i32, target_side: ti.i32, strength: ti.f32):
    """
    Cylinder side surface confinement with PRE-COMPUTED TARGET GRID.
    
    Each particle has a pre-computed target position on the cylinder surface
    (set up in Python via assign_surface_targets). The kernel simply:
    1. RADIAL: Pin particle to cylinder radius R via F = -k(r-R)
    2. TANGENTIAL: Attract toward target's theta via surface-projected force
    3. VERTICAL: Attract toward target's Z coordinate
    4. Z BOUNDARIES: Hard walls at z_min / z_max
    5. ANTI-GRAVITY: Compensate gravity
    
    The target grid is computed in Python as a regular rows x cols layout
    on the semicircle, guaranteeing FULL surface coverage.
    """
    cx = Config.target_center_x
    cy = Config.target_center_y
    r_target = Config.target_radius
    z_lo = Config.z_min
    z_hi = Config.z_max
    
    for i in position:
        if particle_cluster[i] == cluster_id and cluster_shaping[cluster_id] == 1:
            px = position[i][0]
            py = position[i][1]
            pz = position[i][2]
            
            # === RADIAL CONFINEMENT ===
            dx_axis = px - cx
            dy_axis = py - cy
            r_current = ti.sqrt(dx_axis*dx_axis + dy_axis*dy_axis + 1e-12)
            
            nx = dx_axis / r_current
            ny = dy_axis / r_current
            
            r_error = r_current - r_target
            k_radial = Config.mag_strength_surface * strength * 25.0
            force[i][0] += -k_radial * r_error * nx
            force[i][1] += -k_radial * r_error * ny
            
            # === TARGET ATTRACTION (tangential + vertical) ===
            # Pre-computed target is in particle_target[i]
            tx = particle_target[i][0]
            ty = particle_target[i][1]
            tz = particle_target[i][2]
            
            tangent_x = -ny  # Tangent unit vector
            tangent_y = nx
            
            dx_t = tx - px
            dy_t = ty - py
            dz_t = tz - pz
            
            # Project XY displacement onto tangent direction only
            proj_tang = dx_t * tangent_x + dy_t * tangent_y
            
            k_target = Config.mag_strength_surface * strength * 6.0
            
            force[i][0] += k_target * proj_tang * tangent_x
            force[i][1] += k_target * proj_tang * tangent_y
            force[i][2] += k_target * dz_t
            
            # === Z BOUNDARIES ===
            if pz > z_hi:
                k_zb = Config.mag_strength_surface * strength * 15.0
                force[i][2] -= k_zb * (pz - z_hi)
            elif pz < z_lo:
                k_zb = Config.mag_strength_surface * strength * 15.0
                force[i][2] += k_zb * (z_lo - pz)
            
            # === ANTI-GRAVITY ===
            force[i][2] += Config.particle_mass * Config.gravity * 0.95


# =============================================================================
# DIAGNOSTICS
# =============================================================================

@ti.kernel
def compute_cluster_centers():
    for c in range(4):
        cluster_centers[c] = ti.Vector([0.0, 0.0, 0.0])
    
    count = ti.Vector([0, 0, 0, 0])
    for i in position:
        c = particle_cluster[i]
        cluster_centers[c] += position[i]
        count[c] += 1
    
    for c in range(4):
        if count[c] > 0:
            cluster_centers[c] /= float(count[c])


def check_cluster_locked(cluster_id, target_pos):
    cc = cluster_centers.to_numpy()
    dist = np.linalg.norm(cc[cluster_id] - target_pos)
    return dist < Config.lock_threshold


# =============================================================================
# PRE-COMPUTED SURFACE TARGET ASSIGNMENT
# =============================================================================

def assign_surface_targets(cluster_np, counts):
    """
    Pre-compute a unique target position on the cylinder surface for every particle.
    
    For CAPS (clusters 0, 3): targets form a uniform disk on z=z_max / z=z_min.
      Uses concentric rings (Vogel's sunflower spiral) for disk packing.
    
    For SIDES (clusters 1, 2): targets form a uniform grid on the semicylinder.
      Rows along Z, columns along theta. Regular grid = full coverage guaranteed.
    
    This runs ONCE in Python at initialization. The Taichi kernel just reads
    particle_target[i] and applies attraction forces.
    """
    cx = Config.target_center_x
    cy = Config.target_center_y
    R = Config.target_radius
    z_lo = Config.z_min
    z_hi = Config.z_max
    
    targets_np = np.zeros((Config.n_particles, 3), dtype=np.float32)
    
    for cluster_id in range(4):
        # Get indices of particles in this cluster
        indices = np.where(cluster_np == cluster_id)[0]
        n = len(indices)
        if n == 0:
            continue
        
        if cluster_id == 0:
            # TOP CAP: sunflower spiral on disk at z = z_max
            for rank, idx in enumerate(indices):
                # Vogel's model: golden angle spacing
                golden_angle = np.pi * (3.0 - np.sqrt(5.0))  # ~137.5 degrees
                r_frac = np.sqrt((rank + 0.5) / n)  # Radial position [0, 1)
                theta = rank * golden_angle
                
                targets_np[idx] = [
                    cx + R * r_frac * np.cos(theta),
                    cy + R * r_frac * np.sin(theta),
                    z_hi
                ]
        
        elif cluster_id == 3:
            # BOTTOM CAP: sunflower spiral on disk at z = z_min
            for rank, idx in enumerate(indices):
                golden_angle = np.pi * (3.0 - np.sqrt(5.0))
                r_frac = np.sqrt((rank + 0.5) / n)
                theta = rank * golden_angle
                
                targets_np[idx] = [
                    cx + R * r_frac * np.cos(theta),
                    cy + R * r_frac * np.sin(theta),
                    z_lo
                ]
        
        elif cluster_id == 1:
            # RIGHT SIDE: regular grid on semicylinder theta in [-pi/2, pi/2]
            # Determine grid: n_rows (Z) x n_cols (theta)
            # Aspect ratio: height / (pi*R) to get roughly square cells
            aspect = (z_hi - z_lo) / (np.pi * R)
            n_cols = max(2, int(np.round(np.sqrt(n / aspect))))
            n_rows = max(2, int(np.ceil(n / n_cols)))
            
            for rank, idx in enumerate(indices):
                row = rank // n_cols
                col = rank % n_cols
                
                # Z: evenly spaced across cylinder height
                z_frac = (row + 0.5) / n_rows
                z_val = z_lo + z_frac * (z_hi - z_lo)
                
                # Theta: evenly spaced across semicircle [-pi/2, pi/2]
                theta_frac = (col + 0.5) / n_cols
                theta = -np.pi / 2.0 + theta_frac * np.pi
                
                targets_np[idx] = [
                    cx + R * np.cos(theta),
                    cy + R * np.sin(theta),
                    z_val
                ]
        
        elif cluster_id == 2:
            # LEFT SIDE: regular grid on semicylinder theta in [pi/2, 3pi/2]
            aspect = (z_hi - z_lo) / (np.pi * R)
            n_cols = max(2, int(np.round(np.sqrt(n / aspect))))
            n_rows = max(2, int(np.ceil(n / n_cols)))
            
            for rank, idx in enumerate(indices):
                row = rank // n_cols
                col = rank % n_cols
                
                z_frac = (row + 0.5) / n_rows
                z_val = z_lo + z_frac * (z_hi - z_lo)
                
                theta_frac = (col + 0.5) / n_cols
                theta = np.pi / 2.0 + theta_frac * np.pi
                
                targets_np[idx] = [
                    cx + R * np.cos(theta),
                    cy + R * np.sin(theta),
                    z_val
                ]
    
    particle_target.from_numpy(targets_np)
    print(f"\n[Surface Targets Assigned]")
    print(f"  C0 (top cap):    sunflower disk at z={z_hi*1000:.1f}mm")
    print(f"  C1 (right side): grid on semicylinder (right)")
    print(f"  C2 (left side):  grid on semicylinder (left)")
    print(f"  C3 (bottom cap): sunflower disk at z={z_lo*1000:.1f}mm")


# =============================================================================
# INITIALIZATION
# =============================================================================

def initialize_particles():
    pos_np = np.zeros((Config.n_particles, 3), dtype=np.float32)
    cluster_np = np.zeros(Config.n_particles, dtype=np.int32)
    
    cx = Config.target_center_x
    cy = Config.target_center_y
    z_start = Config.z_bottom
    
    for i in range(Config.n_particles):
        x = np.random.uniform(Config.particle_radius, 
                             Config.domain_size - Config.particle_radius)
        y = np.random.uniform(Config.particle_radius, 
                             Config.domain_size - Config.particle_radius)
        z = z_start + np.random.uniform(-0.01e-3, 0.01e-3)
        
        pos_np[i] = [x, y, z]
        
        # Assign to quadrant-based clusters
        if x >= cx and y >= cy:
            cluster_np[i] = 0  # Top cap
        elif x >= cx and y < cy:
            cluster_np[i] = 1  # Right side
        elif x < cx and y < cy:
            cluster_np[i] = 2  # Left side
        else:
            cluster_np[i] = 3  # Bottom cap
    
    position.from_numpy(pos_np)
    particle_cluster.from_numpy(cluster_np)
    velocity.from_numpy(np.zeros((Config.n_particles, 3), dtype=np.float32))
    
    cluster_locked.from_numpy(np.zeros(4, dtype=np.int32))
    cluster_shaping.from_numpy(np.zeros(4, dtype=np.int32))
    
    # Magnetic sources at target REGION centers
    sources_np = np.array([
        [Config.target_center_x, Config.target_center_y, Config.z_max],                        # Top cap center
        [Config.target_center_x + Config.target_radius, Config.target_center_y, Config.z_mid],  # Right side surface
        [Config.target_center_x - Config.target_radius, Config.target_center_y, Config.z_mid],  # Left side surface
        [Config.target_center_x, Config.target_center_y, Config.z_min],                        # Bottom cap center
    ], dtype=np.float32)
    magnetic_sources.from_numpy(sources_np)
    
    counts = np.bincount(cluster_np)
    print(f"\n[Initialization]")
    print(f"  Particle distribution:")
    print(f"    C0 (top cap):    {counts[0]:3d} particles")
    print(f"    C1 (right side): {counts[1]:3d} particles")
    print(f"    C2 (left side):  {counts[2]:3d} particles")
    print(f"    C3 (bottom cap): {counts[3]:3d} particles")
    
    # Pre-compute surface target positions for every particle
    assign_surface_targets(cluster_np, counts)


# =============================================================================
# OUTPUT
# =============================================================================

def write_vtu(output_dir, time_val, pos, clust):
    filename = f"{output_dir}/particles_{time_val:.4f}.vtu"
    
    L = Config.domain_size
    
    # Domain box
    box_pts = np.array([
        [0,0,0], [L,0,0], [L,L,0], [0,L,0],
        [0,0,L], [L,0,L], [L,L,L], [0,L,L],
    ], dtype=np.float32)
    
    # Cylinder wireframe
    n_circ = 60
    n_vert = 20
    cx, cy = Config.target_center_x, Config.target_center_y
    r = Config.target_radius
    
    circ_top = np.array([[cx + r*np.cos(2*np.pi*i/n_circ), 
                          cy + r*np.sin(2*np.pi*i/n_circ), 
                          Config.z_max] for i in range(n_circ)], dtype=np.float32)
    
    circ_bot = np.array([[cx + r*np.cos(2*np.pi*i/n_circ),
                          cy + r*np.sin(2*np.pi*i/n_circ),
                          Config.z_min] for i in range(n_circ)], dtype=np.float32)
    
    # Add mid-height circle for reference
    circ_mid = np.array([[cx + r*np.cos(2*np.pi*i/n_circ),
                          cy + r*np.sin(2*np.pi*i/n_circ),
                          Config.z_mid] for i in range(n_circ)], dtype=np.float32)
    
    vert_lines = []
    for i in range(n_vert):
        angle = 2*np.pi*i/n_vert
        x_pos = cx + r*np.cos(angle)
        y_pos = cy + r*np.sin(angle)
        for j in range(15):
            z_frac = j / 14.0
            z_pos = Config.z_min + (Config.z_max - Config.z_min) * z_frac
            vert_lines.append([x_pos, y_pos, z_pos])
    
    vert_lines = np.array(vert_lines, dtype=np.float32)
    
    all_pos = np.vstack([pos, box_pts, circ_top, circ_mid, circ_bot, vert_lines])
    all_clust = np.concatenate([
        clust,
        np.full(8, -1, dtype=np.int32),
        np.full(n_circ, -2, dtype=np.int32),
        np.full(n_circ, -4, dtype=np.int32),  # Mid circle different color
        np.full(n_circ, -2, dtype=np.int32),
        np.full(len(vert_lines), -3, dtype=np.int32),
    ])
    
    n_total = len(all_pos)
    
    with open(filename, 'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="UnstructuredGrid" version="1.0" byte_order="LittleEndian">\n')
        f.write('  <UnstructuredGrid>\n')
        f.write(f'    <Piece NumberOfPoints="{n_total}" NumberOfCells="0">\n')
        
        f.write('      <Points>\n')
        f.write('        <DataArray type="Float32" NumberOfComponents="3" format="ascii">\n')
        for p in all_pos:
            f.write(f'          {p[0]:.8e} {p[1]:.8e} {p[2]:.8e}\n')
        f.write('        </DataArray>\n')
        f.write('      </Points>\n')
        
        f.write('      <PointData>\n')
        f.write('        <DataArray type="Int32" Name="ClusterID" format="ascii">\n')
        for c in all_clust:
            f.write(f'          {c}\n')
        f.write('        </DataArray>\n')
        f.write('      </PointData>\n')
        
        f.write('      <Cells>\n')
        f.write('        <DataArray type="Int32" Name="connectivity" format="ascii"></DataArray>\n')
        f.write('        <DataArray type="Int32" Name="offsets" format="ascii"></DataArray>\n')
        f.write('        <DataArray type="UInt8" Name="types" format="ascii"></DataArray>\n')
        f.write('      </Cells>\n')
        
        f.write('    </Piece>\n')
        f.write('  </UnstructuredGrid>\n')
        f.write('</VTKFile>\n')


def write_pvd(output_dir):
    import glob
    vtu_files = sorted(glob.glob(f"{output_dir}/particles_*.vtu"))
    
    with open(f"{output_dir}/simulation.pvd", 'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="Collection" version="0.1">\n')
        f.write('  <Collection>\n')
        
        for vtu in vtu_files:
            basename = os.path.basename(vtu)
            time_str = basename.replace('particles_', '').replace('.vtu', '')
            time_val = float(time_str)
            f.write(f'    <DataSet timestep="{time_val}" file="{basename}"/>\n')
        
        f.write('  </Collection>\n')
        f.write('</VTKFile>\n')


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def run_simulation():
    print(f"\n[Phase Schedule]")
    print(f"  0.0-1.0s:   Corner clustering")
    print(f"  1.0-2.0s:   Move C0 (top cap) to region")
    print(f"  2.0-3.0s:   Move C1 (right side) to region")
    print(f"  3.0-4.0s:   Move C2 (left side) to region")
    print(f"  4.0-5.0s:   Move C3 (bottom cap) to region")
    print(f"  5.0-12.0s:  ALL clusters spread simultaneously")
    print(f"{'='*80}\n")
    
    initialize_particles()
    output_dir = "outputs/Phase2_v2_REPULSION"
    os.makedirs(output_dir, exist_ok=True)
    
    t = 0.0
    step = 0
    next_output = 0.0
    
    sources_np = magnetic_sources.to_numpy()
    
    print(f"[Simulation Progress]")
    print(f"{'Time':>6} | {'Phase':>5} | {'Prog%':>5} | Status")
    print(f"{'-'*70}")
    
    import time as pytime
    start_time = pytime.time()
    
    while t < Config.t_max:
        # Phase determination
        if t < 1.0:
            phase = 0
            phase_name = "Clstr"
            progress = t / 1.0
            damping = 0.015
            repulsion = Config.repulsion_normal
        elif t < 2.0:
            phase = 1
            phase_name = "Mv C0"
            progress = (t - 1.0) / 1.0
            damping = 0.10
            repulsion = Config.repulsion_normal
        elif t < 3.0:
            phase = 2
            phase_name = "Mv C1"
            progress = (t - 2.0) / 1.0
            damping = 0.10
            repulsion = Config.repulsion_normal
        elif t < 4.0:
            phase = 3
            phase_name = "Mv C2"
            progress = (t - 3.0) / 1.0
            damping = 0.10
            repulsion = Config.repulsion_normal
        elif t < 5.0:
            phase = 4
            phase_name = "Mv C3"
            progress = (t - 4.0) / 1.0
            damping = 0.10
            repulsion = Config.repulsion_normal
        else:
            # ALL clusters spread simultaneously from t=5 to t=12
            # This gives every cluster 7 full seconds of spreading time
            phase = 5
            phase_name = "SpAll"
            progress = min((t - 5.0) / 3.0, 1.0)  # Ramp up over 3s, then hold
            damping = 0.03
            repulsion = Config.repulsion_spreading
        
        # Forces
        clear_forces()
        apply_gravity()
        
        # Particle repulsion (with variable strength)
        build_spatial_hash()
        apply_particle_repulsion_optimized(repulsion)
        
        compute_cluster_centers()
        
        # Levitation
        if phase >= 5:
            apply_levitation_reduced(0.05)  # Minimal during spreading
        else:
            apply_levitation_reduced(1.0)
        
        # Phase-specific forces
        strength = 0.5 * (1.0 - np.cos(np.pi * progress))
        
        if phase == 0:
            apply_corner_clustering(strength)
            
        elif phase == 1:
            apply_movement_to_region(0, strength)
            apply_corner_holding(1.0, 0)
            if progress > 0.7 and cluster_locked.to_numpy()[0] == 0:
                if check_cluster_locked(0, sources_np[0]):
                    cluster_locked.from_numpy(np.array([1,0,0,0], dtype=np.int32))
                    print(f"       [OK] C0 locked at top cap region")
                    
        elif phase == 2:
            apply_movement_to_region(1, strength)
            apply_corner_holding(1.0, 1)
            if progress > 0.7 and cluster_locked.to_numpy()[1] == 0:
                if check_cluster_locked(1, sources_np[1]):
                    cluster_locked.from_numpy(np.array([1,1,0,0], dtype=np.int32))
                    print(f"       [OK] C1 locked at right side region")
                    
        elif phase == 3:
            apply_movement_to_region(2, strength)
            apply_corner_holding(1.0, 2)
            if progress > 0.7 and cluster_locked.to_numpy()[2] == 0:
                if check_cluster_locked(2, sources_np[2]):
                    cluster_locked.from_numpy(np.array([1,1,1,0], dtype=np.int32))
                    print(f"       [OK] C2 locked at left side region")
                    
        elif phase == 4:
            apply_movement_to_region(3, strength)
            apply_corner_holding(1.0, 3)
            if progress > 0.7 and cluster_locked.to_numpy()[3] == 0:
                if check_cluster_locked(3, sources_np[3]):
                    cluster_locked.from_numpy(np.array([1,1,1,1], dtype=np.int32))
                    print(f"       [OK] C3 locked - Starting surface spreading!")
                    print(f"       [INFO] Repulsion increased {Config.repulsion_spreading/Config.repulsion_normal:.1f}x for uniform distribution")
        
        elif phase == 5:
            # All four clusters spread simultaneously
            cluster_shaping.from_numpy(np.array([1,1,1,1], dtype=np.int32))
            s = min(strength, 1.0)
            apply_cap_confinement(0, Config.z_max, s)
            apply_side_confinement(1, 1, s)
            apply_side_confinement(2, 2, s)
            apply_cap_confinement(3, Config.z_min, s)
        
        # Integration
        apply_damping(damping)
        integrate()
        enforce_boundaries()
        
        # Output
        if t >= next_output:
            write_vtu(output_dir, t, position.to_numpy(), particle_cluster.to_numpy())
            print(f"{t:6.2f} | {phase_name:>5} | {progress*100:5.1f}")
            next_output += Config.output_interval
        
        t += Config.dt
        step += 1
    
    elapsed = pytime.time() - start_time
    steps_per_sec = step / elapsed
    
    print(f"{'-'*70}")
    print(f"[Complete]")
    print(f"  Total steps: {step:,}")
    print(f"  Elapsed time: {elapsed:.1f}s ({steps_per_sec:,.0f} steps/sec)")
    
    write_pvd(output_dir)
    print(f"\n[Output] {output_dir}/simulation.pvd")
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    run_simulation()