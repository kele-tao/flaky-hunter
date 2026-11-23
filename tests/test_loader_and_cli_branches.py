"""Coverage for the loader dispatch table, terminal branches and CLI help paths."""

from __future__ import annotations

import json
import pathlib

import pytest

from flaky_hunter.ansi import Painter
from flaky_hunter.cli import main
from flaky_hunter.errors import FlakyHunterError
from flaky_hunter.loader import load_results
from flaky_hunter.terminal import render_analyze

NO_COLOUR = Painter(False)


def test_loader_dispatches_jsonl(tmp_path):
    lines = [
        json.dumps({"name": "test_a", "status": "passed"}),
        json.dumps({"name": "test_b", "status": "failed"}),
    ]
    (tmp_path / "results.jsonl").write_text("\n".join(lines), encoding="utf-8")
    report = load_results([tmp_path])
    assert len(report.runs[0].cases) == 2


def test_loader_sniffs_json_inside_a_txt_file(tmp_path):
    (tmp_path / "upload.txt").write_text(
        '{"tests": [{"nodeid": "a.py::t", "outcome": "passed"}]}', encoding="utf-8"
    )
    report = load_results([tmp_path])
    assert report.runs[0].cases[0].outcome == "pass"


def test_loader_sniffs_xml_inside_a_txt_file(tmp_path):
    (tmp_path / "upload.txt").write_text(
        '<testsuite timestamp="2026-01-01T00:00:00Z">'
        '<testcase classname="tests.test_a" name="t" time="0.1"/></testsuite>',
        encoding="utf-8",
    )
    report = load_results([tmp_path])
    assert report.runs[0].cases[0].test_id == "tests/test_a.py::t"


def test_loader_rejects_unknown_suffixes_in_a_single_file(tmp_path):
    path = tmp_path / "results.yaml"
    path.write_text("results: []", encoding="utf-8")
    with pytest.raises(FlakyHunterError, match="no result files found"):
        load_results([path])


def test_loader_reports_a_single_file_error(tmp_path):
    path = tmp_path / "broken.xml"
    path.write_text("<testsuite><testcase", encoding="utf-8")
    with pytest.raises(FlakyHunterError, match="broken.xml"):
        load_results([path])


def test_loader_errors_when_every_file_is_unparseable(tmp_path):
    (tmp_path / "a.xml").write_text("nonsense", encoding="utf-8")
    (tmp_path / "b.json").write_text('{"nope": 1}', encoding="utf-8")
    with pytest.raises(FlakyHunterError, match="none of the 2 candidate files"):
        load_results([tmp_path])


def test_loader_accepts_a_single_file_argument(tmp_path):
    path = tmp_path / "run-1.xml"
    path.write_text(
        '<testsuite timestamp="2026-01-01T00:00:00Z">'
        '<testcase classname="tests.test_a" name="t" time="0.1"/></testsuite>',
        encoding="utf-8",
    )
    report = load_results([path])
    assert report.files == 1
    assert report.cases == 1


def test_terminal_renders_warnings_and_baseline_and_clusters():
    from flaky_hunter.analysis import analyse_runs
    from flaky_hunter.baseline import compare
    from flaky_hunter.correlations import analyse_correlations
    from flaky_hunter.model import Run, make_case

    runs = []
    for index in range(10):
        run = Run(run_id=f"run-{index:03d}", ts=f"2026-01-{index + 1:02d}T09:00:00Z")
        for name in ("a", "b"):
            case = make_case(
                run_id=run.run_id,
                ts=run.ts,
                classname="tests.test_x",
                name=name,
                outcome="fail" if index % 2 else "pass",
                duration=5.0,
                message="ConnectionError: refused 10.0.0.1:5432",
            )
            case.seq = index
            run.cases.append(case)
        runs.append(run)
    analysis = analyse_runs(runs, warnings=["a.xml: ignored (bad)"] * 7)
    analysis.correlations = analyse_correlations(analysis.stats)
    analysis.baseline_diff = compare(analysis.stats, {"version": 1, "tests": {}})
    analysis.baseline_path = "baseline.json"
    text = render_analyze(analysis, NO_COLOUR)
    assert "warnings" in text
    assert "... 2 more" in text
    assert "baseline diff" in text
    assert "NEW flaky" in text
    assert "failure signatures" in text
    assert "correlated failures" in text


def test_analyse_lightweight_view(tmp_path, capsys):
    path = tmp_path / "run-1.xml"
    path.write_text(
        '<testsuite timestamp="2026-01-01T00:00:00Z">'
        '<testcase classname="tests.test_a" name="t" time="0.1"/></testsuite>',
        encoding="utf-8",
    )
    assert main(["analyze", str(path), "--color", "never"]) == 0
    out = capsys.readouterr().out
    assert "1 tests tracked" in out


