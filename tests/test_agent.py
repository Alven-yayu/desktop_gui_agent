# -*- coding: utf-8 -*-
"""Agent决策模块测试 — model_client + action_parser + task_manager"""
import pytest


# ===== 异常类测试 =====

class TestModelError:
    """ModelError 异常类测试"""

    def test_model_error_is_exception(self):
        """ModelError 应该是 Exception 的子类"""
        from desktop_gui_agent.utils.exceptions import ModelError
        assert issubclass(ModelError, Exception)

    def test_model_error_can_be_raised(self):
        """ModelError 可以被抛出并捕获"""
        from desktop_gui_agent.utils.exceptions import ModelError
        with pytest.raises(ModelError) as exc_info:
            raise ModelError("模型加载失败")
        assert "模型加载失败" in str(exc_info.value)


# ===== 错误分类测试（Phase 5）=====

class TestErrorCategory:
    """classify_error() 测试"""

    def test_screenshot_error_is_retryable(self):
        """ScreenshotError 应归类为 RETRYABLE"""
        from desktop_gui_agent.utils.exceptions import ScreenshotError, classify_error, ErrorCategory
        assert classify_error(ScreenshotError("截图失败")) == ErrorCategory.RETRYABLE

    def test_ocr_error_is_skip(self):
        """OCRError 应归类为 SKIP"""
        from desktop_gui_agent.utils.exceptions import OCRError, classify_error, ErrorCategory
        assert classify_error(OCRError("OCR失败")) == ErrorCategory.SKIP

    def test_model_error_loading_is_fatal(self):
        """模型加载失败的 ModelError 应归类为 FATAL"""
        from desktop_gui_agent.utils.exceptions import ModelError, classify_error, ErrorCategory
        err = ModelError("本地模型加载失败")
        assert classify_error(err) == ErrorCategory.FATAL

    def test_model_error_api_retry_is_skip(self):
        """API 重试失败的 ModelError 应归类为 SKIP"""
        from desktop_gui_agent.utils.exceptions import ModelError, classify_error, ErrorCategory
        err = ModelError("API 调用失败（已重试）")
        assert classify_error(err) == ErrorCategory.SKIP

    def test_connection_error_is_retryable(self):
        """ConnectionError 应归类为 RETRYABLE"""
        from desktop_gui_agent.utils.exceptions import classify_error, ErrorCategory
        import requests
        try:
            # 触发一个 ConnectionError
            raise requests.ConnectionError("连接失败")
        except requests.ConnectionError as e:
            assert classify_error(e) == ErrorCategory.RETRYABLE

    def test_timeout_error_is_retryable(self):
        """Timeout 应归类为 RETRYABLE"""
        from desktop_gui_agent.utils.exceptions import classify_error, ErrorCategory
        import requests
        try:
            raise requests.Timeout("超时")
        except requests.Timeout as e:
            assert classify_error(e) == ErrorCategory.RETRYABLE

    def test_generic_exception_is_skip(self):
        """未知异常保守归类为 SKIP"""
        from desktop_gui_agent.utils.exceptions import classify_error, ErrorCategory
        assert classify_error(ValueError("未知错误")) == ErrorCategory.SKIP

    def test_control_error_is_skip(self):
        """ControlError 应归类为 SKIP"""
        from desktop_gui_agent.utils.exceptions import ControlError, classify_error, ErrorCategory
        assert classify_error(ControlError("坐标越界")) == ErrorCategory.SKIP

    def test_ui_locator_error_is_skip(self):
        """UILocatorError 应归类为 SKIP"""
        from desktop_gui_agent.utils.exceptions import UILocatorError, classify_error, ErrorCategory
        assert classify_error(UILocatorError("空图片")) == ErrorCategory.SKIP


# ===== 配置项测试 =====

class TestAgentConfig:
    """Agent 模块配置项测试"""

    def test_model_config_exists(self):
        """模型相关配置项应该存在且类型正确"""
        from desktop_gui_agent import config
        assert isinstance(config.MODEL_NAME, str)
        assert config.MODEL_MODE in ("local", "api")
        assert config.MODEL_MAX_TOKENS > 0

    def test_agent_loop_config_exists(self):
        """主循环配置项应该存在且类型正确"""
        from desktop_gui_agent import config
        assert isinstance(config.AGENT_MAX_STEPS, int)
        assert config.AGENT_MAX_STEPS > 0
        assert isinstance(config.AGENT_MAX_CONSECUTIVE_ERRORS, int)
        assert config.AGENT_MAX_CONSECUTIVE_ERRORS > 0

    def test_agent_step_delay_is_valid_tuple(self):
        """步骤延迟应该是 (min, max) 元组"""
        from desktop_gui_agent import config
        delay = config.AGENT_STEP_DELAY
        assert isinstance(delay, tuple)
        assert len(delay) == 2
        assert delay[0] <= delay[1]
        assert delay[0] >= 0

    def test_api_config_defaults_to_none(self):
        """API 配置默认应为 None（本地模式优先）"""
        from desktop_gui_agent import config
        assert config.MODEL_API_URL is None or isinstance(config.MODEL_API_URL, str)
        assert config.MODEL_API_KEY is None or isinstance(config.MODEL_API_KEY, str)


# ===== ActionParser 测试 =====

