from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .academic_integrity import is_complete_assessed_work_request, is_grade_confirmation_request
from .prompts import MENTOR_SYSTEM_PROMPT, NO_CONTEXT_RESPONSE


def generate_mentor_response(
    learner_question: str,
    retrieval: dict[str, Any],
    model: str,
    conversation_history: list[dict[str, str]] | None = None,
    max_output_tokens: int = 500,
) -> dict[str, Any]:
    if retrieval.get("no_context") or not retrieval.get("evidence_sufficient"):
        return {
            "model": None,
            "llm_called": False,
            "answer": NO_CONTEXT_RESPONSE,
            "answer_with_sources": NO_CONTEXT_RESPONSE,
            "source_references": [],
        }

    deterministic = _deterministic_academic_response(learner_question, retrieval)
    if deterministic:
        return deterministic

    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env or the environment.")

    client = OpenAI()
    evidence = retrieval.get("results", [])
    input_text = _build_user_input(learner_question, evidence, conversation_history or [])
    response = client.responses.create(
        model=model,
        instructions=MENTOR_SYSTEM_PROMPT,
        input=input_text,
        max_output_tokens=max_output_tokens,
        store=False,
    )
    answer = _clean_answer(response.output_text.strip())
    source_references = build_source_references(evidence)
    return {
        "model": model,
        "llm_called": True,
        "answer": answer,
        "answer_with_sources": _append_sources(answer, source_references),
        "source_references": source_references,
    }


