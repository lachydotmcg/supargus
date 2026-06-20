"""JSON and HTML report generation."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from .models import BrokerMatch, WatchdogFinding, to_dict, utc_now


def write_json(data: dict[str, Any], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def matches_payload(matches: list[BrokerMatch]) -> dict[str, Any]:
    request_only_statuses = {"fetch_error", "needs_manual_review"}
    return {
        "generated_at": utc_now(),
        "matches": [to_dict(match) for match in matches],
        "summary": {
            "checked": len(matches),
            "possible_matches": sum(1 for match in matches if match.status == "possible_match"),
            "manual_review": sum(1 for match in matches if match.status == "needs_manual_review"),
            "request_only": sum(1 for match in matches if match.action_mode == "request_only" or match.status in request_only_statuses),
            "public_unverified": sum(1 for match in matches if match.action_mode == "public_unverified"),
            "verified_or_likely": sum(1 for match in matches if match.status == "possible_match" and match.score > 0),
            "errors": sum(1 for match in matches if match.status == "fetch_error"),
        },
    }


def watchdog_payload(findings: list[WatchdogFinding]) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "findings": [to_dict(finding) for finding in findings],
        "summary": {
            "findings": len(findings),
            "high": sum(1 for finding in findings if finding.severity == "high"),
            "medium": sum(1 for finding in findings if finding.severity == "medium"),
            "low": sum(1 for finding in findings if finding.severity == "low"),
        },
    }


def write_html_report(
    path: str | Path,
    *,
    title: str,
    matches: list[BrokerMatch] | None = None,
    findings: list[WatchdogFinding] | None = None,
) -> Path:
    matches = matches or []
    findings = findings or []
    match_rows = "\n".join(
        f"<tr><td>{escape(match.broker_name)}</td><td>{escape(match.status)}</td>"
        f"<td>{escape(match.confidence)}</td><td>{match.score}</td>"
        f"<td><a href='{escape(match.search_url)}'>search</a></td></tr>"
        for match in matches
    )
    finding_cards = "\n".join(
        f"<section class='card {escape(finding.severity)}'><h3>{escape(finding.title)}</h3>"
        f"<p>{escape(finding.detail)}</p><pre>{escape(finding.evidence)}</pre>"
        f"<p><strong>Fix:</strong> {escape(finding.remediation)}</p></section>"
        for finding in findings
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; background: #101418; color: #edf2f7; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px; }}
    h1 {{ margin: 0 0 8px; }}
    .meta {{ color: #94a3b8; margin-bottom: 28px; }}
    table {{ width: 100%; border-collapse: collapse; background: #151b22; border: 1px solid #2d3748; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #2d3748; text-align: left; }}
    th {{ color: #a7f3d0; }}
    a {{ color: #7dd3fc; }}
    .card {{ background: #151b22; border: 1px solid #2d3748; border-left: 4px solid #94a3b8; padding: 16px; margin: 12px 0; }}
    .card.high {{ border-left-color: #fb7185; }}
    .card.medium {{ border-left-color: #facc15; }}
    .card.low {{ border-left-color: #38bdf8; }}
    pre {{ white-space: pre-wrap; background: #0b0f14; padding: 12px; overflow: auto; }}
  </style>
</head>
<body><main>
  <h1>{escape(title)}</h1>
  <div class="meta">Generated {escape(utc_now())}</div>
  <h2>Broker Matches</h2>
  <table>
    <thead><tr><th>Broker</th><th>Status</th><th>Confidence</th><th>Score</th><th>Evidence</th></tr></thead>
    <tbody>{match_rows or "<tr><td colspan='5'>No broker matches in this report.</td></tr>"}</tbody>
  </table>
  <h2>Watchdog Findings</h2>
  {finding_cards or "<p>No watchdog findings in this report.</p>"}
</main></body></html>"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    return p
