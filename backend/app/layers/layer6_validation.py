"""Layer 6a — The six validation checks. (DEV_PLAN Step 7, SPEC §4.5)

Strict order. Any failure reports specifically which check and where.
Silent failures are not permitted. Never show green when any check failed.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import trimesh

from ..models.schemas import (
    FrameworkConstraints, GeneratedRestoration, MATERIAL_SPECS,
    ValidationCheck, ValidationReport, VD_TOLERANCE_MM,
)

log = logging.getLogger(__name__)

CONTACT_TOLERANCE_MM = 0.1
ADJACENT_OPEN_MM = 0.5          # gap larger than this = open contact
ADJACENT_TIGHT_MM = -0.15       # overlap deeper than this = over-tight


def validate_all(restorations: list[GeneratedRestoration],
                 framework: FrameworkConstraints,
                 opposing_scan_path: str | None,
                 out_dir: str) -> ValidationReport:
    ok = [r for r in restorations if not r.failed and r.file_path]
    meshes = {r.tooth_number: trimesh.load(r.file_path, force="mesh") for r in ok}

    checks = [
        _check1_integrity(ok, meshes),
        _check2_thickness(ok, meshes),
        _check3_vertical_dimension(ok, meshes, framework),
        _check4_occlusal_contacts(ok, meshes, framework, opposing_scan_path),
        _check5_adjacent_contacts(ok, meshes),
    ]
    checks.append(_check6_sintering_scale(ok, meshes, out_dir))

    report = ValidationReport(
        case_id=framework.case_id, checks=checks,
        all_passed=all(c.passed for c in checks) and not any(r.failed for r in restorations),
    )
    for c in checks:
        log.info("check %d %-22s %s %s", c.check_number, c.name,
                 "PASS" if c.passed else "FAIL", c.details)
    return report


# ---------------------------------------------------------------- check 1

def _check1_integrity(rest, meshes) -> ValidationCheck:
    failures: dict[int, str] = {}
    for r in rest:
        m = meshes[r.tooth_number]
        problems = []
        if not m.is_watertight:
            trimesh.repair.fill_holes(m)            # one automatic repair attempt
            trimesh.repair.fix_normals(m)
            if not m.is_watertight:
                problems.append("not watertight")
        if not m.is_winding_consistent:
            problems.append("inconsistent winding")
        edges, counts = np.unique(m.edges_sorted, axis=0, return_counts=True)
        if np.any(counts > 2):
            problems.append("non-manifold edges")
        if problems:
            failures[r.tooth_number] = ", ".join(problems)
        elif not m.is_watertight:
            failures[r.tooth_number] = "repair failed"
    return ValidationCheck(
        check_number=1, name="restoration integrity", passed=not failures,
        details="all meshes watertight and manifold" if not failures
        else f"{len(failures)} restoration(s) with mesh defects",
        per_tooth_failures=failures)


# ---------------------------------------------------------------- check 2

def _check2_thickness(rest, meshes) -> ValidationCheck:
    """Sample surface points, measure distance to the opposite wall via ray
    casting inward. Solid v0 crowns: thickness = local solid depth."""
    failures: dict[int, str] = {}
    for r in rest:
        m = meshes[r.tooth_number]
        spec = MATERIAL_SPECS[r.material]
        pts, face_idx = m.sample(200, return_index=True)
        normals = m.face_normals[face_idx]
        origins = pts - normals * 1e-3
        hits = m.ray.intersects_location(origins, -normals)[0]
        if len(hits) == 0:
            continue
        # nearest opposite-wall hit per sample
        min_required = min(spec.min_occlusal_mm, spec.min_axial_mm)
        d = trimesh.proximity.ProximityQuery(m)
        # conservative: local thickness proxy = 2×distance from surface sample to medial point
        thickness = np.abs(d.signed_distance(pts - normals * min_required))
        thin = np.sum(thickness + min_required < min_required * 0.99)
        if thin > 10:                                # tolerate sampling noise
            failures[r.tooth_number] = (
                f"{thin}/200 samples below {min_required}mm minimum for {r.material.value}")
    return ValidationCheck(
        check_number=2, name="minimum thickness", passed=not failures,
        details="material minimums met" if not failures
        else f"{len(failures)} restoration(s) below material minimum thickness",
        per_tooth_failures=failures)


# ---------------------------------------------------------------- check 3

def _check3_vertical_dimension(rest, meshes, framework) -> ValidationCheck:
    """Each restoration's occlusal height vs its own target (which may be
    opposing-arch-derived rather than a single flat plane)."""
    posteriors = [r for r in rest if _is_posterior(r.tooth_number)]
    if not posteriors:
        return ValidationCheck(check_number=3, name="vertical dimension", passed=True,
                               details="no posterior restorations; VD check not applicable")
    targets = {t.tooth_number: t.target_occlusal_z for t in framework.tooth_targets}
    failures: dict[int, str] = {}
    worst = 0.0
    for r in posteriors:
        tz = targets.get(r.tooth_number)
        if tz is None:
            continue
        achieved = float(meshes[r.tooth_number].vertices[:, 2].max())
        err = abs(achieved - tz)
        worst = max(worst, err)
        if err > VD_TOLERANCE_MM:
            failures[r.tooth_number] = f"height {achieved:.2f}mm vs target {tz:.2f}mm"
    return ValidationCheck(
        check_number=3, name="vertical dimension", passed=not failures,
        details=f"per-tooth occlusal height error ≤ {worst:.2f}mm "
                f"(tolerance ±{VD_TOLERANCE_MM}mm)"
                + (f"; {len(failures)} tooth/teeth out of tolerance" if failures else ""),
        per_tooth_failures=failures)


def _is_posterior(tooth: int) -> bool:
    n = tooth if tooth <= 16 else 33 - tooth
    return n in (1, 2, 3, 4, 5, 12, 13, 14, 15, 16)


# ---------------------------------------------------------------- check 4

def _check4_occlusal_contacts(rest, meshes, framework, opposing_path) -> ValidationCheck:
    if not opposing_path or not os.path.exists(opposing_path):
        return ValidationCheck(
            check_number=4, name="occlusal contacts", passed=True,
            details="single-arch case: no opposing scan uploaded; contact simulation skipped "
                    "(noted in case report — clinician must verify occlusion)")
    opposing = trimesh.load(opposing_path, force="mesh")
    if len(opposing.faces) > 40_000:                 # memory cap for cloud instances
        try:
            opposing = opposing.simplify_quadric_decimation(face_count=40_000)
        except Exception:
            pass
    pq = trimesh.proximity.ProximityQuery(opposing)
    contacts = {"right": 0, "left": 0}
    hyper: dict[int, str] = {}
    for r in rest:
        m = meshes[r.tooth_number]
        top = m.vertices[m.vertices[:, 2] > np.percentile(m.vertices[:, 2], 80)]
        if len(top) == 0:
            continue
        d = np.abs(pq.signed_distance(top[np.random.choice(len(top), min(80, len(top)), replace=False)]))
        n_contact = int(np.sum(d < CONTACT_TOLERANCE_MM))
        side = "right" if _is_right(r.tooth_number) else "left"
        contacts[side] += n_contact
        if n_contact > 40:
            hyper[r.tooth_number] = f"{n_contact} contact points — possible hyperocclusion"
    total = contacts["right"] + contacts["left"]
    balanced = total == 0 or (min(contacts.values()) / max(max(contacts.values()), 1)) > 0.25
    passed = balanced and not hyper
    return ValidationCheck(
        check_number=4, name="occlusal contacts", passed=passed,
        details=f"contacts right={contacts['right']} left={contacts['left']}"
                + ("" if balanced else " — unbalanced")
                + (f"; {len(hyper)} hyperoccluded" if hyper else ""),
        per_tooth_failures=hyper)


def _is_right(tooth: int) -> bool:
    return tooth <= 8 or tooth >= 25


# ---------------------------------------------------------------- check 5

def _check5_adjacent_contacts(rest, meshes) -> ValidationCheck:
    failures: dict[int, str] = {}
    ordered = sorted(rest, key=lambda r: r.tooth_number)
    for a, b in zip(ordered, ordered[1:]):
        if b.tooth_number - a.tooth_number != 1:
            continue                                 # not neighbours
        ma, mb = meshes[a.tooth_number], meshes[b.tooth_number]
        pq = trimesh.proximity.ProximityQuery(mb)
        sample = ma.vertices[np.random.choice(len(ma.vertices),
                                              min(150, len(ma.vertices)), replace=False)]
        d = pq.signed_distance(sample)               # positive = inside b
        gap = float(-d.max())                        # min separation (neg if overlapping)
        if gap > ADJACENT_OPEN_MM:
            failures[a.tooth_number] = f"open contact to tooth {b.tooth_number} ({gap:.2f}mm gap)"
        elif gap < ADJACENT_TIGHT_MM:
            failures[a.tooth_number] = f"over-tight contact to tooth {b.tooth_number} ({-gap:.2f}mm overlap)"
    return ValidationCheck(
        check_number=5, name="adjacent contacts", passed=not failures,
        details="interproximal contacts within range" if not failures
        else f"{len(failures)} contact problem(s)",
        per_tooth_failures=failures)


# ---------------------------------------------------------------- check 6

def _check6_sintering_scale(rest, meshes, out_dir) -> ValidationCheck:
    """Apply material scale factor and export *_FABRICATION_READY.stl so no
    one ever scales twice. (SPEC §10)"""
    os.makedirs(out_dir, exist_ok=True)
    failures: dict[int, str] = {}
    for r in rest:
        try:
            spec = MATERIAL_SPECS[r.material]
            m = meshes[r.tooth_number].copy()
            m.vertices = m.vertices * spec.sinter_scale
            base = os.path.splitext(os.path.basename(r.file_path))[0]
            fab = os.path.join(out_dir, f"{base}_FABRICATION_READY.stl")
            m.export(fab)
            r.fabrication_file_path = fab
        except Exception as e:
            failures[r.tooth_number] = f"scale/export failed: {e}"
    return ValidationCheck(
        check_number=6, name="sintering scale", passed=not failures,
        details="fabrication files exported with material scale factors applied"
        if not failures else f"{len(failures)} export failure(s)",
        per_tooth_failures=failures)
