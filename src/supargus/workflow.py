"""One-command local workflow runner."""

from __future__ import annotations

from pathlib import Path

from .broker import search_brokers
from .bundle import export_bundle
from .config import WorkflowConfig
from .forms import build_form_queue
from .identity import load_identity
from .monitor import latest_snapshot, save_snapshot, write_diff
from .registry import load_registry
from .report import matches_payload, watchdog_payload, write_html_report, write_json
from .takedown import prepare_requests
from .tracker import import_requests, load_tracker, prepare_followups
from .watchdog import run_watchdog


def run_workflow(config: WorkflowConfig, *, registry_paths: list[str] | None = None) -> dict:
    workspace = Path(config.workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    identity = load_identity(config.identity)
    brokers = load_registry(registry_paths)
    matches = search_brokers(
        brokers,
        identity,
        fetch=config.fetch,
        limit=config.limit,
    )

    outputs: dict[str, str | int | bool] = {}
    broker_path = write_json(matches_payload(matches), workspace / "broker_matches.json")
    outputs["broker_matches"] = str(broker_path)

    previous = latest_snapshot(config.history_dir)
    if previous:
        diff_path = write_diff(previous, broker_path, workspace / "monitor_diff.json")
        outputs["monitor_diff"] = str(diff_path)
    snapshot = save_snapshot(broker_path, config.history_dir)
    outputs["snapshot"] = str(snapshot)

    if config.watchdog:
        findings = run_watchdog()
        watchdog_path = write_json(watchdog_payload(findings), workspace / "watchdog.json")
        outputs["watchdog"] = str(watchdog_path)
        outputs["watchdog_findings"] = len(findings)
    else:
        findings = []

    html_path = write_html_report(
        workspace / "supargus_report.html",
        title="Supargus Privacy Report",
        matches=matches,
        findings=findings,
    )
    outputs["html_report"] = str(html_path)

    if config.prepare_requests:
        requests, manifest = prepare_requests(
            matches,
            brokers,
            identity,
            config.requests_dir,
            include_low_confidence=config.include_low_confidence,
        )
        outputs["request_manifest"] = str(manifest)
        outputs["request_count"] = len(requests)
        form_tasks, form_manifest = build_form_queue(requests, workspace / "forms" / "forms.json")
        outputs["form_queue"] = str(form_manifest)
        outputs["form_tasks"] = len(form_tasks)
        if config.import_tracker:
            records = import_requests(requests, config.tracker)
            outputs["tracker"] = str(config.tracker)
            outputs["tracker_records"] = len(records)

    if config.followups:
        records = load_tracker(config.tracker)
        followups, manifest = prepare_followups(records, config.followups_dir)
        outputs["followup_manifest"] = str(manifest)
        outputs["followup_count"] = len(followups)

    if config.export_bundle:
        bundle_path, manifest = export_bundle(workspace, config.bundle_path)
        outputs["bundle"] = str(bundle_path)
        outputs["bundle_files"] = int(manifest["file_count"])

    return outputs
