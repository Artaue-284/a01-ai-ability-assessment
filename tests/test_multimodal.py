import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from llm.multimodal import MultimodalAnalyzer


QUESTION = {"question": "分析上传证据并说明结论", "rubric": ["引用证据", "指出风险"]}


def empty_text_config():
    return {"ant_line_base_url": "", "ant_line_api_key": "", "ant_line_model": ""}


class MultimodalAnalyzerTests(unittest.TestCase):
    def test_csv_is_extracted_without_claiming_model_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            path.write_text("name,score\nA,80\nB,90\n", encoding="utf-8")
            with patch("llm.multimodal.load_llm_config", side_effect=empty_text_config), patch.dict(os.environ, {
                "MULTIMODAL_BASE_URL": "", "MULTIMODAL_API_KEY": "", "MULTIMODAL_MODEL": "",
            }, clear=False):
                result = MultimodalAnalyzer().analyze(path, "text/csv", QUESTION)
        self.assertEqual(result["status"], "extracted")
        self.assertEqual(result["mode"], "local-extraction")
        self.assertEqual(result["metadata"]["rows"], 2)
        self.assertIn("score", result["extracted_text"])

    def test_image_requires_real_vision_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            Image.new("RGB", (12, 8), "white").save(path)
            with patch("llm.multimodal.load_llm_config", side_effect=empty_text_config), patch.dict(os.environ, {
                "MULTIMODAL_BASE_URL": "", "MULTIMODAL_API_KEY": "", "MULTIMODAL_MODEL": "",
            }, clear=False):
                result = MultimodalAnalyzer().analyze(path, "image/png", QUESTION)
        self.assertEqual(result["status"], "needs-vision-model")
        self.assertEqual(result["metadata"]["width"], 12)
        self.assertNotEqual(result["status"], "analyzed")

    def test_configured_vision_model_receives_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            Image.new("RGB", (10, 10), "blue").save(path)
            with patch("llm.multimodal.load_llm_config", side_effect=empty_text_config), patch.dict(os.environ, {
                "MULTIMODAL_BASE_URL": "https://vision.example/v1",
                "MULTIMODAL_API_KEY": "test-key",
                "MULTIMODAL_MODEL": "vision-test",
            }, clear=False), patch.object(MultimodalAnalyzer, "_chat", return_value="图片包含蓝色方块") as call:
                result = MultimodalAnalyzer().analyze(path, "image/png", QUESTION)
        self.assertEqual(result["status"], "analyzed")
        self.assertEqual(result["model"], "vision-test")
        self.assertTrue(call.called)


if __name__ == "__main__":
    unittest.main()
