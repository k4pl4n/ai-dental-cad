"""Anthropic Claude API wrapper. (SPEC §9)

Three call types: perception (vision), planning (text), report (text).
Strict-JSON calls reject and retry once on malformed responses.

MOCK_MODE (env AIDCAD_MOCK=1) returns deterministic canned responses so the
full pipeline can be exercised without an API key — dev/test only.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re

log = logging.getLogger(__name__)

MODEL = os.environ.get("AIDCAD_MODEL", "claude-sonnet-4-20250514")
MOCK = os.environ.get("AIDCAD_MOCK", "0") == "1"
MAX_JSON_RETRIES = 2


class ClaudeError(Exception):
    pass


def _client():
    try:
        import anthropic
    except ImportError as e:
        raise ClaudeError("anthropic package not installed (pip install anthropic)") from e
    return anthropic.Anthropic()  # ANTHROPIC_API_KEY from env


def _image_block(path: str) -> dict:
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": data}}


def _extract_json(text: str) -> dict:
    """Tolerate accidental markdown fences; otherwise require raw JSON."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start:end + 1])


def _call(system: str, content: list | str, max_tokens: int = 4096) -> str:
    client = _client()
    msg = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


def call_json(system: str, content: list | str, max_tokens: int = 4096) -> tuple[dict, str]:
    """Strict-JSON call with retry. Returns (parsed, model_version)."""
    last_err: Exception | None = None
    for attempt in range(MAX_JSON_RETRIES + 1):
        text = _call(system, content, max_tokens)
        try:
            return _extract_json(text), MODEL
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            log.warning("malformed JSON from model (attempt %d): %s", attempt + 1, e)
            if isinstance(content, str):
                content = content + "\n\nREMINDER: respond with ONLY the JSON object. No prose."
    raise ClaudeError(f"model returned malformed JSON after retries: {last_err}")


def call_text(system: str, prompt: str, max_tokens: int = 2048) -> str:
    return _call(system, prompt, max_tokens)


# ------------------------------------------------------------ public API

def perception_call(prompt: str, image_paths: list[str],
                    tooth_range: tuple[int, int] = (1, 16)) -> tuple[dict, str]:
    if MOCK:
        return _mock_perception(*tooth_range), "mock"
    content = [_image_block(p) for p in image_paths] + [{"type": "text", "text": prompt}]
    from ..prompts.perception import PERCEPTION_SYSTEM
    return call_json(PERCEPTION_SYSTEM, content, max_tokens=8192)


def planning_call(prompt: str) -> tuple[dict, str]:
    if MOCK:
        lower = '"arch": "lower"' in prompt
        return _mock_plan(lower), "mock"
    from ..prompts.planning import PLANNING_SYSTEM
    return call_json(PLANNING_SYSTEM, prompt, max_tokens=4096)


def report_call(prompt: str) -> str:
    if MOCK:
        return _mock_report()
    from ..prompts.report import REPORT_SYSTEM
    return call_text(REPORT_SYSTEM, prompt, max_tokens=2048)


# ------------------------------------------------------------- mock data

def _mock_perception(lo: int = 1, hi: int = 16) -> dict:
    teeth = []
    for num in range(lo, hi + 1):
        n = num if num <= 16 else 33 - num           # mirror lower to upper pattern
        if n in (1, 16):
            cond, sev, conf, obs = "missing", None, 0.95, "No tooth at this position; smooth ridge (third molar site)."
        elif n in (3, 14):
            cond, sev, conf, obs = "prep_stump", None, 0.88, "Truncated cone with uniform tapered walls and no cusp anatomy; clear margin at base."
        elif n in (8, 9):
            cond, sev, conf, obs = "natural_worn", "severe", 0.86, "Incisal edge flat with marked crown height loss; over half of clinical crown lost."
        elif n in (7, 10):
            cond, sev, conf, obs = "natural_worn", "moderate", 0.82, "Blunted incisal edge, visible height reduction."
        elif n == 5:
            cond, sev, conf, obs = "missing", None, 0.91, "Edentulous gap; adjacent teeth intact."
        elif n in (2, 15):
            cond, sev, conf, obs = "natural_worn", "moderate", 0.8, "Flattened occlusal surface with blunted cusps."
        else:
            cond, sev, conf, obs = "natural_healthy", None, 0.9, "Intact cusp anatomy, normal crown height."
        teeth.append({"tooth_number": num, "condition": cond, "wear_severity": sev,
                      "confidence": conf, "observation": obs})
    return {
        "teeth": teeth,
        "arch_summary": ("The upper arch presents generalised moderate-to-severe wear with reduced "
                         "vertical dimension. Teeth 3 and 14 are prepared for full-coverage crowns. "
                         "Tooth 5 is missing with intact neighbours. The anterior segment shows marked "
                         "incisal wear consistent with parafunction."),
        "vertical_dimension_status": "moderately reduced",
        "occlusal_plane_note": "Occlusal plane essentially level; no cant correction indicated.",
        "scan_quality_issues": [],
    }


