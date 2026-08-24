from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PRESERVED_METADATA = [
    "module_id",
    "level",
    "document_id",
    "document_type",
    "knowledge_role",
    "section_title",
    "topic",
    "task_reference",
    "instructional_unit",
    "source_file",
    "page_start",
    "page_end",
]


def load_embedding_eligible_chunks(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("embedding_eligible") is True:
                rows.append(row)
    return rows


def chunk_to_embedding_text(chunk: dict[str, Any]) -> str:
    lines = []
    if chunk.get("section_title"):
        lines.append(f"Section: {chunk['section_title']}")
    if chunk.get("topic") and chunk.get("topic") != chunk.get("section_title"):
        lines.append(f"Topic: {chunk['topic']}")
    if chunk.get("task_reference"):
        lines.append(f"Task reference: {chunk['task_reference']}")
    if chunk.get("instructional_unit"):
        lines.append(f"Instructional unit: {chunk['instructional_unit']}")
    if chunk.get("knowledge_role"):
        lines.append(f"Knowledge role: {chunk['knowledge_role']}")
    lines.append("")
    lines.append(chunk["content"])
    return "\n".join(lines).strip()


def chunk_metadata(chunk: dict[str, Any]) -> dict[str, str | int | float | bool]:
    metadata: dict[str, str | int | float | bool] = {}
    for key in PRESERVED_METADATA:
        value = chunk.get(key)
        if value is None:
            metadata[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            metadata[key] = value
        else:
            metadata[key] = str(value)
    metadata["embedding_eligible"] = bool(chunk.get("embedding_eligible"))
    return metadata

