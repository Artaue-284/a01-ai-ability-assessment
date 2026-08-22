from __future__ import annotations

import argparse
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
