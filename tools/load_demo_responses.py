from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm.adaptive_test import AdaptiveTestEngine
from backend import database as db
from llm.scorer import LLMScorer
from question_bank.loader import assessment_readiness, load_all_questions
from tools.simulate_balanced_cohort import (
    LEVEL_ABILITIES, build_person, elapsed_seconds, human_like_open_answer, success_probability,
)


DEMO_POSITIONS = (
    ("企业演示单位A", "AI应用助理实习生", "协助团队使用AI完成资料整理、办公自动化和结果核验。", "ai-application-assistant"),
    ("企业演示单位A", "提示词运营专员", "负责业务提示词设计、版本测试、效果复盘和模板沉淀。", "prompt-operations"),
    ("企业演示单位A", "AI项目协调助理", "参与AI项目需求梳理、进度协同、风险记录和验收跟踪。", "ai-project-coordinator"),
    ("企业演示单位A", "智能办公自动化助理", "使用AI工具改进文档、表格和日常流程，并保留人工复核节点。", "ai-application-assistant"),
    ("企业演示单位A", "AI内容质量评估实习生", "核验AI生成内容的事实、逻辑、来源和合规风险，形成评估记录。", "prompt-operations"),
)


def seed_demo_accounts(teacher_password: str, enterprise_password: str) -> dict:
    if len(teacher_password) < 12 or len(enterprise_password) < 12:
        raise ValueError("演示角色密码必须至少 12 位")
    specs = [
        ("teacher", "teacher_review_a", teacher_password, "教师评审A", "教学评审组"),
        ("teacher", "teacher_review_b", teacher_password, "教师评审B", "教学评审组"),
        ("teacher", "teacher_review_c", teacher_password, "教师裁决C", "教学评审组"),
        ("enterprise", "enterprise_demo_a", enterprise_password, "企业代表A", "校企合作单位"),
        ("enterprise", "enterprise_demo_b", enterprise_password, "企业代表B", "校企合作单位"),
    ]
    created = 0
    from backend.database import create_account, get_account_by_username
    for role, username, password, display_name, org_name in specs:
        if get_account_by_username(username) is None:
            create_account(role, username, password, display_name, org_name)
            created += 1
    return {"created": created, "total": len(specs)}


def seed_demo_positions_and_applications() -> dict:
    """幂等创建 5 个岗位，并让 100 名演示学员投递全部岗位。"""
    from backend.enterprise import score_job_matches
    from backend.database import apply_position, create_position, list_job_templates

    templates = {item["id"]: item for item in list_job_templates()}
    position_ids: list[str] = []
    created_positions = 0
    with db.connection() as connection:
        existing = {(row["company"], row["title"]): dict(row) for row in connection.execute("SELECT * FROM positions").fetchall()}
    for company, title, description, template_id in DEMO_POSITIONS:
        item = existing.get((company, title))
        if item is None:
            item = create_position(company, title, description, template_id, "enterprise_demo_a")
            created_positions += 1
        position_ids.append(item["id"])

    with db.connection() as connection:
        students = [dict(row) for row in connection.execute(
            """SELECT u.id user_id,u.name,u.class_name,t.id test_id,t.state_json
               FROM users u JOIN tests t ON t.user_id=u.id
               WHERE t.data_source='synthetic_demo' AND t.status='completed'
               AND t.completed_at=(SELECT MAX(t2.completed_at) FROM tests t2 WHERE t2.user_id=u.id AND t2.data_source='synthetic_demo' AND t2.status='completed')
               ORDER BY u.id LIMIT 100"""
        ).fetchall()]
    inserted_applications = 0
    for position_id, spec in zip(position_ids, DEMO_POSITIONS):
        template_id = spec[3]
        template = templates[template_id]
        for number, student in enumerate(students, 1):
            scores = {key: float(value) for key, value in json.loads(student["state_json"]).get("scores", {}).items()}
            match = score_job_matches(scores, [template])[0]
            try:
                apply_position(position_id, student["user_id"], student["name"], student["class_name"],
                    f"student{number:03d}@example.invalid", True, match["match_score"], template_id, student["test_id"])
                inserted_applications += 1
            except ValueError as exc:
                if "已投递" not in str(exc):
                    raise
    with db.connection() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM position_applications WHERE position_id IN ({','.join('?' for _ in position_ids)})",
            position_ids,
        ).fetchone()[0]
    return {"positions": len(position_ids), "created_positions": created_positions,
        "students": len(students), "inserted_applications": inserted_applications, "total_applications": total}


def seed_demo_responses(count: int = 100, target_questions: int = 25, seed: int = 20260822) -> dict:
    if not 1 <= count <= 500:
        raise ValueError("count must be between 1 and 500")
    questions = load_all_questions()
    readiness = assessment_readiness(questions)
    if not readiness["ready"]:
        raise RuntimeError(readiness["message"])
    db.init_db(questions)
    scorer = LLMScorer()
    inserted = 0
    question_by_id = {item["id"]: item for item in questions}
    levels = list(LEVEL_ABILITIES)
    for number in range(1, count + 1):
        user_id = f"DEMO-{number:03d}"
        test_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"a01-demo-responses-v1-{number:03d}"))
        with db.connection() as connection:
            if connection.execute("SELECT 1 FROM tests WHERE id=?", (test_id,)).fetchone():
                continue
        rng = random.Random(f"{seed}-{number}")
        level = levels[(number - 1) % len(levels)]
        person = build_person(level, number, rng)
        db.upsert_user(user_id, f"学员{number:03d}", f"AI能力提升{(number - 1) % 5 + 1}班")
        engine = AdaptiveTestEngine(questions, state=AdaptiveTestEngine.initial_state(target_questions), seed=f"demo-{seed}-{number}")
        db.create_test(test_id, user_id, target_questions, engine.state,
            data_source="synthetic_demo", source_note=f"deterministic_seed={seed};profile={level}")
        while not engine.is_complete():
            public = engine.next_question()
            question = question_by_id[public["id"]]
            ability = person["dimension_abilities"][question["dimension"]]
            if question["type"] in {"single_choice", "true_false"}:
                correct = rng.random() < success_probability(ability, int(question["difficulty"])) * (1 - person["carelessness"])
                answer = question["answer"] if correct else rng.choice([item for item in question["options"] if item != question["answer"]])
                open_score = None
            else:
                answer, _ = human_like_open_answer(question, person, rng)
                open_score = scorer._rubric_score(question, answer)
                open_score["model"] = "synthetic-demo-rubric"
            elapsed = elapsed_seconds(question, person, rng)
            result = engine.submit_answer(question["id"], answer, elapsed, open_score)
            db.save_answer(test_id, result, answer, elapsed)
            db.save_state(test_id, engine.state, completed=result["completed"])
        inserted += 1
    with db.connection() as connection:
        totals = connection.execute(
            """SELECT COUNT(DISTINCT t.id) tests,COUNT(a.id) answers
               FROM tests t LEFT JOIN answers a ON a.test_id=t.id
               WHERE t.data_source='synthetic_demo'"""
        ).fetchone()
    return {"requested": count, "inserted": inserted, "total_demo_tests": totals["tests"], "total_demo_answers": totals["answers"], "target_questions": target_questions, "data_source": "synthetic_demo"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Idempotently seed synthetic demo answer sheets")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--questions", type=int, default=25)
    args = parser.parse_args()
    print(seed_demo_responses(args.count, args.questions))
    print(seed_demo_positions_and_applications())
