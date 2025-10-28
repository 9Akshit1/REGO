#!/usr/bin/env python3
"""
FEM-DEM Magnetic Field Coupling for Lunar Regolith Simulation
==============================================================

This script couples magnetic field data from FEMM (Finite Element Method Magnetics)
into a DEM (Discrete Element Method) simulation for lunar regolith particles.

Author: AI Assistant
Date: 2025-10-23
Python: 3.9+

Requirements:
    - numpy
    - scipy
    - matplotlib
    - h5py (optional, for field caching)

Usage:
    1. Place your FEMM B_output.txt file in the working directory
    2. Adjust CONFIG section below for your simulation parameters
    3. Run: python fem_dem_coupling.py
    4. The script will:
       - Parse and crop the magnetic field data
       - Visualize the field
       - Set up a DEM simulation with 4 particles (2 magnetic, 2 non-magnetic)
       - Apply magnetic forces during simulation
       - Output particle trajectories

Physical Model:
    - Lunar gravity: 1.62 m/s² (downward)
    - Vacuum environment (no drag)
    - Paramagnetic force: F = V * (χ/μ₀) * (B·∇)B
    - 4 particles: 2 silicate (non-magnetic), 2 magnetic
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import LinearNDInterpolator, RegularGridInterpolator
from scipy.ndimage import gaussian_filter
from scipy.spatial import ConvexHull
import warnings
import os
from dataclasses import dataclass
from typing import Tuple, Optional, Dict, List

# ============================================================================
# CONFIGURATION SECTION
# ============================================================================

@dataclass
class Config:
    """Central configuration for FEM-DEM coupling simulation"""
    
    # File paths
    femm_data_file: str = "B_output.txt"
    output_dir: str = "output"
    
    # Field processing parameters
    field_threshold_factor: float = 3.0  # Threshold = factor × noise_floor
    field_threshold_abs: float = 1e-4    # Absolute threshold [T]
    coil_padding: float = 0.02           # Padding around coil region [m]
    use_manual_crop: bool = False
    manual_crop_bounds: Tuple = (-0.1, 0.1, -0.1, 0.1)  # (xmin, xmax, ymin, ymax) [m]
    
    # Field smoothing
    apply_smoothing: bool = True
    gaussian_sigma: float = 1.0
    
    # DEM domain parameters
    dem_box_size: Tuple[float, float, float] = (0.2, 0.2, 0.05)  # [m] (x, y, z)
    dem_center: Tuple[float, float, float] = (0.0, 0.0, 0.025)   # [m]
    
    # Physical constants
    mu_0: float = 4 * np.pi * 1e-7       # Vacuum permeability [H/m]
    g_lunar: float = 1.62                # Lunar gravity [m/s²]
    
    # Material properties - Silicate (non-magnetic baseline)
    silicate_density: float = 2800.0     # [kg/m³]
    silicate_radius: float = 50e-6       # [m] (50 microns)
    silicate_chi: float = 1e-8           # Magnetic susceptibility (essentially zero)
    silicate_youngs: float = 5e9         # Young's modulus [Pa]
    silicate_poisson: float = 0.25       # Poisson's ratio
    
    # Material properties - Magnetic regolith
    magnetic_density: float = 3200.0     # [kg/m³]
    magnetic_radius: float = 70e-6       # [m] (70 microns)
    magnetic_chi: float = 5e-5           # Magnetic susceptibility
    magnetic_youngs: float = 6e9         # Young's modulus [Pa]
    magnetic_poisson: float = 0.27       # Poisson's ratio
    
    # Common material properties
    restitution: float = 0.3             # Coefficient of restitution
    friction_static: float = 0.5         # Static friction
    friction_kinetic: float = 0.4        # Kinetic friction
    friction_rolling: float = 0.01       # Rolling friction coefficient
    
    # Simulation parameters
    dt: float = 1e-6                     # Timestep [s]
    sim_duration: float = 0.01           # Total simulation time [s]
    output_interval: int = 100           # Output every N steps
    
    # 3D field extrusion
    extrude_to_3d: bool = True
    z_decay_length: float = 0.02         # Gaussian decay in z [m]

# Initialize configuration
cfg = Config()

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def ensure_output_dir():
    """Create output directory if it doesn't exist"""
    os.makedirs(cfg.output_dir, exist_ok=True)

def log(message: str):
    """Simple logging function"""
    print(f"[FEM-DEM] {message}")

# ============================================================================
# FEM DATA PARSING AND PROCESSING
# ============================================================================

