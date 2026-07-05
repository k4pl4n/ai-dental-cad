"use client";
// Screen 3 — Treatment Plan Review (SPEC §5.3). Colour-coded plan, per-tooth
// Edit for overrides, framework in plain English, one Approve button.
// This is the only screen where technical overrides live.
import { useState } from "react";
import { CaseData, approvePlan, overridePlan } from "../lib/api";
import ToothChart from "./ToothChart";

const TYPES = ["full_crown", "veneer", "inlay", "onlay", "bridge_pontic", "implant_crown"];
const MATERIALS = ["zirconia", "zirconia_layered", "lithium_disilicate", "pmma", "cobalt_chrome", "composite"];

export default function Screen3Plan({ data, onRefresh, onBack }: {
  data: CaseData; onRefresh: () => void; onBack: () => void;
}) {
  const plan = data.plan!;
  const p = data.perception!;
  const fw = plan.framework;
  const upper = p.teeth.some((t) => t.tooth_number <= 16);
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function approve() {
    setBusy(true); setErr("");
    try { await approvePlan(data.case_id); await onRefresh(); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  }

  const frameworkPlain = [
    fw.vd_increase_mm > 0
      ? `The bite will be opened by ${fw.vd_increase_mm}mm to restore lost height.`
      : "The current bite height will be kept.",
    Math.abs(fw.occlusal_plane_tilt_deg) > 0.01
      ? `The biting plane will be tilted ${fw.occlusal_plane_tilt_deg}° to level it.`
      : "The biting plane is level and will be kept as it is.",
    `Front teeth will be built to ${fw.incisal_crown_length_mm}mm crown length.`,
    fw.symmetric ? "Left and right sides will mirror each other." : "The sides are designed independently.",
  ].join(" ");

  return (
    <>
      <h1>Case {data.reference} — proposed treatment plan</h1>
      <p className="sub">{plan.plan_summary}</p>
      {err && <div className="alert error">{err}</div>}
      {plan.sanity_violations.length > 0 && (
        <div className="alert error">
          This plan needs manual review before it can be approved: {plan.sanity_violations.join("; ")}
        </div>
      )}

      <div className="grid2">
        <div className="card">
          <h2>Planned restorations</h2>
          <ToothChart teeth={p.teeth} plan={plan.restorations} upperArch={upper} />
        </div>
        <div className="card">
          <h2>How the arch will be rebuilt</h2>
          <p className="prose">{frameworkPlain}</p>
        </div>
      </div>

      <div className="card">
        <table className="plan">
          <thead>
            <tr><th>Tooth</th><th>Restoration</th><th>Material</th><th>Notes</th><th /></tr>
          </thead>
          <tbody>
            {plan.restorations
              .slice()
              .sort((a, b) => a.tooth_number - b.tooth_number)
              .map((r) => (
                <tr key={r.tooth_number}>
                  <td><strong>{r.tooth_number}</strong></td>
                  <td>{r.restoration_type.replace(/_/g, " ")}{r.user_override ? " (edited)" : ""}</td>
                  <td>{r.material.replace(/_/g, " ")}</td>
                  <td style={{ color: "var(--muted)", fontSize: 13 }}>
                    {r.needs_physical_preparation ? "Tooth must be prepared before fitting. " : ""}
                    {r.rationale}
                  </td>
                  <td><button className="btn secondary" style={{ padding: "6px 14px", fontSize: 13 }}
                              onClick={() => setEditing(r.tooth_number)}>Edit</button></td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <button className="btn secondary" onClick={onBack}>Back</button>
        <button className="btn big" disabled={busy || plan.sanity_violations.length > 0} onClick={approve}>
          {busy ? "Starting design…" : "Approve Plan and Start Design"}
        </button>
      </div>

      {editing !== null && (
        <EditModal
          caseId={data.case_id}
          restoration={plan.restorations.find((r) => r.tooth_number === editing)!}
          onClose={async (changed) => { setEditing(null); if (changed) await onRefresh(); }}
        />
      )}
    </>
  );
}

function EditModal({ caseId, restoration, onClose }: {
  caseId: string;
  restoration: { tooth_number: number; restoration_type: string; material: string };
  onClose: (changed: boolean) => void;
}) {
  const [type, setType] = useState(restoration.restoration_type);
  const [material, setMaterial] = useState(restoration.material);
  const [busy, setBusy] = useState(false);

  async function save(remove: boolean) {
    setBusy(true);
    await overridePlan(caseId, remove
      ? { tooth_number: restoration.tooth_number, remove: true }
      : { tooth_number: restoration.tooth_number, restoration_type: type, material });
    onClose(true);
  }

  return (
    <div className="modal-back" onClick={() => onClose(false)}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Tooth {restoration.tooth_number}</h2>
        <label>Restoration type</label>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
        </select>
        <label>Material</label>
        <select value={material} onChange={(e) => setMaterial(e.target.value)}>
          {MATERIALS.map((m) => <option key={m} value={m}>{m.replace(/_/g, " ")}</option>)}
        </select>
        <div className="row">
          <button className="btn secondary" disabled={busy} onClick={() => save(true)}>
            Remove from plan
          </button>
          <button className="btn" disabled={busy} onClick={() => save(false)}>Save</button>
        </div>
      </div>
    </div>
  );
}
