# -*- coding: utf-8 -*-
"""日志记录模块 — PDF 4.4.3"""
import logging
import os
import sys
from datetime import datetime

# ===== Windows 控制台 UTF-8 修复 =====
# Windows 默认控制台编码为 gbk/cp936，输出中文会乱码。
# 只在真实控制台环境下（非 pytest/CI 捕获模式）替换 stdout，避免与 pytest 冲突。
_stdout_fixed = False


def _fix_stdout_encoding():
    """将 sys.stdout 包装为 UTF-8 编码（仅 Windows 且仅执行一次）。"""
    global _stdout_fixed
    if _stdout_fixed:
        return
    _stdout_fixed = True
    if sys.platform != "win32":
        return
    # 跳过 pytest 等工具已替换过 stdout 的场景
    if not hasattr(sys.stdout, "buffer"):
        return
    try:
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
    except (AttributeError, ValueError, OSError):
        pass


def get_logger(name: str) -> logging.Logger:
    """获取指定模块的 logger 实例。

    同时输出到控制台和文件，格式：时间戳 + 级别 + 模块名 + 消息。

    Args:
        name: 模块名称，通常传 __name__。

    Returns:
        配置好的 Logger 对象。
    """
    # 确保控制台能正确输出中文
    _fix_stdout_encoding()

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 日志格式
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # 文件（自动创建 logs/ 目录）
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    file_handler = logging.FileHandler(
        os.path.join(log_dir, f"{today}.log"), encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
