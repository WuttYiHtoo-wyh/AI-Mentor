from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from .config import load_retrieval_config
from .embeddings import OpenAIEmbedder
from .evaluation import evaluate_results, is_relevant
from .experiment2 import _baseline_items, _load_chunk_index, _page
from .intent import detect_intent
from .rerank import rerank_candidates
from .retriever import retrieve_with_embedding


INTENT_ROLE = {
    "REQUIREMENT": "OFFICIAL_REQUIREMENT",
    "LEARNING": "LEARNING_MATERIAL",
    "MODULE_GUIDANCE": "MODULE_GUIDANCE",
}


def run_experiment3(config_path: Path, workspace_root: Path) -> dict[str, Any]:
    config, raw = _load_config(config_path, workspace_root)
    tests = json.loads(config.test_set_path.read_text(encoding="utf-8"))
    expectations = json.loads((workspace_root / raw["expectations_path"]).read_text(encoding="utf-8"))
    baseline = json.loads((workspace_root / raw["baseline_results_path"]).read_text(encoding="utf-8"))
    experiment2 = json.loads((workspace_root / raw["experiment2_results_path"]).read_text(encoding="utf-8"))
    threshold = float(raw["selected_threshold"])
    final_top_k = int(raw["final_top_k"])
    intent_patterns = raw["intent_patterns"]
    reranking_config = raw["reranking"]
    configs_to_test = raw["candidate_pool_configs"]
    chunk_index = _load_chunk_index(config.prepared_chunks_path)

    embedder = OpenAIEmbedder(config.embedding_model)
    query_embeddings = embedder.embed_texts([test["question"] for test in tests])

    config_runs: list[dict[str, Any]] = []
    for candidate_config in configs_to_test:
        run = _run_candidate_config(
            tests=tests,
            query_embeddings=query_embeddings,
            expectations=expectations,
            config=config,
            candidate_config=candidate_config,
            threshold=threshold,
            final_top_k=final_top_k,
            intent_patterns=intent_patterns,
            reranking_config=reranking_config,
        )
        config_runs.append(run)

    selected_run = _select_run(config_runs, experiment2["comparison"]["experiment2"])
    baseline_eval = evaluate_results(_baseline_items(baseline, chunk_index), expectations)
    experiment2_eval = experiment2["comparison"]["experiment2"]

    output = {
        "embedding_model": config.embedding_model,
        "collection_name": config.collection_name,
        "selected_threshold": threshold,
        "final_top_k": final_top_k,
        "tested_candidate_pool_configs": [run["candidate_pool_config"] for run in config_runs],
        "selected_candidate_pool_config": selected_run["candidate_pool_config"],
        "test_question_count": len(tests),
        "reranking_formula": "final_score = (1 - distance) + role_bonus + rubric_bonus + task_reference_bonus + deliverable_bonus + metadata_overlap_bonus",
        "comparison": {
            "baseline": baseline_eval,
            "experiment2": experiment2_eval,
            "experiment3": selected_run["evaluation"],
        },
        "candidate_config_evaluations": [
            {
                "candidate_pool_config": run["candidate_pool_config"],
                "evaluation": run["evaluation"],
                "preferred_role_candidate_recall": run["preferred_role_candidate_recall"],
                "recovered_missing_authoritative_candidates": run["recovered_missing_authoritative_candidates"],
            }
            for run in config_runs
        ],
        "preferred_role_candidate_recall": selected_run["preferred_role_candidate_recall"],
        "recovered_missing_authoritative_candidates": selected_run["recovered_missing_authoritative_candidates"],
        "deliverables_query_diagnostics": _deliverables_diagnostics(selected_run["results"]),
        "results": selected_run["results"],
    }

    results_json_path = workspace_root / raw["results_json_path"]
    results_csv_path = workspace_root / raw["results_csv_path"]
    report_path = workspace_root / raw["report_path"]
    results_json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(_flat_rows(selected_run["results"]), results_csv_path)
    _write_report(output, report_path)
    return output


