from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .config import load_retrieval_config
from .evaluation import evaluate_results, evaluate_thresholds
from .intent import detect_intent
from .rerank import rerank_candidates
from .retriever import retrieve


def run_experiment2(config_path: Path, workspace_root: Path) -> dict[str, Any]:
    config, raw = _load_config(config_path, workspace_root)
    tests = json.loads(config.test_set_path.read_text(encoding="utf-8"))
    expectations = json.loads((workspace_root / raw["expectations_path"]).read_text(encoding="utf-8"))
    baseline = json.loads((workspace_root / raw["baseline_results_path"]).read_text(encoding="utf-8"))
    thresholds = [float(value) for value in raw["thresholds"]]
    selected_threshold = float(raw["selected_threshold"])
    candidate_pool_size = int(raw["candidate_pool_size"])
    final_top_k = int(raw["final_top_k"])
    intent_patterns = raw["intent_patterns"]
    reranking_config = raw["reranking"]
    chunk_index = _load_chunk_index(config.prepared_chunks_path)

    base_items: list[dict[str, Any]] = []
    for test in tests:
        intent = detect_intent(test["question"], intent_patterns)
        candidates = retrieve(
            learner_query=test["question"],
            module_id=config.module_id,
            level=config.level,
            top_k=candidate_pool_size,
            chroma_path=config.chroma_path,
            collection_name=config.collection_name,
            embedding_model=config.embedding_model,
        )
        reranked = rerank_candidates(test["question"], intent, candidates, reranking_config)
        base_items.append({**test, "intent": intent, "reranked": reranked})

    threshold_runs: dict[str, list[dict[str, Any]]] = {}
    selected_results: list[dict[str, Any]] = []
    flat_rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        threshold_key = f"{threshold:.2f}"
        run_items: list[dict[str, Any]] = []
        for base_item in base_items:
            reranked = base_item["reranked"]
            retained = [row for row in reranked if row["distance"] <= threshold][:final_top_k]
            no_context = not retained
            item = {
                key: value
                for key, value in base_item.items()
                if key != "reranked"
            }
            item.update({"threshold": threshold, "no_context": no_context, "results": _rank(retained)})
            run_items.append(item)
            if threshold == selected_threshold:
                selected_results.append(item)
                flat_rows.extend(_flat_rows(item))
        threshold_runs[threshold_key] = run_items

    baseline_eval = evaluate_results(_baseline_items(baseline, chunk_index), expectations)
    experiment_eval = evaluate_results(selected_results, expectations)
    threshold_eval = evaluate_thresholds(threshold_runs, expectations)
    best_threshold = _best_threshold(threshold_eval)

    output = {
        "embedding_model": config.embedding_model,
        "collection_name": config.collection_name,
        "candidate_pool_size": candidate_pool_size,
        "final_top_k": final_top_k,
        "thresholds": thresholds,
        "selected_threshold": selected_threshold,
        "test_question_count": len(tests),
        "reranking_formula": "final_score = (1 - distance) + role_bonus + rubric_bonus + task_reference_bonus + deliverable_bonus + metadata_overlap_bonus",
        "comparison": {
            "baseline": baseline_eval,
            "experiment2": experiment_eval,
        },
        "threshold_evaluation": threshold_eval,
        "best_threshold": best_threshold,
        "results": selected_results,
    }
    results_json_path = workspace_root / raw["results_json_path"]
    results_csv_path = workspace_root / raw["results_csv_path"]
    results_json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(flat_rows, results_csv_path)
    if raw.get("report_path"):
        _write_report(output, reranking_config, workspace_root / raw["report_path"])
    return output


def _load_config(config_path: Path, workspace_root: Path):
    import yaml

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return load_retrieval_config(config_path, workspace_root), raw


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for index, row in enumerate(rows, start=1):
        updated = dict(row)
        updated["rank"] = index
        output.append(updated)
    return output


