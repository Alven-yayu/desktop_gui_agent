# -*- coding: utf-8 -*-
"""鼠标控制模块 — PDF 4.2.1

基于 pynput 实现屏幕坐标系的鼠标操作：移动、点击、拖拽。
所有公共方法统一返回 bool，不抛异常。
"""
import random
import time
from typing import Optional

from pynput.mouse import Button, Controller as MouseController

from desktop_gui_agent.config import (
    MOUSE_CLICK_DELAY,
    MOUSE_DRAG_DURATION,
    MOUSE_MOVE_DURATION,
)
from desktop_gui_agent.utils.exceptions import ControlError
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)


class MouseController:
    """鼠标操作控制器。

    封装 pynput 鼠标 API，提供平滑移动、人类化延迟、
    统一错误处理等能力。

    Attributes:
        move_duration: 默认平滑移动时长（秒）。
    """

    def __init__(self, move_duration: float = MOUSE_MOVE_DURATION):
        """初始化鼠标控制器。

        Args:
            move_duration: 平滑移动的默认时长（秒）。
        """
        self._mouse = MouseController()
        self.move_duration = move_duration
        logger.info("鼠标控制器初始化完成")

    # ===== 公共方法 =====

    def move_to(self, x: int, y: int) -> bool:
        """平滑移动鼠标到指定坐标。

        Args:
            x: 目标 X 坐标（像素，屏幕左上角为原点）。
            y: 目标 Y 坐标（像素）。

        Returns:
            True 表示移动成功，False 表示失败。
        """
        try:
            self._smooth_move_to(x, y, self.move_duration)
            logger.debug(f"鼠标移动到 ({x}, {y})")
            return True
        except Exception as e:
            logger.error(f"鼠标移动失败 ({x}, {y}): {e}")
            return False

    def click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """左键单击。

        如果提供了坐标，先移动到目标位置再点击。

        Args:
            x: 目标 X 坐标，None 表示在当前位置点击。
            y: 目标 Y 坐标，None 表示在当前位置点击。

        Returns:
            True 表示成功，False 表示失败。
        """
        try:
            if x is not None and y is not None:
                self._smooth_move_to(x, y, self.move_duration)
                # 到达目标后微调，增加人类化抖动（±2px）
                self._add_jitter()
            self._mouse.click(Button.left, 1)
            self._human_delay()
            logger.debug(f"左键单击 ({x}, {y})" if x is not None else "左键单击（当前位置）")
            return True
        except Exception as e:
            logger.error(f"左键单击失败: {e}")
            return False

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """右键单击。

        Args:
            x: 目标 X 坐标。
            y: 目标 Y 坐标。

        Returns:
            True 表示成功。
        """
        try:
            if x is not None and y is not None:
                self._smooth_move_to(x, y, self.move_duration)
                self._add_jitter()
            self._mouse.click(Button.right, 1)
            self._human_delay()
            logger.debug(f"右键单击 ({x}, {y})" if x is not None else "右键单击（当前位置）")
            return True
        except Exception as e:
            logger.error(f"右键单击失败: {e}")
            return False

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """左键双击。

        Args:
            x: 目标 X 坐标。
            y: 目标 Y 坐标。

        Returns:
            True 表示成功。
        """
        try:
            if x is not None and y is not None:
                self._smooth_move_to(x, y, self.move_duration)
                self._add_jitter()
            self._mouse.click(Button.left, 2)
            self._human_delay()
            logger.debug(f"双击 ({x}, {y})" if x is not None else "双击（当前位置）")
            return True
        except Exception as e:
            logger.error(f"双击失败: {e}")
            return False

    def drag_from_to(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: Optional[float] = None,
    ) -> bool:
        """从起点拖拽到终点（模拟按住左键拖动）。

        先移动到起点 → 按下左键 → 平滑移动到终点 → 释放左键。

        Args:
            x1: 起点 X 坐标。
            y1: 起点 Y 坐标。
            x2: 终点 X 坐标。
            y2: 终点 Y 坐标。
            duration: 拖拽时长（秒），None 则使用默认值。

        Returns:
            True 表示成功。
        """
        if duration is None:
            duration = MOUSE_DRAG_DURATION

        try:
            # 1. 移到起点
            self._smooth_move_to(x1, y1, self.move_duration)
            self._add_jitter()
            # 2. 按下左键
            self._mouse.press(Button.left)
            # 3. 平滑拖到终点（拖拽比普通移动稍慢）
            self._smooth_move_to(x2, y2, duration)
            # 4. 释放左键
            self._mouse.release(Button.left)
            self._human_delay()
            logger.debug(f"拖拽: ({x1},{y1}) → ({x2},{y2}), 耗时 {duration}s")
            return True
        except Exception as e:
            # 确保释放按键，避免鼠标一直处于"按下"状态
            try:
                self._mouse.release(Button.left)
            except Exception:
                pass
            logger.error(f"拖拽失败: {e}")
            return False

    # ===== 内部方法 =====

    def _smooth_move_to(self, x: int, y: int, duration: float) -> None:
        """分段线性插值平滑移动鼠标。

        将起点→终点按时间拆分为多步，每步间隔约 10ms，
        步数 = duration / 0.01。如果 duration ≤ 0.01，直接跳跃。

        Args:
            x: 目标 X 坐标。
            y: 目标 Y 坐标。
            duration: 移动总时长（秒）。
        """
        step_interval = 0.01  # 每步 10ms
        steps = max(1, int(duration / step_interval))

        start_x, start_y = self._mouse.position
        for i in range(1, steps + 1):
            t = i / steps
            # 线性插值
            cur_x = int(start_x + (x - start_x) * t)
            cur_y = int(start_y + (y - start_y) * t)
            self._mouse.position = (cur_x, cur_y)
            time.sleep(step_interval)

    def _human_delay(self) -> None:
        """在操作后加入随机延迟，模拟人类操作节奏。

        延迟范围由 MOUSE_CLICK_DELAY 配置控制。
        """
        min_delay, max_delay = MOUSE_CLICK_DELAY
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _add_jitter(self) -> None:
        """对当前鼠标位置添加微小随机抖动（±2px），增加人类化特征。"""
        if random.random() < 0.5:  # 50% 概率抖动，不必每次都抖
            cur_x, cur_y = self._mouse.position
            jitter_x = cur_x + random.randint(-2, 2)
            jitter_y = cur_y + random.randint(-2, 2)
            self._mouse.position = (jitter_x, jitter_y)
