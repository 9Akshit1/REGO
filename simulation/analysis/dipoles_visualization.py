import numpy as np
import matplotlib.pyplot as plt

# Domain geometry (meters to millimeters for easier plotting)
L, cx, cy, cz = 10.0, 5.0, 5.0, 5.0
cR, cH = 10.0/6.0, 4.0
z_lo, z_hi = cz - cH/2, cz + cH/2

# Initialize arrays
p = np.zeros((36, 3))
m = np.zeros((36, 3))
colors = ['gray'] * 36

# 1. Corner Quadrupoles (Indices 0-7)
qc = [[7.5, 7.5], [2.5, 7.5], [7.5, 2.5], [2.5, 2.5]]
for k in range(4):
    # Primary (Blue)
    p[k*2] = [qc[k][0], qc[k][1], -1.5]
    m[k*2] = [0, 0, 1] 
    colors[k*2] = 'blue'
    # Compensate (Red)
    p[k*2+1] = [qc[k][0], qc[k][1], -2.1]
    m[k*2+1] = [0, 0, -1]
    colors[k*2+1] = 'red'

# 2. Trap / Hold Dipoles at Final Targets (Indices 8-11)
targets = [[5.0, 5.0, 7.2], [3.13, 5.0, 5.0], [6.87, 5.0, 5.0], [5.0, 5.0, 2.8]]
for k in range(4):
    p[8+k] = targets[k]
    m[8+k] = [0, 1, 0] # Transverse y-moment during hold
    colors[8+k] = 'green'

# 3. Shape Dipoles (Indices 16-31)
d_shape = 0.15
cap_r = 1.0
wall_zs = [z_lo + (i + 0.5) * cH / 4 for i in range(4)]

# Top Cap (16-19)
for i in range(4):
    th = i * np.pi / 2 + np.pi / 4
    p[16+i] = [cx + cap_r*np.cos(th), cy + cap_r*np.sin(th), z_hi + d_shape]
    m[16+i] = [-np.cos(th), -np.sin(th), 0.5] # Inward tangent + Z
    colors[16+i] = 'orange'

# Bottom Cap (20-23)
for i in range(4):
    th = i * np.pi / 2 + np.pi / 4
    p[20+i] = [cx + cap_r*np.cos(th), cy + cap_r*np.sin(th), z_lo - d_shape]
    m[20+i] = [-np.cos(th), -np.sin(th), -0.5]
    colors[20+i] = 'darkorange'

# Left Wall (24-27) & Right Wall (28-31)
wall_thetas_L = [np.pi - 0.4, np.pi - 0.15, np.pi + 0.15, np.pi + 0.4]
wall_thetas_R = [-0.4, -0.15, 0.15, 0.4]
for i in range(4):
    # Left
    th_l = wall_thetas_L[i]
    p[24+i] = [cx + (cR + d_shape)*np.cos(th_l), cy + (cR + d_shape)*np.sin(th_l), wall_zs[i]]
    m[24+i] = [-np.sin(th_l), np.cos(th_l), 0] # Azimuthal
    colors[24+i] = 'gold'
    # Right
    th_r = wall_thetas_R[i]
    p[28+i] = [cx + (cR + d_shape)*np.cos(th_r), cy + (cR + d_shape)*np.sin(th_r), wall_zs[i]]
    m[28+i] = [-np.sin(th_r), np.cos(th_r), 0]
    colors[28+i] = 'goldenrod'

# 4. Disabled Hold Rings (Indices 12-15 & 32-35)
target_normals = [[0,0,1], [-1,0,0], [1,0,0], [0,0,-1]]
target_trans = [[0,1,0]] * 4
for k in range(4):
    ring_center = np.array(targets[k]) + 0.05 * np.array(target_normals[k])
    p[12+k] = ring_center + 3.0 * np.array(target_trans[k])
    p[32+k] = ring_center - 3.0 * np.array(target_trans[k])
    # Defaults to gray, vectors not explicitly drawn to save visual clutter

# Plotting
fig = plt.figure(figsize=(12, 10))
ax = fig.add_subplot(111, projection='3d')

# Draw target cylinder for reference
z_cyl = np.linspace(z_lo, z_hi, 50)
th_cyl = np.linspace(0, 2*np.pi, 50)
Th_cyl, Z_cyl = np.meshgrid(th_cyl, z_cyl)
X_cyl = cx + cR * np.cos(Th_cyl)
Y_cyl = cy + cR * np.sin(Th_cyl)
ax.plot_surface(X_cyl, Y_cyl, Z_cyl, color='cyan', alpha=0.1, edgecolor='none')

# Plot dipoles as quivers (arrows indicate moment direction)
# Normalize moments for uniform plotting
m_norms = np.linalg.norm(m, axis=1)
m_norms[m_norms == 0] = 1 # Avoid division by zero for inactive ones
m_dirs = m / m_norms[:, np.newaxis]

for i in range(36):
    if colors[i] != 'gray': # Skip rendering arrows for disabled dipoles
        ax.quiver(p[i,0], p[i,1], p[i,2], 
                  m_dirs[i,0], m_dirs[i,1], m_dirs[i,2], 
                  color=colors[i], length=0.8, normalize=True, arrow_length_ratio=0.3)
    ax.scatter(p[i,0], p[i,1], p[i,2], color=colors[i], s=20)

# Custom legend
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker='o', color='w', markerfacecolor='blue', label='Corner Primary (z=-1.5)'),
    Line2D([0], [0], marker='o', color='w', markerfacecolor='red', label='Corner Comp (z=-2.1)'),
    Line2D([0], [0], marker='o', color='w', markerfacecolor='green', label='Transport/Hold (at targets)'),
    Line2D([0], [0], marker='o', color='w', markerfacecolor='orange', label='Shape Surface-Tangent'),
    Line2D([0], [0], marker='o', color='w', markerfacecolor='gray', label='Disabled Hold Rings'),
]
ax.legend(handles=legend_elements, loc='upper left')

ax.set_title("REGO Phase 2 v13.3 — 36-Dipole Layout", fontweight='bold')
ax.set_xlabel("X (mm)")
ax.set_ylabel("Y (mm)")
ax.set_zlabel("Z (mm)")
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.set_zlim(-3, 8)
plt.tight_layout()
plt.show()