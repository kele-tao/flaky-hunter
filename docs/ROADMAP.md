# Roadmap

flaky-hunter 1.0 is deliberately narrow. This page records what is *not* in the
release, so nobody has to guess whether a missing feature is an oversight.

## Cut from 1.0 on purpose

| Idea | Why it is not here |
| --- | --- |
| Automatic bisection of the first failing commit | Needs repository access, a build environment and network; it is a different product. |
| Live GitHub Actions / Buildkite / GitLab API ingestion | Would add an HTTP client and credentials to a tool whose selling point is that it runs offline on a directory of files. Export the artifacts and point flaky-hunter at them. |
| Test-level rerun orchestration (`--rerun-failed 5`) | flaky-hunter only reads results. Rerunning is the CI system's job; the tool tells you *what* to rerun. |
| ML classification of flaky vs broken | A two-parameter statistical model is auditable and explains itself in `explain`. A classifier that cannot justify a verdict is worse than no verdict. |
| Coverage-style historical database (SQLite) | The input is already a directory of runs. Adding state makes the tool harder to run in CI and harder to test. |
| Plotly/D3 interactive charts | Would break the "one self-contained HTML file, works offline" property. Inline SVG sparklines cover the need. |

## Next steps, in priority order

1. **Duration-aware flaky detection.** A test that passes slowly and fails when
   it crosses a timeout is flaky for a reason; today we only use duration for
   the impact ranking. A second score that correlates duration with outcome
   would name the cause, not just the test.
2. **Signature-aware quarantine.** When 14 tests share one signature, quarantine
   the *cluster* and annotate all 14 with a reference to the one bug, instead of
   writing 14 independent entries.
3. **Baseline storage as a git-friendly summary.** `baseline.json` grows with the
   test suite. A compact, diffable form (one line per test, sorted) would make
   baseline review possible in a pull request.
4. **`--format sarif`** so flaky findings appear in GitHub's code scanning UI
   next to ordinary static-analysis results.
5. **Parameter sweep helper.** `benchmarks/evaluate.py` already prints a threshold
   sweep. Exposing it as `flaky-hunter tune` would let a team pick a threshold
   from its own history instead of copying ours.

## Known limitations of the current release

- With fewer than ~10 runs the score is deliberately pessimistic (a shrink factor
  ramps it up). A test that never ran twice cannot be shown to be flaky.
- Correlated-failure detection requires at least two shared failing runs, so a
  shared fixture that fails once is reported as a single failure, not a cluster.
- The raw-log fallback understands the default verbose output of pytest, go test
  and maven surefire. Custom reporters need to emit JUnit XML or pytest JSON.
- Windows path separators in JUnit `classname` attributes are normalised, but a
  test that is renamed between runs is treated as a new test (by design).
