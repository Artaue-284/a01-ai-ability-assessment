import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import ADMIN_ACCESS_KEY, app


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
        self.assertEqual(len(response.json()["items"]), 91)
        source = next(item for item in response.json()["items"] if item["id"] == "BA201")
        payload = {key: source.get(key) for key in (
            "id", "dimension", "difficulty", "type", "question", "options", "answer",
            "explanation", "tags", "ability_level", "discrimination", "max_score", "rubric", "keywords",
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
        self.assertEqual(len(bank.json()["items"]), 91)

    def test_question_agent_returns_draft_without_saving(self):
        draft = {
            "id": "AIEVTEST001",
            "dimension": "evaluation",
            "difficulty": 2,
            "type": "single_choice",
            "question": "需要核验AI生成的数据时，首先应该做什么？",
            "options": ["直接采用", "核对原始来源", "修改格式", "删除数据"],
            "answer": "核对原始来源",
            "explanation": "应先核对权威原始来源。",
            "tags": ["核验"],
            "ability_level": "L2",
            "discrimination": 1.0,
            "max_score": 10,
            "rubric": [],
            "keywords": ["来源"],
            "changed_by": "百宝箱题库智能体（待教师审核）",
            "draft": True,
            "source_model": "baibaoxiang:test-question-app",
        }
        before = len(self.client.get("/api/admin/questions", headers=self.headers).json()["items"])
        with patch("backend.main.QUESTION_GENERATOR") as generator:
            generator.configured = True
            generator.generate.return_value = [draft]
            response = self.client.post("/api/admin/questions/generate-draft", headers=self.headers, json={
                "dimension": "evaluation", "type": "single_choice", "difficulty": 2, "count": 1,
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["draft_only"])
        self.assertTrue(response.json()["items"][0]["draft"])
        after = len(self.client.get("/api/admin/questions", headers=self.headers).json()["items"])
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
