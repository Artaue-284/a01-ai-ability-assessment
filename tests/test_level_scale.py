import csv
import unittest
from collections import Counter
from pathlib import Path

from algorithm.level_scale import LEVEL_SCALE, LEVEL_THRESHOLDS, score_to_level_code, score_to_level_name


ROOT = Path(__file__).resolve().parent.parent


class LevelScaleTests(unittest.TestCase):
    def test_boundaries_and_labels(self):
        self.assertEqual(LEVEL_THRESHOLDS, (34.5, 49.7, 65.9, 80.8))
        cases = [
            (0, "L1"), (34.4, "L1"), (34.5, "L2"), (49.6, "L2"),
            (49.7, "L3"), (65.8, "L3"), (65.9, "L4"), (80.7, "L4"),
            (80.8, "L5"), (100, "L5"),
        ]
        for score, expected in cases:
            self.assertEqual(score_to_level_code(score), expected)
        self.assertEqual(score_to_level_name(80.8), "L5 专家")

    def test_widths_and_calibration_counts_are_pairwise_distinct(self):
        widths = [item["width"] for item in LEVEL_SCALE["levels"]]
        counts = [item["calibration_count"] for item in LEVEL_SCALE["levels"]]
        self.assertEqual(len(set(widths)), 5)
        self.assertEqual(len(set(counts)), 5)
        self.assertEqual(sum(counts), 100)

    def test_saved_sample_distribution_and_accuracy(self):
        path = ROOT / "docs" / "synthetic_validation_100" / "synthetic_respondents.csv"
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        predictions = [score_to_level_code(float(row["overall_score"])) for row in rows]
        counts = Counter(predictions)
        correct = sum(prediction == row["expected_level"] for prediction, row in zip(predictions, rows))
        self.assertEqual([counts[f"L{index}"] for index in range(1, 6)], [20, 19, 21, 26, 14])
        self.assertEqual(correct / len(rows), 0.81)


if __name__ == "__main__":
    unittest.main()
