from typing import Any
import json

COMPONENTS = [
    "state_parseable_v2", "output_bearing_present_v2", "exclusion_safety_v2",
    "required_state_completeness_v2", "answer_state_consistency_v2",
    "intrinsic_state_validity_v2", "carried_state_validity_v2",
    "joint_answer_state_success_v2",
]

def representation_control(sidecars: dict[str, dict]) -> dict[str, Any]:
    side = sidecars["pcgds_v2_00001_api_migration_state_transition_easy"]
    required = list(side["required_state_items"])
    allowed = side["allowed_answer_paths"][0]
    final_output = {"final_answer": {"required_tokens": required, "allowed_paths": [allowed]}}
    states = {
        "rolling_summary_native": "SUMMARY=Final active tokens: " + ",".join(required) + "; allowed path: " + allowed,
        "visible_carry_native": "VISIBLE_KEEP=" + ",".join(required + [allowed]),
        "ssr_native": "OUT=" + ",".join(required) + "\nALW=" + allowed + "\nNO=API_01_D3A169,API_01_FD3DD7\nB=clean",
    }
    # Import only the scorer entry point for this synthetic control; no model
    # output or score file is altered.
    from metric_v2.production_scorer import score_row
    results = {}
    for name, state in states.items():
        scored = score_row(side, {"row_id": name, "task_id": side["source_task_id"], "final_state": state, "final_output": final_output})
        results[name] = {field: scored[field] for field in COMPONENTS + ["answer_success_v2", "state_reason_codes_v2"]}
    return {
        "task_id": side["source_task_id"], "canonical_semantics": {"required_tokens": required, "allowed_paths": [allowed]},
        "representations": results, "all_pass": all(result["carried_state_validity_v2"] for result in results.values()),
        "interpretation": "A failure means the frozen v2 field-role map is representation-sensitive for that native state encoding; it is not evidence about model quality.",
    }
