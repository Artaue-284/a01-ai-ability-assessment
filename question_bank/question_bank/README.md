# 题库系统

## 文件位置

本目录：

`question_bank/questions.json`

## 数量

- 6 个能力维度
- 每个维度 15 道题
- 每个维度：10 道基础题 + 5 道进阶题
- 总计 90 道题

## 题目结构

```json
{
  "id": "PR001",
  "dimension": "prompt",
  "difficulty": 1,
  "type": "single_choice",
  "question": "题目",
  "options": ["选项1", "选项2", "选项3", "选项4"],
  "answer": "正确选项原文",
  "answer_index": 2,
  "score": 10
}
```

### 字段说明

- `id`：题目唯一 ID
- `dimension`：能力维度
- `difficulty`：1=基础，2=进阶
- `type`：题型
- `question`：题干
- `options`：选项
- `answer`：正确答案原文
- `answer_index`：正确答案位置，0=A，1=B，2=C，3=D
- `score`：基础分

## 当前答案分布

答案位置已经打散，不会全部集中在 A。

后续增加题目时，继续保持 A/B/C/D 相对均衡，避免用户通过选项位置猜答案。