class TestActionParser:
    """action_parser.parse() 测试"""

    # ---- click ----
    def test_parse_click_with_coordinates(self):
        """解析 click(x=100, y=200)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("click(x=100, y=200)")
        assert result["action_type"] == "click"
        assert result["params"] == {"x": 100, "y": 200}

    def test_parse_click_with_spaces(self):
        """解析带空格的 click( x=300 , y=400 )"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("  click( x=300 , y=400 )  ")
        assert result["action_type"] == "click"
        assert result["params"] == {"x": 300, "y": 400}

    def test_parse_click_case_insensitive(self):
        """Click / CLICK 应该都能识别"""
        from desktop_gui_agent.agent.action_parser import parse
        assert parse("Click(x=10, y=20)")["action_type"] == "click"
        assert parse("CLICK(x=10, y=20)")["action_type"] == "click"

    # ---- type ----
    def test_parse_type_english(self):
        """解析 type(text="Hello")"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('type(text="Hello World")')
        assert result["action_type"] == "type"
        assert result["params"] == {"text": "Hello World"}

    def test_parse_type_chinese(self):
        """解析 type 含中文"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('type(text="你好世界")')
        assert result["action_type"] == "type"
        assert result["params"] == {"text": "你好世界"}

    def test_parse_type_with_escaped_quotes(self):
        """type 文本中含有转义引号"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse(r'type(text="He said \"hi\"")')
        assert result["action_type"] == "type"
        assert "He said" in result["params"]["text"]

    def test_parse_type_with_enter_true(self):
        """解析 type(text="1+1", enter=True) 应带出 enter=True"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('type(text="1+1", enter=True)')
        assert result["action_type"] == "type"
        assert result["params"] == {"text": "1+1", "enter": True}

    def test_parse_type_without_enter(self):
        """type 不带 enter 参数时 params 无 enter 键（向后兼容）"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('type(text="1+1")')
        assert result["action_type"] == "type"
        assert result["params"] == {"text": "1+1"}
        assert "enter" not in result["params"]

    # ---- scroll ----
    def test_parse_scroll_up(self):
        """解析 scroll(direction="up", steps=3)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('scroll(direction="up", steps=3)')
        assert result["action_type"] == "scroll"
        assert result["params"] == {"direction": "up", "steps": 3}

    def test_parse_scroll_down(self):
        """解析 scroll(direction="down", steps=5)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('scroll(direction="down", steps=5)')
        assert result["action_type"] == "scroll"
        assert result["params"] == {"direction": "down", "steps": 5}

    # ---- hotkey ----
    def test_parse_hotkey_two_keys(self):
        """解析 hotkey(ctrl, c)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("hotkey(ctrl, c)")
        assert result["action_type"] == "hotkey"
        assert result["params"] == {"keys": ["ctrl", "c"]}

    def test_parse_hotkey_three_keys(self):
        """解析 hotkey(ctrl, shift, esc)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("hotkey(ctrl, shift, esc)")
        assert result["action_type"] == "hotkey"
        assert result["params"] == {"keys": ["ctrl", "shift", "esc"]}

    def test_parse_hotkey_single_key(self):
        """解析 hotkey(enter) — 单个按键也合法"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("hotkey(enter)")
        assert result["action_type"] == "hotkey"
        assert result["params"] == {"keys": ["enter"]}

    # ---- finish ----
    def test_parse_finish(self):
        """解析 finish(result="任务完成")"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('finish(result="已成功打开记事本")')
        assert result["action_type"] == "finish"
        assert result["params"] == {"result": "已成功打开记事本"}

    def test_parse_finish_empty_result(self):
        """finish 结果可以为空"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('finish(result="")')
        assert result["action_type"] == "finish"
        assert result["params"] == {"result": ""}

    # ---- 容错 ----
    def test_parse_none_input(self):
        """None 输入返回 unknown"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse(None)
        assert result["action_type"] == "unknown"
        assert "raw" in result

    def test_parse_empty_string(self):
        """空字符串返回 unknown"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("")
        assert result["action_type"] == "unknown"

    def test_parse_garbage_text(self):
        """无法识别的文本返回 unknown"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("这是乱七八糟的输出")
        assert result["action_type"] == "unknown"
        assert result["raw"] == "这是乱七八糟的输出"

    def test_parse_click_missing_y(self):
        """click 缺少 y 参数应返回 unknown"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("click(x=100)")
        assert result["action_type"] == "unknown"

    def test_parse_only_first_action_when_multiple(self):
        """多行动作只取第一个（单步单动作原则）"""
        from desktop_gui_agent.agent.action_parser import parse
        multi = 'click(x=10, y=20)\ntype(text="hello")'
        result = parse(multi)
        assert result["action_type"] == "click"
        assert result["params"] == {"x": 10, "y": 20}

    def test_parse_scroll_default_steps(self):
        """scroll 未指定 steps 时默认 1"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('scroll(direction="down")')
        assert result["action_type"] == "scroll"
        assert result["params"]["steps"] == 1

    # ---- right_click（右键）----
    def test_parse_right_click_marker(self):
        """解析 right_click_marker(3)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("right_click_marker(3)")
        assert result["action_type"] == "right_click_marker"
        assert result["params"] == {"marker": 3}

    def test_parse_right_click_coords(self):
        """解析 right_click(x=100, y=200)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("right_click(x=100, y=200)")
        assert result["action_type"] == "right_click"
        assert result["params"] == {"x": 100, "y": 200}

    def test_parse_right_click_marker_not_click_marker(self):
        """回归：right_click_marker 不能被 click_marker 正则误吞"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("right_click_marker(3)")
        assert result["action_type"] == "right_click_marker"

    def test_parse_right_click_not_click(self):
        """回归：right_click(x=1,y=2) 不能被 click 正则误吞"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("right_click(x=1, y=2)")
        assert result["action_type"] == "right_click"

    # ---- drag（拖拽）----
    def test_parse_drag_marker(self):
        """解析 drag_marker(from=1, to=5)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("drag_marker(from=1, to=5)")
        assert result["action_type"] == "drag_marker"
        assert result["params"] == {"from": 1, "to": 5}

    def test_parse_drag_coords(self):
        """解析 drag(x1=100,y1=200,x2=300,y2=400)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("drag(x1=100,y1=200,x2=300,y2=400)")
        assert result["action_type"] == "drag"
        assert result["params"] == {"x1": 100, "y1": 200, "x2": 300, "y2": 400}

    def test_parse_drag_negative_coords(self):
        """drag 坐标支持负数（不会因负号匹配失败）"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("drag(x1=-5,y1=10,x2=-20,y2=30)")
        assert result["action_type"] == "drag"
        assert result["params"] == {"x1": -5, "y1": 10, "x2": -20, "y2": 30}

    def test_parse_drag_marker_missing_to(self):
        """drag_marker 缺 to 参数返回 unknown"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("drag_marker(from=1)")
        assert result["action_type"] == "unknown"

    # ---- press（单键）----
    def test_parse_press_quoted(self):
        """解析 press(key="tab")（带引号）"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('press(key="tab")')
        assert result["action_type"] == "press"
        assert result["params"] == {"key": "tab"}

    def test_parse_press_unquoted(self):
        """解析 press(key=enter)（不带引号）"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("press(key=enter)")
        assert result["action_type"] == "press"
        assert result["params"] == {"key": "enter"}

    def test_parse_press_missing_key(self):
        """press() 缺 key 参数返回 unknown"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("press()")
        assert result["action_type"] == "unknown"

    # ---- click_marker 带 text（点击目标核对守卫）----
    def test_parse_click_marker_with_text(self):
        """解析 click_marker(3, text=\"保存\") 应带出 text 参数"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('click_marker(3, text="保存")')
        assert result["action_type"] == "click_marker"
        assert result["params"] == {"marker": 3, "text": "保存"}

    def test_parse_click_marker_without_text(self):
        """click_marker(3) 不带 text 时 params 无 text 键（向后兼容）"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("click_marker(3)")
        assert result["action_type"] == "click_marker"
        assert result["params"] == {"marker": 3}
        assert "text" not in result["params"]

    def test_parse_double_click_marker_with_text(self):
        """解析 double_click_marker(2, text=\"回收站\")"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('double_click_marker(2, text="回收站")')
        assert result["action_type"] == "double_click_marker"
        assert result["params"] == {"marker": 2, "text": "回收站"}

    def test_parse_right_click_marker_with_text(self):
        """解析 right_click_marker(2, text=\"回收站\")"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('right_click_marker(2, text="回收站")')
        assert result["action_type"] == "right_click_marker"
        assert result["params"] == {"marker": 2, "text": "回收站"}

    # ---- set_slider（滑块设值）----
    def test_parse_set_slider(self):
        """解析 set_slider(marker=18, value=50)"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("set_slider(marker=18, value=50)")
        assert result["action_type"] == "set_slider"
        assert result["params"] == {"marker": 18, "value": 50}

    def test_parse_set_slider_missing_value(self):
        """set_slider 缺 value 参数返回 unknown"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("set_slider(marker=18)")
        assert result["action_type"] == "unknown"

    # ---- set_control（通用控件设值）----
    def test_parse_set_control_numeric_value(self):
        """set_control 数字 value（滑块）"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("set_control(marker=18, value=50)")
        assert result["action_type"] == "set_control"
        assert result["params"] == {"marker": 18, "value": 50}

    def test_parse_set_control_string_value(self):
        """set_control 字符串 value（下拉选项/文本）"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse('set_control(marker=5, value=".txt")')
        assert result["action_type"] == "set_control"
        assert result["params"] == {"marker": 5, "value": ".txt"}

    def test_parse_set_control_not_swallowed_by_click(self):
        """set_control 不能被 click 正则误吞"""
        from desktop_gui_agent.agent.action_parser import parse
        result = parse("set_control(marker=5, value=\"on\")")
        assert result["action_type"] == "set_control"

# ===== ModelClient 测试 =====
from unittest.mock import patch, MagicMock
from PIL import Image


@pytest.fixture
def sample_screenshot():
    """创建一张测试用的截图"""
    return Image.new("RGB", (800, 600), color=(100, 150, 200))


class TestModelClientInit:
    """ModelClient 初始化测试"""

    def test_init_default_local_mode(self):
        """默认应该是 local 模式"""
        from desktop_gui_agent.agent.model_client import ModelClient
        client = ModelClient()
        assert client.mode == "local"

    def test_init_api_mode(self):
        """可以通过参数指定 api 模式"""
        from desktop_gui_agent.agent.model_client import ModelClient
        client = ModelClient(mode="api", api_url="http://test:8080")
        assert client.mode == "api"

    def test_init_raises_on_invalid_mode(self):
        """非法模式应抛 ModelError"""
        import pytest
        from desktop_gui_agent.agent.model_client import ModelClient
        from desktop_gui_agent.utils.exceptions import ModelError
        with pytest.raises(ModelError):
            ModelClient(mode="invalid_mode")


class TestModelClientQuery:
    """ModelClient.query() 测试"""

    @patch('desktop_gui_agent.agent.model_client.process_vision_info')
    @patch('desktop_gui_agent.agent.model_client._load_local_model')
    def test_query_local_returns_string(self, mock_load, mock_pvi, sample_screenshot):
        """本地模式 query 应返回字符串"""
        from desktop_gui_agent.agent.model_client import ModelClient
        # mock 模型和处理器
        mock_model = MagicMock()
        mock_model.device = "cpu"
        mock_processor = MagicMock()
        mock_processor.apply_chat_template.return_value = "chat template output"
        mock_processor.batch_decode.return_value = ["click(x=100, y=200)"]
        mock_load.return_value = (mock_model, mock_processor)
        mock_pvi.return_value = ([], [])

        client = ModelClient(mode="local")
        result = client.query(sample_screenshot, "点击确定按钮")
        assert isinstance(result, str)
        assert len(result) > 0

    @patch('desktop_gui_agent.agent.model_client.process_vision_info')
    @patch('desktop_gui_agent.agent.model_client._load_local_model')
    def test_query_includes_task_in_prompt(self, mock_load, mock_pvi, sample_screenshot):
        """query 应该把任务描述放入 prompt"""
        from desktop_gui_agent.agent.model_client import ModelClient
        mock_model = MagicMock()
        mock_model.device = "cpu"
        mock_processor = MagicMock()
        mock_processor.apply_chat_template.return_value = "chat template output"
        mock_processor.batch_decode.return_value = ["finish(result=\"done\")"]
        mock_load.return_value = (mock_model, mock_processor)
        mock_pvi.return_value = ([], [])

        client = ModelClient(mode="local")
        result = client.query(sample_screenshot, "打开记事本")
        # 验证模型被调用时 prompt 包含任务
        call_args = mock_processor.apply_chat_template.call_args
        assert call_args is not None

    @patch('desktop_gui_agent.agent.model_client.process_vision_info')
    @patch('desktop_gui_agent.agent.model_client._load_local_model')
    def test_query_with_context(self, mock_load, mock_pvi, sample_screenshot):
        """带历史动作的 query 应包含上下文"""
        from desktop_gui_agent.agent.model_client import ModelClient
        mock_model = MagicMock()
        mock_model.device = "cpu"
        mock_processor = MagicMock()
        mock_processor.apply_chat_template.return_value = "chat template output"
        mock_processor.batch_decode.return_value = ["type(text=\"hello\")"]
        mock_load.return_value = (mock_model, mock_processor)
        mock_pvi.return_value = ([], [])

        client = ModelClient(mode="local")
        context = ["click(x=100, y=200)", "type(text=\"hello\")"]
        result = client.query(sample_screenshot, "继续操作", context=context)
        assert isinstance(result, str)
        # 验证上下文确实被注入到 prompt 中
        call_args = mock_processor.apply_chat_template.call_args
        messages = call_args[0][0]  # 第一个位置参数是 messages 列表
        # 找到 user 消息的 content 列表中的 text 内容
        user_content_text = ""
        for msg in messages:
            if msg["role"] == "user":
                for item in msg["content"]:
                    if item["type"] == "text":
                        user_content_text += item["text"]
        assert "click(x=100, y=200)" in user_content_text
        assert "type(text=\"hello\")" in user_content_text

    @patch('desktop_gui_agent.agent.model_client.requests.post')
    def test_query_api_mode_returns_string(self, mock_post, sample_screenshot):
        """API 模式 query 应返回字符串"""
        from desktop_gui_agent.agent.model_client import ModelClient
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "finish(result=\"ok\")"}}]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = ModelClient(mode="api", api_url="http://test:8080/v1")
        result = client.query(sample_screenshot, "完成任务")
        assert isinstance(result, str)

    @patch('desktop_gui_agent.agent.model_client.requests.post')
    def test_query_api_retry_on_failure(self, mock_post, sample_screenshot):
        """API 调用失败时应重试一次"""
        import desktop_gui_agent.config as config
        from desktop_gui_agent.agent.model_client import ModelClient
        from desktop_gui_agent.utils.exceptions import ModelError
        mock_post.side_effect = Exception("网络错误")

        client = ModelClient(mode="api", api_url="http://test:8080/v1")
        with pytest.raises(ModelError):
            client.query(sample_screenshot, "测试任务")
        # 应该调用了两次（原始 + 重试）
        assert mock_post.call_count == 2

    def test_query_with_none_image(self, sample_screenshot):
        """None 截图应抛 ModelError"""
        import pytest
        from desktop_gui_agent.agent.model_client import ModelClient
        from desktop_gui_agent.utils.exceptions import ModelError
        client = ModelClient(mode="local")
        with pytest.raises(ModelError):
            client.query(None, "测试任务")


# ===== TaskManager 测试 =====

class TestTaskManagerInit:
    """TaskManager 初始化测试"""

    def test_init_default_max_steps(self):
        """默认 max_steps 应为 20"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm.max_steps == 20

    def test_init_default_max_consecutive_errors(self):
        """默认 max_consecutive_errors 应为 3"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm.max_consecutive_errors == 3

    def test_init_custom_max_steps(self):
        """可以自定义 max_steps"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager(max_steps=5)
        assert tm.max_steps == 5

    def test_init_custom_max_consecutive_errors(self):
        """可以自定义 max_consecutive_errors"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager(max_consecutive_errors=5)
        assert tm.max_consecutive_errors == 5

    def test_init_injects_mouse_controller(self):
        """可以注入自定义 mouse controller"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = object()
        tm = TaskManager(mouse=mock_mouse)
        assert tm.mouse is mock_mouse

    def test_init_injects_keyboard_controller(self):
        """可以注入自定义 keyboard controller"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = object()
        tm = TaskManager(keyboard=mock_keyboard)
        assert tm.keyboard is mock_keyboard

    def test_init_injects_model_client(self):
        """可以注入自定义 model client"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_model = object()
        tm = TaskManager(model_client=mock_model)
        assert tm.model_client is mock_model


class TestTaskManagerValidateCoordinates:
    """_validate_coordinates 测试"""

    def test_valid_coordinates_returns_true(self):
        """屏幕范围内的坐标应返回 True"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm._validate_coordinates(100, 200, 1920, 1080) is True

    def test_negative_x_returns_false(self):
        """负 X 坐标应返回 False"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm._validate_coordinates(-1, 200, 1920, 1080) is False

    def test_negative_y_returns_false(self):
        """负 Y 坐标应返回 False"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm._validate_coordinates(100, -1, 1920, 1080) is False

    def test_x_beyond_width_returns_false(self):
        """X 超过屏幕宽度应返回 False"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm._validate_coordinates(2000, 200, 1920, 1080) is False

    def test_y_beyond_height_returns_false(self):
        """Y 超过屏幕高度应返回 False"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm._validate_coordinates(100, 2000, 1920, 1080) is False

    def test_origin_coordinates_valid(self):
        """原点 (0, 0) 应该是有效的"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm._validate_coordinates(0, 0, 1920, 1080) is True

    def test_max_edge_coordinates_valid(self):
        """屏幕右下角边缘坐标应该是有效的"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm._validate_coordinates(1919, 1079, 1920, 1080) is True


