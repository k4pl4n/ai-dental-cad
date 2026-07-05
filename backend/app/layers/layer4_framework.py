"""Layer 4 — Framework. (DEV_PLAN Step 5, SPEC §4.3 framework parameters)

Pure geometry. No AI. Translates the four framework parameters into 3D
constraints: target occlusal heights, incisal curve, contact points,
symmetry axes. Output: FrameworkConstraints — every restoration respects it.
"""
from __future__ import annotations

import logging

import numpy as np
import trimesh

from ..models.schemas import (
    Arch, FrameworkConstraints, FrameworkParameters, IngestedScan, ToothTarget,
)

log = logging.getLogger(__name__)

# Mean mesiodistal crown widths (mm), midline outward:
# central, lateral, canine, PM1, PM2, M1, M2, M3
TOOTH_WIDTHS_UPPER = [8.5, 6.5, 7.6, 7.1, 6.6, 10.4, 9.8, 9.2]
TOOTH_WIDTHS_LOWER = [5.3, 5.9, 6.8, 7.0, 7.1, 11.4, 10.8, 10.7]

# Universal numbering, midline outward. Upper right 8→1, upper left 9→16.
UPPER_RIGHT = [8, 7, 6, 5, 4, 3, 2, 1]     # x < 0 side (patient right)
UPPER_LEFT = [9, 10, 11, 12, 13, 14, 15, 16]
LOWER_RIGHT = [25, 26, 27, 28, 29, 30, 31, 32]
LOWER_LEFT = [24, 23, 22, 21, 20, 19, 18, 17]

ANTERIOR_POSITIONS = set(range(5, 13)) | set(range(21, 29))  # canines+incisors+PMs? no:
ANTERIOR_POSITIONS = {6, 7, 8, 9, 10, 11, 22, 23, 24, 25, 26, 27}  # canine-to-canine


def build_framework(scan: IngestedScan, params: FrameworkParameters,
                    planned_teeth: list[int]) -> FrameworkConstraints:
    mesh = trimesh.load(scan.file_path, force="mesh")
    v = mesh.vertices
    meas = scan.measurements

    target_vd_z = meas.max_occlusal_z_mm + params.vd_increase_mm

    plane_point, plane_normal = _fit_occlusal_plane(v, params.occlusal_plane_tilt_deg)

    anchors = _tooth_anchors(v, scan.arch)          # tooth_number -> (x, y, z_ridge)
    widths = _widths_from_anchors(anchors)

    incisal_z = _incisal_target_z(v, anchors, params, scan.arch)
    incisal_curve = _incisal_curve(anchors, incisal_z, scan.arch)

    targets: list[ToothTarget] = []
    for tooth in sorted(anchors):
        ax, ay, az = anchors[tooth]
        t = ToothTarget(
            tooth_number=tooth,
            position=[float(ax), float(ay), float(az)],
            target_occlusal_z=float(target_vd_z),
            mesiodistal_width_mm=float(widths[tooth]),
        )
        if tooth in ANTERIOR_POSITIONS:
            t.target_incisal_point = [float(ax), float(ay), float(incisal_z)]
        targets.append(t)

    if params.symmetric:
        targets = _mirror_right_to_left(targets, scan.arch)

    fw = FrameworkConstraints(
        case_id=scan.case_id, arch=scan.arch,
        target_vd_z=float(target_vd_z),
        occlusal_plane_point=[float(x) for x in plane_point],
        occlusal_plane_normal=[float(x) for x in plane_normal],
        incisal_curve=incisal_curve,
        symmetry_axis_x=0.0,
        tooth_targets=targets,
    )
    log.info("framework case=%s target_vd_z=%.2f teeth=%d",
             scan.case_id, target_vd_z, len(targets))
    return fw


# ------------------------------------------------------------- occlusal plane

