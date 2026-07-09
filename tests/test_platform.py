# -*- coding: utf-8 -*-
"""PlatformInfo 跨平台适配测试（Phase 5.3）"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest


class TestPlatformInfo:
    """PlatformInfo 平台检测测试"""

    def test_is_windows_on_win32(self):
        """sys.platform='win32' 时 is_windows 应为 True"""
        with patch("sys.platform", "win32"):
            # 重新加载模块以反映 mock 的 platform
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            assert plat.PlatformInfo.is_windows is True
            assert plat.PlatformInfo.is_macos is False
            assert plat.PlatformInfo.is_linux is False
            assert plat.PlatformInfo.os_name == "windows"

    def test_is_macos_on_darwin(self):
        """sys.platform='darwin' 时 is_macos 应为 True"""
        with patch("sys.platform", "darwin"):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            assert plat.PlatformInfo.is_windows is False
            assert plat.PlatformInfo.is_macos is True
            assert plat.PlatformInfo.is_linux is False
            assert plat.PlatformInfo.os_name == "macos"

    def test_is_linux_on_linux(self):
        """sys.platform='linux' 时 is_linux 应为 True"""
        with patch("sys.platform", "linux"):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            assert plat.PlatformInfo.is_windows is False
            assert plat.PlatformInfo.is_macos is False
            assert plat.PlatformInfo.is_linux is True
            assert plat.PlatformInfo.os_name == "linux"

    def test_is_linux_also_on_other_platforms(self):
        """未知 sys.platform 也归类为 is_linux"""
        with patch("sys.platform", "freebsd"):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            assert plat.PlatformInfo.is_windows is False
            assert plat.PlatformInfo.is_macos is False
            assert plat.PlatformInfo.is_linux is True
            assert plat.PlatformInfo.os_name == "linux"

    def test_os_name_is_string(self):
        """os_name 应该是字符串"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        assert isinstance(PlatformInfo.os_name, str)
        assert PlatformInfo.os_name in ("windows", "macos", "linux")


class TestGetChineseFontPath:
    """PlatformInfo.get_chinese_font_path() 测试"""

    def test_returns_path_on_windows_with_font(self):
        """Windows 平台找到字体文件应返回路径"""
        with patch("sys.platform", "win32"), \
             patch("os.path.isfile", return_value=True):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            result = plat.PlatformInfo.get_chinese_font_path()
            assert result is not None
            assert "msyh.ttc" in result

    def test_returns_none_when_no_font_exists(self):
        """所有候选字体都不存在时返回 None"""
        with patch("os.path.isfile", return_value=False):
            from desktop_gui_agent.utils.platform import PlatformInfo
            result = PlatformInfo.get_chinese_font_path()
            assert result is None

    def test_returns_first_existing_font(self):
        """应返回第一个存在的字体路径"""
        real_isfile = os.path.isfile

        def mock_isfile(path):
            # 只让 simhei.ttf 返回 True
            return "simhei.ttf" in path

        with patch("sys.platform", "win32"), \
             patch("os.path.isfile", side_effect=mock_isfile):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            result = plat.PlatformInfo.get_chinese_font_path()
            assert result is not None
            assert "simhei.ttf" in result

    def test_macos_returns_path_with_font(self):
        """macOS 平台找到字体应返回路径"""
        with patch("sys.platform", "darwin"), \
             patch("os.path.isfile", return_value=True):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            result = plat.PlatformInfo.get_chinese_font_path()
            assert result is not None
            assert "PingFang.ttc" in result

    def test_linux_returns_path_with_font(self):
        """Linux 平台找到字体应返回路径"""
        with patch("sys.platform", "linux"), \
             patch("os.path.isfile", return_value=True):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            result = plat.PlatformInfo.get_chinese_font_path()
            assert result is not None
            assert "NotoSansCJK" in result


class TestGetLogDir:
    """PlatformInfo.get_log_dir() 测试"""

    def test_returns_path_object(self):
        """返回值应为 pathlib.Path 对象"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        from pathlib import Path
        result = PlatformInfo.get_log_dir()
        assert isinstance(result, Path)

    def test_log_dir_exists(self):
        """返回的日志目录必须存在（方法内部自动创建）"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        result = PlatformInfo.get_log_dir()
        assert result.exists()
        assert result.is_dir()

    def test_log_dir_ends_with_logs(self):
        """目录名应以 logs 结尾"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        result = PlatformInfo.get_log_dir()
        assert result.name == "logs"


class TestGetRecommendedModifierKey:
    """PlatformInfo.get_recommended_modifier_key() 测试"""

    def test_windows_returns_win(self):
        """Windows 平台修饰键应为 'win'"""
        with patch("sys.platform", "win32"):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            assert plat.PlatformInfo.get_recommended_modifier_key() == "win"

    def test_macos_returns_cmd(self):
        """macOS 平台修饰键应为 'cmd'"""
        with patch("sys.platform", "darwin"):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            assert plat.PlatformInfo.get_recommended_modifier_key() == "cmd"

    def test_linux_returns_win(self):
        """Linux 平台修饰键应为 'win'"""
        with patch("sys.platform", "linux"):
            import importlib
            import desktop_gui_agent.utils.platform as plat
            importlib.reload(plat)
            assert plat.PlatformInfo.get_recommended_modifier_key() == "win"

    def test_returns_string(self):
        """返回值应为字符串"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        result = PlatformInfo.get_recommended_modifier_key()
        assert isinstance(result, str)
        assert result in ("win", "cmd")