def _mock_plan(lower: bool = False) -> dict:
    def r(tooth, rtype, mat, pri, prep, why):
        if lower:
            tooth = 33 - tooth                       # mirror to lower numbering
        return {"tooth_number": tooth, "restoration_type": rtype, "material": mat,
                "priority": pri, "needs_physical_preparation": prep, "rationale": why}
    return {
        "restorations": [
            r(2, "full_crown", "zirconia", 1, True, "Moderate wear in full-arch case; uniform coverage."),
            r(3, "full_crown", "zirconia", 1, False, "Prepared stump ready for crown."),
            r(14, "full_crown", "zirconia", 1, False, "Prepared stump ready for crown."),
            r(15, "full_crown", "zirconia", 1, True, "Moderate wear in full-arch case; uniform coverage."),
            r(7, "full_crown", "zirconia_layered", 4, True, "Moderate incisal wear; incisal repositioning required."),
            r(8, "full_crown", "zirconia_layered", 4, True, "Severe wear >50% crown height; full coverage."),
            r(9, "full_crown", "zirconia_layered", 4, True, "Severe wear >50% crown height; full coverage."),
            r(10, "full_crown", "zirconia_layered", 4, True, "Moderate incisal wear; incisal repositioning required."),
        ],
        "framework": {"vd_increase_mm": 3.0, "occlusal_plane_tilt_deg": 0.0,
                      "incisal_crown_length_mm": 11.0, "symmetric": True,
                      "symmetry_rationale": ""},
        "plan_summary": ("Full-arch rehabilitation restoring lost vertical dimension by 3mm. Posterior "
                         "support established with zirconia crowns on 2, 3, 14, 15; anterior aesthetics "
                         "and incisal edge position restored with layered zirconia on 7–10. Tooth 5 gap "
                         "noted; no fixture visible — implant consult recommended."),
    }


def _mock_report() -> str:
    return ("The patient presents with a moderately worn upper arch and reduced vertical dimension. "
            "Assessment identifies prepared stumps at teeth 3 and 14, severe anterior wear at 8 and 9, "
            "moderate wear at 2, 7, 10 and 15, and an edentulous space at tooth 5.\n\n"
            "The approved plan restores eight teeth: posterior zirconia crowns establishing a 3mm "
            "increase in vertical dimension, and layered zirconia anterior crowns repositioning the "
            "incisal edges to an 11mm central incisor length. The occlusal plane is maintained level. "
            "Left and right sides are designed symmetrically.\n\n"
            "All restorations are generated against the shared framework; posterior support teeth "
            "define the vertical dimension and anterior restorations follow the incisal curve. "
            "Validation confirms watertight geometry, material thickness above minimums, vertical "
            "dimension within tolerance, balanced occlusal contacts and correct interproximal contacts. "
            "Zirconia units are exported with 1.22 sintering compensation.\n\n"
            "Clinical verification required: teeth 2, 7, 8, 9, 10 and 15 are worn but not prepared — "
            "physical preparation is required before these restorations can be seated. The design "
            "assumes the scanned tissue is stable. Tooth 5 remains unrestored; implant placement should "
            "be discussed. Every restoration requires clinical review and approval by the treating "
            "dentist before fabrication and fitting.")
