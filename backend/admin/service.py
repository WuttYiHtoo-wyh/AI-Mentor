from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from backend.admin.constants import (
    DOCUMENT_STATUSES,
    KNOWLEDGE_ROLE_CODES,
    MODULE_STATUSES,
    MODULE_VERSION_STATUSES,
)
from backend.admin.models import DocumentMetadata, Module, ModuleVersion, PreparationJob, PreparationWarning, PreparedChunkRecord, PublishJob, ReviewEvent
from backend.admin.repository import AdminRepository, DuplicateRecordError, NotFoundError, RepositoryError


class ValidationError(ValueError):
    pass


class AdminPersistenceService:
    def __init__(self, repository: AdminRepository) -> None:
        self.repository = repository

    def initialize(self) -> None:
        self.repository.initialize()

    def create_module(
        self,
        *,
        module_code: str,
        name: str,
        description: str = "",
        status: str = "DRAFT",
    ) -> Module:
        module_code = _required(module_code, "module_code")
        name = _required(name, "name")
        status = _status(status, MODULE_STATUSES, "module status")
        now = _now()
        module = Module(
            id=str(uuid4()),
            module_code=module_code,
            name=name,
            description=(description or "").strip(),
            status=status,
            created_at=now,
            updated_at=now,
        )
        return self.repository.create_module(module)

    def list_modules(self) -> list[Module]:
        return self.repository.list_modules()

    def get_module(self, module_id: str) -> Module:
        module = self.repository.get_module(module_id)
        if not module:
            raise NotFoundError("Module not found.")
        return module

    def create_module_version(
        self,
        *,
        module_id: str,
        version: str,
        level: str,
        description: str = "",
        status: str = "DRAFT",
    ) -> ModuleVersion:
        module_id = _required(module_id, "module_id")
        if not self.repository.get_module(module_id):
            raise NotFoundError("Parent module not found.")
        version_value = _required(version, "version")
        level = _required(level, "level")
        status = _status(status, MODULE_VERSION_STATUSES, "module-version status")
        now = _now()
        module_version = ModuleVersion(
            id=str(uuid4()),
            module_id=module_id,
            version=version_value,
            level=level,
            description=(description or "").strip(),
            status=status,
            is_active=False,
            created_at=now,
            updated_at=now,
        )
        return self.repository.create_module_version(module_version)

    def list_module_versions(self, module_id: str) -> list[ModuleVersion]:
        if not self.repository.get_module(module_id):
            raise NotFoundError("Module not found.")
        return self.repository.list_module_versions(module_id)

    def get_module_version(self, version_id: str) -> ModuleVersion:
        version = self.repository.get_module_version(version_id)
        if not version:
            raise NotFoundError("Module version not found.")
        return version

    def create_document_metadata(
        self,
        *,
        module_version_id: str,
        original_filename: str,
        stored_filename: str,
        file_path: str,
        file_type: str,
        document_type: str,
        knowledge_role: str,
        instructional_unit: str | None = None,
        version: str = "v1",
        status: str = "UPLOADED",
        uploaded_by: str = "local-demo",
    ) -> DocumentMetadata:
        module_version_id = _required(module_version_id, "module_version_id")
        if not self.repository.get_module_version(module_version_id):
            raise NotFoundError("Module version not found.")
        original_filename = _required(original_filename, "original_filename")
        stored_filename = _required(stored_filename, "stored_filename")
        file_path = _required(file_path, "file_path")
        file_type = _required(file_type, "file_type").lower()
        document_type = _required(document_type, "document_type")
        knowledge_role = _status(knowledge_role, KNOWLEDGE_ROLE_CODES, "knowledge_role")
        version_value = _required(version, "version")
        status = _status(status, DOCUMENT_STATUSES, "document status")
        uploaded_by = _required(uploaded_by, "uploaded_by")
        now = _now()
        document = DocumentMetadata(
            id=str(uuid4()),
            module_version_id=module_version_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_path=file_path,
            file_type=file_type,
            document_type=document_type,
            knowledge_role=knowledge_role,
            instructional_unit=(instructional_unit.strip() if instructional_unit else None),
            version=version_value,
            status=status,
            uploaded_by=uploaded_by,
            created_at=now,
            updated_at=now,
        )
        return self.repository.create_document_metadata(document)

    def list_documents_for_version(self, version_id: str) -> list[DocumentMetadata]:
        if not self.repository.get_module_version(version_id):
            raise NotFoundError("Module version not found.")
        return self.repository.list_documents_for_version(version_id)

    def get_document(self, document_id: str) -> DocumentMetadata:
        document = self.repository.get_document(document_id)
        if not document:
            raise NotFoundError("Document metadata not found.")
        return document

    def update_module_version_status(self, version_id: str, status: str) -> None:
        status = _status(status, MODULE_VERSION_STATUSES, "module-version status")
        self.repository.update_module_version_status(version_id, status, _now())

    def update_document_status(self, document_id: str, status: str) -> None:
        status = _status(status, DOCUMENT_STATUSES, "document status")
        self.repository.update_document_status(document_id, status, _now())

    def list_preparation_jobs(self, version_id: str) -> list[PreparationJob]:
        if not self.repository.get_module_version(version_id):
            raise NotFoundError("Module version not found.")
        return self.repository.list_preparation_jobs(version_id)

    def get_preparation_job(self, job_id: str) -> PreparationJob:
        job = self.repository.get_preparation_job(job_id)
        if not job:
            raise NotFoundError("Preparation job not found.")
        return job

    def list_prepared_chunks(
        self,
        job_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        document_id: str | None = None,
        status: str | None = None,
        knowledge_role: str | None = None,
        embedding_eligible: bool | None = None,
    ) -> list[PreparedChunkRecord]:
        if not self.repository.get_preparation_job(job_id):
            raise NotFoundError("Preparation job not found.")
        return self.repository.list_prepared_chunks(
            job_id,
            limit=max(1, min(limit, 500)),
            offset=max(0, offset),
            document_id=document_id,
            status=status,
            knowledge_role=knowledge_role,
            embedding_eligible=embedding_eligible,
        )

    def list_preparation_warnings(self, job_id: str) -> list[PreparationWarning]:
        if not self.repository.get_preparation_job(job_id):
            raise NotFoundError("Preparation job not found.")
        return self.repository.list_preparation_warnings(job_id)


def to_dict(entity: Module | ModuleVersion | DocumentMetadata | PreparationJob | PreparedChunkRecord | PreparationWarning | PublishJob | ReviewEvent) -> dict[str, object]:
    return asdict(entity)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _required(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValidationError(f"{field_name} is required.")
    return value.strip()


def _status(value: str, allowed: frozenset[str], label: str) -> str:
    candidate = _required(value, label).upper()
    if candidate not in allowed:
        raise ValidationError(f"Invalid {label}: {value}.")
    return candidate
