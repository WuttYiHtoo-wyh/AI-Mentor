from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .evaluation import evaluate_response
from .evidence_policy import build_response_retrieval_query, order_evidence_for_response
from .experiment import _compact_retrieval, _retrieval_question, _summary
from .generator import generate_mentor_response
from .retrieval import retrieve_experiment3_evidence


def run_mentor_response_experiment2(config_path: Path, workspace_root: Path) -> dict[str, Any]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    tests = json.loads((workspace_root / raw["test_set_path"]).read_text(encoding="utf-8"))
    baseline = json.loads((workspace_root / raw["baseline_response_results_path"]).read_text(encoding="utf-8"))
    retrieval_config_path = workspace_root / raw["retrieval_config_path"]
    model = raw["response_model"]
    max_output_tokens = int(raw.get("max_output_tokens", 500))

    results: list[dict[str, Any]] = []
    conversation_history: list[dict[str, str]] = []
    for test in tests:
        history = conversation_history if test.get("use_conversation_history") else []
        contextual_question = _retrieval_question(test["question"], history)
        retrieval_query = build_response_retrieval_query(contextual_question)
        retrieval = retrieve_experiment3_evidence(
            learner_question=retrieval_query,
            retrieval_config_path=retrieval_config_path,
            workspace_root=workspace_root,
        )
        retrieval["question"] = test["question"]
        retrieval["retrieval_query"] = retrieval_query
        retrieval = order_evidence_for_response(test["question"], retrieval)
        response = generate_mentor_response(
            learner_question=test["question"],
            retrieval=retrieval,
            model=model,
            conversation_history=history,
            max_output_tokens=max_output_tokens,
        )
        result = {
            **test,
            "retrieval": _compact_retrieval_with_policy(retrieval),
            "response": response,
        }
        result["evaluation"] = evaluate_response(test, result)
        results.append(result)
        if test.get("include_in_history", True):
            conversation_history.append({"role": "learner", "content": test["question"]})
            conversation_history.append({"role": "mentor", "content": response["answer"]})

    summary = _summary(results)
    output = {
        "response_model": model,
        "retrieval_source": "Experiment 3 source-balanced retrieval pipeline with response-layer evidence policy",
        "retrieval_config_path": raw["retrieval_config_path"],
        "baseline_response_results_path": raw["baseline_response_results_path"],
        "changes_made": [
            "Generic requirement-context retrieval query construction at response layer.",
            "Generic evidence ordering that prioritizes OFFICIAL_REQUIREMENT for assessment-context questions when available.",
            "Generic task-reference alignment that prefers matching task_reference evidence and suppresses other task evidence when matching task evidence exists.",
        ],
        "test_count": len(results),
        "summary": summary,
        "baseline_summary": baseline["summary"],
        "targeted_results": {
            "MR003": _target_result(results, "MR003"),
            "MR019": _target_result(results, "MR019"),
        },
        "regressions": _regressions(baseline["results"], results),
        "results": results,
    }
    results_json_path = workspace_root / raw["results_json_path"]
    results_csv_path = workspace_root / raw["results_csv_path"]
    report_path = workspace_root / raw["report_path"]
    results_json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(results, results_csv_path)
    _write_report(output, report_path)
    return output


