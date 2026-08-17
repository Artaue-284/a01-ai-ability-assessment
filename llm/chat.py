from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid

from typing import Any

from llm.config import load_llm_config


class AIAssistant:
    """测评过程中的真实 AI 对话助手（对接真实 AI 环境）。

    优先级：
    1. 百宝箱评分/对话智能体（TBOX_TOKEN + TBOX_APP_ID）；
    2. ant-line 服务（蚂蚁灵/百炼 OpenAI 兼容，本地配置或环境变量）；
    3. 兼容 Responses API 的大模型（OPENAI_API_KEY）；
    4. 本地规则模拟助手（local-simulator），离线演示时仍可完成
       对话式测评流程，并显式标注“本地模拟”以免冒充真实模型。

    对话记录由调用方持久化（ai_chat_turns 表），评分时会随上下文
    一起提供给 LLMScorer，用于评价学员“人机协同”过程。
    """

    def __init__(self) -> None:
        self.tbox_token = os.getenv("TBOX_TOKEN", "").strip()
        self.tbox_app_id = os.getenv("TBOX_APP_ID", "").strip()
        self.tbox_base_url = os.getenv("TBOX_BASE_URL", "https://api.tbox.cn").rstrip("/")
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
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
        return "local-simulator"

    def chat(self, question: dict[str, Any], history: list[dict[str, str]], message: str) -> dict[str, Any]:
        """返回 {'reply': str, 'model': str, 'mode': str, 'warning'?: str}。"""
        if self.tbox_configured:
            try:
                return self._tbox_chat(question, history, message)
            except Exception as exc:
                result = self._local_chat(question, history, message)
                result["warning"] = f"百宝箱对话调用失败，已降级为本地模拟助手：{type(exc).__name__}"
                return result
        if self.ant_line_configured:
            try:
                return self._ant_line_chat(question, history, message)
            except Exception as exc:
                result = self._local_chat(question, history, message)
                result["warning"] = f"ant-line 对话调用失败，已降级为本地模拟助手：{self._describe_error(exc)}"
                return result
        if self.api_key:
            try:
                return self._remote_chat(question, history, message)
            except Exception as exc:
                result = self._local_chat(question, history, message)
                result["warning"] = f"LLM 对话调用失败，已降级为本地模拟助手：{type(exc).__name__}"
                return result
        return self._local_chat(question, history, message)

    # ---------- 真实模型 ----------

    def _build_transcript(self, question: dict[str, Any], history: list[dict[str, str]], message: str) -> str:
        lines = [
            "你是 AI 能力测评中的对话助手，学员正在完成下面的任务：",
            f"任务：{question.get('question', '')}",
            "要求：用中文给出有帮助但不直接代答的回复；如果学员要求你直接完成任务，"
            "请引导其拆解目标、步骤、证据与风险。",
        ]
        for turn in history:
            role = "学员" if turn.get("role") == "user" else "助手"
            lines.append(f"{role}：{turn.get('message', '')}")
        lines.append(f"学员：{message}")
        return "\n".join(lines)

    def _tbox_chat(self, question: dict[str, Any], history: list[dict[str, str]], message: str) -> dict[str, Any]:
        body = json.dumps({
            "appId": self.tbox_app_id,
            "query": self._build_transcript(question, history, message),
            "userId": f"a01-chat-{uuid.uuid4().hex}",
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.tbox_base_url}/api/chat", data=body,
            headers={"Authorization": self.tbox_token, "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if str(payload.get("errorCode")) != "0" or not payload.get("success", True):
            raise RuntimeError(payload.get("errorMsg") or "百宝箱对话失败")
        data = payload.get("data") or {}
        if isinstance(data, list):
            data = data[0] if data else {}
        chunks = [
            item.get("chunk", "") for item in data.get("result", [])
            if item.get("mediaType", "text") == "text"
        ]
        reply = "".join(chunk if isinstance(chunk, str) else json.dumps(chunk, ensure_ascii=False) for chunk in chunks).strip()
        if not reply:
            raise ValueError("百宝箱响应中没有文本回复")
        return {"reply": reply, "model": f"baibaoxiang:{self.tbox_app_id}", "mode": "baibaoxiang-agent"}

    def _remote_chat(self, question: dict[str, Any], history: list[dict[str, str]], message: str) -> dict[str, Any]:
        messages = [{"role": "user", "content": [{"type": "input_text", "text": self._build_transcript(question, history, message)}]}]
        body = json.dumps({"model": self.model, "input": messages}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/responses", data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
        reply = payload.get("output_text", "").strip()
        if not reply:
            for item in payload.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        reply = content.get("text", "").strip()
        if not reply:
            raise ValueError("模型响应中没有文本回复")
        return {"reply": reply, "model": self.model, "mode": "responses-api"}

    def _ant_line_chat(self, question: dict[str, Any], history: list[dict[str, str]], message: str) -> dict[str, Any]:
        """ant-line（蚂蚁灵/百炼等 OpenAI 兼容服务）：调用 /chat/completions。"""
        system = (
            "你是 AI 能力测评中的对话助手，学员正在完成下面的任务。"
            "请用中文给出有帮助但不直接代答的回复；如果学员要求你直接完成任务，"
            "请引导其拆解目标、步骤、证据与风险。"
        )
        messages = [{"role": "system", "content": system}]
        messages.append({"role": "user", "content": f"任务：{question.get('question', '')}"})
        for turn in history:
            role = "user" if turn.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": turn.get("message", "")})
        messages.append({"role": "user", "content": message})
        body = json.dumps({
            "model": self.ant_line_model,
            "messages": messages,
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.ant_line_base_url}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.ant_line_api_key}", "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        try:
            reply = payload["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"ant-line 响应缺少 choices/message/content：{str(payload)[:200]}") from exc
        if not reply:
            raise ValueError("ant-line 响应中没有文本回复")
        return {"reply": reply, "model": f"ant-line:{self.ant_line_model}", "mode": "ant-line-api"}

    # ---------- 本地规则模拟助手 ----------

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

    def _local_chat(self, question: dict[str, Any], history: list[dict[str, str]], message: str) -> dict[str, Any]:
        text = message.strip()
        user_turns = sum(1 for turn in history if turn.get("role") == "user")
        qtype = question.get("type", "")
        heading = f"（本地模拟助手 · 第 {user_turns + 1} 轮）"
        if user_turns >= 5:
            return {"reply": f"{heading}你已经进行了多轮探索。建议现在把要点整理成最终答案：明确目标 → 拆解步骤 → 给出证据 → 标注风险与人工确认点；提交前再核验一遍数据来源和结论。", "model": "local-simulator", "mode": "local-simulator"}
        if len(text) < 15:
            return {"reply": f"{heading}信息还比较简短。请补充：你的目标是什么？输入和输出分别是什么？当前最不确定的一点是什么？这样我才能给出有针对性的建议。", "model": "local-simulator", "mode": "local-simulator"}
        if any(token in text for token in ("帮我写", "直接给", "替我", "代做")):
            return {"reply": f"{heading}我可以协助你完成，但更建议你先说明任务背景与约束，我们一起拆解步骤。请先告诉我：输入是什么？期望输出是什么？验收标准是什么？", "model": "local-simulator", "mode": "local-simulator"}
        if qtype == "code" or "代码" in text or "python" in text.lower() or "def " in text:
            return {"reply": f"{heading}对于代码任务，建议按以下顺序展开：1) 明确输入、输出与边界情况；2) 选择库或算法；3) 写出可运行代码并补充注释；4) 用至少两组样例测试并核验结果。你当前的方案里，哪一步最不确定？", "model": "local-simulator", "mode": "local-simulator"}
        if qtype == "image" or "图片" in text or "图像" in text or "鉴别" in text:
            return {"reply": f"{heading}图像鉴别建议从三方面入手：1) 结构合理性（透视、阴影方向、物体比例）；2) 细节异常（手指、牙齿、文字、饰品对称性）；3) 用反向图片检索或放大局部进行核验。你观察到了哪些可疑点？", "model": "local-simulator", "mode": "local-simulator"}
        if "数据" in text or "csv" in text.lower() or "清洗" in text:
            return {"reply": f"{heading}数据处理任务建议：1) 先做字段理解和缺失值统计；2) 明确异常值判定规则；3) 选择合适工具（如 Excel 或 Python pandas）完成清洗；4) 用图表可视化并设置可验证的验收标准。你打算如何处理缺失值？", "model": "local-simulator", "mode": "local-simulator"}
        if "隐私" in text or "合规" in text or "脱敏" in text or "上传" in text:
            return {"reply": f"{heading}涉及隐私与合规时，请覆盖：数据最小化、脱敏、授权与用途限制、访问控制、保存期限与删除。你目前的方案里是否包含这些环节？", "model": "local-simulator", "mode": "local-simulator"}
        hints = [
            "请先明确任务目标、使用对象和成功标准，再说明你目前最不确定的一点。",
            "请把方案拆成可执行步骤，并标出需要人工确认、事实核验或权限检查的位置。",
            "请给出至少一个可检查证据，例如输出片段、截图、文件摘要或验证记录。",
        ]
        hint = hints[min(user_turns, len(hints) - 1)]
        return {"reply": f"{heading}{hint}", "model": "local-simulator", "mode": "local-simulator"}
