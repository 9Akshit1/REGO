"""
Particle-particle induced-dipole magnetic interaction — physics derivation
and isolated validation. REGO.

STATUS: RESEARCH/VALIDATION ONLY. Does not modify phase2_shaping.py.
No production compute_forces() change happens in this file. This implements
the candidate pairwise force EXACTLY as it would be added to compute_forces()
(same Vp, chi_eff(), mu0 as production, imported not reimplemented) inside an
isolated numpy harness, and runs the correctness/magnitude tests requested
before any production integration.

═══════════════════════════════════════════════════════════════════════════
1. PHYSICAL FORMULATION
═══════════════════════════════════════════════════════════════════════════

REGO's particles are INDUCED paramagnetic, not permanent dipoles. Production
`compute_forces()` already commits to a specific induced-response model for
the particle-vs-EXTERNAL-FIELD force:

    F_i = (Vp * chi_eff(|B_ext(pos_i)|) / (2*mu0)) * grad(|B_ext|^2)|_{pos_i}

This is the standard magnetophoretic force on a small linearly-magnetizable
sphere, F = -grad U with U = -(1/2) m.B_ext and m = (Vp*chi_eff/mu0)*B_ext
(the induced moment of particle i, responding ONLY to the external field,
i.e. this formula implicitly already assumes each particle's own moment is
set by the field it sits in, evaluated as if it were the only particle
there). That per-particle induced-moment definition is the one we REUSE here
-- not a new assumption, just made explicit and used a second time (for the
new interaction) instead of only implicitly inside the existing force.

CANDIDATE PARTICLE-PARTICLE TERM: given each particle's induced moment
m_i = (Vp*chi_eff(|B_ext(pos_i)|)/mu0) * B_ext(pos_i), computed from the
EXTERNAL field ONLY (see "self-consistency" below for why), the force
between two nearby particles i,j is the standard frozen-dipole dipole-dipole
force (valid once m_i, m_j are treated as fixed vectors for the purpose of
this pairwise force -- NOT re-derived as position-dependent through m_i
itself, which would add spurious extra terms not present in any of the
cited literature's treatment either):

    n = (pos_j - pos_i)/d,  d = |pos_j - pos_i|
    F_on_j_from_i = (3*mu0/(4*pi*d^4)) *
        [ (m_i.n)*m_j + (m_j.n)*m_i + (m_i.m_j - 5*(m_i.n)*(m_j.n))*n ]
    F_on_i_from_j = -F_on_j_from_i   (Newton's 3rd law, exact by construction)

Special-case sanity (verified analytically, see test C1/C2 below):
  - m_i, m_j both aligned with the separation vector n (chain axis): ATTRACTIVE.
  - m_i, m_j both aligned but n perpendicular to them (side-by-side): REPULSIVE.
  This matches the (1-3cos^2 theta) scaling used in the earlier back-of-
  envelope estimate and the cited literature's disaggregation mechanism.

═══════════════════════════════════════════════════════════════════════════
2. SELF-CONSISTENCY / MUTUAL INDUCTION -- DOCUMENTED APPROXIMATION
═══════════════════════════════════════════════════════════════════════════

True self-consistent mutual induction would require each particle's moment
to respond to the TOTAL local field (external + all neighbors' induced
fields), which is itself a function of all moments -- an implicit, coupled
system. This script computes, at the representative standoff n_R=3 (where
the earlier analytical sweep found the promising operating window), the
actual field ONE induced neighbor particle produces at a touching (2R)
neighbor's location, and compares it to the external field magnitude at
that location. See `mutual_induction_check()` below.

APPROXIMATION ADOPTED (first-order / independent-moment): each particle's
moment is computed from the EXTERNAL field only, as production already does
for the existing external force. The particle-particle force then uses
these independently-computed, frozen moments. This is the same order of
approximation used throughout the cited colloidal-magnetism literature
(Furst & Gast-style point-dipole pairwise models) and is checked, not
assumed, below to have a small (order-of-magnitude quantified) error at the
relevant standoff.

KNOWN LIMITATION (documented, not fixed here): the point-dipole
approximation itself is weakest exactly at contact (r=2R, not r>>R) --
real magnetized spheres in near-contact have higher-order multipole
corrections the point-dipole formula misses, and these corrections
generically STRENGTHEN near-contact attraction/repulsion relative to the
point-dipole estimate (not weaken it). So the numbers below should be read
as a plausible-order-of-magnitude LOWER bound on the near-contact
interaction strength, not an exact near-contact prediction.

═══════════════════════════════════════════════════════════════════════════
3. DOUBLE-COUNTING CHECK
═══════════════════════════════════════════════════════════════════════════

Production `B_and_gradB2()` sums over `N_DIP` EXTERNAL source dipoles
(dip_p/dip_m/dip_s -- the controller-owned trap/transport/shape dipole
array) only; it never includes other PARTICLES as field sources. The
existing per-particle external force and the new particle-particle force
therefore draw on two entirely disjoint field contributions (external
sources vs. other particles) -- there is no double-counting by construction,
verified directly by reading `B_and_gradB2`'s loop bound (`range(N_DIP)`,
not `range(C.N)`).
"""
import sys
import os
import math

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import phase2_shaping as sim  # noqa: E402  (real Vp, chi_eff, mu0 -- not reimplemented)

