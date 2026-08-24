from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import yaml

from backend.admin.constants import SUPPORTED_PREPARATION_EXTENSIONS
from backend.admin.models import DocumentMetadata, PreparationJob, PreparationWarning, PreparedChunkRecord
from backend.admin.repository import AdminRepository, NotFoundError
from backend.admin.service import AdminPersistenceService, ValidationError, _now
from backend.knowledge_preparation.pipeline import prepare_module


class AdminPreparationService:
    def __init__(self, repository: AdminRepository, workspace_root: Path, prepared_root: Path) -> None:
        self.repository = repository
        self.persistence = AdminPersistenceService(repository)
        self.workspace_root = workspace_root
        self.prepared_root = prepared_root

    def prepare_version(self, *, version_id: str, created_by: str = "local-demo") -> PreparationJob:
        module_version = self.persistence.get_module_version(version_id)
        module = self.persistence.get_module(module_version.module_id)
        documents = [doc for doc in self.persistence.list_documents_for_version(version_id) if doc.status in {"UPLOADED", "FAILED"}]
        if not documents:
            raise ValidationError("No UPLOADED or retryable FAILED document metadata records exist for this module version.")

        now = _now()
        output_dir = self.prepared_root / _safe_segment(module.module_code) / _safe_segment(module_version.id)
        config_path = output_dir / "module_config.yaml"
        job = PreparationJob(
            id=str(uuid4()),
            module_version_id=version_id,
            status="QUEUED",
            started_at=None,
            completed_at=None,
            created_at=now,
            created_by=created_by.strip() or "local-demo",
            source_document_count=len(documents),
            chunk_count=0,
            ready_count=0,
            needs_review_count=0,
            embedding_eligible_count=0,
            warning_count=0,
            error_message="",
            output_path=str(output_dir),
            validation_report_path=str(output_dir / "validation_report.json"),
        )
        self.repository.create_preparation_job(job)

        supported_docs = [doc for doc in documents if _extension_for_document(doc) in SUPPORTED_PREPARATION_EXTENSIONS]
        unsupported_docs = [doc for doc in documents if doc not in supported_docs]
        if not supported_docs:
            failed = _replace_job(job, status="FAILED", completed_at=_now(), error_message="No uploaded documents have a supported preparation adapter.")
            self.repository.update_preparation_job(failed)
            self.persistence.update_module_version_status(version_id, "FAILED")
            for doc in documents:
                self.persistence.update_document_status(doc.id, "NEEDS_REVIEW")
            self.repository.add_preparation_warnings(
                [_unsupported_warning(failed.id, version_id, doc) for doc in unsupported_docs]
            )
            return failed

        running = _replace_job(job, status="RUNNING", started_at=_now())
        self.repository.update_preparation_job(running)
        self.persistence.update_module_version_status(version_id, "PREPARING")
        for doc in supported_docs:
            self.persistence.update_document_status(doc.id, "PREPARING")
        for doc in unsupported_docs:
            self.persistence.update_document_status(doc.id, "NEEDS_REVIEW")

        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            config = _build_module_config(module, module_version, supported_docs, output_dir, self.workspace_root)
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            report = prepare_module(config_path=config_path, workspace_root=self.workspace_root)
            shutil.copy2(config_path, output_dir / "preparation_config_used.yaml")
            chunks = _load_chunks(output_dir / "prepared_chunks.jsonl")
            self.repository.add_prepared_chunks(
                [_chunk_record(running.id, version_id, row) for row in chunks]
            )
            warnings = [_warning_record(running.id, version_id, item) for item in report.get("warnings", [])]
            warnings.extend(_unsupported_warning(running.id, version_id, doc) for doc in unsupported_docs)
            self.repository.add_preparation_warnings(warnings)
            final_status = "COMPLETED_WITH_WARNINGS" if warnings or report.get("errors") else "COMPLETED"
            final = _replace_job(
                running,
                status=final_status,
                completed_at=_now(),
                source_document_count=len(documents),
                chunk_count=int(report.get("chunk_count", len(chunks))),
                ready_count=int(report.get("status_counts", {}).get("ready", 0)),
                needs_review_count=int(report.get("status_counts", {}).get("needs_review", 0)),
                embedding_eligible_count=int(report.get("embedding_eligibility_counts", {}).get("true", 0)),
                warning_count=len(warnings) + len(report.get("errors", [])),
                error_message="; ".join(str(error) for error in report.get("errors", [])),
                output_path=str(output_dir),
                validation_report_path=str(output_dir / "validation_report.json"),
            )
            self.repository.update_preparation_job(final)
            version_status = "NEEDS_REVIEW" if final.needs_review_count or final.warning_count else "PREPARED"
            self.persistence.update_module_version_status(version_id, version_status)
            for doc in supported_docs:
                self.persistence.update_document_status(doc.id, "PREPARED")
            return final
        except Exception as exc:
            failed = _replace_job(running, status="FAILED", completed_at=_now(), error_message=str(exc))
            self.repository.update_preparation_job(failed)
            self.persistence.update_module_version_status(version_id, "FAILED")
            for doc in supported_docs:
                self.persistence.update_document_status(doc.id, "FAILED")
            return failed


