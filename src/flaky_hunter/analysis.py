"""Orchestration: load result files, score tests, correlate failures, diff a baseline."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

from . import baseline as baseline_mod
from .correlations import CorrelationReport, analyse_correlations
from .loader import LoadReport, load_results
from .model import Run
from .stats import FLAKY_THRESHOLD, TestStats, analyse_timelines, build_timelines, flaky_tests


@dataclass(slots=True)
class Analysis:
    """A complete, renderable analysis of one results tree."""

    runs: list[Run] = field(default_factory=list)
    stats: list[TestStats] = field(default_factory=list)
    correlations: CorrelationReport = field(default_factory=CorrelationReport)
    warnings: list[str] = field(default_factory=list)
    files: int = 0
    min_runs: int = 5
    threshold: float = FLAKY_THRESHOLD
    baseline_diff: dict | None = None
    baseline_path: str = ""

    @property
    def cases(self) -> int:
        return sum(len(run.cases) for run in self.runs)

    @property
    def failures(self) -> int:
        return sum(item.failures for item in self.stats)

    @property
    def flaky(self) -> list[TestStats]:
        return flaky_tests(self.stats, self.threshold)

    @property
    def first_ts(self) -> str:
        stamps = [run.ts for run in self.runs if run.ts]
        return min(stamps) if stamps else ""

    @property
    def last_ts(self) -> str:
        stamps = [run.ts for run in self.runs if run.ts]
        return max(stamps) if stamps else ""

    def by_id(self, test_id: str) -> TestStats | None:
        for item in self.stats:
            if item.test_id == test_id:
                return item
        return None

    def verdict_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.stats:
            counts[item.verdict] = counts.get(item.verdict, 0) + 1
        return dict(sorted(counts.items()))


def analyse_paths(
    paths: list[pathlib.Path],
    *,
    min_runs: int = 5,
    threshold: float = FLAKY_THRESHOLD,
    baseline_file: pathlib.Path | None = None,
) -> Analysis:
    """Load result files and produce a full analysis."""
    loaded: LoadReport = load_results(paths)
    return analyse_runs(
        loaded.runs,
        warnings=loaded.warnings,
        files=loaded.files,
        min_runs=min_runs,
        threshold=threshold,
        baseline_file=baseline_file,
    )


def analyse_runs(
    runs: list[Run],
    *,
    warnings: list[str] | None = None,
    files: int = 0,
    min_runs: int = 5,
    threshold: float = FLAKY_THRESHOLD,
    baseline_file: pathlib.Path | None = None,
) -> Analysis:
    """Score already-parsed runs (used by the loader and by the tests)."""
    timelines = build_timelines(runs)
    stats = analyse_timelines(timelines, min_runs=min_runs)
    correlations = analyse_correlations(stats)
    analysis = Analysis(
        runs=list(runs),
        stats=stats,
        correlations=correlations,
        warnings=list(warnings or []),
        files=files or len(runs),
        min_runs=min_runs,
        threshold=threshold,
    )
    if baseline_file is not None:
        payload = baseline_mod.load(baseline_file)
        analysis.baseline_diff = baseline_mod.compare(stats, payload)
        analysis.baseline_path = str(baseline_file)
    return analysis


def save_baseline(analysis: Analysis, path: pathlib.Path) -> dict:
    """Persist the current scores as the next run's baseline."""
    return baseline_mod.save(path, analysis.stats)


def quarantine_list(analysis: Analysis, threshold: float) -> list[TestStats]:
    """Tests at or above the threshold that are genuinely flaky, ranked by impact."""
    return flaky_tests(analysis.stats, threshold)
