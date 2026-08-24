from __future__ import annotations

import re
from typing import Any


REQUIREMENT_TERMS = {
    "required",
    "requirement",
    "requirements",
    "deliverable",
    "deliverables",
    "submit",
    "submission",
    "rubric",
    "marks",
    "mark",
    "proficient",
    "assessment",
    "must",
    "included",
    "include",
}

COMPLETE_WORK_TERMS = {
    "complete",
    "write my",
    "do my",
    "answer for me",
    "submission-ready",
}


def build_response_retrieval_query(question: str) -> str:
    if is_assessment_context(question):
        return f"assessment requirement: {question}"
    return question


def is_assessment_context(question: str) -> bool:
    question_l = question.lower()
    if extract_task_reference(question):
        return True
    if _has_requirement_intent_phrase(question_l):
        return True
    if any(term in question_l for term in REQUIREMENT_TERMS):
        return True
    return any(term in question_l for term in COMPLETE_WORK_TERMS)


def order_evidence_for_response(question: str, retrieval: dict[str, Any]) -> dict[str, Any]:
    rows = list(retrieval.get("results", []))
    if not rows:
        return retrieval

    task_reference = extract_task_reference(question)
    assessment_context = is_assessment_context(question)
    if task_reference:
        matching = [row for row in rows if _same_task(row.get("task_reference"), task_reference)]
        if matching:
            rows = matching + [
                row
                for row in rows
                if row not in matching and not _has_other_task(row.get("task_reference"), task_reference)
            ]

    if assessment_context and any(row.get("knowledge_role") == "OFFICIAL_REQUIREMENT" for row in rows):
        rows = sorted(rows, key=lambda row: _authority_sort_key(question, row, task_reference))
    elif not assessment_context:
        rows = sorted(rows, key=lambda row: _learning_sort_key(question, row))

    updated = dict(retrieval)
    updated["results"] = _rerank_display(rows)
    updated["evidence_policy"] = {
        "assessment_context": assessment_context,
        "task_reference": task_reference,
        "official_requirement_available": any(row.get("knowledge_role") == "OFFICIAL_REQUIREMENT" for row in rows),
        "complete_work_request": is_complete_work_request(question),
    }
    return updated


def extract_task_reference(text: str) -> str | None:
    match = re.search(r"\btask\s+(\d+)\b", text.lower())
    return f"Task {match.group(1)}" if match else None


def is_complete_work_request(question: str) -> bool:
    question_l = question.lower()
    return any(term in question_l for term in COMPLETE_WORK_TERMS) and any(
        term in question_l for term in ["write", "complete", "answer", "do my"]
    )


def _has_requirement_intent_phrase(question_l: str) -> bool:
    patterns = [
        r"\bdo\s+i\s+need\b",
        r"\bdo\s+we\s+need\b",
        r"\bwhat\s+do\s+i\s+need\b",
        r"\bwhat\s+do\s+we\s+need\b",
        r"\bhow\s+many\b",
        r"\bneed\s+to\s+(do|submit|include|create|use|show|provide|write|add|make)\b",
        r"\b(?:what|which)\b.+\bshould\s+i\s+(create|include|submit|use|show|provide|add|make)\b",
        r"\b(?:what|which)\b.+\bshould\s+we\s+(create|include|submit|use|show|provide|add|make)\b",
    ]
    return any(re.search(pattern, question_l) for pattern in patterns)


def _authority_sort_key(question: str, row: dict[str, Any], task_reference: str | None) -> tuple[int, int, int, float]:
    role_rank = 0 if row.get("knowledge_role") == "OFFICIAL_REQUIREMENT" else 1
    task_rank = 0 if task_reference and _same_task(row.get("task_reference"), task_reference) else 1
    rubric_rank = _rubric_rank(question, row)
    return (role_rank, task_rank, rubric_rank, -float(row.get("final_score", 0.0)))


def _learning_sort_key(question: str, row: dict[str, Any]) -> tuple[int, int, float]:
    query_tokens = _tokens(question)
    metadata_tokens = _tokens(" ".join([str(row.get("topic", "")), str(row.get("title", "")), str(row.get("instructional_unit", ""))]))
    overlap = len(query_tokens & metadata_tokens)
    role_rank = 0 if row.get("knowledge_role") == "LEARNING_MATERIAL" else 1
    return (-overlap, role_rank, -float(row.get("final_score", 0.0)))


def _rubric_rank(question: str, row: dict[str, Any]) -> int:
    wants_rubric = any(term in question.lower() for term in ["rubric", "proficient", "foundation", "failed", "marks"])
    is_rubric = "rubric" in " ".join([str(row.get("topic", "")), str(row.get("title", ""))]).lower()
    if wants_rubric:
        return 0 if is_rubric else 1
    return 1 if is_rubric else 0


def _same_task(value: Any, task_reference: str) -> bool:
    return str(value or "").strip().lower() == task_reference.lower()


def _has_other_task(value: Any, task_reference: str) -> bool:
    value_s = str(value or "").strip().lower()
    return bool(value_s.startswith("task ")) and value_s != task_reference.lower()


def _rerank_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for index, row in enumerate(rows, start=1):
        updated = dict(row)
        updated["rank"] = index
        output.append(updated)
    return output


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2}
