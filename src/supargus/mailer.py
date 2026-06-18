"""SMTP preview and send support."""

from __future__ import annotations

import json
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from .models import TakedownRequest


@dataclass
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_addr: str
    use_tls: bool = True


def smtp_config_to_dict(config: SmtpConfig, *, redact_password: bool = False) -> dict:
    return {
        "host": config.host,
        "port": config.port,
        "username": config.username,
        "password": "[REDACTED]" if redact_password and config.password else config.password,
        "from_addr": config.from_addr,
        "use_tls": config.use_tls,
    }


def gmail_smtp_config(email: str, app_password: str, *, from_addr: str = "") -> SmtpConfig:
    clean_email = email.strip()
    password = app_password.replace(" ", "").strip()
    if not clean_email:
        raise ValueError("Gmail address is required")
    if len(password) < 16:
        raise ValueError("Gmail app password should be the 16-character app password from Google")
    return SmtpConfig(
        host="smtp.gmail.com",
        port=465,
        username=clean_email,
        password=password,
        from_addr=from_addr.strip() or clean_email,
        use_tls=True,
    )


def save_smtp_config(config: SmtpConfig, path: str | Path, *, force: bool = False) -> Path:
    p = Path(path)
    if p.exists() and not force:
        raise FileExistsError(f"{p} already exists; pass --force to overwrite")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(smtp_config_to_dict(config), indent=2), encoding="utf-8")
    return p


def load_smtp_config(path: str | Path | None = None) -> SmtpConfig:
    data = {}
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    return SmtpConfig(
        host=str(data.get("host") or os.environ.get("SUPARGUS_SMTP_HOST", "")),
        port=int(data.get("port") or os.environ.get("SUPARGUS_SMTP_PORT", "465")),
        username=str(data.get("username") or os.environ.get("SUPARGUS_SMTP_USERNAME", "")),
        password=str(data.get("password") or os.environ.get("SUPARGUS_SMTP_PASSWORD", "")),
        from_addr=str(data.get("from_addr") or os.environ.get("SUPARGUS_SMTP_FROM", "")),
        use_tls=bool(data.get("use_tls", True)),
    )


def build_message(request: TakedownRequest, config: SmtpConfig) -> EmailMessage:
    if not request.to_email:
        raise ValueError(f"{request.broker_name} has no contact email; use manual opt-out: {request.opt_out_url}")
    msg = EmailMessage()
    msg["From"] = config.from_addr or config.username
    msg["To"] = request.to_email
    msg["Subject"] = request.subject
    msg.set_content(request.body)
    return msg


def preview_requests(requests: list[TakedownRequest]) -> str:
    lines = []
    for request in requests:
        destination = request.to_email or f"manual form: {request.opt_out_url}"
        lines.append(f"{request.broker_name} -> {destination}\nSubject: {request.subject}\n")
    return "\n".join(lines).strip()


def send_requests(
    requests: list[TakedownRequest],
    config: SmtpConfig,
    *,
    limit: int | None = None,
) -> list[dict]:
    if not config.host or not config.username or not config.password:
        raise ValueError("SMTP host, username, and password are required")
    selected = [request for request in requests if request.to_email]
    if limit:
        selected = selected[:limit]

    sent = []
    if config.use_tls:
        server_ctx = smtplib.SMTP_SSL(config.host, config.port, timeout=30)
    else:
        server_ctx = smtplib.SMTP(config.host, config.port, timeout=30)

    with server_ctx as server:
        if not config.use_tls:
            server.starttls()
        server.login(config.username, config.password)
        for request in selected:
            msg = build_message(request, config)
            server.send_message(msg)
            request.status = "sent"
            sent.append({"broker_id": request.broker_id, "to": request.to_email, "subject": request.subject})
    return sent
