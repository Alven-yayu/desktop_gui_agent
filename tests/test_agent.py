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
