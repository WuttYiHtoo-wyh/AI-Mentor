from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Module:
    id: str
    module_code: str
    name: str
    description: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ModuleVersion:
    id: str
    module_id: str
    version: str
    level: str
    description: str
    status: str
    is_active: bool
    created_at: str
    updated_at: str
    approved_by: str | None = None
    approved_at: str | None = None
    approval_comment: str = ""
    published_by: str | None = None
    published_at: str | None = None
    vector_collection_name: str = ""
    vector_store_path: str = ""
    retrieval_config_path: str = ""


@dataclass(frozen=True)
class DocumentMetadata:
    id: str
    module_version_id: str
    original_filename: str
    stored_filename: str
    file_path: str
    file_type: str
    document_type: str
    knowledge_role: str
    instructional_unit: str | None
    version: str
    status: str
    uploaded_by: str
    created_at: str
    updated_at: str
    excluded_by: str | None = None
    excluded_at: str | None = None
    exclusion_reason: str = ""


@dataclass(frozen=True)
class PreparationJob:
    id: str
    module_version_id: str
    status: str
    started_at: str | None
    completed_at: str | None
    created_at: str
    created_by: str
    source_document_count: int
    chunk_count: int
    ready_count: int
    needs_review_count: int
    embedding_eligible_count: int
    warning_count: int
    error_message: str
    output_path: str
    validation_report_path: str


@dataclass(frozen=True)
class PreparedChunkRecord:
    id: str
    preparation_job_id: str
    module_version_id: str
    document_id: str
    chunk_id: str
    section_title: str
    topic: str | None
    task_reference: str | None
    instructional_unit: str | None
    page_start: int | None
    page_end: int | None
    knowledge_role: str
    status: str
    embedding_eligible: bool
    warning_count: int
    content: str
    created_at: str
    review_status: str = "NEEDS_REVIEW"
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_comment: str = ""
    updated_by: str | None = None
    updated_at: str | None = None
    metadata_change_comment: str = ""


@dataclass(frozen=True)
class PreparationWarning:
    id: str
    preparation_job_id: str
    module_version_id: str
    document_id: str | None
    chunk_id: str | None
    warning_type: str
    page: int | None
    message: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class ReviewEvent:
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor: str
    previous_status: str | None
    new_status: str | None
    comment: str
    created_at: str


@dataclass(frozen=True)
class PublishJob:
    id: str
    module_version_id: str
    status: str
    started_at: str | None
    completed_at: str | None
    requested_by: str
    source_chunk_count: int
    embedded_chunk_count: int
    collection_name: str
    error_message: str
    created_at: str
