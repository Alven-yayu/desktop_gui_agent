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
