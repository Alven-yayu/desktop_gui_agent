# -*- coding: utf-8 -*-
"""感知模块测试 — screenshot + ocr_recognizer + ui_locator"""
import pytest
from PIL import Image

from desktop_gui_agent.perception.ui_locator import UILocator


# ===== 测试数据 =====

@pytest.fixture
def sample_ocr_results():
    """模拟 OCR 返回的识别结果"""
    return [
        {"text": "搜索按钮", "bbox": (100, 50, 200, 80), "confidence": 0.95},
        {"text": "确定", "bbox": (300, 200, 380, 230), "confidence": 0.90},
        {"text": "取消", "bbox": (400, 200, 480, 230), "confidence": 0.85},
        {"text": "Settings", "bbox": (10, 10, 80, 35), "confidence": 0.92},
    ]


@pytest.fixture
def sample_image():
    """创建一张测试用的纯白图片"""
    return Image.new("RGB", (800, 600), color=(255, 255, 255))


# ===== find_text 测试 =====

class TestFindText:
    """UILocator.find_text() 测试"""

    def test_find_text_exact_match(self, sample_ocr_results):
        """精确匹配：搜"确定"应该只找到"确定"这一条"""
        locator = UILocator()
        results = locator.find_text(sample_ocr_results, "确定")
        assert len(results) == 1
        assert results[0]["text"] == "确定"
        assert results[0]["bbox"] == (300, 200, 380, 230)

    def test_find_text_substring_match(self, sample_ocr_results):
        """子串匹配：搜"搜索"应该匹配"搜索按钮" """
        locator = UILocator()
        results = locator.find_text(sample_ocr_results, "搜索")
        assert len(results) == 1
        assert results[0]["text"] == "搜索按钮"

    def test_find_text_case_insensitive(self, sample_ocr_results):
        """大小写不敏感：搜"settings" 应该匹配 "Settings" """
        locator = UILocator()
        results = locator.find_text(sample_ocr_results, "settings")
        assert len(results) == 1
        assert results[0]["text"] == "Settings"

    def test_find_text_no_match(self, sample_ocr_results):
        """无匹配：搜"不存在"应该返回空列表"""
        locator = UILocator()
        results = locator.find_text(sample_ocr_results, "不存在")
        assert results == []

    def test_find_text_empty_ocr(self):
        """空 OCR 结果：应该返回空列表"""
        locator = UILocator()
        results = locator.find_text([], "搜索")
        assert results == []


# ===== draw_boxes 测试 =====

class TestDrawBoxes:
    """UILocator.draw_boxes() 测试"""

    def test_draw_boxes_returns_image(self, sample_image, sample_ocr_results):
        """应该返回一张 PIL Image"""
        locator = UILocator()
        result = locator.draw_boxes(sample_image, sample_ocr_results)
        assert isinstance(result, Image.Image)

    def test_draw_boxes_preserves_original(self, sample_image, sample_ocr_results):
        """不修改原图：返回的图片应该是一张新图"""
        locator = UILocator()
        original_mode = sample_image.mode
        locator.draw_boxes(sample_image, sample_ocr_results)
        # 原图的属性不应该变
        assert sample_image.mode == original_mode

    def test_draw_boxes_empty_ocr(self, sample_image):
        """空 OCR 结果：不画框，正常返回图片"""
        locator = UILocator()
        result = locator.draw_boxes(sample_image, [])
        assert isinstance(result, Image.Image)

    def test_draw_boxes_none_image_raises(self, sample_ocr_results):
        """空图片：应该抛出 UILocatorError"""
        from desktop_gui_agent.utils.exceptions import UILocatorError

        locator = UILocator()
        with pytest.raises(UILocatorError):
            locator.draw_boxes(None, sample_ocr_results)

    def test_draw_boxes_saves_file(self, sample_image, sample_ocr_results, tmp_path):
        """传了 output_path 应该保存文件"""
        output_path = str(tmp_path / "output.png")
        locator = UILocator()
        locator.draw_boxes(sample_image, sample_ocr_results, output_path=output_path)
        import os
        assert os.path.exists(output_path)


# ===== 终端窗口最小化测试 =====

