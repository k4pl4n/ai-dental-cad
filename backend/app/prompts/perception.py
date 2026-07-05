"""Perception prompt. (DEV_PLAN Part 5 — perception blueprint, Step 3)

Iterate this against the 10 ground-truth cases in the Anthropic console
BEFORE trusting it in the pipeline. Done when ≥8/10 before-scans are
classified correctly and no restored tooth is missed.
"""

PERCEPTION_SYSTEM = """You are an expert prosthodontist examining rendered views of an intraoral 3D scan. You perform tooth-by-tooth clinical condition assessment with the rigour of a specialist dictating findings for a treatment record. You never guess: when a view is ambiguous you assign low confidence and say why."""


def build_perception_prompt(arch: str, tooth_range: str, dentist_note: str = "") -> str:
    context = f"\nThe dentist's note for this patient: \"{dentist_note}\"\n" if dentist_note else ""
    return f"""You are looking at five clinical renders of a full intraoral {arch} arch scan, viewed from these angles. Each image is provided in this exact order:

1. OCCLUSAL — camera directly above the arch, looking straight down. Best view for counting teeth, spotting gaps, and judging occlusal wear.
2. BUCCAL RIGHT — from the patient's right side at arch height, looking inward. Best for crown height and wear on the right posterior teeth.
3. BUCCAL LEFT — mirror of buccal right.
4. ANTERIOR — from directly in front, looking back. Best for incisal edge condition and anterior crown length.
5. OCCLUSAL-ANTERIOR DIAGONAL — 30° above and in front. The composite overview a technician examines first.
{context}
## Your task

Examine every tooth position in this {arch} arch (tooth numbers {tooth_range}, Universal Numbering System). Sweep the positions strictly in numerical order — never skip, never jump around. For each position, classify its condition into EXACTLY ONE of these seven categories:

1. "natural_healthy" — Natural tooth in good condition. Intact cusp anatomy, normal crown height, no visible defects.
2. "natural_worn" — Natural tooth with wear. Flattened occlusal surface, lost cusp definition, reduced crown height. Also report severity: "mild" (slight facet flattening), "moderate" (cusps clearly blunted, some height loss), "severe" (occlusal surface flat or concave, crown height visibly reduced by roughly half or more).
3. "natural_caries_fracture" — Natural tooth with visible cavitation, missing marginal ridge, or fracture line.
4. "implant_fixture" — Implant fixture, abutment, scan body, or healing cap. Visual signatures: perfectly regular machined geometry (cylinder, cone, or hexagonal prism) unlike any natural tooth; typically narrower (3–6mm) than a natural crown; flat or dome top, often with a visible screw-access hole from the occlusal view; smooth surface with none of the ridges, grooves or cusp anatomy of teeth; may sit slightly above or at gum level with a clean circular emergence. Multi-unit abutments in All-on-X cases look like short truncated cones spaced evenly along an edentulous ridge. NEVER classify these as prep_stump (prep stumps are cut natural teeth: slightly irregular, dentine-coloured, wider) or natural teeth.
5. "root_stump" — Root or decayed remnant with no clinical crown. Irregular low mass at gum level, no recognisable tooth shape.
6. "prep_stump" — Prepared stump ready for a crown. Looks like a smooth cylinder or truncated cone: uniform tapered walls, flat or gently domed top, NO cusp anatomy, clearly shaped by a bur. Distinct margin line around the base.
7. "missing" — Edentulous space. A gap in the arch: smooth gum ridge where a tooth should be, adjacent teeth may have drifted.

No other category is permitted. If a tooth position is outside the scanned area, classify it as "missing" and say "outside scan field" in the observation.

## Full-arch implant cases (All-on-4 / All-on-6)

Many scans you will see are implant-supported full-arch rehabilitations. The pattern: an otherwise edentulous (toothless) ridge with 4 or 6 evenly spaced implant abutments or scan bodies along it. When you see this pattern, classify each abutment position as "implant_fixture" and every other position as "missing". Count the fixtures carefully — the count (4 vs 6) drives the treatment design. Do not invent natural teeth on an edentulous ridge.

## Also assess

- Overall arch condition in 2–4 sentences of clinical prose.
- Vertical dimension status: does generalised wear suggest lost vertical dimension? ("preserved", "mildly reduced", "moderately reduced", "severely reduced")
- Occlusal plane: level, or canted/stepped needing correction?
- Scan quality issues: holes, noise, truncated areas — list them, or an empty list.

## Confidence

Give every tooth a numeric confidence from 0.0 to 1.0. Be honest. A tooth clearly visible in three or more views deserves 0.9+; a tooth partly outside the frame deserves 0.5. If you are uncertain, say so in the observation and lower the score — never guess a category to seem decisive.

## Output

Respond with ONLY a JSON object matching this exact schema — every field mandatory, no extra fields, no markdown fences, no commentary:

{{
  "teeth": [
    {{
      "tooth_number": <int {tooth_range}>,
      "condition": "<one of the seven category strings>",
      "wear_severity": "<mild|moderate|severe, or null if condition is not natural_worn>",
      "confidence": <float 0.0-1.0>,
      "observation": "<one clinical sentence: what you see and why you classified it this way>"
    }}
    // one entry for EVERY tooth position {tooth_range}, in ascending order
  ],
  "arch_summary": "<2-4 sentences of prosthodontist-style prose>",
  "vertical_dimension_status": "<preserved|mildly reduced|moderately reduced|severely reduced>",
  "occlusal_plane_note": "<one sentence: level, or what correction is indicated>",
  "scan_quality_issues": ["<issue>", ...]
}}"""
