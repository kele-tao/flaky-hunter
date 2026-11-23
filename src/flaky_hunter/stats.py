"""Flakiness statistics: timelines, Markov transitions, confidence bounds, impact."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .model import FAILED_OUTCOMES, TestCase

Z95 = 1.959963984540054
FLAKY_THRESHOLD = 0.20
MIN_RUNS_FOR_CONFIDENCE = 10
_RANK = {"pass": 0, "skip": 1, "fail": 2, "error": 3}


def wilson_lower(successes: int, trials: int, z: float = Z95) -> float:
    """One-sided Wilson lower bound on a binomial proportion.

    We report the lower bound rather than the raw rate so that a test with two
    failures in two runs (raw rate 1.0) does not outrank a test with eighteen
    failures in forty runs (raw rate 0.45): the bound knows the sample was small.
    """
    if trials <= 0:
        return 0.0
    p = successes / trials
    denom = 1.0 + z * z / trials
    centre = p + z * z / (2.0 * trials)
    margin = z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))
    return max(0.0, (centre - margin) / denom)


@dataclass(slots=True)
class MarkovChain:
    """Two-state chain over (pass, fail). Skips are neither success nor failure."""

    pass_to_fail: float = 0.0
    fail_to_pass: float = 0.0
    pairs: int = 0
    flips: int = 0
    pass_runs: int = 0
    fail_runs: int = 0

    @property
    def flip_ratio(self) -> float:
        return self.flips / self.pairs if self.pairs else 0.0


@dataclass(slots=True)
class TestStats:
    """Everything flaky-hunter knows about one test."""

    test_id: str
    history: list[str] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    runs: int = 0
    passes: int = 0
    failures: int = 0
    skips: int = 0
    retries: int = 0
    failed_runs: list[int] = field(default_factory=list)
    chain: MarkovChain = field(default_factory=MarkovChain)
    failure_rate: float = 0.0
    failure_lower: float = 0.0
    score: float = 0.0
    impact: float = 0.0
    avg_duration: float = 0.0
    total_duration: float = 0.0
    last_outcome: str = "pass"
    first_outcome: str = "pass"
    verdict: str = "stable"
    low_confidence: bool = False

    @property
    def failure_positions(self) -> list[int]:
        return [i for i, outcome in enumerate(self.history) if outcome in FAILED_OUTCOMES]


def _dedupe_within_run(cases: Iterable[TestCase]) -> tuple[list[TestCase], int]:
    """Collapse retries inside a run: keep the worst outcome, count the retries."""
    by_id: dict[str, TestCase] = {}
    retries = 0
    order: list[str] = []
    for case in cases:
        key = case.test_id
        if key not in by_id:
            by_id[key] = case
            order.append(key)
            continue
        retries += 1
        current = by_id[key]
        if _RANK[case.outcome] > _RANK[current.outcome]:
            by_id[key] = TestCase(
                run_id=case.run_id,
                ts=case.ts,
                file=case.file,
                name=case.name,
                outcome=case.outcome,
                duration=max(case.duration, current.duration),
                message=case.message or current.message,
                classname=case.classname,
                seq=case.seq,
            )
        else:
            current.duration = max(current.duration, case.duration)
    return [by_id[key] for key in order], retries


def build_timelines(runs: Sequence) -> dict[str, list[TestCase]]:
    """Flatten runs into per-test observation timelines, ordered by run index."""
    timelines: dict[str, list[TestCase]] = {}
    for run in runs:
        cases, _ = _dedupe_within_run(run.cases)
        for case in cases:
            timelines.setdefault(case.test_id, []).append(case)
    for cases in timelines.values():
        cases.sort(key=lambda c: c.seq)
    return timelines


def _markov(history: Sequence[str]) -> MarkovChain:
    """Fit a two-state Markov chain: P(pass->fail) and P(fail->pass)."""
    states = [o for o in history if o in ("pass", "fail", "error")]
    chain = MarkovChain()
    chain.pass_runs = sum(1 for o in states if o == "pass")
    chain.fail_runs = len(states) - chain.pass_runs
    pairs = list(zip(states, states[1:], strict=False))
    chain.pairs = len(pairs)
    chain.flips = sum(1 for a, b in pairs if (a == "pass") != (b == "pass"))
    from_pass = [(a, b) for a, b in pairs if a == "pass"]
    from_fail = [(a, b) for a, b in pairs if a != "pass"]
    chain.pass_to_fail = (
        sum(1 for _, b in from_pass if b != "pass") / len(from_pass) if from_pass else 0.0
    )
    chain.fail_to_pass = (
        sum(1 for _, b in from_fail if b == "pass") / len(from_fail) if from_fail else 0.0
    )
    return chain


def compute_score(fail_lower: float, flip_ratio: float, runs: int, min_runs: int = 5) -> float:
    """Combine the failure confidence bound and the flip rate, shrinking small samples.

    score = sqrt(failure_lower * flip_ratio) * shrink, where shrink ramps from 0
    to 1 over the first min_runs observations.

    The geometric mean is intentional. A test that always fails has no flips and
    scores zero: it is broken, not flaky. A test that fails once in forty runs
    has neither a confident failure rate nor flips and scores near zero. The
    shrink factor means a test seen twice cannot dominate the leaderboard.
    """
    if runs <= 0:
        return 0.0
    raw = math.sqrt(max(fail_lower, 0.0) * max(flip_ratio, 0.0))
    shrink = min(1.0, runs / float(min_runs))
    return round(raw * shrink, 6)


def classify(item: TestStats) -> str:
    """Assign the human-facing verdict shown in reports."""
    if item.runs == 0:
        return "no-data"
    if item.passes == 0 and item.failures == 0:
        return "skipped"
    if item.failures == 0:
        return "stable"
    if item.passes == 0:
        return "broken"
    tail = item.history[-3:]
    head = item.history[:3]
    # A clean phase change beats a flakiness score: a test that passed three
    # times and now fails three times in a row is a regression, and a test that
    # did the opposite was fixed, whatever the historical score says.
    if all(o != "pass" for o in tail) and all(o == "pass" for o in head):
        return "regressed"
    if all(o in ("pass", "skip") for o in tail) and all(o != "pass" for o in head):
        return "fixed"
    if item.score >= FLAKY_THRESHOLD:
        return "flaky"
    if item.failures == 1:
        return "single-failure"
    return "unstable"


def analyse_timelines(
    timelines: dict[str, list[TestCase]], *, min_runs: int = 5
) -> list[TestStats]:
    """Compute per-test statistics for every test, ranked by impact."""
    results: list[TestStats] = []
    for test_id, cases in timelines.items():
        item = TestStats(test_id=test_id)
        item.runs = len(cases)
        item.history = [c.outcome for c in cases]
        item.durations = [c.duration for c in cases]
        item.messages = [c.message for c in cases]
        item.run_ids = [c.run_id for c in cases]
        item.passes = sum(1 for o in item.history if o == "pass")
        item.failures = sum(1 for o in item.history if o in FAILED_OUTCOMES)
        item.skips = sum(1 for o in item.history if o == "skip")
        item.failed_runs = item.failure_positions
        item.chain = _markov(item.history)
        decided = item.passes + item.failures
        item.failure_rate = item.failures / decided if decided else 0.0
        item.failure_lower = wilson_lower(item.failures, decided)
        item.score = compute_score(item.failure_lower, item.chain.flip_ratio, item.runs, min_runs)
        item.low_confidence = item.runs < MIN_RUNS_FOR_CONFIDENCE
        item.total_duration = round(sum(item.durations), 6)
        item.avg_duration = item.total_duration / item.runs if item.runs else 0.0
        # Raw logs carry no per-test durations. Rather than rank everything at
        # zero, fall back to a one-second-per-test floor so impact still favours
        # tests that fail often; reports show "n/a" for the missing duration.
        effective_duration = item.avg_duration if item.avg_duration > 0 else 1.0
        item.impact = round(item.score * effective_duration * item.failures, 6)
        item.first_outcome = item.history[0] if item.history else "pass"
        item.last_outcome = item.history[-1] if item.history else "pass"
        item.verdict = classify(item)
        results.append(item)
    results.sort(key=lambda s: (-s.impact, -s.score, s.test_id))
    return results


NON_FLAKY_VERDICTS = ("regressed", "fixed", "broken", "skipped", "no-data")


def flaky_tests(stats: Sequence[TestStats], threshold: float = FLAKY_THRESHOLD) -> list[TestStats]:
    """Tests worth quarantining: score clears the threshold, both outcomes seen.

    Regressed and fixed tests are excluded even when their historical score is
    high. They have a direction, so the right response is "fix the regression" or
    "delete the workaround", never "hide it behind a quarantine marker".
    """
    return [
        s
        for s in stats
        if s.score >= threshold and s.passes and s.failures and s.verdict not in NON_FLAKY_VERDICTS
    ]


def parse_test_selector(selector: str, known: Sequence[str]) -> list[str]:
    """Resolve a user supplied selector to concrete test ids.

    Accepts an exact id, a pytest-style path::name fragment, or a substring.
    """
    selector = selector.strip()
    if not selector:
        return []
    if selector in known:
        return [selector]
    candidates = [t for t in known if selector in t]
    if candidates:
        return candidates
    normalised = selector.replace("\\", "/")
    return [t for t in known if normalised in t.replace("\\", "/")]
