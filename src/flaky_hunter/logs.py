"""Fallback parser for raw CI logs (pytest -v output, go test -v, surefire text)."""

from __future__ import annotations

import re

from .errors import ParseError
from .model import Run, make_case

_PYTEST = re.compile(
    r"(?:\[gw\d+\]\s*)?\[\s*\d+%\]\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+)"
    r"(?:\s+-\s+(.*))?\s*$"
)
_PYTEST_BARE = re.compile(
    r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+([\w./\-]+\.py::\S+)(?:\s+-\s+(.*))?\s*$"
)
_GO = re.compile(r"^\s*---\s+(PASS|FAIL|SKIP):\s+(\S+)\s*(?:\(([\d.]+)s\))?")
_SUREFIRE = re.compile(
    r"^\[ERROR\]\s+([\w$]+)\(([\w.$]+)\)\s+Time elapsed:.*?<<<\s+(FAILURE|ERROR)!"
)
_TS = re.compile(r"^\s*(?:\[?[\w.\-]+\]?\s+)?(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", re.M)

_ALIASES = {
    "PASSED": "pass",
    "FAILED": "fail",
    "ERROR": "error",
    "SKIPPED": "skip",
    "XFAIL": "skip",
    "XPASS": "pass",
}


def sniff_log(text: str) -> bool:
    """Cheap check: does this text look like test output at all?"""
    for line in (text or "").splitlines():
        if _PYTEST.search(line) or _GO.match(line) or _SUREFIRE.match(line):
            return True
    return False


def _split_nodeid(nodeid: str) -> tuple[str, str, str]:
    path = ""
    rest = nodeid
    if "::" in nodeid:
        path, rest = nodeid.split("::", 1)
    cls = ""
    if "::" in rest:
        cls, rest = rest.rsplit("::", 1)
    return path, cls, rest


def parse_log(text: str, *, run_id: str, ts: str = "", source: str = "") -> Run:
    """Parse test lines out of a raw CI log.

    This is deliberately line-oriented and forgiving: a log with 30 000 lines of
    build noise and 200 test lines yields the 200 test lines.
    """
    body = text or ""
    if not body.strip():
        raise ParseError("empty log file")
    if not sniff_log(body):
        raise ParseError("no recognisable test result lines (expected pytest/go/maven output)")

    run = Run(run_id=run_id, source=source, ts=ts)
    if not run.ts:
        # Only accept a timestamp that starts a line: failure messages often quote
        # dates ("token expired at 2025-12-31T23:59:59Z"), and we must not treat
        # those as the run time.
        match = _TS.search(body)
        if match:
            run.ts = f"{match.group(1)}T{match.group(2)}"

    go_suite = "go.test"
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _PYTEST.search(line) or _PYTEST_BARE.match(line)
        if match:
            outcome, nodeid, message = match.group(1), match.group(2), (match.group(3) or "")
            path, cls, name = _split_nodeid(nodeid)
            run.cases.append(
                make_case(
                    run_id=run_id,
                    ts=run.ts,
                    classname=cls,
                    file=path,
                    name=name,
                    outcome=_ALIASES[outcome],
                    duration=0.0,
                    message=message,
                )
            )
            continue
        match = _GO.match(line)
        if match:
            outcome, name, seconds = match.group(1), match.group(2), match.group(3)
            run.cases.append(
                make_case(
                    run_id=run_id,
                    ts=run.ts,
                    classname=go_suite,
                    name=name,
                    outcome="pass"
                    if outcome == "PASS"
                    else ("skip" if outcome == "SKIP" else "fail"),
                    duration=float(seconds or 0.0),
                )
            )
            continue
        match = _SUREFIRE.match(line)
        if match:
            method, klass, outcome = match.group(1), match.group(2), match.group(3)
            run.cases.append(
                make_case(
                    run_id=run_id,
                    ts=run.ts,
                    classname=klass,
                    name=method,
                    outcome="fail" if outcome == "FAILURE" else "error",
                )
            )
    if not run.cases:
        raise ParseError("log contains no test result lines")
    return run
