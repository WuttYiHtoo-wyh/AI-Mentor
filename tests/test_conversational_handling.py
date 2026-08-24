from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.mentor_response.chat_service import ChatModuleConfig, answer_chat_turn
from backend.mentor_response.generator import build_source_references
from backend.mentor_response.prompts import NO_CONTEXT_RESPONSE


class ConversationalHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workspace_root = root
        self.retrieval_config_path = root / "retrieval.yaml"
        self.retrieval_config_path.write_text("prepared_chunks_path: missing.jsonl\n", encoding="utf-8")
        self.module_config = ChatModuleConfig(
            module_id="PDDS-DMV",
            level="Basic",
            module_name="Data Modelling and Visualisation",
            retrieval_config_path=self.retrieval_config_path,
            response_model="gpt-4o-mini",
            max_output_tokens=500,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_simple_conversation_returns_without_retrieval(self) -> None:
        cases = {
            "Hi": "Hi! How can I help you with your module today?",
            "Hello": "Hello! What would you like help with in your module?",
            "Hi, I am Wut": "Hi Wut! How can I help you with your module today?",
            "Good morning": "Good morning! What can I help you with today?",
            "Thanks": "You're welcome.",
            "Thank you": "You're welcome.",
            "Bye": "Goodbye. Come back anytime you need help with your module.",
            "Who are you?": (
                "I'm AI Mentor. I can help explain module requirements, course concepts, practical activities, "
                "and review learner-authored work using approved module materials."
            ),
            "What can you help me with?": (
                "I can help with assessment requirements, rubric expectations, course concepts, practical Power BI "
                "activities, simpler explanations, draft review, improvement guidance, and module guidance."
            ),
        }
        with patch("backend.mentor_response.chat_service.retrieve_experiment3_evidence") as retrieve:
            for message, expected in cases.items():
                with self.subTest(message=message):
                    result = answer_chat_turn(message, self.module_config, self.workspace_root)
                    self.assertEqual(expected, result["answer"])
                    self.assertEqual([], result["sources"])
                    self.assertFalse(result["no_context"])
            retrieve.assert_not_called()


    def test_source_references_use_learner_facing_labels(self) -> None:
        evidence = [
            {
                "document_id": "3d37edb6-3c85-4c90-8085-5d1b2b473278",
                "document_type": "guide",
                "knowledge_role": "MODULE_GUIDANCE",
                "source_file": "/data/uploads/DMV/version/Learner_Guide.pdf",
                "page_start": 1,
                "page_end": 3,
            },
            {
                "document_id": "7f493ead-0c9d-4d78-bf91-e503fcfa0378",
                "document_type": "project_brief",
                "knowledge_role": "OFFICIAL_REQUIREMENT",
                "page_start": 4,
                "page_end": 4,
            },
            {
                "document_id": "69b144b1-03e8-4f99-9ca7-3424398d3bda",
                "document_type": "instructional_unit",
                "knowledge_role": "LEARNING_MATERIAL",
                "instructional_unit": "IU2_2",
                "page_start": 5,
                "page_end": 6,
            },
        ]

        self.assertEqual(
            ["Learner Guide, pages 1-3", "Project Brief, page 4", "IU2_2, pages 5-6"],
            build_source_references(evidence),
        )

    def test_source_references_do_not_fall_back_to_document_uuid(self) -> None:
        references = build_source_references([
            {
                "document_id": "3d37edb6-3c85-4c90-8085-5d1b2b473278",
                "document_type": "",
                "knowledge_role": "",
                "page_start": 1,
                "page_end": 1,
            }
        ])

        self.assertEqual(["Approved module material, page 1"], references)

    def test_module_questions_still_use_retrieval(self) -> None:
        retrieval = {
            "no_context": False,
            "evidence_sufficient": True,
            "results": [{"source_filename": "source.pdf", "page_start": 1, "page_end": 1}],
        }
        generation = {"answer": "Grounded answer.", "source_references": ["source.pdf, page 1"]}
        questions = [
            "What is cardinality?",
            "What do I need to do for Task 2?",
            "Who is the programme manager?",
        ]
        with (
            patch("backend.mentor_response.chat_service.retrieve_experiment3_evidence", return_value=retrieval) as retrieve,
            patch("backend.mentor_response.chat_service.generate_mentor_response", return_value=generation) as generate,
        ):
            for question in questions:
                with self.subTest(question=question):
                    result = answer_chat_turn(question, self.module_config, self.workspace_root)
                    self.assertEqual("Grounded answer.", result["answer"])
                    self.assertEqual(["source.pdf, page 1"], result["sources"])
                    self.assertFalse(result["no_context"])
            self.assertEqual(len(questions), retrieve.call_count)
            self.assertEqual(len(questions), generate.call_count)

    def test_unsupported_general_questions_still_return_no_context(self) -> None:
        retrieval = {"no_context": True, "evidence_sufficient": False, "results": []}
        questions = [
            "Do you know Suga from the South Korean boy band BTS?",
            "How do I cook pasta?",
        ]
        with patch("backend.mentor_response.chat_service.retrieve_experiment3_evidence", return_value=retrieval) as retrieve:
            for question in questions:
                with self.subTest(question=question):
                    result = answer_chat_turn(question, self.module_config, self.workspace_root)
                    self.assertEqual(NO_CONTEXT_RESPONSE, result["answer"])
                    self.assertEqual([], result["sources"])
                    self.assertTrue(result["no_context"])
            self.assertEqual(len(questions), retrieve.call_count)

    def test_academic_integrity_refusal_stays_before_retrieval(self) -> None:
        with patch("backend.mentor_response.chat_service.retrieve_experiment3_evidence") as retrieve:
            result = answer_chat_turn("Write my assignment for me.", self.module_config, self.workspace_root)
            self.assertIn("I can't write a complete assignment", result["answer"])
            self.assertEqual([], result["sources"])
            retrieve.assert_not_called()

    def test_draft_review_still_uses_draft_review_path(self) -> None:
        retrieval = {
            "no_context": False,
            "evidence_sufficient": True,
            "results": [{"source_filename": "brief.pdf", "page_start": 2, "page_end": 2}],
        }
        draft = (
            "Here is my Task 2 answer. Can you review it? "
            "I created a Sales table with Product, Store, and Date tables. "
            "I connected the tables, created hierarchies, and added DAX measures for sales analysis."
        )
        generation = {
            "answer": "Draft review answer.",
            "source_references": ["brief.pdf, page 2"],
            "detected_behavior": "DRAFT_REVIEW",
            "detected_task_or_topic": "Task 2",
        }
        with (
            patch("backend.mentor_response.chat_service.retrieve_experiment3_evidence", return_value=retrieval) as retrieve,
            patch("backend.mentor_response.chat_service.generate_draft_review_response", return_value=generation) as generate,
        ):
            result = answer_chat_turn(draft, self.module_config, self.workspace_root)
            self.assertEqual("Draft review answer.", result["answer"])
            self.assertEqual(["brief.pdf, page 2"], result["sources"])
            retrieve.assert_called_once()
            generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
