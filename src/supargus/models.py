"""Shared data models for Supargus."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return dict(getattr(value, "__dict__", {}))


@dataclass
class Address:
    line1: str = ""
    line2: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = ""

    def compact(self) -> str:
        parts = [self.line1, self.line2, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)


@dataclass
class IdentityProfile:
    full_name: str = ""
    aliases: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    addresses: list[Address] = field(default_factory=list)
    usernames: list[str] = field(default_factory=list)
    jurisdiction: str = ""
    notes: str = ""

    def primary_email(self) -> str:
        return self.emails[0] if self.emails else ""

    def primary_address(self) -> Address:
        return self.addresses[0] if self.addresses else Address()

    def search_names(self) -> list[str]:
        names = [self.full_name, *self.aliases]
        return [name for name in names if name]


@dataclass
class BrokerSearch:
    method: str
    url: str
    query_fields: list[str] = field(default_factory=list)


@dataclass
class BrokerOptOut:
    url: str = ""
    method: str = "form"
    contact_email: str = ""
    requires: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Broker:
    id: str
    name: str
    type: str
    regions: list[str]
    search: BrokerSearch
    opt_out: BrokerOptOut
    notes: list[str] = field(default_factory=list)


@dataclass
class BrokerMatch:
    broker_id: str
    broker_name: str
    status: str
    confidence: str
    score: int
    search_url: str
    evidence_url: str = ""
    matched_fields: list[str] = field(default_factory=list)
    evidence: str = ""
    error: str = ""
    checked_at: str = field(default_factory=utc_now)
    broker_type: str = ""
    search_method: str = ""
    action_mode: str = ""


@dataclass
class TakedownRequest:
    broker_id: str
    broker_name: str
    request_type: str
    to_email: str
    subject: str
    body: str
    profile_url: str = ""
    opt_out_url: str = ""
    delivery: str = "manual"
    status: str = "draft"
    created_at: str = field(default_factory=utc_now)
    file_path: str = ""


@dataclass
class WatchdogFinding:
    id: str
    title: str
    severity: str
    category: str
    detail: str
    evidence: str = ""
    remediation: str = ""
    detected_at: str = field(default_factory=utc_now)
