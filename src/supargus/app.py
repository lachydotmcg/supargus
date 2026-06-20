"""Local Supargus application server."""

from __future__ import annotations

import json
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .broker import search_brokers
from .bundle import export_bundle
from .config import DEFAULT_CONFIG_NAME, load_config, save_default_config
from .forms import build_form_queue, load_form_queue
from .identity import load_identity
from .mailer import load_smtp_config, preview_requests, send_requests
from .registry import load_registry, validate_registry
from .report import matches_payload, watchdog_payload, write_html_report, write_json
from .takedown import prepare_requests
from .tracker import format_records, import_requests, load_tracker, prepare_followups, record_payload
from .watchdog import run_watchdog
from .workflow import run_workflow


def _load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _count_requests(path: Path) -> int:
    data = _load_json(path, [])
    return len(data) if isinstance(data, list) else 0


def build_state(workspace: str | Path) -> dict:
    root = Path(workspace)
    broker = _load_json(root / "broker_matches.json", {})
    watchdog = _load_json(root / "watchdog.json", {})
    monitor = _load_json(root / "monitor_diff.json", {})
    tracker_path = root / "tracker.json"
    bundle_path = root / "supargus_evidence_bundle.zip"
    requests_path = root / "requests" / "requests.json"
    followups_path = root / "followups" / "requests.json"
    forms_path = root / "forms" / "forms.json"
    smtp_path = root / "smtp.gmail.json"

    broker_summary = broker.get("summary", {}) if isinstance(broker, dict) else {}
    watchdog_summary = watchdog.get("summary", {}) if isinstance(watchdog, dict) else {}
    monitor_summary = monitor.get("summary", {}) if isinstance(monitor, dict) else {}
    tracker_records = [record_payload(record) for record in load_tracker(tracker_path)]
    matches = broker.get("matches", []) if isinstance(broker, dict) else []
    findings = watchdog.get("findings", []) if isinstance(watchdog, dict) else []
    changes = monitor.get("changes", []) if isinstance(monitor, dict) else []

    return {
        "workspace": str(root.resolve()),
        "paths": {
            "broker_matches": str(root / "broker_matches.json"),
            "watchdog": str(root / "watchdog.json"),
            "monitor_diff": str(root / "monitor_diff.json"),
            "tracker": str(tracker_path),
            "requests": str(requests_path),
            "followups": str(followups_path),
            "forms": str(forms_path),
            "bundle": str(bundle_path),
            "config": str(Path(DEFAULT_CONFIG_NAME).resolve()),
            "smtp_config": str(smtp_path),
        },
        "exists": {
            "broker_matches": _path_exists(root / "broker_matches.json"),
            "watchdog": _path_exists(root / "watchdog.json"),
            "monitor_diff": _path_exists(root / "monitor_diff.json"),
            "tracker": _path_exists(tracker_path),
            "requests": _path_exists(requests_path),
            "followups": _path_exists(followups_path),
            "forms": _path_exists(forms_path),
            "bundle": _path_exists(bundle_path),
            "config": _path_exists(Path(DEFAULT_CONFIG_NAME)),
            "smtp_config": _path_exists(smtp_path),
        },
        "summary": {
            "brokers_checked": int(broker_summary.get("checked", 0) or 0),
            "possible_matches": int(broker_summary.get("possible_matches", 0) or 0),
            "manual_reviews": int(broker_summary.get("manual_review", 0) or 0),
            "request_only": int(broker_summary.get("request_only", 0) or 0),
            "verified_or_likely": int(broker_summary.get("verified_or_likely", 0) or 0),
            "watchdog_findings": int(watchdog_summary.get("findings", 0) or 0),
            "high_severity": int(watchdog_summary.get("high", 0) or 0),
            "scan_changes": int(monitor_summary.get("changes", 0) or 0),
            "tracker_records": len(tracker_records),
            "request_drafts": _count_requests(requests_path),
            "followup_drafts": _count_requests(followups_path),
            "form_tasks": len(load_form_queue(forms_path)),
            "bundle_size": bundle_path.stat().st_size if bundle_path.exists() else 0,
        },
        "matches": matches[:80],
        "findings": findings[:80],
        "changes": changes[:80],
        "tracker": tracker_records[:80],
    }


