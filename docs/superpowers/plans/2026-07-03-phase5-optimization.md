# Phase 5: 优化与鲁棒性 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 Desktop GUI Agent 进行第一轮优化：Prompt 调优（few-shot + CoT + 可配置化）、错误恢复增强（分类+重试）、跨平台适配（PlatformInfo 工具类）。

**Architecture:** 三个独立改动方向，不互依赖。Task 1-2 做 Prompt，Task 3-4 做错误恢复，Task 5-6 做跨平台。每个方向完成后独立可测试。

**Tech Stack:** Python 3.11, pytest, 已有依赖（无新增）

## Global Constraints

- 不改动现有 92 个测试的行为（只追加新测试，不修改已有测试）
- 遵循 PEP8、类型提示、docstring 规范
- 代码注释需符合项目风格（中文 docstring）
- 遵循"有就行"原则：实现核心机制，不追求量化指标
- 所有测试用 `./gui_agent/python.exe -m pytest` 运行
- 每个 Task 结束时独立 commit

---

### Task 1: config.py — Prompt 配置项

**Files:**
- Modify: `desktop_gui_agent/config.py`

**Interfaces:**
- Produces: `PROMPT_SYSTEM: str`, `PROMPT_USER_TEMPLATE: str`, `PROMPT_FEW_SHOT_EXAMPLES: list[str]`, `PROMPT_COT_ENABLED: bool`

- [ ] **Step 1: 在 config.py 末尾追加 Prompt 配置项**

在 `desktop_gui_agent/config.py` 末尾追加以下代码：

```python
# ===== Prompt 模板配置 =====
PROMPT_SYSTEM = """你是桌面GUI智能体。根据截图和任务，输出下一步操作。

有效动作：
- click(x=<int>, y=<int>)           # 点击指定坐标
- type(text="<str>")                 # 输入文本
- scroll(direction="up|down", steps=<int>)  # 滚动
- hotkey(key1, key2, ...)            # 组合键
- finish(result="<str>")             # 任务完成

请根据当前截图，输出下一步需要执行的一个动作。只输出动作本身，不要解释。"""

PROMPT_USER_TEMPLATE = "用户任务：{task}\n请输出下一步动作："

PROMPT_FEW_SHOT_EXAMPLES = [
    """示例1:
任务: "打开记事本"
屏幕: 显示 Windows 桌面，底部有任务栏，左侧有开始按钮
动作: click(x=150, y=300)""",

    """示例2:
任务: "在搜索框输入Python"
屏幕: 显示已打开的开始菜单，搜索框可见且有光标
动作: type(text="Python")""",
]

PROMPT_COT_ENABLED = True
```

- [ ] **Step 2: 验证 config 导入正常**

```bash
./gui_agent/python.exe -c "from desktop_gui_agent import config; print(config.PROMPT_SYSTEM[:20]); print(config.PROMPT_COT_ENABLED)"
```

预期输出：`你是桌面GUI智能体` + `True`

- [ ] **Step 3: 运行已有测试确认不改动行为**

```bash
./gui_agent/python.exe -m pytest tests/test_agent.py::TestAgentConfig -v
```

预期：全部 PASS（已有测试验证 config 值类型，新增项不影响）

- [ ] **Step 4: Commit**

```bash
git add desktop_gui_agent/config.py
git commit -m "feat: config.py 新增 Prompt 模板配置项"
```

---

### Task 2: model_client.py — Prompt 可配置化 + Few-shot + CoT

**Files:**
- Modify: `desktop_gui_agent/agent/model_client.py`
- Test: `tests/test_agent.py`（追加测试用例）

**Interfaces:**
- Consumes: `config.PROMPT_SYSTEM`, `config.PROMPT_USER_TEMPLATE`, `config.PROMPT_FEW_SHOT_EXAMPLES`, `config.PROMPT_COT_ENABLED`
- Produces: `ModelClient.query()` — prompt 拼接逻辑变更，接口签名不变

- [ ] **Step 1: 写测试 — 验证 prompt 拼接正确性**

在 `tests/test_agent.py` 的 `TestModelClientQuery` 类末尾追加测试方法。先读文件确认插入位置：

