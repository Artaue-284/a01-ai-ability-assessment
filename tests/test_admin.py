import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import ADMIN_ACCESS_KEY, app

# 单元测试使用隔离的测试数据库，避免清空或污染 data/assessment.db 中的真实数据。
os.environ.setdefault("A01_DB_PATH", str(Path(__file__).resolve().parent.parent / ".test_runtime" / "assessment_test.db"))


class AdminApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        cls.headers = {"X-Admin-Key": ADMIN_ACCESS_KEY}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_admin_endpoints_require_key(self):
        self.assertEqual(self.client.get("/api/admin/questions").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 401)

    def test_question_management_and_versions(self):
        response = self.client.get("/api/admin/questions", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 96)
        source = next(item for item in response.json()["items"] if item["id"] == "BA201")
        payload = {key: source.get(key) for key in (
            "id", "dimension", "difficulty", "type", "question", "options", "answer",
            "explanation", "tags", "ability_level", "discrimination", "max_score", "rubric", "keywords", "image_url",
        )}
        payload["rubric"] = payload["rubric"] or []
        payload["keywords"] = payload["keywords"] or []
        payload["changed_by"] = "自动测试"
        saved = self.client.post("/api/admin/questions", headers=self.headers, json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        versions = self.client.get("/api/admin/questions/BA201/versions", headers=self.headers)
        self.assertGreaterEqual(len(versions.json()["versions"]), 2)

    def test_review_metrics_and_exports(self):
        metrics = self.client.get("/api/admin/reviews/metrics", headers=self.headers)
        self.assertEqual(metrics.status_code, 200)
        exported = self.client.get("/api/admin/export/answers.csv", headers=self.headers)
        self.assertEqual(exported.status_code, 200)
        self.assertIn("text/csv", exported.headers["content-type"])
        bank = self.client.get("/api/admin/questions-export.json", headers=self.headers)
        self.assertEqual(len(bank.json()["items"]), 96)

    def test_admin_students_list_for_growth_tracking(self):
        response = self.client.get("/api/admin/students", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("items", response.json())


if __name__ == "__main__":
    unittest.main()
