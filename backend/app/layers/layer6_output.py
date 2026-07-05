"""Layer 6b — Output package. (DEV_PLAN Step 8, SPEC §4.6, §12)

One ZIP: per-restoration fabrication STLs, full-arch assembly, verification
model (both arches in simulated bite), PDF case report, plain-text README
with the clinical-verification disclaimer.
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
from datetime import datetime, timezone

import trimesh

from ..models.schemas import (
    Case, GeneratedRestoration, ValidationReport,
)

log = logging.getLogger(__name__)

README_TEXT = """AI DENTAL CAD — FABRICATION PACKAGE
Case reference: {ref}
Generated: {date}

IMPORTANT — CLINICAL VERIFICATION REQUIRED

These files are the output of an AI design aid. They are NOT final medical
devices. Every restoration must be reviewed and approved by a licensed
clinician before fabrication and fitting. See the case report PDF for the
"Clinical verification required" section, including any teeth that need
physical preparation before a restoration can be seated.

Files with the _FABRICATION_READY suffix already include the material
sintering compensation (zirconia ×1.22). DO NOT SCALE THEM AGAIN.

Contents:
- Crown_*_FABRICATION_READY.stl  — individual restorations, ready to mill/print
- assembly_all_restorations.stl  — all restorations in arch position (design scale)
- verification_bite_model.stl    — arches + restorations in simulated bite (design scale)
- case_report.pdf                — full clinical case report
"""


def build_assembly(restorations: list[GeneratedRestoration], out_path: str) -> str | None:
    meshes = [trimesh.load(r.file_path, force="mesh")
              for r in restorations if not r.failed and r.file_path]
    if not meshes:
        return None
    combined = trimesh.util.concatenate(meshes)
    combined.export(out_path)
    return out_path


def build_verification_model(restorations: list[GeneratedRestoration],
                             upper_scan: str | None, lower_scan: str | None,
                             out_path: str) -> str | None:
    parts = []
    for p in (upper_scan, lower_scan):
        if p and os.path.exists(p):
            parts.append(trimesh.load(p, force="mesh"))
    parts += [trimesh.load(r.file_path, force="mesh")
              for r in restorations if not r.failed and r.file_path]
    if not parts:
        return None
    trimesh.util.concatenate(parts).export(out_path)
    return out_path


def build_pdf_report(case: Case, report_text: str, out_path: str) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    from reportlab.lib import colors

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey)

    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    story = [
        Paragraph("Clinical Case Report", h1),
        Paragraph(f"Case {case.reference} — generated "
                  f"{datetime.now(timezone.utc).strftime('%d %B %Y %H:%M UTC')}", small),
        Paragraph("AI design aid output — every restoration requires clinical "
                  "review and approval by a licensed dentist before use.", small),
        Spacer(1, 6 * mm),
    ]
    for para in report_text.split("\n\n"):
        story.append(Paragraph(para.replace("\n", " "), body))
        story.append(Spacer(1, 3 * mm))

    if case.validation:
        story.append(Paragraph("Validation summary", h2))
        rows = [["#", "Check", "Result", "Details"]]
        for c in case.validation.checks:
            rows.append([str(c.check_number), c.name,
                         "PASS" if c.passed else "FAIL", c.details[:90]])
        t = Table(rows, colWidths=[8 * mm, 38 * mm, 16 * mm, 110 * mm])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)

    if case.plan:
        story.append(Paragraph("Planned restorations", h2))
        rows = [["Tooth", "Restoration", "Material", "Needs preparation", "Override"]]
        for r in case.plan.restorations:
            rows.append([str(r.tooth_number), r.restoration_type.value,
                         r.material.value,
                         "yes" if r.needs_physical_preparation else "no",
                         "yes" if r.user_override else "no"])
        t = Table(rows, colWidths=[14 * mm, 40 * mm, 40 * mm, 34 * mm, 22 * mm])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ]))
        story.append(t)

    doc.build(story)
    return out_path


def build_package(case: Case, report_text: str, work_dir: str) -> str:
    """Assemble the final ZIP. Returns its path."""
    os.makedirs(work_dir, exist_ok=True)

    assembly = build_assembly(case.restorations,
                              os.path.join(work_dir, "assembly_all_restorations.stl"))
    upper = next((s.file_path for s in case.scans if s.arch.value == "upper"), None)
    lower = next((s.file_path for s in case.scans if s.arch.value == "lower"), None)
    verification = build_verification_model(
        case.restorations, upper, lower,
        os.path.join(work_dir, "verification_bite_model.stl"))
    pdf = build_pdf_report(case, report_text, os.path.join(work_dir, "case_report.pdf"))

    readme = os.path.join(work_dir, "README.txt")
    with open(readme, "w") as f:
        f.write(README_TEXT.format(ref=case.reference,
                                   date=datetime.now(timezone.utc).strftime("%d %B %Y")))

    zip_path = os.path.join(work_dir, f"{case.reference}_package.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for r in case.restorations:
            if r.fabrication_file_path and os.path.exists(r.fabrication_file_path):
                z.write(r.fabrication_file_path,
                        os.path.basename(r.fabrication_file_path))
        for p in (assembly, verification, pdf, readme):
            if p and os.path.exists(p):
                z.write(p, os.path.basename(p))
        z.writestr("case_data.json", json.dumps({
            "reference": case.reference,
            "plan": case.plan.model_dump() if case.plan else None,
            "validation": case.validation.model_dump() if case.validation else None,
        }, indent=2, default=str))
    log.info("package built for case=%s at %s", case.reference, zip_path)
    return zip_path
