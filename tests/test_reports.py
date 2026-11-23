"""Report renderers: terminal, Markdown, JSON and HTML."""

from __future__ import annotations

import json
import re

from flaky_hunter.analysis import analyse_runs
from flaky_hunter.ansi import Painter
from flaky_hunter.explain import render_explain, render_explain_markdown
from flaky_hunter.report_html import render_html
from flaky_hunter.report_json import render_json
from flaky_hunter.report_md import render_markdown
from flaky_hunter.terminal import render_analyze

NO_COLOUR = Painter(False)


def _flaky_analysis():
    from flaky_hunter.model import Run, make_case

    runs = []
    for index in range(12):
        run = Run(run_id=f"run-{index:03d}", ts=f"2026-01-{index + 1:02d}T09:00:00Z")
        for name, outcome, message in (
            ("test_timeout", "fail" if index % 2 else "pass", "socket.timeout: 30.0s"),
            ("test_ok", "pass", ""),
            ("test_broken", "fail", "AssertionError: always"),
        ):
            case = make_case(
                run_id=run.run_id,
                ts=run.ts,
                classname="tests.test_api",
                name=name,
                outcome=outcome,
                duration=30.0 if name == "test_timeout" else 0.1,
                message=message,
            )
            case.seq = index
            run.cases.append(case)
        runs.append(run)
    return analyse_runs(runs)


def test_terminal_contains_leaderboard_and_verdict():
    analysis = _flaky_analysis()
    text = render_analyze(analysis, NO_COLOUR, elapsed_ms=12)
    assert "leaderboard" in text
    assert "test_timeout" in text
    assert "flaky" in text
    assert "12 runs" in text


def test_terminal_has_no_ansi_when_disabled():
    text = render_analyze(_flaky_analysis(), NO_COLOUR)
    assert "\x1b[" not in text


def test_terminal_has_ansi_when_enabled():
    text = render_analyze(_flaky_analysis(), Painter(True))
    assert "\x1b[" in text


def test_json_report_is_valid_and_sorted():
    analysis = _flaky_analysis()
    payload = json.loads(render_json(analysis))
    assert payload["tool"] == "flaky-hunter"
    assert payload["runs"] == 12
    assert payload["flaky_count"] >= 1
    assert set(payload["tests"][0]) >= {"test_id", "score", "verdict", "history"}
    text = render_json(analysis)
    assert text.index('"files"') < text.index('"tests"')


def test_json_output_is_deterministic():
    analysis = _flaky_analysis()
    assert render_json(analysis) == render_json(analysis)


def test_markdown_report_has_tables_and_quarantine_block():
    text = render_markdown(_flaky_analysis())
    assert text.startswith("# flaky-hunter report")
    assert "| ---" in text
    assert "pytest.mark.quarantine" in text
    assert "not quarantine" in text


def test_html_report_is_standalone_and_contains_svg():
    text = render_html(_flaky_analysis())
    assert text.startswith("<!doctype html>")
    assert "<svg" in text
    assert "http://" not in text.replace("http://www.w3.org", "")
    assert "test_timeout" in text
    assert "<script" in text


def test_html_escapes_untrusted_test_names():
    from flaky_hunter.model import Run, make_case

    run = Run(run_id="run-0", ts="2026-01-01T00:00:00Z")
    case = make_case(
        run_id="run-0",
        ts=run.ts,
        classname="tests.test_x",
        name="<script>alert(1)</script>",
        outcome="fail",
        message="<img src=x>",
    )
    case.seq = 0
    run.cases.append(case)
    analysis = analyse_runs([run, Run(run_id="run-1", ts="2026-01-02T00:00:00Z")])
    text = render_html(analysis)
    assert "<script>alert(1)" not in text
    assert "&lt;script&gt;" in text


def test_explain_renders_evidence_bars():
    analysis = _flaky_analysis()
    item = next(i for i in analysis.stats if i.test_id.endswith("test_timeout"))
    lines = render_explain(analysis, item, NO_COLOUR)
    text = "\n".join(lines)
    assert "wilson 95% lower bound" in text
    assert "markov" in text
    assert "history" in text


def test_explain_markdown_has_metric_table():
    analysis = _flaky_analysis()
    item = next(i for i in analysis.stats if i.test_id.endswith("test_timeout"))
    text = render_explain_markdown(item)
    assert "| metric | value |" in text
    assert "flakiness score" in text


def test_empty_analysis_renders_cleanly():
    analysis = analyse_runs([])
    text = render_analyze(analysis, NO_COLOUR)
    assert isinstance(text, str)
    assert "0 runs" in text
    payload = json.loads(render_json(analysis))
    assert payload["tests"] == []


def test_svg_sparkline_marks_failures_red():
    from flaky_hunter.formatting import svg_sparkline

    svg = svg_sparkline(["pass", "fail", "skip"])
    assert svg.count("<rect") == 3
    assert "#f87171" in svg
    assert "#64748b" in svg


def test_human_duration_units():
    from flaky_hunter.formatting import human_duration

    assert human_duration(0.0004) == "0ms"
    assert human_duration(0.42) == "420ms"
    assert human_duration(2.5) == "2.50s"
    assert human_duration(75) == "1m15s"
    assert human_duration(3700) == "1h01m"


def test_truncate_marks_ellipsis():
    from flaky_hunter.formatting import truncate

    assert truncate("abcdef", 4) == "abc\u2026"
    assert truncate("abc", 10) == "abc"


def test_markdown_has_no_unrendered_ansi():
    text = render_markdown(_flaky_analysis())
    assert not re.search(r"\x1b\[", text)
