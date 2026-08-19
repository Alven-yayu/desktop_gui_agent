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
# 注意：(?<!_) 负向断言防止 right_click_marker / drag_marker 的子串
# "click_marker(" 被本正则误命中（如 right_click_marker(3) 内含 click_marker(3)）。
# 可选 text="..." 参数：模型声明它认为该标注的文字，执行层据此核对，
# 防止模型凭想象/幻觉点错标注（点击目标核对守卫）。
_PATTERN_CLICK_MARKER = re.compile(
    r'(?<!_)click_marker\s*\(\s*(\d+)\s*(?:,\s*text\s*=\s*"([^"]*)"\s*)?\)',
    re.IGNORECASE,
)
_PATTERN_DOUBLE_CLICK_MARKER = re.compile(
    r'(?<!_)double_click_marker\s*\(\s*(\d+)\s*(?:,\s*text\s*=\s*"([^"]*)"\s*)?\)',
    re.IGNORECASE,
)

# 右键（marker + 坐标）
_PATTERN_RIGHT_CLICK_MARKER = re.compile(
    r'(?<!_)right_click_marker\s*\(\s*(\d+)\s*(?:,\s*text\s*=\s*"([^"]*)"\s*)?\)',
    re.IGNORECASE,
)
_PATTERN_RIGHT_CLICK = re.compile(
    r'(?<!_)right_click\s*\(\s*x\s*=\s*(-?\d+)\s*,\s*y\s*=\s*(-?\d+)\s*\)',
    re.IGNORECASE,
)

# 拖拽（marker→marker + 坐标）
_PATTERN_DRAG_MARKER = re.compile(
    r'(?<!_)drag_marker\s*\(\s*from\s*=\s*(\d+)\s*,\s*to\s*=\s*(\d+)\s*\)',
    re.IGNORECASE,
)
_PATTERN_DRAG = re.compile(
    r'(?<!_)drag\s*\(\s*x1\s*=\s*(-?\d+)\s*,\s*y1\s*=\s*(-?\d+)\s*,\s*x2\s*=\s*(-?\d+)\s*,\s*y2\s*=\s*(-?\d+)\s*\)',
    re.IGNORECASE,
)

# 单键按下（支持 press(key="tab") 与 press(key=tab)）
_PATTERN_PRESS = re.compile(
    r'(?<!_)press\s*\(\s*key\s*=\s*"?([a-zA-Z0-9_]+)"?\s*\)',
    re.IGNORECASE,
)

# 滑块精确设值（UIA RangeValue 模式直接设，不用鼠标拖拽）
_PATTERN_SET_SLIDER = re.compile(
    r'(?<!_)set_slider\s*\(\s*marker\s*=\s*(\d+)\s*,\s*value\s*=\s*(\d+)\s*\)',
    re.IGNORECASE,
)

