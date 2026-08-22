import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from algorithm.adaptive_test import AdaptiveTestEngine
from backend.database import connection, create_test, init_db, save_state, upsert_user
from question_bank.loader import load_all_questions

import backend.main as main_module

# 单元测试使用隔离的测试数据库，避免清空或污染 data/assessment.db 中的真实数据。
os.environ.setdefault("A01_DB_PATH", str(Path(__file__).resolve().parent.parent / ".test_runtime" / "assessment_test.db"))


def _reset_fixture() -> None:
    with connection() as db:
        db.execute("DELETE FROM position_applications")
        db.execute("DELETE FROM positions")
        db.execute("DELETE FROM auth_sessions")
        db.execute("DELETE FROM accounts")
        db.execute("DELETE FROM answers WHERE test_id IN ('auth-apply-test','auth-student-test')")
        db.execute("DELETE FROM tests WHERE id IN ('auth-apply-test','auth-student-test')")
        db.execute("DELETE FROM users WHERE id IN ('auth-teacher-u','auth-student-u','auth-enterprise-u')")


def _complete_assessment(user_id: str, test_id: str) -> None:
    """直接完成一次测评并落库，供投递测试使用（避免在 API 层跑 15 题）。"""
    bank = load_all_questions()
    by_id = {q["id"]: q for q in bank}
    engine = AdaptiveTestEngine(bank, seed=test_id, state=AdaptiveTestEngine.initial_state(15))
    while not engine.is_complete():
        question = engine.next_question()
        source = by_id[question["id"]]
        if source["type"] == "single_choice":
            engine.submit_answer(question["id"], source["answer"], 10)
        else:
            engine.submit_answer(question["id"], "覆盖目标步骤核验风险与人工确认的完整回答", 30, {"score": source["max_score"]})
    create_test(test_id, user_id, 15, engine.state)
    save_state(test_id, engine.state, completed=True)


class AuthRoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main_module.app)
        cls.client = cls.client_context.__enter__()
        init_db(load_all_questions())
        _reset_fixture()
        from backend.database import create_account
        create_account("teacher", "teacher01", "demo123", "王老师", "A01班")
        create_account("enterprise", "company01", "demo123", "李经理", "测试科技公司")
        upsert_user("auth-student-u", "投递学员", "A01班")
        _complete_assessment("auth-student-u", "auth-apply-test")

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def _login(self, username, password="demo123"):
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_login_and_me(self):
        data = self._login("teacher01")
        self.assertEqual(data["role"], "teacher")
        self.assertIn("token", data)
        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {data['token']}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "teacher")
        self.assertIn("manage_question_bank", me.json()["permissions"])

    def test_wrong_password_rejected(self):
        response = self.client.post("/api/auth/login", json={"username": "teacher01", "password": "wrong-pass"})
        self.assertEqual(response.status_code, 401)

    def test_role_scoped_access(self):
        teacher = self._login("teacher01")
        enterprise = self._login("company01")
        t_headers = {"Authorization": f"Bearer {teacher['token']}"}
        e_headers = {"Authorization": f"Bearer {enterprise['token']}"}
        # 教师可进教学管理，企业账号不可
        self.assertEqual(self.client.get("/api/admin/dashboard", headers=t_headers).status_code, 200)
        self.assertIn(self.client.get("/api/admin/dashboard", headers=e_headers).status_code, (401, 403))
        # 企业可进企业工作台，教师账号不可
        self.assertEqual(self.client.get("/api/enterprise/overview", headers=e_headers).status_code, 200)
        self.assertIn(self.client.get("/api/enterprise/overview", headers=t_headers).status_code, (401, 403))
        # 教师工作台仅教师可访问
        self.assertEqual(self.client.get("/api/teacher/dashboard", headers=t_headers).status_code, 200)
        self.assertIn(self.client.get("/api/teacher/dashboard", headers=e_headers).status_code, (401, 403))

    def test_account_management_requires_admin(self):
        response = self.client.post("/api/admin/accounts", json={
            "role": "teacher", "username": "teacher02", "password": "demo123",
            "display_name": "李老师", "org_name": "A02班",
        })
        self.assertEqual(response.status_code, 401)
        from backend.database import get_account_by_username
        self.assertIsNone(get_account_by_username("teacher02"))


