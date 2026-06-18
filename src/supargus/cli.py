"""Supargus command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .broker import search_brokers
from .app import run_app
from .bundle import export_bundle
from .config import DEFAULT_CONFIG_NAME, load_config, save_default_config
from .desktop import run_desktop_app
from .forms import build_form_queue, format_form_queue, load_form_queue, update_form_status
from .identity import load_identity, sample_identity, save_identity
from .mailer import gmail_smtp_config, load_smtp_config, preview_requests, save_smtp_config, send_requests
from .models import BrokerMatch, to_dict
from .monitor import diff_payload, latest_snapshot, save_snapshot, write_diff
from .registry import load_registry, validate_registry
from .report import matches_payload, watchdog_payload, write_html_report, write_json
from .takedown import load_requests, prepare_requests
from .tracker import due_for_follow_up, format_records, import_requests, load_tracker, prepare_followups, update_status
from .vault import open_file, seal_file, secure_delete_plaintext, vault_available
from .watchdog import run_watchdog
from .schedule import schedule_instructions
from .workflow import run_workflow


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


def cmd_mail_setup_gmail(args: argparse.Namespace) -> int:
    config = gmail_smtp_config(args.email, args.app_password, from_addr=args.from_addr)
    out = save_smtp_config(config, args.output, force=args.force)
    print(f"Wrote Gmail SMTP config: {out}")
    print("Keep this file private. Revoke the app password in Google Account settings if it is exposed.")
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


def cmd_forms_build(args: argparse.Namespace) -> int:
    requests = load_requests(args.requests)
    tasks, manifest = build_form_queue(requests, args.output)
    print(f"Prepared {len(tasks)} manual form task(s): {manifest}")
    return 0


def cmd_forms_list(args: argparse.Namespace) -> int:
    print(format_form_queue(load_form_queue(args.queue)))
    return 0


def cmd_forms_update(args: argparse.Namespace) -> int:
    tasks = update_form_status(args.queue, args.broker_id, args.status, notes=args.notes)
    print(f"Updated form queue. {len(tasks)} task(s) total.")
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


def cmd_registry_validate(args: argparse.Namespace) -> int:
    errors = validate_registry(args.registry)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("Registry OK")
    return 0


def cmd_track_import(args: argparse.Namespace) -> int:
    requests = load_requests(args.requests)
    records = import_requests(
        requests,
        args.tracker,
        status=args.status,
        follow_up_after_days=args.follow_up_days,
    )
    print(f"Tracker now has {len(records)} record(s): {args.tracker}")
    return 0


def cmd_track_list(args: argparse.Namespace) -> int:
    records = load_tracker(args.tracker)
    if args.due:
        records = due_for_follow_up(records)
    print(format_records(records))
    return 0


def cmd_track_update(args: argparse.Namespace) -> int:
    records = update_status(args.tracker, args.broker_id, args.status, notes=args.notes)
    print(f"Updated tracker. {len(records)} record(s) total.")
    return 0


def cmd_track_followup(args: argparse.Namespace) -> int:
    records = load_tracker(args.tracker)
    requests, manifest = prepare_followups(records, args.output_dir, due_only=not args.all)
    print(f"Prepared {len(requests)} follow-up draft(s). Manifest: {manifest}")
    return 0


def cmd_vault_status(args: argparse.Namespace) -> int:
    if vault_available():
        print("Vault backend available: Windows DPAPI current-user encryption")
        return 0
    print("No secure vault backend is available on this platform yet.")
    return 1


def cmd_vault_seal(args: argparse.Namespace) -> int:
    out = seal_file(args.input, args.output, force=args.force, label=args.label)
    if args.delete_plaintext:
        secure_delete_plaintext(args.input)
        print(f"Sealed {args.input} -> {out} and removed plaintext input.")
    else:
        print(f"Sealed {args.input} -> {out}")
    return 0


def cmd_vault_open(args: argparse.Namespace) -> int:
    out = open_file(args.input, args.output, force=args.force)
    print(f"Opened {args.input} -> {out}")
    return 0


def cmd_monitor_snapshot(args: argparse.Namespace) -> int:
    out = save_snapshot(args.matches, args.history_dir)
    print(f"Saved snapshot: {out}")
    return 0


def cmd_monitor_diff(args: argparse.Namespace) -> int:
    previous = args.previous
    if not previous:
        latest = latest_snapshot(args.history_dir)
        if not latest:
            print("No previous snapshot found. Run `supargus monitor snapshot` first.")
            return 2
        previous = str(latest)
    out = write_diff(previous, args.current, args.output)
    payload = diff_payload(previous, args.current)
    print(f"Wrote monitor diff: {out} ({payload['summary']['changes']} change(s))")
    return 0


def cmd_monitor_scan(args: argparse.Namespace) -> int:
    identity = load_identity(args.identity)
    brokers = load_registry(args.registry)
    matches = search_brokers(brokers, identity, fetch=args.fetch, limit=args.limit, timeout=args.timeout)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    current_path = write_json(matches_payload(matches), output_dir / "broker_matches.json")
    previous = latest_snapshot(args.history_dir)
    if previous:
        write_diff(previous, current_path, output_dir / "monitor_diff.json")
    snapshot = save_snapshot(current_path, args.history_dir)
    print(f"Wrote monitor scan to {output_dir}; snapshot: {snapshot}")
    return 0


def cmd_export_bundle(args: argparse.Namespace) -> int:
    out, manifest = export_bundle(args.workspace, args.output)
    print(f"Exported evidence bundle: {out} ({manifest['file_count']} file(s))")
    return 0


def cmd_config_init(args: argparse.Namespace) -> int:
    out = save_default_config(args.path, force=args.force)
    print(f"Wrote Supargus config: {out}")
    return 0


def cmd_workflow_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    outputs = run_workflow(config, registry_paths=args.registry)
    print("Workflow complete.")
    for key, value in outputs.items():
        print(f"{key}: {value}")
    return 0


def cmd_schedule_print(args: argparse.Namespace) -> int:
    print(schedule_instructions(args.config, time=args.time))
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
    p_brokers_validate = broker_sub.add_parser("validate", help="validate broker registry entries")
    p_brokers_validate.add_argument("--registry", action="append")
    p_brokers_validate.set_defaults(func=cmd_registry_validate)

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
    p_setup_gmail = mail_sub.add_parser("setup-gmail", help="write an SMTP config for a Gmail app password")
    p_setup_gmail.add_argument("--email", required=True)
    p_setup_gmail.add_argument("--app-password", required=True)
    p_setup_gmail.add_argument("--from-addr", default="")
    p_setup_gmail.add_argument("--output", default="workspace/smtp.gmail.json")
    p_setup_gmail.add_argument("--force", action="store_true")
    p_setup_gmail.set_defaults(func=cmd_mail_setup_gmail)
    p_send = mail_sub.add_parser("send", help="send generated email requests via SMTP")
    p_send.add_argument("--requests", default="reports/requests/requests.json")
    p_send.add_argument("--smtp-config")
    p_send.add_argument("--limit", type=int)
    p_send.add_argument("--yes", action="store_true")
    p_send.set_defaults(func=cmd_mail_send)

    p_forms = sub.add_parser("forms", help="build and track manual opt-out form tasks")
    forms_sub = p_forms.add_subparsers(dest="forms_command", required=True)
    p_forms_build = forms_sub.add_parser("build", help="build manual form tasks from request drafts")
    p_forms_build.add_argument("--requests", default="reports/requests/requests.json")
    p_forms_build.add_argument("--output", default="reports/forms/forms.json")
    p_forms_build.set_defaults(func=cmd_forms_build)
    p_forms_list = forms_sub.add_parser("list", help="list manual form tasks")
    p_forms_list.add_argument("--queue", default="reports/forms/forms.json")
    p_forms_list.set_defaults(func=cmd_forms_list)
    p_forms_update = forms_sub.add_parser("update", help="update one manual form task status")
    p_forms_update.add_argument("broker_id")
    p_forms_update.add_argument("status")
    p_forms_update.add_argument("--queue", default="reports/forms/forms.json")
    p_forms_update.add_argument("--notes", default="")
    p_forms_update.set_defaults(func=cmd_forms_update)

    p_watchdog = sub.add_parser("watchdog", help="local machine privacy checks")
    watchdog_sub = p_watchdog.add_subparsers(dest="watchdog_command", required=True)
    p_watchdog_scan = watchdog_sub.add_parser("scan", help="run local watchdog checks")
    p_watchdog_scan.add_argument("--output", default="reports/watchdog.json")
    p_watchdog_scan.add_argument("--html")
    p_watchdog_scan.set_defaults(func=cmd_watchdog_scan)

    p_track = sub.add_parser("track", help="track request status and follow-ups")
    track_sub = p_track.add_subparsers(dest="track_command", required=True)
    p_track_import = track_sub.add_parser("import", help="import request drafts into the tracker")
    p_track_import.add_argument("--requests", default="reports/requests/requests.json")
    p_track_import.add_argument("--tracker", default="reports/tracker.json")
    p_track_import.add_argument("--status", default="draft")
    p_track_import.add_argument("--follow-up-days", type=int, default=30)
    p_track_import.set_defaults(func=cmd_track_import)
    p_track_list = track_sub.add_parser("list", help="list tracked requests")
    p_track_list.add_argument("--tracker", default="reports/tracker.json")
    p_track_list.add_argument("--due", action="store_true", help="show only records due for follow-up")
    p_track_list.set_defaults(func=cmd_track_list)
    p_track_update = track_sub.add_parser("update", help="update a broker request status")
    p_track_update.add_argument("broker_id")
    p_track_update.add_argument("status")
    p_track_update.add_argument("--tracker", default="reports/tracker.json")
    p_track_update.add_argument("--notes", default="")
    p_track_update.set_defaults(func=cmd_track_update)
    p_track_followup = track_sub.add_parser("followup", help="generate follow-up drafts from tracked requests")
    p_track_followup.add_argument("--tracker", default="reports/tracker.json")
    p_track_followup.add_argument("--output-dir", default="reports/followups")
    p_track_followup.add_argument("--all", action="store_true", help="generate follow-ups for all records, not only due records")
    p_track_followup.set_defaults(func=cmd_track_followup)

    p_vault = sub.add_parser("vault", help="encrypt or open local identity vaults")
    vault_sub = p_vault.add_subparsers(dest="vault_command", required=True)
    p_vault_status = vault_sub.add_parser("status", help="show available local vault backend")
    p_vault_status.set_defaults(func=cmd_vault_status)
    p_vault_seal = vault_sub.add_parser("seal", help="encrypt a plaintext identity file")
    p_vault_seal.add_argument("input")
    p_vault_seal.add_argument("output")
    p_vault_seal.add_argument("--force", action="store_true")
    p_vault_seal.add_argument("--label", default="identity")
    p_vault_seal.add_argument("--delete-plaintext", action="store_true")
    p_vault_seal.set_defaults(func=cmd_vault_seal)
    p_vault_open = vault_sub.add_parser("open", help="decrypt a vault file to a plaintext file")
    p_vault_open.add_argument("input")
    p_vault_open.add_argument("output")
    p_vault_open.add_argument("--force", action="store_true")
    p_vault_open.set_defaults(func=cmd_vault_open)

    p_monitor = sub.add_parser("monitor", help="snapshot and diff recurring broker scans")
    monitor_sub = p_monitor.add_subparsers(dest="monitor_command", required=True)
    p_monitor_snapshot = monitor_sub.add_parser("snapshot", help="save a broker match payload as the latest snapshot")
    p_monitor_snapshot.add_argument("--matches", default="reports/broker_matches.json")
    p_monitor_snapshot.add_argument("--history-dir", default="reports/history")
    p_monitor_snapshot.set_defaults(func=cmd_monitor_snapshot)
    p_monitor_diff = monitor_sub.add_parser("diff", help="compare previous and current broker match payloads")
    p_monitor_diff.add_argument("--previous")
    p_monitor_diff.add_argument("--current", required=True)
    p_monitor_diff.add_argument("--history-dir", default="reports/history")
    p_monitor_diff.add_argument("--output", default="reports/monitor_diff.json")
    p_monitor_diff.set_defaults(func=cmd_monitor_diff)
    p_monitor_scan = monitor_sub.add_parser("scan", help="run broker radar, diff against latest snapshot, and save a new snapshot")
    p_monitor_scan.add_argument("--identity", required=True)
    p_monitor_scan.add_argument("--registry", action="append")
    p_monitor_scan.add_argument("--output-dir", default="reports/latest")
    p_monitor_scan.add_argument("--history-dir", default="reports/history")
    p_monitor_scan.add_argument("--fetch", action="store_true")
    p_monitor_scan.add_argument("--limit", type=int)
    p_monitor_scan.add_argument("--timeout", type=float, default=12.0)
    p_monitor_scan.set_defaults(func=cmd_monitor_scan)

    p_export = sub.add_parser("export", help="export evidence and workflow artifacts")
    export_sub = p_export.add_subparsers(dest="export_command", required=True)
    p_export_bundle = export_sub.add_parser("bundle", help="write a zipped evidence bundle")
    p_export_bundle.add_argument("--workspace", default="reports/latest")
    p_export_bundle.add_argument("--output", default="reports/supargus_evidence_bundle.zip")
    p_export_bundle.set_defaults(func=cmd_export_bundle)

    p_config = sub.add_parser("config", help="manage local Supargus workflow config")
    config_sub = p_config.add_subparsers(dest="config_command", required=True)
    p_config_init = config_sub.add_parser("init", help="write a sample workflow config")
    p_config_init.add_argument("path", nargs="?", default=DEFAULT_CONFIG_NAME)
    p_config_init.add_argument("--force", action="store_true")
    p_config_init.set_defaults(func=cmd_config_init)

    p_workflow = sub.add_parser("workflow", help="run the local recurring Supargus workflow")
    workflow_sub = p_workflow.add_subparsers(dest="workflow_command", required=True)
    p_workflow_run = workflow_sub.add_parser("run", help="run broker scan, monitor diff, watchdog, drafts, tracker, followups, and bundle")
    p_workflow_run.add_argument("--config", default=DEFAULT_CONFIG_NAME)
    p_workflow_run.add_argument("--registry", action="append")
    p_workflow_run.set_defaults(func=cmd_workflow_run)

    p_schedule = sub.add_parser("schedule", help="print local scheduling commands")
    schedule_sub = p_schedule.add_subparsers(dest="schedule_command", required=True)
    p_schedule_print = schedule_sub.add_parser("print", help="print Windows Task Scheduler and cron commands")
    p_schedule_print.add_argument("--config", default=DEFAULT_CONFIG_NAME)
    p_schedule_print.add_argument("--time", default="09:00")
    p_schedule_print.set_defaults(func=cmd_schedule_print)

    p_app = sub.add_parser("app", help="open the Supargus desktop app")
    p_app.add_argument("--workspace", default="workspace")
    p_app.set_defaults(func=lambda args: run_desktop_app(args.workspace))

    p_web = sub.add_parser("web", help="serve the fallback local web console")
    p_web.add_argument("--workspace", default="reports/latest")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8765)
    p_web.set_defaults(func=lambda args: run_app(args.workspace, args.host, args.port) or 0)

    p_app_legacy = sub.add_parser("dashboard", help=argparse.SUPPRESS)
    p_app_legacy.add_argument("--workspace", default="reports/latest")
    p_app_legacy.add_argument("--host", default="127.0.0.1")
    p_app_legacy.add_argument("--port", type=int, default=8765)
    p_app_legacy.set_defaults(func=lambda args: run_app(args.workspace, args.host, args.port) or 0)

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
