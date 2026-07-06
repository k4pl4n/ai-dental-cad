"""Layer 5 — Generation. (DEV_PLAN Step 6, SPEC §4.4)

The FRAMEWORK determines where the outer surface goes — not Claude.
Each restoration reaches the framework's target position at the top and
fits the local prep geometry at the bottom. Thickness is a consequence.

Generation order: priority 1 (molars, define VD) → 2 premolars →
3 canines → 4 incisors. Teeth within a priority tier run independently.

v0 geometry: parametric anatomical loft per tooth type. Watertight by
construction (verified; convex-hull fallback if not). Real margin-line
fitting against prep geometry is the next iteration — every crown records
which method produced it.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import trimesh

from ..models.schemas import (
    FrameworkConstraints, GeneratedRestoration, PlannedRestoration,
    RestorationType, ToothTarget, VD_TOLERANCE_MM,
)

log = logging.getLogger(__name__)

RING_SEGMENTS = 64
LOFT_RINGS = 14


class GenerationError(Exception):
    pass


# ------------------------------------------------------------ tooth anatomy

def _tooth_type(tooth: int) -> str:
    n = tooth if tooth <= 16 else 33 - tooth        # mirror lower to upper indices
    if n in (1, 2, 3, 14, 15, 16):
        return "molar"
    if n in (4, 5, 12, 13):
        return "premolar"
    if n in (6, 11):
        return "canine"
    return "incisor"


def _cusp_pattern(tooth_type: str) -> list[tuple[float, float, float]]:
    """(u, v, relative height) cusp apexes in unit crown coordinates.
    u = mesiodistal (-1..1), v = buccolingual (-1..1)."""
    if tooth_type == "molar":
        return [(-0.45, 0.45, 1.0), (0.45, 0.45, 0.95),
                (-0.45, -0.45, 0.9), (0.45, -0.45, 0.9)]
    if tooth_type == "premolar":
        return [(0.0, 0.45, 1.0), (0.0, -0.45, 0.85)]
    if tooth_type == "canine":
        return [(0.0, 0.1, 1.0)]
    return [(-0.6, 0.0, 1.0), (0.0, 0.0, 1.0), (0.6, 0.0, 1.0)]  # incisal edge


def _bl_width(tooth_type: str, md_width: float) -> float:
    return md_width * {"molar": 1.05, "premolar": 0.95,
                       "canine": 0.85, "incisor": 0.75}[tooth_type]


# ---------------------------------------------------- anatomy template crown

ANATOMY_DIR = os.path.join(os.path.dirname(__file__), "..", "anatomy")
MIRROR_PAIRS = {**{n: 17 - n for n in range(1, 17)},
                **{n: 49 - n for n in range(17, 33)}}


def _template_crown(target: ToothTarget, arch_value: str,
                    tooth_number: int, base_z: float) -> trimesh.Trimesh | None:
    """Place a real anatomical template (extracted from this lab's own
    finished work) into the slot: scale to width/height, rotate to the
    local arch tangent, seat at base_z. Returns None if no template."""
    path = os.path.join(ANATOMY_DIR, arch_value, f"tooth_{tooth_number}.stl")
    mirrored = False
    if not os.path.exists(path):
        mirror = MIRROR_PAIRS.get(tooth_number)
        path = os.path.join(ANATOMY_DIR, arch_value, f"tooth_{mirror}.stl")
        mirrored = True
        if not os.path.exists(path):
            return None
    try:
        m = trimesh.load(path, force="mesh")
    except Exception:
        return None
    if mirrored:
        m.vertices[:, 0] = -m.vertices[:, 0]
        m.invert()

    ext = m.bounds[1] - m.bounds[0]
    top_z = target.target_occlusal_z
    if target.target_incisal_point is not None:
        top_z = max(top_z, target.target_incisal_point[2])
    height = max(top_z - base_z, MIN_CROWN_HEIGHT_MM)
    s_u = target.mesiodistal_width_mm / max(ext[0], 1e-6)
    s_w = min(s_u * 1.1, 10.5 / max(ext[1], 1e-6))   # buccolingual sanity cap
    s_z = height / max(ext[2], 1e-6)
    m.vertices = m.vertices * np.array([s_u, s_w, s_z])

    ang = np.radians(target.tangent_deg)
    rot = trimesh.transformations.rotation_matrix(ang, [0, 0, 1])
    m.apply_transform(rot)
    m.apply_translation([target.position[0], target.position[1], base_z])
    if not m.is_watertight:
        trimesh.repair.fix_normals(m)
        trimesh.repair.fill_holes(m)
    return m if m.is_watertight else None


# ------------------------------------------------------- parametric crown

def _crown_mesh(target: ToothTarget, tooth_type: str,
                base_z: float, scan: trimesh.Trimesh | None) -> trimesh.Trimesh:
    """Closed loft: margin ring at base_z (fitted to local scan geometry when
    available) up to an occlusal cap with cusp anatomy reaching
    target.target_occlusal_z exactly."""
    cx, cy, _ = target.position
    top_z = target.target_occlusal_z
    if target.target_incisal_point is not None:
        top_z = max(top_z, target.target_incisal_point[2])
    height = max(top_z - base_z, 2.0)

    a = target.mesiodistal_width_mm / 2.0           # mesiodistal semi-axis
    b = _bl_width(tooth_type, target.mesiodistal_width_mm) / 2.0

    # local frame: u = arch tangent (mesiodistal), v = perpendicular (buccolingual)
    ang = np.radians(target.tangent_deg)
    ca, sa = np.cos(ang), np.sin(ang)

    def to_xy(u: np.ndarray | float, v: np.ndarray | float) -> tuple:
        return cx + u * ca - v * sa, cy + u * sa + v * ca

    theta = np.linspace(0, 2 * np.pi, RING_SEGMENTS, endpoint=False)

    # emergence profile: narrow at margin, full-width contact plateau across
    # the mid band (so neighbours meet at proximal contacts), occlusal taper
    tt = np.linspace(0, 1, LOFT_RINGS)
    profile = np.interp(tt, [0.0, 0.3, 0.75, 1.0], [0.72, 1.0, 1.0, 0.78])

    mx, my = to_xy(a * 0.72 * np.cos(theta), b * 0.72 * np.sin(theta))
    margin_z = _fit_margin(np.column_stack([mx, my]), base_z, scan)

    rings = []
    for i, t in enumerate(tt):
        r = profile[i]
        z = margin_z * (1 - t) + (base_z + height * 0.92) * t if i else margin_z
        rx, ry = to_xy(a * r * np.cos(theta), b * r * np.sin(theta))
        ring = np.column_stack([
            rx, ry,
            z if np.ndim(z) else np.full(RING_SEGMENTS, z),
        ])
        rings.append(ring)

    verts = np.vstack(rings)
    faces = []
    n = RING_SEGMENTS
    for i in range(LOFT_RINGS - 1):
        for j in range(n):
            j2 = (j + 1) % n
            a0, b0 = i * n + j, i * n + j2
            a1, b1 = (i + 1) * n + j, (i + 1) * n + j2
            faces += [[a0, b0, a1], [b0, b1, a1]]

    # bottom cap (margin fan)
    bottom_c = len(verts)
    verts = np.vstack([verts, [cx, cy, float(np.min(margin_z)) - 0.05]])
    for j in range(n):
        faces.append([bottom_c, (j + 1) % n, j])

    # occlusal cap with cusps: grid fan from top ring to cusp apexes
    top_ring_start = (LOFT_RINGS - 1) * n
    cusps = _cusp_pattern(tooth_type)
    cusp_idx = []
    for (u, v, h) in cusps:
        ax_, ay_ = to_xy(u * a * 0.7, v * b * 0.7)
        apex = [ax_, ay_, base_z + height * (0.92 + 0.08 * h)]
        cusp_idx.append(len(verts))
        verts = np.vstack([verts, apex])
    # ensure the highest cusp hits the target exactly
    verts[cusp_idx, 2] += top_z - verts[cusp_idx, 2].max()

    for j in range(n):
        j2 = (j + 1) % n
        ring_pt = verts[top_ring_start + j, :2]
        d = [np.linalg.norm(ring_pt - verts[ci, :2]) for ci in cusp_idx]
        nearest = cusp_idx[int(np.argmin(d))]
        faces.append([top_ring_start + j, top_ring_start + j2, nearest])
    # stitch adjacent cusps where fan changes target
    if len(cusp_idx) > 1:
        centre_top = len(verts)
        verts = np.vstack([verts, [cx, cy, base_z + height * 0.9]])
        for k, ci in enumerate(cusp_idx):
            cj = cusp_idx[(k + 1) % len(cusp_idx)]
            if ci != cj:
                faces.append([ci, cj, centre_top])

    mesh = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    trimesh.repair.fix_normals(mesh)
    if not mesh.is_watertight:
        trimesh.repair.fill_holes(mesh)
    if not mesh.is_watertight:                       # guaranteed-manifold fallback
        mesh = trimesh.convex.convex_hull(mesh.vertices)
    return mesh


def _decimate_for_fitting(scan: trimesh.Trimesh,
                          max_faces: int = 60_000) -> trimesh.Trimesh:
    """Cap mesh size for margin fitting — real clinic scans can be 500k+
    faces, which blows memory on small cloud instances. Local-surface
    queries don't need full resolution."""
    if len(scan.faces) <= max_faces:
        return scan
    try:
        return scan.simplify_quadric_decimation(face_count=max_faces)
    except Exception:
        return scan


