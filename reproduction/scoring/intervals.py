from __future__ import annotations
import random
from dataclasses import dataclass
from collections import defaultdict

OUTCOMES = [
    ("Answer", "answer_success"),
    ("Governance", "state_governance_success"),
    ("Reliable composite", "reliable_composite_success"),
]


CONTRASTS = [
    (
        "Paired method RD",
        "method",
        "rolling_visible_carry_forward",
        "ssr_no_visible_carry",
        ("model_condition_id", "budget", "run_id"),
    ),
    (
        "Paired method RD",
        "method",
        "mature_ssr_loop",
        "rolling_visible_carry_forward",
        ("model_condition_id", "budget", "run_id"),
    ),
    (
        "Paired budget RD",
        "budget",
        "1200",
        "600",
        ("model_condition_id", "method", "run_id"),
    ),
]


@dataclass(frozen=True)
class HeadlineRow:
    population: str
    outcome: str
    successes: int
    total: int
    estimate: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class ContrastRow:
    contrast: str
    contrast_type: str
    outcome: str
    estimate: float
    ci_low: float
    ci_high: float
    paired_units_per_task: int


def bool01(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(bool(value))
    if isinstance(value, str):
        return int(value.strip().lower() in {"1", "true", "yes"})
    return 0


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("Cannot compute percentile of empty values")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def task_cluster_ci(
    task_values: dict[str, float], bootstrap_reps: int, seed: int
) -> tuple[float, float]:
    tasks = sorted(task_values)
    if len(tasks) != 40:
        raise ValueError(f"Expected 40 task clusters, got {len(tasks)}")
    rng = random.Random(seed)
    replicates = []
    for _ in range(bootstrap_reps):
        replicates.append(sum(task_values[rng.choice(tasks)] for _ in tasks) / len(tasks))
    return percentile(replicates, 0.025), percentile(replicates, 0.975)


def headline_task_values(rows: list[dict], outcome_key: str) -> dict[str, float]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        grouped[row["task_id"]].append(bool01(row.get(outcome_key)))
    return {task_id: sum(values) / len(values) for task_id, values in grouped.items()}


def compute_headline_rows(
    rows: list[dict],
    population: str,
    bootstrap_reps: int,
    seed: int,
) -> list[HeadlineRow]:
    results = []
    for outcome, key in OUTCOMES:
        task_values = headline_task_values(rows, key)
        estimate = sum(task_values.values()) / len(task_values)
        ci_low, ci_high = task_cluster_ci(task_values, bootstrap_reps, seed)
        successes = sum(bool01(row.get(key)) for row in rows)
        results.append(
            HeadlineRow(
                population=population,
                outcome=outcome,
                successes=successes,
                total=len(rows),
                estimate=estimate,
                ci_low=ci_low,
                ci_high=ci_high,
            )
        )
    return results


def contrast_task_values(
    rows: list[dict],
    contrast_dimension: str,
    left: str,
    right: str,
    block_fields: Iterable[str],
    outcome_key: str,
) -> tuple[dict[str, float], int]:
    by_pair: dict[tuple, dict[str, int]] = defaultdict(dict)
    for row in rows:
        side = str(row[contrast_dimension])
        if side not in {left, right}:
            continue
        pair_key = (row["task_id"],) + tuple(str(row[field]) for field in block_fields)
        by_pair[pair_key][side] = bool01(row.get(outcome_key))

    per_task: dict[str, list[int]] = defaultdict(list)
    for pair_key, sides in by_pair.items():
        if left not in sides or right not in sides:
            raise ValueError(
                f"Missing paired side for {contrast_dimension} contrast "
                f"{left} - {right}: {pair_key}"
            )
        per_task[pair_key[0]].append(sides[left] - sides[right])

    paired_counts = {len(values) for values in per_task.values()}
    if len(paired_counts) != 1:
        raise ValueError(
            f"Unequal paired units per task for {left} - {right}: {sorted(paired_counts)}"
        )
    paired_units_per_task = paired_counts.pop()
    task_values = {
        task_id: sum(values) / len(values) for task_id, values in per_task.items()
    }
    return task_values, paired_units_per_task


def compute_contrast_rows(
    rows: list[dict], bootstrap_reps: int, seed: int
) -> list[ContrastRow]:
    results = []
    for contrast_type, dimension, left, right, block_fields in CONTRASTS:
        contrast_label = f"{left} - {right}"
        for outcome, key in OUTCOMES:
            task_values, paired_units = contrast_task_values(
                rows,
                contrast_dimension=dimension,
                left=left,
                right=right,
                block_fields=block_fields,
                outcome_key=key,
            )
            estimate = sum(task_values.values()) / len(task_values)
            ci_low, ci_high = task_cluster_ci(task_values, bootstrap_reps, seed)
            results.append(
                ContrastRow(
                    contrast=contrast_label,
                    contrast_type=contrast_type,
                    outcome=outcome,
                    estimate=estimate,
                    ci_low=ci_low,
                    ci_high=ci_high,
                    paired_units_per_task=paired_units,
                )
            )
    return results