```bash
./gui_agent/python.exe -c "import ast; tree=ast.parse(open('tests/test_agent.py').read()); classes=[n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]; print([c.name for c in classes])"
```

然后在 `tests/test_agent.py` 文件末尾（`TestMain` 类之前或最后一个测试类之后）追加：

```python
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
        assert "示例1" in system_content
        assert "打开记事本" in system_content

    @patch('desktop_gui_agent.agent.model_client.process_vision_info')
    @patch('desktop_gui_agent.agent.model_client._load_local_model')
    def test_cot_guidance_in_user_prompt(self, mock_load, mock_pvi):
        """CoT 引导文本应出现在 user prompt 中"""
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
        assert "简述" in user_text

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
```

需要在 `tests/test_agent.py` 顶部确认已有 `from unittest.mock import patch, MagicMock` 和 `from PIL import Image` 导入（文件中已存在，无需重复添加）。

- [ ] **Step 2: 运行新测试确认失败**

```bash
./gui_agent/python.exe -m pytest tests/test_agent.py::TestPromptBuilding -v
```

预期：4 个测试全部 FAIL（model_client 尚未使用 config 中的 prompt 模板）

- [ ] **Step 3: 修改 model_client.py — 读取 config 中的 prompt 模板**

修改 `desktop_gui_agent/agent/model_client.py`：

**3a. 修改 import（第 16-22 行区域）**，在 config 导入中追加新配置项：

```python
from desktop_gui_agent.config import (
    MODEL_API_KEY,
    MODEL_API_URL,
    MODEL_MAX_TOKENS,
    MODEL_MODE,
    MODEL_NAME,
    PROMPT_COT_ENABLED,
    PROMPT_FEW_SHOT_EXAMPLES,
    PROMPT_SYSTEM,
    PROMPT_USER_TEMPLATE,
)
```

**3b. 删除原有的 `_SYSTEM_PROMPT` 和 `_USER_PROMPT_TEMPLATE` 定义（第 36-47 行）**，替换为引用 config：

```python
# ===== Prompt 模板 =====
# 从 config.py 读取，如需自定义可在 config.py 中修改
```

**3c. 修改 `query()` 方法（第 138 行附近）**，在构建 user_prompt 时加入 few-shot 示例和 CoT 引导：

将原来的：
```python
user_prompt = _USER_PROMPT_TEMPLATE.format(task=task)

if context:
    history_lines = "\n".join(f"  步骤{i+1}: {act}" for i, act in enumerate(context))
    user_prompt += f"\n已完成步骤：\n{history_lines}"
```

改为：
```python
user_prompt = PROMPT_USER_TEMPLATE.format(task=task)

# CoT 推理引导（可通过配置关闭）
if PROMPT_COT_ENABLED:
    user_prompt += "\n请先简述屏幕上看到的关键元素（1句话），然后输出下一步动作。"

if context:
    history_lines = "\n".join(f"  步骤{i+1}: {act}" for i, act in enumerate(context))
    user_prompt += f"\n已完成步骤：\n{history_lines}"
```

**3d. 修改 `_query_local()` 方法（第 151-153 行）**，在构建 messages 时将 few-shot 示例注入系统提示词：

将原来的：
```python
messages = [
    {"role": "system", "content": _SYSTEM_PROMPT},
```

改为：
```python
# 拼接系统提示词 + few-shot 示例
system_content = PROMPT_SYSTEM
if PROMPT_FEW_SHOT_EXAMPLES:
    system_content += "\n\n" + "\n\n".join(PROMPT_FEW_SHOT_EXAMPLES)

messages = [
    {"role": "system", "content": system_content},
```

**3e. 同样修改 `_query_api()` 方法（第 229-233 行）**，系统提示词也需要包含 few-shot：

将原来的：
```python
{"role": "system", "content": _SYSTEM_PROMPT},
```

改为：
```python
{"role": "system", "content": system_content},
```

并在 `_query_api()` 方法开头（`if not self.api_url:` 之后）加入相同的 `system_content` 拼接逻辑：

```python
system_content = PROMPT_SYSTEM
if PROMPT_FEW_SHOT_EXAMPLES:
    system_content += "\n\n" + "\n\n".join(PROMPT_FEW_SHOT_EXAMPLES)
```

