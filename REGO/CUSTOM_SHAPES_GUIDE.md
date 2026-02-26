# How to Extend: Adding Custom Shapes

## 5-Minute Tutorial: Add Your Own Shape

### Step 1: Define Your Geometry

Let's say you want a **Torus** (donut shape). Here's how:

```python
from phase2_adaptive_shapes import ShapeTarget
import numpy as np

class Torus(ShapeTarget):
    """Toroidal (donut) shape"""
    
    def __init__(self, center, major_radius, minor_radius):
        """
        Args:
            center: [x, y, z] position of torus center
            major_radius: Distance from center to tube center
            minor_radius: Radius of the tube itself
        """
        self.center = np.array(center, dtype=np.float64)
        self.major_radius = major_radius
        self.minor_radius = minor_radius
    
    def is_inside(self, pos):
        """A point is inside if it's within the tube"""
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        
        # Distance from point to torus axis
        r_xy = np.sqrt(dx**2 + dy**2)
        
        # Distance from point to tube center
        dist_to_axis = np.sqrt((r_xy - self.major_radius)**2 + dz**2)
        
        return dist_to_axis <= self.minor_radius
    
    def get_distance_to_surface(self, pos):
        """Signed distance to torus surface"""
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        
        r_xy = np.sqrt(dx**2 + dy**2)
        dist_to_axis = np.sqrt((r_xy - self.major_radius)**2 + dz**2)
        
        return dist_to_axis - self.minor_radius
    
    def get_target_position(self, pos):
        """Project position onto torus surface"""
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        
        r_xy = np.sqrt(dx**2 + dy**2)
        
        # Find nearest point on tube center circle
        if r_xy > 1e-10:
            scale = self.major_radius / (r_xy + 1e-10)
            center_x = self.center[0] + dx * scale
            center_y = self.center[1] + dy * scale
        else:
            center_x = self.center[0] + self.major_radius
            center_y = self.center[1]
        
        # Now project onto tube surface
        dist_z = np.sqrt((center_x - pos[0])**2 + (center_y - pos[1])**2 + dz**2)
        if dist_z > 1e-10:
            scale = self.minor_radius / (dist_z + 1e-10)
            target_x = center_x + (pos[0] - center_x) * scale
            target_y = center_y + (pos[1] - center_y) * scale
            target_z = self.center[2] + dz * scale
        else:
            target_x = center_x + self.minor_radius
            target_y = center_y
            target_z = self.center[2]
        
        return np.array([target_x, target_y, target_z])
    
    def get_bounds(self):
        """Return geometry bounds for magnetic source planning"""
        total_radius = self.major_radius + self.minor_radius
        return self.center, total_radius, self.minor_radius * 2
    
    def __repr__(self):
        return f"Torus(center={self.center}, major_r={self.major_radius*1e3:.2f}mm, minor_r={self.minor_radius*1e3:.2f}mm)"
```

### Step 2: Use Your Custom Shape

```python
from phase2_adaptive_shapes import config, init_particles, simulate_phase, compute_shape_error
from your_module import Torus

# Create torus: major_radius=3mm, minor_radius=1mm
target = Torus(
    center=[5.0e-3, 5.0e-3, 5.0e-3],
    major_radius=3.0e-3,
    minor_radius=1.0e-3
)

# Setup simulation (uses YOUR shape automatically!)
config.set_target(target)
init_particles()

# Run
simulate_phase(1, 0.5, "Levitation")
simulate_phase(2, 0.7, "Formation")
simulate_phase(3, 0.8, "Stabilization")

# Check results
error_mm, inside = compute_shape_error()
print(f"Torus formation error: {error_mm:.3f}mm")
print(f"Particles inside: {inside}/300")
```

That's it! No other code changes needed. The physics engine automatically handles your shape.

---

## Example Shapes Repository

### Pyramid