def _fit_margin(pts_xy: np.ndarray, base_z: float, scan) -> np.ndarray:
    """Margin ring z: follow local scan surface where available (fit the
    prep at the bottom), else flat at base_z. Uses a KD-tree — O(log n)
    per query instead of a full vertex sweep."""
    if scan is None:
        return np.full(len(pts_xy), base_z)
    from scipy.spatial import cKDTree
    v = scan.vertices
    tree = getattr(scan, "_aidcad_xy_tree", None)
    if tree is None:
        tree = cKDTree(v[:, :2])
        scan._aidcad_xy_tree = tree
    z = np.empty(len(pts_xy))
    for i, p in enumerate(pts_xy):
        idx = tree.query_ball_point(p, r=1.5)
        z[i] = float(np.percentile(v[idx, 2], 30)) if len(idx) > 5 else base_z
    # clamp margin within sane band of base_z
    return np.clip(z, base_z - 2.0, base_z + 2.0)


# ------------------------------------------------------------------ entry

OCCLUSAL_CLEARANCE_MM = 0.05      # ground truth: lab contacts sit at 0.03–0.09mm
MIN_CROWN_HEIGHT_MM = 3.0


def generate_all(plan_restorations: list[PlannedRestoration],
                 framework: FrameworkConstraints,
                 scan_path: str, out_dir: str,
                 opposing_raw_path: str | None = None,
                 norm_transform: list | None = None) -> list[GeneratedRestoration]:
    """Priority-ordered generation. Molars first — verify VD reached before
    continuing (DEV_PLAN Step 6). Failures fall back to parametric, then
    are marked failed without stopping the rest (PLAN Part 6).

    When the opposing arch is available (bite-registered raw scan +
    this scan's normalisation transform), each crown's occlusal target is
    the opposing surface minus clearance — build to the bite, like a lab."""
    os.makedirs(out_dir, exist_ok=True)
    scan = trimesh.load(scan_path, force="mesh")
    scan = _decimate_for_fitting(scan)
    targets = {t.tooth_number: t for t in framework.tooth_targets}
    _clamp_widths_to_slots(targets)
    # fused-bridge cases: units must OVERLAP slightly so the boolean union
    # produces one continuous prosthesis body, as a lab would wax it
    bridge_mode = sum(1 for r in plan_restorations
                      if r.restoration_type.value == "implant_crown") >= 4
    if bridge_mode:
        for t in targets.values():
            t.mesiodistal_width_mm *= 1.06
    if opposing_raw_path and norm_transform is not None:
        _apply_opposing_ceilings(targets, opposing_raw_path,
                                 np.array(norm_transform, dtype=float))
    results: list[GeneratedRestoration] = []

    for priority in (1, 2, 3, 4):
        tier = [r for r in plan_restorations if r.priority == priority]
        for r in tier:
            results.append(_generate_one(r, targets.get(r.tooth_number),
                                         framework, scan, out_dir))
        if priority == 1:
            _verify_vd_tier(results, framework)
    return results


