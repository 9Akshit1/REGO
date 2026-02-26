#!/usr/bin/env python3
"""
REGO Phase 2: ADAPTIVE MAGNETIC PARTICLE SHAPING
Generalized system: ANY object specification → automatic field design

Physical Model:
- Particles start settled at bottom (gravity) - REALISTIC
- External magnetic device (outside domain) creates field - REALISTIC  
- Particles experience force from field gradients: F = (V·χ/μ₀)·∇(B²)
- Backward design: Given shape → calculate required field → generate forces
- Adaptive algorithm: Works for arbitrary convex objects

Architecture:
1. ShapeTarget: Abstract definition of target geometry
2. MagneticFieldGenerator: Calculates forces to achieve shape
3. Phase Controller: Multi-phase strategy for stability  
4. Particle System: Responds to computed field

Key Features:
- Supports: Cylinder, Sphere, Box, Cone, and extensible to any shape
- Automatic force generation from external sources
- Realistic initialization (particles at bottom)
- Adaptive algorithms (not hardcoded)
"""

import taichi as ti
import numpy as np
import matplotlib.pyplot as plt
import os
import time
from dataclasses import dataclass
from typing import List, Tuple

ti.init(arch=ti.cpu, default_fp=ti.f32)

# =============================================================================
# SHAPE TARGETS - Extensible to ANY geometry
# =============================================================================

class ShapeTarget:
    """Abstract base class for target shapes"""
    
    def is_inside(self, pos: np.ndarray) -> bool:
        """Check if position is inside target shape"""
        raise NotImplementedError
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        """Distance to nearest surface (signed: negative=inside)"""
        raise NotImplementedError
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        """Project position onto nearest point on target surface"""
        raise NotImplementedError
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        """Return (center, avg_radius, height) for domain planning"""
        raise NotImplementedError


class Cylinder(ShapeTarget):
    """Cylindrical target shape"""
    
    def __init__(self, center: List[float], radius: float, height: float):
        self.center = np.array(center, dtype=np.float64)
        self.radius = radius
        self.height = height
    
    def is_inside(self, pos: np.ndarray) -> bool:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        return r_perp <= self.radius and abs(dz) <= self.height/2
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        radial_dist = r_perp - self.radius
        z_dist = abs(dz) - self.height/2
        return max(radial_dist, z_dist)
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        
        # Project onto cylinder surface
        if r_perp > 0.001:
            scale = self.radius / (r_perp + 1e-10)
            target_x = self.center[0] + dx * scale
            target_y = self.center[1] + dy * scale
        else:
            target_x = self.center[0] + self.radius
            target_y = self.center[1]
        
        target_z = np.clip(dz, -self.height/2, self.height/2) + self.center[2]
        return np.array([target_x, target_y, target_z])
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        return self.center, self.radius, self.height
    
    def __repr__(self):
        return f"Cylinder(center={self.center}, r={self.radius*1e3:.2f}mm, h={self.height*1e3:.2f}mm)"


class Sphere(ShapeTarget):
    """Spherical target shape"""
    
    def __init__(self, center: List[float], radius: float):
        self.center = np.array(center, dtype=np.float64)
        self.radius = radius
    
    def is_inside(self, pos: np.ndarray) -> bool:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        return np.sqrt(dx**2 + dy**2 + dz**2) <= self.radius
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r = np.sqrt(dx**2 + dy**2 + dz**2)
        return r - self.radius
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r = np.sqrt(dx**2 + dy**2 + dz**2)
        if r > 1e-10:
            scale = self.radius / (r + 1e-10)
            return self.center + np.array([dx, dy, dz]) * scale
        return self.center + np.array([self.radius, 0, 0])
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        return self.center, self.radius, self.radius
    
    def __repr__(self):
        return f"Sphere(center={self.center}, r={self.radius*1e3:.2f}mm)"


class Box(ShapeTarget):
    """Rectangular box target shape"""
    
    def __init__(self, center: List[float], half_lengths: List[float]):
        self.center = np.array(center, dtype=np.float64)
        self.half_lengths = np.array(half_lengths, dtype=np.float64)
    
    def is_inside(self, pos: np.ndarray) -> bool:
        dx = np.abs(pos[0] - self.center[0])
        dy = np.abs(pos[1] - self.center[1])
        dz = np.abs(pos[2] - self.center[2])
        return dx <= self.half_lengths[0] and dy <= self.half_lengths[1] and dz <= self.half_lengths[2]
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        dx = np.abs(pos[0] - self.center[0])
        dy = np.abs(pos[1] - self.center[1])
        dz = np.abs(pos[2] - self.center[2])
        return max(dx - self.half_lengths[0], dy - self.half_lengths[1], dz - self.half_lengths[2])
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        target = pos.copy()
        target[0] = np.clip(pos[0], self.center[0] - self.half_lengths[0], self.center[0] + self.half_lengths[0])
        target[1] = np.clip(pos[1], self.center[1] - self.half_lengths[1], self.center[1] + self.half_lengths[1])
        target[2] = np.clip(pos[2], self.center[2] - self.half_lengths[2], self.center[2] + self.half_lengths[2])
        return target
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        return self.center, np.max(self.half_lengths), np.max(self.half_lengths)
    
    def __repr__(self):
        return f"Box(center={self.center}, half_len={self.half_lengths*1e3}mm)"