- [ ] **Step 4: 运行新测试确认通过**

```bash
./gui_agent/python.exe -m pytest tests/test_agent.py::TestPromptBuilding -v
```

预期：4 个测试全部 PASS

- [ ] **Step 5: 运行全部已有测试确认无回归**

```bash
./gui_agent/python.exe -m pytest tests/ -v
```

预期：92 个已有测试仍然 PASS，新增 4 个也 PASS，共 96 passed

- [ ] **Step 6: Commit**

```bash
git add desktop_gui_agent/agent/model_client.py tests/test_agent.py
git commit -m "feat: Prompt 可配置化 + few-shot 示例 + CoT 推理引导"
```

---

### Task 3: exceptions.py — ErrorCategory 枚举 + classify_error()

**Files:**
- Modify: `desktop_gui_agent/utils/exceptions.py`
- Test: `tests/test_agent.py`（追加测试用例）

**Interfaces:**
- Produces: `ErrorCategory(Enum)` with values `RETRYABLE`, `SKIP`, `FATAL`; `classify_error(exception: Exception) -> ErrorCategory`

- [ ] **Step 1: 写测试 — 验证错误分类规则**

在 `tests/test_agent.py` 的 `TestModelError` 类之后（约第 22 行之后）追加：

```python
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
```

- [ ] **Step 2: 运行新测试确认失败**

```bash
./gui_agent/python.exe -m pytest tests/test_agent.py::TestErrorCategory -v
```

预期：9 个测试全部 FAIL（classify_error 尚未实现）

- [ ] **Step 3: 修改 exceptions.py — 新增 ErrorCategory 和 classify_error()**

在 `desktop_gui_agent/utils/exceptions.py` 文件末尾追加：

```python
# ===== 错误分类（Phase 5）=====

from enum import Enum


class ErrorCategory(Enum):
    """错误类别枚举，用于 TaskManager 的错误处理策略选择。

    RETRYABLE: 可重试（截图偶然失败、网络波动）
    SKIP:      跳过当前步（OCR失败、解析失败、坐标越界）
    FATAL:     立即终止（模型加载失败、配置错误）
    """
    RETRYABLE = "retryable"
    SKIP = "skip"
    FATAL = "fatal"


def classify_error(exception: Exception) -> ErrorCategory:
    """根据异常类型返回错误类别，用于决定错误处理策略。

    分类规则：
    - ScreenshotError / 网络超时 / 连接错误 → RETRYABLE
    - OCRError / 解析失败 / 坐标越界 / 执行失败 → SKIP
    - 模型加载失败 → FATAL
    - 未知异常 → SKIP（保守策略）

    Args:
        exception: 捕获到的异常对象。

    Returns:
        ErrorCategory 枚举值。
    """
    # 延迟导入避免循环依赖
    from desktop_gui_agent.utils.exceptions import (
        ControlError,
        ModelError,
        OCRError,
        ScreenshotError,
        UILocatorError,
    )

    # RETRYABLE: 截图失败
    if isinstance(exception, ScreenshotError):
        return ErrorCategory.RETRYABLE

    # RETRYABLE: 网络相关
    try:
        import requests
        if isinstance(exception, (requests.Timeout, requests.ConnectionError)):
            return ErrorCategory.RETRYABLE
    except ImportError:
        pass

    # FATAL: 模型加载失败（注意：要在 SKIP 的 ModelError 判断之前）
    if isinstance(exception, ModelError):
        msg = str(exception)
        if "加载失败" in msg or "加载" in msg:
            return ErrorCategory.FATAL
        # API 调用已重试失败 → SKIP
        return ErrorCategory.SKIP

    # SKIP: OCR / 控制 / UI定位异常
    if isinstance(exception, (OCRError, ControlError, UILocatorError)):
        return ErrorCategory.SKIP

    # 默认：未知异常保守归类为 SKIP
    return ErrorCategory.SKIP
```

- [ ] **Step 4: 运行新测试确认通过**

```bash
./gui_agent/python.exe -m pytest tests/test_agent.py::TestErrorCategory -v
```

