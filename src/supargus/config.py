"""Local Supargus workflow configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG_NAME = "supargus.config.json"


@dataclass
class WorkflowConfig:
    identity: str = "workspace/identity.sgvault"
    workspace: str = "workspace"
    history_dir: str = "workspace/history"
    tracker: str = "workspace/tracker.json"
    requests_dir: str = "workspace/requests"
    followups_dir: str = "workspace/followups"
    bundle_path: str = "workspace/supargus_evidence_bundle.zip"
    limit: int | None = 10
    fetch: bool = False
    watchdog: bool = True
    prepare_requests: bool = True
    include_low_confidence: bool = False
    import_tracker: bool = True
    followups: bool = True
    export_bundle: bool = True


def default_config() -> WorkflowConfig:
    return WorkflowConfig()


def config_to_dict(config: WorkflowConfig) -> dict:
    return dict(config.__dict__)


def config_from_dict(data: dict) -> WorkflowConfig:
    defaults = config_to_dict(default_config())
    merged = {**defaults, **data}
    if merged.get("limit") is not None:
        merged["limit"] = int(merged["limit"])
    return WorkflowConfig(**merged)


def load_config(path: str | Path) -> WorkflowConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Supargus config must be a JSON object")
    return config_from_dict(data)


def save_default_config(path: str | Path, *, force: bool = False) -> Path:
    p = Path(path)
    if p.exists() and not force:
        raise FileExistsError(f"{p} already exists; pass --force to overwrite")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config_to_dict(default_config()), indent=2), encoding="utf-8")
    return p

