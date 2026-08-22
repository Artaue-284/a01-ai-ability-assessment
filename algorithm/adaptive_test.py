from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any


DIMENSIONS = ("basic", "prompt", "tools", "evaluation", "collaboration", "ethics")

# 每场测评末尾固定追加的主观题型：开放作答 + 实操任务 + 对话式任务。
# 题库含代码/图像题型时自动纳入；题库缺少目标题型时引擎按可用性自动回退。
# 15 题场只取前 3 类（客观题占比不变），18/25 题场完整纳入 5 类。
TAIL_TYPES = (("open_text", 2), ("practical", 3), ("dialogue", 3), ("code", 3), ("image", 3))

# 训练资源：用于在报告中给出可落地的学习与练习建议。
TRAINING_RESOURCES = {
    "basic": {
        "name": "AI 基础认知",
        "resources": [
            {"title": "《AI 速览：大模型基础概念》", "url": "https://www.promptingguide.ai/zh", "practice": "用 3 句话向同学解释什么是大模型幻觉"},
            {"title": "AI 伦理与安全入门", "url": "https://www.aicourse.com/zh/ai-ethics", "practice": "列出 5 个不得上传给公共 AI 的数据类型"},
        ],
    },
    "prompt": {
        "name": "提示词工程",
        "resources": [
            {"title": "Prompt Engineering Guide（中文）", "url": "https://www.promptingguide.ai/zh", "practice": "为同一任务写 3 版提示词并对比输出质量"},
            {"title": "提示词模式库", "url": "https://learnprompting.org/zh-Hans/", "practice": "用少样本示例让 AI 按固定格式输出"},
        ],
    },
    "tools": {
        "name": "AI 工具使用",
        "resources": [
            {"title": "办公 AI 插件与数据分析工具清单", "url": "https://www.aicourse.com/zh/ai-tools", "practice": "用 AI 辅助完成一次 Excel/CSV 数据清洗"},
            {"title": "代码生成工具实战", "url": "https://docs.github.com/zh/copilot", "practice": "让 AI 生成一段脚本并人工核验结果"},
        ],
    },
    "evaluation": {
        "name": "结果评估与优化",
        "resources": [
            {"title": "事实核验与 AI 幻觉识别练习", "url": "https://www.promptingguide.ai/zh/risks", "practice": "对 AI 回答做一次多来源交叉验证并写核验记录"},
            {"title": "评测集与迭代方法", "url": "https://learnprompting.org/zh-Hans/", "practice": "建立 5 条用例的小评测集，比较两版提示词"},
        ],
    },
    "collaboration": {
        "name": "人机协同",
        "resources": [
            {"title": "人机协作工作流设计案例", "url": "https://www.aicourse.com/zh/collaboration", "practice": "把本周一个任务拆成人机分工并设置检查点"},
            {"title": "AI 项目管理实践", "url": "https://www.aicourse.com/zh/ai-project", "practice": "为你的方案补上异常处理与人工升级路径"},
        ],
    },
    "ethics": {
        "name": "伦理与合规",
        "resources": [
            {"title": "数据合规与隐私保护指南", "url": "https://www.aicourse.com/zh/privacy", "practice": "对一份含个人信息的数据做脱敏方案"},
            {"title": "生成内容负责任使用规范", "url": "https://www.aicourse.com/zh/ai-ethics", "practice": "为 AI 生成内容标注来源与复核责任"},
        ],
    },
}


