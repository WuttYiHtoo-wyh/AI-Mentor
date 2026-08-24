from __future__ import annotations

from abc import ABC, abstractmethod

from backend.admin.models import (
    DocumentMetadata,
    Module,
    ModuleVersion,
    PreparationJob,
    PreparationWarning,
    PreparedChunkRecord,
    PublishJob,
    ReviewEvent,
)


class RepositoryError(Exception):
    pass


class DuplicateRecordError(RepositoryError):
    pass


class NotFoundError(RepositoryError):
    pass


class AdminRepository(ABC):
    @abstractmethod
    def initialize(self) -> None:
        """Create tables and seed fixed reference data without destroying records."""

    @abstractmethod
    def create_module(self, module: Module) -> Module:
        raise NotImplementedError

    @abstractmethod
    def list_modules(self) -> list[Module]:
        raise NotImplementedError

    @abstractmethod
    def get_module(self, module_id: str) -> Module | None:
        raise NotImplementedError

    @abstractmethod
    def get_module_by_code(self, module_code: str) -> Module | None:
        raise NotImplementedError

    @abstractmethod
    def create_module_version(self, version: ModuleVersion) -> ModuleVersion:
        raise NotImplementedError

    @abstractmethod
    def list_module_versions(self, module_id: str) -> list[ModuleVersion]:
        raise NotImplementedError

    @abstractmethod
    def get_module_version(self, version_id: str) -> ModuleVersion | None:
        raise NotImplementedError

    @abstractmethod
    def create_document_metadata(self, document: DocumentMetadata) -> DocumentMetadata:
        raise NotImplementedError

    @abstractmethod
    def list_documents_for_version(self, version_id: str) -> list[DocumentMetadata]:
        raise NotImplementedError

    @abstractmethod
    def get_document(self, document_id: str) -> DocumentMetadata | None:
        raise NotImplementedError

    @abstractmethod
    def update_module_version_status(self, version_id: str, status: str, updated_at: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def update_document_status(self, document_id: str, status: str, updated_at: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_preparation_job(self, job: PreparationJob) -> PreparationJob:
        raise NotImplementedError

    @abstractmethod
    def update_preparation_job(self, job: PreparationJob) -> PreparationJob:
        raise NotImplementedError

    @abstractmethod
    def list_preparation_jobs(self, version_id: str) -> list[PreparationJob]:
        raise NotImplementedError

    @abstractmethod
    def get_preparation_job(self, job_id: str) -> PreparationJob | None:
        raise NotImplementedError

    @abstractmethod
    def add_prepared_chunks(self, chunks: list[PreparedChunkRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_prepared_chunks(
        self,
        job_id: str,
        *,
        limit: int,
        offset: int,
        document_id: str | None = None,
        status: str | None = None,
        knowledge_role: str | None = None,
        embedding_eligible: bool | None = None,
    ) -> list[PreparedChunkRecord]:
        raise NotImplementedError

    @abstractmethod
    def add_preparation_warnings(self, warnings: list[PreparationWarning]) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_preparation_warnings(self, job_id: str) -> list[PreparationWarning]:
        raise NotImplementedError

    @abstractmethod
    def get_prepared_chunk(self, chunk_record_id: str) -> PreparedChunkRecord | None:
        raise NotImplementedError

    @abstractmethod
    def get_prepared_chunk_by_chunk_id(self, chunk_id: str) -> PreparedChunkRecord | None:
        raise NotImplementedError

    @abstractmethod
    def update_chunk_review(
        self,
        chunk_record_id: str,
        *,
        review_status: str,
        reviewed_by: str,
        reviewed_at: str,
        review_comment: str,
    ) -> PreparedChunkRecord:
        raise NotImplementedError

    @abstractmethod
    def update_chunk_metadata(
        self,
        chunk_record_id: str,
        *,
        section_title: str | None,
        topic: str | None,
        task_reference: str | None,
        instructional_unit: str | None,
        knowledge_role: str | None,
        updated_by: str,
        updated_at: str,
        metadata_change_comment: str,
    ) -> PreparedChunkRecord:
        raise NotImplementedError

    @abstractmethod
    def list_chunks_for_document(self, document_id: str) -> list[PreparedChunkRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_chunks_for_version(self, version_id: str) -> list[PreparedChunkRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_warnings_for_document(self, document_id: str) -> list[PreparationWarning]:
        raise NotImplementedError

    @abstractmethod
    def list_warnings_for_version(self, version_id: str) -> list[PreparationWarning]:
        raise NotImplementedError

    @abstractmethod
    def exclude_document(self, document_id: str, *, excluded_by: str, excluded_at: str, exclusion_reason: str) -> DocumentMetadata:
        raise NotImplementedError

    @abstractmethod
    def approve_module_version(self, version_id: str, *, approved_by: str, approved_at: str, approval_comment: str) -> ModuleVersion:
        raise NotImplementedError

    @abstractmethod
    def reopen_module_version(self, version_id: str, *, updated_at: str) -> ModuleVersion:
        raise NotImplementedError

    @abstractmethod
    def add_review_event(self, event: ReviewEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_review_events(self, entity_type: str | None = None, entity_id: str | None = None) -> list[ReviewEvent]:
        raise NotImplementedError

    @abstractmethod
    def create_publish_job(self, job: PublishJob) -> PublishJob:
        raise NotImplementedError

    @abstractmethod
    def update_publish_job(self, job: PublishJob) -> PublishJob:
        raise NotImplementedError

    @abstractmethod
    def list_publish_jobs(self, version_id: str) -> list[PublishJob]:
        raise NotImplementedError

    @abstractmethod
    def get_publish_job(self, job_id: str) -> PublishJob | None:
        raise NotImplementedError

    @abstractmethod
    def activate_module_version(
        self,
        version_id: str,
        *,
        published_by: str,
        published_at: str,
        collection_name: str,
        vector_store_path: str,
        retrieval_config_path: str,
    ) -> ModuleVersion:
        raise NotImplementedError

    @abstractmethod
    def get_active_module_version(self, module_code: str, level: str) -> ModuleVersion | None:
        raise NotImplementedError