def _fit_occlusal_plane(v: np.ndarray, tilt_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Plane through three reference points: highest point of the least-worn
    molar region on each side + highest anterior (canine region). Then tilt."""
    x, y = v[:, 0], v[:, 1]
    xr = x.max() - x.min()
    yr = y.max() - y.min()

    def highest_in(mask: np.ndarray) -> np.ndarray:
        pts = v[mask]
        return pts[np.argmax(pts[:, 2])] if len(pts) else v[np.argmax(v[:, 2])]

    posterior = y < (y.min() + 0.35 * yr)
    p_right = highest_in(posterior & (x < x.min() + 0.4 * xr))
    p_left = highest_in(posterior & (x > x.max() - 0.4 * xr))
    p_ant = highest_in(y > (y.max() - 0.25 * yr))

    n = np.cross(p_left - p_right, p_ant - p_right)
    norm = np.linalg.norm(n)
    n = np.array([0.0, 0.0, 1.0]) if norm < 1e-9 else n / norm
    if n[2] < 0:
        n = -n

    if abs(tilt_deg) > 1e-6:                        # tilt about mesial-distal (X) axis
        a = np.radians(tilt_deg)
        rot = np.array([[1, 0, 0],
                        [0, np.cos(a), -np.sin(a)],
                        [0, np.sin(a), np.cos(a)]])
        n = rot @ n
    centre = (p_right + p_left + p_ant) / 3.0
    return centre, n


def _widths_from_anchors(anchors: dict[int, tuple[float, float, float]]) -> dict[int, float]:
    """Mesiodistal width per tooth from the chord distances between its own
    anchor and its neighbours' anchors. This keeps crown widths consistent
    with the slots they must fill, so adjacent contacts close correctly."""
    out: dict[int, float] = {}
    for n, (x, y, _z) in anchors.items():
        chords = []
        for nb in (n - 1, n + 1):
            if nb in anchors:
                ox, oy, _ = anchors[nb]
                chords.append(float(np.hypot(x - ox, y - oy)))
        out[n] = float(np.mean(chords)) if chords else 8.0
    return out


# ------------------------------------------------------------- tooth anchors

def _tooth_anchors(v: np.ndarray, arch: Arch) -> dict[int, tuple[float, float, float]]:
    """Place the 16 standard tooth positions along a parabolic arch curve
    fitted to the scan's XY footprint. Anchor z = local ridge height."""
    x, y = v[:, 0], v[:, 1]
    half_w = (x.max() - x.min()) / 2.0
    y_ant, y_post = y.max(), y.min()

    def curve_y(cx: float) -> float:                # anterior at x=0
        return y_ant - (y_ant - y_post) * (cx / half_w) ** 2

    # arc length along the parabola (numeric)
    xs = np.linspace(0, half_w * 0.98, 200)
    ys = np.array([curve_y(c) for c in xs])
    seg = np.sqrt(np.diff(xs) ** 2 + np.diff(ys) ** 2)
    arc = np.concatenate([[0], np.cumsum(seg)])
    half_len = arc[-1]

    widths = TOOTH_WIDTHS_UPPER if arch == Arch.UPPER else TOOTH_WIDTHS_LOWER
    scale = half_len / sum(widths)                  # fit 8 teeth into the half arch
    centres_along = np.cumsum([w * scale for w in widths]) - np.array(
        [w * scale / 2 for w in widths])

    right, left = ((UPPER_RIGHT, UPPER_LEFT) if arch == Arch.UPPER
                   else (LOWER_RIGHT, LOWER_LEFT))

    anchors: dict[int, tuple[float, float, float]] = {}
    for side, sign in ((right, -1.0), (left, +1.0)):
        for tooth, dist in zip(side, centres_along):
            cx = sign * float(np.interp(dist, arc, xs))
            cy = curve_y(abs(cx))
            cz = _local_ridge_z(v, cx, cy)
            anchors[tooth] = (cx, cy, cz)
    return anchors


def _local_ridge_z(v: np.ndarray, cx: float, cy: float, radius: float = 4.0) -> float:
    d = np.linalg.norm(v[:, :2] - np.array([cx, cy]), axis=1)
    local = v[d < radius]
    if len(local) < 10:
        return float(np.percentile(v[:, 2], 60))
    return float(np.percentile(local[:, 2], 90))    # near-top of local anatomy


# ------------------------------------------------------------- incisal curve

def _incisal_target_z(v: np.ndarray, anchors: dict, params: FrameworkParameters,
                      arch: Arch) -> float:
    """Gingival level at the central incisors + target crown length."""
    centrals = (8, 9) if arch == Arch.UPPER else (24, 25)
    zs = [anchors[t][2] for t in centrals if t in anchors]
    ridge = float(np.mean(zs)) if zs else float(np.percentile(v[:, 2], 60))
    # crown grows occlusally (+Z) from the cervical line; approximate cervical
    # as ridge minus typical existing exposure
    cervical = ridge - 4.0
    return cervical + params.incisal_crown_length_mm


def _incisal_curve(anchors: dict, incisal_z: float, arch: Arch) -> list[list[float]]:
    anterior = sorted(t for t in anchors if t in ANTERIOR_POSITIONS)
    pts = [[anchors[t][0], anchors[t][1], incisal_z] for t in anterior]
    return [[float(c) for c in p] for p in sorted(pts, key=lambda p: p[0])]


# ----------------------------------------------------------------- symmetry

MIRROR_UPPER = {1: 16, 2: 15, 3: 14, 4: 13, 5: 12, 6: 11, 7: 10, 8: 9}
MIRROR_LOWER = {32: 17, 31: 18, 30: 19, 29: 20, 28: 21, 27: 22, 26: 23, 25: 24}


def _mirror_right_to_left(targets: list[ToothTarget], arch: Arch) -> list[ToothTarget]:
    """Reflect right-side targets across the midline to define left-side
    targets — forces symmetric restorations. (DEV_PLAN Step 5)"""
    mirror = MIRROR_UPPER if arch == Arch.UPPER else MIRROR_LOWER
    by_num = {t.tooth_number: t for t in targets}
    for right_t, left_t in mirror.items():
        r, l = by_num.get(right_t), by_num.get(left_t)
        if r is None or l is None:
            continue
        l.target_occlusal_z = r.target_occlusal_z
        l.mesiodistal_width_mm = r.mesiodistal_width_mm
        l.position = [-r.position[0], r.position[1], r.position[2]]
        if r.target_incisal_point is not None:
            l.target_incisal_point = [-r.target_incisal_point[0],
                                      r.target_incisal_point[1],
                                      r.target_incisal_point[2]]
        l.mirrored_from = right_t
    return list(by_num.values())
