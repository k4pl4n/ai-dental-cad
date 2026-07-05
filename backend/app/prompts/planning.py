"""Treatment planning prompt. (DEV_PLAN Part 5 — planning blueprint, Step 4)

Perception is WHAT IS THERE. Planning is WHAT TO DO ABOUT IT.
The clinical algorithm is written into the prompt — Claude should not
reason from first principles.
"""

PLANNING_SYSTEM = """You are an expert prosthodontist producing a full-mouth rehabilitation plan from a completed clinical assessment. You follow the clinical algorithm you are given exactly. You output strict JSON only."""


def build_planning_prompt(perception_json: str, dentist_note: str, arch: str,
                          bite_context: str = "") -> str:
    note = dentist_note.strip() or "(none provided)"
    return f"""## Clinical assessment (per-tooth perception output for the {arch} arch)

{perception_json}

## Dentist's request

"{note}"
{bite_context}

## Clinical algorithm — apply these rules exactly

- natural_healthy → no restoration. Do not include in the plan.
- natural_worn, severity mild → no restoration unless the dentist's request says otherwise.
- natural_worn, severity moderate → onlay or full crown; choose full crown when neighbouring teeth are also being restored (full-arch cases favour uniform full coverage).
- natural_worn, severity severe (>50% clinical crown height loss) → full crown. Mark needs_physical_preparation = true (the tooth is worn, not prepared — the dentist must prep it before fitting).
- natural_caries_fracture → full crown if structural loss is extensive, onlay if localised. Mark needs_physical_preparation = true.
- prep_stump → full crown. needs_physical_preparation = false.
- root_stump → full crown, needs_physical_preparation = true, and note in rationale that the dentist must confirm restorability (possible extraction + implant instead).
- implant_fixture → implant_crown on that fixture.
- missing, adjacent teeth are healthy natural → implant_crown only if an implant fixture is visible at that site; otherwise leave unrestored and note the gap in plan_summary.
- missing, adjacent teeth are being restored → bridge_pontic spanning between the adjacent restorations.
- Anterior wear cases (any worn incisor or canine) → the plan MUST include incisal edge repositioning via the anterior incisal target parameter.

FULL-ARCH IMPLANT CASES (All-on-4 / All-on-6) — apply when the assessment shows 4–6 implant_fixture positions on an otherwise edentulous arch, or the dentist's request mentions All-on-4/All-on-6/full-arch implant prosthesis:
- Plan an implant-supported full-arch bridge: implant_crown at every implant_fixture position, and bridge_pontic at every other position that should carry a visible tooth (second molar to second molar — 12 units per arch is standard; skip third molars).
- Material: zirconia for all units (monolithic full-arch zirconia bridge), zirconia_layered for the anterior units if aesthetics are emphasised in the request.
- needs_physical_preparation = false for all units (the arch is implant-borne).
- State clearly in plan_summary that the units form ONE fused full-arch bridge screwed onto the fixtures, and how many fixtures support it.
- The 16-restorations-per-arch limit still applies; a standard All-on-X plan has 12 units per arch.

Material defaults: zirconia for posterior full crowns and bridge pontics; zirconia_layered or lithium_disilicate for anterior crowns and veneers (prefer lithium_disilicate for single anteriors, zirconia_layered in full-arch cases); zirconia for implant crowns. Override only with clinical justification in the rationale.

Design priority by position — this is generation order, not importance:
- 1: molars (posterior support — they define vertical dimension)
- 2: premolars
- 3: canines
- 4: incisors

## Framework parameters — you must output all four

- vd_increase_mm: how much to raise vertical dimension, in millimetres (0 if preserved). Base it on the assessed VD status: mildly reduced ≈ 1–2mm, moderately ≈ 2–4mm, severely ≈ 4–6mm. NEVER exceed 8.
- occlusal_plane_tilt_deg: correction tilt in degrees (0 if level). Range -15 to 15.
- incisal_crown_length_mm: target anterior central incisor crown length in mm (natural range 10–12; NEVER exceed 12).
- symmetric: true unless asymmetry is clinically indicated — if false, give the reason in symmetry_rationale.

## Sanity constraints — your plan is REJECTED if it violates any

- Maximum 16 restorations in this arch.
- vd_increase_mm ≤ 8.
- incisal_crown_length_mm ≤ 12.

## Output

ONLY this JSON object — every field mandatory, no markdown fences, no commentary:

{{
  "restorations": [
    {{
      "tooth_number": <int>,
      "restoration_type": "<full_crown|veneer|inlay|onlay|bridge_pontic|implant_crown>",
      "material": "<zirconia|zirconia_layered|lithium_disilicate|pmma|cobalt_chrome|composite>",
      "priority": <1|2|3|4>,
      "needs_physical_preparation": <true|false>,
      "rationale": "<one sentence>"
    }}
  ],
  "framework": {{
    "vd_increase_mm": <float>,
    "occlusal_plane_tilt_deg": <float>,
    "incisal_crown_length_mm": <float>,
    "symmetric": <true|false>,
    "symmetry_rationale": "<string, may be empty>"
  }},
  "plan_summary": "<2-4 sentences of clinical prose describing the rehabilitation strategy>"
}}"""
