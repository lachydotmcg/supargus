"""Broker search planning and lightweight evidence checks."""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

from .models import Broker, BrokerMatch, IdentityProfile


USER_AGENT = "Supargus/0.1 local-first privacy watchdog"


def _tokens(identity: IdentityProfile) -> dict[str, str]:
    address = identity.primary_address()
    return {
        "name": identity.full_name,
        "first": identity.full_name.split()[0] if identity.full_name else "",
        "last": identity.full_name.split()[-1] if identity.full_name else "",
        "email": identity.primary_email(),
        "phone": identity.phones[0] if identity.phones else "",
        "city": address.city,
        "state": address.region,
        "region": address.region,
        "postal_code": address.postal_code,
        "country": address.country,
        "username": identity.usernames[0] if identity.usernames else "",
    }


def build_search_url(template: str, identity: IdentityProfile) -> str:
    values = {key: urllib.parse.quote_plus(value) for key, value in _tokens(identity).items()}
    return template.format(**values)


def _identity_needles(identity: IdentityProfile) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for name in identity.search_names():
        candidates.append(("name", name))
    for email in identity.emails:
        candidates.append(("email", email))
    for phone in identity.phones:
        candidates.append(("phone", phone))
    for address in identity.addresses:
        candidates.extend(
            [
                ("city", address.city),
                ("state", address.region),
                ("postal_code", address.postal_code),
            ]
        )
    for username in identity.usernames:
        candidates.append(("username", username))

    seen: set[tuple[str, str]] = set()
    needles: list[tuple[str, str]] = []
    for key, value in candidates:
        normalized = value.strip().lower()
        if not normalized or (key, normalized) in seen:
            continue
        seen.add((key, normalized))
        needles.append((key, normalized))
    return needles


def _fetch(url: str, timeout: float = 12.0) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(400_000)
    except urllib.error.HTTPError as exc:
        return "", f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return "", str(exc.reason)
    except TimeoutError:
        return "", "request timed out"

    if "text" not in content_type and "html" not in content_type and not raw.strip().startswith(b"<"):
        return "", f"unsupported content type: {content_type or 'unknown'}"
    return raw.decode("utf-8", errors="ignore"), ""


def _clean_excerpt(html: str, needles: list[tuple[str, str]], window: int = 180) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(re.sub(r"\s+", " ", text)).strip()
    lower = text.lower()
    positions = [lower.find(value) for _, value in needles if value and lower.find(value) >= 0]
    if not positions:
        return text[:window].strip()
    pos = min(positions)
    start = max(0, pos - window // 2)
    end = min(len(text), pos + window)
    return text[start:end].strip()


def score_broker_page(html: str, identity: IdentityProfile) -> tuple[int, list[str], str]:
    lower = html.lower()
    matched: list[str] = []
    score = 0
    for key, value in _identity_needles(identity):
        if value and value in lower:
            matched.append(key)
            score += 35 if key in {"email", "phone"} else 20
    score = min(score, 100)
    confidence = "high" if score >= 70 else "medium" if score >= 40 else "low" if score > 0 else "unknown"
    return score, matched, confidence


def search_broker(
    broker: Broker,
    identity: IdentityProfile,
    *,
    fetch: bool = False,
    timeout: float = 12.0,
) -> BrokerMatch:
    search_url = build_search_url(broker.search.url, identity) if broker.search.url else broker.opt_out.url
    if not fetch:
        return BrokerMatch(
            broker_id=broker.id,
            broker_name=broker.name,
            status="needs_manual_review",
            confidence="unknown",
            score=0,
            search_url=search_url,
            evidence_url=search_url,
            evidence="Search URL generated locally. Run with --fetch to attempt a lightweight page check.",
        )

    html, error = _fetch(search_url, timeout=timeout)
    if error:
        return BrokerMatch(
            broker_id=broker.id,
            broker_name=broker.name,
            status="fetch_error",
            confidence="unknown",
            score=0,
            search_url=search_url,
            evidence_url=search_url,
            evidence="Public search could not be verified. Treat this broker as request-only unless you review it manually.",
            error=error,
        )

    score, matched, confidence = score_broker_page(html, identity)
    status = "possible_match" if score > 0 else "no_obvious_match"
    return BrokerMatch(
        broker_id=broker.id,
        broker_name=broker.name,
        status=status,
        confidence=confidence,
        score=score,
        search_url=search_url,
        evidence_url=search_url,
        matched_fields=matched,
        evidence=_clean_excerpt(html, _identity_needles(identity)),
    )


def search_brokers(
    brokers: list[Broker],
    identity: IdentityProfile,
    *,
    fetch: bool = False,
    limit: int | None = None,
    timeout: float = 12.0,
) -> list[BrokerMatch]:
    selected = brokers[:limit] if limit else brokers
    return [search_broker(broker, identity, fetch=fetch, timeout=timeout) for broker in selected]
