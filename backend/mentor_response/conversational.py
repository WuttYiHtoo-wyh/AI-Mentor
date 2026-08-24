from __future__ import annotations

import re
from typing import Any


def pre_retrieval_conversational_response(message: str) -> dict[str, Any] | None:
    text = _normalize(message)
    if not text:
        return None

    name = _simple_intro_name(message)
    if name and re.match(r"^(hi|hello|hey)\b", text):
        return _response(f"Hi {name}! How can I help you with your module today?")

    if text in {"hi", "hi there", "hey", "hey there"}:
        return _response("Hi! How can I help you with your module today?")
    if text in {"hello", "hello there"}:
        return _response("Hello! What would you like help with in your module?")
    if text in {"good morning", "morning"}:
        return _response("Good morning! What can I help you with today?")
    if text in {"good afternoon", "afternoon"}:
        return _response("Good afternoon! What can I help you with today?")
    if text in {"good evening", "evening"}:
        return _response("Good evening! What can I help you with today?")
    if text in {"thanks", "thank you", "thank you very much", "thanks a lot"}:
        return _response("You're welcome.")
    if text in {"bye", "goodbye", "see you", "see you later"}:
        return _response("Goodbye. Come back anytime you need help with your module.")
    if text in {"who are you", "what are you"}:
        return _response(
            "I'm AI Mentor. I can help explain module requirements, course concepts, practical activities, "
            "and review learner-authored work using approved module materials."
        )
    if text in {"what can you help me with", "what can you do", "how can you help me"}:
        return _response(
            "I can help with assessment requirements, rubric expectations, course concepts, practical Power BI "
            "activities, simpler explanations, draft review, improvement guidance, and module guidance."
        )
    return None


def _normalize(message: str) -> str:
    text = message.lower().strip()
    text = re.sub(r"[.!?]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _simple_intro_name(message: str) -> str | None:
    match = re.match(
        r"^\s*(?:hi|hello|hey)\s*,?\s+(?:i am|i'm|my name is)\s+([A-Za-z][A-Za-z' -]{0,38}[A-Za-z])\s*[.!?]?\s*$",
        message,
        re.IGNORECASE,
    )
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group(1)).strip()
    if len(name.split()) > 2:
        return None
    return name


def _response(answer: str) -> dict[str, Any]:
    return {
        "model": None,
        "llm_called": False,
        "answer": answer,
        "answer_with_sources": answer,
        "source_references": [],
    }
