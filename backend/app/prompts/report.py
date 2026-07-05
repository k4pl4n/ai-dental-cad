"""Case report prompt. (DEV_PLAN Part 5 — case report blueprint)

Third Claude call, after generation and validation. The only prompt
that returns free text.
"""

REPORT_SYSTEM = """You are a prosthodontist dictating a clinical case report for a colleague. Third person. Present tense. Clinical dictation register. No marketing language. No emojis. No headings other than those requested. 400–800 words."""


def build_report_prompt(perception_summary: str, plan_json: str,
                        framework_json: str, validation_json: str,
                        prep_teeth: list[int], uncertain_teeth: list[int]) -> str:
    prep = ", ".join(str(t) for t in prep_teeth) or "none"
    uncertain = ", ".join(str(t) for t in uncertain_teeth) or "none"
    return f"""Write the clinical case report for this completed AI-assisted restoration design case.

## Source material

CLINICAL ASSESSMENT SUMMARY:
{perception_summary}

APPROVED TREATMENT PLAN:
{plan_json}

FRAMEWORK PARAMETERS APPLIED:
{framework_json}

VALIDATION RESULTS (six checks):
{validation_json}

TEETH REQUIRING PHYSICAL PREPARATION BEFORE FITTING: {prep}
TEETH WITH UNCERTAIN AI CLASSIFICATION (clinician confirmed or overrode): {uncertain}

## Structure — use exactly these five sections

1. Findings — what the assessment found, arch condition, vertical dimension status.
2. Treatment plan — what was planned and why, including any dentist overrides.
3. Design — what was designed: restoration count, materials, framework parameters in plain clinical terms.
4. Validation — the six checks and their outcomes; state plainly anything that did not pass.
5. Clinical verification required — what the clinician must verify before fitting: teeth requiring physical preparation, assumptions made, uncertain classifications, and a reminder that every restoration requires clinical review before use. This section is mandatory even when everything passed.

Length: 400–800 words. Prose only — no bullet lists, no JSON."""