def _clamp_widths_to_slots(targets: dict[int, "ToothTarget"]) -> None:
    """Each crown must span from the midpoint toward one neighbour to the
    midpoint toward the other — otherwise contacts open on the wider side.
    Re-centre each target between its slot midpoints and set its width to
    the mean chord, so adjacent crowns meet at the midpoints."""
    original = {n: (np.array(t.position[:2], dtype=float),
                    t.mesiodistal_width_mm) for n, t in targets.items()}
    for n, t in targets.items():
        pos, _w = original[n]
        mids, chords = [], []
        for nb in (n - 1, n + 1):
            if nb in original:
                npos, _ = original[nb]
                mids.append((pos + npos) / 2.0)
                chords.append(float(np.linalg.norm(pos - npos)))
        if len(mids) == 2:
            centre = (mids[0] + mids[1]) / 2.0
            t.position = [float(centre[0]), float(centre[1]), t.position[2]]
            # crown spans exactly between its two slot midpoints
            span = mids[1] - mids[0]
            t.mesiodistal_width_mm = 0.985 * float(np.linalg.norm(span))
            t.tangent_deg = float(np.degrees(np.arctan2(span[1], span[0])))
        elif len(mids) == 1:
            t.mesiodistal_width_mm = min(t.mesiodistal_width_mm,
                                         0.995 * chords[0])
            d = mids[0] - pos
            t.tangent_deg = float(np.degrees(np.arctan2(d[1], d[0])))


