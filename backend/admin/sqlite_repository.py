from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
import json
from pathlib import Path

from backend.admin.constants import KNOWLEDGE_ROLES
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
from backend.admin.repository import AdminRepository, DuplicateRecordError, RepositoryError


class SQLiteAdminRepository(AdminRepository):
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_roles (
                    code TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    description TEXT NOT NULL,
                    authority_priority INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS modules (
                    id TEXT PRIMARY KEY,
                    module_code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS module_versions (
                    id TEXT PRIMARY KEY,
                    module_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    level TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE CASCADE,
                    UNIQUE (module_id, version, level)
                );

                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    module_version_id TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    knowledge_role TEXT NOT NULL,
                    instructional_unit TEXT,
                    version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    uploaded_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (module_version_id) REFERENCES module_versions(id) ON DELETE CASCADE,
                    FOREIGN KEY (knowledge_role) REFERENCES knowledge_roles(code)
                );

                CREATE INDEX IF NOT EXISTS idx_module_versions_module_id
                    ON module_versions(module_id);
                CREATE INDEX IF NOT EXISTS idx_documents_module_version_id
                    ON documents(module_version_id);
                CREATE INDEX IF NOT EXISTS idx_documents_knowledge_role
                    ON documents(knowledge_role);

                CREATE TABLE IF NOT EXISTS preparation_jobs (
                    id TEXT PRIMARY KEY,
                    module_version_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    source_document_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    ready_count INTEGER NOT NULL DEFAULT 0,
                    needs_review_count INTEGER NOT NULL DEFAULT 0,
                    embedding_eligible_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT NOT NULL DEFAULT '',
                    output_path TEXT NOT NULL DEFAULT '',
                    validation_report_path TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (module_version_id) REFERENCES module_versions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS prepared_chunks (
                    id TEXT PRIMARY KEY,
                    preparation_job_id TEXT NOT NULL,
                    module_version_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    section_title TEXT NOT NULL,
                    topic TEXT,
                    task_reference TEXT,
                    instructional_unit TEXT,
                    page_start INTEGER,
                    page_end INTEGER,
                    knowledge_role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    embedding_eligible INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (preparation_job_id) REFERENCES preparation_jobs(id) ON DELETE CASCADE,
                    FOREIGN KEY (module_version_id) REFERENCES module_versions(id) ON DELETE CASCADE,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
                    UNIQUE (preparation_job_id, chunk_id)
                );

                CREATE TABLE IF NOT EXISTS preparation_warnings (
                    id TEXT PRIMARY KEY,
                    preparation_job_id TEXT NOT NULL,
                    module_version_id TEXT NOT NULL,
                    document_id TEXT,
                    chunk_id TEXT,
                    warning_type TEXT NOT NULL,
                    page INTEGER,
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (preparation_job_id) REFERENCES preparation_jobs(id) ON DELETE CASCADE,
                    FOREIGN KEY (module_version_id) REFERENCES module_versions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_preparation_jobs_version
                    ON preparation_jobs(module_version_id);
                CREATE INDEX IF NOT EXISTS idx_prepared_chunks_job
                    ON prepared_chunks(preparation_job_id);
                CREATE INDEX IF NOT EXISTS idx_prepared_chunks_filters
                    ON prepared_chunks(preparation_job_id, document_id, status, knowledge_role, embedding_eligible);
                CREATE INDEX IF NOT EXISTS idx_preparation_warnings_job
                    ON preparation_warnings(preparation_job_id);

                CREATE TABLE IF NOT EXISTS review_events (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    previous_status TEXT,
                    new_status TEXT,
                    comment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_review_events_entity
                    ON review_events(entity_type, entity_id);

                CREATE TABLE IF NOT EXISTS publish_jobs (
                    id TEXT PRIMARY KEY,
                    module_version_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    requested_by TEXT NOT NULL,
                    source_chunk_count INTEGER NOT NULL DEFAULT 0,
                    embedded_chunk_count INTEGER NOT NULL DEFAULT 0,
                    collection_name TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (module_version_id) REFERENCES module_versions(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_publish_jobs_version
                    ON publish_jobs(module_version_id);
                """
            )
            _ensure_column(conn, "module_versions", "approved_by", "TEXT")
            _ensure_column(conn, "module_versions", "approved_at", "TEXT")
            _ensure_column(conn, "module_versions", "approval_comment", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "module_versions", "published_by", "TEXT")
            _ensure_column(conn, "module_versions", "published_at", "TEXT")
            _ensure_column(conn, "module_versions", "vector_collection_name", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "module_versions", "vector_store_path", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "module_versions", "retrieval_config_path", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "documents", "excluded_by", "TEXT")
            _ensure_column(conn, "documents", "excluded_at", "TEXT")
            _ensure_column(conn, "documents", "exclusion_reason", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "prepared_chunks", "review_status", "TEXT NOT NULL DEFAULT 'NEEDS_REVIEW'")
            _ensure_column(conn, "prepared_chunks", "reviewed_by", "TEXT")
            _ensure_column(conn, "prepared_chunks", "reviewed_at", "TEXT")
            _ensure_column(conn, "prepared_chunks", "review_comment", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(conn, "prepared_chunks", "updated_by", "TEXT")
            _ensure_column(conn, "prepared_chunks", "updated_at", "TEXT")
            _ensure_column(conn, "prepared_chunks", "metadata_change_comment", "TEXT NOT NULL DEFAULT ''")
            conn.executemany(
                """
                INSERT INTO knowledge_roles (code, label, description, authority_priority, enabled)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(code) DO UPDATE SET
                    label=excluded.label,
                    description=excluded.description,
                    authority_priority=excluded.authority_priority,
                    enabled=1
                """,
                [(role.code, role.label, role.description, role.authority_priority) for role in KNOWLEDGE_ROLES],
            )

    def create_module(self, module: Module) -> Module:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO modules (id, module_code, name, description, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        module.id,
                        module.module_code,
                        module.name,
                        module.description,
                        module.status,
                        module.created_at,
                        module.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError(str(exc)) from exc
        return module

    def list_modules(self) -> list[Module]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM modules ORDER BY created_at, module_code").fetchall()
        return [_module_from_row(row) for row in rows]

    def get_module(self, module_id: str) -> Module | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM modules WHERE id = ?", (module_id,)).fetchone()
        return _module_from_row(row) if row else None

    def get_module_by_code(self, module_code: str) -> Module | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM modules WHERE module_code = ?", (module_code,)).fetchone()
        return _module_from_row(row) if row else None

    def create_module_version(self, version: ModuleVersion) -> ModuleVersion:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO module_versions
                        (id, module_id, version, level, description, status, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version.id,
                        version.module_id,
                        version.version,
                        version.level,
                        version.description,
                        version.status,
                        int(version.is_active),
                        version.created_at,
                        version.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "FOREIGN KEY" in str(exc).upper():
                raise RepositoryError(str(exc)) from exc
            raise DuplicateRecordError(str(exc)) from exc
        return version

    def list_module_versions(self, module_id: str) -> list[ModuleVersion]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM module_versions WHERE module_id = ? ORDER BY created_at, level, version",
                (module_id,),
            ).fetchall()
        return [_version_from_row(row) for row in rows]

    def get_module_version(self, version_id: str) -> ModuleVersion | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM module_versions WHERE id = ?", (version_id,)).fetchone()
        return _version_from_row(row) if row else None

    def create_document_metadata(self, document: DocumentMetadata) -> DocumentMetadata:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO documents
                        (
                            id, module_version_id, original_filename, stored_filename, file_path, file_type,
                            document_type, knowledge_role, instructional_unit, version, status, uploaded_by,
                            created_at, updated_at
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.id,
                        document.module_version_id,
                        document.original_filename,
                        document.stored_filename,
                        document.file_path,
                        document.file_type,
                        document.document_type,
                        document.knowledge_role,
                        document.instructional_unit,
                        document.version,
                        document.status,
                        document.uploaded_by,
                        document.created_at,
                        document.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "FOREIGN KEY" in str(exc).upper():
                raise RepositoryError(str(exc)) from exc
            raise DuplicateRecordError(str(exc)) from exc
        return document

    def list_documents_for_version(self, version_id: str) -> list[DocumentMetadata]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE module_version_id = ? ORDER BY created_at, original_filename",
                (version_id,),
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def get_document(self, document_id: str) -> DocumentMetadata | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return _document_from_row(row) if row else None

    def update_module_version_status(self, version_id: str, status: str, updated_at: str) -> None:
        with self._connection() as conn:
            conn.execute("UPDATE module_versions SET status = ?, updated_at = ? WHERE id = ?", (status, updated_at, version_id))

    def update_document_status(self, document_id: str, status: str, updated_at: str) -> None:
        with self._connection() as conn:
            conn.execute("UPDATE documents SET status = ?, updated_at = ? WHERE id = ?", (status, updated_at, document_id))

    def create_preparation_job(self, job: PreparationJob) -> PreparationJob:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO preparation_jobs
                        (
                            id, module_version_id, status, started_at, completed_at, created_at, created_by,
                            source_document_count, chunk_count, ready_count, needs_review_count,
                            embedding_eligible_count, warning_count, error_message, output_path, validation_report_path
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _job_values(job),
                )
        except sqlite3.IntegrityError as exc:
            raise RepositoryError(str(exc)) from exc
        return job

    def update_preparation_job(self, job: PreparationJob) -> PreparationJob:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE preparation_jobs SET
                    status = ?,
                    started_at = ?,
                    completed_at = ?,
                    created_by = ?,
                    source_document_count = ?,
                    chunk_count = ?,
                    ready_count = ?,
                    needs_review_count = ?,
                    embedding_eligible_count = ?,
                    warning_count = ?,
                    error_message = ?,
                    output_path = ?,
                    validation_report_path = ?
                WHERE id = ?
                """,
                (
                    job.status,
                    job.started_at,
                    job.completed_at,
                    job.created_by,
                    job.source_document_count,
                    job.chunk_count,
                    job.ready_count,
                    job.needs_review_count,
                    job.embedding_eligible_count,
                    job.warning_count,
                    job.error_message,
                    job.output_path,
                    job.validation_report_path,
                    job.id,
                ),
            )
        return job

    def list_preparation_jobs(self, version_id: str) -> list[PreparationJob]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM preparation_jobs WHERE module_version_id = ? ORDER BY created_at DESC",
                (version_id,),
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def get_preparation_job(self, job_id: str) -> PreparationJob | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM preparation_jobs WHERE id = ?", (job_id,)).fetchone()
        return _job_from_row(row) if row else None

    def add_prepared_chunks(self, chunks: list[PreparedChunkRecord]) -> None:
        if not chunks:
            return
        try:
            with self._connection() as conn:
                conn.executemany(
                    """
                    INSERT INTO prepared_chunks
                        (
                            id, preparation_job_id, module_version_id, document_id, chunk_id, section_title,
                            topic, task_reference, instructional_unit, page_start, page_end, knowledge_role,
                            status, embedding_eligible, warning_count, content, created_at, review_status,
                            reviewed_by, reviewed_at, review_comment, updated_by, updated_at, metadata_change_comment
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            chunk.id,
                            chunk.preparation_job_id,
                            chunk.module_version_id,
                            chunk.document_id,
                            chunk.chunk_id,
                            chunk.section_title,
                            chunk.topic,
                            chunk.task_reference,
                            chunk.instructional_unit,
                            chunk.page_start,
                            chunk.page_end,
                            chunk.knowledge_role,
                            chunk.status,
                            int(chunk.embedding_eligible),
                            chunk.warning_count,
                            chunk.content,
                            chunk.created_at,
                            chunk.review_status,
                            chunk.reviewed_by,
                            chunk.reviewed_at,
                            chunk.review_comment,
                            chunk.updated_by,
                            chunk.updated_at,
                            chunk.metadata_change_comment,
                        )
                        for chunk in chunks
                    ],
                )
        except sqlite3.IntegrityError as exc:
            raise RepositoryError(str(exc)) from exc

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
        filters = ["preparation_job_id = ?"]
        params: list[object] = [job_id]
        if document_id:
            filters.append("document_id = ?")
            params.append(document_id)
        if status:
            filters.append("status = ?")
            params.append(status)
        if knowledge_role:
            filters.append("knowledge_role = ?")
            params.append(knowledge_role)
        if embedding_eligible is not None:
            filters.append("embedding_eligible = ?")
            params.append(int(embedding_eligible))
        params.extend([limit, offset])
        query = f"""
            SELECT * FROM prepared_chunks
            WHERE {' AND '.join(filters)}
            ORDER BY rowid
            LIMIT ? OFFSET ?
        """
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_prepared_chunk_from_row(row) for row in rows]

    def add_preparation_warnings(self, warnings: list[PreparationWarning]) -> None:
        if not warnings:
            return
        with self._connection() as conn:
            conn.executemany(
                """
                INSERT INTO preparation_warnings
                    (
                        id, preparation_job_id, module_version_id, document_id, chunk_id,
                        warning_type, page, message, payload_json, created_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        warning.id,
                        warning.preparation_job_id,
                        warning.module_version_id,
                        warning.document_id,
                        warning.chunk_id,
                        warning.warning_type,
                        warning.page,
                        warning.message,
                        json.dumps(warning.payload, ensure_ascii=False),
                        warning.created_at,
                    )
                    for warning in warnings
                ],
            )

    def list_preparation_warnings(self, job_id: str) -> list[PreparationWarning]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM preparation_warnings WHERE preparation_job_id = ? ORDER BY rowid",
                (job_id,),
            ).fetchall()
        return [_warning_from_row(row) for row in rows]

    def get_prepared_chunk(self, chunk_record_id: str) -> PreparedChunkRecord | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM prepared_chunks WHERE id = ?", (chunk_record_id,)).fetchone()
        return _prepared_chunk_from_row(row) if row else None

    def get_prepared_chunk_by_chunk_id(self, chunk_id: str) -> PreparedChunkRecord | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM prepared_chunks WHERE chunk_id = ? ORDER BY rowid DESC LIMIT 1", (chunk_id,)).fetchone()
        return _prepared_chunk_from_row(row) if row else None

    def update_chunk_review(
        self,
        chunk_record_id: str,
        *,
        review_status: str,
        reviewed_by: str,
        reviewed_at: str,
        review_comment: str,
    ) -> PreparedChunkRecord:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE prepared_chunks
                SET review_status = ?, reviewed_by = ?, reviewed_at = ?, review_comment = ?
                WHERE id = ?
                """,
                (review_status, reviewed_by, reviewed_at, review_comment, chunk_record_id),
            )
            row = conn.execute("SELECT * FROM prepared_chunks WHERE id = ?", (chunk_record_id,)).fetchone()
        if not row:
            raise RepositoryError("Prepared chunk not found.")
        return _prepared_chunk_from_row(row)

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
        assignments = []
        params: list[object] = []
        for field, value in [
            ("section_title", section_title),
            ("topic", topic),
            ("task_reference", task_reference),
            ("instructional_unit", instructional_unit),
            ("knowledge_role", knowledge_role),
        ]:
            if value is not None:
                assignments.append(f"{field} = ?")
                params.append(value)
        assignments.extend(["updated_by = ?", "updated_at = ?", "metadata_change_comment = ?"])
        params.extend([updated_by, updated_at, metadata_change_comment, chunk_record_id])
        with self._connection() as conn:
            conn.execute(f"UPDATE prepared_chunks SET {', '.join(assignments)} WHERE id = ?", params)
            row = conn.execute("SELECT * FROM prepared_chunks WHERE id = ?", (chunk_record_id,)).fetchone()
        if not row:
            raise RepositoryError("Prepared chunk not found.")
        return _prepared_chunk_from_row(row)

    def list_chunks_for_document(self, document_id: str) -> list[PreparedChunkRecord]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM prepared_chunks WHERE document_id = ? ORDER BY rowid", (document_id,)).fetchall()
        return [_prepared_chunk_from_row(row) for row in rows]

    def list_chunks_for_version(self, version_id: str) -> list[PreparedChunkRecord]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM prepared_chunks WHERE module_version_id = ? ORDER BY rowid", (version_id,)).fetchall()
        return [_prepared_chunk_from_row(row) for row in rows]

    def list_warnings_for_document(self, document_id: str) -> list[PreparationWarning]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM preparation_warnings WHERE document_id = ? ORDER BY rowid", (document_id,)).fetchall()
        return [_warning_from_row(row) for row in rows]

    def list_warnings_for_version(self, version_id: str) -> list[PreparationWarning]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM preparation_warnings WHERE module_version_id = ? ORDER BY rowid", (version_id,)).fetchall()
        return [_warning_from_row(row) for row in rows]

    def exclude_document(self, document_id: str, *, excluded_by: str, excluded_at: str, exclusion_reason: str) -> DocumentMetadata:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE documents
                SET status = 'ARCHIVED', excluded_by = ?, excluded_at = ?, exclusion_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (excluded_by, excluded_at, exclusion_reason, excluded_at, document_id),
            )
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise RepositoryError("Document not found.")
        return _document_from_row(row)

    def approve_module_version(self, version_id: str, *, approved_by: str, approved_at: str, approval_comment: str) -> ModuleVersion:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE module_versions
                SET status = 'APPROVED', approved_by = ?, approved_at = ?, approval_comment = ?, updated_at = ?
                WHERE id = ?
                """,
                (approved_by, approved_at, approval_comment, approved_at, version_id),
            )
            row = conn.execute("SELECT * FROM module_versions WHERE id = ?", (version_id,)).fetchone()
        if not row:
            raise RepositoryError("Module version not found.")
        return _version_from_row(row)

    def reopen_module_version(self, version_id: str, *, updated_at: str) -> ModuleVersion:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE module_versions
                SET status = 'NEEDS_REVIEW', approved_by = NULL, approved_at = NULL, approval_comment = '', updated_at = ?
                WHERE id = ?
                """,
                (updated_at, version_id),
            )
            row = conn.execute("SELECT * FROM module_versions WHERE id = ?", (version_id,)).fetchone()
        if not row:
            raise RepositoryError("Module version not found.")
        return _version_from_row(row)

    def add_review_event(self, event: ReviewEvent) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO review_events
                    (id, entity_type, entity_id, action, actor, previous_status, new_status, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.entity_type,
                    event.entity_id,
                    event.action,
                    event.actor,
                    event.previous_status,
                    event.new_status,
                    event.comment,
                    event.created_at,
                ),
            )

    def list_review_events(self, entity_type: str | None = None, entity_id: str | None = None) -> list[ReviewEvent]:
        filters = []
        params: list[object] = []
        if entity_type:
            filters.append("entity_type = ?")
            params.append(entity_type)
        if entity_id:
            filters.append("entity_id = ?")
            params.append(entity_id)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self._connection() as conn:
            rows = conn.execute(f"SELECT * FROM review_events{where} ORDER BY rowid", params).fetchall()
        return [_review_event_from_row(row) for row in rows]

    def create_publish_job(self, job: PublishJob) -> PublishJob:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO publish_jobs
                        (
                            id, module_version_id, status, started_at, completed_at, requested_by,
                            source_chunk_count, embedded_chunk_count, collection_name, error_message, created_at
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _publish_job_values(job),
                )
        except sqlite3.IntegrityError as exc:
            raise RepositoryError(str(exc)) from exc
        return job

    def update_publish_job(self, job: PublishJob) -> PublishJob:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE publish_jobs
                SET status = ?, started_at = ?, completed_at = ?, requested_by = ?,
                    source_chunk_count = ?, embedded_chunk_count = ?, collection_name = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    job.status,
                    job.started_at,
                    job.completed_at,
                    job.requested_by,
                    job.source_chunk_count,
                    job.embedded_chunk_count,
                    job.collection_name,
                    job.error_message,
                    job.id,
                ),
            )
        return job

    def list_publish_jobs(self, version_id: str) -> list[PublishJob]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM publish_jobs WHERE module_version_id = ? ORDER BY created_at DESC",
                (version_id,),
            ).fetchall()
        return [_publish_job_from_row(row) for row in rows]

    def get_publish_job(self, job_id: str) -> PublishJob | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM publish_jobs WHERE id = ?", (job_id,)).fetchone()
        return _publish_job_from_row(row) if row else None

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
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM module_versions WHERE id = ?", (version_id,)).fetchone()
            if not row:
                raise RepositoryError("Module version not found.")
            conn.execute(
                """
                UPDATE module_versions
                SET is_active = 0, updated_at = ?
                WHERE module_id = ? AND level = ? AND id != ?
                """,
                (published_at, row["module_id"], row["level"], version_id),
            )
            conn.execute(
                """
                UPDATE module_versions
                SET status = 'PUBLISHED', is_active = 1, published_by = ?, published_at = ?,
                    vector_collection_name = ?, vector_store_path = ?, retrieval_config_path = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    published_by,
                    published_at,
                    collection_name,
                    vector_store_path,
                    retrieval_config_path,
                    published_at,
                    version_id,
                ),
            )
            active = conn.execute("SELECT * FROM module_versions WHERE id = ?", (version_id,)).fetchone()
        return _version_from_row(active)

    def get_active_module_version(self, module_code: str, level: str) -> ModuleVersion | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT mv.* FROM module_versions mv
                JOIN modules m ON m.id = mv.module_id
                WHERE m.module_code = ? AND mv.level = ? AND mv.status = 'PUBLISHED' AND mv.is_active = 1
                ORDER BY mv.published_at DESC
                LIMIT 1
                """,
                (module_code, level),
            ).fetchone()
        return _version_from_row(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _module_from_row(row: sqlite3.Row) -> Module:
    return Module(
        id=row["id"],
        module_code=row["module_code"],
        name=row["name"],
        description=row["description"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _version_from_row(row: sqlite3.Row) -> ModuleVersion:
    return ModuleVersion(
        id=row["id"],
        module_id=row["module_id"],
        version=row["version"],
        level=row["level"],
        description=row["description"],
        status=row["status"],
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
        approval_comment=row["approval_comment"],
        published_by=row["published_by"],
        published_at=row["published_at"],
        vector_collection_name=row["vector_collection_name"],
        vector_store_path=row["vector_store_path"],
        retrieval_config_path=row["retrieval_config_path"],
    )


def _document_from_row(row: sqlite3.Row) -> DocumentMetadata:
    return DocumentMetadata(
        id=row["id"],
        module_version_id=row["module_version_id"],
        original_filename=row["original_filename"],
        stored_filename=row["stored_filename"],
        file_path=row["file_path"],
        file_type=row["file_type"],
        document_type=row["document_type"],
        knowledge_role=row["knowledge_role"],
        instructional_unit=row["instructional_unit"],
        version=row["version"],
        status=row["status"],
        uploaded_by=row["uploaded_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        excluded_by=row["excluded_by"],
        excluded_at=row["excluded_at"],
        exclusion_reason=row["exclusion_reason"],
    )


def _job_values(job: PreparationJob) -> tuple[object, ...]:
    return (
        job.id,
        job.module_version_id,
        job.status,
        job.started_at,
        job.completed_at,
        job.created_at,
        job.created_by,
        job.source_document_count,
        job.chunk_count,
        job.ready_count,
        job.needs_review_count,
        job.embedding_eligible_count,
        job.warning_count,
        job.error_message,
        job.output_path,
        job.validation_report_path,
    )


def _job_from_row(row: sqlite3.Row) -> PreparationJob:
    return PreparationJob(
        id=row["id"],
        module_version_id=row["module_version_id"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        source_document_count=row["source_document_count"],
        chunk_count=row["chunk_count"],
        ready_count=row["ready_count"],
        needs_review_count=row["needs_review_count"],
        embedding_eligible_count=row["embedding_eligible_count"],
        warning_count=row["warning_count"],
        error_message=row["error_message"],
        output_path=row["output_path"],
        validation_report_path=row["validation_report_path"],
    )


def _prepared_chunk_from_row(row: sqlite3.Row) -> PreparedChunkRecord:
    return PreparedChunkRecord(
        id=row["id"],
        preparation_job_id=row["preparation_job_id"],
        module_version_id=row["module_version_id"],
        document_id=row["document_id"],
        chunk_id=row["chunk_id"],
        section_title=row["section_title"],
        topic=row["topic"],
        task_reference=row["task_reference"],
        instructional_unit=row["instructional_unit"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        knowledge_role=row["knowledge_role"],
        status=row["status"],
        embedding_eligible=bool(row["embedding_eligible"]),
        warning_count=row["warning_count"],
        content=row["content"],
        created_at=row["created_at"],
        review_status=row["review_status"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        review_comment=row["review_comment"],
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
        metadata_change_comment=row["metadata_change_comment"],
    )


def _warning_from_row(row: sqlite3.Row) -> PreparationWarning:
    return PreparationWarning(
        id=row["id"],
        preparation_job_id=row["preparation_job_id"],
        module_version_id=row["module_version_id"],
        document_id=row["document_id"],
        chunk_id=row["chunk_id"],
        warning_type=row["warning_type"],
        page=row["page"],
        message=row["message"],
        payload=json.loads(row["payload_json"] or "{}"),
        created_at=row["created_at"],
    )


def _review_event_from_row(row: sqlite3.Row) -> ReviewEvent:
    return ReviewEvent(
        id=row["id"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        action=row["action"],
        actor=row["actor"],
        previous_status=row["previous_status"],
        new_status=row["new_status"],
        comment=row["comment"],
        created_at=row["created_at"],
    )


def _publish_job_values(job: PublishJob) -> tuple[object, ...]:
    return (
        job.id,
        job.module_version_id,
        job.status,
        job.started_at,
        job.completed_at,
        job.requested_by,
        job.source_chunk_count,
        job.embedded_chunk_count,
        job.collection_name,
        job.error_message,
        job.created_at,
    )


def _publish_job_from_row(row: sqlite3.Row) -> PublishJob:
    return PublishJob(
        id=row["id"],
        module_version_id=row["module_version_id"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        requested_by=row["requested_by"],
        source_chunk_count=row["source_chunk_count"],
        embedded_chunk_count=row["embedded_chunk_count"],
        collection_name=row["collection_name"],
        error_message=row["error_message"],
        created_at=row["created_at"],
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
