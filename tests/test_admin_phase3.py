from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import fitz
from pydantic import ValidationError as PydanticValidationError

from backend.admin.models import PreparationWarning, PreparedChunkRecord
from backend.admin.preparation_service import AdminPreparationService
from backend.admin.review_service import AdminReviewService
from backend.admin.service import AdminPersistenceService, ValidationError, _now
from backend.admin.sqlite_repository import SQLiteAdminRepository
from backend.admin.upload_service import AdminUploadService
from backend.api.main import AdminChunkMetadataUpdateRequest


class AdminPhase3Tests(unittest.TestCase):
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
        self.review = AdminReviewService(self.repository)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_approve_reject_reset_and_comment_audit(self) -> None:
        version, job = self._prepared_module("MOD-A", "Module A")
        chunk = self.persistence.list_prepared_chunks(job.id)[0]
        approved = self.review.set_chunk_review_status(chunk.id, review_status="APPROVED", reviewer="lecturer", comment="Looks correct")
        self.assertEqual(approved.review_status, "APPROVED")
        self.assertEqual(approved.review_comment, "Looks correct")
        rejected = self.review.set_chunk_review_status(chunk.id, review_status="REJECTED", reviewer="lecturer", comment="Exclude this")
        self.assertEqual(rejected.review_status, "REJECTED")
        reset = self.review.set_chunk_review_status(chunk.id, review_status="NEEDS_REVIEW", reviewer="lecturer", comment="Review again")
        self.assertEqual(reset.review_status, "NEEDS_REVIEW")
        events = self.review.list_review_events("chunk", chunk.id)
        self.assertEqual([event.action for event in events], ["APPROVE_CHUNK", "REJECT_CHUNK", "RESET_CHUNK"])
        self.assertEqual(version.id, job.module_version_id)

    def test_metadata_update_policy_and_content_forbidden(self) -> None:
        _, job = self._prepared_module("MOD-A", "Module A")
        chunk = self.persistence.list_prepared_chunks(job.id)[0]
        updated = self.review.update_chunk_metadata(
            chunk.id,
            updated_by="lecturer",
            comment="Correct topic",
            topic="Corrected Topic",
            task_reference="Task X",
            knowledge_role="LEARNING_MATERIAL",
        )
        self.assertEqual(updated.topic, "Corrected Topic")
        self.assertEqual(updated.metadata_change_comment, "Correct topic")
        with self.assertRaises(ValidationError):
            self.review.update_chunk_metadata(chunk.id, updated_by="lecturer", comment="", knowledge_role="BAD_ROLE")
        with self.assertRaises(PydanticValidationError):
            AdminChunkMetadataUpdateRequest(updated_by="lecturer", content="rewrite chunk")

    def test_bulk_approve_skips_blocking_or_ineligible_chunks(self) -> None:
        version, job = self._prepared_module("MOD-A", "Module A")
        doc_id = self.persistence.list_documents_for_version(version.id)[0].id
        ineligible = PreparedChunkRecord(
            id=str(uuid4()),
            preparation_job_id=job.id,
            module_version_id=version.id,
            document_id=doc_id,
            chunk_id="manual-ineligible",
            section_title="Manual",
            topic="Manual",
            task_reference=None,
            instructional_unit=None,
            page_start=1,
            page_end=1,
            knowledge_role="LEARNING_MATERIAL",
            status="ready",
            embedding_eligible=False,
            warning_count=0,
            content="This is deliberately not embedding eligible.",
            created_at=_now(),
        )
        self.repository.add_prepared_chunks([ineligible])
        result = self.review.approve_document_eligible_chunks(document_id=doc_id, reviewer="lecturer", comment="Bulk approve safe chunks")
        self.assertGreaterEqual(result["updated"], 1)
        refreshed = self.review.get_chunk(ineligible.id)
        self.assertEqual(refreshed.review_status, "NEEDS_REVIEW")
        with self.assertRaises(ValidationError):
            self.review.set_chunk_review_status(ineligible.id, review_status="APPROVED", reviewer="lecturer")

    def test_review_summaries_and_version_approval_flow(self) -> None:
        version, job = self._prepared_module("MOD-A", "Module A")
        chunks = self.persistence.list_prepared_chunks(job.id)
        self.assertFalse(self.review.version_review_summary(version.id)["eligible_for_approval"])
        for chunk in chunks:
            self.review.set_chunk_review_status(chunk.id, review_status="APPROVED", reviewer="lecturer")
        summary = self.review.version_review_summary(version.id)
        self.assertTrue(summary["eligible_for_approval"], summary["approval_blockers"])
        approved = self.review.approve_version(version_id=version.id, approved_by="lead", comment="Ready for publish phase")
        self.assertEqual(approved.status, "APPROVED")
        events = self.review.list_review_events("module_version", version.id)
        self.assertEqual(events[-1].action, "APPROVE_VERSION")
        reopened = self.review.reopen_version(version_id=version.id, actor="lead", comment="Need another review")
        self.assertEqual(reopened.status, "NEEDS_REVIEW")

    def test_failed_pdf_can_be_reprepared_and_approved(self) -> None:
        module = self.persistence.create_module(module_code="DMV-RETRY", name="DMV Retry")
        version = self.persistence.create_module_version(module_id=module.id, version="v1", level="Basic")
        document = self.uploads.save_document_upload(
            version_id=version.id,
            original_filename="DMV-Project_Brief_Basic-v1-formatted.pdf",
            content=_pdf_bytes(
                "DMV Project Brief\n"
                "Task 1: Prepare Data\n"
                "This source contains enough words to form useful knowledge items for review. "
                "It describes project requirements, expected preparation steps, and learner deliverables."
            ),
            document_type="project_brief",
            knowledge_role="OFFICIAL_REQUIREMENT",
        )
        self.persistence.update_document_status(document.id, "FAILED")

        job = self.preparation.prepare_version(version_id=version.id, created_by="tester")
        prepared_document = self.persistence.get_document(document.id)
        chunks = self.persistence.list_prepared_chunks(job.id)
        approved_count = 0
        for chunk in chunks:
            if chunk.embedding_eligible:
                self.review.set_chunk_review_status(chunk.id, review_status="APPROVED", reviewer="lecturer")
                approved_count += 1
            else:
                self.review.set_chunk_review_status(chunk.id, review_status="REJECTED", reviewer="lecturer")

        self.assertIn(job.status, {"COMPLETED", "COMPLETED_WITH_WARNINGS"})
        self.assertEqual(prepared_document.status, "PREPARED")
        self.assertGreater(len(chunks), 0)
        self.assertGreater(approved_count, 0)
        summary = self.review.version_review_summary(version.id)
        self.assertTrue(summary["eligible_for_approval"], summary["approval_blockers"])

    def test_unsupported_uploaded_document_blocks_until_excluded(self) -> None:
        version, job = self._prepared_module("MOD-A", "Module A")
        unsupported = self.uploads.save_document_upload(
            version_id=version.id,
            original_filename="slides.pptx",
            content=b"not really pptx but extension is accepted for upload",
            document_type="instructional_unit",
            knowledge_role="LEARNING_MATERIAL",
            instructional_unit="IU9",
        )
        for chunk in self.persistence.list_prepared_chunks(job.id):
            self.review.set_chunk_review_status(chunk.id, review_status="APPROVED", reviewer="lecturer")
        summary = self.review.version_review_summary(version.id)
        self.assertFalse(summary["eligible_for_approval"])
        self.assertTrue(any("unprepared" in item for item in summary["approval_blockers"]))
        excluded = self.review.exclude_document(document_id=unsupported.id, excluded_by="lecturer", reason="Not part of this prepared V1 set")
        self.assertEqual(excluded.status, "ARCHIVED")
        summary_after = self.review.version_review_summary(version.id)
        self.assertTrue(summary_after["eligible_for_approval"], summary_after["approval_blockers"])

    def test_two_modules_can_reach_approved_with_same_services(self) -> None:
        dmv_version, dmv_job = self._prepared_module("PDDS-DMV-SYNTH", "Data Modelling and Visualisation")
        programming_version, programming_job = self._prepared_module("PROG-FUND-SYNTH", "Programming Fundamentals", level="Foundation")
        for job in [dmv_job, programming_job]:
            for chunk in self.persistence.list_prepared_chunks(job.id):
                self.review.set_chunk_review_status(chunk.id, review_status="APPROVED", reviewer="lecturer")
        approved_a = self.review.approve_version(version_id=dmv_version.id, approved_by="lead")
        approved_b = self.review.approve_version(version_id=programming_version.id, approved_by="lead")
        self.assertEqual(approved_a.status, "APPROVED")
        self.assertEqual(approved_b.status, "APPROVED")

    def _prepared_module(self, module_code: str, name: str, level: str = "Basic"):
        module = self.persistence.create_module(module_code=module_code, name=name)
        version = self.persistence.create_module_version(module_id=module.id, version="v1", level=level)
        self.uploads.save_document_upload(
            version_id=version.id,
            original_filename=f"{module_code}.pdf",
            content=_pdf_bytes(
                f"{name}\n"
                "Section One\n"
                "This source contains enough words to form a useful chunk for review and approval. "
                "It explains a complete idea with traceable source text and no module-specific parser rules. "
                "The lecturer can inspect, approve, reject, or return this chunk to review."
            ),
            document_type="instructional_unit",
            knowledge_role="LEARNING_MATERIAL",
            instructional_unit="IU1",
        )
        job = self.preparation.prepare_version(version_id=version.id, created_by="tester")
        self.assertGreater(job.chunk_count, 0)
        return version, job


def _pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


if __name__ == "__main__":
    unittest.main()

