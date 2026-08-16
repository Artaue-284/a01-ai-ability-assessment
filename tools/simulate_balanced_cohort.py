from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm.adaptive_test import AdaptiveTestEngine, DIMENSIONS
from algorithm.level_scale import score_to_level_code
from backend import database as db
from backend.analytics import pearson, review_metrics
from llm.scorer import LLMScorer
from question_bank.loader import assessment_readiness, load_all_questions


LEVEL_ABILITIES = {
    "L1": 0.28,
    "L2": 0.48,
    "L3": 0.65,
    "L4": 0.80,
    "L5": 0.92,
}
BACKGROUNDS = (
    "文史传播", "经管商科", "理工制造", "计算机", "设计艺术",
    "教育学", "医学健康", "公共管理", "高职技能", "跨专业",
)
PACE_PROFILES = {
    "快速型": 0.76,
    "稳健型": 1.00,
    "审慎型": 1.28,
}
DIMENSION_CLAUSES = {
    "basic": ["区分模型能力与边界", "说明数据和训练并不保证事实正确", "按任务选择合适的模型"],
    "prompt": ["明确目标和受众", "补充输入背景与约束", "规定输出格式并设置验收标准"],
    "tools": ["根据输入类型选择工具", "保留原始数据与操作记录", "用第二种方法核验关键结果"],
    "evaluation": ["核查来源、作者与日期", "交叉验证事实和统计口径", "记录错误并迭代改进"],
    "collaboration": ["划分人机职责", "设置人工确认节点", "异常时暂停、复核并升级"],
    "ethics": ["坚持最小必要原则", "取得授权并进行脱敏", "设置访问控制、保留期限和审计"],
}


def clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def success_probability(ability: float, difficulty: int) -> float:
    difficulty_point = {1: 0.30, 2: 0.56, 3: 0.76, 4: 0.88, 5: 0.95}[difficulty]
    return clip(1 / (1 + math.exp(-7 * (ability - difficulty_point))), 0.04, 0.98)


def score_level(score: float) -> str:
    return score_to_level_code(score)


def build_person(level: str, number: int, rng: random.Random) -> dict[str, Any]:
    base = LEVEL_ABILITIES[level]
    strengths = rng.sample(list(DIMENSIONS), 2)
    weaknesses = rng.sample([item for item in DIMENSIONS if item not in strengths], 2)
    dimension_abilities = {}
    for dimension in DIMENSIONS:
        offset = rng.uniform(-0.035, 0.035)
        if dimension in strengths:
            offset += rng.uniform(0.06, 0.11)
        if dimension in weaknesses:
            offset -= rng.uniform(0.06, 0.11)
        dimension_abilities[dimension] = round(clip(base + offset, 0.08, 0.98), 3)
    pace_name = rng.choice(list(PACE_PROFILES))
    return {
        "student_id": f"SYN-{number:03d}",
        "expected_level": level,
        "latent_ability": base,
        "background": rng.choice(BACKGROUNDS),
        "pace_profile": pace_name,
        "pace_multiplier": PACE_PROFILES[pace_name] * rng.uniform(0.90, 1.10),
        "carelessness": rng.uniform(0.015, 0.09),
        "dimension_abilities": dimension_abilities,
        "strengths": strengths,
        "weaknesses": weaknesses,
    }


def human_like_open_answer(question: dict[str, Any], person: dict[str, Any], rng: random.Random) -> tuple[str, float]:
    ability = person["dimension_abilities"][question["dimension"]]
    quality = clip(ability + rng.gauss(0, 0.075))
    clauses = list(DIMENSION_CLAUSES[question["dimension"]])
    rubric = [str(item) for item in question.get("rubric", [])]
    keywords = [str(item) for item in question.get("keywords", [])]
    coverage = max(1, min(len(clauses), round(1 + quality * (len(clauses) - 1))))
    selected = rng.sample(clauses, coverage)
    if rubric and quality >= 0.52:
        selected.append(rubric[min(len(rubric) - 1, int(quality * len(rubric))) - 1])
    keyword_count = min(len(keywords), max(0, round(quality * len(keywords))))
    if keyword_count:
        selected.append("重点包含" + "、".join(rng.sample(keywords, keyword_count)) + "。")
    if quality < 0.38:
        prefix = rng.choice(("我的理解是：", "我会先尝试：", "大致步骤是："))
    elif quality < 0.75:
        prefix = rng.choice(("我会按以下步骤处理：", "为了完成任务，我会：", "我的方案包括："))
    else:
        prefix = rng.choice(("我会把目标、执行、核验和风险控制串成闭环：", "完整方案如下：", "我会先界定责任边界，再执行并复核："))
    connectors = ("首先", "其次", "然后", "最后")
    body = "；".join(f"{connectors[index % len(connectors)]}{clause}" for index, clause in enumerate(selected))
    if quality > 0.82:
        body += "；最后保存输入、输出、核验结论和人工确认记录，便于复盘与审计"
    return prefix + body + "。", quality


