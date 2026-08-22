from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


class TBoxDialogueUnavailable(RuntimeError):
    """A safe, user-facing classification of a failed remote dialogue call."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TBoxDialogueCoach:
    """Real-model process guidance with explicit replay of the saved dialogue context.

    The scoring agent token is reused by default.  Each turn sends all prior turns,
    so continuity does not depend on undocumented server-side conversation state.
    There is deliberately no automatic retry: a failed/quota-exhausted call cannot
    repeatedly consume quota.
    """

    def __init__(self) -> None:
        self.token = os.getenv("TBOX_DIALOGUE_TOKEN", os.getenv("TBOX_TOKEN", "")).strip()
        self.app_id = os.getenv(
            "TBOX_DIALOGUE_APP_ID",
            os.getenv("TBOX_APP_ID", "202608AP95fB21469777"),
        ).strip()
        self.base_url = os.getenv("TBOX_BASE_URL", "https://api.tbox.cn").rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.token and self.app_id)

    @property
    def mode(self) -> str:
        return "baibaoxiang-context-replay" if self.configured else "structured-guidance-local"

    @staticmethod
    def _stable_user_id(test_id: str, question_id: str) -> str:
        digest = hashlib.sha256(f"{test_id}:{question_id}".encode("utf-8")).hexdigest()[:24]
        return f"a01-dialogue-{digest}"

    @staticmethod
    def _response_text(payload: dict[str, Any]) -> str:
        if str(payload.get("errorCode")) != "0" or not payload.get("success", True):
            raise TBoxDialogueUnavailable(
                TBoxDialogueCoach._classify_error(str(payload.get("errorMsg") or "百宝箱调用失败")),
                str(payload.get("errorMsg") or "百宝箱调用失败"),
            )
        data = payload.get("data") or {}
        if isinstance(data, list):
            data = data[0] if data else {}
        chunks = [
            item.get("chunk", "") for item in data.get("result", [])
            if item.get("mediaType", "text") == "text"
        ]
        text = "".join(
            chunk if isinstance(chunk, str) else json.dumps(chunk, ensure_ascii=False)
            for chunk in chunks
        ).strip()
        if not text:
            raise TBoxDialogueUnavailable("invalid-response", "百宝箱响应中没有文本内容")
        return text

    @staticmethod
    def _classify_error(message: str, status: int | None = None) -> str:
        lowered = message.lower()
        if status in {402, 429} or any(word in lowered for word in ("额度", "余额", "quota", "credit", "限流")):
            return "quota-or-rate-limit"
        if status in {401, 403} or any(word in lowered for word in ("token", "unauthorized", "forbidden", "鉴权")):
            return "configuration-invalid"
        return "remote-unavailable"

    @staticmethod
    def _extract_guidance(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            value = json.loads(cleaned[start:end + 1]) if start >= 0 and end > start else None
        if isinstance(value, dict):
            guidance = value.get("guidance") or value.get("feedback") or value.get("next_question")
            if guidance:
                cleaned = str(guidance).strip()
        # 模型偶发输出工具调用 / Agent 结构化标记——剥离并保留可读文本
        if re.search(r"<tool_call|<arg_key|<arg_value|</arg_", cleaned):
            values = re.findall(r"<arg_value>([\s\S]*?)</arg_value>", cleaned)
            readable = [v.strip() for v in values if v.strip()]
            if readable:
                cleaned = " ".join(readable)[:800]
            else:
                cleaned = re.sub(r"</?(tool_call|arg_key|arg_value|function_call|result|state|transition)>", "", cleaned)
                cleaned = re.sub(r"<[^>]+>", "", cleaned).strip()
        if not cleaned:
            raise TBoxDialogueUnavailable("invalid-response", "百宝箱未返回可用的过程引导")
        return cleaned[:800]

    def guide(
        self,
        *,
        test_id: str,
        question: dict[str, Any],
        history: list[dict[str, Any]],
        message: str,
    ) -> str:
        if not self.configured:
            raise TBoxDialogueUnavailable("not-configured", "百宝箱连续对话尚未配置")
        transcript = []
        for item in history[-5:]:
            transcript.append({"学员": item["user_message"], "引导": item["assistant_message"]})
        prompt = {
            "能力维度": question.get("dimension", ""),
            "题目": question.get("question", ""),
            "评分量表": ["目标与成功标准明确", "步骤可执行", "提供可核验证据", "识别边界和风险"],
            "满分": 20,
            "历史过程对话": transcript,
            "学员本轮作答": message,
            "要求": (
                "这是连续过程辅导，不是最终评分。结合历史对话，只在 feedback 字段给出下一步引导；"
                "每次只给出当前这一轮的引导，不要一次性输出多轮引导计划，"
                "不得泄露参考答案，不得代做，指出一项缺口并提出一个追问，中文不超过120字。"
            ),
        }
        body = json.dumps({
            "appId": self.app_id,
            "query": json.dumps(prompt, ensure_ascii=False),
            "userId": self._stable_user_id(test_id, str(question.get("id", "unknown"))),
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Authorization": self.token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except OSError:
                detail = str(exc)
            raise TBoxDialogueUnavailable(self._classify_error(detail, exc.code), "百宝箱远程对话暂不可用") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TBoxDialogueUnavailable("remote-unavailable", "百宝箱网络或服务暂不可用") from exc
        except json.JSONDecodeError as exc:
            raise TBoxDialogueUnavailable("invalid-response", "百宝箱返回了无法解析的响应") from exc
        return self._extract_guidance(self._response_text(payload))