class FEMMFieldData:
    """Container for parsed FEMM magnetic field data"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.raw_data = None
        self.x = None
        self.y = None
        self.Bx = None
        self.By = None
        self.B_mag = None
        self.dBx_dx = None
        self.dBx_dy = None
        self.dBy_dx = None
        self.dBy_dy = None
        self.has_gradients = False
        self.coil_bounds = None
        
    def parse(self):
        """Parse FEMM output file, skipping comments"""
        log(f"Parsing FEMM data from {self.filepath}")
        
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"FEMM data file not found: {self.filepath}")
        
        # Read file, skip comment lines
        data_lines = []
        with open(self.filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    data_lines.append(line)
        
        if not data_lines:
            raise ValueError("No data found in FEMM file (only comments)")
        
        # Parse data
        data = []
        for line in data_lines:
            parts = line.split()
            if len(parts) >= 5:  # Minimum: X Y Bx By B_mag
                data.append([float(x) for x in parts[:13]])  # Take first 13 columns
        
        self.raw_data = np.array(data)
        log(f"Parsed {len(self.raw_data)} field points")
        
        # Extract columns and convert units (cm -> m, T/cm -> T/m)
        self.x = self.raw_data[:, 0] * 0.01      # cm -> m
        self.y = self.raw_data[:, 1] * 0.01      # cm -> m
        self.Bx = self.raw_data[:, 2]            # Tesla (already SI)
        self.By = self.raw_data[:, 3]            # Tesla
        self.B_mag = self.raw_data[:, 4]         # Tesla
        
        # Check for gradient columns
        if self.raw_data.shape[1] >= 9:
            self.dBx_dx = self.raw_data[:, 5] * 100  # T/cm -> T/m
            self.dBx_dy = self.raw_data[:, 6] * 100
            self.dBy_dx = self.raw_data[:, 7] * 100
            self.dBy_dy = self.raw_data[:, 8] * 100
            self.has_gradients = True
            log("Gradient data found in FEMM file")
        else:
            log("No gradient data found - will compute numerically")
        
        self._validate_data()
        
    def _validate_data(self):
        """Validate parsed data"""
        required_arrays = [self.x, self.y, self.Bx, self.By, self.B_mag]
        if any(arr is None for arr in required_arrays):
            raise ValueError("Missing required field data columns")
        
        if len(self.x) < 4:
            raise ValueError("Insufficient data points for interpolation")
        
        log(f"Field range: X=[{self.x.min():.4f}, {self.x.max():.4f}] m")
        log(f"             Y=[{self.y.min():.4f}, {self.y.max():.4f}] m")
        log(f"             |B|=[{self.B_mag.min():.6f}, {self.B_mag.max():.6f}] T")

    def detect_coil_region(self):
        """Automatically detect the coil region where B field is significant"""
        log("Detecting coil region...")
        
        if cfg.use_manual_crop:
            xmin, xmax, ymin, ymax = cfg.manual_crop_bounds
            self.coil_bounds = (xmin, xmax, ymin, ymax)
            log(f"Using manual crop bounds: {self.coil_bounds}")
            return
        
        # Calculate noise floor (use percentile of low-field regions)
        B_sorted = np.sort(self.B_mag)
        noise_floor = B_sorted[int(len(B_sorted) * 0.1)]  # 10th percentile
        
        # Threshold for significant field
        threshold = max(
            cfg.field_threshold_factor * noise_floor,
            cfg.field_threshold_abs
        )
        
        log(f"Noise floor: {noise_floor:.6f} T")
        log(f"Field threshold: {threshold:.6f} T")
        
        # Find points above threshold
        mask = self.B_mag > threshold
        if not np.any(mask):
            log("WARNING: No points above threshold - using full domain")
            mask = np.ones_like(self.B_mag, dtype=bool)
        
        x_active = self.x[mask]
        y_active = self.y[mask]
        
        # Compute bounding box
        xmin, xmax = x_active.min(), x_active.max()
        ymin, ymax = y_active.min(), y_active.max()
        
        # Add padding
        x_pad = cfg.coil_padding
        y_pad = cfg.coil_padding
        
        self.coil_bounds = (
            xmin - x_pad,
            xmax + x_pad,
            ymin - y_pad,
            ymax + y_pad
        )
        
        log(f"Coil region detected: X=[{xmin:.4f}, {xmax:.4f}] m")
        log(f"                      Y=[{ymin:.4f}, {ymax:.4f}] m")
        log(f"With padding:         X=[{self.coil_bounds[0]:.4f}, {self.coil_bounds[1]:.4f}] m")
        log(f"                      Y=[{self.coil_bounds[2]:.4f}, {self.coil_bounds[3]:.4f}] m")
        
        n_active = np.sum(mask)
        log(f"Active field points: {n_active}/{len(self.B_mag)} ({100*n_active/len(self.B_mag):.1f}%)")
    
    def crop_to_coil(self):
        """Crop field data to coil region"""
        if self.coil_bounds is None:
            self.detect_coil_region()
        
        xmin, xmax, ymin, ymax = self.coil_bounds
        
        mask = (
            (self.x >= xmin) & (self.x <= xmax) &
            (self.y >= ymin) & (self.y <= ymax)
        )
        
        log(f"Cropping to coil region: {np.sum(mask)}/{len(mask)} points retained")
        
        self.x = self.x[mask]
        self.y = self.y[mask]
        self.Bx = self.Bx[mask]
        self.By = self.By[mask]
        self.B_mag = self.B_mag[mask]
        
        if self.has_gradients:
            self.dBx_dx = self.dBx_dx[mask]
            self.dBx_dy = self.dBx_dy[mask]
            self.dBy_dx = self.dBy_dx[mask]
            self.dBy_dy = self.dBy_dy[mask]
    
    def is_structured_grid(self) -> bool:
        """Check if data is on a structured grid"""
        unique_x = np.unique(self.x)
        unique_y = np.unique(self.y)
        
        expected_points = len(unique_x) * len(unique_y)
        actual_points = len(self.x)
        
        is_structured = (expected_points == actual_points)
        
        if is_structured:
            log(f"Structured grid detected: {len(unique_x)}×{len(unique_y)}")
        else:
            log(f"Scattered data detected: {actual_points} points")
        
        return is_structured

# ============================================================================
# FIELD INTERPOLATION
# ============================================================================

class MagneticFieldInterpolator:
    """Interpolate magnetic field data for arbitrary query points"""
    
    def __init__(self, field_data: FEMMFieldData):
        self.field_data = field_data
        self.interp_Bx = None
        self.interp_By = None
        self.interp_B_mag = None
        self.interp_dBx_dx = None
        self.interp_dBx_dy = None
        self.interp_dBy_dx = None
        self.interp_dBy_dy = None
        self.is_3d = False
        
    def build_interpolators(self):
        """Build interpolation functions for field components"""
        log("Building field interpolators...")
        
        points = np.column_stack([self.field_data.x, self.field_data.y])
        
        # Build interpolators for field components
        self.interp_Bx = LinearNDInterpolator(points, self.field_data.Bx, fill_value=0.0)
        self.interp_By = LinearNDInterpolator(points, self.field_data.By, fill_value=0.0)
        self.interp_B_mag = LinearNDInterpolator(points, self.field_data.B_mag, fill_value=0.0)
        
        # Build gradient interpolators
        if self.field_data.has_gradients:
            self.interp_dBx_dx = LinearNDInterpolator(points, self.field_data.dBx_dx, fill_value=0.0)
            self.interp_dBx_dy = LinearNDInterpolator(points, self.field_data.dBx_dy, fill_value=0.0)
            self.interp_dBy_dx = LinearNDInterpolator(points, self.field_data.dBy_dx, fill_value=0.0)
            self.interp_dBy_dy = LinearNDInterpolator(points, self.field_data.dBy_dy, fill_value=0.0)
            log("Gradient interpolators built from FEMM data")
        else:
            self._compute_gradients_numerically()
            log("Gradients computed numerically")
        
        log("Field interpolators ready")
    
    def _compute_gradients_numerically(self):
        """Compute field gradients using finite differences"""
        # Use central differences on a local neighborhood
        points = np.column_stack([self.field_data.x, self.field_data.y])
        
        # For each point, estimate gradients from neighbors
        n_points = len(self.field_data.x)
        dBx_dx = np.zeros(n_points)
        dBx_dy = np.zeros(n_points)
        dBy_dx = np.zeros(n_points)
        dBy_dy = np.zeros(n_points)
        
        # Simple approach: use nearby points for finite difference
        from scipy.spatial import cKDTree
        tree = cKDTree(points)
        
        for i in range(n_points):
            # Find 10 nearest neighbors
            distances, indices = tree.query(points[i], k=min(10, n_points))
            
            if len(indices) > 3:
                # Fit local plane using least squares
                neighbor_points = points[indices]
                dx = neighbor_points[:, 0] - points[i, 0]
                dy = neighbor_points[:, 1] - points[i, 1]
                
                # Skip if all neighbors are too close
                if np.max(np.abs(dx)) > 1e-10 and np.max(np.abs(dy)) > 1e-10:
                    # Gradient of Bx
                    dBx = self.field_data.Bx[indices] - self.field_data.Bx[i]
                    A = np.column_stack([dx, dy])
                    try:
                        coeffs, _, _, _ = np.linalg.lstsq(A, dBx, rcond=None)
                        dBx_dx[i], dBx_dy[i] = coeffs
                    except:
                        pass
                    
                    # Gradient of By
                    dBy = self.field_data.By[indices] - self.field_data.By[i]
                    try:
                        coeffs, _, _, _ = np.linalg.lstsq(A, dBy, rcond=None)
                        dBy_dx[i], dBy_dy[i] = coeffs
                    except:
                        pass
        
        # Build interpolators for computed gradients
        self.interp_dBx_dx = LinearNDInterpolator(points, dBx_dx, fill_value=0.0)
        self.interp_dBx_dy = LinearNDInterpolator(points, dBx_dy, fill_value=0.0)
        self.interp_dBy_dx = LinearNDInterpolator(points, dBy_dx, fill_value=0.0)
        self.interp_dBy_dy = LinearNDInterpolator(points, dBy_dy, fill_value=0.0)
    
    def query_field_2d(self, x: np.ndarray, y: np.ndarray) -> Dict[str, np.ndarray]:
        """Query field at given (x,y) positions"""
        Bx = self.interp_Bx(x, y)
        By = self.interp_By(x, y)
        B_mag = self.interp_B_mag(x, y)
        
        dBx_dx = self.interp_dBx_dx(x, y)
        dBx_dy = self.interp_dBx_dy(x, y)
        dBy_dx = self.interp_dBy_dx(x, y)
        dBy_dy = self.interp_dBy_dy(x, y)
        
        return {
            'Bx': Bx, 'By': By, 'Bz': np.zeros_like(Bx),
            'B_mag': B_mag,
            'dBx_dx': dBx_dx, 'dBx_dy': dBx_dy, 'dBx_dz': np.zeros_like(Bx),
            'dBy_dx': dBy_dx, 'dBy_dy': dBy_dy, 'dBy_dz': np.zeros_like(By),
            'dBz_dx': np.zeros_like(Bx), 'dBz_dy': np.zeros_like(By), 'dBz_dz': np.zeros_like(Bx)
        }
    
    def query_field_3d(self, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> Dict[str, np.ndarray]:
        """Query 3D extruded field (with z-decay)"""
        # Get 2D field
        field_2d = self.query_field_2d(x, y)
        
        if not cfg.extrude_to_3d:
            return field_2d
        
        # Apply Gaussian decay in z direction
        z_center = cfg.dem_center[2]
        decay = np.exp(-((z - z_center)**2) / (2 * cfg.z_decay_length**2))
        
        # Scale all field components by decay
        for key in field_2d:
            field_2d[key] = field_2d[key] * decay
        
        return field_2d

# ============================================================================
# MAGNETIC FORCE COMPUTATION
# ============================================================================

class MagneticForceCalculator:
    """Calculate magnetic forces on particles"""
    
    def __init__(self, interpolator: MagneticFieldInterpolator):
        self.interpolator = interpolator
        
    def compute_paramagnetic_force(self, pos: np.ndarray, volume: float, 
                                   chi: float) -> np.ndarray:
        """
        Compute paramagnetic force on a particle.
        
        F = V * (χ/μ₀) * (B·∇)B
        
        Args:
            pos: Particle position [x, y, z] in meters
            volume: Particle volume in m³
            chi: Magnetic susceptibility (dimensionless)
        
        Returns:
            Force vector [Fx, Fy, Fz] in Newtons
        """
        if chi < 1e-10:  # Essentially non-magnetic
            return np.zeros(3)
        
        # Query field at particle position
        x, y, z = pos
        field = self.interpolator.query_field_3d(
            np.array([x]), np.array([y]), np.array([z])
        )
        
        Bx = field['Bx'][0]
        By = field['By'][0]
        Bz = field['Bz'][0]
        
        dBx_dx = field['dBx_dx'][0]
        dBx_dy = field['dBx_dy'][0]
        dBx_dz = field['dBx_dz'][0]
        
        dBy_dx = field['dBy_dx'][0]
        dBy_dy = field['dBy_dy'][0]
        dBy_dz = field['dBy_dz'][0]
        
        dBz_dx = field['dBz_dx'][0]
        dBz_dy = field['dBz_dy'][0]
        dBz_dz = field['dBz_dz'][0]
        
        # Compute (B·∇)B for each component
        # Fx = Bx*dBx/dx + By*dBx/dy + Bz*dBx/dz
        Fx = Bx * dBx_dx + By * dBx_dy + Bz * dBx_dz
        Fy = Bx * dBy_dx + By * dBy_dy + Bz * dBy_dz
        Fz = Bx * dBz_dx + By * dBz_dy + Bz * dBz_dz
        
        # Scale by V * χ/μ₀
        prefactor = volume * chi / cfg.mu_0
        
        force = prefactor * np.array([Fx, Fy, Fz])
        
        return force

# ============================================================================
# VISUALIZATION
# ============================================================================

class FieldVisualizer:
    """Visualize magnetic field data"""
    
    def __init__(self, field_data: FEMMFieldData):
        self.field_data = field_data
        
    def plot_field_overview(self, save_path: Optional[str] = None):
        """Plot overview of magnetic field"""
        fig, axes = plt.subplots(2, 2, figsize=(14, 12))
        
        # Bx component
        ax = axes[0, 0]
        scatter = ax.scatter(self.field_data.x, self.field_data.y, 
                           c=self.field_data.Bx, s=2, cmap='RdBu_r')
        ax.set_xlabel('X [m]')
        ax.set_ylabel('Y [m]')
        ax.set_title('Bx [T]')
        ax.set_aspect('equal')
        plt.colorbar(scatter, ax=ax)
        
        # By component
        ax = axes[0, 1]
        scatter = ax.scatter(self.field_data.x, self.field_data.y, 
                           c=self.field_data.By, s=2, cmap='RdBu_r')
        ax.set_xlabel('X [m]')
        ax.set_ylabel('Y [m]')
        ax.set_title('By [T]')
        ax.set_aspect('equal')
        plt.colorbar(scatter, ax=ax)
        
        # |B| magnitude
        ax = axes[1, 0]
        scatter = ax.scatter(self.field_data.x, self.field_data.y, 
                           c=self.field_data.B_mag, s=2, cmap='hot')
        ax.set_xlabel('X [m]')
        ax.set_ylabel('Y [m]')
        ax.set_title('|B| [T]')
        ax.set_aspect('equal')
        plt.colorbar(scatter, ax=ax)
        
        # Coil region overlay
        if self.field_data.coil_bounds is not None:
            xmin, xmax, ymin, ymax = self.field_data.coil_bounds
            from matplotlib.patches import Rectangle
            rect = Rectangle((xmin, ymin), xmax-xmin, ymax-ymin,
                           linewidth=2, edgecolor='cyan', facecolor='none',
                           label='Coil region')
            ax.add_patch(rect)
            ax.legend()
        
        # Quiver plot
        ax = axes[1, 1]
        # Subsample for quiver
        stride = max(1, len(self.field_data.x) // 500)
        x_sub = self.field_data.x[::stride]
        y_sub = self.field_data.y[::stride]
        Bx_sub = self.field_data.Bx[::stride]
        By_sub = self.field_data.By[::stride]
        B_mag_sub = self.field_data.B_mag[::stride]
        
        ax.quiver(x_sub, y_sub, Bx_sub, By_sub, B_mag_sub, 
                 cmap='hot', scale=None)
        ax.set_xlabel('X [m]')
        ax.set_ylabel('Y [m]')
        ax.set_title('B field direction')
        ax.set_aspect('equal')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            log(f"Field visualization saved to {save_path}")
        
        plt.show()

# ============================================================================
# DEM PARTICLE CLASS
# ============================================================================

@dataclass
class Particle:
    """DEM particle with magnetic properties"""
    id: int
    material_type: str  # 'silicate' or 'magnetic'
    radius: float       # [m]
    density: float      # [kg/m³]
    chi: float          # Magnetic susceptibility
    
    # State variables
    position: np.ndarray = None      # [x, y, z] [m]
    velocity: np.ndarray = None      # [vx, vy, vz] [m/s]
    force: np.ndarray = None         # [Fx, Fy, Fz] [N]
    
    def __post_init__(self):
        if self.position is None:
            self.position = np.zeros(3)
        if self.velocity is None:
            self.velocity = np.zeros(3)
        if self.force is None:
            self.force = np.zeros(3)
    
    @property
    def mass(self) -> float:
        """Particle mass [kg]"""
        return self.density * self.volume
    
    @property
    def volume(self) -> float:
        """Particle volume [m³]"""
        return (4.0/3.0) * np.pi * self.radius**3

# ============================================================================
# SIMPLE DEM SIMULATOR
# ============================================================================

class SimpleDEMSimulator:
    """
    Simple DEM simulator for demonstration.
    
    Note: This is a minimal implementation for demonstration. For production
    simulations, integrate with OpenFDEM or another DEM framework.
    """
    
    def __init__(self, particles: List[Particle], 
                 magnetic_calculator: MagneticForceCalculator):
        self.particles = particles
        self.magnetic_calculator = magnetic_calculator
        self.time = 0.0
        self.step = 0
        
        # Trajectory storage
        self.trajectories = {p.id: {'t': [], 'pos': [], 'vel': [], 'force': []} 
                            for p in particles}
        
    def apply_gravity(self):
        """Apply lunar gravity to all particles"""
        for p in self.particles:
            # Gravity acts in -z direction (downward)
            F_gravity = np.array([0.0, 0.0, -p.mass * cfg.g_lunar])
            p.force += F_gravity
    
    def apply_magnetic_forces(self):
        """Apply magnetic forces to all particles"""
        for p in self.particles:
            F_mag = self.magnetic_calculator.compute_paramagnetic_force(
                p.position, p.volume, p.chi
            )
            p.force += F_mag
    
    def apply_boundary_forces(self):
        """Simple boundary forces (soft walls)"""
        k_wall = 1e3  # Wall stiffness [N/m]
        
        xmin, ymin, zmin = np.array(cfg.dem_center) - np.array(cfg.dem_box_size) / 2
        xmax, ymax, zmax = np.array(cfg.dem_center) + np.array(cfg.dem_box_size) / 2
        
        for p in self.particles:
            x, y, z = p.position
            
            # X boundaries
            if x < xmin:
                p.force[0] += k_wall * (xmin - x)
            elif x > xmax:
                p.force[0] += k_wall * (xmax - x)
            
            # Y boundaries
            if y < ymin:
                p.force[1] += k_wall * (ymin - y)
            elif y > ymax:
                p.force[1] += k_wall * (ymax - y)
            
            # Z boundaries (floor at zmin)
            if z < zmin:
                p.force[2] += k_wall * (zmin - z)
                # Add damping to prevent bouncing
                p.velocity[2] *= 0.5
            elif z > zmax:
                p.force[2] += k_wall * (zmax - z)
    
    def integrate_step(self, dt: float):
        """Integrate equations of motion using velocity Verlet"""
        for p in self.particles:
            # Velocity Verlet integration
            # v(t+dt/2) = v(t) + a(t)*dt/2
            a = p.force / p.mass
            p.velocity += 0.5 * a * dt
            
            # x(t+dt) = x(t) + v(t+dt/2)*dt
            p.position += p.velocity * dt
            
            # Reset forces for next step
            p.force = np.zeros(3)
    
    def finalize_velocities(self, dt: float):
        """Finalize velocities after force computation"""
        for p in self.particles:
            # v(t+dt) = v(t+dt/2) + a(t+dt)*dt/2
            a = p.force / p.mass
            p.velocity += 0.5 * a * dt
    
    def record_state(self):
        """Record current state of all particles"""
        for p in self.particles:
            self.trajectories[p.id]['t'].append(self.time)
            self.trajectories[p.id]['pos'].append(p.position.copy())
            self.trajectories[p.id]['vel'].append(p.velocity.copy())
            self.trajectories[p.id]['force'].append(p.force.copy())
    
    def run(self, duration: float, dt: float, output_interval: int = 100):
        """Run DEM simulation"""
        n_steps = int(duration / dt)
        log(f"Starting DEM simulation: {n_steps} steps, dt={dt:.2e} s")
        
        self.record_state()
        
        for step in range(n_steps):
            # Reset forces
            for p in self.particles:
                p.force = np.zeros(3)
            
            # Apply all forces
            self.apply_gravity()
            self.apply_magnetic_forces()
            self.apply_boundary_forces()
            
            # Integrate (first half)
            self.integrate_step(dt)
            
            # Recompute forces at new positions
            for p in self.particles:
                p.force = np.zeros(3)
            self.apply_gravity()
            self.apply_magnetic_forces()
            self.apply_boundary_forces()
            
            # Finalize velocities
            self.finalize_velocities(dt)
            
            self.time += dt
            self.step += 1
            
            # Record output
            if step % output_interval == 0:
                self.record_state()
                if step % (output_interval * 10) == 0:
                    log(f"Step {step}/{n_steps}, t={self.time:.6f} s")
        
        # Final record
        self.record_state()
        log(f"Simulation complete: {self.step} steps")
    
    def plot_trajectories(self, save_path: Optional[str] = None):
        """Plot particle trajectories"""
        fig = plt.figure(figsize=(16, 10))
        
        # 3D trajectory plot
        ax1 = fig.add_subplot(2, 3, 1, projection='3d')
        for pid, traj in self.trajectories.items():
            pos = np.array(traj['pos'])
            p = next(p for p in self.particles if p.id == pid)
            label = f"P{pid} ({p.material_type})"
            ax1.plot(pos[:, 0], pos[:, 1], pos[:, 2], label=label, marker='o', markersize=2)
        ax1.set_xlabel('X [m]')
        ax1.set_ylabel('Y [m]')
        ax1.set_zlabel('Z [m]')
        ax1.set_title('Particle Trajectories (3D)')
        ax1.legend()
        
        # X-Y projection
        ax2 = fig.add_subplot(2, 3, 2)
        for pid, traj in self.trajectories.items():
            pos = np.array(traj['pos'])
            p = next(p for p in self.particles if p.id == pid)
            label = f"P{pid} ({p.material_type})"
            ax2.plot(pos[:, 0], pos[:, 1], label=label, marker='o', markersize=2)
        ax2.set_xlabel('X [m]')
        ax2.set_ylabel('Y [m]')
        ax2.set_title('Trajectories (X-Y view)')
        ax2.set_aspect('equal')
        ax2.legend()
        ax2.grid(True)
        
        # Z vs time
        ax3 = fig.add_subplot(2, 3, 3)
        for pid, traj in self.trajectories.items():
            t = np.array(traj['t'])
            pos = np.array(traj['pos'])
            p = next(p for p in self.particles if p.id == pid)
            label = f"P{pid} ({p.material_type})"
            ax3.plot(t * 1000, pos[:, 2], label=label)
        ax3.set_xlabel('Time [ms]')
        ax3.set_ylabel('Z position [m]')
        ax3.set_title('Vertical Position vs Time')
        ax3.legend()
        ax3.grid(True)
        
        # Velocity magnitude
        ax4 = fig.add_subplot(2, 3, 4)
        for pid, traj in self.trajectories.items():
            t = np.array(traj['t'])
            vel = np.array(traj['vel'])
            vel_mag = np.linalg.norm(vel, axis=1)
            p = next(p for p in self.particles if p.id == pid)
            label = f"P{pid} ({p.material_type})"
            ax4.plot(t * 1000, vel_mag, label=label)
        ax4.set_xlabel('Time [ms]')
        ax4.set_ylabel('|v| [m/s]')
        ax4.set_title('Velocity Magnitude vs Time')
        ax4.legend()
        ax4.grid(True)
        
        # Magnetic force magnitude
        ax5 = fig.add_subplot(2, 3, 5)
        for pid, traj in self.trajectories.items():
            t = np.array(traj['t'])
            force = np.array(traj['force'])
            force_mag = np.linalg.norm(force, axis=1)
            p = next(p for p in self.particles if p.id == pid)
            label = f"P{pid} ({p.material_type})"
            ax5.plot(t * 1000, force_mag * 1e9, label=label)  # Convert to nN
        ax5.set_xlabel('Time [ms]')
        ax5.set_ylabel('|F| [nN]')
        ax5.set_title('Total Force Magnitude vs Time')
        ax5.legend()
        ax5.grid(True)
        
        # Energy
        ax6 = fig.add_subplot(2, 3, 6)
        for pid, traj in self.trajectories.items():
            t = np.array(traj['t'])
            pos = np.array(traj['pos'])
            vel = np.array(traj['vel'])
            p = next(p for p in self.particles if p.id == pid)
            
            # Kinetic energy
            KE = 0.5 * p.mass * np.sum(vel**2, axis=1)
            # Potential energy (gravitational)
            PE = p.mass * cfg.g_lunar * pos[:, 2]
            # Total energy
            E_total = KE + PE
            
            label = f"P{pid} ({p.material_type})"
            ax6.plot(t * 1000, E_total * 1e12, label=label)  # Convert to pJ
        ax6.set_xlabel('Time [ms]')
        ax6.set_ylabel('Total Energy [pJ]')
        ax6.set_title('Total Energy vs Time')
        ax6.legend()
        ax6.grid(True)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            log(f"Trajectory plot saved to {save_path}")
        
        plt.show()

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def create_particles() -> List[Particle]:
    """Create initial particle configuration"""
    particles = []
    
    # Starting positions (staggered in the coil region)
    positions = [
        np.array([0.02, 0.02, 0.03]),   # Silicate 1
        np.array([-0.02, 0.02, 0.035]),  # Silicate 2
        np.array([0.02, -0.02, 0.032]),  # Magnetic 1
        np.array([-0.02, -0.02, 0.037]), # Magnetic 2
    ]
    
    # Create 2 silicate particles
    for i in range(2):
        p = Particle(
            id=i,
            material_type='silicate',
            radius=cfg.silicate_radius,
            density=cfg.silicate_density,
            chi=cfg.silicate_chi,
            position=positions[i].copy(),
            velocity=np.zeros(3)
        )
        particles.append(p)
        log(f"Created particle {i}: silicate, r={p.radius*1e6:.1f} µm, "
            f"m={p.mass*1e9:.3f} ng, χ={p.chi:.2e}")
    
    # Create 2 magnetic particles
    for i in range(2):
        p = Particle(
            id=i+2,
            material_type='magnetic',
            radius=cfg.magnetic_radius,
            density=cfg.magnetic_density,
            chi=cfg.magnetic_chi,
            position=positions[i+2].copy(),
            velocity=np.zeros(3)
        )
        particles.append(p)
        log(f"Created particle {i+2}: magnetic, r={p.radius*1e6:.1f} µm, "
            f"m={p.mass*1e9:.3f} ng, χ={p.chi:.2e}")
    
    return particles

def create_synthetic_field() -> FEMMFieldData:
    """Create synthetic magnetic field for testing when FEMM file not available"""
    log("Creating synthetic magnetic field for testing...")
    
    # Create a simple dipole-like field
    x = np.linspace(-0.1, 0.1, 50)
    y = np.linspace(-0.1, 0.1, 50)
    X, Y = np.meshgrid(x, y)
    
    # Dipole centered at origin
    r = np.sqrt(X**2 + Y**2) + 1e-6  # Avoid singularity
    theta = np.arctan2(Y, X)
    
    # Dipole field components (simplified)
    B0 = 0.1  # Field strength [T]
    Bx = B0 * (3 * X * Y) / r**4
    By = B0 * (2 * Y**2 - X**2) / r**4
    B_mag = np.sqrt(Bx**2 + By**2)
    
    # Flatten arrays
    field_data = FEMMFieldData("synthetic")
    field_data.x = X.flatten()
    field_data.y = Y.flatten()
    field_data.Bx = Bx.flatten()
    field_data.By = By.flatten()
    field_data.B_mag = B_mag.flatten()
    field_data.has_gradients = False
    
    log(f"Synthetic field created: {len(field_data.x)} points")
    
    return field_data

def main():
    """Main execution function"""
    ensure_output_dir()
    
    log("="*70)
    log("FEM-DEM MAGNETIC FIELD COUPLING")
    log("Lunar Regolith Simulation")
    log("="*70)
    
    # Step 1: Load and process FEM field data
    log("\n" + "="*70)
    log("STEP 1: Loading FEMM magnetic field data")
    log("="*70)
    
    try:
        field_data = FEMMFieldData(cfg.femm_data_file)
        field_data.parse()
    except FileNotFoundError:
        log(f"WARNING: FEMM file '{cfg.femm_data_file}' not found")
        log("Using synthetic field for demonstration")
        field_data = create_synthetic_field()
    
    # Step 2: Detect and crop coil region
    log("\n" + "="*70)
    log("STEP 2: Detecting coil region")
    log("="*70)
    
    field_data.detect_coil_region()
    field_data.crop_to_coil()
    
    # Step 3: Build interpolators
    log("\n" + "="*70)
    log("STEP 3: Building field interpolators")
    log("="*70)
    
    interpolator = MagneticFieldInterpolator(field_data)
    interpolator.build_interpolators()
    
    # Step 4: Visualize field
    log("\n" + "="*70)
    log("STEP 4: Visualizing magnetic field")
    log("="*70)
    
    visualizer = FieldVisualizer(field_data)
    visualizer.plot_field_overview(
        save_path=os.path.join(cfg.output_dir, "magnetic_field.png")
    )
    
    # Step 5: Create particles
    log("\n" + "="*70)
    log("STEP 5: Creating DEM particles")
    log("="*70)
    
    particles = create_particles()
    
    # Step 6: Initialize magnetic force calculator
    log("\n" + "="*70)
    log("STEP 6: Initializing magnetic force calculator")
    log("="*70)
    
    mag_calc = MagneticForceCalculator(interpolator)
    
    # Test magnetic force on one particle
    test_pos = np.array([0.02, 0.02, 0.03])
    test_volume = (4.0/3.0) * np.pi * (70e-6)**3
    test_chi = 5e-5
    F_test = mag_calc.compute_paramagnetic_force(test_pos, test_volume, test_chi)
    log(f"Test magnetic force at {test_pos}: F = {F_test} N")
    log(f"                                     |F| = {np.linalg.norm(F_test)*1e9:.3f} nN")
    
    # Step 7: Run DEM simulation
    log("\n" + "="*70)
    log("STEP 7: Running DEM simulation")
    log("="*70)
    log(f"Duration: {cfg.sim_duration} s")
    log(f"Timestep: {cfg.dt} s")
    log(f"Lunar gravity: {cfg.g_lunar} m/s²")
    log(f"Domain size: {cfg.dem_box_size} m")
    
    simulator = SimpleDEMSimulator(particles, mag_calc)
    simulator.run(cfg.sim_duration, cfg.dt, cfg.output_interval)
    
    # Step 8: Visualize results
    log("\n" + "="*70)
    log("STEP 8: Visualizing simulation results")
    log("="*70)
    
    simulator.plot_trajectories(
        save_path=os.path.join(cfg.output_dir, "particle_trajectories.png")
    )
    
    # Step 9: Summary statistics
    log("\n" + "="*70)
    log("STEP 9: Summary Statistics")
    log("="*70)
    
    for p in particles:
        traj = simulator.trajectories[p.id]
        pos_final = np.array(traj['pos'][-1])
        vel_final = np.array(traj['vel'][-1])
        force_avg = np.mean(np.array(traj['force']), axis=0)
        
        log(f"\nParticle {p.id} ({p.material_type}):")
        log(f"  Final position: {pos_final}")
        log(f"  Final velocity: {vel_final} m/s")
        log(f"  Average force: {force_avg*1e9} nN")
        log(f"  Total displacement: {np.linalg.norm(pos_final - traj['pos'][0])*1000:.3f} mm")
    
    log("\n" + "="*70)
    log("SIMULATION COMPLETE")
    log("="*70)
    log(f"Output files saved to: {cfg.output_dir}/")

if __name__ == "__main__":
    main()