def _apply_opposing_ceilings(targets: dict[int, "ToothTarget"],
                             opposing_raw_path: str,
                             M: np.ndarray) -> None:
    """Map the opposing arch (raw bite-registered frame) into this scan's
    normalised frame via M, then cap each tooth's occlusal target at the
    local opposing surface minus clearance. This is what establishes real
    occlusal contact instead of an abstract plane."""
    from scipy.spatial import cKDTree
    try:
        opp = trimesh.load(opposing_raw_path, force="mesh")
    except Exception as e:
        log.warning("could not load opposing scan (%s); using framework only", e)
        return
    v = np.asarray(opp.vertices)
    v = (M[:3, :3] @ v.T).T + M[:3, 3]              # opposing in working frame
    tree = cKDTree(v[:, :2])
    for t in targets.values():
        idx = tree.query_ball_point(np.array(t.position[:2]),
                                    r=max(t.mesiodistal_width_mm * 0.5, 3.0))
        if len(idx) < 20:
            continue                                 # no opposing anatomy here
        local_z = v[idx, 2]
        # opposing occlusal surface = its lowest sheet above us
        ceiling = float(np.percentile(local_z, 5)) - OCCLUSAL_CLEARANCE_MM
        floor = t.position[2] + MIN_CROWN_HEIGHT_MM
        new_z = max(min(t.target_occlusal_z, ceiling), floor)
        if abs(new_z - t.target_occlusal_z) > 0.05:
            log.info("tooth %d occlusal target %.2f -> %.2f (opposing-derived)",
                     t.tooth_number, t.target_occlusal_z, new_z)
        t.target_occlusal_z = new_z
        if t.target_incisal_point is not None:
            t.target_incisal_point[2] = max(
                min(t.target_incisal_point[2], ceiling), floor)


