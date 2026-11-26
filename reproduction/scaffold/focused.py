from __future__ import annotations
import json, re, hashlib
from typing import Any

METHOD_PROTOCOLS = {
    "rolling_summary": "plain_natural_language_rolling_summary_v1_ecvs_safe_visible_only",
    "loop_only": "segment_loop_no_persistent_carry_v1_ecvs_safe_visible_only",
    "rolling_visible_carry_forward": "rolling_visible_identifier_carry_forward_v1_ecvs_safe_visible_only",
    "mature_ssr_loop": "mature_ssr_loop_protocol_v1_ecvs_safe_visible_only",
}


REQUESTED_MODEL = "deepseek-v4-pro"


MAX_TOKENS = 4096


TEMPERATURE = 0


THINKING_CONTROL = {"thinking": {"type": "disabled"}}


NEUTRAL_TOKEN_RE = re.compile(
    r"\b(?:REQ|CFG|API|MOD|PATH|FEATURE|FLAG|RULE|PATCH|HOOK|JOB|CHECK)_[0-9]{2}_[A-Z0-9]{6}\b"
)


PATH_RE = re.compile(r"\bsrc/[A-Za-z0-9_./-]+(?:\.py|\.yaml|\.json|\.md)\b")


STATE_FIELD_RE = re.compile(
    r"(OUT|ALW|ALLOW|NO|NO_CAT|B|BOUND|BOUNDARY|G|N|NEXT|CK|CHECK|LOOP)\s*=",
    flags=re.IGNORECASE,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def make_request_payload(prompt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": REQUESTED_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }
    payload.update(THINKING_CONTROL)
    return payload


def extract_visible_candidates(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in NEUTRAL_TOKEN_RE.findall(text):
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def dedupe_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def parse_state_fields(text: str) -> dict[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except Exception:
        obj = None
    if isinstance(obj, dict):
        return {str(key).upper(): json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value for key, value in obj.items()}
    matches = list(STATE_FIELD_RE.finditer(raw))
    if not matches:
        return {"RAW": raw}
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = match.group(1).upper()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        fields[key] = raw[start:end].strip(" ;\n\t")
    return fields


def deterministic_mature_final_output(state: str) -> str:
    fields = parse_state_fields(state)
    out_text = fields.get("OUT", "")
    alw_text = fields.get("ALW", fields.get("ALLOW", ""))
    required_tokens = dedupe_preserve(NEUTRAL_TOKEN_RE.findall(out_text))
    allowed_paths = dedupe_preserve(PATH_RE.findall(alw_text))
    payload = {
        "final_answer": {
            "required_tokens": required_tokens,
            "allowed_paths": allowed_paths,
            "state_labels": {},
            "state_transitions": [],
            "boundary_checks": {
                "construction": "deterministic_from_mature_ssr_slots",
                "source_for_required_tokens": "OUT",
                "source_for_allowed_paths": "ALW",
                "no_NO_or_B_material_copied": True,
            },
        }
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def fit_state(text: str, budget: int) -> tuple[str, bool, int, int]:
    before = len(text)
    if before <= budget:
        return text, False, before, len(text)
    return text[:budget], True, before, budget


def build_update_prompt(method: str, task: dict[str, Any], segment: dict[str, Any], state: str, budget: int, visible_text_so_far: str) -> str:
    if method == "rolling_summary":
        method_block = """You are maintaining a plain natural-language rolling summary for later solving.
Use only the current model-visible segment and prior transferred summary.
Do not use hidden answers, labels, oracle fields, scoring metadata, or required/forbidden/protected token arrays.
Do not use typed state fields, deterministic visible-token carry, SSR fields, or special slot labels.
Keep only information you judge useful for the final answer; remove obsolete or excluded material when you can infer it from visible text."""
        schema = '{"SUMMARY":"..."}'
    elif method == "loop_only":
        method_block = """You are processing the current model-visible segment only.
Do not preserve prior segment details except what is explicitly present in this current segment.
Do not use hidden answers, labels, oracle fields, scoring metadata, or required/forbidden/protected token arrays.
Do not use typed state fields, deterministic visible-token carry, SSR fields, or special slot labels."""
        schema = '{"CURRENT_SEGMENT_NOTES":"..."}'
    elif method == "rolling_visible_carry_forward":
        method_block = """You are maintaining a compact visible-only rolling state.
Use only the current model-visible segment and prior transferred state.
Do not use hidden answers, labels, oracle fields, scoring metadata, or required/forbidden/protected token arrays.
Write ordinary compact notes. Do not use SSR fields OUT/ALW/NO/B/G/N/CK/LOOP."""
        schema = '{"NOTE":"...", "BOUNDARY":"..."}'
    else:
        method_block = """You are maintaining a compact structured state for later solving.
Use only the current model-visible segment and prior transferred state.
Do not use hidden answers, labels, oracle fields, scoring metadata, or required/forbidden/protected token arrays.
Use compact fields OUT, ALW, NO, B, G, N, CK, LOOP. NO and B should use generic categories and visible evidence only."""
        schema = '{"OUT":"...", "ALW":"...", "NO":"...", "B":"...", "G":"...", "N":"...", "CK":"...", "LOOP":"..."}'
    return f"""{method_block}

Task id: {task["task_id"]}
Difficulty: {task["difficulty"]}
Family: {task["family"]}
State budget after deterministic fitting: {budget} characters

Prior transferred state:
{state or "[empty]"}

Current segment {segment["segment_id"]}/{len(task["segments"])} ({segment["role"]}):
{segment["text"]}

Return JSON only in this schema:
{schema}
"""


def compile_state(method: str, raw_state: str, visible_text_so_far: str, budget: int) -> tuple[str, dict[str, Any]]:
    candidates = extract_visible_candidates(visible_text_so_far)
    if method == "rolling_summary":
        rendered = raw_state.strip()
        protocol = METHOD_PROTOCOLS[method]
    elif method == "loop_only":
        rendered = raw_state.strip()
        protocol = METHOD_PROTOCOLS[method]
    elif method == "rolling_visible_carry_forward":
        rendered = f"VISIBLE_KEEP={','.join(candidates)}\nNOTE={raw_state.strip()}"
        protocol = METHOD_PROTOCOLS[method]
    else:
        rendered = raw_state.strip()
        if "OUT" not in rendered:
            rendered = f"OUT={','.join(candidates)}\nALW=visible allowed scope only\nNO=excluded or unsafe categories only\nB=no forbidden/protected/revoked/stale/blocked/archive-only/rollback-only output\nG=solve final active allowed set\nN=continue\nCK=check state labels\nLOOP=boundary-risk check"
        protocol = METHOD_PROTOCOLS[method]
    fitted, hard_cap, before, after = fit_state(rendered, budget)
    audit = {
        "method_protocol_version": protocol,
        "visible_identifier_candidates_count": len(candidates),
        "visible_identifier_candidates_sha256": sha256_json(candidates),
        "compiler_input_visible_text_sha256": sha256_bytes(visible_text_so_far.encode("utf-8")),
        "compiler_input_raw_state_sha256": sha256_bytes(raw_state.encode("utf-8")),
        "compiler_output_state_sha256": sha256_bytes(fitted.encode("utf-8")),
        "state_chars_before_budget": before,
        "state_chars_after_budget": after,
        "state_budget": budget,
        "state_budget_fit_success": len(fitted) <= budget,
        "state_hard_cap_used": hard_cap,
        "compiler_forbidden_source_check": "visible_only_no_oracle",
    }
    return fitted, audit


def build_final_prompt(method: str, task: dict[str, Any], state: str) -> str:
    if method == "mature_ssr_loop":
        method_specific = """Mature SSR slot-transfer rule:
- Treat OUT as the only source for final_answer.required_tokens.
- Treat ALW as the only source for final_answer.allowed_paths.
- Extract neutral task tokens only from OUT, and path-like strings only from ALW.
- Never copy anything from NO, B, G, N, CK, LOOP, notes, boundaries, or exclusion fields into required_tokens or allowed_paths.
- If OUT or ALW is empty, return an empty list for that field rather than guessing from NO/B or the original task."""
    elif method == "rolling_visible_carry_forward":
        method_specific = """Visible-carry rule:
- VISIBLE_KEEP is an output-bearing carried field. If it contains excluded candidates, that is a state-governance failure.
- Use NOTE/BOUNDARY only to decide which VISIBLE_KEEP items are safe for final_answer.required_tokens."""
    elif method == "rolling_summary":
        method_specific = """Rolling-summary rule:
- Use only the transferred natural-language summary.
- Do not infer from hidden oracle fields or scorer metadata.
- Output only items the summary supports as currently active/allowed."""
    else:
        method_specific = """Loop-only rule:
- Use only the final transferred current-segment notes.
- Do not reconstruct prior state unless it is present in those notes.
- Output only items the notes support as currently active/allowed."""
    return f"""Use only the transferred state below and the output schema instruction.
Do not use hidden answers, oracle fields, scoring metadata, or any external context.
State-governance rule: output-bearing transferred-state fields such as OUT, ALW, VISIBLE_KEEP, ACTIVE, REQUIRED, or equivalent keep/output fields may only support active or allowed material in the final answer. Excluded candidates may be named only in state_labels, state_transitions, boundary_checks, NO/EXCLUDED fields, or explicit exclusion notes.
{method_specific}

Task id: {task["task_id"]}
Method: {method}

Transferred state:
{state}

Output schema instruction:
{task["final_instruction"]}

Return JSON only.
"""
