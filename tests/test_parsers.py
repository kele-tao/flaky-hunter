"""Parser tests: every supported result format and the error paths."""

from __future__ import annotations

import pytest

from flaky_hunter.errors import ParseError
from flaky_hunter.junit import parse_junit
from flaky_hunter.loader import load_results
from flaky_hunter.logs import parse_log
from flaky_hunter.pytest_json import parse_generic_json, parse_pytest_json

PYTEST_JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" timestamp="2026-01-01T09:00:00Z">
    <testcase classname="tests.test_api" name="test_ok" time="0.12"/>
    <testcase classname="tests.test_api" name="test_bad" time="31.5">
      <failure message="socket.timeout: timed out after 30.0s">traceback</failure>
    </testcase>
    <testcase classname="tests.test_api" name="test_err" time="0.5">
      <error message="RuntimeError: boom"/>
    </testcase>
    <testcase classname="tests.test_api" name="test_skip" time="0.0">
      <skipped message="needs docker"/>
    </testcase>
  </testsuite>
</testsuites>
"""

JEST_JUNIT = """<testsuite name="jest tests">
  <testcase classname="src/App.test.tsx" name="renders the app" time="0.031"/>
  <testcase classname="src/App.test.tsx" name="handles click" time="0.010">
    <failure>Error: expected 2 but got 3</failure>
  </testcase>
</testsuite>
"""


def test_junit_pytest_shape():
    run = parse_junit(PYTEST_JUNIT, run_id="run-1")
    assert len(run.cases) == 4
    ids = {case.test_id: case.outcome for case in run.cases}
    assert ids["tests/test_api.py::test_ok"] == "pass"
    assert ids["tests/test_api.py::test_bad"] == "fail"
    assert ids["tests/test_api.py::test_err"] == "error"
    assert ids["tests/test_api.py::test_skip"] == "skip"


def test_junit_keeps_failure_message_and_duration():
    run = parse_junit(PYTEST_JUNIT, run_id="run-1")
    bad = next(c for c in run.cases if c.name == "test_bad")
    assert "socket.timeout" in bad.message
    assert bad.duration == pytest.approx(31.5)
    assert run.ts == "2026-01-01T09:00:00Z"


def test_junit_jest_file_paths_are_preserved():
    run = parse_junit(JEST_JUNIT, run_id="r")
    ids = sorted(case.test_id for case in run.cases)
    assert ids == ["src/App.test.tsx::handles click", "src/App.test.tsx::renders the app"]


def test_junit_single_testcase_root():
    xml = '<testcase classname="tests.test_x" name="only" time="1.0"/>'
    run = parse_junit(xml, run_id="r")
    assert len(run.cases) == 1
    assert run.cases[0].test_id == "tests/test_x.py::only"


def test_junit_rejects_non_xml():
    with pytest.raises(ParseError, match="not a JUnit document"):
        parse_junit("this is just a sentence", run_id="r")


def test_junit_rejects_truncated_xml():
    with pytest.raises(ParseError, match="invalid JUnit XML"):
        parse_junit("<testsuite><testcase", run_id="r")


def test_junit_rejects_document_without_cases():
    with pytest.raises(ParseError, match="no <testcase>"):
        parse_junit("<testsuite></testsuite>", run_id="r")


def test_pytest_json_parses_nodeids():
    doc = """
    {"created": 1700000000.0, "tests": [
      {"nodeid": "tests/test_api.py::test_ok", "outcome": "passed", "duration": 0.2},
      {"nodeid": "tests/test_api.py::TestLive::test_flaky", "outcome": "failed",
       "duration": 1.5, "call": {"longrepr": "AssertionError: nope"}}
    ]}
    """
    run = parse_pytest_json(doc, run_id="r1")
    assert [case.outcome for case in run.cases] == ["pass", "fail"]
    assert run.cases[1].test_id == "tests/test_api.py::TestLive::test_flaky"
    assert "AssertionError" in run.cases[1].message


def test_pytest_json_rejects_array():
    with pytest.raises(ParseError, match="must be an object"):
        parse_pytest_json("[1, 2, 3]", run_id="r")


def test_pytest_json_rejects_missing_tests_key():
    with pytest.raises(ParseError, match="missing the tests array"):
        parse_pytest_json('{"summary": {}}', run_id="r")


def test_generic_json_accepts_results_wrapper():
    doc = (
        '{"results": [{"name": "test_a", "status": "passed"}, '
        '{"name": "test_b", "status": "failed"}]}'
    )
    run = parse_generic_json(doc, run_id="r")
    assert [case.outcome for case in run.cases] == ["pass", "fail"]


def test_log_parser_reads_pytest_verbose_output():
    log = (
        "collected 3 items\n"
        "[gw0] [ 33%] PASSED tests/test_api.py::test_ok\n"
        "[gw1] [ 66%] FAILED tests/test_api.py::test_flaky - AssertionError: 1 != 2\n"
        "[gw0] [100%] SKIPPED tests/test_slow.py::test_needs_docker\n"
    )
    run = parse_log(log, run_id="r")
    assert len(run.cases) == 3
    assert run.cases[1].outcome == "fail"
    assert "AssertionError" in run.cases[1].message
    assert run.cases[2].test_id == "tests/test_slow.py::test_needs_docker"


def test_log_parser_reads_go_test_output():
    log = "=== RUN   TestAdd\n--- PASS: TestAdd (0.01s)\n--- FAIL: TestSub (0.02s)\n"
    run = parse_log(log, run_id="r")
    assert [case.outcome for case in run.cases] == ["pass", "fail"]
    assert run.cases[0].duration == pytest.approx(0.01)


def test_log_parser_reads_maven_surefire_output():
    log = "[ERROR] testSubtract(com.acme.CalculatorTest)  Time elapsed: 0.02 s  <<< FAILURE!\n"
    run = parse_log(log, run_id="r")
    assert run.cases[0].outcome == "fail"
    assert run.cases[0].test_id == "com.acme.CalculatorTest::testSubtract"


def test_log_parser_rejects_noise():
    with pytest.raises(ParseError, match="no recognisable test result lines"):
        parse_log("Downloading dependencies...\nBuild finished in 3s\n", run_id="r")


def test_loader_reads_directory_and_ignores_noise(tmp_path, junit_factory):
    junit_factory(tmp_path, "run-0001.xml", [("tests.test_a", "test_x", "pass", 0.1)])
    (tmp_path / "notes.txt").write_text("just some prose about the build", encoding="utf-8")
    (tmp_path / "chart.png").write_bytes(b"not really a png")
    report = load_results([tmp_path])
    assert report.files == 2
    assert len(report.runs) == 1
    assert report.warnings and "notes.txt" in report.warnings[0]


def test_loader_deduplicates_run_ids(tmp_path, junit_factory):
    junit_factory(tmp_path, "run-0001.xml", [("tests.test_a", "test_x", "pass", 0.1)])
    (tmp_path / "copy").mkdir()
    junit_factory(tmp_path / "copy", "run-0001.xml", [("tests.test_a", "test_x", "pass", 0.1)])
    report = load_results([tmp_path])
    assert len(report.runs) == 1


def test_loader_errors_on_missing_path(tmp_path):
    from flaky_hunter.errors import FlakyHunterError

    with pytest.raises(FlakyHunterError, match="no such file"):
        load_results([tmp_path / "does-not-exist"])


def test_loader_errors_when_no_candidates(tmp_path):
    from flaky_hunter.errors import FlakyHunterError

    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    with pytest.raises(FlakyHunterError, match="no result files found"):
        load_results([tmp_path])
