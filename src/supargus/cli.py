"""Supargus command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .broker import search_brokers
from .app import run_app
from .identity import load_identity, sample_identity, save_identity
from .mailer import load_smtp_config, preview_requests, send_requests
from .models import BrokerMatch, to_dict
from .registry import load_registry
from .report import matches_payload, watchdog_payload, write_html_report, write_json
from .takedown import load_requests, prepare_requests
from .watchdog import run_watchdog


def _load_matches(path: str | Path) -> list[BrokerMatch]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("matches", data if isinstance(data, list) else [])
    matches: list[BrokerMatch] = []
    for item in items:
        matches.append(
            BrokerMatch(
                broker_id=str(item.get("broker_id", "")),
                broker_name=str(item.get("broker_name", "")),
                status=str(item.get("status", "")),
                confidence=str(item.get("confidence", "unknown")),
                score=int(item.get("score", 0)),
                search_url=str(item.get("search_url", "")),
                evidence_url=str(item.get("evidence_url", "")),
                matched_fields=[str(v) for v in item.get("matched_fields", [])],
                evidence=str(item.get("evidence", "")),
                error=str(item.get("error", "")),
                checked_at=str(item.get("checked_at", "")),
            )
        )
    return matches


def cmd_init(args: argparse.Namespace) -> int:
    path = save_identity(sample_identity(), args.path, force=args.force)
    print(f"Wrote sample identity profile: {path}")
    print("Edit it with your real details, keep it private, and do not commit it.")
    return 0


def cmd_brokers_find(args: argparse.Namespace) -> int:
    identity = load_identity(args.identity)
    brokers = load_registry(args.registry)
    matches = search_brokers(brokers, identity, fetch=args.fetch, limit=args.limit, timeout=args.timeout)
    payload = matches_payload(matches)
    out = write_json(payload, args.output)
    if args.html:
        write_html_report(args.html, title="Supargus Broker Radar", matches=matches)
    print(f"Checked {len(matches)} brokers. Wrote {out}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    identity = load_identity(args.identity)
    brokers = load_registry(args.registry)
    matches = search_brokers(brokers, identity, fetch=args.fetch, limit=args.limit, timeout=args.timeout)
    findings = run_watchdog() if args.watchdog else []
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(matches_payload(matches), output_dir / "broker_matches.json")
    write_json(watchdog_payload(findings), output_dir / "watchdog.json")
    write_html_report(output_dir / "supargus_report.html", title="Supargus Privacy Report", matches=matches, findings=findings)
    print(f"Wrote scan outputs to {output_dir}")
    return 0


def cmd_takedown_prepare(args: argparse.Namespace) -> int:
    identity = load_identity(args.identity)
    brokers = load_registry(args.registry)
    matches = _load_matches(args.matches)
    requests, manifest = prepare_requests(
        matches,
        brokers,
        identity,
        args.output_dir,
        include_low_confidence=args.include_low_confidence,
    )
    print(f"Prepared {len(requests)} request draft(s). Manifest: {manifest}")
    return 0


def cmd_mail_preview(args: argparse.Namespace) -> int:
    requests = load_requests(args.requests)
    print(preview_requests(requests) or "No requests found.")
    return 0


def cmd_mail_send(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Refusing to send without --yes. Run `supargus mail preview` first.")
        return 2
    requests = load_requests(args.requests)
    config = load_smtp_config(args.smtp_config)
    sent = send_requests(requests, config, limit=args.limit)
    print(f"Sent {len(sent)} email request(s).")
    return 0


def cmd_watchdog_scan(args: argparse.Namespace) -> int:
    findings = run_watchdog()
    payload = watchdog_payload(findings)
    out = write_json(payload, args.output)
    if args.html:
        write_html_report(args.html, title="Supargus Local Watchdog", findings=findings)
    print(f"Found {len(findings)} local watchdog finding(s). Wrote {out}")
    return 0


def cmd_registry_list(args: argparse.Namespace) -> int:
    brokers = load_registry(args.registry)
    for broker in brokers:
        print(f"{broker.id}\t{broker.name}\t{broker.type}\t{','.join(broker.regions)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supargus local-first privacy watchdog")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="write a sample local identity profile")
    p_init.add_argument("path", nargs="?", default="identity.example.json")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_scan = sub.add_parser("scan", help="run broker radar and optional local watchdog")
    p_scan.add_argument("--identity", required=True)
    p_scan.add_argument("--registry", action="append")
    p_scan.add_argument("--output-dir", default="reports/latest")
    p_scan.add_argument("--fetch", action="store_true", help="attempt lightweight HTTP checks against broker search URLs")
    p_scan.add_argument("--limit", type=int)
    p_scan.add_argument("--timeout", type=float, default=12.0)
    p_scan.add_argument("--watchdog", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_brokers = sub.add_parser("brokers", help="broker registry and discovery commands")
    broker_sub = p_brokers.add_subparsers(dest="broker_command", required=True)
    p_brokers_find = broker_sub.add_parser("find", help="generate broker search evidence")
    p_brokers_find.add_argument("--identity", required=True)
    p_brokers_find.add_argument("--registry", action="append")
    p_brokers_find.add_argument("--output", default="reports/broker_matches.json")
    p_brokers_find.add_argument("--html")
    p_brokers_find.add_argument("--fetch", action="store_true")
    p_brokers_find.add_argument("--limit", type=int)
    p_brokers_find.add_argument("--timeout", type=float, default=12.0)
    p_brokers_find.set_defaults(func=cmd_brokers_find)
    p_brokers_list = broker_sub.add_parser("list", help="list configured brokers")
    p_brokers_list.add_argument("--registry", action="append")
    p_brokers_list.set_defaults(func=cmd_registry_list)

    p_takedown = sub.add_parser("takedown", help="takedown workflow commands")
    takedown_sub = p_takedown.add_subparsers(dest="takedown_command", required=True)
    p_prepare = takedown_sub.add_parser("prepare", help="generate request drafts from broker matches")
    p_prepare.add_argument("--identity", required=True)
    p_prepare.add_argument("--matches", required=True)
    p_prepare.add_argument("--registry", action="append")
    p_prepare.add_argument("--output-dir", default="reports/requests")
    p_prepare.add_argument("--include-low-confidence", action="store_true")
    p_prepare.set_defaults(func=cmd_takedown_prepare)

    p_mail = sub.add_parser("mail", help="preview or send generated request emails")
    mail_sub = p_mail.add_subparsers(dest="mail_command", required=True)
    p_preview = mail_sub.add_parser("preview", help="preview generated requests")
    p_preview.add_argument("--requests", default="reports/requests/requests.json")
    p_preview.set_defaults(func=cmd_mail_preview)
    p_send = mail_sub.add_parser("send", help="send generated email requests via SMTP")
    p_send.add_argument("--requests", default="reports/requests/requests.json")
    p_send.add_argument("--smtp-config")
    p_send.add_argument("--limit", type=int)
    p_send.add_argument("--yes", action="store_true")
    p_send.set_defaults(func=cmd_mail_send)

    p_watchdog = sub.add_parser("watchdog", help="local machine privacy checks")
    watchdog_sub = p_watchdog.add_subparsers(dest="watchdog_command", required=True)
    p_watchdog_scan = watchdog_sub.add_parser("scan", help="run local watchdog checks")
    p_watchdog_scan.add_argument("--output", default="reports/watchdog.json")
    p_watchdog_scan.add_argument("--html")
    p_watchdog_scan.set_defaults(func=cmd_watchdog_scan)

    p_app = sub.add_parser("app", help="serve the local Supargus dashboard")
    p_app.add_argument("--workspace", default="reports/latest")
    p_app.add_argument("--host", default="127.0.0.1")
    p_app.add_argument("--port", type=int, default=8765)
    p_app.set_defaults(func=lambda args: run_app(args.workspace, args.host, args.port) or 0)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