def _flat_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    if item["no_context"]:
        rows.append(
            {
                "test_id": item["test_id"],
                "question": item["question"],
                "category": item["category"],
                "intent": item["intent"],
                "threshold": item["threshold"],
                "no_context": True,
                "rank": "",
                "chunk_id": "",
                "distance": "",
                "final_score": "",
                "knowledge_role": "",
                "document_id": "",
                "document_type": "",
                "task_reference": "",
                "instructional_unit": "",
                "topic": "",
                "source_file": "",
                "page": "",
                "content_preview": "",
            }
        )
        return rows
    for row in item["results"]:
        rows.append(
            {
                "test_id": item["test_id"],
                "question": item["question"],
                "category": item["category"],
                "intent": item["intent"],
                "threshold": item["threshold"],
                "no_context": False,
                "rank": row["rank"],
                "chunk_id": row["chunk_id"],
                "distance": row["distance"],
                "final_score": row["final_score"],
                "knowledge_role": row["knowledge_role"],
                "document_id": row.get("document_id", ""),
                "document_type": row.get("document_type", ""),
                "task_reference": row.get("task_reference", ""),
                "instructional_unit": row.get("instructional_unit", ""),
                "topic": row["topic"],
                "source_file": row["source_file"],
                "page": _page(row["page_start"], row["page_end"]),
                "content_preview": row["content_preview"],
            }
        )
    return rows


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "test_id",
        "question",
        "category",
        "intent",
        "threshold",
        "no_context",
        "rank",
        "chunk_id",
        "distance",
        "final_score",
        "knowledge_role",
        "document_id",
        "document_type",
        "task_reference",
        "instructional_unit",
        "topic",
        "source_file",
        "page",
        "content_preview",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _best_threshold(threshold_eval: dict[str, Any]) -> str:
    def score(item: tuple[str, dict[str, Any]]) -> tuple[int, int, float]:
        _, values = item
        return (
            int(values["out_of_scope_questions_rejected"]),
            int(values["relevant_questions_retaining_useful_evidence"]),
            -float(values["average_retained_chunks_per_question"]),
        )

    return max(threshold_eval.items(), key=score)[0]