def _status_chip(value: str) -> str:
    key = value.lower().replace("_", "-")
    return f"<span class='chip chip-{escape(key)}'>{escape(value.replace('_', ' '))}</span>"


def _icon(name: str) -> str:
    icons = {
        "scan": "M4 7h16M7 4v6M17 4v6M5 13h14M8 17h8",
        "shield": "M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3z",
        "send": "M4 12l16-7-6 16-2-7-8-2z",
        "box": "M4 7l8-4 8 4v10l-8 4-8-4V7zM4 7l8 4 8-4M12 11v10",
        "clock": "M12 6v6l4 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
        "bolt": "M13 2L4 14h7l-1 8 10-13h-7l1-7z",
    }
    path = icons.get(name, icons["scan"])
    return (
        "<svg class='icon' viewBox='0 0 24 24' fill='none' aria-hidden='true'>"
        f"<path d='{path}' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/>"
        "</svg>"
    )


def render_dashboard(workspace: str | Path) -> str:
    state = build_state(workspace)
    summary = state["summary"]
    workspace_path = Path(workspace)
    identity_default = workspace_path / "identity.sgvault"
    state_json = json.dumps(state).replace("</", "<\\/")

    rows = "\n".join(
        "<tr>"
        f"<td><strong>{escape(item.get('broker_name', ''))}</strong><span>{escape(item.get('search_url', ''))}</span></td>"
        f"<td>{_status_chip(str(item.get('status', 'unknown')))}</td>"
        f"<td>{escape(str(item.get('confidence', 'unknown')))}</td>"
        f"<td><div class='score'><span style='width:{max(0, min(100, int(item.get('score', 0) or 0)))}%'></span></div></td>"
        f"<td><a href='{escape(item.get('search_url', ''))}' target='_blank' rel='noreferrer'>Open</a></td>"
        "</tr>"
        for item in state["matches"][:14]
    )
    finding_cards = "\n".join(
        f"<article class='finding {escape(item.get('severity', ''))}'>"
        f"<div><strong>{escape(item.get('title', ''))}</strong>{_status_chip(escape(item.get('severity', '')))}</div>"
        f"<p>{escape(item.get('detail', ''))}</p>"
        f"<pre>{escape(item.get('evidence', ''))}</pre>"
        "</article>"
        for item in state["findings"][:8]
    )
    change_rows = "\n".join(
        "<tr>"
        f"<td><strong>{escape(item.get('broker_name', ''))}</strong></td>"
        f"<td>{_status_chip(str(item.get('change_type', '')))}</td>"
        f"<td>{escape(item.get('previous_status', ''))}</td>"
        f"<td>{escape(item.get('current_status', ''))}</td>"
        f"<td>{escape(item.get('detail', ''))}</td>"
        "</tr>"
        for item in state["changes"][:10]
    )
    tracker_rows = "\n".join(
        "<tr>"
        f"<td><strong>{escape(item.get('broker_name', ''))}</strong><span>{escape(item.get('broker_id', ''))}</span></td>"
        f"<td>{_status_chip(str(item.get('status', '')))}</td>"
        f"<td>{escape(item.get('delivery', ''))}</td>"
        f"<td>{escape(item.get('updated_at', ''))}</td>"
        "</tr>"
        for item in state["tracker"][:10]
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Supargus Console</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f9fb;
      --panel: #ffffff;
      --panel-2: #eef8f6;
      --ink: #102027;
      --muted: #52656d;
      --line: #d9e4e8;
      --blue: #0369a1;
      --cyan: #0ea5e9;
      --green: #16a34a;
      --amber: #b7791f;
      --red: #b42318;
      --violet: #6d5bd0;
      --shadow: 0 18px 48px rgba(22, 48, 64, .10);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; background: var(--bg); color: var(--ink); font-family: "Plus Jakarta Sans", Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; line-height: 1.5; }}
    button, input {{ font: inherit; }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .app {{ display: grid; grid-template-columns: 248px minmax(0, 1fr); min-height: 100vh; }}
    .sidebar {{ background: #102027; color: #eff7f8; padding: 24px 18px; position: sticky; top: 0; height: 100vh; }}
    .brand {{ display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }}
    .mark {{ width: 42px; height: 42px; border-radius: 8px; background: linear-gradient(135deg, #20c997, #0ea5e9); display: grid; place-items: center; color: #071316; font-weight: 800; }}
    .brand strong {{ display: block; font-size: 1rem; }}
    .brand span {{ display: block; color: #9fb8bf; font-size: .82rem; }}
    .nav {{ display: grid; gap: 6px; margin: 20px 0 28px; }}
    .nav a {{ color: #cfe1e5; padding: 10px 12px; border-radius: 8px; display: flex; gap: 10px; align-items: center; }}
    .nav a:hover {{ background: rgba(255,255,255,.08); text-decoration: none; }}
    .side-note {{ border: 1px solid rgba(255,255,255,.12); border-radius: 8px; padding: 12px; color: #bdd3d8; font-size: .86rem; }}
    .main {{ padding: 26px; min-width: 0; }}
    .topbar {{ display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 22px; }}
    .eyebrow {{ color: var(--blue); font-weight: 700; font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; }}
    h1 {{ margin: 2px 0 4px; font-size: clamp(1.8rem, 3vw, 3rem); line-height: 1.08; letter-spacing: 0; }}
    .subtitle {{ color: var(--muted); max-width: 760px; margin: 0; }}
    .workspace {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; font-size: .86rem; color: var(--muted); max-width: 460px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; box-shadow: var(--shadow); min-height: 118px; }}
    .metric span {{ color: var(--muted); font-size: .86rem; }}
    .metric strong {{ display: block; margin-top: 8px; font-size: 2rem; line-height: 1; }}
    .metric small {{ color: var(--muted); }}
    .command-grid {{ display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(340px, .85fr); gap: 16px; align-items: start; }}
    section {{ margin-bottom: 16px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); }}
    .panel-head {{ padding: 16px 18px; border-bottom: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    .panel-head h2 {{ font-size: 1.02rem; margin: 0; }}
    .panel-head p {{ color: var(--muted); margin: 2px 0 0; font-size: .88rem; }}
    .panel-body {{ padding: 16px 18px; }}
    .actions {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .action {{ border: 1px solid var(--line); background: #fbfdfe; border-radius: 8px; padding: 14px; text-align: left; cursor: pointer; transition: border-color .2s, box-shadow .2s, transform .2s; min-height: 100px; }}
    .action:hover {{ border-color: #9bc8d8; box-shadow: 0 12px 28px rgba(14, 76, 103, .12); transform: translateY(-1px); }}
    .action:focus-visible, .primary:focus-visible, input:focus-visible {{ outline: 3px solid rgba(14,165,233,.28); outline-offset: 2px; }}
    .action strong {{ display: flex; align-items: center; gap: 9px; font-size: .96rem; }}
    .action span {{ display: block; color: var(--muted); font-size: .84rem; margin-top: 6px; }}
    .icon {{ width: 18px; height: 18px; flex: 0 0 auto; }}
    .form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    label {{ display: grid; gap: 6px; color: var(--muted); font-size: .84rem; font-weight: 650; }}
    input {{ width: 100%; border: 1px solid var(--line); border-radius: 8px; padding: 10px 11px; color: var(--ink); background: #fff; min-height: 44px; }}
    .primary {{ border: 0; border-radius: 8px; min-height: 44px; padding: 10px 14px; background: var(--green); color: white; cursor: pointer; font-weight: 750; transition: background .2s, transform .2s; }}
    .primary:hover {{ background: #13813d; transform: translateY(-1px); }}
    .console {{ background: #071316; color: #d7f5ec; border-radius: 8px; padding: 14px; min-height: 220px; max-height: 420px; overflow: auto; font: 13px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 11px 10px; text-align: left; vertical-align: top; font-size: .9rem; }}
    th {{ color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; }}
    td span {{ display: block; color: var(--muted); font-size: .78rem; margin-top: 2px; max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .chip {{ display: inline-flex; align-items: center; min-height: 24px; padding: 2px 8px; border-radius: 999px; background: #e9f5f7; color: var(--blue); font-size: .76rem; font-weight: 750; text-transform: capitalize; }}
    .chip-possible-match, .chip-new-match, .chip-reappeared {{ background: #e8f8ee; color: #116b34; }}
    .chip-needs-manual-review, .chip-waiting, .chip-submitted {{ background: #fff4d8; color: #835b00; }}
    .chip-high, .chip-fetch-error {{ background: #ffe8e4; color: var(--red); }}
    .score {{ width: 112px; height: 8px; background: #e5edf0; border-radius: 999px; overflow: hidden; margin-top: 7px; }}
    .score span {{ display: block; height: 100%; background: linear-gradient(90deg, var(--cyan), var(--green)); }}
    .finding {{ border: 1px solid var(--line); border-left: 4px solid var(--amber); border-radius: 8px; padding: 12px; margin-bottom: 10px; }}
    .finding.high {{ border-left-color: var(--red); }}
    .finding.medium {{ border-left-color: var(--amber); }}
    .finding div {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
    .finding p {{ color: var(--muted); margin: 8px 0; }}
    pre {{ background: #f2f7f8; padding: 10px; border-radius: 8px; white-space: pre-wrap; overflow: auto; margin: 0; }}
    .empty {{ color: var(--muted); padding: 20px; border: 1px dashed var(--line); border-radius: 8px; background: #fbfdfe; }}
    @media (max-width: 1020px) {{ .app {{ grid-template-columns: 1fr; }} .sidebar {{ position: relative; height: auto; }} .metrics, .command-grid {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 620px) {{ .main {{ padding: 16px; }} .topbar {{ align-items: flex-start; flex-direction: column; }} .actions, .form-grid {{ grid-template-columns: 1fr; }} th:nth-child(4), td:nth-child(4) {{ display: none; }} }}
    @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; scroll-behavior: auto !important; }} }}
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand"><div class="mark">S</div><div><strong>Supargus</strong><span>Privacy ops console</span></div></div>
      <nav class="nav" aria-label="Main navigation">
        <a href="#commands">{_icon("bolt")}Commands</a>
        <a href="#brokers">{_icon("scan")}Broker radar</a>
        <a href="#watchdog">{_icon("shield")}Watchdog</a>
        <a href="#tracker">{_icon("clock")}Tracker</a>
        <a href="#bundle">{_icon("box")}Evidence</a>
      </nav>
      <div class="side-note">Everything here runs on this machine. Cloud AI is optional, and this console calls the same open-source Supargus core as the CLI.</div>
    </aside>
    <main class="main">
      <div class="topbar">
        <div>
          <div class="eyebrow">Local-first data broker defense</div>
          <h1>Command your privacy cleanup from one place.</h1>
          <p class="subtitle">Run scans, build requests, track follow-ups, monitor reappearances, and export receipts without handing your identity profile to another SaaS middleman.</p>
        </div>
        <div class="workspace" title="{escape(state['workspace'])}">{escape(state['workspace'])}</div>
      </div>

      <div class="metrics" id="bundle">
        <div class="metric"><span>Brokers checked</span><strong id="m-brokers">{summary['brokers_checked']}</strong><small>{summary['possible_matches']} possible matches</small></div>
        <div class="metric"><span>Open workflow</span><strong id="m-requests">{summary['request_drafts']}</strong><small>{summary['followup_drafts']} follow-up drafts</small></div>
        <div class="metric"><span>Watchdog</span><strong id="m-watchdog">{summary['watchdog_findings']}</strong><small>{summary['high_severity']} high severity</small></div>
        <div class="metric"><span>Monitor</span><strong id="m-changes">{summary['scan_changes']}</strong><small>{summary['tracker_records']} tracked requests</small></div>
      </div>

      <div class="command-grid" id="commands">
        <section class="panel">
          <div class="panel-head"><div><h2>Command Center</h2><p>Run the same core operations as the CLI.</p></div></div>
          <div class="panel-body">
            <div class="form-grid">
              <label>Identity path <input id="identity" value="{escape(str(identity_default))}"></label>
              <label>Workspace <input id="workspace" value="{escape(str(Path(workspace)))}"></label>
              <label>Config <input id="config" value="{escape(DEFAULT_CONFIG_NAME)}"></label>
              <label>Limit <input id="limit" type="number" min="1" max="100" value="10"></label>
            </div>
            <div class="actions" style="margin-top:14px">
              <button class="action" data-action="workflow">{_icon("bolt")}<strong>Run full workflow</strong><span>Scan, diff, watchdog, requests, tracker, follow-ups, bundle.</span></button>
              <button class="action" data-action="broker_scan">{_icon("scan")}<strong>Broker scan</strong><span>Generate broker evidence and local HTML report.</span></button>
              <button class="action" data-action="watchdog">{_icon("shield")}<strong>Watchdog scan</strong><span>Inspect local proxy, process, browser, and listener risks.</span></button>
              <button class="action" data-action="prepare_requests">{_icon("send")}<strong>Prepare requests</strong><span>Create reviewed takedown drafts from broker matches.</span></button>
              <button class="action" data-action="tracker_import">{_icon("clock")}<strong>Import tracker</strong><span>Track draft status and follow-up windows.</span></button>
              <button class="action" data-action="followups">{_icon("send")}<strong>Generate follow-ups</strong><span>Create follow-up drafts for tracked requests.</span></button>
              <button class="action" data-action="bundle">{_icon("box")}<strong>Export bundle</strong><span>Zip evidence, drafts, tracker state, reports, and hashes.</span></button>
              <button class="action" data-action="validate">{_icon("shield")}<strong>Validate registry</strong><span>Check broker adapters before scans.</span></button>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><div><h2>Run Log</h2><p>Last command response from the local app server.</p></div><button class="primary" id="refresh">Refresh</button></div>
          <div class="panel-body"><div class="console" id="console">Ready. Choose a command to run Supargus locally.</div></div>
        </section>
      </div>

      <section class="panel" id="brokers">
        <div class="panel-head"><div><h2>Broker Radar</h2><p>Evidence records from the latest broker scan.</p></div></div>
        <div class="panel-body">
          <table><thead><tr><th>Broker</th><th>Status</th><th>Confidence</th><th>Score</th><th>Evidence</th></tr></thead>
          <tbody id="brokerRows">{rows or "<tr><td colspan='5'><div class='empty'>No broker results yet. Run Broker scan or Full workflow.</div></td></tr>"}</tbody></table>
        </div>
      </section>

      <section class="panel" id="watchdog">
        <div class="panel-head"><div><h2>Local Watchdog</h2><p>Signals from this machine that deserve review.</p></div></div>
        <div class="panel-body" id="findingRows">{finding_cards or "<div class='empty'>No watchdog data yet. Run Watchdog scan.</div>"}</div>
      </section>

      <section class="panel">
        <div class="panel-head"><div><h2>Monitor Changes</h2><p>What changed since the last broker snapshot.</p></div></div>
        <div class="panel-body">
          <table><thead><tr><th>Broker</th><th>Change</th><th>Previous</th><th>Current</th><th>Detail</th></tr></thead>
          <tbody id="changeRows">{change_rows or "<tr><td colspan='5'><div class='empty'>No monitor diff yet. Run the full workflow twice or monitor scan.</div></td></tr>"}</tbody></table>
        </div>
      </section>

      <section class="panel" id="tracker">
        <div class="panel-head"><div><h2>Compliance Tracker</h2><p>Request status, delivery mode, and follow-up state.</p></div></div>
        <div class="panel-body">
          <table><thead><tr><th>Broker</th><th>Status</th><th>Delivery</th><th>Updated</th></tr></thead>
          <tbody id="trackerRows">{tracker_rows or "<tr><td colspan='4'><div class='empty'>No tracker records yet. Import tracker after preparing requests.</div></td></tr>"}</tbody></table>
        </div>
      </section>
    </main>
  </div>
  <script>
    const initialState = {state_json};
    const consoleEl = document.getElementById('console');
    const refreshButton = document.getElementById('refresh');
    const savedLog = sessionStorage.getItem('supargus:lastLog');
    if (savedLog) {{
      consoleEl.textContent = savedLog;
      sessionStorage.removeItem('supargus:lastLog');
    }}

    function values() {{
      return {{
        identity: document.getElementById('identity').value,
        workspace: document.getElementById('workspace').value,
        config: document.getElementById('config').value,
        limit: Number(document.getElementById('limit').value || 10)
      }};
    }}

    function log(message) {{
      consoleEl.textContent = message;
    }}

    function workspaceUrl() {{
      return `/?workspace=${{encodeURIComponent(values().workspace)}}`;
    }}

    async function post(action) {{
      log(`Running ${{action}}...`);
      const response = await fetch('/api/action', {{
        method: 'POST',
        headers: {{ 'content-type': 'application/json' }},
        body: JSON.stringify({{ action, ...values() }})
      }});
      const body = await response.json();
      if (!response.ok || !body.ok) {{
        log(`ERROR ${{action}}\\n${{body.error || response.statusText}}`);
        return;
      }}
      const message = `${{action}} complete\\n${{JSON.stringify(body.result, null, 2)}}`;
      sessionStorage.setItem('supargus:lastLog', message);
      window.location.href = workspaceUrl();
    }}

    async function reloadState() {{
      const response = await fetch(`/api/state?workspace=${{encodeURIComponent(values().workspace)}}`);
      const state = await response.json();
      document.getElementById('m-brokers').textContent = state.summary.brokers_checked;
      document.getElementById('m-requests').textContent = state.summary.request_drafts;
      document.getElementById('m-watchdog').textContent = state.summary.watchdog_findings;
      document.getElementById('m-changes').textContent = state.summary.scan_changes;
    }}

    document.querySelectorAll('[data-action]').forEach((button) => {{
      button.addEventListener('click', () => post(button.dataset.action));
    }});
    refreshButton.addEventListener('click', () => {{ window.location.href = workspaceUrl(); }});
    window.__SUPARGUS_STATE__ = initialState;
  </script>
</body>
</html>"""


def _json_response(handler: BaseHTTPRequestHandler, data: dict, status: int = 200) -> None:
    body = json.dumps(data, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("cache-control", "no-store")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("content-length", "0") or 0)
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def run_action(workspace: Path, payload: dict) -> dict:
    action = str(payload.get("action", ""))
    identity_path = str(payload.get("identity") or workspace / "identity.sgvault")
    config_path = str(payload.get("config") or DEFAULT_CONFIG_NAME)
    smtp_config = str(payload.get("smtp_config") or workspace / "smtp.gmail.json")
    limit = int(payload.get("limit") or 10)
    root = Path(payload.get("workspace") or workspace)
    fetch = bool(payload.get("fetch", False))
    root.mkdir(parents=True, exist_ok=True)

    if action == "validate":
        errors = validate_registry(None)
        return {"valid": not errors, "errors": errors}

    if action == "workflow":
        if not Path(config_path).exists():
            save_default_config(config_path)
        config = load_config(config_path)
        config.identity = identity_path
        config.workspace = str(root)
        config.history_dir = str(root / "history")
        config.tracker = str(root / "tracker.json")
        config.requests_dir = str(root / "requests")
        config.followups_dir = str(root / "followups")
        config.bundle_path = str(root / "supargus_evidence_bundle.zip")
        config.limit = limit
        config.fetch = fetch
        return run_workflow(config)

    if action == "broker_scan":
        identity = load_identity(identity_path)
        matches = search_brokers(load_registry(None), identity, fetch=fetch, limit=limit)
        out = write_json(matches_payload(matches), root / "broker_matches.json")
        html = write_html_report(root / "broker_matches.html", title="Supargus Broker Radar", matches=matches)
        return {"matches": len(matches), "output": str(out), "html": str(html)}

    if action == "watchdog":
        findings = run_watchdog()
        out = write_json(watchdog_payload(findings), root / "watchdog.json")
        html = write_html_report(root / "watchdog.html", title="Supargus Local Watchdog", findings=findings)
        return {"findings": len(findings), "output": str(out), "html": str(html)}

    if action == "prepare_requests":
        identity = load_identity(identity_path)
        matches = _matches_from_path(root / "broker_matches.json")
        requests, manifest = prepare_requests(matches, load_registry(None), identity, root / "requests")
        tasks, forms_manifest = build_form_queue(requests, root / "forms" / "forms.json")
        return {"requests": len(requests), "manifest": str(manifest), "form_tasks": len(tasks), "forms": str(forms_manifest)}

    if action == "form_queue":
        requests = _load_requests(root / "requests" / "requests.json")
        tasks, manifest = build_form_queue(requests, root / "forms" / "forms.json")
        return {"form_tasks": len(tasks), "forms": str(manifest)}

    if action == "mail_preview":
        requests = _load_requests(root / "requests" / "requests.json")
        return {"preview": preview_requests(requests), "requests": len(requests)}

    if action == "mail_send":
        requests = _load_requests(root / "requests" / "requests.json")
        config = load_smtp_config(smtp_config)
        sent = send_requests(requests, config, limit=limit)
        return {"sent": len(sent), "items": sent}

    if action == "tracker_import":
        requests = _load_requests(root / "requests" / "requests.json")
        records = import_requests(requests, root / "tracker.json")
        return {"records": len(records), "tracker": str(root / "tracker.json")}

    if action == "followups":
        records = load_tracker(root / "tracker.json")
        requests, manifest = prepare_followups(records, root / "followups", due_only=False)
        return {"followups": len(requests), "manifest": str(manifest)}

    if action == "bundle":
        out, manifest = export_bundle(root, root / "supargus_evidence_bundle.zip")
        return {"bundle": str(out), "files": manifest["file_count"]}

    raise ValueError(f"Unknown action: {action}")


def _run_action(workspace: Path, payload: dict) -> dict:
    return run_action(workspace, payload)


def _matches_from_path(path: Path):
    data = _load_json(path, {})
    items = data.get("matches", []) if isinstance(data, dict) else []
    from .models import BrokerMatch

    return [
        BrokerMatch(
            broker_id=str(item.get("broker_id", "")),
            broker_name=str(item.get("broker_name", "")),
            status=str(item.get("status", "")),
            confidence=str(item.get("confidence", "unknown")),
            score=int(item.get("score", 0) or 0),
            search_url=str(item.get("search_url", "")),
            evidence_url=str(item.get("evidence_url", "")),
            matched_fields=[str(v) for v in item.get("matched_fields", [])],
            evidence=str(item.get("evidence", "")),
            error=str(item.get("error", "")),
            checked_at=str(item.get("checked_at", "")),
        )
        for item in items
    ]


def _load_requests(path: Path):
    from .takedown import load_requests

    return load_requests(path)


class _DashboardHandler(BaseHTTPRequestHandler):
    workspace = Path(".")

    def _request_workspace(self) -> Path:
        parsed = urlparse(self.path)
        values = parse_qs(parsed.query).get("workspace", [])
        value = values[0] if values else str(self.workspace)
        return Path(value or self.workspace)

    def _send(self, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler naming
        parsed = urlparse(self.path)
        path = parsed.path
        workspace = self._request_workspace()
        if path == "/":
            self._send(render_dashboard(workspace).encode("utf-8"))
            return
        if path == "/api/state":
            _json_response(self, build_state(workspace))
            return
        if path == "/api/broker_matches.json":
            _json_response(self, _load_json(workspace / "broker_matches.json", {}))
            return
        if path == "/api/watchdog.json":
            _json_response(self, _load_json(workspace / "watchdog.json", {}))
            return
        if path == "/api/monitor_diff.json":
            _json_response(self, _load_json(workspace / "monitor_diff.json", {}))
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler naming
        path = urlparse(self.path).path
        if path != "/api/action":
            self.send_error(404)
            return
        try:
            payload = _read_json(self)
            result = _run_action(self.workspace, payload)
            _json_response(self, {"ok": True, "result": result})
        except Exception as exc:
            _json_response(self, {"ok": False, "error": str(exc)}, status=400)

    def log_message(self, format: str, *args: object) -> None:
        return


def run_app(workspace: str | Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    handler = type("SupargusDashboardHandler", (_DashboardHandler,), {"workspace": Path(workspace)})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Supargus dashboard running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