预期：9 个测试全部 PASS

- [ ] **Step 5: 运行全部已有测试确认无回归**

```bash
./gui_agent/python.exe -m pytest tests/ -v
```

预期：已有测试全部 PASS

- [ ] **Step 6: Commit**

```bash
git add desktop_gui_agent/utils/exceptions.py tests/test_agent.py
git commit -m "feat: 新增 ErrorCategory 错误分类枚举 + classify_error()"
```

---

### Task 4: task_manager.py — 错误分类处理 + 截图重试

**Files:**
- Modify: `desktop_gui_agent/agent/task_manager.py`
- Test: `tests/test_agent.py`（追加测试用例）

**Interfaces:**
- Consumes: `classify_error()`, `ErrorCategory`
- Produces: `TaskManager._capture_with_retry(max_retries=2) -> Image.Image`, `TaskManager.run()` — 错误处理逻辑变更

- [ ] **Step 1: 写测试 — 截图重试 + 错误分类行为**

在 `tests/test_agent.py` 的 `TestTaskManagerRun` 类末尾（第 725 行 `test_run_saves_history_on_completion` 之后，`TestMain` 类之前）追加：

```python
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
```

- [ ] **Step 2: 运行新测试确认失败**

```bash
./gui_agent/python.exe -m pytest tests/test_agent.py::TestTaskManagerRun::test_capture_with_retry_success_first_try tests/test_agent.py::TestTaskManagerRun::test_capture_with_retry_success_after_failure tests/test_agent.py::TestTaskManagerRun::test_capture_with_retry_all_failed tests/test_agent.py::TestTaskManagerRun::test_run_fatal_error_returns_immediately -v
```

预期：4 个测试 FAIL（方法尚未实现）

- [ ] **Step 3: 修改 task_manager.py — 新增 _capture_with_retry() 方法**

在 `task_manager.py` 的 `TaskManager` 类中，`_dispatch()` 方法之后（约第 112 行之后）追加：

```python
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
```

- [ ] **Step 4: 修改 task_manager.py — run() 中的截图步骤使用 _capture_with_retry**

将 `run()` 方法中截图步骤（第 158-165 行附近）从：

```python
                # 1. 截图
                try:
                    image = capture()
                    timings["screenshot"] = time.time() - step_start
                except ScreenshotError as e:
                    logger.error(f"截图失败: {e}")
                    consecutive_errors += 1
                    continue
```

改为：

```python
                # 1. 截图（带重试）
                try:
                    image = self._capture_with_retry(max_retries=2)
                    timings["screenshot"] = time.time() - step_start
                except ScreenshotError as e:
                    logger.error(f"截图失败（已重试）: {e}")
                    consecutive_errors += 1
                    continue
```

- [ ] **Step 5: 修改 task_manager.py — run() 中的模型推理步骤使用 classify_error**

将 `run()` 方法中模型推理步骤（第 179-192 行附近）从：

```python
                try:
                    model_output = self.model_client.query(image, task, context=history_actions)
                except Exception as e:
                    logger.error(f"模型推理失败: {e}")
                    consecutive_errors += 1
                    continue
```

改为：

```python
                try:
                    model_output = self.model_client.query(image, task, context=history_actions)
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
```

需要在文件顶部追加导入：

```python
from desktop_gui_agent.utils.exceptions import ErrorCategory, OCRError, ScreenshotError, classify_error
```

替换原有的：
```python
from desktop_gui_agent.utils.exceptions import OCRError, ScreenshotError
```

- [ ] **Step 6: 运行新测试确认通过**

```bash
./gui_agent/python.exe -m pytest tests/test_agent.py::TestTaskManagerRun::test_capture_with_retry_success_first_try tests/test_agent.py::TestTaskManagerRun::test_capture_with_retry_success_after_failure tests/test_agent.py::TestTaskManagerRun::test_capture_with_retry_all_failed tests/test_agent.py::TestTaskManagerRun::test_run_fatal_error_returns_immediately -v
```

预期：4 个测试全部 PASS

- [ ] **Step 7: 运行全部测试确认无回归**

```bash
./gui_agent/python.exe -m pytest tests/ -v
```

预期：全部 PASS

