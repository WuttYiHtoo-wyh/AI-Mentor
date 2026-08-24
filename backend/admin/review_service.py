from __future__ import annotations

from collections import Counter
from uuid import uuid4

from backend.admin.constants import BLOCKING_WARNING_TYPES, CHUNK_REVIEW_STATUSES, INFORMATIONAL_WARNING_TYPES, KNOWLEDGE_ROLE_CODES
from backend.admin.models import DocumentMetadata, ModuleVersion, PreparedChunkRecord, ReviewEvent
from backend.admin.repository import AdminRepository, NotFoundError
from backend.admin.service import AdminPersistenceService, ValidationError, _now


class AdminReviewService:
    def __init__(self, repository: AdminRepository) -> None:
        self.repository = repository
        self.persistence = AdminPersistenceService(repository)

    def get_chunk(self, chunk_id: str) -> PreparedChunkRecord:
        chunk = self._resolve_chunk(chunk_id)
        if not chunk:
            raise NotFoundError("Prepared chunk not found.")
        return chunk

    def set_chunk_review_status(
        self,
        chunk_id: str,
        *,
        review_status: str,
        reviewer: str,
        comment: str = "",
        allow_blocking: bool = False,
    ) -> PreparedChunkRecord:
        chunk = self.get_chunk(chunk_id)
        review_status = _review_status(review_status)
        reviewer = _required(reviewer, "reviewer")
        if review_status == "APPROVED" and not allow_blocking:
            blocking = self._chunk_blockers(chunk)
            if blocking:
                raise ValidationError("Chunk has blocking review conditions: " + ", ".join(blocking))
        previous = chunk.review_status
        updated = self.repository.update_chunk_review(
            chunk.id,
            review_status=review_status,
            reviewed_by=reviewer,
            reviewed_at=_now(),
            review_comment=comment.strip(),
        )
        action = {"APPROVED": "APPROVE_CHUNK", "REJECTED": "REJECT_CHUNK", "NEEDS_REVIEW": "RESET_CHUNK"}[review_status]
        self._event("chunk", chunk.id, action, reviewer, previous, review_status, comment)
        return updated

    def update_chunk_metadata(
        self,
        chunk_id: str,
        *,
        updated_by: str,
        comment: str,
        section_title: str | None = None,
        topic: str | None = None,
        task_reference: str | None = None,
        instructional_unit: str | None = None,
        knowledge_role: str | None = None,
    ) -> PreparedChunkRecord:
        chunk = self.get_chunk(chunk_id)
        updated_by = _required(updated_by, "updated_by")
        if knowledge_role is not None:
            knowledge_role = knowledge_role.strip().upper()
            if knowledge_role not in KNOWLEDGE_ROLE_CODES:
                raise ValidationError(f"Invalid knowledge_role: {knowledge_role}.")
        if not any(value is not None for value in [section_title, topic, task_reference, instructional_unit, knowledge_role]):
            raise ValidationError("At least one metadata field is required.")
        updated = self.repository.update_chunk_metadata(
            chunk.id,
            section_title=_clean_optional(section_title),
            topic=_clean_optional(topic),
            task_reference=_clean_optional(task_reference),
            instructional_unit=_clean_optional(instructional_unit),
            knowledge_role=knowledge_role,
            updated_by=updated_by,
            updated_at=_now(),
            metadata_change_comment=comment.strip(),
        )
        self._event("chunk", chunk.id, "UPDATE_METADATA", updated_by, chunk.review_status, chunk.review_status, comment)
        return updated

    def bulk_review_chunks(
        self,
        *,
        chunk_ids: list[str],
        action: str,
        reviewer: str,
        comment: str = "",
        allow_blocking: bool = False,
    ) -> dict[str, object]:
        reviewer = _required(reviewer, "reviewer")
        target_status = _action_to_status(action)
        results = []
        for chunk_id in chunk_ids:
            try:
                chunk = self.set_chunk_review_status(
                    chunk_id,
                    review_status=target_status,
                    reviewer=reviewer,
                    comment=comment,
                    allow_blocking=allow_blocking,
                )
                results.append({"chunk_id": chunk.id, "status": "updated", "review_status": chunk.review_status})
            except Exception as exc:
                results.append({"chunk_id": chunk_id, "status": "skipped", "reason": str(exc)})
        return {"requested": len(chunk_ids), "updated": len([r for r in results if r["status"] == "updated"]), "results": results}

    def approve_document_eligible_chunks(self, *, document_id: str, reviewer: str, comment: str = "") -> dict[str, object]:
        document = self.persistence.get_document(document_id)
        chunks = self.repository.list_chunks_for_document(document.id)
        selected = [chunk.id for chunk in chunks if chunk.embedding_eligible and not self._chunk_blockers(chunk)]
        return self.bulk_review_chunks(chunk_ids=selected, action="approve", reviewer=reviewer, comment=comment)

    def document_review_summary(self, document_id: str) -> dict[str, object]:
        document = self.persistence.get_document(document_id)
        chunks = self.repository.list_chunks_for_document(document.id)
        warnings = self.repository.list_warnings_for_document(document.id)
        return _summary(chunks, warnings) | {
            "document_id": document.id,
            "document_status": document.status,
            "excluded": bool(document.excluded_at),
        }

    def version_review_summary(self, version_id: str) -> dict[str, object]:
        version = self.persistence.get_module_version(version_id)
        documents = self.persistence.list_documents_for_version(version.id)
        chunks = self.repository.list_chunks_for_version(version.id)
        warnings = self.repository.list_warnings_for_version(version.id)
        doc_summaries = [self.document_review_summary(document.id) for document in documents]
        base = _summary(chunks, warnings)
        blockers = self._version_approval_blockers(version, documents, chunks, warnings)
        return base | {
            "module_version_id": version.id,
            "version_status": version.status,
            "documents": doc_summaries,
            "eligible_for_approval": not blockers,
            "approval_blockers": blockers,
        }

    def approve_version(self, *, version_id: str, approved_by: str, comment: str = "") -> ModuleVersion:
        version = self.persistence.get_module_version(version_id)
        documents = self.persistence.list_documents_for_version(version.id)
        chunks = self.repository.list_chunks_for_version(version.id)
        warnings = self.repository.list_warnings_for_version(version.id)
        blockers = self._version_approval_blockers(version, documents, chunks, warnings)
        if blockers:
            raise ValidationError("Version is not eligible for approval: " + "; ".join(blockers))
        previous = version.status
        approved_at = _now()
        approved = self.repository.approve_module_version(
            version.id,
            approved_by=_required(approved_by, "approved_by"),
            approved_at=approved_at,
            approval_comment=comment.strip(),
        )
        self._event("module_version", version.id, "APPROVE_VERSION", approved_by, previous, "APPROVED", comment)
        return approved

    def reopen_version(self, *, version_id: str, actor: str, comment: str = "") -> ModuleVersion:
        version = self.persistence.get_module_version(version_id)
        if version.status != "APPROVED":
            raise ValidationError("Only an APPROVED unpublished version can be returned to review.")
        reopened = self.repository.reopen_module_version(version.id, updated_at=_now())
        self._event("module_version", version.id, "REOPEN_VERSION", _required(actor, "actor"), "APPROVED", "NEEDS_REVIEW", comment)
        return reopened

    def exclude_document(self, *, document_id: str, excluded_by: str, reason: str) -> DocumentMetadata:
        document = self.persistence.get_document(document_id)
        reason = _required(reason, "exclusion_reason")
        excluded = self.repository.exclude_document(
            document.id,
            excluded_by=_required(excluded_by, "excluded_by"),
            excluded_at=_now(),
            exclusion_reason=reason,
        )
        self._event("document", document.id, "EXCLUDE_DOCUMENT", excluded_by, document.status, "ARCHIVED", reason)
        return excluded

    def list_review_events(self, entity_type: str | None = None, entity_id: str | None = None) -> list[ReviewEvent]:
        return self.repository.list_review_events(entity_type, entity_id)

    def _resolve_chunk(self, chunk_id: str) -> PreparedChunkRecord | None:
        return self.repository.get_prepared_chunk(chunk_id) or self.repository.get_prepared_chunk_by_chunk_id(chunk_id)

    def _chunk_blockers(self, chunk: PreparedChunkRecord) -> list[str]:
        blockers = []
        if not chunk.embedding_eligible:
            blockers.append("embedding_ineligible")
        warning_types = {warning.warning_type for warning in self.repository.list_warnings_for_document(chunk.document_id)}
        blocking = sorted(warning_types & BLOCKING_WARNING_TYPES)
        blockers.extend(blocking)
        return blockers

    def _version_approval_blockers(
        self,
        version,
        documents: list[DocumentMetadata],
        chunks: list[PreparedChunkRecord],
        warnings,
    ) -> list[str]:
        blockers = []
        jobs = self.repository.list_preparation_jobs(version.id)
        if not jobs or not any(job.status in {"COMPLETED", "COMPLETED_WITH_WARNINGS"} for job in jobs):
            blockers.append("no successful preparation job")
        active_docs = [doc for doc in documents if not doc.excluded_at]
        unprepared_docs = [doc.original_filename for doc in active_docs if doc.status in {"UPLOADED", "PREPARING", "FAILED", "NEEDS_REVIEW"} and not self.repository.list_chunks_for_document(doc.id)]
        if unprepared_docs:
            blockers.append("unprepared or unsupported documents require preparation or exclusion: " + ", ".join(unprepared_docs))
        blocking_warning_types = sorted({warning.warning_type for warning in warnings if warning.warning_type in BLOCKING_WARNING_TYPES and not _warning_document_excluded(warning, documents)})
        if blocking_warning_types:
            blockers.append("blocking warnings remain: " + ", ".join(blocking_warning_types))
        if not chunks:
            blockers.append("no prepared chunks")
        if not any(chunk.review_status == "APPROVED" for chunk in chunks):
            blockers.append("no approved chunks")
        unresolved = [chunk.chunk_id for chunk in chunks if chunk.review_status == "NEEDS_REVIEW"]
        if unresolved:
            blockers.append(f"{len(unresolved)} chunks still need review")
        invalid_status = [chunk.chunk_id for chunk in chunks if chunk.review_status not in {"APPROVED", "REJECTED"}]
        if invalid_status:
            blockers.append("chunks have invalid review status")
        return blockers

    def _event(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        previous_status: str | None,
        new_status: str | None,
        comment: str,
    ) -> None:
        self.repository.add_review_event(
            ReviewEvent(
                id=str(uuid4()),
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                actor=actor,
                previous_status=previous_status,
                new_status=new_status,
                comment=comment.strip(),
                created_at=_now(),
            )
        )


