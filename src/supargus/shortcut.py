"""Desktop/start-menu shortcut helpers for the native Supargus app."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShortcutSpec:
    name: str
    path: Path
    target: Path
    arguments: str
    working_dir: Path


def _pythonw() -> Path:
    exe = Path(sys.executable)
    if platform.system().lower() == "windows":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return exe


def shortcut_locations(name: str) -> dict[str, Path]:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_").strip() or "Supargus"
    home = Path.home()
    start_menu = Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "Microsoft/Windows/Start Menu/Programs"
    return {
        "desktop": home / "Desktop" / f"{safe}.lnk",
        "start_menu": start_menu / f"{safe}.lnk",
    }


def build_shortcut_spec(name: str, workspace: str | Path, location: str, *, working_dir: str | Path | None = None) -> ShortcutSpec:
    locations = shortcut_locations(name)
    if location not in locations:
        raise ValueError(f"Unknown shortcut location: {location}")
    workspace_arg = str(Path(workspace))
    return ShortcutSpec(
        name=name,
        path=locations[location],
        target=_pythonw(),
        arguments=f'-m supargus.cli app --workspace "{workspace_arg}"',
        working_dir=Path(working_dir or Path.cwd()),
    )


def _ps_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def create_windows_shortcut(spec: ShortcutSpec) -> Path:
    if platform.system().lower() != "windows":
        raise RuntimeError("Windows shortcuts are only supported on Windows")
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut({_ps_string(spec.path)}); "
        f"$shortcut.TargetPath = {_ps_string(spec.target)}; "
        f"$shortcut.Arguments = {_ps_string(spec.arguments)}; "
        f"$shortcut.WorkingDirectory = {_ps_string(spec.working_dir)}; "
        "$shortcut.IconLocation = $shortcut.TargetPath; "
        "$shortcut.Save()"
    )
    subprocess.check_call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
    return spec.path


def install_shortcuts(
    *,
    name: str = "Supargus",
    workspace: str | Path = "workspace",
    desktop: bool = True,
    start_menu: bool = True,
    working_dir: str | Path | None = None,
) -> list[Path]:
    locations = []
    if desktop:
        locations.append("desktop")
    if start_menu:
        locations.append("start_menu")
    created = []
    for location in locations:
        created.append(create_windows_shortcut(build_shortcut_spec(name, workspace, location, working_dir=working_dir)))
    return created

