from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from algorithm.adaptive_test import AdaptiveTestEngine
from backend import database as db


class DataProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.original = db.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self.temp.name) / "test.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self.original
        self.temp.cleanup()

    def test_demo_source_is_persisted_and_exported(self):
        db.upsert_user("u1", "学员", "一班")
        db.create_test("t1", "u1", 15, AdaptiveTestEngine.initial_state(15), "synthetic_demo", "seed=1")
        row = db.load_test("t1")
        self.assertEqual(row["data_source"], "synthetic_demo")
        self.assertEqual(row["source_note"], "seed=1")

    def test_demo_answers_do_not_enter_quality_statistics(self):
        db.upsert_user("u1", "学员", "一班")
        state = AdaptiveTestEngine.initial_state(15)
        db.create_test("t1", "u1", 15, state, "synthetic_demo", "seed=1")
        db.save_answer("t1", {"question_id": "Q1", "dimension": "basic", "question_type": "single_choice", "difficulty": 1, "score": 10, "max_score": 10}, "A", 10)
        self.assertEqual(db.question_statistics(), [])


if __name__ == "__main__":
    unittest.main()
