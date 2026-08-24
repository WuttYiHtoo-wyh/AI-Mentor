from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.api.main import app


class AdminUiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.root = Path(__file__).resolve().parents[1]

    def test_admin_tab_and_assets_load(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Lecturer Workspace", response.text)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)
        self.assertEqual(self.client.get("/static/styles.css").status_code, 200)

    def test_admin_frontend_contains_required_workflow_labels(self) -> None:
        app_js = (self.root / "frontend" / "learner_chat" / "app.js").read_text(encoding="utf-8")
        for text in [
            "Create AI Mentor Module",
            "Set Up Module Knowledge",
            "Add Course Documents",
            "Prepare Knowledge",
            "Review Knowledge",
            "Approve Knowledge Version",
            "Select All",
            "selectAllDisplayedChunks",
            "Publish to AI Mentor",
            "Upload supported; preparation not yet supported",
        ]:
            self.assertIn(text, app_js)

    def test_existing_pages_still_route(self) -> None:
        self.assertEqual(self.client.post("/api/chat", json={"message": "Write my assignment. I will copy paste from u"}).status_code, 200)
        self.assertEqual(self.client.get("/api/evaluation/summary").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/metadata").status_code, 200)


if __name__ == "__main__":
    unittest.main()