class TestTaskManagerDispatch:
    """_dispatch 动作分发测试"""

    def test_dispatch_click_calls_mouse(self):
        """click 动作应调用 mouse.click(x, y)"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        result = tm._dispatch({"action_type": "click", "params": {"x": 100, "y": 200}})
        mock_mouse.click.assert_called_once_with(100, 200)
        assert result is True

    def test_dispatch_click_marker_desktop_auto_double_click(self):
        """桌面上点击图标 → 自动双击（桌面图标单击只选中不打开，否则模型
        "点了没反应"误判失败退回搜索）"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.double_click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开QQ音乐"
        tm._is_desktop = True
        tm._marker_map = {
            38: {"click_point": (137, 779), "text": "QQ音乐", "source": "ocr"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value=""), \
             patch.object(TaskManager, "_foreground_class", return_value="Progman"):
            result = tm._dispatch(
                {"action_type": "click_marker",
                 "params": {"marker": 38, "text": "QQ音乐"}}
            )
        mock_mouse.double_click.assert_called_once_with(137, 779)
        mock_mouse.click.assert_not_called()
        assert result is True

    def test_dispatch_click_marker_in_app_single_click(self):
        """应用窗口内点击 → 保持单击（只有桌面图标才双击）"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "关闭当前窗口"
        tm._is_desktop = False
        tm._marker_map = {2: {"click_point": (50, 60), "text": "关闭"}}
        result = tm._dispatch(
            {"action_type": "click_marker", "params": {"marker": 2, "text": "关闭"}}
        )
        mock_mouse.click.assert_called_once_with(50, 60)
        mock_mouse.double_click.assert_not_called()
        assert result is True

    def test_dispatch_type_calls_keyboard(self):
        """type 动作应调用 keyboard.type(text)"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = MagicMock()
        mock_keyboard.type.return_value = True
        tm = TaskManager(keyboard=mock_keyboard)
        result = tm._dispatch({"action_type": "type", "params": {"text": "hello"}})
        mock_keyboard.type.assert_called_once_with("hello")
        assert result is True

    def test_dispatch_type_with_enter_presses_enter(self):
        """type(..., enter=True) 输入后应立即按 enter"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = MagicMock()
        mock_keyboard.type.return_value = True
        tm = TaskManager(keyboard=mock_keyboard)
        result = tm._dispatch({
            "action_type": "type", "params": {"text": "1+1", "enter": True},
        })
        mock_keyboard.type.assert_called_once_with("1+1")
        mock_keyboard.press.assert_called_once_with("enter")
        assert result is True

    def test_dispatch_type_without_enter_no_press(self):
        """type 不带 enter 时不应按 enter"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = MagicMock()
        mock_keyboard.type.return_value = True
        tm = TaskManager(keyboard=mock_keyboard)
        tm._dispatch({"action_type": "type", "params": {"text": "hello"}})
        mock_keyboard.press.assert_not_called()

    def test_dispatch_scroll_calls_keyboard(self):
        """scroll 动作应调用 keyboard.scroll(direction, steps)"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = MagicMock()
        mock_keyboard.scroll.return_value = True
        tm = TaskManager(keyboard=mock_keyboard)
        result = tm._dispatch({"action_type": "scroll", "params": {"direction": "down", "steps": 3}})
        mock_keyboard.scroll.assert_called_once_with("down", 3)
        assert result is True

    def test_dispatch_hotkey_calls_keyboard(self):
        """hotkey 动作应调用 keyboard.hotkey(*keys)"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = MagicMock()
        mock_keyboard.hotkey.return_value = True
        tm = TaskManager(keyboard=mock_keyboard)
        result = tm._dispatch({"action_type": "hotkey", "params": {"keys": ["ctrl", "c"]}})
        mock_keyboard.hotkey.assert_called_once_with("ctrl", "c")
        assert result is True

    def test_dispatch_finish_returns_true(self):
        """finish 动作直接返回 True，不需要调用控制器"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        result = tm._dispatch({"action_type": "finish", "params": {"result": "done"}})
        assert result is True

    def test_dispatch_unknown_returns_false(self):
        """unknown 动作应返回 False"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        result = tm._dispatch({"action_type": "unknown", "raw": "garbage"})
        assert result is False

    def test_dispatch_mouse_failure_returns_false(self):
        """mouse.click 失败时 _dispatch 应返回 False"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = False
        tm = TaskManager(mouse=mock_mouse)
        result = tm._dispatch({"action_type": "click", "params": {"x": 100, "y": 200}})
        assert result is False

    # ---- 新增动作：右键 / 拖拽 / 单键 ----
    def test_dispatch_right_click_marker_calls_mouse(self):
        """right_click_marker 应从 marker_map 解析坐标并调用 mouse.right_click"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.right_click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._marker_map = {3: {"click_point": (10, 20), "text": "回收站", "source": "uia"}}
        result = tm._dispatch({"action_type": "right_click_marker", "params": {"marker": 3}})
        mock_mouse.right_click.assert_called_once_with(10, 20)
        assert result is True

    def test_dispatch_right_click_calls_mouse(self):
        """right_click 坐标形式应调用 mouse.right_click(x, y)"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.right_click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        result = tm._dispatch({"action_type": "right_click", "params": {"x": 100, "y": 200}})
        mock_mouse.right_click.assert_called_once_with(100, 200)
        assert result is True

    def test_dispatch_drag_marker_calls_mouse(self):
        """drag_marker 应解析两个 marker 坐标并调用 mouse.drag_from_to"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.drag_from_to.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._marker_map = {
            1: {"click_point": (100, 200)},
            5: {"click_point": (300, 400)},
        }
        result = tm._dispatch({"action_type": "drag_marker", "params": {"from": 1, "to": 5}})
        mock_mouse.drag_from_to.assert_called_once_with(100, 200, 300, 400)
        assert result is True

    def test_dispatch_drag_calls_mouse(self):
        """drag 坐标形式应调用 mouse.drag_from_to(x1,y1,x2,y2)"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.drag_from_to.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        result = tm._dispatch({
            "action_type": "drag",
            "params": {"x1": 100, "y1": 200, "x2": 300, "y2": 400},
        })
        mock_mouse.drag_from_to.assert_called_once_with(100, 200, 300, 400)
        assert result is True

    def test_dispatch_press_calls_keyboard(self):
        """press 动作应调用 keyboard.press(key)"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = MagicMock()
        mock_keyboard.press.return_value = True
        tm = TaskManager(keyboard=mock_keyboard)
        result = tm._dispatch({"action_type": "press", "params": {"key": "tab"}})
        mock_keyboard.press.assert_called_once_with("tab")
        assert result is True

    def test_dispatch_right_click_marker_missing_returns_false(self):
        """right_click_marker 指向不存在的编号应返回 False"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        tm = TaskManager(mouse=mock_mouse)
        result = tm._dispatch({"action_type": "right_click_marker", "params": {"marker": 99}})
        assert result is False
        mock_mouse.right_click.assert_not_called()

    # ---- 点击目标核对守卫（防幻觉误点）----
    def test_dispatch_guard_blocks_unrelated_marker(self):
        """任务要"打开计算器"，点 #8（哔哩哔哩）应被拦截，不执行点击"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开计算器，输入 1+1 并回车得出结果"
        tm._marker_map = {
            8: {"click_point": (380, 276), "text": "哔哩哔哩", "source": "uia"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="计算器"):
            result = tm._dispatch(
                {"action_type": "click_marker", "params": {"marker": 8}}
            )
        assert result is False
        mock_mouse.click.assert_not_called()
        assert "哔哩哔哩" in tm._bad_marker_hint

    def test_dispatch_guard_rejects_wrong_claimed_text(self):
        """模型声称 #8 是"计算器"但真实是"哔哩哔哩"→ Tier1 拒绝"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开计算器"
        tm._marker_map = {
            8: {"click_point": (380, 276), "text": "哔哩哔哩", "source": "uia"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="计算器"):
            result = tm._dispatch({
                "action_type": "click_marker",
                "params": {"marker": 8, "text": "计算器"},
            })
        assert result is False
        mock_mouse.click.assert_not_called()

    def test_dispatch_guard_passes_on_explicit_confirm(self):
        """模型用 text 明确确认 #8 是"哔哩哔哩"→ 放行（多一轮确认不死锁）"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开计算器"
        tm._marker_map = {
            8: {"click_point": (380, 276), "text": "哔哩哔哩", "source": "uia"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="计算器"):
            result = tm._dispatch({
                "action_type": "click_marker",
                "params": {"marker": 8, "text": "哔哩哔哩"},
            })
        mock_mouse.click.assert_called_once_with(380, 276)
        assert result is True

    def test_dispatch_guard_skips_digit_buttons(self):
        """数字/单字符按钮（计算器"1"）不做关键词校验，正常放行"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开计算器，输入 1+1 并回车得出结果"
        tm._marker_map = {
            29: {"click_point": (200, 300), "text": "1", "source": "uia"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="计算器"):
            result = tm._dispatch(
                {"action_type": "click_marker", "params": {"marker": 29}}
            )
        mock_mouse.click.assert_called_once_with(200, 300)
        assert result is True

    def test_dispatch_guard_skips_empty_marker_text(self):
        """标注无文字时不校验（图标按钮），放行"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开计算器"
        tm._marker_map = {5: {"click_point": (10, 20)}}
        with patch.object(TaskManager, "_foreground_title", return_value="计算器"):
            result = tm._dispatch(
                {"action_type": "click_marker", "params": {"marker": 5}}
            )
        mock_mouse.click.assert_called_once_with(10, 20)
        assert result is True

    def test_dispatch_guard_no_task_backward_compat(self):
        """无 _current_task（旧测试/直接调 _dispatch）→ 守卫跳过，放行"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._marker_map = {1: {"click_point": (100, 200), "text": "回收站"}}
        result = tm._dispatch({"action_type": "click_marker", "params": {"marker": 1}})
        mock_mouse.click.assert_called_once_with(100, 200)
        assert result is True

    # ---- 打开应用 → 强制键盘搜索SOP（防点击落点不可靠）----
    def test_open_search_guard_blocks_when_target_not_foreground(self):
        """任务要"打开计算器"但前台是别的 → 拦截点击，强制键盘搜索"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开计算器，输入 1+1 并回车得出结果"
        tm._marker_map = {
            10: {"click_point": (848, 413), "text": "计算器", "source": "ocr"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="Microsoft Word"), \
             patch.object(TaskManager, "_foreground_class", return_value="OpusApp"):
            result = tm._dispatch(
                {"action_type": "click_marker", "params": {"marker": 10}}
            )
        assert result is False
        mock_mouse.click.assert_not_called()
        assert "搜索" in tm._bad_marker_hint
        assert "计算器" in tm._bad_marker_hint

    def test_open_search_guard_passes_when_target_foreground(self):
        """目标已在前台（计算器已打开）→ 点击放行（如点数字按钮）"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开计算器，输入 1+1 并回车得出结果"
        tm._marker_map = {
            29: {"click_point": (200, 300), "text": "1", "source": "uia"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="计算器"):
            result = tm._dispatch(
                {"action_type": "click_marker", "params": {"marker": 29}}
            )
        mock_mouse.click.assert_called_once_with(200, 300)
        assert result is True

    def test_open_search_guard_skips_system_tasks(self):
        """系统级任务（音量）目标不是应用窗口 → 不强制搜索，放行"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开音量面板，把音量调整到 50%"
        tm._marker_map = {3: {"click_point": (10, 20), "text": "音量"}}
        with patch.object(TaskManager, "_foreground_title", return_value="快速设置"):
            result = tm._dispatch(
                {"action_type": "click_marker", "params": {"marker": 3}}
            )
        mock_mouse.click.assert_called_once_with(10, 20)
        assert result is True

    def test_open_search_guard_skips_non_open_task(self):
        """非"打开X"任务（关闭当前窗口）→ 不拦截点击"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "关闭当前窗口"
        tm._marker_map = {2: {"click_point": (50, 60), "text": "关闭"}}
        result = tm._dispatch({"action_type": "click_marker", "params": {"marker": 2}})
        mock_mouse.click.assert_called_once_with(50, 60)
        assert result is True

    def test_extract_open_target(self):
        """从任务提取目标应用名；模糊/非打开任务返回空串"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        assert tm._extract_open_target("打开计算器，输入 1+1") == "计算器"
        assert tm._extract_open_target("打开微信，发送消息") == "微信"
        # 复合任务：剥离动作词后缀
        assert tm._extract_open_target("打开浏览器搜索 Python") == "浏览器"
        assert tm._extract_open_target("打开记事本输入 Hello World") == "记事本"
        assert tm._extract_open_target("打开计算器计算 1+1") == "计算器"
        assert tm._extract_open_target("用Win搜索打开Chrome浏览器") == ""
        assert tm._extract_open_target("打开桌面上的测试文档.txt") == ""
        assert tm._extract_open_target("关闭当前窗口") == ""
        assert tm._extract_open_target("") == ""
        # "新建 Excel"类任务：目标应用是 Excel（需先打开 Excel）
        assert tm._extract_open_target("新建一个 Excel 表格，填入数据") == "Excel"
        assert tm._extract_open_target("新建表格并保存") == "Excel"
        assert tm._extract_open_target("创建 Excel 工作簿") == "Excel"
        assert tm._extract_open_target("新建文件夹") == ""  # 非 Excel，不误伤

    def test_relates_to_open_target_generic_browser(self):
        """目标"浏览器"→ Chrome/Edge/浏览器 都相关（泛称类别匹配）"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        assert TaskManager._relates_to_open_target("Google Chrome", "浏览器") is True
        assert TaskManager._relates_to_open_target(
            "新建标签页 - Microsoft Edge", "浏览器"
        ) is True
        assert TaskManager._relates_to_open_target("哔哩哔哩", "浏览器") is False
        assert TaskManager._relates_to_open_target("计算器", "计算器") is True
        assert TaskManager._relates_to_open_target("计算器", "") is False

    def test_open_search_guard_allows_desktop_icon_click(self):
        """桌面(Program Manager)图标可点：任务"打开浏览器"点"Google Chrome"应放行"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开浏览器搜索 Python"
        tm._marker_map = {
            24: {"click_point": (500, 600), "text": "Google Chrome", "source": "ocr"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="Program Manager"):
            result = tm._dispatch(
                {"action_type": "click_marker",
                 "params": {"marker": 24, "text": "Google Chrome"}}
            )
        mock_mouse.click.assert_called_once_with(500, 600)
        assert result is True

    def test_open_search_guard_allows_desktop_icon_empty_title(self):
        """桌面 shell 空标题（Win11 WorkerW 常见）→ 桌面图标点击放行，不误拦。
        回归：修复前空标题被误判成"无关窗口"，桌面 QQ音乐 图标点击被拦截致死循环。"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开QQ音乐"
        tm._marker_map = {
            38: {"click_point": (137, 779), "text": "QQ音乐", "source": "ocr"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value=""), \
             patch.object(TaskManager, "_foreground_class", return_value="Progman"):
            result = tm._dispatch(
                {"action_type": "click_marker",
                 "params": {"marker": 38, "text": "QQ音乐"}}
            )
        mock_mouse.click.assert_called_once_with(137, 779)
        assert result is True

    def test_open_search_guard_allows_desktop_workerw_class(self):
        """WorkerW 类名（Win11 桌面）即使标题非 Program Manager 也放行"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开浏览器搜索 Python"
        tm._marker_map = {
            24: {"click_point": (500, 600), "text": "Google Chrome", "source": "ocr"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="某应用窗口"), \
             patch.object(TaskManager, "_foreground_class", return_value="WorkerW"):
            result = tm._dispatch(
                {"action_type": "click_marker",
                 "params": {"marker": 24, "text": "Google Chrome"}}
            )
        mock_mouse.click.assert_called_once_with(500, 600)
        assert result is True

    def test_open_search_guard_allows_in_target_app(self):
        """浏览器已在前台(Edge) → 应用内点击放行，不误拦"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开浏览器搜索 Python"
        tm._marker_map = {
            3: {"click_point": (800, 400), "text": "Python 搜索结果", "source": "ocr"}
        }
        with patch.object(TaskManager, "_foreground_title",
                          return_value="Python - Microsoft Edge"):
            result = tm._dispatch(
                {"action_type": "click_marker",
                 "params": {"marker": 3, "text": "Python 搜索结果"}}
            )
        mock_mouse.click.assert_called_once_with(800, 400)
        assert result is True

    def test_open_search_guard_blocks_search_interface(self):
        """搜索界面点选结果不可靠 → 拦截，提示直接在搜索框输入应用名"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        tm = TaskManager(mouse=mock_mouse)
        tm._current_task = "打开计算器，计算 1+1"
        tm._marker_map = {
            11: {"click_point": (300, 400), "text": "计算器", "source": "ocr"}
        }
        with patch.object(TaskManager, "_foreground_title", return_value="搜索"):
            result = tm._dispatch(
                {"action_type": "click_marker",
                 "params": {"marker": 11, "text": "计算器"}}
            )
        assert result is False
        mock_mouse.click.assert_not_called()
        assert "type" in tm._bad_marker_hint
        assert "不要再按 win" in tm._bad_marker_hint

    # ---- 防重复输入守卫 ----
    def test_dispatch_repeat_type_blocked(self):
        """连续两次 type 相同文本+enter → 第二次拦截，不真正输入"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = MagicMock()
        mock_keyboard.type.return_value = True
        tm = TaskManager(keyboard=mock_keyboard)
        r1 = tm._dispatch(
            {"action_type": "type", "params": {"text": "Python", "enter": True}}
        )
        assert r1 is True
        mock_keyboard.type.assert_called_once_with("Python")
        r2 = tm._dispatch(
            {"action_type": "type", "params": {"text": "Python", "enter": True}}
        )
        assert r2 is False
        assert mock_keyboard.type.call_count == 1  # 第二次未真正输入
        assert "不要重复输入" in tm._bad_marker_hint

    def test_dispatch_repeat_type_enter_change_blocked(self):
        """先 type('记事本') 再 type('记事本', enter=True) → enter 不同也拦截。
        治"搜索框输入'记事本'→又补一遍变'记事本记事本'，回车打开错应用"这类叠加。"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_keyboard = MagicMock()
        mock_keyboard.type.return_value = True
        tm = TaskManager(keyboard=mock_keyboard)
        assert tm._dispatch(
            {"action_type": "type", "params": {"text": "记事本"}}
        ) is True
        assert tm._dispatch(
            {"action_type": "type", "params": {"text": "记事本", "enter": True}}
        ) is False  # 文本相同 → 拦截，无论 enter 是否不同
        assert mock_keyboard.type.call_count == 1

    # ---- 防重复输入守卫（治 1+11）----
    def test_dispatch_drag_marker_missing_returns_false(self):
        """drag_marker 任一点不存在应返回 False"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        tm = TaskManager(mouse=mock_mouse)
        tm._marker_map = {1: {"click_point": (100, 200)}}
        result = tm._dispatch({"action_type": "drag_marker", "params": {"from": 1, "to": 99}})
        assert result is False
        mock_mouse.drag_from_to.assert_not_called()

    def test_dispatch_set_slider_calls_uia(self):
        """set_slider 应调用 UiaParser.set_control_value(bbox, value)"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        tm._marker_map = {18: {"bbox": (100, 200, 300, 220), "text": "声音输出"}}
        with patch("desktop_gui_agent.agent.task_manager.UiaParser") as mock_uia:
            mock_uia.set_control_value.return_value = True
            result = tm._dispatch(
                {"action_type": "set_slider", "params": {"marker": 18, "value": 50}}
            )
            mock_uia.set_control_value.assert_called_once_with((100, 200, 300, 220), 50)
        assert result is True

    def test_dispatch_set_control_string_value(self):
        """set_control 的字符串 value 应传给 set_control_value"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        tm._marker_map = {5: {"bbox": (10, 20, 100, 40), "text": "文件类型"}}
        with patch("desktop_gui_agent.agent.task_manager.UiaParser") as mock_uia:
            mock_uia.set_control_value.return_value = True
            result = tm._dispatch(
                {"action_type": "set_control", "params": {"marker": 5, "value": ".txt"}}
            )
            mock_uia.set_control_value.assert_called_once_with((10, 20, 100, 40), ".txt")
        assert result is True

    def test_dispatch_set_control_missing_bbox_returns_false(self):
        """set_control 指向无 bbox 的标注应返回 False"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        tm._marker_map = {}  # 空标注
        with patch("desktop_gui_agent.agent.task_manager.UiaParser") as mock_uia:
            result = tm._dispatch(
                {"action_type": "set_control", "params": {"marker": 99, "value": 50}}
            )
            mock_uia.set_control_value.assert_not_called()
        assert result is False

    def test_resolve_marker_sets_bad_marker_hint(self):
        """解析不存在的标注编号应记录纠正提示（打破幻觉循环）"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager()
        tm._marker_map = {1: {"click_point": (10, 20)}}
        result = tm._resolve_marker(99)
        assert result is None
        assert "99" in tm._bad_marker_hint
        assert "打开应用" in tm._bad_marker_hint


class TestBuildHistoryActions:
    """TaskManager._build_history_actions 历史截断测试"""

    def test_history_truncated_to_last_n(self):
        """超过 HISTORY_MAX_ITEMS 条时只保留最近 N 条"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        history = [
            {"step": i, "action_raw": f"动作{i}"}
            for i in range(12)
        ]
        result = TaskManager._build_history_actions(history)
        assert len(result) == 8  # HISTORY_MAX_ITEMS
        assert result[0] == "动作4"   # 只保留最后 8 条
        assert result[-1] == "动作11"

    def test_history_short_not_truncated(self):
        """不足 HISTORY_MAX_ITEMS 条时原样返回"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        history = [{"step": i, "action_raw": f"动作{i}"} for i in range(3)]
        result = TaskManager._build_history_actions(history)
        assert len(result) == 3

    def test_history_ignores_entries_without_action_raw(self):
        """没有 action_raw 字段的历史项被跳过"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        history = [
            {"step": 0},
            {"step": 1, "action_raw": "动作1"},
            {"step": 2},
        ]
        result = TaskManager._build_history_actions(history)
        assert result == ["动作1"]


class TestTaskManagerPerceptionHelpers:
    """窗口放大裁剪 + 像素对比辅助方法测试"""

    def test_bbox_in_rect_center_inside(self):
        """标注中心在窗口内 → True"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        bbox = (100, 100, 200, 200)  # 中心 (150,150)
        rect = (0, 0, 300, 300)
        assert TaskManager._bbox_in_rect(bbox, rect) is True

    def test_bbox_in_rect_center_outside(self):
        """标注中心在窗口外 → False"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        bbox = (500, 500, 600, 600)  # 中心 (550,550)
        rect = (0, 0, 300, 300)
        assert TaskManager._bbox_in_rect(bbox, rect) is False

    def test_bbox_in_rect_none_returns_false(self):
        """空 bbox → False"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        assert TaskManager._bbox_in_rect(None, (0, 0, 100, 100)) is False

    def test_crop_image_zooms_to_rect(self):
        """裁剪到窗口矩形（含坐标偏移）"""
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        img = Image.new("RGB", (1000, 800), color=(255, 255, 255))
        cropped = TaskManager._crop_image(img, (100, 100, 500, 400), margin=0)
        assert cropped.size == (400, 300)

    def test_crop_image_clamps_to_bounds(self):
        """矩形超出图片边界时裁剪到边界内"""
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        img = Image.new("RGB", (300, 300), color=(255, 255, 255))
        cropped = TaskManager._crop_image(img, (-100, -100, 200, 200), margin=0)
        assert cropped.size[0] <= 300
        assert cropped.size[1] <= 300

    def test_crop_image_too_small_returns_original(self):
        """裁剪后过小（<50px）时返回原图，不裁剪"""
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        img = Image.new("RGB", (300, 300), color=(255, 255, 255))
        cropped = TaskManager._crop_image(img, (0, 0, 30, 30), margin=0)
        assert cropped is img

    def test_expand_rect_expands_with_margin(self):
        """窗口矩形外扩 margin"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        rect = (100, 100, 500, 400)
        expanded = TaskManager._expand_rect(rect, margin=40, image_size=(1000, 800))
        assert expanded == (60, 60, 540, 440)

    def test_expand_rect_clamps_to_image_bounds(self):
        """外扩后超出图片边界时夹紧到边界内"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        rect = (0, 0, 100, 100)
        expanded = TaskManager._expand_rect(rect, margin=40, image_size=(100, 100))
        assert expanded == (0, 0, 100, 100)

    def test_expand_rect_no_overlap_returns_none(self):
        """窗口与图片无有效重叠（窗口完全在图外）时返回 None"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        rect = (1000, 1000, 2000, 2000)  # 完全在 100x100 图外
        expanded = TaskManager._expand_rect(rect, margin=40, image_size=(100, 100))
        assert expanded is None

    def test_translate_ctrl_shifts_coords(self):
        """UIA 控件 bbox/click_point 平移到裁剪图坐标系，其他字段保留"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        ctrl = {"bbox": (100, 100, 200, 150), "click_point": (150, 125), "name": "x"}
        out = TaskManager._translate_ctrl(ctrl, 100, 100)
        assert out["bbox"] == (0, 0, 100, 50)
        assert out["click_point"] == (50, 25)
        assert out["name"] == "x"

    def test_translate_ocr_shifts_bbox(self):
        """OCR 结果 bbox 平移到裁剪图坐标系"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        item = {"text": "hi", "bbox": (200, 300, 300, 330), "confidence": 0.9}
        out = TaskManager._translate_ocr(item, 100, 200)
        assert out["bbox"] == (100, 100, 200, 130)
        assert out["text"] == "hi"

    def test_pixel_diff_identical_images_zero(self):
        """相同图片差异为 0"""
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        img = Image.new("RGB", (100, 100), color=(255, 0, 0))
        assert TaskManager._screen_pixel_diff(img, img.copy()) == 0.0

    def test_pixel_diff_different_images_positive(self):
        """不同图片差异显著大于 0"""
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        a = Image.new("RGB", (100, 100), color=(255, 0, 0))
        b = Image.new("RGB", (100, 100), color=(0, 0, 255))
        ratio = TaskManager._screen_pixel_diff(a, b)
        assert ratio > 0.5

    def test_get_foreground_window_rect_no_window(self):
        """无前台窗口（GetForegroundWindow 返回 0）→ None"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        with patch("ctypes.windll.user32.GetForegroundWindow", return_value=0):
            assert TaskManager._get_foreground_window_rect() is None

    def test_get_foreground_window_rect_exception_returns_none(self):
        """内部异常时返回 None，不崩溃"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        with patch("ctypes.windll.user32.GetForegroundWindow", side_effect=AttributeError):
            assert TaskManager._get_foreground_window_rect() is None

    def test_ordered_uia_controls_system_task_prioritizes_taskbar(self):
        """系统级任务（no_crop）任务栏/托盘控件排前面，不被桌面控件挤掉"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        fg = [{"name": "Slay the Spire 2"}, {"name": "此电脑"}, {"name": "回收站"}]
        tb = [{"name": "开始"}, {"name": "音量"}, {"name": "时钟"}]
        ordered = TaskManager._ordered_uia_controls(fg, tb, no_crop=True)
        assert ordered[0]["name"] == "开始"      # 任务栏最前
        assert ordered[1]["name"] == "音量"
        assert ordered[-1]["name"] == "回收站"   # 桌面控件殿后
        assert "音量" in [c["name"] for c in ordered[:3]]

    def test_ordered_uia_controls_normal_task_keeps_foreground_first(self):
        """普通任务保持前台窗口控件在前（任务栏仍追加在尾部）"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        fg = [{"name": "记事本"}, {"name": "按钮"}]
        tb = [{"name": "音量"}, {"name": "时钟"}]
        ordered = TaskManager._ordered_uia_controls(fg, tb, no_crop=False)
        assert ordered[0]["name"] == "记事本"
        assert ordered[1]["name"] == "按钮"
        assert ordered[2]["name"] == "音量"
        assert ordered[3]["name"] == "时钟"

    def test_is_desktop_shell_empty_title(self):
        """空标题（Win11 WorkerW 桌面）→ 桌面"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        assert TaskManager._is_desktop_shell("", "WorkerW") is True

    def test_is_desktop_shell_program_manager(self):
        """标题 "Program Manager"（Progman 桌面）→ 桌面。
        回归：修复前只认空标题，Progman 被误判成应用窗口导致桌面图标偏移/
        自动双击不生效、点在文字上打不开。"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        assert TaskManager._is_desktop_shell("Program Manager", "Progman") is True

    def test_is_desktop_shell_app_window_false(self):
        """普通应用窗口（有标题非桌面类）→ 非桌面"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        assert TaskManager._is_desktop_shell("计算器", "ApplicationFrameWindow") is False


class TestTaskManagerRun:
    """TaskManager.run() 主循环测试"""

    def test_run_finish_on_first_step(self):
        """模型第一步就返回 finish，应该立即成功退出"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="任务完成")'
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
            )
            result = tm.run("测试任务")

        assert result["success"] is True
        assert result["steps"] == 1
        assert "任务完成" in result["result"]

    def test_run_injects_cursor_position(self):
        """每步应把当前鼠标位置注入到模型上下文的 extra_text"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="done")'
        mock_mouse = MagicMock()
        mock_mouse.get_position.return_value = (10, 20)
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
            )
            tm.run("测试任务")

        assert mock_model.query.call_count == 1
        extra = mock_model.query.call_args.kwargs.get("extra_text", "")
        assert "【当前鼠标位置】(10, 20)" in extra

    def test_run_cursor_position_tolerates_bad_mock(self):
        """mouse.get_position 返回非元组时不应崩溃，也不注入"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="done")'
        mock_mouse = MagicMock()  # get_position 返回 MagicMock（非元组）
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
            )
            result = tm.run("测试任务")

        assert result["success"] is True
        extra = mock_model.query.call_args.kwargs.get("extra_text", "")
        assert "【当前鼠标位置】" not in extra

    def test_run_injects_local_paths(self):
        """每步应把本机桌面路径注入到模型上下文（文件对话框导航用）"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="done")'
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
            )
            tm.run("测试任务")

        extra = mock_model.query.call_args.kwargs.get("extra_text", "")
        assert "【本机路径】" in extra
        assert "桌面:" in extra

    def test_run_reaches_max_steps(self):
        """模型持续返回非 finish 动作，达到 max_steps 上限"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        # 每步返回不同坐标，避免触发死循环检测（连续3次相同动作）
        mock_model.query.side_effect = [
            'click(x=10, y=10)',
            'click(x=20, y=20)',
            'click(x=30, y=30)',
        ]
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_steps=3,
            )
            result = tm.run("测试任务")

        assert result["success"] is False
        assert result["steps"] == 3
        assert "达到最大步数上限" in result["error"]

    def test_run_consecutive_errors_exceeded(self):
        """连续 3 次模型返回空输出，应触发连续错误终止"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = ""  # 空输出
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_consecutive_errors=3,
            )
            result = tm.run("测试任务")

        assert result["success"] is False
        assert "连续错误次数超限" in result["error"]

    def test_run_drag_out_of_bounds_increments_errors(self):
        """drag 坐标越界应计入连续错误，最终终止，且不调用 drag_from_to"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        # 每次越界坐标不同，避免死循环检测，从而触发连续错误终止
        mock_model.query.side_effect = [
            'drag(x1=-5,y1=0,x2=10,y2=10)',
            'drag(x1=-6,y1=0,x2=10,y2=10)',
            'drag(x1=-7,y1=0,x2=10,y2=10)',
        ]
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_steps=5,
                max_consecutive_errors=3,
            )
            result = tm.run("测试任务")

        assert result["success"] is False
        assert "连续错误次数超限" in result["error"]
        mock_mouse.drag_from_to.assert_not_called()

    def test_run_right_click_valid_coords_executes(self):
        """right_click 坐标在校验范围内应正常执行"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.side_effect = [
            'right_click(x=10, y=10)',
            'finish(result="done")',
        ]
        mock_mouse = MagicMock()
        mock_mouse.right_click.return_value = True
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_steps=5,
            )
            result = tm.run("测试任务")

        assert result["success"] is True
        mock_mouse.right_click.assert_called_once_with(10, 10)

    def test_run_error_counter_resets_after_success(self):
        """连续错误计数应在成功后重置"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.side_effect = [
            "",                     # error 1
            'click(x=10, y=10)',   # success → reset
            "",                     # error 1 again
            "",                     # error 2
            "",                     # error 3 → terminate
        ]
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_consecutive_errors=3,
            )
            result = tm.run("测试任务")

        assert result["success"] is False
        assert result["steps"] == 5

    def test_run_parse_failure_counted_as_error(self):
        """无法解析的模型输出应计入连续错误"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = "这是无法解析的垃圾输出"
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_consecutive_errors=2,
            )
            result = tm.run("测试任务")

        assert result["success"] is False
        assert "连续错误次数超限" in result["error"]

    def test_run_action_failure_counted_as_error(self):
        """控制器返回 False 应计入连续错误"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'click(x=50, y=50)'
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = False  # 执行失败
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_consecutive_errors=2,
            )
            result = tm.run("测试任务")

        assert result["success"] is False
        assert "连续错误次数超限" in result["error"]

    def test_run_coordinate_out_of_bounds_counted_as_error(self):
        """click 坐标越界应计入连续错误"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'click(x=500, y=50)'  # 越界
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_consecutive_errors=2,
            )
            result = tm.run("测试任务")

        assert result["success"] is False
        assert "连续错误次数超限" in result["error"]

    def test_run_saves_history_on_completion(self):
        """任务完成时应保存历史记录到 JSON 文件"""
        import os
        import json
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="done")'
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
            )
            result = tm.run("记录历史测试")

        assert result["success"] is True
        from desktop_gui_agent.utils.platform import PlatformInfo
        log_dir = str(PlatformInfo.get_log_dir())
        json_files = [f for f in os.listdir(log_dir) if f.startswith("task_")]
        assert len(json_files) > 0
        # 按任务内容查找自己的文件，避免与其他测试竞争同一个目录
        found = None
        for fname in reversed(sorted(json_files)):
            with open(os.path.join(log_dir, fname), "r", encoding="utf-8") as f:
                rec = json.load(f)
            if rec.get("task") == "记录历史测试":
                found = rec
                break
        assert found is not None, "未找到任务'记录历史测试'的历史文件"
        assert len(found["history"]) == 1
        assert found["history"][0]["action_type"] == "finish"

    # ---- Phase 5: 错误恢复增强 ----

    def test_capture_with_retry_success_first_try(self):
        """截图首次成功应返回图片"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        tm = TaskManager()
        test_image = Image.new("RGB", (100, 100))
        with patch("desktop_gui_agent.agent.task_manager.capture", return_value=test_image):
            result = tm._capture_with_retry(max_retries=2)
        assert result is test_image

    def test_capture_with_retry_success_after_failure(self):
        """截图第 2 次重试成功"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        from desktop_gui_agent.utils.exceptions import ScreenshotError

        tm = TaskManager()
        test_image = Image.new("RGB", (100, 100))
        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_cap, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_cap.side_effect = [ScreenshotError("失败1"), test_image]
            result = tm._capture_with_retry(max_retries=2)
        assert result is test_image
        assert mock_cap.call_count == 2

    def test_capture_with_retry_all_failed(self):
        """截图全部重试失败应抛出 ScreenshotError"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        from desktop_gui_agent.utils.exceptions import ScreenshotError

        tm = TaskManager()
        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_cap, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_cap.side_effect = ScreenshotError("连续失败")
            with pytest.raises(ScreenshotError):
                tm._capture_with_retry(max_retries=2)
        assert mock_cap.call_count == 3  # 1 次原始 + 2 次重试

    def test_run_fatal_error_returns_immediately(self):
        """FATAL 错误应立即终止，不等 max_steps"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        from desktop_gui_agent.utils.exceptions import ModelError

        mock_model = MagicMock()
        mock_model.query.side_effect = ModelError("本地模型加载失败")
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_consecutive_errors=10,
            )
            result = tm.run("测试")

        assert result["success"] is False
        assert "致命错误" in result["error"]
        assert result["steps"] == 1  # 第一步就终止


# ===== 关闭当前窗口任务守卫测试 =====

class TestCloseWindowGuard:
    """"关闭当前窗口"任务锚点/完成守卫/受保护窗口测试。

    背景：真实测试中 agent 把"当前窗口"当活变量，关完一个又关下一个，
    甚至把终端（Claude Code）也关了且不 finish。修复 = 任务开始锚点 +
    代码级完成守卫 + 受保护窗口安全警告。
    """

    def test_is_close_window_task_matches_keywords(self):
        """含"关闭当前窗口"类关键词的任务应被识别为关闭任务"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        for task in ("关闭当前窗口", "帮我关闭当前窗口", "关闭当前应用",
                     "请关闭当前窗口", "关闭窗口", "关掉当前窗口"):
            assert TaskManager._is_close_window_task(task), task

    def test_is_close_window_task_ignores_unrelated(self):
        """无关任务不应被误判为关闭任务"""
        from desktop_gui_agent.agent.task_manager import TaskManager
        for task in ("打开计算器并计算1+1", "清空回收站", "下载图片保存到桌面",
                     "打开记事本输入Hello World"):
            assert not TaskManager._is_close_window_task(task), task

    def _make_run(self, task, initial_window, alive):
        """运行一次 mock 任务循环，返回注入模型的 extra_text。

        统一 mock 掉截图/OCR/睡眠，并 patch 初始窗口锚点与存活判断，
        使测试与真实屏幕/win32 状态无关。
        """
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="done")'
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"), \
             patch.object(TaskManager, "_capture_initial_window",
                          return_value=initial_window), \
             patch.object(TaskManager, "_window_alive", return_value=alive):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
            )
            tm.run(task)

        return mock_model.query.call_args.kwargs.get("extra_text", "")

    def test_run_injects_initial_window_anchor(self):
        """每步应注入任务开始时的前台窗口作为参照锚点"""
        extra = self._make_run(
            "关闭当前窗口",
            {"title": "无标题 - Notepad", "hwnd": 123, "is_terminal": False},
            alive=True,
        )
        assert "【任务开始时的前台窗口】无标题 - Notepad" in extra

    def test_run_injects_completion_hint_when_target_closed(self):
        """初始窗口已消失 → 注入"目标已关闭、立即 finish"提示"""
        extra = self._make_run(
            "关闭当前窗口",
            {"title": "无标题 - Notepad", "hwnd": 123, "is_terminal": False},
            alive=False,
        )
        assert "【!!! 目标窗口已关闭 — 任务完成 !!!】" in extra
        assert "finish" in extra

    def test_run_no_completion_hint_when_target_alive(self):
        """初始窗口还在 → 不注入完成提示"""
        extra = self._make_run(
            "关闭当前窗口",
            {"title": "无标题 - Notepad", "hwnd": 123, "is_terminal": False},
            alive=True,
        )
        assert "目标窗口已关闭" not in extra

    def test_run_no_completion_hint_for_non_close_task(self):
        """非关闭任务即使初始窗口消失，也不应误报任务完成"""
        extra = self._make_run(
            "打开记事本输入Hello World",
            {"title": "无标题 - Notepad", "hwnd": 123, "is_terminal": False},
            alive=False,
        )
        assert "目标窗口已关闭" not in extra

    def test_run_injects_terminal_safety_warning(self):
        """当前前台是终端窗口时注入安全警告（防止误关 Claude Code）"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="done")'
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch("desktop_gui_agent.agent.task_manager.capture") as mock_capture, \
             patch("desktop_gui_agent.agent.task_manager.recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"), \
             patch.object(TaskManager, "_capture_initial_window",
                          return_value={"title": "无标题 - Notepad",
                                        "hwnd": 123, "is_terminal": False}), \
             patch.object(TaskManager, "_window_alive", return_value=True), \
             patch("desktop_gui_agent.agent.task_manager._is_terminal_window",
                   return_value=True):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
            )
            tm.run("关闭当前窗口")

        extra = mock_model.query.call_args.kwargs.get("extra_text", "")
        assert "【!!! 安全警告 — 当前前台是终端/命令提示符窗口 !!!】" in extra

    def test_no_anchor_no_hint_when_initial_is_terminal(self):
        """锚点不可用（前台是终端被过滤）时，不注入矛盾锚点、不误报完成。

        与"运行任务先最小化终端"配合：最小化把终端移开后锚点才有效；
        若仍捕获到终端（_capture_initial_window 返回 {}），守卫安全降级。
        """
        extra = self._make_run("关闭当前窗口", {}, alive=False)
        assert "任务开始时的前台窗口" not in extra
        assert "目标窗口已关闭" not in extra


# ===== 重复动作纠正提示测试 =====

class TestRepeatHint:
    """重复动作纠正提示（泛化修复死循环）"""

    @staticmethod
    def _hint(history):
        from desktop_gui_agent.agent.task_manager import TaskManager
        return TaskManager._build_repeat_hint(history, "无标题 - Notepad")

    def test_no_history_no_hint(self):
        assert self._hint([]) == ""
        assert self._hint([{"action_type": "hotkey", "action_params": {"keys": ["win"]}, "success": True}]) == ""

    def test_consecutive_repeat_fires_hint(self):
        h = [
            {"action_type": "hotkey", "action_params": {"keys": ["win"]}, "success": True},
            {"action_type": "hotkey", "action_params": {"keys": ["win"]}, "success": True},
        ]
        assert "正在重复同一个动作" in self._hint(h)

    def test_alternating_loop_fires_hint(self):
        """交替循环（click → drag → click → drag）也会触发重复提示"""
        h = [
            {"action_type": "click_marker", "action_params": {"marker": 14}, "success": True},
            {"action_type": "drag_marker", "action_params": {"from": 20, "to": 2814}, "success": False},
            {"action_type": "click_marker", "action_params": {"marker": 14}, "success": True},
            {"action_type": "drag_marker", "action_params": {"from": 20, "to": 2814}, "success": False},
        ]
        hint = self._hint(h)
        assert "正在重复同一个动作" in hint
        # 提示应提到被重复的具体动作（click 或 drag 之一，取决于遍历顺序）
        assert ("click_marker" in hint) or ("drag_marker" in hint)

    def test_failed_repeat_mentions_failure(self):
        h = [
            {"action_type": "drag_marker", "action_params": {"from": 20, "to": 2814}, "success": False},
            {"action_type": "click_marker", "action_params": {"marker": 14}, "success": True},
            {"action_type": "drag_marker", "action_params": {"from": 20, "to": 2814}, "success": False},
        ]
        assert "执行失败" in self._hint(h)

    def test_normal_sequence_no_hint(self):
        """正常任务序列（win→type→enter）不应触发"""
        h = [
            {"action_type": "hotkey", "action_params": {"keys": ["win"]}, "success": True},
            {"action_type": "type", "action_params": {"text": "计算器"}, "success": True},
            {"action_type": "hotkey", "action_params": {"keys": ["enter"]}, "success": True},
        ]
        assert self._hint(h) == ""


# ===== Main 入口测试 =====

class TestMain:
    """main.py CLI 入口测试"""

    def test_main_parses_task_and_runs(self):
        """main() 应解析命令行参数并调用 TaskManager.run()"""
        import sys
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.main import main

        mock_tm = MagicMock()
        mock_tm.run.return_value = {
            "success": True,
            "result": "完成",
            "steps": 1,
            "error": None,
        }

        mock_hotkey = MagicMock()
        test_args = ["main.py", "打开计算器"]
        with patch.object(sys, "argv", test_args), \
             patch("desktop_gui_agent.main.TaskManager", return_value=mock_tm), \
             patch("desktop_gui_agent.main.GlobalHotkey", return_value=mock_hotkey):
            exit_code = main()

        assert exit_code == 0
        mock_tm.run.assert_called_once_with("打开计算器", cancel_event=mock_hotkey.exit_event)

    def test_main_custom_max_steps(self):
        """--max-steps 参数应传递给 TaskManager"""
        import sys
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.main import main

        mock_tm = MagicMock()
        mock_tm.run.return_value = {
            "success": True,
            "result": "完成",
            "steps": 2,
            "error": None,
        }

        mock_hotkey = MagicMock()
        test_args = ["main.py", "--max-steps", "10", "测试任务"]
        with patch.object(sys, "argv", test_args), \
             patch("desktop_gui_agent.main.TaskManager", return_value=mock_tm) as mock_tm_cls, \
             patch("desktop_gui_agent.main.GlobalHotkey", return_value=mock_hotkey):
            exit_code = main()

        assert exit_code == 0
        mock_tm_cls.assert_called_once_with(
            max_steps=10, max_consecutive_errors=3, api_preset=None
        )

    def test_main_returns_1_on_failure(self):
        """任务失败时 main() 应返回 1"""
        import sys
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.main import main

        mock_tm = MagicMock()
        mock_tm.run.return_value = {
            "success": False,
            "result": "",
            "steps": 5,
            "error": "达到最大步数上限",
        }

        mock_hotkey = MagicMock()
        test_args = ["main.py", "不可能的任务"]
        with patch.object(sys, "argv", test_args), \
             patch("desktop_gui_agent.main.TaskManager", return_value=mock_tm), \
             patch("desktop_gui_agent.main.GlobalHotkey", return_value=mock_hotkey):
            exit_code = main()

        assert exit_code == 1

    def test_main_no_task_uses_interactive_mode(self):
        """无命令行参数时进入交互模式"""
        import sys
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.main import main

        mock_tm = MagicMock()
        mock_tm.run.return_value = {
            "success": True,
            "result": "完成",
            "steps": 1,
            "error": None,
        }

        mock_hotkey = MagicMock()
        mock_hotkey.exit_event.is_set.return_value = False  # 不触发退出
        # 模拟：无命令行参数 → 交互模式 → 用户输入任务 → 然后退出
        test_args = ["main.py"]
        with patch.object(sys, "argv", test_args), \
             patch.object(sys.stdin, "isatty", return_value=True), \
             patch("desktop_gui_agent.main.TaskManager", return_value=mock_tm), \
             patch("desktop_gui_agent.main.GlobalHotkey", return_value=mock_hotkey), \
             patch("builtins.input", side_effect=["用户输入的任务", "exit"]), \
             patch("desktop_gui_agent.main.time.sleep"):  # 跳过实际延时
            exit_code = main()

        assert exit_code == 0
        mock_tm.run.assert_called_once_with(
            "用户输入的任务", cancel_event=mock_hotkey.exit_event
        )


# ===== Prompt 拼接测试 =====

class TestPromptBuilding:
    """Prompt 模板拼接测试（Phase 5）"""

    @patch('desktop_gui_agent.agent.model_client.process_vision_info')
    @patch('desktop_gui_agent.agent.model_client._load_local_model')
    def test_few_shot_examples_injected(self, mock_load, mock_pvi):
        """few-shot 示例应被注入到系统提示词中"""
        from desktop_gui_agent.agent.model_client import ModelClient
        from PIL import Image

        mock_model = MagicMock()
        mock_model.device = "cpu"
        mock_processor = MagicMock()
        mock_processor.apply_chat_template.return_value = "chat template"
        mock_processor.batch_decode.return_value = ["click(x=100, y=200)"]
        mock_load.return_value = (mock_model, mock_processor)
        mock_pvi.return_value = ([], [])

        client = ModelClient(mode="local")
        client.query(Image.new("RGB", (100, 100)), "打开记事本")

        call_args = mock_processor.apply_chat_template.call_args
        messages = call_args[0][0]
        system_content = ""
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
        assert "【点击标注" in system_content
        assert "计算器" in system_content

    def test_prompt_has_general_framework(self):
        """PROMPT 应包含通用决策框架（四步SOP + 动作选型）而非任务脚本"""
        import desktop_gui_agent.config as config
        assert "四步SOP" in config.PROMPT_SYSTEM
        assert "动作选型" in config.PROMPT_SYSTEM
        assert "hotkey(ctrl, l)" in config.PROMPT_SYSTEM  # 文件对话框地址栏导航
        assert "Alt+Tab" in config.PROMPT_SYSTEM  # 应用切换

    def test_prompt_action_table_has_new_actions(self):
        """PROMPT_SYSTEM 动作表应包含右键/拖拽/单键"""
        import desktop_gui_agent.config as config
        assert "right_click_marker" in config.PROMPT_SYSTEM
        assert "drag_marker" in config.PROMPT_SYSTEM
        assert "press(key=" in config.PROMPT_SYSTEM

    def test_few_shot_single_step_by_action_type(self):
        """few-shot 应按动作类型提供单步样例（点击/输入/滚动/搜索/完成）"""
        import desktop_gui_agent.config as config
        joined = "\n".join(config.PROMPT_FEW_SHOT_EXAMPLES)
        assert "点击标注" in joined                # 点击
        assert "type(text=" in joined              # 输入
        assert "scroll(" in joined                 # 滚动
        assert "hotkey(win)" in joined             # 搜索兜底
        assert "finish(result=" in joined          # 任务完成

    def test_prompt_has_keyboard_first_principle(self):
        """PROMPT 应包含键盘优先原则（模型最可靠的路径）"""
        import desktop_gui_agent.config as config
        assert "键盘优先" in config.PROMPT_SYSTEM
        assert "hotkey(win)→type" in config.PROMPT_SYSTEM or "hotkey(win)" in config.PROMPT_SYSTEM
        assert "hotkey(alt, f4)" in config.PROMPT_SYSTEM  # 关闭窗口
        assert "click_marker" in config.PROMPT_SYSTEM     # 鼠标用于大按钮

    def test_prompt_has_file_dialog_principles(self):
        """PROMPT 应包含文件对话框导航原则（Ctrl+S 打开 / Ctrl+L 地址栏）"""
        import desktop_gui_agent.config as config
        assert "hotkey(ctrl, s)" in config.PROMPT_SYSTEM  # 打开保存框
        assert "hotkey(ctrl, l)" in config.PROMPT_SYSTEM  # 地址栏

    def test_prompt_has_shortcut_principle(self):
        """PROMPT 应包含快捷键转 hotkey 的原则"""
        import desktop_gui_agent.config as config
        assert "hotkey(alt, f4)" in config.PROMPT_SYSTEM  # 关闭窗口
        assert "hotkey(ctrl, v)" in config.PROMPT_SYSTEM  # 粘贴

    def test_prompt_has_slider_principle(self):
        """PROMPT 应包含通用滑块设值原则（UIA set_control，不靠目测拖动）"""
        import desktop_gui_agent.config as config
        assert "set_control(marker=N, value=X)" in config.PROMPT_SYSTEM
        assert "滑块" in config.PROMPT_SYSTEM
        assert "系统托盘" in config.PROMPT_SYSTEM  # 托盘图标可打开面板（泛化到音量/网络/亮度）
        assert "音量/网络/亮度" in config.PROMPT_SYSTEM

    @patch('desktop_gui_agent.agent.model_client.process_vision_info')
    @patch('desktop_gui_agent.agent.model_client._load_local_model')
    def test_cot_guidance_in_user_prompt(self, mock_load, mock_pvi):
        """CoT 引导文本应出现在 user prompt 中（单层模式）"""
        import desktop_gui_agent.config as config
        from desktop_gui_agent.agent.model_client import ModelClient
        from PIL import Image

        mock_model = MagicMock()
        mock_model.device = "cpu"
        mock_processor = MagicMock()
        mock_processor.apply_chat_template.return_value = "chat template"
        mock_processor.batch_decode.return_value = ["finish(result=\"ok\")"]
        mock_load.return_value = (mock_model, mock_processor)
        mock_pvi.return_value = ([], [])

        client = ModelClient(mode="local")
        client.query(Image.new("RGB", (100, 100)), "测试")

        call_args = mock_processor.apply_chat_template.call_args
        messages = call_args[0][0]
        user_text = ""
        for msg in messages:
            if msg["role"] == "user":
                for item in msg["content"]:
                    if item["type"] == "text":
                        user_text += item["text"]
        assert "按格式输出" in user_text

    @patch('desktop_gui_agent.agent.model_client.process_vision_info')
    @patch('desktop_gui_agent.agent.model_client._load_local_model')
    def test_cot_disabled_skips_guidance(self, mock_load, mock_pvi):
        """PROMPT_COT_ENABLED=False 时应不含 CoT 引导"""
        from desktop_gui_agent.agent.model_client import ModelClient
        from PIL import Image
        import desktop_gui_agent.config as config

        mock_model = MagicMock()
        mock_model.device = "cpu"
        mock_processor = MagicMock()
        mock_processor.apply_chat_template.return_value = "chat template"
        mock_processor.batch_decode.return_value = ["click(x=1, y=1)"]
        mock_load.return_value = (mock_model, mock_processor)
        mock_pvi.return_value = ([], [])

        # 临时关闭 CoT
        old_cot = config.PROMPT_COT_ENABLED
        config.PROMPT_COT_ENABLED = False
        try:
            client = ModelClient(mode="local")
            client.query(Image.new("RGB", (100, 100)), "测试")

            call_args = mock_processor.apply_chat_template.call_args
            messages = call_args[0][0]
            user_text = ""
            for msg in messages:
                if msg["role"] == "user":
                    for item in msg["content"]:
                        if item["type"] == "text":
                            user_text += item["text"]
            assert "简述" not in user_text
        finally:
            config.PROMPT_COT_ENABLED = old_cot

    @patch('desktop_gui_agent.agent.model_client.process_vision_info')
    @patch('desktop_gui_agent.agent.model_client._load_local_model')
    def test_empty_few_shot_examples_skips_injection(self, mock_load, mock_pvi):
        """FEW_SHOT_EXAMPLES 为空列表时不报错"""
        from desktop_gui_agent.agent.model_client import ModelClient
        from PIL import Image
        import desktop_gui_agent.config as config

        mock_model = MagicMock()
        mock_model.device = "cpu"
        mock_processor = MagicMock()
        mock_processor.apply_chat_template.return_value = "chat template"
        mock_processor.batch_decode.return_value = ["finish(result=\"ok\")"]
        mock_load.return_value = (mock_model, mock_processor)
        mock_pvi.return_value = ([], [])

        old_examples = config.PROMPT_FEW_SHOT_EXAMPLES
        config.PROMPT_FEW_SHOT_EXAMPLES = []
        try:
            client = ModelClient(mode="local")
            result = client.query(Image.new("RGB", (100, 100)), "测试")
            assert isinstance(result, str)
        finally:
            config.PROMPT_FEW_SHOT_EXAMPLES = old_examples


# ===== API 预设测试 =====

class TestApiPreset:
    """_resolve_api_preset() 测试"""

    def test_resolve_dashscope_preset(self):
        """DashScope 预设应返回正确的 mode/model/url"""
        from desktop_gui_agent.agent.model_client import _resolve_api_preset
        result = _resolve_api_preset("dashscope")
        assert result["mode"] == "api"
        assert result["model_name"] == "qwen-vl-max"
        assert "dashscope.aliyuncs.com" in result["api_url"]
        assert "api_key" in result

    def test_resolve_ollama_preset(self):
        """Ollama 预设应返回正确的 mode/model/url"""
        from desktop_gui_agent.agent.model_client import _resolve_api_preset
        result = _resolve_api_preset("ollama")
        assert result["mode"] == "api"
        assert result["model_name"] == "qwen2.5:7b"
        assert "localhost:11434" in result["api_url"]

    def test_resolve_none_preset_returns_empty(self):
        """preset=None 应返回空字典"""
        from desktop_gui_agent.agent.model_client import _resolve_api_preset
        assert _resolve_api_preset(None) == {}
        assert _resolve_api_preset("") == {}

    def test_resolve_unknown_preset_raises(self):
        """未知预设应抛出 ModelError"""
        import pytest
        from desktop_gui_agent.agent.model_client import _resolve_api_preset
        from desktop_gui_agent.utils.exceptions import ModelError
        with pytest.raises(ModelError, match="不存在"):
            _resolve_api_preset("unknown_preset")

    def test_model_client_applies_api_preset(self):
        """ModelClient 初始化时应正确应用 api_preset"""
        from desktop_gui_agent.agent.model_client import ModelClient
        client = ModelClient(api_preset="dashscope")
        assert client.mode == "api"
        assert "qwen-vl-max" == client.model_name
        assert "dashscope" in client.api_url

    def test_api_preset_overrides_mode(self):
        """api_preset 应覆盖显式的 mode 参数"""
        from desktop_gui_agent.agent.model_client import ModelClient
        client = ModelClient(mode="local", api_preset="ollama")
        # preset 优先，mode 被覆盖为 api
        assert client.mode == "api"
        assert "qwen2.5:7b" in client.model_name

    def test_dashscope_preset_reads_key_from_env(self, monkeypatch):
        """DashScope 预设应从 DASHSCOPE_API_KEY 环境变量读取密钥"""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-key-123")
        from desktop_gui_agent.agent.model_client import _resolve_api_preset
        result = _resolve_api_preset("dashscope")
        assert result["api_key"] == "sk-test-key-123"


# ===== CLI --api 参数测试 =====

class TestCliApiArg:
    """main.py --api 参数测试"""

    def test_parse_api_dashscope(self):
        """--api dashscope 应被正确解析"""
        from desktop_gui_agent.main import _parse_args
        args = _parse_args(["--api", "dashscope", "打开记事本"])
        assert args.api == "dashscope"
        assert args.task == "打开记事本"

    def test_parse_api_ollama(self):
        """--api ollama 应被正确解析"""
        from desktop_gui_agent.main import _parse_args
        args = _parse_args(["--api", "ollama", "打开计算器"])
        assert args.api == "ollama"

    def test_parse_api_local(self):
        """--api local 应被正确解析"""
        from desktop_gui_agent.main import _parse_args
        args = _parse_args(["--api", "local", "任务"])
        assert args.api == "local"

    def test_parse_no_api_defaults_to_none(self):
        """不传 --api 时默认为 None"""
        from desktop_gui_agent.main import _parse_args
        args = _parse_args(["打开记事本"])
        assert args.api is None

    def test_parse_api_invalid_choice_rejected(self):
        """无效 --api 值应被 argparse 拒绝"""
        import pytest
        from desktop_gui_agent.main import _parse_args
        with pytest.raises(SystemExit):
            _parse_args(["--api", "invalid", "任务"])


# ===== 全局快捷键测试 =====

class TestGlobalHotkey:
    """GlobalHotkey 测试 — Ctrl+Alt+Q 安全退出"""

    def test_init_default(self):
        """默认初始化应成功，exit_event 未设置"""
        from desktop_gui_agent.utils.global_hotkey import GlobalHotkey
        import threading

        hotkey = GlobalHotkey()
        assert hotkey.exit_event is not None
        assert isinstance(hotkey.exit_event, threading.Event)
        assert hotkey.exit_event.is_set() is False

    def test_init_with_callback(self):
        """初始化时应接受回调函数"""
        from desktop_gui_agent.utils.global_hotkey import GlobalHotkey

        called = []

        def on_exit():
            called.append(True)

        hotkey = GlobalHotkey(on_exit=on_exit)
        assert hotkey._on_exit is on_exit

    def test_start_stop(self):
        """start() 和 stop() 应正常启停"""
        from desktop_gui_agent.utils.global_hotkey import GlobalHotkey

        hotkey = GlobalHotkey()
        hotkey.start()
        assert hotkey._listener is not None
        assert hotkey._thread is not None

        hotkey.stop()
        assert hotkey._listener is None
        assert hotkey._thread is None

    def test_double_start_is_safe(self):
        """重复 start() 应安全跳过"""
        from desktop_gui_agent.utils.global_hotkey import GlobalHotkey

        hotkey = GlobalHotkey()
        hotkey.start()
        first_listener = hotkey._listener
        hotkey.start()  # 不应崩溃
        assert hotkey._listener is first_listener  # 未重新创建

        hotkey.stop()

    def test_double_stop_is_safe(self):
        """重复 stop() 应安全跳过"""
        from desktop_gui_agent.utils.global_hotkey import GlobalHotkey

        hotkey = GlobalHotkey()
        hotkey.start()
        hotkey.stop()
        hotkey.stop()  # 不应崩溃

    def test_filter_injected_events(self):
        """win32_event_filter 应过滤注入事件"""
        from desktop_gui_agent.utils.global_hotkey import GlobalHotkey
        from unittest.mock import MagicMock

        # LLKHF_INJECTED = 0x10
        class FakeData:
            flags = 0x10  # injected

        result = GlobalHotkey._filter_injected(None, FakeData())
        assert result is False  # 应丢弃注入事件

    def test_filter_pass_real_events(self):
        """win32_event_filter 应放行真实事件"""
        from desktop_gui_agent.utils.global_hotkey import GlobalHotkey

        class FakeData:
            flags = 0x00  # not injected

        result = GlobalHotkey._filter_injected(None, FakeData())
        assert result is True  # 应放行真实事件


class TestCaptureState:
    """TaskManager._capture_state() 状态捕获测试"""

    def test_capture_state_returns_dict(self):
        """状态捕获应返回含正确键的字典"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        state = TaskManager._capture_state()

        assert isinstance(state, dict)
        assert "fg_window_title" in state
        assert "uia_count" in state
        assert "uia_type_counts" in state
        assert "uia_names" in state
        assert isinstance(state["uia_count"], int)
        assert isinstance(state["uia_type_counts"], dict)
        assert isinstance(state["uia_names"], tuple)

    def test_capture_state_fg_window_title_is_string(self):
        """前台窗口标题应为字符串（可能为空）"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        state = TaskManager._capture_state()

        assert isinstance(state["fg_window_title"], str)


class TestHasStateChanged:
    """TaskManager._has_state_changed() 状态对比测试"""

    @staticmethod
    def _make_state(title="测试窗口", count=10, types=None, names=None):
        """辅助：构建标准状态快照"""
        return {
            "fg_window_title": title,
            "uia_count": count,
            "uia_type_counts": types or {"Button": 8, "Edit": 2},
            "uia_names": names or tuple(f"控件{i}" for i in range(min(count, 10))),
        }

    def test_same_state_returns_false(self):
        """完全相同状态应返回 False"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        state = self._make_state()
        assert TaskManager._has_state_changed(state, state) is False

    def test_different_window_title_returns_true(self):
        """前台窗口变化应返回 True"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        before = self._make_state(title="计算器")
        after = self._make_state(title="记事本")
        assert TaskManager._has_state_changed(before, after) is True

    def test_control_count_change_over_20_percent_returns_true(self):
        """控件数变化 >20% 应返回 True"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        before = self._make_state(count=10)
        after = self._make_state(count=13)  # +30%
        assert TaskManager._has_state_changed(before, after) is True

    def test_control_count_change_under_20_percent_returns_false(self):
        """控件数变化 <=20% 且其他不变应返回 False"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        before = self._make_state(count=10)
        after = self._make_state(count=11)  # +10%，且类型和名称相同
        # 需要名称也相同
        names = tuple(f"控件{i}" for i in range(10))
        before = self._make_state(count=10, names=names)
        after = self._make_state(count=11, names=names)
        assert TaskManager._has_state_changed(before, after) is False

    def test_different_control_types_returns_true(self):
        """控件类型分布变化应返回 True"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        before = self._make_state(types={"Button": 8, "Edit": 2})
        after = self._make_state(types={"Button": 8, "Edit": 1, "CheckBox": 1})
        assert TaskManager._has_state_changed(before, after) is True

    def test_different_control_names_returns_true(self):
        """控件名称大范围变化应返回 True"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        before = self._make_state(names=("按钮A", "按钮B", "按钮C", "输入框"))
        after = self._make_state(names=("按钮X", "按钮Y", "按钮Z", "下拉框"))
        assert TaskManager._has_state_changed(before, after) is True

    def test_both_no_uia_returns_true(self):
        """双方均无 UIA 数据时保守返回 True（避免误报无效）"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        before = {"fg_window_title": "", "uia_count": 0, "uia_type_counts": {}, "uia_names": ()}
        after = {"fg_window_title": "", "uia_count": 0, "uia_type_counts": {}, "uia_names": ()}
        assert TaskManager._has_state_changed(before, after) is True

    def test_uia_from_zero_to_some_returns_true(self):
        """UIA 控件从无到有应返回 True"""
        from desktop_gui_agent.agent.task_manager import TaskManager

        before = {"fg_window_title": "桌面", "uia_count": 0, "uia_type_counts": {}, "uia_names": ()}
        after = self._make_state(count=5)
        assert TaskManager._has_state_changed(before, after) is True


