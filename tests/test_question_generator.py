import json
import os
import unittest
from unittest.mock import patch

from llm.question_generator import TBoxQuestionGenerator


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class QuestionGeneratorTests(unittest.TestCase):
    def test_tbox_choice_draft_is_normalized(self):
        generated = {
            "items": [{
                "question": "核验AI给出的重要统计数据时，第一步应该做什么？",
                "options": ["直接采用", "查找原始来源", "修改数字", "删除结论"],
                "answer": "查找原始来源",
                "explanation": "重要数据应先追溯并核对权威原始来源。",
                "tags": ["事实核验"],
                "rubric": [],
                "keywords": ["来源"],
            }],
        }
        response = {
            "errorCode": "0",
            "success": True,
            "data": {"result": [{"mediaType": "text", "chunk": json.dumps(generated, ensure_ascii=False)}]},
        }
        with patch.dict(os.environ, {
            "TBOX_QUESTION_TOKEN": "question-token",
            "TBOX_QUESTION_APP_ID": "question-app",
        }, clear=False), patch("urllib.request.urlopen", return_value=FakeResponse(response)) as request:
            item = TBoxQuestionGenerator().generate("evaluation", "single_choice", 2, 1)[0]
        self.assertTrue(item["draft"])
        self.assertEqual(item["source_model"], "baibaoxiang:question-app")
        self.assertEqual(item["answer"], "查找原始来源")
        self.assertEqual(len(item["options"]), 4)
        self.assertTrue(item["id"].startswith("AIEV"))
        sent = json.loads(request.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(sent["appId"], "question-app")
        self.assertFalse(sent["stream"])

    def test_invalid_choice_is_rejected(self):
        generator = TBoxQuestionGenerator()
        with self.assertRaisesRegex(ValueError, "4个不同选项"):
            generator._normalize({
                "question": "这是一道不完整的选择题？",
                "options": ["A", "B"],
                "answer": "A",
                "explanation": "选项不足。",
            }, "basic", "single_choice", 1)

    def test_object_rubric_is_converted_to_readable_points(self):
        item = TBoxQuestionGenerator()._normalize({
            "question": "请说明如何核验AI生成报告中的事实与逻辑问题。",
            "options": [],
            "answer": None,
            "explanation": "需要同时检查事实来源与推理链条。",
            "rubric": [
                {"point": "使用独立可信来源交叉验证", "score": 4},
                {"criterion": "检查因果关系与上下文连贯性", "score": 4},
                {"description": "给出可执行的修订步骤", "score": 2},
            ],
            "tags": ["结果评估"],
            "keywords": ["交叉验证"],
        }, "evaluation", "open_text", 2)
        self.assertEqual(item["rubric"], [
            "使用独立可信来源交叉验证",
            "检查因果关系与上下文连贯性",
            "给出可执行的修订步骤",
        ])


if __name__ == "__main__":
    unittest.main()
