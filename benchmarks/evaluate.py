"""Score flaky-hunter against the committed ground truth.

    python benchmarks/evaluate.py

Prints precision, recall, the identity of every false positive / false negative
and a threshold sweep. The README quotes the numbers printed by this script;
nothing is hand-written.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from flaky_hunter.analysis import analyse_paths  # noqa: E402

SWEEP = (0.10, 0.15, 0.20, 0.25, 0.30)


def _score(flagged: set[str], truth: set[str]) -> dict:
    tp = sorted(flagged & truth)
    fp = sorted(flagged - truth)
    fn = sorted(truth - flagged)
    return {
        "flagged": len(flagged),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(len(tp) / len(flagged), 3) if flagged else 0.0,
        "recall": round(len(tp) / len(truth), 3) if truth else 0.0,
    }


def main() -> int:
    truth = json.loads((ROOT / "examples" / "ground_truth.json").read_text(encoding="utf-8"))
    labels = truth["labels"]
    actually_flaky = set(labels["truly_flaky"])
    analysis = analyse_paths([ROOT / "examples" / "results"])
    flagged = {item.test_id for item in analysis.flaky}
    primary = _score(flagged, actually_flaky)

    sweep = []
    for threshold in SWEEP:
        chosen = {
            item.test_id
            for item in analysis.stats
            if item.score >= threshold and item.passes and item.failures
        }
        entry = _score(chosen, actually_flaky)
        sweep.append(
            {
                "threshold": threshold,
                "flagged": entry["flagged"],
                "precision": entry["precision"],
                "recall": entry["recall"],
                "false_positive": entry["false_positive"],
            }
        )

    top_impact = [item.test_id for item in analysis.stats[:4]]
    outage_test = labels["explained_by_shared_outage"][0]
    flaky_cache_test = labels["truly_flaky"][2]
    pair = next(
        (
            p
            for p in analysis.correlations.pairs
            if {p.left, p.right} == {outage_test, flaky_cache_test}
        ),
        None,
    )
    report = {
        "runs": truth["runs"],
        "tests": truth["tests"],
        "threshold": analysis.threshold,
        "primary": primary,
        "threshold_sweep": sweep,
        "top4_by_impact": top_impact,
        "all_truly_flaky_in_top4": actually_flaky <= set(top_impact),
        "regressed_detected": [
            item.test_id for item in analysis.stats if item.verdict == "regressed"
        ],
        "fixed_detected": [item.test_id for item in analysis.stats if item.verdict == "fixed"],
        "signature_clusters": [
            {"size": c.size, "failures": c.failures, "signature": c.signature}
            for c in analysis.correlations.clusters
        ],
        "explains_false_positive": (
            {
                "pair": [pair.left, pair.right],
                "jaccard": pair.jaccard,
                "shared_runs": len(pair.shared_runs),
            }
            if pair
            else None
        ),
    }
    out = ROOT / "benchmarks" / "evaluation.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"corpus: {report['runs']} runs x {report['tests']} tests, threshold {report['threshold']}"
    )
    print(
        f"flagged {primary['flagged']}  precision {primary['precision']:.2f}  "
        f"recall {primary['recall']:.2f}  false positives {len(primary['false_positive'])}"
    )
    for test_id in primary["true_positive"]:
        print("  true positive   " + test_id)
    for test_id in primary["false_positive"]:
        print("  false positive  " + test_id)
    for test_id in primary["false_negative"]:
        print("  false negative  " + test_id)
    print("  top 4 by impact:")
    for rank, test_id in enumerate(top_impact, 1):
        print(f"    {rank}. {test_id}")
    print("  threshold sweep:")
    for row in sweep:
        print(
            f"    {row['threshold']:.2f}  flagged {row['flagged']}  "
            f"precision {row['precision']:.2f}  recall {row['recall']:.2f}"
        )
    pair_info = report["explains_false_positive"]
    if pair_info:
        print("  the false positive fails in exactly the same runs as a true flake:")
        print(f"    jaccard {pair_info['jaccard']:.2f} over {pair_info['shared_runs']} shared runs")
        print(f"    {pair_info['pair'][0]}")
        print(f"    {pair_info['pair'][1]}")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
