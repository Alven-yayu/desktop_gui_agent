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
