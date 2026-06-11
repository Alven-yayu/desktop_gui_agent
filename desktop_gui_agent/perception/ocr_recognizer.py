from typing import List, Dict, Any

import numpy as np
from paddleocr import PaddleOCR
from PIL import Image

from desktop_gui_agent.config import OCR_LANG, OCR_CONFIDENCE_THRESHOLD
from desktop_gui_agent.utils.exceptions import OCRError
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

_ocr_engine = None

def _get_ocr_engine() -> PaddleOCR:
    global _ocr_engine
    if _ocr_engine is None:
        try:
            _ocr_engine = PaddleOCR(
                use_angle_cls=True,
                lang=OCR_LANG,
                show_log=False
            )
            logger.info("OCR 引擎加载成功")
        except Exception as e:
            logger.error(f"OCR 引擎加载失败: {e}")
            raise OCRError("OCR 引擎加载失败")
    return _ocr_engine


def recognize(image: Image.Image) -> List[Dict[str, Any]]:
    """识别图片中的文字，返回结构化结果。

    Args:
        image: PIL Image 截图。

    Returns:
        识别结果列表，每个元素为 {"text": str, "bbox": (x1,y1,x2,y2), "confidence": float}。
        无文字或输入为空时返回空列表。
    """
    if image is None:
        logger.warning("输入图片为空，跳过 OCR")
        return []

    engine = _get_ocr_engine()
    # PaddleOCR 2.x 需要 numpy 数组，把 PIL Image 转过去
    img_array = np.array(image)
    result = engine.ocr(img_array)

    if not result or not result[0]:
        logger.info("未识别到文字")
        return []

    elements = []
    for line in result[0]:
        box, (text, conf) = line
        if conf < OCR_CONFIDENCE_THRESHOLD:
            continue
        x1, y1 = box[0]
        x2, y2 = box[2]
        elements.append({
            "text": text,
            "bbox": (int(x1), int(y1), int(x2), int(y2)),
            "confidence": round(conf, 4),
        })

    logger.info(f"识别到 {len(elements)} 个文字元素")
    return elements

