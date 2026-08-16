import tempfile
import unittest
from pathlib import Path

from tools.simulate_balanced_cohort import run_simulation


class BalancedSimulationTests(unittest.TestCase):
    def test_balanced_levels_and_double_review_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_simulation(Path(temp_dir), per_level=1, target_questions=15, seed=123)
            self.assertEqual(report["design"]["total_samples"], 5)
            self.assertEqual(report["design"]["distribution"], {"L1": 1, "L2": 1, "L3": 1, "L4": 1, "L5": 1})
            self.assertEqual(report["design"]["maximum_level_share"], 0.2)
            self.assertEqual(report["double_review"]["double_reviewed_answers"], 10)
            self.assertEqual(report["double_review"]["review_records"], 20)
            self.assertTrue((Path(temp_dir) / "synthetic_validation.db").exists())
            self.assertTrue((Path(temp_dir) / "synthetic_validation_report.json").exists())


if __name__ == "__main__":
    unittest.main()
