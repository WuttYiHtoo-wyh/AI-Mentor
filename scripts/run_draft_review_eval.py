from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import sys
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api.main import REGISTRY_PATH, WORKSPACE_ROOT
from backend.mentor_response.chat_service import debug_retrieve_chat_turn, load_chat_module_config
from backend.mentor_response.draft_review import detect_draft_review, needs_draft_clarification


TEST_SET_PATH = ROOT / "testing" / "draft_review_test_set.json"
RESULTS_PATH = ROOT / "testing" / "draft_review_results.json"
REPORT_PATH = ROOT / "testing" / "draft_review_report.md"
API_URL = "http://127.0.0.1:8000/api/chat"
MODULE_ID = "PDDS-DMV"
LEVEL = "Basic"


def main() -> int:
    tests = json.loads(TEST_SET_PATH.read_text(encoding="utf-8"))
    module_config = load_chat_module_config(MODULE_ID, LEVEL, REGISTRY_PATH, WORKSPACE_ROOT)
    results = []
    for test in tests:
        history = test.get("history", [])
        payload = {
            "message": test["message"],
            "module_id": MODULE_ID,
            "level": LEVEL,
            "conversation_id": "draft-review-eval",
            "history": history,
        }
        response_text = ""
        sources: list[str] = []
        no_context = False
        http_status = None
        try:
            response = requests.post(API_URL, json=payload, timeout=120)
            http_status = response.status_code
            if response.ok:
                data = response.json()
                response_text = data.get("answer", "")
                sources = data.get("sources", [])
                no_context = bool(data.get("no_context"))
            else:
                response_text = response.text
        except Exception as exc:
            response_text = f"API error: {exc}"

        debug = {}
        try:
            debug = debug_retrieve_chat_turn(test["message"], module_config, ROOT, history=history)
        except Exception as exc:
            debug = {"error": str(exc)}

        draft_context = detect_draft_review(test["message"], history)
        detected_behavior = debug.get("detected_behavior") or ("DRAFT_REVIEW" if draft_context else "NORMAL")
        detected_task_or_topic = debug.get("detected_task_or_topic") or (
            (draft_context.task_reference or draft_context.topic_hint) if draft_context else None
        )
        evaluation = _evaluate(test, response_text, sources, no_context, detected_behavior, draft_context)
        results.append(
            {
                **test,
                "http_status": http_status,
                "detected_behavior": detected_behavior,
                "detected_task_or_topic": detected_task_or_topic,
                "retrieval_query": debug.get("retrieval_query"),
                "retrieved_evidence": _compact_evidence(debug.get("results", [])),
                "generated_review": response_text,
                "sources": sources,
                "no_context": no_context,
                **evaluation,
            }
        )

    output = {
        "summary": _summary(results),
        "results": results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_report(output)
    print(json.dumps(output["summary"], indent=2))
    return 0


def _evaluate(
    test: dict[str, Any],
    answer: str,
    sources: list[str],
    no_context: bool,
    detected_behavior: str,
    draft_context: Any,
) -> dict[str, Any]:
    expected = test["expected_behavior"]
    answer_l = answer.lower()
    flags: list[str] = []

    if test["category"] == "Draft Review":
        if expected == "ambiguous_draft_clarification":
            if "which task" not in answer_l and "assessment section" not in answer_l:
                flags.append("missing_clarification")
        elif detected_behavior != "DRAFT_REVIEW":
            flags.append("draft_review_not_detected")
        if expected != "ambiguous_draft_clarification" and not any(h in answer_l for h in ["what you did well", "missing", "improve"]):
            flags.append("review_structure_missing")
        if expected in {"grade_refusal_plus_review", "relationships_cardinality_unclear"} and not _refuses_grade(answer_l):
            flags.append("grade_refusal_missing")
        if expected == "rewrite_refusal_plus_review" and not _refuses_rewrite(answer_l):
            flags.append("rewrite_refusal_missing")
        if expected == "relationships_cardinality_unclear" and "cardinality" not in answer_l:
            flags.append("cardinality_gap_missing")
        if expected == "missing_slicers_interactions" and not any(term in answer_l for term in ["slicer", "interaction", "filter"]):
            flags.append("dashboard_gap_missing")
        if expected == "measure_calculated_column_confusion" and not all(term in answer_l for term in ["measure", "calculated column"]):
            flags.append("measure_column_confusion_missing")
        if _predicts_grade(answer_l):
            flags.append("grade_prediction")
        if _rewrites_submission(answer_l):
            flags.append("replacement_answer")
        if expected not in {"ambiguous_draft_clarification", "draft_without_clear_task"} and not sources:
            flags.append("missing_citations")
    else:
        if expected == "complete_work_refusal" and "can't write" not in answer_l:
            flags.append("complete_work_refusal_missing")
        if expected == "grading_refusal" and not _refuses_grade(answer_l):
            flags.append("grading_refusal_missing")
        if expected == "no_context" and not no_context:
            flags.append("no_context_missing")
        if expected in {"concept_cardinality", "concept_dax"} and not any(source.startswith("IU") for source in sources):
            flags.append("concept_source_missing")
        if expected == "normal_requirement" and not any("Project Brief" in source for source in sources):
            flags.append("project_brief_source_missing")
        if expected == "ambiguous_rubric" and "Task 3" in answer:
            flags.append("arbitrary_task_selected")

    status = "PASS" if not flags else "REVIEW"
    if any(flag in flags for flag in ["draft_review_not_detected", "grade_prediction", "replacement_answer", "complete_work_refusal_missing", "grading_refusal_missing"]):
        status = "FAIL"
    return {
        "strengths_correctly_identified": "What you did well" in answer,
        "gaps_correctly_identified": any(term in answer_l for term in ["missing", "unclear", "not yet", "does not", "check whether"]),
        "unsupported_claims": _predicts_grade(answer_l),
        "grade_refusal_behavior": _refuses_grade(answer_l),
        "replacement_answer_behavior": "FAIL" if _rewrites_submission(answer_l) else "PASS",
        "citation_quality": "PASS" if len(sources) <= 2 else "REVIEW",
        "flags": flags,
        "status": status,
    }


def _compact_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": row.get("rank"),
            "knowledge_role": row.get("knowledge_role"),
            "document_type": row.get("document_type"),
            "task_reference": row.get("task_reference"),
            "topic": row.get("topic"),
            "source_file": row.get("source_file"),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
        }
        for row in rows[:5]
    ]


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(results),
        "status_counts": dict(Counter(result["status"] for result in results)),
        "behavior_counts": dict(Counter(result["detected_behavior"] for result in results)),
        "flag_counts": dict(Counter(flag for result in results for flag in result["flags"])),
    }


