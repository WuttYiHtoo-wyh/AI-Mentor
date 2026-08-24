from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import chromadb
import fitz

from backend.mentor_response.chat_service import load_chat_module_config
from backend.admin.preparation_service import AdminPreparationService
from backend.admin.publish_service import AdminPublishService
from backend.admin.review_service import AdminReviewService
from backend.admin.service import AdminPersistenceService, ValidationError
from backend.admin.sqlite_repository import SQLiteAdminRepository
from backend.admin.upload_service import AdminUploadService
from backend.retrieval_experiment.retriever import retrieve_with_embedding


class FakeEmbedder:
    def __init__(self, _model: str, fail: bool = False) -> None:
        self.fail = fail

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("simulated embedding failure")
        return [[float(len(text) % 10), 1.0, 0.5] for text in texts]


class AdminPhase4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workspace = Path(self.tmp.name)
        self.repository = SQLiteAdminRepository(self.workspace / "data" / "ai_mentor.db")
        self.repository.initialize()
        self.persistence = AdminPersistenceService(self.repository)
        self.uploads = AdminUploadService(self.repository, self.workspace / "data" / "uploads")
        self.preparation = AdminPreparationService(self.repository, workspace_root=self.workspace, prepared_root=self.workspace / "data" / "prepared")
        self.review = AdminReviewService(self.repository)
        self.publish = self._publish_service()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_non_approved_version_cannot_publish(self) -> None:
        version = self._prepare_reviewed_version("PROG", "Programming Fundamentals", approve_version=False)
        with self.assertRaises(ValidationError):
            self.publish.publish_version(version_id=version.id, requested_by="lecturer")

    def test_approved_version_publishes_only_approved_eligible_chunks_and_activates(self) -> None:
        version = self._prepare_reviewed_version("PROG", "Programming Fundamentals")
        job = self.publish.publish_version(version_id=version.id, requested_by="lecturer")
        self.assertEqual(job.status, "COMPLETED")
        self.assertGreater(job.embedded_chunk_count, 0)
        active = self.repository.get_active_module_version("PROG", "Basic")
        self.assertIsNotNone(active)
        self.assertEqual(active.id, version.id)
        collection = chromadb.PersistentClient(path=str(self.workspace / "data" / "admin_chroma")).get_collection(job.collection_name)
        rows = collection.get(where={"module_id": "PROG"}, include=["metadatas"])
        self.assertEqual(len(rows["ids"]), job.embedded_chunk_count)
        self.assertTrue(all(meta["review_status"] == "APPROVED" for meta in rows["metadatas"]))
        self.assertTrue(all(meta["module_version"] == version.id for meta in rows["metadatas"]))

    def test_failed_publish_does_not_replace_previous_active_version(self) -> None:
        v1 = self._prepare_reviewed_version("PROG", "Programming Fundamentals", version_label="v1")
        first = self.publish.publish_version(version_id=v1.id, requested_by="lecturer")
        self.assertEqual(first.status, "COMPLETED")
        v2 = self._prepare_reviewed_version("PROG", "Programming Fundamentals", version_label="v2")
        failing = self._publish_service(fail=True)
        failed_job = failing.publish_version(version_id=v2.id, requested_by="lecturer")
        self.assertEqual(failed_job.status, "FAILED")
        active = self.repository.get_active_module_version("PROG", "Basic")
        self.assertEqual(active.id, v1.id)
        self.assertNotEqual(active.id, v2.id)

    def test_version_switch_keeps_old_published_inactive(self) -> None:
        v1 = self._prepare_reviewed_version("PROG", "Programming Fundamentals", version_label="v1")
        first = self.publish.publish_version(version_id=v1.id, requested_by="lecturer")
        v2 = self._prepare_reviewed_version("PROG", "Programming Fundamentals", version_label="v2")
        second = self.publish.publish_version(version_id=v2.id, requested_by="lecturer")
        old = self.persistence.get_module_version(v1.id)
        active = self.repository.get_active_module_version("PROG", "Basic")
        self.assertEqual(first.status, "COMPLETED")
        self.assertEqual(second.status, "COMPLETED")
        self.assertEqual(old.status, "PUBLISHED")
        self.assertFalse(old.is_active)
        self.assertEqual(active.id, v2.id)
        self.assertNotEqual(first.collection_name, second.collection_name)

    def test_cross_module_vector_isolation(self) -> None:
        prog = self._prepare_reviewed_version("PROG", "Programming Fundamentals")
        dmv = self._prepare_reviewed_version("DMV-SYNTH", "Data Modelling and Visualisation")
        prog_job = self.publish.publish_version(version_id=prog.id, requested_by="lecturer")
        dmv_job = self.publish.publish_version(version_id=dmv.id, requested_by="lecturer")
        client = chromadb.PersistentClient(path=str(self.workspace / "data" / "admin_chroma"))
        prog_rows = client.get_collection(prog_job.collection_name).get(where={"module_id": "PROG"}, include=["metadatas"])
        dmv_rows = client.get_collection(dmv_job.collection_name).get(where={"module_id": "DMV-SYNTH"}, include=["metadatas"])
        self.assertGreater(len(prog_rows["ids"]), 0)
        self.assertGreater(len(dmv_rows["ids"]), 0)
        self.assertEqual(client.get_collection(prog_job.collection_name).get(where={"module_id": "DMV-SYNTH"})["ids"], [])
        self.assertEqual(client.get_collection(dmv_job.collection_name).get(where={"module_id": "PROG"})["ids"], [])

    def test_admin_published_module_resolves_and_retrieves_with_existing_retriever(self) -> None:
        version = self._prepare_reviewed_version("PROG", "Programming Fundamentals")
        job = self.publish.publish_version(version_id=version.id, requested_by="lecturer")
        registry = self.workspace / "configs" / "chat_modules.yaml"
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text("default_module_id: STATIC\ndefault_level: Basic\nmodules: []\n", encoding="utf-8")
        chat_config = load_chat_module_config("PROG", "Basic", registry, self.workspace)
        self.assertEqual(chat_config.module_id, "PROG")
        rows = retrieve_with_embedding(
            query_embedding=[1.0, 1.0, 0.5],
            module_id="PROG",
            level="Basic",
            top_k=3,
            chroma_path=self.workspace / "data" / "admin_chroma",
            collection_name=job.collection_name,
        )
        self.assertGreater(len(rows), 0)
        self.assertTrue(all(row["module_id"] == "PROG" for row in rows))

    def _publish_service(self, fail: bool = False) -> AdminPublishService:
        return AdminPublishService(
            self.repository,
            workspace_root=self.workspace,
            chroma_root=self.workspace / "data" / "admin_chroma",
            config_root=self.workspace / "data" / "published_configs",
            embedder_factory=lambda model: FakeEmbedder(model, fail=fail),
        )

    def _prepare_reviewed_version(self, code: str, name: str, version_label: str = "v1", approve_version: bool = True):
        module = self.repository.get_module_by_code(code) or self.persistence.create_module(module_code=code, name=name)
        version = self.persistence.create_module_version(module_id=module.id, version=version_label, level="Basic")
        self.uploads.save_document_upload(
            version_id=version.id,
            original_filename=f"{code}-{version_label}.pdf",
            content=_pdf_bytes(f"{name} {version_label}\nThis approved source explains a complete concept for {code}. It has enough words to become a semantically useful chunk for publication and retrieval isolation checks."),
            document_type="instructional_unit",
            knowledge_role="LEARNING_MATERIAL",
            instructional_unit="IU1",
        )
        prep = self.preparation.prepare_version(version_id=version.id, created_by="tester")
        for chunk in self.persistence.list_prepared_chunks(prep.id):
            self.review.set_chunk_review_status(chunk.id, review_status="APPROVED", reviewer="lecturer")
        if approve_version:
            self.review.approve_version(version_id=version.id, approved_by="lead")
        return version


def _pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


if __name__ == "__main__":
    unittest.main()
