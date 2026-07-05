"use client";
// One route per case. Renders Screen 2/3/4/5 by case status, polling the
// backend — so the user can navigate away and return (SPEC §5.4).
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CaseData, getCase } from "../../../lib/api";
import Screen2Assessment from "../../../components/Screen2Assessment";
import Screen3Plan from "../../../components/Screen3Plan";
import Screen4Progress from "../../../components/Screen4Progress";
import Screen5Review from "../../../components/Screen5Review";

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<CaseData | null>(null);
  const [error, setError] = useState("");
  // Screen 2 is a review the user proceeds past explicitly; the backend
  // status jumps straight to plan_review when confidence is high.
  const [assessmentConfirmed, setAssessmentConfirmed] = useState(false);

  async function refresh() {
    try { setData(await getCase(id)); } catch (e: any) { setError(e.message); }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (error) return <div className="alert error">{error}</div>;
  if (!data) return <p className="sub">Loading case…</p>;

  const s = data.status;
  if (s === "failed")
    return (
      <>
        <h1>Case {data.reference}</h1>
        <div className="alert error">{data.error || "This case failed. Please try again."}</div>
        <a className="btn secondary" href="/">Start a new case</a>
      </>
    );
  if (s === "uploading" || s === "analysing")
    return (
      <>
        <h1>Case {data.reference}</h1>
        <div className="card">
          <h2>Analysing the scan…</h2>
          <p className="sub">Reading the scan, examining every tooth. This takes 30–60 seconds.</p>
          <div className="bar"><div style={{ width: "40%" }} /></div>
        </div>
      </>
    );
  if (s === "assessment_review" || (s === "plan_review" && !assessmentConfirmed))
    return <Screen2Assessment data={data} onContinue={() => setAssessmentConfirmed(true)} onRefresh={refresh} />;
  if (s === "plan_review")
    return <Screen3Plan data={data} onRefresh={refresh} onBack={() => setAssessmentConfirmed(false)} />;
  if (s === "designing") return <Screen4Progress data={data} />;
  if (s === "complete") return <Screen5Review data={data} />;
  return <p className="sub">Unknown status: {s}</p>;
}