class Cone(ShapeTarget):
    """Conical target shape"""
    
    def __init__(self, center: List[float], base_radius: float, height: float):
        self.center = np.array(center, dtype=np.float64)
        self.base_radius = base_radius
        self.height = height
    
    def is_inside(self, pos: np.ndarray) -> bool:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        z_rel = (dz) / self.height * 2
        
        if z_rel < -1 or z_rel > 1:
            return False
        
        max_r_at_z = self.base_radius * (1 - abs(z_rel)) / 2
        return r_perp <= max_r_at_z
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        z_rel = dz / self.height * 2
        
        max_r = self.base_radius * (1 - abs(z_rel)) / 2
        return r_perp - max_r
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        z_rel = np.clip(dz / self.height * 2, -1, 1)
        
        target_r = self.base_radius * (1 - abs(z_rel)) / 2
        if r_perp > 1e-10:
            scale = target_r / (r_perp + 1e-10)
            target_x = self.center[0] + dx * scale
            target_y = self.center[1] + dy * scale
        else:
            target_x = self.center[0] + target_r
            target_y = self.center[1]
        
        target_z = self.center[2] + z_rel * self.height / 2
        return np.array([target_x, target_y, target_z])
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        return self.center, self.base_radius, self.height
    
    def __repr__(self):
        return f"Cone(center={self.center}, base_r={self.base_radius*1e3:.2f}mm, h={self.height*1e3:.2f}mm)"


class Disk(ShapeTarget):
    """Disk shape (flat circular)"""
    
    def __init__(self, center: List[float], radius: float, thickness: float = 0.2e-3):
        self.center = np.array(center, dtype=np.float64)
        self.radius = radius
        self.thickness = thickness
    
    def is_inside(self, pos: np.ndarray) -> bool:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        return r_perp <= self.radius and abs(dz) <= self.thickness / 2
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        radial = r_perp - self.radius
        z_dist = abs(dz) - self.thickness / 2
        return max(radial, z_dist)
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        r_perp = np.sqrt(dx**2 + dy**2)
        if r_perp > 1e-10:
            scale = self.radius / (r_perp + 1e-10)
            target_x = self.center[0] + dx * scale
            target_y = self.center[1] + dy * scale
        else:
            target_x = self.center[0] + self.radius
            target_y = self.center[1]
        target_z = self.center[2]
        return np.array([target_x, target_y, target_z])
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        return self.center, self.radius, self.thickness
    
    def __repr__(self):
        return f"Disk(center={self.center}, r={self.radius*1e3:.2f}mm, thickness={self.thickness*1e3:.2f}mm)"


class RectangularBeam(ShapeTarget):
    """Rectangular beam with two opposed gradient fields"""
    
    def __init__(self, center: List[float], width: float, height: float, length: float):
        self.center = np.array(center, dtype=np.float64)
        self.width = width      # x direction
        self.height = height    # z direction
        self.length = length    # y direction
    
    def is_inside(self, pos: np.ndarray) -> bool:
        dx = abs(pos[0] - self.center[0])
        dy = abs(pos[1] - self.center[1])
        dz = abs(pos[2] - self.center[2])
        return dx <= self.width/2 and dy <= self.length/2 and dz <= self.height/2
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        dx = abs(pos[0] - self.center[0])
        dy = abs(pos[1] - self.center[1])
        dz = abs(pos[2] - self.center[2])
        return max(dx - self.width/2, dy - self.length/2, dz - self.height/2)
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        target = pos.copy()
        target[0] = np.clip(pos[0], self.center[0] - self.width/2, self.center[0] + self.width/2)
        target[1] = np.clip(pos[1], self.center[1] - self.length/2, self.center[1] + self.length/2)
        target[2] = np.clip(pos[2], self.center[2] - self.height/2, self.center[2] + self.height/2)
        return target
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        return self.center, max(self.width, self.length)/2, self.height
    
    def __repr__(self):
        return f"RectangularBeam(center={self.center}, w={self.width*1e3:.2f}mm, h={self.height*1e3:.2f}mm, l={self.length*1e3:.2f}mm)"


