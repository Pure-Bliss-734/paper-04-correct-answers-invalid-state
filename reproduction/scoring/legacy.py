from __future__ import annotations
import json
from typing import Any
from scoring import base as BASE

def _state_text(final_state: Any) -> str:
    if isinstance(final_state, str):
        return final_state
    return json.dumps(final_state, ensure_ascii=False, sort_keys=True)


def state_carry_surface_present(task: dict[str, Any], output_row: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Require non-empty carried state with output-bearing evidence.

    A state is governance-bearing if it carries at least one required active
    token in any parsed state surface, or if it contains an output-bearing state
    field.  This is deliberately stricter than "no contradiction"; an empty
    state is not a governed state.
    """
    final_state = _state_text(output_row.get("final_state", ""))
    fields = BASE.parse_state_fields(final_state)
    all_text = "\n".join(fields.values()) if fields else final_state
    output_bearing_text = BASE.state_surface(fields, BASE.OUTPUT_BEARING_STATE_FIELDS)
    required = list(task["oracle"]["required_exact_tokens"])
    allowed_paths = list(task["oracle"].get("allowed_paths", []))

    required_token_present = any(token in all_text for token in required)
    allowed_path_present = any(path in all_text for path in allowed_paths)
    output_field_present = bool(output_bearing_text.strip())
    non_empty_state = bool(final_state.strip())
    present = non_empty_state and (required_token_present or allowed_path_present or output_field_present)
    audit = {
        "non_empty_state": non_empty_state,
        "required_token_present_in_state": required_token_present,
        "allowed_path_present_in_state": allowed_path_present,
        "output_bearing_state_field_present": output_field_present,
        "parsed_state_fields": sorted(fields.keys()),
    }
    return present, audit


def score_task(task: dict[str, Any], output_row: dict[str, Any]) -> dict[str, Any]:
    score = BASE.score_task(task, output_row)
    carry_present, audit = state_carry_surface_present(task, output_row)
    legacy_governance = bool(score["state_governance_success"])
    strict_governance = legacy_governance and carry_present

    score["state_governance_success_legacy_no_conflict_only"] = legacy_governance
    score["state_carry_surface_present"] = carry_present
    score["state_governance_success"] = strict_governance
    score["reliable_composite_success"] = bool(score["answer_success"]) and strict_governance
    score["reliable_success"] = score["reliable_composite_success"]
    score["state_governance_audit"] = audit
    return score


