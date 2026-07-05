"""Layer 3 — Reasoning. (DEV_PLAN Step 4, SPEC §4.3)

Takes perception output + the dentist's note. Produces the treatment plan
and the four framework parameters via Claude. Enforces sanity constraints;
implausible plans are flagged for manual review, never sent to generation.
"""
from __future__ import annotations

import logging

from ..models.schemas import (
    FrameworkParameters, PerceptionResult, PlannedRestoration, TreatmentPlan,
    MAX_RESTORATIONS_PER_ARCH,
)
from ..prompts.planning import build_planning_prompt
from ..services import claude_client
from .layer2_perception import perception_to_json

log = logging.getLogger(__name__)

PRIORITY_BY_POSITION_UPPER = {  # Universal numbering, upper arch
    **{n: 1 for n in (1, 2, 3, 14, 15, 16)},       # molars
    **{n: 2 for n in (4, 5, 12, 13)},              # premolars
    **{n: 3 for n in (6, 11)},                     # canines
    **{n: 4 for n in (7, 8, 9, 10)},               # incisors
}
PRIORITY_BY_POSITION_LOWER = {
    **{n: 1 for n in (17, 18, 19, 30, 31, 32)},
    **{n: 2 for n in (20, 21, 28, 29)},
    **{n: 3 for n in (22, 27)},
    **{n: 4 for n in (23, 24, 25, 26)},
}
PRIORITY_BY_POSITION = {**PRIORITY_BY_POSITION_UPPER, **PRIORITY_BY_POSITION_LOWER}


class PlanningError(Exception):
    pass


def plan_treatment(perception: PerceptionResult, dentist_note: str,
                   bite_metrics: dict | None = None) -> TreatmentPlan:
    from .layer1_bite import bite_context_for_prompt
    prompt = build_planning_prompt(
        perception_to_json(perception), dentist_note, perception.arch.value,
        bite_context=bite_context_for_prompt(bite_metrics))
    raw, _model = claude_client.planning_call(prompt)

    restorations = _parse_restorations(raw)
    framework = _parse_framework(raw)
    violations = check_sanity(restorations, framework)

    plan = TreatmentPlan(
        case_id=perception.case_id,
        restorations=restorations,
        framework=framework,
        plan_summary=str(raw.get("plan_summary", "")),
        sanity_violations=violations,
    )
    if violations:
        log.warning("plan for case=%s flagged for manual review: %s",
                    perception.case_id, violations)
    return plan


def _parse_restorations(raw: dict) -> list[PlannedRestoration]:
    if "restorations" not in raw or not isinstance(raw["restorations"], list):
        raise PlanningError("planning response missing 'restorations' array")
    out = []
    for e in raw["restorations"]:
        try:
            r = PlannedRestoration(
                tooth_number=e["tooth_number"],
                restoration_type=e["restoration_type"],
                material=e["material"],
                priority=e.get("priority") or PRIORITY_BY_POSITION.get(e["tooth_number"], 4),
                rationale=str(e.get("rationale", "")),
                needs_physical_preparation=bool(e.get("needs_physical_preparation", False)),
            )
        except Exception as ex:
            raise PlanningError(f"invalid restoration entry {e!r}: {ex}") from ex
        # priority is positional truth, not model opinion — enforce it
        r.priority = PRIORITY_BY_POSITION.get(r.tooth_number, r.priority)
        out.append(r)
    return out


def _parse_framework(raw: dict) -> FrameworkParameters:
    fw = raw.get("framework")
    if not isinstance(fw, dict):
        raise PlanningError("planning response missing 'framework' object")
    try:
        return FrameworkParameters(
            vd_increase_mm=float(fw["vd_increase_mm"]),
            occlusal_plane_tilt_deg=float(fw["occlusal_plane_tilt_deg"]),
            incisal_crown_length_mm=float(fw["incisal_crown_length_mm"]),
            symmetric=bool(fw["symmetric"]),
            symmetry_rationale=str(fw.get("symmetry_rationale", "")),
        )
    except PlanningError:
        raise
    except Exception as e:
        # Pydantic range violation = sanity violation, handled upstream
        raise PlanningError(f"invalid framework parameters: {e}") from e


def check_sanity(restorations: list[PlannedRestoration],
                 framework: FrameworkParameters) -> list[str]:
    """DEV_PLAN Part 5 sanity constraints. Violation → manual review."""
    v = []
    if len(restorations) > MAX_RESTORATIONS_PER_ARCH:
        v.append(f"{len(restorations)} restorations exceeds max {MAX_RESTORATIONS_PER_ARCH} per arch")
    if framework.vd_increase_mm > 8.0:
        v.append(f"VD increase {framework.vd_increase_mm}mm exceeds 8mm maximum")
    if framework.incisal_crown_length_mm > 12.0:
        v.append(f"incisal crown length {framework.incisal_crown_length_mm}mm exceeds 12mm maximum")
    seen: set[int] = set()
    for r in restorations:
        if r.tooth_number in seen:
            v.append(f"duplicate restoration for tooth {r.tooth_number}")
        seen.add(r.tooth_number)
    return v


def apply_override(plan: TreatmentPlan, tooth_number: int,
                   restoration_type: str | None = None,
                   material: str | None = None,
                   remove: bool = False) -> tuple[TreatmentPlan, str, str]:
    """User override from Screen 3. Returns (plan, original, corrected) for
    the Correction record."""
    for i, r in enumerate(plan.restorations):
        if r.tooth_number == tooth_number:
            original = f"{r.restoration_type.value}/{r.material.value}"
            if remove:
                plan.restorations.pop(i)
                return plan, original, "removed"
            if restoration_type:
                r.restoration_type = restoration_type
            if material:
                r.material = material
            r.user_override = True
            return plan, original, f"{r.restoration_type.value}/{r.material.value}"
    raise PlanningError(f"no planned restoration for tooth {tooth_number}")
