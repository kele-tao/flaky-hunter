"""Terminal renderer for the analyze command."""

from __future__ import annotations

import shutil

from .analysis import Analysis
from .ansi import BOLD, CYAN, DIM, GREEN, GREY, RED, VERDICT_COLOURS, WHITE, YELLOW, Painter
from .formatting import (
    history_glyphs,
    human_count,
    human_duration,
    human_duration_or_na,
    pct,
    render_table,
    short_score,
    truncate,
)

MAX_ROWS = 12
MAX_CLUSTERS = 4


def _width(default: int = 100) -> int:
    return max(min(shutil.get_terminal_size((default, 24)).columns, 140), 80)


def _header(analysis: Analysis, painter: Painter) -> list[str]:
    paint = painter
    width = _width()
    lines: list[str] = []
    top = analysis.stats
    total_runs = len(analysis.runs)
    span = ""
    if analysis.first_ts and analysis.last_ts:
        span = f"{analysis.first_ts} .. {analysis.last_ts}"
    lines.append("")
    lines.append(
        paint("  flaky-hunter", BOLD, WHITE)
        + paint(
            f"  {total_runs} runs  {analysis.files} files  {human_count(analysis.cases)} results",
            GREY,
        )
    )
    lines.append(paint("  " + "-" * (width - 4), GREY))
    flaky = analysis.flaky
    wasted = sum(item.total_duration for item in flaky)
    lines.append(
        "  "
        + paint(f"{len(top)} tests", BOLD)
        + paint(" tracked   ", DIM)
        + paint(f"{len(flaky)} flaky", BOLD, YELLOW)
        + paint("   ", DIM)
        + paint(f"{sum(item.failures for item in top)} failing observations", BOLD, RED)
        + paint("   ~", DIM)
        + paint(human_duration(wasted), BOLD, YELLOW)
        + paint(" of CI time in flaky tests", DIM)
    )
    if span:
        lines.append(paint(f"  window {span}", GREY))
    counts = analysis.verdict_counts()
    parts = [
        paint(f"{name} {count}", VERDICT_COLOURS.get(name, WHITE))
        for name, count in counts.items()
        if name in ("flaky", "broken", "regressed", "fixed", "single-failure", "unstable")
    ]
    if parts:
        lines.append("  " + "   ".join(parts))
    lines.append("")
    return lines


def _leaderboard(analysis: Analysis, painter: Painter) -> list[str]:
    paint = painter
    rows: list[list[str]] = []
    header = ["#", "test", "score", "fail", "runs", "P->F", "impact", "avg", "history", "verdict"]
    rows.append([paint(cell, BOLD, GREY) for cell in header])
    shown = [item for item in analysis.stats if item.failures or item.skips][:MAX_ROWS]
    if not shown:
        shown = analysis.stats[:MAX_ROWS]
    for rank, item in enumerate(shown, 1):
        verdict_colour = VERDICT_COLOURS.get(item.verdict, WHITE)
        rows.append(
            [
                paint(str(rank), GREY),
                truncate(item.test_id, 42),
                short_score(item.score),
                f"{item.failures}/{item.runs}",
                pct(item.failure_rate, 0),
                f"{item.chain.pass_to_fail:.2f}",
                f"{item.impact:.3f}",
                human_duration_or_na(item.avg_duration),
                history_glyphs(item.history, paint),
                paint(item.verdict, verdict_colour),
            ]
        )
    lines = [paint("  leaderboard (ranked by impact = score x duration x failures)", BOLD)]
    for line in render_table(rows, aligns="rlrrrrrrll", gap=2):
        lines.append("  " + line)
    lines.append("")
    return lines


def _clusters(analysis: Analysis, painter: Painter) -> list[str]:
    paint = painter
    clusters = analysis.correlations.clusters
    if not clusters:
        return []
    lines = [
        paint("  failure signatures", BOLD)
        + paint(f" ({len(clusters)} cluster(s) with 2+ tests)", DIM)
    ]
    for cluster in clusters[:MAX_CLUSTERS]:
        label = truncate(cluster.label.replace("\n", " "), 74)
        lines.append(
            "    "
            + paint(f"{cluster.size:>2} tests", BOLD, YELLOW)
            + paint(f" x {cluster.failures} failures  ", DIM)
            + paint(label, WHITE)
        )
        for test_id in cluster.tests[:3]:
            lines.append(paint("       " + truncate(test_id, 74), GREY))
        if cluster.size > 3:
            lines.append(paint(f"       ... {cluster.size - 3} more", GREY))
    lines.append("")
    return lines