def _summary(chunks: list[PreparedChunkRecord], warnings) -> dict[str, object]:
    statuses = Counter(chunk.review_status for chunk in chunks)
    warning_types = Counter(warning.warning_type for warning in warnings)
    blocking_count = sum(count for warning_type, count in warning_types.items() if warning_type in BLOCKING_WARNING_TYPES)
    informational_count = sum(count for warning_type, count in warning_types.items() if warning_type in INFORMATIONAL_WARNING_TYPES)
    return {
        "total_chunks": len(chunks),
        "approved": statuses.get("APPROVED", 0),
        "rejected": statuses.get("REJECTED", 0),
        "needs_review": statuses.get("NEEDS_REVIEW", 0),
        "embedding_eligible": sum(1 for chunk in chunks if chunk.embedding_eligible),
        "warning_count": len(warnings),
        "blocking_warning_count": blocking_count,
        "informational_warning_count": informational_count,
        "warning_types": dict(sorted(warning_types.items())),
    }


def _warning_document_excluded(warning, documents: list[DocumentMetadata]) -> bool:
    if not warning.document_id:
        return False
    by_id = {document.id: document for document in documents}
    document = by_id.get(warning.document_id)
    return bool(document and document.excluded_at)


def _action_to_status(action: str) -> str:
    normalized = _required(action, "action").lower().replace("_", "-")
    mapping = {"approve": "APPROVED", "reject": "REJECTED", "needs-review": "NEEDS_REVIEW", "reset": "NEEDS_REVIEW"}
    if normalized not in mapping:
        raise ValidationError("Invalid bulk review action.")
    return mapping[normalized]


def _review_status(value: str) -> str:
    status = _required(value, "review_status").upper()
    if status not in CHUNK_REVIEW_STATUSES:
        raise ValidationError(f"Invalid review_status: {value}.")
    return status


def _required(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValidationError(f"{field_name} is required.")
    return value.strip()


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()