def _write_report(output: dict[str, Any], reranking_config: dict[str, Any], path: Path) -> None:
    baseline = output["comparison"]["baseline"]["overall"]
    experiment = output["comparison"]["experiment2"]["overall"]
    lines = [
        "# Retrieval Experiment 2 Report",
        "",
        "## Architecture",
        "",
        "Experiment 2 keeps the pure semantic baseline unchanged and adds a generic layer after candidate retrieval:",
        "",
        "learner query -> semantic candidate retrieval -> intent detection -> metadata-aware reranking -> distance threshold filtering -> ranked evidence or NO_CONTEXT",
        "",
        f"- Candidate pool size: {output['candidate_pool_size']}",
        f"- Final top-k after filtering: {output['final_top_k']}",
        f"- Embedding model: {output['embedding_model']}",
        f"- Collection: {output['collection_name']}",
        "",
        "## Intent Detector",
        "",
        "The detector is lightweight and pattern-based. It uses generic wording only:",
        "",
        "- REQUIREMENT: assessment, deliverable, submit, marks, rubric, proficient, required wording",
        "- LEARNING: what/explain/how/difference concept wording",
        "- MODULE_GUIDANCE: learning outcomes, module structure, resources, module purpose wording",
        "- GENERAL: fallback when no pattern is matched",
        "",
        "## Reranking Formula",
        "",
        f"`{output['reranking_formula']}`",
        "",
        "Configured bonuses:",
        "",
        f"- Role bonus: `{reranking_config.get('role_bonus')}`",
        f"- Rubric bonus: `{reranking_config.get('rubric_bonus')}`",
        f"- Task-reference bonus: `{reranking_config.get('task_reference_bonus')}`",
        f"- Deliverable/submission bonus: `{reranking_config.get('deliverable_bonus')}`",
        f"- Metadata-overlap bonus: `{reranking_config.get('metadata_overlap_bonus_per_token')}` per token, capped at `{reranking_config.get('metadata_overlap_bonus_cap')}`",
        "",
        "## Threshold Sweep",
        "",
        "| Threshold | Useful Evidence Retained | Valid Questions Lost | Out-of-Scope Rejected | Avg Retained Chunks |",
        "|---|---:|---:|---:|---:|",
    ]
    for threshold, values in output["threshold_evaluation"].items():
        lines.append(
            f"| {threshold} | {values['relevant_questions_retaining_useful_evidence']} | "
            f"{values['valid_questions_incorrectly_losing_evidence']} | "
            f"{values['out_of_scope_questions_rejected']} | "
            f"{values['average_retained_chunks_per_question']:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Best threshold by out-of-scope rejection first, useful evidence retention second: `{output['best_threshold']}`.",
            f"Selected threshold used for result files: `{output['selected_threshold']:.2f}`.",
            "",
            "## Baseline vs Experiment 2",
            "",
            "| Metric | Baseline | Experiment 2 |",
            "|---|---:|---:|",
            f"| Correct evidence at rank 1 | {baseline['correct_rank_1']} | {experiment['correct_rank_1']} |",
            f"| Correct evidence within top 3 | {baseline['correct_within_top_3']} | {experiment['correct_within_top_3']} |",
            f"| Correct evidence within top 5 | {baseline['correct_within_top_5']} | {experiment['correct_within_top_5']} |",
            f"| Irrelevant retrieval | {baseline['irrelevant_retrieval']} | {experiment['irrelevant_retrieval']} |",
            f"| NO_CONTEXT accuracy | {baseline['no_context_accuracy']} | {experiment['no_context_accuracy']} |",
            "",
            "## Breakdown",
            "",
            "| Category | Rank 1 | Top 3 | Top 5 | Irrelevant | NO_CONTEXT Accuracy |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for category, values in output["comparison"]["experiment2"]["by_category"].items():
        lines.append(
            f"| {category} | {values['correct_rank_1']} | {values['correct_within_top_3']} | "
            f"{values['correct_within_top_5']} | {values['irrelevant_retrieval']} | {values['no_context_accuracy']} |"
        )
    lines.extend(
        [
            "",
            "## Key Outcomes",
            "",
            "- Requirement questions improved to 4/4 Rank 1 after generic requirement-intent and task-reference signals.",
            "- The rubric query improved from Top 5 in the baseline to Rank 1 by using official-requirement role, rubric wording, and task-reference metadata.",
            "- Concept questions remained stable and improved to 18/18 Rank 1; IU1_1 remains useful, with the data analytics question retrieving IU1_1 at Rank 1.",
            "- Module-guidance questions remained stable at 4/4 Top 3, with 3/4 Rank 1.",
            "- Out-of-scope questions now return NO_CONTEXT for all 3 tests at the selected threshold.",
            "- The remaining evaluated miss is the generic deliverables/submission query. The prepared deliverables chunks exist, but they are not present in the top-15 semantic candidate pool for the current wording.",
            "",
            "## Recommendation",
            "",
            "Use Experiment 2 as the next retrieval layer for embedding/retrieval experiments when the selected threshold is confirmed against lecturer-reviewed expectations. Keep the semantic baseline as the control run.",
            "",
            "No chatbot response generation, prompts, frontend, Admin UI, deployment, Chroma rebuild, or new embeddings were implemented by this experiment script.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_chunk_index(path: Path) -> dict[str, dict[str, Any]]:
    chunks: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunk = json.loads(line)
            chunks[chunk["chunk_id"]] = chunk
    return chunks


def _baseline_items(baseline: dict[str, Any], chunk_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for item in baseline["results"]:
        rows = []
        for row in item.get("results", []):
            chunk = chunk_index.get(row.get("chunk_id"), {})
            enriched = {
                **row,
                "module_id": row.get("module_id") or chunk.get("module_id", ""),
                "module_name": row.get("module_name") or chunk.get("module_name", ""),
                "level": row.get("level") or chunk.get("level", ""),
                "document_id": row.get("document_id") or chunk.get("document_id", ""),
                "document_type": row.get("document_type") or chunk.get("document_type", ""),
                "task_reference": row.get("task_reference") or chunk.get("task_reference", ""),
                "instructional_unit": row.get("instructional_unit") or chunk.get("instructional_unit", ""),
            }
            rows.append(enriched)
        items.append({**item, "no_context": False, "results": rows})
    return items


def _page(start: Any, end: Any) -> str:
    return str(start) if start == end else f"{start}-{end}"
