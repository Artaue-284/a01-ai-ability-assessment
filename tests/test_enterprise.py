import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.enterprise import DEFAULT_JOB_TEMPLATES, build_dialogue_guidance, score_job_matches
from backend.main import ENTERPRISE_ACCESS_KEY, app


class EnterpriseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(app)
        cls.client = cls.context.__enter__()
        cls.headers = {"X-Enterprise-Key": ENTERPRISE_ACCESS_KEY}

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def test_role_contract_separates_personal_and_enterprise_data(self):
        response = self.client.get("/api/roles")
        self.assertEqual(response.status_code, 200)
        roles = response.json()["roles"]
        self.assertIn("view_own_report", roles["student"])
        self.assertIn("view_identified_class_dashboard", roles["teacher"])
        self.assertIn("view_anonymous_group_insights", roles["enterprise"])
        self.assertNotIn("view_own_report", roles["enterprise"])

    def test_enterprise_endpoints_require_separate_key(self):
        self.assertEqual(self.client.get("/api/enterprise/overview").status_code, 401)
        response = self.client.get("/api/enterprise/overview", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload["templates"]), 3)
        if not payload["eligible"]:
            self.assertEqual(payload["dimension_averages"], {})

    def test_explainable_job_matching(self):
        scores = {"basic": 70, "prompt": 82, "tools": 76, "evaluation": 71, "collaboration": 65, "ethics": 80}
        matches = score_job_matches(scores, DEFAULT_JOB_TEMPLATES)
        self.assertEqual(len(matches), 3)
        self.assertGreaterEqual(matches[0]["match_score"], matches[-1]["match_score"])
        self.assertIn("不构成录用", matches[0]["notice"])
        self.assertIn("strengths", matches[0])
        self.assertIn("gaps", matches[0])

    def test_dialogue_guidance_requires_process_evidence(self):
        self.assertIn("任务目标", build_dialogue_guidance(1, "我准备开始"))
        self.assertIn("可检查证据", build_dialogue_guidance(3, "已经做了两步"))

    def test_evidence_rejects_unsupported_files_before_write(self):
        start = self.client.post("/api/test/start", json={
            "user_name": "权限边界自动测试",
            "class_name": "自动测试",
            "target_questions": 15,
        })
        self.assertEqual(start.status_code, 200, start.text)
        response = self.client.post("/api/evidence", json={
            "test_id": start.json()["test_id"],
            "question_id": "PT001",
            "filename": "dangerous.exe",
            "media_type": "application/octet-stream",
            "content_base64": "dGVzdA==",
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("仅支持", response.json()["detail"])

    def test_evidence_accepts_safe_text_and_generates_sha256(self):
        start = self.client.post("/api/test/start", json={
            "user_name": "证据上传自动测试",
            "class_name": "自动测试",
            "target_questions": 15,
        })
        self.assertEqual(start.status_code, 200, start.text)
        with tempfile.TemporaryDirectory() as temp_dir, patch("backend.main.ROOT", Path(temp_dir)), patch(
            "backend.main.save_evidence_file",
            side_effect=lambda item: {key: value for key, value in item.items() if key != "storage_path"},
        ):
            response = self.client.post("/api/evidence", json={
                "test_id": start.json()["test_id"],
                "question_id": "PT001",
                "filename": "evidence.txt",
                "media_type": "text/plain",
                "content_base64": "dGVzdA==",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["size_bytes"], 4)
        self.assertEqual(len(response.json()["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
