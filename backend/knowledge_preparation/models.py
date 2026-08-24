from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ALLOWED_KNOWLEDGE_ROLES = {
    "OFFICIAL_REQUIREMENT",
    "LEARNING_MATERIAL",
    "MODULE_GUIDANCE",
}


@dataclass(frozen=True)
class SourceConfig:
    module_id: str
    module_name: str
    level: str
    document_id: str
    document_type: str
    knowledge_role: str
    source_path: Path
    instructional_unit: str | None = None


@dataclass(frozen=True)
class ModuleConfig:
    module_id: str
    module_name: str
    level: str
    output_dir: Path
    sources: list[SourceConfig]


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    lines: list[str]
    word_count: int
    has_tables: bool = False
    table_count: int = 0
    image_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    source: SourceConfig
    pages: list[ExtractedPage]
    repeated_lines: set[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    page_start: int
    page_end: int
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PreparedChunk:
    chunk_id: str
    module_id: str
    module_name: str
    level: str
    document_id: str
    document_type: str
    knowledge_role: str
    section_title: str
    topic: str | None
    task_reference: str | None
    instructional_unit: str | None
    source_file: str
    page_start: int
    page_end: int
    status: str
    content: str
    embedding_eligible: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "module_id": self.module_id,
            "module_name": self.module_name,
            "level": self.level,
            "document_id": self.document_id,
            "document_type": self.document_type,
            "knowledge_role": self.knowledge_role,
            "section_title": self.section_title,
            "topic": self.topic,
            "task_reference": self.task_reference,
            "instructional_unit": self.instructional_unit,
            "source_file": self.source_file,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "status": self.status,
            "embedding_eligible": self.embedding_eligible,
            "content": self.content,
            "warnings": self.warnings,
        }
