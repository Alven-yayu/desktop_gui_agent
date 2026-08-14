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


# ===== 错误分类（Phase 5）=====

from enum import Enum


class ErrorCategory(Enum):
    """错误类别枚举，用于 TaskManager 的错误处理策略选择。

    RETRYABLE: 可重试（截图偶然失败、网络波动）
    SKIP:      跳过当前步（OCR失败、解析失败、坐标越界）
    FATAL:     立即终止（模型加载失败、配置错误）
    """
    RETRYABLE = "retryable"
    SKIP = "skip"
    FATAL = "fatal"


def classify_error(exception: Exception) -> ErrorCategory:
    """根据异常类型返回错误类别，用于决定错误处理策略。

    分类规则：
    - ScreenshotError / 网络超时 / 连接错误 → RETRYABLE
    - OCRError / 解析失败 / 坐标越界 / 执行失败 → SKIP
    - 模型加载失败 → FATAL
    - 未知异常 → SKIP（保守策略）

    Args:
        exception: 捕获到的异常对象。

    Returns:
        ErrorCategory 枚举值。
    """
    # RETRYABLE: 截图失败
    if isinstance(exception, ScreenshotError):
        return ErrorCategory.RETRYABLE

    # RETRYABLE: 网络相关
    try:
        import requests
        if isinstance(exception, (requests.Timeout, requests.ConnectionError)):
            return ErrorCategory.RETRYABLE
    except ImportError:
        pass

    # FATAL: 模型加载失败（注意：要在 SKIP 的 ModelError 判断之前）
    if isinstance(exception, ModelError):
        msg = str(exception)
        if "加载失败" in msg or "加载" in msg:
            return ErrorCategory.FATAL
        # API 调用已重试失败 → SKIP
        return ErrorCategory.SKIP

    # SKIP: OCR / 控制 / UI定位异常
    if isinstance(exception, (OCRError, ControlError, UILocatorError)):
        return ErrorCategory.SKIP

    # 默认：未知异常保守归类为 SKIP
    return ErrorCategory.SKIP
