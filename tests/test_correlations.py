"""Correlation tests: signature clustering and Jaccard overlap."""

from __future__ import annotations

from flaky_hunter.correlations import (
    analyse_correlations,
    cluster_by_signature,
    correlated_pairs,
    jaccard,
    normalize_message,
    suspicion_groups,
)
from flaky_hunter.model import Run, make_case
from flaky_hunter.stats import analyse_timelines


def _run(run_id: str, seq: int, entries: list[tuple[str, str, str]]) -> Run:
    run = Run(run_id=run_id, ts=f"2026-01-{seq + 1:02d}T00:00:00Z")
    for name, outcome, message in entries:
        case = make_case(
            run_id=run_id,
            ts=run.ts,
            classname="",
            file="tests/test_x.py",
            name=name,
            outcome=outcome,
            message=message,
            duration=1.0,
        )
        case.seq = seq
        run.cases.append(case)
    return run


def _stats(runs: list[Run]):
    return analyse_timelines(
        __import__("flaky_hunter.stats", fromlist=["build_timelines"]).build_timelines(runs)
    )


def test_normalize_message_strips_numbers_paths_and_ports():
    a = normalize_message("socket.timeout: connect to 10.4.2.17:5432 after 30.1s")
    b = normalize_message("socket.timeout: connect to 10.9.9.9:5432 after 12.7s")
    assert a == b


def test_normalize_message_keeps_the_wording_that_matters():
    assert "timeout" in normalize_message("TimeoutError: request timed out")
    assert "keyerror" in normalize_message("KeyError: 'session:4711'")


def test_normalize_message_is_lowercase_and_bounded():
    assert normalize_message("A" * 500) == "a" * 160


def test_jaccard_basics():
    assert jaccard(set(), {"a"}) == 0.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest_approx(1 / 3)


def pytest_approx(value: float):
    import pytest

    return pytest.approx(value)


def test_same_message_clusters_tests_together():
    runs = []
    for index in range(6):
        outcome = "fail" if index % 2 else "pass"
        runs.append(
            _run(
                f"run-{index}",
                index,
                [
                    ("alpha", outcome, "TimeoutError: request to <host> timed out after 30s"),
                    ("beta", outcome, "TimeoutError: request to <host> timed out after 30s"),
                    ("gamma", "pass", ""),
                ],
            )
        )
    clusters = cluster_by_signature(_stats(runs))
    assert len(clusters) == 1
    assert clusters[0].size == 2
    assert clusters[0].failures == 6


def test_distinct_messages_do_not_cluster():
    runs = [
        _run(
            "run-0",
            0,
            [("a", "fail", "ValueError: bad column"), ("b", "fail", "KeyError: missing")],
        ),
        _run(
            "run-1",
            1,
            [("a", "fail", "ValueError: bad column"), ("b", "fail", "KeyError: missing")],
        ),
    ]
    assert cluster_by_signature(_stats(runs)) == []


def test_correlated_pairs_need_two_shared_failures():
    runs = [
        _run("run-0", 0, [("a", "fail", "boom"), ("b", "fail", "boom")]),
        _run("run-1", 1, [("a", "fail", "boom"), ("b", "fail", "boom")]),
        _run("run-2", 2, [("a", "pass", ""), ("b", "pass", "")]),
    ]
    pairs = correlated_pairs(_stats(runs))
    assert len(pairs) == 1
    assert pairs[0].jaccard == 1.0


def test_independent_flakes_are_not_correlated():
    runs = []
    for index in range(10):
        runs.append(
            _run(
                f"run-{index}",
                index,
                [
                    ("a", "fail" if index % 2 else "pass", "boom"),
                    ("b", "fail" if index % 3 == 0 else "pass", "boom"),
                ],
            )
        )
    pairs = correlated_pairs(_stats(runs), min_jaccard=0.5)
    assert pairs == []


def test_suspicion_groups_merge_transitively():
    from flaky_hunter.correlations import CorrelatedPair

    pairs = [
        CorrelatedPair("a", "b", 1.0, ["r1"], 2, 2),
        CorrelatedPair("b", "c", 0.8, ["r1"], 2, 2),
    ]
    groups = suspicion_groups(pairs)
    assert groups == [["a", "b", "c"]]


def test_analyse_correlations_returns_all_three_sections():
    runs = []
    for index in range(8):
        outcome = "fail" if index % 2 else "pass"
        runs.append(
            _run(
                f"run-{index}",
                index,
                [
                    ("a", outcome, "ConnectionError: refused 127.0.0.1:6379"),
                    ("b", outcome, "ConnectionError: refused 127.0.0.1:6379"),
                ],
            )
        )
    report = analyse_correlations(_stats(runs))
    assert report.clusters
    assert report.pairs
    assert report.groups
