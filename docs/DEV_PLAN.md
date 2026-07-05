# AI Dental CAD — The Complete Dev Plan

_This is the definitive build guide. Read it once end to end. Then work through it in order. Do not skip forward._

---

## Part 1 — What You Are Actually Building (Lock This Down)

You are building a system where a dental clinic uploads a scan of a patient's mouth — in any condition, worn teeth, missing teeth, implants, prepared stumps, or all of these together — and receives a complete set of restorations designed to rehabilitate that mouth, exported as printable STL files, in under ten minutes, with no lab, no technician, and no CAD software licence.

The dentist's total interaction is: upload scan, type a short description of what the patient needs, review the AI's proposed treatment plan, approve it, and download the files. That is the whole product. Everything you build serves this workflow.

Your ground truth is the 10 before/after cases you already have. Every case in that dataset is a full-arch rehabilitation. That tells you what the market wants: not single crowns — complete transformations. Single crowns are the entry point. Full-arch is the moat.

**Stop building anything that does not lead directly to this outcome.** No lab technician features. No CAD editing tools. No margin drawing UI. Those belong in a different product.

---

## Part 2 — The Six-Layer Architecture

Everything in the system belongs to one of six layers. Data flows top to bottom. Each layer receives structured input from the previous layer and returns structured output to the next. Nothing skips a layer.

**Layer 1 — Ingestion.** Receives raw STL/PLY files. Validates them, normalises orientation, determines upper vs lower arch, extracts mesh metrics. Output: a clean, oriented, measured mesh object.

**Layer 2 — Perception.** Renders the mesh to five clinical views. Sends them to Claude Vision with a strict clinical prompt. Output: a per-tooth condition assessment plus overall arch summary.

**Layer 3 — Reasoning.** Two separate Claude calls. First produces the treatment plan (which teeth need what). Second produces the framework parameters (target vertical dimension, occlusal plane, incisal edge position). Output: a treatment plan object and a framework parameter object.

**Layer 4 — Framework.** Pure geometry. Takes the framework parameters and translates them into 3D constraints — target occlusal heights, target incisal positions, contact points, symmetry axes. Output: a geometric constraint object every restoration must respect.

**Layer 5 — Generation.** Generates each individual restoration to fit its constraints. Posterior support teeth first (they define vertical dimension), then premolars, canines, incisors. Output: a set of individual STL meshes.

**Layer 6 — Validation & Output.** Runs six checks — integrity, minimum thickness, vertical dimension, occlusal contacts, adjacent contacts, sintering scale. Packages fabrication-ready files, clinical report PDF, verification model. Output: the download package.

Every service in your backend belongs to exactly one layer. Every function you write, ask yourself: which layer? If it doesn't fit cleanly, split it.

---

## Part 3 — The Build Sequence

Do these in order. Do not parallelise. Each step depends on the previous being correct.

### Step 1 — Ingestion Hardening (3–5 days)

Your current ingestion works for well-behaved files. It will fail on real clinic scans. Fix these five things.

Validate the mesh properly. Open it, check it has vertices and faces, verify vertex count is between 30,000 and 800,000. Reject anything else with a clear error the dentist understands ("this file does not appear to be a standard intraoral scan").

Normalise orientation. Run principal component analysis on the vertex positions. The three axes correspond to mesial-distal (largest), buccal-lingual (medium), occlusal-apical (smallest). Rotate the mesh so mesial-distal is always X, occlusal points always positive Z. Every downstream step assumes this orientation.

Detect upper vs lower geometrically. Upper arches have a filled palate in the centre; lower arches have a tongue gap. Sample the vertex density in the arch centre — if it's high, it's upper; if it's low, it's lower. Do not trust filenames.

Measure the arch. Mesial-distal width from posterior to posterior. Anterior-posterior depth. These numbers feed your framework calculations.

Extract mesh quality. Surface area, volume, watertight status, hole count, non-manifold edge count. Log all of it. If the mesh has significant errors, run Open3D's built-in repair before proceeding.

You are done with step 1 when your ingestion handles all 10 of your before scans and any 10 additional test scans from Thingiverse or GrabCAD without crashing or misclassifying.

### Step 2 — Rendering Pipeline (3–5 days)

Five views. Not three. Not seven. Five.

Occlusal (top-down): the most important single view. Camera directly above the arch centroid, looking straight down. Distance = 1.5× the longest bounding box dimension.

Buccal right and buccal left: two camera positions on either side of the arch, at centroid height, looking horizontally inward.

Anterior: camera in front of the arch, at centroid height, looking straight back into it.

