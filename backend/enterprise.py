from __future__ import annotations

from typing import Any


ROLE_PERMISSIONS = {
    "student": [
        "start_assessment",
        "submit_answer",
        "view_own_report",
        "view_own_growth",
        "upload_own_evidence",
        "authorize_own_job_match",
    ],
    "teacher": [
        "view_identified_class_dashboard",
        "manage_question_bank",
        "review_open_answers",
        "export_research_data",
    ],
    "enterprise": [
        "manage_job_templates",
        "view_anonymous_group_insights",
    ],
}


DEFAULT_JOB_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "ai-application-assistant",
        "name": "AI应用助理",
        "description": "能选择合适工具、完成基础交付并对结果进行核验。",
        "weights": {"basic": 0.15, "prompt": 0.15, "tools": 0.25, "evaluation": 0.20, "collaboration": 0.15, "ethics": 0.10},
        "min_scores": {"basic": 55, "prompt": 55, "tools": 65, "evaluation": 60, "collaboration": 55, "ethics": 60},
    },
    {
        "id": "prompt-operations",
        "name": "提示词运营",
        "description": "能把业务目标拆解为稳定提示流程并持续优化输出。",
        "weights": {"basic": 0.10, "prompt": 0.30, "tools": 0.15, "evaluation": 0.25, "collaboration": 0.10, "ethics": 0.10},
        "min_scores": {"basic": 55, "prompt": 70, "tools": 55, "evaluation": 65, "collaboration": 55, "ethics": 60},
    },
    {
        "id": "ai-project-coordinator",
        "name": "AI项目协调",
        "description": "能设计人机分工、设置检查点并控制交付与合规风险。",
        "weights": {"basic": 0.10, "prompt": 0.15, "tools": 0.15, "evaluation": 0.20, "collaboration": 0.25, "ethics": 0.15},
        "min_scores": {"basic": 55, "prompt": 60, "tools": 60, "evaluation": 65, "collaboration": 70, "ethics": 65},
    },
]


def score_job_matches(dimension_scores: dict[str, float], templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return explainable matches. This is decision support, never an automated hiring decision."""
    result = []
    for template in templates:
        weights = template.get("weights", {})
        minimums = template.get("min_scores", {})
        weighted = sum(float(dimension_scores.get(key, 0)) * float(weight) for key, weight in weights.items())
        gaps = []
        strengths = []
        for key, minimum in minimums.items():
            score = float(dimension_scores.get(key, 0))
            delta = round(score - float(minimum), 1)
            (strengths if delta >= 0 else gaps).append({"dimension": key, "delta": delta, "score": round(score, 1), "minimum": minimum})
        penalty = min(20.0, sum(abs(item["delta"]) for item in gaps) * 0.12)
        match_score = round(max(0.0, min(100.0, weighted - penalty)), 1)
        result.append({
            "template_id": template["id"],
            "name": template["name"],
            "description": template.get("description", ""),
            "match_score": match_score,
            "strengths": sorted(strengths, key=lambda item: item["delta"], reverse=True)[:2],
            "gaps": sorted(gaps, key=lambda item: item["delta"])[:2],
            "notice": "仅用于学习发展建议，不构成录用、淘汰或自动化决策依据。",
        })
    return sorted(result, key=lambda item: item["match_score"], reverse=True)


def build_dialogue_guidance(turn_index: int, message: str) -> str:
    """Deterministic scaffolding that asks for evidence without leaking an answer."""
    text = message.strip()
    if turn_index == 1:
        return "请先明确任务目标、使用对象和成功标准；再说明你目前最不确定的一点。"
    if turn_index == 2:
        return "请把方案拆成可执行步骤，并标出需要人工确认、事实核验或权限检查的位置。"
    if turn_index == 3:
        return "请给出至少一个可检查证据，例如输出片段、截图、文件摘要或验证记录。"
    if len(text) < 40:
        return "当前说明较简略。请补充具体输入、操作过程、输出结果与验证结论。"
    return "请进行最后复盘：指出方案的边界、潜在风险、失败时的替代路径，以及你会如何改进。"