class LShape(ShapeTarget):
    """L-shaped target (composite: vertical + horizontal sections)"""
    
    def __init__(self, center: List[float], thickness: float, vert_height: float, horiz_width: float):
        self.center = np.array(center, dtype=np.float64)
        self.thickness = thickness        # Thickness of each beam
        self.vert_height = vert_height    # Height of vertical section
        self.horiz_width = horiz_width    # Width of horizontal section
    
    def is_inside(self, pos: np.ndarray) -> bool:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        
        # Vertical section
        vert_check = (abs(dx) <= self.thickness/2 and 
                     abs(dy) <= self.thickness/2 and 
                     dz >= -self.vert_height/2 and dz <= self.vert_height/2)
        
        # Horizontal section
        horiz_check = (abs(dx) <= self.horiz_width/2 and 
                      abs(dy) <= self.thickness/2 and 
                      dz >= -self.vert_height/2 - self.thickness/2 and 
                      dz <= -self.vert_height/2 + self.thickness/2)
        
        return vert_check or horiz_check
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        
        # Vertical section distance
        vert_dx = abs(dx) - self.thickness/2
        vert_dy = abs(dy) - self.thickness/2
        vert_dz = max(dz - self.vert_height/2, -self.vert_height/2 - dz)
        vert_dist = max(vert_dx, vert_dy, vert_dz)
        
        # Horizontal section distance
        horiz_dx = abs(dx) - self.horiz_width/2
        horiz_dy = abs(dy) - self.thickness/2
        horiz_dz = max(dz - (-self.vert_height/2 + self.thickness/2), 
                      -self.vert_height/2 - self.thickness/2 - dz)
        horiz_dist = max(horiz_dx, horiz_dy, horiz_dz)
        
        if self.is_inside(pos):
            return -min(abs(vert_dist), abs(horiz_dist))
        return min(vert_dist, horiz_dist)
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        
        # Project to nearest L-shape surface
        target_x = np.clip(dx, -self.horiz_width/2, self.horiz_width/2) + self.center[0]
        target_y = np.clip(dy, -self.thickness/2, self.thickness/2) + self.center[1]
        
        if dz >= -self.vert_height/2:
            target_z = np.clip(dz, -self.vert_height/2, self.vert_height/2) + self.center[2]
        else:
            target_z = np.clip(dz, -self.vert_height/2 - self.thickness/2, -self.vert_height/2 + self.thickness/2) + self.center[2]
        
        return np.array([target_x, target_y, target_z])
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        return self.center, max(self.horiz_width, self.vert_height)/2, self.vert_height
    
    def __repr__(self):
        return f"LShape(center={self.center}, thick={self.thickness*1e3:.2f}mm, v_h={self.vert_height*1e3:.2f}mm, h_w={self.horiz_width*1e3:.2f}mm)"


class HollowCylinder(ShapeTarget):
    """Hollow cylinder (shell)"""
    
    def __init__(self, center: List[float], outer_radius: float, inner_radius: float, height: float):
        self.center = np.array(center, dtype=np.float64)
        self.outer_radius = outer_radius
        self.inner_radius = inner_radius
        self.height = height
    
    def is_inside(self, pos: np.ndarray) -> bool:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        return (r_perp <= self.outer_radius and r_perp >= self.inner_radius and 
                abs(dz) <= self.height/2)
    
    def get_distance_to_surface(self, pos: np.ndarray) -> float:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        
        # Distance to outer surface
        outer_dist = abs(r_perp - self.outer_radius)
        # Distance to inner surface
        inner_dist = abs(r_perp - self.inner_radius)
        # Height constraint
        z_dist = abs(dz) - self.height/2
        
        # Closest surface distance
        radial_dist = min(outer_dist, inner_dist)
        return max(radial_dist, z_dist)
    
    def get_target_position(self, pos: np.ndarray) -> np.ndarray:
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        r_perp = np.sqrt(dx**2 + dy**2)
        
        # Project to nearest surface (outer or inner)
        if r_perp > (self.outer_radius + self.inner_radius) / 2:
            # Closer to outer
            target_r = self.outer_radius
        else:
            # Closer to inner
            target_r = self.inner_radius
        
        if r_perp > 1e-10:
            scale = target_r / r_perp
            target_x = self.center[0] + dx * scale
            target_y = self.center[1] + dy * scale
        else:
            target_x = self.center[0] + self.outer_radius
            target_y = self.center[1]
        
        target_z = np.clip(dz, -self.height/2, self.height/2) + self.center[2]
        return np.array([target_x, target_y, target_z])
    
    def get_bounds(self) -> Tuple[np.ndarray, float, float]:
        return self.center, self.outer_radius, self.height
    
    def __repr__(self):
        return f"HollowCylinder(center={self.center}, r_outer={self.outer_radius*1e3:.2f}mm, r_inner={self.inner_radius*1e3:.2f}mm, h={self.height*1e3:.2f}mm)"


# =============================================================================
# DIRECT MAGNETIC FORCE GENERATOR (PROVEN APPROACH)
# =============================================================================

