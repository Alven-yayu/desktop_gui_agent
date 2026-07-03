# Phase 5: 优化与鲁棒性 — 设计文档

**日期**: 2026-07-03
**版本**: 1.0
**状态**: 已确认
**范围**: Desktop GUI Agent — prompt 调优、错误恢复增强、跨平台适配

---

## 1. 目标与范围

在 Phase 1-4 完成核心功能的基础上，对三个方向进行第一轮优化。遵循"有就行"原则：每个方向实现核心机制，不追求量化指标达标。

### 1.1 三个方向

| 方向 | 目标 | 改动量 |
|---|---|---|
| Prompt 调优 | 提高模型输出格式合规率 | ~80 行 |
| 错误恢复增强 | 区分错误类型，可恢复错误自动重试 | ~100 行 |
| 跨平台适配 | 统一平台判断逻辑，自动适配 | ~120 行 |

**总改动量**: ~300 行，新增 1 个文件 (`utils/platform.py`)

---

## 2. Prompt 调优

### 2.1 当前问题

`model_client.py` 的 `_SYSTEM_PROMPT` 只有动作格式罗列，模型容易：
- 在动作前后附加多余解释文字
- 输出错误的参数格式
- 对非标准 UI 场景产生幻觉

### 2.2 改进项

#### ① Few-shot 示例（核心）

在系统提示词中嵌入 2 个完整示例，建立输入→输出的格式锚定：

```
示例1:
  任务: "打开记事本"
  屏幕: 显示 Windows 桌面
  动作: click(x=150, y=300)

示例2:
  任务: "在搜索框输入Python"
  屏幕: 显示已打开的开始菜单，搜索框可见
  动作: type(text="Python")
```

示例放在 `config.py` 的 `PROMPT_FEW_SHOT_EXAMPLES` 配置项中，方便后续扩展。

#### ② CoT 推理引导

在 `_USER_PROMPT_TEMPLATE` 中加入引导语，要求模型先简述屏幕状态再输出动作：

> "请先简述屏幕上看到的关键元素（1句话），然后输出下一步动作。"

CoT 引导可选开启，通过 `config.PROMPT_COT_ENABLED = True` 控制。

#### ③ Prompt 模板可配置化

将 prompt 相关常量从 `model_client.py` 模块级变量迁移到 `config.py`：

```python
# config.py 新增
PROMPT_SYSTEM = "你是桌面GUI智能体..."  # 原 _SYSTEM_PROMPT
PROMPT_USER_TEMPLATE = "用户任务：{task}\n..."  # 原 _USER_PROMPT_TEMPLATE
PROMPT_FEW_SHOT_EXAMPLES = [...]  # 新增
PROMPT_COT_ENABLED = True  # 新增
```

### 2.3 涉及文件

| 文件 | 改动 |
|---|---|
| `config.py` | 新增 PROMPT_SYSTEM、PROMPT_USER_TEMPLATE、PROMPT_FEW_SHOT_EXAMPLES、PROMPT_COT_ENABLED |
| `agent/model_client.py` | 读取 config 中的 prompt 模板，拼接 few-shot 示例和 CoT 引导 |

---

## 3. 错误恢复增强

### 3.1 当前问题

`task_manager.py` 的 `run()` 对所有错误统一 `consecutive_errors += 1`，不区分：
- 可恢复错误（截图偶然失败、网络波动）→ 应该重试
- 不可恢复错误（坐标越界、模型输出无法解析）→ 应该跳过
- 致命错误（模型加载失败）→ 应该立即终止

### 3.2 改进项

#### ① 错误分类（`utils/exceptions.py`）

新增 `ErrorCategory` 枚举和分类函数：

```python
from enum import Enum

class ErrorCategory(Enum):
    RETRYABLE = "retryable"     # 可重试：截图失败、API超时、网络错误
    SKIP = "skip"               # 跳过当前步：OCR失败、模型空输出、解析失败
    FATAL = "fatal"             # 立即终止：模型加载失败、配置错误

def classify_error(exception: Exception) -> ErrorCategory:
    """根据异常类型返回错误类别"""
```

分类规则：

| 异常/场景 | 类别 |
|---|---|
| `ScreenshotError` | RETRYABLE |
| `requests.Timeout` / `ConnectionError` | RETRYABLE |
| HTTP 429 / 5xx | RETRYABLE |
| `OCRError` | SKIP |
| 模型返回空输出 | SKIP |
| parse 返回 unknown | SKIP |
| 坐标越界 | SKIP |
| 控制器执行返回 False | SKIP |
| `ModelError`（模型加载） | FATAL |
| `ModelError`（API 调用已重试失败） | SKIP |
| 配置项缺失/非法 | FATAL |

