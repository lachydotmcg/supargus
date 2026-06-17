"""Local privacy watchdog checks."""

from __future__ import annotations

import csv
import json
import os
import platform
import subprocess
from pathlib import Path

from .models import WatchdogFinding


SUSPICIOUS_PROCESS_TOKENS = {
    "brightdata": "Residential proxy network component",
    "luminati": "Residential proxy network component",
    "hola": "Consumer VPN/proxy component",
    "honeygain": "Bandwidth-sharing application",
    "packetstream": "Bandwidth-sharing proxy application",
    "pawns": "Bandwidth-sharing proxy application",
    "iproyal": "Residential proxy / pawns application",
    "peer2profit": "Bandwidth-sharing proxy application",
    "traffmonetizer": "Bandwidth-sharing application",
    "earnapp": "Bandwidth-sharing application",
    "repocket": "Bandwidth-sharing application",
    "mysterium": "Decentralized VPN/proxy application",
    "grass": "Bandwidth / network sharing application",
}

BROAD_EXTENSION_PERMISSIONS = {"<all_urls>", "webRequest", "proxy", "tabs", "cookies", "management"}


def _run(command: list[str]) -> str:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=15)
    except Exception:
        return ""


def check_env_proxies() -> list[WatchdogFinding]:
    findings = []
    seen: set[str] = set()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        value = os.environ.get(key)
        canonical = key.upper()
        if value and canonical not in seen:
            seen.add(canonical)
            findings.append(
                WatchdogFinding(
                    id=f"env_proxy_{canonical.lower()}",
                    title=f"Proxy environment variable set: {canonical}",
                    severity="medium",
                    category="network",
                    detail="Processes launched from this environment may route traffic through this proxy.",
                    evidence=f"{key}={value}",
                    remediation="Remove the variable if you did not intentionally configure it.",
                )
            )
    return findings


def check_windows_proxy_settings() -> list[WatchdogFinding]:
    if platform.system().lower() != "windows":
        return []
    try:
        import winreg
    except ImportError:
        return []

    findings = []
    path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            proxy_enable = winreg.QueryValueEx(key, "ProxyEnable")[0]
            proxy_server = winreg.QueryValueEx(key, "ProxyServer")[0]
    except OSError:
        return []

    if proxy_enable and proxy_server:
        findings.append(
            WatchdogFinding(
                id="windows_user_proxy",
                title="Windows user proxy is enabled",
                severity="high",
                category="network",
                detail="System and browser traffic may be routed through a configured proxy.",
                evidence=str(proxy_server),
                remediation="Review Windows proxy settings and disable unknown proxies.",
            )
        )
    return findings


def check_processes() -> list[WatchdogFinding]:
    system = platform.system().lower()
    output = _run(["tasklist", "/FO", "CSV"]) if system == "windows" else _run(["ps", "aux"])
    findings = []
    lower = output.lower()
    for token, description in SUSPICIOUS_PROCESS_TOKENS.items():
        if token in lower:
            findings.append(
                WatchdogFinding(
                    id=f"process_{token}",
                    title=f"Possible proxy/bandwidth app process: {token}",
                    severity="high",
                    category="process",
                    detail=description,
                    evidence=token,
                    remediation="Inspect the process, installation path, startup entries, and whether you intentionally installed it.",
                )
            )
    return findings


def check_listening_ports() -> list[WatchdogFinding]:
    system = platform.system().lower()
    output = _run(["netstat", "-ano"]) if system == "windows" else _run(["netstat", "-ltnp"])
    findings = []
    interesting_lines = []
    for line in output.splitlines():
        lower = line.lower()
        if "listen" in lower or "listening" in lower:
            if "127.0.0.1" not in line and "[::1]" not in line and "localhost" not in lower:
                interesting_lines.append(line.strip())
    if interesting_lines:
        findings.append(
            WatchdogFinding(
                id="non_loopback_listeners",
                title="Network listeners exposed beyond localhost",
                severity="medium",
                category="network",
                detail="One or more processes appear to be listening on non-loopback interfaces.",
                evidence="\n".join(interesting_lines[:12]),
                remediation="Map the PID to a process and close listeners you do not recognize.",
            )
        )
    return findings


def _extension_dirs() -> list[Path]:
    home = Path.home()
    candidates = [
        home / "AppData/Local/Google/Chrome/User Data/Default/Extensions",
        home / "AppData/Local/Microsoft/Edge/User Data/Default/Extensions",
        home / "AppData/Local/BraveSoftware/Brave-Browser/User Data/Default/Extensions",
    ]
    return [path for path in candidates if path.exists()]


def check_browser_extensions() -> list[WatchdogFinding]:
    findings = []
    for root in _extension_dirs():
        for manifest in root.glob("*/*/manifest.json"):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                continue
            permissions = set(data.get("permissions") or []) | set(data.get("host_permissions") or [])
            broad = sorted(str(permission) for permission in permissions if str(permission) in BROAD_EXTENSION_PERMISSIONS)
            if broad:
                findings.append(
                    WatchdogFinding(
                        id=f"extension_{manifest.parent.parent.name}",
                        title=f"Browser extension has broad permissions: {data.get('name', manifest.parent.parent.name)}",
                        severity="medium",
                        category="browser",
                        detail="Extensions with broad permissions can observe or alter browsing activity.",
                        evidence=f"{manifest}\npermissions: {', '.join(broad)}",
                        remediation="Review the extension in your browser and remove it if you do not recognize it.",
                    )
                )
    return findings


def check_scheduled_tasks() -> list[WatchdogFinding]:
    if platform.system().lower() != "windows":
        return []
    output = _run(["schtasks", "/Query", "/FO", "CSV", "/NH"])
    findings = []
    for row in csv.reader(output.splitlines()):
        text = " ".join(row).lower()
        for token, description in SUSPICIOUS_PROCESS_TOKENS.items():
            if token in text:
                findings.append(
                    WatchdogFinding(
                        id=f"scheduled_task_{token}",
                        title=f"Scheduled task references {token}",
                        severity="high",
                        category="startup",
                        detail=description,
                        evidence=" | ".join(row),
                        remediation="Inspect the scheduled task and disable it if unwanted.",
                    )
                )
    return findings


def run_watchdog() -> list[WatchdogFinding]:
    findings: list[WatchdogFinding] = []
    for check in (
        check_env_proxies,
        check_windows_proxy_settings,
        check_processes,
        check_listening_ports,
        check_browser_extensions,
        check_scheduled_tasks,
    ):
        findings.extend(check())
    return findings
