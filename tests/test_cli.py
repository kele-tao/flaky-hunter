"""CLI tests: exit codes, flags, friendly errors and unicode safety."""

from __future__ import annotations

import json

import pytest

from flaky_hunter.cli import main

JUNIT = """<testsuite name="pytest" timestamp="2026-01-01T09:00:00Z">
  <testcase classname="tests.test_api" name="test_flaky" time="2.0"/>
  <testcase classname="tests.test_api" name="test_flaky" time="2.0"/>
</testsuite>
"""


def _tree(
    tmp_path,
    n=8,
    template='<testsuite name="pytest" timestamp="2026-01-{day:02d}T09:00:00Z">'
    '<testcase classname="tests.test_api" name="{name}" time="1.0">{body}</testcase>'
    "</testsuite>",
):
    for index in range(n):
        directory = tmp_path / "results"
        directory.mkdir(exist_ok=True)
        flaky_fail = index % 2 == 0
        cases = [
            ("test_flaky", '<failure message="socket.timeout: 30.0s"/>' if flaky_fail else ""),
            ("test_ok", ""),
        ]
        body = "".join(
            f'<testcase classname="tests.test_api" name="{name}" time="1.0">{extra}</testcase>'
            for name, extra in cases
        )
        xml = (
            '<testsuite name="pytest" timestamp="2026-01-'
            + f"{index + 1:02d}"
            + 'T09:00:00Z">'
            + body
            + "</testsuite>"
        )
        (directory / f"run-{index + 1:04d}.xml").write_text(xml, encoding="utf-8")
    return tmp_path / "results"


def test_analyze_exits_1_when_flaky(tmp_path, capsys):
    results = _tree(tmp_path)
    code = main(["analyze", str(results), "--color", "never"])
    out = capsys.readouterr().out
    assert code == 1
    assert "flaky" in out
    assert "test_flaky" in out


def test_analyze_exits_0_on_clean_results(tmp_path, capsys):
    (tmp_path / "results").mkdir()
    xml = (
        '<testsuite name="pytest" timestamp="2026-01-01T09:00:00Z">'
        '<testcase classname="tests.test_api" name="test_ok" time="0.1"/>'
        "</testsuite>"
    )
    (tmp_path / "results" / "run-0001.xml").write_text(xml, encoding="utf-8")
    code = main(["analyze", str(tmp_path / "results"), "--color", "never"])
    assert code == 0
    assert "0 flaky" in capsys.readouterr().out


