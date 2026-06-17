"""Tiny local Supargus dashboard server."""

from __future__ import annotations

import json
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _badge(label: str, value: object) -> str:
    return f"<div class='badge'><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>"


def render_dashboard(workspace: str | Path) -> str:
    root = Path(workspace)
    broker = _load_json(root / "broker_matches.json")
    watchdog = _load_json(root / "watchdog.json")
    monitor = _load_json(root / "monitor_diff.json")
    requests = _load_json(root / "requests/requests.json")
    if isinstance(requests, list):
        request_count = len(requests)
    else:
        request_count = 0

    broker_summary = broker.get("summary", {})
    watchdog_summary = watchdog.get("summary", {})
    monitor_summary = monitor.get("summary", {})
    matches = broker.get("matches", [])[:12]
    findings = watchdog.get("findings", [])[:12]
    changes = monitor.get("changes", [])[:12]

    match_rows = "\n".join(
        "<tr>"
        f"<td>{escape(item.get('broker_name', ''))}</td>"
        f"<td>{escape(item.get('status', ''))}</td>"
        f"<td>{escape(item.get('confidence', ''))}</td>"
        f"<td>{escape(str(item.get('score', 0)))}</td>"
        f"<td><a href='{escape(item.get('search_url', ''))}'>open</a></td>"
        "</tr>"
        for item in matches
    )
    finding_cards = "\n".join(
        f"<section class='finding {escape(item.get('severity', ''))}'>"
        f"<h3>{escape(item.get('title', ''))}</h3>"
        f"<p>{escape(item.get('detail', ''))}</p>"
        f"<pre>{escape(item.get('evidence', ''))}</pre>"
        "</section>"
        for item in findings
    )
    change_rows = "\n".join(
        "<tr>"
        f"<td>{escape(item.get('broker_name', ''))}</td>"
        f"<td>{escape(item.get('change_type', ''))}</td>"
        f"<td>{escape(item.get('previous_status', ''))}</td>"
        f"<td>{escape(item.get('current_status', ''))}</td>"
        f"<td>{escape(item.get('detail', ''))}</td>"
        "</tr>"
        for item in changes
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Supargus Local Dashboard</title>
  <style>
    body {{ margin: 0; background: #0d1117; color: #e6edf3; font-family: system-ui, -apple-system, Segoe UI, sans-serif; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 30px 20px 56px; }}
    h1 {{ margin: 0 0 6px; font-size: 2rem; }}
    .sub {{ color: #8b949e; margin-bottom: 24px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 28px; }}
    .badge {{ background: #161b22; border: 1px solid #30363d; padding: 14px; border-radius: 8px; }}
    .badge span {{ color: #8b949e; display: block; font-size: .85rem; }}
    .badge strong {{ font-size: 1.5rem; }}
    table {{ width: 100%; border-collapse: collapse; background: #161b22; border: 1px solid #30363d; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #30363d; text-align: left; }}
    th {{ color: #a7f3d0; }}
    a {{ color: #58a6ff; }}
    .finding {{ background: #161b22; border: 1px solid #30363d; border-left: 4px solid #8b949e; padding: 14px; margin: 10px 0; }}
    .finding.high {{ border-left-color: #f85149; }}
    .finding.medium {{ border-left-color: #d29922; }}
    pre {{ white-space: pre-wrap; background: #0b0f14; padding: 10px; overflow: auto; }}
  </style>
</head>
<body><main>
  <h1>Supargus</h1>
  <div class="sub">Local-first privacy watchdog. Served from {escape(str(root.resolve()))}</div>
  <div class="grid">
    {_badge("Brokers checked", broker_summary.get("checked", 0))}
    {_badge("Possible matches", broker_summary.get("possible_matches", 0))}
    {_badge("Manual reviews", broker_summary.get("manual_review", 0))}
    {_badge("Watchdog findings", watchdog_summary.get("findings", 0))}
    {_badge("High severity", watchdog_summary.get("high", 0))}
    {_badge("Request drafts", request_count)}
    {_badge("Scan changes", monitor_summary.get("changes", 0))}
  </div>
  <h2>Broker Radar</h2>
  <table>
    <thead><tr><th>Broker</th><th>Status</th><th>Confidence</th><th>Score</th><th>Evidence</th></tr></thead>
    <tbody>{match_rows or "<tr><td colspan='5'>Run supargus brokers find to populate this section.</td></tr>"}</tbody>
  </table>
  <h2>Local Watchdog</h2>
  {finding_cards or "<p>Run supargus watchdog scan to populate this section.</p>"}
  <h2>Monitor Changes</h2>
  <table>
    <thead><tr><th>Broker</th><th>Change</th><th>Previous</th><th>Current</th><th>Detail</th></tr></thead>
    <tbody>{change_rows or "<tr><td colspan='5'>Run supargus monitor diff to populate this section.</td></tr>"}</tbody>
  </table>
</main></body></html>"""


class _DashboardHandler(BaseHTTPRequestHandler):
    workspace = Path(".")

    def _send(self, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
        path = urlparse(self.path).path
        if path == "/":
            self._send(render_dashboard(self.workspace).encode("utf-8"))
            return
        if path == "/api/broker_matches.json":
            self._send((self.workspace / "broker_matches.json").read_bytes(), "application/json")
            return
        if path == "/api/watchdog.json":
            self._send((self.workspace / "watchdog.json").read_bytes(), "application/json")
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        return


def run_app(workspace: str | Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    handler = type("SupargusDashboardHandler", (_DashboardHandler,), {"workspace": Path(workspace)})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Supargus dashboard running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
