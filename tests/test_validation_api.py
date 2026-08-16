import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import ADMIN_ACCESS_KEY, app


class ValidationApiTests(unittest.TestCase):
    def test_synthetic_validation_requires_admin_and_preserves_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.json"
            report_path.write_text(json.dumps({
                "evidence_scope": "synthetic_balanced_cohort",
                "design": {"total_samples": 100, "maximum_level_share": 0.2},
                "double_review": {"double_reviewed_answers": 200},
                "disclaimer": "synthetic only",
            }), encoding="utf-8")
            with patch("backend.main.SYNTHETIC_REPORT_FILE", report_path):
                client = TestClient(app)
                self.assertEqual(client.get("/api/admin/validation/synthetic").status_code, 401)
                response = client.get(
                    "/api/admin/validation/synthetic", headers={"X-Admin-Key": ADMIN_ACCESS_KEY}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["evidence_scope"], "synthetic_balanced_cohort")


if __name__ == "__main__":
    unittest.main()
