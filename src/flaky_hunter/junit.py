"""JUnit XML parser: pytest, jest-junit, go-junit-report and maven surefire all land here."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .errors import ParseError
from .model import Run, make_case

_WS = re.compile(r"\s+")


def _tag(element: ET.Element) -> str:
    tag = element.tag
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _first_line(text: str, limit: int = 240) -> str:
    flat = _WS.sub(" ", (text or "").strip())
    return flat[:limit]


def _case_message(element: ET.Element) -> tuple[str, str]:
    """Return (outcome, message) for a testcase element."""
    outcome = "pass"
    message = ""
    for child in element:
        tag = _tag(child)
        if tag in {"failure", "error", "flakyFailure"}:
            outcome = "error" if tag == "error" else "fail"
            message = child.get("message") or _first_line("".join(child.itertext()))
            if not message:
                message = child.get("type", "")
            break
        if tag == "skipped":
            outcome = "skip"
            message = child.get("message") or ""
    if not message:
        message = element.get("message", "")
    return outcome, message


def _iter_testcases(root: ET.Element) -> list[ET.Element]:
    if _tag(root) == "testcase":
        return [root]
    found = [el for el in root.iter() if _tag(el) == "testcase"]
    return found


def parse_junit(text: str, *, run_id: str, ts: str = "", source: str = "") -> Run:
    """Parse JUnit XML of any of the shapes JUnit writers use."""
    stripped = (text or "").lstrip()
    if not stripped:
        raise ParseError("empty JUnit document")
    head = stripped[:64].lower()
    if not head.startswith("<?xml") and "<testsuite" not in head and "<testcase" not in head:
        raise ParseError("not a JUnit document (no <testsuite> or <testcase> element)")
    try:
        root = ET.fromstring(stripped)
    except ET.ParseError as exc:
        raise ParseError(f"invalid JUnit XML: {exc}") from exc

    run = Run(run_id=run_id, source=source, ts=ts)
    suite_ts = root.get("timestamp") or ts
    if not suite_ts:
        for element in root.iter():
            if _tag(element) == "testsuite" and element.get("timestamp"):
                suite_ts = element.get("timestamp") or ""
                break
    seen = 0
    for element in _iter_testcases(root):
        name = element.get("name") or ""
        classname = element.get("classname") or element.get("class") or ""
        file_attr = element.get("file") or ""
        if not name and not classname:
            continue
        try:
            duration = float(element.get("time") or 0.0)
        except ValueError:
            duration = 0.0
        if not name:
            name = classname
        outcome, message = _case_message(element)
        run.cases.append(
            make_case(
                run_id=run_id,
                ts=element.get("timestamp") or suite_ts,
                classname=classname,
                file=file_attr,
                name=name,
                outcome=outcome,
                duration=duration,
                message=message,
            )
        )
        seen += 1
    if not seen:
        raise ParseError("JUnit document contains no <testcase> elements")
    run.ts = suite_ts
    return run
