from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import PreparedChunk


def write_jsonl(chunks: list[PreparedChunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_record(), ensure_ascii=False) + "\n")


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