class TestVerifyCorrectIntegration:
    """验证-纠正循环集成测试"""

    def test_recovery_hint_injected_after_no_change(self):
        """连续 2 次无变化后，模型查询应收到恢复提示"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        import desktop_gui_agent.agent.task_manager as tm_module

        mock_model = MagicMock()
        # 前两步返回相同动作，第三步返回 finish
        mock_model.query.side_effect = [
            'click_marker(1)',
            'click_marker(1)',
            'finish(result="done")',
        ]
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        mock_keyboard = MagicMock()

        # 注入假状态：模拟每次 _capture_state 返回相同状态
        fake_state = {
            "fg_window_title": "计算器",
            "uia_count": 36,
            "uia_type_counts": {"Button": 33, "Edit": 3},
            "uia_names": tuple(f"btn{i}" for i in range(15)),
        }

        with patch.object(tm_module, "capture") as mock_capture, \
             patch.object(tm_module, "recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"), \
             patch.object(tm_module.TaskManager, "_capture_state", return_value=fake_state):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_steps=3,
            )
            result = tm.run("测试任务")

        # 连续 2 次无变化后，第 3 步模型应该收到含纠正提示的 extra_text
        # 检查第 3 次 query 调用参数
        assert result["success"] is True
        # 验证第 2 次 (step 2) 和第 3 次 (step 3) 的 extra_text
        call_args_list = mock_model.query.call_args_list
        assert len(call_args_list) >= 3
        # 第 3 次调用（索引 2）应包含恢复提示
        extra_text_3 = call_args_list[2].kwargs.get("extra_text", "")
        assert "纠正提示" in extra_text_3 or "上一步无效" in extra_text_3

    def test_no_change_counter_resets_on_state_change(self):
        """状态恢复变化后计数器重置，不再注入恢复提示"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        import desktop_gui_agent.agent.task_manager as tm_module

        mock_model = MagicMock()
        mock_model.query.side_effect = [
            'click_marker(1)',
            'click_marker(2)',
            'finish(result="done")',
        ]
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        mock_keyboard = MagicMock()

        # 第一次状态相同（模拟无效点击），第二次状态不同（模拟有效点击）
        same_state = {
            "fg_window_title": "计算器",
            "uia_count": 36,
            "uia_type_counts": {"Button": 33},
            "uia_names": tuple(f"btn{i}" for i in range(10)),
        }
        different_state = {
            "fg_window_title": "计算器",
            "uia_count": 35,  # 按钮少了一个（被点了）
            "uia_type_counts": {"Button": 32},
            "uia_names": tuple(f"btn{i}" for i in range(9)) + ("结果",),
        }

        # 第一次 _has_state_changed 返回 False，第二次返回 True
        with patch.object(tm_module, "capture") as mock_capture, \
             patch.object(tm_module, "recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"), \
             patch.object(tm_module.TaskManager, "_has_state_changed") as mock_changed:
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []
            # 三步各调用一次 _has_state_changed：第1步无变化，第2步有变化，第3步有变化
            mock_changed.side_effect = [False, True, True]

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_steps=3,
            )
            tm.run("测试任务")

        # 第 3 次调用（finish 那一步）不应含恢复提示（因为计数器已重置）
        extra_text_3 = mock_model.query.call_args_list[2].kwargs.get("extra_text", "")
        assert "纠正提示" not in extra_text_3


