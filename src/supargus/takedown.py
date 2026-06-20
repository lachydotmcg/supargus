"""Takedown request generation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Broker, BrokerMatch, IdentityProfile, TakedownRequest, to_dict


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_").lower()[:80] or "request"


def _identifiers(identity: IdentityProfile) -> str:
    lines = []
    if identity.full_name:
        lines.append(f"- Name: {identity.full_name}")
    for alias in identity.aliases:
        lines.append(f"- Alias: {alias}")
    for email in identity.emails:
        lines.append(f"- Email: {email}")
    for phone in identity.phones:
        lines.append(f"- Phone: {phone}")
    for address in identity.addresses:
        if address.compact():
            lines.append(f"- Address: {address.compact()}")
    for username in identity.usernames:
        lines.append(f"- Username: {username}")
    return "\n".join(lines) if lines else "- Identifiers supplied in attached evidence bundle"


def build_request(
    broker: Broker,
    match: BrokerMatch,
    identity: IdentityProfile,
    *,
    request_type: str = "delete_opt_out",
) -> TakedownRequest:
    profile_url = match.evidence_url or match.search_url
    subject = f"Privacy request - remove my personal information from {broker.name}"
    jurisdiction = f"\nJurisdiction / privacy rights context: {identity.jurisdiction}\n" if identity.jurisdiction else ""
    body = f"""Hello {broker.name} privacy team,

I am requesting removal of my personal information from your service and any associated sale, share, publication, enrichment, or people-search products.
{jurisdiction}
Profile or search URL:
{profile_url}

Identifiers to remove:
{_identifiers(identity)}

Please confirm when this profile has been removed and my personal information is no longer sold, shared, published, or made available through your service.

If you require additional verification, please explain the minimum information required and why it is necessary.

Thank you.
"""
    delivery = "email" if broker.opt_out.contact_email else "manual_form"
    return TakedownRequest(
        broker_id=broker.id,
        broker_name=broker.name,
        request_type=request_type,
        to_email=broker.opt_out.contact_email,
        subject=subject,
        body=body.strip() + "\n",
        profile_url=profile_url,
        opt_out_url=broker.opt_out.url,
        delivery=delivery,
    )


def prepare_requests(
    matches: list[BrokerMatch],
    brokers: list[Broker],
    identity: IdentityProfile,
    output_dir: str | Path,
    *,
    include_low_confidence: bool = False,
) -> tuple[list[TakedownRequest], Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    broker_map = {broker.id: broker for broker in brokers}
    requests: list[TakedownRequest] = []
    request_only_statuses = {"needs_manual_review", "fetch_error"}

    for match in matches:
        if match.status == "no_obvious_match":
            continue
        if match.confidence in {"unknown", "low"} and not include_low_confidence and match.status not in request_only_statuses:
            continue
        broker = broker_map.get(match.broker_id)
        if not broker:
            continue
        request = build_request(broker, match, identity)
        filename = out / f"{_safe_slug(request.broker_id)}.txt"
        filename.write_text(request.body, encoding="utf-8")
        request.file_path = str(filename)
        requests.append(request)

    manifest = out / "requests.json"
    manifest.write_text(json.dumps([to_dict(request) for request in requests], indent=2), encoding="utf-8")
    return requests, manifest


def load_requests(path: str | Path) -> list[TakedownRequest]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    requests: list[TakedownRequest] = []
    for item in data:
        requests.append(
            TakedownRequest(
                broker_id=str(item.get("broker_id", "")),
                broker_name=str(item.get("broker_name", "")),
                request_type=str(item.get("request_type", "delete_opt_out")),
                to_email=str(item.get("to_email", "")),
                subject=str(item.get("subject", "")),
                body=str(item.get("body", "")),
                profile_url=str(item.get("profile_url", "")),
                opt_out_url=str(item.get("opt_out_url", "")),
                delivery=str(item.get("delivery", "manual")),
                status=str(item.get("status", "draft")),
                created_at=str(item.get("created_at", "")),
                file_path=str(item.get("file_path", "")),
            )
        )
    return requests
