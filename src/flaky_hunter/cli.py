"""flaky-hunter command line interface."""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
from collections.abc import Sequence

from . import __version__
from .analysis import Analysis, analyse_paths
from .ansi import BOLD, GREEN, GREY, RED, WHITE, YELLOW, Painter, colour_enabled
from .errors import FlakyHunterError
from .explain import render_explain, render_explain_markdown
from .formatting import pct
from .quarantine import plan as quarantine_plan
from .quarantine import render_terminal as render_quarantine
from .quarantine import write_ini
from .report_html import render_html
from .report_json import render_json
from .report_md import render_markdown
from .stats import FLAKY_THRESHOLD, parse_test_selector
from .terminal import render_analyze

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
FORMATS = ("terminal", "md", "json", "html")


class FlakyArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that exits 2 with a one-line message, never a traceback."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write(f"flaky-hunter: error: {message}\n")
        raise SystemExit(EXIT_USAGE)


def build_parser() -> FlakyArgumentParser:
    parser = FlakyArgumentParser(
        prog="flaky-hunter",
        description="Find the tests that waste your CI minutes.",
        epilog=(
            "exit codes: 0 no flaky tests above threshold, 1 flaky tests found "
            "(or quality gate failed), 2 usage or input error"
        ),
    )
    parser.add_argument("--version", action="version", version=f"flaky-hunter {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    def shared_flags(sub_parser: argparse.ArgumentParser) -> None:
        sub_parser.add_argument(
            "--baseline",
            type=pathlib.Path,
            default=None,
            metavar="FILE",
            help="baseline JSON from a previous run to diff against",
        )
        sub_parser.add_argument(
            "--min-runs",
            type=int,
            default=5,
            metavar="N",
            help="runs needed before a test reaches full score (default: 5)",
        )
        sub_parser.add_argument(
            "--threshold",
            type=float,
            default=FLAKY_THRESHOLD,
            metavar="S",
            help=f"flakiness score threshold in [0,1] (default: {FLAKY_THRESHOLD})",
        )
        sub_parser.add_argument(
            "--color",
            choices=("auto", "always", "never"),
            default="auto",
            help="colour output (default: auto)",
        )

    def common(sub_parser: argparse.ArgumentParser, *, paths: bool = True) -> None:
        if paths:
            sub_parser.add_argument(
                "paths",
                nargs="+",
                metavar="PATH",
                help="result file or directory (JUnit XML, pytest JSON, raw CI logs)",
            )
        else:
            sub_parser.add_argument(
                "--results",
                nargs="+",
                default=["results"],
                metavar="PATH",
                help="result file or directory to read (default: ./results)",
            )
        shared_flags(sub_parser)

    analyze = sub.add_parser("analyze", help="rank tests by flaky impact")
    common(analyze)
    analyze.add_argument("--top", type=int, default=12, metavar="N", help="rows in the leaderboard")
    analyze.add_argument("--json", action="store_true", help="print machine-readable JSON")
    analyze.add_argument(
        "--save-baseline",
        type=pathlib.Path,
        default=None,
        metavar="FILE",
        help="write the current scores as the next baseline",
    )
    analyze.add_argument(
        "--fail-on-new",
        action="store_true",
        help="exit 1 when the baseline diff reports newly flaky or worsened tests",
    )

    report = sub.add_parser("report", help="write a Markdown, JSON or HTML report")
    common(report)
    report.add_argument(
        "--format",
        choices=FORMATS,
        default="terminal",
        help="output format (default: terminal)",
    )
    report.add_argument("--html", action="store_true", help="shortcut for --format html")
    report.add_argument(
        "-o", "--out", type=pathlib.Path, default=None, metavar="FILE", help="write to FILE"
    )
    report.add_argument("--top", type=int, default=25, metavar="N", help="rows in the leaderboard")
    report.add_argument("--title", default="flaky-hunter report", help="report title")

    quarantine = sub.add_parser(
        "quarantine", help="write a pytest.ini that quarantines flaky tests"
    )
    common(quarantine)
    quarantine.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path("pytest.ini"),
        metavar="FILE",
        help="config file to create or update (default: pytest.ini)",
    )
    quarantine.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing file instead of merging into it",
    )
    quarantine.add_argument(
        "--dry-run", action="store_true", help="print the config, write nothing"
    )

    explain = sub.add_parser("explain", help="show the evidence behind one test verdict")
    explain.add_argument("test", metavar="TEST", help="test id or a unique fragment of it")
    common(explain, paths=False)
    explain.add_argument("--json", action="store_true", help="print machine-readable JSON")
    explain.add_argument("--md", action="store_true", help="print a Markdown block")

    baseline = sub.add_parser("baseline", help="create a baseline file from a results tree")
    common(baseline)
    baseline.add_argument(
        "--out", type=pathlib.Path, default=pathlib.Path("baseline.json"), metavar="FILE"
    )

    return parser


