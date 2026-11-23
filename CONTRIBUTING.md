# Contributing

Thanks for taking a look. flaky-hunter is deliberately small: a pure-standard-library
Python package with no network access and no third-party runtime dependencies.
Keeping it that way is part of the product.

## Development setup

```bash
git clone https://github.com/kele-tao/flaky-hunter
cd flaky-hunter
python -m venv .venv
# Windows: .venv\Scripts\activate   |   POSIX: source .venv/bin/activate
pip install -e ".[dev]"
```

## The three commands that must pass before a pull request

```bash
ruff check .
ruff format --check .
pytest -q
```

CI runs the same three commands on Python 3.10, 3.11 and 3.12, plus a CLI smoke
test.

## What a good change looks like

- **Parsers** come with a fixture in `tests/` built from a real tool's output, not
  from imagination. If you support a new format, say which tool and version
  produced it in the docstring.
- **Statistics** changes come with a unit test that states the expected number.
  If you change the score formula, update the "How it works" section of the
  README and the explanation printed by `flaky-hunter explain` in the same commit.
- **Report** changes must keep output deterministic: no timestamps in parsed
  output, no dictionary iteration order leaking into the result.
- **CLI** changes must keep the rule that user errors print one actionable line
  to stderr and exit 2, never a traceback.

## Adding a result format

1. Add a `parse_<format>` function to the appropriate module (`junit.py`,
   `pytest_json.py` or `logs.py`) returning a `Run`.
2. Dispatch to it from `loader._parse_file` based on suffix and content sniffing.
3. Add happy-path, malformed-input and empty-input tests.
4. Add one line to the supported-formats table in the README.

## Regenerating the example corpus

The committed corpus under `examples/results/` is generated, never edited by hand:

```bash
python benchmarks/gen_results.py --out examples/results
python benchmarks/evaluate.py
```

The generator is seeded, so the checked-in files are reproducible byte for byte.
If you change a test in `benchmarks/gen_results.py`, also update
`examples/ground_truth.json` (both are written by the same script) and refresh the
precision/recall numbers quoted in the README.

## Reporting bugs

Use the issue template and include the exact command, the version and a minimal
result file. Please redact hostnames and tokens; `flaky-hunter explain` prints
failure messages almost verbatim.
