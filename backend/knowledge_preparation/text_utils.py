from __future__ import annotations

import re


WHITESPACE_RE = re.compile(r"[ \t]+")


def clean_line(line: str) -> str:
    return WHITESPACE_RE.sub(" ", line).strip()


def normalize_text(text: str) -> str:
    lines = [clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def token_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def stable_slug(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "chunk"

