"""Manual opt-out form assist queue."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import TakedownRequest, utc_now


@dataclass
class FormTask:
    broker_id: str
    broker_name: str
    opt_out_url: str
    profile_url: str = ""
    request_body: str = ""
    status: str = "needs_form"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    notes: str = ""


def _task_key(task: FormTask) -> str:
    return f"{task.broker_id}:{task.opt_out_url}:{task.profile_url}"


def task_from_request(request: TakedownRequest) -> FormTask | None:
    if request.to_email:
        return None
    if not request.opt_out_url:
        return None
    return FormTask(
        broker_id=request.broker_id,
        broker_name=request.broker_name,
        opt_out_url=request.opt_out_url,
        profile_url=request.profile_url,
        request_body=request.body,
    )


def load_form_queue(path: str | Path) -> list[FormTask]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("tasks", data if isinstance(data, list) else [])
    return [
        FormTask(
            broker_id=str(item.get("broker_id", "")),
            broker_name=str(item.get("broker_name", "")),
            opt_out_url=str(item.get("opt_out_url", "")),
            profile_url=str(item.get("profile_url", "")),
            request_body=str(item.get("request_body", "")),
            status=str(item.get("status", "needs_form")),
            created_at=str(item.get("created_at", utc_now())),
            updated_at=str(item.get("updated_at", utc_now())),
            notes=str(item.get("notes", "")),
        )
        for item in items
    ]


def save_form_queue(tasks: list[FormTask], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_now(),
        "tasks": [task.__dict__ for task in tasks],
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def build_form_queue(requests: list[TakedownRequest], path: str | Path) -> tuple[list[FormTask], Path]:
    existing = load_form_queue(path)
    by_key = {_task_key(task): task for task in existing}
    for request in requests:
        task = task_from_request(request)
        if not task:
            continue
        by_key.setdefault(_task_key(task), task)
    tasks = sorted(by_key.values(), key=lambda item: (item.broker_name.lower(), item.opt_out_url))
    return tasks, save_form_queue(tasks, path)


def update_form_status(path: str | Path, broker_id: str, status: str, *, notes: str = "") -> list[FormTask]:
    tasks = load_form_queue(path)
    changed = False
    for task in tasks:
        if task.broker_id == broker_id:
            task.status = status
            task.updated_at = utc_now()
            if notes:
                task.notes = notes
            changed = True
    if not changed:
        raise KeyError(f"No form task found for broker id: {broker_id}")
    save_form_queue(tasks, path)
    return tasks


def format_form_queue(tasks: list[FormTask]) -> str:
    if not tasks:
        return "No manual form tasks."
    lines = []
    for task in tasks:
        destination = re.sub(r"\s+", " ", task.opt_out_url).strip()
        lines.append(f"{task.broker_id}\t{task.status}\t{task.broker_name}\t{destination}")
    return "\n".join(lines)