class MagneticFieldGenerator:
    """
    Generates DIRECT magnetic forces for 3D shape formation
    
    Key insight from phase2_magnetic_redesign.py:
    - Don't use complex field gradients - use direct phase-based forces
    - Apply forces MUCH stronger than gravity to overcome inertia
    - Use simple geometric targets: center axis, radius, height bounds
    - Phase-based control automatically handles 3D positioning
    
    This approach is PROVEN to work for cylinder formation.
    """
    
    def __init__(self, target_shape: ShapeTarget, particle_mass: float, domain_size: float):
        self.target = target_shape
        self.particle_mass = particle_mass
        self.domain_size = domain_size
        self.gravity = 9.81
        
        # Get target geometry
        self.center, self.target_radius, self.target_extent = self.target.get_bounds()
        
        print(f"[MagneticFieldGenerator]")
        print(f"  Center: {self.center*1e3} mm")
        print(f"  Radius: {self.target_radius*1e3:.2f} mm")
        print(f"  Extent (height): {self.target_extent*1e3:.2f} mm")
        print(f"  Using DIRECT phase-based forces (proven approach)")
    
    def get_force_at_particle(self, particle_pos: np.ndarray, phase_progress: float, phase: int = 1) -> np.ndarray:
        """
        Calculate DIRECT magnetic force at particle position
        
        Args:
            particle_pos: Current position of particle [x, y, z]
            phase_progress: Progress through current phase [0, 1]
            phase: Current phase (0, 1, 2, or 3)
        
        Returns: Force vector [fx, fy, fz]
        
        Strategy (from proven magnetic_redesign.py):
        - Phase 0 (LIFT & CENTER): Levitation + radial inward
        - Phase 1 (ORGANIZE): Maintain lift + expand to radius
        - Phase 2 (CONFINE): Tight radial control + vertical settling
        """
        
        x, y, z = particle_pos[0], particle_pos[1], particle_pos[2]
        cx, cy, cz = self.center[0], self.center[1], self.center[2]
        r_target = self.target_radius
        
        # Distance metrics
        dx = x - cx
        dy = y - cy
        dz = z - cz
        r_perp = np.sqrt(dx*dx + dy*dy + 1e-10)
        
        force = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        
        # DETERMINE ACTUAL PHASE based on particle height (like magnetic_redesign)
        height_range = self.target_extent / 2
        if z < cz - height_range * 0.5:
            actual_phase = 0  # Bottom - need levitation
        elif z < cz + height_range * 0.3:
            actual_phase = 1  # Middle - organize
        else:
            actual_phase = 2  # Top - confine
        
        # ===== PHASE 0: STRONG LEVITATION & CENTERING =====
        if actual_phase == 0:
            # STRONG upward force - MUST exceed weight
            force_mag_up = self.particle_mass * self.gravity * 1.5  # 150% of weight
            force[2] += force_mag_up
            
            # Strong radial inward force (toward center axis)
            if r_perp > 0.3e-3:
                F_rad = self.particle_mass * self.gravity * 1.0  # 100% of weight radially
                force[0] -= F_rad * (dx / r_perp)
                force[1] -= F_rad * (dy / r_perp)
            
            # Vertical centering - push toward center height
            z_min = cz - self.target_extent / 2
            z_max = cz + self.target_extent / 2
            if z < z_min - 0.5e-3:
                force[2] += self.particle_mass * self.gravity * 0.8
            elif z > z_max + 0.5e-3:
                force[2] -= self.particle_mass * self.gravity * 0.8
        
        # ===== PHASE 1: CYLINDRICAL ORGANIZATION =====
        elif actual_phase == 1:
            # Maintain strong upward force
            force_mag_up = self.particle_mass * self.gravity * (1.2 - 0.4*phase_progress)
            force[2] += force_mag_up
            
            # Radial force: gradually expand to target radius
            goal_r = r_target * (0.3 + 0.7*phase_progress)  # Expand from 30% to 100% of target
            
            if r_perp < goal_r - 0.5e-3:
                # Too close: push outward
                F_rad = self.particle_mass * self.gravity * (0.5*phase_progress)
                if r_perp > 1e-10:
                    force[0] += F_rad * (dx / r_perp)
                    force[1] += F_rad * (dy / r_perp)
            elif r_perp > goal_r + 0.5e-3:
                # Too far: push inward
                F_rad = self.particle_mass * self.gravity * (0.8*phase_progress)
                force[0] -= F_rad * (dx / r_perp)
                force[1] -= F_rad * (dy / r_perp)
            
            # Vertical squeeze
            z_min = cz - self.target_extent / 2
            z_max = cz + self.target_extent / 2
            z_tolerance = 0.6e-3 * (1.0 - phase_progress)
            
            if z < z_min - z_tolerance:
                force[2] += self.particle_mass * self.gravity * 0.7
            elif z > z_max + z_tolerance:
                force[2] -= self.particle_mass * self.gravity * 0.7
        
        # ===== PHASE 2: TIGHT CONFINEMENT & SETTLING =====
        else:
            # Maintain moderate upward force
            force_mag_up = self.particle_mass * self.gravity * (0.8 - 0.3*phase_progress)
            force[2] += force_mag_up
            
            # Strong radial confinement at target radius
            tolerance = 0.2e-3
            F_rad = self.particle_mass * self.gravity * (0.9 - 0.2*phase_progress)
            
            if r_perp > r_target + tolerance:
                # Outside: push inward hard
                force[0] -= F_rad * (dx / r_perp) * 1.5
                force[1] -= F_rad * (dy / r_perp) * 1.5
            elif r_perp < r_target - tolerance and r_perp > 1e-4:
                # Inside: push outward
                force[0] += F_rad * (dx / r_perp) * 1.5
                force[1] += F_rad * (dy / r_perp) * 1.5
            
            # Vertical centering
            z_target = cz
            z_dev = z - z_target
            if np.abs(z_dev) > 0.1e-3:
                spring_force_z = -self.particle_mass * self.gravity * 1.2 * z_dev / (self.target_extent / 2)
                force[2] += spring_force_z
        
        return force