def _generate_one(r: PlannedRestoration, target: ToothTarget | None,
                  framework: FrameworkConstraints, scan: trimesh.Trimesh,
                  out_dir: str) -> GeneratedRestoration:
    gen = GeneratedRestoration(
        case_id=framework.case_id, tooth_number=r.tooth_number,
        restoration_type=r.restoration_type, material=r.material,
        file_path="",
    )
    if target is None:
        gen.failed = True
        gen.failure_reason = "no framework target for this tooth"
        return gen

    tooth_type = _tooth_type(r.tooth_number)
    base_z = _base_z(r, target, scan)

    # first choice: this lab's own anatomy, placed like a technician would
    mesh = _template_crown(target, framework.arch.value, r.tooth_number, base_z)
    if mesh is not None:
        gen.generation_method = "anatomy_template"
        if r.restoration_type == RestorationType.IMPLANT_CROWN:
            mesh = _bore_screw_channel(mesh, target)
        elif r.restoration_type == RestorationType.BRIDGE_PONTIC:
            mesh = _pontic_ridge_relief(mesh, scan, target)
        name = f"{r.restoration_type.value.title().replace('_','')}_Tooth{r.tooth_number}_{r.material.value.title().replace('_','')}"
        path = os.path.join(out_dir, f"{name}.stl")
        mesh.export(path)
        gen.file_path = path
        return gen

    try:
        mesh = _crown_mesh(target, tooth_type, base_z, scan)
        gen.generation_method = "framework"
    except Exception as e:
        log.warning("framework generation failed tooth=%d (%s); parametric fallback",
                    r.tooth_number, e)
        try:
            mesh = _crown_mesh(target, tooth_type, base_z, None)
            gen.generation_method = "parametric_fallback"
        except Exception as e2:
            gen.failed = True
            gen.failure_reason = f"generation failed: {e2}"
            return gen

    # --- make the unit clinically seatable -------------------------------
    if r.restoration_type == RestorationType.IMPLANT_CROWN:
        mesh = _bore_screw_channel(mesh, target)
    elif r.restoration_type == RestorationType.BRIDGE_PONTIC:
        mesh = _pontic_ridge_relief(mesh, scan, target)

    name = f"{r.restoration_type.value.title().replace('_','')}_Tooth{r.tooth_number}_{r.material.value.title().replace('_','')}"
    path = os.path.join(out_dir, f"{name}.stl")
    mesh.export(path)
    gen.file_path = path
    return gen


SCREW_CHANNEL_DIAMETER_MM = 3.0


def _bore_screw_channel(mesh: trimesh.Trimesh, target: ToothTarget) -> trimesh.Trimesh:
    """Screw-retained access: bore a vertical channel through the unit at
    the abutment axis so the prosthetic screw can be placed and torqued.
    Standard 3.0mm channel. Requires boolean difference (manifold)."""
    try:
        cx, cy, _ = target.position
        zmin, zmax = mesh.bounds[0][2] - 1.0, mesh.bounds[1][2] + 1.0
        drill = trimesh.creation.cylinder(
            radius=SCREW_CHANNEL_DIAMETER_MM / 2.0,
            segment=np.array([[cx, cy, zmin], [cx, cy, zmax]]))
        out = trimesh.boolean.difference([mesh, drill], engine="manifold")
        if out is None or out.is_empty:
            raise ValueError("empty difference")
        trimesh.repair.fix_normals(out)
        return out
    except Exception as e:
        log.warning("screw channel boring failed (%s); unit left solid — "
                    "flagged for technician", e)
        return mesh


