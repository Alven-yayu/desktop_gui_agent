"""自定义异常类 — PDF 4.1.2 异常处理"""


class OCRError(Exception):
    """OCR 识别失败（模型加载失败、识别异常）"""
    pass


class ScreenshotError(Exception):
    """截图失败（屏幕不存在等）"""
    pass
