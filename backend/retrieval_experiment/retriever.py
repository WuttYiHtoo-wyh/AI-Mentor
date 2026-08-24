from __future__ import annotations

from pathlib import Path
from typing import Any

from .embeddings import OpenAIEmbedder
from .vector_store import open_collection


def retrieve(
    learner_query: str,
    module_id: str,
    level: str,
    top_k: int,
    chroma_path: Path,
    collection_name: str,
    embedding_model: str,
    knowledge_role: str | None = None,
) -> list[dict[str, Any]]:
    embedder = OpenAIEmbedder(embedding_model)
    query_embedding = embedder.embed_texts([learner_query])[0]
    return retrieve_with_embedding(
        query_embedding=query_embedding,
        module_id=module_id,
        level=level,
        top_k=top_k,
        chroma_path=chroma_path,
        collection_name=collection_name,
        knowledge_role=knowledge_role,
    )


def retrieve_with_embedding(
    query_embedding: list[float],
    module_id: str,
    level: str,
    top_k: int,
    chroma_path: Path,
    collection_name: str,
    knowledge_role: str | None = None,
) -> list[dict[str, Any]]:
    collection = open_collection(chroma_path, collection_name)
    where: dict[str, Any] = {"$and": [{"module_id": module_id}, {"level": level}]}
    if knowledge_role:
        where["$and"].append({"knowledge_role": knowledge_role})

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    rows: list[dict[str, Any]] = []
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    documents = result.get("documents", [[]])[0]
    for index, chunk_id in enumerate(ids):
        metadata = metadatas[index]
        distance = float(distances[index])
        rows.append(
            {
                "rank": index + 1,
                "chunk_id": chunk_id,
                "distance": distance,
                "similarity": 1.0 - distance,
                "title": metadata.get("section_title", ""),
                "topic": metadata.get("topic", ""),
                "module_id": metadata.get("module_id", ""),
                "module_name": metadata.get("module_name", ""),
                "level": metadata.get("level", ""),
                "document_id": metadata.get("document_id", ""),
                "document_type": metadata.get("document_type", ""),
                "knowledge_role": metadata.get("knowledge_role", ""),
                "task_reference": metadata.get("task_reference", ""),
                "instructional_unit": metadata.get("instructional_unit", ""),
                "source_file": metadata.get("source_file", ""),
                "page_start": metadata.get("page_start", ""),
                "page_end": metadata.get("page_end", ""),
                "content_preview": _preview(documents[index]),
            }
        )
    return rows


def _preview(text: str, limit: int = 500) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
