from __future__ import annotations

import re


NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}

STRUCTURAL_LABELS = {
    "task": ["task", "tas", "tsk"],
    "part": ["part", "prt"],
    "section": ["section", "sect", "sec"],
    "assignment": ["assignment", "assign", "assgn"],
}


def normalize_structural_references(text: str) -> str:
    normalized = text
    for canonical, variants in STRUCTURAL_LABELS.items():
        variant_pattern = "|".join(re.escape(variant) for variant in variants)
        normalized = re.sub(
            rf"\b({variant_pattern})\s*[-:#]?\s*(\d{{1,2}})\b",
            lambda match: f"{canonical.title()} {match.group(2)}",
            normalized,
            flags=re.IGNORECASE,
        )
        word_pattern = "|".join(NUMBER_WORDS)
        normalized = re.sub(
            rf"\b({variant_pattern})\s+({word_pattern})\b",
            lambda match: f"{canonical.title()} {NUMBER_WORDS[match.group(2).lower()]}",
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized
