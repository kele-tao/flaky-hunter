"""Result-file discovery and dispatch to the right parser."""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field

from . import junit, logs, pytest_json
from .errors import FlakyHunterError, ParseError
from .model import Run, dedupe_runs, sort_runs

SUPPORTED_SUFFIXES = (".xml", ".json", ".log", ".txt", ".out", ".jsonl")

_RUN_ID = re.compile(r"\d+")


@dataclass(slots=True)
class LoadReport:
    """Outcome of loading a results tree: usable runs plus per-file warnings."""

    runs: list[Run] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: int = 0

    @property
    def cases(self) -> int:
        return sum(len(run.cases) for run in self.runs)


def _run_id_for(path: pathlib.Path, index: int) -> str:
    """Derive a stable run id from the file name, keeping numeric order."""
    numbers = _RUN_ID.findall(path.stem)
    if numbers:
        return path.stem
    return f"{index:04d}-{path.stem}"


def _parse_file(path: pathlib.Path, text: str, run_id: str) -> Run:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return junit.parse_junit(text, run_id=run_id, source=str(path))
    if suffix == ".json":
        return pytest_json.parse_pytest_json(text, run_id=run_id, source=str(path))
    if suffix == ".jsonl":
        entries = [line for line in text.splitlines() if line.strip()]
        return pytest_json.parse_generic_json(
            "[" + ",".join(entries) + "]", run_id=run_id, source=str(path)
        )
    if suffix in {".log", ".txt", ".out"}:
        if text.lstrip().startswith(("<", "{")):
            try:
                return junit.parse_junit(text, run_id=run_id, source=str(path))
            except ParseError:
                return pytest_json.parse_generic_json(text, run_id=run_id, source=str(path))
        return logs.parse_log(text, run_id=run_id, source=str(path))
    raise ParseError(f"cannot tell how to read {path.name}")


def _candidate_files(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(p for p in sorted(path.rglob("*")) if p.is_file())
        elif path.is_file():
            files.append(path)
        else:
            raise FlakyHunterError(f"no such file or directory: {path}")
    return [
        p for p in files if p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith(".")
    ]


def load_results(paths: list[pathlib.Path]) -> LoadReport:
    """Load every supported result file under the given paths."""
    report = LoadReport()
    files = _candidate_files(paths)
    if not files:
        raise FlakyHunterError(
            "no result files found (looked for " + ", ".join(SUPPORTED_SUFFIXES) + ")"
        )
    for index, path in enumerate(files):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report.warnings.append(f"{path.name}: {exc.strerror or exc}")
            continue
        report.files += 1
        run_id = _run_id_for(path, index)
        try:
            run = _parse_file(path, text, run_id)
        except ParseError as exc:
            if len(files) == 1:
                raise FlakyHunterError(f"{path.name}: {exc}") from exc
            report.warnings.append(f"{path.name}: ignored ({exc})")
            continue
        report.runs.append(run)
    if not report.runs:
        raise FlakyHunterError(
            "none of the " + str(len(files)) + " candidate files contained test results"
        )
    report.runs = sort_runs(dedupe_runs(report.runs))
    return report


def write_baseline(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