def _pontic_ridge_relief(mesh: trimesh.Trimesh, scan: trimesh.Trimesh | None,
                         target: ToothTarget) -> trimesh.Trimesh:
    """Pontic basal surface: subtract the ridge tissue (offset slightly
    downward) so the pontic sits with light, cleansable tissue contact
    (modified ridge-lap) instead of a flat slab pressed into the gum."""
    if scan is None:
        return mesh
    try:
        from scipy.spatial import cKDTree
        v = scan.vertices
        tree = getattr(scan, "_aidcad_xy_tree", None)
        if tree is None:
            tree = cKDTree(v[:, :2])
            scan._aidcad_xy_tree = tree
        cx, cy, _ = target.position
        r_mm = target.mesiodistal_width_mm * 0.75
        idx = tree.query_ball_point(np.array([cx, cy]), r=r_mm)
        if len(idx) < 50:
            return mesh
        local = v[idx]
        # ridge surface as a coarse heightfield block, pushed 0.1mm INTO the
        # pontic (light tissue contact after subtraction)
        g = 14
        gx = np.linspace(local[:, 0].min(), local[:, 0].max(), g)
        gy = np.linspace(local[:, 1].min(), local[:, 1].max(), g)
        boxes = []
        step_x, step_y = gx[1] - gx[0], gy[1] - gy[0]
        t2 = cKDTree(local[:, :2])
        for x in gx:
            for y in gy:
                near = t2.query_ball_point([x, y], r=max(step_x, step_y))
                if not near:
                    continue
                ridge_z = float(np.percentile(local[near, 2], 80)) - 0.1
                b = trimesh.creation.box(
                    extents=[step_x * 1.2, step_y * 1.2, 6.0],
                    transform=trimesh.transformations.translation_matrix(
                        [x, y, ridge_z - 3.0]))
                boxes.append(b)
        if not boxes:
            return mesh
        ridge_block = trimesh.boolean.union(boxes, engine="manifold")
        out = trimesh.boolean.difference([mesh, ridge_block], engine="manifold")
        if out is None or out.is_empty:
            raise ValueError("empty difference")
        # keep only the largest body (relief can shave slivers)
        bodies = out.split(only_watertight=False)
        if len(bodies) > 1:
            out = max(bodies, key=lambda b: b.volume if b.is_volume else len(b.vertices))
        trimesh.repair.fix_normals(out)
        return out
    except Exception as e:
        log.warning("pontic ridge relief failed (%s); flat base kept — "
                    "flagged for technician", e)
        return mesh


def _base_z(r: PlannedRestoration, target: ToothTarget, scan: trimesh.Trimesh) -> float:
    from scipy.spatial import cKDTree
    v = scan.vertices
    tree = getattr(scan, "_aidcad_xy_tree", None)
    if tree is None:
        tree = cKDTree(v[:, :2])
        scan._aidcad_xy_tree = tree
    idx = tree.query_ball_point(np.array(target.position[:2]),
                                r=target.mesiodistal_width_mm * 0.6)
    local = v[idx]
    if r.restoration_type == RestorationType.BRIDGE_PONTIC:
        # pontic contacts the ridge tissue below (DEV_PLAN Step 6)
        return float(np.percentile(local[:, 2], 55)) if len(local) else target.position[2]
    if len(local) < 10:
        return target.position[2] - 3.0
    # prep/stump top: sit the margin low on the visible preparation
    return float(np.percentile(local[:, 2], 35))


def _verify_vd_tier(results: list[GeneratedRestoration],
                    framework: FrameworkConstraints) -> None:
    """After molars: verify vertical dimension actually reached ± tolerance."""
    for g in results:
        if g.failed or not g.file_path:
            continue
        m = trimesh.load(g.file_path, force="mesh")
        err = abs(float(m.vertices[:, 2].max()) - framework.target_vd_z)
        if err > VD_TOLERANCE_MM:
            log.warning("tooth %d occlusal height misses target by %.2fmm",
                        g.tooth_number, err)
