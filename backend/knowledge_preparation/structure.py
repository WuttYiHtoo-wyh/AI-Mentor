from __future__ import annotations

import re

from .models import ExtractedDocument, Section


NUMBERED_HEADING_RE = re.compile(r"^\d+(\.\d+)*\.?\s+\S")
TASK_HEADING_RE = re.compile(r"^Task\s+\d+\s*:", re.IGNORECASE)
def detect_sections(document: ExtractedDocument) -> list[Section]:
    sections: list[Section] = []
    current = Section(title="Document", page_start=1, page_end=1)

    for page in document.pages:
        page_warnings = list(page.warnings)
        previous_line = ""
        for line in page.lines:
            if _is_heading(line, previous_line):
                if current.lines:
                    sections.append(current)
                elif sections and current.title != "Document":
                    sections[-1].lines.append(current.title)
                    sections[-1].page_end = page.page_number
                current = Section(
                    title=line,
                    page_start=page.page_number,
                    page_end=page.page_number,
                    warnings=list(page_warnings),
                )
            else:
                current.lines.append(line)
                current.page_end = page.page_number
                current.warnings.extend(w for w in page_warnings if w not in current.warnings)
            previous_line = line

    if current.lines:
        sections.append(current)

    if not sections and document.pages:
        return [
            Section(
                title="Document",
                page_start=document.pages[0].page_number,
                page_end=document.pages[-1].page_number,
                lines=[line for page in document.pages for line in page.lines],
                warnings=[warning for page in document.pages for warning in page.warnings],
            )
        ]
    return sections


def _is_heading(line: str, previous_line: str = "") -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^\d+\s*\|\s*P\s*a\s*g\s*e$", stripped, re.IGNORECASE):
        return False
    if TASK_HEADING_RE.match(stripped):
        return True
    if NUMBERED_HEADING_RE.match(stripped) and len(stripped) <= 120:
        # Numbered headings usually name a section. Numbered list items often read
        # as complete sentences; keep those attached to their parent section.
        if stripped.endswith("."):
            return False
        return True
    if stripped.isupper() and 4 <= len(stripped) <= 80:
        return True
    return False
