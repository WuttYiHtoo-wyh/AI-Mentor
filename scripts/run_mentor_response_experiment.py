from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.mentor_response.experiment import run_mentor_response_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AI Mentor response-layer experiment.")
    parser.add_argument(
        "--config",
        default="configs/mentor_response_experiment.yaml",
        help="Path to response-layer experiment YAML config.",
    )
    args = parser.parse_args()
    result = run_mentor_response_experiment(config_path=ROOT / args.config, workspace_root=ROOT)
    print(json.dumps(_summary(result), indent=2))
    return 0


def _summary(result: dict) -> dict:
    return {
        "response_model": result["response_model"],
        "test_count": result["test_count"],
        "summary": result["summary"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
