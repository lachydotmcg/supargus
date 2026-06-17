"""Broker registry loading."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from .models import Broker, BrokerOptOut, BrokerSearch


def _broker_from_dict(data: dict[str, Any]) -> Broker:
    search_data = data.get("search") or {}
    opt_data = data.get("opt_out") or {}
    return Broker(
        id=str(data["id"]),
        name=str(data["name"]),
        type=str(data.get("type", "data_broker")),
        regions=[str(v) for v in data.get("regions", [])],
        search=BrokerSearch(
            method=str(search_data.get("method", "manual")),
            url=str(search_data.get("url", "")),
            query_fields=[str(v) for v in search_data.get("query_fields", [])],
        ),
        opt_out=BrokerOptOut(
            url=str(opt_data.get("url", "")),
            method=str(opt_data.get("method", "form")),
            contact_email=str(opt_data.get("contact_email", "")),
            requires=[str(v) for v in opt_data.get("requires", [])],
            notes=[str(v) for v in opt_data.get("notes", [])],
        ),
        notes=[str(v) for v in data.get("notes", [])],
    )


def load_broker_file(path: str | Path) -> list[Broker]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("brokers", [])
    else:
        items = data
    return [_broker_from_dict(item) for item in items]


def load_default_brokers() -> list[Broker]:
    default_path = files("supargus").joinpath("data/default_brokers.json")
    data = json.loads(default_path.read_text(encoding="utf-8"))
    return [_broker_from_dict(item) for item in data["brokers"]]


def load_registry(extra_paths: list[str] | None = None) -> list[Broker]:
    brokers = load_default_brokers()
    for path in extra_paths or []:
        brokers.extend(load_broker_file(path))

    seen: set[str] = set()
    unique: list[Broker] = []
    for broker in brokers:
        if broker.id in seen:
            continue
        seen.add(broker.id)
        unique.append(broker)
    return unique

