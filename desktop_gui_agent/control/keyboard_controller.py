# -*- coding: utf-8 -*-
"""键盘控制模块 — PDF 4.2.2

基于 pynput 实现键盘输入、组合键和滚轮操作。
所有公共方法统一返回 bool，不抛异常。

中文输入策略：非ASCII文本通过剪贴板 + Ctrl+V 粘贴。
"""
import random
import time
from typing import Optional, Set

from pynput.keyboard import Controller, Key
from pynput.mouse import Controller as MouseScrollController

from desktop_gui_agent.config import (
    KEYBOARD_HOTKEY_DELAY,
    KEYBOARD_SCROLL_STEP,
    KEYBOARD_TYPE_DELAY,
)
from desktop_gui_agent.utils.exceptions import ControlError
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# 特殊按键名到 pynput Key 枚举的映射
_KEY_MAP: dict = {
    "ctrl": Key.ctrl,
    "control": Key.ctrl,
    "ctrl_l": Key.ctrl_l,
    "ctrl_r": Key.ctrl_r,
    "shift": Key.shift,
    "shift_l": Key.shift_l,
    "shift_r": Key.shift_r,
    "alt": Key.alt,
    "alt_l": Key.alt_l,
    "alt_r": Key.alt_r,
    "cmd": Key.cmd,
    "command": Key.cmd,
    "win": Key.cmd,
    "windows": Key.cmd,
    "enter": Key.enter,
    "return": Key.enter,
    "tab": Key.tab,
    "space": Key.space,
    "backspace": Key.backspace,
    "esc": Key.esc,
    "escape": Key.esc,
    "delete": Key.delete,
    "del": Key.delete,
    "insert": Key.insert,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
    "caps_lock": Key.caps_lock,
    "num_lock": Key.num_lock,
    "print_screen": Key.print_screen,
    "scroll_lock": Key.scroll_lock,
    "pause": Key.pause,
}


def _resolve_key(key_str: str):
    """将按键名称字符串解析为 pynput Key 或普通字符。

    Args:
        key_str: 按键名称（不区分大小写）。

    Returns:
        pynput Key 枚举值或单字符字符串。
        无法识别时返回 None。
    """
    lower = key_str.lower().strip()
    if lower in _KEY_MAP:
        return _KEY_MAP[lower]
    # 单个字符
    if len(lower) == 1:
        return lower
    return None


