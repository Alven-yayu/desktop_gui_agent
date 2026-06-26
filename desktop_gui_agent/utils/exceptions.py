# -*- coding: utf-8 -*-
"""自定义异常类 — PDF 4.1.2 异常处理"""


class OCRError(Exception):
    """OCR 识别失败（模型加载失败、识别异常）"""
    pass


class ScreenshotError(Exception):
    """截图失败（屏幕不存在等）"""
    pass


class UILocatorError(Exception):
    """UI 定位失败（空图片、OCR 结果异常等）"""
    pass


class ControlError(Exception):
    """控制操作失败（坐标越界、权限不足、设备未连接等）"""
    pass


class ModelError(Exception):
    """模型推理失败（模型加载失败、推理超时、API调用失败等）"""
    pass