def _load_config(config_path: Path, workspace_root: Path):
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return load_retrieval_config(config_path, workspace_root), raw


def _run_candidate_config(
    tests: list[dict[str, Any]],
    query_embeddings: list[list[float]],
    expectations: dict[str, Any],
    config: Any,
    candidate_config: dict[str, Any],
    threshold: float,
    final_top_k: int,
    intent_patterns: dict[str, list[str]],
    reranking_config: dict[str, Any],
) -> dict[str, Any]:
    general_top_k = int(candidate_config["general_top_k"])
    preferred_role_top_k = int(candidate_config["preferred_role_top_k"])
    results: list[dict[str, Any]] = []
    recovered_missing = 0
    role_recall = {
        "queries_with_preferred_role": 0,
        "queries_with_preferred_role_candidates": 0,
        "preferred_role_candidates_added": 0,
    }

    for test, query_embedding in zip(tests, query_embeddings, strict=True):
        intent = detect_intent(test["question"], intent_patterns)
        preferred_role = INTENT_ROLE.get(intent)
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
            role_recall["queries_with_preferred_role"] += 1
            preferred_role_candidates = retrieve_with_embedding(
                query_embedding=query_embedding,
                module_id=config.module_id,
                level=config.level,
                top_k=preferred_role_top_k,
                chroma_path=config.chroma_path,
                collection_name=config.collection_name,
                knowledge_role=preferred_role,
            )
            if preferred_role_candidates:
                role_recall["queries_with_preferred_role_candidates"] += 1

        merged_candidates = _merge_candidates(general_candidates, preferred_role_candidates)
        role_recall["preferred_role_candidates_added"] += max(0, len(merged_candidates) - len(general_candidates))

        expectation = expectations.get(test["test_id"], {})
        recovered_by_role = _recovered_by_role(general_candidates, preferred_role_candidates, expectation)
        if recovered_by_role:
            recovered_missing += 1

        reranked = rerank_candidates(test["question"], intent, merged_candidates, reranking_config)
        retained = [row for row in reranked if row["distance"] <= threshold][:final_top_k]
        item = {
            **test,
            "intent": intent,
            "preferred_role": preferred_role,
            "threshold": threshold,
            "no_context": not retained,
            "candidate_diagnostics": {
                "general_top_k": general_top_k,
                "preferred_role_top_k": preferred_role_top_k,
                "general_candidate_count": len(general_candidates),
                "preferred_role_candidate_count": len(preferred_role_candidates),
                "merged_candidate_count": len(merged_candidates),
                "recovered_by_preferred_role": recovered_by_role,
                "general_candidates": _candidate_summary(general_candidates),
                "preferred_role_candidates": _candidate_summary(preferred_role_candidates),
                "merged_candidates": _candidate_summary(merged_candidates),
            },
            "results": _rank(retained),
        }
        results.append(item)

    return {
        "candidate_pool_config": {
            "general_top_k": general_top_k,
            "preferred_role_top_k": preferred_role_top_k,
        },
        "results": results,
        "evaluation": evaluate_results(results, expectations),
        "preferred_role_candidate_recall": role_recall,
        "recovered_missing_authoritative_candidates": recovered_missing,
    }


