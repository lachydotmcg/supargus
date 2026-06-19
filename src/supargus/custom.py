"""Custom removal targets for URLs outside the broker registry."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .models import IdentityProfile, TakedownRequest, to_dict, utc_now


@dataclass
class CustomRemovalTarget:
    id: str
    url: str
    domain: str
    reason: str = "custom_removal"
    status: str = "needs_review"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    notes: str = ""


def _target_id(url: str) -> str:
    digest = hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:10]
    return f"custom_{digest}"


def _domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path.split("/")[0]
    return host.lower().removeprefix("www.") or "custom_target"


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_").lower()[:80] or "custom"


def _target_from_dict(data: dict) -> CustomRemovalTarget:
    return CustomRemovalTarget(
        id=str(data.get("id", "")),
        url=str(data.get("url", "")),
        domain=str(data.get("domain", "")),
        reason=str(data.get("reason", "custom_removal")),
        status=str(data.get("status", "needs_review")),
        created_at=str(data.get("created_at", utc_now())),
        updated_at=str(data.get("updated_at", utc_now())),
        notes=str(data.get("notes", "")),
    )


def load_custom_targets(path: str | Path) -> list[CustomRemovalTarget]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("targets", data if isinstance(data, list) else [])
    return [_target_from_dict(item) for item in items]


def save_custom_targets(targets: list[CustomRemovalTarget], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_now(),
        "targets": [target.__dict__ for target in targets],
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def add_custom_target(path: str | Path, url: str, *, reason: str = "custom_removal", notes: str = "") -> CustomRemovalTarget:
    normalized = url.strip()
    if not normalized:
        raise ValueError("URL is required")
    if "://" not in normalized:
        normalized = f"https://{normalized}"
    target = CustomRemovalTarget(
        id=_target_id(normalized),
        url=normalized,
        domain=_domain(normalized),
        reason=reason,
        notes=notes,
    )
    targets = load_custom_targets(path)
    by_id = {item.id: item for item in targets}
    by_id[target.id] = target
    save_custom_targets(sorted(by_id.values(), key=lambda item: item.domain), path)
    return target


def update_custom_status(path: str | Path, target_id: str, status: str, *, notes: str = "") -> list[CustomRemovalTarget]:
    targets = load_custom_targets(path)
    changed = False
    for target in targets:
        if target.id == target_id:
            target.status = status
            target.updated_at = utc_now()
            if notes:
                target.notes = notes
            changed = True
    if not changed:
        raise KeyError(f"No custom target found for id: {target_id}")
    save_custom_targets(targets, path)
    return targets


def format_custom_targets(targets: list[CustomRemovalTarget]) -> str:
    if not targets:
        return "No custom removal targets."
    return "\n".join(f"{target.id}\t{target.status}\t{target.domain}\t{target.url}" for target in targets)


def build_custom_request(target: CustomRemovalTarget, identity: IdentityProfile) -> TakedownRequest:
    subject = f"Privacy request - remove my personal information from {target.domain}"
    identifiers = []
    if identity.full_name:
        identifiers.append(f"- Name: {identity.full_name}")
    for email in identity.emails:
        identifiers.append(f"- Email: {email}")
    for phone in identity.phones:
        identifiers.append(f"- Phone: {phone}")
    for address in identity.addresses:
        if address.compact():
            identifiers.append(f"- Address: {address.compact()}")
    identifier_text = "\n".join(identifiers) if identifiers else "- Identifiers supplied in local evidence"
    body = f"""Hello,

I am requesting removal of my personal information from the following page or service:

{target.url}

Reason:
{target.reason}

Identifiers to remove:
{identifier_text}

Please confirm once my personal information has been removed and is no longer sold, shared, published, indexed, or made available through your service.

If you require additional verification, please explain the minimum information required and why it is necessary.

Thank you.
"""
    return TakedownRequest(
        broker_id=target.id,
        broker_name=target.domain,
        request_type="custom_removal",
        to_email="",
        subject=subject,
        body=body.strip() + "\n",
        profile_url=target.url,
        opt_out_url=target.url,
        delivery="manual_form",
        status="draft",
    )


def prepare_custom_requests(
    targets: list[CustomRemovalTarget],
    identity: IdentityProfile,
    output_dir: str | Path,
) -> tuple[list[TakedownRequest], Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    requests: list[TakedownRequest] = []
    for target in targets:
        request = build_custom_request(target, identity)
        filename = out / f"{_safe_slug(request.broker_id)}.txt"
        filename.write_text(request.body, encoding="utf-8")
        request.file_path = str(filename)
        requests.append(request)

    manifest = out / "requests.json"
    manifest.write_text(json.dumps([to_dict(request) for request in requests], indent=2), encoding="utf-8")
    return requests, manifest

