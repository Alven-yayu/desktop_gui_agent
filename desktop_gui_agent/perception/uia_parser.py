# -*- coding: utf-8 -*-
"""UIA 感知模块 — 通过 Windows UI Automation API 获取控件树。

封装 pywinauto（UIA 后端），从当前前台窗口提取可交互控件的
名称、类型、精确边界框，用于与 OCR 结果融合标注。

仅 Windows 平台可用（UIA 是 Windows 专有 API）。
"""

import ctypes
import sys
from typing import Any, Dict, List, Optional
from ctypes import wintypes

from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# ===== 需要 UIA 感知的控件类型 =====
# 只收集用户会真正点击/交互的控件，避免标注图被无意义元素淹没
_INTERACTABLE_TYPES = frozenset({
    "Button",
    "Edit",
    "RadioButton",
    "CheckBox",
    "ListItem",
    "TabItem",
    "MenuItem",
    "Hyperlink",
    "ComboBox",
    "SplitButton",
    "TreeItem",
    "DataItem",
    "Thumb",       # 滑块/滚动条
    "Text",        # 可点击的文本块（超链接等）
})


class UiaParser:
    """Windows UI Automation 感知器。

    封装 pywinauto UIA 后端，从当前前台窗口获取控件树，
    返回可交互控件的名称、类型、精确边界框。

    用法（仅 Windows 生效，其他平台返回空列表）：
        controls = UiaParser.get_foreground_controls()
        # controls: [{"name": "7", "control_type": "Button",
        #             "bbox": (l,t,r,b), "enabled": True}, ...]
    """

    @staticmethod
    def get_foreground_controls(
        include_types: Optional[frozenset] = None,
    ) -> List[Dict[str, Any]]:
        """获取前台窗口的所有可交互控件。

        仅 Windows 平台生效。非 Windows 平台或获取失败时返回空列表。

        Args:
            include_types: 要收集的控件类型集合，None 则使用默认列表。

        Returns:
            控件信息列表，每个元素包含：
            - name:  控件名称（按钮文本、标签等）
            - control_type: UIA 控件类型名
            - bbox:  (left, top, right, bottom) 屏幕绝对坐标
            - enabled: 是否可交互
            - click_point: (cx, cy) 推荐点击位置（边界框中心）

            按人类阅读顺序排序（从上到下、从左到右）。
        """
        if sys.platform != "win32":
            logger.debug("非 Windows 平台，UIA 感知不可用")
            return []

        types_to_collect = include_types or _INTERACTABLE_TYPES

        try:
            hwnd = _get_foreground_hwnd()
            if hwnd is None or hwnd == 0:
                logger.debug("无法获取前台窗口句柄")
                return []

            window = _wrap_hwnd(hwnd)
            if window is None:
                return []

            controls = _collect_descendants(window, types_to_collect)

            # 按人类阅读顺序排序
            controls.sort(key=lambda c: (c["bbox"][1], c["bbox"][0]))

            logger.info(
                f"UIA 感知：前台窗口「{_get_window_title(hwnd)}」"
                f"，共 {len(controls)} 个可交互控件"
            )
            return controls

        except Exception as e:
            # NOTICE: UIA 解析失败不能影响主循环（某些非标准窗口可能
            # 不暴露 UIA 树），静默回退到纯 OCR 模式
            logger.debug(f"UIA 感知失败（回退到纯 OCR 模式）: {e}")
            return []

    @staticmethod
    def get_controls_by_hwnd(
        hwnd: int,
        include_types: Optional[frozenset] = None,
    ) -> List[Dict[str, Any]]:
        """获取指定窗口句柄的所有可交互控件。

        用于已知窗口句柄的精确场景（如通过进程名查找特定应用窗口）。

        Args:
            hwnd: 目标窗口句柄。
            include_types: 要收集的控件类型集合，None 则使用默认列表。

        Returns:
            控件信息列表，按阅读顺序排序。
        """
        if sys.platform != "win32":
            return []

        types_to_collect = include_types or _INTERACTABLE_TYPES

        try:
            window = _wrap_hwnd(hwnd)
            if window is None:
                return []

            controls = _collect_descendants(window, types_to_collect)
            controls.sort(key=lambda c: (c["bbox"][1], c["bbox"][0]))
            return controls

        except Exception as e:
            logger.debug(f"UIA 感知失败（hwnd={hwnd}）: {e}")
            return []


# ===== 内部辅助 =====


def _get_foreground_hwnd() -> Optional[int]:
    """获取当前前台窗口的 HWND（仅 Windows）。

    Returns:
        前台窗口句柄，失败返回 None。
    """
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if hwnd == 0:
        return None
    return hwnd


def _get_window_title(hwnd: int) -> str:
    """获取窗口标题（用于日志）。"""
    try:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return "(无标题)"
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return "(unknown)"


def _wrap_hwnd(hwnd: int):
    """用 pywinauto UIA 后端包装窗口句柄。

    Args:
        hwnd: 原始窗口句柄。

    Returns:
        pywinauto UIAWrapper 对象，失败返回 None。
    """
    from pywinauto import Desktop

    try:
        desktop = Desktop(backend="uia")
        # 通过句柄定位窗口
        window = desktop.window(handle=hwnd)
        if not window.exists():
            logger.debug(f"UIA 窗口不存在: hwnd={hwnd}")
            return None
        return window
    except Exception as e:
        logger.debug(f"UIA 包装窗口失败 (hwnd={hwnd}): {e}")
        return None


def _collect_descendants(window, include_types: frozenset) -> List[Dict[str, Any]]:
    """递归收集窗口子树中所有可交互控件。

    Args:
        window: pywinauto UIAWrapper 窗口对象。
        include_types: 需要收集的控件类型集合。

    Returns:
        控件信息列表。
    """
    controls: List[Dict[str, Any]] = []

    try:
        descendants = window.descendants()
    except Exception:
        # 某些特殊窗口（如 UWP）可能不支持全树遍历
        return controls

    for elem in descendants:
        try:
            ctrl_type = elem.element_info.control_type or ""
        except Exception:
            ctrl_type = ""

        if ctrl_type not in include_types:
            continue

        try:
            is_enabled = elem.element_info.enabled
        except Exception:
            is_enabled = False

        # 跳过禁用控件
        if not is_enabled:
            continue

        # 获取名称
        try:
            name = elem.element_info.name or ""
        except Exception:
            name = ""

        # 跳过空名称（通常是容器/分隔线等不可见元素）
        # 但对 Edit 控件放宽——搜索框可能无名称但有交互意义
        if not name.strip() and ctrl_type != "Edit":
            continue

        # 获取边界框
        try:
            rect = elem.element_info.rectangle
            if rect is None:
                continue
            left, top, right, bottom = (
                rect.left, rect.top, rect.right, rect.bottom
            )
        except Exception:
            continue

        # 过滤零尺寸控件
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            continue

        # 过滤超出常规屏幕范围的控件（多屏环境可能合法，但本例先过滤）
        if left < -1000 or top < -1000:
            continue

        controls.append({
            "name": name.strip(),
            "control_type": ctrl_type,
            "bbox": (left, top, right, bottom),
            "enabled": is_enabled,
            "click_point": ((left + right) // 2, (top + bottom) // 2),
        })

    return controls
