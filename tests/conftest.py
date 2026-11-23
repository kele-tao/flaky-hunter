"""Shared pytest fixtures: build small synthetic result trees without any network."""

from __future__ import annotations

import pathlib

import pytest

from flaky_hunter.model import Run, make_case


@pytest.fixture
def junit_factory():
    """Return a callable that writes a JUnit XML file and returns its path."""

    def write(
        directory: pathlib.Path, name: str, cases: list[tuple[str, str, str, float]]
    ) -> pathlib.Path:
        rows = []
        for classname, test_name, outcome, duration in cases:
            body = ""
            if outcome in ("fail", "error"):
                tag = "failure" if outcome == "fail" else "error"
                body = f'<{tag} message="boom {test_name}"/>'
            elif outcome == "skip":
                body = "<skipped/>"
            rows.append(
                f'  <testcase classname="{classname}" name="{test_name}" '
                f'time="{duration}">{body}</testcase>'
            )
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<testsuite name="pytest" timestamp="2026-01-0{len(name) % 9 + 1}T09:00:00Z">\n'
            + "\n".join(rows)
            + "\n</testsuite>\n"
        )
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding="utf-8")
        return path

    return write


@pytest.fixture
def run_factory():
    """Return a callable that builds a Run from (name, outcome) pairs."""

    def build(run_id: str, ts: str, cases: list[tuple[str, str]], duration: float = 1.0) -> Run:
        run = Run(run_id=run_id, ts=ts)
        for classname, outcome in cases:
            path, _, name = classname.partition("::")
            run.cases.append(
                make_case(
                    run_id=run_id,
                    ts=ts,
                    classname="",
                    file=path,
                    name=name,
                    outcome=outcome,
                    duration=duration,
                )
            )
        return run

    return build