class TestMinimizeConsole:
    """minimize_console() 测试"""

    def test_minimize_console_exists(self):
        """minimize_console 函数应可导入"""
        from desktop_gui_agent.perception.screenshot import minimize_console
        assert callable(minimize_console)

    def test_minimize_console_returns_bool(self):
        """minimize_console 应返回布尔值"""
        from desktop_gui_agent.perception.screenshot import minimize_console
        result = minimize_console()
        assert isinstance(result, bool)

    def test_minimize_console_no_error_on_non_windows(self, monkeypatch):
        """非 Windows 平台应直接返回 False，不报错"""
        monkeypatch.setattr("sys.platform", "darwin")
        from desktop_gui_agent.perception.screenshot import minimize_console
        result = minimize_console()
        assert result is False

    def test_minimize_console_no_console_window(self, monkeypatch):
        """无控制台句柄时函数不应崩溃（回退到 EnumWindows 或返回 False）"""
        monkeypatch.setattr("sys.platform", "win32")
        from unittest.mock import patch

        from desktop_gui_agent.perception.screenshot import minimize_console

        # Mock GetConsoleWindow 返回 0 + EnumWindows 不抛异常
        with patch("ctypes.windll.kernel32.GetConsoleWindow", return_value=0), \
             patch("desktop_gui_agent.perception.screenshot._minimize_own_windows",
                   return_value=False):
            result = minimize_console()
            assert isinstance(result, bool)  # 不崩溃即可，True 或 False 都行

    def test_is_terminal_window_recognizes_windows_terminal(self):
        """Windows Terminal 类名应被识别为终端窗口"""
        from unittest.mock import patch
        from desktop_gui_agent.perception.screenshot import _is_terminal_window

        def fake_getclass(hwnd, buf, size):
            buf.value = "CASCADIA_HOSTING_WINDOW_CLASS"
            return len(buf.value)

        with patch("ctypes.windll.user32.GetClassNameW", side_effect=fake_getclass):
            assert _is_terminal_window(1) is True

    def test_is_terminal_window_rejects_normal_window(self):
        """普通应用窗口类名不应被识别为终端"""
        from unittest.mock import patch
        from desktop_gui_agent.perception.screenshot import _is_terminal_window

        def fake_getclass(hwnd, buf, size):
            buf.value = "Notepad"
            return len(buf.value)

        with patch("ctypes.windll.user32.GetClassNameW", side_effect=fake_getclass):
            assert _is_terminal_window(1) is False


# ===== UiaParser 任务栏感知测试 =====

class TestUiaTaskbar:
    """UiaParser.get_taskbar_controls() 测试"""

    def test_get_taskbar_controls_returns_list(self):
        """应返回列表（Windows 上任务栏存在时可能非空）"""
        from desktop_gui_agent.perception.uia_parser import UiaParser
        result = UiaParser.get_taskbar_controls()
        assert isinstance(result, list)

    def test_get_taskbar_controls_non_windows(self, monkeypatch):
        """非 Windows 平台返回空列表"""
        monkeypatch.setattr("sys.platform", "darwin")
        from desktop_gui_agent.perception.uia_parser import UiaParser
        assert UiaParser.get_taskbar_controls() == []

    def test_taskbar_controls_have_bbox(self):
        """任务栏控件应含 bbox/click_point 字段"""
        from desktop_gui_agent.perception.uia_parser import UiaParser
        controls = UiaParser.get_taskbar_controls()
        for c in controls:
            assert "bbox" in c
            assert "click_point" in c


# ===== annotate_screenshot OCR 点击点测试 =====

