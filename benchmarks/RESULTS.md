# flaky-hunter benchmarks

Produced by `python benchmarks/run.py` on Windows 11 / Python 3.12.10; generated 2026-11-23T08:05:10Z.

| corpus | runs | results | tests | flaky | analyse (s) | results/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| example-40x25 | 40 | 1,000 | 25 | 4 | 0.0324 | 30,875 |
| medium-200x25 | 200 | 5,000 | 25 | 4 | 0.1784 | 28,023 |
| large-1000x25 | 1000 | 25,000 | 25 | 4 | 1.3599 | 18,383 |

## Raw CI log fallback

| result lines | file (MB) | tests | analyse (s) | results/s |
| ---: | ---: | ---: | ---: | ---: |
| 50,000 | 2.6 | 120 | 0.7015 | 71,272 |
| 100,000 | 5.2 | 120 | 1.0618 | 94,178 |

## Report rendering (25-test example corpus)

| format | seconds |
| --- | ---: |
| JSON | 0.0039 |
| Markdown | 0.0003 |
| HTML | 0.0011 |

Analyse time includes reading the files from disk, parsing, scoring, signature clustering and correlation detection. Reports render from an already-computed analysis.
