from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import chromadb
import yaml

from backend.admin.models import PreparedChunkRecord, PublishJob, ReviewEvent
from backend.admin.repository import AdminRepository, NotFoundError
from backend.admin.review_service import AdminReviewService
from backend.admin.service import AdminPersistenceService, ValidationError, _now
from backend.retrieval_experiment.chunks import chunk_to_embedding_text
from backend.retrieval_experiment.embeddings import OpenAIEmbedder
from backend.retrieval_experiment.vector_store import reset_collection, upsert_batches


class Embedder(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


class AdminPublishService:
    def __init__(
        self,
        repository: AdminRepository,
        *,
        workspace_root: Path,
        chroma_root: Path,
        config_root: Path,
        embedding_model: str = "text-embedding-3-small",
        batch_size: int = 64,
        embedder_factory=None,
    ) -> None:
        self.repository = repository
        self.persistence = AdminPersistenceService(repository)
        self.review = AdminReviewService(repository)
        self.workspace_root = workspace_root
        self.chroma_root = chroma_root
        self.config_root = config_root
        self.embedding_model = embedding_model
        self.batch_size = batch_size
        self.embedder_factory = embedder_factory or (lambda model: OpenAIEmbedder(model))

    def publish_version(self, *, version_id: str, requested_by: str = "local-demo") -> PublishJob:
        version = self.persistence.get_module_version(version_id)
        module = self.persistence.get_module(version.module_id)
        if version.status != "APPROVED":
            raise ValidationError("Only APPROVED module versions can be published.")

        blockers = self.review.version_review_summary(version_id)["approval_blockers"]
        if blockers:
            raise ValidationError("Version is not publishable: " + "; ".join(blockers))

        publishable = self._publishable_chunks(version_id)
        if not publishable:
            raise ValidationError("No approved embedding-eligible chunks are available to publish.")

        collection_name = collection_name_for(module.module_code, version.level, version.version, version.id)
        created_at = _now()
        job = PublishJob(
            id=str(uuid4()),
            module_version_id=version_id,
            status="QUEUED",
            started_at=None,
            completed_at=None,
            requested_by=requested_by.strip() or "local-demo",
            source_chunk_count=len(publishable),
            embedded_chunk_count=0,
            collection_name=collection_name,
            error_message="",
            created_at=created_at,
        )
        self.repository.create_publish_job(job)
        self._event(version_id, "PUBLISH_STARTED", requested_by, None, "QUEUED", f"collection={collection_name}; chunks={len(publishable)}")

        running = _replace_job(job, status="RUNNING", started_at=_now())
        self.repository.update_publish_job(running)
        try:
            ids = [chunk.chunk_id for chunk in publishable]
            documents = [chunk.content for chunk in publishable]
            documents_by_id = {doc.id: doc for doc in self.persistence.list_documents_for_version(version_id)}
            metadatas = [
                _chunk_metadata(chunk, module.module_code, module.name, version.version, version.level, documents_by_id)
                for chunk in publishable
            ]
            embedding_texts = [
                chunk_to_embedding_text(_chunk_dict(chunk, module.module_code, module.name, version.version, version.level, documents_by_id))
                for chunk in publishable
            ]
            embedder = self.embedder_factory(self.embedding_model)
            embeddings: list[list[float]] = []
            for start in range(0, len(embedding_texts), self.batch_size):
                embeddings.extend(embedder.embed_texts(embedding_texts[start : start + self.batch_size]))
            if len(embeddings) != len(publishable):
                raise RuntimeError("Embedding count did not match publishable chunk count.")

            collection = reset_collection(self.chroma_root, collection_name)
            upsert_batches(collection, ids, embeddings, documents, metadatas, self.batch_size)
            self._verify_collection(collection_name, version_id, len(publishable))
            retrieval_config_path = self._write_retrieval_config(
                module.module_code,
                module.name,
                version.level,
                collection_name,
                self._latest_prepared_chunks_path(version_id),
            )
            published_at = _now()
            self.repository.activate_module_version(
                version_id,
                published_by=requested_by,
                published_at=published_at,
                collection_name=collection_name,
                vector_store_path=str(self.chroma_root),
                retrieval_config_path=str(retrieval_config_path),
            )
            final = _replace_job(
                running,
                status="COMPLETED",
                completed_at=published_at,
                embedded_chunk_count=len(publishable),
                collection_name=collection_name,
            )
            self.repository.update_publish_job(final)
            self._event(version_id, "PUBLISH_COMPLETED", requested_by, "RUNNING", "COMPLETED", f"collection={collection_name}; chunks={len(publishable)}")
            self._event(version_id, "VERSION_ACTIVATED", requested_by, "APPROVED", "PUBLISHED", collection_name)
            return final
        except Exception as exc:
            failed = _replace_job(running, status="FAILED", completed_at=_now(), error_message=str(exc))
            self.repository.update_publish_job(failed)
            self._event(version_id, "PUBLISH_FAILED", requested_by, "RUNNING", "FAILED", str(exc))
            return failed

    def list_publish_jobs(self, version_id: str) -> list[PublishJob]:
        if not self.repository.get_module_version(version_id):
            raise NotFoundError("Module version not found.")
        return self.repository.list_publish_jobs(version_id)

    def get_publish_job(self, job_id: str) -> PublishJob:
        job = self.repository.get_publish_job(job_id)
        if not job:
            raise NotFoundError("Publish job not found.")
        return job

    def active_version(self, module_code: str, level: str):
        version = self.repository.get_active_module_version(module_code, level)
        if not version:
            raise NotFoundError("No active published version found.")
        return version

    def _publishable_chunks(self, version_id: str) -> list[PreparedChunkRecord]:
        documents = {doc.id: doc for doc in self.persistence.list_documents_for_version(version_id)}
        warnings = self.repository.list_warnings_for_version(version_id)
        blocking_docs = {warning.document_id for warning in warnings if warning.document_id and warning.warning_type in {"source_file_missing", "missing_required_chunk_metadata", "empty_chunk", "duplicate_chunk_id", "unsupported_preparation_format", "extraction_warning", "unsupported_knowledge_role"}}
        selected = []
        for chunk in self.repository.list_chunks_for_version(version_id):
            doc = documents.get(chunk.document_id)
            if not doc or doc.excluded_at:
                continue
            if chunk.review_status != "APPROVED" or not chunk.embedding_eligible:
                continue
            if chunk.document_id in blocking_docs:
                continue
            selected.append(chunk)
        return selected

    def _verify_collection(self, collection_name: str, version_id: str, expected_count: int) -> None:
        client = chromadb.PersistentClient(path=str(self.chroma_root))
        collection = client.get_collection(collection_name)
        result = collection.get(where={"module_version": version_id}, include=["metadatas"])
        ids = result.get("ids", [])
        metadatas = result.get("metadatas", [])
        if len(ids) != expected_count:
            raise RuntimeError(f"Vector verification failed: expected {expected_count}, found {len(ids)}.")
        for metadata in metadatas:
            if metadata.get("module_version") != version_id:
                raise RuntimeError("Vector verification failed: wrong module version metadata.")
            if metadata.get("review_status") != "APPROVED":
                raise RuntimeError("Vector verification failed: unapproved chunk metadata found.")

    def _latest_prepared_chunks_path(self, version_id: str) -> Path:
        jobs = [job for job in self.repository.list_preparation_jobs(version_id) if job.output_path]
        if not jobs:
            raise RuntimeError("No preparation artifact path found for published version.")
        return Path(jobs[0].output_path) / "prepared_chunks.jsonl"

    def _write_retrieval_config(self, module_code: str, module_name: str, level: str, collection_name: str, prepared_chunks_path: Path) -> Path:
        self.config_root.mkdir(parents=True, exist_ok=True)
        path = self.config_root / f"{_safe(module_code)}_{_safe(level)}.yaml"
        template_path = self.workspace_root / "configs" / "retrieval_experiment3.yaml"
        if template_path.exists():
            template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
        else:
            template = _default_retrieval_config()
        template["prepared_chunks_path"] = _config_path_value(prepared_chunks_path, self.workspace_root)
        template["chroma_path"] = _config_path_value(self.chroma_root, self.workspace_root)
        template["collection_name"] = collection_name
        template["embedding_model"] = self.embedding_model
        template["module_id"] = module_code
        template["module_name"] = module_name
        template["level"] = level
        path.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")
        return path

    def _event(self, version_id: str, action: str, actor: str, previous: str | None, new: str | None, comment: str) -> None:
        self.repository.add_review_event(
            ReviewEvent(
                id=str(uuid4()),
                entity_type="module_version",
                entity_id=version_id,
                action=action,
                actor=actor.strip() or "local-demo",
                previous_status=previous,
                new_status=new,
                comment=comment,
                created_at=_now(),
            )
        )


def _config_path_value(path: Path, workspace_root: Path) -> str:
    resolved_path = path.resolve()
    resolved_workspace = workspace_root.resolve()
    try:
        return str(resolved_path.relative_to(resolved_workspace))
    except ValueError:
        return str(resolved_path)



def collection_name_for(module_code: str, level: str, version: str, version_id: str) -> str:
    return f"mentor_{_safe(module_code)}_{_safe(level)}_{_safe(version)}_{version_id[:8]}".lower()


def _safe(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_")[:50] or "module"


def _chunk_dict(chunk: PreparedChunkRecord, module_code: str, module_name: str, module_version: str, level: str, documents_by_id: dict) -> dict[str, object]:
    data = _chunk_metadata(chunk, module_code, module_name, module_version, level, documents_by_id)
    data["content"] = chunk.content
    return data


def _chunk_metadata(chunk: PreparedChunkRecord, module_code: str, module_name: str, module_version: str, level: str, documents_by_id: dict) -> dict[str, object]:
    document = documents_by_id.get(chunk.document_id)
    return {
        "module_id": module_code,
        "module_name": module_name,
        "module_version": chunk.module_version_id,
        "module_version_label": module_version,
        "level": level,
        "document_id": chunk.document_id,
        "document_type": document.document_type if document else "",
        "knowledge_role": chunk.knowledge_role,
        "section_title": chunk.section_title,
        "topic": chunk.topic or "",
        "task_reference": chunk.task_reference or "",
        "instructional_unit": chunk.instructional_unit or "",
        "source_file": document.file_path if document else "",
        "page_start": chunk.page_start or "",
        "page_end": chunk.page_end or "",
        "chunk_id": chunk.chunk_id,
        "review_status": chunk.review_status,
        "embedding_eligible": bool(chunk.embedding_eligible),
    }
def _replace_job(job: PublishJob, **changes) -> PublishJob:
    data = job.__dict__.copy()
    data.update(changes)
    return PublishJob(**data)


def _default_retrieval_config() -> dict[str, object]:
    return {
        "prepared_chunks_path": "",
        "chroma_path": "",
        "collection_name": "",
        "embedding_model": "text-embedding-3-small",
        "module_id": "",
        "level": "",
        "test_set_path": "testing/retrieval_test_set.json",
        "results_json_path": "testing/admin_published_retrieval_results.json",
        "results_csv_path": "testing/admin_published_retrieval_results.csv",
        "batch_size": 64,
        "selected_threshold": 0.7,
        "final_top_k": 5,
        "candidate_pool_configs": [{"general_top_k": 12, "preferred_role_top_k": 8}],
        "intent_patterns": {},
        "reranking": {},
    }
