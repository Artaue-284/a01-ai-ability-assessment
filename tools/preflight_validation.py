from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm.simulate_validation import run_validation
from question_bank.loader import (
    assessment_readiness,
    load_all_questions,
    validate_question_bank,
)


DIMENSION_NAMES = {
    "basic": "基础认知",
    "prompt": "提示工程",
    "tools": "工具应用",
    "evaluation": "评估验证",
    "collaboration": "人机协作",
    "ethics": "伦理安全",
}


def normalized_text(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def semantic_checks(questions: list[dict]) -> dict:
    issues: list[dict] = []
    answer_positions: Counter[str] = Counter()
    by_dimension = defaultdict(lambda: Counter(total=0))

    for question in questions:
        qid = question["id"]
        dimension = question["dimension"]
        qtype = question["type"]
        difficulty = int(question["difficulty"])
        by_dimension[dimension]["total"] += 1
        by_dimension[dimension][qtype] += 1
        by_dimension[dimension][f"difficulty_{difficulty}"] += 1

        text = str(question.get("question", "")).strip()
        if len(text) < 12:
            issues.append({"severity": "warning", "id": qid, "issue": "题干过短，需人工确认语境是否充分"})

        if qtype == "single_choice":
            options = question.get("options", [])
            answer = question.get("answer")
            answer_index = question.get("answer_index")
            if not isinstance(answer_index, int) and answer in options:
                answer_index = options.index(answer)
            if isinstance(answer_index, int) and 0 <= answer_index < len(options):
                position = chr(ord("A") + answer_index)
                answer_positions[position] += 1
                correct_length = len(str(options[answer_index]))
                other_lengths = [len(str(option)) for idx, option in enumerate(options) if idx != answer_index]
                if other_lengths and correct_length > 1.8 * statistics.mean(other_lengths) and correct_length - statistics.mean(other_lengths) >= 8:
                    issues.append({"severity": "review", "id": qid, "issue": "正确选项明显长于干扰项，可能形成长度线索"})
            option_keys = [normalized_text(str(option)) for option in options]
            if len(option_keys) != len(set(option_keys)):
                issues.append({"severity": "error", "id": qid, "issue": "存在重复选项"})

    near_duplicates = []
    for index, left in enumerate(questions):
        left_text = normalized_text(str(left.get("question", "")))
        for right in questions[index + 1 :]:
            right_text = normalized_text(str(right.get("question", "")))
            ratio = SequenceMatcher(None, left_text, right_text).ratio()
            if ratio >= 0.86:
                near_duplicates.append({"left": left["id"], "right": right["id"], "similarity": round(ratio, 3)})

    total_objective = sum(answer_positions.values())
    expected = total_objective / 4 if total_objective else 0
    answer_bias = {
        position: {
            "count": answer_positions[position],
            "ratio": round(answer_positions[position] / max(1, total_objective), 3),
        }
        for position in "ABCD"
    }
    if expected and any(abs(answer_positions[position] - expected) > total_objective * 0.12 for position in "ABCD"):
        issues.append({"severity": "review", "id": "BANK", "issue": "正确答案位置分布偏斜，建议人工复核"})

    return {
        "issues": issues,
        "near_duplicates": near_duplicates,
        "answer_positions": answer_bias,
        "dimension_coverage": {key: dict(value) for key, value in sorted(by_dimension.items())},
    }


def render_report(result: dict) -> str:
    validation = result["structural_validation"]
    checks = result["semantic_checks"]
    lines = [
        "# AI 预审与合成试测报告",
        "",
        "> 本报告用于开发阶段预检，不能替代独立人工盲审或真实学生试测。",
        "",
        "## 结论",
        "",
        f"- 题库结构校验：{'通过' if validation['valid'] else '未通过'}，共 {validation['total']} 题。",
        f"- 测评就绪检查：{'通过' if result['readiness']['ready'] else '未通过'}。",
        f"- 自动质量检查：发现 {len(checks['issues'])} 个待复核项、{len(checks['near_duplicates'])} 组近似题干。",
        "- 前端已在每次出题时随机打乱选项，因此题库源文件的答案位置分布不会暴露给受测者。",
        f"- 18 题合成分类一致率：{result['simulations']['18']['overall_classification_accuracy'] * 100:.1f}%（仅算法调试）。",
        f"- 25 题合成分类一致率：{result['simulations']['25']['overall_classification_accuracy'] * 100:.1f}%（仅算法调试）。",
        "",
        "## 题库覆盖",
        "",
        "| 维度 | 总题数 | 单选 | 开放 | 实操 | 难度1 | 难度2 | 难度3 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for dimension, counts in checks["dimension_coverage"].items():
        lines.append(
            f"| {DIMENSION_NAMES.get(dimension, dimension)} | {counts.get('total', 0)} | "
            f"{counts.get('single_choice', 0)} | {counts.get('open_text', 0)} | "
            f"{counts.get('practical', 0)} | {counts.get('difficulty_1', 0)} | "
            f"{counts.get('difficulty_2', 0)} | {counts.get('difficulty_3', 0)} |"
        )

    lines.extend(["", "## 题库源文件答案位置分布", "", "> 展示层会逐题随机打乱选项；下表用于提醒命题维护者，不代表用户实际看到的位置。", "", "| 位置 | 数量 | 占比 |", "|---|---:|---:|"])
    for position, stats in checks["answer_positions"].items():
        lines.append(f"| {position} | {stats['count']} | {stats['ratio'] * 100:.1f}% |")

    lines.extend(["", "## 自动发现的待复核项", ""])
    if checks["issues"]:
        for issue in checks["issues"]:
            lines.append(f"- [{issue['severity']}] {issue['id']}：{issue['issue']}")
    else:
        lines.append("- 未发现明显的结构性或选项偏置问题。")
    if checks["near_duplicates"]:
        for pair in checks["near_duplicates"]:
            lines.append(f"- [review] {pair['left']} / {pair['right']}：题干相似度 {pair['similarity']:.1%}")

    lines.extend(
        [
            "",
            "## 仍需真人完成的最小环节",
            "",
            "1. 由 1 名非出题成员在不知道标准答案的情况下完成全量题库盲审，并记录歧义题。",
            "2. 邀请至少 10 名真实体验者完成 25 题测试；系统会自动沉淀用时、正确率与区分度数据。",
            "3. 正式对外表述评分有效性前，将样本继续累计到至少 30 人，并完成开放题双评。",
            "",
            "合成用户只验证程序与自适应路径是否稳定，不可写成真实准确率或真实用户试测结果。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="运行题库自动预审和自适应算法合成压力测试")
    parser.add_argument("--runs", type=int, default=100, help="每个能力层级的合成次数")
    parser.add_argument("--json-output", type=Path, default=ROOT / "docs" / "AI预审与合成试测数据.json")
    parser.add_argument("--report-output", type=Path, default=ROOT / "docs" / "AI预审与合成试测报告.md")
    args = parser.parse_args()

    questions = load_all_questions()
    result = {
        "disclaimer": "仅用于开发预检，不等同于独立人工盲审或真实学生试测。",
        "structural_validation": validate_question_bank(questions),
        "readiness": assessment_readiness(questions),
        "semantic_checks": semantic_checks(questions),
        "simulations": {
            "18": run_validation(args.runs, 18),
            "25": run_validation(args.runs, 25),
        },
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.report_output.write_text(render_report(result), encoding="utf-8")
    print(f"JSON={args.json_output}")
    print(f"REPORT={args.report_output}")
    print(f"ISSUES={len(result['semantic_checks']['issues'])}")
    print(f"NEAR_DUPLICATES={len(result['semantic_checks']['near_duplicates'])}")


if __name__ == "__main__":
    main()
