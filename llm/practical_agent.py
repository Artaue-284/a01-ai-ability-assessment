from __future__ import annotations

import ast
import json
import math
import operator
import urllib.request
from typing import Any

from llm.config import load_llm_config


class SafeCalculator:
    """只计算纯数值表达式，不允许名称、属性、调用或容器访问。"""

    _binary = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow,
    }
    _unary = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    @classmethod
    def evaluate(cls, expression: str) -> float:
        if len(expression) > 120:
            raise ValueError("表达式过长")
        tree = ast.parse(expression, mode="eval")

        def visit(node: ast.AST, depth: int = 0) -> float:
            if depth > 12:
                raise ValueError("表达式嵌套过深")
            if isinstance(node, ast.Expression):
                return visit(node.body, depth + 1)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                value = float(node.value)
            elif isinstance(node, ast.BinOp) and type(node.op) in cls._binary:
                left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
                if isinstance(node.op, ast.Pow) and (abs(right) > 10 or abs(left) > 1e6):
                    raise ValueError("幂运算超出安全范围")
                value = float(cls._binary[type(node.op)](left, right))
            elif isinstance(node, ast.UnaryOp) and type(node.op) in cls._unary:
                value = float(cls._unary[type(node.op)](visit(node.operand, depth + 1)))
            else:
                raise ValueError("仅允许纯数值四则运算")
            if not math.isfinite(value) or abs(value) > 1e12:
                raise ValueError("计算结果超出安全范围")
            return value

        return visit(tree)


class PracticalAgent:
    """带白名单工具的实操 Agent；不执行代码、系统命令或任意网络请求。"""

    MAX_TOOL_CALLS = 3

    def __init__(self) -> None:
        config = load_llm_config()
        self.base_url = config["ant_line_base_url"].rstrip("/")
        self.api_key = config["ant_line_api_key"]
        self.model = config["ant_line_model"] or "Ling-3.0-flash"

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @staticmethod
    def _tools() -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "calculate", "description": "计算纯数值算术表达式", "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"], "additionalProperties": False}}},
            {"type": "function", "function": {"name": "inspect_evidence", "description": "读取本题已上传证据的安全分析摘要", "parameters": {"type": "object", "properties": {"evidence_id": {"type": "string"}}, "required": ["evidence_id"], "additionalProperties": False}}},
            {"type": "function", "function": {"name": "list_evidence", "description": "列出本题可用证据及其分析状态", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
        ]

    @staticmethod
    def _execute(name: str, arguments: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        if name == "calculate":
            value = SafeCalculator.evaluate(str(arguments.get("expression", "")))
            return {"value": value}
        if name == "list_evidence":
            return {"items": [{"id": item["id"], "filename": item["filename"], "status": item.get("analysis_status") or "not-analyzed", "mode": item.get("analysis_mode") or ""} for item in evidence]}
        if name == "inspect_evidence":
            wanted = str(arguments.get("evidence_id", ""))
            item = next((item for item in evidence if item["id"] == wanted), None)
            if item is None:
                raise ValueError("证据不存在或不属于当前题目")
            return {"id": item["id"], "filename": item["filename"], "status": item.get("analysis_status") or "not-analyzed", "mode": item.get("analysis_mode") or "", "summary": (item.get("analysis_summary") or "")[:4000], "metadata": item.get("analysis_metadata") or {}}
        raise ValueError("工具不在白名单中")

    def run(self, question: dict[str, Any], instruction: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("当前实操 Agent 未配置")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "你是受控 AI 实操助手。只可调用提供的白名单工具；禁止要求或声称执行系统命令、任意代码、任意文件读取或网页访问。先完成必要工具调用，再用中文简洁报告结果、证据与限制。"},
            {"role": "user", "content": f"实操题：{question.get('question', '')}\n学员指令：{instruction}"},
        ]
        actions: list[dict[str, Any]] = []
        for _ in range(self.MAX_TOOL_CALLS + 1):
            payload = self._complete(messages)
            message = payload["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if not calls:
                content = str(message.get("content") or "").strip()
                if not content:
                    raise ValueError("模型没有返回实操结果")
                return {"status": "completed", "mode": "controlled-tool-agent", "model": self.model, "result": content, "actions": actions}
            if len(actions) + len(calls) > self.MAX_TOOL_CALLS:
                raise ValueError("模型工具调用次数超过限制")
            messages.append(message)
            for call in calls:
                function = call.get("function") or {}
                name = str(function.get("name") or "")
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                    output = self._execute(name, arguments, evidence)
                    action = {"tool": name, "arguments": arguments, "ok": True, "output": output}
                except Exception as exc:
                    output = {"error": str(exc)}
                    action = {"tool": name, "arguments": function.get("arguments", ""), "ok": False, "error": str(exc)}
                actions.append(action)
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(output, ensure_ascii=False)})
        raise ValueError("实操 Agent 未在限制轮次内完成")

    def _complete(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps({"model": self.model, "messages": messages, "tools": self._tools(), "tool_choice": "auto", "stream": False}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
