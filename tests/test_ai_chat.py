import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from algorithm.adaptive_test import AdaptiveTestEngine, TRAINING_RESOURCES
from backend.database import connection, create_test, init_db, upsert_user
from llm.chat import AIAssistant
from llm.scorer import LLMScorer
from question_bank.loader import load_all_questions

import backend.main as main_module
import llm.config as llm_config

# 单元测试使用隔离的测试数据库，避免清空或污染 data/assessment.db 中的真实数据。
os.environ.setdefault("A01_DB_PATH", str(Path(__file__).resolve().parent.parent / ".test_runtime" / "assessment_test.db"))


def _isolate_llm_config() -> patch:
    """把 ant-line 本地配置文件隔离为不存在路径，避免读取真实密钥影响测试。"""
    return patch.object(llm_config, "CONFIG_PATH", Path("__nonexistent_llm_config__.json"))


def _reset_api_fixture() -> None:
    """清理上次运行遗留的测试数据，保证用例可重复执行。"""
    with connection() as db:
        db.execute("DELETE FROM answers WHERE test_id='ai-chat-api-test'")
        db.execute("DELETE FROM tests WHERE id='ai-chat-api-test'")
        db.execute("DELETE FROM users WHERE id='ai-chat-api-user'")


class AiAssistantUnitTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "TBOX_TOKEN": "", "TBOX_APP_ID": "", "OPENAI_API_KEY": "",
            "OPENAI_BASE_URL": "", "OPENAI_MODEL": "",
        }, clear=False)
        self.env.start()
        self.config = _isolate_llm_config()
        self.config.start()

    def tearDown(self):
        self.env.stop()
        self.config.stop()

    def test_local_simulator_returns_guidance(self):
        assistant = AIAssistant()
        self.assertEqual(assistant.mode, "local-simulator")
        result = assistant.chat(
            {"type": "dialogue", "question": "把一场300人AI讲座拆成可执行方案"},
            [],
            "目标是为300人办一场AI主题讲座，我该从哪里开始？",
        )
        self.assertIn("reply", result)
        self.assertEqual(result["model"], "local-simulator")
        self.assertGreater(len(result["reply"]), 10)

    def test_local_simulator_detects_code_topic(self):
        assistant = AIAssistant()
        result = assistant.chat(
            {"type": "code", "question": "编写读取CSV统计销售额的代码"},
            [],
            "我想用python读取csv然后统计各品类销售额，但不确定用哪个库",
        )
        self.assertIn("代码", result["reply"])

    def test_scorer_uses_conversation_context(self):
        question = {"type": "open_text", "rubric": ["目标明确", "步骤完整"], "keywords": ["目标", "步骤"], "max_score": 20}
        without = LLMScorer().score(question, "先明确目标，再拆解步骤。", context="")
        with_context = LLMScorer().score(
            question, "先明确目标，再拆解步骤。",
            context="学员：我需要帮助\nAI助手：请先明确目标\n学员：目标是为300人办讲座\nAI助手：建议拆解为以下步骤",
        )
        self.assertGreaterEqual(with_context["score"], without["score"])

    def test_engine_tail_includes_dialogue_and_report_has_resources(self):
        bank = load_all_questions()
        engine = AdaptiveTestEngine(bank, seed="tail-check", state=AdaptiveTestEngine.initial_state(15))
        while not engine.is_complete():
            question = engine.next_question()
            source = next(item for item in bank if item["id"] == question["id"])
            if source["type"] == "single_choice":
                engine.submit_answer(question["id"], source["answer"], 10)
            else:
                engine.submit_answer(question["id"], "回答覆盖目标、步骤、核验、风险与人工确认", 30, {"score": source["max_score"]})
        report = engine.build_report()
        self.assertIn("dialogue", report["type_distribution"])
        self.assertIn("training_resources", report)
        self.assertTrue(report["training_resources"])
        self.assertIn("resources", report["training_resources"][0])

    def test_training_resources_cover_all_dimensions(self):
        for key in ("basic", "prompt", "tools", "evaluation", "collaboration", "ethics"):
            self.assertIn("resources", TRAINING_RESOURCES[key])
            self.assertTrue(TRAINING_RESOURCES[key]["resources"])

    def test_single_turn_reply_truncates_scripted_multi_turn_output(self):
        """回归：模型一次性输出多轮引导剧本时，只保留当前一轮。"""
        assistant = AIAssistant()
        scripted = (
            "你好！我们先来拆解目标。请问最常问的高频问题是什么？"
            "（等待学员回复第1轮后，继续引导）\n"
            "很好，接下来界定什么时候转人工。"
            "（等待学员回复第2轮后，继续引导）\n"
            "最后设计转接信息字段。"
        )
        result = assistant._single_turn_reply(scripted)
        self.assertNotIn("等待学员回复", result)
        self.assertNotIn("第2轮", result)
        self.assertIn("高频问题", result)
        # 正常单轮回复不被截断
        normal = "建议先明确活动时间、地点和费用这三类高频问题，再界定转人工条件。"
        self.assertEqual(assistant._single_turn_reply(normal), normal)

    def test_real_model_prompts_require_single_turn_reply(self):
        """回归：所有真实模型通道的系统/对话提示必须包含逐轮约束。"""
        assistant = AIAssistant()
        transcript = assistant._build_transcript(
            {"question": "对话式任务：请与 AI 协作完成方案。要求：至少 3 轮有效对话。"}, [], "第一步怎么做？"
        )
        self.assertIn("逐轮", transcript)
        self.assertIn("只回应当前这一轮", transcript)
        self.assertIn("不要一次性输出多轮引导计划", transcript)


class AiChatApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(main_module.app)
        cls.client = cls.client_context.__enter__()
        init_db(load_all_questions())
        _reset_api_fixture()
        upsert_user("ai-chat-api-user", "AI对话测试", "测试班级")
        create_test("ai-chat-api-test", "ai-chat-api-user", 18, AdaptiveTestEngine.initial_state(18))
        cls.env = patch.dict(os.environ, {
            "TBOX_TOKEN": "", "TBOX_APP_ID": "", "OPENAI_API_KEY": "",
        }, clear=False)
        cls.env.start()
        cls.config = _isolate_llm_config()
        cls.config.start()
        main_module.AI_ASSISTANT = AIAssistant()

    @classmethod
    def tearDownClass(cls):
        cls.config.stop()
        cls.env.stop()
        main_module.AI_ASSISTANT = AIAssistant()
        cls.client_context.__exit__(None, None, None)

    def test_ai_chat_endpoint_and_log(self):
        response = self.client.post("/api/ai-chat", json={
            "test_id": "ai-chat-api-test", "question_id": "OP001",
            "message": "我负责策划讲座，请帮我拆解第一步",
        })
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn("reply", data)
        self.assertEqual(data["mode"], "local-simulator")
        self.assertEqual(data["turns_used"], 1)
        self.assertEqual(data["turns_remaining"], 11)
        log = self.client.get("/api/test/ai-chat-api-test/ai-chat/OP001")
        self.assertEqual(log.status_code, 200)
        items = log.json()["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["role"], "user")
        self.assertEqual(items[1]["role"], "assistant")

    def test_ai_chat_rejects_objective_question(self):
        response = self.client.post("/api/ai-chat", json={
            "test_id": "ai-chat-api-test", "question_id": "BA201", "message": "请帮助我",
        })
        self.assertEqual(response.status_code, 422)

    def test_ai_chat_rejects_completed_test(self):
        response = self.client.post("/api/ai-chat", json={
            "test_id": "missing-test", "question_id": "OP001", "message": "请帮助我",
        })
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
