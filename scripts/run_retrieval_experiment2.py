from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.retrieval_experiment.experiment2 import run_experiment2


def main() -> int:
    parser = argparse.ArgumentParser(description="Run metadata-aware retrieval Experiment 2.")
    parser.add_argument(
        "--config",
        default="configs/retrieval_experiment2.yaml",
        help="Path to Experiment 2 YAML config.",
    )
    args = parser.parse_args()
    result = run_experiment2(config_path=ROOT / args.config, workspace_root=ROOT)
    print(json.dumps(_summary(result), indent=2))
    return 0


def _summary(result: dict) -> dict:
    return {
        "embedding_model": result["embedding_model"],
        "candidate_pool_size": result["candidate_pool_size"],
        "selected_threshold": result["selected_threshold"],
        "test_question_count": result["test_question_count"],
        "comparison": result["comparison"],
        "threshold_evaluation": result["threshold_evaluation"],
    }


if __name__ == "__main__":
    raise SystemExit(main())

