"""Generate deterministic synthetic CI results with documented ground truth.

The example corpus in examples/results/ is produced by this script, so the
precision/recall numbers quoted in the README can be reproduced by anyone:

    python benchmarks/gen_results.py --out examples/results
    python benchmarks/evaluate.py

Every test below has a known ground-truth role: three genuinely flaky tests,
one regression, one fixed test, one test whose failures are fully explained by a
shared outage, one single-failure test and stable tests.

The "shared outage" test is deliberately indistinguishable from a real flake
using per-test statistics alone: it fails in exactly the runs where the cache
test fails. flaky-hunter therefore quarantines it, and the correlated-failure
section is what tells the reader why that is a false positive.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import xml.etree.ElementTree as ET

START = "2026-01-05T09:00:00Z"
SEED = 20260105

TIMEOUT = "socket.timeout: connection to api.internal:8443/v2/items timed out after 30.0s"
EVICTION = "KeyError: 'session:{session}'"
EXPORT = "ValueError: unknown column 'total' in row {row}"
TOKEN = "AssertionError: token expired at 2025-12-31T23:59:59Z"
FLUSH = "ConnectionRefusedError: [Errno 111] Connection refused 10.4.2.17:5432"

TRULY_FLAKY = (
    "tests/test_api.py::test_fetch_times_out",
    "tests/test_api.py::test_retry_after_timeout",
    "tests/test_cache.py::test_eviction_race",
)
REGRESSED = ("tests/test_report.py::test_export_csv",)
FIXED = ("tests/test_auth.py::test_legacy_login",)
SHARED_OUTAGE = ("tests/test_metrics.py::test_flush_metrics",)
SINGLE_FAILURE = ("tests/test_metrics.py::test_gauge_reset",)


class Spec:
    """One synthetic test: file, name, base duration and an outcome rule."""

    def __init__(self, file: str, name: str, duration: float, rule, message: str = "") -> None:
        self.file = file
        self.name = name
        self.duration = duration
        self.rule = rule
        self.message = message

    @property
    def test_id(self) -> str:
        return self.file + "::" + self.name


def _p(rate: float):
    """Fail with probability rate, using the shared deterministic RNG."""

    def rule(run: int, rng: random.Random) -> str:
        return "fail" if rng.random() < rate else "pass"

    return rule


def _always_pass(run: int) -> str:
    return "pass"


def _window(start: int, end: int, outcome: str):
    def rule(run: int) -> str:
        return outcome if start <= run <= end else "pass"

    return rule


def _legacy_rule(run: int) -> str:
    """Fails early in the window, then a fix landed: verdict should be fixed."""
    return "fail" if run in (0, 1, 2, 3, 5, 6) else "pass"


def _single_failure(run: int) -> str:
    return "fail" if run == 17 else "pass"


def _skip_rule(run: int) -> str:
    return "skip" if run in (7, 8) else "pass"


def build_specs() -> list[Spec]:
    """The 25-test corpus, in a fixed order."""
    return [
        Spec("tests/test_api.py", "test_fetch_times_out", 31.2, _p(0.40), TIMEOUT),
        Spec("tests/test_api.py", "test_retry_after_timeout", 3.4, _p(0.35), TIMEOUT),
        Spec("tests/test_api.py", "test_health_ok", 0.04, _always_pass),
        Spec("tests/test_api.py", "test_pagination", 0.12, _always_pass),
        Spec("tests/test_api.py", "test_rate_limit", 0.21, _always_pass),
        Spec("tests/test_api.py", "test_upload_chunked", 1.31, _always_pass),
        Spec(
            "tests/test_cache.py",
            "test_eviction_race",
            0.42,
            _p(0.32),
            EVICTION.format(session=4711),
        ),
        Spec("tests/test_cache.py", "test_get_miss", 0.01, _always_pass),
        Spec("tests/test_cache.py", "test_set_ttl", 0.02, _always_pass),
        Spec("tests/test_cache.py", "test_lru_order", 0.03, _always_pass),
        Spec(
            "tests/test_report.py",
            "test_export_csv",
            0.87,
            _window(30, 39, "fail"),
            EXPORT.format(row=12),
        ),
        Spec("tests/test_report.py", "test_export_pdf", 1.42, _skip_rule),
        Spec("tests/test_report.py", "test_render_table", 0.05, _always_pass),
        Spec("tests/test_report.py", "test_column_alias", 0.06, _always_pass),
        Spec("tests/test_auth.py", "test_legacy_login", 0.34, _legacy_rule, TOKEN),
        Spec("tests/test_auth.py", "test_login_success", 0.09, _always_pass),
        Spec("tests/test_auth.py", "test_login_bad_password", 0.08, _always_pass),
        Spec("tests/test_auth.py", "test_token_refresh", 0.11, _always_pass),
        Spec("tests/test_auth.py", "test_logout", 0.05, _always_pass),
        Spec("tests/test_metrics.py", "test_flush_metrics", 0.91, _flush_rule, FLUSH),
        Spec("tests/test_metrics.py", "test_counter_inc", 0.01, _always_pass),
        Spec("tests/test_metrics.py", "test_histogram_buckets", 0.02, _always_pass),
        Spec("tests/test_metrics.py", "test_gauge_reset", 0.02, _single_failure),
        Spec("tests/test_db.py", "test_migration_idempotent", 2.61, _always_pass),
        Spec("tests/test_db.py", "test_transaction_rollback", 0.44, _always_pass),
    ]


def _flush_rule(run: int, ctx: dict) -> str:
    """Fails exactly when the cache eviction test fails: one shared outage."""
    return "fail" if ctx["eviction_failed"] else "pass"


def generate(
    out_dir: pathlib.Path, runs: int = 40, seed: int = SEED, write_truth: bool = True
) -> dict:
    """Write one JUnit XML file per run and return the ground-truth payload."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("run-*.xml"):
        stale.unlink()
    specs = build_specs()
    rng = random.Random(seed)
    for run in range(runs):
        eviction_failed = False
        suite = ET.Element("testsuite", {"name": "pytest", "tests": "0", "failures": "0"})
        failures = 0
        cases: list[ET.Element] = []
        for spec in specs:
            if spec.name == "test_flush_metrics":
                outcome = _flush_rule(run, {"eviction_failed": eviction_failed})
            else:
                try:
                    outcome = spec.rule(run, rng)
                except TypeError:
                    outcome = spec.rule(run)
            if spec.name == "test_eviction_race" and outcome != "pass":
                eviction_failed = True
            if outcome != "pass":
                failures += 1
                if spec.name in ("test_fetch_times_out", "test_retry_after_timeout"):
                    duration = 30.0 + rng.random()
                else:
                    duration = spec.duration * (1.0 + rng.random() * 0.4)
            else:
                duration = spec.duration * (0.9 + rng.random() * 0.2)
            case = ET.SubElement(
                suite,
                "testcase",
                {
                    "classname": spec.file.replace("/", ".")[:-3],
                    "name": spec.name,
                    "time": f"{duration:.3f}",
                },
            )
            if outcome == "fail":
                message = spec.message.replace("{session}", str(4000 + len(cases) * 7)).replace(
                    "{row}", str(10 + len(cases))
                )
                failure = ET.SubElement(case, "failure", {"message": message})
                failure.text = message + "\n  (see logs/ci-" + str(run + 1) + ".txt)"
            elif outcome == "skip":
                ET.SubElement(case, "skipped", {"message": "requires pdf extras"})
            cases.append(case)
        suite.set("tests", str(len(cases)))
        suite.set("failures", str(failures))
        suite.set("timestamp", _timestamp(run))
        tree = ET.ElementTree(suite)
        ET.indent(tree, space="  ")
        tree.write(out_dir / f"run-{run + 1:04d}.xml", encoding="utf-8", xml_declaration=True)
    truth = ground_truth(runs)
    if write_truth:
        truth_path = out_dir.parent / "ground_truth.json"
        truth_path.write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    return truth


