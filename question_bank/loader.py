from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
QUESTION_FILES = [
    ROOT / "question_bank" / "question_bank" / "questions.json",
    ROOT / "question_bank" / "questions.json",
]
DIMENSIONS = {"basic", "prompt", "tools", "evaluation", "collaboration", "ethics"}
QUESTION_TYPES = {"single_choice", "true_false", "open_text", "practical", "code", "image"}


def _repair_text(value):
    """兼容早期题库中由 GBK 字节误存为 Latin-1 文本造成的乱码。"""
    if isinstance(value, str):
        try:
            repaired = value.encode("latin1").decode("gbk")
            if any("\u4e00" <= char <= "\u9fff" for char in repaired):
                return repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return value
    if isinstance(value, list):
        return [_repair_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _repair_text(item) for key, item in value.items()}
    return value


def load_questions() -> list[dict]:
    path = next((p for p in QUESTION_FILES if p.exists()), None)
    if path is None:
        return []
    questions = _repair_text(json.loads(path.read_text(encoding="utf-8")))
    return normalize_questions(questions)


def load_all_questions() -> list[dict]:
    questions = load_questions()
    bank_dir = ROOT / "question_bank"
    for pattern in ("open_tasks.json", "advanced_questions.json", "curated_*.json"):
        paths = [bank_dir / pattern] if "*" not in pattern else sorted(bank_dir.glob(pattern))
        for path in paths:
            if path.exists():
                questions.extend(json.loads(path.read_text(encoding="utf-8")))
    return normalize_questions(questions)


def normalize_questions(questions: list[dict]) -> list[dict]:
    for question in questions:
        question.setdefault("type", "single_choice")
        question.setdefault("tags", [question["dimension"]])
        question.setdefault("max_score", question.get("score", 10))
        question.setdefault("ability_level", f"L{min(5, int(question.get('difficulty', 1)) + 1)}")
        question.setdefault("discrimination", 1.0)
        question.setdefault("explanation", "待教研审核补充解析")
    return questions


def validate_question_bank(questions: list[dict]) -> dict:
    required = {"id", "dimension", "difficulty", "type", "question"}
    errors = []
    warnings = []
    ids = set()
    for index, question in enumerate(questions):
        missing = required - question.keys()
        if missing:
            errors.append(f"第 {index + 1} 题缺少字段: {sorted(missing)}")
        if question.get("id") in ids:
            errors.append(f"题目 ID 重复: {question.get('id')}")
        ids.add(question.get("id"))
        if question.get("dimension") not in DIMENSIONS:
            errors.append(f"题目 {question.get('id')} 使用未知维度")
        if question.get("type") not in QUESTION_TYPES:
            errors.append(f"题目 {question.get('id')} 使用未知题型")
        if question.get("difficulty") not in (1, 2, 3, 4, 5):
            errors.append(f"题目 {question.get('id')} 难度必须为 1-5")
        if not question.get("tags"):
            warnings.append(f"题目 {question.get('id')} 缺少标签")
        if not question.get("explanation") or question.get("explanation") == "待教研审核补充解析":
            warnings.append(f"题目 {question.get('id')} 尚未补充解析")
        if question.get("type") == "single_choice":
            if len(question.get("options", [])) < 2 or "answer" not in question:
                errors.append(f"客观题 {question.get('id')} 缺少选项或答案")
        elif not question.get("rubric"):
            errors.append(f"非客观题 {question.get('id')} 缺少评分量表")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "total": len(questions),
        "by_dimension": dict(Counter(q.get("dimension") for q in questions)),
        "by_type": dict(Counter(q.get("type") for q in questions)),
        "by_difficulty": dict(Counter(str(q.get("difficulty")) for q in questions)),
        "by_level": dict(Counter(q.get("ability_level") for q in questions)),
        "review_completion": round(100 * (len(questions) - len(warnings)) / max(1, len(questions)), 1),
    }


def assessment_readiness(questions: list[dict]) -> dict:
    counts = Counter(q.get("dimension") for q in questions)
    objective = Counter(q.get("dimension") for q in questions if q.get("type") in {"single_choice", "true_false"})
    non_objective = Counter(q.get("dimension") for q in questions if q.get("type") in {"open_text", "practical"})
    missing = {}
    for dimension in DIMENSIONS:
        issues = []
        if counts[dimension] < 15:
            issues.append(f"总题数 {counts[dimension]}/15")
        if objective[dimension] < 10:
            issues.append(f"客观题 {objective[dimension]}/10")
        if non_objective[dimension] < 1:
            issues.append("缺少开放或实操题")
        if issues:
            missing[dimension] = issues
    return {
        "ready": not missing,
        "missing": missing,
        "message": "题库可以开始正式测评" if not missing else "初始题库已移除，新题库尚未补足，当前暂停正式测评",
    }
