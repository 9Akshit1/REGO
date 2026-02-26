#!/usr/bin/env python3
"""Debug test for output issue"""

import sys

# Test timestep calculation
dt = 1e-5
output_interval = 0.05
duration = 0.5

output_interval_steps = int(round(output_interval / dt))
print(f"dt: {dt}")
print(f"output_interval: {output_interval}")
print(f"output_interval_steps: {output_interval_steps}")
print(f"Expected outputs per 0.5s: {int(duration / output_interval)}")
print()

# Simulate the loop
t = 0.0
timestep_idx = 0
next_output_idx = output_interval_steps
outputs = []

while t < duration - dt * 0.5:
    if timestep_idx >= next_output_idx:
        outputs.append((timestep_idx, t))
        next_output_idx += output_interval_steps
    
    t += dt
    timestep_idx += 1

print(f"Total timesteps: {timestep_idx}")
print(f"Total outputs: {len(outputs)}")
print("\nOutput timesteps:")
for idx, (step, time) in enumerate(outputs):
    print(f"  Output {idx}: timestep {step}, time {time:.6f}s")
