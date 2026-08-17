# 题库系统

> 本说明已随 v1.5.0 同步更新：题库由 `question_bank/loader.py` 聚合加载，不再是单一 `questions.json`。

## 文件位置

- 客观题：`question_bank/curated_*.json`（每维 13 道）+ `advanced_questions.json`（每维 1 道高阶题）
- 主观题：`open_tasks.json`（开放作答 6）、`dialogue_tasks.json`（对话任务 2）、`code_tasks.json`（代码任务 2）、`image_tasks.json`（图像鉴别 2）、`open_tasks.json`（实操/开放）

## 数量（当前 96 题）

- 6 个能力维度，每维 15~17 题
- 84 道客观题（每题 10 分）+ 12 道主观题（开放 3 / 实操 3 / 对话 2 / 代码 2 / 图像 2）
- 每维满足赛题"10 道基础题 + 5 道进阶题"要求（难度 1/2/3 分层）

## 题目结构

```json
{
  "id": "PR1001",
  "dimension": "prompt",
  "difficulty": 2,
  "type": "single_choice",
  "tags": ["上下文", "少样本"],
  "question": "题干",
  "options": ["A", "B", "C", "D"],
  "answer": "正确选项原文",
  "answer_index": 2,
  "max_score": 10
}
```

主观题扩展字段：`rubric`（评分量表）、`keywords`（评分关键词）、`image_url`（图像题图片资源地址）。

## 维护约定

- 答案位置保持 A/B/C/D 相对均衡，避免用户通过选项位置猜答案。
- 修改题目走题库管理后台（生成版本记录），或直接编辑 JSON 后重新导入。
- 新增题目请同步更新结构校验（`tools/preflight_validation.py`）。
