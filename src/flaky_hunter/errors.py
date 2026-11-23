"""Error types that the CLI turns into friendly, actionable messages."""

from __future__ import annotations


class FlakyHunterError(Exception):
    """Base class for user-facing failures (exit code 2)."""


class ParseError(FlakyHunterError):
    """A result file could not be understood."""
