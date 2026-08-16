import json
import unittest
from collections import Counter
from pathlib import Path

from algorithm.adaptive_test import AdaptiveTestEngine, DIMENSIONS
from algorithm.simulate_validation import run_validation
from question_bank.loader import assessment_readiness, load_all_questions, normalize_questions, validate_question_bank


ROOT = Path(__file__).resolve().parent.parent


def questions():
    return load_all_questions()


class EngineTests(unittest.TestCase):
    def test_question_bank_is_valid_and_balanced(self):
        bank = questions()
        stats = validate_question_bank(bank)
        self.assertTrue(stats["valid"], stats["errors"])
        self.assertEqual(stats["total"], 91)
        self.assertTrue(all(q.get("ability_level") for q in bank))
        self.assertTrue(all(q.get("tags") for q in bank))
        self.assertTrue(all(len(q.get("explanation", "").strip()) >= 12 for q in bank))
        self.assertEqual(len({q["explanation"] for q in bank}), 91)
        self.assertIn("review_completion", stats)
        for dimension in DIMENSIONS:
            self.assertEqual(stats["by_dimension"][dimension], 16 if dimension == "evaluation" else 15)
        self.assertTrue(assessment_readiness(bank)["ready"])
        self.assertEqual(stats["review_completion"], 100.0)

    def test_layered_random_has_no_duplicates_and_finishes(self):
        bank = questions()
        engine = AdaptiveTestEngine(bank, seed="student-a", state=AdaptiveTestEngine.initial_state(18))
        seen = set()
        while not engine.is_complete():
            q = engine.next_question()
            self.assertIsNotNone(q)
            self.assertNotIn(q["id"], seen)
            seen.add(q["id"])
            source = next(item for item in bank if item["id"] == q["id"])
            answer = source.get("answer", "1. 任务拆解 2. 数据核验 3. 人工确认 4. 隐私脱敏与权限控制")
            open_score = {"score": source.get("max_score", 20), "feedback": "test"}
            engine.submit_answer(q["id"], answer, 20, open_score)
        report = engine.build_report()
        self.assertEqual(report["question_count"], 18)
        self.assertIn("open_text", report["type_distribution"])
        self.assertIn("practical", report["type_distribution"])
        self.assertEqual(set(report["dimension_scores"]), set(DIMENSIONS))

    def test_choice_lengths_and_answer_positions_are_balanced(self):
        objective = [item for item in questions() if item["type"] == "single_choice"]
        positions = Counter("ABCD"[item["options"].index(item["answer"])] for item in objective)
        self.assertEqual(positions, Counter({"A": 21, "B": 21, "C": 21, "D": 21}))
        for item in objective:
            lengths = [len(option) for option in item["options"]]
            self.assertLessEqual(max(lengths) - min(lengths), 8, item["id"])
            self.assertLessEqual(max(lengths) / max(1, min(lengths)), 1.6, item["id"])

    def test_two_sessions_are_independent(self):
        bank = questions()
        first = AdaptiveTestEngine(bank, seed="one")
        second = AdaptiveTestEngine(bank, seed="two")
        q1, q2 = first.next_question(), second.next_question()
        first.submit_answer(q1["id"], "wrong", 5)
        self.assertEqual(len(first.state["used_ids"]), 1)
        self.assertEqual(len(second.state["used_ids"]), 0)
        self.assertIsNotNone(q2)

    def test_question_palette_supports_non_linear_answering(self):
        bank = questions()
        engine = AdaptiveTestEngine(bank, seed="palette", state=AdaptiveTestEngine.initial_state(18))
        engine.next_question()
        palette = engine.question_palette()
        self.assertEqual(sum(item["status"] != "locked" for item in palette), 12)
        for slot in (6, 2, 10, 1, 12, 4, 8, 3, 11, 5, 9, 7):
            question = engine.select_question(slot)
            source = next(item for item in bank if item["id"] == question["id"])
            engine.submit_answer(question["id"], source["answer"], 10)
        self.assertTrue(all(item["status"] != "locked" for item in engine.question_palette()))
        self.assertEqual(len({item for item in engine.state["question_slots"]}), 18)

    def test_palette_uses_three_result_states(self):
        bank = questions()
        engine = AdaptiveTestEngine(bank, seed="states", state=AdaptiveTestEngine.initial_state(15))
        engine.next_question()
        for slot in range(1, 13):
            question = engine.select_question(slot)
            engine.submit_answer(question["id"], "__wrong__", 5)
        subjective = engine.select_question(14)
        engine.submit_answer(subjective["id"], "部分完成", 5, {"score": 10})
        self.assertEqual(engine.question_palette()[13]["status"], "partial")

    def test_validation_simulator_separates_profiles(self):
        result = run_validation(runs=10, target=18)
        means = [result["profiles"][level]["mean_score"] for level in ("L1", "L2", "L3", "L4", "L5")]
        self.assertEqual(means, sorted(means))


if __name__ == "__main__":
    unittest.main()
