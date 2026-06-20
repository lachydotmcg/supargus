"""Compliance tracker for privacy requests."""

from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import TakedownRequest, to_dict, utc_now


DEFAULT_FOLLOW_UP_DAYS = 30


@dataclass
class TrackerRecord:
    broker_id: str
    broker_name: str
    status: str
    request_id: str = ""
    request_type: str = "delete_opt_out"
    delivery: str = "manual"
    to_email: str = ""
    opt_out_url: str = ""
    profile_url: str = ""
    requested_data: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    follow_up_after_days: int = DEFAULT_FOLLOW_UP_DAYS
    notes: str = ""

    @property
    def key(self) -> str:
        return f"{self.broker_id}:{self.profile_url or self.opt_out_url or self.to_email}"


def _parse_dt(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return datetime.now(timezone.utc)


def _record_from_dict(data: dict) -> TrackerRecord:
    record = TrackerRecord(
        broker_id=str(data.get("broker_id", "")),
        broker_name=str(data.get("broker_name", "")),
        status=str(data.get("status", "draft")),
        request_id=str(data.get("request_id", "")),
        request_type=str(data.get("request_type", "delete_opt_out")),
        delivery=str(data.get("delivery", "manual")),
        to_email=str(data.get("to_email", "")),
        opt_out_url=str(data.get("opt_out_url", "")),
        profile_url=str(data.get("profile_url", "")),
        requested_data=str(data.get("requested_data", "")),
        created_at=str(data.get("created_at", utc_now())),
        updated_at=str(data.get("updated_at", utc_now())),
        follow_up_after_days=int(data.get("follow_up_after_days", DEFAULT_FOLLOW_UP_DAYS)),
        notes=str(data.get("notes", "")),
    )
    if not record.request_id:
        record.request_id = request_id_for(record)
    return record


def request_id_for(value: TrackerRecord | TakedownRequest) -> str:
    raw = "|".join(
        [
            value.broker_id,
            value.profile_url,
            value.opt_out_url,
            getattr(value, "to_email", ""),
            getattr(value, "created_at", ""),
        ]
    )
    return f"SG-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:10].upper()}"


def _requested_data_from_body(body: str) -> str:
    marker = "Identifiers to remove:"
    if marker not in body:
        return ""
    tail = body.split(marker, 1)[1]
    lines: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.startswith("Please confirm"):
            break
        lines.append(stripped)
    return "\n".join(lines)


def next_follow_up_at(record: TrackerRecord) -> str:
    updated = _parse_dt(record.updated_at)
    return (updated + timedelta(days=record.follow_up_after_days)).isoformat(timespec="seconds")


def status_explanation(record: TrackerRecord) -> str:
    if record.status == "draft":
        return "Draft created locally. Review the request before submitting or sending."
    if record.status in {"sent", "submitted", "waiting"}:
        return "Request is in progress. Supargus will flag it for follow-up if there is no response."
    if record.status == "confirmed":
        return "Broker has confirmed completion in your tracker."
    if record.status == "denied":
        return "Broker denied or rejected the request. Review notes and consider escalation."
    return "Status is tracked locally from your latest action."


def timeline_for_record(record: TrackerRecord) -> list[dict[str, Any]]:
    submitted = record.status in {"sent", "submitted", "waiting", "confirmed", "denied"}
    complete = record.status == "confirmed"
    denied = record.status == "denied"
    return [
        {"label": "Draft created", "state": "complete", "at": record.created_at},
        {
            "label": "Request submitted",
            "state": "complete" if submitted else "next",
            "at": record.updated_at if submitted else "",
        },
        {
            "label": "Follow-up window",
            "state": "complete" if complete else "blocked" if denied else "future",
            "at": next_follow_up_at(record),
        },
        {
            "label": "Removal confirmed",
            "state": "complete" if complete else "blocked" if denied else "future",
            "at": record.updated_at if complete else "",
        },
    ]


def record_payload(record: TrackerRecord) -> dict[str, Any]:
    payload = to_dict(record)
    payload["request_id"] = record.request_id or request_id_for(record)
    payload["status_explanation"] = status_explanation(record)
    payload["next_follow_up_at"] = next_follow_up_at(record)
    payload["timeline"] = timeline_for_record(record)
    return payload


def load_tracker(path: str | Path) -> list[TrackerRecord]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("records", [])
    else:
        items = data
    return [_record_from_dict(item) for item in items]


def save_tracker(records: list[TrackerRecord], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_now(),
        "records": [record_payload(record) for record in records],
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def import_requests(
    requests: list[TakedownRequest],
    tracker_path: str | Path,
    *,
    status: str = "draft",
    follow_up_after_days: int = DEFAULT_FOLLOW_UP_DAYS,
) -> list[TrackerRecord]:
    existing = load_tracker(tracker_path)
    by_key = {record.key: record for record in existing}
    for request in requests:
        request_id = request_id_for(request)
        record = TrackerRecord(
            broker_id=request.broker_id,
            broker_name=request.broker_name,
            status=status,
            request_id=request_id,
            request_type=request.request_type,
            delivery=request.delivery,
            to_email=request.to_email,
            opt_out_url=request.opt_out_url,
            profile_url=request.profile_url,
            requested_data=_requested_data_from_body(request.body),
            created_at=request.created_at,
            updated_at=utc_now(),
            follow_up_after_days=follow_up_after_days,
        )
        by_key[record.key] = record
    records = sorted(by_key.values(), key=lambda item: (item.broker_name, item.profile_url))
    save_tracker(records, tracker_path)
    return records


def update_status(
    tracker_path: str | Path,
    broker_id: str,
    status: str,
    *,
    notes: str = "",
) -> list[TrackerRecord]:
    records = load_tracker(tracker_path)
    changed = False
    for record in records:
        if record.broker_id == broker_id:
            record.status = status
            record.updated_at = utc_now()
            if notes:
                record.notes = notes
            changed = True
    if not changed:
        raise KeyError(f"No tracker record found for broker id: {broker_id}")
    save_tracker(records, tracker_path)
    return records


def due_for_follow_up(records: list[TrackerRecord], *, now: datetime | None = None) -> list[TrackerRecord]:
    now = now or datetime.now(timezone.utc)
    due_statuses = {"sent", "submitted", "waiting", "draft"}
    due: list[TrackerRecord] = []
    for record in records:
        if record.status not in due_statuses:
            continue
        updated = _parse_dt(record.updated_at)
        if updated + timedelta(days=record.follow_up_after_days) <= now:
            due.append(record)
    return due


def format_records(records: list[TrackerRecord]) -> str:
    if not records:
        return "No tracker records."
    lines = []
    for record in records:
        destination = record.to_email or record.opt_out_url or "manual"
        lines.append(f"{record.request_id or request_id_for(record)}\t{record.broker_id}\t{record.status}\t{record.broker_name}\t{destination}")
    return "\n".join(lines)


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_").lower()[:80] or "followup"


def build_followup_request(record: TrackerRecord) -> TakedownRequest:
    destination = record.to_email
    contact_line = (
        f"I previously submitted this request through your opt-out form: {record.opt_out_url}"
        if not destination and record.opt_out_url
        else "I previously submitted a privacy request."
    )
    profile = f"\nProfile or search URL:\n{record.profile_url}\n" if record.profile_url else ""
    notes = f"\nPrior notes/status:\n{record.notes}\n" if record.notes else ""
    subject = f"Follow-up: privacy request for {record.broker_name}"
    body = f"""Hello {record.broker_name} privacy team,

I am following up on my previous privacy request.

{contact_line}

Original request status in my records: {record.status}
Original request created: {record.created_at}
Last updated: {record.updated_at}
{profile}{notes}
Please confirm whether my personal information has been removed and is no longer sold, shared, published, or made available through your service.

If additional verification is required, please explain the minimum information required and why it is necessary.

Thank you.
"""
    return TakedownRequest(
        broker_id=record.broker_id,
        broker_name=record.broker_name,
        request_type="follow_up",
        to_email=destination,
        subject=subject,
        body=body.strip() + "\n",
        profile_url=record.profile_url,
        opt_out_url=record.opt_out_url,
        delivery="email" if destination else "manual_form",
    )


def prepare_followups(
    records: list[TrackerRecord],
    output_dir: str | Path,
    *,
    due_only: bool = True,
) -> tuple[list[TakedownRequest], Path]:
    selected = due_for_follow_up(records) if due_only else records
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    requests: list[TakedownRequest] = []
    for record in selected:
        request = build_followup_request(record)
        filename = out / f"{_safe_slug(request.broker_id)}_followup.txt"
        filename.write_text(request.body, encoding="utf-8")
        request.file_path = str(filename)
        requests.append(request)

    manifest = out / "requests.json"
    manifest.write_text(json.dumps([to_dict(request) for request in requests], indent=2), encoding="utf-8")
    return requests, manifest