```python
class Pyramid(ShapeTarget):
    """Square pyramid pointing up"""
    
    def __init__(self, center, base_side, height):
        self.center = np.array(center)
        self.base_side = base_side
        self.height = height
    
    def is_inside(self, pos):
        dx = abs(pos[0] - self.center[0])
        dy = abs(pos[1] - self.center[1])
        dz = pos[2] - self.center[2]
        
        if dz < 0 or dz > self.height:
            return False
        
        # Radius decreases linearly with height
        scale = 1 - (dz / self.height)
        max_half_side = (self.base_side / 2) * scale
        
        return dx <= max_half_side and dy <= max_half_side
    
    def get_distance_to_surface(self, pos):
        # Simplified - could be more accurate
        if self.is_inside(pos):
            return -0.1e-3  # Approximate
        else:
            dx = abs(pos[0] - self.center[0])
            dy = abs(pos[1] - self.center[1])
            return max(dx, dy)
    
    def get_target_position(self, pos):
        # Project to surface
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        
        dz_clipped = np.clip(dz, 0, self.height)
        scale = 1 - (dz_clipped / self.height)
        max_half_side = (self.base_side / 2) * scale
        
        # Clamp to pyramid surface
        x_clipped = np.sign(dx) * min(abs(dx), max_half_side) + self.center[0]
        y_clipped = np.sign(dy) * min(abs(dy), max_half_side) + self.center[1]
        
        return np.array([x_clipped, y_clipped, self.center[2] + dz_clipped])
    
    def get_bounds(self):
        return self.center, self.base_side / 2, self.height
```

### Ellipsoid

```python
class Ellipsoid(ShapeTarget):
    """Ellipsoidal (stretched sphere) shape"""
    
    def __init__(self, center, radii):
        self.center = np.array(center)
        self.radii = np.array(radii)  # [rx, ry, rz]
    
    def is_inside(self, pos):
        dx = (pos[0] - self.center[0]) / (self.radii[0] + 1e-10)
        dy = (pos[1] - self.center[1]) / (self.radii[1] + 1e-10)
        dz = (pos[2] - self.center[2]) / (self.radii[2] + 1e-10)
        return dx**2 + dy**2 + dz**2 <= 1
    
    def get_distance_to_surface(self, pos):
        # Approximate ellipsoid distance
        dx = (pos[0] - self.center[0]) / (self.radii[0] + 1e-10)
        dy = (pos[1] - self.center[1]) / (self.radii[1] + 1e-10)
        dz = (pos[2] - self.center[2]) / (self.radii[2] + 1e-10)
        dist = np.sqrt(dx**2 + dy**2 + dz**2)
        return (dist - 1) * np.mean(self.radii)
    
    def get_target_position(self, pos):
        dx = pos[0] - self.center[0]
        dy = pos[1] - self.center[1]
        dz = pos[2] - self.center[2]
        
        dist_norm = np.sqrt(
            (dx / (self.radii[0] + 1e-10))**2 +
            (dy / (self.radii[1] + 1e-10))**2 +
            (dz / (self.radii[2] + 1e-10))**2
        )
        
        if dist_norm > 1e-10:
            target_x = self.center[0] + dx * self.radii[0] / dist_norm
            target_y = self.center[1] + dy * self.radii[1] / dist_norm
            target_z = self.center[2] + dz * self.radii[2] / dist_norm
        else:
            target_x = self.center[0] + self.radii[0]
            target_y = self.center[1]
            target_z = self.center[2]
        
        return np.array([target_x, target_y, target_z])
    
    def get_bounds(self):
        return self.center, np.max(self.radii), np.max(self.radii)
```

### Compound Shape (Multiple Objects)

```python
class CompoundShape(ShapeTarget):
    """Multiple shapes combined"""
    
    def __init__(self, shapes):
        self.shapes = shapes
    
    def is_inside(self, pos):
        return any(shape.is_inside(pos) for shape in self.shapes)
    
    def get_distance_to_surface(self, pos):
        distances = [shape.get_distance_to_surface(pos) for shape in self.shapes]
        # Take minimum (closest surface)
        return min(distances)
    
    def get_target_position(self, pos):
        # Find closest shape and project onto it
        closest_idx = np.argmin([
            abs(shape.get_distance_to_surface(pos)) 
            for shape in self.shapes
        ])
        return self.shapes[closest_idx].get_target_position(pos)
    
    def get_bounds(self):
        bounds = [shape.get_bounds() for shape in self.shapes]
        avg_center = np.mean([b[0] for b in bounds], axis=0)
        max_radius = max(b[1] for b in bounds)
        max_height = max(b[2] for b in bounds)
        return avg_center, max_radius, max_height

# Example: Cylinder + Sphere (combined)
compound = CompoundShape([
    Cylinder([5e-3, 5e-3, 4e-3], 2e-3, 2e-3),
    Sphere([5e-3, 5e-3, 6.5e-3], 1.5e-3)
])
config.set_target(compound)
```

### Rotated/Tilted Cylinder

