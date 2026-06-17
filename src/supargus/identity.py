"""Identity profile loading and sample generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Address, IdentityProfile, to_dict


def sample_identity() -> IdentityProfile:
    return IdentityProfile(
        full_name="Jane Example",
        aliases=["J. Example"],
        emails=["jane@example.com"],
        phones=["+15551234567"],
        addresses=[
            Address(
                line1="123 Example Street",
                city="Austin",
                region="TX",
                postal_code="78701",
                country="US",
            )
        ],
        usernames=["janeexample"],
        jurisdiction="US-CA",
        notes="Replace this file with your own details. Keep it private.",
    )


def _address_from_dict(data: dict[str, Any]) -> Address:
    return Address(
        line1=str(data.get("line1", "")),
        line2=str(data.get("line2", "")),
        city=str(data.get("city", "")),
        region=str(data.get("region", "")),
        postal_code=str(data.get("postal_code", "")),
        country=str(data.get("country", "")),
    )


def identity_from_dict(data: dict[str, Any]) -> IdentityProfile:
    addresses = data.get("addresses") or []
    return IdentityProfile(
        full_name=str(data.get("full_name", "")),
        aliases=[str(v) for v in data.get("aliases", [])],
        emails=[str(v) for v in data.get("emails", [])],
        phones=[str(v) for v in data.get("phones", [])],
        addresses=[_address_from_dict(v) for v in addresses if isinstance(v, dict)],
        usernames=[str(v) for v in data.get("usernames", [])],
        jurisdiction=str(data.get("jurisdiction", "")),
        notes=str(data.get("notes", "")),
    )


def load_identity(path: str | Path) -> IdentityProfile:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "YAML identity files require the optional dependency: pip install supargus[yaml]"
            ) from exc
        data = yaml.safe_load(raw) or {}
    else:
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("identity file must contain an object")
    return identity_from_dict(data)


def save_identity(profile: IdentityProfile, path: str | Path, *, force: bool = False) -> Path:
    p = Path(path)
    if p.exists() and not force:
        raise FileExistsError(f"{p} already exists; pass --force to overwrite")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(to_dict(profile), indent=2), encoding="utf-8")
    return p

