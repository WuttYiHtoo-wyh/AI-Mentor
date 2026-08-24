from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.retrieval_experiment.config import load_retrieval_config
from backend.retrieval_experiment.embeddings import OpenAIEmbedder
from backend.retrieval_experiment.experiment3 import INTENT_ROLE, _merge_candidates, _rank
from backend.retrieval_experiment.intent import detect_intent
from backend.retrieval_experiment.rerank import rerank_candidates
from backend.retrieval_experiment.retriever import retrieve_with_embedding


def retrieve_experiment3_evidence(
    learner_question: str,
    retrieval_config_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    config = load_retrieval_config(retrieval_config_path, workspace_root)
    raw = yaml.safe_load(retrieval_config_path.read_text(encoding="utf-8"))
    selected_config = raw["candidate_pool_configs"][-1]
    general_top_k = int(selected_config["general_top_k"])
    preferred_role_top_k = int(selected_config["preferred_role_top_k"])
    threshold = float(raw["selected_threshold"])
    final_top_k = int(raw["final_top_k"])
    intent = detect_intent(learner_question, raw["intent_patterns"])
    preferred_role = INTENT_ROLE.get(intent)

    embedder = OpenAIEmbedder(config.embedding_model)
    query_embedding = embedder.embed_texts([learner_question])[0]
    general_candidates = retrieve_with_embedding(
        query_embedding=query_embedding,
        module_id=config.module_id,
        level=config.level,
        top_k=general_top_k,
        chroma_path=config.chroma_path,
        collection_name=config.collection_name,
    )
    preferred_role_candidates: list[dict[str, Any]] = []
    if preferred_role:
        preferred_role_candidates = retrieve_with_embedding(
            query_embedding=query_embedding,
            module_id=config.module_id,
            level=config.level,
            top_k=preferred_role_top_k,
            chroma_path=config.chroma_path,
            collection_name=config.collection_name,
            knowledge_role=preferred_role,
        )
    merged = _merge_candidates(general_candidates, preferred_role_candidates)
    reranked = rerank_candidates(learner_question, intent, merged, raw["reranking"])
    retained = [row for row in reranked if row["distance"] <= threshold][:final_top_k]
    return {
        "question": learner_question,
        "intent": intent,
        "preferred_role": preferred_role,
        "threshold": threshold,
        "final_top_k": final_top_k,
        "no_context": not retained,
        "evidence_sufficient": bool(retained),
        "results": _rank(retained),
        "diagnostics": {
            "general_top_k": general_top_k,
            "preferred_role_top_k": preferred_role_top_k,
            "general_candidate_count": len(general_candidates),
            "preferred_role_candidate_count": len(preferred_role_candidates),
            "merged_candidate_count": len(merged),
        },
    }
