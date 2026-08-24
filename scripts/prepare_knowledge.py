from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.knowledge_preparation import prepare_module


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare source documents into validated knowledge chunks.")
    parser.add_argument(
        "--config",
        default="configs/modules/dmv_basic.yaml",
        help="Path to a module source registry YAML file.",
    )
    args = parser.parse_args()

    report = prepare_module(config_path=ROOT / args.config, workspace_root=ROOT)
    print(json.dumps(_summary(report), indent=2))
    return 1 if report["errors"] else 0


def _summary(report: dict) -> dict:
    return {
        "module_id": report["module_id"],
        "source_count": report["source_count"],
        "chunk_count": report["chunk_count"],
        "status_counts": report["status_counts"],
        "role_counts": report["role_counts"],
        "document_counts": report["document_counts"],
        "embedding_eligibility_counts": report["embedding_eligibility_counts"],
        "error_count": len(report["errors"]),
        "warning_count": len(report["warnings"]),
        "output": report["output"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
