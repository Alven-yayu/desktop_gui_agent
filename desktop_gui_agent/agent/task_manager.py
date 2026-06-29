# -*- coding: utf-8 -*-
"""任务管理器 — PDF 4.3.3

驱动 Agent 主循环：截图→OCR→模型→解析→执行，循环至任务完成或触发上限。
"""
import json
import os
import random
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
from desktop_gui_agent.utils.exceptions import OCRError, ScreenshotError
from desktop_gui_agent.utils.logger import get_logger

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
    ):
        """初始化任务管理器。

        Args:
            mouse: 鼠标控制器，None 则使用默认 MouseController。
            keyboard: 键盘控制器，None 则使用默认 KeyboardController。
            model_client: 模型客户端，None 则使用默认 ModelClient。
            max_steps: 最大步数上限。
            max_consecutive_errors: 连续错误次数阈值。
        """
        self.max_steps = max_steps
        self.max_consecutive_errors = max_consecutive_errors
        self.mouse = mouse
        self.keyboard = keyboard
        self.model_client = model_client
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

        if action_type == "click":
            return self.mouse.click(params["x"], params["y"])
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

    def run(self, task: str) -> dict:
        """执行 Agent 主循环。

        每步依次：截图 → OCR → 模型推理 → 动作解析 → 坐标校验 → 执行。
        循环直到：finish 动作 / 达到 max_steps / 连续错误超限 / 用户中断。

        Args:
            task: 用户自然语言任务描述。

        Returns:
            {"success": bool, "result": str, "steps": int, "error": str}
        """
        # 初始化默认依赖（允许通过 __init__ 注入 mock）
        if self.mouse is None:
            self.mouse = MouseController()
        if self.keyboard is None:
            self.keyboard = KeyboardController()
        if self.model_client is None:
            self.model_client = ModelClient()

        step = 0
        consecutive_errors = 0
        history = []
        result_text = ""

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
                step_start = time.time()
                timings = {}

                # 1. 截图
                try:
                    image = capture()
                    timings["screenshot"] = time.time() - step_start
                except ScreenshotError as e:
                    logger.error(f"截图失败: {e}")
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

                # 3. 模型推理
                model_start = time.time()
                history_actions = [h["action_raw"] for h in history if "action_raw" in h]
                try:
                    model_output = self.model_client.query(image, task, context=history_actions)
                except Exception as e:
                    logger.error(f"模型推理失败: {e}")
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
        log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "screenshots")
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
        log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
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
