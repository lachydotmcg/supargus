"""Compliance tracker for privacy requests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import TakedownRequest, utc_now


DEFAULT_FOLLOW_UP_DAYS = 30


@dataclass
class TrackerRecord:
    broker_id: str
    broker_name: str
    status: str
    request_type: str = "delete_opt_out"
    delivery: str = "manual"
    to_email: str = ""
    opt_out_url: str = ""
    profile_url: str = ""
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
    return TrackerRecord(
        broker_id=str(data.get("broker_id", "")),
        broker_name=str(data.get("broker_name", "")),
        status=str(data.get("status", "draft")),
        request_type=str(data.get("request_type", "delete_opt_out")),
        delivery=str(data.get("delivery", "manual")),
        to_email=str(data.get("to_email", "")),
        opt_out_url=str(data.get("opt_out_url", "")),
        profile_url=str(data.get("profile_url", "")),
        created_at=str(data.get("created_at", utc_now())),
        updated_at=str(data.get("updated_at", utc_now())),
        follow_up_after_days=int(data.get("follow_up_after_days", DEFAULT_FOLLOW_UP_DAYS)),
        notes=str(data.get("notes", "")),
    )


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
        "records": [record.__dict__ for record in records],
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
        record = TrackerRecord(
            broker_id=request.broker_id,
            broker_name=request.broker_name,
            status=status,
            request_type=request.request_type,
            delivery=request.delivery,
            to_email=request.to_email,
            opt_out_url=request.opt_out_url,
            profile_url=request.profile_url,
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
        lines.append(f"{record.broker_id}\t{record.status}\t{record.broker_name}\t{destination}")
    return "\n".join(lines)