def elapsed_seconds(question: dict[str, Any], person: dict[str, Any], rng: random.Random) -> float:
    base = 34 + 13 * int(question["difficulty"])
    if question["type"] != "single_choice":
        base *= 3.4
    ability = person["dimension_abilities"][question["dimension"]]
    duration = base * person["pace_multiplier"] * (1.18 - 0.28 * ability) * rng.uniform(0.72, 1.35)
    return round(max(8.0, min(620.0, duration)), 1)


def teacher_score(quality: float, max_score: float, reviewer: str, dimension: str, rng: random.Random) -> float:
    bias = 0.018 if reviewer == "模拟教师A" else -0.012
    if reviewer == "模拟教师B" and dimension == "ethics":
        bias -= 0.025
    noise = rng.gauss(0, 0.055 if reviewer == "模拟教师A" else 0.065)
    if rng.random() < 0.07:
        noise += rng.choice((-0.13, 0.13))
    raw = clip(quality + bias + noise) * max_score
    return round(raw * 2) / 2


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_simulation(output_dir: Path, per_level: int = 20, target_questions: int = 25, seed: int = 20260816) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    questions = load_all_questions()
    readiness = assessment_readiness(questions)
    if not readiness["ready"]:
        raise RuntimeError(readiness["message"])

    original_db_path = db.DB_PATH
    db.DB_PATH = output_dir / "synthetic_validation.db"
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()

    respondents: list[dict[str, Any]] = []
    all_answers: list[dict[str, Any]] = []
    latent_and_observed: list[tuple[float, float]] = []
    scorer = LLMScorer()
    student_number = 0
    try:
        db.init_db(questions)
        for level in LEVEL_ABILITIES:
            for _ in range(per_level):
                student_number += 1
                person = build_person(level, student_number, rng)
                user_id = person["student_id"]
                test_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"a01-synthetic-{seed}-{user_id}"))
                db.upsert_user(user_id, f"仿真学员{student_number:03d}", f"仿真-{level}-{person['background']}")
                engine = AdaptiveTestEngine(
                    questions,
                    state=AdaptiveTestEngine.initial_state(target_questions),
                    seed=f"balanced-{seed}-{user_id}",
                )
                db.create_test(test_id, user_id, target_questions, engine.state)
                open_quality: dict[str, float] = {}
                total_time = 0.0
                while not engine.is_complete():
                    public = engine.next_question()
                    question = next(item for item in questions if item["id"] == public["id"])
                    ability = person["dimension_abilities"][question["dimension"]]
                    if question["type"] == "single_choice":
                        probability = success_probability(ability, int(question["difficulty"]))
                        probability *= 1 - person["carelessness"]
                        correct = rng.random() < probability
                        if correct:
                            answer = question["answer"]
                        else:
                            answer = rng.choice([item for item in question["options"] if item != question["answer"]])
                        open_score = None
                    else:
                        answer, quality = human_like_open_answer(question, person, rng)
                        open_quality[question["id"]] = quality
                        open_score = scorer._rubric_score(question, answer)
                        open_score["model"] = "synthetic-rubric-baseline"
                    elapsed = elapsed_seconds(question, person, rng)
                    total_time += elapsed
                    result = engine.submit_answer(question["id"], answer, elapsed, open_score)
                    db.save_answer(test_id, result, answer, elapsed)
                    db.save_state(test_id, engine.state, completed=result["completed"])

                report = engine.build_report()
                predicted_level = score_level(report["overall_score"])
                latent_and_observed.append((person["latent_ability"], report["overall_score"] / 100))
                respondents.append({
                    "student_id": user_id,
                    "expected_level": level,
                    "predicted_level": predicted_level,
                    "background": person["background"],
                    "pace_profile": person["pace_profile"],
                    "overall_score": report["overall_score"],
                    "question_count": report["question_count"],
                    "total_minutes": round(total_time / 60, 1),
                    "min_confidence": min(report["confidence"].values()),
                    **{f"score_{dimension}": report["dimension_scores"][dimension] for dimension in DIMENSIONS},
                })

                with db.connection() as connection:
                    answer_rows = connection.execute(
                        "SELECT * FROM answers WHERE test_id=? ORDER BY id", (test_id,)
                    ).fetchall()
                for answer_row in answer_rows:
                    answer_item = dict(answer_row)
                    all_answers.append({
                        "student_id": user_id,
                        "expected_level": level,
                        "answer_id": answer_item["id"],
                        "question_id": answer_item["question_id"],
                        "dimension": answer_item["dimension"],
                        "question_type": answer_item["question_type"],
                        "difficulty": answer_item["difficulty"],
                        "score": answer_item["score"],
                        "max_score": answer_item["max_score"],
                        "elapsed_seconds": answer_item["elapsed_seconds"],
                    })
                    if answer_item["question_type"] == "single_choice":
                        continue
                    quality = open_quality[answer_item["question_id"]]
                    review_scores = []
                    for reviewer in ("模拟教师A", "模拟教师B"):
                        reviewer_rng = random.Random(f"{seed}-{answer_item['id']}-{reviewer}")
                        score = teacher_score(
                            quality, float(answer_item["max_score"]), reviewer, answer_item["dimension"], reviewer_rng
                        )
                        review_scores.append(score)
                        db.save_human_review(
                            answer_item["id"], reviewer, score,
                            "独立模拟评分：依据量表覆盖、过程完整性、核验和风险控制判断。",
                            {
                                "simulation": True,
                                "reviewer_profile": reviewer,
                                "dimension": answer_item["dimension"],
                                "quality_band": round(quality, 3),
                            },
                        )
                    if abs(review_scores[0] - review_scores[1]) / float(answer_item["max_score"]) >= 0.20:
                        resolved = round(statistics.median([
                            review_scores[0], review_scores[1], quality * float(answer_item["max_score"])
                        ]) * 2) / 2
                        db.resolve_review(
                            answer_item["id"], resolved, "模拟裁决教师C",
                            "两名模拟教师评分差异达到20%，按独立第三评分与中位数规则裁决。",
                        )

        review_rows = db.review_records()
        metrics = review_metrics(review_rows)
        with db.connection() as connection:
            resolutions = [dict(row) for row in connection.execute(
                "SELECT * FROM review_resolutions ORDER BY answer_id"
            ).fetchall()]
        level_summary = {}
        for level in LEVEL_ABILITIES:
            group = [item for item in respondents if item["expected_level"] == level]
            level_summary[level] = {
                "sample_size": len(group),
                "mean_score": round(statistics.mean(item["overall_score"] for item in group), 2),
                "score_sd": round(statistics.pstdev(item["overall_score"] for item in group), 2),
                "mean_minutes": round(statistics.mean(item["total_minutes"] for item in group), 2),
                "classification_accuracy": round(
                    sum(item["predicted_level"] == level for item in group) / len(group), 3
                ),
                "predicted_levels": dict(Counter(item["predicted_level"] for item in group)),
            }
        expected_distribution = Counter(item["expected_level"] for item in respondents)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "seed": seed,
            "evidence_scope": "synthetic_balanced_cohort",
            "disclaimer": "100份样本均为程序生成的仿真人工答题，不是真实学生数据；双评由两名独立模拟教师评分器完成，不替代真实教师签字与现场效度验证。",
            "design": {
                "levels": list(LEVEL_ABILITIES),
                "samples_per_level": per_level,
                "total_samples": len(respondents),
                "target_questions": target_questions,
                "distribution": dict(expected_distribution),
                "maximum_level_share": round(max(expected_distribution.values()) / len(respondents), 3),
                "background_count": len(set(item["background"] for item in respondents)),
                "individual_variation": ["六维强弱项", "专业背景", "答题速度", "粗心率", "开放题表达与覆盖率"],
            },
            "assessment_results": {
                "completion_rate": 1.0,
                "overall_classification_accuracy": round(
                    sum(item["expected_level"] == item["predicted_level"] for item in respondents) / len(respondents), 3
                ),
                "latent_observed_pearson": pearson(
                    [item[0] for item in latent_and_observed], [item[1] for item in latent_and_observed]
                ),
                "mean_score": round(statistics.mean(item["overall_score"] for item in respondents), 2),
                "mean_minutes": round(statistics.mean(item["total_minutes"] for item in respondents), 2),
                "levels": level_summary,
            },
            "double_review": {
                **metrics,
                "reviewer_type": "two_independent_simulated_teacher_raters",
                "review_records": len(review_rows),
                "resolved_disagreements": len(resolutions),
                "major_disagreement_threshold": 0.20,
            },
            "artifacts": {
                "database": "synthetic_validation.db",
                "respondents_csv": "synthetic_respondents.csv",
                "answers_csv": "synthetic_answers.csv",
                "reviews_csv": "synthetic_teacher_reviews.csv",
                "resolutions_csv": "synthetic_review_resolutions.csv",
            },
        }
        write_csv(output_dir / "synthetic_respondents.csv", respondents)
        write_csv(output_dir / "synthetic_answers.csv", all_answers)
        write_csv(output_dir / "synthetic_teacher_reviews.csv", review_rows)
        write_csv(output_dir / "synthetic_review_resolutions.csv", resolutions)
        (output_dir / "synthetic_validation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return report
    finally:
        db.DB_PATH = original_db_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成分层均衡的仿真人工答题样本并执行模拟教师双评")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs" / "synthetic_validation_100")
    parser.add_argument("--per-level", type=int, default=20)
    parser.add_argument("--target", type=int, default=25, choices=range(15, 26))
    parser.add_argument("--seed", type=int, default=20260816)
    arguments = parser.parse_args()
    result = run_simulation(arguments.output_dir, arguments.per_level, arguments.target, arguments.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
