from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "level_thresholds.json"


def load_level_scale() -> dict:
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"等级阈值配置不存在：{CONFIG_PATH}")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    thresholds = config.get("thresholds")
    levels = config.get("levels")
    if not isinstance(thresholds, list) or len(thresholds) != 4:
        raise RuntimeError("等级阈值必须包含4个断点")
    thresholds = [float(value) for value in thresholds]
    if thresholds != sorted(thresholds) or thresholds[0] <= 0 or thresholds[-1] >= 100:
        raise RuntimeError("等级阈值必须在0到100之间严格递增")
    if not isinstance(levels, list) or len(levels) != 5:
        raise RuntimeError("等级配置必须包含L1至L5五项")
    widths = [round(float(item["width"]), 1) for item in levels]
    counts = [int(item["calibration_count"]) for item in levels]
    if len(set(widths)) != 5 or len(set(counts)) != 5:
        raise RuntimeError("等级区间宽度与校准人数必须分别两两不同")
    return config


LEVEL_SCALE = load_level_scale()
LEVEL_THRESHOLDS = tuple(float(value) for value in LEVEL_SCALE["thresholds"])
LEVELS = tuple(LEVEL_SCALE["levels"])


def score_to_level_code(score: float) -> str:
    for index, threshold in enumerate(LEVEL_THRESHOLDS):
        if score < threshold:
            return LEVELS[index]["code"]
    return LEVELS[-1]["code"]


def score_to_level_name(score: float) -> str:
    code = score_to_level_code(score)
    level = next(item for item in LEVELS if item["code"] == code)
    return f"{code} {level['name']}"
