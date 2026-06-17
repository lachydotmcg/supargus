"""Broker registry loading."""

from __future__ import annotations

import json
import string
from importlib.resources import files
from pathlib import Path
from typing import Any

from .models import Broker, BrokerOptOut, BrokerSearch


ALLOWED_SEARCH_METHODS = {"url", "manual", "browser"}
ALLOWED_OPT_OUT_METHODS = {"form", "email", "manual", "browser"}
ALLOWED_PLACEHOLDERS = {
    "name",
    "first",
    "last",
    "email",
    "phone",
    "city",
    "state",
    "region",
    "postal_code",
    "country",
    "username",
}


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


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def validate_brokers(brokers: list[Broker]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for idx, broker in enumerate(brokers, 1):
        prefix = f"{broker.id or f'broker[{idx}]'}"
        if not broker.id:
            errors.append(f"{prefix}: missing id")
        elif broker.id in seen:
            errors.append(f"{prefix}: duplicate id")
        seen.add(broker.id)

        if not broker.name:
            errors.append(f"{prefix}: missing name")
        if broker.search.method not in ALLOWED_SEARCH_METHODS:
            errors.append(f"{prefix}: unsupported search method {broker.search.method!r}")
        if broker.opt_out.method not in ALLOWED_OPT_OUT_METHODS:
            errors.append(f"{prefix}: unsupported opt-out method {broker.opt_out.method!r}")
        if broker.search.method in {"url", "browser"} and not broker.search.url:
            errors.append(f"{prefix}: search URL required for {broker.search.method} search")
        if not broker.opt_out.url and not broker.opt_out.contact_email:
            errors.append(f"{prefix}: opt-out URL or contact email required")

        unknown = _placeholders(broker.search.url) - ALLOWED_PLACEHOLDERS
        for placeholder in sorted(unknown):
            errors.append(f"{prefix}: unknown search URL placeholder {{{placeholder}}}")

        for field in broker.search.query_fields:
            if field not in ALLOWED_PLACEHOLDERS:
                errors.append(f"{prefix}: unknown query field {field!r}")
    return errors


def validate_registry(extra_paths: list[str] | None = None) -> list[str]:
    return validate_brokers(load_registry(extra_paths))
