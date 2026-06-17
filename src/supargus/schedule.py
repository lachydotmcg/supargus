"""Scheduling command generation."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path


def _python_exe() -> str:
    return sys.executable


def workflow_command(config_path: str | Path, *, python_executable: str | None = None) -> list[str]:
    return [
        python_executable or _python_exe(),
        "-m",
        "supargus.cli",
        "workflow",
        "run",
        "--config",
        str(config_path),
    ]


def powershell_command(config_path: str | Path) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in workflow_command(config_path))


def schtasks_create_command(
    config_path: str | Path,
    *,
    task_name: str = "SupargusPrivacyWatchdog",
    time: str = "09:00",
) -> str:
    command = powershell_command(config_path)
    return (
        f'schtasks /Create /SC DAILY /TN "{task_name}" '
        f'/TR "{command}" /ST {time} /F'
    )


def cron_line(config_path: str | Path, *, hour: int = 9, minute: int = 0) -> str:
    command = " ".join(shlex.quote(part) for part in workflow_command(config_path, python_executable="python3"))
    return f"{minute} {hour} * * * {command}"


def schedule_instructions(config_path: str | Path, *, time: str = "09:00") -> str:
    hour, minute = _parse_time(time)
    return "\n".join(
        [
            "Windows Task Scheduler:",
            schtasks_create_command(config_path, time=time),
            "",
            "macOS/Linux cron:",
            cron_line(config_path, hour=hour, minute=minute),
            "# If Supargus is installed in a virtualenv, replace python3 with that venv's Python path.",
        ]
    )


def _parse_time(value: str) -> tuple[int, int]:
    hour_s, minute_s = value.split(":", 1)
    hour = int(hour_s)
    minute = int(minute_s)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("time must be HH:MM in 24-hour format")
    return hour, minute