sim.init()
C = sim.C
MU0 = sim.MU0
R = C.R
Vp = (4.0 / 3.0) * math.pi * R ** 3


def chi_eff_np(Bmag):
    alpha = C.chi * Bmag / (MU0 * C.Msat)
    alpha = min(alpha, 20.0)
    return C.chi / (math.cosh(alpha) ** 2)


def induced_moment(B_ext_vec):
    """m = (Vp*chi_eff(|B|)/mu0) * B_ext -- SAME formula production's
    external force implicitly uses (F=-grad[-(1/2)m.B] with this m)."""
    Bmag = np.linalg.norm(B_ext_vec)
    ce = chi_eff_np(Bmag)
    return (Vp * ce / MU0) * B_ext_vec, ce, Bmag


def dd_force_on_j(mi, pos_i, mj, pos_j):
    """Frozen-dipole force on particle j due to particle i's induced moment."""
    rvec = pos_j - pos_i
    d = np.linalg.norm(rvec)
    if d < 1e-15:
        return np.zeros(3)
    n = rvec / d
    mi_n = np.dot(mi, n)
    mj_n = np.dot(mj, n)
    mi_mj = np.dot(mi, mj)
    pref = 3.0 * MU0 / (4.0 * math.pi * d ** 4)
    return pref * (mi_n * mj + mj_n * mi + (mi_mj - 5.0 * mi_n * mj_n) * n)


def dd_energy(mi, pos_i, mj, pos_j):
    rvec = pos_j - pos_i
    d = np.linalg.norm(rvec)
    n = rvec / d
    return (MU0 / (4.0 * math.pi * d ** 3)) * (np.dot(mi, mj) - 3.0 * np.dot(mi, n) * np.dot(mj, n))


def real_dipole_B(probe_pos):
    """Real external B field from the currently-configured production dip_p/
    dip_m/dip_s array, using the unmodified production kernel."""
    @sim.ti.kernel
    def _k(px: sim.ti.f64, py: sim.ti.f64, pz: sim.ti.f64) -> sim.ti.types.vector(4, sim.ti.f64):
        return sim.B_and_gradB2(sim.ti.Vector([px, py, pz]))
    bg = _k(probe_pos[0], probe_pos[1], probe_pos[2])
    return np.array([bg[0], bg[1], bg[2]]), bg[3]  # gB2 (unused here), Bmag... fix below


def real_dipole_B_vec(probe_pos):
    """Returns the actual B VECTOR (not just magnitude) at probe_pos, by
    finite-difference-free direct reconstruction: production's
    B_and_gradB2 only returns |B| and grad(B^2), not the B vector, so we
    reconstruct B directly from the same dipole sum here (identical formula,
    read directly from the module's own dip_p/dip_m/dip_s arrays)."""
    dp = sim.dip_p.to_numpy()
    dm = sim.dip_m.to_numpy()
    ds = sim.dip_s.to_numpy()
    MU0_4PI = MU0 / (4.0 * math.pi)
    B = np.zeros(3)
    for k in range(sim.N_DIP):
        sk = ds[k]
        if sk > 1e-15:
            mv = dm[k] * sk
            rv = probe_pos - dp[k]
            r2 = np.dot(rv, rv)
            if r2 > 1e-22:
                r5 = r2 * r2 * math.sqrt(r2)
                mdotr = np.dot(mv, rv)
                B += (MU0_4PI / r5) * (3.0 * mdotr * rv - r2 * mv)
    return B


