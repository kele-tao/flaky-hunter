"""Baseline comparison: alert on newly flaky, regressed and fixed tests."""

from __future__ import annotations

import json
import pathlib

from .errors import FlakyHunterError
from .stats import TestStats

BASELINE_VERSION = 1


def snapshot(stats: list[TestStats]) -> dict:
    """Build the JSON payload we save as a baseline."""
    return {
        "version": BASELINE_VERSION,
        "tests": {
            item.test_id: {
                "score": round(item.score, 6),
                "verdict": item.verdict,
                "runs": item.runs,
                "failure_rate": round(item.failure_rate, 6),
                "last_outcome": item.last_outcome,
            }
            for item in sorted(stats, key=lambda s: s.test_id)
        },
    }


def save(path: pathlib.Path, stats: list[TestStats]) -> dict:
    payload = snapshot(stats)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def load(path: pathlib.Path) -> dict:
    if not path.exists():
        raise FlakyHunterError(f"baseline file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FlakyHunterError(f"baseline {path.name} is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("tests"), dict):
        raise FlakyHunterError(
            f"baseline {path.name} has no tests object; regenerate it with --save-baseline"
        )
    return payload


def compare(stats: list[TestStats], baseline: dict, *, delta: float = 0.10) -> dict:
    """Diff current scores against a baseline.

    newly_flaky  - not in the baseline and now flaky (score >= 0.30)
    worsened     - already in the baseline but the score rose by more than delta
    fixed        - flaky in the baseline, clean in the last three runs now
    new_tests    - present now, absent before (informational)
    removed      - present before, absent now (informational)
    """
    known = baseline.get("tests", {})
    before = {test_id: entry.get("score", 0.0) for test_id, entry in known.items()}
    before_verdict = {test_id: entry.get("verdict", "") for test_id, entry in known.items()}
    current = {item.test_id: item for item in stats}

    newly_flaky = [
        item.test_id for item in stats if item.verdict == "flaky" and item.test_id not in known
    ]
    worsened = [
        item.test_id
        for item in stats
        if item.test_id in known and item.score - before[item.test_id] > delta
    ]
    fixed = [
        item.test_id
        for item in stats
        if before_verdict.get(item.test_id) in ("flaky", "broken", "regressed")
        and item.verdict in ("stable", "fixed")
    ]
    new_tests = [item.test_id for item in stats if item.test_id not in known]
    removed = sorted(test_id for test_id in known if test_id not in current)
    return {
        "newly_flaky": sorted(newly_flaky),
        "worsened": sorted(worsened),
        "fixed": sorted(fixed),
        "new_tests": sorted(new_tests),
        "removed": removed,
        "baseline_tests": len(known),
    }