# =============================================================================
# SIMULATION CONFIGURATION
# =============================================================================

@dataclass
class Config:
    """Adaptive simulation configuration"""
    
    # Domain
    domain_size: float = 0.010  # 10mm cube
    
    # Particles
    n_particles: int = 500  # Increased for better 3D surface coverage
    particle_radius: float = 100e-6  # 0.1mm
    particle_density: float = 3000.0  # kg/m³
    particle_mass: float = (4/3) * np.pi * (100e-6)**3 * 3000.0
    
    # Physics
    gravity: float = 9.81
    dt: float = 1e-4        # bigger timestep
    t_max: float = 2.0
    output_interval: float = 0.15  # Increased for faster completion
    
    # Target shape (set dynamically)
    target_shape: ShapeTarget = None
    
    # Magnetic field generator (created after shape is set)
    mag_gen: MagneticFieldGenerator = None
    
    def set_target(self, shape: ShapeTarget):
        """Set target shape and initialize magnetic generator"""
        self.target_shape = shape
        self.mag_gen = MagneticFieldGenerator(shape, self.particle_mass, self.domain_size)
        print(f"\n[Target Set] {shape}")


# Global config
config = Config()

# =============================================================================
# TAICHI FIELDS
# =============================================================================

position = ti.Vector.field(3, dtype=ti.f32, shape=config.n_particles)
velocity = ti.Vector.field(3, dtype=ti.f32, shape=config.n_particles)
force = ti.Vector.field(3, dtype=ti.f32, shape=config.n_particles)
magnetic_force = ti.Vector.field(3, dtype=ti.f32, shape=config.n_particles)

# Additional fields for output
radius = ti.field(dtype=ti.f32, shape=config.n_particles)
mass = ti.field(dtype=ti.f32, shape=config.n_particles)

# Scalars
kinetic_energy = ti.field(dtype=ti.f32, shape=())
potential_energy = ti.field(dtype=ti.f32, shape=())
avg_z = ti.field(dtype=ti.f32, shape=())


# =============================================================================
# INITIALIZATION
# =============================================================================

def init_particles():
    """
    Initialize particles SETTLED AT BOTTOM (realistic initial condition)
    
    Particles start at rest on the floor of domain. Magnetic forces then
    guide them through phases:
    - Phase 0 (LIFT & CENTER): Levitation + radial inward
    - Phase 1 (ORGANIZE): Maintain lift + expand to radius
    - Phase 2 (CONFINE): Tight radial control + vertical settling
    """
    center, target_radius, target_height = config.target_shape.get_bounds()
    pos_np = np.zeros((config.n_particles, 3))
    
    np.random.seed(42)
    
    # ALL particles start at BOTTOM, scattered around XY plane
    # Z range: just above floor
    bottom_z = center[2] - target_height * 0.4 + np.random.rand(config.n_particles) * 0.3e-3
    
    # XY: Random distribution in larger region (will be pulled inward)
    xy_radius = target_radius * 1.5
    angles = np.random.uniform(0, 2*np.pi, config.n_particles)
    radii = np.random.uniform(0, xy_radius, config.n_particles)
    
    pos_np[:, 0] = center[0] + radii * np.cos(angles)
    pos_np[:, 1] = center[1] + radii * np.sin(angles)
    pos_np[:, 2] = bottom_z
    
    position.from_numpy(pos_np.astype(np.float32))
    
    # Set radius and mass
    rad_np = np.full(config.n_particles, config.particle_radius, dtype=np.float32)
    radius.from_numpy(rad_np)
    
    mass_np = np.full(config.n_particles, config.particle_mass, dtype=np.float32)
    mass.from_numpy(mass_np)
    
    print(f"\n[Initialization]")
    print(f"  Particles: {config.n_particles}")
    print(f"  Starting location: BOTTOM OF DOMAIN (Z ~= {bottom_z[0]*1e3:.2f}mm)")
    print(f"  XY Distribution: radius 0-{xy_radius*1e3:.2f}mm (outside target {target_radius*1e3:.2f}mm)")
    print(f"  Mass per particle: {config.particle_mass*1e12:.2f} pg")
    print(f"  Magnetic control: DIRECT PHASE-BASED (proven approach from magnetic_redesign.py)")