def test_analyze_json_flag_is_machine_readable(tmp_path, capsys):
    results = _tree(tmp_path)
    main(["analyze", str(results), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "flaky-hunter"
    assert payload["runs"] == 8


def test_missing_path_is_a_usage_error(tmp_path, capsys):
    code = main(["analyze", str(tmp_path / "nope"), "--color", "never"])
    captured = capsys.readouterr()
    assert code == 2
    assert "no such file or directory" in captured.err
    assert "Traceback" not in captured.err


def test_bad_threshold_is_a_usage_error(tmp_path, capsys):
    results = _tree(tmp_path)
    code = main(["analyze", str(results), "--threshold", "9"])
    assert code == 2
    assert "between 0 and 1" in capsys.readouterr().err


def test_unknown_flag_exits_2(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", "results", "--nonsense"])
    assert excinfo.value.code == 2


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "usage: flaky-hunter" in capsys.readouterr().out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "1.0.0" in capsys.readouterr().out


def test_report_writes_markdown_file(tmp_path, capsys):
    results = _tree(tmp_path)
    out = tmp_path / "report.md"
    code = main(["report", str(results), "--format", "md", "-o", str(out)])
    assert code == 1
    assert out.exists()
    assert "leaderboard" in out.read_text(encoding="utf-8").lower()


def test_report_html_shortcut(tmp_path):
    results = _tree(tmp_path)
    out = tmp_path / "report.html"
    assert main(["report", str(results), "--html", "-o", str(out)]) == 1
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert "svg" in text


def test_report_json_to_stdout(tmp_path, capsys):
    results = _tree(tmp_path)
    main(["report", str(results), "--format", "json"])
    assert json.loads(capsys.readouterr().out)["flaky_count"] >= 1


def test_report_rejects_unknown_format(tmp_path):
    results = _tree(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["report", str(results), "--format", "pdf"])
    assert excinfo.value.code == 2


def test_quarantine_writes_new_pytest_ini(tmp_path, capsys):
    results = _tree(tmp_path)
    target = tmp_path / "pytest.ini"
    assert main(["quarantine", str(results), "--out", str(target)]) == 1
    text = target.read_text(encoding="utf-8")
    assert "[pytest]" in text
    assert "quarantine:" in text
    assert "not quarantine" in text
    assert "test_flaky" in text


def test_quarantine_merges_into_existing_config(tmp_path):
    results = _tree(tmp_path)
    target = tmp_path / "pytest.ini"
    target.write_text(
        "[pytest]\naddopts = -q --strict-markers\ntestpaths = tests\n", encoding="utf-8"
    )
    main(["quarantine", str(results), "--out", str(target)])
    text = target.read_text(encoding="utf-8")
    assert "--strict-markers" in text
    assert "testpaths = tests" in text
    assert "not quarantine" in text


def test_quarantine_dry_run_writes_nothing(tmp_path, capsys):
    results = _tree(tmp_path)
    target = tmp_path / "pytest.ini"
    main(["quarantine", str(results), "--out", str(target), "--dry-run"])
    assert not target.exists()
    assert "quarantine:" in capsys.readouterr().out


def test_explain_finds_a_test_by_fragment(tmp_path, capsys):
    results = _tree(tmp_path)
    code = main(["explain", "test_flaky", "--results", str(results), "--color", "never"])
    out = capsys.readouterr().out
    assert code == 1
    assert "wilson" in out
    assert "markov" in out


def test_explain_unknown_test_is_a_usage_error(tmp_path, capsys):
    results = _tree(tmp_path)
    code = main(["explain", "definitely_not_a_test", "--results", str(results)])
    captured = capsys.readouterr()
    assert code == 2
    assert "no test matches" in captured.err
    assert "Traceback" not in captured.err


def test_explain_ambiguous_selector_lists_candidates(tmp_path, capsys):

    results = tmp_path / "results"
    results.mkdir()
    body = "".join(
        f'<testcase classname="tests.test_api" name="test_{name}" time="1.0"/>'
        for name in ("alpha", "alphabet")
    )
    (results / "run-0001.xml").write_text(
        '<testsuite timestamp="2026-01-01T09:00:00Z">' + body + "</testsuite>", encoding="utf-8"
    )
    code = main(["explain", "test_alpha", "--results", str(results)])
    captured = capsys.readouterr()
    assert code == 2
    assert "matches 2 tests" in captured.err


def test_baseline_command_writes_file(tmp_path, capsys):
    results = _tree(tmp_path)
    out = tmp_path / "baseline.json"
    assert main(["baseline", str(results), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "tests" in payload


def test_analyze_with_baseline_reports_new_flaky(tmp_path, capsys):
    results = _tree(tmp_path)
    baseline = tmp_path / "baseline.json"
    clean = {
        "version": 1,
        "tests": {"tests/test_api.py::flaky": {"score": 0.0, "verdict": "stable"}},
    }
    baseline.write_text(json.dumps(clean), encoding="utf-8")
    main(["analyze", str(results), "--baseline", str(baseline), "--color", "never"])
    out = capsys.readouterr().out
    assert "baseline diff" in out
    assert "NEW flaky" in out


def test_analyze_fail_on_new_returns_1(tmp_path):
    results = _tree(tmp_path)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"version": 1, "tests": {}}), encoding="utf-8")
    assert main(["analyze", str(results), "--baseline", str(baseline), "--fail-on-new"]) == 1


def test_missing_baseline_file_is_friendly(tmp_path, capsys):
    results = _tree(tmp_path)
    code = main(["analyze", str(results), "--baseline", str(tmp_path / "nope.json")])
    assert code == 2
    assert "baseline file not found" in capsys.readouterr().err


def test_unicode_test_names_round_trip(tmp_path, capsys):
    results = tmp_path / "results"
    results.mkdir()
    body = (
        '<testcase classname="tests.test_i18n" name="test_\u4e2d\u6587_\U0001f600" time="0.2">'
        '<failure message="\u5931\u8d25: \u65e0\u6cd5\u8fde\u63a5"/></testcase>'
    )
    (results / "run-0001.xml").write_text(
        '<testsuite timestamp="2026-01-01T09:00:00Z">' + body + "</testsuite>", encoding="utf-8"
    )
    code = main(["report", str(results), "--format", "md", "-o", str(tmp_path / "r.md")])
    text = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert code == 0
    assert "\u4e2d\u6587" in text


def test_large_input_smoke(tmp_path, capsys):
    results = tmp_path / "results"
    results.mkdir()
    names = [f"test_case_{i}" for i in range(400)]
    for run in range(5):
        body = "".join(
            f'<testcase classname="tests.test_big" name="{name}" time="0.01">'
            + ('<failure message="boom"/>' if (index + run) % 17 == 0 else "")
            + "</testcase>"
            for index, name in enumerate(names)
        )
        (results / f"run-{run:03d}.xml").write_text(
            '<testsuite timestamp="2026-01-0'
            + str(run + 1)
            + 'T09:00:00Z">'
            + body
            + "</testsuite>",
            encoding="utf-8",
        )
    code = main(["analyze", str(results), "--color", "never"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert "2,000 results" in out
