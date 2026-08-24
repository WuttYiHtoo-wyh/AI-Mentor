from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from backend.admin.constants import MAX_UPLOAD_BYTES, SUPPORTED_UPLOAD_EXTENSIONS
from backend.admin.repository import AdminRepository, NotFoundError
from backend.admin.service import AdminPersistenceService, ValidationError


class AdminUploadService:
    def __init__(self, repository: AdminRepository, upload_root: Path) -> None:
        self.repository = repository
        self.persistence = AdminPersistenceService(repository)
        self.upload_root = upload_root

    def save_document_upload(
        self,
        *,
        version_id: str,
        original_filename: str,
        content: bytes,
        document_type: str,
        knowledge_role: str,
        instructional_unit: str | None = None,
        document_version: str = "v1",
        uploaded_by: str = "local-demo",
    ):
        module_version = self.persistence.get_module_version(version_id)
        module = self.persistence.get_module(module_version.module_id)
        if not content:
            raise ValidationError("Uploaded file is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValidationError(f"Uploaded file exceeds the {MAX_UPLOAD_BYTES} byte limit.")

        safe_original = _safe_display_filename(original_filename)
        extension = Path(safe_original).suffix.lower()
        if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
            raise ValidationError(f"Unsupported file extension: {extension or '(none)'}.")

        stored_filename = f"{uuid4().hex}{extension}"
        target_dir = self.upload_root / _safe_path_segment(module.module_code) / _safe_path_segment(module_version.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = (target_dir / stored_filename).resolve()
        upload_root = self.upload_root.resolve()
        if upload_root not in target_path.parents:
            raise ValidationError("Invalid upload path.")
        if target_path.exists():
            raise ValidationError("Generated upload filename already exists; retry upload.")

        target_path.write_bytes(content)
        return self.persistence.create_document_metadata(
            module_version_id=version_id,
            original_filename=safe_original,
            stored_filename=stored_filename,
            file_path=str(target_path),
            file_type=extension.lstrip("."),
            document_type=document_type,
            knowledge_role=knowledge_role,
            instructional_unit=instructional_unit,
            version=document_version,
            status="UPLOADED",
            uploaded_by=uploaded_by,
        )


def _safe_display_filename(filename: str) -> str:
    name = Path(filename or "").name.strip()
    if not name or name in {".", ".."}:
        raise ValidationError("A valid filename is required.")
    sanitized = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    if not sanitized:
        raise ValidationError("A valid filename is required.")
    return sanitized[:240]


def _safe_path_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not safe:
        raise NotFoundError("Invalid module or version identifier.")
    return safe[:120]

