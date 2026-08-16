import json
import os
import unittest
from unittest.mock import patch

from llm.scorer import LLMScorer


QUESTION = {
    "dimension": "ethics",
    "question": "是否可以直接上传包含姓名和手机号的名单？",
    "rubric": ["识别隐私风险", "先脱敏", "使用获批工具"],
    "max_score": 10,
    "keywords": ["隐私", "脱敏"],
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class ScorerTests(unittest.TestCase):
    def test_tbox_response_is_parsed_and_clamped(self):
        response = {
            "errorCode": "0",
            "success": True,
            "data": {
                "result": [{
                    "mediaType": "text",
                    "chunk": json.dumps({
                        "score": 12,
                        "rubric_met": ["识别隐私风险", "先脱敏"],
                        "feedback": "已识别风险并提出脱敏。",
                        "needs_review": False,
                        "confidence": 0.92,
                    }, ensure_ascii=False),
                }],
            },
        }
        with patch.dict(os.environ, {
            "TBOX_TOKEN": "test-token",
            "TBOX_APP_ID": "test-app",
            "OPENAI_API_KEY": "",
        }, clear=False), patch("urllib.request.urlopen", return_value=FakeResponse(response)) as request:
            result = LLMScorer().score(QUESTION, "不能直接上传，应先脱敏。")
        self.assertEqual(result["score"], 10)
        self.assertEqual(result["model"], "baibaoxiang:test-app")
        self.assertEqual(result["confidence"], 0.92)
        self.assertFalse(result["needs_review"])
        sent = json.loads(request.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["appId"], "test-app")
        self.assertFalse(sent["stream"])

    def test_low_confidence_forces_review(self):
        result = LLMScorer._normalize_remote_result({
            "score": 4,
            "rubric_met": [],
            "feedback": "证据不足",
            "needs_review": False,
            "confidence": 0.5,
        }, QUESTION, "test")
        self.assertTrue(result["needs_review"])

    def test_tbox_failure_falls_back_transparently(self):
        with patch.dict(os.environ, {
            "TBOX_TOKEN": "test-token",
            "TBOX_APP_ID": "test-app",
            "OPENAI_API_KEY": "",
        }, clear=False), patch("urllib.request.urlopen", side_effect=TimeoutError):
            result = LLMScorer().score(QUESTION, "隐私数据应先脱敏")
        self.assertEqual(result["model"], "rubric-fallback-v1")
        self.assertIn("百宝箱调用失败", result["warning"])


if __name__ == "__main__":
    unittest.main()