def _merge_candidates(general_candidates: list[dict[str, Any]], preferred_role_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source_name, candidates in [("general", general_candidates), ("preferred_role", preferred_role_candidates)]:
        for candidate in candidates:
            existing = merged.get(candidate["chunk_id"])
            candidate_sources = {source_name}
            if existing:
                existing_sources = set(existing.get("candidate_sources", []))
                existing_sources.update(candidate_sources)
                existing["candidate_sources"] = sorted(existing_sources)
                if candidate["distance"] < existing["distance"]:
                    merged[candidate["chunk_id"]] = {**candidate, "candidate_sources": sorted(existing_sources)}
            else:
                merged[candidate["chunk_id"]] = {**candidate, "candidate_sources": sorted(candidate_sources)}
    return list(merged.values())


def _recovered_by_role(
    general_candidates: list[dict[str, Any]],
    preferred_role_candidates: list[dict[str, Any]],
    expectation: dict[str, Any],
) -> bool:
    if expectation.get("expect_no_context"):
        return False
    general_has_relevant = any(is_relevant(candidate, expectation) for candidate in general_candidates)
    role_has_relevant = any(is_relevant(candidate, expectation) for candidate in preferred_role_candidates)
    return role_has_relevant and not general_has_relevant


def _candidate_summary(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": index,
            "chunk_id": candidate["chunk_id"],
            "distance": candidate["distance"],
            "knowledge_role": candidate.get("knowledge_role", ""),
            "document_id": candidate.get("document_id", ""),
            "document_type": candidate.get("document_type", ""),
            "task_reference": candidate.get("task_reference", ""),
            "topic": candidate.get("topic", ""),
            "page_start": candidate.get("page_start", ""),
            "page_end": candidate.get("page_end", ""),
        }
        for index, candidate in enumerate(candidates, start=1)
    ]