#### ② TaskManager 分类处理

`task_manager.py` 的 `run()` 中错误处理逻辑改为：

- **RETRYABLE**：最多重试 2 次（间隔 0.5s），全失败 → `consecutive_errors += 1`
- **SKIP**：不重试，直接 `consecutive_errors += 1`
- **FATAL**：立即终止，返回 `{"success": False, "error": "致命错误: ..."}`

#### ③ 截图失败重试

将当前截图步骤的简单 `try/except → continue` 替换为带重试的 `_capture_with_retry()` 方法：

```python
def _capture_with_retry(self, max_retries: int = 2) -> Image.Image:
    """截图，失败时最多重试 max_retries 次"""
```

### 3.3 涉及文件

| 文件 | 改动 |
|---|---|
| `utils/exceptions.py` | 新增 ErrorCategory 枚举 + classify_error() |
| `agent/task_manager.py` | run() 中集成错误分类处理；新增 _capture_with_retry() |

---

## 4. 跨平台适配

### 4.1 当前问题

- 平台判断散落在 `logger.py`（控制台编码）、`ui_locator.py`（字体路径）、`config.py`（部分路径）中
- 没有统一的平台信息入口
- 日志目录使用相对路径 `../../logs`，在不同启动方式下行为不一致

### 4.2 改进项

#### ① `utils/platform.py` — 平台信息工具类

新建文件，提供：

```python
class PlatformInfo:
    is_windows: bool
    is_macos: bool
    is_linux: bool
    os_name: str  # "windows" / "macos" / "linux"

    @staticmethod
    def get_log_dir() -> Path: ...
    @staticmethod
    def get_chinese_font_path() -> Optional[str]: ...
    @staticmethod
    def get_recommended_modifier_key() -> str: ...  # "win"/"cmd"/"win"
```

将 `ui_locator.py` 的中文字体查找逻辑和 `logger.py` 的日志目录创建逻辑迁移到此类中。

#### ② 收拢已有平台判断

| 原有位置 | 收拢到 PlatformInfo |
|---|---|
| `logger.py:14-31` Windows 控制台 UTF-8 修复 | 保留（行为逻辑），但调用 PlatformInfo |
| `ui_locator.py:23-43` 平台字体候选列表 | `PlatformInfo.get_chinese_font_path()` |
| `ui_locator.py:45-65` `_get_chinese_font()` | 重构为使用 PlatformInfo |
| `logger.py:68` 日志目录路径 | `PlatformInfo.get_log_dir()` |

#### ③ `config.py` 平台自动适配

利用 `PlatformInfo` 在模块加载时自动设置平台相关默认值，无需用户手改。

### 4.3 涉及文件

| 文件 | 改动 |
|---|---|
| `utils/platform.py` | **新建**，包含 PlatformInfo 类 |
| `utils/logger.py` | 日志目录改为调用 PlatformInfo.get_log_dir() |
| `perception/ui_locator.py` | 字体路径改为调用 PlatformInfo.get_chinese_font_path() |
| `config.py` | 可选：新增平台自动适配逻辑 |

---

## 5. 测试策略

- `utils/platform.py`：独立测试，mock sys.platform 验证各平台返回值
- `utils/exceptions.py`：测试 classify_error 对各异常类型的分类结果
- `agent/task_manager.py`：新增 _capture_with_retry 的单测，模拟前 N 次失败最后一次成功
- `agent/model_client.py`：验证 prompt 模板拼接正确性（few-shot 示例注入、CoT 引导）
- 不改动现有 92 个测试的行为

---

## 6. 文件改动总览

```
新建:
  utils/platform.py                        (~80 行)

修改:
  config.py                                +20 行 (prompt 配置项)
  agent/model_client.py                    +40 行 (prompt 模板读取+拼接)
  utils/exceptions.py                      +30 行 (ErrorCategory + classify_error)
  agent/task_manager.py                    +50 行 (错误分类处理+截图重试)
  utils/logger.py                          -10+5 行 (收拢平台判断)
  perception/ui_locator.py                 -35+10 行 (收拢字体查找到 PlatformInfo)

新增测试:
  tests/test_platform.py                   (~50 行)
  tests/test_perception.py                 +~10 行
  tests/test_agent.py                      +~20 行
```

---

## 7. 不在范围内

- 性能基准测试（screenshot/OCR/推理耗时统计）
- 15 个系统测试任务的端到端执行
- 多 agent 协作
- GUI 可视化配置界面
- prompt 的自动化 A/B 测试
