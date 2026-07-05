"""Layer 2b — Perception. (DEV_PLAN Step 3, SPEC §4.2)

Renders the ingested mesh to five clinical views, sends them to Claude
Vision with the strict clinical prompt, validates the response against
the seven-category taxonomy.

Output: PerceptionResult — per-tooth condition + overall arch summary.
"""
from __future__ import annotations

import json
import logging

from ..models.schemas import (
    Arch, IngestedScan, PerceptionResult, ToothAssessment,
    CONFIDENCE_FLAG_THRESHOLD,
)
from ..prompts.perception import build_perception_prompt
from ..services import claude_client
from . import layer2_rendering

log = logging.getLogger(__name__)


def tooth_range_for(arch: Arch) -> tuple[int, int]:
    """Universal Numbering System: upper 1–16, lower 17–32. (SPEC Appendix B)"""
    return (1, 16) if arch == Arch.UPPER else (17, 32)


class PerceptionError(Exception):
    pass


def perceive(scan: IngestedScan, render_dir: str, dentist_note: str = "") -> PerceptionResult:
    lo, hi = tooth_range_for(scan.arch)

    # -- render ------------------------------------------------------------
    visual = True
    try:
        image_paths, renderer = layer2_rendering.render_five_views(scan.file_path, render_dir)
        log.info("rendered 5 views for case=%s via %s", scan.case_id, renderer)
    except layer2_rendering.RenderingError as e:
        # PLAN Part 6: fallback to mesh-metrics-only, flag prominently.
        log.error("rendering failed for case=%s: %s", scan.case_id, e)
        return _metrics_only_result(scan, lo, hi)

    # -- vision call ---------------------------------------------------------
    prompt = build_perception_prompt(scan.arch.value, f"{lo}-{hi}", dentist_note)
    raw, model_version = claude_client.perception_call(prompt, image_paths,
                                                       tooth_range=(lo, hi))

    # -- validate ------------------------------------------------------------
    teeth = _validate_teeth(raw, lo, hi)
    overall = sum(t.confidence for t in teeth) / max(len(teeth), 1)

    return PerceptionResult(
        case_id=scan.case_id,
        arch=scan.arch,
        teeth=teeth,
        arch_summary=str(raw.get("arch_summary", "")),
        vertical_dimension_status=str(raw.get("vertical_dimension_status", "unknown")),
        occlusal_plane_note=str(raw.get("occlusal_plane_note", "")),
        scan_quality_issues=[str(s) for s in raw.get("scan_quality_issues", [])],
        model_version=model_version,
        overall_confidence=round(overall, 3),
        visual_analysis_available=visual,
    )


def _validate_teeth(raw: dict, lo: int, hi: int) -> list[ToothAssessment]:
    if "teeth" not in raw or not isinstance(raw["teeth"], list):
        raise PerceptionError("perception response missing 'teeth' array")
    by_number: dict[int, ToothAssessment] = {}
    for entry in raw["teeth"]:
        try:
            t = ToothAssessment(**{k: entry.get(k) for k in
                                   ("tooth_number", "condition", "wear_severity",
                                    "confidence", "observation")})
        except Exception as e:
            raise PerceptionError(f"invalid tooth entry {entry!r}: {e}") from e
        if lo <= t.tooth_number <= hi:
            by_number[t.tooth_number] = t
    # never allow skipped teeth — systematic sweep is enforced here too
    missing_positions = [n for n in range(lo, hi + 1) if n not in by_number]
    if missing_positions:
        raise PerceptionError(f"perception skipped tooth positions: {missing_positions}")
    return [by_number[n] for n in range(lo, hi + 1)]


def flagged_teeth(result: PerceptionResult) -> list[int]:
    """Teeth below the per-tooth confidence threshold → clinician confirmation."""
    return [t.tooth_number for t in result.teeth
            if t.confidence < CONFIDENCE_FLAG_THRESHOLD]


def _metrics_only_result(scan: IngestedScan, lo: int, hi: int) -> PerceptionResult:
    """Degraded mode: visual analysis unavailable. Everything flagged."""
    teeth = [ToothAssessment(tooth_number=n, condition="natural_healthy",
                             confidence=0.0,
                             observation="Visual analysis unavailable — mesh metrics only. Clinician must classify.")
             for n in range(lo, hi + 1)]
    return PerceptionResult(
        case_id=scan.case_id, arch=scan.arch, teeth=teeth,
        arch_summary=("VISUAL ANALYSIS UNAVAILABLE. Assessment is based on mesh metrics only "
                      f"(area {scan.metrics.surface_area_mm2:.0f}mm², "
                      f"{scan.metrics.vertex_count:,} vertices). "
                      "All tooth classifications require manual entry."),
        vertical_dimension_status="unknown",
        occlusal_plane_note="unknown",
        scan_quality_issues=["rendering pipeline unavailable"],
        model_version="none",
        overall_confidence=0.0,
        visual_analysis_available=False,
    )


def perception_to_json(result: PerceptionResult) -> str:
    """Compact JSON for feeding into the planning prompt."""
    return json.dumps({
        "arch": result.arch.value,
        "teeth": [t.model_dump() for t in result.teeth],
        "arch_summary": result.arch_summary,
        "vertical_dimension_status": result.vertical_dimension_status,
        "occlusal_plane_note": result.occlusal_plane_note,
    }, indent=1, default=str)