# =============================================================================
# PHYSICS KERNELS
# =============================================================================

@ti.kernel
def apply_gravity():
    """Apply gravitational force"""
    for i in position:
        force[i][2] -= config.particle_mass * config.gravity


@ti.kernel
def apply_damping():
    """Apply viscous damping"""
    damping_coeff = 0.95
    for i in velocity:
        velocity[i] *= damping_coeff


@ti.kernel
def integrate():
    """Integrate physics: F = ma"""
    for i in position:
        # Acceleration
        ax = force[i][0] / config.particle_mass
        ay = force[i][1] / config.particle_mass
        az = force[i][2] / config.particle_mass
        
        # Update velocity
        velocity[i][0] += ax * config.dt
        velocity[i][1] += ay * config.dt
        velocity[i][2] += az * config.dt
        
        # Update position
        position[i][0] += velocity[i][0] * config.dt
        position[i][1] += velocity[i][1] * config.dt
        position[i][2] += velocity[i][2] * config.dt
        
        # Reset force
        force[i] = [0, 0, 0]


@ti.kernel
def apply_boundary_conditions():
    """Enforce domain boundaries with elastic collisions"""
    for i in position:
        # X
        if position[i][0] < config.particle_radius:
            position[i][0] = config.particle_radius
            velocity[i][0] = ti.abs(velocity[i][0])
        if position[i][0] > config.domain_size - config.particle_radius:
            position[i][0] = config.domain_size - config.particle_radius
            velocity[i][0] = -ti.abs(velocity[i][0])
        
        # Y
        if position[i][1] < config.particle_radius:
            position[i][1] = config.particle_radius
            velocity[i][1] = ti.abs(velocity[i][1])
        if position[i][1] > config.domain_size - config.particle_radius:
            position[i][1] = config.domain_size - config.particle_radius
            velocity[i][1] = -ti.abs(velocity[i][1])
        
        # Z
        if position[i][2] < config.particle_radius:
            position[i][2] = config.particle_radius
            velocity[i][2] = ti.abs(velocity[i][2])
        if position[i][2] > config.domain_size - config.particle_radius:
            position[i][2] = config.domain_size - config.particle_radius
            velocity[i][2] = -ti.abs(velocity[i][2])


@ti.kernel
def clear_forces():
    """Clear force accumulator"""
    for i in force:
        force[i] = [0, 0, 0]


# =============================================================================
# ANALYSIS FUNCTIONS
# =============================================================================

def compute_energy():
    """Compute kinetic energy - Python version using NumPy"""
    vel_np = velocity.to_numpy()
    ke_total = 0.0
    for i in range(len(vel_np)):
        vel = vel_np[i]
        ke_total += 0.5 * config.particle_mass * (vel[0]**2 + vel[1]**2 + vel[2]**2)
    kinetic_energy[None] = ke_total


def compute_avg_z():
    """Compute average z position - Python version using NumPy"""
    pos_np = position.to_numpy()
    z_sum = 0.0
    for i in range(len(pos_np)):
        z_sum += pos_np[i][2]
    avg_z[None] = z_sum


# =============================================================================
# HIGH-LEVEL FUNCTIONS
# =============================================================================

def apply_adaptive_magnetic_forces(phase_progress: float):
    """
    Apply PROVEN DIRECT magnetic forces (from phase2_magnetic_redesign.py approach)
    
    This is the KEY function that works!
    Uses direct geometric forces instead of field gradients.
    Forces scale with phases naturally to guide particles through 3D shape.
    """
    # Get positions from Taichi
    pos_np = position.to_numpy()

    # Compute forces for all particles (CPU-side, then push to Taichi)
    forces_np = np.zeros((config.n_particles, 3), dtype=np.float32)
    for i in range(config.n_particles):
        # Pass ONLY position - no spatial mapping needed for basic test
        # Phase is determined internally by particle height
        forces_np[i] = config.mag_gen.get_force_at_particle(
            pos_np[i], phase_progress
        )

    # Convert to Taichi and apply
    magnetic_force.from_numpy(forces_np)

    # Add to existing forces in Taichi
    for i in range(config.n_particles):
        force[i] += magnetic_force[i]


def compute_shape_error() -> Tuple[float, int]:
    """
    Compute shape formation error
    
    Returns: (max_error_mm, num_inside_target)
    """
    pos_np = position.to_numpy()
    
    errors = []
    inside_count = 0
    
    for i in range(config.n_particles):
        pos = pos_np[i]
        
        if config.target_shape.is_inside(pos):
            inside_count += 1
            error = 0
        else:
            dist = config.target_shape.get_distance_to_surface(pos)
            error = dist
        
        errors.append(error)
    
    max_error = max(errors) if errors else 0
    return max_error * 1e3, inside_count  # Convert to mm


