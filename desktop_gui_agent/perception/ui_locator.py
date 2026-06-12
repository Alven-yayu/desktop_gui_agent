"""UI 元素定位与可视化模块。

基于 OCR 识别结果，查找屏幕上的 UI 元素，并支持在截图上可视化标注。
"""
import os
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from desktop_gui_agent.config import UI_BOX_COLOR, UI_LINE_WIDTH
from desktop_gui_agent.utils.exceptions import UILocatorError
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)


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

        # 使用 PIL 默认字体
        try:
            font = ImageFont.truetype("arial.ttf", size=14)
        except (OSError, IOError):
            font = ImageFont.load_default()

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
