# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-23

First public release.

### Added

- **Ingest**: JUnit XML (pytest, jest-junit, go-junit-report, maven surefire),
  pytest-json-report JSON, generic JSON arrays and a line-oriented fallback
  parser for raw CI logs (pytest `-v`, `go test -v`, surefire text).
- **Statistics**: per-test histories ordered by run timestamp, retry collapsing
  inside one run, failure rate, a 95% Wilson lower bound, a two-state Markov
  chain (P(pass->fail), P(fail->pass)) and a flakiness score that multiplies
  the confidence bound by the flip rate and shrinks small samples to zero.
- **Ranking**: impact = score x average duration x failures, so a slow timeout
  outranks a 20 ms assertion that flakes equally often.
- **Correlations**: error-signature clustering after normalising numbers,
  host:port pairs, paths, UUIDs and timings, plus Jaccard overlap between
  failure run-sets and union-find grouping.
- **Reports**: terminal leaderboard, `--format md`, `--format json` and a
  self-contained `--format html` with inline SVG sparklines.
- **Quarantine**: `flaky-hunter quarantine` writes or merges a `pytest.ini`
  carrying a `quarantine` marker and `addopts = -m "not quarantine"`.
- **Baselines**: `flaky-hunter baseline`, `--baseline FILE`, `--save-baseline`
  and `--fail-on-new` for CI gates.
- **`explain`**: the evidence behind one verdict, including the arithmetic and
  the correlated tests that probably share its root cause.
- **Benchmarks**: a deterministic generator, `benchmarks/run.py` and
  `benchmarks/evaluate.py`, which scores the tool against committed ground
  truth (precision 0.75, recall 1.00 on the bundled corpus).

### Notes

- Zero runtime dependencies; Python 3.10+.
- Exit codes: 0 clean, 1 flaky tests found, 2 usage or input error.