class PositionClosedLoopTests(unittest.TestCase):
    """企业轻量化业务闭环：企业发岗位 → 学员投递 → 企业看申请 → 教师看统计。"""

    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main_module.app)
        cls.client = cls.client_context.__enter__()
        init_db(load_all_questions())
        _reset_fixture()
        from backend.database import create_account
        create_account("teacher", "teacher01", "demo123", "王老师", "A01班")
        create_account("enterprise", "company01", "demo123", "李经理", "测试科技公司")
        upsert_user("auth-student-u", "投递学员", "A01班")
        _complete_assessment("auth-student-u", "auth-student-test")
        cls.enterprise = cls.client.post("/api/auth/login", json={"username": "company01", "password": "demo123"}).json()
        cls.e_headers = {"Authorization": f"Bearer {cls.enterprise['token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_full_application_loop(self):
        # 企业发布岗位
        created = self.client.post("/api/enterprise/positions", json={
            "title": "AI应用助理实习生", "description": "协助完成数据清洗与可视化",
            "template_id": "ai-application-assistant",
        }, headers=self.e_headers)
        self.assertEqual(created.status_code, 200, created.text)
        position_id = created.json()["id"]
        self.assertEqual(created.json()["company"], "测试科技公司")
        # 学员浏览岗位广场（开放岗位可见）
        plaza = self.client.get("/api/positions", params={"user_id": "auth-student-u"})
        self.assertEqual(plaza.status_code, 200)
        items = plaza.json()["items"]
        self.assertTrue(any(item["id"] == position_id for item in items))
        # 未测评学员投递被拒
        upsert_user("auth-noscore-u", "无测评学员", "A01班")
        blocked = self.client.post(f"/api/positions/{position_id}/apply", json={
            "user_id": "auth-noscore-u", "user_name": "无测评学员", "consent": True,
        })
        self.assertEqual(blocked.status_code, 409)
        # 学员投递（授权共享能力画像）
        applied = self.client.post(f"/api/positions/{position_id}/apply", json={
            "user_id": "auth-student-u", "user_name": "投递学员", "class_name": "A01班",
            "contact": "13800000000", "consent": True,
        })
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertGreater(applied.json()["match_score"], 0)
        # 重复投递被拒
        again = self.client.post(f"/api/positions/{position_id}/apply", json={
            "user_id": "auth-student-u", "user_name": "投递学员", "consent": True,
        })
        self.assertEqual(again.status_code, 409)
        # 未授权投递被拒
        no_consent = self.client.post(f"/api/positions/{position_id}/apply", json={
            "user_id": "auth-student-u", "user_name": "投递学员", "consent": False,
        })
        self.assertEqual(no_consent.status_code, 409)
        # 企业查看投递列表（脱敏：仅姓名/班级/联系方式/匹配分）
        applications = self.client.get(f"/api/enterprise/positions/{position_id}/applications", headers=self.e_headers)
        self.assertEqual(applications.status_code, 200)
        rows = applications.json()["items"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["user_name"], "投递学员")
        self.assertGreater(rows[0]["match_score"], 0)
        # 企业关闭岗位后，学员端不再可见、不可投递
        closed = self.client.post(f"/api/enterprise/positions/{position_id}/status", json={"status": "closed"}, headers=self.e_headers)
        self.assertEqual(closed.status_code, 200)
        plaza2 = self.client.get("/api/positions").json()["items"]
        self.assertFalse(any(item["id"] == position_id for item in plaza2))
        # 教师端统计
        teacher = self.client.post("/api/auth/login", json={"username": "teacher01", "password": "demo123"})
        if teacher.status_code == 200:
            dashboard = self.client.get("/api/teacher/dashboard", headers={"Authorization": f"Bearer {teacher.json()['token']}"})
            self.assertEqual(dashboard.status_code, 200)
            self.assertGreaterEqual(dashboard.json()["applications"]["total_applications"], 1)
        # 学员已投递记录
        mine = self.client.get("/api/users/auth-student-u/applications")
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.json()["total"], 1)


if __name__ == "__main__":
    unittest.main()