Occlusal-anterior diagonal: camera at 30–45 degrees above and in front. This composite view is what technicians naturally look at first.

Use Open3D's OffscreenRenderer. It works without a display, which matters because Railway has no screen. Render at 1024×1024. Apply ambient light plus one directional light from above. Save as PNG.

**Verify manually.** Open each rendered image yourself. Can you identify prepared stumps? Can you count the teeth? Can you see worn teeth as flat surfaces? If not, adjust camera positions and lighting before writing another line of code. The vision AI can only see what you show it.

### Step 3 — The Perception Prompt (2–3 weeks)

This is the highest-leverage work in the entire project. Budget serious time.

Iterate the prompt directly in the Anthropic console before writing any integration code. Paste in your rendered images manually. Get Claude's response. Compare to what you know is in the corresponding after scan. Adjust. Repeat.

The prompt must do these specific things:

Describe what Claude is looking at. Not "a dental scan" — "five clinical renders of a full intraoral arch scan, viewed from occlusal, right buccal, left buccal, anterior, and diagonal angles. Each image is labelled below."

Enforce seven exact tooth condition categories. Natural healthy. Natural worn (mild/moderate/severe). Natural with caries or fracture. Implant fixture. Root or stump with no crown. Prep stump. Missing (edentulous space). Nothing else. These seven categories drive treatment planning.

Give Claude specific visual signatures for each condition. Prep stumps look like cylinders or truncated cones without cusp anatomy. Severely worn teeth appear as flat occlusal surfaces with lost cusps. Implants look cylindrical, often with a metallic sheen. Missing teeth show as gaps. Write these signatures into the prompt.

