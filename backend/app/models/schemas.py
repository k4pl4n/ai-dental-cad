"""Core data model — mirrors PRODUCT_SPEC.md §8.

Every object that crosses a layer boundary is defined here.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- enums

class ToothCondition(str, enum.Enum):
    """The seven exact categories. Nothing else. (SPEC §4.2)"""
    NATURAL_HEALTHY = "natural_healthy"
    NATURAL_WORN = "natural_worn"            # severity in ToothAssessment.wear_severity
    NATURAL_CARIES_FRACTURE = "natural_caries_fracture"
    IMPLANT_FIXTURE = "implant_fixture"
    ROOT_STUMP = "root_stump"
    PREP_STUMP = "prep_stump"
    MISSING = "missing"


class WearSeverity(str, enum.Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class RestorationType(str, enum.Enum):
    FULL_CROWN = "full_crown"
    VENEER = "veneer"
    INLAY = "inlay"
    ONLAY = "onlay"
    BRIDGE_PONTIC = "bridge_pontic"
    IMPLANT_CROWN = "implant_crown"


class Material(str, enum.Enum):
    ZIRCONIA = "zirconia"
    ZIRCONIA_LAYERED = "zirconia_layered"
    LITHIUM_DISILICATE = "lithium_disilicate"
    PMMA = "pmma"
    COBALT_CHROME = "cobalt_chrome"
    COMPOSITE = "composite"


class Arch(str, enum.Enum):
    UPPER = "upper"
    LOWER = "lower"


class CaseStatus(str, enum.Enum):
    UPLOADING = "uploading"
    ANALYSING = "analysing"
    ASSESSMENT_REVIEW = "assessment_review"   # low-confidence gate (SPEC §5 screen 2)
    PLAN_REVIEW = "plan_review"
    DESIGNING = "designing"
    COMPLETE = "complete"
    FAILED = "failed"


# ------------------------------------------------- material specifications

class MaterialSpec(BaseModel):
    min_occlusal_mm: float
    min_axial_mm: float
    sinter_scale: float


MATERIAL_SPECS: dict[Material, MaterialSpec] = {
    Material.ZIRCONIA:           MaterialSpec(min_occlusal_mm=0.5, min_axial_mm=0.5, sinter_scale=1.22),
    Material.ZIRCONIA_LAYERED:   MaterialSpec(min_occlusal_mm=1.0, min_axial_mm=0.5, sinter_scale=1.22),
    Material.LITHIUM_DISILICATE: MaterialSpec(min_occlusal_mm=1.0, min_axial_mm=0.6, sinter_scale=1.0),
    Material.PMMA:               MaterialSpec(min_occlusal_mm=1.5, min_axial_mm=1.0, sinter_scale=1.0),
    Material.COBALT_CHROME:      MaterialSpec(min_occlusal_mm=0.3, min_axial_mm=0.3, sinter_scale=1.0),
    Material.COMPOSITE:          MaterialSpec(min_occlusal_mm=1.5, min_axial_mm=1.0, sinter_scale=1.0),
}


# ---------------------------------------------------------------- layer 1

class MeshMetrics(BaseModel):
    vertex_count: int
    face_count: int
    surface_area_mm2: float
    volume_mm3: float
    watertight: bool
    hole_count: int
    non_manifold_edges: int


class ArchMeasurements(BaseModel):
    mesiodistal_width_mm: float      # posterior-to-posterior
    anteroposterior_depth_mm: float
    max_occlusal_z_mm: float         # current maximum Z (framework input)
    centroid: list[float]            # [x, y, z] after normalisation


class IngestedScan(BaseModel):
    scan_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    case_id: str
    arch: Arch
    file_path: str                   # normalised mesh on disk
    original_filename: str
    metrics: MeshMetrics
    measurements: ArchMeasurements
    repairs_applied: list[str] = []


# ---------------------------------------------------------------- layer 2

class ToothAssessment(BaseModel):
    tooth_number: int = Field(ge=1, le=32)   # Universal Numbering System
    condition: ToothCondition
    wear_severity: Optional[WearSeverity] = None
    confidence: float = Field(ge=0.0, le=1.0)
    observation: str


class PerceptionResult(BaseModel):
    case_id: str
    arch: Arch
    teeth: list[ToothAssessment]
    arch_summary: str
    vertical_dimension_status: str
    occlusal_plane_note: str
    scan_quality_issues: list[str] = []
    model_version: str
    overall_confidence: float
    visual_analysis_available: bool = True   # False = mesh-metrics-only fallback (PLAN Part 6)


CONFIDENCE_FLAG_THRESHOLD = 0.75   # per-tooth: below this → clinician confirmation
CONFIDENCE_HALT_THRESHOLD = 0.60   # overall: below this → do not proceed to planning


# ---------------------------------------------------------------- layer 3

class PlannedRestoration(BaseModel):
    tooth_number: int = Field(ge=1, le=32)
    restoration_type: RestorationType
    material: Material
    priority: int = Field(ge=1, le=4)        # 1 molars … 4 incisors
    rationale: str = ""
    user_override: bool = False
    needs_physical_preparation: bool = False  # worn-but-unprepared teeth (PLAN Step 6)


class FrameworkParameters(BaseModel):
    vd_increase_mm: float = Field(ge=0.0, le=8.0)          # sanity max 8mm
    occlusal_plane_tilt_deg: float = Field(ge=-15.0, le=15.0)
    incisal_crown_length_mm: float = Field(gt=0.0, le=12.0)  # sanity max 12mm
    symmetric: bool
    symmetry_rationale: str = ""


class TreatmentPlan(BaseModel):
    case_id: str
    restorations: list[PlannedRestoration]
    framework: FrameworkParameters
    plan_summary: str = ""
    approved: bool = False
    sanity_violations: list[str] = []


MAX_RESTORATIONS_PER_ARCH = 16


# ---------------------------------------------------------------- layer 4

class ToothTarget(BaseModel):
    tooth_number: int
    position: list[float]            # arch-curve anchor point [x, y, z]
    target_occlusal_z: float         # posteriors: must reach this ± 0.5mm
    target_incisal_point: Optional[list[float]] = None   # anteriors only
    mesiodistal_width_mm: float
    tangent_deg: float = 0.0         # local arch-curve direction at this tooth
    mirrored_from: Optional[int] = None


class FrameworkConstraints(BaseModel):
    """Layer 4 output — pure geometry, no AI. Every restoration respects this."""
    case_id: str
    arch: Arch
    target_vd_z: float               # current max Z + vd_increase
    occlusal_plane_point: list[float]
    occlusal_plane_normal: list[float]
    incisal_curve: list[list[float]]  # sampled 3D polyline at target incisal height
    symmetry_axis_x: float           # arch midline (x = const after normalisation)
    tooth_targets: list[ToothTarget]


VD_TOLERANCE_MM = 0.5


# ---------------------------------------------------------------- layers 5–6

class GeneratedRestoration(BaseModel):
    case_id: str
    tooth_number: int
    restoration_type: RestorationType
    material: Material
    file_path: str                   # design-scale STL (pre-sinter-compensation)
    fabrication_file_path: Optional[str] = None  # _FABRICATION_READY.stl
    generation_method: str = "framework"          # framework | parametric_fallback
    failed: bool = False
    failure_reason: Optional[str] = None


class ValidationCheck(BaseModel):
    check_number: int = Field(ge=1, le=6)
    name: str
    passed: bool
    details: str
    per_tooth_failures: dict[int, str] = {}


class ValidationReport(BaseModel):
    case_id: str
    checks: list[ValidationCheck]
    all_passed: bool
    regeneration_attempted: bool = False


# ---------------------------------------------------------------- case & audit

class Correction(BaseModel):
    """Every user override — this is the training-data flywheel. (SPEC §8)"""
    case_id: str
    correction_type: str             # perception | plan | design
    tooth_number: Optional[int] = None
    original_value: str
    corrected_value: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditEvent(BaseModel):
    case_id: str
    event: str                       # ai_decision | user_override | download | status_change …
    detail: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def make_case_ref() -> str:
    return "CAD-" + uuid.uuid4().hex[:6].upper()


class Case(BaseModel):
    case_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    reference: str = Field(default_factory=make_case_ref)
    user_id: str = "dev"
    status: CaseStatus = CaseStatus.UPLOADING
    description: str = ""            # dentist's free-text
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    scans: list[IngestedScan] = []
    perception: Optional[PerceptionResult] = None
    plan: Optional[TreatmentPlan] = None
    restorations: list[GeneratedRestoration] = []
    validation: Optional[ValidationReport] = None
    package_path: Optional[str] = None
    corrections: list[Correction] = []
