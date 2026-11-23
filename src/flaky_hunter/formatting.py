"""Formatting helpers shared by the terminal, Markdown and HTML renderers."""

from __future__ import annotations

import re
from collections.abc import Sequence

from .ansi import GLYPH_COLOURS, GLYPHS, Painter

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

BLOCK_LEVELS = " .:-=+*#%@"
FAIL_COLOUR = "#f87171"
PASS_COLOUR = "#4ade80"
SKIP_COLOUR = "#64748b"


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def human_duration(seconds: float) -> str:
    """Render a duration with a sensible unit."""
    value = max(float(seconds or 0.0), 0.0)
    if value < 0.001:
        return "0ms"
    if value < 1.0:
        return f"{value * 1000:.0f}ms"
    if value < 60.0:
        return f"{value:.2f}s" if value < 10 else f"{value:.1f}s"
    if value < 3600.0:
        minutes = int(value // 60)
        secs = int(value % 60)
        return f"{minutes}m{secs:02d}s"
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    return f"{hours}h{minutes:02d}m"


def human_duration_or_na(seconds: float) -> str:
    """Like human_duration, but renders unknown (zero) durations honestly."""
    return "n/a" if not seconds else human_duration(seconds)


def human_count(number: int) -> str:
    return f"{number:,}"


def pct(value: float, digits: int = 0) -> str:
    return f"{value * 100:.{digits}f}%"


def short_score(value: float) -> str:
    return f"{value:.2f}"


def truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 1] + "\u2026"


def history_glyphs(history: Sequence[str], painter: Painter | None = None) -> str:
    """Terminal sparkline: one glyph per run, oldest first."""
    if painter is None:
        return "".join(GLYPHS.get(o, "?") for o in history)
    return "".join(painter(GLYPHS.get(o, "?"), GLYPH_COLOURS.get(o, "")) for o in history)


def history_emoji(history: Sequence[str]) -> str:
    """Markdown sparkline that survives on GitHub."""
    table = {"pass": "\U0001f7e9", "fail": "\U0001f7e5", "error": "\U0001f7e5", "skip": "\u2b1c"}
    return "".join(table.get(o, "\u2753") for o in history)


def svg_sparkline(
    history: Sequence[str], *, width: int = 180, height: int = 18, gap: int = 2
) -> str:
    """Inline SVG bar sparkline: green pass bars, red failure bars."""
    runs = max(len(history), 1)
    cell = max((width - gap * (runs - 1)) / runs, 1.0)
    parts = [
        f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'role="img" aria-label="test history">'
    ]
    for index, outcome in enumerate(history):
        x = index * (cell + gap)
        if outcome in ("fail", "error"):
            colour = FAIL_COLOUR
            bar = height
        elif outcome == "skip":
            colour = SKIP_COLOUR
            bar = max(height // 3, 3)
        else:
            colour = PASS_COLOUR
            bar = height
        y = height - bar
        parts.append(
            f'<rect x="{x:.1f}" y="{y}" width="{cell:.1f}" height="{bar}" rx="1" fill="{colour}"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_table(rows: list[list[str]], *, aligns: str = "", gap: int = 2) -> list[str]:
    """Left/right align columns, ignoring ANSI escapes when measuring width."""
    if not rows:
        return []
    columns = len(rows[0])
    widths = [0] * columns
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(strip_ansi(cell)))
    lines: list[str] = []
    for row in rows:
        cells: list[str] = []
        for index, cell in enumerate(row):
            visible = len(strip_ansi(cell))
            padding = " " * max(widths[index] - visible, 0)
            right = aligns[index] == "r" if index < len(aligns) else False
            cells.append(padding + cell if right else cell + padding)
        lines.append((" " * gap).join(cells).rstrip())
    return lines


def marker_snippet_prefix() -> str:
    return "[pytest]"
