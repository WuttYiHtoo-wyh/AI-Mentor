from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from backend.admin.preparation_service import AdminPreparationService
from backend.admin.service import AdminPersistenceService, ValidationError
from backend.admin.sqlite_repository import SQLiteAdminRepository
from backend.admin.upload_service import AdminUploadService


class AdminPhase2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.repository = SQLiteAdminRepository(self.workspace / "data" / "ai_mentor.db")
        self.repository.initialize()
        self.persistence = AdminPersistenceService(self.repository)
        self.uploads = AdminUploadService(self.repository, self.workspace / "data" / "uploads")
        self.preparation = AdminPreparationService(
            self.repository,
            workspace_root=self.workspace,
            prepared_root=self.workspace / "data" / "prepared",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_upload_validation_rejects_invalid_extension_and_empty_file(self) -> None:
        version = self._create_version("MOD-A", "Module A")
        with self.assertRaises(ValidationError):
            self.uploads.save_document_upload(
                version_id=version.id,
                original_filename="../bad.exe",
                content=b"not empty",
                document_type="project_brief",
                knowledge_role="OFFICIAL_REQUIREMENT",
            )
        with self.assertRaises(ValidationError):
            self.uploads.save_document_upload(
                version_id=version.id,
                original_filename="empty.pdf",
                content=b"",
                document_type="project_brief",
                knowledge_role="OFFICIAL_REQUIREMENT",
            )

    def test_upload_creates_safe_document_metadata(self) -> None:
        version = self._create_version("MOD-A", "Module A")
        document = self.uploads.save_document_upload(
            version_id=version.id,
            original_filename="../Brief With Spaces.pdf",
            content=_pdf_bytes("Module A Brief", ["You are required to:", "Create a clean dataset.", "Expected outcome: A clean file."]),
            document_type="project_brief",
            knowledge_role="OFFICIAL_REQUIREMENT",
            uploaded_by="lecturer",
        )
        self.assertEqual(document.original_filename, "Brief With Spaces.pdf")
        self.assertEqual(document.file_type, "pdf")
        self.assertTrue(Path(document.file_path).exists())
        self.assertNotEqual(document.stored_filename, document.original_filename)
        self.assertEqual(document.status, "UPLOADED")

    def test_prepare_version_imports_chunks_job_and_warnings(self) -> None:
        version = self._create_version("MOD-A", "Module A")
        self.uploads.save_document_upload(
            version_id=version.id,
            original_filename="brief.pdf",
            content=_pdf_bytes("Project Brief", ["Task 1: Prepare Data", "You are required to:", "Import the source data.", "Clean the source data.", "Expected outcome: Clean data is ready."]),
            document_type="project_brief",
            knowledge_role="OFFICIAL_REQUIREMENT",
        )
        job = self.preparation.prepare_version(version_id=version.id, created_by="lecturer")
        self.assertIn(job.status, {"COMPLETED", "COMPLETED_WITH_WARNINGS"})
        self.assertGreater(job.chunk_count, 0)
        self.assertTrue(Path(job.output_path, "prepared_chunks.jsonl").exists())
        self.assertTrue(Path(job.validation_report_path).exists())
        chunks = self.persistence.list_prepared_chunks(job.id)
        self.assertGreater(len(chunks), 0)
        refreshed = self.persistence.get_module_version(version.id)
        self.assertIn(refreshed.status, {"PREPARED", "NEEDS_REVIEW"})

    def test_unsupported_preparation_format_is_not_silently_chunked(self) -> None:
        version = self._create_version("MOD-A", "Module A")
        document = self.uploads.save_document_upload(
            version_id=version.id,
            original_filename="slides.pptx",
            content=b"placeholder pptx bytes",
            document_type="instructional_unit",
            knowledge_role="LEARNING_MATERIAL",
            instructional_unit="IU1",
        )
        job = self.preparation.prepare_version(version_id=version.id)
        self.assertEqual(job.status, "FAILED")
        self.assertEqual(job.chunk_count, 0)
        warnings = self.persistence.list_preparation_warnings(job.id)
        self.assertEqual(warnings[0].warning_type, "unsupported_preparation_format")
        self.assertEqual(self.persistence.get_document(document.id).status, "NEEDS_REVIEW")

    def test_two_independent_modules_prepare_through_same_services(self) -> None:
        dmv_version = self._create_version("PDDS-DMV-SYNTH", "Data Modelling and Visualisation")
        programming_version = self._create_version("PROG-FUND-SYNTH", "Programming Fundamentals", level="Foundation")
        self.uploads.save_document_upload(
            version_id=dmv_version.id,
            original_filename="dmv-brief.pdf",
            content=_pdf_bytes("DMV Brief", ["Task 1: Prepare Data", "You are required to:", "Load data.", "Clean data."]),
            document_type="project_brief",
            knowledge_role="OFFICIAL_REQUIREMENT",
        )
        self.uploads.save_document_upload(
            version_id=programming_version.id,
            original_filename="programming-iu1.pdf",
            content=_pdf_bytes("Programming IU1", ["Variables", "A variable stores a value.", "Functions", "A function groups reusable logic."]),
            document_type="instructional_unit",
            knowledge_role="LEARNING_MATERIAL",
            instructional_unit="IU1",
        )
        dmv_job = self.preparation.prepare_version(version_id=dmv_version.id)
        programming_job = self.preparation.prepare_version(version_id=programming_version.id)
        self.assertGreater(dmv_job.chunk_count, 0)
        self.assertGreater(programming_job.chunk_count, 0)
        self.assertNotEqual(dmv_job.module_version_id, programming_job.module_version_id)
        self.assertEqual(len(self.persistence.list_prepared_chunks(dmv_job.id)), dmv_job.chunk_count)
        self.assertEqual(len(self.persistence.list_prepared_chunks(programming_job.id)), programming_job.chunk_count)

    def _create_version(self, module_code: str, name: str, level: str = "Basic"):
        module = self.persistence.create_module(module_code=module_code, name=name)
        return self.persistence.create_module_version(module_id=module.id, version="v1", level=level)


def _pdf_bytes(title: str, lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "\n".join([title, *lines]), fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


if __name__ == "__main__":
    unittest.main()

