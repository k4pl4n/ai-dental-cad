"""FastAPI application — the API behind the five screens. (SPEC §5)

POST /cases                         upload + analyse        (Screen 1)
GET  /cases/{id}                    full case state         (all screens)
POST /cases/{id}/confirm-assessment low-confidence gate     (Screen 2)
POST /cases/{id}/plan/override      per-tooth edit          (Screen 3)
POST /cases/{id}/approve            approve → design        (Screen 3→4)
GET  /cases/{id}/download           the ZIP                 (Screen 5)
GET  /cases/{id}/renders/{view}     rendered view PNGs
GET  /health
"""
from __future__ import annotations

import logging
import os
import shutil
import threading

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .layers import layer2_perception, layer3_reasoning
from .models.schemas import AuditEvent, Case, CaseStatus, Correction
from .services import pipeline, store

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aidcad")

app = FastAPI(title="AI Dental CAD", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("AIDCAD_CORS", "http://localhost:3000").split(","),
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------ screen 1

@app.post("/cases")
async def create_case(background: BackgroundTasks,
                      upper: UploadFile | None = File(None),
                      lower: UploadFile | None = File(None),
                      description: str = Form("")):
    if upper is None and lower is None:
        raise HTTPException(422, "Upload at least one arch scan (STL or PLY).")
    case = Case(description=description[:2000])
    store.save_case(case)
    store.add_audit(AuditEvent(case_id=case.case_id, event="upload",
                               detail=f"upper={getattr(upper,'filename',None)} "
                                      f"lower={getattr(lower,'filename',None)}"))

    updir = pipeline.case_dir(case, "uploads")
    paths = []
    for uf, name in ((upper, "upper"), (lower, "lower")):
        if uf is None:
            paths.append(None)
            continue
        ext = os.path.splitext(uf.filename or "")[1].lower() or ".stl"
        p = os.path.join(updir, f"{name}{ext}")
        with open(p, "wb") as f:
            shutil.copyfileobj(uf.file, f)
        paths.append(p)

    background.add_task(pipeline.analyse, case, paths[0], paths[1])
    return {"case_id": case.case_id, "reference": case.reference,
            "status": CaseStatus.ANALYSING.value}


# ----------------------------------------------------------- case state

@app.get("/cases")
def list_cases():
    return store.list_cases()


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    case = store.load_case(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    d = case.model_dump(mode="json")
    d["traffic_light"] = pipeline.traffic_light(case)
    d["flagged_teeth"] = (layer2_perception.flagged_teeth(case.perception)
                          if case.perception else [])
    return d


# ------------------------------------------------------------ screen 2

class AssessmentCorrection(BaseModel):
    tooth_number: int
    condition: str
    note: str = ""


@app.post("/cases/{case_id}/confirm-assessment")
def confirm_assessment(case_id: str, corrections: list[AssessmentCorrection]):
    """Dentist confirms/corrects flagged teeth, then planning proceeds."""
    case = _require(case_id, {CaseStatus.ASSESSMENT_REVIEW, CaseStatus.PLAN_REVIEW})
    for corr in corrections:
        for t in case.perception.teeth:
            if t.tooth_number == corr.tooth_number:
                store.add_correction(Correction(
                    case_id=case_id, correction_type="perception",
                    tooth_number=corr.tooth_number,
                    original_value=t.condition.value, corrected_value=corr.condition))
                t.condition = corr.condition
                t.confidence = 1.0
                t.observation += f" [clinician: {corr.note or 'confirmed'}]"
    case.perception.overall_confidence = 1.0
    plan = layer3_reasoning.plan_treatment(case.perception, case.description)
    case.plan = plan
    case.status = CaseStatus.PLAN_REVIEW
    store.save_case(case)
    return {"status": case.status.value}


# ------------------------------------------------------------ screen 3

class PlanOverride(BaseModel):
    tooth_number: int
    restoration_type: str | None = None
    material: str | None = None
    remove: bool = False


@app.post("/cases/{case_id}/plan/override")
def override_plan(case_id: str, override: PlanOverride):
    case = _require(case_id, {CaseStatus.PLAN_REVIEW})
    try:
        case.plan, orig, corrected = layer3_reasoning.apply_override(
            case.plan, override.tooth_number,
            override.restoration_type, override.material, override.remove)
    except layer3_reasoning.PlanningError as e:
        raise HTTPException(422, str(e))
    store.add_correction(Correction(
        case_id=case_id, correction_type="plan", tooth_number=override.tooth_number,
        original_value=orig, corrected_value=corrected))
    store.add_audit(AuditEvent(case_id=case_id, event="user_override",
                               detail=f"tooth {override.tooth_number}: {orig} → {corrected}"))
    store.save_case(case)
    return {"plan": case.plan.model_dump(mode="json")}


@app.post("/cases/{case_id}/approve")
def approve_plan(case_id: str, background: BackgroundTasks):
    case = _require(case_id, {CaseStatus.PLAN_REVIEW})
    if case.plan.sanity_violations:
        raise HTTPException(422, "Plan has safety violations and cannot be approved: "
                                 + "; ".join(case.plan.sanity_violations))
    case.plan.approved = True
    store.add_audit(AuditEvent(case_id=case_id, event="plan_approved",
                               detail=f"{len(case.plan.restorations)} restorations"))
    store.save_case(case)
    background.add_task(pipeline.design, case)
    return {"status": CaseStatus.DESIGNING.value}


# ------------------------------------------------------------ screen 5

@app.get("/cases/{case_id}/download")
def download(case_id: str):
    case = _require(case_id, {CaseStatus.COMPLETE})
    if not case.package_path or not os.path.exists(case.package_path):
        raise HTTPException(404, "Package not found")
    store.add_audit(AuditEvent(case_id=case_id, event="download",
                               detail=os.path.basename(case.package_path)))
    return FileResponse(case.package_path, filename=os.path.basename(case.package_path),
                        media_type="application/zip")


@app.get("/cases/{case_id}/renders/{view}")
def render_image(case_id: str, view: str):
    if view not in ("occlusal", "buccal_right", "buccal_left", "anterior", "diagonal"):
        raise HTTPException(404, "Unknown view")
    case = store.load_case(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    p = os.path.join(store.DATA_DIR, "cases", case.case_id, "renders", f"{view}.png")
    if not os.path.exists(p):
        raise HTTPException(404, "Render not available")
    return FileResponse(p, media_type="image/png")


def _require(case_id: str, statuses: set[CaseStatus]) -> Case:
    case = store.load_case(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    if case.status not in statuses:
        raise HTTPException(409, f"Case is in status '{case.status.value}'")
    return case
