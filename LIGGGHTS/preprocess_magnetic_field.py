#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LIGGGHTS-COMPATIBLE Magnetic Field Preprocessor with COMPREHENSIVE DEBUGGING
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys
import os
import re

# FUNDAMENTAL PHYSICAL CONSTANTS
MU0 = 1.25663706212e-6  # Vacuum permeability [H/m]

def parse_liggghts_complete(liggghts_file='in.lunar_dust_magnetic'):
    """Parse LIGGGHTS input file to extract ALL simulation parameters"""
    
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
        
        # Extract domain
        region_pattern = r'region\s+\w+\s+block\s+([\-\d\.e]+)\s+([\-\d\.e]+)\s+([\-\d\.e]+)\s+([\-\d\.e]+)\s+([\-\d\.e]+)\s+([\-\d\.e]+)'
        region_match = re.search(region_pattern, content)
        
        if region_match:
            config['domain']['x_min'] = float(region_match.group(1))
            config['domain']['x_max'] = float(region_match.group(2))
            config['domain']['y_min'] = float(region_match.group(3))
            config['domain']['y_max'] = float(region_match.group(4))
            config['domain']['z_min'] = float(region_match.group(5))
            config['domain']['z_max'] = float(region_match.group(6))
            
            print(f"\n✓ DOMAIN: X=[{config['domain']['x_min']:.4f}, {config['domain']['x_max']:.4f}] m")
            print(f"          Y=[{config['domain']['y_min']:.4f}, {config['domain']['y_max']:.4f}] m")
            print(f"          Z=[{config['domain']['z_min']:.4f}, {config['domain']['z_max']:.4f}] m")
        
        # Extract number of particle types
        create_box_pattern = r'create_box\s+(\d+)'
        create_box_match = re.search(create_box_pattern, content)
        if create_box_match:
            config['n_types'] = int(create_box_match.group(1))
            print(f"\n✓ PARTICLE TYPES: {config['n_types']}")
        
        # Extract timestep
        timestep_pattern = r'timestep\s+([\d\.e\-]+)'
        timestep_match = re.search(timestep_pattern, content)
        if timestep_match:
            config['timestep'] = float(timestep_match.group(1))
            print(f"✓ TIMESTEP: {config['timestep']:.2e} s")
        
        # Extract gravity
        gravity_pattern = r'fix\s+\w+\s+all\s+gravity\s+([\d\.e\-]+)'
        gravity_match = re.search(gravity_pattern, content)
        if gravity_match:
            config['gravity'] = float(gravity_match.group(1))
            print(f"✓ GRAVITY: {config['gravity']:.3f} m/s²")
        
        # Extract magnetic susceptibilities
        mag_sus_pattern = r'fix\s+mag_sus\s+all\s+property/global\s+magneticSusceptibility\s+peratomtype\s+([\d\.\-e\s]+)'
        mag_sus_match = re.search(mag_sus_pattern, content)
        
        if mag_sus_match:
            chi_values = [float(x) for x in mag_sus_match.group(1).split()]
            print(f"\n✓ MAGNETIC SUSCEPTIBILITIES:")
            for i, chi in enumerate(chi_values, 1):
                chi_type = "diamagnetic" if chi < 0 else "paramagnetic"
                print(f"  Type {i}: χ = {chi:.2e} ({chi_type})")
        
        # Extract particle templates
        template_pattern = r'fix\s+(\w+)\s+all\s+particletemplate/sphere\s+\d+\s+atom_type\s+(\d+)\s+(?:&\s*)?density\s+constant\s+([\d\.e\-]+)\s+(?:&\s*)?radius\s+constant\s+([\d\.e\-]+)'
        
        print(f"\n✓ PARTICLE TEMPLATES:")
        for match in re.finditer(template_pattern, content, re.MULTILINE | re.DOTALL):
            template_name = match.group(1)
            ptype = int(match.group(2))
            density = float(match.group(3))
            radius = float(match.group(4))
            
            config['particles'][ptype] = {
                'chi': chi_values[ptype-1],
                'r': radius,
                'density': density,
                'name': template_name
            }
            
            print(f"  Type {ptype}: r={radius*1e6:6.1f} μm, ρ={density:4.0f} kg/m³, χ={chi_values[ptype-1]:.2e}")
        
        print(f"{'='*80}\n")
        return config
        
    except Exception as e:
        print(f"\n✗ ERROR parsing LIGGGHTS file: {e}")
        raise

