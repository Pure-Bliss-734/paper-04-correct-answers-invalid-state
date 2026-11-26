from __future__ import annotations


def derive(row: dict, source_hash: str) -> dict:
    active = [item for item, label in row.get("final_item_statuses", {}).items()
              if str(label).lower() == "active"]
    options = list(row.get("allowed_answer_paths", row.get("optional_allowed_items", [])))
    universe = list(dict.fromkeys(row.get("task_relevant_item_universe", []) + active + options))
    return {
        "sidecar_schema": "carried_state_validity_v3.oracle_sidecar.v1",
        "derivation_version": "metric_v3_oracle_derivation_20260813",
        "source_sidecar_sha256": source_hash,
        "source_task_id": row["source_task_id"],
        "family": row.get("family", ""),
        "task_relevant_item_universe": universe,
        "mandatory_current_facts": active,
        "admissible_action_options": options,
        "action_option_requirements": {option: active for option in options},
        "disallowed_output_items": list(row.get("disallowed_output_items", [])),
        "globally_secret_or_oracle_only_items": list(row.get("globally_secret_or_oracle_only_items", [])),
        # These labels are retained as audit metadata for the contract; the
        # adapter never receives them and never consults them.
        "final_item_statuses": dict(row.get("final_item_statuses", {})),
        "expected_state_transitions": list(row.get("expected_state_transitions", [])),
        "required_answer_items": list(row.get("required_answer_items", [])),
        "allowed_answer_paths": options,
        "blocked_paths": list(row.get("blocked_paths", [])),
    }