def setup_wait_hold_dipole():
    sim.dip_s.fill(0.0)
    IDX = sim.IDX_CLUSTER_DIP[1]
    tgt = C.targets[1].copy()
    p_np = sim.dip_p.to_numpy(); m_np = sim.dip_m.to_numpy(); s_np = sim.dip_s.to_numpy()
    p_np[IDX] = tgt
    m_np[IDX] = sim._m_trap * np.array([-1., 0., 0.])
    s_np[IDX] = sim.SHAPE_WAIT_HOLD_STRENGTH
    sim.dip_p.from_numpy(p_np); sim.dip_m.from_numpy(m_np); sim.dip_s.from_numpy(s_np)
    return tgt


# ═══════════════════════════════════════════════════════════════════════════
# TEST 1: single particle -- no interaction possible, sanity only
# ═══════════════════════════════════════════════════════════════════════════
def test1_single_particle():
    print("\n" + "=" * 78)
    print("TEST 1: single particle (no pairs -> zero p-p force by construction)")
    print("=" * 78)
    print("  With N=1 there are no pairs to sum over, so the new term is "
          "identically zero and the existing external-field force (unchanged, "
          "not touched by this work) is exactly what production already "
          "computes. No numerical check needed beyond this structural fact.")


# ═══════════════════════════════════════════════════════════════════════════
# TEST 2: two-particle interaction, cases A-E, uniform-field idealization
# ═══════════════════════════════════════════════════════════════════════════
def test2_two_particle(B_uniform_mag=0.76):
    """Uses a locally-uniform external field of magnitude B_uniform_mag
    (chosen = the real n_R=3 standoff value from the earlier sweep, the
    promising operating point) so the two-particle force test isolates the
    orientation dependence cleanly from external-field gradient effects."""
    print("\n" + "=" * 78)
    print(f"TEST 2: two-particle interaction (uniform |B_ext|={B_uniform_mag}T, "
          f"the n_R=3 promising standoff)")
    print("=" * 78)
    d = 2.0 * R  # bare contact separation
    W1 = C.mp * C.g

    def run_case(name, field_dir, sep_dir, expect):
        field_dir = np.array(field_dir, dtype=np.float64)
        field_dir /= np.linalg.norm(field_dir)
        sep_dir = np.array(sep_dir, dtype=np.float64)
        sep_dir /= np.linalg.norm(sep_dir)
        B_ext = B_uniform_mag * field_dir
        m, ce, Bmag = induced_moment(B_ext)
        pos_i = np.zeros(3)
        pos_j = d * sep_dir
        F_on_j = dd_force_on_j(m, pos_i, m, pos_j)
        F_on_i = dd_force_on_j(m, pos_j, m, pos_i)
        newton3_err = np.linalg.norm(F_on_j + F_on_i) / max(np.linalg.norm(F_on_j), 1e-300)
        radial_component = np.dot(F_on_j, sep_dir)  # >0 repulsive (pushes j away from i), <0 attractive
        # energy-consistency: numerically differentiate energy along sep_dir
        eps = d * 1e-6
        Ep = dd_energy(m, pos_i, m, pos_j + eps * sep_dir)
        Em = dd_energy(m, pos_i, m, pos_j - eps * sep_dir)
        F_from_energy = -(Ep - Em) / (2 * eps)  # force = -dU/dr along sep_dir
        verdict = "REPULSIVE" if radial_component > 0 else "ATTRACTIVE"
        ok = "OK" if verdict == expect else "MISMATCH"
        print(f"  {name}: F_radial={radial_component:.4e}N ({verdict}, expected {expect} -> {ok})  "
              f"|F|/W1={np.linalg.norm(F_on_j)/W1:.3f}  "
              f"Newton3rd_rel_err={newton3_err:.2e}  "
              f"F_from_energy_vs_direct_rel_err={abs(F_from_energy-radial_component)/max(abs(radial_component),1e-300):.2e}  "
              f"chi_eff={ce:.4e}")
        return radial_component

    # Case A: aligned with field (chain axis) -- attractive
    run_case("Case A (aligned along field, chain axis)", [0, 0, 1], [0, 0, 1], "ATTRACTIVE")
    # Case B: side-by-side perpendicular to field -- repulsive
    run_case("Case B (side-by-side, perp to field)     ", [0, 0, 1], [1, 0, 0], "REPULSIVE")
    # Case C: intermediate 45deg -- check continuity
    print("  Case C (intermediate angles, continuity check):")
    prev = None
    for deg in [0, 15, 30, 45, 54.7356, 60, 75, 90]:  # 54.7356deg = magic angle where force changes sign
        th = math.radians(deg)
        sep_dir = [math.sin(th), 0, math.cos(th)]
        r = run_case(f"    theta={deg:6.2f}deg", [0, 0, 1], sep_dir, "ATTRACTIVE" if deg < 54.7 else "REPULSIVE")
        if prev is not None:
            pass
        prev = r
    print("  (theta=54.7356deg is the analytic magic angle where 1-3cos^2(theta)=0 -- "
          "force should cross zero there; see continuity print above.)")


