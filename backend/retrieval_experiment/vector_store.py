from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb


def reset_collection(chroma_path: Path, collection_name: str):
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def open_collection(chroma_path: Path, collection_name: str):
    client = chromadb.PersistentClient(path=str(chroma_path))
    return client.get_collection(collection_name)


def upsert_batches(
    collection,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    batch_size: int,
) -> None:
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        collection.upsert(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )

