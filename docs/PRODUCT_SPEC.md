# AI Dental CAD Platform — Product Specification

_This document describes the product for a developer to build. It defines what exists, what it does, and how the pieces connect. It does not prescribe code or a build sequence — that is the developer's job._

---

## 1. Product Summary

A web application that receives a 3D intraoral scan of a patient's mouth and returns a complete set of dental restorations designed to rehabilitate that mouth, exported as printable STL files.

The application handles any clinical situation visible in the scan — worn teeth, missing teeth, dental implants, prepared stumps, or any combination. It designs restorations for every tooth that needs one, simultaneously, so they work together as a functioning arch.

The user is a dentist or dental clinic. The primary interaction is: upload scan → review AI's plan → download printable files. No lab technician is involved. No CAD software licence is required.

Total user interaction time per case: under 5 minutes. Total system processing time per case: under 10 minutes.

---

## 2. Who The User Is

The user is a dentist or dental technician working in a clinic that already owns:
- An intraoral scanner (iTero, Medit i700, 3Shape Trios, Primescan, or similar)
- Access to a chairside mill or 3D printer (in-office or through a local partner)

They do not have CAD training. They do not want to learn dental CAD software. They want to hand a scan to an AI and receive back a printable design they can trust.

They are technically comfortable but clinically focused. They understand teeth. They do not understand PointNet++.

---

## 3. Core User Flow

The complete journey from scan upload to printed crown:

**Step 1. Upload.** The dentist opens the web app in any browser. They upload one or two STL/PLY files (upper arch, and optionally the lower arch). They optionally type a natural-language description of what the patient needs. They click one button.

**Step 2. Analysis.** The system processes the scan. Within 30–60 seconds, the dentist sees the AI's clinical assessment of every tooth in the arch, colour-coded by treatment need.

**Step 3. Plan review.** The system proposes a treatment plan — which teeth need what restoration, in what material. The dentist reviews. They can override any individual tooth's treatment. They approve the plan.

**Step 4. Design.** The system generates every restoration in the plan. This takes 2–8 minutes depending on case complexity. The dentist watches progress or leaves it to complete.

**Step 5. Review and download.** The dentist sees a before/after 3D comparison of the arch. They read a clinical case report. If everything looks correct, they download a ZIP containing individual restoration STL files, a full-arch assembly, and a verification model.

**Step 6. Fabrication.** The dentist sends the STL files to their mill or printer. The finished restorations are fitted to the patient.

The system's job ends at Step 5. Fabrication and fitting are the dentist's responsibility.

---

## 4. What The System Must Do (Functional Requirements)

### 4.1 Accept and understand intraoral scans

The system accepts STL and PLY files up to 200MB. It validates that they are intraoral dental scans (vertex count 30,000–800,000, mesh geometry that resembles a dental arch). Invalid files are rejected with a clear user-facing error before any processing runs.

The system automatically determines whether a scan is an upper or lower arch, and orients it consistently regardless of the coordinate convention used by the source scanner.

### 4.2 Assess the clinical condition of every tooth

For every tooth position visible in the scan, the system determines its condition from one of seven categories:
- Natural tooth in good condition (no restoration needed)
- Natural tooth with wear (mild, moderate, or severe)
- Natural tooth with caries or fracture
- Dental implant fixture
- Root or stump with no crown
- Prepared stump (ready for a crown)
- Missing tooth (edentulous space)

Each assessment includes a confidence score. Low-confidence assessments are flagged for user review before treatment planning proceeds.

The system also assesses the overall arch condition, including estimated vertical dimension status and whether any occlusal plane correction is needed.

### 4.3 Generate a treatment plan

Based on the tooth-by-tooth assessment, the system produces a treatment plan. For each tooth requiring treatment, the plan specifies:
- Tooth number (universal notation, 1–32)
- Restoration type (full crown, veneer, inlay, onlay, bridge pontic, implant crown)
- Material recommendation (zirconia, layered zirconia, lithium disilicate, PMMA, cobalt-chrome, composite)
- Design priority (posterior support first, then premolars, canines, incisors)

The plan also specifies four full-arch framework parameters:
- Target vertical dimension change (in millimetres)
- Occlusal plane orientation (tilt in degrees)
- Anterior incisal edge target position (crown length in millimetres)
- Symmetry axis (whether left and right sides should mirror)

The user can override any individual tooth's treatment before approving the plan.

### 4.4 Design every restoration in one coordinated pass

Once the plan is approved, the system designs every restoration in the plan. The restorations are designed to fit together as a coherent arch, not independently.

Restorations respect:
- The framework parameters (occlusal plane, vertical dimension, incisal edge position)
- The local preparation geometry (they fit the tooth beneath them)
- Adjacent contact points (they touch neighbouring restorations correctly)
- Opposing arch contacts (they occlude with the opposite arch)
- Minimum material thickness (they meet clinical strength requirements)

Output is one STL mesh per restoration.

### 4.5 Validate the design

Before releasing files to the user, the system runs six clinical validation checks:
1. Every restoration is a watertight, manifold mesh
2. Minimum wall thickness meets material specifications everywhere
3. Vertical dimension in the simulated closed position matches the target within 0.5mm
4. Occlusal contacts are balanced across both sides of the arch
5. Adjacent restorations have correct contact points (not open, not over-tight)
6. Material-specific sintering compensation has been applied (zirconia crowns scaled by 1.22 before export)

Any failure produces a specific, actionable message. Silent failures are not permitted.

### 4.6 Deliver fabrication-ready output

The final download package contains:
- Individual STL files per restoration, named unambiguously (e.g., `Crown_Tooth14_Zirconia_FABRICATION_READY.stl`)
- A full-arch assembly STL showing all restorations positioned together
- A verification model showing upper and lower arches in the simulated bite position
- A PDF clinical case report

The case report documents what the AI found, what it planned, what it designed, and what the clinician must verify before fitting (including any teeth that need physical preparation before the restoration can be seated).

---

## 5. The User Interface — Five Screens

### Screen 1: Upload

Purpose: capture the scan and any clinical context.

Contains: two file upload zones (upper arch, lower arch — lower is optional), one free-text description field, one primary button labelled "Analyse".

No forms. No dropdowns. No tooth chart. No prescription fields.

### Screen 2: Clinical Assessment

Purpose: show the user what the AI understood from the scan, before any treatment decisions.

Contains: a 3D view of the arch (occlusal angle) with each tooth position colour-coded by condition (green healthy, yellow moderate concern, red requires full coverage, grey missing). Hovering any tooth reveals the AI's specific observation. A written prose summary on the right in prosthodontist-style clinical language. Two buttons: Continue, Back.

Confidence indicators are visible. If the AI is uncertain about any teeth, they are highlighted and the Continue button is disabled until the user confirms or overrides.

### Screen 3: Treatment Plan Review

Purpose: show the proposed plan and allow overrides before design begins.

Contains: a 3D arch view with each planned restoration shown in a distinct colour per type. A list of every planned restoration below with tooth number, restoration type, material, and an Edit button per row. A framework summary describing the four framework parameters in plain English. One primary button: "Approve Plan and Start Design".

The Edit button opens a small panel allowing the user to change restoration type, change material, or remove that tooth from the plan.

### Screen 4: Design in Progress

Purpose: show live progress during the 2–8 minute generation phase.

Contains: a progress indicator showing which restorations are being generated. Thumbnails of completed restorations appearing in a grid as they finish. A visualisation of the framework being applied (a diagram showing the vertical dimension increase, the planned occlusal plane).

The user can navigate away and return; progress persists.

### Screen 5: Review and Download

Purpose: allow final review and provide the download.

Contains: a synchronised split 3D viewer (before scan on the left, proposed after on the right, rotating together). A written case report below the viewer. A traffic-light status indicator (green ready, yellow review notes, red regenerate). A primary download button when status is green, providing the complete ZIP package.

An optional detailed technical view is available (collapsed by default) for clinicians who want to see the underlying measurements.

---

## 6. What The System Must NOT Do

Explicit non-goals to prevent scope creep:

**No CAD editing tools.** The system generates a complete design. Users cannot draw margins, sculpt cusps, or adjust cross-sections. If a design is wrong, the user changes the plan and regenerates.

**No lab technician features.** No user roles for technicians. No case queues. No annotation threads. This product replaces the lab, not augments it.

**No patient management.** No patient records, appointment scheduling, or clinical notes beyond what appears in the AI case report.

**No practice management integration** in the first release. Direct scanner integrations (Medit Link, iTero Cloud) come later. Initial version accepts uploaded files only.

**No aligner design.** The system focuses on fixed prosthodontics — crowns, veneers, bridges, implant crowns, onlays. Aligners are a different product.

**No claims of medical device autonomy.** The AI produces designs that a licensed dentist reviews and approves. This framing is preserved consistently across the UI, marketing, and terms of service.

---

## 7. Success Criteria

The product is considered functional when it hits all of these on 8 of 10 test cases from the internal ground-truth dataset:

- Perception accuracy: correctly classifies at least 90% of teeth. Zero teeth requiring restoration are missed as healthy.
- Treatment planning accuracy: at least 85% of planned restorations match the treatment actually performed in the after scan.
- Vertical dimension accuracy: proposed vertical dimension within 2mm of the actual after-scan measurement.
- Per-tooth height accuracy: individual restoration heights within 2mm of after-scan measurements on average.
- Full pipeline reliability: end-to-end runs to completion without crashes, and all six validation checks pass.

Once ready for live use, the primary ongoing metric is First Pass Approval Rate — the percentage of cases where the dentist downloads and uses the AI's output without modification. Target thresholds:
- Below 60%: not ready for growth
- 60–75%: viable product
- 75–90%: strong product
- Above 90%: category-defining

---

## 8. The Data Model

The system persists these entities:

**Case.** One per uploaded scan. Fields: unique ID, human-readable reference (e.g., CAD-A7B3F1), user ID, status (uploading, analysing, plan-review, designing, complete, failed), timestamps, links to all associated files and results.

**Scan.** The uploaded file. Fields: case ID, arch (upper/lower), file location (cloud storage key), mesh metrics (vertex count, surface area, volume, watertight status).

**Perception result.** The AI's clinical assessment. Fields: case ID, per-tooth condition array (tooth number, condition category, confidence, observation), overall arch summary, model version used.

**Treatment plan.** Fields: case ID, per-tooth planned restoration array (tooth number, restoration type, material, priority), framework parameters (vertical dimension change, occlusal plane, incisal target, symmetry), approval status, user overrides applied.

**Restoration output.** One per generated restoration. Fields: case ID, tooth number, restoration type, material, file location, validation check results, sintering scale applied.

**Correction.** Captured whenever the user overrides an AI decision. Fields: case ID, correction type (perception, plan, or design), original value, corrected value, timestamp. This is training data for future model improvement.

---

## 9. Integrations Required

**Anthropic Claude API.** Used for three separate call types: visual perception (with images), treatment planning (text only), and case report generation (text only). Model: Claude Sonnet 4 or successor. Estimated cost per case: under £0.05.

**Cloud file storage.** AWS S3 or equivalent. Stores uploaded scans and generated restorations. All files encrypted at rest, signed URLs for delivery.

**Authentication.** Clerk or Supabase Auth. Email + password sign-in. Session-based. No requirement for enterprise SSO in the first release.

**Database.** PostgreSQL via Supabase. Row-level security so users only see their own cases.

**Payments.** Stripe. Two products at launch: monthly unlimited (£199/month), or pay-per-case (£15/case).

**Email transactional.** Resend or SendGrid. Notifies users when cases complete, when cases fail, and for billing events.

**Monitoring.** Sentry for errors. UptimeRobot for availability. Simple database logging for case processing times and results.

No custom infrastructure required. All components are managed services with reasonable free tiers.

---

## 10. Materials and Manufacturing Specifications

The system must correctly handle these materials, each with its own minimum thickness rules and sintering compensation factor:

**Zirconia (full).** Minimum occlusal thickness 0.5mm. Minimum axial wall 0.5mm. Sintering scale factor 1.22 (files exported 22% oversized).

**Zirconia (layered).** Minimum occlusal 1.0mm. Minimum axial 0.5mm. Sintering scale factor 1.22.

**Lithium disilicate (e.max).** Minimum occlusal 1.0mm. Minimum axial 0.6mm. Sintering scale factor 1.0 (crystallised state).

**PMMA (temporary).** Minimum occlusal 1.5mm. Minimum axial 1.0mm. Sintering scale factor 1.0.

**Cobalt-chrome.** Minimum occlusal 0.3mm. Minimum axial 0.3mm. Sintering scale factor 1.0.

