from __future__ import annotations
import json, re, hashlib, copy
from typing import Any

RETRYABLE_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}


DEFAULT_RETRY_POLICY = {
    "schema_version": "pcg_dynamic_state_v2.transport_retry_policy.v1",
    "policy_id": "frozen_two_attempt_policy_20260625",
    "max_transport_attempts": 2,
    "retryable_http_statuses": sorted(RETRYABLE_HTTP),
    "backoff_seconds": [2.0],
    "respect_retry_after": False,
    "max_sleep_seconds": 2.0,
}


NEUTRAL_TOKEN_RE = re.compile(r"\b(?:REQ|CFG|API|MOD|PATH|FEATURE|FLAG|RULE|PATCH|HOOK|JOB|CHECK)_[0-9]{2}_[A-Z0-9]{6}\b")


PATH_RE = re.compile(r"\bsrc/[A-Za-z0-9_./-]+(?:\.py|\.yaml|\.json|\.md)\b")


STATE_FIELD_RE = re.compile(
    r"(OUT|ALW|ALLOW|ACTIVE_SET|ACTIVE|REQUIRED_TOKENS|REQUIRED|VISIBLE_KEEP|KEEP|OUTPUT_SET|OUTPUT|FINAL_ACTIVE_SET|FINAL_ACTIVE|FINAL|CARRY_ALL|NO_CAT|NO|DENIED|DENY|EXCLUDED|EXCLUDE|FORBIDDEN|PROTECTED|REVOKED|STALE|BLOCKED|BOUNDARY_CHECKS|BOUNDARY|BOUND|B|NOTES|NOTE|CHECKS|CHECK|CK|STATE_LABELS|STATE_TRANSITIONS|LOOP|G|N)\s*=",
    flags=re.I,
)


def retry_policy_for(endpoint: dict[str, Any]) -> dict[str, Any]:
    policy = copy.deepcopy(DEFAULT_RETRY_POLICY)
    override = endpoint.get("request_controls", {}).get("retry_policy")
    if isinstance(override, dict):
        policy.update(copy.deepcopy(override))
    policy["max_transport_attempts"] = max(1, int(policy.get("max_transport_attempts", 1)))
    policy["retryable_http_statuses"] = [int(item) for item in policy.get("retryable_http_statuses", [])]
    policy["backoff_seconds"] = [float(item) for item in policy.get("backoff_seconds", [])] or [0.0]
    policy["max_sleep_seconds"] = float(policy.get("max_sleep_seconds", max(policy["backoff_seconds"])))
    policy["respect_retry_after"] = bool(policy.get("respect_retry_after"))
    return policy


def retry_sleep_seconds(policy: dict[str, Any], attempt_index: int, retry_after_seconds: float | None) -> float:
    backoff = policy["backoff_seconds"]
    planned = backoff[min(attempt_index - 1, len(backoff) - 1)]
    if policy.get("respect_retry_after") and retry_after_seconds is not None:
        planned = max(planned, retry_after_seconds)
    return min(float(planned), float(policy["max_sleep_seconds"]))


def extract_response_content(raw: dict[str, Any], requested_model: str) -> tuple[str, dict[str, Any], str, bool, Any, str | None, int | None]:
    attempts = raw.get("attempts", [])
    last = attempts[-1] if attempts else {}
    status = last.get("http_status")
    body = last.get("body", "")
    if not body:
        return "", {}, "", False, None, None, status
    try:
        obj = json.loads(body)
    except Exception:
        return body, {}, "", False, None, None, status
    choices = obj.get("choices") or []
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    content = message.get("content") or ""
    reasoning_present = bool(message.get("reasoning_content") or message.get("reasoning") or message.get("reasoning_details"))
    usage = obj.get("usage") or {}
    reasoning_tokens = usage.get("reasoning_tokens")
    details = usage.get("completion_tokens_details")
    if reasoning_tokens is None and isinstance(details, dict):
        reasoning_tokens = details.get("reasoning_tokens")
    returned_model = str(obj.get("model") or requested_model)
    return content, usage, returned_model, reasoning_present, reasoning_tokens, choice.get("finish_reason"), status


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
    payload = {
        "final_answer": {
            "required_tokens": dedupe_preserve(NEUTRAL_TOKEN_RE.findall(out_text)),
            "allowed_paths": dedupe_preserve(PATH_RE.findall(alw_text)),
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
