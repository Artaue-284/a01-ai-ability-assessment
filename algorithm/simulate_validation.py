from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path

from algorithm.adaptive_test import AdaptiveTestEngine, DIMENSIONS
from algorithm.level_scale import score_to_level_code
from question_bank.loader import assessment_readiness, load_all_questions


ROOT = Path(__file__).resolve().parent.parent
PROFILES = {
    "L1": 0.20,
    "L2": 0.50,
    "L3": 0.64,
    "L4": 0.82,
    "L5": 0.94,
}


def load_bank() -> list[dict]:
    return load_all_questions()


def expected_success(ability: float, difficulty: int) -> float:
    difficulty_point = {1: 0.28, 2: 0.55, 3: 0.76, 4: 0.88, 5: 0.95}[difficulty]
    return 1 / (1 + math.exp(-7 * (ability - difficulty_point)))


def score_to_level(score: float) -> str:
    return score_to_level_code(score)


def simulate(profile: str, run_number: int, bank: list[dict], target: int) -> dict:
    rng = random.Random(f"{profile}-{run_number}")
    ability = PROFILES[profile]
    engine = AdaptiveTestEngine(bank, seed=f"questions-{profile}-{run_number}", state=AdaptiveTestEngine.initial_state(target))
    difficulties = []
    while not engine.is_complete():
        question = engine.next_question()
        source = next(item for item in bank if item["id"] == question["id"])
        probability = expected_success(ability, int(source["difficulty"]))
        ratio = 1.0 if rng.random() < probability else 0.0
        if source["type"] == "single_choice":
            answer = source["answer"] if ratio else "__wrong__"
            open_score = None
        else:
            noisy_ratio = max(0.0, min(1.0, ability + rng.gauss(0, 0.09)))
            answer = "模拟开放回答"
            open_score = {"score": source["max_score"] * noisy_ratio, "model": "simulation"}
        engine.submit_answer(question["id"], answer, rng.uniform(12, 75), open_score)
        difficulties.append(int(source["difficulty"]))
    report = engine.build_report()
    return {
        "expected": profile,
        "predicted": score_to_level(report["overall_score"]),
        "score": report["overall_score"],
        "questions": report["question_count"],
        "mean_difficulty": statistics.mean(difficulties),
        "min_confidence": min(report["confidence"].values()),
    }


def run_validation(runs: int = 100, target: int = 18) -> dict:
    bank = load_bank()
    readiness = assessment_readiness(bank)
    if not readiness["ready"]:
        raise RuntimeError("题库尚未达到正式测评要求，不能生成算法有效性报告")
    rows = [simulate(profile, run, bank, target) for profile in PROFILES for run in range(runs)]
    summary = {}
    for profile in PROFILES:
        group = [row for row in rows if row["expected"] == profile]
        summary[profile] = {
            "runs": len(group),
            "mean_score": round(statistics.mean(row["score"] for row in group), 1),
            "score_sd": round(statistics.pstdev(row["score"] for row in group), 1),
            "mean_questions": round(statistics.mean(row["questions"] for row in group), 1),
            "mean_difficulty": round(statistics.mean(row["mean_difficulty"] for row in group), 2),
            "classification_accuracy": round(sum(row["predicted"] == profile for row in group) / len(group), 3),
            "predicted_levels": dict(Counter(row["predicted"] for row in group)),
        }
    return {
        "runs_per_profile": runs,
        "target_questions": target,
        "overall_classification_accuracy": round(sum(row["predicted"] == row["expected"] for row in rows) / len(rows), 3),
        "profiles": summary,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模拟五类能力用户，验证自适应测评稳定性")
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--target", type=int, default=18, choices=range(15, 26))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_validation(args.runs, args.target)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
