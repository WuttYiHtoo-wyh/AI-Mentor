from __future__ import annotations


INTENT_ORDER = ["MODULE_GUIDANCE", "REQUIREMENT", "LEARNING"]


def detect_intent(query: str, patterns: dict[str, list[str]]) -> str:
    normalized = query.lower()
    for intent in INTENT_ORDER:
        for pattern in patterns.get(intent, []):
            if pattern.lower() in normalized:
                return intent
    return "GENERAL"

