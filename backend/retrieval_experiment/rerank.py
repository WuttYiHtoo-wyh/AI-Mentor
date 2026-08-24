from __future__ import annotations

import re
from typing import Any


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "the",
    "to",
    "what",
    "why",
}


def rerank_candidates(
    query: str,
    intent: str,
    candidates: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    scored = []
    for candidate in candidates:
        semantic_score = float(candidate["similarity"])
        role_bonus = _role_bonus(intent, candidate["knowledge_role"], config)
        rubric_bonus = _rubric_bonus(query, candidate, config)
        task_bonus = _task_reference_bonus(query, candidate, config)
        deliverable_bonus = _deliverable_bonus(query, candidate, config)
        overlap_bonus = _metadata_overlap_bonus(query, candidate, config)
        final_score = semantic_score + role_bonus + rubric_bonus + task_bonus + deliverable_bonus + overlap_bonus
        scored.append(
            {
                **candidate,
                "semantic_score": semantic_score,
                "role_bonus": role_bonus,
                "rubric_bonus": rubric_bonus,
                "task_reference_bonus": task_bonus,
                "deliverable_bonus": deliverable_bonus,
                "metadata_overlap_bonus": overlap_bonus,
                "final_score": final_score,
            }
        )
    return sorted(scored, key=lambda row: (-row["final_score"], row["distance"]))


def _role_bonus(intent: str, role: str, config: dict[str, Any]) -> float:
    return float(config.get("role_bonus", {}).get(intent, {}).get(role, 0.0))


def _rubric_bonus(query: str, candidate: dict[str, Any], config: dict[str, Any]) -> float:
    query_l = query.lower()
    if not any(term in query_l for term in ["rubric", "proficient", "foundation", "failed", "marks"]):
        return 0.0
    haystack = " ".join([candidate.get("title", ""), candidate.get("topic", "")]).lower()
    if "rubric" in haystack:
        return float(config.get("rubric_bonus", 0.0))
    return 0.0


def _task_reference_bonus(query: str, candidate: dict[str, Any], config: dict[str, Any]) -> float:
    query_task = _task_reference(query)
    candidate_task = _task_reference(
        " ".join(
            [
                candidate.get("title", ""),
                candidate.get("topic", ""),
                str(candidate.get("task_reference") or ""),
            ]
        )
    )
    if query_task and candidate_task and query_task == candidate_task:
        return float(config.get("task_reference_bonus", 0.0))
    return 0.0


def _deliverable_bonus(query: str, candidate: dict[str, Any], config: dict[str, Any]) -> float:
    query_l = query.lower()
    if not any(term in query_l for term in ["submit", "submission", "deliverable", "turn in", "hand in"]):
        return 0.0
    haystack = " ".join([candidate.get("title", ""), candidate.get("topic", ""), candidate.get("content_preview", "")]).lower()
    if any(term in haystack for term in ["deliverable", "submit", "submission"]):
        return float(config.get("deliverable_bonus", 0.0))
    return 0.0


def _metadata_overlap_bonus(query: str, candidate: dict[str, Any], config: dict[str, Any]) -> float:
    query_tokens = _tokens(query)
    metadata_tokens = _tokens(
        " ".join(
            [
                candidate.get("title", ""),
                candidate.get("topic", ""),
                candidate.get("knowledge_role", ""),
                str(candidate.get("task_reference") or ""),
                str(candidate.get("instructional_unit") or ""),
            ]
        )
    )
    overlap = len(query_tokens & metadata_tokens)
    per_token = float(config.get("metadata_overlap_bonus_per_token", 0.0))
    cap = float(config.get("metadata_overlap_bonus_cap", 0.0))
    return min(cap, overlap * per_token)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in STOPWORDS and len(token) > 1}


def _task_reference(text: str) -> str | None:
    match = re.search(r"\btask\s+(\d+)\b", text.lower())
    return f"task {match.group(1)}" if match else None
