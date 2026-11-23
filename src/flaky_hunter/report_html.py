"""Self-contained HTML report: one file, no network, inline SVG sparklines."""

from __future__ import annotations

import html
import json

from .analysis import Analysis
from .formatting import (
    human_count,
    human_duration,
    human_duration_or_na,
    pct,
    svg_sparkline,
)

CSS = """
:root{--bg:#0b0f17;--panel:#121826;--panel2:#0f1521;--line:#1f2937;--text:#e5e7eb;--muted:#94a3b8;
--green:#4ade80;--red:#f87171;--amber:#fbbf24;--blue:#60a5fa;--violet:#a78bfa}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:36px 28px 64px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}
h1{font-size:26px;margin:0;letter-spacing:-.4px}
.sub{color:var(--muted);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
gap:12px;margin:22px 0 26px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.09em}
.card .v{font-size:24px;font-weight:650;margin-top:4px;font-variant-numeric:tabular-nums}
.card.warn .v{color:var(--amber)}.card.bad .v{color:var(--red)}.card.good .v{color:var(--green)}
h2{font-size:15px;letter-spacing:.02em;text-transform:uppercase;color:var(--muted);
margin:34px 0 10px;font-weight:600}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);
border-radius:12px;overflow:hidden;font-variant-numeric:tabular-nums}
th{text-align:left;font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
padding:9px 12px;background:var(--panel2);border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 12px;border-bottom:1px solid #16202f;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#141c2b}
td.num,th.num{text-align:right}
.id{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12.5px;color:#cbd5e1}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;
letter-spacing:.03em;border:1px solid transparent}
.b-flaky{color:#111;background:var(--amber)}
.b-broken,.b-regressed{color:#fecaca;background:#7f1d1d;border-color:#b91c1c}
.b-fixed{color:#052e16;background:var(--green)}
.b-stable{color:#bbf7d0;background:#14532d}
.b-single-failure,.b-unstable{color:#fde68a;background:#422006;border-color:#a16207}
.b-skipped,.b-no-data{color:#cbd5e1;background:#1e293b}
.spark{display:block}
td.score{white-space:nowrap;min-width:84px}
.bar{height:5px;background:#1e293b;border-radius:4px;overflow:hidden;width:64px;margin:3px 0 0 auto}
.bar>span{display:block;height:100%;background:linear-gradient(90deg,#fbbf24,#f87171)}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
.sig{color:#fca5a5}
pre{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;
overflow:auto;font:12.5px/1.6 ui-monospace,Consolas,monospace;color:#d1d5db}
.note{color:var(--muted);font-size:12.5px;margin:8px 0 0}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.chip{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:4px 11px;
font-size:12px;color:var(--muted)}
.chip b{color:var(--text)}
footer{margin-top:44px;color:var(--muted);font-size:12px;
border-top:1px solid var(--line);padding-top:14px}
a{color:var(--blue)}
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _badge(verdict: str) -> str:
    cls = "b-" + verdict.replace(" ", "-")
    return f'<span class="badge {cls}">{_esc(verdict)}</span>'


def _duration_cell(seconds: float) -> str:
    return f'<td class="mono">{_esc(human_duration_or_na(seconds))}</td>'


def _score_bar(score: float) -> str:
    width = min(max(score, 0.0), 1.0) * 100
    return (
        f'<div class="bar" title="score {score:.3f}"><span style="width:{width:.0f}%"></span></div>'
    )


def _summary_cards(analysis: Analysis) -> str:
    flaky = analysis.flaky
    wasted = sum(item.total_duration * item.failure_rate for item in flaky)
    cards = [
        ("runs", human_count(len(analysis.runs)), ""),
        ("test results", human_count(analysis.cases), ""),
        ("distinct tests", human_count(len(analysis.stats)), ""),
        ("flaky tests", str(len(flaky)), "warn" if flaky else "good"),
        ("failing observations", human_count(sum(i.failures for i in analysis.stats)), "bad"),
        ("flaky CI time", human_duration(wasted), "warn" if wasted else ""),
    ]
    out = ['<section class="cards">']
    for label, value, kind in cards:
        out.append(
            f'<div class="card {kind}"><div class="k">{_esc(label)}</div>'
            f'<div class="v">{_esc(value)}</div></div>'
        )
    out.append("</section>")
    if analysis.warnings:
        out.append(
            '<p class="note">' + _esc("warnings: " + "; ".join(analysis.warnings[:3])) + "</p>"
        )
    return "".join(out)


def _leaderboard(analysis: Analysis, limit: int) -> str:
    rows = [s for s in analysis.stats if s.failures][:limit]
    if not rows:
        return '<p class="note">No failing runs were observed in this results set.</p>'
    out = [
        "<table><thead><tr><th>#</th><th>test</th><th>verdict</th><th>history</th>"
        '<th class="num">score</th><th class="num">fail</th><th class="num">P(fail)</th>'
        '<th class="num">P-&gt;F</th><th class="num">impact</th><th class="num">avg</th>'
        "</tr></thead><tbody>"
    ]
    for rank, item in enumerate(rows, 1):
        spark_width = min(28 * max(len(item.history), 1), 240)
        out.append(
            "<tr>"
            f'<td class="num mono">{rank}</td>'
            f'<td class="id">{_esc(item.test_id)}</td>'
            f"<td>{_badge(item.verdict)}</td>"
            f"<td>{svg_sparkline(item.history, width=spark_width)}</td>"
            f'<td class="num mono score">{item.score:.2f}{_score_bar(item.score)}</td>'
            f'<td class="num mono">{item.failures}/{item.runs}</td>'
            f'<td class="num mono">{pct(item.failure_rate, 0)}</td>'
            f'<td class="num mono">{item.chain.pass_to_fail:.2f}</td>'
            f'<td class="num mono">{item.impact:.3f}</td>'
            f"{_duration_cell(item.avg_duration)}"
            "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def _signatures(analysis: Analysis) -> str:
    clusters = analysis.correlations.clusters
    if not clusters:
        return '<p class="note">Every failing test reported a distinct error signature.</p>'
    out = [
        "<table><thead><tr><th>tests</th><th>failures</th><th>signature</th><th>example</th>"
        "</tr></thead><tbody>"
    ]
    for cluster in clusters[:10]:
        out.append(
            "<tr>"
            f'<td class="num mono">{cluster.size}</td>'
            f'<td class="num mono">{cluster.failures}</td>'
            f'<td class="mono sig">{_esc(cluster.signature[:110])}</td>'
            f'<td class="mono">{_esc(" ".join(cluster.tests[:3]))}</td>'
            "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def _correlated(analysis: Analysis) -> str:
    pairs = analysis.correlations.pairs
    if not pairs:
        return (
            '<p class="note">No pair of tests failed in the same runs often enough '
            "to suggest a shared fixture.</p>"
        )
    out = [
        "<table><thead><tr><th>jaccard</th><th>test A</th><th>test B</th><th>shared runs</th>"
        "</tr></thead><tbody>"
    ]
    for pair in pairs[:10]:
        out.append(
            "<tr>"
            f'<td class="num mono">{pair.jaccard:.2f}</td>'
            f'<td class="id">{_esc(pair.left)}</td>'
            f'<td class="id">{_esc(pair.right)}</td>'
            f'<td class="mono">{_esc(", ".join(pair.shared_runs[:6]))}</td>'
            "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def _baseline(analysis: Analysis) -> str:
    diff = analysis.baseline_diff
    if not diff:
        return ""
    chips = [
        f'<span class="chip">newly flaky <b>{len(diff["newly_flaky"])}</b></span>',
        f'<span class="chip">worsened <b>{len(diff["worsened"])}</b></span>',
        f'<span class="chip">fixed <b>{len(diff["fixed"])}</b></span>',
        f'<span class="chip">new tests <b>{len(diff["new_tests"])}</b></span>',
        f'<span class="chip">removed <b>{len(diff["removed"])}</b></span>',
    ]
    rows = []
    for label, key in (
        ("newly flaky", "newly_flaky"),
        ("worsened", "worsened"),
        ("fixed", "fixed"),
    ):
        for test_id in diff[key]:
            rows.append(f'<tr><td>{_esc(label)}</td><td class="id">{_esc(test_id)}</td></tr>')
    body = ""
    if rows:
        body = (
            "<table><thead><tr><th>change</th><th>test</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )
    return "<div class='chips'>" + "".join(chips) + "</div>" + body


def _quarantine(analysis: Analysis) -> str:
    flaky = analysis.flaky
    if not flaky:
        return '<p class="note">No test clears the flakiness threshold. Nothing to quarantine.</p>'
    lines = [
        "[pytest]",
        "markers =",
        "    quarantine: flaky test excluded from CI until fixed",
        "",
        'addopts = -m "not quarantine"',
    ]
    snippet = "\n".join(lines)
    marks = "\n".join("# score " + f"{item.score:.2f}" + "  " + item.test_id for item in flaky[:10])
    return (
        "<pre>" + _esc(snippet) + "</pre>"
        '<p class="note">Annotate these tests with @pytest.mark.quarantine:</p>'
        "<pre>" + _esc(marks) + "</pre>"
    )


def _verdict_chips(analysis: Analysis) -> str:
    chips = [
        f'<span class="chip">{_esc(name)} <b>{count}</b></span>'
        for name, count in analysis.verdict_counts().items()
    ]
    return '<div class="chips">' + "".join(chips) + "</div>"


def render_html(analysis: Analysis, *, limit: int = 25, title: str = "flaky-hunter report") -> str:
    """Render the entire report as one standalone HTML document."""
    generated_from = _esc(
        f"{len(analysis.runs)} runs / {analysis.files} files / "
        f"{human_count(analysis.cases)} results"
    )
    window = ""
    if analysis.first_ts:
        window = _esc(f"window {analysis.first_ts} .. {analysis.last_ts}")
    payload = {
        "runs": len(analysis.runs),
        "tests": len(analysis.stats),
        "flaky": len(analysis.flaky),
        "threshold": analysis.threshold,
    }
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>" + _esc(title) + "</title><style>" + CSS + "</style></head><body>"
        "<div class='wrap'>"
        "<header><h1>" + _esc(title) + "</h1>"
        "<div class='sub'>"
        + generated_from
        + (" - " + window if window else "")
        + "</div></header>"
        + _summary_cards(analysis)
        + "<h2>Leaderboard</h2>"
        + _leaderboard(analysis, limit)
        + "<h2>Failure signatures</h2>"
        + _signatures(analysis)
        + "<h2>Correlated failures</h2>"
        + _correlated(analysis)
        + ("<h2>Baseline diff</h2>" + _baseline(analysis) if analysis.baseline_diff else "")
        + "<h2>Verdicts</h2>"
        + _verdict_chips(analysis)
        + "<h2>Suggested quarantine</h2>"
        + _quarantine(analysis)
        + "<footer>Generated by flaky-hunter from real CI result files. "
        "Scores combine a 95% Wilson lower bound on the failure rate with the "
        "empirical Markov flip rate, shrunk on small samples.</footer>"
        "<script>window.__FLAKY_HUNTER__=" + _esc(json.dumps(payload)) + ";</script>"
        "</div></body></html>\n"
    )