def _compact_retrieval_with_policy(retrieval: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_retrieval(retrieval)
    compact["evidence_policy"] = retrieval.get("evidence_policy", {})
    return compact


def _target_result(results: list[dict[str, Any]], test_id: str) -> dict[str, Any]:
    result = next(row for row in results if row["test_id"] == test_id)
    return {
        "question": result["question"],
        "evaluation": result["evaluation"],
        "answer": result["response"]["answer_with_sources"],
        "evidence_used": [
            {
                "rank": row["rank"],
                "knowledge_role": row["knowledge_role"],
                "task_reference": row["task_reference"],
                "topic": row["topic"],
                "page_start": row["page_start"],
                "page_end": row["page_end"],
            }
            for row in result["retrieval"]["evidence_used"]
        ],
        "evidence_policy": result["retrieval"].get("evidence_policy", {}),
    }


def _regressions(baseline_results: list[dict[str, Any]], current_results: list[dict[str, Any]]) -> list[dict[str, str]]:
    baseline_by_id = {row["test_id"]: row for row in baseline_results}
    regressions = []
    for current in current_results:
        baseline = baseline_by_id[current["test_id"]]
        for field in ["groundedness", "correctness", "academic_integrity_behavior", "source_citation_quality"]:
            if baseline["evaluation"][field] == "PASS" and current["evaluation"][field] != "PASS":
                regressions.append(
                    {
                        "test_id": current["test_id"],
                        "field": field,
                        "baseline": baseline["evaluation"][field],
                        "current": current["evaluation"][field],
                    }
                )
    return regressions


def _write_csv(results: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "test_id",
        "category",
        "question",
        "retrieval_query",
        "intent",
        "evidence_policy",
        "evidence_sufficient",
        "no_context",
        "evidence_count",
        "response",
        "sources",
        "groundedness",
        "correctness",
        "requirement_accuracy",
        "helpfulness",
        "unsupported_claim_presence",
        "academic_integrity_behavior",
        "source_citation_quality",
    ]
    rows = []
    for result in results:
        rows.append(
            {
                "test_id": result["test_id"],
                "category": result["category"],
                "question": result["question"],
                "retrieval_query": result["retrieval"]["retrieval_query"],
                "intent": result["retrieval"]["intent"],
                "evidence_policy": json.dumps(result["retrieval"].get("evidence_policy", {}), ensure_ascii=False),
                "evidence_sufficient": result["evaluation"]["evidence_sufficient"],
                "no_context": result["retrieval"]["no_context"],
                "evidence_count": len(result["retrieval"]["evidence_used"]),
                "response": result["response"]["answer_with_sources"],
                "sources": "; ".join(result["response"]["source_references"]),
                "groundedness": result["evaluation"]["groundedness"],
                "correctness": result["evaluation"]["correctness"],
                "requirement_accuracy": result["evaluation"]["requirement_accuracy"],
                "helpfulness": result["evaluation"]["helpfulness"],
                "unsupported_claim_presence": result["evaluation"]["unsupported_claim_presence"],
                "academic_integrity_behavior": result["evaluation"]["academic_integrity_behavior"],
                "source_citation_quality": result["evaluation"]["source_citation_quality"],
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(output: dict[str, Any], path: Path) -> None:
    summary = output["summary"]
    regressions = output["regressions"]
    lines = [
        "# AI Mentor Response Experiment 2 Report",
        "",
        "## Changes Made",
        "",
    ]
    for change in output["changes_made"]:
        lines.append(f"- {change}")
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Model used: `{output['response_model']}`.",
            f"- Response tests: `{output['test_count']}`.",
            f"- Groundedness: `{summary['groundedness']}`.",
            f"- Correctness: `{summary['correctness']}`.",
            f"- Requirement accuracy: `{summary['requirement_accuracy']}`.",
            f"- Unsupported-claim cases: `{summary['unsupported_claim_cases']}`.",
            f"- Academic-integrity behavior: `{summary['academic_integrity_behavior']}`.",
            f"- Source citation quality: `{summary['source_citation_quality']}`.",
            f"- NO_CONTEXT cases: `{summary['no_context_cases']}`.",
            "",
            "## MR003 Result",
            "",
            _target_report_line(output["targeted_results"]["MR003"]),
            "",
            "## MR019 Result",
            "",
            _target_report_line(output["targeted_results"]["MR019"]),
            "",
            "## Regressions",
            "",
        ]
    )
    if regressions:
        for regression in regressions:
            lines.append(
                f"- `{regression['test_id']}` {regression['field']}: {regression['baseline']} -> {regression['current']}"
            )
    else:
        lines.append("- None detected against the previous response experiment results.")
    ready = not regressions and summary["unsupported_claim_cases"] == 0 and summary["academic_integrity_behavior"].get("FAIL", 0) == 0
    lines.extend(
        [
            "",
            "## Freeze Recommendation",
            "",
            (
                "The response layer is ready to freeze for the first learner chat UI."
                if ready
                else "Do not freeze yet; review the remaining failures or regressions first."
            ),
            "",
            "No frontend, Admin UI, deployment, grading integration, new retrieval experiment, retrieval config change, or commit was performed.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _target_report_line(result: dict[str, Any]) -> str:
    evaluation = result["evaluation"]
    first_evidence = result["evidence_used"][0] if result["evidence_used"] else {}
    return (
        f"- correctness={evaluation['correctness']}, requirement_accuracy={evaluation['requirement_accuracy']}, "
        f"academic_integrity={evaluation['academic_integrity_behavior']}, first_evidence="
        f"{first_evidence.get('knowledge_role', '')} / {first_evidence.get('task_reference', '')} / {first_evidence.get('topic', '')}"
    )