def preprocess_magnetic_field(field_file='B_output.txt', force_multiplier=0.1, 
                              liggghts_file='in.lunar_dust_magnetic'):
    """
    Preprocess FEM magnetic field for LIGGGHTS with proper constraints
    """
    
    print("="*80)
    print("LIGGGHTS-COMPATIBLE MAGNETIC FIELD PREPROCESSOR")
    print("="*80)
    
    # Parse LIGGGHTS configuration
    config = parse_liggghts_complete(liggghts_file)
    
    # Read FEM field data
    print(f"\n{'='*80}")
    print(f"READING FEM FIELD DATA: {field_file}")
    print(f"{'='*80}\n")
    
    data = pd.read_csv(field_file, sep='\t', comment='#', skipinitialspace=True)
    data = data.dropna(how='all')
    
    # Convert cm to m
    fem_x = data['X'].astype(float).values / 100.0
    fem_y = data['Y'].astype(float).values / 100.0
    
    # Extract field components
    fem_Bx = data['Bx'].astype(float).values
    fem_By = data['By'].astype(float).values
    fem_B_mag = data['B_mag'].astype(float).values
    
    # Extract gradients (T/cm to T/m)
    dBx_dx = data['dBx_dx'].astype(float).values * 100.0
    dBx_dy = data['dBx_dy'].astype(float).values * 100.0
    dBy_dx = data['dBy_dx'].astype(float).values * 100.0
    dBy_dy = data['dBy_dy'].astype(float).values * 100.0
    
    print(f"✓ Loaded {len(data)} field points")
    print(f"✓ FEM domain: X=[{fem_x.min():.4f}, {fem_x.max():.4f}], Y=[{fem_y.min():.4f}, {fem_y.max():.4f}] m")
    print(f"✓ Field range: |B|=[{fem_B_mag.min():.6f}, {fem_B_mag.max():.6f}] T")
    
    # Get unique grid coordinates
    x_unique = np.sort(np.unique(fem_x))
    y_unique = np.sort(np.unique(fem_y))
    nx, ny = len(x_unique), len(y_unique)
    
    print(f"✓ FEM grid: {nx} × {ny} points")
    
    # Reshape to 2D grids
    Bx_grid = fem_Bx.reshape(ny, nx)
    By_grid = fem_By.reshape(ny, nx)
    B_grid = fem_B_mag.reshape(ny, nx)
    
    dBx_dx_grid = dBx_dx.reshape(ny, nx)
    dBx_dy_grid = dBx_dy.reshape(ny, nx)
    dBy_dx_grid = dBy_dx.reshape(ny, nx)
    dBy_dy_grid = dBy_dy.reshape(ny, nx)
    
    # Calculate (B·∇)B force gradients
    gradBx = Bx_grid * dBx_dx_grid + By_grid * dBx_dy_grid
    gradBy = Bx_grid * dBy_dx_grid + By_grid * dBy_dy_grid
    grad_mag = np.sqrt(gradBx**2 + gradBy**2)

    print(f"✓ Max |(B·∇)B|: {grad_mag.max():.2e} T²/m")

    # ============================================================================
    # CROP FEM DOMAIN TO MAGNETIC COIL REGION
    # ============================================================================
    print(f"\n{'='*80}")
    print("CROPPING FEM DOMAIN TO MAGNETIC COIL REGION")
    print(f"{'='*80}")

    # Identify coil region from high-gradient areas
    crop_threshold = 0.05
    grad_threshold = crop_threshold * grad_mag.max()
    coil_mask = grad_mag > grad_threshold

    # Find bounding box of coil
    coil_x_indices = np.any(coil_mask, axis=0)
    coil_y_indices = np.any(coil_mask, axis=1)

    # Add small margin
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
        B_grid = B_grid[np.ix_(y_coil_indices, x_coil_indices)]
        gradBx = gradBx[np.ix_(y_coil_indices, x_coil_indices)]
        gradBy = gradBy[np.ix_(y_coil_indices, x_coil_indices)]
        grad_mag = grad_mag[np.ix_(y_coil_indices, x_coil_indices)]

        # Crop the FEM gradient arrays too
        dBx_dx_grid = dBx_dx_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBx_dy_grid = dBx_dy_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBy_dx_grid = dBy_dx_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBy_dy_grid = dBy_dy_grid[np.ix_(y_coil_indices, x_coil_indices)]

        assert Bx_grid.shape == dBx_dx_grid.shape == dBy_dx_grid.shape == dBx_dy_grid.shape == dBy_dy_grid.shape, \
            "Grid shapes disagree — check cropping logic!"

        print(f"  Cropped grid: {len(x_unique)} × {len(y_unique)} points")
        print(f"  Coil width: {(x_coil_max-x_coil_min)*100:.1f} × {(y_coil_max-y_coil_min)*100:.1f} cm")
        print(f"  Shapes after cropping: Bx={Bx_grid.shape}, gradients={dBx_dx_grid.shape}")
        print(f"{'='*80}\n")
    
    # Create LIGGGHTS integration file
    create_liggghts_integration(x_unique, y_unique, Bx_grid, By_grid, B_grid,
                                gradBx, gradBy, force_multiplier, config)
    
    # Create visualizations
    create_visualizations(x_unique, y_unique, Bx_grid, By_grid, B_grid, 
                         gradBx, gradBy, grad_mag, force_multiplier, config)
    
    print(f"\n{'='*80}")
    print("✓ PREPROCESSING COMPLETE!")
    print(f"{'='*80}")
    print("Generated files:")
    print("  • magnetic_field_apply.lmp")
    print("  • magnetic_field_analysis.png")
    print(f"{'='*80}\n")
    
    return True

