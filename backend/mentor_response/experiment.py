from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .evaluation import evaluate_response
from .generator import generate_mentor_response
from .retrieval import retrieve_experiment3_evidence


def run_mentor_response_experiment(config_path: Path, workspace_root: Path) -> dict[str, Any]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    test_set_path = workspace_root / raw["test_set_path"]
    tests = json.loads(test_set_path.read_text(encoding="utf-8"))
    retrieval_config_path = workspace_root / raw["retrieval_config_path"]
    model = raw["response_model"]
    max_output_tokens = int(raw.get("max_output_tokens", 500))

    results: list[dict[str, Any]] = []
    conversation_history: list[dict[str, str]] = []
    for test in tests:
        history = conversation_history if test.get("use_conversation_history") else []
        retrieval_question = _retrieval_question(test["question"], history)
        retrieval = retrieve_experiment3_evidence(
            learner_question=retrieval_question,
            retrieval_config_path=retrieval_config_path,
            workspace_root=workspace_root,
        )
        retrieval["question"] = test["question"]
        retrieval["retrieval_query"] = retrieval_question
        response = generate_mentor_response(
            learner_question=test["question"],
            retrieval=retrieval,
            model=model,
            conversation_history=history,
            max_output_tokens=max_output_tokens,
        )
        result = {
            **test,
            "retrieval": _compact_retrieval(retrieval),
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
        "retrieval_source": "Experiment 3 source-balanced retrieval pipeline",
        "retrieval_config_path": raw["retrieval_config_path"],
        "prompt_structure": {
            "system_prompt": "Module-independent AI Mentor grounding, authority, NO_CONTEXT, and academic-integrity rules.",
            "user_input": "Recent conversation context, latest learner question, and retrieved approved module evidence.",
            "citations": "Application-appended learner-facing source references from metadata.",
        },
        "test_count": len(results),
        "summary": summary,
        "results": results,
    }

    results_json_path = workspace_root / raw["results_json_path"]
    results_csv_path = workspace_root / raw["results_csv_path"]
    report_path = workspace_root / raw["report_path"]
    results_json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(results, results_csv_path)
    _write_report(output, report_path)
    return output


