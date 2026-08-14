# -*- coding: utf-8 -*-
"""全局快捷键监听 — Ctrl+Alt+Q 安全退出。

独立于 KeyboardController（用于注入按键）运行，
使用 pynput Listener 监听真实物理键盘事件，
通过 win32_event_filter 过滤掉 Controller 注入的模拟按键。

用法：
    hotkey = GlobalHotkey(on_exit=shutdown_callback)
    hotkey.start()
    # ... agent 工作 ...
    hotkey.stop()
"""
import atexit
import threading
import weakref
from typing import Callable, Optional

from pynput.keyboard import Key, KeyCode, Listener

from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# 所有 GlobalHotkey 实例的弱引用集合：进程退出时统一停止监听，
# 避免每个实例各注册一个 atexit 回调（堆积 + 强引用泄漏）。
_instances = weakref.WeakSet()


def _stop_all_on_exit() -> None:
    """atexit 保底：停止所有存活实例的键盘监听。"""
    for hk in list(_instances):
        try:
            hk.stop()
        except Exception:
            pass


atexit.register(_stop_all_on_exit)

# Ctrl+Alt+Q 的虚拟键码
_VK_Q = 0x51


class GlobalHotkey:
    """全局快捷键监听器。

    在独立 daemon 线程中运行 pynput keyboard Listener，
    监听 Ctrl+Alt+Q 组合键。触发时调用用户注册的回调。

    Attributes:
        on_exit: 用户注册的退出回调（无参数无返回值）。
        _ctrl_held: 当前 Ctrl 键是否按下。
        _alt_held: 当前 Alt 键是否按下。
        _listener: pynput Listener 实例。
        _lock: 保护 _ctrl_held / _alt_held 的线程锁。
    """

    def __init__(self, on_exit: Optional[Callable[[], None]] = None):
        """初始化全局快捷键监听器。

        Args:
            on_exit: 检测到 Ctrl+Alt+Q 时的回调函数。
                     若为 None 则设置 threading.Event。
        """
        self._exit_event = threading.Event()
        self._on_exit = on_exit
        self._ctrl_held = False
        self._alt_held = False
        self._lock = threading.Lock()
        self._listener: Optional[Listener] = None
        self._thread: Optional[threading.Thread] = None
        _instances.add(self)

    # ---- 公开 API ----

    @property
    def exit_event(self) -> threading.Event:
        """外部可通过此 Event 判断是否已触发退出。"""
        return self._exit_event

    def start(self) -> None:
        """启动全局快捷键监听（守护线程）。"""
        if self._listener is not None:
            logger.warning("全局快捷键监听已在运行中")
            return

        self._listener = Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            win32_event_filter=self._filter_injected,
        )
        self._thread = threading.Thread(
            target=self._listener.start,
            daemon=True,
            name="global-hotkey",
        )
        self._thread.start()
        logger.info("全局快捷键监听已启动（Ctrl+Alt+Q 退出）")

    def stop(self) -> None:
        """停止全局快捷键监听。"""
        if self._listener is None:
            return
        try:
            self._listener.stop()
        except Exception:
            pass
        self._listener = None
        self._thread = None
        logger.debug("全局快捷键监听已停止")

    # ---- 内部 ----

    @staticmethod
    def _filter_injected(msg, data):
        """过滤 pynput Controller 注入的模拟按键事件。

        在 Windows 上，LLKHF_INJECTED (0x10) 标志位标识注入事件。
        返回 False 则丢弃该事件（不触发 on_press / on_release）。
        """
        # data.flags 中 LLKHF_INJECTED = 0x10 表示注入
        if data.flags & 0x10:
            return False  # 丢弃模拟按键
        return True

    def _on_press(self, key) -> None:
        """物理按键按下回调。"""
        try:
            if key in (Key.ctrl_l, Key.ctrl_r):
                with self._lock:
                    self._ctrl_held = True
            elif key in (Key.alt_l, Key.alt_r):
                with self._lock:
                    self._alt_held = True
            elif isinstance(key, KeyCode) and key.vk == _VK_Q:
                with self._lock:
                    if self._ctrl_held and self._alt_held:
                        self._fire()
        except Exception:
            pass  # 回调异常不影响监听器

    def _on_release(self, key) -> None:
        """物理按键释放回调。"""
        try:
            if key in (Key.ctrl_l, Key.ctrl_r):
                with self._lock:
                    self._ctrl_held = False
            elif key in (Key.alt_l, Key.alt_r):
                with self._lock:
                    self._alt_held = False
        except Exception:
            pass

    def _fire(self) -> None:
        """触发退出：设置 Event + 调用用户回调。"""
        self._exit_event.set()
        logger.info("检测到 Ctrl+Alt+Q，正在安全退出...")
        if self._on_exit is not None:
            try:
                self._on_exit()
            except Exception as e:
                logger.error(f"退出回调异常: {e}")
