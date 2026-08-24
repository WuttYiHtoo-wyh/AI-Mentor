from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.admin.models import ModuleVersion
from backend.admin.repository import DuplicateRecordError, NotFoundError, RepositoryError
from backend.admin.service import AdminPersistenceService, ValidationError
from backend.admin.sqlite_repository import SQLiteAdminRepository


class AdminPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "ai_mentor_test.db"
        self.repository = SQLiteAdminRepository(self.db_path)
        self.service = AdminPersistenceService(self.repository)
        self.service.initialize()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_initialization_is_repeatable(self) -> None:
        self.service.initialize()
        module = self.service.create_module(module_code="MOD-A", name="Module A")
        self.service.initialize()
        self.assertEqual(self.service.get_module(module.id).module_code, "MOD-A")

    def test_unique_module_code(self) -> None:
        self.service.create_module(module_code="MOD-A", name="Module A")
        with self.assertRaises(DuplicateRecordError):
            self.service.create_module(module_code="MOD-A", name="Duplicate Module A")

    def test_create_list_retrieve_modules(self) -> None:
        dmv = self.service.create_module(
            module_code="PDDS-DMV",
            name="Data Modelling and Visualisation",
            description="Demo module A",
        )
        programming = self.service.create_module(
            module_code="PROG-FUND",
            name="Programming Fundamentals",
            description="Demo module B",
        )
        module_codes = {module.module_code for module in self.service.list_modules()}
        self.assertEqual(module_codes, {"PDDS-DMV", "PROG-FUND"})
        self.assertEqual(self.service.get_module(dmv.id).name, "Data Modelling and Visualisation")
        self.assertEqual(self.service.get_module(programming.id).name, "Programming Fundamentals")

    def test_invalid_module_data_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.service.create_module(module_code="", name="No Code")
        with self.assertRaises(ValidationError):
            self.service.create_module(module_code="BAD", name="", status="DRAFT")
        with self.assertRaises(ValidationError):
            self.service.create_module(module_code="BAD", name="Bad", status="PUBLISHED")

    def test_create_list_retrieve_versions(self) -> None:
        module = self.service.create_module(module_code="MOD-A", name="Module A")
        basic_v1 = self.service.create_module_version(module_id=module.id, version="v1", level="Basic")
        advanced_v1 = self.service.create_module_version(module_id=module.id, version="v1", level="Advanced")
        versions = self.service.list_module_versions(module.id)
        self.assertEqual({version.level for version in versions}, {"Basic", "Advanced"})
        self.assertFalse(self.service.get_module_version(basic_v1.id).is_active)
        self.assertEqual(self.service.get_module_version(advanced_v1.id).version, "v1")

    def test_invalid_parent_module_rejected(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.create_module_version(module_id="missing", version="v1", level="Basic")

    def test_duplicate_version_for_same_module_level_rejected(self) -> None:
        module = self.service.create_module(module_code="MOD-A", name="Module A")
        self.service.create_module_version(module_id=module.id, version="v1", level="Basic")
        with self.assertRaises(DuplicateRecordError):
            self.service.create_module_version(module_id=module.id, version="v1", level="Basic")

    def test_foreign_key_enforced_in_repository(self) -> None:
        version = ModuleVersion(
            id="version-with-missing-parent",
            module_id="missing-module",
            version="v1",
            level="Basic",
            description="",
            status="DRAFT",
            is_active=False,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        with self.assertRaises(RepositoryError):
            self.repository.create_module_version(version)

    def test_create_list_retrieve_document_metadata(self) -> None:
        module = self.service.create_module(module_code="MOD-A", name="Module A")
        version = self.service.create_module_version(module_id=module.id, version="v1", level="Basic")
        brief = self.service.create_document_metadata(
            module_version_id=version.id,
            original_filename="Brief.pdf",
            stored_filename="brief.pdf",
            file_path="storage/uploads/mod-a/v1/doc-1/brief.pdf",
            file_type="pdf",
            document_type="project_brief",
            knowledge_role="OFFICIAL_REQUIREMENT",
            uploaded_by="lecturer@example.test",
        )
        iu = self.service.create_document_metadata(
            module_version_id=version.id,
            original_filename="IU1.pdf",
            stored_filename="iu1.pdf",
            file_path="storage/uploads/mod-a/v1/doc-2/iu1.pdf",
            file_type="pdf",
            document_type="instructional_unit",
            knowledge_role="LEARNING_MATERIAL",
            instructional_unit="IU1",
            uploaded_by="lecturer@example.test",
        )
        documents = self.service.list_documents_for_version(version.id)
        self.assertEqual({document.id for document in documents}, {brief.id, iu.id})
        self.assertEqual(self.service.get_document(iu.id).knowledge_role, "LEARNING_MATERIAL")

    def test_document_role_and_parent_validation(self) -> None:
        module = self.service.create_module(module_code="MOD-A", name="Module A")
        version = self.service.create_module_version(module_id=module.id, version="v1", level="Basic")
        with self.assertRaises(ValidationError):
            self.service.create_document_metadata(
                module_version_id=version.id,
                original_filename="Doc.pdf",
                stored_filename="doc.pdf",
                file_path="storage/doc.pdf",
                file_type="pdf",
                document_type="guide",
                knowledge_role="LECTURER_NOTE",
                uploaded_by="lecturer",
            )
        with self.assertRaises(NotFoundError):
            self.service.create_document_metadata(
                module_version_id="missing-version",
                original_filename="Doc.pdf",
                stored_filename="doc.pdf",
                file_path="storage/doc.pdf",
                file_type="pdf",
                document_type="guide",
                knowledge_role="MODULE_GUIDANCE",
                uploaded_by="lecturer",
            )

    def test_two_unrelated_modules_use_same_services(self) -> None:
        dmv = self.service.create_module(module_code="PDDS-DMV", name="Data Modelling and Visualisation")
        programming = self.service.create_module(module_code="PROG-FUND", name="Programming Fundamentals")
        dmv_version = self.service.create_module_version(module_id=dmv.id, version="v1", level="Basic")
        programming_version = self.service.create_module_version(module_id=programming.id, version="v1", level="Foundation")
        self.service.create_document_metadata(
            module_version_id=dmv_version.id,
            original_filename="DMV Brief.pdf",
            stored_filename="dmv-brief.pdf",
            file_path="storage/uploads/pdds-dmv/v1/brief.pdf",
            file_type="pdf",
            document_type="project_brief",
            knowledge_role="OFFICIAL_REQUIREMENT",
            uploaded_by="lecturer-a",
        )
        self.service.create_document_metadata(
            module_version_id=programming_version.id,
            original_filename="Programming IU1.pdf",
            stored_filename="programming-iu1.pdf",
            file_path="storage/uploads/prog-fund/v1/iu1.pdf",
            file_type="pdf",
            document_type="instructional_unit",
            knowledge_role="LEARNING_MATERIAL",
            instructional_unit="IU1",
            uploaded_by="lecturer-b",
        )
        self.assertEqual(len(self.service.list_documents_for_version(dmv_version.id)), 1)
        self.assertEqual(len(self.service.list_documents_for_version(programming_version.id)), 1)


if __name__ == "__main__":
    unittest.main()

