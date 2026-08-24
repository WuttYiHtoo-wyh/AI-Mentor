from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pdfplumber

from .models import PreparedChunk, SourceConfig
from .text_utils import stable_slug


RUBRIC_SECTION_TITLE = "MARKING RUBRICS"


def replace_rubric_fragments(source: SourceConfig, chunks: list[PreparedChunk]) -> list[PreparedChunk]:
    if source.document_type != "project_brief":
        return chunks

    rubric_chunks = _extract_rubric_chunks(source)
    if not rubric_chunks:
        return chunks

    kept = [
        chunk
        for chunk in chunks
        if not (
            chunk.document_id == source.document_id
            and chunk.page_start >= min(chunk.page_start for chunk in rubric_chunks)
            and chunk.section_title != "Document"
        )
    ]
    return kept + rubric_chunks


def _extract_rubric_chunks(source: SourceConfig) -> list[PreparedChunk]:
    rows = _extract_rubric_rows(source.source_path)
    chunks: list[PreparedChunk] = []
    for index, row in enumerate(rows, start=1):
        if row["assessment_area"] == "Total":
            content = "Section: MARKING RUBRICS\n\nTotal marks: 100"
            chunks.append(_chunk(source, index, row, content, "Rubric Total", None, "ready"))
            continue

        content = "\n".join(
            [
                "Section: MARKING RUBRICS",
                f"Assessment Area: {row['assessment_area']}",
                f"Task Reference: {row['task_reference']}",
                f"Marks: {row['marks']}",
                "",
                "| Performance band | Expectation |",
                "|---|---|",
                f"| Failed (0-49%) | {row['failed']} |",
                f"| Foundation (50-74%) | {row['foundation']} |",
                f"| Proficient (75-100%) | {row['proficient']} |",
            ]
        )
        status = "ready" if _row_is_valid(row) else "needs_review"
        warnings = [] if status == "ready" else ["rubric_reconstruction_requires_review"]
        chunks.append(
            _chunk(
                source=source,
                index=index,
                row=row,
                content=content,
                topic=f"{row['assessment_area']} Rubric",
                task_reference=_task_reference(row["task_reference"]),
                status=status,
                warnings=warnings,
            )
        )
    return chunks


def _extract_rubric_rows(path: Path) -> list[dict[str, str | int]]:
    logical_rows: list[dict[str, str | int]] = []
    current: list[str] | None = None
    current_page = 0

    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables() or []:
                for raw_row in table:
                    cells = [_clean_cell(cell) for cell in raw_row]
                    cells = (cells + [""] * 6)[:6]
                    if _skip_row(cells):
                        continue
                    if _is_total_row(cells):
                        if current is not None:
                            logical_rows.append(_to_row(current, current_page, page_index))
                            current = None
                        logical_rows.append(
                            {
                                "assessment_area": "Total",
                                "task_reference": "",
                                "failed": "",
                                "foundation": "",
                                "proficient": "",
                                "marks": "100",
                                "page_start": page_index,
                                "page_end": page_index,
                            }
                        )
                        current = None
                        continue
                    if cells[0] or cells[5]:
                        if current is not None:
                            logical_rows.append(_to_row(current, current_page, page_index))
                        current = cells
                        current_page = page_index
                    elif current is not None:
                        for idx, cell in enumerate(cells):
                            if cell:
                                current[idx] = _join(current[idx], cell)
                if current is not None:
                    logical_rows.append(_to_row(current, current_page, page_index))
                    current = None
    return [row for row in logical_rows if row["assessment_area"]]


def _clean_cell(cell: str | None) -> str:
    if not cell:
        return ""
    text = " ".join(str(cell).split())
    text = re.sub(r"(?<=\d)�(?=\d)", "–", text)
    text = text.replace("Proficient (75- 100%)", "Proficient (75-100%)")
    text = text.replace("recommendation s", "recommendations")
    text = text.replace("recommendatio ns", "recommendations")
    text = text.replace("performers/trend s", "performers/trends")
    text = text.replace("Transformatio n", "Transformation")
    text = text.replace("star- schema", "star-schema")
    text = text.replace("drill- down", "drill-down")
    return text.strip()


def _skip_row(cells: list[str]) -> bool:
    joined = " ".join(cells)
    if not joined:
        return True
    header_terms = {"Assessment Area", "Task Reference", "Failed (0-49%)", "Foundation (50-74%)"}
    return any(term in joined for term in header_terms)


def _is_total_row(cells: list[str]) -> bool:
    return cells[4] == "Total" and cells[5] == "100"


def _to_row(cells: list[str], page_start: int, page_end: int) -> dict[str, str | int]:
    return {
        "assessment_area": _normalize_joined(cells[0]),
        "task_reference": _normalize_joined(cells[1]),
        "failed": _normalize_joined(cells[2]),
        "foundation": _normalize_joined(cells[3]),
        "proficient": _normalize_joined(cells[4]),
        "marks": _normalize_joined(cells[5]),
        "page_start": page_start,
        "page_end": page_end,
    }


def _normalize_joined(text: str) -> str:
    text = text.replace("drill- down", "drill-down")
    text = text.replace("Deliverable :", "Deliverable:")
    text = text.replace("recommendations .", "recommendations.")
    text = re.sub(r"\s+([.;,:])", r"\1", text)
    return text


def _join(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    return f"{left} {right}"


def _row_is_valid(row: dict[str, str | int]) -> bool:
    if row["assessment_area"] == "Total":
        return row["marks"] == "100"
    required = ["assessment_area", "task_reference", "failed", "foundation", "proficient", "marks"]
    return all(str(row[field]).strip() for field in required) and str(row["marks"]).isdigit()


def _task_reference(value: str) -> str | None:
    match = re.search(r"\bTask\s+\d+\b", value, re.IGNORECASE)
    return match.group(0).title() if match else None


def _chunk(
    source: SourceConfig,
    index: int,
    row: dict[str, str | int],
    content: str,
    topic: str,
    task_reference: str | None,
    status: str,
    warnings: list[str] | None = None,
) -> PreparedChunk:
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]
    chunk_id = "-".join(
        [
            stable_slug(source.module_id),
            stable_slug(source.level),
            stable_slug(source.document_id),
            "rubric",
            f"{index:02d}",
            digest,
        ]
    )
    return PreparedChunk(
        chunk_id=chunk_id,
        module_id=source.module_id,
        module_name=source.module_name,
        level=source.level,
        document_id=source.document_id,
        document_type=source.document_type,
        knowledge_role=source.knowledge_role,
        section_title=RUBRIC_SECTION_TITLE,
        topic=topic,
        task_reference=task_reference,
        instructional_unit=source.instructional_unit,
        source_file=str(source.source_path),
        page_start=int(row["page_start"]),
        page_end=int(row["page_end"]),
        status=status,
        content=content,
        embedding_eligible=status == "ready",
        warnings=warnings or [],
    )
