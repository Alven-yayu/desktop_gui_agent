# -*- coding: utf-8 -*-
"""UI 元素定位与可视化模块。

基于 OCR 识别结果，查找屏幕上的 UI 元素，并支持在截图上可视化标注。
"""
import os
import sys
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from desktop_gui_agent.config import UI_BOX_COLOR, UI_LINE_WIDTH
from desktop_gui_agent.utils.exceptions import UILocatorError
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# ===== 中文字体查找 =====
# PIL 默认字体不支持中文渲染，需找到支持中文的系统字体。
# Windows: 按优先级搜索 微软雅黑 / 黑体 / 宋体
# macOS: 苹方 / 黑体
# Linux: Noto Sans CJK / WenQuanYi
_CHINESE_FONT_CANDIDATES = []
if sys.platform == "win32":
    _CHINESE_FONT_CANDIDATES = [
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyh.ttc"),   # 微软雅黑
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyhbd.ttc"), # 微软雅黑粗体
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "simhei.ttf"), # 黑体
        os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "simsun.ttc"), # 宋体
    ]
elif sys.platform == "darwin":
    _CHINESE_FONT_CANDIDATES = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]
else:
    _CHINESE_FONT_CANDIDATES = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]


def _get_chinese_font(size: int = 14) -> ImageFont.FreeTypeFont:
    """查找并返回支持中文的字体。

    按平台依次尝试常见中文字体，若全部缺失则回退到 PIL 默认字体。

    Args:
        size: 字体大小（像素）。

    Returns:
        ImageFont 对象（优先 FreeTypeFont，否则默认 bitmap 字体）。
    """
    for font_path in _CHINESE_FONT_CANDIDATES:
        if os.path.isfile(font_path):
            try:
                return ImageFont.truetype(font_path, size=size)
            except (OSError, IOError):
                continue

    # 全部失败时回退到 PIL 默认字体（中文会显示为方块，但不抛异常）
    logger.warning("未找到中文字体，标注中的中文可能无法正常显示")
    return ImageFont.load_default()


class UILocator:
    """UI 元素定位器。

    功能：
    - 根据文字关键词在 OCR 结果中查找元素
    - 在截图上绘制检测框和文字标签

    Attributes:
        box_color: 检测框颜色（十六进制字符串，如 "#00FF00"）。
        line_width: 检测框线宽（像素）。
    """

    def __init__(self, box_color: str = UI_BOX_COLOR, line_width: int = UI_LINE_WIDTH):
        """初始化定位器。

        Args:
            box_color: 检测框颜色。
            line_width: 检测框线宽。
        """
        self.box_color = box_color
        self.line_width = line_width

    def find_text(self, ocr_results: List[Dict], query: str) -> List[Dict]:
        """在 OCR 结果中查找包含目标文字的元素（子串匹配，大小写不敏感）。

        Args:
            ocr_results: OCR 识别结果列表，每项含 "text", "bbox", "confidence"。
            query: 要查找的文字关键词。

        Returns:
            匹配到的元素列表（原样返回 OCR 结果中的 dict）。
            无匹配或输入为空时返回空列表。
        """
        if not ocr_results:
            return []

        query_lower = query.lower()
        matches = []
        for item in ocr_results:
            if query_lower in item["text"].lower():
                matches.append(item)
        return matches

    def draw_boxes(
        self,
        image: Image.Image,
        ocr_results: List[Dict],
        output_path: Optional[str] = None,
    ) -> Image.Image:
        """在截图上绘制所有 OCR 检测框和文字标签。

        不修改原图，返回一张新的标注图片。

        Args:
            image: 原始截图（PIL Image）。
            ocr_results: OCR 识别结果列表。
            output_path: 可选，保存到指定文件路径（目录不存在会自动创建）。

        Returns:
            绘制了检测框和标签的新 PIL Image 对象。

        Raises:
            UILocatorError: image 为 None 时。
        """
        if image is None:
            raise UILocatorError("无法绘制：输入图片为空")

        # 复制原图，避免修改原始图片
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)

        # 查找支持中文的字体
        font = _get_chinese_font(size=14)

        for item in ocr_results:
            bbox = item["bbox"]
            x1, y1, x2, y2 = bbox

            # 画矩形框
            draw.rectangle([x1, y1, x2, y2], outline=self.box_color, width=self.line_width)

            # 画文字标签（放在框的左上角上方）
            label = f"{item['text']} ({item['confidence']:.2f})"
            draw.text((x1, max(0, y1 - 18)), label, fill=self.box_color, font=font)

        # 可选保存到文件
        if output_path is not None:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            annotated.save(output_path)
            logger.info(f"标注图片已保存到: {output_path}")

        return annotated
