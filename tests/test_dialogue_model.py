import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from llm.dialogue import TBoxDialogueCoach, TBoxDialogueUnavailable


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class DialogueModelTests(unittest.TestCase):
    def _coach(self):
        with patch.dict("os.environ", {"TBOX_TOKEN": "secret", "TBOX_APP_ID": "app-1"}, clear=False):
            return TBoxDialogueCoach()

    def test_real_mode_replays_history_without_exposing_token(self):
        coach = self._coach()
        payload = {
            "success": True,
            "errorCode": "0",
            "data": {"result": [{"mediaType": "text", "chunk": '{"feedback":"请补充可核验的成功标准。"}'}]},
        }
        with patch("urllib.request.urlopen", return_value=_Response(payload)) as opened:
            guidance = coach.guide(
                test_id="test-1",
                question={"id": "PT001", "dimension": "tools", "question": "完成一次AI任务"},
                history=[{"user_message": "先确定目标", "assistant_message": "目标如何衡量？"}],
                message="我准备用提示词完成",
            )
        self.assertEqual(guidance, "请补充可核验的成功标准。")
        sent = json.loads(opened.call_args.args[0].data.decode("utf-8"))
        query = json.loads(sent["query"])
        self.assertEqual(query["历史过程对话"][0]["学员"], "先确定目标")
        self.assertNotIn("secret", opened.call_args.args[0].data.decode("utf-8"))

    def test_quota_error_is_classified_and_not_retried(self):
        coach = self._coach()
        error = urllib.error.HTTPError("https://api.tbox.cn/api/chat", 429, "limit", {}, io.BytesIO("额度已用完".encode("utf-8")))
        with patch("urllib.request.urlopen", side_effect=error) as opened:
            with self.assertRaises(TBoxDialogueUnavailable) as caught:
                coach.guide(
                    test_id="test-1",
                    question={"id": "PT001", "question": "任务"},
                    history=[],
                    message="开始",
                )
        self.assertEqual(caught.exception.code, "quota-or-rate-limit")
        self.assertEqual(opened.call_count, 1)


if __name__ == "__main__":
    unittest.main()