class AdaptiveTestEngine:
    """分层随机 + 自适应补测引擎。

    前 12 题确保六维基础覆盖；后续根据维度置信度、正确率和用时补测，
    最后固定加入开放题和实操题。题库扩展到千题时无需修改算法。
    """

    def __init__(self, questions: list[dict], state: dict[str, Any] | None = None, seed: str | int | None = None):
        self.questions = questions
        self.by_id = {q["id"]: q for q in questions}
        self.random = random.Random(seed)
        self.state = state or self.initial_state()

    @staticmethod
    def initial_state(target_questions: int = 18) -> dict[str, Any]:
        return {
            "scores": {key: 50.0 for key in DIMENSIONS},
            "dimension_stats": {key: {
                "count": 0, "earned": 0.0, "possible": 0.0, "time": 0.0,
                "weighted_earned": 0.0, "weighted_possible": 0.0,
            } for key in DIMENSIONS},
            "used_ids": [],
            "history": [],
            "target_questions": max(15, min(25, target_questions)),
            "pending_question_id": None,
            "question_slots": [],
        }

    def public_question(self, question: dict | None) -> dict | None:
        if question is None:
            return None
        hidden = {"answer", "answer_index", "keywords", "rubric"}
        return {k: v for k, v in question.items() if k not in hidden}

    def next_question(self) -> dict | None:
        if self.is_complete():
            return None
        self._ensure_question_slots()
        pending = self.state.get("pending_question_id")
        if pending:
            return self._public_question_with_slot(pending)
        used = set(self.state["used_ids"])
        question_id = next((qid for qid in self.state["question_slots"] if qid not in used), None)
        if question_id is None:
            return None
        self.state["pending_question_id"] = question_id
        return self._public_question_with_slot(question_id)

    def _public_question_with_slot(self, question_id: str) -> dict:
        question = self.public_question(self.by_id[question_id])
        question["slot_number"] = self.state["question_slots"].index(question_id) + 1
        return question

    def _select_candidate(self, excluded: set[str], dimension: str, question_type: str, difficulty: int) -> str:
        candidates = [q for q in self.questions if q["id"] not in excluded]
        if not candidates:
            raise ValueError("题库没有足够的不重复题目")
        return self.random.choice(self._relax_filter(candidates, dimension, question_type, difficulty))["id"]

    def _ensure_question_slots(self) -> None:
        slots = self.state.setdefault("question_slots", [])
        # 兼容升级前已开始的测评：保留原作答顺序和当前待答题。
        if not slots:
            slots.extend(self.state.get("used_ids", []))
            pending = self.state.get("pending_question_id")
            if pending and pending not in slots:
                slots.append(pending)
        excluded = set(slots)
        initial_target = min(12, self.state["target_questions"] - 2)
        while len(slots) < initial_target:
            index = len(slots)
            dimension = DIMENSIONS[index % len(DIMENSIONS)]
            difficulty = 1 if index < 6 else 2
            question_id = self._select_candidate(excluded, dimension, "single_choice", difficulty)
            slots.append(question_id)
            excluded.add(question_id)
        if len(self.state["used_ids"]) >= initial_target and len(slots) < self.state["target_questions"]:
            self._prepare_adaptive_stage(excluded)

    def _prepare_adaptive_stage(self, excluded: set[str]) -> None:
        slots = self.state["question_slots"]
        target = self.state["target_questions"]
        objective_count = target - len(TAIL_TYPES)
        ranked_dimensions = sorted(DIMENSIONS, key=lambda key: (self.confidence(key), self.state["scores"][key]))
        while len(slots) < objective_count:
            dimension = ranked_dimensions[(len(slots) - 12) % len(ranked_dimensions)]
            question_id = self._select_candidate(excluded, dimension, "single_choice", self._target_difficulty(dimension))
            slots.append(question_id)
            excluded.add(question_id)
        for question_type, difficulty in TAIL_TYPES:
            if len(slots) >= target:
                break
            dimension = ranked_dimensions[(len(slots) - objective_count) % len(ranked_dimensions)]
            question_id = self._select_tail_question(excluded, dimension, question_type, difficulty)
            slots.append(question_id)
            excluded.add(question_id)

    def _select_tail_question(self, excluded: set[str], dimension: str, question_type: str, difficulty: int) -> str:
        """选择末段主观题；题库缺少目标题型时自动回退到开放题或实操题。"""
        if any(q["id"] not in excluded and q["type"] == question_type for q in self.questions):
            return self._select_candidate(excluded, dimension, question_type, difficulty)
        fallback_type = "practical" if question_type == "dialogue" else "open_text"
        return self._select_candidate(excluded, dimension, fallback_type, difficulty)

    def select_question(self, slot_number: int) -> dict:
        self._ensure_question_slots()
        if not 1 <= slot_number <= self.state["target_questions"]:
            raise ValueError("题号超出测评范围")
        if slot_number > len(self.state["question_slots"]):
            raise ValueError("请先完成第一阶段题目，再解锁自适应题组")
        question_id = self.state["question_slots"][slot_number - 1]
        if question_id in self.state["used_ids"]:
            return self._public_question_with_slot(question_id)
        self.state["pending_question_id"] = question_id
        return self._public_question_with_slot(question_id)

    def question_palette(self) -> list[dict]:
        self._ensure_question_slots()
        used = set(self.state["used_ids"])
        pending = self.state.get("pending_question_id")
        slots = self.state["question_slots"]
        results = {item["question_id"]: item for item in self.state.get("history", [])}
        def result_status(question_id: str) -> str:
            result = results[question_id]
            ratio = result["score"] / result["max_score"] if result["max_score"] else 0
            if ratio >= 0.999:
                return "correct"
            if ratio >= 0.5:
                return "partial"
            return "incorrect"
        return [{
            "number": number,
            "status": result_status(slots[number - 1])
                      if number <= len(slots) and slots[number - 1] in used
                      else "current" if number <= len(slots) and slots[number - 1] == pending
                      else "available" if number <= len(slots) else "locked",
        } for number in range(1, self.state["target_questions"] + 1)]

    @staticmethod
    def _relax_filter(candidates: list[dict], dimension: str, question_type: str, difficulty: int) -> list[dict]:
        filters = (
            lambda q: q["dimension"] == dimension and q["type"] == question_type and q["difficulty"] == difficulty,
            lambda q: q["dimension"] == dimension and q["type"] == question_type,
            lambda q: q["type"] == question_type and q["difficulty"] == difficulty,
            lambda q: q["type"] == question_type,
            lambda q: q["dimension"] == dimension,
        )
        for predicate in filters:
            pool = [q for q in candidates if predicate(q)]
            if pool:
                return pool
        return candidates

    def submit_answer(self, question_id: str, answer: str, elapsed_seconds: float, open_score: dict | None = None) -> dict:
        if question_id != self.state.get("pending_question_id"):
            raise ValueError("该题不是当前待答题目，或已经提交")
        question = self.by_id[question_id]
        max_score = float(question.get("max_score", question.get("score", 10)))
        if question["type"] in ("single_choice", "true_false"):
            earned = max_score if answer == question.get("answer") else 0.0
            feedback = {"correct": earned == max_score, "correct_answer": question.get("answer")}
        else:
            open_score = open_score or {}
            earned = max(0.0, min(max_score, float(open_score.get("score", 0))))
            feedback = open_score

        dimension = question["dimension"]
        stats = self.state["dimension_stats"][dimension]
        stats.setdefault("weighted_earned", 0.0)
        stats.setdefault("weighted_possible", 0.0)
        stats["count"] += 1
        stats["earned"] += earned
        stats["possible"] += max_score
        stats["time"] += max(0, elapsed_seconds)
        item_weight = 0.75 + 0.25 * float(question["difficulty"])
        response_ratio = earned / max_score if max_score else 0.0
        stats["weighted_earned"] += item_weight * response_ratio
        stats["weighted_possible"] += item_weight
        # 从 50 分先验平滑过渡到实测正确率：单题不会跳到 0/100，
        # 但累计 2-3 道有效证据后允许识别高低能力档。
        observed = stats["weighted_earned"] / stats["weighted_possible"]
        reliability = 1 - math.exp(-stats["weighted_possible"] / 1.5)
        calibrated = 50.0 * (1 - reliability) + 100.0 * observed * reliability
        self.state["scores"][dimension] = round(calibrated, 1)
        self.state["used_ids"].append(question_id)
        self.state["pending_question_id"] = None
        event = {
            "question_id": question_id, "dimension": dimension, "question_type": question["type"],
            "difficulty": question["difficulty"], "score": earned, "max_score": max_score,
            "elapsed_seconds": elapsed_seconds,
        }
        self.state["history"].append(event)
        return {**event, "feedback": feedback, "progress": self.progress(), "completed": self.is_complete()}

    def _weakest_dimension(self) -> str:
        return min(DIMENSIONS, key=lambda key: (self.state["scores"][key], self.state["dimension_stats"][key]["count"]))

    def _least_confident_dimension(self) -> str:
        return min(DIMENSIONS, key=lambda key: (self.confidence(key), self.state["scores"][key]))

    def _target_difficulty(self, dimension: str) -> int:
        score = self.state["scores"][dimension]
        return 1 if score < 45 else 2 if score < 75 else 3

    def confidence(self, dimension: str) -> float:
        stats = self.state["dimension_stats"][dimension]
        n = stats["count"]
        if not n:
            return 0.0
        accuracy = stats["earned"] / stats["possible"] if stats["possible"] else 0.5
        information = 1 - math.exp(-stats.get("weighted_possible", n) / 2.5)
        decisiveness = 0.8 + min(0.2, abs(accuracy - 0.5) * 0.4)
        return round(min(0.99, information * decisiveness), 3)

    def is_complete(self) -> bool:
        used = len(self.state["used_ids"])
        target = self.state["target_questions"]
        has_open = any(item["question_type"] == "open_text" for item in self.state["history"])
        has_practical = any(item["question_type"] == "practical" for item in self.state["history"])
        return used >= target and has_open and has_practical

    def progress(self) -> dict:
        return {
            "answered": len(self.state["used_ids"]),
            "target": self.state["target_questions"],
            "percent": min(100, round(100 * len(self.state["used_ids"]) / self.state["target_questions"])),
        }

    def build_report(self) -> dict:
        scores = self.state["scores"]
        overall = round(sum(scores.values()) / len(scores), 1)
        ordered = sorted(scores, key=scores.get, reverse=True)
        weaknesses = list(reversed(ordered[-2:]))
        names = {
            "basic": "AI基础认知", "prompt": "提示词工程", "tools": "AI工具使用",
            "evaluation": "结果评估与优化", "collaboration": "人机协同", "ethics": "伦理与合规",
        }
        suggestions = [f"优先强化{name}：结合本次错题完成一次针对性练习。" for name in map(names.get, weaknesses)]
        training = []
        for key in weaknesses:
            entry = TRAINING_RESOURCES.get(key)
            if entry:
                training.append({"dimension": key, "name": entry["name"], "resources": entry["resources"]})
        return {
            "overall_score": overall,
            "level": self._level(overall),
            "dimension_scores": scores,
            "confidence": {key: self.confidence(key) for key in DIMENSIONS},
            "strengths": [key for key in ordered if scores[key] >= 75],
            "weaknesses": weaknesses,
            "suggestions": suggestions,
            "training_resources": training,
            "evidence": self.state["history"],
            "question_count": len(self.state["used_ids"]),
            "type_distribution": dict(Counter(item["question_type"] for item in self.state["history"])),
            "difficulty_distribution": dict(Counter(str(item["difficulty"]) for item in self.state["history"])),
        }

    @staticmethod
    def _level(score: float) -> str:
        if score >= 90: return "L5 专家"
        if score >= 80: return "L4 高级"
        if score >= 65: return "L3 熟练"
        if score >= 50: return "L2 基础"
        return "L1 入门"
