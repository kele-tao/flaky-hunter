"""flaky-hunter: find the tests that waste your CI minutes.

Public API::

    from flaky_hunter import analyse_paths, render_json
    analysis = analyse_paths([Path("results")])
    print(render_json(analysis))
"""

from __future__ import annotations

from .analysis import Analysis, analyse_paths, analyse_runs
from .baseline import compare as compare_baseline
from .baseline import load as load_baseline
from .baseline import save as save_baseline
from .errors import FlakyHunterError, ParseError
from .loader import load_results
from .model import Run, TestCase, normalize_outcome
from .stats import MarkovChain, TestStats, flaky_tests, wilson_lower

__version__ = "1.0.0"

__all__ = [
    "Analysis",
    "FlakyHunterError",
    "MarkovChain",
    "ParseError",
    "Run",
    "TestCase",
    "TestStats",
    "__version__",
    "analyse_paths",
    "analyse_runs",
    "compare_baseline",
    "flaky_tests",
    "load_baseline",
    "load_results",
    "normalize_outcome",
    "save_baseline",
    "wilson_lower",
]
