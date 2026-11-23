"""Extra coverage for the JSON parser and the HTML/Markdown report branches."""

from __future__ import annotations

import json

import pytest

from flaky_hunter.analysis import analyse_runs
from flaky_hunter.errors import ParseError
from flaky_hunter.model import Run, make_case
from flaky_hunter.pytest_json import parse_generic_json, parse_pytest_json
from flaky_hunter.report_html import render_html
from flaky_hunter.report_md import render_markdown


def _analysis(with_baseline: bool = False):
    from flaky_hunter.baseline import compare

    runs = []
    for index in range(10):
        run = Run(run_id=f"run-{index:03d}", ts=f"2026-01-{index + 1:02d}T09:00:00Z")
        for name, outcome, message in (
            ("test_timeout", "fail" if index % 2 else "pass", "socket.timeout: 30s"),
            ("test_regressed", "fail" if index >= 7 else "pass", "AssertionError: changed"),
            ("test_ok", "pass", ""),
        ):
            case = make_case(
                run_id=run.run_id,
                ts=run.ts,
                classname="tests.test_big",
                name=name,
                outcome=outcome,
                duration=2.0,
                message=message,
            )
            case.seq = index
            run.cases.append(case)
        runs.append(run)
    analysis = analyse_runs(runs)
    if with_baseline:
        analysis.baseline_diff = compare(
            analysis.stats,
            {"version": 1, "tests": {"tests/test_big.py::test_timeout": {"score": 0.0}}},
        )
        analysis.baseline_path = "baseline.json"
    return analysis


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"nodeid": "a.py::t", "outcome": "passed"}, "pass"),
        ({"nodeid": "b.py::t", "result": "failed"}, "fail"),
        ({"nodeid": "c.py::t", "status": "skipped"}, "skip"),
        ({"nodeid": "d.py::t", "state": "error"}, "error"),
        ({"nodeid": "e.py::t", "passed": True}, "pass"),
        ({"nodeid": "f.py::t", "failed": True}, "fail"),
        ({"nodeid": "g.py::t"}, "pass"),
    ],
)
def test_pytest_json_accepts_every_outcome_key(entry, expected):
    run = parse_pytest_json(json.dumps({"tests": [entry]}), run_id="r")
    assert run.cases[0].outcome == expected


def test_pytest_json_accepts_duration_ms_and_call_objects():
    doc = {
        "tests": [
            {
                "nodeid": "tests/test_a.py::test_x",
                "outcome": "failed",
                "duration_ms": 2500,
                "call": {"longrepr": "AssertionError: nope"},
            }
        ]
    }
    run = parse_pytest_json(json.dumps(doc), run_id="r")
    assert run.cases[0].duration == pytest.approx(2.5)
    assert run.cases[0].message == "AssertionError: nope"


def test_pytest_json_uses_started_timestamp_and_skips_junk():
    doc = {"started": 1700000000.5, "tests": [{"nodeid": "a.py::t", "outcome": "passed"}, 42, {}]}
    run = parse_pytest_json(json.dumps(doc), run_id="r")
    assert run.ts == "1700000000.5"
    assert len(run.cases) == 1


def test_pytest_json_rejects_empty_test_list():
    with pytest.raises(ParseError, match="no test entries"):
        parse_pytest_json('{"tests": []}', run_id="r")


def test_pytest_json_rejects_broken_json():
    with pytest.raises(ParseError, match="invalid JSON"):
        parse_pytest_json("{oops", run_id="r")


def test_generic_json_accepts_bare_array_and_ignores_junk():
    doc = [
        {"name": "test_a", "status": "passed", "duration": 1.5},
        {"test": "test_b", "outcome": "failed", "file": "tests/test_b.py"},
        {},
        "not-an-object",
    ]
    run = parse_generic_json(json.dumps(doc), run_id="r")
    assert [case.outcome for case in run.cases] == ["pass", "fail"]
    assert run.cases[1].test_id == "tests/test_b.py::test_b"


def test_generic_json_accepts_cases_wrapper():
    run = parse_generic_json('{"cases": [{"name": "test_a", "status": "ok"}]}', run_id="r")
    assert run.cases[0].test_id.endswith("test_a")


def test_generic_json_rejects_non_list_payload():
    with pytest.raises(ParseError, match="must be an array"):
        parse_generic_json('"a string"', run_id="r")


def test_html_report_renders_baseline_section():
    text = render_html(_analysis(with_baseline=True))
    assert "Baseline diff" in text
    assert "newly flaky" in text
    assert "worsened" in text


def test_html_report_renders_clean_suite_message():
    run = Run(run_id="r1", ts="2026-01-01T00:00:00Z")
    case = make_case(
        run_id="r1", ts=run.ts, classname="tests.test_a", name="test_ok", outcome="pass"
    )
    case.seq = 0
    run.cases.append(case)
    text = render_html(analyse_runs([run]))
    assert "No failing runs were observed" in text
    assert "No test clears the flakiness threshold" in text


def test_markdown_report_renders_baseline_and_verdict_sections():
    text = render_markdown(_analysis(with_baseline=True))
    assert "## Baseline diff" in text
    assert "**Newly flaky**" in text
    assert "## Verdicts" in text


def test_markdown_report_handles_no_failures():
    run = Run(run_id="r1", ts="2026-01-01T00:00:00Z")
    case = make_case(
        run_id="r1", ts=run.ts, classname="tests.test_a", name="test_ok", outcome="pass"
    )
    case.seq = 0
    run.cases.append(case)
    text = render_markdown(analyse_runs([run]))
    assert "No test clears the flakiness threshold" in text
