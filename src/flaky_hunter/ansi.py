"""Tiny ANSI helpers so colours can be turned off deterministically."""

from __future__ import annotations

import os
import sys

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
GREY = "\x1b[90m"
BRIGHT_RED = "\x1b[91m"
BRIGHT_GREEN = "\x1b[92m"
BRIGHT_YELLOW = "\x1b[93m"
WHITE = "\x1b[97m"


class Painter:
    """Wrap text in ANSI codes, or return it untouched when colour is off."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *codes: str) -> str:
        if not self.enabled or not codes:
            return text
        return "".join(codes) + text + RESET

    def strip(self, text: str) -> str:
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)


def colour_enabled(mode: str = "auto") -> bool:
    """Resolve --color auto|always|never, honouring NO_COLOR and FORCE_COLOR."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") not in (None, "", "0"):
        return True
    return sys.stdout.isatty()


VERDICT_COLOURS = {
    "flaky": BRIGHT_YELLOW,
    "broken": BRIGHT_RED,
    "regressed": RED,
    "fixed": BRIGHT_GREEN,
    "unstable": YELLOW,
    "single-failure": YELLOW,
    "stable": GREEN,
    "skipped": GREY,
    "no-data": GREY,
}

GLYPHS = {"pass": "\u2588", "fail": "\u2717", "skip": "\u00b7", "error": "\u2717"}
GLYPH_COLOURS = {"pass": GREEN, "fail": RED, "skip": GREY, "error": BRIGHT_RED}
