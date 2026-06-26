# -*- coding: utf-8 -*-
"""动作解析器 — PDF 4.3.2

将模型原始文本输出解析为结构化动作指令。
支持五种动作：click / type / scroll / hotkey / finish。
解析失败时返回 unknown 类型。
"""
import re
from typing import Any, Dict, Optional

from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# ===== 各动作的正则表达式 =====
# 匹配格式: action_name(key1=val1, key2=val2, ...)

_PATTERN_CLICK = re.compile(
    r'click\s*\(\s*x\s*=\s*(-?\d+)\s*,\s*y\s*=\s*(-?\d+)\s*\)',
    re.IGNORECASE,
)

_PATTERN_TYPE = re.compile(
    r'type\s*\(\s*text\s*=\s*"(.*?)"\s*\)',
    re.IGNORECASE,
)

_PATTERN_SCROLL = re.compile(
    r'scroll\s*\(\s*direction\s*=\s*"(up|down)"\s*(?:,\s*steps\s*=\s*(\d+))?\s*\)',
    re.IGNORECASE,
)

_PATTERN_HOTKEY = re.compile(
    r'hotkey\s*\(\s*([^)]+)\s*\)',
    re.IGNORECASE,
)

_PATTERN_FINISH = re.compile(
    r'finish\s*\(\s*result\s*=\s*"(.*?)"\s*\)',
    re.IGNORECASE,
)


def parse(model_output: Optional[str]) -> Dict[str, Any]:
    """解析模型输出为结构化动作字典。

    按优先级依次尝试五种动作的格式匹配：
    click → type → scroll → hotkey → finish。
    如果模型输出包含多行，只解析第一个有效动作（单步单动作原则）。

    Args:
        model_output: 模型的原始文本输出。

    Returns:
        成功时: {"action_type": str, "params": dict}
        失败时: {"action_type": "unknown", "raw": str}
    """
    if not model_output:
        logger.warning("模型输出为空")
        return {"action_type": "unknown", "raw": model_output or ""}

    text = model_output.strip()

    # 只取第一行（单步单动作原则）
    first_line = text.split("\n")[0].strip()

    # 按优先级尝试各动作
    for pattern, action_type, params_builder in _PARSERS:
        match = pattern.search(first_line)
        if match:
            params = params_builder(match)
            if params is not None:
                logger.info(f"解析成功: {action_type} {params}")
                return {"action_type": action_type, "params": params}

    # 所有模式都不匹配
    logger.warning(f"无法解析模型输出: {first_line[:100]}")
    return {"action_type": "unknown", "raw": first_line}


def _build_click_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 click 参数字典。"""
    return {"x": int(match.group(1)), "y": int(match.group(2))}


def _build_type_params(match: re.Match) -> Dict[str, str]:
    """从正则匹配结果构建 type 参数字典。"""
    return {"text": match.group(1)}


def _build_scroll_params(match: re.Match) -> Dict[str, Any]:
    """从正则匹配结果构建 scroll 参数字典。"""
    direction = match.group(1)
    steps = int(match.group(2)) if match.group(2) else 1
    return {"direction": direction, "steps": steps}


def _build_hotkey_params(match: re.Match) -> Dict[str, list]:
    """从正则匹配结果构建 hotkey 参数字典。"""
    # 逗号分隔每个按键名，去除空白和引号
    keys_str = match.group(1)
    keys = [k.strip().strip('"').strip("'") for k in keys_str.split(",") if k.strip()]
    return {"keys": keys}


def _build_finish_params(match: re.Match) -> Dict[str, str]:
    """从正则匹配结果构建 finish 参数字典。"""
    return {"result": match.group(1)}


# 解析器列表，按优先级排序：click > type > scroll > hotkey > finish
_PARSERS = [
    (_PATTERN_CLICK, "click", _build_click_params),
    (_PATTERN_TYPE, "type", _build_type_params),
    (_PATTERN_SCROLL, "scroll", _build_scroll_params),
    (_PATTERN_HOTKEY, "hotkey", _build_hotkey_params),
    (_PATTERN_FINISH, "finish", _build_finish_params),
]
