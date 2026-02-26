# REGO: Magnetic-Field–Driven Shaping and Consolidation of Planetary Regolith
## Pure Python Implementation with GeoTaichi

**This is a complete rewrite of your REGO project using GeoTaichi - a professional, high-performance DEM framework in pure Python.**

---

## 🎯 Why GeoTaichi?

After struggling with MercuryDPM's limitations (external forces not working, C++ compilation issues, printf bugs), we've switched to **GeoTaichi** - and it's PERFECT for your project:

✅ **Pure Python** - Easy to understand and modify  
✅ **Fast as C++** - Taichi JIT compilation (CPU/GPU support)  
✅ **Professional DEM** - Used in peer-reviewed geophysics research  
✅ **Easy Custom Forces** - Adding magnetic forces is straightforward  
✅ **Built-in Visualization** - No ParaView needed (but compatible)  
✅ **Well-Documented** - Active community and examples  

---

## 📚 Key Resources & References

### GeoTaichi Main Resources
- **GitHub Repository**: https://github.com/Yihao-Shi/GeoTaichi
- **PyPI Package**: https://pypi.org/project/geotaichi/
- **Published Paper**: [Computer Physics Communications (2024)](https://www.sciencedirect.com/science/article/abs/pii/S0010465524001425)
  - *GeoTaichi: A Taichi-powered high-performance numerical simulator for multiscale geophysical problems*
  - Authors: Y.H. Shi, N. Guo, Z.X. Yang
  - DOI: 10.1016/j.cpc.2024.109219

### Relevant Example Projects
1. **Granular Packing**: https://github.com/Yihao-Shi/GeoTaichi/tree/main/example/dem/GranularPackings
2. **Triaxial Test**: https://github.com/Yihao-Shi/GeoTaichi/tree/main/example/dem/TriaxialTest
3. **Debris Flow**: https://github.com/Yihao-Shi/GeoTaichi/tree/main/example/dem/DebrisFlow
4. **Rotating Drum**: https://github.com/Yihao-Shi/GeoTaichi/tree/main/example/dem/RotatingDrums

### Taichi Framework
- **Taichi Lang**: https://github.com/taichi-dev/taichi
- **Documentation**: https://docs.taichi-lang.org/

---

## ⚡ Installation

### Option 1: Quick Install (Recommended)
```bash
# Create virtual environment
python3 -m venv rego_env
source rego_env/bin/activate  # On Windows: rego_env\Scripts\activate

# Install dependencies
pip install numpy scipy matplotlib taichi geotaichi pyvista

# Clone this REGO project
git clone <your-repo>
cd REGO
```

### Option 2: From GeoTaichi Source
```bash
# Clone GeoTaichi
git clone https://github.com/Yihao-Shi/GeoTaichi
cd GeoTaichi

# Install dependencies
bash requirements.sh

# Set environment variable
export PYTHONPATH="$PYTHONPATH:$(pwd)"
```

---

## 🚀 Quick Start

### Phase 0: Baseline DEM Validation
```bash
python phase0_baseline.py
```
This creates a basic 3D DEM simulation with:
- 100-500 spherical particles
- Realistic regolith physics
- Gravity, friction, energy dissipation
- Outputs: VTU files for visualization

### Phase 1: Magnetic Manipulation
```bash
python phase1_magnetic.py
```
Demonstrates magnetic field control:
- Dipole magnetic field model
- Paramagnetic particle response
- Energy tracking
- Particle levitation/clustering

### Visualization
```bash
# Built-in interactive viewer
python visualize.py

# Or use ParaView
paraview Phase1_*.vtu
```

---

## 📊 What This Implementation Provides

### Complete REGO Simulation Stack
1. **Particle Physics** (Phase 0)
   - Hertz-Mindlin contact model
   - Realistic friction and damping
   - Energy conservation tracking
   - Proper regolith properties

2. **Magnetic Forces** (Phase 1)
   - Dipole field model: B ∝ 1/r³
   - Force: F = (χ·V/μ₀) · B · ∇B
   - Per-particle force application
   - Tunable magnetic susceptibility

3. **Visualization & Analysis**
   - Real-time 3D rendering
   - Energy plots
   - Force vector overlays
   - Trajectory tracking

4. **Parameter Studies**
   - Sweepable χ (magnetic susceptibility)
   - Adjustable B₀ (field strength)
   - Different field geometries
   - Particle size distributions

---

## 🔬 Physics Implementation

### Magnetic Force Model
```
Dipole Field:     B(r) = B₀ · (R₀/r)³
Field Gradient:   dB/dr = -3B/r
Magnetic Force:   F = (χ · V / μ₀) · B · |dB/dr|
Direction:        Towards higher field (source)
```

### Material Properties
| Material | χ | Notes |
|----------|---|-------|
| Pure lunar regolith | 10⁻⁶ | Negligible magnetic response |
| 10% iron oxide | 10⁻⁴ | Weak but demonstrable |
| 50% iron oxide | 10⁻³ | Moderate control |
| Ferrite particles | 10⁻¹ | Strong magnetic control |

### Key Parameters
- **Particle radius**: 100 μm (lunar regolith scale)
- **Density**: 3000 kg/m³ (basaltic)
- **Friction coefficient**: 0.5
- **Lunar gravity**: 1.62 m/s² (downward)
- **Domain size**: 5-10 mm cube

---

## 📁 Project Structure

```
REGO/
├── README.md                    # This file
├── phase0_baseline.py           # Phase 0: DEM validation
├── phase1_magnetic.py           # Phase 1: Magnetic manipulation
├── utils/
│   ├── magnetic_field.py        # Magnetic force calculations
│   ├── material_properties.py   # Regolith properties
│   └── visualization.py         # Plotting and rendering
├── visualize.py                 # Interactive viewer
├── requirements.txt             # Python dependencies
└── outputs/                     # Simulation results (generated)
    ├── Phase0_*.vtu
    ├── Phase1_*.vtu
    └── analysis/
        ├── energy_plot.png
        ├── displacement_vs_chi.png
        └── force_comparison.png
```

---

## 🎓 How It Works

### The GeoTaichi Advantage

Unlike MercuryDPM where external forces don't work properly, GeoTaichi allows **easy customization** of particle forces through Python callbacks:

```python
@ti.kernel
def apply_magnetic_forces():
    for i in particles:
        pos = particles[i].position
        
        # Compute magnetic field at particle position
        B, dBdr = magnetic_field(pos, source_position)
        
        # Magnetic force (paramagnetic)
        F_mag = (chi * volume / MU0) * B * abs(dBdr) * direction
        
        # Add to particle force accumulator
        particles[i].force += F_mag
```

This is called **before** the time integration step, ensuring forces are properly applied!

---

## 🔧 Customization

### Adjusting Magnetic Parameters
Edit `phase1_magnetic.py`:
```python
# Magnetic susceptibility
chi = 1e-3  # 50% iron oxide

# Field strength
B0 = 10.0  # Tesla

# Source position
source_height = domain_size + 0.5e-3  # 0.5mm above domain
```

### Changing Particle Properties
Edit `utils/material_properties.py`:
```python
REGOLITH = {
    'radius': 100e-6,      # m
    'density': 3000,       # kg/m³
    'restitution': 0.5,    # coefficient
    'friction': 0.5,       # coefficient
}
```

---

## 📈 Expected Results

### Phase 0 (Baseline)
- Particles settle under lunar gravity
- Form stable packing
- Energy dissipates to near-zero
- **Success metric**: Stable final configuration

### Phase 1 (Magnetic)
With χ=10⁻³, B₀=10T:
- Particles rise against gravity
- Cluster near magnetic source
- **Rise**: 0.5-2 mm (depending on parameters)
- **Force ratio**: F_mag / F_grav ≈ 0.5-2.0

---

## 🐛 Troubleshooting

### "No module named 'taichi'"
```bash
pip install taichi
```

### "Taichi initialization failed"
Make sure you're specifying CPU mode:
```python
ti.init(arch=ti.cpu)  # Not ti.gpu
```

### Particles exploding/NaN
- Check timestep is small enough (dt < 1e-6 s)
- Verify contact stiffness is reasonable
- Ensure forces aren't too large

---

## 📖 Citation

If you use this code in your research, please cite both REGO and GeoTaichi:

```bibtex
@software{rego2025,
  title={REGO: Magnetic-Field–Driven Shaping and Consolidation of Planetary Regolith},
  author={Your Name},
  year={2025},
  note={Python implementation with GeoTaichi}
}

@article{shi2024geotaichi,
  title={GeoTaichi: A Taichi-powered high-performance numerical simulator for multiscale geophysical problems},
  author={Shi, YH and Guo, N and Yang, ZX},
  journal={Computer Physics Communications},
  volume={301},
  pages={109219},
  year={2024},
  publisher={Elsevier}
}
```

---

## 🤝 Contributing

This is a research project! Contributions welcome:
- Bug reports
- Feature requests
- Performance improvements
- Additional physics models

---

## 📧 Contact

For questions about this REGO implementation, open an issue.  
For GeoTaichi questions, contact: shiyh@zju.edu.cn

---

## ⚖️ License

This project: MIT License (modify as needed)  
GeoTaichi: GPL-3.0 License

---

**Let's make field-programmable regolith a reality! 🚀**