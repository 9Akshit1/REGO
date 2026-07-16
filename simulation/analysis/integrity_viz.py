import matplotlib.pyplot as plt
import numpy as np

fig = plt.figure(figsize=(10, 8))
ax = fig.add_subplot(111, projection='3d')

# 1. Create the bonded cylinder (the target)
z = np.linspace(3, 7, 20)
theta = np.linspace(0, 2*np.pi, 20)
theta_grid, z_grid = np.meshgrid(theta, z)
x_grid = 5 + 1.67 * np.cos(theta_grid)
y_grid = 5 + 1.67 * np.sin(theta_grid)

# Plot cylinder body
ax.plot_surface(x_grid, y_grid, z_grid, color='cyan', alpha=0.3, edgecolor='navy', lw=0.5)

# 2. Define the 10x Lunar Gravity Vectors (16.2 m/s²)
# Origin for arrows (the Center of Mass)
origin = [5, 5, 5]

# Axial (+Z) - Thick Red
ax.quiver(*origin, 0, 0, 2.5, color='red', lw=5, label='6a: Axial (+Z) - Launch Shock')

# Lateral (+X) - Thick Green
ax.quiver(*origin, 2.5, 0, 0, color='green', lw=5, label='6b: Lateral (+X) - Vibration')

# Diagonal (X+Z) - Thick Gold
# Resultant of 7.07g in X and 7.07g in Z
ax.quiver(*origin, 1.77, 0, 1.77, color='orange', lw=5, label='6c: Diagonal - Shear Test')

# Formatting
ax.set_title("REGO Phase 6: Mechanical Integrity Validation (10-G Stress)", fontweight='bold')
ax.set_xlabel("X (mm)")
ax.set_ylabel("Y (mm)")
ax.set_zlabel("Z (mm)")
ax.set_xlim(2, 8); ax.set_ylim(2, 8); ax.set_zlim(2, 8)
ax.legend(loc='upper left')

plt.show()