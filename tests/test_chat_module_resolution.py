from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.mentor_response.chat_service import (
    KNOWLEDGE_UNAVAILABLE_ANSWER,
    ChatModuleConfig,
    answer_chat_turn,
    load_chat_module_config,
)


class ChatModuleResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.registry = self.workspace / "configs" / "chat_modules.yaml"
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(
            "\n".join(
                [
                    "default_module_id: STATIC",
                    "default_level: Basic",
                    "modules:",
                    "  - module_id: STATIC",
                    "    level: Basic",
                    "    module_name: Static Module",
                    "    retrieval_config_path: configs/static_retrieval.yaml",
                    "    response_model: gpt-4o-mini",
                    "    max_output_tokens: 500",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (self.workspace / "configs" / "static_retrieval.yaml").write_text("collection_name: static\n", encoding="utf-8")
        self.admin_config = ChatModuleConfig(
            module_id="STATIC",
            level="Basic",
            module_name="Admin Module",
            retrieval_config_path=self.workspace / "data" / "published_configs" / "admin.yaml",
            response_model="gpt-4o-mini",
            max_output_tokens=500,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_static_collection_exists_uses_static_path(self) -> None:
        with (
            patch("backend.mentor_response.chat_service._retrieval_collection_exists", return_value=True) as exists,
            patch("backend.mentor_response.chat_service._load_admin_published_module_config") as admin,
        ):
            config = load_chat_module_config("STATIC", "Basic", self.registry, self.workspace)

        self.assertEqual(config.module_name, "Static Module")
        self.assertEqual(config.retrieval_config_path, self.workspace / "configs" / "static_retrieval.yaml")
        self.assertTrue(config.knowledge_available)
        exists.assert_called_once()
        admin.assert_not_called()

    def test_static_missing_admin_active_version_uses_admin_path(self) -> None:
        with (
            patch("backend.mentor_response.chat_service._retrieval_collection_exists", side_effect=[False, True]) as exists,
            patch("backend.mentor_response.chat_service._load_admin_published_module_config", return_value=self.admin_config) as admin,
        ):
            config = load_chat_module_config("STATIC", "Basic", self.registry, self.workspace)

        self.assertEqual(config.module_name, "Admin Module")
        self.assertEqual(config.retrieval_config_path, self.admin_config.retrieval_config_path)
        self.assertTrue(config.knowledge_available)
        self.assertEqual(exists.call_count, 2)
        admin.assert_called_once_with("STATIC", "Basic", self.workspace)

    def test_static_missing_no_admin_returns_controlled_unavailable_response(self) -> None:
        with (
            patch("backend.mentor_response.chat_service._retrieval_collection_exists", return_value=False),
            patch("backend.mentor_response.chat_service._load_admin_published_module_config", return_value=None),
            patch("backend.mentor_response.chat_service.retrieve_experiment3_evidence") as retrieve,
        ):
            config = load_chat_module_config("STATIC", "Basic", self.registry, self.workspace)
            result = answer_chat_turn("What is this module about?", config, self.workspace)

        self.assertFalse(config.knowledge_available)
        self.assertEqual(result["answer"], KNOWLEDGE_UNAVAILABLE_ANSWER)
        self.assertEqual(result["sources"], [])
        self.assertTrue(result["no_context"])
        retrieve.assert_not_called()

    def test_greeting_still_works_when_knowledge_unavailable(self) -> None:
        config = ChatModuleConfig(
            module_id="STATIC",
            level="Basic",
            module_name="Static Module",
            retrieval_config_path=self.workspace / "missing.yaml",
            response_model="gpt-4o-mini",
            max_output_tokens=500,
            knowledge_available=False,
        )
        with patch("backend.mentor_response.chat_service.retrieve_experiment3_evidence") as retrieve:
            result = answer_chat_turn("Hi", config, self.workspace)

        self.assertEqual(result["answer"], "Hi! How can I help you with your module today?")
        self.assertFalse(result["no_context"])
        retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
