"""Layer 1 — Ingestion. (DEV_PLAN Part 3, Step 1)

Receives raw STL/PLY. Validates, normalises orientation via PCA,
detects upper vs lower geometrically, measures the arch, extracts
mesh quality metrics, repairs if needed.

Output: IngestedScan — a clean, oriented, measured mesh object.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import trimesh

from ..models.schemas import (
    Arch, ArchMeasurements, IngestedScan, MeshMetrics,
)

log = logging.getLogger(__name__)

MIN_VERTICES = 30_000
MAX_VERTICES = 800_000
MAX_FILE_MB = 200

USER_ERROR_NOT_A_SCAN = (
    "This file does not appear to be a standard intraoral scan. "
    "Please export the scan from your scanner software as STL or PLY and try again."
)


class IngestionError(Exception):
    """User-facing ingestion failure. Message is shown verbatim to the dentist."""


# ------------------------------------------------------------------ loading

def _load_mesh(path: str) -> trimesh.Trimesh:
    if not os.path.exists(path):
        raise IngestionError("The uploaded file could not be found.")
    if os.path.getsize(path) > MAX_FILE_MB * 1024 * 1024:
        raise IngestionError(f"File exceeds the {MAX_FILE_MB}MB limit.")
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".stl", ".ply"):
        raise IngestionError("Only STL and PLY files are supported.")
    try:
        loaded = trimesh.load(path, force="mesh")
    except Exception:
        raise IngestionError(USER_ERROR_NOT_A_SCAN)
    if not isinstance(loaded, trimesh.Trimesh) or loaded.vertices is None:
        raise IngestionError(USER_ERROR_NOT_A_SCAN)
    return loaded


def _validate(mesh: trimesh.Trimesh, strict: bool = True) -> None:
    v, f = len(mesh.vertices), len(mesh.faces)
    if f == 0 or v == 0:
        raise IngestionError(USER_ERROR_NOT_A_SCAN)
    if strict and not (MIN_VERTICES <= v <= MAX_VERTICES):
        raise IngestionError(
            f"{USER_ERROR_NOT_A_SCAN} (The mesh has {v:,} vertices; "
            f"intraoral scans have {MIN_VERTICES:,}–{MAX_VERTICES:,}.)"
        )


# ------------------------------------------------------- PCA normalisation

def normalise_orientation(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Rotate so mesial-distal = X (largest spread), buccal-lingual = Y,
    occlusal-apical = Z, with occlusal pointing +Z. Centre on origin (XY)."""
    verts = mesh.vertices - mesh.vertices.mean(axis=0)
    cov = np.cov(verts.T)
    eigvals, eigvecs = np.linalg.eigh(cov)          # ascending
    # columns: [smallest, middle, largest] variance
    axes = np.column_stack([eigvecs[:, 2], eigvecs[:, 1], eigvecs[:, 0]])  # X,Y,Z
    if np.linalg.det(axes) < 0:                     # keep right-handed
        axes[:, 1] = -axes[:, 1]
    rotated = verts @ axes

    # Occlusal side up: tooth surfaces carry far more geometric detail than
    # the trimmed gingival base. Compare mean local curvature proxy
    # (face-normal dispersion) of top vs bottom z-halves; flip if needed.
    if _detail_score(mesh, rotated, top=True) < _detail_score(mesh, rotated, top=False):
        rotated[:, 2] = -rotated[:, 2]
        rotated[:, 1] = -rotated[:, 1]              # preserve handedness

    # Anterior toward +Y: the arch opens posteriorly, so vertex mass at the
    # anterior curve sits farther from the X axis on one side.
    y = rotated[:, 1]
    if np.abs(y.min()) > np.abs(y.max()):
        rotated[:, 1] = -rotated[:, 1]
        rotated[:, 0] = -rotated[:, 0]              # preserve handedness

    out = mesh.copy()
    out.vertices = rotated
    return out


def _detail_score(mesh: trimesh.Trimesh, rotated: np.ndarray, top: bool) -> float:
    z = rotated[:, 2]
    zmid = np.median(z)
    sel = z > zmid if top else z < zmid
    if sel.sum() < 100:
        return 0.0
    # dispersion of face normals whose centroid falls in the half
    fc_z = rotated[mesh.faces].mean(axis=1)[:, 2]
    fsel = fc_z > zmid if top else fc_z < zmid
    if fsel.sum() < 50:
        return 0.0
    normals = mesh.face_normals[fsel]
    return float(1.0 - np.linalg.norm(normals.mean(axis=0)))


# ---------------------------------------------------- upper/lower detection

ARCH_FILL_THRESHOLD = 0.75