class TestAnnotateOcrClickPoint:
    """annotate_screenshot 的 OCR 点击点定位测试。

    设计意图：桌面图标在文字上方，点击需落在图标上（双击打开），
    点文字会进重命名模式 → 桌面场景点击点向上偏移一个文字高度；
    应用窗口内文字本身就是要点击的目标（菜单项/列表项）→ 取文字中心。
    """

    def _annotate_ocr(self, is_desktop=False, text="确定",
                      bbox=(100, 50, 200, 80)):
        """辅助：用单条 OCR 结果跑 annotate_screenshot，返回 marker_map。"""
        from desktop_gui_agent.perception.screenshot import annotate_screenshot
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        ocr = [{"text": text, "bbox": bbox, "confidence": 0.9}]
        _, marker_map = annotate_screenshot(
            img, ocr, task="测试", uia_controls=[], is_desktop=is_desktop,
        )
        return marker_map

    def test_ocr_click_point_is_text_center_in_app(self):
        """应用窗口内：OCR 点击点应为文字中心 (150, 65)"""
        marker_map = self._annotate_ocr(is_desktop=False)
        assert marker_map[1]["click_point"] == (150, 65)

    def test_ocr_click_point_not_above_text_in_app(self):
        """应用窗口内：点击点不应再是文字上方 (150, 20)"""
        marker_map = self._annotate_ocr(is_desktop=False)
        assert marker_map[1]["click_point"] != (150, 20)

    def test_ocr_click_point_offset_on_desktop(self):
        """桌面：OCR 点击点应上偏一个文字高度，落在图标上 (150, 20)"""
        marker_map = self._annotate_ocr(is_desktop=True)
        # 文字高度 = 80-50 = 30，文字顶 y=50，上偏后 y = max(0, 50-30) = 20
        assert marker_map[1]["click_point"] == (150, 20)

    def test_ocr_click_point_desktop_preserves_icon_intent(self):
        """桌面：点击点的 y 应显著小于文字中心 y，指向图标而非文字"""
        marker_map = self._annotate_ocr(is_desktop=True)
        cp = marker_map[1]["click_point"]
        assert cp[1] < 65  # 文字中心 y=65，上偏后必须在其上方

    def test_max_items_defaults_from_config(self):
        """默认最多标注 ANNOTATE_MAX_ITEMS 个元素"""
        from desktop_gui_agent.config import ANNOTATE_MAX_ITEMS
        from desktop_gui_agent.perception.screenshot import annotate_screenshot

        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        # max_items+1 条互不相同的 OCR 文字。注意：文本不能包含任务关键词，
        # 否则会被 _is_ocr_noise 当作噪声过滤（task 会加入噪声模式）。
        ocr = [
            {"text": f"按钮{i:02d}", "bbox": (50, 10 + i * 10, 150, 35 + i * 10), "confidence": 0.9}
            for i in range(ANNOTATE_MAX_ITEMS + 1)
        ]
        _, marker_map = annotate_screenshot(img, ocr, task="", uia_controls=[])
        assert len(marker_map) == ANNOTATE_MAX_ITEMS  # 超出的最后一条被截断

    def test_uia_marker_keeps_control_name(self):
        """UIA 标注应保留控件文字，供模型核对"编号=含义"（防猜按钮）"""
        from desktop_gui_agent.perception.screenshot import annotate_screenshot
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        uia = [{
            "name": "二", "control_type": "Button",
            "bbox": (100, 100, 160, 140), "click_point": (130, 120),
        }]
        _, marker_map = annotate_screenshot(img, [], task="", uia_controls=uia)
        assert marker_map[1]["source"] == "uia"
        assert marker_map[1]["text"] == "二"

    def test_ocr_warm_up_starts_worker(self):
        """warm_up 应触发 OCR 子进程启动（提前预热冷启动，避免首步卡死）"""
        from unittest.mock import MagicMock
        import desktop_gui_agent.perception.ocr_recognizer as ocr_mod
        mock_worker = MagicMock()
        mock_worker._ensure_started.return_value = True
        ocr_mod._worker = mock_worker
        assert ocr_mod.warm_up() is True
        mock_worker._ensure_started.assert_called_once()
        ocr_mod._worker = None

    def test_ocr_warm_up_failure_returns_false(self):
        """worker 启动失败时 warm_up 返回 False（agent 降级纯 UIA）"""
        from unittest.mock import MagicMock
        import desktop_gui_agent.perception.ocr_recognizer as ocr_mod
        mock_worker = MagicMock()
        mock_worker._ensure_started.return_value = False
        ocr_mod._worker = mock_worker
        assert ocr_mod.warm_up() is False
        ocr_mod._worker = None

    def test_annotation_reserves_ocr_slots_when_uia_dense(self):
        """UIA 控件占满上限时，OCR 仍有预留名额——任务目标文字（如桌面"QQ音乐"
        图标）不被 UIA 桌面图标饿死，保证有稳定编号可点"""
        from desktop_gui_agent.perception.screenshot import annotate_screenshot
        from desktop_gui_agent.config import ANNOTATE_OCR_RESERVED
        img = Image.new("RGB", (800, 600), color=(255, 255, 255))
        # 70 个 UIA 图标（远超标注上限，模拟密集桌面）
        uia = [
            {"name": f"图标{i}", "control_type": "Button",
             "bbox": (10 + i * 15, 10, 20 + i * 15, 30),
             "click_point": (15 + i * 15, 20)}
            for i in range(70)
        ]
        ocr = [{"text": "QQ音乐", "bbox": (500, 400, 560, 430), "confidence": 0.99}]
        _, marker_map = annotate_screenshot(
            img, ocr, task="打开QQ音乐", uia_controls=uia
        )
        texts = [m["text"] for m in marker_map.values()]
        assert "QQ音乐" in texts  # 目标文字一定有编号（不被 UIA 桌面图标饿死）
        uia_count = sum(1 for m in marker_map.values() if m["source"] == "uia")
        # UIA 不能占用预留的 OCR 名额
        from desktop_gui_agent.config import ANNOTATE_MAX_ITEMS
        assert uia_count <= ANNOTATE_MAX_ITEMS - ANNOTATE_OCR_RESERVED
