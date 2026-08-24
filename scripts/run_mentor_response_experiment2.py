from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.mentor_response.experiment2 import run_mentor_response_experiment2


def main() -> int:
    parser = argparse.ArgumentParser(description="Run targeted AI Mentor response Experiment 2.")
    parser.add_argument(
        "--config",
        default="configs/mentor_response_experiment2.yaml",
        help="Path to response Experiment 2 YAML config.",
    )
    args = parser.parse_args()
    result = run_mentor_response_experiment2(config_path=ROOT / args.config, workspace_root=ROOT)
    print(json.dumps(_summary(result), indent=2))
    return 0


def _summary(result: dict) -> dict:
    return {
        "response_model": result["response_model"],
        "test_count": result["test_count"],
        "summary": result["summary"],
        "targeted_results": {
            test_id: value["evaluation"]
            for test_id, value in result["targeted_results"].items()
        },
        "regressions": result["regressions"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
