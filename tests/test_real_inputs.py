"""Regression tests for behaviour that only shows up on real-world inputs."""

from __future__ import annotations

import json
import pathlib

from flaky_hunter.analysis import analyse_paths, analyse_runs
from flaky_hunter.cli import main
from flaky_hunter.formatting import human_duration_or_na
from flaky_hunter.logs import parse_log
from flaky_hunter.model import Run, make_case
from flaky_hunter.stats import flaky_tests

REPO = pathlib.Path(__file__).resolve().parent.parent


def _run(run_id: str, seq: int, entries: list[tuple[str, str, float]]) -> Run:
    run = Run(run_id=run_id, ts=f"2026-01-{seq + 1:02d}T00:00:00Z")
    for name, outcome, duration in entries:
        case = make_case(
            run_id=run_id,
            ts=run.ts,
            classname="tests.test_x",
            name=name,
            outcome=outcome,
            duration=duration,
        )
        case.seq = seq
        run.cases.append(case)
    return run


def test_human_duration_or_na():
    assert human_duration_or_na(0.0) == "n/a"
    assert human_duration_or_na(1.5) == "1.50s"


def test_flaky_tests_excludes_regressed_and_fixed():
    runs = []
    for index in range(20):
        runs.append(
            _run(
                f"run-{index}",
                index,
                [
                    ("flaky", "fail" if index % 2 else "pass", 1.0),
                    ("regressed", "fail" if index >= 14 else "pass", 1.0),
                    ("fixed", "fail" if index < 6 else "pass", 1.0),
                ],
            )
        )
    analysis = analyse_runs(runs)
    flagged = {item.test_id.split("::")[-1] for item in flaky_tests(analysis.stats, 0.10)}
    assert "flaky" in flagged
    assert "regressed" not in flagged
    assert "fixed" not in flagged


def test_impact_uses_a_floor_when_durations_are_unknown():
    runs = []
    for index in range(12):
        runs.append(
            _run(
                f"run-{index}",
                index,
                [
                    ("often", "fail" if index % 2 else "pass", 0.0),
                    ("rarely", "fail" if index % 5 == 0 else "pass", 0.0),
                ],
            )
        )
    stats = analyse_runs(runs).stats
    by_name = {item.test_id.split("::")[-1]: item for item in stats}
    assert by_name["often"].impact > by_name["rarely"].impact > 0


def test_log_parser_ignores_dates_inside_failure_messages():
    log = (
        "2026-03-04 11:22:33 Running suite\n"
        "[ 50%] FAILED tests/test_a.py::test_token - AssertionError: expired 2025-12-31T23:59:59Z\n"
        "[100%] PASSED tests/test_a.py::test_ok\n"
    )
    run = parse_log(log, run_id="r")
    assert run.ts == "2026-03-04T11:22:33"


def test_example_corpus_is_stable_and_matches_ground_truth():
    truth = json.loads((REPO / "examples" / "ground_truth.json").read_text(encoding="utf-8"))
    analysis = analyse_paths([REPO / "examples" / "results"])
    assert len(analysis.runs) == truth["runs"]
    assert len(analysis.stats) == truth["tests"]
    flagged = {item.test_id for item in analysis.flaky}
    expected = set(truth["labels"]["truly_flaky"])
    assert expected <= flagged
    assert len(flagged - expected) == 1


def test_raw_log_examples_parse_with_the_fallback_parser():
    analysis = analyse_paths([REPO / "examples" / "raw-log"])
    assert analysis.files == 10
    assert len(analysis.stats) == 25
    assert all(item.avg_duration == 0.0 for item in analysis.stats)


def test_analyze_renders_na_durations_for_logs(tmp_path, capsys):
    code = main(
        ["analyze", str(REPO / "examples" / "raw-log"), "--color", "never", "--threshold", "0.9"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "n/a" in out


def test_determinism_of_json_report_on_examples():
    from flaky_hunter.report_json import render_json

    first = analyse_paths([REPO / "examples" / "results"])
    second = analyse_paths([REPO / "examples" / "results"])
    assert render_json(first) == render_json(second)
