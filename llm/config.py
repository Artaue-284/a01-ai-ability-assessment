from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "data" / "llm_config.json"


def load_llm_config() -> dict[str, str]:
    """加载 ant-line（蚂蚁灵/百炼 OpenAI 兼容服务）配置。

    优先级：环境变量 > data/llm_config.json 本地配置文件。
    密钥只保存在进程环境变量或本地配置文件中，不写入代码、数据库或题库。
    """
    data: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except (json.JSONDecodeError, OSError):
            data = {}
    return {
        "ant_line_base_url": os.getenv("ANT_LINE_BASE_URL", "").strip() or str(data.get("base_url", "")).strip(),
        "ant_line_api_key": os.getenv("ANT_LINE_API_KEY", "").strip() or str(data.get("api_key", "")).strip(),
        "ant_line_model": os.getenv("ANT_LINE_MODEL", "").strip() or str(data.get("model", "")).strip(),
    }
