"""Benchmark flaky-hunter against a generated corpus.

    python benchmarks/run.py            # full run, writes benchmarks/results.json + RESULTS.md
    python benchmarks/run.py --quick    # single small measurement, used by the test suite

Every number in the README benchmark table is produced here. The generator is
deterministic, so re-running on the same machine reproduces the same results
modulo wall-clock noise.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import platform
import statistics
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from gen_results import generate, generate_scaled  # noqa: E402

from flaky_hunter.analysis import analyse_paths  # noqa: E402
from flaky_hunter.report_html import render_html  # noqa: E402
from flaky_hunter.report_json import render_json  # noqa: E402
from flaky_hunter.report_md import render_markdown  # noqa: E402


def _time(fn, repeats: int = 3) -> tuple[float, float]:
    """Return (best seconds, median seconds) over a few warm runs."""
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    return min(samples), statistics.median(samples)


def _measure(corpus_dir: pathlib.Path) -> dict:
    analysis = analyse_paths([corpus_dir])
    results = sum(len(run.cases) for run in analysis.runs)
    best, median = _time(lambda: analyse_paths([corpus_dir]))
    throughput = results / best if best else 0.0
    report_times = {
        "json": _time(lambda: render_json(analysis), repeats=2)[0],
        "markdown": _time(lambda: render_markdown(analysis), repeats=2)[0],
        "html": _time(lambda: render_html(analysis), repeats=2)[0],
    }
    return {
        "runs": len(analysis.runs),
        "results": results,
        "tests": len(analysis.stats),
        "flaky": len(analysis.flaky),
        "parse_and_analyse_seconds": round(best, 4),
        "median_seconds": round(median, 4),
        "results_per_second": int(throughput),
        "report_seconds": {key: round(value, 4) for key, value in report_times.items()},
    }


def _log_measure(result_lines: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "big.log"
        size = generate_scaled(path, result_lines)
        best, median = _time(lambda: analyse_paths([path]), repeats=2)
        analysis = analyse_paths([path])
        return {
            "result_lines": result_lines,
            "file_mb": round(size / (1024 * 1024), 2),
            "tests": len(analysis.stats),
            "parse_and_analyse_seconds": round(best, 4),
            "median_seconds": round(median, 4),
            "results_per_second": int(result_lines / best) if best else 0,
        }


def _markdown(payload: dict) -> str:
    rows = payload["corpora"]
    lines = [
        "# flaky-hunter benchmarks",
        "",
        "Produced by "
        + chr(96)
        + "python benchmarks/run.py"
        + chr(96)
        + " on "
        + payload["environment"]["platform"]
        + " / Python "
        + payload["environment"]["python"]
        + "; generated "
        + payload["generated_at"]
        + ".",
        "",
        "| corpus | runs | results | tests | flaky | analyse (s) | results/s |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| "
            + row["name"]
            + " | "
            + str(row["runs"])
            + " | "
            + f"{row['results']:,}"
            + " | "
            + str(row["tests"])
            + " | "
            + str(row["flaky"])
            + " | "
            + f"{row['parse_and_analyse_seconds']:.4f}"
            + " | "
            + f"{row['results_per_second']:,}"
            + " |"
        )
    lines.extend(
        [
            "",
            "## Raw CI log fallback",
            "",
            "| result lines | file (MB) | tests | analyse (s) | results/s |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload["logs"]:
        lines.append(
            "| "
            + f"{row['result_lines']:,}"
            + " | "
            + f"{row['file_mb']:.1f}"
            + " | "
            + str(row["tests"])
            + " | "
            + f"{row['parse_and_analyse_seconds']:.4f}"
            + " | "
            + f"{row['results_per_second']:,}"
            + " |"
        )
    reports = payload["corpora"][0]["report_seconds"]
    lines.extend(
        [
            "",
            "## Report rendering (25-test example corpus)",
            "",
            "| format | seconds |",
            "| --- | ---: |",
            "| JSON | " + f"{reports['json']:.4f}" + " |",
            "| Markdown | " + f"{reports['markdown']:.4f}" + " |",
            "| HTML | " + f"{reports['html']:.4f}" + " |",
            "",
            "Analyse time includes reading the files from disk, parsing, scoring, "
            "signature clustering and correlation detection. Reports render from an "
            "already-computed analysis.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark flaky-hunter.")
    parser.add_argument("--quick", action="store_true", help="one small measurement only")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = pathlib.Path(tmp)
        corpora = []
        if args.quick:
            generate(tmpdir / "small", runs=10)
            entry = _measure(tmpdir / "small")
            entry["name"] = "quick-10x25"
            corpora.append(entry)
            logs = []
        else:
            for runs, label in (
                (40, "example-40x25"),
                (200, "medium-200x25"),
                (1000, "large-1000x25"),
            ):
                generate(tmpdir / f"r{runs}", runs=runs)
                entry = _measure(tmpdir / f"r{runs}")
                entry["name"] = label
                corpora.append(entry)
            logs = [_log_measure(50_000), _log_measure(100_000)]
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "environment": {
                "platform": platform.system() + " " + platform.release(),
                "python": platform.python_version(),
                "machine": platform.machine(),
            },
            "corpora": corpora,
            "logs": logs,
            "wall_seconds": round(time.perf_counter() - started, 2),
        }
    out = ROOT / "benchmarks" / "results.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if not args.quick:
        md = ROOT / "benchmarks" / "RESULTS.md"
        md.write_text(_markdown(payload), encoding="utf-8")
        print("wrote " + str(out.relative_to(ROOT)) + " and benchmarks/RESULTS.md")
    else:
        print("wrote " + str(out.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