def detect_arch(mesh: trimesh.Trimesh) -> Arch:
    """Geometric, never from filename. Upper arches have a filled palate in
    the centre; lower arches have a tongue gap. Measure how much of the XY
    convex hull is occupied by mesh: palate fills the horseshoe interior
    (fill ratio ≈ 0.85+), a lower arch leaves it empty (≈ 0.5–0.65).
    (DEV_PLAN Step 1)"""
    from scipy.spatial import ConvexHull, Delaunay

    xy = mesh.vertices[:, :2]
    cell_mm = 2.5                                    # physical grid resolution
    nx = max(int((xy[:, 0].max() - xy[:, 0].min()) / cell_mm), 8)
    ny = max(int((xy[:, 1].max() - xy[:, 1].min()) / cell_mm), 8)
    gx = np.linspace(xy[:, 0].min(), xy[:, 0].max(), nx + 1)
    gy = np.linspace(xy[:, 1].min(), xy[:, 1].max(), ny + 1)
    occupancy, _, _ = np.histogram2d(xy[:, 0], xy[:, 1], bins=[gx, gy])
    occupied = occupancy > 0

    hull = Delaunay(xy[ConvexHull(xy).vertices])
    cx, cy = (gx[:-1] + gx[1:]) / 2, (gy[:-1] + gy[1:]) / 2
    X, Y = np.meshgrid(cx, cy, indexing="ij")
    inside = (hull.find_simplex(np.column_stack([X.ravel(), Y.ravel()])) >= 0
              ).reshape(X.shape)
    fill = float(occupied[inside].mean())
    return Arch.UPPER if fill > ARCH_FILL_THRESHOLD else Arch.LOWER


# ------------------------------------------------------------- measurement

def measure_arch(mesh: trimesh.Trimesh) -> ArchMeasurements:
    v = mesh.vertices
    return ArchMeasurements(
        mesiodistal_width_mm=float(v[:, 0].max() - v[:, 0].min()),
        anteroposterior_depth_mm=float(v[:, 1].max() - v[:, 1].min()),
        max_occlusal_z_mm=float(v[:, 2].max()),
        centroid=[float(c) for c in v.mean(axis=0)],
    )


# ---------------------------------------------------------- quality/repair

def extract_metrics(mesh: trimesh.Trimesh) -> MeshMetrics:
    try:
        holes = len(trimesh.repair.broken_faces(mesh))
    except Exception:
        holes = 0
    edges = mesh.edges_sorted
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    non_manifold = int(np.sum(counts > 2))
    return MeshMetrics(
        vertex_count=len(mesh.vertices),
        face_count=len(mesh.faces),
        surface_area_mm2=float(mesh.area),
        volume_mm3=float(abs(mesh.volume)) if mesh.is_volume else 0.0,
        watertight=bool(mesh.is_watertight),
        hole_count=holes,
        non_manifold_edges=non_manifold,
    )


def repair_if_needed(mesh: trimesh.Trimesh, metrics: MeshMetrics) -> tuple[trimesh.Trimesh, list[str]]:
    applied: list[str] = []
    if metrics.non_manifold_edges > 0 or metrics.hole_count > 0 or not metrics.watertight:
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        applied.append("removed duplicate faces / unreferenced vertices")
        trimesh.repair.fix_normals(mesh)
        applied.append("fixed normals")
        if not mesh.is_watertight:
            trimesh.repair.fill_holes(mesh)
            applied.append("filled holes")
    return mesh, applied


# ------------------------------------------------------------------ entry

def ingest(file_path: str, case_id: str, out_dir: str,
           original_filename: str = "", strict: bool = True,
           expected_arch: Arch | None = None) -> IngestedScan:
    """Full Layer-1 pipeline for one uploaded file.

    expected_arch: which upload slot the dentist used (upper/lower zone).
    Real prep scans often exclude the palate, which defeats pure geometric
    detection — so the dentist's explicit slot choice wins, and geometry
    is used as a cross-check that logs a warning on disagreement."""
    mesh = _load_mesh(file_path)
    _validate(mesh, strict=strict)

    mesh = normalise_orientation(mesh)
    metrics = extract_metrics(mesh)
    mesh, repairs = repair_if_needed(mesh, metrics)
    if repairs:
        metrics = extract_metrics(mesh)

    detected = detect_arch(mesh)
    if expected_arch is not None and detected != expected_arch:
        log.warning("case=%s: uploaded in %s slot but geometry suggests %s — "
                    "using the dentist's slot", case_id,
                    expected_arch.value, detected.value)
        repairs = repairs + [f"arch check: geometry suggested {detected.value}, "
                             f"kept dentist's {expected_arch.value} slot"]
    arch = expected_arch or detected
    measurements = measure_arch(mesh)

    os.makedirs(out_dir, exist_ok=True)
    normalised_path = os.path.join(out_dir, f"{case_id}_{arch.value}_normalised.stl")
    mesh.export(normalised_path)

    scan = IngestedScan(
        case_id=case_id, arch=arch, file_path=normalised_path,
        original_filename=original_filename or os.path.basename(file_path),
        metrics=metrics, measurements=measurements, repairs_applied=repairs,
    )
    log.info("ingested case=%s arch=%s verts=%d watertight=%s repairs=%s",
             case_id, arch.value, metrics.vertex_count, metrics.watertight, repairs)
    return scan