class KeyboardController:
    """键盘操作控制器。

    封装 pynput 键盘 API，提供文本输入、组合键、滚轮等功能，
    统一错误处理和人类化延迟。

    Attributes:
        _pressed_keys: 当前已按下但尚未释放的按键集合。
    """

    def __init__(self):
        """初始化键盘控制器。"""
        self._keyboard = Controller()
        self._mouse = MouseScrollController()
        self._pressed_keys: Set = set()
        logger.info("键盘控制器初始化完成")

    # ===== 公共方法 =====

    def type(self, text: Optional[str]) -> bool:
        """输入文本，逐字符打字。

        纯ASCII文本直接用 Controller.type() 模拟打字速度；
        包含非ASCII字符（中文等）则通过剪贴板粘贴。

        Args:
            text: 要输入的文本，空字符串直接返回 True。

        Returns:
            True 表示成功，False 表示失败。
        """
        if text is None:
            logger.warning("输入文本为 None，跳过")
            return False
        if not text:
            return True

        try:
            if self._is_ascii(text):
                self._type_ascii(text)
            else:
                self._type_via_clipboard(text)
            logger.debug(f"文本输入成功，长度={len(text)}")
            return True
        except Exception as e:
            logger.error(f"文本输入失败: {e}")
            return False

    def press(self, key: Optional[str]) -> bool:
        """按下并释放单个按键。

        Args:
            key: 按键名称，支持特殊键（如 'enter'）和普通字符（如 'a'）。

        Returns:
            True 表示成功，False 表示失败。
        """
        if not key:
            logger.warning("按键名称为空，跳过")
            return False

        try:
            resolved = _resolve_key(key)
            if resolved is None:
                logger.warning(f"无法识别的按键: {key}")
                return False
            self._keyboard.press(resolved)
            self._keyboard.release(resolved)
            logger.debug(f"按下按键: {key}")
            return True
        except Exception as e:
            logger.error(f"按键操作失败 ({key}): {e}")
            return False

    def hotkey(self, *keys: str) -> bool:
        """执行组合键操作。

        先依次按下所有键，再反向释放。
        例如 hotkey('ctrl', 'c') 执行 Ctrl+C 复制。

        Args:
            *keys: 按键序列，支持特殊键名和普通字符。

        Returns:
            True 表示成功，False 表示失败。
        """
        if not keys:
            logger.warning("组合键参数为空")
            return False

        try:
            resolved = []
            for key in keys:
                rk = _resolve_key(key)
                if rk is None:
                    logger.warning(f"无法识别的按键: {key}")
                    # 释放已按下的键
                    self._release_all()
                    return False
                resolved.append(rk)

            # 依次按下
            for i, rk in enumerate(resolved):
                self._keyboard.press(rk)
                self._pressed_keys.add(keys[i])
                self._hotkey_delay()

            # 反向释放
            for i, rk in enumerate(reversed(resolved)):
                self._keyboard.release(rk)
                key_str = keys[len(keys) - 1 - i]
                self._pressed_keys.discard(key_str)
                self._hotkey_delay()

            logger.debug(f"组合键执行成功: {'+'.join(keys)}")
            return True
        except Exception as e:
            logger.error(f"组合键执行失败 ({'+'.join(keys)}): {e}")
            self._release_all()
            return False

    def scroll(self, direction: str, steps: int = 1) -> bool:
        """鼠标滚轮滚动。

        Args:
            direction: 滚动方向，'up' 或 'down'。
            steps: 滚动步数，每步约 120 像素。

        Returns:
            True 表示成功，False 表示失败。
        """
        direction_lower = direction.lower().strip()
        if direction_lower not in ("up", "down"):
            logger.warning(f"无效的滚动方向: {direction}")
            return False

        if steps <= 0:
            steps = 1

        try:
            dy = KEYBOARD_SCROLL_STEP if direction_lower == "down" else -KEYBOARD_SCROLL_STEP
            for _ in range(steps):
                self._mouse.scroll(0, dy)
                time.sleep(0.02)  # 步间微小延迟
            logger.debug(f"滚轮滚动: {direction}, {steps}步")
            return True
        except Exception as e:
            logger.error(f"滚轮滚动失败 ({direction}): {e}")
            return False

    # ===== 内部方法 =====

    @staticmethod
    def _is_ascii(text: str) -> bool:
        """检查文本是否全部为ASCII字符。"""
        try:
            text.encode("ascii")
            return True
        except UnicodeEncodeError:
            return False

    def _type_ascii(self, text: str) -> None:
        """逐字符输入ASCII文本，模拟人工打字。

        Args:
            text: 纯ASCII文本。
        """
        min_delay, max_delay = KEYBOARD_TYPE_DELAY
        for char in text:
            self._keyboard.press(char)
            self._keyboard.release(char)
            delay = random.uniform(min_delay, max_delay)
            time.sleep(delay)

    def _type_via_clipboard(self, text: str) -> None:
        """通过剪贴板粘贴输入中文文本。

        复制文本到剪贴板后执行 Ctrl+V 粘贴。

        Args:
            text: 包含非ASCII字符的文本。
        """
        import pyperclip

        original = pyperclip.paste()
        try:
            pyperclip.copy(text)
            # 短暂等待确保剪贴板内容已更新
            time.sleep(0.05)
            # 执行 Ctrl+V
            self.hotkey("ctrl", "v")
            time.sleep(0.1)
        finally:
            # 恢复原始剪贴板内容
            try:
                pyperclip.copy(original)
            except Exception:
                pass

    def _hotkey_delay(self) -> None:
        """组合键按下/释放之间的微小随机延迟。"""
        min_delay, max_delay = KEYBOARD_HOTKEY_DELAY
        time.sleep(random.uniform(min_delay, max_delay))

    def _release_all(self) -> None:
        """释放所有跟踪的已按下按键，防止按键卡住。"""
        for key_str in list(self._pressed_keys):
            try:
                resolved = _resolve_key(key_str)
                if resolved is not None:
                    self._keyboard.release(resolved)
            except Exception:
                pass
        self._pressed_keys.clear()
