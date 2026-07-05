"""Pipeline orchestrator — runs the six layers with the failure handling
from DEV_PLAN Part 6. Owns case status transitions and audit logging.

Flow (matches the five screens):
  analyse()  : L1 ingest → L2 render+perceive → confidence gate → L3 plan
  design()   : L4 framework → L5 generate → L6 validate → report → package
"""
from __future__ import annotations

import json
import logging
import os
import traceback

from ..layers import (
    layer1_bite, layer1_ingestion, layer2_perception, layer3_reasoning,
    layer4_framework, layer5_generation, layer6_output, layer6_validation,
)
from ..models.schemas import (
    Arch, AuditEvent, Case, CaseStatus,
    CONFIDENCE_HALT_THRESHOLD,
)
from ..prompts.report import build_report_prompt
from . import claude_client, store

log = logging.getLogger(__name__)


def _audit(case: Case, event: str, detail: str) -> None:
    store.add_audit(AuditEvent(case_id=case.case_id, event=event, detail=detail))


def _set_status(case: Case, status: CaseStatus) -> None:
    case.status = status
    _audit(case, "status_change", status.value)
    store.save_case(case)


def case_dir(case: Case, *parts: str) -> str:
    d = os.path.join(store.DATA_DIR, "cases", case.case_id, *parts)
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------- analyse

def analyse(case: Case, upper_path: str | None, lower_path: str | None) -> Case:
    """Screen 1 → Screen 2/3. Ingest, perceive, plan."""
    _set_status(case, CaseStatus.ANALYSING)
    try:
        # Layer 1 — ingestion (fail = stop, clear error, no partial results)
        for path, label in ((upper_path, "upper"), (lower_path, "lower")):
            if not path:
                continue
            scan = layer1_ingestion.ingest(
                path, case.case_id, case_dir(case, "scans"),
                original_filename=os.path.basename(path),
                expected_arch=Arch(label))
            case.scans.append(scan)
            _audit(case, "ai_decision",
                   f"ingested {label} file as {scan.arch.value} arch "
                   f"({scan.metrics.vertex_count:,} vertices)")
        if not case.scans:
            raise layer1_ingestion.IngestionError("No scan file was provided.")

        # Bite: measured from the RAW pair in the scanner's registered frame
        if upper_path and lower_path:
            case.bite_metrics = layer1_bite.measure_bite(upper_path, lower_path)
            if case.bite_metrics:
                _audit(case, "ai_decision", f"bite measured: {case.bite_metrics}")

        primary = _primary_scan(case)

        # Layer 2 — perception
        perception = layer2_perception.perceive(
            primary, case_dir(case, "renders"), case.description)
        case.perception = perception
        _audit(case, "ai_decision",
               f"perception complete, overall confidence {perception.overall_confidence}")

        # Confidence gate (PLAN Part 6)
        if perception.overall_confidence < CONFIDENCE_HALT_THRESHOLD:
            _set_status(case, CaseStatus.ASSESSMENT_REVIEW)
            return case

        # Layer 3 — reasoning (with measured bite context when available)
        plan = layer3_reasoning.plan_treatment(perception, case.description,
                                               bite_metrics=case.bite_metrics)
        case.plan = plan
        _audit(case, "ai_decision",
               f"plan produced: {len(plan.restorations)} restorations, "
               f"VD +{plan.framework.vd_increase_mm}mm"
               + (f", SANITY VIOLATIONS: {plan.sanity_violations}"
                  if plan.sanity_violations else ""))

        _set_status(case, CaseStatus.PLAN_REVIEW)
    except layer1_ingestion.IngestionError as e:
        case.error = str(e)
        _set_status(case, CaseStatus.FAILED)
    except Exception as e:
        log.error("analyse failed case=%s: %s\n%s", case.case_id, e, traceback.format_exc())
        case.error = "Analysis failed. Please try again or contact support."
        _set_status(case, CaseStatus.FAILED)
    return case


def _primary_scan(case: Case):
    for s in case.scans:
        if s.arch == Arch.UPPER:
            return s
    return case.scans[0]


# ---------------------------------------------------------------- design

def design(case: Case) -> Case:
    """Screen 3 approve → Screen 4/5. Framework, generation, validation,
    report, package."""
    if not case.plan or not case.perception:
        case.error = "No approved plan on this case."
        _set_status(case, CaseStatus.FAILED)
        return case
    if case.plan.sanity_violations:
        case.error = ("The plan violates safety constraints and requires manual review: "
                      + "; ".join(case.plan.sanity_violations))
        _set_status(case, CaseStatus.PLAN_REVIEW)
        return case

    _set_status(case, CaseStatus.DESIGNING)
    try:
        primary = _primary_scan(case)

        # Layer 4
        framework = layer4_framework.build_framework(
            primary, case.plan.framework,
            [r.tooth_number for r in case.plan.restorations])
        _audit(case, "ai_decision",
               f"framework built, target VD z={framework.target_vd_z:.2f}mm")

        # Layer 5
        case.restorations = layer5_generation.generate_all(
            case.plan.restorations, framework, primary.file_path,
            case_dir(case, "restorations"))
        failed = [r.tooth_number for r in case.restorations if r.failed]
        if failed:
            _audit(case, "ai_decision", f"generation failures on teeth {failed}")

        # Layer 6 — validation
        opposing = next((s.file_path for s in case.scans if s.arch != primary.arch), None)
        case.validation = layer6_validation.validate_all(
            case.restorations, framework, opposing, case_dir(case, "fabrication"))

        # Case report (third Claude call)
        report_text = _generate_report(case)

        # Package
        case.package_path = layer6_output.build_package(
            case, report_text, case_dir(case, "package"))

        _set_status(case, CaseStatus.COMPLETE)
    except Exception as e:
        log.error("design failed case=%s: %s\n%s", case.case_id, e, traceback.format_exc())
        case.error = "Design generation failed. The case has been flagged for review."
        _set_status(case, CaseStatus.FAILED)
    return case


def _generate_report(case: Case) -> str:
    prep_teeth = [r.tooth_number for r in case.plan.restorations
                  if r.needs_physical_preparation]
    uncertain = layer2_perception.flagged_teeth(case.perception)
    prompt = build_report_prompt(
        perception_summary=case.perception.arch_summary,
        plan_json=json.dumps(case.plan.model_dump(), default=str, indent=1),
        framework_json=json.dumps(case.plan.framework.model_dump(), default=str),
        validation_json=json.dumps(case.validation.model_dump(), default=str, indent=1),
        prep_teeth=prep_teeth, uncertain_teeth=uncertain)
    try:
        return claude_client.report_call(prompt)
    except Exception as e:
        log.warning("report generation failed: %s — using structured fallback", e)
        return (f"Automated narrative unavailable. {case.perception.arch_summary} "
                f"Planned: {len(case.plan.restorations)} restorations. "
                f"Teeth requiring physical preparation: {prep_teeth or 'none'}. "
                "All restorations require clinical review before use.")


# --------------------------------------------------------- status helpers

def traffic_light(case: Case) -> str:
    """Green ready / yellow read-the-notes / red regenerate. NEVER green
    when any validation check failed. (PLAN Part 6)"""
    if case.status == CaseStatus.FAILED or case.validation is None:
        return "red"
    if not case.validation.all_passed:
        return "red" if sum(1 for c in case.validation.checks if not c.passed) > 1 else "yellow"
    if any(r.failed for r in case.restorations):
        return "yellow"
    if any(r.needs_physical_preparation for r in (case.plan.restorations if case.plan else [])):
        return "yellow"
    return "green"