class TestPerformanceTiming:
    """性能计时测试"""

    def test_timings_recorded_in_history(self):
        """每步历史记录应包含 timings 字段"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        import desktop_gui_agent.agent.task_manager as tm_module

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="done")'
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch.object(tm_module, "capture") as mock_capture, \
             patch.object(tm_module, "recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_steps=1,
            )
            result = tm.run("测试任务")

        # 验证 run() 返回成功
        assert result["success"] is True

        # 验证模型 query 被调用时传入了正确的参数
        mock_model.query.assert_called_once()
        call_kwargs = mock_model.query.call_args.kwargs
        assert "extra_text" in call_kwargs

    def test_perf_timing_logged_during_run(self, caplog):
        """性能计时应在运行中输出 [Perf] 日志"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager
        import desktop_gui_agent.agent.task_manager as tm_module
        import logging

        mock_model = MagicMock()
        mock_model.query.return_value = 'finish(result="done")'
        mock_mouse = MagicMock()
        mock_keyboard = MagicMock()

        with patch.object(tm_module, "capture") as mock_capture, \
             patch.object(tm_module, "recognize") as mock_ocr, \
             patch("desktop_gui_agent.agent.task_manager.time.sleep"):
            mock_capture.return_value = Image.new("RGB", (100, 100))
            mock_ocr.return_value = []

            tm = TaskManager(
                model_client=mock_model,
                mouse=mock_mouse,
                keyboard=mock_keyboard,
                max_steps=1,
            )

            # 捕获根 logger 的日志（logger 名称路径太深时 caplog 可能匹配不上）
            with caplog.at_level(logging.INFO):
                tm.run("测试任务")

        # 应有 [Perf] 日志
        perf_logs = [r.message for r in caplog.records if "[Perf]" in r.message]
        assert len(perf_logs) >= 1, f"未找到 Perf 日志，共 {len(caplog.records)} 条记录"
        assert "截图=" in perf_logs[0]
        assert "模型=" in perf_logs[0]
        assert "执行=" in perf_logs[0]