- [ ] **Step 8: Commit**

```bash
git add desktop_gui_agent/agent/task_manager.py tests/test_agent.py
git commit -m "feat: 截图重试机制 + 错误分类处理集成到 TaskManager"
```

---

### Task 5: platform.py — PlatformInfo 工具类（新建）

**Files:**
- Create: `desktop_gui_agent/utils/platform.py`
- Create: `tests/test_platform.py`

**Interfaces:**
- Produces: `PlatformInfo` 类 — `is_windows: bool`, `is_macos: bool`, `is_linux: bool`, `os_name: str`, `get_log_dir() -> Path`, `get_chinese_font_path() -> Optional[str]`, `get_recommended_modifier_key() -> str`

- [ ] **Step 1: 写测试文件**

新建 `tests/test_platform.py`：

```python
# -*- coding: utf-8 -*-
"""平台信息工具类测试（Phase 5）"""
import os
import sys
from unittest.mock import patch

import pytest


class TestPlatformInfoProperties:
    """PlatformInfo 属性测试（当前平台）"""

    def test_is_windows_on_windows(self):
        """Windows 上 is_windows 应为 True"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        if sys.platform == "win32":
            assert PlatformInfo.is_windows is True
        else:
            pytest.skip("非 Windows 平台")

    def test_os_name_is_string(self):
        """os_name 应返回非空字符串"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        assert isinstance(PlatformInfo.os_name, str)
        assert len(PlatformInfo.os_name) > 0

    def test_recommended_modifier_key_is_string(self):
        """get_recommended_modifier_key 应返回非空字符串"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        key = PlatformInfo.get_recommended_modifier_key()
        assert isinstance(key, str)
        assert key in ("win", "cmd")


class TestPlatformInfoMockedPlatforms:
    """mock sys.platform 验证各平台返回值"""

    @patch("sys.platform", "darwin")
    def test_macos_detection(self):
        """mock darwin → is_macos=True, modifier_key='cmd'"""
        # 需要重新导入以触发模块级缓存刷新
        import importlib
        import desktop_gui_agent.utils.platform as plat
        importlib.reload(plat)
        assert plat.PlatformInfo.is_macos is True
        assert plat.PlatformInfo.is_windows is False
        assert plat.PlatformInfo.is_linux is False
        assert plat.PlatformInfo.get_recommended_modifier_key() == "cmd"

    @patch("sys.platform", "linux")
    def test_linux_detection(self):
        """mock linux → is_linux=True, modifier_key='win'"""
        import importlib
        import desktop_gui_agent.utils.platform as plat
        importlib.reload(plat)
        assert plat.PlatformInfo.is_linux is True
        assert plat.PlatformInfo.is_windows is False
        assert plat.PlatformInfo.is_macos is False
        assert plat.PlatformInfo.get_recommended_modifier_key() == "win"


class TestPlatformInfoFontPath:
    """get_chinese_font_path() 测试"""

    def test_returns_string_or_none(self):
        """应返回 str 或 None"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        result = PlatformInfo.get_chinese_font_path()
        assert result is None or isinstance(result, str)

    def test_returns_valid_path_when_exists(self):
        """如果返回了路径，则该文件应存在"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        result = PlatformInfo.get_chinese_font_path()
        if result is not None:
            assert os.path.isfile(result), f"字体文件不存在: {result}"


class TestPlatformInfoLogDir:
    """get_log_dir() 测试"""

    def test_returns_path_object(self):
        """应返回 pathlib.Path 对象"""
        from pathlib import Path
        from desktop_gui_agent.utils.platform import PlatformInfo
        result = PlatformInfo.get_log_dir()
        assert isinstance(result, Path)

    def test_log_dir_exists_after_call(self):
        """调用后日志目录应被创建"""
        from desktop_gui_agent.utils.platform import PlatformInfo
        log_dir = PlatformInfo.get_log_dir()
        assert log_dir.exists()
```

- [ ] **Step 2: 运行新测试确认失败**

```bash
./gui_agent/python.exe -m pytest tests/test_platform.py -v
```

预期：全部 FAIL（platform.py 尚未创建）

- [ ] **Step 3: 创建 platform.py**

