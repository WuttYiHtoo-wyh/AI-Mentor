from __future__ import annotations

import hashlib
import re

from .models import PreparedChunk, Section, SourceConfig
from .text_utils import stable_slug, token_count


TARGET_TOKENS = 850
MAX_TOKENS = 1200
OVERLAP_TOKENS = 100
MIN_REVIEW_TOKENS = 12
INFORMATIONAL_WARNINGS = {"low_text_image_heavy_page"}


def chunk_sections(source: SourceConfig, sections: list[Section]) -> list[PreparedChunk]:
    sections = _merge_short_sections(sections)
    chunks: list[PreparedChunk] = []
    ordinal = 0
    for section in sections:
        content = _build_content(section)
        if not content.strip():
            continue
        for part in _split_if_needed(content):
            ordinal += 1
            warnings = list(section.warnings)
            review_warnings = [warning for warning in warnings if warning not in INFORMATIONAL_WARNINGS]
            status = "needs_review" if review_warnings else "ready"
            if token_count(part) < MIN_REVIEW_TOKENS:
                status = "needs_review"
                warnings.append("short_chunk_requires_review")
            if token_count(part) > MAX_TOKENS:
                status = "needs_review"
                warnings.append("oversized_after_fallback_split")
            chunks.append(
                PreparedChunk(
                    chunk_id=_chunk_id(source, section, ordinal, part),
                    module_id=source.module_id,
                    module_name=source.module_name,
                    level=source.level,
                    document_id=source.document_id,
                    document_type=source.document_type,
                    knowledge_role=source.knowledge_role,
                    section_title=section.title,
                    topic=_topic_from_section(section.title),
                    task_reference=_task_reference(section.title),
                    instructional_unit=source.instructional_unit,
                    source_file=str(source.source_path),
                    page_start=section.page_start,
                    page_end=section.page_end,
                    status=status,
                    content=part,
                    warnings=warnings,
                )
            )
    return chunks


def _merge_short_sections(sections: list[Section]) -> list[Section]:
    merged: list[Section] = []
    for section in sections:
        section_tokens = token_count(_build_content(section))
        should_merge = (
            (section_tokens < MIN_REVIEW_TOKENS and not section.warnings and not section.title.strip().isupper())
            or _looks_like_list_continuation(section, merged[-1] if merged else None)
            or _looks_like_code_fragment(section)
        )
        if should_merge and merged:
            previous = merged[-1]
            continuation_lines, split_section = _split_embedded_heading(section)
            previous.lines.extend([section.title, *continuation_lines])
            previous.page_end = max(previous.page_end, section.page_end)
            previous.warnings.extend(w for w in section.warnings if w not in previous.warnings)
            if split_section is not None:
                merged.append(split_section)
        else:
            merged.append(section)
    return merged


def _looks_like_list_continuation(section: Section, previous: Section | None) -> bool:
    if previous is None or section.warnings:
        return False
    title = section.title.strip()
    if not (title.isupper() and len(title.split()) == 1):
        return False
    if section.lines and section.lines[0].strip().endswith(":"):
        return False
    previous_tail = [line.strip() for line in previous.lines[-4:] if line.strip()]
    uppercase_tail = [line for line in previous_tail if line.isupper() and len(line.split()) == 1]
    return len(uppercase_tail) >= 2


def _looks_like_code_fragment(section: Section) -> bool:
    if section.warnings:
        return False
    title = section.title.strip()
    if token_count(_build_content(section)) >= 20:
        return False
    if title.endswith("("):
        return True
    if title.upper() in {"SELECT", "SELECT *"}:
        return True
    return False


def _split_embedded_heading(section: Section) -> tuple[list[str], Section | None]:
    for index, line in enumerate(section.lines):
        stripped = line.strip()
        if stripped.isupper() and len(stripped.split()) <= 3:
            return (
                section.lines[:index],
                Section(
                    title=stripped,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    lines=section.lines[index + 1 :],
                    warnings=list(section.warnings),
                ),
            )
    return section.lines, None


def _build_content(section: Section) -> str:
    body = "\n".join(section.lines).strip()
    if not body:
        return ""
    return f"Section: {section.title}\n\n{body}"


def _split_if_needed(content: str) -> list[str]:
    if token_count(content) <= MAX_TOKENS:
        return [content]

    paragraphs = _paragraphs(content)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for paragraph in paragraphs:
        paragraph_tokens = token_count(paragraph)
        if current and current_tokens + paragraph_tokens > TARGET_TOKENS:
            chunks.append("\n\n".join(current))
            overlap = _tail_tokens(" ".join(current), OVERLAP_TOKENS)
            current = [overlap] if overlap else []
            current_tokens = token_count(overlap)

        if paragraph_tokens > MAX_TOKENS:
            chunks.extend(_split_words(paragraph))
            current = []
            current_tokens = 0
        else:
            current.append(paragraph)
            current_tokens += paragraph_tokens

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _paragraphs(content: str) -> list[str]:
    raw = re.split(r"\n{2,}", content)
    if len(raw) > 1:
        return [part.strip() for part in raw if part.strip()]
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    groups: list[str] = []
    current: list[str] = []
    for line in lines:
        current.append(line)
        if len(current) >= 8:
            groups.append("\n".join(current))
            current = []
    if current:
        groups.append("\n".join(current))
    return groups


def _split_words(text: str) -> list[str]:
    words = text.split()
    parts = []
    step = max(1, MAX_TOKENS - OVERLAP_TOKENS)
    for start in range(0, len(words), step):
        parts.append(" ".join(words[start : start + MAX_TOKENS]))
    return parts


def _tail_tokens(text: str, count: int) -> str:
    words = text.split()
    return " ".join(words[-count:])


def _topic_from_section(title: str) -> str | None:
    title = title.strip()
    title = re.sub(r"^\d+(\.\d+)*\.?\s+", "", title)
    return title or None


def _task_reference(title: str) -> str | None:
    match = re.search(r"\bTask\s+\d+\b", title, re.IGNORECASE)
    return match.group(0).title() if match else None


def _chunk_id(source: SourceConfig, section: Section, ordinal: int, content: str) -> str:
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]
    return "-".join(
        [
            stable_slug(source.module_id),
            stable_slug(source.level),
            stable_slug(source.document_id),
            f"{ordinal:04d}",
            stable_slug(section.title)[:40],
            digest,
        ]
    )
