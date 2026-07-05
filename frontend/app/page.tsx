"use client";
// Screen 1 — Upload. Two upload zones, one description box, one button.
// No forms. No dropdowns. (SPEC §5.1)
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { createCase } from "../lib/api";

function Zone({ label, file, onFile }: {
  label: string; file: File | null; onFile: (f: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div
      className={`dropzone ${file ? "filled" : ""}`}
      onClick={() => input.current?.click()}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]); }}
    >
      <input ref={input} type="file" accept=".stl,.ply" hidden
             onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
      <strong>{label}</strong>
      <div style={{ marginTop: 6 }}>{file ? file.name : "Drop an STL or PLY file, or click to browse"}</div>
    </div>
  );
}

export default function UploadScreen() {
  const router = useRouter();
  const [upper, setUpper] = useState<File | null>(null);
  const [lower, setLower] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function analyse() {
    setBusy(true); setError("");
    try {
      const { case_id } = await createCase(upper, lower, description);
      router.push(`/case/${case_id}`);
    } catch (e: any) {
      setError(e.message); setBusy(false);
    }
  }

  return (
    <>
      <h1>New case</h1>
      <p className="sub">Upload the scan, describe what the patient needs, and press Analyse.</p>
      {error && <div className="alert error">{error}</div>}
      <div className="card">
        <div className="grid2">
          <Zone label="Upper arch" file={upper} onFile={setUpper} />
          <Zone label="Lower arch (optional)" file={lower} onFile={setLower} />
        </div>
        <div style={{ marginTop: 20 }}>
          <textarea
            placeholder="What does the patient need? e.g. “Full mouth rehabilitation, generalised wear, wants longer front teeth.”"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div style={{ marginTop: 20, textAlign: "right" }}>
          <button className="btn big" disabled={busy || (!upper && !lower)} onClick={analyse}>
            {busy ? "Uploading…" : "Analyse"}
          </button>
        </div>
      </div>
    </>
  );
}
