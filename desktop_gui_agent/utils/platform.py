# -*- coding: utf-8 -*-
"""平台检测与资源适配工具。

统一管理平台判断逻辑和平台相关资源路径，
收拢散落在各模块的 sys.platform 判断。
"""
import os
import sys
from pathlib import Path
from typing import Optional


class PlatformInfo:
    """平台信息工具类。

    在模块加载时检测当前平台并缓存结果。
    提供跨平台的字体路径、日志目录、修饰键等资源。

    Attributes:
        is_windows: 是否为 Windows。
        is_macos: 是否为 macOS。
        is_linux: 是否为 Linux。
        os_name: 平台名称字符串（"windows"/"macos"/"linux"）。
    """

    is_windows: bool = sys.platform == "win32"
    is_macos: bool = sys.platform == "darwin"
    is_linux: bool = sys.platform not in ("win32", "darwin")
    os_name: str = (
        "windows" if is_windows
        else "macos" if is_macos
        else "linux"
    )

    # ===== 中文字体候选路径 =====
    _FONT_CANDIDATES: dict = {
        "win32": [
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyh.ttc"),
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyhbd.ttc"),
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "simhei.ttf"),
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "simsun.ttc"),
        ],
        "darwin": [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
        ],
        "linux": [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ],
    }

    @staticmethod
    def get_chinese_font_path() -> Optional[str]:
        """查找系统中可用的中文字体，返回第一个存在的字体路径。

        按平台依次尝试已知的常见中文字体路径。
        若全部缺失则返回 None，调用方应回退到 PIL 默认字体。

        Returns:
            字体文件路径，未找到时返回 None。
        """
        candidates = PlatformInfo._FONT_CANDIDATES.get(sys.platform, [])
        for font_path in candidates:
            if os.path.isfile(font_path):
                return font_path
        return None

    @staticmethod
    def get_log_dir() -> Path:
        """获取日志存储目录的绝对路径。

        以项目根目录（desktop_gui_agent 的父目录）为基准，
        返回 ``<项目根>/logs/`` 的绝对路径。

        Returns:
            logs 目录的 Path 对象。
        """
        # utils/platform.py → utils/ → desktop_gui_agent/ → 项目根
        project_root = Path(__file__).resolve().parent.parent.parent
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    @staticmethod
    def get_recommended_modifier_key() -> str:
        """返回当前平台推荐的主修饰键。

        Windows / Linux → ``"win"``
        macOS → ``"cmd"``

        Returns:
            修饰键名称字符串。
        """
        if sys.platform == "darwin":
            return "cmd"
        return "win"
