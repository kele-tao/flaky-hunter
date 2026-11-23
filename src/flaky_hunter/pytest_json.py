"""pytest-json-report parser (and a generic JSON array/object fallback)."""

from __future__ import annotations

import json

from .errors import ParseError
from .model import Run, make_case

_OUTCOME_KEYS = ("outcome", "result", "status", "state")


def _pick_outcome(entry: dict) -> str:
    for key in _OUTCOME_KEYS:
        if key in entry and isinstance(entry[key], str):
            return entry[key]
    if entry.get("passed") is True:
        return "pass"
    if entry.get("failed") is True:
        return "fail"
    return "pass"


def _duration(entry: dict) -> float:
    for key in ("duration", "time", "elapsed", "duration_ms"):
        if key in entry:
            try:
                value = float(entry[key])
            except (TypeError, ValueError):
                continue
            if key == "duration_ms":
                return value / 1000.0
            return value
    return 0.0


def _message(entry: dict) -> str:
    for key in ("message", "longrepr", "call", "trace", "error"):
        raw = entry.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().splitlines()[0][:240]
        if isinstance(raw, dict):
            for inner in ("longrepr", "message", "crash"):
                text = raw.get(inner)
                if isinstance(text, str) and text.strip():
                    return text.strip().splitlines()[0][:240]
    return ""


def parse_pytest_json(text: str, *, run_id: str, ts: str = "", source: str = "") -> Run:
    """Parse a pytest-json-report document.

    Shape: {"created": ..., "tests": [{"nodeid": "...", "outcome": "passed",
    "duration": 0.12, "call": {"longrepr": "..."}}]}
    """
    try:
        doc = json.loads(text or "")
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc.msg} at line {exc.lineno}") from exc
    if not isinstance(doc, dict):
        raise ParseError("pytest JSON must be an object with a tests array")
    tests = doc.get("tests")
    if not isinstance(tests, list):
        raise ParseError("pytest JSON is missing the tests array")
    created = doc.get("created") or doc.get("started") or ts
    run = Run(run_id=run_id, source=source, ts=str(created or ts))
    for entry in tests:
        if not isinstance(entry, dict):
            continue
        nodeid = entry.get("nodeid") or entry.get("name") or ""
        if not nodeid:
            continue
        file_part = ""
        name = nodeid
        if "::" in nodeid:
            file_part, name = nodeid.split("::", 1)
        classname = ""
        if "::" in name:
            classname, name = name.rsplit("::", 1)
        run.cases.append(
            make_case(
                run_id=run_id,
                ts=run.ts,
                classname=classname,
                file=file_part,
                name=name,
                outcome=_pick_outcome(entry),
                duration=_duration(entry),
                message=_message(entry),
            )
        )
    if not run.cases:
        raise ParseError("pytest JSON contains no test entries")
    return run


def parse_generic_json(text: str, *, run_id: str, ts: str = "", source: str = "") -> Run:
    """Fallback: a bare array of test objects, each with name + outcome."""
    try:
        doc = json.loads(text or "")
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc.msg} at line {exc.lineno}") from exc
    if isinstance(doc, dict):
        for key in ("results", "tests", "cases", "data"):
            if isinstance(doc.get(key), list):
                doc = doc[key]
                break
        else:
            doc = [doc]
    if not isinstance(doc, list):
        raise ParseError("generic JSON must be an array of test objects")
    run = Run(run_id=run_id, source=source, ts=ts)
    for entry in doc:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("test") or entry.get("nodeid") or ""
        if not name:
            continue
        run.cases.append(
            make_case(
                run_id=run_id,
                ts=ts,
                classname=entry.get("classname") or entry.get("suite") or "",
                file=entry.get("file") or "",
                name=str(name),
                outcome=_pick_outcome(entry),
                duration=_duration(entry),
                message=_message(entry),
            )
        )
    if not run.cases:
        raise ParseError("generic JSON contains no test objects with a name")
    return run
