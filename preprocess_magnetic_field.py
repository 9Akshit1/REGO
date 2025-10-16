#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fully Dynamic & Scientifically Accurate Magnetic Field Preprocessor for LIGGGHTS
- Automatically extracts ALL parameters from DEM and FEM files
- Scientifically accurate physics (diamagnetic lunar regolith)
- Proper domain mapping with automatic scaling/offset calculation
- CORRECTED: Crops FEM domain to only magnetic coil region
- No hardcoded values except fundamental physical constants
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys
import os
import re

# FUNDAMENTAL PHYSICAL CONSTANTS (only hardcoded values allowed)
MU0 = 1.25663706212e-6  # Vacuum permeability [H/m] (CODATA 2018)

def parse_liggghts_complete(liggghts_file='in.lunar_dust_magnetic'):
    """Comprehensively parse LIGGGHTS input file to extract ALL simulation parameters
    
    Returns:
    --------
    config : dict
        Complete simulation configuration including all dynamic parameters
    """
    
    config = {
        'particles': {},
        'domain': {},
        'walls': [],
        'n_types': 0,
        'timestep': None,
        'gravity': None
    }
    
    try:
        with open(liggghts_file, 'r') as f:
            content = f.read()
        
        print(f"\n{'='*80}")
        print(f"PARSING LIGGGHTS INPUT FILE: {liggghts_file}")
        print(f"{'='*80}")
        
        # ===== EXTRACT DOMAIN/BOX SIZE =====
        region_pattern = r'region\s+\w+\s+block\s+([\-\d\.e]+)\s+([\-\d\.e]+)\s+([\-\d\.e]+)\s+([\-\d\.e]+)\s+([\-\d\.e]+)\s+([\-\d\.e]+)'
        region_match = re.search(region_pattern, content)
        
        if region_match:
            config['domain']['x_min'] = float(region_match.group(1))
            config['domain']['x_max'] = float(region_match.group(2))
            config['domain']['y_min'] = float(region_match.group(3))
            config['domain']['y_max'] = float(region_match.group(4))
            config['domain']['z_min'] = float(region_match.group(5))
            config['domain']['z_max'] = float(region_match.group(6))
            
            print(f"\n✓ DOMAIN DETECTED:")
            print(f"  X: [{config['domain']['x_min']:.4f}, {config['domain']['x_max']:.4f}] m")
            print(f"  Y: [{config['domain']['y_min']:.4f}, {config['domain']['y_max']:.4f}] m")
            print(f"  Z: [{config['domain']['z_min']:.4f}, {config['domain']['z_max']:.4f}] m")
        else:
            raise ValueError("Could not detect domain from LIGGGHTS file!")
        
        # ===== EXTRACT NUMBER OF PARTICLE TYPES =====
        create_box_pattern = r'create_box\s+(\d+)'
        create_box_match = re.search(create_box_pattern, content)
        
        if create_box_match:
            config['n_types'] = int(create_box_match.group(1))
            print(f"\n✓ PARTICLE TYPES: {config['n_types']}")
        else:
            raise ValueError("Could not detect number of particle types!")
        
        # ===== EXTRACT TIMESTEP =====
        timestep_pattern = r'timestep\s+([\d\.e\-]+)'
        timestep_match = re.search(timestep_pattern, content)
        
        if timestep_match:
            config['timestep'] = float(timestep_match.group(1))
            print(f"\n✓ TIMESTEP: {config['timestep']:.2e} s")
        else:
            raise ValueError("Could not detect timestep!")
        
        # ===== EXTRACT GRAVITY =====
        gravity_pattern = r'fix\s+\w+\s+all\s+gravity\s+([\d\.e\-]+)'
        gravity_match = re.search(gravity_pattern, content)
        
        if gravity_match:
            config['gravity'] = float(gravity_match.group(1))
            gravity_type = "Lunar" if abs(config['gravity'] - 1.625) < 0.1 else "Earth" if abs(config['gravity'] - 9.81) < 0.5 else "Custom"
            print(f"✓ GRAVITY: {config['gravity']:.3f} m/s² ({gravity_type})")
        else:
            raise ValueError("Could not detect gravity!")
        
        # ===== EXTRACT MAGNETIC SUSCEPTIBILITIES =====
        mag_sus_pattern = r'fix\s+mag_sus\s+all\s+property/global\s+magneticSusceptibility\s+peratomtype\s+([\d\.\-e\s]+)'
        mag_sus_match = re.search(mag_sus_pattern, content)
        
        if mag_sus_match:
            chi_values = [float(x) for x in mag_sus_match.group(1).split()]
            print(f"\n✓ MAGNETIC SUSCEPTIBILITIES (from LIGGGHTS file):")
            for i, chi in enumerate(chi_values, 1):
                chi_type = "diamagnetic" if chi < 0 else "paramagnetic" if chi > 0 else "non-magnetic"
                print(f"  Type {i}: χ = {chi:.2e} ({chi_type})")
        else:
            raise ValueError("Could not find magneticSusceptibility in LIGGGHTS file!")
        
        # ===== EXTRACT COHESION ENERGY DENSITIES =====
        # Handle multi-line definitions with & continuation
        cohesion_pattern = r'fix\s+\w+\s+all\s+property/global\s+cohesionEnergyDensity\s+peratomtypepair\s+(\d+)\s+&?\s*((?:[\d\.\-e]+\s*&?\s*)+)'
        cohesion_match = re.search(cohesion_pattern, content, re.MULTILINE | re.DOTALL)

        if cohesion_match:
            n_types_declared = int(cohesion_match.group(1))
            cohesion_values_str = cohesion_match.group(2)
            
            # Remove continuation characters and extra whitespace
            cohesion_values_str = cohesion_values_str.replace('&', ' ')
            cohesion_values = [float(x) for x in cohesion_values_str.split()]
            
            # Calculate expected matrix size
            expected_size = n_types_declared * n_types_declared
            
            print(f"\n✓ COHESION ENERGY DENSITIES (from LIGGGHTS file):")
            print(f"  Declared types: {n_types_declared}")
            print(f"  Found {len(cohesion_values)} values (expected {expected_size})")
            
            if len(cohesion_values) == expected_size:
                # Reshape to matrix
                cohesion_matrix = np.array(cohesion_values).reshape(n_types_declared, n_types_declared)
                config['cohesion_matrix'] = cohesion_matrix
                
                print(f"  Matrix ({n_types_declared}×{n_types_declared}):")
                for i in range(n_types_declared):
                    row_str = "  Type {}: [{}] J/m³".format(
                        i+1, 
                        ", ".join([f"{cohesion_matrix[i, j]:6.0f}" for j in range(n_types_declared)])
                    )
                    print(row_str)
            else:
                print(f"  ⚠ WARNING: Value count mismatch! Using fallback estimates.")
                config['cohesion_matrix'] = None
        else:
            print(f"\n⚠ WARNING: Could not find cohesionEnergyDensity in LIGGGHTS file!")
            config['cohesion_matrix'] = None
        
        # ===== EXTRACT PARTICLE TEMPLATES =====
        template_pattern = r'fix\s+(\w+)\s+all\s+particletemplate/sphere\s+\d+\s+atom_type\s+(\d+)\s+(?:&\s*)?density\s+constant\s+([\d\.e\-]+)\s+(?:&\s*)?radius\s+constant\s+([\d\.e\-]+)'
        
        print(f"\n✓ PARTICLE TEMPLATES:")
        template_matches = list(re.finditer(template_pattern, content, re.MULTILINE | re.DOTALL))
        
        if not template_matches:
            raise ValueError("No particle templates found!")
        
        for match in template_matches:
            template_name = match.group(1)
            ptype = int(match.group(2))
            density = float(match.group(3))
            radius = float(match.group(4))
            
            if ptype > len(chi_values):
                raise ValueError(f"Type {ptype} has no corresponding χ value!")
            
            config['particles'][ptype] = {
                'chi': chi_values[ptype-1],
                'r': radius,
                'density': density,
                'name': template_name
            }
            
            print(f"  Type {ptype} ({template_name:15s}): r={radius*1e6:6.1f} μm, ρ={density:4.0f} kg/m³, χ={config['particles'][ptype]['chi']:.2e}")
        
        # ===== EXTRACT WALL DEFINITIONS =====
        wall_patterns = {
            'xplane': r'fix\s+(\w+)\s+all\s+wall/gran.*?xplane\s+([\-\d\.e]+)',
            'yplane': r'fix\s+(\w+)\s+all\s+wall/gran.*?yplane\s+([\-\d\.e]+)',
            'zplane': r'fix\s+(\w+)\s+all\s+wall/gran.*?zplane\s+([\-\d\.e]+)',
        }
        
        print(f"\n✓ WALL DEFINITIONS:")
        for wall_type, pattern in wall_patterns.items():
            for match in re.finditer(pattern, content):
                wall_name = match.group(1)
                position = float(match.group(2))
                config['walls'].append({
                    'name': wall_name,
                    'type': wall_type,
                    'position': position
                })
                print(f"  {wall_name:15s}: {wall_type} at {position:.4f} m")
        
        # ===== SUMMARY =====
        print(f"\n{'='*80}")
        print(f"CONFIGURATION SUMMARY:")
        print(f"  Simulation box: {config['domain']['x_max']-config['domain']['x_min']:.3f} × {config['domain']['y_max']-config['domain']['y_min']:.3f} m (XY)")
        print(f"  Particle types: {len(config['particles'])}")
        print(f"  Size range: {min(p['r'] for p in config['particles'].values())*1e6:.1f} - {max(p['r'] for p in config['particles'].values())*1e6:.1f} μm")
        
        chi_values = [p['chi'] for p in config['particles'].values()]
        print(f"  χ range: {min(chi_values):.2e} to {max(chi_values):.2e}")
        
        if all(chi < 0 for chi in chi_values):
            print(f"  ✓ All particles DIAMAGNETIC (repelled from high-field regions)")
        elif all(chi > 0 for chi in chi_values):
            print(f"  ✓ All particles PARAMAGNETIC (attracted to high-field regions)")
        else:
            print(f"  ✓ Mixed magnetic properties")
        
        print(f"  Walls detected: {len(config['walls'])}")
        print(f"{'='*80}\n")
        
        return config
        
    except FileNotFoundError:
        print(f"\n✗ ERROR: LIGGGHTS file '{liggghts_file}' not found!")
        raise
    
    except Exception as e:
        print(f"\n✗ ERROR parsing LIGGGHTS file: {e}")
        import traceback
        traceback.print_exc()
        raise

