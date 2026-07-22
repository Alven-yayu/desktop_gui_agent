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

# marker 动作（推荐！模型只需指定编号，代码翻译为坐标）
_PATTERN_CLICK_MARKER = re.compile(
    r'click_marker\s*\(\s*(\d+)\s*\)',
    re.IGNORECASE,
)
_PATTERN_DOUBLE_CLICK_MARKER = re.compile(
    r'double_click_marker\s*\(\s*(\d+)\s*\)',
    re.IGNORECASE,
)

# 传统坐标动作（兼容旧版，不推荐）
_PATTERN_DOUBLE_CLICK = re.compile(
    r'double_click\s*\(\s*x\s*=\s*(-?\d+)\s*,\s*y\s*=\s*(-?\d+)\s*\)',
    re.IGNORECASE,
)

_PATTERN_CLICK = re.compile(
    r'(?<!_)click\s*\(\s*x\s*=\s*(-?\d+)\s*,\s*y\s*=\s*(-?\d+)\s*\)',
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

    # 搜索范围：优先匹配含"动作："的行，否则搜全部行
    lines = text.split("\n")
    candidates = [l.strip() for l in lines]

    # 如果有"动作："开头或"动作："所在的行，优先匹配
    action_lines = [l for l in candidates if "动作：" in l]
    search_lines = action_lines + candidates  # 优先搜动作行

    for line in search_lines:
        # 去掉可能的"动作："前缀
        clean = line.replace("动作：", "").replace("动作:", "").strip()
        for pattern, action_type, params_builder in _PARSERS:
            match = pattern.search(clean)
            if match:
                params = params_builder(match)
                if params is not None:
                    logger.info(f"解析成功: {action_type} {params}")
                    return {"action_type": action_type, "params": params}

    # 所有模式都不匹配
    logger.warning(f"无法解析模型输出: {text[:100]}")
    return {"action_type": "unknown", "raw": text}


def _build_click_marker_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 click_marker 参数字典。"""
    return {"marker": int(match.group(1))}


def _build_double_click_marker_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 double_click_marker 参数字典。"""
    return {"marker": int(match.group(1))}


def _build_double_click_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 double_click 参数字典。"""
    return {"x": int(match.group(1)), "y": int(match.group(2))}


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
    """从正则匹配结果构建 hotkey 参数字典。

    支持三种格式：
    - hotkey(ctrl, c)      逗号分隔
    - hotkey(\"ctrl\", \"c\")  带引号逗号分隔
    - hotkey(\"ctrl+c\")     加号连接（模型有时会这样输出）
    """
    keys_str = match.group(1)
    # 先尝试逗号分隔
    if "," in keys_str:
        keys = [k.strip().strip('"').strip("'") for k in keys_str.split(",") if k.strip()]
    else:
        # 否则按 + 分隔（处理 "win+r" 格式）
        keys = [k.strip().strip('"').strip("'") for k in keys_str.split("+") if k.strip()]
    return {"keys": keys}


def _build_finish_params(match: re.Match) -> Dict[str, str]:
    """从正则匹配结果构建 finish 参数字典。"""
    return {"result": match.group(1)}


# 解析器列表，按优先级排序：click > type > scroll > hotkey > finish
_PARSERS = [
    # marker 动作优先——模型只需给编号，代码翻译坐标
    (_PATTERN_CLICK_MARKER, "click_marker", _build_click_marker_params),
    (_PATTERN_DOUBLE_CLICK_MARKER, "double_click_marker", _build_double_click_marker_params),
    # 传统坐标动作（兼容）
    (_PATTERN_DOUBLE_CLICK, "double_click", _build_double_click_params),
    (_PATTERN_CLICK, "click", _build_click_params),
    (_PATTERN_TYPE, "type", _build_type_params),
    (_PATTERN_SCROLL, "scroll", _build_scroll_params),
    (_PATTERN_HOTKEY, "hotkey", _build_hotkey_params),
    (_PATTERN_FINISH, "finish", _build_finish_params),
]
