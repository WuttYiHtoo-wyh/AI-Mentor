from __future__ import annotations

from collections import Counter

from .models import PreparedChunk
from .text_utils import token_count


INFORMATIONAL_WARNINGS = {"low_text_image_heavy_page"}
REVIEW_WARNINGS = {
    "table_detected_requires_structure_review",
    "short_chunk_requires_review",
    "oversized_after_fallback_split",
    "rubric_reconstruction_requires_review",
}


def apply_embedding_eligibility(chunks: list[PreparedChunk]) -> None:
    content_counts = Counter(chunk.content.strip() for chunk in chunks)
    for chunk in chunks:
        chunk.embedding_eligible = _is_eligible(chunk, content_counts)


def _is_eligible(chunk: PreparedChunk, content_counts: Counter[str]) -> bool:
    content = chunk.content.strip()
    if not content:
        return False
    if content_counts[content] > 1:
        return False
    if token_count(content) > 1200:
        return False
    non_info_warnings = [warning for warning in chunk.warnings if warning not in INFORMATIONAL_WARNINGS]
    if "rubric_reconstruction_requires_review" in non_info_warnings:
        return False
    if _looks_broken_short_fragment(chunk):
        return False
    return True


def _looks_broken_short_fragment(chunk: PreparedChunk) -> bool:
    words = token_count(chunk.content)
    if words >= 12:
        return False
    title = chunk.section_title.strip()
    if chunk.content.strip().endswith(":"):
        return True
    if title.upper() in {"DOCUMENT", "LEARNER GUIDE"}:
        return True
    if title.endswith("(") or title in {"SELECT", "SELECT *"}:
        return True
    return False