def _validate(args: argparse.Namespace) -> None:
    if not 0.0 <= float(args.threshold) <= 1.0:
        raise FlakyHunterError(f"--threshold must be between 0 and 1, got {args.threshold}")
    if args.min_runs < 1:
        raise FlakyHunterError(f"--min-runs must be at least 1, got {args.min_runs}")
    if getattr(args, "top", 1) < 1:
        raise FlakyHunterError(f"--top must be at least 1, got {args.top}")


def _run_analysis(args: argparse.Namespace) -> Analysis:
    raw_paths = getattr(args, "paths", None) or getattr(args, "results", None) or ["results"]
    paths = [pathlib.Path(p) for p in raw_paths]
    return analyse_paths(
        paths,
        min_runs=args.min_runs,
        threshold=args.threshold,
        baseline_file=args.baseline,
    )


def _write(text: str, out: pathlib.Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    sys.stderr.write(f"wrote {out} ({len(text.encode('utf-8'))} bytes)\n")


def _cmd_analyze(args: argparse.Namespace, painter: Painter) -> int:
    started = time.perf_counter()
    analysis = _run_analysis(args)
    elapsed = (time.perf_counter() - started) * 1000
    if args.save_baseline:
        from .analysis import save_baseline

        payload = save_baseline(analysis, args.save_baseline)
        sys.stderr.write(f"saved baseline {args.save_baseline} ({len(payload['tests'])} tests)\n")
    if args.json:
        sys.stdout.write(render_json(analysis))
    else:
        sys.stdout.write(render_analyze(analysis, painter, elapsed_ms=elapsed))
    if args.fail_on_new and analysis.baseline_diff:
        diff = analysis.baseline_diff
        if diff["newly_flaky"] or diff["worsened"]:
            return EXIT_FINDINGS
    return EXIT_FINDINGS if analysis.flaky else EXIT_OK


def _cmd_report(args: argparse.Namespace, painter: Painter) -> int:
    analysis = _run_analysis(args)
    fmt = "html" if args.html else args.format
    if fmt == "md" or fmt == "markdown":
        text = render_markdown(analysis, top=args.top, title=args.title)
    elif fmt == "json":
        text = render_json(analysis)
    elif fmt == "html":
        text = render_html(analysis, limit=args.top, title=args.title)
    else:
        text = render_analyze(analysis, painter)
        if args.out is None:
            sys.stdout.write(text)
            return EXIT_FINDINGS if analysis.flaky else EXIT_OK
    _write(text, args.out)
    return EXIT_FINDINGS if analysis.flaky else EXIT_OK


def _cmd_quarantine(args: argparse.Namespace, painter: Painter) -> int:
    analysis = _run_analysis(args)
    selected = quarantine_plan(analysis, args.threshold)
    if args.dry_run:
        from .quarantine import render_ini

        sys.stdout.write(render_ini(selected))
        return EXIT_FINDINGS if selected.tests else EXIT_OK
    path, created = write_ini(args.out, selected, force=args.force)
    for line in render_quarantine(selected, path, created):
        sys.stdout.write(painter(line, WHITE) + "\n")
    if args.baseline is None and selected.tests:
        sys.stdout.write(
            painter(
                "  tip: rerun with --baseline baseline.json to see what changed since last week",
                GREY,
            )
            + "\n"
        )
    return EXIT_FINDINGS if selected.tests else EXIT_OK


def _cmd_explain(args: argparse.Namespace, painter: Painter) -> int:
    analysis = _run_analysis(args)
    known = [item.test_id for item in analysis.stats]
    matches = parse_test_selector(args.test, known)
    if not matches:
        closest = _suggest(args.test, known)
        hint = f" Did you mean: {closest[0]}?" if closest else ""
        raise FlakyHunterError(f"no test matches {args.test!r}.{hint}")
    if len(matches) > 1:
        listing = "\n  ".join(matches[:8])
        raise FlakyHunterError(
            f"{args.test!r} matches {len(matches)} tests; be more specific:\n  {listing}"
        )
    item = analysis.by_id(matches[0])
    if item is None:
        raise FlakyHunterError(f"no statistics for {matches[0]!r}")
    if args.json:
        from .report_json import analysis_payload

        payload = analysis_payload(analysis)
        entry = next(t for t in payload["tests"] if t["test_id"] == item.test_id)
        import json

        payload["test"] = entry
        payload["peers"] = [
            pair
            for pair in payload["correlated"]
            if pair["left"] == item.test_id or pair["right"] == item.test_id
        ]
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    elif args.md:
        sys.stdout.write(render_explain_markdown(item))
    else:
        for line in render_explain(analysis, item, painter):
            sys.stdout.write(line + "\n")
    return EXIT_FINDINGS if item.verdict == "flaky" else EXIT_OK


def _cmd_baseline(args: argparse.Namespace, painter: Painter) -> int:
    from .analysis import save_baseline

    analysis = _run_analysis(args)
    payload = save_baseline(analysis, args.out)
    sys.stdout.write(
        painter(f"  wrote {args.out}", BOLD, WHITE)
        + painter(f"  {len(payload['tests'])} tests  {len(analysis.runs)} runs", GREY)
        + "\n"
    )
    return EXIT_OK


def _suggest(selector: str, known: Sequence[str]) -> list[str]:
    """Cheap fuzzy suggestion: tests sharing the most characters with the input."""
    needle = selector.lower().replace("::", "").replace("/", "")
    scored: list[tuple[int, str]] = []
    for test_id in known:
        haystack = test_id.lower().replace("::", "").replace("/", "")
        score = sum(1 for char in set(needle) if char in haystack)
        scored.append((score, test_id))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [test_id for score, test_id in scored[:3] if score > 0]


def _print_summary(analysis: Analysis, painter: Painter, elapsed_ms: float) -> None:
    flaky = analysis.flaky
    colour = YELLOW if flaky else GREEN
    sys.stdout.write(
        painter(
            f"  {len(analysis.stats)} tests over {len(analysis.runs)} runs: "
            f"{len(flaky)} flaky ({pct(len(flaky) / max(len(analysis.stats), 1))})",
            BOLD,
            colour,
        )
        + painter(f"  [{elapsed_ms:.0f} ms]", GREY)
        + "\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    painter = Painter(colour_enabled(args.color))
    started = time.perf_counter()
    try:
        _validate(args)
        if args.command == "analyze":
            return _cmd_analyze(args, painter)
        if args.command == "report":
            return _cmd_report(args, painter)
        if args.command == "quarantine":
            return _cmd_quarantine(args, painter)
        if args.command == "explain":
            return _cmd_explain(args, painter)
        if args.command == "baseline":
            return _cmd_baseline(args, painter)
        parser.error(f"unknown command {args.command!r}")
    except FlakyHunterError as exc:
        sys.stderr.write(
            painter("flaky-hunter: " + str(exc).replace("\n", "\n              "), BOLD, RED) + "\n"
        )
        return EXIT_USAGE
    except KeyboardInterrupt:
        sys.stderr.write("flaky-hunter: interrupted\n")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    finally:
        elapsed = (time.perf_counter() - started) * 1000
        if args.command in ("analyze", "report", "quarantine", "explain", "baseline"):
            import os

            if os.environ.get("FLAKY_HUNTER_TRACE"):
                from .formatting import strip_ansi

                sys.stderr.write(strip_ansi(f"[flaky-hunter] {elapsed:.1f} ms\n"))
