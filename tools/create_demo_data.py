from __future__ import annotations

import argparse
import json
import random
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from algorithm.adaptive_test import AdaptiveTestEngine
from backend.database import create_test, init_db, save_answer, save_state, upsert_user
from llm.scorer import LLMScorer
from question_bank.loader import load_all_questions


def create_demo(users: int, seed: int) -> None:
    rng = random.Random(seed)
    questions = load_all_questions()
    init_db(questions)
    scorer = LLMScorer()
    profiles = [("入门", 0.30), ("基础", 0.50), ("熟练", 0.68), ("高级", 0.84)]
    for index in range(users):
        label, ability = profiles[index % len(profiles)]
        user_id = f"demo-user-{index + 1:02d}"
        test_id = str(uuid.uuid4())
        upsert_user(user_id, f"演示学员{index + 1:02d}", f"{label}组")
        state = AdaptiveTestEngine.initial_state(18)
        create_test(test_id, user_id, 18, state)
        engine = AdaptiveTestEngine(questions, state=state, seed=f"demo-{seed}-{index}")
        while not engine.is_complete():
            public = engine.next_question()
            question = next(item for item in questions if item["id"] == public["id"])
            if question["type"] == "single_choice":
                correct_probability = max(0.08, min(0.96, ability - 0.13 * (question["difficulty"] - 1)))
                answer = question["answer"] if rng.random() < correct_probability else next(option for option in question["options"] if option != question["answer"])
                open_score = None
            else:
                answer = "明确任务目标，进行步骤拆解，核验数据来源，设置人工确认，并记录风险与改进结果。"
                open_score = scorer._rubric_score(question, answer)
            elapsed = rng.uniform(15, 75)
            result = engine.submit_answer(question["id"], answer, elapsed, open_score)
            save_answer(test_id, result, answer, elapsed)
            save_state(test_id, engine.state, completed=result["completed"])
    print(json.dumps({"created_users": users, "seed": seed}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="创建本地教学看板演示数据")
    parser.add_argument("--users", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260813)
    args = parser.parse_args()
    create_demo(args.users, args.seed)