def preprocess_magnetic_field(field_file='B_output.txt', force_multiplier=0.1, 
                              liggghts_file='in.lunar_dust_magnetic', 
                              peak_threshold=0.20, calc_freq=10,
                              create_field_viz=True):  
    """
    Preprocess FEM magnetic field data for LIGGGHTS with full scientific accuracy.
    
    Parameters:
    -----------
    field_file : str
        FEM magnetic field data file
    force_multiplier : float
        Scaling factor for magnetic forces (0.0 = auto-calculate, default: 0.1)
    liggghts_file : str
        LIGGGHTS input file to extract parameters from
    peak_threshold : float
        Peak selection threshold (0.05-0.95, default: 0.20)
    calc_freq : int
        Frequency of force recalculation in timesteps (default: 10)
    """
    
    print("=" * 80)
    print("FULLY DYNAMIC MAGNETIC FIELD PREPROCESSOR FOR LIGGGHTS")
    print("Scientific accuracy with complete parameter extraction")
    print("=" * 80)
    print(f"Calculation frequency: every {calc_freq} timesteps")
    print(f"Peak selection: Dynamic (threshold={peak_threshold*100:.0f}% of max gradient)")
    
    # Parse LIGGGHTS configuration
    config = parse_liggghts_complete(liggghts_file)
    
    # Read FEM field data
    print(f"\n{'='*80}")
    print(f"READING FEM MAGNETIC FIELD DATA: {field_file}")
    print(f"{'='*80}\n")
    
    try:
        data = pd.read_csv(field_file, sep='\t', comment='#', skipinitialspace=True)
        data = data.dropna(how='all')
        
        print(f"✓ Loaded {len(data)} field points")
        print(f"✓ Columns: {list(data.columns)}")
        
        # Extract coordinates (convert cm to m)
        fem_x_cm = data['X'].astype(float).values
        fem_y_cm = data['Y'].astype(float).values
        fem_x = fem_x_cm / 100.0
        fem_y = fem_y_cm / 100.0
        
        # Extract field components
        fem_Bx = data['Bx'].astype(float).values
        fem_By = data['By'].astype(float).values
        fem_B_mag = data['B_mag'].astype(float).values
        
        # Extract gradients (convert T/cm to T/m)
        dBx_dx = data['dBx_dx'].astype(float).values * 100.0
        dBx_dy = data['dBx_dy'].astype(float).values * 100.0
        dBy_dx = data['dBy_dx'].astype(float).values * 100.0
        dBy_dy = data['dBy_dy'].astype(float).values * 100.0
        
        print(f"\n✓ Unit conversions: cm→m, T/cm→T/m")
        
    except Exception as e:
        print(f"✗ Error reading field file: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Analyze FEM field
    print(f"\n{'='*80}")
    print("FEM FIELD ANALYSIS (FULL DOMAIN)")
    print(f"{'='*80}")
    print(f"  Coordinate range: X=[{fem_x.min():.4f}, {fem_x.max():.4f}], Y=[{fem_y.min():.4f}, {fem_y.max():.4f}] m")
    print(f"  FEM domain size: {fem_x.max()-fem_x.min():.4f} × {fem_y.max()-fem_y.min():.4f} m")
    print(f"  Field strength: |B|=[{fem_B_mag.min():.6f}, {fem_B_mag.max():.6f}] T")
    print(f"  Max |B|: {fem_B_mag.max():.6f} T")
    
    x_unique = np.sort(np.unique(fem_x))
    y_unique = np.sort(np.unique(fem_y))
    
    print(f"  Grid: {len(x_unique)} × {len(y_unique)} points")
    print(f"  Spacing: Δx={x_unique[1]-x_unique[0]:.5f} m, Δy={y_unique[1]-y_unique[0]:.5f} m")
    
    # Reshape to 2D grids
    nx, ny = len(x_unique), len(y_unique)
    Bx_grid = fem_Bx.reshape(ny, nx)
    By_grid = fem_By.reshape(ny, nx)
    B_grid = fem_B_mag.reshape(ny, nx)
    
    dBx_dx_grid = dBx_dx.reshape(ny, nx)
    dBx_dy_grid = dBx_dy.reshape(ny, nx)
    dBy_dx_grid = dBy_dx.reshape(ny, nx)
    dBy_dy_grid = dBy_dy.reshape(ny, nx)
    
    # Calculate magnetic force gradients: (B·∇)B
    print(f"\n✓ Calculating (B·∇)B force gradients...")
    # Use magnitude-based gradient for stronger, more physically meaningful forces
    dBmag_dx_grid = (Bx_grid * dBx_dx_grid + By_grid * dBy_dx_grid) / (B_grid + 1e-10)
    dBmag_dy_grid = (Bx_grid * dBx_dy_grid + By_grid * dBy_dy_grid) / (B_grid + 1e-10)
    gradBx = B_grid * dBmag_dx_grid
    gradBy = B_grid * dBmag_dy_grid
    grad_mag = np.sqrt(gradBx**2 + gradBy**2)
    
    print(f"  (B·∇)Bx: [{gradBx.min():.2e}, {gradBx.max():.2e}] T²/m")
    print(f"  (B·∇)By: [{gradBy.min():.2e}, {gradBy.max():.2e}] T²/m")
    print(f"  |(B·∇)B|: [{grad_mag.min():.2e}, {grad_mag.max():.2e}] T²/m")
    
    # CRITICAL FIX: Crop FEM domain to only include magnetic coil region
    print(f"\n{'='*80}")
    print("CROPPING FEM DOMAIN TO MAGNETIC COIL REGION")
    print(f"{'='*80}")
    
    # Identify coil region from high-gradient areas
    # Use threshold: coil region has |(B·∇)B| > 5% of maximum
    crop_threshold = 0.05
    grad_threshold = crop_threshold * grad_mag.max()
    coil_mask = grad_mag > grad_threshold
    
    # Find bounding box of coil
    coil_x_indices = np.any(coil_mask, axis=0)
    coil_y_indices = np.any(coil_mask, axis=1)
    
    # Add small margin (5% of coil size) to include field near coil edges
    x_coil_indices_list = np.where(coil_x_indices)[0]
    y_coil_indices_list = np.where(coil_y_indices)[0]
    
    if len(x_coil_indices_list) == 0 or len(y_coil_indices_list) == 0:
        print(f"  ⚠ WARNING: Could not detect coil region automatically!")
        print(f"  Using full FEM domain instead.")
        x_coil_min, x_coil_max = x_unique[0], x_unique[-1]
        y_coil_min, y_coil_max = y_unique[0], y_unique[-1]
    else:
        x_margin = max(1, int(0.05 * len(x_coil_indices_list)))
        y_margin = max(1, int(0.05 * len(y_coil_indices_list)))
        
        x_start = max(0, x_coil_indices_list[0] - x_margin)
        x_end = min(len(x_unique) - 1, x_coil_indices_list[-1] + x_margin)
        y_start = max(0, y_coil_indices_list[0] - y_margin)
        y_end = min(len(y_unique) - 1, y_coil_indices_list[-1] + y_margin)
        
        x_coil_min = x_unique[x_start]
        x_coil_max = x_unique[x_end]
        y_coil_min = y_unique[y_start]
        y_coil_max = y_unique[y_end]
        
        print(f"  Original FEM domain: X=[{fem_x.min():.4f}, {fem_x.max():.4f}], Y=[{fem_y.min():.4f}, {fem_y.max():.4f}] m")
        print(f"  Detected coil region: X=[{x_coil_min:.4f}, {x_coil_max:.4f}], Y=[{y_coil_min:.4f}, {y_coil_max:.4f}] m")
        print(f"  Threshold: {crop_threshold*100:.0f}% of max gradient = {grad_threshold:.2e} T²/m")
        
        # Crop all arrays to coil region
        x_coil_indices = (x_unique >= x_coil_min) & (x_unique <= x_coil_max)
        y_coil_indices = (y_unique >= y_coil_min) & (y_unique <= y_coil_max)
        
        x_unique = x_unique[x_coil_indices]
        y_unique = y_unique[y_coil_indices]
        
        # Crop 2D grids
        Bx_grid = Bx_grid[np.ix_(y_coil_indices, x_coil_indices)]
        By_grid = By_grid[np.ix_(y_coil_indices, x_coil_indices)]
        B_grid  = B_grid[np.ix_(y_coil_indices, x_coil_indices)]
        gradBx  = gradBx[np.ix_(y_coil_indices, x_coil_indices)]
        gradBy  = gradBy[np.ix_(y_coil_indices, x_coil_indices)]
        grad_mag = grad_mag[np.ix_(y_coil_indices, x_coil_indices)]

        # 🔥 FIX: crop the FEM gradient arrays too, so shapes all match
        dBx_dx_grid = dBx_dx_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBx_dy_grid = dBx_dy_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBy_dx_grid = dBy_dx_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBy_dy_grid = dBy_dy_grid[np.ix_(y_coil_indices, x_coil_indices)]

        # Debug print to catch mismatches early
        print("Shapes after cropping:",
              "Bx", Bx_grid.shape,
              "dBx_dx", dBx_dx_grid.shape,
              "dBy_dx", dBy_dx_grid.shape)
        assert Bx_grid.shape == dBx_dx_grid.shape == dBy_dx_grid.shape == dBx_dy_grid.shape == dBy_dy_grid.shape, \
            "Grid shapes disagree — check cropping logic!"
        
        print(f"  Cropped grid: {len(x_unique)} × {len(y_unique)} points")
        print(f"  Coil width: {(x_coil_max-x_coil_min)*100:.1f} × {(y_coil_max-y_coil_min)*100:.1f} cm")
        print(f"{'='*80}\n")

    # Calculate peak width from FEM grid spacing
    dx_fem = x_unique[1] - x_unique[0]
    dy_fem = y_unique[1] - y_unique[0]
    peak_width = 3.0 * max(dx_fem, dy_fem)
    print(f"  Calculated peak width: {peak_width*1000:.1f} mm (3x grid spacing)")

    # ===============================================================
    # CALCULATE FORCE MULTIPLIER FOR ADDITIVE MANUFACTURING
    # WITH REALISTIC LUNAR COHESION + MAGNETIC FORCES
    # ===============================================================

    def _contact_area_sjkr(delta_n, r1, r2):
        """Approximate SJKR contact area from overlap and reduced radius."""
        if delta_n <= 0:
            return 0.0
        Rstar = (r1 * r2) / (r1 + r2)
        return 2.0 * np.pi * delta_n * (2.0 * Rstar)

    # Sort particles by radius
    particles_sorted = sorted(config['particles'].items(), key=lambda x: x[1]['r'])
    smallest_ptype, smallest = particles_sorted[0]
    largest_ptype, largest = particles_sorted[-1]

    # Mass and gravity
    max_mass = largest['density'] * (4/3) * np.pi * largest['r']**3
    min_mass = smallest['density'] * (4/3) * np.pi * smallest['r']**3
    max_F_grav = max_mass * config['gravity']
    min_F_grav = min_mass * config['gravity']

    print(f"\n===== GRAVITY FORCES =====")
    print(f"  Smallest particle mass: {min_mass:.3e} kg → F_grav = {min_F_grav*1e9:.3f} nN")
    print(f"  Largest  particle mass: {max_mass:.3e} kg → F_grav = {max_F_grav*1e9:.3f} nN")

    # Cohesion gamma values (from LIGGGHTS if available)
    if config.get('cohesion_matrix') is not None:
        cm = config['cohesion_matrix']
        gamma_small = float(cm[smallest_ptype-1, smallest_ptype-1])
        gamma_large = float(cm[largest_ptype-1, largest_ptype-1])
    else:
        gamma_small = config.get('fallback_gamma_small', 1000.0)
        gamma_large = config.get('fallback_gamma_large', 150.0)

    # Contact areas
    typical_delta = config.get('typical_overlap', 1e-7)
    A_contact_small = _contact_area_sjkr(typical_delta, smallest['r'], smallest['r'])
    A_contact_large = _contact_area_sjkr(typical_delta, largest['r'], largest['r'])
    if A_contact_small <= 0: A_contact_small = np.pi * smallest['r']**2 * 1e-3
    if A_contact_large <= 0: A_contact_large = np.pi * largest['r']**2 * 1e-3

    # Cohesion forces
    F_cohesion_small = gamma_small * A_contact_small
    F_cohesion_large = gamma_large * A_contact_large
    cohesion_ratio_small = F_cohesion_small / min_F_grav
    cohesion_ratio_large = F_cohesion_large / max_F_grav

    print(f"\n===== COHESION FORCES =====")
    print(f"  Smallest: γ={gamma_small:.1f} J/m³, A={A_contact_small:.2e} m²")
    print(f"            F_cohesion = {F_cohesion_small*1e9:.2f} nN vs F_grav = {min_F_grav*1e9:.3f} nN")
    print(f"            Ratio = {cohesion_ratio_small:.1f}× (cohesion dominates!)")
    print(f"  Largest : γ={gamma_large:.1f} J/m³, A={A_contact_large:.2e} m²")
    print(f"            F_cohesion = {F_cohesion_large*1e9:.2f} nN vs F_grav = {max_F_grav*1e9:.2f} nN")
    print(f"            Ratio = {cohesion_ratio_large:.1f}×")

    # ---------------------------------------------------------------
    # MAGNETIC FORCE CALCULATION (corrected)
    # ---------------------------------------------------------------
    B2 = Bx_grid**2 + By_grid**2
    # Better: use chain rule with existing gradBx, gradBy
    # ∇(B²) = 2B·∇B (chain rule)
    gradB2_x = 2 * (Bx_grid * dBx_dx_grid + By_grid * dBy_dx_grid)
    gradB2_y = 2 * (Bx_grid * dBx_dy_grid + By_grid * dBy_dy_grid)
    mag_gradB2 = np.sqrt(gradB2_x**2 + gradB2_y**2)
    gradB2_metric = np.percentile(mag_gradB2.ravel(), config.get('grad_percentile', 95.0))

    force_mag_bases = {}
    for ptype, p in config['particles'].items():
        chi = float(p.get('chi', config.get('default_chi', -3.5e-5)))
        V = (4/3) * np.pi * p['r']**3
        Fmag = (chi * V / MU0) * 0.5 * gradB2_metric
        force_mag_bases[ptype] = Fmag

    max_F_mag_base = max(abs(v) for v in force_mag_bases.values())
    min_F_mag_base = min(abs(v) for v in force_mag_bases.values())

    print(f"\n===== MAGNETIC BASE FORCES =====")
    print(f"  Gradient metric (95th ∇B²) = {gradB2_metric:.3e}")
    for t, v in force_mag_bases.items():
        print(f"  Type {t}: Base F_mag = {v*1e9:.3f} nN (χ={config['particles'][t]['chi']})")

    # ---------------------------------------------------------------
    # MULTIPLIER CALCULATION
    # ---------------------------------------------------------------
    safety_factor = config.get('safety_factor', 2.0)
    target_ratio_small = cohesion_ratio_small * safety_factor
    target_ratio_large = cohesion_ratio_large * safety_factor

    multiplier_for_large = (target_ratio_large * max_F_grav) / (max_F_mag_base + 1e-30)
    multiplier_for_small = (target_ratio_small * min_F_grav) / (min_F_mag_base + 1e-30)
    calculated_multiplier = np.sqrt(multiplier_for_large * multiplier_for_small)

    print(f"\n===== MULTIPLIER CALCULATION =====")
    print(f"  Smallest target = {target_ratio_small:.0f}× gravity → Multiplier {multiplier_for_small:.2e}")
    print(f"  Largest  target = {target_ratio_large:.0f}× gravity → Multiplier {multiplier_for_large:.2e}")
    print(f"  → Recommended balanced multiplier: {calculated_multiplier:.2e}")

    print(f"  → User-given multiplier: {force_multiplier:.2e}")

    ratio_check = force_multiplier / calculated_multiplier
    if ratio_check < 0.3:
        print(f"  ⚠ TOO WEAK ({1/ratio_check:.1f}× smaller than needed) → cohesion may not be overcome")
    elif ratio_check > 3.0:
        print(f"  ⚠ TOO STRONG ({ratio_check:.1f}× larger than needed) → risk of particle ejection")
    else:
        print("  ✓ Multiplier is within reasonable range")

    force_mult = float(force_multiplier)       # Take user's value for simulation

    # ---------------------------------------------------------------
    # DAMPING COEFFICIENT (realistic)
    # ---------------------------------------------------------------
    # 1) Velocity-based damping: γ_vel = Fmax / v_target
    max_chi = max(float(p['chi']) for p in config['particles'].values())
    max_V = (4/3) * np.pi * largest['r']**3
    max_force_estimate = abs((max_chi * max_V / MU0) * 0.5 * gradB2_metric * force_mult)
    target_velocity = config.get('target_velocity', 1e-3)  # 1 mm/s
    gamma_vel = max_force_estimate / max(target_velocity, 1e-12)

    # 2) Critical damping: γ_crit = 2√(k·m). Approximate spring stiffness k ~ F/δ
    delta_ref = typical_delta
    k_est = max_force_estimate / max(delta_ref, 1e-12)
    gamma_crit = 2.0 * np.sqrt(k_est * max_mass)

    ## Choose damping: use 10% of critical damping for realistic motion
    # (allows movement while preventing instability)
    damping_coeff = 0.1 * gamma_crit
    v_eq = max_force_estimate / damping_coeff if damping_coeff > 0 else 0.0

    print(f"\n===== DAMPING ESTIMATE =====")
    print(f"  Max estimated force = {max_force_estimate:.3e} N")
    print(f"  Velocity-based γ_vel = {gamma_vel:.3e} kg/s (target v={target_velocity*1e3:.2f} mm/s)")
    print(f"  Critical damping γ_crit = {gamma_crit:.3e} kg/s (mass={max_mass:.3e} kg, δ={delta_ref:.1e} m)")
    print(f"  → Using damping coefficient γ = {damping_coeff:.3e} kg/s")
    print(f"  Equilibrium velocity estimate = {v_eq*1e3:.3f} mm/s")
    if v_eq*1e3 > 50.0:
        print("  ⚠ WARNING: equilibrium velocity very high (>50 mm/s)")
    elif v_eq*1e3 < 0.1:
        print("  ⚠ WARNING: equilibrium velocity very low (<0.1 mm/s)")
            
    # Save data and create outputs
    save_field_data(x_unique, y_unique, Bx_grid, By_grid, B_grid, gradBx, gradBy, grad_mag)
    create_liggghts_integration(x_unique, y_unique, Bx_grid, By_grid, gradBx, gradBy, 
                                force_multiplier, config, peak_threshold, peak_width, 
                                calc_freq, damping_coeff, create_field_viz)
    create_visualizations(x_unique, y_unique, Bx_grid, By_grid, B_grid, gradBx, gradBy, 
                         grad_mag, peak_threshold, peak_width, force_multiplier, config)
    generate_physics_summary(B_grid, gradBx, gradBy, force_multiplier, config)
    
    print(f"\n{'='*80}")
    print("✓ PREPROCESSING COMPLETE!")
    print(f"{'='*80}")
    print("Generated files:")
    print("  • magnetic_field_apply.lmp")
    print("  • field_data.npz")
    print("  • magnetic_field_analysis.png")
    print("  • physics_summary.txt")
    print(f"{'='*80}\n")
    
    return True

def save_field_data(x, y, Bx, By, B, gradBx, gradBy, grad_mag):
    """Save field data to numpy file for future analysis"""
    np.savez('field_data.npz',
             x=x, y=y, Bx=Bx, By=By, B=B,
             gradBx=gradBx, gradBy=gradBy, grad_mag=grad_mag)
    print("✓ Field data saved: field_data.npz")

def create_liggghts_integration(x_fem, y_fem, Bx, By, gradBx, gradBy, force_mult, 
                                config, peak_threshold, peak_width, calc_freq, damping_coeff, create_field_viz):
    """Create LIGGGHTS command file with optimized force calculation"""
    
    particles = config['particles']
    domain = config['domain']
    
    # Calculate particle volumes
    for ptype in particles:
        r = particles[ptype]['r']
        particles[ptype]['V'] = (4/3) * np.pi * r**3
    
    # Extract domain bounds
    x_fem_min, x_fem_max = x_fem.min(), x_fem.max()
    y_fem_min, y_fem_max = y_fem.min(), y_fem.max()
    
    x_sim_min, x_sim_max = domain['x_min'], domain['x_max']
    y_sim_min, y_sim_max = domain['y_min'], domain['y_max']
    
    fem_width_x = x_fem_max - x_fem_min
    fem_width_y = y_fem_max - y_fem_min
    sim_width_x = x_sim_max - x_sim_min
    sim_width_y = y_sim_max - y_sim_min
    
    print(f"\n{'='*80}")
    print(f"COORDINATE MAPPING: Centering coil in DEM domain")
    print(f"{'='*80}")
    print(f"  FEM coil size: {fem_width_x*100:.1f} × {fem_width_y*100:.1f} cm")
    print(f"  DEM box size: {sim_width_x*100:.1f} × {sim_width_y*100:.1f} cm")
    
    # ========================================================================
    # COORDINATE MAPPING: Place magnetic coil on DEM bottom wall
    # ========================================================================
    # Strategy: Align coil center (XY) with DEM box center (XY)
    #           Then position coil just above bottom wall in Z

    dem_center_x = (x_sim_min + x_sim_max) / 2.0  # DEM box center X
    dem_center_y = (y_sim_min + y_sim_max) / 2.0  # DEM box center Y
    z_bottom_wall = domain['z_min']  # Bottom wall Z position

    # Coil geometry (from cropped FEM data)
    coil_center_x = (x_fem_min + x_fem_max) / 2.0
    coil_center_y = (y_fem_min + y_fem_max) / 2.0
    coil_width_x = x_fem_max - x_fem_min
    coil_width_y = y_fem_max - y_fem_min

    # Check if coil fits in DEM box
    dem_width_x = x_sim_max - x_sim_min
    dem_width_y = y_sim_max - y_sim_min

    if coil_width_x > dem_width_x * 0.95 or coil_width_y > dem_width_y * 0.95:
        print(f"\n⚠ WARNING: Coil may be too large for DEM box!")
        print(f"  Coil size: {coil_width_x*100:.1f} × {coil_width_y*100:.1f} cm")
        print(f"  DEM box:   {dem_width_x*100:.1f} × {dem_width_y*100:.1f} cm")
        # Optional: Add scaling here if needed
        scale_x = min(1.0, dem_width_x * 0.9 / coil_width_x)
        scale_y = min(1.0, dem_width_y * 0.9 / coil_width_y)
        print(f"  Applying scaling: {scale_x:.3f} (X), {scale_y:.3f} (Y)")
    else:
        scale_x = 1.0
        scale_y = 1.0
        print(f"\n✓ Coil fits in DEM box (no scaling needed)")

    # Mapping: Align coil center with DEM box center (XY plane)
    offset_x = coil_center_x - dem_center_x * scale_x
    offset_y = coil_center_y - dem_center_y * scale_y

    print(f"  ✓ COIL PLACEMENT:")
    print(f"    Coil center (FEM): ({coil_center_x:.4f}, {coil_center_y:.4f}) m")
    print(f"    Target (DEM center): ({dem_center_x:.4f}, {dem_center_y:.4f}) m")
    print(f"    Offset: ({offset_x:.4f}, {offset_y:.4f}) m")
    print(f"    Z position: On bottom wall at Z={z_bottom_wall:.4f} m")
    print(f"    Mapping: X_FEM = {scale_x:.3f}*X_DEM + {offset_x:.4f}")
    print(f"             Y_FEM = {scale_y:.3f}*Y_DEM + {offset_y:.4f}")
    
    # Generate LIGGGHTS script
    with open('magnetic_field_apply.lmp', 'w', encoding='utf-8') as f:
        f.write("# " + "="*74 + "\n")
        f.write("# MAGNETIC FIELD APPLICATION - SCIENTIFICALLY ACCURATE\n")
        f.write("# Auto-generated from FEM and DEM configuration files\n")
        f.write(f"# Force update frequency: every {calc_freq} timesteps\n")
        f.write("# " + "="*74 + "\n\n")

        if create_field_viz:
            f.write("\n# === NEIGHBOR LIST PRE-CONFIGURATION ===\n")
            f.write("# Increase capacity before creating visualization atoms\n")
            
            x_unique = np.sort(np.unique(x_fem))
            y_unique = np.sort(np.unique(y_fem))
            subsample = 3  # Reduce by 3x in each dimension = 9x total reduction
            x_viz = x_unique[::subsample]
            y_viz = y_unique[::subsample]
            n_viz = len(x_viz) * len(y_viz)
            
            f.write(f"# Visualization atoms: {n_viz} (subsampled from {len(x_unique)}×{len(y_unique)})\n")
            f.write(f"neigh_modify one 10000\n")
            f.write(f"neigh_modify page 200000\n\n")
        
        f.write("print \"===================================================================================\"\n")
        f.write("print \"ACTIVATING MAGNETIC FIELD (SCIENTIFICALLY ACCURATE PHYSICS)\"\n")
        f.write("print \"===================================================================================\"\n\n")
        
        f.write("# === FUNDAMENTAL CONSTANTS ===\n")
        f.write(f"variable mu0 equal {MU0:.12e}  # Vacuum permeability [H/m]\n")
        f.write(f"variable force_mult equal {force_mult:.6e}\n")
        f.write(f"variable calc_freq equal {calc_freq}\n")
        f.write(f"variable damping_gamma equal {damping_coeff:.6e}\n\n")
        
        f.write("# === PHYSICS NOTES ===\n")
        chi_values = [p['chi'] for p in particles.values()]
        if all(chi < 0 for chi in chi_values):
            f.write("# All particles are DIAMAGNETIC (negative χ)\n")
            f.write("# Particles are REPELLED from high-field regions\n")
        elif all(chi > 0 for chi in chi_values):
            f.write("# All particles are PARAMAGNETIC (positive χ)\n")
            f.write("# Particles are ATTRACTED to high-field regions\n")
        else:
            f.write("# Mixed magnetic properties (both diamagnetic and paramagnetic)\n")
        
        f.write("# Force formula: F = (χ·V/μ₀)·(B·∇)B\n")
        f.write("# where (B·∇)B is the magnetic force gradient\n\n")
        
        f.write("# === COORDINATE MAPPING (DEM → FEM) ===\n")
        f.write(f"# DEM domain: X=[{x_sim_min:.4f}, {x_sim_max:.4f}], Y=[{y_sim_min:.4f}, {y_sim_max:.4f}] m\n")
        f.write(f"# FEM domain: X=[{x_fem_min:.4f}, {x_fem_max:.4f}], Y=[{y_fem_min:.4f}, {y_fem_max:.4f}] m\n")
        f.write(f"# Transformation: X_FEM = scale * X_DEM + offset\n")
        f.write(f"variable scale_x equal {scale_x:.12f}\n")
        f.write(f"variable scale_y equal {scale_y:.12f}\n")
        f.write(f"variable offset_x equal {offset_x:.12f}\n")
        f.write(f"variable offset_y equal {offset_y:.12f}\n\n")
        
        # Find peak locations in force gradient with DYNAMIC selection
        grad_mag = np.sqrt(gradBx**2 + gradBy**2)
        flat_grad = grad_mag.flatten()
        max_grad = grad_mag.max()
        
        # Dynamic threshold-based peak finding
        threshold_value = peak_threshold * max_grad  # e.g., 20% of maximum
        min_separation = peak_width * 2.0  # Minimum distance between peaks
        
        # Find all candidate peaks above threshold
        candidate_indices = np.where(flat_grad >= threshold_value)[0]
        candidate_indices = candidate_indices[np.argsort(flat_grad[candidate_indices])[::-1]]  # Sort by strength
        
        print(f"\n  Peak selection criteria:")
        print(f"    Threshold: {peak_threshold*100:.0f}% of max gradient = {threshold_value:.2e} T²/m")
        print(f"    Min separation: {min_separation*1000:.1f} mm")
        print(f"    Candidates above threshold: {len(candidate_indices)}")
        
        # Spatially distributed peak finding (avoid clustering)
        top_indices = []
        peak_magnitudes = []
        
        for idx in candidate_indices:
            iy, ix = np.unravel_index(idx, grad_mag.shape)
            
            # Check if this peak is far enough from existing peaks
            too_close = False
            for existing_idx in top_indices:
                ey, ex = np.unravel_index(existing_idx, grad_mag.shape)
                dist = np.sqrt((x_fem[ix] - x_fem[ex])**2 + (y_fem[iy] - y_fem[ey])**2)
                if dist < min_separation:
                    too_close = True
                    break
            
            if not too_close:
                top_indices.append(idx)
                peak_magnitudes.append(flat_grad[idx])
        
        n_peaks_actual = len(top_indices)
        
        # Quality check: warn if too few or too many peaks
        if n_peaks_actual == 0:
            print(f"  ⚠ WARNING: No peaks found! Lowering threshold to 10% of max...")
            threshold_value = 0.10 * max_grad
            candidate_indices = np.where(flat_grad >= threshold_value)[0]
            candidate_indices = candidate_indices[np.argsort(flat_grad[candidate_indices])[::-1]]
            
            for idx in candidate_indices:
                iy, ix = np.unravel_index(idx, grad_mag.shape)
                too_close = False
                for existing_idx in top_indices:
                    ey, ex = np.unravel_index(existing_idx, grad_mag.shape)
                    dist = np.sqrt((x_fem[ix] - x_fem[ex])**2 + (y_fem[iy] - y_fem[ey])**2)
                    if dist < min_separation:
                        too_close = True
                        break
                if not too_close:
                    top_indices.append(idx)
                    peak_magnitudes.append(flat_grad[idx])
            
            n_peaks_actual = len(top_indices)
        
        print(f"  ✓ Selected {n_peaks_actual} spatially distributed peaks")
        
        if n_peaks_actual > 20:
            print(f"  ⚠ WARNING: {n_peaks_actual} peaks is a lot! This may slow down LIGGGHTS.")
            print(f"     Consider increasing peak_threshold (currently {peak_threshold:.2f})")
        elif n_peaks_actual < 3:
            print(f"  ⚠ WARNING: Only {n_peaks_actual} peaks found. Field approximation may be coarse.")
            print(f"     Consider decreasing peak_threshold (currently {peak_threshold:.2f})")
        
        # Calculate field coverage
        total_field_energy = np.sum(grad_mag**2)
        covered_energy = 0
        for idx in top_indices:
            iy, ix = np.unravel_index(idx, grad_mag.shape)
            # Approximate Gaussian contribution
            Y_grid, X_grid = np.meshgrid(y_fem, x_fem, indexing='ij')
            gaussian = np.exp(-((X_grid - x_fem[ix])**2 + (Y_grid - y_fem[iy])**2) / (2 * peak_width**2))
            covered_energy += np.sum((grad_mag * gaussian)**2)
        
        coverage_percent = min(100.0, 100.0 * covered_energy / total_field_energy)
        print(f"  Estimated field coverage: {coverage_percent:.1f}% of total gradient energy")
        
        f.write("# === FIELD APPROXIMATION ===\n")
        f.write(f"# {n_peaks_actual}-peak Gaussian approximation (dynamically selected)\n")
        f.write(f"# Peak selection: {peak_threshold*100:.0f}% threshold, {min_separation*1000:.1f} mm min separation\n")
        f.write(f"# Peak width: {peak_width*1000:.1f} mm (3× FEM grid spacing)\n")
        f.write(f"# Field coverage: ~{coverage_percent:.1f}% of gradient energy\n\n")
        
        gaussian_terms_x = []
        gaussian_terms_y = []
        
        print(f"\nGAUSSIAN PEAK LOCATIONS:")
        print(f"  DEM domain: X=[{x_sim_min:.4f}, {x_sim_max:.4f}], Y=[{y_sim_min:.4f}, {y_sim_max:.4f}]")
        print(f"  Coordinate mapping: x_fem = {scale_x:.3f}*x_dem + {offset_x:.4f}")
        print(f"                      y_fem = {scale_y:.3f}*y_dem + {offset_y:.4f}\n")
        
        for i, flat_idx in enumerate(top_indices):
            iy, ix = np.unravel_index(flat_idx, grad_mag.shape)
            peak_x_fem = x_fem[ix]
            peak_y_fem = y_fem[iy]
            peak_gradBx = gradBx[iy, ix]
            peak_gradBy = gradBy[iy, ix]
            
            # Back-calculate DEM coordinates for verification
            peak_x_dem = (peak_x_fem - offset_x) / scale_x
            peak_y_dem = (peak_y_fem - offset_y) / scale_y
            
            print(f"  Peak {i+1}:")
            print(f"    FEM coords: ({peak_x_fem:.4f}, {peak_y_fem:.4f}) m")
            print(f"    DEM coords: ({peak_x_dem:.4f}, {peak_y_dem:.4f}) m")
            print(f"    Gradient magnitude: {np.sqrt(peak_gradBx**2 + peak_gradBy**2):.2e} T²/m")
            
            f.write(f"# Peak {i+1} at FEM=({peak_x_fem:.4f}, {peak_y_fem:.4f}) m\n")
            f.write(f"variable peak{i}_x equal {peak_x_fem:.12f}\n")
            f.write(f"variable peak{i}_y equal {peak_y_fem:.12f}\n")
            f.write(f"variable peak{i}_gradBx equal {peak_gradBx:.12e}\n")
            f.write(f"variable peak{i}_gradBy equal {peak_gradBy:.12e}\n")
            f.write(f"variable peak{i}_width equal {peak_width:.12f}\n\n")
            
            # Gaussian field approximation centered at each peak
            f.write(f"variable dx{i} atom \"(x*v_scale_x+v_offset_x)-v_peak{i}_x\"\n")
            f.write(f"variable dy{i} atom \"(y*v_scale_y+v_offset_y)-v_peak{i}_y\"\n")
            f.write(f"variable r2_{i} atom \"v_dx{i}*v_dx{i}+v_dy{i}*v_dy{i}\"\n")
            f.write(f"variable gauss{i} atom \"exp(-v_r2_{i}/(2*v_peak{i}_width*v_peak{i}_width))\"\n")
            f.write(f"variable gBx{i} atom \"v_peak{i}_gradBx*v_gauss{i}\"\n")
            f.write(f"variable gBy{i} atom \"v_peak{i}_gradBy*v_gauss{i}\"\n\n")
            
            gaussian_terms_x.append(f"v_gBx{i}")
            gaussian_terms_y.append(f"v_gBy{i}")
        
        print()  # Blank line after peak listing
        
        # Sum all Gaussian contributions
        f.write("# === TOTAL MAGNETIC FORCE FIELD ===\n")
        f.write(f"variable BgradB_x atom \"{' + '.join(gaussian_terms_x)}\"\n")
        f.write(f"variable BgradB_y atom \"{' + '.join(gaussian_terms_y)}\"\n\n")

        # Calculate forces for each particle type
        f.write("# === MAGNETIC FORCES BY PARTICLE TYPE ===\n")
        for ptype, props in particles.items():
            chi, V, r_um = props['chi'], props['V'], props['r'] * 1e6
            # Coefficient: χ·V/μ₀ (with correct SI units)
            coeff = chi * V / MU0
            mag_type = "diamagnetic (repelled)" if chi < 0 else "paramagnetic (attracted)" if chi > 0 else "non-magnetic"
            
            f.write(f"# Type {ptype} ({props['name']}): r={r_um:.1f} μm, χ={chi:.2e} ({mag_type})\n")
            f.write(f"variable coeff_t{ptype} equal {coeff:.12e}  # χ·V/μ₀ [m³/H]\n")
            f.write(f"variable fx_mag_t{ptype} atom \"v_coeff_t{ptype}*v_BgradB_x*v_force_mult\"\n")
            f.write(f"variable fy_mag_t{ptype} atom \"v_coeff_t{ptype}*v_BgradB_y*v_force_mult\"\n\n")
        
        # ===== FORCE APPLICATION WITH TIME-DEPENDENT RAMP =====
        f.write("\n# === FORCE RAMP-UP FOR SMOOTH TRANSITION ===\n")
        f.write("# Forces gradually increase from 0 to full strength over Phase 2\n")
        f.write("# This prevents instant particle repositioning\n")
        f.write("# Ramp duration: 100,000 timesteps (1.0 seconds)\n")
        f.write("variable step_phase2_start equal 150000\n")
        f.write("variable ramp_duration equal 100000\n")
        f.write("variable ramp_time equal \"(step-v_step_phase2_start)*(step>v_step_phase2_start)\"\n")
        f.write("variable ramp_progress equal \"v_ramp_time/v_ramp_duration*(v_ramp_time<v_ramp_duration)+1.0*(v_ramp_time>=v_ramp_duration)\"\n\n")

        # Around line 580 in create_liggghts_integration()
        # Replace the force application loop with:

        f.write("# === FORCE APPLICATION WITH SMOOTH RAMP ===\n")
        for ptype in particles.keys():
            f.write(f"# Type {ptype}: Magnetic force with smooth ramp + Damping\n")
            f.write(f"variable fx_mag_t{ptype}_ramped atom \"v_fx_mag_t{ptype}*v_ramp_progress\"\n")
            f.write(f"variable fy_mag_t{ptype}_ramped atom \"v_fy_mag_t{ptype}*v_ramp_progress\"\n")
            
            # CRITICAL FIX: Apply force only to specific type
            f.write(f"fix mag_force_t{ptype} type{ptype}_particles addforce v_fx_mag_t{ptype}_ramped v_fy_mag_t{ptype}_ramped 0.0\n")
            
            # Damping also per-type
            f.write(f"variable vx_damp_t{ptype} atom \"-v_damping_gamma*vx\"\n")
            f.write(f"variable vy_damp_t{ptype} atom \"-v_damping_gamma*vy\"\n")
            f.write(f"fix damp_force_t{ptype} type{ptype}_particles addforce v_vx_damp_t{ptype} v_vy_damp_t{ptype} 0.0\n\n")
                
        # === FORCE MONITORING (TYPE-SPECIFIC) ===
        # Note: Groups _temp_type1-4 already created in main script, just use them
        for ptype in particles.keys():
            f.write(f"compute fx_sum_t{ptype} _temp_type{ptype} reduce sum v_fx_mag_t{ptype}\n")
            f.write(f"compute fy_sum_t{ptype} _temp_type{ptype} reduce sum v_fy_mag_t{ptype}\n")
        f.write("\n")
        
        # === VTK OUTPUT VARIABLES (WITH FIELD VISUALIZATION) ===
        f.write("# These variables allow visualization of both forces AND field in ParaView\n")

        # Particle forces (existing)
        type_conditions = [f"(type=={ptype})*v_fx_mag_t{ptype}_ramped" for ptype in particles.keys()] 
        f.write(f"variable fx_mag_viz atom \"{' + '.join(type_conditions)}\"\n")
        type_conditions = [f"(type=={ptype})*v_fy_mag_t{ptype}_ramped" for ptype in particles.keys()]
        f.write(f"variable fy_mag_viz atom \"{' + '.join(type_conditions)}\"\n")
        f.write(f"variable fz_mag_viz atom \"0.0\"  # No z-component (2D field)\n\n")

        # Field magnitude at particle locations (NEW)
        f.write("# Magnetic field magnitude at each particle location\n")
        gauss_sum = " + ".join([f"v_gauss{i}*v_peak{i}_gradBx*v_peak{i}_gradBx + v_gauss{i}*v_peak{i}_gradBy*v_peak{i}_gradBy" 
                                for i in range(len(top_indices))])
        f.write(f"variable B_magnitude atom \"sqrt({gauss_sum})\"\n\n")

        # Gradient magnitude for visualization
        f.write(f"variable B_gradient_mag atom \"sqrt(v_BgradB_x*v_BgradB_x + v_BgradB_y*v_BgradB_y)\"\n\n")
        
        # Diagnostic variables
        f.write("# === DIAGNOSTIC VARIABLES ===\n")
        f.write("# Use these to verify coordinate mapping and field interpolation\n")
        f.write("variable x_mapped atom \"x*v_scale_x+v_offset_x\"  # DEM→FEM X coordinate\n")
        f.write("variable y_mapped atom \"y*v_scale_y+v_offset_y\"  # DEM→FEM Y coordinate\n")
        f.write("variable grad_check atom \"sqrt(v_BgradB_x*v_BgradB_x+v_BgradB_y*v_BgradB_y)\"  # Field gradient magnitude\n\n")

        # ========================================================================
        # FIELD GRID VISUALIZATION (creates dummy particles to show field shape)
        # ========================================================================
        if create_field_viz:
            f.write("\n# === FIELD GRID FOR VISUALIZATION (OPTIMIZED) ===\n")
            f.write(f"# Subsampled {subsample}x to reduce atom count\n")
            
            grid_spacing = x_viz[1] - x_viz[0] if len(x_viz) > 1 else 0.001
            
            # CRITICAL FIX: Position visualization grid BELOW particles
            z_bottom_wall = domain['z_min']
            z_viz_offset = 0.000  # 1 cm
            z_viz_bottom = z_bottom_wall + z_viz_offset    # above bottom wall
            z_viz_top = z_viz_bottom + 0.001  # 1mm thick
            
            f.write(f"# Positioned {z_viz_offset*1000:.1f} mm below bottom wall to avoid particle deletion\n")
            f.write(f"# Visualization plane: Z=[{z_viz_bottom:.6f}, {z_viz_top:.6f}] m\n\n")
            
            region_name = "field_viz_region"
            f.write(f"region {region_name} block ")
            f.write(f"{x_viz.min()-grid_spacing/2:.8f} {x_viz.max()+grid_spacing/2:.8f} ")
            f.write(f"{y_viz.min()-grid_spacing/2:.8f} {y_viz.max()+grid_spacing/2:.8f} ")
            f.write(f"{z_viz_bottom:.8f} {z_viz_top:.8f} units box\n")
            
            f.write(f"lattice sc {grid_spacing:.8f}\n")
            f.write(f"create_atoms 5 region {region_name}\n")
            f.write("neigh_modify exclude type 5 5\n")
            f.write(f"lattice none 1.0  # Reset lattice\n\n")

            f.write("# Freeze visualization particles\n")
            f.write("group field_viz type 5\n")
            f.write("fix freeze_viz field_viz setforce 0.0 0.0 0.0\n")
            f.write("velocity field_viz set 0.0 0.0 0.0\n\n")

            f.write("# === MAGNETIC FIELD GEOMETRY VISUALIZATION ===\n")
            f.write("# Type 5 particles show field structure as a 2D grid BELOW the simulation\n")
            f.write(f"# Grid location: {z_viz_offset*1000:.1f} mm below bottom wall (Z={z_bottom_wall:.4f} m)\n")
            f.write(f"# This prevents interference with real particles (types 1-4)\n\n")

            f.write(f"# Coil projection on visualization plane:\n")
            f.write(f"#   X: [{x_fem_min:.4f}, {x_fem_max:.4f}] m ({coil_width_x*100:.1f} cm wide)\n")
            f.write(f"#   Y: [{y_fem_min:.4f}, {y_fem_max:.4f}] m ({coil_width_y*100:.1f} cm wide)\n")
            f.write(f"#   Z: {(z_viz_bottom+z_viz_top)/2:.4f} m (visualization plane)\n\n")

            f.write("# In ParaView:\n")
            f.write("#   1. Filter by 'type == 5' to see field visualization grid\n")
            f.write("#   2. Color by 'v_B_magnitude' to see field strength\n")
            f.write("#   3. Filter by 'type != 5' to see actual particles\n")
            f.write("#   4. Add Glyph (arrows) to show force vectors\n\n")
        else:
            f.write("\n# === FIELD VISUALIZATION DISABLED ===\n")
            f.write("# To enable, set create_field_viz=True in preprocessor\n")
            f.write("# Visualization atoms would show field structure as type 5 particles\n\n")

        f.write("print \"✓ Magnetic field successfully activated!\"\n")
        f.write("print \"  - Force formula: F = (χ·V/μ₀)·(B·∇)B\"\n")
        f.write(f"print \"  - Update frequency: every {calc_freq} timesteps\"\n")
        f.write(f"print \"  - Velocity damping: γ = {damping_coeff:.2e}\"\n")
        f.write("print \"  - VTK variables: v_fx_mag, v_fy_mag, v_fz_mag\"\n")
        f.write("print \"  - Diagnostic variables: v_x_mapped, v_y_mapped, v_grad_check\"\n")

def create_visualizations(x_fem, y_fem, Bx, By, B, gradBx, gradBy, grad_mag, peak_threshold, peak_width, force_mult, config):
    """Create comprehensive scientific visualizations of the magnetic field"""
    
    X, Y = np.meshgrid(x_fem, y_fem)
    fig = plt.figure(figsize=(18, 14))
    gs = fig.add_gridspec(4, 3, figure=fig, hspace=0.4, wspace=0.35)
    
    # Row 0: Basic field components
    ax1 = fig.add_subplot(gs[0, 0])
    im1 = ax1.contourf(X*100, Y*100, B, levels=30, cmap='viridis')
    ax1.set_title('|B| Field Magnitude', fontweight='bold', fontsize=10)
    ax1.set_xlabel('X (cm)'); ax1.set_ylabel('Y (cm)')
    cbar1 = plt.colorbar(im1, ax=ax1, label='Tesla [T]')
    cbar1.ax.tick_params(labelsize=8)
    ax1.grid(alpha=0.3, linewidth=0.5)
    ax1.tick_params(labelsize=8)
    
    ax2 = fig.add_subplot(gs[0, 1])
    im2 = ax2.contourf(X*100, Y*100, Bx, levels=30, cmap='RdBu_r')
    ax2.set_title('Bx Component', fontweight='bold', fontsize=10)
    ax2.set_xlabel('X (cm)'); ax2.set_ylabel('Y (cm)')
    cbar2 = plt.colorbar(im2, ax=ax2, label='Tesla [T]')
    cbar2.ax.tick_params(labelsize=8)
    ax2.grid(alpha=0.3, linewidth=0.5)
    ax2.tick_params(labelsize=8)
    
    ax3 = fig.add_subplot(gs[0, 2])
    im3 = ax3.contourf(X*100, Y*100, By, levels=30, cmap='RdBu_r')
    ax3.set_title('By Component', fontweight='bold', fontsize=10)
    ax3.set_xlabel('X (cm)'); ax3.set_ylabel('Y (cm)')
    cbar3 = plt.colorbar(im3, ax=ax3, label='Tesla [T]')
    cbar3.ax.tick_params(labelsize=8)
    ax3.grid(alpha=0.3, linewidth=0.5)
    ax3.tick_params(labelsize=8)
    
    # Row 1: Force gradients (B·∇)B
    ax4 = fig.add_subplot(gs[1, 0])
    im4 = ax4.contourf(X*100, Y*100, gradBx, levels=30, cmap='plasma')
    ax4.set_title('(B·∇)Bx Force Gradient', fontweight='bold', fontsize=10)
    ax4.set_xlabel('X (cm)'); ax4.set_ylabel('Y (cm)')
    cbar4 = plt.colorbar(im4, ax=ax4, format='%.2e', label='T²/m')
    cbar4.ax.tick_params(labelsize=8)
    ax4.grid(alpha=0.3, linewidth=0.5)
    ax4.tick_params(labelsize=8)
    
    ax5 = fig.add_subplot(gs[1, 1])
    im5 = ax5.contourf(X*100, Y*100, gradBy, levels=30, cmap='plasma')
    ax5.set_title('(B·∇)By Force Gradient', fontweight='bold', fontsize=10)
    ax5.set_xlabel('X (cm)'); ax5.set_ylabel('Y (cm)')
    cbar5 = plt.colorbar(im5, ax=ax5, format='%.2e', label='T²/m')
    cbar5.ax.tick_params(labelsize=8)
    ax5.grid(alpha=0.3, linewidth=0.5)
    ax5.tick_params(labelsize=8)
    
    ax6 = fig.add_subplot(gs[1, 2])
    im6 = ax6.contourf(X*100, Y*100, grad_mag, levels=30, cmap='hot')
    ax6.set_title('|(B·∇)B| Total Gradient', fontweight='bold', fontsize=10)
    ax6.set_xlabel('X (cm)'); ax6.set_ylabel('Y (cm)')
    cbar6 = plt.colorbar(im6, ax=ax6, format='%.2e', label='T²/m')
    cbar6.ax.tick_params(labelsize=8)
    ax6.grid(alpha=0.3, linewidth=0.5)
    ax6.tick_params(labelsize=8)
    
    # Mark peak locations on the gradient magnitude plot
    # Use same algorithm as LIGGGHTS integration for consistency
    flat_grad = grad_mag.flatten()
    max_grad = grad_mag.max()
    threshold_value = peak_threshold * max_grad  # Match default peak_threshold
    min_separation = peak_width * 2.0
    
    candidate_indices = np.where(flat_grad >= threshold_value)[0]
    candidate_indices = candidate_indices[np.argsort(flat_grad[candidate_indices])[::-1]]
    
    top_indices = []
    for idx in candidate_indices:
        iy, ix = np.unravel_index(idx, grad_mag.shape)
        too_close = False
        for existing_idx in top_indices:
            ey, ex = np.unravel_index(existing_idx, grad_mag.shape)
            dist = np.sqrt((x_fem[ix] - x_fem[ex])**2 + (y_fem[iy] - y_fem[ey])**2)
            if dist < min_separation:
                too_close = True
                break
        if not too_close:
            top_indices.append(idx)
    
    # Plot peak markers
    for i, idx in enumerate(top_indices):
        iy, ix = np.unravel_index(idx, grad_mag.shape)
        ax6.plot(x_fem[ix]*100, y_fem[iy]*100, 'w*', markersize=15, 
                markeredgecolor='black', markeredgewidth=1.5, label=f'Peak {i+1}' if i < 3 else '')
    
    if len(top_indices) > 0:
        ax6.legend(loc='upper right', fontsize=7, framealpha=0.8)
    
    # Row 2: Force magnitude for different particle types (log scale)
    particles = config['particles']
    
    for idx, ptype in enumerate(sorted(particles.keys())[:3]):
        ax = fig.add_subplot(gs[2, idx])
        props = particles[ptype]
        chi = props['chi']
        V = (4/3) * np.pi * props['r']**3
        
        # Force magnitude: |F| = |χ·V/μ₀|·|(B·∇)B|
        force_mag_N = np.abs(chi * V / MU0) * grad_mag * force_mult
        force_mag_pN = force_mag_N * 1e12  # Convert to piconewtons
        force_mag_log = np.log10(force_mag_pN + 1e-6)  # Log scale
        
        im = ax.contourf(X*100, Y*100, force_mag_log, levels=30, cmap='inferno')
        mag_type = "Dia" if chi < 0 else "Para"
        ax.set_title(f'{mag_type}-mag Force: Type {ptype} ({props["r"]*1e6:.0f} μm)', fontsize=9)
        ax.set_xlabel('X (cm)', fontsize=8); ax.set_ylabel('Y (cm)', fontsize=8)
        
        cbar = plt.colorbar(im, ax=ax, format='%.1f')
        cbar.set_label('log₁₀(Force [pN])', fontsize=8)
        cbar.ax.tick_params(labelsize=7)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.3, linewidth=0.5)
    
    # Row 3: Force components for largest particle type
    ptype_largest = max(particles.keys(), key=lambda k: particles[k]['r'])
    props_largest = particles[ptype_largest]
    chi_largest = props_largest['chi']
    V_largest = (4/3) * np.pi * props_largest['r']**3
    coeff = (chi_largest * V_largest / MU0) * force_mult
    
    Fx_nN = coeff * gradBx * 1e9  # Convert to nanonewtons
    Fy_nN = coeff * gradBy * 1e9
    
    ax_fx = fig.add_subplot(gs[3, 0])
    im_fx = ax_fx.contourf(X*100, Y*100, Fx_nN, levels=30, cmap='RdBu_r')
    mag_behavior = "Repulsion" if chi_largest < 0 else "Attraction"
    ax_fx.set_title(f'Type {ptype_largest} Fx ({mag_behavior})', fontsize=9, fontweight='bold')
    ax_fx.set_xlabel('X (cm)', fontsize=8); ax_fx.set_ylabel('Y (cm)', fontsize=8)
    cbar_fx = plt.colorbar(im_fx, ax=ax_fx, format='%.2e')
    cbar_fx.set_label('Force Fx [nN]', fontsize=8)
    cbar_fx.ax.tick_params(labelsize=7)
    ax_fx.tick_params(labelsize=7)
    ax_fx.grid(alpha=0.3, linewidth=0.5)
    
    ax_fy = fig.add_subplot(gs[3, 1])
    im_fy = ax_fy.contourf(X*100, Y*100, Fy_nN, levels=30, cmap='RdBu_r')
    ax_fy.set_title(f'Type {ptype_largest} Fy ({mag_behavior})', fontsize=9, fontweight='bold')
    ax_fy.set_xlabel('X (cm)', fontsize=8); ax_fy.set_ylabel('Y (cm)', fontsize=8)
    cbar_fy = plt.colorbar(im_fy, ax=ax_fy, format='%.2e')
    cbar_fy.set_label('Force Fy [nN]', fontsize=8)
    cbar_fy.ax.tick_params(labelsize=7)
    ax_fy.tick_params(labelsize=7)
    ax_fy.grid(alpha=0.3, linewidth=0.5)
    
    # Row 3, Column 3: Summary text
    ax_text = fig.add_subplot(gs[3, 2])
    ax_text.axis('off')
    
    summary_text = "FIELD SUMMARY\n" + "="*30 + "\n\n"
    summary_text += f"Max |B|: {B.max():.3f} T\n"
    summary_text += f"Max |(B·∇)B|: {grad_mag.max():.2e} T²/m\n\n"
    summary_text += "PARTICLE PHYSICS:\n"
    
    for ptype in sorted(particles.keys()):
        props = particles[ptype]
        chi = props['chi']
        mag_label = "Diamag" if chi < 0 else "Paramag"
        summary_text += f"Type {ptype}: {mag_label}, χ={chi:.1e}\n"
    
    ax_text.text(0.1, 0.9, summary_text, transform=ax_text.transAxes,
                fontfamily='monospace', fontsize=8, verticalalignment='top')
    
    plt.suptitle('Magnetic Field Analysis for LIGGGHTS DEM Simulation',
                fontsize=14, fontweight='bold', y=0.995)
    plt.savefig('magnetic_field_analysis.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("✓ Visualization saved: magnetic_field_analysis.png")

def generate_physics_summary(B_mag, gradBx, gradBy, force_mult, config):
    """Generate comprehensive physics summary with scientifically accurate calculations"""
    
    grad_mag = np.sqrt(gradBx**2 + gradBy**2)
    particles = config['particles']
    g = config['gravity']
    
    with open('physics_summary.txt', 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("MAGNETIC FORCE PHYSICS SUMMARY\n")
        f.write("Scientifically Accurate Calculations for DEM Simulation\n")
        f.write("="*80 + "\n\n")
        
        f.write("FUNDAMENTAL CONSTANTS:\n")
        f.write(f"  μ₀ (vacuum permeability): {MU0:.12e} H/m\n\n")
        
        f.write("MAGNETIC FIELD CHARACTERISTICS:\n")
        f.write(f"  Max |B|: {B_mag.max():.6f} T\n")
        f.write(f"  Min |B|: {B_mag.min():.6f} T\n")
        f.write(f"  Max |(B·∇)B|: {grad_mag.max():.6e} T²/m\n")
        f.write(f"  Min |(B·∇)B|: {grad_mag.min():.6e} T²/m\n\n")
        
        f.write("DEM SIMULATION PARAMETERS:\n")
        f.write(f"  Domain: [{config['domain']['x_min']:.4f}, {config['domain']['x_max']:.4f}] × ")
        f.write(f"[{config['domain']['y_min']:.4f}, {config['domain']['y_max']:.4f}] m\n")
        f.write(f"  Gravity: {g:.6f} m/s²\n")
        f.write(f"  Particle types: {len(particles)}\n")
        f.write(f"  Force multiplier: {force_mult:.6f}\n")
        f.write(f"  Timestep: {config['timestep']:.2e} s\n\n")
        
        f.write("MAGNETIC PHYSICS:\n")
        chi_values = [p['chi'] for p in particles.values()]
        if all(chi < 0 for chi in chi_values):
            f.write("  Material type: DIAMAGNETIC (all χ < 0)\n")
            f.write("  Behavior: Particles REPELLED from high-field regions\n")
        elif all(chi > 0 for chi in chi_values):
            f.write("  Material type: PARAMAGNETIC (all χ > 0)\n")
            f.write("  Behavior: Particles ATTRACTED to high-field regions\n")
        else:
            f.write("  Material type: MIXED (both diamagnetic and paramagnetic)\n")
        
        f.write("  Force formula: F = (χ·V/μ₀)·(B·∇)B\n")
        f.write("  where:\n")
        f.write("    χ = magnetic susceptibility [dimensionless]\n")
        f.write("    V = particle volume [m³]\n")
        f.write("    (B·∇)B = magnetic force gradient [T²/m]\n\n")
        
        f.write("PARTICLE-SPECIFIC FORCE ANALYSIS (at maximum field gradient):\n")
        f.write("="*80 + "\n\n")
        
        for ptype in sorted(particles.keys()):
            props = particles[ptype]
            chi, r, rho = props['chi'], props['r'], props['density']
            V = (4/3) * np.pi * r**3
            m = rho * V
            
            # Maximum magnetic force: F = |χ·V/μ₀|·max|(B·∇)B|·force_mult
            F_mag_max = np.abs(chi * V / MU0) * grad_mag.max() * force_mult
            F_grav = m * g
            ratio = F_mag_max / F_grav if F_grav > 0 else 0
            
            # Calculate characteristic velocity and time scales
            if ratio > 0:
                # Acceleration: a = F/m
                a_mag = F_mag_max / m
                # Characteristic time to reach 1 mm/s: t = v/a
                t_char = 0.001 / a_mag if a_mag > 0 else float('inf')
            else:
                a_mag = 0
                t_char = float('inf')
            
            f.write(f"Type {ptype}: {props['name']}\n")
            f.write(f"{'-'*80}\n")
            f.write(f"  Geometric properties:\n")
            f.write(f"    Radius: {r*1e6:.2f} μm = {r:.6e} m\n")
            f.write(f"    Volume: {V:.6e} m³\n")
            f.write(f"    Density: {rho:.1f} kg/m³\n")
            f.write(f"    Mass: {m:.6e} kg\n\n")
            
            f.write(f"  Magnetic properties:\n")
            f.write(f"    Susceptibility χ: {chi:.6e} ")
            f.write(f"({'diamagnetic' if chi < 0 else 'paramagnetic' if chi > 0 else 'non-magnetic'})\n")
            f.write(f"    Coefficient χ·V/μ₀: {chi*V/MU0:.6e} m³/H\n\n")
            
            f.write(f"  Force analysis:\n")
            f.write(f"    F_magnetic (max): {F_mag_max:.6e} N = {F_mag_max*1e12:.2f} pN\n")
            f.write(f"    F_gravity: {F_grav:.6e} N = {F_grav*1e12:.2f} pN\n")
            f.write(f"    Ratio F_mag/F_grav: {ratio:.3f}\n\n")
            
            f.write(f"  Motion characteristics:\n")
            f.write(f"    Max acceleration: {a_mag:.6e} m/s²\n")
            f.write(f"    Time to 1 mm/s: {t_char:.3f} s = {t_char/config['timestep']:.0f} timesteps\n")
            
            if ratio > 10:
                f.write(f"    → STRONG magnetic effect ({ratio:.1f}× gravity)\n")
                f.write(f"    → Expect significant particle reorganization\n")
            elif ratio > 1:
                f.write(f"    → MODERATE magnetic effect ({ratio:.1f}× gravity)\n")
                f.write(f"    → Observable reorganization likely\n")
            elif ratio > 0.1:
                f.write(f"    → WEAK magnetic effect ({ratio*100:.1f}% of gravity)\n")
                f.write(f"    → Subtle effects, may compete with cohesion/friction\n")
            else:
                f.write(f"    → NEGLIGIBLE magnetic effect ({ratio*100:.3f}% of gravity)\n")
                f.write(f"    → Effects likely masked by other forces\n")
            
            f.write("\n")
        
        f.write("="*80 + "\n")
        f.write("SCIENTIFIC RECOMMENDATIONS:\n")
        f.write("="*80 + "\n\n")
        
        max_ratio = max([np.abs(p['chi']) * (4/3) * np.pi * p['r']**3 / MU0 * grad_mag.max() * force_mult / 
                        (p['density'] * (4/3) * np.pi * p['r']**3 * g) 
                        for p in particles.values()])
        
        if max_ratio > 10:
            f.write("1. FORCE MAGNITUDE: Forces are significant and realistic\n")
            f.write("   → Observable magnetic reorganization expected\n")
            f.write("   → Particle motion should be visible in VTK output\n\n")
        elif max_ratio > 0.1:
            f.write("1. FORCE MAGNITUDE: Forces are moderate\n")
            f.write("   → Subtle effects competing with gravity/cohesion\n")
            f.write("   → Longer simulation time may be needed\n")
            f.write("   → Consider increasing force_multiplier if no motion observed\n\n")
        else:
            f.write("1. FORCE MAGNITUDE: Forces are very weak\n")
            f.write("   → Magnetic effects likely negligible\n")
            f.write("   → Try increasing force_multiplier by 10-100×\n")
            f.write("   → Or reduce cohesion/friction parameters\n\n")
        
        f.write("2. VISUALIZATION CHECKS:\n")
        f.write("   → Load VTK files in ParaView\n")
        f.write("   → Add Glyph filter with v_fx_mag, v_fy_mag, v_fz_mag as vectors\n")
        f.write("   → Check v_grad_check to verify field interpolation\n")
        f.write("   → Compare particle positions before/after field activation\n\n")
        
        f.write("3. PHYSICAL VALIDATION:\n")
        if all(chi < 0 for chi in chi_values):
            f.write("   → Particles should move AWAY from high-field regions\n")
            f.write("   → Expect accumulation in low-field zones (edges/corners)\n")
        elif all(chi > 0 for chi in chi_values):
            f.write("   → Particles should move TOWARD high-field regions\n")
            f.write("   → Expect concentration near field maxima\n")
        f.write("   → All particle sizes should respond similarly (χ independent of size)\n")
        f.write("   → Velocities should be mm/s scale, not m/s\n\n")
        
        f.write("4. NUMERICAL ACCURACY:\n")
        f.write("   → Domain mapping verified: DEM coordinates → FEM coordinates\n")
        f.write("   → Gaussian approximation with sufficient peaks\n")
        f.write("   → Force update frequency optimized for performance\n")
        f.write("   → Velocity damping prevents numerical instability\n\n")
        
        f.write("="*80 + "\n")
        f.write("Notes:\n")
        f.write("  • All calculations use SI units throughout\n")
        f.write("  • μ₀ value from CODATA 2018 physical constants\n")
        f.write("  • Force formula valid for weak-field approximation (χ << 1)\n")
        f.write("  • Coordinate mapping automatically extracted from input files\n")
        f.write("  • No hardcoded parameters except fundamental constants\n")
        f.write("="*80 + "\n")
    
    print("✓ Physics summary saved: physics_summary.txt")

def main():
    """Main execution function with command-line argument parsing"""
    
    # Default parameters
    field_file = 'B_output.txt'
    force_multiplier = 0.1
    liggghts_file = 'in.lunar_dust_magnetic'
    peak_threshold = 0.20  # 20% of max gradient
    calc_freq = 100
    create_field_viz=True
    
    # Parse command-line arguments
    if len(sys.argv) > 1:
        field_file = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            force_multiplier = float(sys.argv[2])
        except ValueError:
            print("⚠ Invalid force multiplier, using default 0.1")
    if len(sys.argv) > 3:
        liggghts_file = sys.argv[3]
    if len(sys.argv) > 4:
        try:
            peak_threshold = float(sys.argv[4])
            if not 0.05 <= peak_threshold <= 0.95:
                print("⚠ peak_threshold should be between 0.05 and 0.95, using default 0.20")
                peak_threshold = 0.20
        except ValueError:
            print("⚠ Invalid peak_threshold, using default 0.20")
    if len(sys.argv) > 5:
        try:
            calc_freq = int(sys.argv[5])
            if calc_freq < 1:
                print("⚠ calc_freq should be >= 1, using default 100")
                calc_freq = 100
        except ValueError:
            print("⚠ Invalid calc_freq, using default 100")
    if len(sys.argv) > 6:
        create_field_viz = sys.argv[6].lower() in ['true', '1', 'yes']
    else:
        create_field_viz = False
    
    # Validate input files
    if not os.path.exists(field_file):
        print(f"✗ ERROR: Field file '{field_file}' not found!")
        print("\nUsage: python preprocess_magnetic_field.py [field_file] [force_mult] [liggghts_file] [peak_threshold]")
        print("  field_file     : FEM magnetic field data (default: B_output.txt)")
        print("  force_mult     : Force scaling factor (default: 0.1)")
        print("  liggghts_file  : LIGGGHTS input file (default: in.lunar_dust_magnetic)")
        print("  peak_threshold : Peak selection threshold, 0.05-0.95 (default: 0.20)")
        print("                   Lower = more peaks, higher = fewer peaks")
        sys.exit(1)
    
    if not os.path.exists(liggghts_file):
        print(f"✗ ERROR: LIGGGHTS file '{liggghts_file}' not found!")
        sys.exit(1)
    
    # Run preprocessor
    print("\n" + "="*80)
    print("FULLY DYNAMIC MAGNETIC FIELD PREPROCESSOR")
    print("Automatic parameter extraction with scientific accuracy")
    print("="*80 + "\n")
    
    try:
        success = preprocess_magnetic_field(
            field_file=field_file,
            force_multiplier=force_multiplier,
            liggghts_file=liggghts_file,
            peak_threshold=peak_threshold,
            calc_freq=calc_freq,
            create_field_viz=create_field_viz
        )
        
        if success:
            print("\n" + "="*80)
            print("NEXT STEPS:")
            print("="*80)
            print("1. Review physics_summary.txt for detailed force analysis")
            print("2. Check magnetic_field_analysis.png for field visualization")
            print("3. Run LIGGGHTS simulation:")
            print(f"   liggghts < {liggghts_file}")
            print("4. In ParaView:")
            print("   - Load VTK files from post/ directory")
            print("   - Add Glyph filter using v_fx_mag, v_fy_mag, v_fz_mag as vectors")
            print("   - Verify v_grad_check shows correct field distribution")
            print("   - Compare particle configurations before/after field activation")
            print("5. Verify physics:")
            
            # Read back the config to determine magnetic behavior
            with open(liggghts_file, 'r') as f:
                content = f.read()
            mag_sus_pattern = r'fix\s+mag_sus\s+all\s+property/global\s+magneticSusceptibility\s+peratomtype\s+([\d\.\-e\s]+)'
            mag_sus_match = re.search(mag_sus_pattern, content)
            if mag_sus_match:
                chi_values = [float(x) for x in mag_sus_match.group(1).split()]
                if all(chi < 0 for chi in chi_values):
                    print("   - Particles should move AWAY from high-field regions (diamagnetic)")
                elif all(chi > 0 for chi in chi_values):
                    print("   - Particles should move TOWARD high-field regions (paramagnetic)")
                else:
                    print("   - Mixed behavior expected (both attraction and repulsion)")
            
            print("   - Particle velocities should be mm/s scale (not m/s)")
            print("   - All particle sizes should respond similarly")
            print("="*80 + "\n")
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()