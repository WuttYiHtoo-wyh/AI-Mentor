from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def is_relevant(result: dict[str, Any], expectation: dict[str, Any]) -> bool:
    for expected in expectation.get("expected", []):
        if _matches(result, expected):
            return True
    return False


def evaluate_results(results: list[dict[str, Any]], expectations: dict[str, Any]) -> dict[str, Any]:
    metrics = _blank_metrics()
    by_category: dict[str, dict[str, int]] = defaultdict(_blank_metrics)
    for item in results:
        expectation = expectations.get(item["test_id"], {})
        category = item["category"]
        no_context = item.get("no_context", False)
        relevant_ranks = [
            row["rank"]
            for row in item.get("results", [])
            if is_relevant(row, expectation)
        ]
        _accumulate(metrics, expectation, no_context, relevant_ranks)
        _accumulate(by_category[category], expectation, no_context, relevant_ranks)
    return {
        "overall": dict(metrics),
        "by_category": {category: dict(values) for category, values in sorted(by_category.items())},
    }


def evaluate_thresholds(
    threshold_runs: dict[str, list[dict[str, Any]]],
    expectations: dict[str, Any],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for threshold, results in threshold_runs.items():
        retained_counts = [len(item.get("results", [])) for item in results]
        valid_items = [item for item in results if not expectations.get(item["test_id"], {}).get("expect_no_context")]
        out_items = [item for item in results if expectations.get(item["test_id"], {}).get("expect_no_context")]
        valid_lost = 0
        valid_retained = 0
        out_rejected = 0
        for item in valid_items:
            expectation = expectations[item["test_id"]]
            if any(is_relevant(row, expectation) for row in item.get("results", [])):
                valid_retained += 1
            else:
                valid_lost += 1
        for item in out_items:
            if item.get("no_context"):
                out_rejected += 1
        output[threshold] = {
            "relevant_questions_retaining_useful_evidence": valid_retained,
            "valid_questions_incorrectly_losing_evidence": valid_lost,
            "out_of_scope_questions_rejected": out_rejected,
            "average_retained_chunks_per_question": sum(retained_counts) / len(retained_counts) if retained_counts else 0,
        }
    return output


def _blank_metrics() -> Counter:
    return Counter(
        {
            "questions": 0,
            "correct_rank_1": 0,
            "correct_within_top_3": 0,
            "correct_within_top_5": 0,
            "irrelevant_retrieval": 0,
            "no_context_accuracy": 0,
        }
    )


def _accumulate(metrics: Counter, expectation: dict[str, Any], no_context: bool, relevant_ranks: list[int]) -> None:
    metrics["questions"] += 1
    if expectation.get("expect_no_context"):
        if no_context:
            metrics["no_context_accuracy"] += 1
        else:
            metrics["irrelevant_retrieval"] += 1
        return
    if relevant_ranks:
        if min(relevant_ranks) == 1:
            metrics["correct_rank_1"] += 1
        if min(relevant_ranks) <= 3:
            metrics["correct_within_top_3"] += 1
        if min(relevant_ranks) <= 5:
            metrics["correct_within_top_5"] += 1
    else:
        metrics["irrelevant_retrieval"] += 1


def _matches(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, value in expected.items():
        if key == "topic_contains":
            haystack = " ".join(
                [
                    str(result.get("topic", "")),
                    str(result.get("title", "")),
                    str(result.get("task_reference", "")),
                ]
            ).lower()
            if str(value).lower() not in haystack:
                return False
        elif str(result.get(key, "")) != str(value):
            return False
    return True
