from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml

from backend.admin.sqlite_repository import SQLiteAdminRepository
from backend.api.runtime_paths import ADMIN_DB_PATH

from .academic_integrity import pre_retrieval_academic_response
from .conversational import pre_retrieval_conversational_response
from .draft_review import (
    build_draft_review_retrieval_query,
    clarification_response,
    detect_draft_review,
    generate_draft_review_response,
    needs_draft_clarification,
)
from .evidence_policy import build_response_retrieval_query, order_evidence_for_response
from .experiment import _retrieval_question
from .generator import generate_mentor_response
from .retrieval import retrieve_experiment3_evidence
from .structural_reference import normalize_structural_references


@dataclass(frozen=True)
class ChatModuleConfig:
    module_id: str
    level: str
    module_name: str
    retrieval_config_path: Path
    response_model: str
    max_output_tokens: int


def load_chat_module_config(
    module_id: str,
    level: str,
    registry_path: Path,
    workspace_root: Path,
) -> ChatModuleConfig:
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    for module in registry.get("modules", []):
        if module.get("module_id") == module_id and module.get("level") == level:
            return ChatModuleConfig(
                module_id=module["module_id"],
                level=module["level"],
                module_name=module.get("module_name", module["module_id"]),
                retrieval_config_path=workspace_root / module["retrieval_config_path"],
                response_model=module["response_model"],
                max_output_tokens=int(module.get("max_output_tokens", 500)),
            )
    admin_config = _load_admin_published_module_config(module_id, level, workspace_root)
    if admin_config:
        return admin_config
    raise ValueError(f"No chat module configuration found for module_id={module_id!r}, level={level!r}")


def get_default_module(registry_path: Path) -> tuple[str, str]:
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    return registry["default_module_id"], registry["default_level"]


def _load_admin_published_module_config(module_id: str, level: str, workspace_root: Path) -> ChatModuleConfig | None:
    db_path = ADMIN_DB_PATH
    if not db_path.exists():
        return None
    repository = SQLiteAdminRepository(db_path)
    repository.initialize()
    version = repository.get_active_module_version(module_id, level)
    if not version or not version.retrieval_config_path:
        return None
    module = repository.get_module(version.module_id)
    if not module:
        return None
    return ChatModuleConfig(
        module_id=module.module_code,
        level=version.level,
        module_name=module.name,
        retrieval_config_path=Path(version.retrieval_config_path),
        response_model="gpt-4o-mini",
        max_output_tokens=500,
    )


