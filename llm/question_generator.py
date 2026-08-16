from __future__ import annotations

import json
import os
import urllib.request
import uuid


DIMENSION_NAMES = {
    "basic": "AI基础认知",
    "prompt": "提示词工程",
    "tools": "AI工具使用",
    "evaluation": "结果评估与优化",
    "collaboration": "人机协同",
    "ethics": "伦理与合规",
}

TYPE_NAMES = {
    "single_choice": "单项选择题",
    "open_text": "开放作答题",
    "practical": "实操任务",
}


class TBoxQuestionGenerator:
    """百宝箱题库教研智能体适配器，只生成待教师审核的草稿。"""

    def __init__(self) -> None:
        self.token = os.getenv("TBOX_QUESTION_TOKEN", "").strip()
        self.app_id = os.getenv("TBOX_QUESTION_APP_ID", "202608AP9YhY21462248").strip()
        self.base_url = os.getenv("TBOX_BASE_URL", "https://api.tbox.cn").rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.token and self.app_id)

    def generate(self, dimension: str, question_type: str, difficulty: int, count: int = 1) -> list[dict]:
        if not self.configured:
            raise RuntimeError("题库智能体尚未配置令牌和 APP ID")
        if dimension not in DIMENSION_NAMES:
            raise ValueError("能力维度无效")
        if question_type not in TYPE_NAMES:
            raise ValueError("题型无效")
        if not 1 <= difficulty <= 5 or not 1 <= count <= 5:
            raise ValueError("难度或生成数量超出范围")

        instruction = {
            "任务": "生成AI能力测评题目草稿，仅输出JSON对象，不要Markdown或解释文字",
            "能力维度": f"{dimension} / {DIMENSION_NAMES[dimension]}",
            "题型": f"{question_type} / {TYPE_NAMES[question_type]}",
            "难度": difficulty,
            "数量": count,
            "业务场景": "校企联合AI能力培养与测评，面向高校学生",
            "质量要求": [
                "题干清晰、只有一个主要考查点，不依赖临时新闻或冷僻记忆",
                "选项题提供4个互斥选项，answer必须与正确选项文字完全一致",
                "开放题或实操题提供3至5条可观察、可评分的rubric",
                "解析说明正确答案理由及常见错误，避免暗示性和歧视性表述",
            ],
            "输出格式": {
                "items": [{
                    "question": "题干",
                    "options": ["选项A", "选项B", "选项C", "选项D"],
                    "answer": "正确选项全文；非选择题为null",
                    "explanation": "解析",
                    "tags": ["标签1", "标签2"],
                    "rubric": ["评分点1", "评分点2", "评分点3"],
                    "keywords": ["关键词1", "关键词2"],
                }],
            },
        }
        body = json.dumps({
            "appId": self.app_id,
            "query": json.dumps(instruction, ensure_ascii=False),
            "userId": f"a01-question-{uuid.uuid4().hex}",
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Authorization": self.token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if str(payload.get("errorCode")) != "0" or not payload.get("success", True):
            raise RuntimeError(payload.get("errorMsg") or "百宝箱题库生成失败")
        result = self._parse_result(payload)
        items = result.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("题库智能体未返回有效的 items 数组")
        if len(items) < count:
            raise ValueError(f"题库智能体只返回 {len(items)} 题，少于请求的 {count} 题")
        return [self._normalize(item, dimension, question_type, difficulty) for item in items[:count]]

    @staticmethod
    def _parse_result(payload: dict) -> dict:
        data = payload.get("data") or {}
        if isinstance(data, list):
            data = data[0] if data else {}
        chunks = [
            item.get("chunk", "") for item in data.get("result", [])
            if item.get("mediaType", "text") == "text"
        ]
        text = "".join(chunk if isinstance(chunk, str) else json.dumps(chunk, ensure_ascii=False) for chunk in chunks).strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("题库智能体响应中没有有效JSON")
            value = json.loads(text[start:end + 1])
        if not isinstance(value, dict):
            raise ValueError("题库智能体结果必须是JSON对象")
        return value

    def _normalize(self, raw: object, dimension: str, question_type: str, difficulty: int) -> dict:
        if not isinstance(raw, dict):
            raise ValueError("题目草稿必须是JSON对象")

        def text_list(value: object, preferred_keys: tuple[str, ...] = ()) -> list[str]:
            if not isinstance(value, list):
                return []
            normalized = []
            for entry in value:
                if isinstance(entry, dict):
                    text = next((entry.get(key) for key in preferred_keys if entry.get(key)), "")
                else:
                    text = entry
                text = str(text).strip()
                if text:
                    normalized.append(text)
            return normalized

        question = str(raw.get("question", "")).strip()
        explanation = str(raw.get("explanation", "")).strip()
        if len(question) < 5 or len(explanation) < 2:
            raise ValueError("题干或解析过短")
        options = [str(item).strip() for item in raw.get("options", []) if str(item).strip()]
        answer = raw.get("answer")
        answer = str(answer).strip() if answer is not None else None
        rubric = text_list(raw.get("rubric", []), ("point", "criterion", "description", "text"))
        if question_type == "single_choice":
            if len(options) != 4 or len(set(options)) != 4 or answer not in options:
                raise ValueError("选择题必须包含4个不同选项，且答案须与其中一个选项完全一致")
            rubric = []
        else:
            options, answer = [], None
            if len(rubric) < 3:
                raise ValueError("开放题或实操题至少需要3条评分量表")
        prefix = {"basic": "BA", "prompt": "PR", "tools": "TO", "evaluation": "EV", "collaboration": "CO", "ethics": "ET"}[dimension]
        return {
            "id": f"AI{prefix}{uuid.uuid4().hex[:8].upper()}",
            "dimension": dimension,
            "difficulty": difficulty,
            "type": question_type,
            "question": question,
            "options": options,
            "answer": answer,
            "explanation": explanation,
            "tags": text_list(raw.get("tags", []), ("name", "text"))[:8],
            "ability_level": f"L{difficulty}",
            "discrimination": 1.0,
            "max_score": 10 if question_type == "single_choice" else 20,
            "rubric": rubric[:8],
            "keywords": text_list(raw.get("keywords", []), ("name", "text"))[:12],
            "changed_by": "百宝箱题库智能体（待教师审核）",
            "draft": True,
            "source_model": f"baibaoxiang:{self.app_id}",
        }
