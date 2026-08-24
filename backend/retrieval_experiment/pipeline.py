from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .chunks import chunk_metadata, chunk_to_embedding_text, load_embedding_eligible_chunks
from .config import load_retrieval_config
from .embeddings import OpenAIEmbedder
from .retriever import retrieve
from .vector_store import reset_collection, upsert_batches


def run_retrieval_baseline(config_path: Path, workspace_root: Path) -> dict[str, Any]:
    config = load_retrieval_config(config_path, workspace_root)
    chunks = load_embedding_eligible_chunks(config.prepared_chunks_path)
    embedder = OpenAIEmbedder(config.embedding_model)

    ids = [chunk["chunk_id"] for chunk in chunks]
    documents = [chunk["content"] for chunk in chunks]
    metadatas = [chunk_metadata(chunk) for chunk in chunks]
    embedding_texts = [chunk_to_embedding_text(chunk) for chunk in chunks]

    embeddings: list[list[float]] = []
    for start in range(0, len(embedding_texts), config.batch_size):
        embeddings.extend(embedder.embed_texts(embedding_texts[start : start + config.batch_size]))

    collection = reset_collection(config.chroma_path, config.collection_name)
    upsert_batches(collection, ids, embeddings, documents, metadatas, config.batch_size)

    test_questions = json.loads(config.test_set_path.read_text(encoding="utf-8"))
    flat_rows: list[dict[str, Any]] = []
    nested_results: list[dict[str, Any]] = []
    for test in test_questions:
        matches = retrieve(
            learner_query=test["question"],
            module_id=config.module_id,
            level=config.level,
            top_k=5,
            chroma_path=config.chroma_path,
            collection_name=config.collection_name,
            embedding_model=config.embedding_model,
            knowledge_role=test.get("knowledge_role"),
        )
        nested_results.append({**test, "results": matches})
        for match in matches:
            flat_rows.append(
                {
                    "test_id": test["test_id"],
                    "question": test["question"],
                    "category": test["category"],
                    "rank": match["rank"],
                    "chunk_id": match["chunk_id"],
                    "distance": match["distance"],
                    "similarity": match["similarity"],
                    "knowledge_role": match["knowledge_role"],
                    "topic": match["topic"],
                    "source_file": match["source_file"],
                    "page": _page_range(match["page_start"], match["page_end"]),
                    "content_preview": match["content_preview"],
                }
            )

    output = {
        "embedding_model": config.embedding_model,
        "chunks_embedded": len(chunks),
        "collection_name": config.collection_name,
        "chroma_path": str(config.chroma_path),
        "test_question_count": len(test_questions),
        "results": nested_results,
        "distance_summary": _distance_summary(flat_rows),
    }
    config.results_json_path.parent.mkdir(parents=True, exist_ok=True)
    config.results_json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(flat_rows, config.results_csv_path)
    return output


def _page_range(page_start: Any, page_end: Any) -> str:
    return str(page_start) if page_start == page_end else f"{page_start}-{page_end}"


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "test_id",
        "question",
        "category",
        "rank",
        "chunk_id",
        "distance",
        "similarity",
        "knowledge_role",
        "topic",
        "source_file",
        "page",
        "content_preview",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _distance_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    distances = [float(row["distance"]) for row in rows]
    if not distances:
        return {}
    return {
        "min": min(distances),
        "max": max(distances),
        "average": sum(distances) / len(distances),
    }

