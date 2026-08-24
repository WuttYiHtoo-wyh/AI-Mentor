from __future__ import annotations

from collections import Counter

import fitz
import pdfplumber

from .models import ExtractedDocument, ExtractedPage, SourceConfig
from .text_utils import clean_line, normalize_text


LOW_TEXT_WORD_THRESHOLD = 80


def extract_document(source: SourceConfig) -> ExtractedDocument:
    if not source.source_path.exists():
        return ExtractedDocument(
            source=source,
            pages=[],
            repeated_lines=set(),
            warnings=[f"source_missing:{source.source_path}"],
        )

    fitz_doc = fitz.open(source.source_path)
    table_counts = _extract_table_counts(source)
    pages: list[ExtractedPage] = []
    all_lines: list[str] = []

    for index, page in enumerate(fitz_doc, start=1):
        text = normalize_text(page.get_text("text"))
        lines = [_normalize_bullet_line(line) for line in text.splitlines()]
        lines = [line for line in lines if line]
        word_count = len(text.split())
        image_count = len(page.get_images(full=True))
        table_count = table_counts.get(index, 0)
        warnings: list[str] = []

        if word_count < LOW_TEXT_WORD_THRESHOLD and image_count > 0:
            warnings.append("low_text_image_heavy_page")
        elif word_count < 20:
            warnings.append("very_low_text_page")
        if table_count:
            warnings.append("table_detected_requires_structure_review")

        all_lines.extend(lines)
        pages.append(
            ExtractedPage(
                page_number=index,
                text=text,
                lines=lines,
                word_count=word_count,
                has_tables=table_count > 0,
                table_count=table_count,
                image_count=image_count,
                warnings=warnings,
            )
        )

    repeated_lines = _find_repeated_lines(all_lines, len(pages))
    cleaned_pages = [
        ExtractedPage(
            page_number=page.page_number,
            text="\n".join(line for line in page.lines if line not in repeated_lines),
            lines=[line for line in page.lines if line not in repeated_lines],
            word_count=len([word for line in page.lines if line not in repeated_lines for word in line.split()]),
            has_tables=page.has_tables,
            table_count=page.table_count,
            image_count=page.image_count,
            warnings=page.warnings,
        )
        for page in pages
    ]

    return ExtractedDocument(source=source, pages=cleaned_pages, repeated_lines=repeated_lines)


def _find_repeated_lines(lines: list[str], page_count: int) -> set[str]:
    if page_count < 3:
        return set()
    counts = Counter(line for line in lines if 3 <= len(line) <= 90)
    threshold = max(3, int(page_count * 0.35))
    return {line for line, count in counts.items() if count >= threshold}


def _extract_table_counts(source: SourceConfig) -> dict[int, int]:
    counts: dict[int, int] = {}
    try:
        with pdfplumber.open(source.source_path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables() or []
                counts[index] = len(tables)
    except Exception:
        return {}
    return counts


def _normalize_bullet_line(line: str) -> str:
    cleaned = clean_line(line)
    if cleaned in {"o", "•", "●", "-", "–"}:
        return ""
    return cleaned
