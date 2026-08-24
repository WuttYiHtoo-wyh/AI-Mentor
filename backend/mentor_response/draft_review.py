from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .academic_integrity import is_grade_confirmation_request
from .generator import build_source_references


@dataclass(frozen=True)
class DraftReviewContext:
    review_request: str
    draft: str
    task_reference: str | None
    topic_hint: str
    uses_previous_context: bool = False


DRAFT_REVIEW_PROMPT = """You are an AI Mentor reviewing learner-authored draft work.

Use only the retrieved approved module evidence and the learner's draft.
Do not assign, estimate, confirm, or imply a grade, mark, percentage, pass/fail result, or full-mark outcome.
Do not rewrite the learner's work into a complete submission-ready answer.

Review behavior:
- Compare the learner draft against the retrieved official requirements, rubric, and relevant teaching evidence.
- Distinguish clearly supported strengths from missing or unclear points.
- If a requirement cannot be verified from the draft text, say it is unclear rather than assuming it is correct.
- Preserve the learner's task/topic context when it is clear.
- If the learner asks for a grade or full marks, refuse that part first, then continue the review.
- If the learner asks you to rewrite the whole answer, refuse that part, then give review guidance.

Preferred structure for substantial drafts:
What you did well
- ...

What is missing or unclear
- ...

What to improve next
- ...

Check this concept
- ... only if teaching evidence is relevant.

Keep the review concise and practical. Do not include chunk IDs or internal scores. Source references are added separately by the application."""


def detect_draft_review(message: str, history: list[dict[str, str]] | None = None) -> DraftReviewContext | None:
    review_request = message.strip()
    if not _has_review_intent(review_request):
        return None

    draft = _extract_current_draft(review_request)
    uses_previous = False
    if not _is_meaningful_draft(draft):
        previous = _previous_learner_draft(history or [])
        if _is_meaningful_draft(previous):
            draft = previous
            uses_previous = True

    if not _is_meaningful_draft(draft):
        return None

    task_reference = _extract_task_reference(review_request + "\n" + draft)
    topic_hint = _topic_hint(review_request, draft)
    return DraftReviewContext(
        review_request=review_request,
        draft=draft,
        task_reference=task_reference,
        topic_hint=topic_hint,
        uses_previous_context=uses_previous,
    )


def needs_draft_clarification(context: DraftReviewContext) -> bool:
    if context.task_reference:
        return False
    return len(_tokens(context.draft)) < 16


def build_draft_review_retrieval_query(context: DraftReviewContext) -> str:
    parts = ["draft review assessment requirements rubric"]
    if context.task_reference:
        parts.append(context.task_reference)
    if context.topic_hint:
        parts.append(context.topic_hint)
    return " ".join(parts)


def clarification_response(context: DraftReviewContext) -> dict[str, Any]:
    answer = "Which task or assessment section is this draft for? I need that context before I can review it against the right requirements."
    return {
        "answer": answer,
        "source_references": [],
        "detected_behavior": "DRAFT_REVIEW_CLARIFICATION",
        "detected_task_or_topic": context.task_reference or context.topic_hint,
    }


def generate_draft_review_response(
    context: DraftReviewContext,
    retrieval: dict[str, Any],
    model: str,
    max_output_tokens: int = 700,
) -> dict[str, Any]:
    evidence = retrieval.get("results", [])
    source_references = build_source_references(evidence)
    if retrieval.get("no_context") or not retrieval.get("evidence_sufficient"):
        answer = (
            "I can see that you want feedback on your draft, but I could not find enough approved module evidence "
            "to review it against the right requirements. Please tell me which task or assessment section this draft belongs to."
        )
        return {
            "model": None,
            "llm_called": False,
            "answer": answer,
            "source_references": [],
            "detected_behavior": "DRAFT_REVIEW",
            "detected_task_or_topic": context.task_reference or context.topic_hint,
        }

    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env or the environment.")

    client = OpenAI()
    response = client.responses.create(
        model=model,
        instructions=DRAFT_REVIEW_PROMPT,
        input=_build_review_input(context, evidence),
        max_output_tokens=max_output_tokens,
        store=False,
    )
    answer = _apply_review_boundaries(context, _clean_review_answer(response.output_text.strip()))
    return {
        "model": model,
        "llm_called": True,
        "answer": answer,
        "source_references": source_references,
        "detected_behavior": "DRAFT_REVIEW",
        "detected_task_or_topic": context.task_reference or context.topic_hint,
    }