def answer_chat_turn(
    message: str,
    module_config: ChatModuleConfig,
    workspace_root: Path,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    clean_message = message.strip()
    if not clean_message:
        raise ValueError("Message must not be empty.")

    recent_history = _sanitize_history(history or [])
    normalized_message = normalize_structural_references(clean_message)
    conversational_response = pre_retrieval_conversational_response(normalized_message)
    if conversational_response:
        return {
            "answer": conversational_response["answer"],
            "sources": conversational_response["source_references"],
            "conversation_context_used": False,
            "module_id": module_config.module_id,
            "level": module_config.level,
            "module_name": module_config.module_name,
            "no_context": False,
            "detected_behavior": "CONVERSATIONAL",
            "detected_task_or_topic": None,
        }

    draft_review = detect_draft_review(normalized_message, recent_history)
    academic_response = pre_retrieval_academic_response(normalized_message, allow_draft_review=bool(draft_review))
    if academic_response:
        return {
            "answer": academic_response["answer"],
            "sources": academic_response["source_references"],
            "conversation_context_used": bool(recent_history),
            "module_id": module_config.module_id,
            "level": module_config.level,
            "module_name": module_config.module_name,
            "no_context": False,
        }

    if _needs_rubric_clarification(normalized_message):
        answer = "Which task or assessment area would you like me to explain the rubric for?"
        return {
            "answer": answer,
            "sources": [],
            "conversation_context_used": bool(recent_history),
            "module_id": module_config.module_id,
            "level": module_config.level,
            "module_name": module_config.module_name,
            "no_context": False,
            "detected_behavior": "RUBRIC_CLARIFICATION",
            "detected_task_or_topic": None,
        }

    if draft_review:
        if needs_draft_clarification(draft_review):
            response = clarification_response(draft_review)
            return {
                "answer": response["answer"],
                "sources": response["source_references"],
                "conversation_context_used": bool(recent_history),
                "module_id": module_config.module_id,
                "level": module_config.level,
                "module_name": module_config.module_name,
                "no_context": False,
                "detected_behavior": response["detected_behavior"],
                "detected_task_or_topic": response["detected_task_or_topic"],
            }
        retrieval_query = build_draft_review_retrieval_query(draft_review)
        retrieval = retrieve_experiment3_evidence(
            learner_question=retrieval_query,
            retrieval_config_path=module_config.retrieval_config_path,
            workspace_root=workspace_root,
        )
        retrieval = _enrich_with_prepared_content(retrieval, module_config.retrieval_config_path, workspace_root)
        retrieval["question"] = clean_message
        retrieval["retrieval_query"] = retrieval_query
        retrieval = order_evidence_for_response(retrieval_query, retrieval)
        response = generate_draft_review_response(
            context=draft_review,
            retrieval=retrieval,
            model=module_config.response_model,
            max_output_tokens=max(module_config.max_output_tokens, 700),
        )
        return {
            "answer": response["answer"],
            "sources": response["source_references"][:2],
            "conversation_context_used": bool(recent_history),
            "module_id": module_config.module_id,
            "level": module_config.level,
            "module_name": module_config.module_name,
            "no_context": bool(retrieval.get("no_context")),
            "detected_behavior": response["detected_behavior"],
            "detected_task_or_topic": response["detected_task_or_topic"],
        }

    contextual_question = _retrieval_question(normalized_message, recent_history)
    retrieval_query = build_response_retrieval_query(contextual_question)
    retrieval = retrieve_experiment3_evidence(
        learner_question=retrieval_query,
        retrieval_config_path=module_config.retrieval_config_path,
        workspace_root=workspace_root,
    )
    retrieval = _enrich_with_prepared_content(retrieval, module_config.retrieval_config_path, workspace_root)
    retrieval["question"] = clean_message
    retrieval["retrieval_query"] = retrieval_query
    retrieval = order_evidence_for_response(normalized_message, retrieval)

    response = generate_mentor_response(
        learner_question=normalized_message,
        retrieval=retrieval,
        model=module_config.response_model,
        conversation_history=recent_history,
        max_output_tokens=module_config.max_output_tokens,
    )
    return {
        "answer": response["answer"],
        "sources": response["source_references"][:2],
        "conversation_context_used": bool(recent_history),
        "module_id": module_config.module_id,
        "level": module_config.level,
        "module_name": module_config.module_name,
        "no_context": bool(retrieval.get("no_context")),
        "detected_behavior": "NORMAL",
        "detected_task_or_topic": retrieval.get("evidence_policy", {}).get("task_reference"),
    }


def debug_retrieve_chat_turn(
    message: str,
    module_config: ChatModuleConfig,
    workspace_root: Path,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    clean_message = message.strip()
    recent_history = _sanitize_history(history or [])
    normalized_message = normalize_structural_references(clean_message)
    conversational_response = pre_retrieval_conversational_response(normalized_message)
    if conversational_response:
        return {
            "question": clean_message,
            "normalized_message": normalized_message,
            "intent": "CONVERSATIONAL",
            "preferred_role": None,
            "no_context": False,
            "evidence_sufficient": False,
            "results": [],
            "retrieval_query": None,
            "detected_behavior": "CONVERSATIONAL",
            "detected_task_or_topic": None,
        }

    draft_review = detect_draft_review(normalized_message, recent_history)
    if _needs_rubric_clarification(normalized_message):
        return {
            "question": clean_message,
            "normalized_message": normalized_message,
            "intent": "RUBRIC_CLARIFICATION",
            "preferred_role": None,
            "no_context": False,
            "evidence_sufficient": False,
            "results": [],
            "retrieval_query": None,
            "detected_behavior": "RUBRIC_CLARIFICATION",
            "detected_task_or_topic": None,
        }
    if draft_review and needs_draft_clarification(draft_review):
        return {
            "question": clean_message,
            "normalized_message": normalized_message,
            "intent": "DRAFT_REVIEW",
            "preferred_role": None,
            "no_context": False,
            "evidence_sufficient": False,
            "results": [],
            "retrieval_query": None,
            "detected_behavior": "DRAFT_REVIEW_CLARIFICATION",
            "detected_task_or_topic": draft_review.task_reference or draft_review.topic_hint,
        }
    if draft_review:
        retrieval_query = build_draft_review_retrieval_query(draft_review)
        retrieval = retrieve_experiment3_evidence(
            learner_question=retrieval_query,
            retrieval_config_path=module_config.retrieval_config_path,
            workspace_root=workspace_root,
        )
        retrieval = _enrich_with_prepared_content(retrieval, module_config.retrieval_config_path, workspace_root)
        retrieval["question"] = clean_message
        retrieval["retrieval_query"] = retrieval_query
        retrieval["normalized_message"] = normalized_message
        retrieval = order_evidence_for_response(retrieval_query, retrieval)
        retrieval["detected_behavior"] = "DRAFT_REVIEW"
        retrieval["detected_task_or_topic"] = draft_review.task_reference or draft_review.topic_hint
        return retrieval

    contextual_question = _retrieval_question(normalized_message, recent_history)
    retrieval_query = build_response_retrieval_query(contextual_question)
    retrieval = retrieve_experiment3_evidence(
        learner_question=retrieval_query,
        retrieval_config_path=module_config.retrieval_config_path,
        workspace_root=workspace_root,
    )
    retrieval = _enrich_with_prepared_content(retrieval, module_config.retrieval_config_path, workspace_root)
    retrieval["question"] = clean_message
    retrieval["retrieval_query"] = retrieval_query
    retrieval["normalized_message"] = normalized_message
    retrieval = order_evidence_for_response(normalized_message, retrieval)
    retrieval["detected_behavior"] = "NORMAL"
    retrieval["detected_task_or_topic"] = retrieval.get("evidence_policy", {}).get("task_reference")
    return retrieval


def _sanitize_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    sanitized = []
    for turn in history[-8:]:
        role = turn.get("role", "")
        content = str(turn.get("content", "")).strip()
        if role not in {"learner", "mentor"} or not content:
            continue
        sanitized.append({"role": role, "content": content[:4000]})
    return sanitized[-6:]


def _enrich_with_prepared_content(
    retrieval: dict[str, Any],
    retrieval_config_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    prepared_path = _prepared_chunks_path(retrieval_config_path, workspace_root)
    if not prepared_path or not prepared_path.exists():
        return retrieval
    chunk_ids = {row.get("chunk_id") for row in retrieval.get("results", []) if row.get("chunk_id")}
    if not chunk_ids:
        return retrieval

    content_by_id: dict[str, str] = {}
    with prepared_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            chunk_id = row.get("chunk_id")
            if chunk_id in chunk_ids:
                content_by_id[chunk_id] = str(row.get("content", ""))
                if len(content_by_id) == len(chunk_ids):
                    break

    if not content_by_id:
        return retrieval
    updated = dict(retrieval)
    updated_rows = []
    for row in retrieval.get("results", []):
        enriched = dict(row)
        content = content_by_id.get(row.get("chunk_id"))
        if content:
            enriched["content"] = content
        updated_rows.append(enriched)
    updated["results"] = updated_rows
    return updated


def _prepared_chunks_path(retrieval_config_path: Path, workspace_root: Path) -> Path | None:
    raw = yaml.safe_load(retrieval_config_path.read_text(encoding="utf-8"))
    value = raw.get("prepared_chunks_path")
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else workspace_root / path


def _needs_rubric_clarification(message: str) -> bool:
    message_l = message.lower().strip()
    if "rubric" not in message_l:
        return False
    if "task" in message_l or "assessment area" in message_l or "criterion" in message_l:
        return False
    return len(message_l.split()) <= 8
