import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

# Constants
MU0_4PI = 1e-7
L, cx, cy, cz = 10.0e-3, 5.0e-3, 5.0e-3, 5.0e-3
cR, cH = (10.0/6.0)*1e-3, 4.0e-3
z_lo, z_hi = cz - cH/2, cz + cH/2

N_DIP = 36
p, m, s = np.zeros((N_DIP, 3)), np.zeros((N_DIP, 3)), np.zeros(N_DIP)

# 1. Hold Dipoles (Indices 8-11, Weak gravity balance during shape)
targets = np.array([
    [5.0e-3, 5.0e-3, 7.2e-3],
    [3.13e-3, 5.0e-3, 5.0e-3],
    [6.87e-3, 5.0e-3, 5.0e-3],
    [5.0e-3, 5.0e-3, 2.8e-3]
])
_m_trap = 0.0006
for k in range(4):
    p[8+k] = targets[k]
    m[8+k] = _m_trap * np.array([0., 1., 0.])
    s[8+k] = 0.08  # Weak well (prevents gravity drift without fighting shape)

# 2. Shape Dipoles (Indices 16-31, Full Strength)
_m_shape = 0.0012
_d_shape = 0.15e-3
cap_r = 1.0e-3
wall_zs = [z_lo + (i + 0.5) * cH / 4 for i in range(4)]

# Top/Bottom Caps
for i in range(4):
    th = i * np.pi / 2 + np.pi / 4
    # Top
    p[16+i] = [cx + cap_r*np.cos(th), cy + cap_r*np.sin(th), z_hi + _d_shape]
    m[16+i] = _m_shape * (-np.array([np.cos(th), np.sin(th), 0.0]) * 0.8 + np.array([0., 0., 0.6]))
    s[16+i] = 1.0
    # Bottom
    p[20+i] = [cx + cap_r*np.cos(th), cy + cap_r*np.sin(th), z_lo - _d_shape]
    m[20+i] = _m_shape * (-np.array([np.cos(th), np.sin(th), 0.0]) * 0.8 + np.array([0., 0., -0.6]))
    s[20+i] = 1.0

# Left/Right Walls
wall_thetas_L = [np.pi - 0.4, np.pi - 0.15, np.pi + 0.15, np.pi + 0.4]
wall_thetas_R = [-0.4, -0.15, 0.15, 0.4]
for i in range(4):
    th_l, th_r = wall_thetas_L[i], wall_thetas_R[i]
    p[24+i] = [cx + (cR + _d_shape)*np.cos(th_l), cy + (cR + _d_shape)*np.sin(th_l), wall_zs[i]]
    m[24+i] = _m_shape * (np.array([-np.sin(th_l), np.cos(th_l), 0.0]) * 0.7 + np.array([-np.cos(th_l), -np.sin(th_l), 0.0]) * 0.3)
    s[24+i] = 1.0
    
    p[28+i] = [cx + (cR + _d_shape)*np.cos(th_r), cy + (cR + _d_shape)*np.sin(th_r), wall_zs[i]]
    m[28+i] = _m_shape * (np.array([-np.sin(th_r), np.cos(th_r), 0.0]) * 0.7 + np.array([-np.cos(th_r), -np.sin(th_r), 0.0]) * 0.3)
    s[28+i] = 1.0

# Numpy translation of B_and_gradB2 analytical Jacobian
def B_and_gradB2(r):
    B = np.zeros(3)
    # Pass 1: accumulate total B
    for k in range(N_DIP):
        if s[k] > 1e-15:
            mv, rv = m[k] * s[k], r - p[k]
            r2 = np.dot(rv, rv)
            if r2 > 1e-12:
                r5 = r2 * r2 * np.sqrt(r2)
                B += (MU0_4PI / r5) * (3.0 * np.dot(mv, rv) * rv - r2 * mv)
    
    # Pass 2: accumulate ∇(B²) via Jacobian
    gB2 = np.zeros(3)
    for k in range(N_DIP):
        if s[k] > 1e-15:
            mv, rv = m[k] * s[k], r - p[k]
            r2 = np.dot(rv, rv)
            if r2 > 1e-12:
                r5 = r2**2 * np.sqrt(r2)
                mdotrv, Bdotrv, mdotB = np.dot(mv, rv), np.dot(B, rv), np.dot(mv, B)
                c5, c7 = MU0_4PI / r5, 15.0 * MU0_4PI / (r5 * r2)
                gB2 += 2.0 * (c5 * (3.0*Bdotrv*mv + 3.0*mdotrv*B + 3.0*mdotB*rv) - c7 * mdotrv * Bdotrv * rv)
    return gB2

# --- Plotting Engine ---
x_vals, y_vals = np.linspace(3e-3, 7e-3, 7), np.linspace(3e-3, 7e-3, 7)
z_vals = np.linspace(2.5e-3, 7.5e-3, 9)
X, Y, Z = np.meshgrid(x_vals, y_vals, z_vals, indexing='ij')

U, V, W, C_color = np.zeros_like(X), np.zeros_like(Y), np.zeros_like(Z), np.zeros_like(X)
for i in range(X.shape[0]):
    for j in range(X.shape[1]):
        for k in range(X.shape[2]):
            r = np.array([X[i,j,k], Y[i,j,k], Z[i,j,k]])
            if np.sqrt((r[0]-cx)**2 + (r[1]-cy)**2) < cR and z_lo < r[2] < z_hi:
                continue # Skip drawing inside the solid cylinder bounds
                
            gb2 = B_and_gradB2(r)
            mag = np.linalg.norm(gb2)
            if mag > 0:
                scale = np.log10(mag + 1) / mag
                U[i,j,k], V[i,j,k], W[i,j,k] = gb2[0]*scale, gb2[1]*scale, gb2[2]*scale
                C_color[i,j,k] = np.log10(mag + 1e-10)

fig = plt.figure(figsize=(10, 8))
ax = fig.add_subplot(111, projection='3d')

# Cylinder Surface
Th_cyl, Z_cyl_surf = np.meshgrid(np.linspace(0, 2*np.pi, 30), np.linspace(z_lo, z_hi, 30))
ax.plot_surface((cx + cR * np.cos(Th_cyl))*1e3, (cy + cR * np.sin(Th_cyl))*1e3, Z_cyl_surf*1e3, 
                color='cyan', alpha=0.3, edgecolor='none')

mask = (U != 0) | (V != 0) | (W != 0)
q = ax.quiver(X[mask]*1e3, Y[mask]*1e3, Z[mask]*1e3, U[mask], V[mask], W[mask], 
              length=0.4, normalize=True, cmap='plasma', array=C_color[mask])

cbar = fig.colorbar(q, ax=ax, shrink=0.5, aspect=10)
cbar.set_label('Log10(|∇B²|)')
ax.set(title="Analytical ∇B² Field (Jacobian) - Shape Phase (v13.3)",
       xlabel="X (mm)", ylabel="Y (mm)", zlabel="Z (mm)", 
       xlim=[3,7], ylim=[3,7], zlim=[2.5, 7.5])

plt.tight_layout()
plt.show()