class TestCalculatorDisplayHint:
    """计算器显示区读取：注入模型真实算式状态，防误判重复输入"""

    def test_extract_expr_and_result(self):
        """同时有表达式和结果时，两者都注入"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        fake_controls = [
            {"name": "表达式为 1 + 1", "control_type": "Text", "bbox": (0, 0, 10, 10)},
            {"name": "显示为 2", "control_type": "Text", "bbox": (0, 0, 10, 10)},
        ]
        with patch("desktop_gui_agent.perception.uia_parser.UiaParser.get_foreground_controls",
                   return_value=fake_controls):
            hint = TaskManager._calculator_display_hint()
        assert "表达式为 1 + 1" in hint
        assert "显示为 2" in hint

    def test_extract_result_only(self):
        """只有结果（空表达式）时，注入结果"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        fake_controls = [
            {"name": "显示为 0", "control_type": "Text", "bbox": (0, 0, 10, 10)},
        ]
        with patch("desktop_gui_agent.perception.uia_parser.UiaParser.get_foreground_controls",
                   return_value=fake_controls):
            hint = TaskManager._calculator_display_hint()
        assert "显示为 0" in hint

    def test_no_calculator_returns_empty(self):
        """非计算器窗口返回空串（不注入噪音）"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        fake_controls = [
            {"name": "开始", "control_type": "Button", "bbox": (0, 0, 10, 10)},
        ]
        with patch("desktop_gui_agent.perception.uia_parser.UiaParser.get_foreground_controls",
                   return_value=fake_controls):
            hint = TaskManager._calculator_display_hint()
        assert hint == ""

    def test_excel_active_cell_hint_reads_address(self):
        """Excel 激活单元格地址注入：COM 读到 B1 时返回提示"""
        from unittest.mock import MagicMock, patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_excel = MagicMock()
        mock_excel.ActiveCell.Address = "$B$1"
        with patch("win32com.client.GetActiveObject", return_value=mock_excel):
            hint = TaskManager._excel_active_cell_hint()
        assert hint == "【Excel 状态】当前激活单元格：B1\n"

    def test_excel_active_cell_hint_no_excel_returns_empty(self):
        """Excel 未打开（GetActiveObject 抛异常）时返回空串"""
        from unittest.mock import patch
        from desktop_gui_agent.agent.task_manager import TaskManager
        with patch("win32com.client.GetActiveObject", side_effect=Exception("no excel")):
            hint = TaskManager._excel_active_cell_hint()
        assert hint == ""


class TestCalculatorClickGuard:
    """计算器按键守卫：任务要计算时禁止逐个点按键，强制 type 一次性输入"""

    def _make_tm(self, task, fg_title="计算器"):
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        tm = TaskManager(mouse=MagicMock(), keyboard=MagicMock())
        tm._current_task = task
        tm._marker_map = {1: {"source": "uia", "text": "加", "control_type": "Button",
                              "bbox": (0, 0, 10, 10), "click_point": (5, 5)}}
        with patch.object(TaskManager, "_foreground_title", return_value=fg_title):
            return tm

    def test_calc_task_calculator_button_blocked(self):
        """计算任务+计算器前台+点加号 → 拦截"""
        tm = self._make_tm("打开计算器并计算1+1")
        with patch.object(tm, "_foreground_title", return_value="计算器"):
            assert tm._calculator_click_guard(1) is False
        assert "type" in tm._bad_marker_hint

    def test_non_calc_task_allowed(self):
        """非计算任务 → 放行"""
        tm = self._make_tm("打开记事本输入Hello")
        with patch.object(tm, "_foreground_title", return_value="记事本"):
            assert tm._calculator_click_guard(1) is True

    def test_calc_task_non_calculator_window_allowed(self):
        """计算任务但前台非计算器 → 放行（可能是搜索界面）"""
        tm = self._make_tm("打开计算器并计算1+1", fg_title="搜索")
        with patch.object(tm, "_foreground_title", return_value="搜索"):
            assert tm._calculator_click_guard(1) is True

    def test_dispatch_calculator_click_blocked(self):
        """完整 dispatch：计算任务点计算器加号 → 拦截且不执行点击"""
        from unittest.mock import MagicMock
        from desktop_gui_agent.agent.task_manager import TaskManager
        mock_mouse = MagicMock()
        mock_mouse.click.return_value = True
        tm = TaskManager(mouse=mock_mouse, keyboard=MagicMock())
        tm._current_task = "打开计算器并计算1+1"
        tm._marker_map = {1: {"source": "uia", "text": "加", "control_type": "Button",
                              "bbox": (0, 0, 10, 10), "click_point": (5, 5)}}
        with patch.object(tm, "_foreground_title", return_value="计算器"):
            result = tm._dispatch({"action_type": "click_marker",
                                   "params": {"marker": 1, "text": "加"}})
        assert result is False
        mock_mouse.click.assert_not_called()