def _build_module_config(module, module_version, documents: list[DocumentMetadata], output_dir: Path, workspace_root: Path) -> dict[str, object]:
    sources = []
    for doc in documents:
        path = Path(doc.file_path)
        source_path = _config_path_value(path, workspace_root)
        source = {
            "document_id": doc.id,
            "document_type": doc.document_type,
            "knowledge_role": doc.knowledge_role,
            "source_path": source_path,
        }
        if doc.instructional_unit:
            source["instructional_unit"] = doc.instructional_unit
        sources.append(source)
    return {
        "module_id": module.module_code,
        "module_name": module.name,
        "level": module_version.level,
        "output_dir": _config_path_value(output_dir, workspace_root),
        "sources": sources,
    }


def _config_path_value(path: Path, workspace_root: Path) -> str:
    resolved_path = path.resolve()
    resolved_workspace = workspace_root.resolve()
    try:
        return str(resolved_path.relative_to(resolved_workspace))
    except ValueError:
        return str(resolved_path)


def _extension_for_document(document: DocumentMetadata) -> str:
    return "." + document.file_type.lower().lstrip(".")


def _load_chunks(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _chunk_record(job_id: str, version_id: str, row: dict[str, object]) -> PreparedChunkRecord:
    return PreparedChunkRecord(
        id=str(uuid4()),
        preparation_job_id=job_id,
        module_version_id=version_id,
        document_id=str(row.get("document_id", "")),
        chunk_id=str(row.get("chunk_id", "")),
        section_title=str(row.get("section_title", "")),
        topic=row.get("topic") if row.get("topic") is not None else None,
        task_reference=row.get("task_reference") if row.get("task_reference") is not None else None,
        instructional_unit=row.get("instructional_unit") if row.get("instructional_unit") is not None else None,
        page_start=_int_or_none(row.get("page_start")),
        page_end=_int_or_none(row.get("page_end")),
        knowledge_role=str(row.get("knowledge_role", "")),
        status=str(row.get("status", "")),
        embedding_eligible=bool(row.get("embedding_eligible")),
        warning_count=len(row.get("warnings", []) or []),
        content=str(row.get("content", "")),
        created_at=_now(),
    )


def _warning_record(job_id: str, version_id: str, item: dict[str, object]) -> PreparationWarning:
    return PreparationWarning(
        id=str(uuid4()),
        preparation_job_id=job_id,
        module_version_id=version_id,
        document_id=item.get("document_id") if item.get("document_id") is not None else None,
        chunk_id=item.get("chunk_id") if item.get("chunk_id") is not None else None,
        warning_type=str(item.get("type", "warning")),
        page=_int_or_none(item.get("page")),
        message=str(item.get("warning") or item.get("message") or ""),
        payload=item,
        created_at=_now(),
    )


def _unsupported_warning(job_id: str, version_id: str, document: DocumentMetadata) -> PreparationWarning:
    return PreparationWarning(
        id=str(uuid4()),
        preparation_job_id=job_id,
        module_version_id=version_id,
        document_id=document.id,
        chunk_id=None,
        warning_type="unsupported_preparation_format",
        page=None,
        message=f"No preparation adapter is available for .{document.file_type}. Upload metadata is preserved.",
        payload={"document_id": document.id, "file_type": document.file_type},
        created_at=_now(),
    )


def _replace_job(job: PreparationJob, **changes) -> PreparationJob:
    data = job.__dict__.copy()
    data.update(changes)
    return PreparationJob(**data)


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _safe_segment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value).strip(".-")[:120] or "module"