```python
class RotatedCylinder(ShapeTarget):
    """Cylinder at arbitrary orientation"""
    
    def __init__(self, center, axis, radius, height):
        self.center = np.array(center)
        self.axis = np.array(axis) / np.linalg.norm(axis)  # Unit vector
        self.radius = radius
        self.height = height
    
    def is_inside(self, pos):
        v = pos - self.center
        # Project onto cylinder axis
        proj_len = np.dot(v, self.axis)
        if abs(proj_len) > self.height / 2:
            return False
        # Distance from axis
        v_perp = v - proj_len * self.axis
        return np.linalg.norm(v_perp) <= self.radius
    
    # ... implement other methods similarly with rotation ...
```

---

## Template: Copy & Paste

Here's a minimal template for your own shape:

```python
class YourShape(ShapeTarget):
    """Your shape description"""
    
    def __init__(self, center, param1, param2):
        self.center = np.array(center)
        self.param1 = param1
        self.param2 = param2
    
    def is_inside(self, pos):
        """TODO: Implement geometry check"""
        # Return True if pos is inside your shape
        # You know your geometry!
        pass
    
    def get_distance_to_surface(self, pos):
        """TODO: Implement signed distance"""
        # Return distance to surface (negative if inside)
        pass
    
    def get_target_position(self, pos):
        """TODO: Implement surface projection"""
        # Return nearest point on surface to pos
        pass
    
    def get_bounds(self):
        """TODO: Return geometry bounds"""
        # For magnetic source planning
        return self.center, typical_radius, typical_height
    
    def __repr__(self):
        return f"YourShape(...)"


# Use it!
shape = YourShape(center_pos, param1_val, param2_val)
config.set_target(shape)
init_particles()
simulate_phase(1, 0.5, "Phase 1")
```

---

## Testing Your Shape

```python
# Verify your shape is correctly defined
shape = YourShape(...)

# Test: is_inside
assert shape.is_inside(shape.center) == True  # Center should be inside
assert shape.is_inside(shape.center + [1, 0, 0]) == False  # Far away should be outside

# Test: get_distance_to_surface
dist = shape.get_distance_to_surface(shape.center)
assert dist < 0  # Inside = negative distance

# Test: get_target_position
target = shape.get_target_position(shape.center + [10e-3, 0, 0])
assert shape.is_inside(target) == True  # Target should be inside (or on surface)

# Test: get_bounds
center, radius, height = shape.get_bounds()
assert np.allclose(center, shape.center)
```

---

## Common Mistakes

### ❌ Not normalizing vectors
```python
# Wrong
direction = v1 - v2
force = direction * magnitude

# Correct
direction = v1 - v2
direction = direction / np.linalg.norm(direction)
force = direction * magnitude
```

### ❌ Forgetting 1e-10 epsilon
```python
# Wrong
scale = radius / r_perp  # Crashes if r_perp == 0

# Correct
scale = radius / (r_perp + 1e-10)
```

### ❌ Using float32 instead of float64
```python
# Wrong (loses precision)
self.radius = np.float32(0.001)

# Correct
self.radius = np.float64(0.001)  # or just float
```

### ❌ Inconsistent coordinate systems
```python
# Make sure all calculations use same frame!
# If center is [5mm, 5mm, 5mm], all distances from center
dx = pos[0] - self.center[0]  # ✓ Correct relative position
```

---

## Quick Reference: What Each Method Does

| Method | Purpose | Returns |
|--------|---------|---------|
| `is_inside(pos)` | Check if point is inside shape | bool |
| `get_distance_to_surface(pos)` | Distance to nearest surface | float (negative=inside) |
| `get_target_position(pos)` | Project point onto surface | array([x, y, z]) |
| `get_bounds()` | Geometry extents | (center, radius, height) |

The physics engine calls these methods ~90,000,000 times during a simulation, so make them efficient!

---

## Questions?

- **How do I make a 2D shape in 3D?** Add a constraint: `if pos[2] != target_z: return False`
- **How do I make a hollow shape?** Invert the is_inside check: `return not inner_check and outer_check`
- **How do I handle asymmetric shapes?** Just implement the checks - orientation doesn't matter!

The beauty of the ShapeTarget interface is that you only need to describe your geometry. The physics engine handles the rest!

---

**Your custom shapes will work immediately with the fully adaptive magnetic particle system. No tuning, no hardcoding - just describe your geometry.**
