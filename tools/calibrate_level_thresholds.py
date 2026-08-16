from __future__ import annotations

import argparse
import bisect
import csv
import json
from collections import Counter
from pathlib import Path


LEVELS = ("L1", "L2", "L3", "L4", "L5")


def classify(score: float, thresholds: list[float]) -> str:
    for index, threshold in enumerate(thresholds):
        if score < threshold:
            return LEVELS[index]
    return LEVELS[-1]


def load_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = []
    for row in rows:
        result.append({
            "student_id": row["student_id"],
            "expected_level": row["expected_level"],
            "score": float(row["overall_score"]),
        })
    return sorted(result, key=lambda item: item["score"])


def calibrate(rows: list[dict], min_bin: int = 10, max_bin: int = 35) -> dict:
    """在标签匹配率优先的前提下寻找不等宽且人数不等的五级断点。"""
    count = len(rows)
    scores = [row["score"] for row in rows]
    prefix = [{level: 0 for level in LEVELS}]
    score_prefix = [0.0]
    square_prefix = [0.0]
    for row in rows:
        current = prefix[-1].copy()
        current[row["expected_level"]] += 1
        prefix.append(current)
        score_prefix.append(score_prefix[-1] + row["score"])
        square_prefix.append(square_prefix[-1] + row["score"] ** 2)

    def correct_in(start: int, end: int, level: str) -> int:
        return prefix[end][level] - prefix[start][level]

    def sse(start: int, end: int) -> float:
        size = end - start
        total = score_prefix[end] - score_prefix[start]
        squares = square_prefix[end] - square_prefix[start]
        return squares - total * total / size

    best = None
    first_range = range(min_bin, min(max_bin, count - min_bin * 4) + 1)
    for c1 in first_range:
        for c2 in range(c1 + min_bin, min(c1 + max_bin, count - min_bin * 3) + 1):
            for c3 in range(c2 + min_bin, min(c2 + max_bin, count - min_bin * 2) + 1):
                for c4 in range(c3 + min_bin, min(c3 + max_bin, count - min_bin) + 1):
                    cuts = [c1, c2, c3, c4]
                    thresholds = [round((rows[cut - 1]["score"] + rows[cut]["score"]) / 2, 1) for cut in cuts]
                    cuts = [bisect.bisect_left(scores, threshold) for threshold in thresholds]
                    sizes = [cuts[0], cuts[1] - cuts[0], cuts[2] - cuts[1], cuts[3] - cuts[2], count - cuts[3]]
                    if any(size < min_bin or size > max_bin for size in sizes) or len(set(sizes)) != 5:
                        continue
                    widths = [thresholds[0], *[thresholds[i] - thresholds[i - 1] for i in range(1, 4)], 100 - thresholds[-1]]
                    rounded_widths = [round(width, 1) for width in widths]
                    if min(widths) < 5 or len(set(rounded_widths)) != 5:
                        continue
                    boundaries = [0, *cuts, count]
                    correct = sum(correct_in(boundaries[i], boundaries[i + 1], LEVELS[i]) for i in range(5))
                    imbalance = sum((size - count / 5) ** 2 for size in sizes)
                    within_sse = sum(sse(boundaries[i], boundaries[i + 1]) for i in range(5))
                    key = (correct, -imbalance, -within_sse)
                    if best is None or key > best[0]:
                        best = (key, thresholds, rounded_widths, sizes)
    if best is None:
        raise RuntimeError("没有找到同时满足不等区间和不等人数约束的阈值")

    _, thresholds, widths, sizes = best
    predicted = [classify(row["score"], thresholds) for row in rows]
    confusion = {level: dict(Counter(
        prediction for row, prediction in zip(rows, predicted) if row["expected_level"] == level
    )) for level in LEVELS}
    correct = sum(row["expected_level"] == prediction for row, prediction in zip(rows, predicted))
    legacy = [50.0, 65.0, 80.0, 90.0]
    legacy_correct = sum(row["expected_level"] == classify(row["score"], legacy) for row in rows)
    return {
        "method": "supervised_cutpoint_search_with_non_equal_width_and_count_constraints",
        "evidence_scope": "synthetic_balanced_cohort",
        "sample_size": len(rows),
        "levels": list(LEVELS),
        "thresholds": thresholds,
        "intervals": [
            {"level": level, "lower": 0.0 if index == 0 else thresholds[index - 1],
             "upper": 100.0 if index == 4 else thresholds[index], "width": widths[index], "count": sizes[index]}
            for index, level in enumerate(LEVELS)
        ],
        "accuracy": round(correct / len(rows), 3),
        "legacy_accuracy": round(legacy_correct / len(rows), 3),
        "confusion": confusion,
        "constraints": {
            "pairwise_distinct_interval_widths": len(set(widths)) == 5,
            "pairwise_distinct_level_counts": len(set(sizes)) == 5,
            "minimum_level_count": min_bin,
            "maximum_level_count": max_bin,
        },
        "disclaimer": "阈值由100份仿真人工答题样本校准，只用于竞赛原型与模拟验证，不代表真人常模。",
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=root / "docs" / "synthetic_validation_100" / "synthetic_respondents.csv")
    args = parser.parse_args()
    print(json.dumps(calibrate(load_rows(args.input)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