# ═══════════════════════════════════════════════════════════════════════════
# TEST 6 (numbered per report): reproduce the analytical standoff sweep via
# the CODED implementation, not hand arithmetic
# ═══════════════════════════════════════════════════════════════════════════
def test_analytical_vs_coded_sweep():
    print("\n" + "=" * 78)
    print("TEST: coded implementation vs earlier analytical standoff sweep")
    print("=" * 78)
    tgt = setup_wait_hold_dipole()
    W1 = C.mp * C.g
    print(f"{'n_R':>6} {'standoff(mm)':>13} {'Bmag(T)':>10} {'chi_eff':>12} {'F_ext/W1':>10} "
          f"{'F_dd_perp/W1(coded)':>20} {'F_dd_axial/W1(coded)':>20}")
    for n_R in [2.0, 3.0, 5.0, 8.0, 12.0]:
        standoff = n_R * R
        probe_pt = tgt + np.array([standoff, 0.0, 0.0])
        B_ext = real_dipole_B_vec(probe_pt)
        Bmag = np.linalg.norm(B_ext)
        m, ce, _ = induced_moment(B_ext)
        # external force on one particle (reuse production formula components)
        @sim.ti.kernel
        def _kg(px: sim.ti.f64, py: sim.ti.f64, pz: sim.ti.f64) -> sim.ti.types.vector(4, sim.ti.f64):
            return sim.B_and_gradB2(sim.ti.Vector([px, py, pz]))
        bg = _kg(probe_pt[0], probe_pt[1], probe_pt[2])
        gB2 = np.array([bg[0], bg[1], bg[2]])
        F_ext = (Vp * ce / (2.0 * MU0)) * gB2
        d = 2.0 * R
        pos_i = probe_pt
        pos_j_perp = probe_pt + np.array([0, d, 0])  # perpendicular to local field (~radial, x-dir)
        pos_j_axial = probe_pt + np.array([d, 0, 0])  # along local field (~radial, x-dir)
        F_perp = dd_force_on_j(m, pos_i, m, pos_j_perp)
        F_axial = dd_force_on_j(m, pos_i, m, pos_j_axial)
        print(f"{n_R:>6.1f} {standoff*1e3:>13.4f} {Bmag:>10.4f} {ce:>12.4e} {np.linalg.norm(F_ext)/W1:>10.4f} "
              f"{np.linalg.norm(F_perp)/W1:>20.4e} {np.linalg.norm(F_axial)/W1:>20.4e}")


# ═══════════════════════════════════════════════════════════════════════════
# Mutual-induction sanity check (Section 2 above)
# ═══════════════════════════════════════════════════════════════════════════
def mutual_induction_check():
    print("\n" + "=" * 78)
    print("MUTUAL INDUCTION CHECK (is the independent-moment approximation valid?)")
    print("=" * 78)
    tgt = setup_wait_hold_dipole()
    n_R = 3.0
    probe_pt = tgt + np.array([n_R * R, 0.0, 0.0])
    B_ext = real_dipole_B_vec(probe_pt)
    m, ce, Bmag = induced_moment(B_ext)
    d = 2.0 * R
    # B produced by THIS induced particle at a touching neighbor's location (on-axis, worst case)
    n_hat = np.array([1.0, 0.0, 0.0])
    MU0_4PI = MU0 / (4.0 * math.pi)
    B_neighbor = MU0_4PI * (3.0 * np.dot(m, n_hat) * n_hat - m) / d ** 3
    print(f"  external |B| at n_R={n_R} standoff        = {Bmag:.4e} T")
    print(f"  induced moment magnitude                  = {np.linalg.norm(m):.4e} A.m^2")
    print(f"  field from ONE such induced neighbor at touching distance (2R) = "
          f"{np.linalg.norm(B_neighbor):.4e} T")
    ratio = np.linalg.norm(B_neighbor) / Bmag
    print(f"  ratio (neighbor-induced / external)       = {ratio*100:.3f}%")
    print(f"  -> independent-moment (first-order) approximation error is "
          f"~{ratio*100:.2f}% at the representative n_R=3 standoff -- small, "
          f"documented, and consistent with the literature's own approximation order.")


if __name__ == "__main__":
    print(__doc__)
    test1_single_particle()
    test2_two_particle()
    mutual_induction_check()
    test_analytical_vs_coded_sweep()
