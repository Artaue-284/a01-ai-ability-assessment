from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid

from llm.config import load_llm_config


class LLMScorer:
    """结构化开放题评分器。

    优先调用百宝箱评分智能体，其次调用 ant-line（蚂蚁灵/百炼 OpenAI 兼容）
    或兼容 Responses API 的模型；未配置时使用透明、可复现的 rubric 规则评分，
    不会把本地结果伪装成真实模型结果。
    """

    def __init__(self) -> None:
        self.tbox_token = os.getenv("TBOX_TOKEN", "").strip()
        self.tbox_app_id = os.getenv("TBOX_APP_ID", "").strip()
        self.tbox_base_url = os.getenv("TBOX_BASE_URL", "https://api.tbox.cn").rstrip("/")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
        ant_line = load_llm_config()
        self.ant_line_base_url = ant_line["ant_line_base_url"].rstrip("/")
        self.ant_line_api_key = ant_line["ant_line_api_key"]
        self.ant_line_model = ant_line["ant_line_model"] or "qwen-plus"

    @property
    def tbox_configured(self) -> bool:
        return bool(self.tbox_token and self.tbox_app_id)

    @property
    def ant_line_configured(self) -> bool:
        return bool(self.ant_line_api_key and self.ant_line_base_url)

    @property
    def mode(self) -> str:
        if self.tbox_configured:
            return "baibaoxiang-agent"
        if self.ant_line_configured:
            return "ant-line-api"
        if self.api_key:
            return "responses-api"
        return "local-rubric"

    def score(self, question: dict, answer: str, context: str = "") -> dict:
        if self.tbox_configured:
            try:
                return self._tbox_score(question, answer, context)
            except Exception as exc:
                result = self._rubric_score(question, answer, context)
                result["warning"] = f"百宝箱调用失败，已降级为规则评分：{type(exc).__name__}"
                return result
        if self.ant_line_configured:
            try:
                return self._ant_line_score(question, answer, context)
            except Exception as exc:
                result = self._rubric_score(question, answer, context)
                result["warning"] = f"ant-line 调用失败，已降级为规则评分：{self._describe_error(exc)}"
                return result
        if self.api_key:
            try:
                return self._remote_score(question, answer, context)
            except Exception as exc:
                result = self._rubric_score(question, answer, context)
                result["warning"] = f"LLM 调用失败，已降级为规则评分：{type(exc).__name__}"
                return result
        return self._rubric_score(question, answer, context)

    def _rubric_score(self, question: dict, answer: str, context: str = "") -> dict:
        rubric = question.get("rubric", [])
        keywords = question.get("keywords", [])
        normalized = answer.lower().strip()
        hits = [word for word in keywords if word.lower() in normalized]
        coverage = len(hits) / max(1, len(keywords))
        length_factor = min(1.0, len(normalized) / 120)
        structure = min(1.0, sum(token in answer for token in ("1", "2", "首先", "其次", "最后", "步骤")) / 2)
        ratio = 0.65 * coverage + 0.2 * length_factor + 0.15 * structure
        # 人机协同证据：对话式/实操任务中真实与 AI 的协作过程计入得分（不冒充模型评分）。
        if context:
            assistant_turns = context.count("AI助手")
            ratio = min(1.0, ratio + 0.05 * min(1.0, assistant_turns / 3))
        max_score = float(question.get("max_score", 20))
        score = round(max_score * ratio, 1)
        met = rubric[: round(len(rubric) * ratio)]
        return {
            "score": score, "max_score": max_score, "model": "rubric-fallback-v1",
            "rubric_met": met, "keyword_evidence": hits,
            "feedback": "已覆盖部分关键要点。" if ratio >= 0.5 else "回答较少覆盖评分要点，请补充具体步骤、验证方法和约束。",
            "needs_review": True,
        }

    @staticmethod
    def _describe_error(exc: Exception) -> str:
        """把调用异常转换为可诊断的文本（含 HTTP 状态码与响应片段）。"""
        if isinstance(exc, urllib.error.HTTPError):
            body = ""
            try:
                body = exc.read().decode("utf-8", "ignore")[:200].replace("\n", " ")
            except Exception:
                pass
            return f"HTTP {exc.code} {body}"
        if isinstance(exc, urllib.error.URLError):
            return f"网络错误：{exc.reason}"
        return type(exc).__name__

    @staticmethod
    def _normalize_remote_result(result: dict, question: dict, model: str) -> dict:
        max_score = float(question.get("max_score", 20))
        score = max(0.0, min(max_score, float(result["score"])))
        rubric_met = result.get("rubric_met", [])
        if not isinstance(rubric_met, list):
            raise ValueError("rubric_met 必须是数组")
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
        needs_review = bool(result.get("needs_review", confidence < 0.75))
        if confidence < 0.75:
            needs_review = True
        return {
            "score": score,
            "max_score": max_score,
            "model": model,
            "rubric_met": rubric_met,
            "feedback": str(result.get("feedback", "")),
            "needs_review": needs_review,
            "confidence": confidence,
        }

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise
            value = json.loads(cleaned[start:end + 1])
        if not isinstance(value, dict):
            raise ValueError("评分结果必须是 JSON 对象")
        return value

    def _tbox_score(self, question: dict, answer: str, context: str = "") -> dict:
        prompt = {
            "能力维度": question.get("dimension", ""),
            "题目": question["question"],
            "评分量表": question.get("rubric", []),
            "满分": question.get("max_score", 20),
            "学员作答": answer,
        }
        if context:
            prompt["人机对话过程（学员与AI助手的协作记录）"] = context
            prompt["要求"] = "结合对话过程评价学员的人机协同能力，但分数上限仍由评分量表决定。"
        body = json.dumps({
            "appId": self.tbox_app_id,
            "query": json.dumps(prompt, ensure_ascii=False),
            "userId": f"a01-score-{uuid.uuid4().hex}",
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.tbox_base_url}/api/chat", data=body,
            headers={"Authorization": self.tbox_token, "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if str(payload.get("errorCode")) != "0" or not payload.get("success", True):
            raise RuntimeError(payload.get("errorMsg") or "百宝箱评分失败")
        data = payload.get("data") or {}
        if isinstance(data, list):
            data = data[0] if data else {}
        chunks = [
            item.get("chunk", "") for item in data.get("result", [])
            if item.get("mediaType", "text") == "text"
        ]
        text = "".join(chunk if isinstance(chunk, str) else json.dumps(chunk, ensure_ascii=False) for chunk in chunks)
        if not text:
            raise ValueError("百宝箱响应中没有文本评分结果")
        return self._normalize_remote_result(
            self._parse_json_object(text), question, f"baibaoxiang:{self.tbox_app_id}",
        )

    def _remote_score(self, question: dict, answer: str, context: str = "") -> dict:
        prompt = {
            "题目": question["question"], "评分点": question.get("rubric", []),
            "满分": question.get("max_score", 20), "作答": answer,
            "要求": "严格依据评分点，输出 JSON：score, rubric_met, feedback, needs_review。",
        }
        if context:
            prompt["人机对话过程"] = context
            prompt["要求"] += " 结合对话过程评价人机协同能力，但分数上限由评分量表决定。"
        body = json.dumps({
            "model": self.model,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": json.dumps(prompt, ensure_ascii=False)}]}],
            "text": {"format": {"type": "json_object"}},
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/responses", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = payload.get("output_text")
        if not text:
            for item in payload.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text": text = content.get("text")
        return self._normalize_remote_result(json.loads(text), question, self.model)

    def _ant_line_score(self, question: dict, answer: str, context: str = "") -> dict:
        """ant-line（蚂蚁灵/百炼等 OpenAI 兼容服务）：调用 /chat/completions。"""
        prompt = {
            "能力维度": question.get("dimension", ""),
            "题目": question["question"],
            "评分量表": question.get("rubric", []),
            "满分": question.get("max_score", 20),
            "学员作答": answer,
        }
        if context:
            prompt["人机对话过程"] = context
            prompt["要求"] = "结合对话过程评价学员的人机协同能力，但分数上限仍由评分量表决定。"
        system = (
            "你是 AI 能力测评评分专家。请严格依据评分量表评分，不因措辞华丽加分。"
            "只输出 JSON 对象：{\"score\": 数字, \"rubric_met\": [字符串数组], "
            "\"feedback\": \"改进建议\", \"needs_review\": 布尔, \"confidence\": 0到1}。"
            "score 必须是 0 到满分之间的数字。"
        )
        body = json.dumps({
            "model": self.ant_line_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.ant_line_base_url}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.ant_line_api_key}", "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"ant-line 响应缺少 choices/message/content：{str(payload)[:200]}") from exc
        return self._normalize_remote_result(self._parse_json_object(text), question, f"ant-line:{self.ant_line_model}")
