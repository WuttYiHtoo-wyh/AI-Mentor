from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeRole:
    code: str
    label: str
    description: str
    authority_priority: int


KNOWLEDGE_ROLES: tuple[KnowledgeRole, ...] = (
    KnowledgeRole(
        code="OFFICIAL_REQUIREMENT",
        label="Official Requirement",
        description="Authoritative for assessment tasks, deliverables, rubric expectations, marks, and what learners must do.",
        authority_priority=100,
    ),
    KnowledgeRole(
        code="LEARNING_MATERIAL",
        label="Learning Material",
        description="Authoritative for taught concepts and explanations within approved learning materials.",
        authority_priority=50,
    ),
    KnowledgeRole(
        code="MODULE_GUIDANCE",
        label="Module Guidance",
        description="Authoritative for general module or course guidance.",
        authority_priority=25,
    ),
)

KNOWLEDGE_ROLE_CODES = frozenset(role.code for role in KNOWLEDGE_ROLES)

MODULE_STATUSES = frozenset({"DRAFT", "ACTIVE", "ARCHIVED"})

MODULE_VERSION_STATUSES = frozenset(
    {
        "DRAFT",
        "PREPARING",
        "PREPARED",
        "NEEDS_REVIEW",
        "APPROVED",
        "PUBLISHED",
        "FAILED",
        "REJECTED",
        "ARCHIVED",
    }
)

DOCUMENT_STATUSES = frozenset(
    {
        "UPLOADED",
        "PREPARING",
        "PREPARED",
        "NEEDS_REVIEW",
        "APPROVED",
        "FAILED",
        "REJECTED",
        "ARCHIVED",
    }
)

CHUNK_REVIEW_STATUSES = frozenset({"NEEDS_REVIEW", "APPROVED", "REJECTED"})

INFORMATIONAL_WARNING_TYPES = frozenset(
    {
        "low_text_image_heavy_page",
        "very_low_text_page",
        "table_detected_requires_structure_review",
        "short_chunk_requires_review",
        "chunk_needs_review",
        "duplicate_chunk_content",
        "missing_instructional_unit",
    }
)

BLOCKING_WARNING_TYPES = frozenset(
    {
        "source_file_missing",
        "missing_required_chunk_metadata",
        "empty_chunk",
        "duplicate_chunk_id",
        "unsupported_preparation_format",
        "extraction_warning",
        "unsupported_knowledge_role",
    }
)

PREPARATION_JOB_STATUSES = frozenset(
    {
        "QUEUED",
        "RUNNING",
        "COMPLETED",
        "COMPLETED_WITH_WARNINGS",
        "FAILED",
    }
)

PUBLISH_JOB_STATUSES = frozenset({"QUEUED", "RUNNING", "COMPLETED", "FAILED"})

SUPPORTED_UPLOAD_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})
SUPPORTED_PREPARATION_EXTENSIONS = frozenset({".pdf"})
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
