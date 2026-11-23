"""Markdown report renderer."""

from __future__ import annotations

from .analysis import Analysis
from .formatting import (
    history_emoji,
    human_count,
    human_duration,
    human_duration_or_na,
    short_score,
    truncate,
)

FENCE = chr(96) * 3
BT = chr(96)


def code(text: str) -> str:
    """Wrap text in a Markdown code span."""
    return BT + text + BT


def _summary_table(analysis: Analysis) -> list[str]:
    flaky = analysis.flaky
    wasted = sum(item.total_duration * item.failure_rate for item in flaky)
    rows = [
        "| metric | value |",
        "| --- | --- |",
        f"| runs analysed | {len(analysis.runs)} |",
        f"| result files | {analysis.files} |",
        f"| test results | {human_count(analysis.cases)} |",
        f"| distinct tests | {len(analysis.stats)} |",
        f"| flaky tests (score >= {analysis.threshold:.2f}) | {len(flaky)} |",
        f"| failing observations | {sum(item.failures for item in analysis.stats)} |",
        f"| flaky CI time (estimate) | {human_duration(wasted)} |",
    ]
    if analysis.first_ts:
        rows.append(f"| window | {analysis.first_ts} .. {analysis.last_ts} |")
    return rows


def render_markdown(
    analysis: Analysis, *, top: int = 15, title: str = "flaky-hunter report"
) -> str:
    """Render a GitHub-flavoured Markdown report."""
    lines: list[str] = ["# " + title, ""]
    lines.extend(_summary_table(analysis))
    lines.append("")

    lines.append("## Leaderboard (top " + str(min(top, len(analysis.stats))) + " by impact)")
    lines.append("")
    if not analysis.stats:
        lines.append("_No test results were found._")
    else:
        lines.append("| # | test | score | fail | runs | P->F | impact | avg | history | verdict |")
        lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |")
        shown = [s for s in analysis.stats if s.failures][:top] or analysis.stats[:top]
        for rank, item in enumerate(shown, 1):
            lines.append(
                "| "
                + str(rank)
                + " | "
                + code(item.test_id)
                + " | "
                + short_score(item.score)
                + " | "
                + str(item.failures)
                + "/"
                + str(item.runs)
                + " | "
                + str(item.runs)
                + " | "
                + format(item.chain.pass_to_fail, ".2f")
                + " | "
                + format(item.impact, ".3f")
                + " | "
                + human_duration_or_na(item.avg_duration)
                + " | "
                + history_emoji(item.history)
                + " | "
                + item.verdict
                + " |"
            )
    lines.append("")

    if analysis.correlations.clusters:
        lines.append("## Failure signatures")
        lines.append("")
        lines.append("Tests that fail with the same normalised message are almost always one bug.")
        lines.append("")
        lines.append("| tests | failures | signature |")
        lines.append("| ---: | ---: | --- |")
        for cluster in analysis.correlations.clusters[:10]:
            lines.append(
                "| "
                + str(cluster.size)
                + " | "
                + str(cluster.failures)
                + " | "
                + code(truncate(cluster.label, 110))
                + " |"
            )
        lines.append("")

    if analysis.correlations.pairs:
        lines.append("## Correlated failures")
        lines.append("")
        lines.append("| jaccard | test A | test B | shared runs |")
        lines.append("| ---: | --- | --- | --- |")
        for pair in analysis.correlations.pairs[:10]:
            lines.append(
                "| "
                + format(pair.jaccard, ".2f")
                + " | "
                + code(pair.left)
                + " | "
                + code(pair.right)
                + " | "
                + ", ".join(pair.shared_runs[:5])
                + " |"
            )
        lines.append("")

    if analysis.baseline_diff:
        diff = analysis.baseline_diff
        lines.append("## Baseline diff")
        lines.append("")
        for label, key in (
            ("Newly flaky", "newly_flaky"),
            ("Worsened", "worsened"),
            ("Fixed", "fixed"),
            ("New tests", "new_tests"),
            ("Removed", "removed"),
        ):
            entries = diff[key]
            lines.append("**" + label + "** (" + str(len(entries)) + ")")
            lines.append("")
            if entries:
                lines.extend("- " + code(test_id) for test_id in entries[:10])
            else:
                lines.append("- none")
            lines.append("")

    flaky = analysis.flaky
    lines.append("## Suggested quarantine")
    lines.append("")
    if flaky:
        lines.append("Mark these tests so CI can exclude them while they are fixed:")
        lines.append("")
        lines.append(FENCE + "ini")
        lines.append("[pytest]")
        lines.append("markers =")
        lines.append("    quarantine: flaky test excluded from CI until fixed")
        lines.append("")
        lines.append("addopts = -m " + chr(34) + "not quarantine" + chr(34))
        lines.append(FENCE)
        lines.append("")
        lines.append("Then annotate each test:")
        lines.append("")
        lines.append(FENCE + "python")
        for item in flaky[:8]:
            name = item.test_id.split("::")[-1]
            lines.append(
                "@pytest.mark.quarantine  # score " + short_score(item.score) + ": " + name
            )
        lines.append(FENCE)
    else:
        lines.append("No test clears the flakiness threshold. Nothing to quarantine.")
    lines.append("")

    verdicts = analysis.verdict_counts()
    if verdicts:
        lines.append("## Verdicts")
        lines.append("")
        lines.append("| verdict | tests |")
        lines.append("| --- | ---: |")
        lines.extend("| " + name + " | " + str(count) + " |" for name, count in verdicts.items())
        lines.append("")

    lines.append(
        "_Generated by flaky-hunter; every number above is computed from the result files._"
    )
    return "\n".join(lines) + "\n"