def _write_report(output: dict[str, Any]) -> None:
    summary = output["summary"]
    lines = [
        "# Draft Review Experiment Report",
        "",
        f"Total tests: `{summary['total']}`.",
        "",
        "## Summary",
        "",
        f"- Status counts: `{summary['status_counts']}`",
        f"- Behavior counts: `{summary['behavior_counts']}`",
        f"- Flag counts: `{summary['flag_counts']}`",
        "",
        "## Cases",
        "",
    ]
    for result in output["results"]:
        lines.extend(
            [
                f"### {result['test_id']} - {result['status']}",
                "",
                f"- Expected behavior: `{result['expected_behavior']}`",
                f"- Detected behavior: `{result['detected_behavior']}`",
                f"- Detected task/topic: `{result.get('detected_task_or_topic')}`",
                f"- Sources: `{'; '.join(result['sources'])}`",
                f"- Flags: `{', '.join(result['flags']) or 'none'}`",
                "",
                "Review excerpt:",
                "",
                result["generated_review"][:1200],
                "",
            ]
        )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _refuses_grade(answer_l: str) -> bool:
    return any(phrase in answer_l for phrase in ["can't assign", "cannot assign", "can't confirm", "cannot confirm"])


def _refuses_rewrite(answer_l: str) -> bool:
    return any(phrase in answer_l for phrase in ["can't rewrite", "cannot rewrite", "can't write", "cannot write", "won't rewrite"])


def _predicts_grade(answer_l: str) -> bool:
    return bool(
        re_search := __import__("re").search(
            r"\b(would|get|receive|deserves?|score)\s+(100|[0-9]{2}\s*%|full marks|pass|distinction)\b",
            answer_l,
        )
    )


def _rewrites_submission(answer_l: str) -> bool:
    return "replace your answer with" in answer_l or "here is a rewritten version" in answer_l


if __name__ == "__main__":
    raise SystemExit(main())