新建 `desktop_gui_agent/utils/platform.py`：

```python
# -*- coding: utf-8 -*-
"""平台信息工具类 — PDF 4.5（Phase 5 跨平台适配）

提供统一的平台检测和平台相关资源路径管理。
将散落在各模块的平台判断逻辑收拢到此模块。
"""
import os
import sys
from pathlib import Path
from typing import Optional


class PlatformInfo:
    """平台检测与资源路径管理。

    通过 sys.platform 检测当前操作系统，
    提供中文字体查找、日志目录、推荐修饰键等平台相关信息。

    Attributes:
        is_windows: 是否为 Windows。
        is_macos: 是否为 macOS。
        is_linux: 是否为 Linux。
        os_name: 操作系统简称。
    """

    # 模块加载时一次性检测平台
    is_windows: bool = sys.platform == "win32"
    is_macos: bool = sys.platform == "darwin"
    is_linux: bool = sys.platform.startswith("linux")

    if is_windows:
        os_name: str = "windows"
    elif is_macos:
        os_name: str = "macos"
    elif is_linux:
        os_name: str = "linux"
    else:
        os_name: str = sys.platform

    @staticmethod
    def get_log_dir() -> Path:
        """返回日志存储目录的绝对路径。

        目录不存在时会自动创建。使用项目根目录下的 logs/ 目录，
        避免相对路径在不同启动方式下行为不一致。

        Returns:
            日志目录的 Path 对象。
        """
        # 从本文件位置向上找到项目根目录
        # utils/platform.py → utils/ → desktop_gui_agent/ → 项目根
        project_root = Path(__file__).resolve().parent.parent.parent
        log_dir = project_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    @staticmethod
    def get_chinese_font_path() -> Optional[str]:
        """查找并返回系统中文字体的路径。

        按平台依次尝试已知字体路径，返回第一个存在的。
        全部缺失时返回 None。

        Returns:
            字体文件的绝对路径，或 None。
        """
        if PlatformInfo.is_windows:
            windir = os.environ.get("WINDIR", "C:\\Windows")
            candidates = [
                os.path.join(windir, "Fonts", "msyh.ttc"),    # 微软雅黑
                os.path.join(windir, "Fonts", "msyhbd.ttc"),  # 微软雅黑粗体
                os.path.join(windir, "Fonts", "simhei.ttf"),  # 黑体
                os.path.join(windir, "Fonts", "simsun.ttc"),  # 宋体
            ]
        elif PlatformInfo.is_macos:
            candidates = [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
            ]
        elif PlatformInfo.is_linux:
            candidates = [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            ]
        else:
            return None

        for font_path in candidates:
            if os.path.isfile(font_path):
                return font_path

        return None

    @staticmethod
    def get_recommended_modifier_key() -> str:
        """返回当前平台推荐的修饰键名称。

        Windows/Linux: "win"
        macOS: "cmd"（对应 ⌘ 键）

        Returns:
            修饰键字符串。
        """
        if PlatformInfo.is_macos:
            return "cmd"
        return "win"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
./gui_agent/python.exe -m pytest tests/test_platform.py -v
```

预期：全部 PASS（Windows 上 `test_macos_detection` 和 `test_linux_detection` 通过 mock 验证）

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
./gui_agent/python.exe -m pytest tests/ -v
```

预期：全部 PASS（新增 test_platform.py 的用例）

- [ ] **Step 6: Commit**

```bash
git add desktop_gui_agent/utils/platform.py tests/test_platform.py
git commit -m "feat: 新增 PlatformInfo 平台信息工具类"
```

---

### Task 6: ui_locator.py + logger.py — 收拢平台判断到 PlatformInfo

**Files:**
- Modify: `desktop_gui_agent/perception/ui_locator.py`
- Modify: `desktop_gui_agent/utils/logger.py`

**Interfaces:**
- Consumes: `PlatformInfo.get_chinese_font_path()`, `PlatformInfo.get_log_dir()`
- Produces: `_get_chinese_font()` 内部重构；`get_logger()` 日志路径使用绝对路径

- [ ] **Step 1: 运行已有测试确认基线**

```bash
./gui_agent/python.exe -m pytest tests/test_perception.py tests/test_platform.py -v
```

预期：全部 PASS

- [ ] **Step 2: 修改 ui_locator.py — 收拢字体查找**

**2a. 删除原有的平台字体候选列表（第 23-42 行）**，即删除：

```python
_CHINESE_FONT_CANDIDATES = []
if sys.platform == "win32":
    _CHINESE_FONT_CANDIDATES = [
        ...
    ]