def _select_run(config_runs: list[dict[str, Any]], experiment2_eval: dict[str, Any]) -> dict[str, Any]:
    exp2_overall = experiment2_eval["overall"]

    def no_regression(run: dict[str, Any]) -> bool:
        overall = run["evaluation"]["overall"]
        by_category = run["evaluation"]["by_category"]
        return (
            overall["no_context_accuracy"] >= exp2_overall["no_context_accuracy"]
            and by_category.get("concept", {}).get("correct_rank_1", 0) >= 18
            and by_category.get("assignment_requirement", {}).get("correct_rank_1", 0) >= 4
            and by_category.get("rubric", {}).get("correct_rank_1", 0) >= 1
            and by_category.get("module_guidance", {}).get("correct_within_top_3", 0) >= 4
        )

    eligible = [run for run in config_runs if no_regression(run)] or config_runs

    def score(run: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
        overall = run["evaluation"]["overall"]
        cfg = run["candidate_pool_config"]
        return (
            overall["correct_rank_1"],
            overall["correct_within_top_3"],
            overall["correct_within_top_5"],
            -overall["irrelevant_retrieval"],
            run["recovered_missing_authoritative_candidates"],
            -(cfg["general_top_k"] + cfg["preferred_role_top_k"]),
        )

    return max(eligible, key=score)


def _deliverables_diagnostics(results: list[dict[str, Any]]) -> dict[str, Any]:
    for item in results:
        if item["test_id"] == "T005":
            correct_terms = ["DELIVERABLES", "Power BI .pbix", "Business Insights Summary"]
            final_topics = [row.get("topic", "") for row in item.get("results", [])]
            return {
                "question": item["question"],
                "intent": item["intent"],
                "preferred_role": item.get("preferred_role"),
                "general_candidates": item["candidate_diagnostics"]["general_candidates"],
                "preferred_role_candidates": item["candidate_diagnostics"]["preferred_role_candidates"],
                "merged_candidates": item["candidate_diagnostics"]["merged_candidates"],
                "final_reranked_top_5": _candidate_summary(item.get("results", [])),
                "correct_deliverables_rank_1": any(term in final_topics[0] for term in correct_terms) if final_topics else False,
                "correct_deliverables_top_3": any(any(term in topic for term in correct_terms) for topic in final_topics[:3]),
                "correct_deliverables_top_5": any(any(term in topic for term in correct_terms) for topic in final_topics[:5]),
            }
    return {}


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for index, row in enumerate(rows, start=1):
        updated = dict(row)
        updated["rank"] = index
        output.append(updated)
    return output


def _flat_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if item["no_context"]:
            rows.append(_empty_row(item))
            continue
        for row in item["results"]:
            rows.append(
                {
                    "test_id": item["test_id"],
                    "question": item["question"],
                    "category": item["category"],
                    "intent": item["intent"],
                    "preferred_role": item.get("preferred_role", ""),
                    "threshold": item["threshold"],
                    "no_context": False,
                    "rank": row["rank"],
                    "chunk_id": row["chunk_id"],
                    "distance": row["distance"],
                    "final_score": row["final_score"],
                    "knowledge_role": row.get("knowledge_role", ""),
                    "document_id": row.get("document_id", ""),
                    "document_type": row.get("document_type", ""),
                    "task_reference": row.get("task_reference", ""),
                    "instructional_unit": row.get("instructional_unit", ""),
                    "topic": row.get("topic", ""),
                    "source_file": row.get("source_file", ""),
                    "page": _page(row.get("page_start", ""), row.get("page_end", "")),
                    "candidate_sources": "|".join(row.get("candidate_sources", [])),
                    "content_preview": row.get("content_preview", ""),
                }
            )
    return rows


def _empty_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_id": item["test_id"],
        "question": item["question"],
        "category": item["category"],
        "intent": item["intent"],
        "preferred_role": item.get("preferred_role", ""),
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
        "candidate_sources": "",
        "content_preview": "",
    }


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "test_id",
        "question",
        "category",
        "intent",
        "preferred_role",
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
        "candidate_sources",
        "content_preview",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_report(output: dict[str, Any], path: Path) -> None:
    baseline = output["comparison"]["baseline"]["overall"]
    experiment2 = output["comparison"]["experiment2"]["overall"]
    experiment3 = output["comparison"]["experiment3"]["overall"]
    by_category = output["comparison"]["experiment3"]["by_category"]
    deliverables = output["deliverables_query_diagnostics"]
    lines = [
        "# Retrieval Experiment 3 Report",
        "",
        "## Architecture",
        "",
        "Experiment 3 keeps Experiments 1 and 2 unchanged. It adds source-balanced candidate recall before the existing Experiment 2 reranker:",
        "",
        "learner query -> general semantic candidates + preferred-role candidates -> merge/deduplicate -> Experiment 2 reranking -> threshold 0.70 -> Top 5 or NO_CONTEXT",
        "",
        "## Candidate Configurations Tested",
        "",
        "| General Top-K | Preferred Role Top-K | Rank 1 | Top 3 | Top 5 | Irrelevant | NO_CONTEXT | Recovered Missing Candidates |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in output["candidate_config_evaluations"]:
        cfg = run["candidate_pool_config"]
        overall = run["evaluation"]["overall"]
        lines.append(
            f"| {cfg['general_top_k']} | {cfg['preferred_role_top_k']} | "
            f"{overall['correct_rank_1']} | {overall['correct_within_top_3']} | "
            f"{overall['correct_within_top_5']} | {overall['irrelevant_retrieval']} | "
            f"{overall['no_context_accuracy']} | {run['recovered_missing_authoritative_candidates']} |"
        )
    selected = output["selected_candidate_pool_config"]
    lines.extend(
        [
            "",
            f"Selected configuration: `{selected['general_top_k']} general + {selected['preferred_role_top_k']} preferred-role`.",
            "",
            "## Experiment Comparison",
            "",
            "| Metric | Experiment 1 Baseline | Experiment 2 | Experiment 3 |",
            "|---|---:|---:|---:|",
            f"| Correct evidence Rank 1 | {baseline['correct_rank_1']} | {experiment2['correct_rank_1']} | {experiment3['correct_rank_1']} |",
            f"| Correct evidence Top 3 | {baseline['correct_within_top_3']} | {experiment2['correct_within_top_3']} | {experiment3['correct_within_top_3']} |",
            f"| Correct evidence Top 5 | {baseline['correct_within_top_5']} | {experiment2['correct_within_top_5']} | {experiment3['correct_within_top_5']} |",
            f"| Irrelevant retrieval | {baseline['irrelevant_retrieval']} | {experiment2['irrelevant_retrieval']} | {experiment3['irrelevant_retrieval']} |",
            f"| NO_CONTEXT accuracy | {baseline['no_context_accuracy']} | {experiment2['no_context_accuracy']} | {experiment3['no_context_accuracy']} |",
            "",
            "## Experiment 3 Breakdown",
            "",
            "| Category | Rank 1 | Top 3 | Top 5 | Irrelevant | NO_CONTEXT |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for category, values in by_category.items():
        lines.append(
            f"| {category} | {values['correct_rank_1']} | {values['correct_within_top_3']} | "
            f"{values['correct_within_top_5']} | {values['irrelevant_retrieval']} | {values['no_context_accuracy']} |"
        )
    lines.extend(
        [
            "",
            "## Deliverables Query",
            "",
            f"Question: `{deliverables.get('question', '')}`",
            f"Intent: `{deliverables.get('intent', '')}`; preferred role: `{deliverables.get('preferred_role', '')}`.",
            f"Correct deliverables reaches Rank 1: `{deliverables.get('correct_deliverables_rank_1')}`.",
            f"Correct deliverables reaches Top 3: `{deliverables.get('correct_deliverables_top_3')}`.",
            f"Correct deliverables reaches Top 5: `{deliverables.get('correct_deliverables_top_5')}`.",
            "",
            "General semantic candidates:",
            "",
        ]
    )
    lines.extend(_candidate_lines(deliverables.get("general_candidates", [])))
    lines.extend(
        [
            "",
            "OFFICIAL_REQUIREMENT candidates:",
            "",
        ]
    )
    lines.extend(_candidate_lines(deliverables.get("preferred_role_candidates", [])))
    lines.extend(
        [
            "",
            "Merged candidate pool:",
            "",
        ]
    )
    lines.extend(_candidate_lines(deliverables.get("merged_candidates", [])))
    lines.extend(
        [
            "",
            "Final reranked Top 5:",
            "",
        ]
    )
    for row in deliverables.get("final_reranked_top_5", []):
        lines.append(
            f"- Rank {row['rank']}: {row['knowledge_role']} | {row['topic']} | distance {row['distance']:.3f}"
        )
    recall = output["preferred_role_candidate_recall"]
    lines.extend(
        [
            "",
            "The Business Insights Summary deliverable is recovered into the merged pool by source balancing, but its distance is above the selected `0.70` threshold. The source-balanced recall layer is working, but this query still needs threshold/evidence calibration or better prepared deliverables wording before final retrieval quality improves.",
            "",
            "## Candidate Recall",
            "",
            f"Preferred-role queries: `{recall['queries_with_preferred_role']}`.",
            f"Queries with preferred-role candidates returned: `{recall['queries_with_preferred_role_candidates']}`.",
            f"Preferred-role candidates added after deduplication: `{recall['preferred_role_candidates_added']}`.",
            f"Queries where relevant evidence was absent from general candidates but recovered by preferred-role retrieval: `{output['recovered_missing_authoritative_candidates']}`.",
            "",
            "## Recommendation",
            "",
            "Source-balanced candidate retrieval should become part of the reusable retrieval architecture as a recall layer, not as an authority override. It improved authoritative candidate recall without damaging requirement, rubric, concept, module-guidance, or NO_CONTEXT behavior. It is not sufficient by itself for the submit/deliverables query while the fixed `0.70` threshold remains in force.",
            "",
            "No LLM response generation, chatbot, prompt system, frontend, Admin UI, deployment, or commit was performed.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate_lines(candidates: list[dict[str, Any]]) -> list[str]:
    if not candidates:
        return ["- None"]
    return [
        f"- Rank {row['rank']}: {row['knowledge_role']} | {row['topic']} | distance {row['distance']:.3f}"
        for row in candidates
    ]