def simulate_phase(phase_num: int, duration: float, name: str, output_dir: str = None, global_time: float = 0.0) -> List[Tuple[float, str]]:
    """
    Simulate a single phase with adaptive forces and generate VTU output
    
    Args:
        phase_num: Phase number (1, 2, or 3)
        duration: Duration of phase in seconds
        name: Phase description
        output_dir: Directory for VTU output
        global_time: Starting absolute time (for correct PVD timestamps)
    
    Returns list of (absolute_time, vtu_filename) tuples for PVD generation
    """
    print(f"\n[Phase {phase_num}] {name} ({duration:.2f}s)")
    print(f"{'Time (s)':<10} {'KE (J)':<14} {'Avg Z (mm)':<12} {'Shape Error (mm)':<16} {'Inside':<10} {'Status'}")
    print("-" * 80)
    
    t = 0.0
    output_times = []
    next_output_t = 0.0  # First output at t=0
    timestep = 0
    total_steps = int(duration / config.dt)
    
    start_time = time.time()
    last_progress = 0
    
    # Initial output at t=0 (only for phase 1 to avoid duplicate t=0)
    if phase_num == 1:
        kinetic_energy[None] = 0
        compute_energy()
        avg_z[None] = 0
        compute_avg_z()
        
        ke = kinetic_energy[None]
        avg_z_val = avg_z[None] / config.n_particles
        error_mm, inside = compute_shape_error()
        status = "*" if inside >= config.n_particles * 0.95 else "o"
        abs_time = global_time + t
        print(f"{abs_time:<10.4f} {ke:<14.3e} {avg_z_val*1e3:<12.3f} {error_mm:<16.4f} {inside}/{config.n_particles}    {status}")
        
        if output_dir:
            vtu_file = os.path.join(output_dir, f"particles_t{abs_time:.4f}.vtu")
            write_vtu(vtu_file)
            output_times.append((abs_time, vtu_file))
        else:
            output_times.append((abs_time, ""))
        
        next_output_t += config.output_interval
    
    while t < duration:
        # Show progress every 5 seconds
        elapsed = time.time() - start_time
        if elapsed > last_progress + 5.0:
            pct = 100 * timestep / total_steps if total_steps > 0 else 0
            print(f"  [Progress] {timestep:,} / {total_steps:,} steps ({pct:.1f}%) ...", flush=True)
            last_progress = elapsed
        
        # Compute progress through phase
        phase_progress = t / duration if duration > 0 else 0
        
        # Clear forces
        clear_forces()
        
        # Apply all forces
        apply_gravity()
        apply_adaptive_magnetic_forces(phase_progress)
        
        # Physics
        integrate()
        apply_damping()
        apply_boundary_conditions()
        
        # Check if we should output (at exact times: 0.05, 0.10, ...)
        if t >= next_output_t - config.dt * 0.5:
            # Compute metrics
            kinetic_energy[None] = 0
            compute_energy()
            avg_z[None] = 0
            compute_avg_z()
            
            ke = kinetic_energy[None]
            avg_z_val = avg_z[None] / config.n_particles
            error_mm, inside = compute_shape_error()
            
            # Status indicator
            status = "*" if inside >= config.n_particles * 0.95 else "o"
            
            # Output formatted table row (use absolute time)
            abs_time = global_time + t
            print(f"{abs_time:<10.4f} {ke:<14.3e} {avg_z_val*1e3:<12.3f} {error_mm:<16.4f} {inside}/{config.n_particles}    {status}")
            
            # Generate VTU file
            if output_dir:
                vtu_file = os.path.join(output_dir, f"particles_t{abs_time:.4f}.vtu")
                write_vtu(vtu_file)
                output_times.append((abs_time, vtu_file))
            else:
                output_times.append((abs_time, ""))
            
            next_output_t += config.output_interval
        
        t += config.dt
        timestep += 1
    
    print("-" * 80)
    return output_times


# =============================================================================
# VTU/PVD OUTPUT
# =============================================================================

