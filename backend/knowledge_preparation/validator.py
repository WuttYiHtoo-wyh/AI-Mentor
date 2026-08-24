from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .models import ALLOWED_KNOWLEDGE_ROLES, ExtractedDocument, ModuleConfig, PreparedChunk
from .text_utils import token_count


REQUIRED_FIELDS = [
    "chunk_id",
    "module_id",
    "module_name",
    "level",
    "document_id",
    "document_type",
    "knowledge_role",
    "section_title",
    "source_file",
    "page_start",
    "page_end",
    "status",
    "content",
]


def validate(
    config: ModuleConfig,
    documents: list[ExtractedDocument],
    chunks: list[PreparedChunk],
    max_tokens: int,
) -> dict[str, Any]:
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    _validate_sources(config, errors, warnings)
    _validate_extraction(documents, warnings)
    _validate_chunks(chunks, max_tokens, errors, warnings)

    by_status = Counter(chunk.status for chunk in chunks)
    by_role = Counter(chunk.knowledge_role for chunk in chunks)
    by_document = Counter(chunk.document_id for chunk in chunks)
    by_embedding_eligibility = Counter(str(chunk.embedding_eligible).lower() for chunk in chunks)
    return {
        "module_id": config.module_id,
        "module_name": config.module_name,
        "level": config.level,
        "source_count": len(config.sources),
        "chunk_count": len(chunks),
        "status_counts": dict(sorted(by_status.items())),
        "role_counts": dict(sorted(by_role.items())),
        "document_counts": dict(sorted(by_document.items())),
        "embedding_eligibility_counts": dict(sorted(by_embedding_eligibility.items())),
        "errors": errors,
        "warnings": warnings,
    }


def _validate_sources(config: ModuleConfig, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    seen_documents: set[str] = set()
    for source in config.sources:
        if source.document_id in seen_documents:
            errors.append({"type": "duplicate_source_document_id", "document_id": source.document_id})
        seen_documents.add(source.document_id)
        if source.knowledge_role not in ALLOWED_KNOWLEDGE_ROLES:
            errors.append({"type": "unsupported_knowledge_role", "document_id": source.document_id})
        if not source.source_path.exists():
            errors.append({"type": "source_file_missing", "source_file": str(source.source_path)})
        if source.knowledge_role == "LEARNING_MATERIAL" and not source.instructional_unit:
            warnings.append({"type": "missing_instructional_unit", "document_id": source.document_id})


def _validate_extraction(documents: list[ExtractedDocument], warnings: list[dict[str, Any]]) -> None:
    for document in documents:
        if document.warnings:
            for warning in document.warnings:
                warnings.append(
                    {
                        "type": "extraction_warning",
                        "document_id": document.source.document_id,
                        "warning": warning,
                    }
                )
        for page in document.pages:
            for warning in page.warnings:
                warnings.append(
                    {
                        "type": warning,
                        "document_id": document.source.document_id,
                        "page": page.page_number,
                    }
                )


def _validate_chunks(
    chunks: list[PreparedChunk],
    max_tokens: int,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    chunk_ids = Counter(chunk.chunk_id for chunk in chunks)
    content_by_doc = defaultdict(list)
    for chunk in chunks:
        record = chunk.to_record()
        missing = [field for field in REQUIRED_FIELDS if record.get(field) in (None, "")]
        if missing:
            errors.append({"type": "missing_required_chunk_metadata", "chunk_id": chunk.chunk_id, "fields": missing})
        if not chunk.content.strip():
            errors.append({"type": "empty_chunk", "chunk_id": chunk.chunk_id})
        if token_count(chunk.content) > max_tokens:
            warnings.append(
                {
                    "type": "oversized_chunk",
                    "chunk_id": chunk.chunk_id,
                    "tokens": token_count(chunk.content),
                    "max_tokens": max_tokens,
                }
            )
        if "short_chunk_requires_review" in chunk.warnings:
            warnings.append(
                {
                    "type": "short_chunk_requires_review",
                    "chunk_id": chunk.chunk_id,
                    "tokens": token_count(chunk.content),
                }
            )
        if chunk.status == "needs_review":
            warnings.append({"type": "chunk_needs_review", "chunk_id": chunk.chunk_id, "warnings": chunk.warnings})
        content_by_doc[chunk.document_id].append((chunk.chunk_id, chunk.content.strip()))

    for chunk_id, count in chunk_ids.items():
        if count > 1:
            errors.append({"type": "duplicate_chunk_id", "chunk_id": chunk_id, "count": count})

    for document_id, values in content_by_doc.items():
        seen: dict[str, str] = {}
        for chunk_id, content in values:
            if content in seen:
                warnings.append(
                    {
                        "type": "duplicate_chunk_content",
                        "document_id": document_id,
                        "chunk_id": chunk_id,
                        "first_chunk_id": seen[content],
                    }
                )
            seen[content] = chunk_id
