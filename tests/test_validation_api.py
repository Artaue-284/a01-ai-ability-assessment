import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import ADMIN_ACCESS_KEY, app

# 单元测试使用隔离的测试数据库，避免清空或污染 data/assessment.db 中的真实数据。
os.environ.setdefault("A01_DB_PATH", str(Path(__file__).resolve().parent.parent / ".test_runtime" / "assessment_test.db"))


class ValidationApiTests(unittest.TestCase):
    """验证类接口的鉴权与返回结构（题库校验、测评就绪、复核指标）。"""

    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        cls.headers = {"X-Admin-Key": ADMIN_ACCESS_KEY}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_validation_endpoints_require_admin(self):
        for path in ("/api/question-bank/stats", "/api/admin/reviews/metrics", "/api/admin/dashboard"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
                self.assertEqual(self.client.get(path, headers=self.headers).status_code, 200)

    def test_question_bank_stats_preserve_validation_scope(self):
        response = self.client.get("/api/question-bank/stats", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("valid", payload)
        self.assertIn("total", payload)
        self.assertGreaterEqual(payload["total"], 90)
        self.assertIn("assessment_readiness", payload)
        self.assertIn("item_statistics", payload)

    def test_review_metrics_structure(self):
        response = self.client.get("/api/admin/reviews/metrics", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        metrics = response.json()
        for key in ("reviewed_answers", "double_reviewed_answers", "model_human_pearson",
                    "inter_rater_pearson", "quadratic_weighted_kappa", "major_disagreements"):
            self.assertIn(key, metrics)


if __name__ == "__main__":
    unittest.main()