elif sys.platform == "darwin":
    _CHINESE_FONT_CANDIDATES = [
        ...
    ]
else:
    _CHINESE_FONT_CANDIDATES = [
        ...
    ]
```

**2b. 修改 `_get_chinese_font()` 函数（第 45-65 行）**，重构为使用 PlatformInfo：

将原来的：
```python
def _get_chinese_font(size: int = 14) -> ImageFont.FreeTypeFont:
    """查找并返回支持中文的字体。..."""
    for font_path in _CHINESE_FONT_CANDIDATES:
        if os.path.isfile(font_path):
            try:
                return ImageFont.truetype(font_path, size=size)
            except (OSError, IOError):
                continue

    # 全部失败时回退到 PIL 默认字体
    logger.warning("未找到中文字体，标注中的中文可能无法正常显示")
    return ImageFont.load_default()
```

改为：
```python
def _get_chinese_font(size: int = 14) -> ImageFont.FreeTypeFont:
    """查找并返回支持中文的字体。

    通过 PlatformInfo 获取平台对应的中文字体路径。
    若全部缺失则回退到 PIL 默认字体。

    Args:
        size: 字体大小（像素）。

    Returns:
        ImageFont 对象（优先 FreeTypeFont，否则默认 bitmap 字体）。
    """
    from desktop_gui_agent.utils.platform import PlatformInfo

    font_path = PlatformInfo.get_chinese_font_path()
    if font_path is not None:
        try:
            return ImageFont.truetype(font_path, size=size)
        except (OSError, IOError):
            pass

    # 全部失败时回退到 PIL 默认字体（中文会显示为方块，但不抛异常）
    logger.warning("未找到中文字体，标注中的中文可能无法正常显示")
    return ImageFont.load_default()
```

**2c. 删除顶部不再需要的 `_CHINESE_FONT_CANDIDATES` 引用相关的 `import os` 和 `import sys`**（如果只用于字体候选列表的话）。实际上 `os` 和 `sys` 在其他地方还有用，保留它们。

- [ ] **Step 3: 修改 logger.py — 日志目录使用 PlatformInfo**

修改 `get_logger()` 函数中的日志目录创建逻辑（第 67-70 行）：

将原来的：
```python
    # 文件（自动创建 logs/ 目录）
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
```

改为：
```python
    # 文件（自动创建 logs/ 目录，使用绝对路径避免相对路径不一致）
    from desktop_gui_agent.utils.platform import PlatformInfo
    log_dir = str(PlatformInfo.get_log_dir())
```

- [ ] **Step 4: 运行测试确认无回归**

```bash
./gui_agent/python.exe -m pytest tests/test_perception.py tests/test_platform.py -v
```

预期：全部 PASS（perception 测试仍通过 draw_boxes，platform 测试仍通过）

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
./gui_agent/python.exe -m pytest tests/ -v
```

预期：全部 PASS

- [ ] **Step 6: Commit**

```bash
git add desktop_gui_agent/perception/ui_locator.py desktop_gui_agent/utils/logger.py
git commit -m "refactor: 收拢平台判断到 PlatformInfo（字体查找 + 日志目录）"
```

---

## 完成检查清单

- [ ] `./gui_agent/python.exe -m pytest tests/ -v` — 全部 PASS，无回归
- [ ] 新配置项 `PROMPT_SYSTEM` 等可在 `config.py` 中修改
- [ ] few-shot 示例正确注入系统提示词
- [ ] CoT 引导可通过 `PROMPT_COT_ENABLED` 开关
- [ ] 截图失败自动重试（最多 2 次）
- [ ] 致命错误（模型加载失败）立即终止
- [ ] 平台检测通过 `PlatformInfo` 统一入口
- [ ] Git log 显示 6 个清晰的 commit