def _timestamp(run: int) -> str:
    day = run % 28 + 1
    month = 1 + (run // 28)
    return f"2026-{month:02d}-{day:02d}T09:{run % 60:02d}:00Z"


def ground_truth(runs: int = 40) -> dict:
    """The committed labels used to score flaky-hunter honestly."""
    specs = build_specs()
    labelled = (
        set(TRULY_FLAKY) | set(REGRESSED) | set(FIXED) | set(SHARED_OUTAGE) | set(SINGLE_FAILURE)
    )
    return {
        "generator": "benchmarks/gen_results.py",
        "seed": SEED,
        "runs": runs,
        "tests": len(specs),
        "labels": {
            "truly_flaky": list(TRULY_FLAKY),
            "regressed": list(REGRESSED),
            "fixed": list(FIXED),
            "explained_by_shared_outage": list(SHARED_OUTAGE),
            "single_failure": list(SINGLE_FAILURE),
            "stable": [spec.test_id for spec in specs if spec.test_id not in labelled],
        },
        "notes": (
            "test_flush_metrics fails in exactly the runs where test_eviction_race fails "
            "(jaccard 1.00). It is labelled explained_by_shared_outage, so a quarantine list "
            "that includes it is a false positive: the tool cannot tell a symptom from an "
            "independent flake using per-test statistics, which is why the correlated-failure "
            "section exists."
        ),
    }


def generate_log_runs(out_dir: pathlib.Path, runs: int = 10, seed: int = SEED) -> int:
    """Write raw pytest -v style logs (one file per run) for the fallback parser demo.

    The same 25-test corpus and the same outcome rules are used, so the log demo
    and the JUnit demo describe the same test suite in two different formats.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("ci-*.log"):
        stale.unlink()
    specs = build_specs()
    rng = random.Random(seed + 1)
    written = 0
    for run in range(runs):
        eviction_failed = False
        lines = [
            "$ pytest -v --tb=line",
            "platform win32 -- Python 3.12.10 -- pytest-8.3.4",
            "collected " + str(len(specs)) + " items",
            "",
        ]
        failed = 0
        for position, spec in enumerate(specs, 1):
            if spec.name == "test_flush_metrics":
                outcome = _flush_rule(run, {"eviction_failed": eviction_failed})
            else:
                try:
                    outcome = spec.rule(run, rng)
                except TypeError:
                    outcome = spec.rule(run)
            if spec.name == "test_eviction_race" and outcome != "pass":
                eviction_failed = True
            nodeid = spec.test_id
            percent = int(100 * position / len(specs))
            if outcome == "fail":
                failed += 1
                lines.append(f"[gw0] [{percent:3d}%] FAILED {nodeid} - {spec.message}")
            elif outcome == "skip":
                lines.append(f"[gw0] [{percent:3d}%] SKIPPED {nodeid}")
            else:
                lines.append(f"[gw0] [{percent:3d}%] PASSED {nodeid}")
            written += 1
        lines.append("")
        lines.append(f"===== {failed} failed, {len(specs) - failed} passed in 12.4s =====")
        path = out_dir / f"ci-{run + 1:03d}.log"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def generate_scaled(path: pathlib.Path, target_results: int, seed: int = 7) -> int:
    """Write a large raw CI log used by benchmarks/run.py (about target_results lines)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    tests = [f"tests/test_mod{i // 12}.py::test_case_{i}" for i in range(120)]
    lines = ["# CI log generated by benchmarks/gen_results.py", ""]
    written = 0
    while written < target_results:
        for nodeid in tests:
            roll = rng.random()
            if roll < 0.02:
                status = "FAILED"
                suffix = " - AssertionError: expected 3 but got 4"
            elif roll < 0.03:
                status = "SKIPPED"
                suffix = ""
            else:
                status = "PASSED"
                suffix = ""
            percent = (written * 37) % 100
            lines.append(f"[gw0] [{percent:3d}%] {status} {nodeid}{suffix}")
            written += 1
            if written >= target_results:
                break
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.stat().st_size


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic test results.")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("examples/results"))
    parser.add_argument("--runs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--scale", type=int, default=0, help="write a large log with N result lines"
    )
    parser.add_argument(
        "--scale-out", type=pathlib.Path, default=pathlib.Path("benchmarks/big.log")
    )
    parser.add_argument(
        "--log-out",
        type=pathlib.Path,
        default=None,
        help="also write raw pytest -v logs to this directory",
    )
    parser.add_argument("--log-runs", type=int, default=10)
    args = parser.parse_args(argv)
    truth = generate(args.out, runs=args.runs, seed=args.seed)
    print(
        f"wrote {args.runs} runs x {truth['tests']} tests to {args.out} "
        f"({len(list(args.out.glob('run-*.xml')))} files)"
    )
    if args.log_out is not None:
        written = generate_log_runs(args.log_out, runs=args.log_runs, seed=args.seed)
        print(f"wrote {args.log_runs} raw logs ({written} test lines) to {args.log_out}")
    if args.scale:
        size = generate_scaled(args.scale_out, args.scale, seed=args.seed)
        print(f"wrote {args.scale} result lines to {args.scale_out} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
