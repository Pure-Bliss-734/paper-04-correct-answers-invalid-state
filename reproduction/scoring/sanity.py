from __future__ import annotations
from typing import Any

def build_prompt(task: dict[str, Any]) -> str:
    segments = "\n\n".join(f"[{segment['role']} {segment['segment_id']}]\n{segment['text']}" for segment in task["segments"])
    return (
        "You are solving a deterministic state-carry evaluation task.\n"
        "Use only the visible task text below. Do not invent tokens or paths.\n"
        "Return JSON only. The JSON must contain:\n"
        "- final_answer.required_tokens: exactly the final active token set.\n"
        "- final_answer.allowed_paths: only currently allowed paths.\n"
        "- final_answer.state_labels: map every visible candidate token to active, revoked, stale, forbidden, protected, blocked, archive_only, rollback_only, decoy, or allowed.\n"
        "- final_answer.state_transitions: the state changes used.\n"
        "- final_answer.boundary_checks: booleans confirming no revoked, stale, forbidden, protected, blocked, archive-only, rollback-only, or decoy token/path is output.\n"
        "- final_state: an object with ACTIVE, ALW, and NO arrays for carried state.\n\n"
        f"{segments}\n\n"
        f"[final_instruction]\n{task['final_instruction']}\n"
    )


