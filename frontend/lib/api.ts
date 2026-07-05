// API client for the AI Dental CAD backend.
const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ToothAssessment {
  tooth_number: number;
  condition: string;
  wear_severity: string | null;
  confidence: number;
  observation: string;
}

export interface PlannedRestoration {
  tooth_number: number;
  restoration_type: string;
  material: string;
  priority: number;
  rationale: string;
  user_override: boolean;
  needs_physical_preparation: boolean;
}

export interface CaseData {
  case_id: string;
  reference: string;
  status: string;
  error: string | null;
  description: string;
  traffic_light: "green" | "yellow" | "red";
  flagged_teeth: number[];
  perception: {
    teeth: ToothAssessment[];
    arch_summary: string;
    vertical_dimension_status: string;
    occlusal_plane_note: string;
    overall_confidence: number;
    visual_analysis_available: boolean;
  } | null;
  plan: {
    restorations: PlannedRestoration[];
    framework: {
      vd_increase_mm: number;
      occlusal_plane_tilt_deg: number;
      incisal_crown_length_mm: number;
      symmetric: boolean;
    };
    plan_summary: string;
    sanity_violations: string[];
  } | null;
  restorations: {
    tooth_number: number;
    restoration_type: string;
    material: string;
    failed: boolean;
  }[];
  validation: {
    all_passed: boolean;
    checks: { check_number: number; name: string; passed: boolean; details: string }[];
  } | null;
}

export async function createCase(upper: File | null, lower: File | null, description: string) {
  const fd = new FormData();
  if (upper) fd.append("upper", upper);
  if (lower) fd.append("lower", lower);
  fd.append("description", description);
  const r = await fetch(`${BASE}/cases`, { method: "POST", body: fd });
  if (!r.ok) throw new Error((await r.json()).detail || "Upload failed");
  return r.json() as Promise<{ case_id: string; reference: string }>;
}

export async function getCase(caseId: string): Promise<CaseData> {
  const r = await fetch(`${BASE}/cases/${caseId}`, { cache: "no-store" });
  if (!r.ok) throw new Error("Case not found");
  return r.json();
}

export async function confirmAssessment(
  caseId: string,
  corrections: { tooth_number: number; condition: string; note?: string }[]
) {
  const r = await fetch(`${BASE}/cases/${caseId}/confirm-assessment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corrections),
  });
  if (!r.ok) throw new Error((await r.json()).detail || "Confirmation failed");
  return r.json();
}

export async function overridePlan(
  caseId: string,
  o: { tooth_number: number; restoration_type?: string; material?: string; remove?: boolean }
) {
  const r = await fetch(`${BASE}/cases/${caseId}/plan/override`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(o),
  });
  if (!r.ok) throw new Error((await r.json()).detail || "Override failed");
  return r.json();
}

export async function approvePlan(caseId: string) {
  const r = await fetch(`${BASE}/cases/${caseId}/approve`, { method: "POST" });
  if (!r.ok) throw new Error((await r.json()).detail || "Approval failed");
  return r.json();
}

export function downloadUrl(caseId: string) {
  return `${BASE}/cases/${caseId}/download`;
}

export function renderUrl(caseId: string, view: string) {
  return `${BASE}/cases/${caseId}/renders/${view}`;
}
