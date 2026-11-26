from __future__ import annotations
import re, random, hashlib, json
from collections import defaultdict
from typing import Any

TOKEN_RE = re.compile(r"\b(?:REQ|CFG|API|MOD|PATH|FEATURE|FLAG|RULE|PATCH|HOOK|JOB|CHECK)_[0-9]{2}_[A-Z0-9]{6}\b")


PATH_RE = re.compile(r"\bsrc/[A-Za-z0-9_./-]+(?:\.py|\.yaml|\.json|\.md)\b")


INITIAL_ACTIVE_RE = re.compile(r"Initial active tokens:\s*([^\.]+)\.", re.I)


INITIAL_ALLOWED_RE = re.compile(r"Allowed path candidates currently include\s+([^\.]+?\.(?:py|yaml|json|md))", re.I)


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def visible_text(task: dict[str, Any]) -> str:
    return "\n".join(str(segment.get("text", "")) for segment in task.get("segments", []))


def visible_tokens(task: dict[str, Any]) -> list[str]:
    return unique(TOKEN_RE.findall(visible_text(task)))


def visible_paths(task: dict[str, Any]) -> list[str]:
    return unique(PATH_RE.findall(visible_text(task)))


def parse_initial_active(task: dict[str, Any]) -> list[str]:
    match = INITIAL_ACTIVE_RE.search(visible_text(task))
    if not match:
        return []
    return unique(TOKEN_RE.findall(match.group(1)))


def parse_initial_allowed_paths(task: dict[str, Any]) -> list[str]:
    return unique(match.group(1) for match in INITIAL_ALLOWED_RE.finditer(visible_text(task)))


def visible_status_map(task: dict[str, Any]) -> dict[str, str]:
    text = visible_text(task)
    status = {token: "candidate" for token in visible_tokens(task)}
    for token in parse_initial_active(task):
        status[token] = "active"
    for token in list(status):
        contexts = " ".join(sentence for sentence in re.split(r"(?<=[.])\s+", text) if token in sentence)
        low = contexts.lower()
        if "revoked" in low:
            status[token] = "revoked"
        elif "stale" in low or "superseded" in low or "deprecated" in low:
            status[token] = "stale"
        elif "forbidden" in low:
            status[token] = "forbidden"
        elif "protected" in low or "private" in low:
            status[token] = "protected"
        elif "archive log re-mentions" in low or "historical fix" in low:
            status[token] = "revoked"
        elif "error trace re-mentions" in low:
            status[token] = "forbidden"
        elif "rollback-only" in low or "rollback only" in low:
            status[token] = "rollback_only"
        elif "archive-only" in low or "archive only" in low:
            status[token] = "archive_only"
        elif "decoy" in low:
            status[token] = "decoy"
        elif "blocked" in low:
            status[token] = "blocked"
        if re.search(rf"{re.escape(token)}\s+(?:is|becomes|became)\s+(?:now\s+)?active\b", contexts, flags=re.I):
            status[token] = "active"
    return status


def state_labels_from_status(status: dict[str, str]) -> dict[str, str]:
    mapping = {
        "active": "active",
        "candidate": "decoy",
        "revoked": "revoked",
        "stale": "stale",
        "forbidden": "forbidden",
        "protected": "protected",
        "rollback_only": "rollback_only",
        "archive_only": "archive_only",
        "decoy": "decoy",
        "blocked": "blocked",
    }
    return {token: mapping.get(label, "decoy") for token, label in status.items()}


def answer_payload(required_tokens: list[str], allowed_paths: list[str], state_labels: dict[str, str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "final_answer": {
            "required_tokens": required_tokens,
            "allowed_paths": allowed_paths,
            "boundary_checks": {
                "baseline_policy_generated": True,
            },
        }
    }
    if state_labels:
        payload["final_answer"]["state_labels"] = state_labels
    return payload


def state_surface(required_tokens: list[str], allowed_paths: list[str], excluded_tokens: list[str] | None = None) -> str:
    surface: dict[str, Any] = {
        "ACTIVE": required_tokens,
        "ALW": allowed_paths,
    }
    if excluded_tokens is not None:
        surface["NO"] = excluded_tokens
    return json.dumps(surface, ensure_ascii=False, sort_keys=True)


def random_policy(task: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    tokens = visible_tokens(task)
    paths = visible_paths(task)
    k = len(parse_initial_active(task)) or min(2, len(tokens))
    seed = int(hashlib.sha256(f"random_visible_v1|{row['row_id']}|20260706".encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    sampled_tokens = sorted(rng.sample(tokens, k=min(k, len(tokens)))) if tokens else []
    sampled_paths = sorted(rng.sample(paths, k=1)) if paths else []
    return {
        "final_output": answer_payload(sampled_tokens, sampled_paths),
        "final_state": state_surface(sampled_tokens, sampled_paths),
        "policy_trace": {
            "seed": seed,
            "visible_token_count": len(tokens),
            "visible_path_count": len(paths),
            "sampled_token_count": len(sampled_tokens),
        },
    }


def copy_initial_policy(task: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    tokens = parse_initial_active(task)
    paths = parse_initial_allowed_paths(task)
    return {
        "final_output": answer_payload(tokens, paths),
        "final_state": state_surface(tokens, paths),
        "policy_trace": {
            "initial_active_count": len(tokens),
            "initial_allowed_path_count": len(paths),
        },
    }


def carry_all_visible_policy(task: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    tokens = visible_tokens(task)
    paths = visible_paths(task)
    return {
        "final_output": answer_payload(tokens, paths),
        "final_state": json.dumps({"CARRY_ALL": tokens + paths}, ensure_ascii=False, sort_keys=True),
        "policy_trace": {
            "visible_token_count": len(tokens),
            "visible_path_count": len(paths),
        },
    }


def rule_visible_transition_policy(task: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    status = visible_status_map(task)
    active = [token for token, label in status.items() if label == "active"]
    excluded = [token for token, label in status.items() if label != "active"]
    paths = parse_initial_allowed_paths(task)
    return {
        "final_output": answer_payload(active, paths),
        "final_state": state_surface(active, paths, excluded),
        "policy_trace": {
            "state_labels_suppressed_for_answer_surface": True,
            "visible_status_labels": state_labels_from_status(status),
            "visible_status_counts": dict(sorted(counts(status.values()).items())),
            "active_count": len(active),
            "excluded_count": len(excluded),
            "initial_allowed_path_count": len(paths),
        },
    }


def oracle_ceiling_policy(task: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    oracle = task["oracle"]
    required = list(oracle["required_exact_tokens"])
    allowed_paths = list(oracle["allowed_paths"])
    excluded = list(oracle["final_excluded_set"])
    return {
        "final_output": answer_payload(required, allowed_paths, dict(oracle["expected_state_labels"])),
        "final_state": state_surface(required, allowed_paths, excluded),
        "policy_trace": {
            "oracle_required_count": len(required),
            "oracle_excluded_count": len(excluded),
            "oracle_allowed_path_count": len(allowed_paths),
        },
    }


def counts(values: Any) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for value in values:
        result[str(value)] += 1
    return dict(result)


