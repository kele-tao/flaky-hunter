"""The explain command: why one test is (or is not) considered flaky."""

from __future__ import annotations

from .analysis import Analysis
from .ansi import BLUE, BOLD, CYAN, DIM, GREY, RED, VERDICT_COLOURS, WHITE, YELLOW, Painter
from .formatting import (
    history_glyphs,
    human_duration_or_na,
    pct,
    short_score,
    truncate,
)

FENCE = chr(96) * 3


def _bar(value: float, width: int = 28) -> str:
    filled = int(round(min(max(value, 0.0), 1.0) * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def render_explain(analysis: Analysis, item, painter: Painter) -> list[str]:
    """Render the evidence behind a single test verdict."""
    paint = painter
    lines: list[str] = []
    title = truncate(item.test_id, 78)
    lines.append("")
    lines.append(paint("  " + title, BOLD, WHITE))
    verdict_colour = VERDICT_COLOURS.get(item.verdict, GREY)
    lines.append(
        "  verdict "
        + paint(item.verdict.upper(), BOLD, verdict_colour)
        + paint(
            f"   score {item.score:.3f}   impact {item.impact:.3f}   "
            f"runs {item.runs} ({item.passes} pass / {item.failures} fail / {item.skips} skip)",
            DIM,
        )
    )
    lines.append("")
    lines.append(paint("  history", BOLD))
    glyphs = history_glyphs(item.history, paint)
    lines.append(f"    oldest {glyphs} newest")
    marks = "".join("^" if outcome in ("fail", "error") else " " for outcome in item.history)
    lines.append(paint("           " + marks, RED))
    lines.append("")
    lines.append(paint("  evidence", BOLD))
    rows = [
        (
            "failure rate",
            pct(item.failure_rate, 1)
            + f"  ({item.failures}/{item.passes + item.failures} decided runs)",
        ),
        ("wilson 95% lower bound", f"{item.failure_lower:.3f}   " + _bar(item.failure_lower)),
        ("markov  P(pass -> fail)", f"{item.chain.pass_to_fail:.3f}"),
        ("markov  P(fail -> pass)", f"{item.chain.fail_to_pass:.3f}"),
        (
            "flip ratio",
            f"{item.chain.flip_ratio:.3f}   "
            f"({item.chain.flips} flips over {item.chain.pairs} transitions)",
        ),
        ("flakiness score", f"{item.score:.3f}   sqrt(bound x flip) x shrink"),
        ("average duration", human_duration_or_na(item.avg_duration)),
        ("impact", f"{item.impact:.3f}   score x duration x failures"),
    ]
    for label, value in rows:
        lines.append("    " + paint(label.ljust(24), CYAN) + value)
    lines.append("")
    if item.messages:
        paired = zip(item.history, item.messages, strict=False)
        failures = [
            (index, message)
            for index, (outcome, message) in enumerate(paired)
            if outcome in ("fail", "error") and message
        ]
        if failures:
            lines.append(paint("  failure messages", BOLD) + paint(" (most recent first)", DIM))
            for index, message in reversed(failures[-3:]):
                lines.append("    " + paint(f"run {index:<3}", YELLOW) + truncate(message, 92))
            lines.append("")
    if item.low_confidence:
        lines.append(
            paint(
                f"  note: only {item.runs} runs observed; "
                "scores below 10 runs carry wide error bars.",
                BLUE,
            )
        )
        lines.append("")
    peers = [
        pair
        for pair in analysis.correlations.pairs
        if pair.left == item.test_id or pair.right == item.test_id
    ]
    if peers:
        lines.append(
            paint("  correlated failures", BOLD)
            + paint(" (same CI runs, check the shared fixture)", DIM)
        )
        for pair in peers[:5]:
            other = pair.right if pair.left == item.test_id else pair.left
            lines.append(
                "    "
                + paint(f"jaccard {pair.jaccard:.2f}", YELLOW)
                + "  "
                + truncate(other, 70)
                + paint(f"  shared runs: {', '.join(pair.shared_runs[:4])}", GREY)
            )
        lines.append("")
    return lines


def render_explain_markdown(item) -> str:
    """A GitHub-friendly block used by report --format md --explain."""
    lines = [
        "### " + item.test_id,
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| verdict | {item.verdict} |",
        f"| flakiness score | {short_score(item.score)} |",
        f"| runs / failures | {item.runs} / {item.failures} |",
        f"| wilson lower bound | {item.failure_lower:.3f} |",
        f"| P(pass -> fail) | {item.chain.pass_to_fail:.3f} |",
        f"| P(fail -> pass) | {item.chain.fail_to_pass:.3f} |",
        f"| average duration | {human_duration_or_na(item.avg_duration)} |",
        "",
        "History (oldest first): " + " ".join(item.history),
        "",
    ]
    return "\n".join(lines)