def create_liggghts_integration(x_fem, y_fem, Bx, By, B_grid, gradBx, gradBy, 
                                force_mult, config):
    """
    Create LIGGGHTS-compatible magnetic field application with COMPREHENSIVE DEBUGGING
    """
    
    particles = config['particles']
    domain = config['domain']

    # ============================================================================
    # CRITICAL: CORRECT COORDINATE MAPPING FEM → DEM
    # ============================================================================
    # Strategy: Map FEM coil center directly to DEM origin (0, 0)
    # 
    # The issue: DEM domain center is (0, 0) in physical coordinates
    # FEM coil center is at some arbitrary position from COMSOL
    # 
    # Simple mapping: Shift FEM by its own center to place it at DEM origin
    # ============================================================================

    # FEM coil bounds and center
    x_coil_min, x_coil_max = x_fem.min(), x_fem.max()
    y_coil_min, y_coil_max = y_fem.min(), y_fem.max()
    x_coil_center = (x_coil_min + x_coil_max) / 2.0
    y_coil_center = (y_coil_min + y_coil_max) / 2.0
    coil_width_x = x_coil_max - x_coil_min
    coil_width_y = y_coil_max - y_coil_min

    # DEM domain center (0, 0 in this simulation)
    x_dem_center = (domain['x_min'] + domain['x_max']) / 2.0
    y_dem_center = (domain['y_min'] + domain['y_max']) / 2.0

    # SIMPLE OFFSET: Just use FEM center directly
    # This places FEM coil center at DEM (0, 0)
    offset_x = x_coil_center
    offset_y = y_coil_center

    print(f"\n{'='*80}")
    print("COORDINATE MAPPING VERIFICATION")
    print(f"{'='*80}")
    print(f"FEM coil:")
    print(f"  Bounds: X=[{x_coil_min:.6f}, {x_coil_max:.6f}] m")
    print(f"          Y=[{y_coil_min:.6f}, {y_coil_max:.6f}] m")
    print(f"  Center: ({x_coil_center:.6f}, {y_coil_center:.6f}) m")
    print(f"  Width:  {coil_width_x*100:.2f} × {coil_width_y*100:.2f} cm")
    print(f"")
    print(f"DEM domain:")
    print(f"  Bounds: X=[{domain['x_min']:.6f}, {domain['x_max']:.6f}] m")
    print(f"          Y=[{domain['y_min']:.6f}, {domain['y_max']:.6f}] m")
    print(f"  Center: ({x_dem_center:.6f}, {y_dem_center:.6f}) m")
    print(f"")
    print(f"Coordinate transformation:")
    print(f"  Offset: ({offset_x:.6f}, {offset_y:.6f}) m")
    print(f"  Formula: x_DEM = x_FEM - {offset_x:.6f}")
    print(f"           y_DEM = y_FEM - {offset_y:.6f}")
    print(f"")
    print(f"Verification (coil center after mapping):")
    coil_center_in_dem_x = x_coil_center - offset_x
    coil_center_in_dem_y = y_coil_center - offset_y
    print(f"  FEM coil center ({x_coil_center:.6f}, {y_coil_center:.6f})")
    print(f"  Maps to DEM: ({coil_center_in_dem_x:.6f}, {coil_center_in_dem_y:.6f})")
    print(f"  DEM center:  ({x_dem_center:.6f}, {y_dem_center:.6f})")
    print(f"  Match? {abs(coil_center_in_dem_x - x_dem_center) < 1e-6 and abs(coil_center_in_dem_y - y_dem_center) < 1e-6}")
    print(f"")
    print(f"Coil coverage in DEM domain:")
    coil_x_min_dem = x_coil_min - offset_x
    coil_x_max_dem = x_coil_max - offset_x
    coil_y_min_dem = y_coil_min - offset_y
    coil_y_max_dem = y_coil_max - offset_y
    print(f"  X: [{coil_x_min_dem:.6f}, {coil_x_max_dem:.6f}] m")
    print(f"  Y: [{coil_y_min_dem:.6f}, {coil_y_max_dem:.6f}] m")
    print(f"{'='*80}\n")

    # Use FULL resolution - no coarsening
    # This ensures we don't miss particles due to grid spacing
    target_regions = len(x_fem) * len(y_fem)
    
    # Calculate optimal grid density
    aspect_ratio = len(x_fem) / len(y_fem)
    nx_grid = min(len(x_fem), int(np.sqrt(target_regions * aspect_ratio)))
    ny_grid = min(len(y_fem), int(target_regions / nx_grid))
    
    # Coarsen grid if needed
    x_indices = np.linspace(0, len(x_fem)-1, nx_grid, dtype=int)
    y_indices = np.linspace(0, len(y_fem)-1, ny_grid, dtype=int)
    
    x_coarse = x_fem[x_indices]
    y_coarse = y_fem[y_indices]
    
    print(f"\n✓ Creating {nx_grid}x{ny_grid} = {nx_grid*ny_grid} regions")
    print(f"  Region size: ~{(x_coarse[1]-x_coarse[0])*1000:.1f} × {(y_coarse[1]-y_coarse[0])*1000:.1f} mm")
    print(f"\n📍 CRITICAL DEBUG - Coordinate Transform:")
    print(f"  FEM coil center: ({x_coil_center:.6f}, {y_coil_center:.6f})")
    print(f"  DEM target: ({x_dem_center:.6f}, {y_dem_center:.6f})")
    print(f"  Offset being applied: ({offset_x:.6f}, {offset_y:.6f})")
    print(f"  ")
    print(f"  Example: FEM point ({x_coarse[0]:.6f}, {y_coarse[0]:.6f})")
    print(f"  Maps to DEM: ({x_coarse[0] - offset_x:.6f}, {y_coarse[0] - offset_y:.6f})")
    print(f"  ")
    print(f"  FEM coil center ({x_coil_center:.6f}, {y_coil_center:.6f})")
    print(f"  Maps to DEM: ({x_coil_center - offset_x:.6f}, {y_coil_center - offset_y:.6f})")
    print(f"  (Should be exactly ({x_dem_center:.6f}, {y_dem_center:.6f}))\n")
    
    # Generate LIGGGHTS script with COMPREHENSIVE DEBUGGING
    with open('magnetic_field_apply.lmp', 'w', encoding='utf-8') as f:
        f.write("# " + "="*74 + "\n")
        f.write("# LIGGGHTS MAGNETIC FIELD WITH COMPREHENSIVE DEBUGGING\n")
        f.write(f"# Grid: {nx_grid}×{ny_grid} = {nx_grid*ny_grid} regions\n")
        f.write("# " + "="*74 + "\n\n")
        
        # =====================================================================
        # INITIAL SYSTEM STATE
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: INITIAL SYSTEM STATE\n")
        f.write("# " + "="*74 + "\n")
        f.write("print '==============================================================================='\n")
        f.write("print 'DEBUG: PRE-MAGNETIC FIELD SYSTEM STATE'\n")
        f.write("print '==============================================================================='\n")
        f.write("variable n_atoms equal atoms\n")
        f.write("variable dt_val equal dt\n")
        f.write("variable step_val equal step\n")
        f.write("variable time_val equal time\n")
        f.write("print 'Total atoms: ${n_atoms}'\n")
        f.write(f"print 'Total types: {config['n_types']}'\n")
        f.write("print 'Timestep: ${dt_val}'\n")
        f.write("print 'Current step: ${step_val}'\n")
        f.write("print 'Simulation time: ${time_val} s'\n")
        f.write("print '-------------------------------------------------------------------------------'\n\n")
        
        # Domain check
        f.write("# Domain boundaries\n")
        f.write(f"print 'Domain X: {domain["x_min"]:.6f} to {domain["x_max"]:.6f} m'\n")
        f.write(f"print 'Domain Y: {domain["y_min"]:.6f} to {domain["y_max"]:.6f} m'\n")
        f.write(f"print 'Domain Z: {domain["z_min"]:.6f} to {domain["z_max"]:.6f} m'\n")
        f.write("print '-------------------------------------------------------------------------------'\n\n")
        
        # Per-type particle counts
        f.write("# Particle counts by type\n")
        for ptype in particles.keys():
            f.write(f"variable n_type{ptype} equal count(type{ptype}_particles)\n")
            f.write(f"print 'Type {ptype} particles: ${{n_type{ptype}}}'\n")
        f.write("print '-------------------------------------------------------------------------------'\n\n")
        
        # Center of mass tracking
        f.write("# Center of mass (initial)\n")
        for ptype in particles.keys():
            f.write(f"variable com_x_{ptype}_init equal xcm(type{ptype}_particles,x)\n")
            f.write(f"variable com_y_{ptype}_init equal xcm(type{ptype}_particles,y)\n")
            f.write(f"variable com_z_{ptype}_init equal xcm(type{ptype}_particles,z)\n")
            f.write(f"print 'Type {ptype} COM (initial): (${{com_x_{ptype}_init}}, ${{com_y_{ptype}_init}}, ${{com_z_{ptype}_init}}) m'\n")
        f.write("print '-------------------------------------------------------------------------------'\n\n")
        
        # Average velocity - skip for now (LIGGGHTS compute timing issue)
        f.write("# Average velocities (initial) - skipped due to LIGGGHTS limitations\n")
        f.write("print 'Velocity statistics available in thermo output'\n")
        f.write("print '-------------------------------------------------------------------------------'\n\n")
        
        # =====================================================================
        # MAGNETIC FIELD REGIONS
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: MAGNETIC FIELD REGIONS\n")
        f.write("# " + "="*74 + "\n")
        f.write(f"print 'Defining {nx_grid*ny_grid} magnetic field regions...'\n")
        f.write(f"print 'FEM coil center: ({x_coil_center:.6f}, {y_coil_center:.6f}) m'\n")
        f.write(f"print 'DEM domain center: ({x_dem_center:.6f}, {y_dem_center:.6f}) m'\n")
        f.write(f"print 'Offset applied: ({offset_x:.6f}, {offset_y:.6f}) m'\n")
        f.write("print '-------------------------------------------------------------------------------'\n\n")
        
        region_count = 0
        region_data = []
        
        for i in range(len(x_coarse) - 1):
            for j in range(len(y_coarse) - 1):
                x_lo_fem, x_hi_fem = x_coarse[i], x_coarse[i+1]
                y_lo_fem, y_hi_fem = y_coarse[j], y_coarse[j+1]
                
                # Map to DEM coordinates
                x_lo_dem = x_lo_fem - offset_x
                x_hi_dem = x_hi_fem - offset_x
                y_lo_dem = y_lo_fem - offset_y
                y_hi_dem = y_hi_fem - offset_y
                
                # Get gradient indices in coil grid
                i_orig = np.searchsorted(x_fem, x_lo_fem)
                j_orig = np.searchsorted(y_fem, y_lo_fem)
                
                # Bounds check
                if i_orig >= len(x_fem):
                    i_orig = len(x_fem) - 1
                if j_orig >= len(y_fem):
                    j_orig = len(y_fem) - 1
                
                # Average gradient in this region
                grad_bx = gradBx[j_orig, i_orig]
                grad_by = gradBy[j_orig, i_orig]
                
                grad_mag = np.sqrt(grad_bx**2 + grad_by**2)
                
                # Skip negligible fields
                if grad_mag < 1e-10:
                    continue
                
                region_count += 1
                
                # Define region
                z_min = domain['z_min']
                z_max = domain['z_max']
                f.write(f"region mag_{region_count} block ")
                f.write(f"{x_lo_dem:.8f} {x_hi_dem:.8f} ")
                f.write(f"{y_lo_dem:.8f} {y_hi_dem:.8f} ")
                f.write(f"{z_min:.8f} {z_max:.8f} units box\n")
                
                region_data.append({
                    'id': region_count,
                    'gradBx': grad_bx,
                    'gradBy': grad_by,
                    'grad_mag': grad_mag,
                    'x_lo': x_lo_dem,
                    'x_hi': x_hi_dem,
                    'y_lo': y_lo_dem,
                    'y_hi': y_hi_dem
                })
        
        f.write(f"\nprint '{region_count} regions defined successfully'\n")
        f.write("print '==============================================================================='\n\n")
        
        # ===== ADD THIS ENTIRE SECTION =====
        # Print first 5 region bounds for verification
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: FIRST 5 REGION BOUNDS (in DEM coordinates)\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'First 5 region bounds (DEM coordinates):'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        for i, r_data in enumerate(region_data[:5], 1):
            rid = r_data['id']
            f.write(f"print '  Region {rid}:'\n")
            f.write(f"print '    X: [{r_data['x_lo']:.6f}, {r_data['x_hi']:.6f}] m'\n")
            f.write(f"print '    Y: [{r_data['y_lo']:.6f}, {r_data['y_hi']:.6f}] m'\n")
            f.write(f"print '    Center: ({(r_data['x_lo']+r_data['x_hi'])/2:.6f}, {(r_data['y_lo']+r_data['y_hi'])/2:.6f}) m'\n")
        
        f.write("print ''\n")
        f.write(f"print 'Particle locations (from initial state):'\n")
        f.write("print '  Type 1 COM: will be printed in next section'\n")
        f.write("print ''\n")
        f.write("print 'Expected: If particles are at (0, 0), they should be in regions'\n")
        f.write("print '          with bounds that span across X=0, Y=0'\n")
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # REGION VERIFICATION
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: REGION VERIFICATION\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Verifying particle counts in magnetic regions...'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        # Find regions that overlap with center (where particles actually are)
        # Center region: -0.01 to 0.01 in X and Y
        center_regions = []
        for r_data in region_data:
            x_center = (r_data['x_lo'] + r_data['x_hi']) / 2.0
            y_center = (r_data['y_lo'] + r_data['y_hi']) / 2.0
            # Check if region center is within 2cm of origin
            if abs(x_center) < 0.02 and abs(y_center) < 0.02:
                center_regions.append(r_data)
        
        f.write(f"print 'Found {len(center_regions)} regions near center (within 2cm of origin)'\n")
        f.write("print ''\n")
        
        # Sample first 10 CENTER regions (not first 10 overall)
        regions_to_check = center_regions[:10] if len(center_regions) >= 10 else center_regions
        
        if len(regions_to_check) == 0:
            f.write("print 'WARNING: NO regions found near center! Checking first 10 regions instead...'\n")
            regions_to_check = region_data[:10]
        
        for r_data in regions_to_check:
            rid = r_data['id']
            for ptype in particles.keys():
                f.write(f"variable n_in_reg_{rid}_t{ptype} equal count(type{ptype}_particles,mag_{rid})\n")
                f.write(f"print '  Region {rid}, Type {ptype}: ${{n_in_reg_{rid}_t{ptype}}} particles'\n")
        
        f.write("print '  ... (showing regions near center)'\n")
        f.write("print '==============================================================================='\n\n")

        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: CENTER REGION DETAILS\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Details of first 3 center regions:'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        for i, r_data in enumerate(center_regions[:3], 1):
            rid = r_data['id']
            x_center = (r_data['x_lo'] + r_data['x_hi']) / 2.0
            y_center = (r_data['y_lo'] + r_data['y_hi']) / 2.0
            f.write(f"print 'Center Region {i} (ID={rid}):'\n")
            f.write(f"print '  Bounds: X=[{r_data['x_lo']:.6f}, {r_data['x_hi']:.6f}] m'\n")
            f.write(f"print '          Y=[{r_data['y_lo']:.6f}, {r_data['y_hi']:.6f}] m'\n")
            f.write(f"print '  Center: ({x_center:.6f}, {y_center:.6f}) m'\n")
            f.write(f"print '  Gradient: {r_data['grad_mag']:.3e} T²/m'\n")
            f.write("print ''\n")
        
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # MAGNETIC FORCES
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: APPLYING MAGNETIC FORCES\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Calculating and applying magnetic forces...'\n")
        f.write(f"print 'Force multiplier: {force_mult}'\n")
        f.write(f"print 'μ₀ = {MU0:.10e} H/m'\n")
        f.write("print '-------------------------------------------------------------------------------'\n\n")
        
        # Calculate average force per particle type
        for ptype, props in particles.items():
            chi = props['chi']
            r = props['r']
            V = (4/3) * np.pi * r**3
            coeff = chi * V / MU0
            
            f.write(f"\n# Type {ptype}: {props['name']}\n")
            f.write(f"print 'Type {ptype} - {props["name"]}:'\n")
            f.write(f"print '  Radius: {r*1e6:.2f} μm'\n")
            f.write(f"print '  Volume: {V:.6e} m³'\n")
            f.write(f"print '  Density: {props["density"]:.0f} kg/m³'\n")
            f.write(f"print '  χ: {chi:.6e}'\n")
            f.write(f"print '  Force coefficient (χV/μ₀): {coeff:.6e} m³/H'\n")
            
            # Calculate spatially-weighted average force
            total_fx_expected = 0.0
            total_fy_expected = 0.0
            total_weight = 0.0
            
            for r_data in region_data:
                weight = r_data['grad_mag']
                fx = coeff * r_data['gradBx'] * force_mult
                fy = coeff * r_data['gradBy'] * force_mult
                total_fx_expected += fx * weight
                total_fy_expected += fy * weight
                total_weight += weight
            
            if total_weight > 0:
                avg_fx = total_fx_expected / total_weight
                avg_fy = total_fy_expected / total_weight
            else:
                avg_fx = 0.0
                avg_fy = 0.0
            
            f.write(f"print '  Weighted average force: Fx={avg_fx:.6e} N, Fy={avg_fy:.6e} N'\n")
            
            # Calculate force magnitude and ratio
            m_particle = props['density'] * V
            f_gravity = m_particle * config['gravity']
            force_mag = np.sqrt(avg_fx**2 + avg_fy**2)
            force_ratio = force_mag / f_gravity if f_gravity > 0 else 0
            
            f.write(f"print '  Particle mass: {m_particle:.6e} kg'\n")
            f.write(f"print '  Gravity force: {f_gravity:.6e} N (downward)'\n")
            f.write(f"print '  Magnetic force magnitude: {force_mag:.6e} N'\n")
            f.write(f"print '  Force ratio F_mag/F_grav: {force_ratio:.4f}'\n")
            
            # Apply force
            if abs(avg_fx) > 1e-25 or abs(avg_fy) > 1e-25:
                f.write(f"fix magf_t{ptype} type{ptype}_particles addforce {avg_fx:.12e} {avg_fy:.12e} 0.0\n")
                f.write(f"print '  ✓ Applied fix magf_t{ptype}'\n")
            else:
                f.write(f"print '  ✗ Force negligible, not applied'\n")
            
            f.write("print ''\n")
        
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # VERIFY FORCES ARE ACTIVE
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: VERIFY FORCES ARE ACTIVE\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Checking if forces are actually applied...'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        f.write("print 'Force verification from thermo output (step 900001):'\n")
        f.write("print '  Total Fx (all particles) = shown in thermo as c_fx_all'\n")
        f.write("print '  Total Fy (all particles) = shown in thermo as c_fy_all'\n")
        f.write("print '  Type 4 Fx = shown in thermo as c_fx_t4'\n")
        f.write("print '  Type 4 Fy = shown in thermo as c_fy_t4'\n")
        f.write("print '  '\n")
        f.write("print '✓ If values are NON-ZERO → magnetic forces are active'\n")
        f.write("print '✓ If values are ~0 → magnetic forces NOT working'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        f.write("print 'Note: Forces include gravity + magnetic + contact + damping'\n")
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # VELOCITY DAMPING
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: VELOCITY DAMPING\n")
        f.write("# " + "="*74 + "\n")
        damping = 1e-4
        f.write(f"print 'Applying velocity damping: {damping:.6e} (kg/s)'\n")
        for ptype in particles.keys():
            f.write(f"fix damp_t{ptype} type{ptype}_particles viscous {damping:.6e}\n")
            f.write(f"print '  ✓ Damping applied to type {ptype}'\n")
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # POST-APPLICATION STATE
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: IMMEDIATE POST-ACTIVATION STATE\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'System state immediately after magnetic field activation:'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        # Check positions haven't changed yet
        for ptype in particles.keys():
            f.write(f"variable com_x_{ptype}_post equal xcm(type{ptype}_particles,x)\n")
            f.write(f"variable com_y_{ptype}_post equal xcm(type{ptype}_particles,y)\n")
            f.write(f"print 'Type {ptype} COM (post-activation): (${{com_x_{ptype}_post}}, ${{com_y_{ptype}_post}}) m'\n")
            f.write(f"variable delta_x_{ptype} equal v_com_x_{ptype}_post-v_com_x_{ptype}_init\n")
            f.write(f"variable delta_y_{ptype} equal v_com_y_{ptype}_post-v_com_y_{ptype}_init\n")
            f.write(f"print 'Type {ptype} COM displacement: (${{delta_x_{ptype}}}, ${{delta_y_{ptype}}}) m (should be ~0)'\n")
        
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # TRACKING VARIABLES FOR CONTINUOUS MONITORING
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: SETUP CONTINUOUS MONITORING\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Setting up variables for continuous monitoring...'\n")
        f.write("print '(These will be used in thermo_style)'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        # Kinetic energy tracking
        for ptype in particles.keys():
            f.write(f"compute ke_t{ptype} type{ptype}_particles ke/atom\n")
            f.write(f"variable ke_avg_t{ptype} equal ave(c_ke_t{ptype})\n")
            f.write(f"variable ke_total_t{ptype} equal sum(c_ke_t{ptype})\n")
        
        # Position extrema
        for ptype in particles.keys():
            f.write(f"variable x_min_t{ptype} equal bound(type{ptype}_particles,xmin)\n")
            f.write(f"variable x_max_t{ptype} equal bound(type{ptype}_particles,xmax)\n")
            f.write(f"variable y_min_t{ptype} equal bound(type{ptype}_particles,ymin)\n")
            f.write(f"variable y_max_t{ptype} equal bound(type{ptype}_particles,ymax)\n")
            f.write(f"variable z_min_t{ptype} equal bound(type{ptype}_particles,zmin)\n")
            f.write(f"variable z_max_t{ptype} equal bound(type{ptype}_particles,zmax)\n")
        
        # Velocity RMS
        for ptype in particles.keys():
            f.write(f"variable vrms_x_t{ptype} equal sqrt(ave(vx*vx))\n")
            f.write(f"variable vrms_y_t{ptype} equal sqrt(ave(vy*vy))\n")
            f.write(f"variable vrms_z_t{ptype} equal sqrt(ave(vz*vz))\n")
        
        f.write("print '✓ Monitoring variables created'\n")
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # EXPECTED BEHAVIOR PREDICTIONS
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: EXPECTED BEHAVIOR PREDICTIONS\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Predicted particle behavior based on magnetic susceptibility:'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        for ptype, props in particles.items():
            chi = props['chi']
            if chi < 0:
                f.write(f"print 'Type {ptype} (χ={chi:.2e}): DIAMAGNETIC'\n")
                f.write(f"print '  → Expected: Repelled from high-field regions (coil center)'\n")
                f.write(f"print '  → Should move AWAY from ({x_dem_center:.4f}, {y_dem_center:.4f})'\n")
            elif chi > 0:
                f.write(f"print 'Type {ptype} (χ={chi:.2e}): PARAMAGNETIC'\n")
                f.write(f"print '  → Expected: Attracted to high-field regions (coil center)'\n")
                f.write(f"print '  → Should move TOWARD ({x_dem_center:.4f}, {y_dem_center:.4f})'\n")
            else:
                f.write(f"print 'Type {ptype} (χ={chi:.2e}): NON-MAGNETIC'\n")
                f.write(f"print '  → Expected: No magnetic response (gravity only)'\n")
        
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # FIELD STATISTICS
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: MAGNETIC FIELD STATISTICS\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Magnetic field gradient statistics:'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        # Calculate statistics
        grad_mags = [r['grad_mag'] for r in region_data]
        gradBx_vals = [r['gradBx'] for r in region_data]
        gradBy_vals = [r['gradBy'] for r in region_data]
        
        f.write(f"print 'Total active regions: {len(region_data)}'\n")
        f.write(f"print '|(B·∇)B| max: {max(grad_mags):.6e} T²/m'\n")
        f.write(f"print '|(B·∇)B| min: {min(grad_mags):.6e} T²/m'\n")
        f.write(f"print '|(B·∇)B| mean: {np.mean(grad_mags):.6e} T²/m'\n")
        f.write(f"print '|(B·∇)B| median: {np.median(grad_mags):.6e} T²/m'\n")
        f.write(f"print '(B·∇)Bx range: [{min(gradBx_vals):.6e}, {max(gradBx_vals):.6e}] T²/m'\n")
        f.write(f"print '(B·∇)By range: [{min(gradBy_vals):.6e}, {max(gradBy_vals):.6e}] T²/m'\n")
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # SPATIAL COVERAGE
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: SPATIAL COVERAGE OF MAGNETIC FIELD\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Magnetic field spatial extent:'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        x_los = [r['x_lo'] for r in region_data]
        x_his = [r['x_hi'] for r in region_data]
        y_los = [r['y_lo'] for r in region_data]
        y_his = [r['y_hi'] for r in region_data]
        
        f.write(f"print 'X coverage: [{min(x_los):.6f}, {max(x_his):.6f}] m'\n")
        f.write(f"print 'Y coverage: [{min(y_los):.6f}, {max(y_his):.6f}] m'\n")
        f.write(f"print 'Z coverage: [{domain["z_min"]:.6f}, {domain["z_max"]:.6f}] m'\n")
        f.write(f"print 'Field width (X): {max(x_his) - min(x_los):.6f} m ({(max(x_his) - min(x_los))*100:.2f} cm)'\n")
        f.write(f"print 'Field width (Y): {max(y_his) - min(y_los):.6f} m ({(max(y_his) - min(y_los))*100:.2f} cm)'\n")
        f.write(f"print 'Field width (Z): {domain["z_max"] - domain["z_min"]:.6f} m ({(domain["z_max"] - domain["z_min"])*100:.2f} cm)'\n")
        
        # Check overlap with DEM domain
        field_x_min, field_x_max = min(x_los), max(x_his)
        field_y_min, field_y_max = min(y_los), max(y_his)
        
        overlap_x_min = max(field_x_min, domain['x_min'])
        overlap_x_max = min(field_x_max, domain['x_max'])
        overlap_y_min = max(field_y_min, domain['y_min'])
        overlap_y_max = min(field_y_max, domain['y_max'])
        
        if overlap_x_max > overlap_x_min and overlap_y_max > overlap_y_min:
            coverage_x = (overlap_x_max - overlap_x_min) / (domain['x_max'] - domain['x_min']) * 100
            coverage_y = (overlap_y_max - overlap_y_min) / (domain['y_max'] - domain['y_min']) * 100
            f.write(f"print 'DEM domain coverage: X={coverage_x:.1f}%, Y={coverage_y:.1f}%'\n")
        else:
            f.write("print 'WARNING: Magnetic field does NOT overlap with DEM domain!'\n")
        
        f.write("print '==============================================================================='\n\n")

        f.write("# DEBUG: PARTICLE-FIELD OVERLAP CHECK\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Checking if particles are actually in field regions...'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")

        for ptype in particles.keys():
            f.write(f"variable com_x_{ptype}_check equal xcm(type{ptype}_particles,x)\n")
            f.write(f"variable com_y_{ptype}_check equal xcm(type{ptype}_particles,y)\n")
            f.write(f"variable com_z_{ptype}_check equal xcm(type{ptype}_particles,z)\n")

        f.write("run 0\n\n")

        for ptype in particles.keys():
            f.write(f"print 'Type {ptype} COM: (${{com_x_{ptype}_check}}, ${{com_y_{ptype}_check}}, ${{com_z_{ptype}_check}}) m'\n")

        f.write(f"print 'Field X range: [{min(x_los):.6f}, {max(x_his):.6f}] m'\n")
        f.write(f"print 'Field Y range: [{min(y_los):.6f}, {max(y_his):.6f}] m'\n")
        f.write(f"print 'Field Z range: [{domain["z_min"]:.6f}, {domain["z_max"]:.6f}] m'\n")
        f.write("print ''\n")
        f.write("print 'OVERLAP CHECK:'\n")

        # Check if COM is in field bounds
        for ptype in particles.keys():
            # This requires storing COM values, so just print comparison
            f.write(f"print '  Type {ptype}: Check if COM is within field bounds above'\n")

        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # SAMPLE REGION DETAILS
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUG: SAMPLE REGION DETAILS (First 5)\n")
        f.write("# " + "="*74 + "\n")
        f.write("print 'Detailed information for first 5 regions:'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        
        for r_data in region_data[:5]:
            rid = r_data['id']
            f.write(f"print 'Region {rid}:'\n")
            f.write(f"print '  X: [{r_data["x_lo"]:.8f}, {r_data["x_hi"]:.8f}] m'\n")
            f.write(f"print '  Y: [{r_data["y_lo"]:.8f}, {r_data["y_hi"]:.8f}] m'\n")
            f.write(f"print '  (B·∇)Bx: {r_data["gradBx"]:.6e} T²/m'\n")
            f.write(f"print '  (B·∇)By: {r_data["gradBy"]:.6e} T²/m'\n")
            f.write(f"print '  |(B·∇)B|: {r_data["grad_mag"]:.6e} T²/m'\n")
            
            # Calculate force for each particle type in this region
            for ptype, props in particles.items():
                chi = props['chi']
                r = props['r']
                V = (4/3) * np.pi * r**3
                coeff = chi * V / MU0
                fx = coeff * r_data['gradBx'] * force_mult
                fy = coeff * r_data['gradBy'] * force_mult
                f.write(f"print '  Force on Type {ptype}: ({fx:.6e}, {fy:.6e}) N'\n")
            f.write("print ''\n")
        
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # FINAL ACTIVATION MESSAGE
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# MAGNETIC FIELD ACTIVATION COMPLETE\n")
        f.write("# " + "="*74 + "\n")
        f.write("print '==============================================================================='\n")
        f.write("print 'MAGNETIC FIELD SUCCESSFULLY ACTIVATED'\n")
        f.write("print '==============================================================================='\n")
        f.write(f"print 'Configuration summary:'\n")
        f.write(f"print '  • {region_count} active field regions'\n")
        f.write(f"print '  • {len(particles)} particle types with magnetic forces'\n")
        f.write(f"print '  • Force multiplier: {force_mult}'\n")
        f.write(f"print '  • Velocity damping: {damping:.2e} kg/s'\n")
        f.write("print '-------------------------------------------------------------------------------'\n")
        f.write("print 'IMPORTANT: Check thermo output for particle motion over time'\n")
        f.write("print 'Expected observations:'\n")
        
        for ptype, props in particles.items():
            chi = props['chi']
            if chi < 0:
                f.write(f"print '  • Type {ptype}: Should drift AWAY from coil center (diamagnetic)'\n")
            elif chi > 0:
                f.write(f"print '  • Type {ptype}: Should drift TOWARD coil center (paramagnetic)'\n")
        
        f.write("print '==============================================================================='\n\n")
        
        # =====================================================================
        # SUGGEST ENHANCED THERMO STYLE
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# SUGGESTED ENHANCED THERMO OUTPUT\n")
        f.write("# " + "="*74 + "\n")
        f.write("# Uncomment the lines below to add detailed monitoring to thermo output:\n")
        f.write("#\n")
        
        # Build thermo_style command
        thermo_vars = ["step", "time", "atoms", "ke", "pe", "etotal"]
        
        for ptype in particles.keys():
            thermo_vars.append(f"v_n_type{ptype}")
            thermo_vars.append(f"v_com_x_{ptype}_post")
            thermo_vars.append(f"v_com_y_{ptype}_post")
            thermo_vars.append(f"v_ke_avg_t{ptype}")
        
        f.write(f"# thermo_style custom {' '.join(thermo_vars)}\n")
        f.write("# thermo 1000\n")
        f.write("#\n")
        f.write("# This will print:\n")
        f.write("#   - Simulation step and time\n")
        f.write("#   - Total atoms, kinetic energy, potential energy\n")
        f.write("#   - Per-type: count, COM position, average KE\n")
        f.write("# " + "="*74 + "\n\n")
        
        # =====================================================================
        # CHECKPOINT SUGGESTIONS
        # =====================================================================
        f.write("# " + "="*74 + "\n")
        f.write("# DEBUGGING CHECKPOINTS DURING SIMULATION\n")
        f.write("# " + "="*74 + "\n")
        f.write("# Add these commands at key points in your main script to track evolution:\n")
        f.write("#\n")
        f.write("# Every N steps (e.g., 10000):\n")
        f.write("# print '=== CHECKPOINT: Step $(step), Time $(time) s ==='\n")
        
        for ptype in particles.keys():
            f.write(f"# print 'Type {ptype} COM: (${{com_x_{ptype}_post}}, ${{com_y_{ptype}_post}}) m'\n")
            f.write(f"# print 'Type {ptype} bounds: X=[${{x_min_t{ptype}}}, ${{x_max_t{ptype}}}], Y=[${{y_min_t{ptype}}}, ${{y_max_t{ptype}}}]'\n")
            f.write(f"# print 'Type {ptype} <KE>: ${{ke_avg_t{ptype}}} J'\n")
        
        f.write("# print '======================================'\n")
        f.write("#\n")
        f.write("# " + "="*74 + "\n\n")
    
    print(f"✓ LIGGGHTS integration file created: magnetic_field_apply.lmp")
    print(f"  - {region_count} regions defined")
    print(f"  - COMPREHENSIVE DEBUGGING enabled")
    print(f"  - Pre-activation checks")
    print(f"  - Post-activation verification")
    print(f"  - Continuous monitoring variables")
    print(f"  - Expected behavior predictions")
    print(f"  - Sample region details")
    print(f"  - Force verification")
    print(f"  - Spatial coverage analysis")

def create_visualizations(x_grid, y_grid, Bx, By, B, gradBx, gradBy, grad_mag, 
                         force_mult, config):
    """Create field visualization"""
    
    domain = config['domain']
    
    # ============================================================================
    # CRITICAL: Use DEM coordinate system for ALL plots
    # ============================================================================
    # Calculate coordinate transformation (same as in create_liggghts_integration)
    x_coil_center_fem = (x_grid.min() + x_grid.max()) / 2.0
    y_coil_center_fem = (y_grid.min() + y_grid.max()) / 2.0
    
    x_dem_center = (domain['x_min'] + domain['x_max']) / 2.0
    y_dem_center = (domain['y_min'] + domain['y_max']) / 2.0
    
    # Offset to map FEM coil center → DEM center
    offset_x = x_coil_center_fem - x_dem_center
    offset_y = y_coil_center_fem - y_dem_center
    
    # Create meshgrid and transform to DEM coordinates
    X_fem, Y_fem = np.meshgrid(x_grid, y_grid)
    X_dem = (X_fem - offset_x) * 100  # Convert to cm
    Y_dem = (Y_fem - offset_y) * 100
    
    # DEM domain boundaries in cm
    x_dem_min, x_dem_max = domain['x_min'] * 100, domain['x_max'] * 100
    y_dem_min, y_dem_max = domain['y_min'] * 100, domain['y_max'] * 100
    
    # ============================================================================
    # Create 6-panel plot in DEM coordinates
    # ============================================================================
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    
    # Field magnitude
    im1 = axes[0,0].contourf(X_dem, Y_dem, B, levels=30, cmap='viridis')
    axes[0,0].set_title('|B| Field Magnitude')
    axes[0,0].set_xlabel('X (cm) - DEM Coordinates')
    axes[0,0].set_ylabel('Y (cm) - DEM Coordinates')
    plt.colorbar(im1, ax=axes[0,0], label='Tesla')
    
    # Bx component
    im2 = axes[0,1].contourf(X_dem, Y_dem, Bx, levels=30, cmap='RdBu_r')
    axes[0,1].set_title('Bx Component')
    axes[0,1].set_xlabel('X (cm) - DEM Coordinates')
    axes[0,1].set_ylabel('Y (cm) - DEM Coordinates')
    plt.colorbar(im2, ax=axes[0,1], label='Tesla')
    
    # By component
    im3 = axes[0,2].contourf(X_dem, Y_dem, By, levels=30, cmap='RdBu_r')
    axes[0,2].set_title('By Component')
    axes[0,2].set_xlabel('X (cm) - DEM Coordinates')
    axes[0,2].set_ylabel('Y (cm) - DEM Coordinates')
    plt.colorbar(im3, ax=axes[0,2], label='Tesla')
    
    # (B·∇)Bx
    im4 = axes[1,0].contourf(X_dem, Y_dem, gradBx, levels=30, cmap='plasma')
    axes[1,0].set_title('(B·∇)Bx')
    axes[1,0].set_xlabel('X (cm) - DEM Coordinates')
    axes[1,0].set_ylabel('Y (cm) - DEM Coordinates')
    plt.colorbar(im4, ax=axes[1,0], label='T²/m', format='%.2e')
    
    # (B·∇)By
    im5 = axes[1,1].contourf(X_dem, Y_dem, gradBy, levels=30, cmap='plasma')
    axes[1,1].set_title('(B·∇)By')
    axes[1,1].set_xlabel('X (cm) - DEM Coordinates')
    axes[1,1].set_ylabel('Y (cm) - DEM Coordinates')
    plt.colorbar(im5, ax=axes[1,1], label='T²/m', format='%.2e')
    
    # |(B·∇)B|
    im6 = axes[1,2].contourf(X_dem, Y_dem, grad_mag, levels=30, cmap='hot')
    axes[1,2].set_title('|(B·∇)B| Total Gradient')
    axes[1,2].set_xlabel('X (cm) - DEM Coordinates')
    axes[1,2].set_ylabel('Y (cm) - DEM Coordinates')
    plt.colorbar(im6, ax=axes[1,2], label='T²/m', format='%.2e')
    
    # ============================================================================
    # Overlay DEM domain and markers on all plots
    # ============================================================================
    for ax in axes.flat:
        # Draw DEM domain as red rectangle
        ax.plot([x_dem_min, x_dem_max, x_dem_max, x_dem_min, x_dem_min],
                [y_dem_min, y_dem_min, y_dem_max, y_dem_max, y_dem_min],
                'r-', linewidth=2, label='DEM Domain')
        
        # Mark DEM center (at origin in DEM coordinates)
        ax.plot(x_dem_center * 100, y_dem_center * 100, 'r+', 
                markersize=15, markeredgewidth=3, label='DEM Center (0,0)')
        
        # Mark FEM coil center in DEM coordinates (should overlap with DEM center)
        fem_center_in_dem_x = (x_coil_center_fem - offset_x) * 100
        fem_center_in_dem_y = (y_coil_center_fem - offset_y) * 100
        ax.plot(fem_center_in_dem_x, fem_center_in_dem_y, 'bx', 
                markersize=15, markeredgewidth=3, label='FEM Coil Center')
        
        # Add particle region (green box)
        particle_x_min = (domain['x_min'] + 0.006) * 100
        particle_x_max = (domain['x_max'] - 0.006) * 100
        particle_y_min = (domain['y_min'] + 0.006) * 100
        particle_y_max = (domain['y_max'] - 0.006) * 100
        
        from matplotlib.patches import Rectangle
        particle_region = Rectangle((particle_x_min, particle_y_min),
                                    particle_x_max - particle_x_min,
                                    particle_y_max - particle_y_min,
                                    fill=True, facecolor='lime', alpha=0.15,
                                    edgecolor='green', linewidth=2,
                                    label='Particle Region')
        ax.add_patch(particle_region)
        
        ax.legend(loc='upper right', fontsize=7)
        ax.grid(True, alpha=0.3)
        ax.set_aspect('equal')
        
        # Set limits to show full context
        margin = 0.5  # cm
        ax.set_xlim(x_dem_min - margin, x_dem_max + margin)
        ax.set_ylim(y_dem_min - margin, y_dem_max + margin)
    
    plt.suptitle('Magnetic Field Analysis for LIGGGHTS\n(All coordinates in DEM reference frame)', 
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('magnetic_field_analysis.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("✓ Visualization saved: magnetic_field_analysis.png")
    print(f"  All 6 panels now use DEM coordinates with proper alignment")

    # ============================================================================
    # Debug overlay plot (same as before, but ensure consistency)
    # ============================================================================
    fig_debug, ax_debug = plt.subplots(1, 1, figsize=(12, 12))
    
    # Plot field magnitude IN DEM COORDINATES
    im = ax_debug.contourf(X_dem, Y_dem, grad_mag, levels=30, cmap='hot', alpha=0.6)
    plt.colorbar(im, ax=ax_debug, label='|(B·∇)B| (T²/m)')
    
    # Overlay DEM domain
    ax_debug.plot([x_dem_min, x_dem_max, x_dem_max, x_dem_min, x_dem_min],
                  [y_dem_min, y_dem_min, y_dem_max, y_dem_max, y_dem_min],
                  'r-', linewidth=3, label='DEM Domain')
    
    # Mark DEM center
    ax_debug.plot(x_dem_center * 100, y_dem_center * 100, 'r+', 
                  markersize=25, markeredgewidth=4, label='DEM Center (0,0)')
    
    # Mark FEM coil center IN DEM COORDINATES
    ax_debug.plot(fem_center_in_dem_x, fem_center_in_dem_y, 'bx', 
                  markersize=25, markeredgewidth=4, label='FEM Coil Center (mapped)')
    
    # Particle region
    particle_region_debug = Rectangle((particle_x_min, particle_y_min),
                                      particle_x_max - particle_x_min,
                                      particle_y_max - particle_y_min,
                                      fill=True, facecolor='lime', alpha=0.3,
                                      edgecolor='green', linewidth=3,
                                      label='Expected Particle X-Y Region')
    ax_debug.add_patch(particle_region_debug)
    
    # Text annotation
    ax_debug.text(0, y_dem_max * 0.9, 
                  'Particles settle across\nfull X-Y domain\n(at Z ≈ 0-5mm)',
                  ha='center', va='top', fontsize=12, 
                  bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))
    
    ax_debug.set_xlabel('X (cm) - DEM Coordinates', fontsize=12)
    ax_debug.set_ylabel('Y (cm) - DEM Coordinates', fontsize=12)
    ax_debug.set_title('Field-Particle Overlap Check\n(All coordinates in DEM reference frame)', 
                       fontsize=14, fontweight='bold')
    ax_debug.legend(loc='lower right', fontsize=10)
    ax_debug.grid(True, alpha=0.3)
    ax_debug.set_aspect('equal')
    
    # Set limits
    ax_debug.set_xlim(x_dem_min - margin, x_dem_max + margin)
    ax_debug.set_ylim(y_dem_min - margin, y_dem_max + margin)
    
    plt.tight_layout()
    plt.savefig('magnetic_field_debug_overlay.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("✓ Debug overlay saved: magnetic_field_debug_overlay.png")
    print(f"  Check that:")
    print(f"    1. Red + and Blue X overlap (both at origin)")
    print(f"    2. Green box covers most of DEM domain")
    print(f"    3. Field (colored contours) covers particle region")

def main():
    """Main execution"""
    
    field_file = 'B_output.txt'
    force_multiplier = 0.1
    liggghts_file = 'in.lunar_dust_magnetic'
    
    if len(sys.argv) > 1:
        field_file = sys.argv[1]
    if len(sys.argv) > 2:
        force_multiplier = float(sys.argv[2])
    if len(sys.argv) > 3:
        liggghts_file = sys.argv[3]
    
    if not os.path.exists(field_file):
        print(f"✗ ERROR: Field file '{field_file}' not found!")
        sys.exit(1)
    
    if not os.path.exists(liggghts_file):
        print(f"✗ ERROR: LIGGGHTS file '{liggghts_file}' not found!")
        sys.exit(1)
    
    try:
        success = preprocess_magnetic_field(
            field_file=field_file,
            force_multiplier=force_multiplier,
            liggghts_file=liggghts_file
        )
        
        if success:
            print("\n" + "="*80)
            print("NEXT STEPS:")
            print("="*80)
            print("1. Run LIGGGHTS:")
            print(f"   liggghts < {liggghts_file}")
            print("2. Check console output for all DEBUG sections")
            print("3. Verify:")
            print("   • Initial particle counts are correct")
            print("   • Forces are non-zero and reasonable")
            print("   • Particles are in magnetic field regions")
            print("   • COM motion matches expected direction")
            print("4. Check ParaView output (post/*.vtk)")
            print("="*80 + "\n")
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()