def _correlated(analysis: Analysis, painter: Painter) -> list[str]:
    paint = painter
    pairs = analysis.correlations.pairs
    if not pairs:
        return []
    lines = [paint("  correlated failures (same runs -> suspect a shared fixture)", BOLD)]
    for pair in pairs[:4]:
        lines.append(
            "    "
            + paint(f"jaccard {pair.jaccard:.2f}", YELLOW)
            + "  "
            + truncate(pair.left, 40)
            + paint("  <->  ", DIM)
            + truncate(pair.right, 40)
        )
    lines.append("")
    return lines


def _baseline(analysis: Analysis, painter: Painter) -> list[str]:
    diff = analysis.baseline_diff
    if not diff:
        return []
    paint = painter
    lines = [paint("  baseline diff", BOLD) + paint(f" ({analysis.baseline_path})", DIM)]
    if diff["newly_flaky"]:
        lines.append("    " + paint(f"NEW flaky   {len(diff['newly_flaky'])}", BOLD, RED))
        for test_id in diff["newly_flaky"][:5]:
            lines.append(paint("       " + truncate(test_id, 80), RED))
    if diff["worsened"]:
        lines.append("    " + paint(f"worsened    {len(diff['worsened'])}", BOLD, YELLOW))
        for test_id in diff["worsened"][:5]:
            lines.append(paint("       " + truncate(test_id, 80), YELLOW))
    if diff["fixed"]:
        lines.append("    " + paint(f"fixed       {len(diff['fixed'])}", BOLD, GREEN))
        for test_id in diff["fixed"][:5]:
            lines.append(paint("       " + truncate(test_id, 80), GREEN))
    if diff["new_tests"]:
        lines.append("    " + paint(f"new tests   {len(diff['new_tests'])}", GREY))
    if diff["removed"]:
        lines.append("    " + paint(f"removed     {len(diff['removed'])}", GREY))
    if not any(diff[key] for key in ("newly_flaky", "worsened", "fixed", "new_tests", "removed")):
        lines.append("    " + paint("no change against the baseline", GREEN))
    lines.append("")
    return lines


def _quarantine(analysis: Analysis, painter: Painter) -> list[str]:
    paint = painter
    candidates = analysis.flaky[:6]
    if not candidates:
        return []
    lines = [
        paint("  suggested quarantine", BOLD)
        + paint(f" ({len(analysis.flaky)} test(s) above score {analysis.threshold:.2f})", DIM)
    ]
    for item in candidates:
        lines.append(
            "    "
            + paint(short_score(item.score), YELLOW)
            + "  "
            + truncate(item.test_id, 72)
            + paint(
                f"  saves ~{human_duration(item.total_duration * (1 - item.failure_rate))}", GREY
            )
        )
    lines.append("")
    lines.append(
        "  "
        + paint(
            "run: flaky-hunter quarantine <results> --threshold " + f"{analysis.threshold:.2f}",
            CYAN,
        )
    )
    lines.append("")
    return lines


def _warnings(analysis: Analysis, painter: Painter) -> list[str]:
    if not analysis.warnings:
        return []
    lines = [painter("  warnings", BOLD, YELLOW)]
    for warning in analysis.warnings[:5]:
        lines.append(painter("    " + truncate(warning, 96), GREY))
    if len(analysis.warnings) > 5:
        lines.append(painter(f"    ... {len(analysis.warnings) - 5} more", GREY))
    lines.append("")
    return lines


def _footer(analysis: Analysis, painter: Painter, elapsed_ms: float) -> list[str]:
    paint = painter
    return [
        "  "
        + paint("next", BOLD)
        + paint("  flaky-hunter explain <test-id>", CYAN)
        + paint("   |   ", GREY)
        + paint("flaky-hunter report results/ --format html", CYAN)
        + paint(f"   ({elapsed_ms:.0f} ms)", GREY),
        "",
    ]


def render_analyze(analysis: Analysis, painter: Painter, *, elapsed_ms: float = 0.0) -> str:
    """Render the full analyze screen."""
    lines: list[str] = []
    lines.extend(_header(analysis, painter))
    if not analysis.stats:
        lines.append(painter("  no test results found", BOLD, RED))
        return "\n".join(lines) + "\n"
    lines.extend(_leaderboard(analysis, painter))
    lines.extend(_clusters(analysis, painter))
    lines.extend(_correlated(analysis, painter))
    lines.extend(_baseline(analysis, painter))
    lines.extend(_quarantine(analysis, painter))
    lines.extend(_warnings(analysis, painter))
    lines.extend(_footer(analysis, painter, elapsed_ms))
    return "\n".join(lines) + "\n"
