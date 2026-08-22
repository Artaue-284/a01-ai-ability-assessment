from __future__ import annotations

import base64
import csv
import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image

from llm.config import load_llm_config


MAX_EXTRACTED_CHARS = 20_000


class MultimodalAnalyzer:
    """Analyze uploaded evidence without claiming capabilities that are unavailable.

    Text-bearing files are extracted locally and interpreted by the configured text
    model. Images require a separately configured vision-capable OpenAI-compatible
    model; image metadata alone is never presented as visual understanding.
    """

    def __init__(self) -> None:
        ant_line = load_llm_config()
        self.text_base_url = ant_line["ant_line_base_url"].rstrip("/")
        self.text_api_key = ant_line["ant_line_api_key"]
        self.text_model = ant_line["ant_line_model"] or "Ling-3.0-flash"
        self.vision_base_url = os.getenv("MULTIMODAL_BASE_URL", "").strip().rstrip("/")
        self.vision_api_key = os.getenv("MULTIMODAL_API_KEY", "").strip()
        self.vision_model = os.getenv("MULTIMODAL_MODEL", "").strip()

    @property
    def vision_configured(self) -> bool:
        return bool(self.vision_base_url and self.vision_api_key and self.vision_model)

    @property
    def text_configured(self) -> bool:
        return bool(self.text_base_url and self.text_api_key and self.text_model)

    @staticmethod
    def _extract_text(path: Path) -> tuple[str, dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="replace")[:MAX_EXTRACTED_CHARS]
            return text, {"characters": len(text)}
        if suffix == ".json":
            value = json.loads(path.read_text(encoding="utf-8"))
            text = json.dumps(value, ensure_ascii=False, indent=2)[:MAX_EXTRACTED_CHARS]
            return text, {"characters": len(text), "json_type": type(value).__name__}
        if suffix == ".csv":
            raw = path.read_text(encoding="utf-8-sig", errors="replace")
            rows = list(csv.reader(io.StringIO(raw)))
            columns = rows[0] if rows else []
            sample = rows[:21]
            text = "\n".join(", ".join(cell for cell in row) for row in sample)[:MAX_EXTRACTED_CHARS]
            return text, {"rows": max(0, len(rows) - 1), "columns": columns[:50], "sample_rows": min(20, max(0, len(rows) - 1))}
        if suffix == ".pdf":
            import pdfplumber

            pages: list[str] = []
            with pdfplumber.open(path) as document:
                for page in document.pages[:20]:
                    pages.append(page.extract_text() or "")
            text = "\n\n".join(pages)[:MAX_EXTRACTED_CHARS]
            return text, {"pages_processed": len(pages), "characters": len(text)}
        raise ValueError("该文件类型不支持文本提取")

    @staticmethod
    def _chat(base_url: str, api_key: str, model: str, messages: list[dict[str, Any]], timeout: int = 90) -> str:
        body = json.dumps({"model": model, "messages": messages, "stream": False, "max_tokens": 800}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"模型调用失败 HTTP {exc.code}: {detail}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("模型响应缺少可读内容") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("模型未返回分析文本")
        return content.strip()[:4000]

    def analyze(self, path: Path, media_type: str, question: dict[str, Any]) -> dict[str, Any]:
        suffix = path.suffix.lower()
        prompt = (
            "你是AI能力测评证据分析员。根据上传内容和题目要求，提取可核验证据、指出缺失信息和风险。"
            "不得臆测文件中不存在的内容。请用中文输出简洁分析。\n"
            f"题目：{question.get('question', '')}\n评分量表：{json.dumps(question.get('rubric', []), ensure_ascii=False)}"
        )
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            with Image.open(path) as image:
                metadata = {"width": image.width, "height": image.height, "format": image.format, "mode": image.mode}
            if not self.vision_configured:
                return {
                    "status": "needs-vision-model",
                    "mode": "image-metadata-only",
                    "model": "",
                    "summary": "图片已安全保存并读取元数据，但尚未配置可验证的视觉模型，未执行图像内容理解。",
                    "extracted_text": "",
                    "metadata": metadata,
                    "warning": "请配置 MULTIMODAL_BASE_URL、MULTIMODAL_API_KEY 和 MULTIMODAL_MODEL。",
                }
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            mime = media_type if media_type.startswith("image/") else f"image/{suffix.lstrip('.')}"
            summary = self._chat(
                self.vision_base_url,
                self.vision_api_key,
                self.vision_model,
                [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ]}],
            )
            return {"status": "analyzed", "mode": "vision-model", "model": self.vision_model, "summary": summary, "extracted_text": "", "metadata": metadata}

        extracted, metadata = self._extract_text(path)
        if not extracted.strip():
            return {"status": "no-readable-content", "mode": "local-extraction", "model": "", "summary": "文件中未提取到可读文本。", "extracted_text": "", "metadata": metadata}
        if not self.text_configured:
            return {
                "status": "extracted",
                "mode": "local-extraction",
                "model": "",
                "summary": "已提取文件内容；未配置文本模型，因此没有生成语义分析。",
                "extracted_text": extracted,
                "metadata": metadata,
            }
        summary = self._chat(
            self.text_base_url,
            self.text_api_key,
            self.text_model,
            [{"role": "system", "content": "只依据提供的文件文本进行分析，不得补造内容。"}, {"role": "user", "content": f"{prompt}\n\n文件内容：\n{extracted}"}],
        )
        return {"status": "analyzed", "mode": "text-extraction-plus-model", "model": self.text_model, "summary": summary, "extracted_text": extracted, "metadata": metadata}
