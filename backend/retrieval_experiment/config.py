from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RetrievalConfig:
    prepared_chunks_path: Path
    chroma_path: Path
    collection_name: str
    embedding_model: str
    module_id: str
    level: str
    test_set_path: Path
    results_json_path: Path
    results_csv_path: Path
    batch_size: int = 64


def load_retrieval_config(config_path: Path, workspace_root: Path) -> RetrievalConfig:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Retrieval config must be a mapping: {config_path}")

    required = [
        "prepared_chunks_path",
        "chroma_path",
        "collection_name",
        "embedding_model",
        "module_id",
        "level",
        "test_set_path",
        "results_json_path",
        "results_csv_path",
    ]
    missing = [field for field in required if not data.get(field)]
    if missing:
        raise ValueError(f"Missing retrieval config fields: {', '.join(missing)}")

    return RetrievalConfig(
        prepared_chunks_path=workspace_root / data["prepared_chunks_path"],
        chroma_path=workspace_root / data["chroma_path"],
        collection_name=data["collection_name"],
        embedding_model=data["embedding_model"],
        module_id=data["module_id"],
        level=data["level"],
        test_set_path=workspace_root / data["test_set_path"],
        results_json_path=workspace_root / data["results_json_path"],
        results_csv_path=workspace_root / data["results_csv_path"],
        batch_size=int(data.get("batch_size", 64)),
    )

