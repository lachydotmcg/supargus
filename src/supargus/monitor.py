"""Snapshot and diff support for recurring Supargus scans."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .models import BrokerMatch, to_dict, utc_now


SIGNAL_STATUSES = {"possible_match", "needs_manual_review"}


@dataclass
class MatchChange:
    broker_id: str
    broker_name: str
    change_type: str
    previous_status: str = ""
    current_status: str = ""
    previous_score: int = 0
    current_score: int = 0
    detail: str = ""
    detected_at: str = field(default_factory=utc_now)


def _match_key(match: BrokerMatch) -> str:
    return match.broker_id


def load_match_payload(path: str | Path) -> list[BrokerMatch]:
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
                broker_type=str(item.get("broker_type", "")),
                search_method=str(item.get("search_method", "")),
                action_mode=str(item.get("action_mode", "")),
            )
        )
    return matches


def diff_matches(previous: list[BrokerMatch], current: list[BrokerMatch]) -> list[MatchChange]:
    prev = {_match_key(match): match for match in previous if match.broker_id}
    cur = {_match_key(match): match for match in current if match.broker_id}
    changes: list[MatchChange] = []

    for key, current_match in sorted(cur.items()):
        previous_match = prev.get(key)
        if previous_match is None and current_match.status in SIGNAL_STATUSES:
            changes.append(
                MatchChange(
                    broker_id=current_match.broker_id,
                    broker_name=current_match.broker_name,
                    change_type="new_match",
                    current_status=current_match.status,
                    current_score=current_match.score,
                    detail="Broker appeared in the current scan but not in the previous snapshot.",
                )
            )
            continue

        if previous_match is None:
            continue

        if previous_match.status == "no_obvious_match" and current_match.status in SIGNAL_STATUSES:
            changes.append(
                MatchChange(
                    broker_id=current_match.broker_id,
                    broker_name=current_match.broker_name,
                    change_type="reappeared",
                    previous_status=previous_match.status,
                    current_status=current_match.status,
                    previous_score=previous_match.score,
                    current_score=current_match.score,
                    detail="Broker moved from no obvious match to an actionable match.",
                )
            )
        elif previous_match.status in SIGNAL_STATUSES and current_match.status == "no_obvious_match":
            changes.append(
                MatchChange(
                    broker_id=current_match.broker_id,
                    broker_name=current_match.broker_name,
                    change_type="cleared",
                    previous_status=previous_match.status,
                    current_status=current_match.status,
                    previous_score=previous_match.score,
                    current_score=current_match.score,
                    detail="Broker no longer shows an obvious match.",
                )
            )
        elif previous_match.status != current_match.status:
            changes.append(
                MatchChange(
                    broker_id=current_match.broker_id,
                    broker_name=current_match.broker_name,
                    change_type="status_changed",
                    previous_status=previous_match.status,
                    current_status=current_match.status,
                    previous_score=previous_match.score,
                    current_score=current_match.score,
                    detail="Broker status changed between scans.",
                )
            )
        elif abs(previous_match.score - current_match.score) >= 25:
            changes.append(
                MatchChange(
                    broker_id=current_match.broker_id,
                    broker_name=current_match.broker_name,
                    change_type="score_changed",
                    previous_status=previous_match.status,
                    current_status=current_match.status,
                    previous_score=previous_match.score,
                    current_score=current_match.score,
                    detail="Broker confidence score changed materially.",
                )
            )

    for key, previous_match in sorted(prev.items()):
        if key not in cur and previous_match.status in SIGNAL_STATUSES:
            changes.append(
                MatchChange(
                    broker_id=previous_match.broker_id,
                    broker_name=previous_match.broker_name,
                    change_type="missing_from_current",
                    previous_status=previous_match.status,
                    previous_score=previous_match.score,
                    detail="Broker was actionable before but is absent from the current scan payload.",
                )
            )

    return changes


def diff_payload(previous_path: str | Path, current_path: str | Path) -> dict:
    previous = load_match_payload(previous_path)
    current = load_match_payload(current_path)
    changes = diff_matches(previous, current)
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.change_type] = counts.get(change.change_type, 0) + 1
    return {
        "generated_at": utc_now(),
        "previous": str(previous_path),
        "current": str(current_path),
        "summary": {
            "changes": len(changes),
            "new_match": counts.get("new_match", 0),
            "reappeared": counts.get("reappeared", 0),
            "cleared": counts.get("cleared", 0),
            "status_changed": counts.get("status_changed", 0),
            "score_changed": counts.get("score_changed", 0),
            "missing_from_current": counts.get("missing_from_current", 0),
        },
        "changes": [to_dict(change) for change in changes],
    }


def write_diff(previous_path: str | Path, current_path: str | Path, output_path: str | Path) -> Path:
    payload = diff_payload(previous_path, current_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def save_snapshot(matches_path: str | Path, history_dir: str | Path) -> Path:
    history = Path(history_dir)
    history.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = history / f"broker_matches_{stamp}.json"
    shutil.copyfile(matches_path, dest)
    latest = history / "latest.json"
    shutil.copyfile(matches_path, latest)
    return dest


def latest_snapshot(history_dir: str | Path) -> Path | None:
    history = Path(history_dir)
    latest = history / "latest.json"
    if latest.exists():
        return latest
    snapshots = sorted(history.glob("broker_matches_*.json"))
    return snapshots[-1] if snapshots else None
