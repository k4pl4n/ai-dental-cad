"use client";
// Screen 5 — Review & Download (SPEC §5.5). Traffic light, case summary,
// big download button. Green means ready. Yellow means read the notes.
// Red means regenerate. Detailed technical view collapsed by default.
import { useState } from "react";
import { CaseData, downloadUrl, renderUrl } from "../lib/api";

const LIGHT_LABEL: Record<string, string> = {
  green: "Ready — download and fabricate after clinical review",
  yellow: "Ready with notes — read the case report before fabricating",
  red: "Not ready — review the issues and regenerate",
};

export default function Screen5Review({ data }: { data: CaseData }) {
  const [showTech, setShowTech] = useState(false);
  const light = data.traffic_light;
  const ok = data.restorations.filter((r) => !r.failed).length;
  const failedTeeth = data.restorations.filter((r) => r.failed).map((r) => r.tooth_number);
  const prepTeeth = (data.plan?.restorations || [])
    .filter((r) => r.needs_physical_preparation).map((r) => r.tooth_number);

  return (
    <>
      <h1>Case {data.reference} — review and download</h1>

      <div className="card">
        <div className="traffic">
          <span className="lamp" style={{ background: `var(--${light})` }} />
          {LIGHT_LABEL[light]}
        </div>
        {prepTeeth.length > 0 && (
          <div className="alert warn" style={{ marginTop: 14 }}>
            Teeth {prepTeeth.join(", ")} must be physically prepared before their
            restorations can be seated. Details are in the case report.
          </div>
        )}
        {failedTeeth.length > 0 && (
          <div className="alert error" style={{ marginTop: 14 }}>
            Restorations for teeth {failedTeeth.join(", ")} could not be generated and
            are not included in the package.
          </div>
        )}
        <div style={{ marginTop: 18 }}>
          {light !== "red" ? (
            <a className="btn big" href={downloadUrl(data.case_id)}>
              Download package ({ok} restorations)
            </a>
          ) : (
            <a className="btn big secondary" href="/">Start again with a new case</a>
          )}
        </div>
        <p className="sub" style={{ marginTop: 12 }}>
          The ZIP contains fabrication-ready STL files (sintering compensation already
          applied — do not scale again), a full-arch assembly, a bite verification model,
          and the clinical case report PDF.
        </p>
      </div>

      <div className="grid2">
        <div className="card">
          <h2>Before</h2>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={renderUrl(data.case_id, "diagonal")} alt="before"
               style={{ width: "100%", borderRadius: 10 }} />
        </div>
        <div className="card">
          <h2>Designed restorations</h2>
          <p className="prose">
            {ok} restorations designed against the approved framework
            (+{data.plan?.framework.vd_increase_mm}mm bite height,
            {" "}{data.plan?.framework.incisal_crown_length_mm}mm front tooth length).
            Open the verification model STL in any viewer to inspect the simulated bite.
          </p>
        </div>
      </div>

      <div className="card">
        <button className="btn secondary" onClick={() => setShowTech(!showTech)}>
          {showTech ? "Hide" : "Show"} detailed technical view
        </button>
        {showTech && data.validation && (
          <table className="plan" style={{ marginTop: 16 }}>
            <thead><tr><th>#</th><th>Check</th><th>Result</th><th>Details</th></tr></thead>
            <tbody>
              {data.validation.checks.map((c) => (
                <tr key={c.check_number}>
                  <td>{c.check_number}</td>
                  <td>{c.name}</td>
                  <td>
                    <span className={`status-pill status-${c.passed ? "green" : "red"}`}>
                      {c.passed ? "pass" : "fail"}
                    </span>
                  </td>
                  <td style={{ color: "var(--muted)", fontSize: 13 }}>{c.details}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
