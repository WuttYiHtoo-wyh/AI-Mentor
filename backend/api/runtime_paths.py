from __future__ import annotations

import os
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = WORKSPACE_ROOT / "frontend" / "learner_chat"
TESTING_DIR = WORKSPACE_ROOT / "testing"

DATA_DIR_ENV = "AI_MENTOR_DATA_DIR"
_configured_data_dir = os.environ.get(DATA_DIR_ENV, "").strip()

RUNTIME_DATA_ROOT = Path(_configured_data_dir).expanduser() if _configured_data_dir else WORKSPACE_ROOT / "data"

ADMIN_DB_PATH = RUNTIME_DATA_ROOT / "ai_mentor.db"
ADMIN_UPLOAD_ROOT = RUNTIME_DATA_ROOT / "uploads"
ADMIN_PREPARED_ROOT = RUNTIME_DATA_ROOT / "prepared"
ADMIN_CHROMA_ROOT = RUNTIME_DATA_ROOT / "admin_chroma"
ADMIN_PUBLISHED_CONFIG_ROOT = RUNTIME_DATA_ROOT / "published_configs"

HUMAN_REVIEW_PATH = (
    RUNTIME_DATA_ROOT / "human_review_results.json"
    if _configured_data_dir
    else TESTING_DIR / "human_review_results.json"
)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)