# 通用控件设值：按控件类型自动分发（滑块/输入框/复选框/下拉框/单选）
# value 支持引号字符串（下拉选项、文本）或数字（滑块）
_PATTERN_SET_CONTROL = re.compile(
    r'(?<!_)set_control\s*\(\s*marker\s*=\s*(\d+)\s*,\s*value\s*=\s*(?:"([^"]*)"|(\d+))\s*\)',
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

# type 支持可选 enter=True：输入后立即回车（搜索/地址栏/算式等需要确认的场景）。
# 一次动作完成"输入+确认"，避免模型在两步之间做多余的中间判断（如计算器反复补数字）。
_PATTERN_TYPE = re.compile(
    r'type\s*\(\s*text\s*=\s*"(.*?)"\s*(?:,\s*enter\s*=\s*(True|False))?\s*\)',
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


def _build_click_marker_params(match: re.Match) -> Dict[str, Any]:
    """从正则匹配结果构建 click_marker 参数字典。

    支持可选 text 参数：模型声明它认为该标注的文字，
    供执行层核对真实标注内容（防幻觉误点）。
    """
    params: Dict[str, Any] = {"marker": int(match.group(1))}
    if match.group(2) is not None and match.group(2).strip():
        params["text"] = match.group(2).strip()
    return params


def _build_double_click_marker_params(match: re.Match) -> Dict[str, Any]:
    """从正则匹配结果构建 double_click_marker 参数字典。"""
    params: Dict[str, Any] = {"marker": int(match.group(1))}
    if match.group(2) is not None and match.group(2).strip():
        params["text"] = match.group(2).strip()
    return params


def _build_right_click_marker_params(match: re.Match) -> Dict[str, Any]:
    """从正则匹配结果构建 right_click_marker 参数字典。"""
    params: Dict[str, Any] = {"marker": int(match.group(1))}
    if match.group(2) is not None and match.group(2).strip():
        params["text"] = match.group(2).strip()
    return params


def _build_right_click_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 right_click 参数字典。"""
    return {"x": int(match.group(1)), "y": int(match.group(2))}


def _build_drag_marker_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 drag_marker 参数字典。"""
    return {"from": int(match.group(1)), "to": int(match.group(2))}


def _build_drag_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 drag 参数字典。"""
    return {
        "x1": int(match.group(1)),
        "y1": int(match.group(2)),
        "x2": int(match.group(3)),
        "y2": int(match.group(4)),
    }


def _build_press_params(match: re.Match) -> Dict[str, str]:
    """从正则匹配结果构建 press 参数字典。"""
    return {"key": match.group(1)}


def _build_set_slider_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 set_slider 参数字典。"""
    return {"marker": int(match.group(1)), "value": int(match.group(2))}


def _build_set_control_params(match: re.Match) -> Dict[str, Any]:
    """从正则匹配结果构建 set_control 参数字典。

    value 支持两种形式：
    - 引号字符串（下拉框选项、输入框文本、复选状态）
    - 数字（滑块目标值）
    """
    marker = int(match.group(1))
    if match.group(2) is not None:
        value = match.group(2)  # 带引号的字符串
    else:
        value = int(match.group(3))  # 数字
    return {"marker": marker, "value": value}


def _build_double_click_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 double_click 参数字典。"""
    return {"x": int(match.group(1)), "y": int(match.group(2))}


def _build_click_params(match: re.Match) -> Dict[str, int]:
    """从正则匹配结果构建 click 参数字典。"""
    return {"x": int(match.group(1)), "y": int(match.group(2))}


def _build_type_params(match: re.Match) -> Dict[str, Any]:
    """从正则匹配结果构建 type 参数字典。

    enter=True 表示输入后立即回车（由执行层完成，避免模型两步间多判断）。
    """
    params: Dict[str, Any] = {"text": match.group(1)}
    if match.group(2) == "True":
        params["enter"] = True
    return params


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


# 解析器列表，按优先级排序：marker 动作优先 > 右键/拖拽/单键 > 传统坐标 > 其余
# 注意：right_click_marker 必须排在 click_marker 之前（虽然已有负向断言兜底，
# 排前面更保险），drag_marker 也要在 click/double_click 之前，防止被吞。
_PARSERS = [
    (_PATTERN_RIGHT_CLICK_MARKER, "right_click_marker", _build_right_click_marker_params),
    (_PATTERN_RIGHT_CLICK, "right_click", _build_right_click_params),
    (_PATTERN_CLICK_MARKER, "click_marker", _build_click_marker_params),
    (_PATTERN_DOUBLE_CLICK_MARKER, "double_click_marker", _build_double_click_marker_params),
    (_PATTERN_DRAG_MARKER, "drag_marker", _build_drag_marker_params),
    (_PATTERN_DRAG, "drag", _build_drag_params),
    (_PATTERN_SET_SLIDER, "set_slider", _build_set_slider_params),
    (_PATTERN_SET_CONTROL, "set_control", _build_set_control_params),
    (_PATTERN_PRESS, "press", _build_press_params),
    # 传统坐标动作（兼容）
    (_PATTERN_DOUBLE_CLICK, "double_click", _build_double_click_params),
    (_PATTERN_CLICK, "click", _build_click_params),
    (_PATTERN_TYPE, "type", _build_type_params),
    (_PATTERN_SCROLL, "scroll", _build_scroll_params),
    (_PATTERN_HOTKEY, "hotkey", _build_hotkey_params),
    (_PATTERN_FINISH, "finish", _build_finish_params),
]
