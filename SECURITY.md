# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | yes |

## What flaky-hunter touches

flaky-hunter reads local test-result files and writes reports, baselines and
pytest configuration. It makes **no network requests**, executes **no test
code**, and imports **no third-party packages** at runtime.

## Reporting a vulnerability

Please open a private security advisory on GitHub
(https://github.com/kele-tao/flaky-hunter/security/advisories/new) rather than a
public issue. Include the version, a minimal input file and the command used.

You can expect an acknowledgement within 72 hours and a fix or mitigation within
14 days for issues that affect parsing of untrusted input files.

## Parsing untrusted input

CI result files are data, not code. flaky-hunter parses them with
`xml.etree.ElementTree` (no DTD or external entity resolution, as required by
the standard library's default parser) and `json`, caps stored error messages at
a few hundred characters, and never evaluates anything it reads.
