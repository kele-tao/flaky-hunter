"""Failure-signature clustering and correlated-flakiness detection.

Two independent signals explain most CI noise:

* Many tests share one root cause ("connection reset by peer", "timeout after
  30s"). Grouping by normalised error message turns 14 red tests into 1 bug.
* Some tests fail in exactly the same runs. That is a shared fixture, a shared
  database, or a shared port -- not 6 independent flakes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .stats import TestStats

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_HEX = re.compile(r"\b0x[0-9a-f]+\b", re.I)
_NUM = re.compile(r"\b\d+(?:\.\d+)?\b")
_WS = re.compile(r"\s+")
_TIMING = re.compile(r"(?:after|in|took)\s+[\d.]+\s*(?:ms|s|seconds?|milliseconds)?", re.I)
_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/](?:[\w.\-]+[\\/])+[\w.\-]+")
_HOSTPORT = re.compile(r"\b[a-z0-9][a-z0-9.\-]*:\d{2,5}\b", re.I)
_COUNT = re.compile(r"\b\d+\s+(?:tests?|items?|rows?|retries)\b", re.I)


def normalize_message(message: str) -> str:
    """Reduce an error message to a stable signature.

    Numbers, hashes, ports, tmp paths and timings differ on every run; the words
    that describe the failure do not. Two messages with the same signature are
    almost certainly the same bug.
    """
    text = _WS.sub(" ", (message or "").strip())
    if not text:
        return ""
    text = _UUID.sub("<uuid>", text)
    text = _HOSTPORT.sub("<host>", text)
    text = _PATH.sub("<path>", text)
    text = _HEX.sub("<hex>", text)
    text = _COUNT.sub("<count>", text)
    text = _TIMING.sub("<timing>", text)
    text = _NUM.sub("<n>", text)
    text = text.strip(" :;-")
    return text[:160].lower()


@dataclass(slots=True)
class SignatureCluster:
    """All tests that fail with the same normalised message."""

    signature: str
    label: str
    tests: list[str] = field(default_factory=list)
    failures: int = 0
    example: str = ""

    @property
    def size(self) -> int:
        return len(self.tests)


@dataclass(slots=True)
class CorrelatedPair:
    """Two tests that fail in overlapping runs."""

    left: str
    right: str
    jaccard: float
    shared_runs: list[str]
    left_failures: int
    right_failures: int


@dataclass(slots=True)
class CorrelationReport:
    """Clusters, pairs and the merged suspicion groups."""

    clusters: list[SignatureCluster] = field(default_factory=list)
    pairs: list[CorrelatedPair] = field(default_factory=list)
    groups: list[list[str]] = field(default_factory=list)


def _failure_message(item: TestStats) -> str:
    """Most recent failure message, falling back to the last message seen."""
    paired = zip(item.history, item.messages, strict=False)
    for outcome, message in reversed(list(paired)):
        if outcome in ("fail", "error") and message:
            return message
    return item.messages[-1] if item.messages else ""


def cluster_by_signature(stats: Sequence[TestStats], min_size: int = 2) -> list[SignatureCluster]:
    """Group failing tests by normalised error message, biggest cluster first."""
    groups: dict[str, SignatureCluster] = {}
    for item in stats:
        if not item.failures:
            continue
        raw = _failure_message(item)
        signature = normalize_message(raw) or "<no message>"
        cluster = groups.get(signature)
        if cluster is None:
            cluster = SignatureCluster(signature=signature, label=signature or "<no message>")
            groups[signature] = cluster
        cluster.tests.append(item.test_id)
        cluster.failures += item.failures
        if not cluster.example and raw:
            cluster.example = raw[:200]
    clusters = [c for c in groups.values() if c.size >= min_size]
    clusters.sort(key=lambda c: (-c.size, -c.failures, c.signature))
    return clusters


def jaccard(left: set[str], right: set[str]) -> float:
    """Intersection over union of two run-id sets."""
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def correlated_pairs(
    stats: Sequence[TestStats],
    *,
    min_failures: int = 2,
    min_jaccard: float = 0.5,
    limit: int = 12,
) -> list[CorrelatedPair]:
    """Pairs of tests whose failures overlap more than chance would explain.

    We only compare tests that failed at least twice, and we ignore pairs where
    one test failed once: a single coincidence is not evidence of a shared cause.
    """
    candidates = [s for s in stats if s.failures >= min_failures]
    pairs: list[CorrelatedPair] = []
    for i, left in enumerate(candidates):
        left_runs = {left.run_ids[pos] for pos in left.failure_positions}
        for right in candidates[i + 1 :]:
            right_runs = {right.run_ids[pos] for pos in right.failure_positions}
            shared = left_runs & right_runs
            if len(shared) < min_failures:
                continue
            score = jaccard(left_runs, right_runs)
            if score < min_jaccard:
                continue
            pairs.append(
                CorrelatedPair(
                    left=left.test_id,
                    right=right.test_id,
                    jaccard=round(score, 3),
                    shared_runs=sorted(shared),
                    left_failures=left.failures,
                    right_failures=right.failures,
                )
            )
    pairs.sort(key=lambda p: (-p.jaccard, -len(p.shared_runs), p.left, p.right))
    return pairs[:limit]


def suspicion_groups(pairs: Sequence[CorrelatedPair]) -> list[list[str]]:
    """Union-find over correlated pairs: each group probably shares a fixture."""
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for pair in pairs:
        a, b = find(pair.left), find(pair.right)
        if a != b:
            parent[b] = a
    groups: dict[str, list[str]] = {}
    for node in parent:
        groups.setdefault(find(node), []).append(node)
    result = [sorted(members) for members in groups.values() if len(members) > 1]
    result.sort(key=lambda members: (-len(members), members[0]))
    return result


def analyse_correlations(
    stats: Sequence[TestStats],
    *,
    min_cluster: int = 2,
    min_jaccard: float = 0.5,
) -> CorrelationReport:
    """Run signature clustering and pair detection in one pass."""
    pairs = correlated_pairs(stats, min_jaccard=min_jaccard)
    return CorrelationReport(
        clusters=cluster_by_signature(stats, min_size=min_cluster),
        pairs=pairs,
        groups=suspicion_groups(pairs),
    )
