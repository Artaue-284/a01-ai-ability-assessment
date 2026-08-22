import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm.chat import AIAssistant
from llm.scorer import LLMScorer

import llm.config as llm_config


QUESTION = {
    "dimension": "prompt",
    "question": "请为会议纪要生成行动清单写一条提示词",
    "rubric": ["明确目标", "规定格式", "包含核验"],
    "max_score": 20,
    "keywords": ["行动清单", "表格"],
}


def make_config_file(key: str = "sk-test-key", base_url: str = "https://mock.example/v1", model: str = "qwen-plus") -> Path:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"api_key": key, "base_url": base_url, "model": model}, handle, ensure_ascii=False)
    return Path(path)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class AntLineChannelTests(unittest.TestCase):
    """ant-line（蚂蚁灵/百炼 OpenAI 兼容）通道测试：评分与 AI 助手均走 /chat/completions。"""

    def setUp(self):
        self.config = make_config_file()
        self.config_patch = patch.object(llm_config, "CONFIG_PATH", self.config)
        self.config_patch.start()
        self.env = patch.dict(os.environ, {
            "TBOX_TOKEN": "", "TBOX_APP_ID": "", "OPENAI_API_KEY": "",
            "OPENAI_BASE_URL": "", "OPENAI_MODEL": "",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.config_patch.stop()
        self.config.unlink(missing_ok=True)

    def test_scorer_uses_ant_line_chat_completions(self):
        payload = {"choices": [{"message": {"content": json.dumps({
            "score": 8, "rubric_met": ["明确目标"], "feedback": "结构清晰",
            "needs_review": False, "confidence": 0.9,
        }, ensure_ascii=False)}}]}
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload)) as request:
            scorer = LLMScorer()
            result = scorer.score(QUESTION, "请根据会议纪要生成行动清单，输出表格。")
        self.assertEqual(scorer.mode, "ant-line-api")
        self.assertEqual(result["score"], 8)
        self.assertEqual(result["model"], "ant-line:qwen-plus")
        sent = json.loads(request.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["model"], "qwen-plus")
        self.assertIn("chat/completions", request.call_args.args[0].full_url)
        self.assertEqual(request.call_args.args[0].headers["Authorization"], "Bearer sk-test-key")

    def test_scorer_falls_back_transparently_on_ant_line_failure(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError):
            result = LLMScorer().score(QUESTION, "请生成行动清单表格。")
        self.assertEqual(result["model"], "rubric-fallback-v1")
        self.assertIn("ant-line", result["warning"])

    def test_assistant_uses_ant_line_chat(self):
        payload = {"choices": [{"message": {"content": "请先明确任务目标与输出格式。"}}]}
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload)) as request:
            assistant = AIAssistant()
            result = assistant.chat(
                {"type": "dialogue", "question": "拆解一场300人AI讲座方案"},
                [{"role": "user", "message": "我想办讲座"}],
                "请帮我列出第一步",
            )
        self.assertEqual(assistant.mode, "ant-line-api")
        self.assertEqual(result["mode"], "ant-line-api")
        self.assertEqual(result["reply"], "请先明确任务目标与输出格式。")
        self.assertEqual(result["model"], "ant-line:qwen-plus")
        sent = json.loads(request.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["model"], "qwen-plus")
        self.assertEqual(sent["messages"][-1]["content"], "请帮我列出第一步")

    def test_env_variables_override_config_file(self):
        with patch.dict(os.environ, {"ANT_LINE_BASE_URL": "https://env.example/v1"}, clear=False):
            scorer = LLMScorer()
        self.assertEqual(scorer.ant_line_base_url, "https://env.example/v1")
        self.assertEqual(scorer.ant_line_api_key, "sk-test-key")


if __name__ == "__main__":
    unittest.main()
