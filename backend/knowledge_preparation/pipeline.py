from __future__ import annotations

from pathlib import Path
from typing import Any

from .chunker import MAX_TOKENS, chunk_sections
from .config import load_module_config
from .eligibility import apply_embedding_eligibility
from .extractor import extract_document
from .models import ExtractedDocument, PreparedChunk
from .rubric import replace_rubric_fragments
from .structure import detect_sections
from .validator import validate
from .writer import write_jsonl, write_report


def prepare_module(config_path: Path, workspace_root: Path) -> dict[str, Any]:
    config = load_module_config(config_path=config_path, workspace_root=workspace_root)
    documents: list[ExtractedDocument] = []
    chunks: list[PreparedChunk] = []

    for source in config.sources:
        document = extract_document(source)
        documents.append(document)
        sections = detect_sections(document)
        source_chunks = chunk_sections(source, sections)
        source_chunks = replace_rubric_fragments(source, source_chunks)
        chunks.extend(source_chunks)

    apply_embedding_eligibility(chunks)
    report = validate(config=config, documents=documents, chunks=chunks, max_tokens=MAX_TOKENS)
    output_jsonl = config.output_dir / "prepared_chunks.jsonl"
    report_json = config.output_dir / "validation_report.json"
    write_jsonl(chunks, output_jsonl)
    write_report(report, report_json)

    report["output"] = {
        "prepared_jsonl": str(output_jsonl),
        "validation_report": str(report_json),
    }
    write_report(report, report_json)
    return report