Require systematic sweep. Claude examines teeth from 1 to 32 in order (or right-to-left for the arch it's viewing). Never randomly. This prevents skipped teeth.

Demand a confidence score per tooth. Not just "prep stump" — "prep stump, confidence 0.86". Anything below 0.75 gets flagged for clinician confirmation before treatment planning proceeds.

Enforce strict JSON output. Define the schema in the prompt. Every field mandatory. Reject and retry on malformed responses.

You are done with step 3 when Claude correctly identifies the treatment condition of at least 8 out of 10 of your before scans, and misses no teeth that received restorations in the after scan.

### Step 4 — Treatment Planning Prompt (1 week)

Second Claude call. Takes the perception output. Produces the treatment plan.

Do not conflate this with perception. Keep them separate. Perception is _what is there_. Planning is _what to do about it_.

Give Claude the explicit clinical algorithm in the prompt. It should not have to reason from first principles. Rules like: worn teeth with >50% clinical crown height loss get full coverage. Prep stumps get crowns. Missing teeth with adjacent healthy neighbours get implant crowns if a fixture is visible; missing teeth with adjacent restored neighbours get bridge pontics. Anterior wear cases must include incisal edge repositioning.

Output must include per-tooth decisions (tooth number, restoration type, material recommendation, design priority) and the four framework parameters (vertical dimension increase, occlusal plane orientation, anterior incisal target, symmetry axis).

Design priority is critical: posterior support teeth (molars) get priority 1, premolars priority 2, canines priority 3, incisors priority 4. This is the order they will be generated.

### Step 5 — Framework Service (1 week)

This is pure geometry. No AI. Takes the four framework parameters and translates them into 3D constraints.

Vertical dimension: current maximum Z of the arch plus the target increase = target occlusal height. Every posterior restoration's occlusal surface must reach this height.

Occlusal plane: fit a plane through three reference points — one posterior on each side (highest point of the least-worn molar), one anterior (highest point of the canine). Tilt as Claude specified.

Incisal edge position: a 3D curve following the arch curvature at the target incisal height. Each anterior tooth gets a target 3D point on this curve.

Symmetry: reflect right-side targets across the arch midline to define left-side targets. This forces symmetric restorations unless Claude explicitly said asymmetry is clinically indicated.

Store all of this in a framework object. Every subsequent restoration call receives this object plus its own tooth position.

### Step 6 — Restoration Generation Overhaul (2–3 weeks)

Your current crown service generates one crown at a time using Claude's suggested thickness. Rewrite it to use the framework.

The framework determines where the outer surface goes. Not Claude. The restoration must reach the framework's target position at the top and fit the local prep geometry at the bottom. Thickness becomes a consequence, not an input.

Generate in priority order. All molars first (in parallel — left and right can run at the same time). Verify vertical dimension actually reached the target ± 0.5mm. Then premolars. Then canines. Then incisors. Then any remaining teeth.

For teeth that are worn but not prepared — this is most of the cases in your dataset — apply a standard preparation design for that tooth position and note in the case report which teeth need physical preparation before fitting. Do not fake it. The dentist must know.

For missing teeth with bridge pontics, span the gap between adjacent restorations, contact the ridge tissue below, respect the opposing arch above.

### Step 7 — The Six Validation Checks (1 week)

Run these in strict order. Any failure stops the pipeline and reports specifically which check failed and where.

1. Individual restoration integrity. Every mesh watertight, no non-manifold edges, no inverted normals. Attempt automatic repair once. If still failing, flag that specific restoration.

2. Minimum thickness. Sample points across every restoration surface, measure distance to inner surface. Zirconia ≥ 0.5mm everywhere. Lithium disilicate ≥ 1.0mm occlusal, ≥ 0.6mm axial. Log locations of any violations.

3. Vertical dimension. Simulate upper and lower closing. Measure actual VD at first contact. Must equal target ± 0.5mm.

4. Occlusal contact distribution. In closed position, find all points within 0.1mm between upper and lower. Verify balanced contacts across both sides. No isolated hyperoccluded restoration.

5. Adjacent contact integrity. For each pair of neighbouring restorations, verify contact point exists at correct height, not open, not over-tight.

6. Sintering scale. Multiply every zirconia crown's vertex coordinates by 1.22 before export. Other materials by their factor. Name output files `_FABRICATION_READY.stl` so no one scales twice.

### Step 8 — The Output Package (3 days)

Bundle everything into one download.

Individual STL per restoration, named clearly: `Crown_Tooth14_Zirconia_FABRICATION_READY.stl`. A full arch assembly STL showing all restorations positioned. A verification model showing upper and lower arches in simulated bite. A PDF case report generated from the pipeline results. All in a single ZIP.

The PDF is important. It documents: what was found (perception summary), what was planned (treatment plan), what was designed (per-restoration specs), what was validated (all six checks with results), what to verify clinically before fitting (assumptions made, teeth requiring physical preparation).

### Step 9 — The Five-Screen UI (3–4 weeks)

Rebuild the frontend around the clinical workflow. Everything else is legacy.

Screen 1 — Upload. Two upload zones (upper, lower) and a free-text description box. One button: Analyse. Nothing else. No forms. No dropdowns.

Screen 2 — Clinical Assessment. Occlusal view with per-tooth condition highlights (green healthy, yellow moderate, red full-coverage, grey missing). Hover shows Claude's observation per tooth. Right panel: prose clinical summary in the language a prosthodontist would use. Continue or Back.

Screen 3 — Treatment Plan Review. Arch view with colour-coded planned restorations. List below with per-tooth Edit buttons for override. Framework parameters shown in plain English. One button: Approve Plan and Start Design.

Screen 4 — Design in Progress. Live progress. Restoration thumbnails appear as they generate. Framework parameters visible (VD change, occlusal plane, incisal target). Typical time 2–8 minutes.

Screen 5 — Review & Download. Split 3D viewer: before on left, proposed after on right, synchronised rotation. Case report below. Traffic light status. Big download button.

**No technical language anywhere except the override screen.** No axial wall thickness. No margin width. No QC score. Green means ready. Yellow means read the notes. Red means regenerate. That's the entire visual vocabulary.

---

## Part 4 — Dataset Strategy

You have 10 cases. That is not training data. It is ground truth. Use it that way.

### Immediate use (weeks 1–8)

For each of the 10 cases:

Run your perception step on the before scan. Record what Claude said. Compare to the after scan reality. Log false positives and false negatives per tooth type.

Run your treatment planning on the perception output. Compare to the restorations actually present in the after scan. Score treatment plan accuracy.

Once you have restoration generation working, run the full pipeline on the before scan. Measure the generated result against the after scan geometrically. Vertical dimension error. Occlusal height error per tooth. Crown volume ratio.

Maintain a single spreadsheet. Rows: the 10 cases. Columns: perception accuracy, planning accuracy, VD error, per-tooth height error, overall similarity score. Update every time you change a service. Watch trends. If a change improves one metric while worsening another, you have a regression.

### Acquisition strategy (months 2–12)

You need at least 500 before/after pairs to fine-tune anything meaningful, and 2,000+ to train ML models properly.

Data sources in priority order:

Beta clinic partnerships. The email template from your previous conversations works. Offer free access in exchange for anonymised historical case data. Every clinic doing full-arch work has years of scans on their servers.

Turkey and UK first. Turkey has a large dental industry with excellent digital adoption and English-speaking labs. UK is your home market. Focus on clinics with intraoral scanners already (they are your entire customer base anyway).

Prosthodontic residency programmes. University dental schools have massive scan archives and are much more receptive to research licensing than private clinics. Contact King's, Manchester, and Leeds.

3DTeethSeg22 challenge data. 1,500 scans with segmentation labels. Not before/after, but useful for training tooth segmentation.

For every case that comes in through your live platform, capture the four data points that become your training set: the before scan, Claude's perception output, the treatment plan the dentist approved (with any overrides), and the final downloaded restorations. Store all four. This is the flywheel.

---

## Part 5 — Prompt Blueprints

The three prompts that make or break the system. Write these carefully. Iterate them against your ground truth.

### Perception prompt structure

Opening: role assignment as expert prosthodontist examining rendered intraoral scan views.

Image description: label each image by view angle.

Task list: identify every tooth position, classify condition using exact seven-category taxonomy, estimate vertical dimension status, identify any implants or missing teeth, note scan quality issues.

Category definitions: written descriptions of the visual signatures of each of the seven conditions.

Systematic instruction: sweep tooth positions 1–32 in order.

Confidence requirement: score 0.0–1.0 per tooth. Explicit instruction to say "uncertain" rather than guess.

Output schema: exact JSON structure required. Every field mandatory. Numeric confidence, not text.

### Treatment planning prompt structure

Opening: role as prosthodontist producing a rehabilitation plan.

Context: paste the perception output and the dentist's free-text description.

Clinical algorithm: explicit rules for what each condition category requires. Coverage thresholds. Bridge vs implant decisions. Anterior incisal edge decisions.

Framework parameter requirements: VD increase (mm, numeric), occlusal plane (tilt in degrees), anterior incisal target (crown length in mm), symmetry (boolean plus rationale).

Design priority: assign each restoration priority 1–4 by position.

Sanity constraints: max 16 restorations per arch, max 8mm VD increase, max 12mm single crown height. If violated, return to review.

Output schema: strict JSON.

### Case report prompt structure

Third Claude call, after generation and validation complete.

Context: perception summary, treatment plan, framework parameters, validation results.

Task: write clinical narrative for the dentist. What was found, what was planned, what was designed, what to verify clinically before fitting, assumptions made (teeth requiring preparation, uncertain classifications).

Tone: clinical dictation. Third person. Present tense. No marketing language. No emojis.

Length: 400–800 words.

Output: prose, not JSON. This is the only prompt that returns free text.

---

## Part 6 — Failure Handling

Every layer has a failure mode. Each needs a specific response.

Ingestion fails on corrupt or non-dental file → stop immediately, clear user-facing error, no partial results shown.

Rendering fails on server environment issue → fallback to mesh-metrics-only analysis, flag prominently on results screen that visual analysis was unavailable.

Perception confidence below 0.6 overall → do not proceed to planning, route to a review screen with the rendered images and ask the dentist to correct classifications before continuing.

Treatment planning returns implausible plan (violates sanity constraints) → flag for manual review, do not proceed to generation.

Individual restoration generation fails → attempt parametric fallback using framework + tooth-type anatomy library, no local prep geometry required. If that also fails, mark that specific tooth as failed and continue with the rest.

Validation check fails → attempt automatic regeneration with adjusted parameters once. If still failing, include in output package but clearly marked as requiring technician review.

**Never show a green ready-to-mill status when any validation check failed.** Trust once lost does not come back.

---

## Part 7 — Validation Against Ground Truth

Before you ship to any real customer, your system must hit these numbers on all 10 of your ground truth cases:

Perception accuracy: false negative rate below 10% (teeth needing restoration that Claude missed) and false positive rate below 15%.

Treatment planning accuracy: at least 85% of planned restorations match the actual restorations in the after scan.

Vertical dimension: within 2mm of actual after-scan VD.

Per-tooth height: within 2mm of actual after-scan crown heights on average.

Full pipeline completion: no crashes, all six validation checks pass on at least 8 of 10 cases.

If any number is below threshold, do not deploy. Fix and re-validate.

---

## Part 8 — Infrastructure and Deployment

Keep it simple. You do not need Kubernetes.

Frontend: Next.js on Vercel. Free tier holds until 10+ paying customers.

Backend: FastAPI on Railway. Upgrade to the £20 plan for adequate memory (large scans plus rendering plus generation can hit 4GB peaks). If you hit ceilings, move to a Fly.io GPU instance.

Storage: AWS S3 for scan files and generated outputs. Set lifecycle rules to move files older than 90 days to Glacier — dental scans are small enough that £10/month covers years of use.

Database: Supabase for case records, users, corrections. Free tier holds until you have 500+ cases.

Auth: Clerk. Free tier covers your first 10,000 users which you will not hit in year one.

Queue: Add Redis + Celery on Railway once cases regularly take >30 seconds. Not before. Premature async makes debugging harder.

Monitoring: UptimeRobot on your backend health endpoint. Sentry for error tracking (free tier). Log every case ID + result + duration to a simple table so you can query which cases are failing and why.

Payments: Stripe. Two products — £199/month unlimited, or £15 per case pay-as-you-go. Nothing else at launch.

---

## Part 9 — Commercial Rollout

The build is not the hard part. Sales is the hard part.

### Weeks 1–4 of live product

Ten clinics. Not a hundred. Ten. Each one you personally onboard. Each one you personally watch use the product for the first case. Each one you follow up with weekly. You will learn more from those ten than from any other activity.

Target profile: clinics with an intraoral scanner (iTero, Medit, Trios, Primescan) already installed. Ideally also with a chairside mill (CEREC MC series, imes-icore, Roland DGSHAPE). These clinics already spend money on same-day dentistry infrastructure. You are the missing piece.

Geographic focus: your city first. In-person demos convert 5–10× better than remote. If you are in the UK, London and Manchester. If in Turkey, Istanbul and Ankara.

### Pricing

Start at £199/month unlimited. Not lower. Cheap products get treated as toys. Premium anchoring signals seriousness.

Offer three months free to the first ten beta labs in exchange for signed data licensing (they own the patient relationship; you get anonymised scan geometry). Written email agreement is sufficient at this stage.

Move beta clinics to paid at month 4. Any who leave were never going to convert.

### Month 3–6

Twenty paying clinics. £4,000 MRR. Enough to justify one hire — either customer success (to protect existing revenue) or a second engineer (to accelerate the product). Pick based on where your bottleneck actually is. Usually it's customer success.

### Month 6–12

Reach 50 clinics and £10,000 MRR. Now you have a fundable business. Pre-seed round if you want it — £300–600k against traction and dataset moat. Or bootstrap harder and stay independent.

Start Turkey market entry through a local reseller. Do not try to support Turkish clinics directly from another country. Find a partner at TDA (Turkish Dental Association) events.

### Regulatory

MHRA email at devices@mhra.gov.uk in month 3. Ask for classification guidance. Free. Documented in writing.

One hour with a healthcare regulatory lawyer at month 6. £300. Get the SaMD classification confirmed in writing.

Start compiling technical documentation from day one — every design decision, every accuracy measurement, every case study. When you eventually pursue FDA 510(k) or MDR class IIa, this evidence pack cuts 6–12 months off the process.

**Positioning matters legally.** Your product is a design aid. The clinician reviews and approves every case. That framing is defensible today. The moment you claim autonomy without human review, you become a medical device manufacturer and the compliance burden multiplies.

---

## Part 10 — The One Metric

Track First Pass Approval Rate every single week from your first live case.

FPAR = number of cases where the dentist downloaded and used the AI-generated restorations without modifying anything, divided by total cases in that week.

Below 60% = you are shipping too early. Fix the pipeline before onboarding more clinics.

60–75% = viable product. Growth is safe.

75–90% = strong product. Word of mouth kicks in.

Above 90% = category-defining. Regulatory advantage becomes possible.

Every technical decision you make from here onward should improve FPAR. Every feature that doesn't touch FPAR is a distraction. Post it on a wall.

---

## Part 11 — What To Do Tomorrow Morning

Concrete first-week actions:

Day 1. Read this document again. Delete every service in your current backend that doesn't fit the six-layer architecture. Set up the empty folder structure with one file per layer.

Day 2. Rewrite the ingestion layer per Part 3 Step 1. Test it on all 10 of your before scans. Do not proceed until every one loads cleanly.

Day 3. Rewrite the rendering layer. Render all 10 cases. Open the images yourself. Confirm you can identify the treatment situation in each.

Day 4. Write your perception prompt in the Anthropic console. Paste in Case 1 images. Iterate the prompt until the output matches what you know from Case 1's after scan. Move to Case 2. Repeat. Do this all week if needed.

Day 5. Write out the treatment planning prompt. Test it in the console using Case 1's perception output. Compare to Case 1's actual after-scan restorations. Iterate.

By end of week 1 you have three of the six layers working correctly on your ground truth. This is the foundation. Everything else builds on it.

Do not add features. Do not touch the frontend. Do not talk to labs yet. Get these three layers right first. That is the entire job of week 1.

---

_The strategy is now settled. The execution is the whole game. Follow the sequence. Validate against the ground truth. Ship to ten clinics. Iterate on FPAR. Everything else falls out of that._
