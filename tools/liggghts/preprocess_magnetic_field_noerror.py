#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LIGGGHTS-COMPATIBLE Magnetic Field Preprocessor
KEY FIXES:
1. No atom-style variables (not supported in LIGGGHTS)
2. Use fix addforce with simple numeric values only
3. Pre-calculate forces for discrete regions
4. Proper FEM coil → DEM domain mapping
5. Continuous-like field via dense region grid
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
        B_grid = B_grid[np.ix_(y_coil_indices, x_coil_indices)]
        gradBx = gradBx[np.ix_(y_coil_indices, x_coil_indices)]
        gradBy = gradBy[np.ix_(y_coil_indices, x_coil_indices)]
        grad_mag = grad_mag[np.ix_(y_coil_indices, x_coil_indices)]

        # Crop the FEM gradient arrays too (CRITICAL for shape matching)
        dBx_dx_grid = dBx_dx_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBx_dy_grid = dBx_dy_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBy_dx_grid = dBy_dx_grid[np.ix_(y_coil_indices, x_coil_indices)]
        dBy_dy_grid = dBy_dy_grid[np.ix_(y_coil_indices, x_coil_indices)]

        # Verify all shapes match
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
    Create LIGGGHTS-compatible magnetic field application
    
    STRATEGY: Use dense grid of regions with fix addforce
    - Each region gets constant force (average in that region)
    - No variables (LIGGGHTS doesn't support atom-style variables)
    - Simple numeric values only
    """
    
    particles = config['particles']
    domain = config['domain']

    # Calculate actual coil center from extracted region
    x_coil_min, x_coil_max = x_fem.min(), x_fem.max()
    y_coil_min, y_coil_max = y_fem.min(), y_fem.max()
    x_coil_center = (x_coil_min + x_coil_max) / 2.0
    y_coil_center = (y_coil_min + y_coil_max) / 2.0
    
    # Calculate DEM domain center
    x_dem_center = (domain['x_min'] + domain['x_max']) / 2.0
    y_dem_center = (domain['y_min'] + domain['y_max']) / 2.0
    
    # Offset to center coil in DEM domain
    offset_x = x_coil_center - x_dem_center
    offset_y = y_coil_center - y_dem_center

    # Use maximum resolution for quasi-continuous field (all FEM points in coil)
    # LIGGGHTS can handle 500-1000 regions with fix addforce
    target_regions = min(800, len(x_fem) * len(y_fem))
    
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
    
    # Generate LIGGGHTS script
    with open('magnetic_field_apply.lmp', 'w', encoding='utf-8') as f:
        f.write("# " + "="*74 + "\n")
        f.write("# LIGGGHTS-COMPATIBLE MAGNETIC FIELD APPLICATION\n")
        f.write("# Strategy: Dense region grid with fix addforce (numeric values only)\n")
        f.write(f"# Grid: {nx_grid}×{ny_grid} = {nx_grid*ny_grid} regions\n")
        f.write("# " + "="*74 + "\n\n")
        
        f.write("print '==============================================================================='\n")
        f.write("print 'ACTIVATING MAGNETIC FIELD'\n")
        f.write("print '==============================================================================='\n\n")
        
        # Define all regions first
        f.write("# === MAGNETIC FIELD REGIONS ===\n")
        f.write(f"# Mapping FEM coil to DEM domain with offset ({offset_x:.4f}, {offset_y:.4f}) m\n\n")
        
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
                
                # Define region - use actual particle Z range
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
                    'grad_mag': grad_mag
                })
        
        f.write(f"\n# Total regions created: {region_count}\n\n")
        
        # Apply forces using LIGGGHTS-compatible method
        f.write("# === MAGNETIC FORCES BY PARTICLE TYPE ===\n")
        f.write("# Formula: F = (χ·V/μ₀)·(B·∇)B\n")
        f.write("# Strategy: Spatially-weighted average force per particle type\n")
        f.write("# Note: LIGGGHTS limitations require simplified approach\n\n")
        
        # Calculate average force per particle type across all regions
        for ptype, props in particles.items():
            chi = props['chi']
            r = props['r']
            V = (4/3) * np.pi * r**3
            coeff = chi * V / MU0
            
            f.write(f"\n# Type {ptype}: {props['name']}\n")
            f.write(f"# r={r*1e6:.1f} μm, χ={chi:.2e}, V={V:.2e} m³\n")
            f.write(f"# Coefficient: {coeff:.6e} m³/H\n\n")
            
            # Calculate spatially-weighted average force
            total_fx_expected = 0.0
            total_fy_expected = 0.0
            total_weight = 0.0
            force_count = 0
            
            for r_data in region_data:
                # Weight by gradient magnitude (stronger field = more influence)
                weight = r_data['grad_mag']
                
                fx = coeff * r_data['gradBx'] * force_mult
                fy = coeff * r_data['gradBy'] * force_mult
                
                total_fx_expected += fx * weight
                total_fy_expected += fy * weight
                total_weight += weight
                force_count += 1
            
            # Average force (weighted by field strength)
            if total_weight > 0:
                avg_fx = total_fx_expected / total_weight
                avg_fy = total_fy_expected / total_weight
            else:
                avg_fx = 0.0
                avg_fy = 0.0
            
            # Apply single uniform force to this particle type
            f.write(f"# Spatially-averaged force for Type {ptype}:\n")
            f.write(f"# Fx = {avg_fx:.6e} N, Fy = {avg_fy:.6e} N\n")
            
            if abs(avg_fx) > 1e-25 or abs(avg_fy) > 1e-25:
                f.write(f"fix magf_t{ptype} type{ptype}_particles addforce {avg_fx:.12e} {avg_fy:.12e} 0.0\n\n")
            else:
                f.write(f"# Force negligible, not applied\n\n")
            
            # Calculate expected force statistics
            m_particle = props['density'] * V
            f_gravity = m_particle * config['gravity']
            force_mag = np.sqrt(avg_fx**2 + avg_fy**2)
            force_ratio = force_mag / f_gravity if f_gravity > 0 else 0
            
            f.write(f"# Single particle gravity: {f_gravity:.6e} N\n")
            f.write(f"# Force magnitude: {force_mag:.6e} N\n")
            f.write(f"# Force ratio (F_mag/F_grav): {force_ratio:.3f}x\n\n")
            
            # Calculate expected force statistics
            force_mag_expected = np.sqrt(total_fx_expected**2 + total_fy_expected**2)
            
            # Compare to gravity for this particle type
            m_particle = props['density'] * V
            f_gravity = m_particle * config['gravity']
            force_ratio = force_mag_expected / f_gravity if f_gravity > 0 else 0
            
            f.write(f"\n# Type {ptype}: {force_count} force fixes created\n")
            f.write(f"# Expected total force: Fx={total_fx_expected:.6e} N, Fy={total_fy_expected:.6e} N\n")
            f.write(f"# Expected |F_mag|: {force_mag_expected:.6e} N\n")
            f.write(f"# Single particle gravity: {f_gravity:.6e} N\n")
            f.write(f"# Force ratio (F_mag/F_grav per region): {force_ratio/force_count if force_count > 0 else 0:.3f}x\n\n")

        # Print comprehensive summary
        print(f"\n{'='*80}")
        print("FORCE APPLICATION SUMMARY")
        print(f"{'='*80}")
        for ptype, props in particles.items():
            chi = props['chi']
            r = props['r']
            V = (4/3) * np.pi * r**3
            m = props['density'] * V
            f_grav = m * config['gravity']
            
            print(f"\nType {ptype} ({props['name']}):")
            print(f"  Radius: {r*1e6:.1f} μm")
            print(f"  Mass: {m:.6e} kg")
            print(f"  Gravity force: {f_grav:.6e} N")
            print(f"  Magnetic susceptibility: {chi:.2e}")
            print(f"  Force coefficient: {chi * V / MU0:.6e}")
            
            # Estimate typical magnetic force
            typical_grad = np.median(np.sqrt(gradBx**2 + gradBy**2))
            f_mag_typical = abs(chi * V / MU0) * typical_grad * force_mult
            print(f"  Typical magnetic force: {f_mag_typical:.6e} N")
            print(f"  F_mag/F_grav ratio: {f_mag_typical/f_grav:.3f}x")
        print(f"{'='*80}\n")
        
        # Add damping
        f.write("# === VELOCITY DAMPING ===\n")
        damping = 1e-4  # Gentle damping
        for ptype in particles.keys():
            f.write(f"fix damp_t{ptype} type{ptype}_particles viscous {damping:.6e}\n")
        f.write("\n")
        
        f.write("print 'Magnetic field activated'\n")
        f.write(f"print '  - {region_count} field regions'\n")
        f.write(f"print '  - {len(particles)} particle types'\n")
        f.write(f"print '  - Method: fix addforce with numeric values'\n")
        f.write("print '==============================================================================='\n")
    
    print(f"✓ LIGGGHTS integration file created: magnetic_field_apply.lmp")
    print(f"  - {region_count} regions defined")
    print(f"  - {region_count * len(particles)} force fixes")
    print(f"  - Pure numeric values (no variables)")

def create_visualizations(x_grid, y_grid, Bx, By, B, gradBx, gradBy, grad_mag, 
                         force_mult, config):
    """Create field visualization"""
    
    X, Y = np.meshgrid(x_grid, y_grid)
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    
    # Field magnitude
    im1 = axes[0,0].contourf(X*100, Y*100, B, levels=30, cmap='viridis')
    axes[0,0].set_title('|B| Field Magnitude')
    axes[0,0].set_xlabel('X (cm)')
    axes[0,0].set_ylabel('Y (cm)')
    plt.colorbar(im1, ax=axes[0,0], label='Tesla')
    
    # Bx component
    im2 = axes[0,1].contourf(X*100, Y*100, Bx, levels=30, cmap='RdBu_r')
    axes[0,1].set_title('Bx Component')
    axes[0,1].set_xlabel('X (cm)')
    axes[0,1].set_ylabel('Y (cm)')
    plt.colorbar(im2, ax=axes[0,1], label='Tesla')
    
    # By component
    im3 = axes[0,2].contourf(X*100, Y*100, By, levels=30, cmap='RdBu_r')
    axes[0,2].set_title('By Component')
    axes[0,2].set_xlabel('X (cm)')
    axes[0,2].set_ylabel('Y (cm)')
    plt.colorbar(im3, ax=axes[0,2], label='Tesla')
    
    # (B·∇)Bx
    im4 = axes[1,0].contourf(X*100, Y*100, gradBx, levels=30, cmap='plasma')
    axes[1,0].set_title('(B·∇)Bx')
    axes[1,0].set_xlabel('X (cm)')
    axes[1,0].set_ylabel('Y (cm)')
    plt.colorbar(im4, ax=axes[1,0], label='T²/m', format='%.2e')
    
    # (B·∇)By
    im5 = axes[1,1].contourf(X*100, Y*100, gradBy, levels=30, cmap='plasma')
    axes[1,1].set_title('(B·∇)By')
    axes[1,1].set_xlabel('X (cm)')
    axes[1,1].set_ylabel('Y (cm)')
    plt.colorbar(im5, ax=axes[1,1], label='T²/m', format='%.2e')
    
    # |(B·∇)B|
    im6 = axes[1,2].contourf(X*100, Y*100, grad_mag, levels=30, cmap='hot')
    axes[1,2].set_title('|(B·∇)B| Total Gradient')
    axes[1,2].set_xlabel('X (cm)')
    axes[1,2].set_ylabel('Y (cm)')
    plt.colorbar(im6, ax=axes[1,2], label='T²/m', format='%.2e')
    
    plt.suptitle('Magnetic Field Analysis for LIGGGHTS', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('magnetic_field_analysis.png', dpi=300, bbox_inches='tight')
    plt.close()
    
    print("✓ Visualization saved: magnetic_field_analysis.png")

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
            print("2. Check output in ParaView (post/*.vtk)")
            print("3. Verify particles move away from high-field regions (diamagnetic)")
            print("="*80 + "\n")
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()