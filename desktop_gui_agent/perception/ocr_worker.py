# -*- coding: utf-8 -*-
"""OCR 子进程 worker — 隔离 paddle GPU 与主进程 torch 的 pybind11 冲突。

主进程（agent）加载 torch（模型客户端），若同一进程再加载 paddlepaddle-gpu
会因 pybind11 类型注册冲突崩溃（_gpuDeviceProperties already registered）。
因此把 OCR 放到独立子进程：worker 只加载 paddle（GPU），主进程通过
stdin/stdout 传图取结果，两者互不影响。

协议（stdin/stdout，每行一个 JSON）：
  请求:  {"image_b64": "<PNG base64>"}
  响应:  {"results": [{"text","bbox","confidence"}, ...]}  或 {"error": "..."}

注意：所有日志走 stderr，stdout 只输出协议 JSON（防止污染 stdout 数据流）。
"""
import base64
import io
import json
import os
import site
import sys

# ===== 先把 NVIDIA GPU 库路径加入 PATH（paddle GPU 需要 cudnn/cublas）=====
def _add_nvidia_paths() -> None:
    try:
        candidates = set(site.getsitepackages())
    except Exception:
        candidates = set()
    for sp in candidates:
        nvidia_dir = os.path.join(sp, "nvidia")
        if not os.path.isdir(nvidia_dir):
            continue
        for entry in sorted(os.listdir(nvidia_dir)):
            bin_dir = os.path.join(nvidia_dir, entry, "bin")
            if os.path.isdir(bin_dir) and bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


_add_nvidia_paths()

import contextlib

import numpy as np
from PIL import Image


@contextlib.contextmanager
def _redirect_stdout_to_stderr():
    """把 Python 层 stdout 临时重定向到 stderr。

    PaddleOCR 即使 show_log=False 也会向 stdout 打印进度等，会污染
    stdin/stdout 协议。加载和 OCR 期间重定向，保证协议 JSON 纯净。
    """
    old = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old


from paddleocr import PaddleOCR

# 加载 OCR 引擎（GPU），期间重定向 stdout。
# 失败则写 error 到 stderr 并退出（主进程会重启或降级）。
try:
    with _redirect_stdout_to_stderr():
        _ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    # 就绪握手：主进程等这个信号才发请求
    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()
    print("OCR worker 就绪 (GPU)", file=sys.stderr, flush=True)
except Exception as e:
    print(f"OCR worker 引擎加载失败: {e}", file=sys.stderr, flush=True)
    sys.exit(1)


def _ocr_image(image_b64: str):
    """对 base64 图片做 OCR，返回结构化结果列表。"""
    img = Image.open(io.BytesIO(base64.b64decode(image_b64)))
    with _redirect_stdout_to_stderr():
        result = _ocr.ocr(np.array(img))
    elements = []
    if result and result[0]:
        for box, (text, conf) in result[0]:
            # 置信度过滤统一在主进程按 OCR_CONFIDENCE_THRESHOLD 做，
            # 这里不过滤（避免两处阈值硬编码不同步）
            x1, y1 = box[0]
            x2, y2 = box[2]
            elements.append({
                "text": text,
                "bbox": (int(x1), int(y1), int(x2), int(y2)),
                "confidence": round(conf, 4),
            })
    return elements


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        results = _ocr_image(req.get("image_b64", ""))
        sys.stdout.write(json.dumps({"results": results}) + "\n")
    except Exception as e:
        sys.stdout.write(json.dumps({"error": str(e)}) + "\n")
    sys.stdout.flush()