def _compact_retrieval(retrieval: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": retrieval["question"],
        "retrieval_query": retrieval.get("retrieval_query", retrieval["question"]),
        "intent": retrieval["intent"],
        "preferred_role": retrieval["preferred_role"],
        "threshold": retrieval["threshold"],
        "no_context": retrieval["no_context"],
        "evidence_sufficient": retrieval["evidence_sufficient"],
        "diagnostics": retrieval["diagnostics"],
        "evidence_used": [
            {
                "rank": row["rank"],
                "chunk_id": row["chunk_id"],
                "knowledge_role": row.get("knowledge_role", ""),
                "document_id": row.get("document_id", ""),
                "document_type": row.get("document_type", ""),
                "task_reference": row.get("task_reference", ""),
                "instructional_unit": row.get("instructional_unit", ""),
                "topic": row.get("topic", ""),
                "source_file": row.get("source_file", ""),
                "page_start": row.get("page_start", ""),
                "page_end": row.get("page_end", ""),
                "distance": row.get("distance", ""),
                "final_score": row.get("final_score", ""),
                "content_preview": row.get("content_preview", ""),
            }
            for row in retrieval["results"]
        ],
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    fields = [
        "groundedness",
        "correctness",
        "requirement_accuracy",
        "helpfulness",
        "academic_integrity_behavior",
        "source_citation_quality",
    ]
    summary: dict[str, Any] = {"tests": len(results)}
    for field in fields:
        counts: dict[str, int] = {}
        for result in results:
            value = result["evaluation"][field]
            counts[value] = counts.get(value, 0) + 1
        summary[field] = counts
    summary["unsupported_claim_cases"] = sum(1 for result in results if result["evaluation"]["unsupported_claim_presence"])
    summary["no_context_cases"] = sum(1 for result in results if result["retrieval"]["no_context"])
    summary["llm_calls"] = sum(1 for result in results if result["response"]["llm_called"])
    return summary


def _retrieval_question(question: str, conversation_history: list[dict[str, str]]) -> str:
    if not conversation_history or not _should_use_history_for_retrieval(question):
        return question
    recent = conversation_history[-4:]
    context = " ".join(f"{turn.get('role', '')}: {turn.get('content', '')}" for turn in recent)
    return f"Recent conversation: {context}\nFollow-up question: {question}"


def _should_use_history_for_retrieval(question: str) -> bool:
    question_l = question.strip().lower()
    word_markers = {"that", "this", "it", "those", "them"}
    phrase_markers = [
        "more simply",
        "explain more",
        "what about",
        "how about",
        "can you explain",
        "tell me more",
    ]
    words = set(question_l.replace("?", " ").replace(".", " ").split())
    if len(question_l.split()) <= 6 and (words & word_markers or any(phrase in question_l for phrase in phrase_markers)):
        return True
    return any(phrase in question_l for phrase in ["explain that", "explain it", "what does that mean", "more simply"])


def _write_csv(results: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "test_id",
        "category",
        "question",
        "intent",
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
                "intent": result["retrieval"]["intent"],
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
    weak = [
        result
        for result in output["results"]
        if result["evaluation"]["correctness"] != "PASS"
        or result["evaluation"]["groundedness"] != "PASS"
        or result["evaluation"]["academic_integrity_behavior"] != "PASS"
    ]
    strong = [
        result
        for result in output["results"]
        if result["evaluation"]["correctness"] == "PASS"
        and result["evaluation"]["groundedness"] == "PASS"
        and result["evaluation"]["academic_integrity_behavior"] == "PASS"
    ]
    lines = [
        "# AI Mentor Response-Layer Experiment Report",
        "",
        f"Model used: `{output['response_model']}`.",
        f"Response tests: `{output['test_count']}`.",
        "",
        "## Prompt Structure",
        "",
        "- System instructions define the AI Mentor as a learning assistant, not an Auto Grader.",
        "- User input contains recent conversation context, latest learner question, and fresh Experiment 3 evidence.",
        "- The model is instructed to answer only from retrieved approved module evidence.",
        "- Source references are appended by the application from metadata, not invented by the model.",
        "",
        "## Summary",
        "",
        f"- LLM calls: `{summary['llm_calls']}`.",
        f"- NO_CONTEXT cases: `{summary['no_context_cases']}`.",
        f"- Unsupported-claim cases: `{summary['unsupported_claim_cases']}`.",
        f"- Groundedness: `{summary['groundedness']}`.",
        f"- Correctness: `{summary['correctness']}`.",
        f"- Requirement accuracy: `{summary['requirement_accuracy']}`.",
        f"- Academic-integrity behavior: `{summary['academic_integrity_behavior']}`.",
        f"- Source citation quality: `{summary['source_citation_quality']}`.",
        "",
        "## Strong Cases",
        "",
    ]
    for result in strong[:10]:
        lines.append(f"- `{result['test_id']}` {result['question']}")
    lines.extend(["", "## Weak Or Review Cases", ""])
    if not weak:
        lines.append("- None.")
    for result in weak:
        lines.append(
            f"- `{result['test_id']}` {result['question']} | "
            f"groundedness={result['evaluation']['groundedness']}, "
            f"correctness={result['evaluation']['correctness']}, "
            f"academic_integrity={result['evaluation']['academic_integrity_behavior']}"
        )
    lines.extend(
        [
            "",
            "## NO_CONTEXT Behavior",
            "",
            "When retrieval returned no acceptable evidence, the experiment did not call the LLM and returned the controlled Mentor response.",
            "",
            "## Academic Integrity",
            "",
            "The behavior tests include complete-work and grading requests. The prompt requires refusal of those parts while still offering learning guidance.",
            "",
            "## Source Citations",
            "",
            "Responses with sufficient evidence include concise metadata-derived references such as Project Brief pages, IU pages, or Learner Guide pages. Chunk IDs are not exposed.",
            "",
            "## UI Readiness",
            "",
            "The response layer is ready for a simple learner chat UI experiment, with two caveats: review cases should be manually checked, and the known submit/deliverables retrieval gap remains documented rather than tuned around.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
