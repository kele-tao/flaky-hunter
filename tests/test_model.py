"""Model and normalisation tests."""

from __future__ import annotations

import pytest

from flaky_hunter.model import (
    Run,
    dedupe_runs,
    make_case,
    normalize_outcome,
    sort_runs,
    split_classname,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("passed", "pass"),
        ("PASS", "pass"),
        ("success", "pass"),
        ("failed", "fail"),
        ("FAILURE", "fail"),
        ("errored", "error"),
        ("skipped", "skip"),
        ("ignored", "skip"),
        ("", "pass"),
        ("something-weird", "fail"),
    ],
)
def test_normalize_outcome(raw, expected):
    assert normalize_outcome(raw) == expected


def test_split_classname_handles_dotted_modules_and_class_names():
    assert split_classname("tests.test_api") == ("tests/test_api.py", "")
    assert split_classname("pkg.mod.test_mod") == ("pkg/mod/test_mod.py", "")
    assert split_classname("src/App.test.tsx") == ("src/App.test.tsx", "")
    assert split_classname("com.acme.CalculatorTest") == ("", "com.acme.CalculatorTest")
    assert split_classname("") == ("", "")


def test_make_case_builds_pytest_style_ids():
    case = make_case(
        run_id="r",
        ts="t",
        classname="tests.test_api",
        name="test_ok",
        outcome="passed",
        duration=1.5,
    )
    assert case.test_id == "tests/test_api.py::test_ok"
    assert case.duration == 1.5


def test_make_case_keeps_file_attribute_over_classname():
    case = make_case(
        run_id="r",
        ts="t",
        classname="com.acme.Foo",
        file="src/com/acme/Foo.java",
        name="bar",
        outcome="fail",
    )
    assert case.test_id == "src/com/acme/Foo.java::com.acme.Foo::bar"


def test_negative_durations_are_clamped():
    case = make_case(run_id="r", ts="t", classname="", name="x", outcome="pass", duration=-3)
    assert case.duration == 0.0


def test_sort_runs_orders_by_timestamp_then_id():
    late = Run(run_id="a", ts="2026-02-01T00:00:00Z")
    early = Run(run_id="b", ts="2026-01-01T00:00:00Z")
    same_a = Run(run_id="x", ts="2026-01-15T00:00:00Z")
    same_b = Run(run_id="w", ts="2026-01-15T00:00:00Z")
    ordered = sort_runs([late, early, same_a, same_b])
    assert [r.run_id for r in ordered] == ["b", "w", "x", "a"]
    assert [r.cases for r in ordered] == [[] for _ in ordered]


def test_sort_runs_stamps_sequence_numbers():
    run = Run(run_id="a", ts="2026-01-01T00:00:00Z")
    run.cases.append(make_case(run_id="a", ts="", classname="", name="n", outcome="pass"))
    sort_runs([run])
    assert run.cases[0].seq == 0


def test_dedupe_runs_keeps_first_occurrence():
    first = Run(run_id="dup", source="first.xml")
    second = Run(run_id="dup", source="second.xml")
    other = Run(run_id="unique")
    kept = dedupe_runs([first, second, other])
    assert [r.source for r in kept] == ["first.xml", ""]
