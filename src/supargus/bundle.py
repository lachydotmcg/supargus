"""Evidence bundle export."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .models import utc_now


DEFAULT_BUNDLE_PATTERNS = [
    "broker_matches.json",
    "watchdog.json",
    "monitor_diff.json",
    "tracker.json",
    "supargus_report.html",
    "broker_matches.html",
    "watchdog.html",
    "requests/requests.json",
    "requests/*.txt",
    "forms/forms.json",
    "custom/custom.json",
    "custom/requests/requests.json",
    "custom/requests/*.txt",
    "followups/requests.json",
    "followups/*.txt",
]


@dataclass
class BundleItem:
    path: str
    size: int
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_bundle_files(workspace: str | Path, patterns: list[str] | None = None) -> list[Path]:
    root = Path(workspace)
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in patterns or DEFAULT_BUNDLE_PATTERNS:
        for path in root.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    return sorted(files)


def export_bundle(
    workspace: str | Path,
    output_path: str | Path,
    *,
    patterns: list[str] | None = None,
) -> tuple[Path, dict]:
    root = Path(workspace)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    files = collect_bundle_files(root, patterns)
    items: list[BundleItem] = []

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(root).as_posix()
            zf.write(path, rel)
            items.append(BundleItem(path=rel, size=path.stat().st_size, sha256=_sha256(path)))

        manifest = {
            "generated_at": utc_now(),
            "workspace": str(root.resolve()),
            "file_count": len(items),
            "files": [item.__dict__ for item in items],
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return out, manifest
