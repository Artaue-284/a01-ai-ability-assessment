import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from algorithm.adaptive_test import AdaptiveTestEngine
from backend.database import connection, create_test, init_db, list_question_items, upsert_user
from question_bank.loader import load_all_questions

import backend.main as main_module

# 单元测试使用隔离的测试数据库，避免清空或污染 data/assessment.db 中的真实数据。
os.environ.setdefault("A01_DB_PATH", str(Path(__file__).resolve().parent.parent / ".test_runtime" / "assessment_test.db"))


class OptionOrderRegressionTests(unittest.TestCase):
    """回归测试：客观题作答时选项被随机打乱，提交后/回看时必须保持同一顺序。

    修复前：作答时使用 shuffled(options)，只读视图回退到题库原始顺序，
    导致学员看到的选项位置与内容错位（如选 B 提交后 B 的内容跑到 D）。
    修复后：前端把作答时的选项顺序随提交保存，后端持久化并在
    select/回看接口返回，只读视图按保存顺序渲染。
    """

    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main_module.app)
        cls.client = cls.client_context.__enter__()
        init_db(load_all_questions())
        with connection() as db:
            db.execute("DELETE FROM answers WHERE test_id='option-order-test'")
            db.execute("DELETE FROM tests WHERE id='option-order-test'")
            db.execute("DELETE FROM users WHERE id='option-order-user'")
        upsert_user("option-order-user", "选项顺序测试", "测试班级")
        create_test("option-order-test", "option-order-user", 15, AdaptiveTestEngine.initial_state(15))

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_submitted_options_order_is_persisted_and_returned(self):
        # 1. 取第一道客观题（题库原始顺序）
        first = self.client.post("/api/test/option-order-test/select/1").json()
        self.assertEqual(first["readonly"], False)
        question = first["question"]
        self.assertIn(question["type"], ("single_choice", "true_false"))
        original = list(question["options"])
        # 模拟前端打乱：反转顺序（与原始顺序必然不同）
        shuffled = list(reversed(original))

        # 2. 提交正确答案（以题库当前版本为准，可能与历史 JSON 不一致）+ 作答时看到的选项顺序
        db_bank = {item["id"]: item for item in list_question_items(include_disabled=True)}
        response = self.client.post("/api/answer/submit", json={
            "test_id": "option-order-test",
            "question_id": question["id"],
            "answer": db_bank[question["id"]]["answer"],
            "elapsed_seconds": 8,
            "options_order": shuffled,
        })
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["options_order"], shuffled)
        self.assertEqual(data["score"], data["max_score"])  # 判题不受乱序影响

        # 3. 回看该题：只读视图必须返回同一选项顺序，避免选项错位
        review = self.client.post("/api/test/option-order-test/select/1").json()
        self.assertEqual(review["readonly"], True)
        self.assertEqual(review["options_order"], shuffled)

    def test_answer_without_options_order_stays_compatible(self):
        # 兼容旧客户端：不传 options_order 时 select 回看返回空列表，前端回退题库顺序
        second = self.client.post("/api/test/option-order-test/select/2").json()
        question = second["question"]
        response = self.client.post("/api/answer/submit", json={
            "test_id": "option-order-test",
            "question_id": question["id"],
            "answer": "WRONG",
            "elapsed_seconds": 3,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["options_order"], [])
        review = self.client.post("/api/test/option-order-test/select/2").json()
        self.assertEqual(review["options_order"], [])


if __name__ == "__main__":
    unittest.main()
