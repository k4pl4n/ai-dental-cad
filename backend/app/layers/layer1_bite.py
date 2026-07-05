"""Layer 1b — Bite registration analysis. Pure geometry, no AI.

Intraoral scanners export upper and lower arches in a shared, jaw-related
coordinate frame — the biting position. This module measures that
relationship from the RAW uploaded files (before any normalisation, which
would destroy it).

Ground truth from 5 real full-arch cases (this clinic, 2026):
- before treatment: 0–123 contact points, median interarch ~9–11mm
- after treatment:  190–520 contact points at 0.03–0.09mm, median ~5–7mm
So the design target is: fill the interarch space until proper contact.
"""
from __future__ import annotations

import logging

import numpy as np
import trimesh
from scipy.spatial import cKDTree

log = logging.getLogger(__name__)

CONTACT_MM = 0.5
SAMPLE_POINTS = 8000


def occlusal_axis(upper: trimesh.Trimesh, lower: trimesh.Trimesh) -> int:
    """Axis along which the arches are stacked = smallest relative overlap."""
    ub, lb = upper.bounds, lower.bounds
    scores = []
    for i in range(3):
        overlap = min(ub[1][i], lb[1][i]) - max(ub[0][i], lb[0][i])
        extent = max(ub[1][i], lb[1][i]) - min(ub[0][i], lb[0][i])
        scores.append(overlap / max(extent, 1e-9))
    return int(np.argmin(scores))


def measure_bite(upper_path: str, lower_path: str) -> dict | None:
    """Interarch metrics in the scanner's registered frame. Returns None if
    the two scans clearly don't share a frame (no bounding overlap)."""
    try:
        upper = trimesh.load(upper_path, force="mesh")
        lower = trimesh.load(lower_path, force="mesh")
    except Exception as e:
        log.warning("bite measurement failed to load meshes: %s", e)
        return None

    ub, lb = upper.bounds, lower.bounds
    overlaps = [min(ub[1][i], lb[1][i]) - max(ub[0][i], lb[0][i]) for i in range(3)]
    if min(overlaps) < -20:                          # frames unrelated
        log.warning("scans do not appear bite-registered (no overlap)")
        return {"bite_registered": False}

    up = upper.vertices[::max(len(upper.vertices) // SAMPLE_POINTS, 1)]
    lo = lower.vertices[::max(len(lower.vertices) // SAMPLE_POINTS, 1)]
    d, _ = cKDTree(lo).query(up, k=1)

    ax = occlusal_axis(upper, lower)
    metrics = {
        "bite_registered": True,
        "occlusal_axis": "xyz"[ax],
        "contact_points": int(np.sum(d < CONTACT_MM)),
        "min_interarch_gap_mm": round(float(d.min()), 3),
        "median_interarch_mm": round(float(np.median(d)), 2),
        "p10_interarch_mm": round(float(np.percentile(d, 10)), 2),
    }
    log.info("bite: %s", metrics)
    return metrics


def bite_context_for_prompt(metrics: dict | None) -> str:
    """Human-readable measured-bite block for the planning prompt."""
    if not metrics or not metrics.get("bite_registered"):
        return ""
    return f"""
## Measured bite (from the scanner's registered occlusion — trust these numbers over visual estimates)

- Occlusal contact points within {CONTACT_MM}mm: {metrics['contact_points']} (healthy treated arches show 200–500; near zero means the bite is currently open, e.g. prepped or worn dentition)
- Minimum interarch gap: {metrics['min_interarch_gap_mm']}mm
- Closest 10% of interarch distances: {metrics['p10_interarch_mm']}mm — this approximates the occlusal clearance the restorations must fill to establish contact
- Median interarch distance: {metrics['median_interarch_mm']}mm

Choose vd_increase_mm so that restorations FILL the measured clearance to proper contact: aim for the p10 clearance value, never exceeding the 8mm sanity limit. Reference: in this clinic's completed full-arch cases, restorations reduced the median interarch distance by 3.5–5mm and established 190–520 contacts.
"""
