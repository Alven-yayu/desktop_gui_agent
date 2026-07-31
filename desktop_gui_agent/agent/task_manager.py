# -*- coding: utf-8 -*-
"""任务管理器 — PDF 4.3.3

驱动 Agent 主循环：截图→OCR→模型→解析→执行，循环至任务完成或触发上限。
"""
import json
import os
import random
import threading
import time
from datetime import datetime
from typing import Optional

from PIL import Image

from desktop_gui_agent.agent.action_parser import parse
from desktop_gui_agent.agent.model_client import ModelClient
from desktop_gui_agent.config import AGENT_MAX_STEPS, AGENT_MAX_CONSECUTIVE_ERRORS, AGENT_STEP_DELAY
from desktop_gui_agent.control.keyboard_controller import KeyboardController
from desktop_gui_agent.control.mouse_controller import MouseController
from desktop_gui_agent.perception.ocr_recognizer import recognize
from desktop_gui_agent.perception.screenshot import capture
from desktop_gui_agent.utils.exceptions import ErrorCategory, OCRError, ScreenshotError, classify_error
from desktop_gui_agent.utils.logger import get_logger
from desktop_gui_agent.utils.platform import PlatformInfo

logger = get_logger(__name__)


class TaskManager:
    """Agent 主循环控制器。

    接收用户任务描述，驱动"感知→决策→执行"循环，
    直到任务完成、达到步数上限或触发错误阈值。

    Attributes:
        max_steps: 最大步数上限。
        max_consecutive_errors: 连续错误次数阈值。
        mouse: 鼠标控制器实例。
        keyboard: 键盘控制器实例。
        model_client: 模型客户端实例。
    """

    def __init__(
        self,
        mouse: Optional[object] = None,
        keyboard: Optional[object] = None,
        model_client: Optional[object] = None,
        max_steps: int = AGENT_MAX_STEPS,
        max_consecutive_errors: int = AGENT_MAX_CONSECUTIVE_ERRORS,
        api_preset: Optional[str] = None,
    ):
        """初始化任务管理器。

        Args:
            mouse: 鼠标控制器，None 则使用默认 MouseController。
            keyboard: 键盘控制器，None 则使用默认 KeyboardController。
            model_client: 模型客户端，None 则使用默认 ModelClient。
            max_steps: 最大步数上限。
            max_consecutive_errors: 连续错误次数阈值。
            api_preset: API 预设名称（"dashscope" / "ollama"），None 则用本地模型。
        """
        self.max_steps = max_steps
        self.max_consecutive_errors = max_consecutive_errors
        self.api_preset = api_preset
        self.mouse = mouse
        self.keyboard = keyboard
        self.model_client = model_client
        self._marker_map: dict = {}  # 标注编号 → 坐标映射
        logger.info(
            f"TaskManager 初始化，max_steps={max_steps}，"
            f"max_consecutive_errors={max_consecutive_errors}"
        )

    @staticmethod
    def _validate_coordinates(x: int, y: int, screen_width: int, screen_height: int) -> bool:
        """校验坐标是否在屏幕范围内。

        Args:
            x: X 坐标（像素）。
            y: Y 坐标（像素）。
            screen_width: 屏幕宽度（像素）。
            screen_height: 屏幕高度（像素）。

        Returns:
            True 表示坐标有效，False 表示越界。
        """
        if x < 0 or y < 0:
            return False
        if x >= screen_width or y >= screen_height:
            return False
        return True

    def _dispatch(self, action: dict) -> bool:
        """根据动作类型分发到对应的控制器方法。

        Args:
            action: 结构化动作字典，含 action_type 和 params。

        Returns:
            True 表示执行成功，False 表示失败。
        """
        action_type = action.get("action_type", "unknown")
        params = action.get("params", {})

        if action_type == "click_marker":
            marker = params["marker"]
            info = self._marker_map.get(marker, {})
            # 优先 click_point（新格式），回退 icon（旧格式兼容）
            x, y = info.get("click_point") or info.get("icon", (None, None))
            if x is None:
                keys = list(self._marker_map.keys())
                logger.warning(f"标注 #{marker} 不存在，可用: {keys}")
                return False
            source = info.get("source", "?")
            logger.info(
                f"[UIA] click_marker(#{marker}) → ({x}, {y}) "
                f"\"{info.get('text', '')}\" ({source})"
            )
            return self.mouse.click(x, y)
        elif action_type == "double_click_marker":
            marker = params["marker"]
            info = self._marker_map.get(marker, {})
            x, y = info.get("click_point") or info.get("icon", (None, None))
            if x is None:
                keys = list(self._marker_map.keys())
                logger.warning(f"标注 #{marker} 不存在，可用: {keys}")
                return False
            source = info.get("source", "?")
            logger.info(
                f"[UIA] double_click_marker(#{marker}) → ({x}, {y}) "
                f"\"{info.get('text', '')}\" ({source})"
            )
            return self.mouse.double_click(x, y)
        elif action_type == "click":
            return self.mouse.click(params["x"], params["y"])
        elif action_type == "double_click":
            return self.mouse.double_click(params["x"], params["y"])
        elif action_type == "type":
            return self.keyboard.type(params["text"])
        elif action_type == "scroll":
            return self.keyboard.scroll(params["direction"], params["steps"])
        elif action_type == "hotkey":
            return self.keyboard.hotkey(*params["keys"])
        elif action_type == "finish":
            return True
        else:
            logger.warning(f"未知动作类型: {action_type}")
            return False

    def _capture_with_retry(self, max_retries: int = 2) -> Image.Image:
        """截图，失败时最多重试 max_retries 次。

        每次重试间隔 0.5s。全部失败后抛出 ScreenshotError，
        由上层 run() 中的错误分类机制处理。

        Args:
            max_retries: 最大重试次数（默认 2）。

        Returns:
            截图的 PIL Image 对象。

        Raises:
            ScreenshotError: 全部重试仍失败。
        """
        last_error = None
        for attempt in range(max_retries + 1):  # 原始 + 重试
            try:
                return capture()
            except ScreenshotError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(
                        f"截图失败（第 {attempt + 1} 次），{0.5}s 后重试..."
                    )
                    time.sleep(0.5)
        raise last_error  # type: ignore[misc]

    def run(self, task: str, cancel_event: Optional[threading.Event] = None) -> dict:
        """执行 Agent 主循环。

        每步依次：截图 → OCR → 模型推理 → 动作解析 → 坐标校验 → 执行。
        循环直到：finish 动作 / 达到 max_steps / 连续错误超限 / 用户中断。

        Args:
            task: 用户自然语言任务描述。
            cancel_event: 外部传入的取消事件，set() 后循环立即终止。

        Returns:
            {"success": bool, "result": str, "steps": int, "error": str}
        """
        # 初始化默认依赖（允许通过 __init__ 注入 mock）
        if self.mouse is None:
            self.mouse = MouseController()
        if self.keyboard is None:
            self.keyboard = KeyboardController()
        if self.model_client is None:
            self.model_client = ModelClient(api_preset=self.api_preset)

        step = 0
        consecutive_errors = 0
        history = []
        result_text = ""

        # 终端窗口避让：先尝试最小化，失败则自动裁剪
        # （每次 run() 调用时执行一次，防止 OCR 自干扰）
        from desktop_gui_agent.perception.screenshot import _init_terminal_avoidance
        _init_terminal_avoidance()

        logger.info(f"开始执行任务: {task}")

        try:
            while step < self.max_steps:
                # 检查连续错误是否已达上限
                if consecutive_errors >= self.max_consecutive_errors:
                    logger.error(f"连续错误次数达到上限 {self.max_consecutive_errors}")
                    return {
                        "success": False,
                        "result": result_text,
                        "steps": step,
                        "error": "连续错误次数超限",
                    }

                step += 1

                # 检查用户是否请求终止
                if cancel_event and cancel_event.is_set():
                    logger.info("用户请求终止任务")
                    return {
                        "success": False,
                        "result": result_text,
                        "steps": step - 1,
                        "error": "用户终止",
                    }

                step_start = time.time()
                timings = {}

                # 1. 截图（带重试）
                try:
                    image = self._capture_with_retry(max_retries=2)
                    timings["screenshot"] = time.time() - step_start
                except ScreenshotError as e:
                    logger.error(f"截图失败（已重试）: {e}")
                    consecutive_errors += 1
                    continue

                # 保存截图
                screenshot_path = self._save_screenshot(image, step)

                # 2. OCR 识别
                ocr_start = time.time()
                try:
                    ocr_results = recognize(image)
                except OCRError as e:
                    logger.warning(f"OCR 失败（不计入错误计数）: {e}")
                    ocr_results = []
                timings["ocr"] = time.time() - ocr_start

                # 2.5 UIA 感知：获取前台窗口的原生 UI 控件树
                # （Windows 标准应用可精确定位按钮/文本框，不用猜坐标）
                from desktop_gui_agent.perception.uia_parser import UiaParser

                uia_controls = []
                try:
                    uia_controls = UiaParser.get_foreground_controls()
                except Exception as e:
                    logger.debug(f"UIA 感知跳过: {e}")

                # 3. 截图标注 + 模型推理
                # 融合标注：UIA 控件(绿色矩形框) + OCR 文字(橙色圆点)，
                # 统一编号，模型只需选编号，代码查表翻译为精确坐标
                from desktop_gui_agent.perception.screenshot import annotate_screenshot

                annotated_image, marker_map = annotate_screenshot(
                    image, ocr_results, max_items=20, task=task,
                    uia_controls=uia_controls,
                )
                self._marker_map = marker_map  # 保存供 _dispatch 翻译编号
                # 构建标注文字说明（区分 UIA 矩形框和 OCR 圆点）
                def _build_marker_line(num: int, info: dict) -> str:
                    """构建单个标注的文字说明行。"""
                    source = info.get("source", "?")
                    text = info.get("text", "")
                    cp = info.get("click_point", (0, 0))
                    if source == "uia":
                        ctrl_type = info.get("control_type", "")
                        return f"  #{num}[{ctrl_type}]: \"{text}\" ({cp[0]},{cp[1]})"
                    else:
                        return f"  #{num}[文字]: \"{text}\" ({cp[0]},{cp[1]})"

                marker_text_lines = [
                    _build_marker_line(num, info)
                    for num, info in marker_map.items()
                ]
                marker_extra = (
                    "【屏幕标注说明】\n"
                    "  绿色矩形框 = Windows 应用按钮/控件（来自 UIA）\n"
                    "  橙色圆点 = 非标准 UI 文字（来自 OCR）\n"
                    "  请观察标注在图中的实际位置，用编号指定目标：\n"
                    + "\n".join(marker_text_lines)
                ) if marker_text_lines else ""

                model_start = time.time()
                history_actions = [h["action_raw"] for h in history if "action_raw" in h]
                try:
                    model_output = self.model_client.query(
                        annotated_image, task, context=history_actions,
                        ocr_results=ocr_results, extra_text=marker_extra,
                    )
                except Exception as e:
                    category = classify_error(e)
                    if category == ErrorCategory.FATAL:
                        logger.error(f"致命错误，立即终止: {e}")
                        return {
                            "success": False,
                            "result": result_text,
                            "steps": step,
                            "error": f"致命错误: {e}",
                        }
                    logger.error(f"模型推理失败 ({category.value}): {e}")
                    consecutive_errors += 1
                    continue
                timings["model"] = time.time() - model_start

                if not model_output:
                    logger.warning("模型返回空输出")
                    consecutive_errors += 1
                    continue

                # 4. 动作解析
                action = parse(model_output)
                if action["action_type"] == "unknown":
                    logger.warning(f"无法解析模型输出: {model_output[:100]}")
                    consecutive_errors += 1
                    continue

                # 死循环检测：连续3次输出相同动作 → 强制终止
                if len(history) >= 2:
                    last_two = [
                        (h.get("action_type"), h.get("action_params", {}))
                        for h in history[-2:]
                    ]
                    current = (action["action_type"], action.get("params", {}))
                    if last_two[0] == last_two[1] == current:
                        logger.warning("检测到连续3次相同动作，模型可能陷入死循环，强制终止")
                        return {
                            "success": False,
                            "result": result_text,
                            "steps": step,
                            "error": "模型陷入死循环（连续3次相同动作）",
                        }

                # 5. 坐标校验（仅 click 动作）
                if action["action_type"] == "click":
                    x, y = action["params"]["x"], action["params"]["y"]
                    screen_w, screen_h = image.size
                    if not self._validate_coordinates(x, y, screen_w, screen_h):
                        logger.warning(f"坐标越界: ({x}, {y})，屏幕={screen_w}x{screen_h}")
                        consecutive_errors += 1
                        continue

                # 6. 执行动作
                exec_start = time.time()
                success = self._dispatch(action)
                timings["execution"] = time.time() - exec_start

                # 7. 记录本步历史
                history.append({
                    "step": step,
                    "screenshot": screenshot_path,
                    "ocr_results": ocr_results,
                    "model_output": model_output,
                    "action_type": action["action_type"],
                    "action_params": action.get("params", {}),
                    "action_raw": model_output,
                    "success": success,
                    "timings": timings,
                })

                if not success:
                    logger.warning(f"动作执行失败: {action['action_type']}")
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0  # 成功后重置连续错误计数

                # 8. 判断终止条件
                if action["action_type"] == "finish":
                    result_text = action["params"].get("result", "任务完成")
                    logger.info(f"任务完成: {result_text}")
                    return {
                        "success": True,
                        "result": result_text,
                        "steps": step,
                        "error": None,
                    }

                # 9. 步骤间延迟
                min_delay, max_delay = AGENT_STEP_DELAY
                time.sleep(random.uniform(min_delay, max_delay))

            # 达到 max_steps
            logger.warning(f"达到最大步数上限 {self.max_steps}")
            return {
                "success": False,
                "result": result_text,
                "steps": step,
                "error": "达到最大步数上限",
            }

        except KeyboardInterrupt:
            logger.info("用户中断（Ctrl+C），保存已执行步骤")
            return {
                "success": False,
                "result": result_text,
                "steps": step,
                "error": "用户中断",
            }
        finally:
            # 保存完整历史记录
            self._save_history(history, task)

    def _save_screenshot(self, image: Image.Image, step: int) -> str:
        """保存截图到 logs/screenshots/ 目录。

        Args:
            image: 截图 PIL Image。
            step: 当前步骤编号。

        Returns:
            截图保存路径。
        """
        log_dir = PlatformInfo.get_log_dir() / "screenshots"
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"step_{step}.png")
        image.save(path, "PNG")
        return path

    def _save_history(self, history: list, task: str) -> None:
        """将任务执行历史保存为 JSON 文件。

        Args:
            history: 步骤历史记录列表。
            task: 原始任务描述。
        """
        log_dir = PlatformInfo.get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%H%M%S")
        path = os.path.join(log_dir, f"task_{timestamp}.json")
        record = {"task": task, "history": history}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"任务历史已保存: {path}")
        except Exception as e:
            logger.error(f"保存任务历史失败: {e}")