def _build_review_input(context: DraftReviewContext, evidence: list[dict[str, Any]]) -> str:
    parts = [
        f"Learner review request:\n{context.review_request}",
        "",
        f"Learner-authored draft to review:\n{context.draft}",
        "",
        "Detected context:",
        f"- Task/reference: {context.task_reference or 'Not explicit'}",
        f"- Topic hint: {context.topic_hint or 'Not explicit'}",
        f"- Learner asks for grade/marks confirmation: {'Yes' if is_grade_confirmation_request(context.review_request) else 'No'}",
        f"- Learner asks for full rewrite/replacement: {'Yes' if _asks_for_rewrite(context.review_request) else 'No'}",
        "",
        "Retrieved approved module evidence:",
    ]
    for index, row in enumerate(evidence, start=1):
        parts.append(
            "\n".join(
                [
                    f"[E{index}]",
                    f"Knowledge role: {row.get('knowledge_role', '')}",
                    f"Document type: {row.get('document_type', '')}",
                    f"Topic: {row.get('topic', '')}",
                    f"Task/reference: {row.get('task_reference') or 'N/A'}",
                    f"Pages: {row.get('page_start', '')}-{row.get('page_end', '')}",
                    "Content:",
                    str(row.get("content") or row.get("content_preview") or ""),
                ]
            )
        )
    return "\n\n".join(parts)


def _has_review_intent(text: str) -> bool:
    text_l = text.lower()
    return bool(
        re.search(
            r"\b(review|check|feedback|correct|improve|missing|align(?:ed|ment)?|against the rubric|is this right|is this okay|okay)\b",
            text_l,
        )
    )


def _asks_for_rewrite(text: str) -> bool:
    return bool(re.search(r"\b(rewrite|write the whole|write it all|complete rewrite|replace)\b", text.lower()))


def _apply_review_boundaries(context: DraftReviewContext, answer: str) -> str:
    preamble: list[str] = []
    if is_grade_confirmation_request(context.review_request) and not re.search(r"\b(can't|cannot)\s+(assign|confirm|estimate|guarantee)", answer, re.I):
        preamble.append("I can't assign, confirm, estimate, or guarantee a mark or percentage, but I can review your draft against the official requirements.")
    if _asks_for_rewrite(context.review_request) and not re.search(r"\b(can't|cannot|won't)\s+(rewrite|write|replace)", answer, re.I):
        preamble.append("I can't rewrite the whole answer into a submission-ready replacement, but I can point out what to improve.")
    if not preamble:
        return answer
    return "\n\n".join(preamble + [answer])


def _extract_current_draft(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    non_empty = [line for line in lines if line]
    if len(non_empty) >= 2:
        return "\n".join(non_empty[1:]).strip()
    if re.search(r"\bi\s+(created|added|connected|used|wrote|explained|removed|cleaned|handled|built|made)\b", text, re.I):
        return text.strip()
    return ""


def _previous_learner_draft(history: list[dict[str, str]]) -> str:
    for turn in reversed(history[-4:]):
        if turn.get("role") != "learner":
            continue
        content = str(turn.get("content", "")).strip()
        if _is_meaningful_draft(content):
            return content
    return ""


def _is_meaningful_draft(text: str) -> bool:
    tokens = _tokens(text)
    if len(tokens) < 7:
        return False
    return bool(
        re.search(r"\bi\s+(created|added|connected|used|wrote|explained|removed|cleaned|handled|built|made)\b", text, re.I)
        or len(tokens) >= 28
    )


def _extract_task_reference(text: str) -> str | None:
    match = re.search(r"\btask\s+(\d+)\b", text.lower())
    return f"Task {match.group(1)}" if match else None


def _topic_hint(request: str, draft: str) -> str:
    words = []
    for token in _tokens(request + " " + draft):
        if token in _STOPWORDS or token in words:
            continue
        words.append(token)
        if len(words) >= 18:
            break
    return " ".join(words)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _clean_review_answer(answer: str) -> str:
    cleaned = answer.replace("\ufffd", "-").strip()
    return re.sub(r"\s*If you have any (more|further) questions, feel free to ask!?$", "", cleaned, flags=re.I).strip()


_STOPWORDS = {
    "about",
    "against",
    "answer",
    "can",
    "could",
    "draft",
    "for",
    "from",
    "have",
    "help",
    "improve",
    "into",
    "correct",
    "get",
    "mark",
    "marks",
    "missing",
    "is",
    "it",
    "review",
    "rubric",
    "that",
    "the",
    "this",
    "what",
    "with",
    "wrote",
    "you",
}