**Composite resin.** Minimum occlusal 1.5mm. Minimum axial 1.0mm. Sintering scale factor 1.0.

The output STL filename must reflect whether sintering compensation has been applied (`_FABRICATION_READY` suffix). No user should ever have to remember to scale a file themselves.

---

## 11. Ground Truth Dataset

The system is validated against 10 anonymised before/after case pairs already in the developer's possession. Each pair consists of four scans: upper before, upper after, lower before, lower after. All 10 cases are full-arch rehabilitations.

The validation methodology: run the full pipeline on each before scan. Measure the proposed output against the actual after scan geometrically. Compare vertical dimension, occlusal heights per tooth, arch volume, and treatment plan accuracy.

This dataset is not for machine learning training — 10 cases is far too few. It is for validating that the Claude-based reasoning pipeline produces clinically plausible outputs on real cases. Full ML training requires 500+ before/after pairs, acquired through beta clinic partnerships once the product is live.

---

## 12. Legal and Regulatory Positioning

The product is a **design aid**, not a medical device. Every design is reviewed and approved by a licensed clinician before use on a patient. This framing must be preserved throughout the UI, marketing copy, and terms of service.

Specifically:
- The UI never claims a design is "safe" or "final". It says "ready for clinical review" or "ready for fabrication after clinical verification".
- The terms of service explicitly place clinical responsibility on the user.
- The case report always includes a "clinical verification required" section.
- Downloaded files include a plain-text README stating the same.

The developer should also implement audit logging: every AI decision, every user override, every download is recorded with timestamps. This log becomes the evidence pack for eventual regulatory clearance (FDA 510(k), CE MDR class IIa).

---

## 13. Technology Constraints

The developer has flexibility in technology choice, but these constraints hold:

- The frontend must run in any modern browser (Chrome, Safari, Firefox, Edge) on desktop and tablet. No native app.
- The backend must run on standard cloud infrastructure. No specialised GPU hardware required for the first release (rendering and generation run on CPU; only future ML fine-tuning needs GPUs).
- The 3D rendering must be usable on scans up to 800,000 vertices without stalling the browser.
- All AI reasoning goes through the Claude API. The developer does not train custom ML models in the first release.
- All data is encrypted in transit and at rest. GDPR-compliant.

---

## 14. What Success Looks Like

Six months after launch:
- 20+ paying clinics
- £4,000+ monthly recurring revenue
- First Pass Approval Rate above 70%
- Zero patient safety incidents
- A ground truth dataset expanded from 10 cases to 200+ real cases contributed by beta clinics
- Documented regulatory pathway confirmed with MHRA

Twelve months after launch:
- 50+ paying clinics
- £10,000+ MRR
- FPAR above 80%
- Turkey market entry through a local partner
- 500+ case dataset — the moment when ML fine-tuning becomes worthwhile

Twenty-four months after launch:
- 200+ clinics
- Beginning FDA 510(k) submission
- Custom-trained models replacing the initial Claude-only pipeline for perception and margin detection
- Bridge and implant crown workflows shipped

---

## Appendix A — Rendered View Angles (Precise Specification)

For the perception stage, the system renders each arch scan to exactly five views. Camera positions relative to the arch centroid:

1. **Occlusal.** Position: directly above centroid at distance = 1.5× longest bounding box dimension. Direction: looking straight down.
2. **Buccal right.** Position: to the right of the arch at centroid height, distance = 1.5× width. Direction: looking horizontally inward.
3. **Buccal left.** Position: mirror of buccal right.
4. **Anterior.** Position: directly in front of the arch at centroid height, distance = 1.5× depth. Direction: looking straight back into the arch.
5. **Occlusal-anterior diagonal.** Position: above and in front, 30° elevation, 15° from midline. Direction: aimed at the arch centroid.

All renders are 1024×1024 pixels. Lighting: one ambient light plus one directional light from above.

---

## Appendix B — Tooth Numbering Convention

The system uses the Universal Numbering System (1–32).

- Teeth 1–16 are the upper arch, numbered from the patient's upper right third molar (1) to the upper left third molar (16).
- Teeth 17–32 are the lower arch, numbered from the patient's lower left third molar (17) to the lower right third molar (32).

All user-facing tooth references use this system. Alternative systems (FDI, Palmer) are not supported in the first release.

---

_This specification defines the product. Anything not in this document is out of scope for the first release._
