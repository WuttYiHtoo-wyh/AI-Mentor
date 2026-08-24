from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.retrieval_experiment.experiment3 import run_experiment3


def main() -> int:
    parser = argparse.ArgumentParser(description="Run source-balanced retrieval Experiment 3.")
    parser.add_argument(
        "--config",
        default="configs/retrieval_experiment3.yaml",
        help="Path to Experiment 3 YAML config.",
    )
    args = parser.parse_args()
    result = run_experiment3(config_path=ROOT / args.config, workspace_root=ROOT)
    print(json.dumps(_summary(result), indent=2))
    return 0


def _summary(result: dict) -> dict:
    return {
        "embedding_model": result["embedding_model"],
        "selected_candidate_pool_config": result["selected_candidate_pool_config"],
        "selected_threshold": result["selected_threshold"],
        "test_question_count": result["test_question_count"],
        "comparison": result["comparison"],
        "preferred_role_candidate_recall": result["preferred_role_candidate_recall"],
        "recovered_missing_authoritative_candidates": result["recovered_missing_authoritative_candidates"],
        "deliverables_query_diagnostics": {
            key: value
            for key, value in result["deliverables_query_diagnostics"].items()
            if key
            in {
                "question",
                "intent",
                "preferred_role",
                "correct_deliverables_rank_1",
                "correct_deliverables_top_3",
                "correct_deliverables_top_5",
            }
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
