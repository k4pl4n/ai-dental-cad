"use client";
// Screen 2 — Clinical Assessment (SPEC §5.2). What the AI understood,
// before any treatment decisions. Uncertain teeth block Continue until
// the clinician confirms or corrects them.
import { useState } from "react";
import { CaseData, confirmAssessment, renderUrl } from "../lib/api";
import ToothChart from "./ToothChart";

const CONDITIONS = [
  "natural_healthy", "natural_worn", "natural_caries_fracture",
  "implant_fixture", "root_stump", "prep_stump", "missing",
];

export default function Screen2Assessment({ data, onContinue, onRefresh }: {
  data: CaseData; onContinue: () => void; onRefresh: () => void;
}) {
  const p = data.perception!;
  const flagged = data.flagged_teeth || [];
  const needsConfirm = data.status === "assessment_review" || flagged.length > 0;
  const [fixes, setFixes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const upper = p.teeth.some((t) => t.tooth_number <= 16);

  async function proceed() {
    if (needsConfirm) {
      setBusy(true);
      const corrections = flagged.map((n) => ({
        tooth_number: n,
        condition: fixes[n] || p.teeth.find((t) => t.tooth_number === n)!.condition,
      }));
      await confirmAssessment(data.case_id, corrections);
      await onRefresh();
      setBusy(false);
    }
    onContinue();
  }

  return (
    <>
      <h1>Case {data.reference} — clinical assessment</h1>
      <p className="sub">This is what was found in the scan. Hover any tooth for the observation.</p>

      {!p.visual_analysis_available && (
        <div className="alert error">
          Visual analysis was unavailable for this case — the assessment below is based on
          mesh measurements only and must be reviewed tooth by tooth.
        </div>
      )}

      <div className="grid2">
        <div className="card">
          <h2>Arch overview</h2>
          <ToothChart teeth={p.teeth} flagged={flagged} upperArch={upper} />
          <div className="legend">
            <span><span className="dot" style={{ background: "var(--green)" }} />Healthy</span>
            <span><span className="dot" style={{ background: "var(--yellow)" }} />Moderate concern</span>
            <span><span className="dot" style={{ background: "var(--red)" }} />Needs full coverage</span>
            <span><span className="dot" style={{ background: "var(--grey)" }} />Missing</span>
          </div>
        </div>
        <div className="card">
          <h2>Clinical summary</h2>
          <p className="prose">{p.arch_summary}</p>
          <p className="prose" style={{ color: "var(--muted)" }}>
            Vertical dimension: {p.vertical_dimension_status}. {p.occlusal_plane_note}
          </p>
        </div>
      </div>

      {flagged.length > 0 && (
        <div className="card">
          <div className="alert warn">
            The assessment is uncertain about {flagged.length} tooth position{flagged.length > 1 ? "s" : ""}.
            Please confirm or correct each before continuing.
          </div>
          {flagged.map((n) => {
            const t = p.teeth.find((x) => x.tooth_number === n)!;
            return (
              <div key={n} style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 10 }}>
                <strong style={{ width: 80 }}>Tooth {n}</strong>
                <span style={{ flex: 1, fontSize: 13.5, color: "var(--muted)" }}>{t.observation}</span>
                <select value={fixes[n] || t.condition}
                        onChange={(e) => setFixes({ ...fixes, [n]: e.target.value })}>
                  {CONDITIONS.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
                </select>
              </div>
            );
          })}
        </div>
      )}

      <div className="card">
        <h2>Scan views</h2>
        <div className="renders">
          {["occlusal", "buccal_right", "buccal_left", "anterior", "diagonal"].map((v) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={v} src={renderUrl(data.case_id, v)} alt={v} title={v.replace("_", " ")} />
          ))}
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <a className="btn secondary" href="/">Back</a>
        <button className="btn" disabled={busy} onClick={proceed}>
          {busy ? "Saving…" : "Continue"}
        </button>
      </div>
    </>
  );
}
