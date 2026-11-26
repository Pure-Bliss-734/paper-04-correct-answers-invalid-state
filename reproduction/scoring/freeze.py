from __future__ import annotations
import json, hashlib
from typing import Any

METHOD_PROTOCOLS = {
    "loop_only": "segment_loop_no_persistent_carry_v1_ecvs_safe_visible_only",
    "rolling_summary": "plain_natural_language_rolling_summary_v1_ecvs_safe_visible_only",
    "rolling_visible_carry_forward": "rolling_visible_identifier_carry_forward_v1_ecvs_safe_visible_only",
    "rolling_visible_fields_only": "rolling_visible_fields_only_protocol_v1_pcg_dynamic_state_v2_safe_visible_only",
    "ssr_no_visible_carry": "ssr_no_visible_carry_protocol_v1_alias_ssr_only_no_deterministic_visible_carry",
    "mature_ssr_loop": "mature_ssr_loop_protocol_v1_ecvs_safe_visible_only",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def prompt_template_fingerprint(method: str) -> str:
    if method == "rolling_summary":
        method_block = "plain natural-language rolling summary; no typed fields; no deterministic visible-token carry"
    elif method == "loop_only":
        method_block = "current segment only; no persistent carry"
    elif method == "rolling_visible_carry_forward":
        method_block = "visible-only rolling state with VISIBLE_KEEP-style output-bearing carry"
    elif method == "rolling_visible_fields_only":
        method_block = "visible-field negative control; deterministic field carry without SSR attribution"
    elif method == "ssr_no_visible_carry":
        method_block = "SSR schema without deterministic visible-token carry"
    else:
        method_block = "mature SSR loop with OUT/ALW/NO/B/G/N/CK/LOOP slots"
    template = {
        "prompt_builder_version": "pcg_dynamic_state_v2_state_transfer_prompt_builder_20260623_v1",
        "method": method,
        "method_protocol_version": METHOD_PROTOCOLS[method],
        "state_update_policy": method_block,
        "final_prompt_policy": "use only transferred state plus output schema; no hidden answers, oracle fields, scoring metadata, or external context",
        "state_budget_in_prompt": True,
        "task_segments_in_prompt": True,
    }
    return sha256_json(template)


def initial_user_prompt_hash(task: dict[str, Any], method: str, budget: int) -> str:
    segment = task["segments"][0]
    prompt = {
        "prompt_builder_version": "pcg_dynamic_state_v2_state_transfer_prompt_builder_20260623_v1",
        "method": method,
        "task_id": task["task_id"],
        "difficulty": task["difficulty"],
        "family": task["family"],
        "state_budget": budget,
        "prior_transferred_state": "[empty]",
        "segment_id": segment["segment_id"],
        "segment_role": segment["role"],
        "segment_text": segment["text"],
        "output_schema": "method-specific JSON state update",
    }
    return sha256_json(prompt)


