# -*- coding: utf-8 -*-
"""OCR 识别模块 — 通过独立子进程 worker 调用 PaddleOCR。

主进程加载 torch（模型客户端），与 paddlepaddle-gpu 同进程会因 pybind11
类型注册冲突崩溃。因此 OCR 放到独立子进程（ocr_worker.py）：
- worker 进程只加载 paddle（GPU），OCR 快（约 0.4s vs CPU 4-6s）
- 主进程通过 stdin/stdout 传图取结果，与 torch 互不影响
- worker 故障时降级返回空结果（agent 退化为纯 UIA 标注）

OCR 输入会缩小到最长边 1920px：OCR 不需要全屏原分辨率，缩小提速并减少
进程间传输量。
"""
import base64
import io
import json
import os
import subprocess
import sys
import threading
from typing import List, Dict, Any

from PIL import Image

from desktop_gui_agent.config import OCR_CONFIDENCE_THRESHOLD
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# OCR 输入最长边（px）：全屏图缩小后再 OCR，提速 + 减少传输
_OCR_MAX_SIZE = 1920


class _OcrWorker:
    """管理 OCR 子进程的客户端。

    惰性启动子进程，按需重启（子进程异常退出时自动拉起）。线程安全。
    """

    def __init__(self):
        self._proc: subprocess.Popen = None
        self._lock = threading.Lock()

    def _script_path(self) -> str:
        """返回 ocr_worker.py 的绝对路径。"""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_worker.py")

    def _ensure_started(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        try:
            self._proc = subprocess.Popen(
                [sys.executable, self._script_path()],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,  # 文本模式，readline() 返回 str，JSON 解析友好
            )
            # 等 worker 就绪信号（引擎加载需几秒），确保能立即处理请求
            ready_line = self._read_json_line()
            if not ready_line:
                logger.error("OCR worker 未就绪（可能启动失败）")
                self._restart()
                return False
            return True
        except Exception as e:
            logger.error(f"OCR worker 启动失败: {e}")
            self._proc = None
            return False

    def _read_json_line(self) -> str:
        """从 worker stdout 读取包含 JSON 对象的行。

        PaddleOCR 会把警告写到 stdout（如 ppocr WARNING 行），污染协议。
        因此逐行读取，跳过非 JSON 行，直到找到包含 '{' 的响应行。
        最多读 20 行，防止 worker 无响应时死循环。

        Returns:
            包含 JSON 的行；未找到返回空字符串。
        """
        for _ in range(20):
            line = self._proc.stdout.readline()
            if not line:
                return ""
            if "{" in line:
                return line
        return ""

    @staticmethod
    def _parse_response(resp_line: str) -> dict:
        """容错解析 worker 响应：跳过开头非 JSON 的垃圾，取第一个完整 JSON 对象。"""
        start = resp_line.find("{")
        if start < 0:
            return {}
        return json.loads(resp_line[start:])

    def recognize(self, image_b64: str) -> List[Dict[str, Any]]:
        """发送图片给 worker，返回 OCR 结果列表。

        Args:
            image_b64: 图片的 base64 编码（PNG）。

        Returns:
            OCR 结果列表；worker 失败时返回空列表。
        """
        with self._lock:
            if not self._ensure_started():
                return []
            req = json.dumps({"image_b64": image_b64}) + "\n"
            try:
                # text=True 模式下 stdin 是文本流，write 需要 str（不要 encode 成 bytes）
                self._proc.stdin.write(req)
                self._proc.stdin.flush()
                resp_line = self._read_json_line()
            except Exception:
                resp_line = ""

            if not resp_line:
                # worker 异常退出，重启重试一次
                self._restart()
                try:
                    self._proc.stdin.write(req)
                    self._proc.stdin.flush()
                    resp_line = self._read_json_line()
                except Exception:
                    return []
                if not resp_line:
                    return []

            try:
                resp = self._parse_response(resp_line)
            except Exception as e:
                # 响应被污染/损坏，重启 worker 防止后续全坏
                logger.error(f"OCR worker 响应解析失败，重启: {e} | 响应头: {resp_line[:80]!r}")
                self._restart()
                return []

            if "error" in resp:
                logger.error(f"OCR worker 返回错误: {resp['error']}")
                return []
            return resp.get("results", [])

    def _restart(self):
        """终止当前 worker 进程并清空引用（下次调用自动重启）。"""
        try:
            if self._proc is not None:
                self._proc.kill()
        except Exception:
            pass
        self._proc = None


# 全局单例 worker（惰性创建）
_worker = None


def recognize(image: Image.Image) -> List[Dict[str, Any]]:
    """识别图片中的文字，返回结构化结果。

    通过 OCR 子进程 worker 执行，主进程不加载 paddle。

    Args:
        image: PIL Image 截图。

    Returns:
        识别结果列表，每个元素为 {"text": str, "bbox": (x1,y1,x2,y2),
        "confidence": float}。无文字、输入为空或 worker 不可用时返回空列表。
    """
    if image is None:
        logger.warning("输入图片为空，跳过 OCR")
        return []

    global _worker
    if _worker is None:
        _worker = _OcrWorker()

    try:
        # 缩小图片（OCR 不需要全屏原分辨率）
        img = image.copy()
        img.thumbnail((_OCR_MAX_SIZE, _OCR_MAX_SIZE))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        elements = _worker.recognize(image_b64)
        # 过滤低置信度（worker 已按 0.5 过滤，这里再兜底一层）
        elements = [
            e for e in elements
            if e.get("confidence", 0) >= OCR_CONFIDENCE_THRESHOLD
        ]
        logger.info(f"OCR 识别到 {len(elements)} 个文字元素")
        return elements
    except Exception as e:
        logger.error(f"OCR 识别失败: {e}")
        return []