def build_source_references(evidence: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    references: list[str] = []
    for row in evidence:
        label = _source_label(row)
        pages = _page_label(row.get("page_start"), row.get("page_end"))
        reference = f"{label}, {pages}" if pages else label
        if reference not in seen:
            seen.add(reference)
            references.append(reference)
    return references


def _deterministic_academic_response(learner_question: str, retrieval: dict[str, Any]) -> dict[str, Any] | None:
    question_l = learner_question.lower()
    evidence = retrieval.get("results", [])
    references = build_source_references(evidence)
    if is_grade_confirmation_request(learner_question):
        answer = (
            "I can't assign or confirm a percentage grade.\n\n"
            "I can help you compare your work against the rubric and identify areas for improvement, "
            "but the final grade must come from the official grading process."
        )
        return {
            "model": None,
            "llm_called": False,
            "answer": answer,
            "answer_with_sources": _append_sources(answer, references),
            "source_references": references,
        }
    if is_complete_assessed_work_request(learner_question):
        answer = (
            "I can't write a complete assignment for you to copy and submit.\n\n"
            "I can help you work through it yourself. For example, I can:\n"
            "- explain a task or requirement;\n"
            "- explain a difficult concept;\n"
            "- guide you through the steps;\n"
            "- review a draft you've written and suggest improvements."
        )
        return {
            "model": None,
            "llm_called": False,
            "answer": answer,
            "answer_with_sources": _append_sources(answer, references),
            "source_references": references,
        }
    official_checklist = _official_requirement_checklist_response(learner_question, retrieval, evidence, references)
    if official_checklist:
        return official_checklist
    official_rubric = _official_requirement_rubric_response(learner_question, retrieval, evidence, references)
    if official_rubric:
        return official_rubric
    absent_requirement = _official_absent_need_response(learner_question, evidence, references)
    if absent_requirement:
        return absent_requirement
    if any(term in question_l for term in ["percentage grade", "grade me", "give me a grade", "what grade"]):
        answer = (
            "I can't assign or provide a percentage grade. I am not the Auto Grader.\n\n"
            "I can help you understand the relevant rubric or grading guidance, or help you compare your work against "
            "the published criteria if you ask about a specific task or rubric area."
        )
        return {
            "model": None,
            "llm_called": False,
            "answer": answer,
            "answer_with_sources": _append_sources(answer, references),
            "source_references": references,
        }
    policy = retrieval.get("evidence_policy", {})
    if policy.get("complete_work_request"):
        task_reference = policy.get("task_reference") or "the referenced task"
        primary = evidence[0] if evidence else {}
        topic = primary.get("topic") or task_reference
        answer = (
            f"I can't write or complete your {task_reference} assessed answer for you.\n\n"
            f"I can help you understand the requirement. Based on the official evidence for {topic}, use it as a checklist and focus on:\n"
            "- what the task is asking you to create;\n"
            "- how the required model, relationships, hierarchy, or other task elements should be shown in your own work;\n"
            "- how your work will be checked against the relevant rubric expectations.\n\n"
            "Bring a specific part you are unsure about, and I can help you reason through it without producing the final submission for you."
        )
        return {
            "model": None,
            "llm_called": False,
            "answer": answer,
            "answer_with_sources": _append_sources(answer, references),
            "source_references": references,
        }
    return None


def _official_requirement_checklist_response(
    learner_question: str,
    retrieval: dict[str, Any],
    evidence: list[dict[str, Any]],
    references: list[str],
) -> dict[str, Any] | None:
    policy = retrieval.get("evidence_policy", {})
    if not policy.get("assessment_context"):
        return None
    if _asks_for_rubric_band_or_marks(learner_question):
        return None

    for row in evidence:
        if row.get("knowledge_role") != "OFFICIAL_REQUIREMENT":
            continue
        checklist = _extract_official_checklist(str(row.get("content") or row.get("content_preview") or ""))
        if not checklist:
            continue
        section_title = _section_title(row, checklist["section_title"])
        task_reference = row.get("task_reference")
        label = str(task_reference or section_title or "this requirement")
        lines = [
            f"For {label}, the official requirements are:",
            "",
        ]
        lines.extend(f"{index}. {item}" for index, item in enumerate(checklist["items"], start=1))
        if checklist["expected_outcome"]:
            lines.extend(["", f"Expected outcome: {checklist['expected_outcome']}"])
        answer = "\n".join(lines)
        return {
            "model": None,
            "llm_called": False,
            "answer": answer,
            "answer_with_sources": _append_sources(answer, references),
            "source_references": references,
        }
    return None


def _asks_for_rubric_band_or_marks(question: str) -> bool:
    return bool(re.search(r"\b(proficient|foundation|failed|rubric|marks?|grade|percentage)\b", question.lower()))


def _official_requirement_rubric_response(
    learner_question: str,
    retrieval: dict[str, Any],
    evidence: list[dict[str, Any]],
    references: list[str],
) -> dict[str, Any] | None:
    policy = retrieval.get("evidence_policy", {})
    if not policy.get("assessment_context"):
        return None
    for row in evidence:
        if row.get("knowledge_role") != "OFFICIAL_REQUIREMENT":
            continue
        rubric = _extract_official_rubric(str(row.get("content") or row.get("content_preview") or ""))
        if not rubric:
            continue
        answer = _format_rubric_answer(learner_question, row, rubric)
        return {
            "model": None,
            "llm_called": False,
            "answer": answer,
            "answer_with_sources": _append_sources(answer, references),
            "source_references": references,
        }
    return None


def _extract_official_rubric(content: str) -> dict[str, Any] | None:
    normalized = _clean_source_text(content)
    if "Performance band" not in normalized or "Expectation" not in normalized:
        return None
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    area = _line_value(lines, "Assessment Area")
    task = _line_value(lines, "Task Reference")
    marks = _line_value(lines, "Marks")
    bands: dict[str, str] = {}
    for band in ["Failed", "Foundation", "Proficient"]:
        match = re.search(rf"\|\s*({band}\s*\([^)]+\))\s*\|\s*([^|]+?)\s*\|", normalized, flags=re.I | re.S)
        if match:
            bands[band] = f"{match.group(1).strip()}: {_clean_source_text(match.group(2).strip())}"
    if not bands:
        return None
    return {"area": area, "task": task, "marks": marks, "bands": bands}


def _line_value(lines: list[str], label: str) -> str:
    prefix = f"{label}:"
    for line in lines:
        if line.lower().startswith(prefix.lower()):
            return line.split(":", 1)[1].strip()
    return ""


def _format_rubric_answer(question: str, row: dict[str, Any], rubric: dict[str, Any]) -> str:
    question_l = question.lower()
    task = rubric["task"] or row.get("task_reference") or "this assessment area"
    area = rubric["area"] or row.get("topic") or "the official rubric"
    marks = rubric["marks"]
    if "proficient" in question_l and rubric["bands"].get("Proficient"):
        lines = [f"For {task}, the Proficient expectation is:"]
        lines.extend(["", f"- {rubric['bands']['Proficient']}"])
    elif "foundation" in question_l and rubric["bands"].get("Foundation"):
        lines = [f"For {task}, the Foundation expectation is:"]
        lines.extend(["", f"- {rubric['bands']['Foundation']}"])
    elif "failed" in question_l and rubric["bands"].get("Failed"):
        lines = [f"For {task}, the Failed expectation is:"]
        lines.extend(["", f"- {rubric['bands']['Failed']}"])
    else:
        lines = [f"For {task}, the official rubric for {area} says:"]
        if marks:
            lines.append(f"Marks: {marks}.")
        lines.append("")
        lines.extend(f"- {value}" for value in rubric["bands"].values())
    return "\n".join(lines)


def _extract_official_checklist(content: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in _clean_source_text(content).splitlines() if line.strip()]
    if not lines:
        return None

    section_title = ""
    body_lines = []
    for line in lines:
        if line.lower().startswith("section:"):
            section_title = line.split(":", 1)[1].strip()
            continue
        body_lines.append(line)

    marker_index = None
    marker_patterns = [
        r"\byou\s+are\s+required\s+to\s*:\s*$",
        r"\bshould\s+include\s*:\s*$",
        r"\bmust\s+include\s*:\s*$",
        r"\bis\s+required\s+to\s*:\s*$",
        r"\bare\s+required\s+to\s*:\s*$",
    ]
    for index, line in enumerate(body_lines):
        if any(re.search(pattern, line.lower()) for pattern in marker_patterns):
            marker_index = index
            break
    if marker_index is None:
        return None

    after_marker = _merge_wrapped_lines(body_lines[marker_index + 1 :])
    if not after_marker:
        return None

    expected_outcome = ""
    if _looks_like_expected_outcome(after_marker[-1]):
        expected_outcome = after_marker[-1].rstrip(".") + "."
        after_marker = after_marker[:-1]

    items = [_normalize_requirement_item(line) for line in _combine_child_items(after_marker) if _is_requirement_item(line)]
    if not items:
        return None
    return {
        "section_title": section_title,
        "items": items,
        "expected_outcome": expected_outcome,
    }


def _looks_like_expected_outcome(line: str) -> bool:
    line_l = line.lower()
    if line_l.startswith(("expected outcome:", "outcome:")):
        return True
    return bool(re.match(r"^(a|an|the)\s+", line_l)) and not line.rstrip().endswith(":")


def _is_requirement_item(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.lower().startswith(("section:", "expected outcome:", "outcome:")):
        return False
    return True


def _normalize_requirement_item(line: str) -> str:
    stripped = re.sub(r"^[\-*\u2022]\s*", "", line.strip())
    return stripped.rstrip(".") + "."


def _section_title(row: dict[str, Any], extracted_title: str) -> str:
    return str(row.get("topic") or row.get("title") or extracted_title or "").strip()


def _merge_wrapped_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if merged and _looks_like_wrapped_continuation(line):
            merged[-1] = f"{merged[-1]} {line}"
        else:
            merged.append(line)
    return merged


def _looks_like_wrapped_continuation(line: str) -> bool:
    return bool(line) and line[0].islower()


def _combine_child_items(lines: list[str]) -> list[str]:
    combined: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.endswith(":"):
            children: list[str] = []
            index += 1
            while index < len(lines) and _looks_like_child_item(lines[index]):
                children.append(lines[index].rstrip("."))
                index += 1
            if children:
                combined.append(f"{line.rstrip(':')}: {', '.join(children)}.")
            else:
                combined.append(line)
            continue
        combined.append(line)
        index += 1
    return combined


def _looks_like_child_item(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and len(stripped.split()) <= 4 and not stripped.endswith((".", ":"))


def _clean_source_text(text: str) -> str:
    return str(text or "").replace("\ufffd", "-")


def _official_absent_need_response(
    learner_question: str,
    evidence: list[dict[str, Any]],
    references: list[str],
) -> dict[str, Any] | None:
    needed_item = _extract_needed_item(learner_question)
    if not needed_item:
        return None
    official_evidence = [row for row in evidence if row.get("knowledge_role") == "OFFICIAL_REQUIREMENT"]
    if not official_evidence:
        return None
    item_tokens = _significant_tokens(needed_item)
    if not item_tokens:
        return None
    official_text = " ".join(
        str(row.get(field, ""))
        for row in official_evidence
        for field in ["content_preview", "topic", "title", "section_title", "task_reference"]
    ).lower()
    official_tokens = _significant_tokens(official_text)
    if item_tokens <= official_tokens:
        return None

    answer = (
        f"The retrieved official requirements do not state that {needed_item.strip()} is required.\n\n"
        "Use the Project Brief requirements as the authority for what must be included. "
        "If you want to add something beyond those requirements, treat it as optional unless your lecturer gives a specific instruction."
    )
    return {
        "model": None,
        "llm_called": False,
        "answer": answer,
        "answer_with_sources": _append_sources(answer, references),
        "source_references": references,
    }


def _extract_needed_item(question: str) -> str | None:
    match = re.search(r"\bdo\s+(?:i|we)\s+need(?:\s+to)?\s+(.+?)\??$", question.strip(), flags=re.I)
    if not match:
        return None
    item = match.group(1).strip()
    return item if item else None


def _significant_tokens(text: str) -> set[str]:
    stopwords = {
        "about",
        "also",
        "create",
        "include",
        "make",
        "need",
        "provide",
        "required",
        "show",
        "submit",
        "that",
        "this",
        "use",
        "with",
    }
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 3 and token not in stopwords}


def _build_user_input(
    learner_question: str,
    evidence: list[dict[str, Any]],
    conversation_history: list[dict[str, str]],
) -> str:
    parts = [
        "Recent conversation context:",
        _format_history(conversation_history),
        "",
        f"Learner question: {learner_question}",
        "",
        "Response policy notes:",
        _format_policy_notes(learner_question, evidence),
        "",
        "Retrieved approved module evidence:",
    ]
    for index, row in enumerate(evidence, start=1):
        parts.append(
            "\n".join(
                [
                    f"[E{index}]",
                    f"Knowledge role: {row.get('knowledge_role', '')}",
                    f"Source: {_source_label(row)}, {_page_label(row.get('page_start'), row.get('page_end'))}",
                    f"Topic: {row.get('topic', '')}",
                    f"Task/reference: {row.get('task_reference') or 'N/A'}",
                    "Content:",
                    row.get("content") or row.get("content_preview", ""),
                ]
            )
        )
    return "\n\n".join(parts)


def _format_history(conversation_history: list[dict[str, str]]) -> str:
    if not conversation_history:
        return "No previous turns."
    recent = conversation_history[-6:]
    return "\n".join(f"{turn.get('role', 'unknown')}: {turn.get('content', '')}" for turn in recent)


def _format_policy_notes(learner_question: str, evidence: list[dict[str, Any]]) -> str:
    notes = []
    roles = {row.get("knowledge_role", "") for row in evidence}
    if "OFFICIAL_REQUIREMENT" in roles:
        notes.append(
            "If this is an assessment or requirement question, answer primarily from OFFICIAL_REQUIREMENT evidence. "
            "Use other roles only for brief supporting explanation."
        )
        if _is_requirement_need_question(learner_question):
            notes.append(
                "For questions asking what is needed, required, included, or how many are needed, state only what the "
                "OFFICIAL_REQUIREMENT evidence requires. If the learner asks whether an item is required and the "
                "official evidence does not require it, say it is not required by the retrieved official evidence."
            )
    task_refs = sorted({str(row.get("task_reference")) for row in evidence if row.get("task_reference")})
    if task_refs:
        notes.append(
            "Keep the answer aligned to these task/reference values from the evidence: "
            + ", ".join(task_refs)
            + ". Do not drift into other assessment tasks."
        )
    question_l = learner_question.lower()
    if _is_direct_question(question_l):
        notes.append(
            "This looks like a direct factual or how-to question. Prefer a direct answer and one short explanation. "
            "Do not produce a long procedural tutorial unless the learner explicitly asks for steps."
        )
    if any(phrase in question_l for phrase in ["simple", "simply", "don't understand", "do not understand", "example"]):
        notes.append(
            "The learner is asking for a simpler explanation. Use plain language, one small concrete example if supported by the evidence, "
            "and a brief explanation of what the example means."
        )
    if any(term in question_l for term in ["write my", "do my", "complete", "answer for me"]):
        notes.append(
            "The learner may be asking for complete assessed work. Refuse to produce a complete submission-ready answer. "
            "Give only brief learning guidance, at most three short bullets, grounded in the matching task evidence."
        )
    return "\n".join(f"- {note}" for note in notes) if notes else "No additional response policy notes."


def _is_direct_question(question_l: str) -> bool:
    return question_l.startswith(("where ", "what is ", "what are ", "how many ", "which ", "when "))


def _is_requirement_need_question(question: str) -> bool:
    question_l = question.lower()
    return any(
        re.search(pattern, question_l)
        for pattern in [
            r"\bdo\s+i\s+need\b",
            r"\bdo\s+we\s+need\b",
            r"\bwhat\s+do\s+i\s+need\b",
            r"\bwhat\s+do\s+we\s+need\b",
            r"\bhow\s+many\b",
            r"\brequired\b",
            r"\brequirement\b",
            r"\bneed\s+to\s+(do|submit|include|create|use|show|provide|write|add|make)\b",
        ]
    )


def _clean_answer(answer: str) -> str:
    filler_patterns = [
        r"\s*If you have any (more|further) questions, feel free to ask!?$",
        r"\s*Feel free to ask if you have any (more|further) questions!?$",
        r"\s*If you need more help, feel free to ask!?$",
    ]
    cleaned = answer.strip().replace("\ufffd", "-")
    for pattern in filler_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _append_sources(answer: str, references: list[str]) -> str:
    if not references:
        return answer
    return answer.rstrip() + "\n\nSources: " + "; ".join(references)


def _source_label(row: dict[str, Any]) -> str:
    instructional_unit = str(row.get("instructional_unit") or "").strip()
    if instructional_unit:
        return instructional_unit

    document_type = _normalized_label_token(row.get("document_type"))
    knowledge_role = _normalized_label_token(row.get("knowledge_role"))
    source_file = _normalized_label_token(Path(str(row.get("source_file") or "")).stem)

    if document_type in {"projectbrief", "brief", "assignmentbrief"} or knowledge_role == "officialrequirement":
        return "Project Brief"
    if document_type in {"learnerguide", "moduleguide", "guide"} or knowledge_role == "moduleguidance" or "learnerguide" in source_file:
        return "Learner Guide"
    if knowledge_role == "learningmaterial":
        return "Learning Material"
    return "Approved module material"


def _normalized_label_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _page_label(start: Any, end: Any) -> str:
    if start in (None, ""):
        return ""
    if end in (None, "") or str(start) == str(end):
        return f"page {start}"
    return f"pages {start}-{end}"
