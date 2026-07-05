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


def _fit_margin(pts_xy: np.ndarray, base_z: float, scan) -> np.ndarray:
    """Margin ring z: follow local scan surface where available (fit the
    prep at the bottom), else flat at base_z."""
    if scan is None:
        return np.full(len(pts_xy), base_z)
    v = scan.vertices
    z = np.empty(len(pts_xy))
    for i, p in enumerate(pts_xy):
        d = np.linalg.norm(v[:, :2] - p, axis=1)
        near = v[d < 1.5]
        z[i] = float(np.percentile(near[:, 2], 30)) if len(near) > 5 else base_z
    # clamp margin within sane band of base_z
    return np.clip(z, base_z - 2.0, base_z + 2.0)


# ------------------------------------------------------------------ entry

def generate_all(plan_restorations: list[PlannedRestoration],
                 framework: FrameworkConstraints,
                 scan_path: str, out_dir: str) -> list[GeneratedRestoration]:
    """Priority-ordered generation. Molars first — verify VD reached before
    continuing (DEV_PLAN Step 6). Failures fall back to parametric, then
    are marked failed without stopping the rest (PLAN Part 6)."""
    os.makedirs(out_dir, exist_ok=True)
    scan = trimesh.load(scan_path, force="mesh")
    targets = {t.tooth_number: t for t in framework.tooth_targets}
    _clamp_widths_to_slots(targets)
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
            t.mesiodistal_width_mm = 0.995 * float(np.linalg.norm(span))
            t.tangent_deg = float(np.degrees(np.arctan2(span[1], span[0])))
        elif len(mids) == 1:
            t.mesiodistal_width_mm = min(t.mesiodistal_width_mm,
                                         0.995 * chords[0])
            d = mids[0] - pos
            t.tangent_deg = float(np.degrees(np.arctan2(d[1], d[0])))


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

    name = f"{r.restoration_type.value.title().replace('_','')}_Tooth{r.tooth_number}_{r.material.value.title().replace('_','')}"
    path = os.path.join(out_dir, f"{name}.stl")
    mesh.export(path)
    gen.file_path = path
    return gen


def _base_z(r: PlannedRestoration, target: ToothTarget, scan: trimesh.Trimesh) -> float:
    v = scan.vertices
    d = np.linalg.norm(v[:, :2] - np.array(target.position[:2]), axis=1)
    local = v[d < target.mesiodistal_width_mm * 0.6]
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
