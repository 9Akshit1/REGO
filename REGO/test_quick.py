#!/usr/bin/env python3
"""Quick test with reduced simulation time"""

# Import just the parts we need
import sys
sys.path.insert(0, '.')

# Modify the config BEFORE importing the main module
import phase2_adaptive_shapes as phase2

# Reduce the simulation time for quick testing
phase2.config.dt = 1e-4  # 10x larger timestep
phase2.config.output_interval = 0.01  # 4 outputs per 0.04s phase instead of 20

# Run just Phase 1 with reduced duration
print("Quick Test: Running short Phase 1 (0.04s total)")
print("=" * 70)

phase2.config.set_target(phase2.Cylinder(
    center=[5.0e-3, 5.0e-3, 5.0e-3],
    radius=2.5e-3,
    height=4.0e-3
))

phase2.init_particles()

import os
output_dir = 'outputs/Phase2_Adaptive/test_quick'
os.makedirs(output_dir, exist_ok=True)

times = phase2.simulate_phase(1, 0.04, "Quick Test", output_dir)
print(f"\nTest complete! Generated {len(times)} outputs")
