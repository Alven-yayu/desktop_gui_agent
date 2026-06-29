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

    def test_run_reaches_max_steps(self):
        """模型持续返回非 finish 动作，达到 max_steps 上限"""
        from unittest.mock import MagicMock, patch
        from PIL import Image
        from desktop_gui_agent.agent.task_manager import TaskManager

        mock_model = MagicMock()
        mock_model.query.return_value = 'click(x=50, y=50)'
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
        log_dir = os.path.join(
            os.path.dirname(__file__), "..", "desktop_gui_agent", "..", "logs"
        )
        json_files = [f for f in os.listdir(log_dir) if f.startswith("task_")]
        assert len(json_files) > 0
        latest = sorted(json_files)[-1]
        with open(os.path.join(log_dir, latest), "r", encoding="utf-8") as f:
            record = json.load(f)
        assert record["task"] == "记录历史测试"
        assert len(record["history"]) == 1
        assert record["history"][0]["action_type"] == "finish"


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

        test_args = ["main.py", "打开计算器"]
        with patch.object(sys, "argv", test_args), \
             patch("desktop_gui_agent.main.TaskManager", return_value=mock_tm):
            exit_code = main()

        assert exit_code == 0
        mock_tm.run.assert_called_once_with("打开计算器")

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

        test_args = ["main.py", "--max-steps", "10", "测试任务"]
        with patch.object(sys, "argv", test_args), \
             patch("desktop_gui_agent.main.TaskManager", return_value=mock_tm) as mock_tm_cls:
            exit_code = main()

        assert exit_code == 0
        mock_tm_cls.assert_called_once_with(max_steps=10, max_consecutive_errors=3)

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

        test_args = ["main.py", "不可能的任务"]
        with patch.object(sys, "argv", test_args), \
             patch("desktop_gui_agent.main.TaskManager", return_value=mock_tm):
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

        # 模拟：无命令行参数 → 交互模式 → 用户输入任务
        test_args = ["main.py"]
        with patch.object(sys, "argv", test_args), \
             patch("desktop_gui_agent.main.TaskManager", return_value=mock_tm), \
             patch("builtins.input", return_value="用户输入的任务"):
            exit_code = main()

        assert exit_code == 0
        mock_tm.run.assert_called_once_with("用户输入的任务")
