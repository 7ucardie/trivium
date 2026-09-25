"""The status page `ask serve` shows at `/`: what is loaded, how it is doing, and recent decisions."""

from __future__ import annotations

import json
import time
from html import escape
from pathlib import Path

REFRESH_SECONDS = 15


def recent_decisions(path: Path, limit: int = 25) -> list[dict]:
    """The newest decisions in the log, newest first, with any feedback attached. Reads only the tail."""
    if not path.exists():
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 512 * 1024))
        lines = f.read().decode("utf-8", "replace").splitlines()
    if size > 512 * 1024:
        lines = lines[1:]  # the first line is probably cut in half
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    feedback = {r["decision"]: r for r in records if r.get("type") == "feedback"}
    decisions = [dict(r, feedback=feedback.get(r.get("id"))) for r in records if r.get("type") == "decision"]
    return decisions[::-1][:limit]


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def render(info: dict, decisions: list[dict], now: float | None = None) -> str:
    """info: model, backend, runtime, load_seconds, started, routes, generates, errors, route_ms (list)."""
    now = now or time.time()
    p50, p90 = (_percentile(info["route_ms"], q) for q in (0.5, 0.9))
    latency = f"{p50:.0f} / {p90:.0f} ms" if p50 is not None else "no requests yet"
    cards = [
        ("Model", info["model"]),
        ("Backend · runtime", f"{info['backend']} · {info['runtime']}"),
        ("Up for", f"{_duration(now - info['started'])} (loaded in {info['load_seconds']:.1f} s)"),
        ("Served", f"{info['routes']} routed · {info['generates']} answered locally · {info['errors']} errors"),
        ("Routing p50 / p90", latency),
    ]
    card_html = "".join(
        f'<div class="card"><div class="label">{escape(k)}</div><div class="value">{escape(str(v))}</div></div>'
        for k, v in cards
    )
    rows = []
    for d in decisions:
        answers = d.get("answers") or {}
        labels = " · ".join(a.get("choice", "?") for a in answers.values()) or "manual"
        low = [q for q, a in answers.items() if a.get("p", 1) < 0.6]
        fb = d.get("feedback") or {}
        verdict = {"good": "✓", "bad": "✗"}.get(fb.get("verdict"), "")
        if fb.get("should"):
            verdict += f" → {fb['should']}"
        rerouted = d.get("routed") and d.get("routed") != d.get("target")
        target = escape(d.get("target", "?")) + (f' <span class="dim">(router: {escape(d["routed"])})</span>' if rerouted else "")
        ms = f"{d['route_ms']:.0f}" if isinstance(d.get("route_ms"), (int, float)) else ""
        rows.append(
            "<tr>"
            f'<td class="dim nowrap">{_ago(now - d.get("ts", now))}</td>'
            f'<td class="prompt" title="{escape(d.get("prompt", ""))}">{escape(d.get("prompt", "")[:140])}</td>'
            f'<td class="nowrap"><span class="pill">{target}</span></td>'
            f'<td class="nowrap">{escape(labels)}'
            + (f' <span class="warn" title="below 0.6: {escape(", ".join(low))}">low</span>' if low else "")
            + "</td>"
            f'<td class="num">{ms}</td>'
            f'<td class="nowrap">{escape(verdict)}</td>'
            "</tr>"
        )
    table = (
        "<table><thead><tr><th>When</th><th>Prompt</th><th>Target</th><th>Kind · difficulty · tools</th>"
        '<th class="num">ms</th><th>Rated</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"
        if rows else '<p class="dim">No decisions logged yet. Try <code>ask why "what does HTTP 409 mean"</code>.</p>'
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>Trivium status</title>
<style>
:root {{ --bg:#f7f7f5; --panel:#fff; --text:#1b1b1a; --dim:#6b6a66; --line:#e3e2dd; --accent:#1f6fd1; --warn:#9a5b00; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141413; --panel:#1f1f1d; --text:#ecebe6; --dim:#9d9b94; --line:#33322f; --accent:#6aa6f0; --warn:#e0a44a; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px 48px; }}
h1 {{ font-size:20px; margin:0 0 4px; }} .sub {{ color:var(--dim); margin:0 0 20px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:10px; margin-bottom:24px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
.label {{ color:var(--dim); font-size:12px; }} .value {{ font-weight:600; overflow-wrap:anywhere; }}
h2 {{ font-size:15px; margin:0 0 8px; }}
.scroll {{ overflow-x:auto; background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ color:var(--dim); font-weight:500; font-size:12px; }} tr:last-child td {{ border-bottom:0; }}
.prompt {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; min-width:260px; }}
.pill {{ color:var(--accent); font-weight:600; }} .dim {{ color:var(--dim); }} .warn {{ color:var(--warn); font-size:12px; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }} .nowrap {{ white-space:nowrap; }}
code {{ font-family:ui-monospace,Menlo,monospace; }} a {{ color:var(--accent); }}
</style></head>
<body><main>
<h1>Trivium</h1>
<p class="sub">Local router on 127.0.0.1. Refreshes every {REFRESH_SECONDS} s · <a href="/health">/health</a></p>
<div class="cards">{card_html}</div>
<h2>Recent decisions</h2>
<div class="scroll">{table}</div>
</main></body></html>"""
