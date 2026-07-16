import matplotlib.pyplot as plt
plt.plot([0,100,700,800], [20,140,140,20], 'b-', linewidth=3)
plt.axvspan(100,700, alpha=0.2, color='orange', label='Consolidation @140°C')
plt.axhline(113, color='red', ls='--', label='Sulfur solidifies')
plt.axhline(119, color='red', ls=':', label='Sulfur melts')
plt.xlabel('Time (s)'); plt.ylabel('Temperature (°C)')
plt.legend(); plt.grid(True)
plt.savefig("temperature_schedule.png", dpi=200)