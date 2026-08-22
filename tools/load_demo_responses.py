from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
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


def seed_growth_history(student_count: int = 100, attempts_per_student: int = 50,
                        target_questions: int = 25, seed: int = 20260823) -> dict:
    """为每名演示学员补齐 50 次独立测评，并保证题目组合不完全相同。"""
    questions = load_all_questions()
    db.init_db(questions)
    scorer = LLMScorer()
    question_by_id = {item["id"]: item for item in questions}
    levels = list(LEVEL_ABILITIES)
    inserted_tests = 0
    inserted_answers = 0
    base_time = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    with db.connection() as connection:
        for number in range(1, student_count + 1):
            user_id = f"DEMO-{number:03d}"
            existing_rows = connection.execute(
                """SELECT t.id,t.source_note,GROUP_CONCAT(a.question_id,'|') signature
                   FROM tests t LEFT JOIN answers a ON a.test_id=t.id
                   WHERE t.user_id=? AND t.data_source='synthetic_demo' AND t.status='completed'
                   GROUP BY t.id ORDER BY t.completed_at,t.id""", (user_id,),
            ).fetchall()
            if not existing_rows:
                raise RuntimeError(f"缺少演示学员基础测评：{user_id}")
            first_id = existing_rows[0]["id"]
            first_time = base_time + timedelta(minutes=number)
            connection.execute(
                "UPDATE tests SET started_at=?,completed_at=?,source_note=? WHERE id=?",
                (first_time.isoformat(), (first_time + timedelta(minutes=35)).isoformat(),
                 "growth_attempt=1;synthetic_demo=true", first_id),
            )
            signatures = {row["signature"] for row in existing_rows if row["signature"]}
            completed = len(existing_rows)
            for attempt in range(completed + 1, attempts_per_student + 1):
                test_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"a01-demo-growth-v2-{number:03d}-{attempt:02d}"))
                if connection.execute("SELECT 1 FROM tests WHERE id=?", (test_id,)).fetchone():
                    continue
                level = levels[(number - 1) % len(levels)]
                nonce = 0
                while True:
                    rng = random.Random(f"{seed}-{number}-{attempt}-{nonce}")
                    person = build_person(level, number, rng)
                    progress = (attempt - 1) / max(1, attempts_per_student - 1)
                    for dimension, value in person["dimension_abilities"].items():
                        person["dimension_abilities"][dimension] = min(0.97, value + (0.97 - value) * 0.48 * progress)
                    engine = AdaptiveTestEngine(questions, state=AdaptiveTestEngine.initial_state(target_questions),
                                                seed=f"growth-{seed}-{number}-{attempt}-{nonce}")
                    answer_rows = []
                    while not engine.is_complete():
                        public = engine.next_question()
                        question = question_by_id[public["id"]]
                        ability = person["dimension_abilities"][question["dimension"]]
                        if question["type"] in {"single_choice", "true_false"}:
                            correct = rng.random() < success_probability(ability, int(question["difficulty"])) * (1 - person["carelessness"])
                            answer = question["answer"] if correct else rng.choice([option for option in question["options"] if option != question["answer"]])
                            open_score = None
                        else:
                            answer, _ = human_like_open_answer(question, person, rng)
                            open_score = scorer._rubric_score(question, answer)
                            open_score["model"] = "synthetic-demo-rubric"
                        elapsed = elapsed_seconds(question, person, rng)
                        result = engine.submit_answer(question["id"], answer, elapsed, open_score)
                        answer_rows.append((result, answer, elapsed))
                    signature = "|".join(engine.state["used_ids"])
                    if signature not in signatures:
                        signatures.add(signature)
                        break
                    nonce += 1
                    if nonce > 20:
                        raise RuntimeError(f"无法为 {user_id} 第 {attempt} 次测评生成不同题目组合")
                started = base_time + timedelta(days=attempt - 1, minutes=number)
                completed_at = started + timedelta(minutes=30 + attempt % 15)
                connection.execute(
                    """INSERT INTO tests(id,user_id,status,target_questions,state_json,started_at,completed_at,data_source,source_note)
                       VALUES (?,?,'completed',?,?,?,?, 'synthetic_demo',?)""",
                    (test_id, user_id, target_questions, json.dumps(engine.state, ensure_ascii=False),
                     started.isoformat(), completed_at.isoformat(), f"growth_attempt={attempt};synthetic_demo=true;seed={seed}"),
                )
                for result, answer, elapsed in answer_rows:
                    connection.execute(
                        """INSERT INTO answers(test_id,question_id,dimension,question_type,difficulty,answer_text,
                           score,max_score,elapsed_seconds,feedback_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (test_id, result["question_id"], result["dimension"], result["question_type"], result["difficulty"],
                         answer, result["score"], result["max_score"], elapsed,
                         json.dumps(result.get("feedback", {}), ensure_ascii=False), completed_at.isoformat()),
                    )
                inserted_tests += 1
                inserted_answers += len(answer_rows)
    with db.connection() as connection:
        counts = connection.execute(
            """SELECT MIN(n) minimum,MAX(n) maximum FROM
               (SELECT user_id,COUNT(*) n FROM tests WHERE data_source='synthetic_demo' AND status='completed' GROUP BY user_id)"""
        ).fetchone()
    return {"students": student_count, "attempts_per_student": attempts_per_student,
        "inserted_tests": inserted_tests, "inserted_answers": inserted_answers,
        "minimum_attempts": counts["minimum"], "maximum_attempts": counts["maximum"]}


def seed_double_review_cases(minimum_cases: int = 24) -> dict:
    """生成可追溯的双评演示记录；不冒充真实教师效度证据。"""
    now = db.utc_now()
    with db.connection() as connection:
        rows = connection.execute(
            """SELECT a.id,a.score,a.max_score,a.dimension FROM answers a
               JOIN tests t ON t.id=a.test_id
               WHERE t.data_source='synthetic_demo'
               AND a.question_type IN ('open_text','practical','code','image','dialogue')
               ORDER BY CASE WHEN t.source_note LIKE '%growth_attempt=50;%' THEN 0 ELSE 1 END,a.id DESC
               LIMIT ?""", (minimum_cases,),
        ).fetchall()
        for index, row in enumerate(rows):
            max_score = float(row["max_score"])
            base = float(row["score"])
            delta_a = (index % 3 - 1) * 0.05 * max_score
            delta_b = ((index + 1) % 3 - 1) * 0.05 * max_score
            if index % 6 == 0:
                delta_a, delta_b = 0.12 * max_score, -0.12 * max_score
            score_a = round(max(0, min(max_score, base + delta_a)) * 2) / 2
            score_b = round(max(0, min(max_score, base + delta_b)) * 2) / 2
            rubric = json.dumps({"data_source": "synthetic_demo", "purpose": "double_review_demo"}, ensure_ascii=False)
            for reviewer, score in (("教师双评A", score_a), ("教师双评B", score_b)):
                connection.execute(
                    """INSERT INTO human_reviews(answer_id,reviewer,score,comment,rubric_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?) ON CONFLICT(answer_id,reviewer) DO UPDATE SET
                       score=excluded.score,comment=excluded.comment,rubric_json=excluded.rubric_json,updated_at=excluded.updated_at""",
                    (row["id"], reviewer, score, "依据评分量表独立盲评，用于演示双评与一致性流程。", rubric, now, now),
                )
            if index < 4:
                resolved = round(((score_a + score_b) / 2) * 2) / 2
                connection.execute(
                    """INSERT INTO review_resolutions(answer_id,resolved_score,resolver,note,created_at)
                       VALUES (?,?,?,?,?) ON CONFLICT(answer_id) DO UPDATE SET resolved_score=excluded.resolved_score,
                       resolver=excluded.resolver,note=excluded.note,created_at=excluded.created_at""",
                    (row["id"], resolved, "教师裁决C", "双评演示裁决：综合两名教师评分与量表证据。", now),
                )
        paired = connection.execute(
            """SELECT COUNT(*) FROM (SELECT answer_id FROM human_reviews GROUP BY answer_id HAVING COUNT(DISTINCT reviewer)>=2)"""
        ).fetchone()[0]
    return {"requested": minimum_cases, "double_reviewed_answers": paired, "seeded_cases": len(rows), "resolved_cases": min(4, len(rows))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Idempotently seed synthetic demo answer sheets")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--questions", type=int, default=25)
    parser.add_argument("--attempts", type=int, default=50)
    args = parser.parse_args()
    print(seed_demo_responses(args.count, args.questions))
    print(seed_growth_history(args.count, args.attempts, args.questions))
    print(seed_double_review_cases())
    print(seed_demo_positions_and_applications())