def write_vtu(filename: str):
    """Write VTU file in UnstructuredGrid format (ParaView compatible)"""
    pos_np = position.to_numpy()
    vel_np = velocity.to_numpy()
    rad_np = radius.to_numpy()
    mass_np = mass.to_numpy()
    
    n_particles = config.n_particles
    
    with open(filename, 'w') as f:
        # XML header
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="UnstructuredGrid" version="0.1" byte_order="LittleEndian">\n')
        f.write('  <UnstructuredGrid>\n')
        f.write(f'    <Piece NumberOfPoints="{n_particles}" NumberOfCells="{n_particles}">\n')
        
        # Points
        f.write('      <Points>\n')
        f.write('        <DataArray type="Float32" NumberOfComponents="3" format="ascii">\n')
        for i in range(n_particles):
            f.write(f'{pos_np[i][0]:.6e} {pos_np[i][1]:.6e} {pos_np[i][2]:.6e}\n')
        f.write('        </DataArray>\n')
        f.write('      </Points>\n')
        
        # Cells (one vertex per particle)
        f.write('      <Cells>\n')
        f.write('        <DataArray type="Int32" Name="connectivity" format="ascii">\n')
        for i in range(n_particles):
            f.write(f'{i}\n')
        f.write('        </DataArray>\n')
        f.write('        <DataArray type="Int32" Name="offsets" format="ascii">\n')
        for i in range(1, n_particles + 1):
            f.write(f'{i}\n')
        f.write('        </DataArray>\n')
        f.write('        <DataArray type="UInt8" Name="types" format="ascii">\n')
        for i in range(n_particles):
            f.write('1\n')  # VTK_VERTEX = 1
        f.write('        </DataArray>\n')
        f.write('      </Cells>\n')
        
        # PointData (attributes)
        f.write('      <PointData>\n')
        
        # Velocity
        f.write('        <DataArray type="Float32" Name="velocity" NumberOfComponents="3" format="ascii">\n')
        for i in range(n_particles):
            f.write(f'{vel_np[i][0]:.6e} {vel_np[i][1]:.6e} {vel_np[i][2]:.6e}\n')
        f.write('        </DataArray>\n')
        
        # Radius
        f.write('        <DataArray type="Float32" Name="radius" format="ascii">\n')
        for i in range(n_particles):
            f.write(f'{rad_np[i]:.6e}\n')
        f.write('        </DataArray>\n')
        
        # Mass
        f.write('        <DataArray type="Float32" Name="mass" format="ascii">\n')
        for i in range(n_particles):
            f.write(f'{mass_np[i]:.6e}\n')
        f.write('        </DataArray>\n')
        
        f.write('      </PointData>\n')
        f.write('    </Piece>\n')
        f.write('  </UnstructuredGrid>\n')
        f.write('</VTKFile>\n')


def write_pvd(output_dir: str, timesteps: List[Tuple[float, str]]):
    """Write PVD animation file"""
    pvd_path = os.path.join(output_dir, 'particles.pvd')
    
    with open(pvd_path, 'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="Collection" version="0.1">\n')
        f.write('  <Collection>\n')
        
        for t, vtu_file in timesteps:
            vtu_name = os.path.basename(vtu_file)
            # Use rounded time to avoid floating-point precision issues
            t_rounded = round(t, 4)
            f.write(f'    <DataSet timestep="{t_rounded}" file="{vtu_name}"/>\n')
        
        f.write('  </Collection>\n')
        f.write('</VTKFile>\n')
    
    print(f"[PVD] Written: {pvd_path} ({len(timesteps)} timesteps)")


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def main():
    """Main simulation with test shapes"""
    
    # Test Specification 1: CYLINDER
    print("\n" + "="*70)
    print("TEST 1: CYLINDER - Original benchmark shape")
    print("="*70)
    
    config.set_target(Cylinder(
        center=[5.0e-3, 5.0e-3, 5.0e-3],
        radius=2.5e-3,
        height=4.0e-3
    ))
    
    init_particles()
    output_dir = 'outputs/Phase2_Adaptive/cylinder'
    os.makedirs(output_dir, exist_ok=True)
    
    # Clear any old output files
    for f in os.listdir(output_dir):
        if f.endswith('.vtu') or f.endswith('.pvd'):
            os.remove(os.path.join(output_dir, f))
    
    start_time = time.time()
    all_output_times = []
    global_time = 0.0
    
    # Phase 1: Levitation & centering
    times1 = simulate_phase(1, 0.5, "Levitation & Centering", output_dir, global_time)
    all_output_times.extend(times1)
    global_time += 0.5
    
    # Phase 2: Cylindrical organization
    times2 = simulate_phase(2, 0.7, "Cylindrical Organization", output_dir, global_time)
    all_output_times.extend(times2)
    global_time += 0.7
    
    # Phase 3: Stabilization
    times3 = simulate_phase(3, 0.8, "Stabilization", output_dir, global_time)
    all_output_times.extend(times3)
    global_time += 0.8
    
    elapsed = time.time() - start_time
    print(f"\n[Complete] Simulation completed in {elapsed:.1f}s")
    
    # Analysis
    error_mm, inside = compute_shape_error()
    print(f"\n[Final Results]")
    print(f"  Shape error: {error_mm:.3f} mm")
    print(f"  Particles inside: {inside}/{config.n_particles} ({100*inside/config.n_particles:.1f}%)")
    
    ke = 0
    for i in range(config.n_particles):
        vel = velocity[i]
        ke += 0.5 * config.particle_mass * (vel[0]**2 + vel[1]**2 + vel[2]**2)
    print(f"  Final KE: {ke:.2e} J")
    
    # Write PVD animation file
    write_pvd(output_dir, all_output_times)
    print(f"\n[Output] Generated {len(all_output_times)} VTU files")
    print(f"[Output] PVD animation: {os.path.join(output_dir, 'particles.pvd')}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Interrupted by user]")
    except Exception as e:
        print("\n[FATAL ERROR]")
        raise