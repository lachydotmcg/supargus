"""Local action plan generation from Supargus scan and removal artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .forms import load_form_queue
from .models import utc_now
from .takedown import load_requests
from .tracker import due_for_follow_up, load_tracker


ACTION_PLAN_NAME = "action_plan.json"


@dataclass
class ActionPlanItem:
    id: str
    title: str
    category: str
    priority: str
    status: str
    next_step: str
    detail: str = ""
    broker_id: str = ""
    broker_name: str = ""
    url: str = ""


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _item(
    item_id: str,
    title: str,
    category: str,
    priority: str,
    status: str,
    next_step: str,
    *,
    detail: str = "",
    broker_id: str = "",
    broker_name: str = "",
    url: str = "",
) -> ActionPlanItem:
    return ActionPlanItem(
        id=item_id,
        title=title,
        category=category,
        priority=priority,
        status=status,
        next_step=next_step,
        detail=detail,
        broker_id=broker_id,
        broker_name=broker_name,
        url=url,
    )


def build_action_plan(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace)
    broker_payload = _load_json(root / "broker_matches.json", {})
    matches = broker_payload.get("matches", []) if isinstance(broker_payload, dict) else []
    requests = load_requests(root / "requests" / "requests.json") if (root / "requests" / "requests.json").exists() else []
    forms = load_form_queue(root / "forms" / "forms.json")
    tracker = load_tracker(root / "tracker.json")
    due = due_for_follow_up(tracker)

    items: list[ActionPlanItem] = []
    for match in matches:
        status = str(match.get("status", ""))
        broker_id = str(match.get("broker_id", ""))
        broker_name = str(match.get("broker_name", broker_id))
        if status == "possible_match":
            items.append(
                _item(
                    f"match-{broker_id}",
                    f"Review likely exposure at {broker_name}",
                    "verified_scan",
                    "high",
                    "needs_review",
                    "Open the evidence URL, confirm the profile is yours, then prepare or approve the removal request.",
                    detail=f"Confidence: {match.get('confidence', 'unknown')} / Score: {match.get('score', 0)}",
                    broker_id=broker_id,
                    broker_name=broker_name,
                    url=str(match.get("evidence_url") or match.get("search_url") or ""),
                )
            )
        elif status in {"needs_manual_review", "fetch_error"}:
            items.append(
                _item(
                    f"request-only-{broker_id}",
                    f"Send request-only opt-out to {broker_name}",
                    "request_only",
                    "medium",
                    "ready_to_prepare",
                    "This broker could not be directly verified. Prepare a deletion/opt-out request if it may hold your data.",
                    detail=str(match.get("error") or match.get("evidence") or "Private or blocked search flow."),
                    broker_id=broker_id,
                    broker_name=broker_name,
                    url=str(match.get("search_url") or ""),
                )
            )

    for request in requests:
        if request.delivery == "email":
            items.append(
                _item(
                    f"email-{request.broker_id}",
                    f"Preview email request for {request.broker_name}",
                    "email_review",
                    "high",
                    "ready_to_review",
                    "Preview this draft, then send only after confirming the identifiers and destination.",
                    broker_id=request.broker_id,
                    broker_name=request.broker_name,
                    url=request.profile_url or request.opt_out_url,
                )
            )

    for task in forms:
        if task.status not in {"submitted", "confirmed"}:
            items.append(
                _item(
                    f"form-{task.broker_id}",
                    f"Complete manual form for {task.broker_name}",
                    "manual_form",
                    "high",
                    task.status,
                    "Open the broker form, paste the prepared request, then mark it submitted.",
                    broker_id=task.broker_id,
                    broker_name=task.broker_name,
                    url=task.opt_out_url,
                )
            )

    for record in due:
        items.append(
            _item(
                f"followup-{record.broker_id}",
                f"Follow up with {record.broker_name}",
                "follow_up",
                "medium",
                "due",
                "Generate a follow-up request because the broker has not been marked confirmed.",
                broker_id=record.broker_id,
                broker_name=record.broker_name,
                url=record.profile_url or record.opt_out_url,
            )
        )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    items = sorted(items, key=lambda item: (priority_rank.get(item.priority, 9), item.category, item.broker_name))
    summary = {
        "total": len(items),
        "high": sum(1 for item in items if item.priority == "high"),
        "verified_scan": sum(1 for item in items if item.category == "verified_scan"),
        "request_only": sum(1 for item in items if item.category == "request_only"),
        "email_review": sum(1 for item in items if item.category == "email_review"),
        "manual_form": sum(1 for item in items if item.category == "manual_form"),
        "follow_up": sum(1 for item in items if item.category == "follow_up"),
    }
    return {
        "generated_at": utc_now(),
        "workspace": str(root),
        "summary": summary,
        "model": "local_scan_plus_request_only",
        "note": "Public people-search hits are reviewed as evidence. Private or blocked broker databases become request-only cleanup actions.",
        "items": [asdict(item) for item in items],
    }


def write_action_plan(workspace: str | Path, output: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    root = Path(workspace)
    plan = build_action_plan(root)
    path = Path(output) if output else root / ACTION_PLAN_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan, path
