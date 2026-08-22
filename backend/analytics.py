from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return None if denominator == 0 else round(numerator / denominator, 3)


def weighted_kappa(first: list[float], second: list[float], categories: int = 5) -> float | None:
    if len(first) < 2 or len(first) != len(second):
        return None
    def category(value: float) -> int:
        return max(0, min(categories - 1, round(value * (categories - 1))))
    a = [category(value) for value in first]
    b = [category(value) for value in second]
    n = len(a)
    observed = 0.0
    expected = 0.0
    counts_a = [a.count(i) / n for i in range(categories)]
    counts_b = [b.count(i) / n for i in range(categories)]
    for x, y in zip(a, b):
        observed += ((x - y) / (categories - 1)) ** 2 / n
    for i in range(categories):
        for j in range(categories):
            expected += counts_a[i] * counts_b[j] * ((i - j) / (categories - 1)) ** 2
    return None if expected == 0 else round(1 - observed / expected, 3)


def review_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_answer: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_answer[int(record["answer_id"])].append(record)
    paired = [items for items in by_answer.values() if len(items) >= 2]
    first = [items[0]["score"] / items[0]["max_score"] for items in paired]
    second = [items[1]["score"] / items[1]["max_score"] for items in paired]
    model = []
    human = []
    for items in by_answer.values():
        model.append(items[0]["model_score"] / items[0]["max_score"])
        human.append(sum(item["score"] for item in items) / len(items) / items[0]["max_score"])
    disagreements = sum(abs(a - b) >= 0.2 for a, b in zip(first, second))
    return {
        "reviewed_answers": len(by_answer),
        "double_reviewed_answers": len(paired),
        "model_human_pearson": pearson(model, human),
        "inter_rater_pearson": pearson(first, second),
        "quadratic_weighted_kappa": weighted_kappa(first, second),
        "major_disagreements": disagreements,
        "note": "样本少于30时仅用于过程监测，不应作为正式效度结论。",
    }