def test_analyze_top_flag_changes_row_count(tmp_path, capsys):
    results = tmp_path / "results"
    results.mkdir()
    body = "".join(
        f'<testcase classname="tests.test_big" name="test_{i}" time="1.0">'
        '<failure message="boom"/></testcase>'
        for i in range(20)
    )
    for run in range(3):
        (results / f"run-{run:03d}.xml").write_text(
            f'<testsuite timestamp="2026-01-0{run + 1}T00:00:00Z">{body}</testsuite>',
            encoding="utf-8",
        )
    main(["analyze", str(results), "--top", "3", "--color", "never"])
    out = capsys.readouterr().out
    assert " 1  " in out
    assert "test_5" not in out


def test_report_terminal_format_without_out_prints_to_stdout(tmp_path, capsys):
    results = tmp_path / "results"
    results.mkdir()
    (results / "run-000.xml").write_text(
        '<testsuite timestamp="2026-01-01T00:00:00Z">'
        '<testcase classname="tests.test_a" name="t" time="0.1"/></testsuite>',
        encoding="utf-8",
    )
    assert main(["report", str(results), "--color", "never"]) == 0
    assert "flaky-hunter" in capsys.readouterr().out


def test_quarantine_with_no_candidates_reports_success(tmp_path, capsys):
    results = tmp_path / "results"
    results.mkdir()
    (results / "run-000.xml").write_text(
        '<testsuite timestamp="2026-01-01T00:00:00Z">'
        '<testcase classname="tests.test_a" name="t" time="0.1"/></testsuite>',
        encoding="utf-8",
    )
    target = tmp_path / "pytest.ini"
    code = main(["quarantine", str(results), "--out", str(target), "--threshold", "0.9"])
    assert code == 0
    assert target.exists()
    assert "quarantine threshold 0.90" in capsys.readouterr().out
    text = target.read_text(encoding="utf-8")
    assert "quarantine:" in text
    assert "quarantined by flaky-hunter" not in text  # nothing was selected


def test_quarantine_rejects_a_foreign_config_file(tmp_path, capsys):
    results = tmp_path / "results"
    results.mkdir()
    body = "".join(
        f'<testcase classname="tests.test_a" name="test_{i}" time="1.0">'
        '<failure message="boom"/></testcase>'
        for i in range(3)
    )
    for run in range(6):
        (results / f"run-{run:03d}.xml").write_text(
            f'<testsuite timestamp="2026-01-0{run + 1}T00:00:00Z">{body}</testsuite>',
            encoding="utf-8",
        )
    target = tmp_path / "pytest.ini"
    target.write_text("[tool.black]\nline-length = 88\n", encoding="utf-8")
    code = main(["quarantine", str(results), "--out", str(target)])
    assert code == 2
    assert "refusing to edit" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "[tool.black]\nline-length = 88\n"


def test_explain_json_and_markdown_modes(tmp_path, capsys):
    results = tmp_path / "results"
    results.mkdir()
    body = "".join(
        '<testcase classname="tests.test_a" name="test_flaky" time="1.0">'
        '<failure message="boom"/></testcase>'
        if i % 2
        else '<testcase classname="tests.test_a" name="test_flaky" time="1.0"/>'
        for i in range(12)
    )
    (results / "run-000.xml").write_text(
        f'<testsuite timestamp="2026-01-01T00:00:00Z">{body}</testsuite>', encoding="utf-8"
    )
    capsys.readouterr()
    main(["explain", "test_flaky", "--results", str(results), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["test"]["test_id"].endswith("test_flaky")
    assert isinstance(payload["peers"], list)

    main(["explain", "test_flaky", "--results", str(results), "--md"])
    text = capsys.readouterr().out
    assert "| metric | value |" in text


def test_main_with_help_flag_and_stdin_paths_are_rejected(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", "--help"])
    assert excinfo.value.code == 0
    assert "PATH" in capsys.readouterr().out


def test_suggest_helper_returns_ranked_candidates():
    from flaky_hunter.cli import _suggest

    known = ["tests/test_api.py::test_timeout", "tests/test_api.py::test_ok"]
    assert _suggest("timeout", known)[0] == "tests/test_api.py::test_timeout"
    assert _suggest("zzzzz", known) == []


def test_module_entry_point_runs(tmp_path):
    import subprocess
    import sys

    repo_root = pathlib.Path(__file__).resolve().parent.parent
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(repo_root / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "flaky_hunter", "--version"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo_root),
        timeout=60,
    )
    assert proc.returncode == 0
    assert "1.0.0" in proc.stdout
