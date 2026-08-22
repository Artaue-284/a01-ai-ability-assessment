import shutil
import unittest
import uuid
from pathlib import Path

from tools.simulate_balanced_cohort import run_simulation

# 输出目录放在工作区 .test_runtime 下：既隔离测试产物，也避免依赖系统临时目录权限。
TEST_RUNTIME = Path(__file__).resolve().parent.parent / ".test_runtime"


class BalancedSimulationTests(unittest.TestCase):
    def test_balanced_levels_and_double_review_artifacts(self):
        output_dir = TEST_RUNTIME / f"balanced_sim_{uuid.uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            report = run_simulation(output_dir, per_level=1, target_questions=15, seed=123)
            self.assertEqual(report["design"]["total_samples"], 5)
            self.assertEqual(report["design"]["distribution"], {"L1": 1, "L2": 1, "L3": 1, "L4": 1, "L5": 1})
            self.assertEqual(report["design"]["maximum_level_share"], 0.2)
            # 每场 15 题 = 12 客观 + 3 末段主观（开放作答/实操/对话），5 人 → 15 份主观作答，双评 15 份、30 条复核记录。
            self.assertEqual(report["double_review"]["double_reviewed_answers"], 15)
            self.assertEqual(report["double_review"]["review_records"], 30)
            self.assertTrue((output_dir / "synthetic_validation.db").exists())
            self.assertTrue((output_dir / "synthetic_validation_report.json").exists())
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
