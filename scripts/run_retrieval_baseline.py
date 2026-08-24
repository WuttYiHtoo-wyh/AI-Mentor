from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.retrieval_experiment import run_retrieval_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a pure semantic retrieval baseline experiment.")
    parser.add_argument(
        "--config",
        default="configs/retrieval_baseline.yaml",
        help="Path to retrieval baseline YAML config.",
    )
    args = parser.parse_args()
    result = run_retrieval_baseline(config_path=ROOT / args.config, workspace_root=ROOT)
    print(json.dumps(_summary(result), indent=2))
    return 0


def _summary(result: dict) -> dict:
    return {
        "embedding_model": result["embedding_model"],
        "chunks_embedded": result["chunks_embedded"],
        "collection_name": result["collection_name"],
        "test_question_count": result["test_question_count"],
        "distance_summary": result["distance_summary"],
    }


if __name__ == "__main__":
    raise SystemExit(main())

