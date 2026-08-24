from __future__ import annotations

import re
from typing import Any


def pre_retrieval_academic_response(message: str, allow_draft_review: bool = False) -> dict[str, Any] | None:
    if is_grade_confirmation_request(message) and not allow_draft_review:
        answer = (
            "I can't assign or confirm a percentage grade.\n\n"
            "I can help you compare your work against the rubric and identify areas for improvement, "
            "but the final grade must come from the official grading process."
        )
        return _response(answer)
    if is_complete_assessed_work_request(message) and not allow_draft_review:
        answer = (
            "I can't write a complete assignment for you to copy and submit.\n\n"
            "I can help you work through it yourself. For example, I can:\n"
            "- explain a task or requirement;\n"
            "- explain a difficult concept;\n"
            "- guide you through the steps;\n"
            "- review a draft you've written and suggest improvements."
        )
        return _response(answer)
    return None


def is_complete_assessed_work_request(message: str) -> bool:
    text = _normalize(message)
    if _is_draft_review_request(text) or _is_learning_help_request(text):
        return False

    assessed_context = bool(
        re.search(r"\b(assignment|assessment|submission|task\s*\d+|answer|project|report)\b", text)
    )
    complete_or_proxy = bool(re.search(r"\b(complete|whole|entire|full|everything|copy|paste|submit|submission)\b", text))
    production_verb = bool(re.search(r"\b(write|do|complete|give|make|create|prepare|generate)\b", text))
    ownership_or_submission = bool(
        re.search(r"\b(for me|my assignment|my assessment|my submission|i can submit|can submit|copy\s*(and|&)?\s*paste|copy directly)\b", text)
    )

    if assessed_context and production_verb and (complete_or_proxy or ownership_or_submission):
        return True
    if re.search(r"\b(write|do|complete)\s+my\s+(assignment|assessment|submission|project|report)\b", text):
        return True
    if re.search(r"\b(write|do|complete)\s+task\s*\d+\s+for\s+me\b", text):
        return True
    if re.search(r"\bgive\s+me\s+(the\s+)?complete\s+.+\b(submit|submission|answer)\b", text):
        return True
    return bool(re.search(r"\b(write|give|make|create)\s+.+\b(copy|paste|submit|submission)\b", text))


def is_grade_confirmation_request(message: str) -> bool:
    text = _normalize(message)
    if not re.search(r"\b(grade|mark|marks|score|percentage|percent|%)\b", text):
        return False
    return bool(
        re.search(r"\b(can you|could you|please|give me|assign|confirm|estimate|validate|is this|would this)\b", text)
        or re.search(r"\bcan\s+i\s+get\b", text)
        or re.search(r"\bi\s+can\s+get\b", text)
        or re.search(r"\b\d+\s*%\b", text)
    )


def _is_draft_review_request(text: str) -> bool:
    return bool(
        re.search(r"\bi\s+(wrote|have written|drafted|made|created)\b", text)
        and re.search(r"\b(review|improve|feedback|suggest|check|help me improve)\b", text)
    )


def _is_learning_help_request(text: str) -> bool:
    return bool(re.match(r"^(explain|what is|what are|how do|how should|why|guide me|help me understand)\b", text))


def _normalize(message: str) -> str:
    text = re.sub(r"\bu\b", "you", message.lower())
    return re.sub(r"\s+", " ", text).strip()


def _response(answer: str) -> dict[str, Any]:
    return {
        "model": None,
        "llm_called": False,
        "answer": answer,
        "answer_with_sources": answer,
        "source_references": [],
    }
