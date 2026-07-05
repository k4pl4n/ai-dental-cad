# AI Dental CAD

Upload an intraoral scan → AI assesses every tooth → proposes a treatment plan → generates printable restoration STLs → validated download package. Built to `docs/PRODUCT_SPEC.md` and `docs/DEV_PLAN.md`.

## Structure

```
backend/
  app/
    main.py                 FastAPI — the API behind the five screens
    models/schemas.py       All cross-layer objects + material specs
    layers/                 The six-layer architecture (one file per layer)
      layer1_ingestion.py   Validate, PCA-normalise, upper/lower detect, measure
      layer2_rendering.py   Five clinical views (Open3D, matplotlib fallback)
      layer2_perception.py  Claude Vision → per-tooth 7-category assessment
      layer3_reasoning.py   Claude → treatment plan + framework params, sanity gate
      layer4_framework.py   Pure geometry: VD target, occlusal plane, incisal curve, symmetry
      layer5_generation.py  Priority-ordered parametric crown/pontic generation
      layer6_validation.py  The six checks + sintering scale export
      layer6_output.py      ZIP: STLs, assembly, bite model, PDF report, README
    prompts/                The three prompt blueprints (perception, planning, report)
    services/               claude_client (mockable), pipeline orchestrator, SQLite store
  tests/
    make_synthetic_scan.py  Synthetic upper arch for pipeline testing
    test_e2e.py             Full pipeline end-to-end test (mock Claude)
frontend/                   Next.js — the five screens
```

## Run the backend

```bash
cd backend
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...          # or AIDCAD_MOCK=1 for canned responses
uvicorn app.main:app --reload --port 8000
```

Optional env: `AIDCAD_MODEL` (default claude-sonnet-4), `AIDCAD_DATA_DIR`, `AIDCAD_CORS`.
Install `open3d` in production for high-quality renders (matplotlib fallback works but is slow and lower fidelity — perception accuracy depends on render quality).

## Run the frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                                   # http://localhost:3000
```

## Test end-to-end (no API key needed)

```bash
cd backend
AIDCAD_MOCK=1 python tests/test_e2e.py
```

## Where this is vs. the dev plan

Done (v0): six-layer architecture, all three prompts, ingestion with PCA orientation + geometric upper/lower detection, five-view rendering, confidence gates, sanity constraints, framework geometry, priority-ordered generation with parametric fallback, all six validation checks, sintering compensation + `_FABRICATION_READY` naming, ZIP package with PDF report and disclaimer README, corrections + audit logging (regulatory evidence pack), five-screen UI with per-tooth overrides.

Next (per DEV_PLAN):
1. **Validate against the 10 ground-truth cases** — run every before scan through ingestion (Step 1 exit criterion), inspect all renders manually (Step 2), iterate the perception prompt in the Anthropic console against known after-scan reality (Step 3 — budget 2–3 weeks, highest-leverage work).
2. Replace the v0 parametric crowns with margin-line-fitted anatomy (Step 6 is a 2–3 week overhaul; current geometry is honest about method via `generation_method`).
3. Maintain the accuracy spreadsheet (Part 4) — perception accuracy, planning accuracy, VD error per case, updated on every service change.
4. Deploy: Vercel (frontend) + Railway £20 (backend, install open3d) + S3 + Supabase + Clerk + Stripe (Part 8). Swap `services/store.py` for Supabase.

## The one metric

First Pass Approval Rate — % of cases downloaded and used without modification. Track weekly from the first live case. Below 60%: fix the pipeline, don't onboard more clinics.
