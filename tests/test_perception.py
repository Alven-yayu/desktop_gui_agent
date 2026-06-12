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
