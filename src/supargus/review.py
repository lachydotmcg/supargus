"""Review queue for approving local removal requests before sending."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import TakedownRequest, utc_now
from .tracker import request_id_for


REVIEW_QUEUE_NAME = "review_queue.json"
REVIEW_STATUSES = {"pending", "approved", "skipped"}


@dataclass
class ReviewItem:
    request_id: str
    broker_id: str
    broker_name: str
    status: str = "pending"
    delivery: str = "manual"
    to_email: str = ""
    opt_out_url: str = ""
    profile_url: str = ""
    subject: str = ""
    file_path: str = ""
    updated_at: str = ""


def _item_from_dict(data: dict) -> ReviewItem:
    return ReviewItem(
        request_id=str(data.get("request_id", "")),
        broker_id=str(data.get("broker_id", "")),
        broker_name=str(data.get("broker_name", "")),
        status=str(data.get("status", "pending")),
        delivery=str(data.get("delivery", "manual")),
        to_email=str(data.get("to_email", "")),
        opt_out_url=str(data.get("opt_out_url", "")),
        profile_url=str(data.get("profile_url", "")),
        subject=str(data.get("subject", "")),
        file_path=str(data.get("file_path", "")),
        updated_at=str(data.get("updated_at", "")),
    )


def load_review_queue(path: str | Path) -> list[ReviewItem]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else data
    return [_item_from_dict(item) for item in items]


def save_review_queue(items: list[ReviewItem], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"generated_at": utc_now(), "items": [asdict(item) for item in items]}, indent=2),
        encoding="utf-8",
    )
    return p


def build_review_queue(requests: list[TakedownRequest], path: str | Path) -> tuple[list[ReviewItem], Path]:
    existing = {item.request_id: item for item in load_review_queue(path)}
    items: list[ReviewItem] = []
    for request in requests:
        request_id = request_id_for(request)
        previous = existing.get(request_id)
        items.append(
            ReviewItem(
                request_id=request_id,
                broker_id=request.broker_id,
                broker_name=request.broker_name,
                status=previous.status if previous else "pending",
                delivery=request.delivery,
                to_email=request.to_email,
                opt_out_url=request.opt_out_url,
                profile_url=request.profile_url,
                subject=request.subject,
                file_path=request.file_path,
                updated_at=previous.updated_at if previous else utc_now(),
            )
        )
    items = sorted(items, key=lambda item: (item.status, item.broker_name, item.request_id))
    return items, save_review_queue(items, path)


def update_review_status(path: str | Path, request_id: str, status: str) -> list[ReviewItem]:
    if status not in REVIEW_STATUSES:
        raise ValueError(f"Unsupported review status: {status}")
    items = load_review_queue(path)
    changed = False
    for item in items:
        if item.request_id == request_id:
            item.status = status
            item.updated_at = utc_now()
            changed = True
    if not changed:
        raise KeyError(f"No review item found for request id: {request_id}")
    save_review_queue(items, path)
    return items


def approved_requests(requests: list[TakedownRequest], queue_path: str | Path) -> list[TakedownRequest]:
    approved_ids = {item.request_id for item in load_review_queue(queue_path) if item.status == "approved"}
    return [request for request in requests if request_id_for(request) in approved_ids]
