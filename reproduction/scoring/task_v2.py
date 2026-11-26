from __future__ import annotations


def derive(row: dict, source_hash: str) -> dict:
    oracle = row["oracle"]
    labels = oracle.get("expected_state_labels", {})
    universe = list(dict.fromkeys(
        list(labels.keys()) + list(oracle.get("required_exact_tokens", []))
        + list(oracle.get("allowed_paths", [])) + list(oracle.get("blocked_paths", []))
    ))
    disallowed = list(dict.fromkeys(
        list(oracle.get("final_excluded_set", [])) + list(oracle.get("blocked_paths", []))
    ))
    return {
        "sidecar_schema": "carried_state_validity_v2.oracle_sidecar.v1",
        "derivation_version": "metric_v2_oracle_derivation_20260813",
        "source_oracle_sha256": source_hash,
        "source_task_id": row["task_id"],
        "family": row.get("family", ""),
        "task_relevant_item_universe": universe,
        "required_state_items": list(oracle.get("required_exact_tokens", [])),
        "optional_allowed_items": list(oracle.get("allowed_paths", [])),
        "disallowed_output_items": disallowed,
        "globally_secret_or_oracle_only_items": list(oracle.get("oracle_only_literals", [])),
        "final_item_statuses": dict(labels),
        "required_answer_items": list(oracle.get("required_exact_tokens", [])),
        "allowed_answer_paths": list(oracle.get("allowed_paths", [])),
        "blocked_paths": list(oracle.get("blocked_paths", [])),
        "forbidden_exact_tokens": list(oracle.get("forbidden_exact_tokens", [])),
        "protected_exact_tokens": list(oracle.get("protected_exact_tokens", [])),
        "revoked_exact_tokens": list(oracle.get("revoked_exact_tokens", [])),
        "stale_exact_tokens": list(oracle.get("stale_exact_tokens", [])),
        "expected_state_labels": dict(oracle.get("expected_state_labels", {})),
        "expected_state_transitions": list(oracle.get("expected_state_transitions", [])),
    }


