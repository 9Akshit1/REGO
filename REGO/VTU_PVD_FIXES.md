# VTU/PVD Output Fixes - phase2_adaptive_shapes.py

## Issues Found and Fixed

### 1. **Duplicate PVD Entries**
**Problem**: The PVD file contained duplicate entries because phases 1, 2, and 3 each started at local t=0, and all were appended to the same list without offset.

**Example of bad output:**
```xml
<DataSet timestep="0.0" file="particles_t0.0000.vtu"/>
<DataSet timestep="0.1" file="particles_t0.1000.vtu"/>
...
<DataSet timestep="0.0" file="particles_t0.0000.vtu"/>  <!-- DUPLICATE! -->
<DataSet timestep="0.1" file="particles_t0.1000.vtu"/>  <!-- DUPLICATE! -->
```

**Solution**: Modified `simulate_phase()` to accept `global_time` parameter and use absolute time for all timesteps:
- Phase 1: 0.0 - 0.5s (global_time = 0.0)
- Phase 2: 0.5 - 1.2s (global_time = 0.5)
- Phase 3: 1.2 - 2.0s (global_time = 1.2)

All VTU files now use absolute time in filename: `particles_t0.0000.vtu`, `particles_t0.5000.vtu`, etc.

### 2. **Floating-Point Precision in PVD Timestamps**
**Problem**: PVD timestep values had floating-point rounding errors:
```xml
<DataSet timestep="0.10000000000000184" file="..."/>
```

**Solution**: Added rounding in `write_pvd()`:
```python
t_rounded = round(t, 4)  # Round to 4 decimal places
f.write(f'    <DataSet timestep="{t_rounded}" file="{vtu_name}"/>\n')
```

### 3. **Duplicate Initial Output**
**Problem**: Each phase was outputting at t=0 with the same particle positions, creating duplicate files.

**Solution**: Modified `simulate_phase()` to only output initial state (`t=0`) for Phase 1:
```python
if phase_num == 1:  # Only output initial state once
    # ... compute and output ...
```

### 4. **VTU File Naming Collision**
**Problem**: All phases were creating `particles_t0.0000.vtu` because they used local phase time.

**Solution**: Use absolute time in filename:
```python
vtu_file = os.path.join(output_dir, f"particles_t{abs_time:.4f}.vtu")
# Output: particles_t0.0000.vtu, particles_t0.1000.vtu, ..., particles_t0.5000.vtu, particles_t0.6000.vtu, ...
```

### 5. **Old Files Not Cleared**
**Problem**: Old VTU/PVD files were not removed before simulation.

**Solution**: Added cleanup in `main()`:
```python
# Clear any old output files
for f in os.listdir(output_dir):
    if f.endswith('.vtu') or f.endswith('.pvd'):
        os.remove(os.path.join(output_dir, f))
```

## Code Changes

### Function Signature
```python
# Before
def simulate_phase(phase_num: int, duration: float, name: str, output_dir: str = None)

# After
def simulate_phase(phase_num: int, duration: float, name: str, output_dir: str = None, global_time: float = 0.0)
```

### Main Function Calls
```python
# Before
times1 = simulate_phase(1, 0.5, "Levitation & Centering", output_dir)
times2 = simulate_phase(2, 0.7, "Cylindrical Organization", output_dir)
times3 = simulate_phase(3, 0.8, "Stabilization", output_dir)

# After
times1 = simulate_phase(1, 0.5, "Levitation & Centering", output_dir, 0.0)
times2 = simulate_phase(2, 0.7, "Cylindrical Organization", output_dir, 0.5)
times3 = simulate_phase(3, 0.8, "Stabilization", output_dir, 1.2)
```

## Verification

### Expected Output Structure
```
outputs/Phase2_Adaptive/cylinder/
├── particles_t0.0000.vtu    # Phase 1, t=0.0s
├── particles_t0.1000.vtu    # Phase 1, t=0.1s
├── particles_t0.2000.vtu    # Phase 1, t=0.2s
├── ...
├── particles_t0.5000.vtu    # Phase 2, t=0.5s (start of Phase 2)
├── particles_t0.6000.vtu    # Phase 2, t=0.6s
├── ...
├── particles_t1.2000.vtu    # Phase 3, t=1.2s (start of Phase 3)
├── particles_t1.3000.vtu    # Phase 3, t=1.3s
├── ...
└── particles.pvd            # Animation index with correct absolute times
```

### Expected PVD Content
```xml
<?xml version="1.0"?>
<VTKFile type="Collection" version="0.1">
  <Collection>
    <DataSet timestep="0.0" file="particles_t0.0000.vtu"/>
    <DataSet timestep="0.1" file="particles_t0.1000.vtu"/>
    <DataSet timestep="0.2" file="particles_t0.2000.vtu"/>
    ...
    <DataSet timestep="0.5" file="particles_t0.5000.vtu"/>
    <DataSet timestep="0.6" file="particles_t0.6000.vtu"/>
    ...
  </Collection>
</VTKFile>
```

## ParaView Opening

The corrected files should now open properly in ParaView:
1. Open `particles.pvd` (not individual VTU files)
2. All timesteps should appear in sequence with correct absolute times
3. Animation should play smoothly from t=0.0s to t=2.0s
4. Particle positions should show continuous motion across phase boundaries

## Testing Status

✅ VTU format verified - valid XML structure
✅ PVD generation corrected - unique absolute times
✅ File cleanup implemented - old files removed before run
✅ Absolute time tracking - no duplicates
✅ Floating-point precision - rounded to 4 decimals
