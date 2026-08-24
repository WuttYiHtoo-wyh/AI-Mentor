from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

from backend.admin.repository import AdminRepository
from backend.admin.service import AdminPersistenceService, ValidationError
PUBLISHED_DELETE_BLOCKER = "Published versions cannot be deleted directly. Create a new version or use a future rollback/archive workflow."


class AdminVersionDeleteService:
    def __init__(self, repository: AdminRepository, *, upload_root: Path, chroma_root: Path) -> None:
        self.repository = repository
        self.persistence = AdminPersistenceService(repository)
        self.upload_root = upload_root
        self.chroma_root = chroma_root

    def delete_version(self, version_id: str) -> dict[str, Any]:
        version = self.persistence.get_module_version(version_id)
        if version.status == "PUBLISHED" or version.is_active:
            raise ValidationError(PUBLISHED_DELETE_BLOCKER)

        documents = self.persistence.list_documents_for_version(version.id)
        publish_jobs = self.repository.list_publish_jobs(version.id)
        collection_names = sorted({job.collection_name for job in publish_jobs if job.collection_name})
        result = self.repository.delete_module_version_and_artifacts(version.id)

        file_deleted = 0
        warnings: list[str] = []
        for document in documents:
            file_result = _delete_uploaded_file(document.file_path, document.stored_filename, self.upload_root)
            if file_result.get("file_deleted"):
                file_deleted += 1
            warnings.extend(str(item) for item in file_result.get("warnings", []))

        chroma_deleted = 0
        for collection_name in collection_names:
            deleted, warning = self._delete_owned_chroma_collection(collection_name, version.id)
            if deleted:
                chroma_deleted += 1
            if warning:
                warnings.append(warning)

        return {
            "deleted": bool(result["deleted"]),
            "version_id": version.id,
            "removed_documents": int(result["removed_documents"]),
            "removed_chunks": int(result["removed_chunks"]),
            "removed_warnings": int(result["removed_warnings"]),
            "removed_preparation_jobs": int(result["removed_preparation_jobs"]),
            "removed_publish_jobs": int(result["removed_publish_jobs"]),
            "removed_review_events": int(result["removed_review_events"]),
            "removed_files": file_deleted,
            "removed_chroma_collections": chroma_deleted,
            "warnings": warnings,
        }

    def _delete_owned_chroma_collection(self, collection_name: str, version_id: str) -> tuple[bool, str | None]:
        if not self.chroma_root.exists():
            return False, None
        try:
            client = chromadb.PersistentClient(path=str(self.chroma_root))
            collection = client.get_collection(collection_name)
            rows = collection.get(include=["metadatas"])
        except Exception:
            return False, None

        metadatas = rows.get("metadatas", []) or []
        if metadatas and any(metadata.get("module_version") != version_id for metadata in metadatas):
            return False, f"Chroma collection {collection_name} was not removed because it contains data outside this version."
        try:
            client.delete_collection(collection_name)
        except Exception as exc:
            return False, f"Chroma collection {collection_name} was not removed: {exc}"
        return True, None

def _delete_uploaded_file(file_path: str, stored_filename: str, upload_root: Path) -> dict[str, object]:
    warnings: list[str] = []
    path = Path(file_path)
    try:
        target = path.resolve(strict=False)
        root = upload_root.resolve(strict=False)
    except OSError as exc:
        return {"file_deleted": False, "warnings": [f"Could not resolve uploaded file path: {exc}"]}

    if root != target and root not in target.parents:
        return {"file_deleted": False, "warnings": ["Stored file path is outside the upload root; file was not deleted."]}
    if target.name != stored_filename:
        return {"file_deleted": False, "warnings": ["Stored file path does not match the document record; file was not deleted."]}
    if not target.exists():
        return {"file_deleted": False, "warnings": ["Stored file was already missing."]}
    if not target.is_file():
        return {"file_deleted": False, "warnings": ["Stored path is not a file; it was not deleted."]}
    try:
        target.unlink()
    except OSError as exc:
        warnings.append(f"Document metadata was deleted, but the stored file could not be removed: {exc}")
        return {"file_deleted": False, "warnings": warnings}
    return {"file_deleted": True, "warnings": warnings}

