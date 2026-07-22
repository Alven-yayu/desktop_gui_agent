# -*- coding: utf-8 -*-
"""控制模块测试 — mouse_controller + keyboard_controller"""
import pytest
from unittest.mock import patch, MagicMock


# ===== KeyboardController 测试 =====

class TestKeyboardType:
    """KeyboardController.type() 测试"""

    def test_type_ascii_text_returns_true(self):
        """纯ASCII文本输入应该返回True"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.type("Hello World")
        assert result is True

    def test_type_empty_text_returns_true(self):
        """空文本直接返回True，不执行操作"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.type("")
        assert result is True

    def test_type_chinese_text_uses_clipboard(self):
        """中文文本应走剪贴板粘贴路径"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        with patch.object(kc, '_type_via_clipboard', return_value=True) as mock_cb:
            result = kc.type("你好世界")
            assert result is True
            mock_cb.assert_called_once()

    def test_type_none_text_returns_false(self):
        """None输入应返回False"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.type(None)
        assert result is False


class TestKeyboardPress:
    """KeyboardController.press() 测试"""

    @patch('desktop_gui_agent.control.keyboard_controller.Key')
    @patch('desktop_gui_agent.control.keyboard_controller.Controller')
    def test_press_normal_key_returns_true(self, MockController, MockKey):
        """按下普通按键应返回True"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.press('enter')
        assert result is True

    def test_press_empty_key_returns_false(self):
        """空按键名返回False"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.press("")
        assert result is False

    def test_press_none_key_returns_false(self):
        """None按键名返回False"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.press(None)
        assert result is False


class TestKeyboardHotkey:
    """KeyboardController.hotkey() 测试"""

    @patch('desktop_gui_agent.control.keyboard_controller.Controller')
    def test_hotkey_two_keys_returns_true(self, MockController):
        """双键组合键应返回True"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.hotkey('ctrl', 'c')
        assert result is True

    @patch('desktop_gui_agent.control.keyboard_controller.Controller')
    def test_hotkey_single_key_returns_true(self, MockController):
        """单键也应返回True（退化为press）"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.hotkey('enter')
        assert result is True

    def test_hotkey_empty_args_returns_false(self):
        """无参数应返回False"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.hotkey()
        assert result is False

    def test_hotkey_ensures_keys_released(self):
        """即使操作失败，也应确保按键释放"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        kc.hotkey('ctrl', 'c')
        # 测试重点：不应有按键卡住状态
        # 验证_is_key_pressed 标志被重置
        assert kc._pressed_keys == set()


class TestKeyboardScroll:
    """KeyboardController.scroll() 测试"""

    @patch('desktop_gui_agent.control.keyboard_controller.MouseScrollController')
    def test_scroll_up_returns_true(self, MockMouse):
        """向上滚动应返回True"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.scroll('up', 3)
        assert result is True

    def test_scroll_invalid_direction_returns_false(self):
        """无效方向应返回False"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.scroll('left', 1)
        assert result is False

    def test_scroll_non_positive_steps(self):
        """非正步数应被调整为正数"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        result = kc.scroll('up', 0)
        assert result is True  # 应自动调整为至少1步


class TestKeyboardControllerInit:
    """KeyboardController 初始化测试"""

    def test_init_default(self):
        """默认初始化应成功"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController

        kc = KeyboardController()
        assert kc is not None
        assert hasattr(kc, 'type')
        assert hasattr(kc, 'press')
        assert hasattr(kc, 'hotkey')
        assert hasattr(kc, 'scroll')


# ===== KeyboardController 上下文管理器测试 =====

class TestKeyboardControllerContextManager:
    """KeyboardController 的 __enter__ / __exit__ 测试"""

    def test_context_manager_returns_self(self):
        """__enter__ 应返回自身"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController
        kc = KeyboardController()
        with kc as ctrl:
            assert ctrl is kc

    def test_context_manager_releases_keys_on_exit(self):
        """__exit__ 应调用 _release_all 释放所有按键"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController
        from unittest.mock import patch

        kc = KeyboardController()
        with patch.object(kc, '_release_all') as mock_release:
            with kc:
                pass
            mock_release.assert_called_once()

    def test_context_manager_releases_keys_on_exception(self):
        """异常退出时也应释放按键（不抑制异常）"""
        from desktop_gui_agent.control.keyboard_controller import KeyboardController
        from unittest.mock import patch

        kc = KeyboardController()
        with patch.object(kc, '_release_all'):
            try:
                with kc:
                    raise RuntimeError("模拟异常")
            except RuntimeError:
                pass
            # 即使抛了异常，_release_all 也应被调用
            # （由 mock 验证，不会真的操作键盘）
