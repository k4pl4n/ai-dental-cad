"use client";
// Screen 4 — Design in Progress (SPEC §5.4). Live progress, thumbnails as
// restorations complete, framework parameters visible. Poll-driven, so the
// user can navigate away and come back.
import { CaseData } from "../lib/api";

export default function Screen4Progress({ data }: { data: CaseData }) {
  const plan = data.plan!;
  const fw = plan.framework;
  const done = new Set(data.restorations.filter((r) => !r.failed).map((r) => r.tooth_number));
  const failed = new Set(data.restorations.filter((r) => r.failed).map((r) => r.tooth_number));
  const total = plan.restorations.length;
  const pct = total ? Math.round(((done.size + failed.size) / total) * 100) : 0;

  return (
    <>
      <h1>Case {data.reference} — designing restorations</h1>
      <p className="sub">Typical time 2–8 minutes. You can leave this page and come back.</p>

      <div className="card">
        <div className="bar"><div style={{ width: `${Math.max(pct, 6)}%` }} /></div>
        <p className="sub">{done.size} of {total} restorations complete</p>
        <div className="progress-grid">
          {plan.restorations
            .slice()
            .sort((a, b) => a.priority - b.priority || a.tooth_number - b.tooth_number)
            .map((r) => (
              <div key={r.tooth_number}
                   className={`thumb ${done.has(r.tooth_number) ? "done" : ""}`}>
                <div style={{ fontSize: 22 }}>
                  {done.has(r.tooth_number) ? "✓" : failed.has(r.tooth_number) ? "!" : "…"}
                </div>
                Tooth {r.tooth_number}
                <div>{r.restoration_type.replace(/_/g, " ")}</div>
              </div>
            ))}
        </div>
      </div>

      <div className="card">
        <h2>Framework being applied</h2>
        <p className="prose">
          Bite height change: <strong>+{fw.vd_increase_mm}mm</strong> ·
          Biting plane tilt: <strong>{fw.occlusal_plane_tilt_deg}°</strong> ·
          Front tooth length: <strong>{fw.incisal_crown_length_mm}mm</strong> ·
          Symmetry: <strong>{fw.symmetric ? "mirrored" : "independent"}</strong>
        </p>
        <p className="sub">
          Back teeth are designed first — they set the bite height. Then premolars,
          canines, and front teeth follow the arch curve.
        </p>
      </div>
    </>
  );
}
