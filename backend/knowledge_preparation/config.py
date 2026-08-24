from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import ALLOWED_KNOWLEDGE_ROLES, ModuleConfig, SourceConfig


class ConfigError(ValueError):
    pass


def load_module_config(config_path: Path, workspace_root: Path) -> ModuleConfig:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"Config must be a mapping: {config_path}")

    required = ["module_id", "module_name", "level", "sources"]
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ConfigError(f"Missing module config fields: {', '.join(missing)}")

    output_dir = workspace_root / data.get("output_dir", "prepared_knowledge")
    sources = [_load_source(data, source, workspace_root) for source in data["sources"]]
    return ModuleConfig(
        module_id=data["module_id"],
        module_name=data["module_name"],
        level=data["level"],
        output_dir=output_dir,
        sources=sources,
    )


def _load_source(module_data: dict[str, Any], source: dict[str, Any], workspace_root: Path) -> SourceConfig:
    required = ["document_id", "document_type", "knowledge_role", "source_path"]
    missing = [key for key in required if not source.get(key)]
    if missing:
        raise ConfigError(f"Missing source config fields: {', '.join(missing)}")

    role = source["knowledge_role"]
    if role not in ALLOWED_KNOWLEDGE_ROLES:
        raise ConfigError(f"Unsupported knowledge_role {role!r} for {source['document_id']}")

    source_path = workspace_root / source["source_path"]
    return SourceConfig(
        module_id=module_data["module_id"],
        module_name=module_data["module_name"],
        level=module_data["level"],
        document_id=source["document_id"],
        document_type=source["document_type"],
        knowledge_role=role,
        instructional_unit=source.get("instructional_unit"),
        source_path=source_path,
    )

