"use client";
// Occlusal-view arch chart. Colour vocabulary (SPEC §5.2):
// green healthy · yellow moderate · red full coverage · grey missing.
import { useState } from "react";
import type { ToothAssessment, PlannedRestoration } from "../lib/api";

const CONDITION_COLOUR: Record<string, string> = {
  natural_healthy: "var(--green)",
  natural_worn: "var(--yellow)",
  natural_caries_fracture: "var(--red)",
  implant_fixture: "var(--accent)",
  root_stump: "var(--red)",
  prep_stump: "var(--red)",
  missing: "var(--grey)",
};

const PLAN_COLOUR: Record<string, string> = {
  full_crown: "#7c5cd6",
  veneer: "#2fa8a0",
  inlay: "#c77c2e",
  onlay: "#c77c2e",
  bridge_pontic: "#d65c9a",
  implant_crown: "#0f6fde",
};

/** 16 positions along a parabolic arch, anterior at top. */
function positions(): { n: number; x: number; y: number }[] {
  const out = [];
  for (let i = 0; i < 16; i++) {
    const t = (i + 0.5) / 16;            // tooth 1 (right molar) → 16 (left molar)
    const x = 200 + 160 * Math.cos(Math.PI * (1 - t));
    const y = 210 - 175 * Math.sin(Math.PI * t) ** 0.9;
    out.push({ n: i + 1, x, y });
  }
  return out;
}

export default function ToothChart({ teeth, plan, flagged, upperArch = true }: {
  teeth: ToothAssessment[];
  plan?: PlannedRestoration[];
  flagged?: number[];
  upperArch?: boolean;
}) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const byNum = new Map(teeth.map((t) => [t.tooth_number, t]));
  const planBy = new Map((plan || []).map((r) => [r.tooth_number, r]));
  const offset = upperArch ? 0 : 16;

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox="0 0 400 240" style={{ width: "100%" }}>
        {positions().map(({ n, x, y }) => {
          const num = n + offset;
          const t = byNum.get(num);
          const p = planBy.get(num);
          const fill = p
            ? PLAN_COLOUR[p.restoration_type] || "var(--accent)"
            : t
              ? CONDITION_COLOUR[t.condition] || "var(--grey)"
              : "var(--line)";
          const isFlagged = flagged?.includes(num);
          return (
            <g key={num}
               onMouseMove={(e) => t && setTip({
                 x: e.clientX + 14, y: e.clientY + 6,
                 text: `Tooth ${num} — ${p ? `${p.restoration_type.replace("_", " ")} (${p.material.replace("_", " ")})` : t.condition.replace(/_/g, " ")}${t ? `\n${t.observation}` : ""}`,
               })}
               onMouseLeave={() => setTip(null)}>
              <circle className="tooth" cx={x} cy={y} r={13} fill={fill}
                      opacity={t?.condition === "missing" && !p ? 0.45 : 1} />
              {isFlagged && <circle cx={x} cy={y} r={17} fill="none"
                                    stroke="var(--yellow)" strokeWidth={2.5} strokeDasharray="4 3" />}
              <text x={x} y={y + 4} textAnchor="middle" fontSize="10" fill="#fff" fontWeight="700">
                {num}
              </text>
            </g>
          );
        })}
      </svg>
      {tip && <div className="tooltip" style={{ left: tip.x, top: tip.y, whiteSpace: "pre-wrap" }}>{tip.text}</div>}
    </div>
  );
}
