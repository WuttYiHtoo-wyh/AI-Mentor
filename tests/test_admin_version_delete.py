from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import chromadb
import fitz

from backend.admin.models import PublishJob
from backend.admin.preparation_service import AdminPreparationService
from backend.admin.repository import NotFoundError
from backend.admin.review_service import AdminReviewService
from backend.admin.service import AdminPersistenceService, ValidationError, _now
from backend.admin.sqlite_repository import SQLiteAdminRepository
from backend.admin.upload_service import AdminUploadService
from backend.admin.version_delete_service import AdminVersionDeleteService


class AdminVersionDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace = Path(self.tmp.name)
        self.repository = SQLiteAdminRepository(self.workspace / "data" / "ai_mentor.db")
        self.repository.initialize()
        self.persistence = AdminPersistenceService(self.repository)
        self.upload_root = self.workspace / "data" / "uploads"
        self.chroma_root = self.workspace / "data" / "admin_chroma"
        self.uploads = AdminUploadService(self.repository, self.upload_root)
        self.preparation = AdminPreparationService(
            self.repository,
            workspace_root=self.workspace,
            prepared_root=self.workspace / "data" / "prepared",
        )
        self.review = AdminReviewService(self.repository)
        self.delete = AdminVersionDeleteService(self.repository, upload_root=self.upload_root, chroma_root=self.chroma_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_delete_draft_version_with_documents_chunks_jobs_and_files(self) -> None:
        version = self._create_version("RESET-DMV", "Reset DMV")
        doc_a = self._upload_pdf(version.id, "brief-a.pdf", "First prepared document has enough words for chunk creation and review.")
        doc_b = self._upload_pdf(version.id, "brief-b.pdf", "Second prepared document has enough words for chunk creation and review.")
        file_paths = [Path(doc_a.file_path), Path(doc_b.file_path)]
        job = self.preparation.prepare_version(version_id=version.id, created_by="tester")
        chunks = self.repository.list_chunks_for_version(version.id)
        self.assertGreater(len(chunks), 0)
        self.review.set_chunk_review_status(chunks[0].id, review_status="REJECTED", reviewer="lecturer")

        result = self.delete.delete_version(version.id)

        self.assertTrue(result["deleted"])
        self.assertEqual(result["removed_documents"], 2)
        self.assertEqual(result["removed_chunks"], len(chunks))
        self.assertEqual(result["removed_preparation_jobs"], 1)
        self.assertGreaterEqual(result["removed_review_events"], 1)
        self.assertEqual(result["removed_files"], 2)
        self.assertFalse(any(path.exists() for path in file_paths))
        with self.assertRaises(NotFoundError):
            self.persistence.get_module_version(version.id)
        self.assertEqual(self.repository.list_chunks_for_version(version.id), [])
        self.assertIsNone(self.repository.get_preparation_job(job.id))

    def test_duplicate_filenames_do_not_affect_other_versions(self) -> None:
        v1 = self._create_version("DUP-MOD", "Duplicate Module", version_label="v1")
        v2 = self._create_version("DUP-MOD", "Duplicate Module", version_label="v2")
        first = self._upload_pdf(v1.id, "DMV-Project_Brief_Basic-v1-formatted.pdf", "First duplicate belongs to deleted version.")
        second = self._upload_pdf(v2.id, "DMV-Project_Brief_Basic-v1-formatted.pdf", "Second duplicate belongs to kept version.")
        self.preparation.prepare_version(version_id=v1.id, created_by="tester")
        self.preparation.prepare_version(version_id=v2.id, created_by="tester")
        second_chunks = self.repository.list_chunks_for_version(v2.id)

        self.delete.delete_version(v1.id)

        self.assertIsNotNone(self.persistence.get_module_version(v2.id))
        self.assertEqual([doc.id for doc in self.persistence.list_documents_for_version(v2.id)], [second.id])
        self.assertTrue(Path(second.file_path).exists())
        self.assertFalse(Path(first.file_path).exists())
        self.assertEqual(len(self.repository.list_chunks_for_version(v2.id)), len(second_chunks))

    def test_published_active_version_deletion_is_blocked(self) -> None:
        version = self._create_version("PUB-BLOCK", "Published Block")
        document = self._upload_pdf(version.id, "brief.pdf", "Published version document must be protected from deletion.")
        self.preparation.prepare_version(version_id=version.id, created_by="tester")
        self.repository.activate_module_version(
            version.id,
            published_by="tester",
            published_at=_now(),
            collection_name="active_collection",
            vector_store_path=str(self.chroma_root),
            retrieval_config_path=str(self.workspace / "published.yaml"),
        )

        with self.assertRaisesRegex(ValidationError, "Published versions cannot be deleted directly"):
            self.delete.delete_version(version.id)

        self.assertIsNotNone(self.persistence.get_module_version(version.id))
        self.assertIsNotNone(self.persistence.get_document(document.id))
        self.assertTrue(Path(document.file_path).exists())
        self.assertGreater(len(self.repository.list_chunks_for_version(version.id)), 0)

    def test_cross_module_isolation_and_unrelated_volume_data_untouched(self) -> None:
        delete_version = self._create_version("DELETE-ONLY", "Delete Only")
        keep_version = self._create_version("KEEP-ONLY", "Keep Only")
        delete_doc = self._upload_pdf(delete_version.id, "shared.pdf", "Document in deleted module version.")
        keep_doc = self._upload_pdf(keep_version.id, "shared.pdf", "Document in unrelated module version.")
        unrelated_file = self.workspace / "data" / "uploads" / "unrelated-runtime-file.txt"
        unrelated_file.parent.mkdir(parents=True, exist_ok=True)
        unrelated_file.write_text("do not delete", encoding="utf-8")
        self.preparation.prepare_version(version_id=delete_version.id, created_by="tester")
        self.preparation.prepare_version(version_id=keep_version.id, created_by="tester")
        keep_chunks = self.repository.list_chunks_for_version(keep_version.id)

        self.delete.delete_version(delete_version.id)

        self.assertFalse(Path(delete_doc.file_path).exists())
        self.assertTrue(Path(keep_doc.file_path).exists())
        self.assertTrue(unrelated_file.exists())
        self.assertIsNotNone(self.persistence.get_module_version(keep_version.id))
        self.assertEqual(len(self.repository.list_chunks_for_version(keep_version.id)), len(keep_chunks))

    def test_unpublished_owned_chroma_collection_removed_and_unrelated_collection_kept(self) -> None:
        version = self._create_version("CHROMA-DEL", "Chroma Delete")
        self._upload_pdf(version.id, "brief.pdf", "Chroma staging cleanup document.")
        self.preparation.prepare_version(version_id=version.id, created_by="tester")
        owned_collection = "owned_staging_collection"
        other_collection = "other_collection"
        self._create_collection(owned_collection, version.id)
        self._create_collection(other_collection, "other-version")
        self.repository.create_publish_job(PublishJob(
            id=str(uuid4()),
            module_version_id=version.id,
            status="FAILED",
            started_at=None,
            completed_at=None,
            requested_by="tester",
            source_chunk_count=1,
            embedded_chunk_count=1,
            collection_name=owned_collection,
            error_message="staging only",
            created_at=_now(),
        ))
        self.repository.create_publish_job(PublishJob(
            id=str(uuid4()),
            module_version_id=version.id,
            status="FAILED",
            started_at=None,
            completed_at=None,
            requested_by="tester",
            source_chunk_count=1,
            embedded_chunk_count=1,
            collection_name=other_collection,
            error_message="should not delete mixed ownership",
            created_at=_now(),
        ))

        result = self.delete.delete_version(version.id)
        client = chromadb.PersistentClient(path=str(self.chroma_root))

        self.assertEqual(result["removed_publish_jobs"], 2)
        self.assertEqual(result["removed_chroma_collections"], 1)
        with self.assertRaises(Exception):
            client.get_collection(owned_collection)
        self.assertIsNotNone(client.get_collection(other_collection))
        self.assertTrue(any("outside this version" in warning for warning in result["warnings"]))

    def test_invalid_version_id_returns_not_found(self) -> None:
        with self.assertRaises(NotFoundError):
            self.delete.delete_version("missing-version")

    def _create_version(self, module_code: str, name: str, version_label: str = "v1"):
        module = self.repository.get_module_by_code(module_code) or self.persistence.create_module(module_code=module_code, name=name)
        return self.persistence.create_module_version(module_id=module.id, version=version_label, level="Basic")

    def _upload_pdf(self, version_id: str, filename: str, body: str):
        return self.uploads.save_document_upload(
            version_id=version_id,
            original_filename=filename,
            content=_pdf_bytes("Document", [body, "Task 1: Prepare data.", "Expected outcome: version reset remains isolated and safe."]),
            document_type="project_brief",
            knowledge_role="OFFICIAL_REQUIREMENT",
        )

    def _create_collection(self, collection_name: str, version_id: str) -> None:
        self.chroma_root.mkdir(parents=True, exist_ok=True)
        collection = chromadb.PersistentClient(path=str(self.chroma_root)).create_collection(collection_name)
        collection.add(
            ids=[f"{collection_name}-chunk"],
            embeddings=[[1.0, 0.0, 0.5]],
            documents=["staging document"],
            metadatas=[{"module_version": version_id}],
        )


def _pdf_bytes(title: str, lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join([title, *lines]), fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


if __name__ == "__main__":
    unittest.main()