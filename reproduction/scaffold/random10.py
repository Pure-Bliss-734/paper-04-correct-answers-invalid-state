from __future__ import annotations
import json, re
from typing import Any
from scaffold import focused as B

METHOD_PROTOCOLS = {
    "loop_only": "segment_loop_no_persistent_carry_v1_ecvs_safe_visible_only",
    "rolling_summary": "plain_natural_language_rolling_summary_v1_ecvs_safe_visible_only",
    "rolling_visible_carry_forward": "rolling_visible_identifier_carry_forward_v1_ecvs_safe_visible_only",
    "rolling_visible_fields_only": "rolling_visible_fields_only_protocol_v1_pcg_dynamic_state_v2_safe_visible_only",
    "ssr_no_visible_carry": "ssr_no_visible_carry_protocol_v1_alias_ssr_only_no_deterministic_visible_carry",
    "mature_ssr_loop": "mature_ssr_loop_protocol_v1_ecvs_safe_visible_only",
}


NEGATIVE_TERMS = [
    "revoked",
    "stale",
    "forbidden",
    "protected",
    "blocked",
    "archive-only",
    "archive only",
    "rollback-only",
    "rollback only",
    "decoy",
    "not outputtable",
    "must not",
    "do not",
    "excluded",
]


POSITIVE_TERMS = [
    "initial active",
    "active tokens",
    "currently active",
    "current allowed",
    "allowed path",
    "allowed implementation path",
    "final active",
]


def visible_field_candidates(visible_text: str) -> tuple[list[str], list[str]]:
    tokens = B.dedupe_preserve(B.NEUTRAL_TOKEN_RE.findall(visible_text))
    keep: list[str] = []
    excluded: list[str] = []
    lowered = visible_text.lower()
    for token in tokens:
        positions = [idx for idx in range(len(visible_text)) if visible_text.startswith(token, idx)]
        windows = [lowered[max(0, idx - 100) : min(len(lowered), idx + len(token) + 100)] for idx in positions]
        has_negative = any(any(term in window for term in NEGATIVE_TERMS) for window in windows)
        has_positive = any(any(term in window for term in POSITIVE_TERMS) for window in windows)
        if has_negative and not has_positive:
            excluded.append(token)
        elif not has_negative or has_positive:
            keep.append(token)
    return B.dedupe_preserve(keep), B.dedupe_preserve(excluded)


def visible_allowed_paths(visible_text: str) -> tuple[list[str], list[str]]:
    paths = B.dedupe_preserve(B.PATH_RE.findall(visible_text))
    allowed: list[str] = []
    blocked: list[str] = []
    lowered = visible_text.lower()
    for path in paths:
        positions = [idx for idx in range(len(visible_text)) if visible_text.startswith(path, idx)]
        windows = [lowered[max(0, idx - 90) : min(len(lowered), idx + len(path) + 90)] for idx in positions]
        if any("blocked" in window or "attractive path" in window for window in windows):
            blocked.append(path)
        else:
            allowed.append(path)
    return B.dedupe_preserve(allowed), B.dedupe_preserve(blocked)


def build_update_prompt(method: str, task: dict[str, Any], segment: dict[str, Any], state: str, budget: int, visible_text_so_far: str) -> str:
    common = f"""Task id: {task["task_id"]}
Difficulty: {task["difficulty"]}
Family: {task["family"]}
State budget after deterministic fitting: {budget} characters

Prior transferred state:
{state or "[empty]"}

Current segment {segment["segment_id"]}/{len(task["segments"])} ({segment["role"]}):
{segment["text"]}
"""
    if method == "loop_only":
        method_block = """You are writing only a current-segment loop check.
Do not preserve prior-segment details unless they appear in the current segment.
Do not use SSR fields or deterministic visible carry.
Do not use hidden answers, oracle fields, scoring metadata, or required/forbidden arrays.
Return JSON only: {"CURRENT_GOAL":"...", "GAP":"...", "NEXT_MISTAKE_TO_AVOID":"..."}"""
    elif method == "rolling_summary":
        method_block = """You are maintaining the plain natural-language rolling-summary baseline.
Use the same base behavior as visible-carry methods, but without deterministic VISIBLE_KEEP.
Do not use SSR fields or hidden oracle/scoring material.
Return JSON only: {"SUMMARY":"..."}"""
    elif method == "rolling_visible_carry_forward":
        method_block = """You are maintaining the plain natural-language rolling-summary base.
The runner will append deterministic VISIBLE_KEEP after your state update.
Do not use SSR fields OUT/ALW/NO/B/G/N/CK/LOOP and do not use hidden oracle/scoring material.
Return JSON only: {"NOTE":"...", "BOUNDARY":"..."}"""
    elif method == "rolling_visible_fields_only":
        method_block = """You are maintaining the same natural-language rolling-summary base.
The runner will replace broad notes with compact deterministic visible fields only.
Do not use SSR fields OUT/ALW/NO/B/G/N/CK/LOOP and do not use hidden oracle/scoring material.
Return JSON only: {"NOTE":"...", "BOUNDARY":"..."}"""
    elif method == "ssr_no_visible_carry":
        method_block = """You are maintaining SSR schema without runner-side deterministic visible carry.
Use only model-visible text and prior model-visible SSR state.
Do not append all visible candidates mechanically.
NO/B may contain generic exclusion categories but must not seed the final answer.
Return JSON only: {"OUT":"...", "ALW":"...", "NO":"...", "B":"...", "G":"...", "N":"...", "CK":"..."}"""
    else:
        method_block = """You are maintaining mature SSR schema with deterministic visible-carry support.
Use only model-visible text and prior model-visible state.
NO/B may contain generic exclusion categories but must not seed the final answer.
Return JSON only: {"OUT":"...", "ALW":"...", "NO":"...", "B":"...", "G":"...", "N":"...", "CK":"...", "LOOP":"..."}"""
    return f"{method_block}\n\n{common}"


