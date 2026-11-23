"""Statistics tests: the maths has to be right, not merely plausible."""

from __future__ import annotations

import math

import pytest

from flaky_hunter.analysis import analyse_runs
from flaky_hunter.model import TestCase, make_case
from flaky_hunter.stats import (
    FLAKY_THRESHOLD,
    analyse_timelines,
    build_timelines,
    classify,
    compute_score,
    parse_test_selector,
    wilson_lower,
)


def _case(run_id: str, seq: int, name: str, outcome: str, duration: float = 1.0) -> TestCase:
    case = make_case(
        run_id=run_id,
        ts=f"2026-01-{seq + 1:02d}T09:00:00Z",
        classname="tests.test_x",
        name=name,
        outcome=outcome,
        duration=duration,
    )
    case.seq = seq
    return case


def test_wilson_lower_is_zero_with_no_trials():
    assert wilson_lower(0, 0) == 0.0


def test_wilson_lower_is_zero_for_no_failures():
    assert wilson_lower(0, 40) == 0.0


def test_wilson_lower_is_below_the_raw_rate():
    assert wilson_lower(18, 40) < 0.45


def test_wilson_lower_penalises_small_samples():
    small = wilson_lower(2, 2)
    large = wilson_lower(20, 20)
    assert small < large < 1.0
    assert small == pytest.approx(0.342, abs=0.01)


def test_wilson_lower_matches_the_textbook_formula():
    z = 1.96
    p, n = 0.3, 30
    expected = (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (
        1 + z * z / n
    )
    assert wilson_lower(9, 30, z) == pytest.approx(expected, rel=1e-9)


def test_alternating_history_is_maximally_flaky():
    timeline = {"t": [_case(f"run-{i}", i, "t", "fail" if i % 2 else "pass") for i in range(20)]}
    stats = analyse_timelines(timeline)
    item = stats[0]
    assert item.chain.flip_ratio == pytest.approx(1.0)
    assert item.score > FLAKY_THRESHOLD
    assert item.verdict == "flaky"


def test_always_failing_test_is_broken_not_flaky():
    timeline = {"t": [_case(f"run-{i}", i, "t", "fail") for i in range(20)]}
    item = analyse_timelines(timeline)[0]
    assert item.chain.flip_ratio == 0.0
    assert item.score == 0.0
    assert item.verdict == "broken"


def test_always_passing_test_is_stable():
    timeline = {"t": [_case(f"run-{i}", i, "t", "pass") for i in range(20)]}
    item = analyse_timelines(timeline)[0]
    assert item.verdict == "stable"
    assert item.score == 0.0


def test_regression_is_detected_from_the_tail():
    history = ["pass"] * 12 + ["fail"] * 8
    timeline = {"t": [_case(f"run-{i}", i, "t", outcome) for i, outcome in enumerate(history)]}
    item = analyse_timelines(timeline)[0]
    assert item.verdict == "regressed"


def test_fix_is_detected_from_the_head():
    history = ["fail"] * 6 + ["pass"] * 14
    timeline = {"t": [_case(f"run-{i}", i, "t", outcome) for i, outcome in enumerate(history)]}
    item = analyse_timelines(timeline)[0]
    assert item.verdict == "fixed"


def test_single_failure_gets_its_own_verdict():
    history = ["pass"] * 19 + ["fail"]
    timeline = {"t": [_case(f"run-{i}", i, "t", outcome) for i, outcome in enumerate(history)]}
    assert analyse_timelines(timeline)[0].verdict == "single-failure"


def test_skips_are_excluded_from_the_markov_chain():
    history = ["pass", "skip", "fail", "skip", "pass", "fail"]
    timeline = {"t": [_case(f"run-{i}", i, "t", outcome) for i, outcome in enumerate(history)]}
    item = analyse_timelines(timeline)[0]
    assert item.chain.pairs == 3
    assert item.skips == 2
    assert item.passes == 2


def test_score_shrinks_on_tiny_samples():
    full = compute_score(0.4, 0.8, runs=20)
    tiny = compute_score(0.4, 0.8, runs=1)
    half = compute_score(0.4, 0.8, runs=3)
    assert 0 < half < full
    assert tiny == pytest.approx(full / 5, rel=1e-6)


def test_score_is_zero_without_flips_or_without_failures():
    assert compute_score(0.0, 0.9, runs=10) == 0.0
    assert compute_score(0.5, 0.0, runs=10) == 0.0
    assert compute_score(0.5, 0.5, runs=0) == 0.0


def test_impact_ranks_by_duration_and_failures():
    slow = [
        _case(f"run-{i}", i, "slow", "fail" if i % 2 else "pass", duration=30.0) for i in range(20)
    ]
    fast = [
        _case(f"run-{i}", i, "fast", "fail" if i % 2 else "pass", duration=0.01) for i in range(20)
    ]
    stats = analyse_timelines({"tests/test_x.py::slow": slow, "tests/test_x.py::fast": fast})
    assert stats[0].test_id == "tests/test_x.py::slow"
    assert stats[0].impact > stats[1].impact


def test_retries_within_one_run_keep_the_worst_outcome():
    cases = [
        _case("run-1", 0, "t", "pass"),
        _case("run-1", 0, "t", "fail"),
    ]
    timelines = build_timelines([type("R", (), {"cases": cases, "run_id": "run-1"})()])
    assert len(timelines["tests/test_x.py::t"]) == 1
    assert timelines["tests/test_x.py::t"][0].outcome == "fail"


def test_timelines_are_ordered_by_run_not_by_file_order():
    from flaky_hunter.model import Run

    early = Run(run_id="b-run", ts="2026-01-01T00:00:00Z")
    late = Run(run_id="a-run", ts="2026-02-01T00:00:00Z")
    early.cases.append(_case("b-run", 0, "t", "fail"))
    late.cases.append(_case("a-run", 0, "t", "pass"))
    from flaky_hunter.model import sort_runs

    runs = sort_runs([late, early])
    timeline = build_timelines(runs)
    assert [c.outcome for c in timeline["tests/test_x.py::t"]] == ["fail", "pass"]


def test_classify_handles_no_data():
    from flaky_hunter.stats import TestStats

    assert classify(TestStats(test_id="x")) == "no-data"


def test_selector_matches_exact_and_fragment():
    known = ["tests/test_api.py::test_timeout", "tests/test_api.py::test_ok"]
    assert parse_test_selector("tests/test_api.py::test_ok", known) == [
        "tests/test_api.py::test_ok"
    ]
    assert parse_test_selector("timeout", known) == ["tests/test_api.py::test_timeout"]
    assert parse_test_selector("nope", known) == []


def test_analyse_runs_reports_verdict_counts():
    from flaky_hunter.model import Run

    runs = []
    for index in range(6):
        run = Run(run_id=f"run-{index}", ts=f"2026-01-0{index + 1}T00:00:00Z")
        run.cases.append(_case(f"run-{index}", index, "flaky", "fail" if index % 2 else "pass"))
        run.cases.append(_case(f"run-{index}", index, "stable", "pass"))
        runs.append(run)
    analysis = analyse_runs(runs)
    assert analysis.verdict_counts()["stable"] >= 1
    assert len(analysis.flaky) == 1
    assert analysis.failures == 3
