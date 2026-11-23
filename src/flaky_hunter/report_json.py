"""JSON report renderer: the machine-readable contract of flaky-hunter."""

from __future__ import annotations

import json

from .analysis import Analysis


def analysis_payload(analysis: Analysis, *, include_history: bool = True) -> dict:
    """Serialise an analysis to a JSON-ready dict (stable ordering everywhere)."""
    tests = []
    for item in analysis.stats:
        entry = {
            "test_id": item.test_id,
            "verdict": item.verdict,
            "score": round(item.score, 6),
            "impact": round(item.impact, 6),
            "runs": item.runs,
            "passes": item.passes,
            "failures": item.failures,
            "skips": item.skips,
            "failure_rate": round(item.failure_rate, 6),
            "failure_lower_bound": round(item.failure_lower, 6),
            "pass_to_fail": round(item.chain.pass_to_fail, 6),
            "fail_to_pass": round(item.chain.fail_to_pass, 6),
            "flip_ratio": round(item.chain.flip_ratio, 6),
            "avg_duration": round(item.avg_duration, 6),
            "total_duration": round(item.total_duration, 6),
            "low_confidence": item.low_confidence,
            "last_outcome": item.last_outcome,
        }
        if include_history:
            entry["history"] = list(item.history)
            entry["run_ids"] = list(item.run_ids)
            entry["failed_run_indices"] = list(item.failed_runs)
        tests.append(entry)
    payload = {
        "tool": "flaky-hunter",
        "version": 1,
        "runs": len(analysis.runs),
        "files": analysis.files,
        "results": analysis.cases,
        "threshold": analysis.threshold,
        "window": {"first": analysis.first_ts, "last": analysis.last_ts},
        "verdicts": analysis.verdict_counts(),
        "flaky_count": len(analysis.flaky),
        "tests": tests,
        "signatures": [
            {
                "signature": cluster.signature,
                "tests": list(cluster.tests),
                "failures": cluster.failures,
                "example": cluster.example,
            }
            for cluster in analysis.correlations.clusters
        ],
        "correlated": [
            {
                "left": pair.left,
                "right": pair.right,
                "jaccard": pair.jaccard,
                "shared_runs": list(pair.shared_runs),
            }
            for pair in analysis.correlations.pairs
        ],
        "suspicion_groups": [list(group) for group in analysis.correlations.groups],
        "quarantine": [item.test_id for item in analysis.flaky],
        "warnings": list(analysis.warnings),
    }
    if analysis.baseline_diff is not None:
        payload["baseline"] = dict(analysis.baseline_diff)
    return payload


def render_json(analysis: Analysis, *, indent: int = 2) -> str:
    """Serialise with sorted keys so output is byte-identical for identical input."""
    payload = analysis_payload(analysis)
    return json.dumps(payload, indent=indent, sort_keys=True) + "\n"