def compile_state(method: str, raw_state: str, visible_text_so_far: str, budget: int) -> tuple[str, dict[str, Any]]:
    candidates = B.extract_visible_candidates(visible_text_so_far)
    field_keep, field_excluded = visible_field_candidates(visible_text_so_far)
    allowed_paths, blocked_paths = visible_allowed_paths(visible_text_so_far)
    protocol = METHOD_PROTOCOLS[method]
    raw = raw_state.strip()
    if method in {"rolling_summary", "loop_only"}:
        rendered = raw
    elif method == "rolling_visible_carry_forward":
        rendered = f"VISIBLE_KEEP={','.join(candidates)}\nNOTE={raw}"
    elif method == "rolling_visible_fields_only":
        rendered = (
            f"VISIBLE_KEEP={','.join(field_keep)}\n"
            f"VISIBLE_ALLOWED_SCOPE={','.join(allowed_paths)}\n"
            f"VISIBLE_BOUNDARY=excluded_count:{len(field_excluded)}; blocked_path_count:{len(blocked_paths)}\n"
            "VISIBLE_NOTE=compact deterministic visible fields only"
        )
    elif method == "ssr_no_visible_carry":
        rendered = raw
    else:
        fields = B.parse_state_fields(raw)
        if fields:
            out = fields.get("OUT", "")
            alw = fields.get("ALW", fields.get("ALLOW", ""))
            no = fields.get("NO", fields.get("B", "excluded categories only"))
            rest = "\n".join(f"{k}={v}" for k, v in fields.items() if k not in {"OUT", "ALW", "ALLOW", "NO", "B"})
            rendered = f"OUT={out or ','.join(field_keep)}\nALW={alw or ','.join(allowed_paths)}\nNO={no}\nB=no forbidden/protected/revoked/stale/blocked/archive-only/rollback-only output\n{rest}"
        else:
            rendered = f"OUT={','.join(field_keep)}\nALW={','.join(allowed_paths)}\nNO=excluded categories only\nB=no forbidden/protected/revoked/stale/blocked/archive-only/rollback-only output\nG=solve final active allowed set\nN=continue\nCK=check state labels\nLOOP=boundary-risk check"
    fitted, hard_cap, before, after = B.fit_state(rendered, budget)
    audit = {
        "method_protocol_version": protocol,
        "visible_identifier_candidates_count": len(candidates),
        "visible_field_keep_count": len(field_keep),
        "visible_field_excluded_count": len(field_excluded),
        "visible_allowed_path_count": len(allowed_paths),
        "visible_blocked_path_count": len(blocked_paths),
        "visible_identifier_candidates_sha256": B.sha256_json(candidates),
        "visible_field_keep_sha256": B.sha256_json(field_keep),
        "compiler_input_visible_text_sha256": B.sha256_bytes(visible_text_so_far.encode("utf-8")),
        "compiler_input_raw_state_sha256": B.sha256_bytes(raw_state.encode("utf-8")),
        "compiler_output_state_sha256": B.sha256_bytes(fitted.encode("utf-8")),
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
        method_specific = """Mature SSR final-solve contract:
- final_answer.required_tokens must derive only from OUT.
- final_answer.allowed_paths must derive only from ALW.
- Never copy material from NO/B/G/N/CK/LOOP into required_tokens or allowed_paths."""
    elif method == "ssr_no_visible_carry":
        method_specific = """SSR-without-carry final-solve contract:
- final_answer.required_tokens must derive only from OUT.
- final_answer.allowed_paths must derive only from ALW.
- NO/B/excluded fields must not contribute output-bearing tokens."""
    elif method == "rolling_visible_fields_only":
        method_specific = """Visible-fields-only rule:
- VISIBLE_KEEP is output-bearing.
- VISIBLE_ALLOWED_SCOPE is allowed-scope evidence.
- VISIBLE_BOUNDARY and VISIBLE_NOTE are not output-bearing."""
    elif method == "rolling_visible_carry_forward":
        method_specific = """Visible-carry rule:
- VISIBLE_KEEP is output-bearing candidate state.
- NOTE/BOUNDARY may be used only to decide which visible candidates remain safe."""
    elif method == "rolling_summary":
        method_specific = "Use only the transferred natural-language summary."
    else:
        method_specific = "Use only the current-segment loop notes."
    return f"""Use only the transferred state below and the output schema instruction.
Do not use hidden answers, oracle fields, scoring metadata, or external context.
{method_specific}

Task id: {task["task_id"]}
Method: {method}

Transferred state:
{state}

Output schema instruction:
{task["final_instruction"]}

Return JSON only.
"""
