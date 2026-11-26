from __future__ import annotations
import json, re
from typing import Any

def request_payload(endpoint_row: dict[str, Any], prompt: str) -> dict[str, Any]:
    controls = endpoint_row["request_controls"]
    payload: dict[str, Any] = {
        "model": endpoint_row["requested_model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    if "max_tokens" in controls:
        payload["max_tokens"] = controls["max_tokens"]
    temp = controls.get("temperature", {})
    if temp.get("send_mode") == "explicit":
        payload["temperature"] = temp.get("value")
    reasoning = controls.get("reasoning_or_thinking", {})
    if reasoning.get("send_mode") == "explicit" and isinstance(reasoning.get("value"), dict):
        payload.update(reasoning["value"])
    return payload


def parse_response_content(body: str) -> tuple[str, str, str | None]:
    try:
        parsed = json.loads(body)
        content = parsed["choices"][0]["message"].get("content", "")
    except Exception as exc:
        return body, "", f"{type(exc).__name__}: {exc}"
    final_state = ""
    obj = parse_json_maybe(content)
    if isinstance(obj, dict):
        state = obj.get("final_state", obj.get("carried_state", obj.get("state", "")))
        if state:
            final_state = json.dumps(state, ensure_ascii=False, sort_keys=True) if not isinstance(state, str) else state
    return content, final_state, None


def parse_json_maybe(text: str) -> Any:
    value = str(text or "").strip()
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        pass
    match = re.search(r"\{.*\}", value, flags=re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


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
