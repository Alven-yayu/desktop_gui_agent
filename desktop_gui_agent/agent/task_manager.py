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
from desktop_gui_agent.config import (
    AGENT_MAX_STEPS, AGENT_MAX_CONSECUTIVE_ERRORS, AGENT_STEP_DELAY,
    VERIFY_CORRECT_ENABLED, VERIFY_CORRECT_MAX_NO_CHANGE, VERIFY_CORRECT_WAIT,
    PERF_TIMING_ENABLED,
)
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

    def _resolve_marker(self, marker: int) -> Optional[tuple]:
        """根据标注编号从 marker_map 解析屏幕坐标 (x, y)。

        Args:
            marker: 模型输出的标注编号。

        Returns:
            (x, y) 坐标元组；编号不存在时返回 None 并记录警告。
        """
        info = self._marker_map.get(marker, {})
        # 优先 click_point（新格式），回退 icon（旧格式兼容）
        x, y = info.get("click_point") or info.get("icon", (None, None))
        if x is None:
            keys = list(self._marker_map.keys())
            logger.warning(f"标注 #{marker} 不存在，可用: {keys}")
            return None
        return int(x), int(y)

    def _marker_log(self, action_name: str, marker: int, x: int, y: int) -> None:
        """输出 marker 动作的定位日志，方便对照截图排查。

        Args:
            action_name: 动作名称（如 click_marker）。
            marker: 标注编号。
            x, y: 解析出的屏幕坐标。
        """
        info = self._marker_map.get(marker, {})
        source = info.get("source", "?")
        logger.info(
            f"[UIA] {action_name}(#{marker}) → ({x}, {y}) "
            f"\"{info.get('text', '')}\" ({source})"
        )

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
            pos = self._resolve_marker(params["marker"])
            if pos is None:
                return False
            x, y = pos
            self._marker_log("click_marker", params["marker"], x, y)
            return self.mouse.click(x, y)
        elif action_type == "double_click_marker":
            pos = self._resolve_marker(params["marker"])
            if pos is None:
                return False
            x, y = pos
            self._marker_log("double_click_marker", params["marker"], x, y)
            return self.mouse.double_click(x, y)
        elif action_type == "right_click_marker":
            pos = self._resolve_marker(params["marker"])
            if pos is None:
                return False
            x, y = pos
            self._marker_log("right_click_marker", params["marker"], x, y)
            return self.mouse.right_click(x, y)
        elif action_type == "right_click":
            return self.mouse.right_click(params["x"], params["y"])
        elif action_type == "drag_marker":
            p1 = self._resolve_marker(params["from"])
            p2 = self._resolve_marker(params["to"])
            if p1 is None or p2 is None:
                return False
            x1, y1 = p1
            x2, y2 = p2
            logger.info(
                f"[UIA] drag_marker(#{params['from']}→#{params['to']}) "
                f"({x1},{y1})→({x2},{y2})"
            )
            return self.mouse.drag_from_to(x1, y1, x2, y2)
        elif action_type == "drag":
            return self.mouse.drag_from_to(
                params["x1"], params["y1"], params["x2"], params["y2"]
            )
        elif action_type == "press":
            return self.keyboard.press(params["key"])
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

    @staticmethod
    def _capture_state() -> dict:
        """捕获当前 UI 状态快照，用于动作前后对比。

        收集前台窗口标题和 UIA 控件树特征，不依赖截图
        （UIA 比像素对比更快、更语义化）。

        Returns:
            状态特征字典，包含 window/uia_count/uia_types/uia_names。
            非 Windows 或获取失败时返回空特征。
        """
        state = {
            "fg_window_title": "",
            "uia_count": 0,
            "uia_type_counts": {},
            "uia_names": (),
        }

        # 前台窗口标题
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            state["fg_window_title"] = buf.value
        except Exception:
            pass

        # UIA 控件特征
        try:
            from desktop_gui_agent.perception.uia_parser import UiaParser
            controls = UiaParser.get_foreground_controls()
        except Exception:
            controls = []

        if controls:
            state["uia_count"] = len(controls)
            # 各类型数量
            type_counts = {}
            for c in controls:
                ct = c.get("control_type", "?")
                type_counts[ct] = type_counts.get(ct, 0) + 1
            state["uia_type_counts"] = type_counts
            # 前 15 个控件名称（排序后的元组，可哈希）
            names = tuple(
                sorted(c.get("name", "") for c in controls)[:15]
            )
            state["uia_names"] = names

        return state

    @staticmethod
    def _has_state_changed(before: dict, after: dict) -> bool:
        """对比前后状态快照，判断是否有实质性变化。

        判断标准（满足任一即认为已变化）：
        1. 前台窗口标题不同
        2. UIA 控件总数变化 > 20%
        3. 控件类型种类发生变化
        4. 控件名称集合变化 > 30%

        Args:
            before: 动作前的状态快照。
            after: 动作后的状态快照。

        Returns:
            True 表示检测到变化（动作生效），False 表示无变化（动作无效）。
        """
        # 1. 前台窗口变了（最直观的信号）
        if before["fg_window_title"] != after["fg_window_title"]:
            return True

        b_count = before.get("uia_count", 0)
        a_count = after.get("uia_count", 0)

        # 如果都没有 UIA 数据，无法判断，保守认为有变化（避免误报）
        if b_count == 0 and a_count == 0:
            return True

        # 2. 控件总数变化 > 20%
        if b_count > 0:
            change_ratio = abs(a_count - b_count) / b_count
            if change_ratio > 0.2:
                return True
        elif a_count > 0:
            # 从无到有（或反之）——明显变化
            return True

        # 3. 控件类型种类变化
        b_types = set(before.get("uia_type_counts", {}).keys())
        a_types = set(after.get("uia_type_counts", {}).keys())
        if b_types != a_types:
            return True

        # 4. 控件名称集合变化 > 30%
        b_names = set(before.get("uia_names", ()))
        a_names = set(after.get("uia_names", ()))
        if b_names or a_names:
            all_names = b_names | a_names
            if all_names:
                common = b_names & a_names
                similarity = len(common) / len(all_names) if all_names else 1.0
                if similarity < 0.7:  # 变化 > 30%
                    return True

        return False

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
        consecutive_no_change = 0  # 验证-纠正：连续无状态变化步数
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

                # 先取前台窗口标题（标注需要判断是否在桌面，也让模型知道当前应用）
                fg_window_title = ""
                try:
                    import ctypes
                    hwnd = ctypes.windll.user32.GetForegroundWindow()
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                    fg_window_title = buf.value
                except Exception:
                    pass

                # 桌面判断：前台窗口无标题说明当前在桌面（没有应用窗口）。
                # 桌面上 OCR 点击点需上偏以落在图标上；应用内取文字中心。
                is_desktop = not bool(fg_window_title.strip())

                annotated_image, marker_map = annotate_screenshot(
                    image, ocr_results, max_items=20, task=task,
                    uia_controls=uia_controls, is_desktop=is_desktop,
                )
                self._marker_map = marker_map  # 保存供 _dispatch 翻译编号
                # 构建标注文字说明（区分 UIA 矩形框和 OCR 圆点）
                def _build_marker_line(num: int, info: dict) -> str:
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

                # 验证-纠正：连续无变化时，在下一次模型查询前注入恢复提示
                recovery_hint = ""
                if VERIFY_CORRECT_ENABLED and consecutive_no_change >= VERIFY_CORRECT_MAX_NO_CHANGE:
                    recovery_hint = (
                        "【!!! 纠正提示 — 上一步无效 !!!】\n"
                        "前面步骤没有让屏幕发生任何变化，上一次操作没有生效。\n"
                        "请换一种方法达成目标，严格禁止重复刚才做过的操作！\n\n"
                    )
                    logger.warning(
                        f"[Verify] 注入恢复提示（连续{consecutive_no_change}次无变化）"
                    )

                # 当前鼠标位置：模型规划拖拽/右键时需要知道鼠标在哪。
                # 防御性处理：mock 场景下 get_position 可能返回非元组。
                cursor_line = ""
                try:
                    pos = self.mouse.get_position()
                    if isinstance(pos, (tuple, list)) and len(pos) == 2:
                        cursor_line = (
                            f"【当前鼠标位置】({int(pos[0])}, {int(pos[1])})\n"
                        )
                except Exception:
                    pass

                marker_extra = (
                    recovery_hint +
                    cursor_line +
                    f"【当前前台窗口】{fg_window_title}\n"
                    "【屏幕标注说明】\n"
                    "  绿色矩形框 = Windows 应用按钮/控件（来自 UIA）\n"
                    "  橙色圆点 = 非标准 UI 文字（来自 OCR）\n"
                    "  请观察标注在图中的实际位置，用编号指定目标：\n"
                    + "\n".join(marker_text_lines)
                ) if marker_text_lines else recovery_hint if recovery_hint else ""

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

                # 5. 坐标校验（click / right_click / drag 坐标形式）
                # 越界坐标会导致鼠标点到屏幕外，视为一次错误
                screen_w, screen_h = image.size
                invalid = False
                if action["action_type"] in ("click", "right_click"):
                    x, y = action["params"]["x"], action["params"]["y"]
                    if not self._validate_coordinates(x, y, screen_w, screen_h):
                        logger.warning(f"坐标越界: ({x}, {y})，屏幕={screen_w}x{screen_h}")
                        invalid = True
                elif action["action_type"] == "drag":
                    p = action["params"]
                    pts = [(p["x1"], p["y1"]), (p["x2"], p["y2"])]
                    for px, py in pts:
                        if not self._validate_coordinates(px, py, screen_w, screen_h):
                            logger.warning(
                                f"drag 坐标越界: ({px}, {py})，屏幕={screen_w}x{screen_h}"
                            )
                            invalid = True
                            break
                if invalid:
                    consecutive_errors += 1
                    continue

                # 6. 执行动作（含验证-纠正循环）
                # 动作前：捕获 UI 状态快照
                pre_state = self._capture_state() if VERIFY_CORRECT_ENABLED else None

                exec_start = time.time()
                success = self._dispatch(action)
                timings["execution"] = time.time() - exec_start

                # 动作后：等待 UI 稳定，捕获新状态并对比
                if pre_state is not None:
                    time.sleep(VERIFY_CORRECT_WAIT)
                    post_state = self._capture_state()
                    changed = self._has_state_changed(pre_state, post_state)
                    if not changed:
                        consecutive_no_change += 1
                        logger.warning(
                            f"[Verify] 步骤{step} 无状态变化 "
                            f"(连续{consecutive_no_change}次)"
                        )
                    else:
                        if consecutive_no_change > 0:
                            logger.info(
                                f"[Verify] 步骤{step} 状态已恢复变化"
                            )
                        consecutive_no_change = 0

                # 7. 性能计时日志（在记录历史之前，确保 finish 步骤也输出）
                if PERF_TIMING_ENABLED:
                    step_total = time.time() - step_start
                    logger.info(
                        f"[Perf] 步骤{step} 总耗时{step_total:.2f}s | "
                        f"截图={timings.get('screenshot',0):.3f}s "
                        f"OCR={timings.get('ocr',0):.3f}s "
                        f"模型={timings.get('model',0):.3f}s "
                        f"执行={timings.get('execution',0):.3f}s"
                    )

                # 8. 记录本步历史
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

                # 9. 判断终止条件
                if action["action_type"] == "finish":
                    result_text = action["params"].get("result", "任务完成")
                    logger.info(f"任务完成: {result_text}")
                    return {
                        "success": True,
                        "result": result_text,
                        "steps": step,
                        "error": None,
                    }

                # 10. 步骤间延迟
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
