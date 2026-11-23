"""Core model: per-test outcome timelines normalised from heterogeneous CI result files."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

OUTCOMES = ("pass", "fail", "error", "skip")
FAILED_OUTCOMES = ("fail", "error")


@dataclass(slots=True)
class TestCase:
    """A single observed execution of one test inside one CI run."""

    __test__ = False  # not a pytest test class, despite the name

    run_id: str
    ts: str
    file: str
    name: str
    outcome: str
    duration: float = 0.0
    message: str = ""
    classname: str = ""
    seq: int = 0

    @property
    def test_id(self) -> str:
        head = self.name
        if self.classname:
            head = f"{self.classname}::{self.name}"
        if self.file:
            return f"{self.file}::{head}"
        return head


@dataclass(slots=True)
class Run:
    """One CI run (typically one result file) and the cases it reported."""

    run_id: str
    source: str = ""
    ts: str = ""
    cases: list[TestCase] = field(default_factory=list)


def normalize_outcome(raw: str) -> str:
    """Map the many ways CI tools spell an outcome to our four canonical values."""
    value = (raw or "").strip().lower()
    if value in {"passed", "pass", "ok", "success", "succeeded", "green", "true"}:
        return "pass"
    if value in {"failed", "fail", "failure", "failing", "red", "false"}:
        return "fail"
    if value in {"error", "errored", "broken", "interrupted"}:
        return "error"
    if value in {"skipped", "skip", "ignored", "pending", "disabled", "n/a", "none"}:
        return "skip"
    return "pass" if value == "" else "fail"


def _looks_like_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or value.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb", ".cs"))
    )


def split_classname(classname: str) -> tuple[str, str]:
    """Split a CI classname attribute into (file, class).

    pytest writes classname="tests.test_api" (a dotted module path), JUnit
    writers for Java/Go write a package or class name, and jest writes a file
    path. We keep the distinction so test_id reads like a pytest node id in
    every case.
    """
    cls = (classname or "").strip().replace("\\", "/")
    if not cls:
        return "", ""
    if _looks_like_path(cls):
        return cls, ""
    if "." in cls and cls.rsplit(".", 1)[-1][:1].islower():
        base = cls.replace(".", "/")
        if not base.endswith((".py", ".js", ".ts", ".go", ".java", ".rb", ".cs")):
            base += ".py"
        return base, ""
    return "", cls


def make_case(
    *,
    run_id: str,
    ts: str,
    classname: str,
    name: str,
    outcome: str,
    duration: float = 0.0,
    message: str = "",
    file: str = "",
) -> TestCase:
    """Build a case, resolving a class name to file+class when no file is given."""
    path, cls = split_classname(classname)
    if file:
        path = file.replace("\\", "/")
    return TestCase(
        run_id=run_id,
        ts=ts,
        file=path,
        name=name.strip() or "<anonymous>",
        outcome=normalize_outcome(outcome),
        duration=max(float(duration or 0.0), 0.0),
        message=(message or "").strip(),
        classname=cls,
    )


def sort_runs(runs: Iterable[Run]) -> list[Run]:
    """Order runs by timestamp then id, and stamp each case with its run index."""
    ordered = sorted(runs, key=lambda r: (r.ts or "", r.run_id))
    for index, run in enumerate(ordered):
        run.cases.sort(key=lambda c: (c.test_id, c.outcome))
        for case in run.cases:
            case.seq = index
    return ordered


def dedupe_runs(runs: Sequence[Run]) -> list[Run]:
    """Collapse duplicate run ids (re-uploaded files) keeping the first file seen."""
    seen: dict[str, Run] = {}
    for run in runs:
        if run.run_id not in seen:
            seen[run.run_id] = run
    return list(seen.values())
