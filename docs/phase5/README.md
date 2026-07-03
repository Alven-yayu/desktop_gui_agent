# Phase 5：优化与鲁棒性 — 需求分析

> 参考：PRD 4.5 节（优化与鲁棒性阶段）
> 设计文档：`docs/superpowers/specs/2026-07-03-phase5-optimization-design.md`

---

## 模块职责

在 Phase 1-4 核心功能已完成的基���上，对三个方向进行第一轮优化：**Prompt 调优**（让模型输出更准确）、**错误恢复增强**（智能区分错误类型并重试）、**跨平台适配**（统一平台判断逻辑）。遵循"有就行"原则——每个方向实现核心机制，不追求量化指标达标。

---

## 子模块

```
Phase 5 三个方向
      │
      ├── 5.1 Prompt 调优 (model_client.py + config.py)
      │        few-shot 示例 + CoT 推理引导 + 模板可配置化
      │
      ├── 5.2 错误恢复增强 (task_manager.py + exceptions.py)
      │        错误分类 + 智能重试 + 截图重试
      │
      └── 5.3 跨平台适配 (platform.py + ui_locator.py + logger.py)
               PlatformInfo 工具类 + 字体/日志路径收拢
```

---

## 5.1 Prompt 调优

**功能：** 优化模型提示词模板，通过 few-shot 示例和 CoT 推理引导提高模型输出格式合规率，同时将 prompt 模板迁移到配置文件方便后续调优。

### 5.1.1 Few-shot 示例

| 输入 | 类型 | 说明 |
|------|------|------|
| `PROMPT_FEW_SHOT_EXAMPLES` | `list[str]` | 配置在 `config.py`，每条是一个完整的"任务-屏幕-动作"示例 |

| 输出 | 类型 | 说明 |
|------|------|------|
| 增强后的系统提示词 | `str` | `PROMPT_SYSTEM` + few-shot 示例拼接，送入模型 |

**业务规则：**
- 至少包含 2 个示例：一个点击类（click），一个输入类（type）
- 示例放在系统提示词末尾，建立输入→输出的格式锚定
- 示例从 `config.py` 读取，方便后续追加和调优
- 示例内容覆盖典型 Windows 桌面场景（开始菜单、任务栏、对话框）

### 5.1.2 CoT 推理引导

**功能：** 在用户提示词中引导模型先简述屏幕状态再输出动作。

**业务规则：**
- 通过 `config.PROMPT_COT_ENABLED = True` 控制开关
- 引导文本："请先简述屏幕上看到的关键元素（1句话），然后输出下一步动作。"
- 可通过配置关闭（模型已足够稳定时关闭以减少 token 消耗）

### 5.1.3 Prompt 模板可配置化

**功能：** 将 hardcoded 在 `model_client.py` 中的 prompt 模板迁移到 `config.py`。

| 新配置项 | 类型 | 默认值 | 说明 |
|----------|------|--------|------|
| `PROMPT_SYSTEM` | `str` | 原 `_SYSTEM_PROMPT` 内容 | 系统提示词 |
| `PROMPT_USER_TEMPLATE` | `str` | `"用户任务：{task}\n请输出下一步动作："` | 用户提示词模板 |
| `PROMPT_FEW_SHOT_EXAMPLES` | `list[str]` | 2 条示例 | few-shot 示例列表 |
| `PROMPT_COT_ENABLED` | `bool` | `True` | 是否启用 CoT 推理引导 |

**异常处理：**

| 场景 | 处理 |
|------|------|
| 配置项缺失 | 使用 `model_client.py` 内置的兜底默认值 |
| 示例列表为空 | 跳过 few-shot 注入，不影响正常推理 |

---

## 5.2 错误恢复增强

**功能：** 将当前"所有错误统一处理"改为按错误类型分类，可恢复错误自动重试，不可恢复错误跳过，致命错误立即终止。

### 5.2.1 错误分类

| 输入 | 类型 | 说明 |
|------|------|------|
| `exception` | `Exception` | 捕获到的异常对象 |

| 输出 | 类型 | 说明 |
|------|------|------|
| `ErrorCategory` | `Enum` | `RETRYABLE` / `SKIP` / `FATAL` |

**分类规则：**

| 错误场景 | 类别 | 说明 |
|----------|------|------|
| `ScreenshotError` | `RETRYABLE` | 截图偶然失败，重试通常能恢复 |
| `requests.Timeout` / `ConnectionError` | `RETRYABLE` | 网络波动 |
| HTTP 429 / 5xx | `RETRYABLE` | 服务端临时过载 |
| `OCRError` | `SKIP` | OCR 失败不影响继续（OCR 为空也能跑） |
| 模型返回空输出 | `SKIP` | 偶发，重试模型通常还是空 |
| parse 返回 unknown | `SKIP` | 模型输出本身有问题，重试意义不大 |
| 坐标越界 | `SKIP` | 模型算错坐标，重试同一模型大概率再错 |
| 控制器返回 False | `SKIP` | 执行层问题，重试可能成功也可能不成功 |
| `ModelError`（模型加载） | `FATAL` | 无法恢复，立即终止 |
| 配置项缺失/非法 | `FATAL` | 无法继续运行 |

### 5.2.2 TaskManager 分类处理

**功能：** `task_manager.py` 的 `run()` 中集成错误分类，不同类别不同处理策略。

| 错误类别 | 处理策略 |
|----------|----------|
| `RETRYABLE` | 最多重试 2 次（间隔 0.5s），全失败则 `consecutive_errors += 1` |
| `SKIP` | 不重试，直接 `consecutive_errors += 1` |
| `FATAL` | 立即终止循环，返回 `{"success": False, "error": "致命错误: ..."}` |

### 5.2.3 截图重试

**功能：** 新增 `_capture_with_retry()` 方法，替代原来的简单 try/except。

| 输入 | 类型 | 说明 |
|------|------|------|
| `max_retries` | `int`（默认 2） | 最大重试次数 |

| 输出 | 类型 | 说明 |
|------|------|------|
| 截图 | `PIL.Image` | 成功捕获的截图 |

**业务规则：**
- 每次重试间隔 0.5s
- max_retries 次全失败后抛出 `ScreenshotError`，由上层分类处理
- 重试时记录 WARNING 日志

**异常处理：**

| 场景 | 处理 |
|------|------|
| 截图重试全部失败 | 交由错误分类机制 → RETRYABLE → consecutive_errors += 1 |
| 模型推理重试全部失败 | 交由错误分类机制 → 分类决定 |
| 未知异常 | 保守归类为 SKIP，避免误判导致终止 |

---

## 5.3 跨平台适配

**功能：** 新建 `utils/platform.py` 统一管理平台检测和平台相关资源路径，收拢散落在各模块的平台判断逻辑。

### 5.3.1 PlatformInfo 工具类

| 属性/方法 | 类型 | 说明 |
|-----------|------|------|
| `is_windows` | `bool` | 是否为 Windows |
| `is_macos` | `bool` | 是否为 macOS |
| `is_linux` | `bool` | 是否为 Linux |
| `os_name` | `str` | `"windows"` / `"macos"` / `"linux"` |
| `get_log_dir()` | `Path` | 日志存储目录（平台相关） |
| `get_chinese_font_path()` | `str \| None` | 系统中文字体路径 |
| `get_recommended_modifier_key()` | `str` | 推荐修饰键：`"win"` / `"cmd"` / `"win"` |

**业务规则：**
- 通过 `sys.platform` 检测平台，模块加载时缓存结果
- `get_chinese_font_path()` 按平台依次尝试已知字体路径，返回第一个存在的
- `get_log_dir()` 返回项目根目录下的 `logs/` 目录的绝对路径（避免相对路径在不同启动方式下不一致）
- `get_recommended_modifier_key()`：Windows/Linux 返回 `"win"`，macOS 返回 `"cmd"`

### 5.3.2 收拢已有平台判断

| 原有位置 | 收拢方式 |
|----------|----------|
| `ui_locator.py:23-43` 字体候选列表 | 迁移到 `PlatformInfo.get_chinese_font_path()` |
| `ui_locator.py:45-65` `_get_chinese_font()` | 重构内部调用 `PlatformInfo` |
| `logger.py:68` 日志目录相对路径 | 改用 `PlatformInfo.get_log_dir()` 获取绝对路径 |

**异常处理：**

| 场景 | 处理 |
|------|------|
| 中文字体全部缺失 | 返回 `None`，调用方回退到 PIL 默认字体（中文显示为方块） |
| 日志目录创建失败 | 记录错误日志，回退到项目根目录 |

---

## 模块数据流

```
Phase 5 改动不影响主数据流。改动集中在：

1. Prompt 注入链：
   config.PROMPT_SYSTEM
        + config.PROMPT_FEW_SHOT_EXAMPLES    ──→ model_client.query() → 拼接后送入模型
        + config.PROMPT_COT_ENABLED

2. 错误处理链：
   异常发生 ──→ classify_error()
                   ├── RETRYABLE → _retry_loop() → 失败 → consecutive_errors += 1
                   ├── SKIP → consecutive_errors += 1
                   └── FATAL → 立即终止

3. 平台适配链：
   各模块请求平台资源 ──→ PlatformInfo.xxx() ──→ 返回平台适配的值
```

---

## 新增文件

| 文件 | 说明 |
|------|------|
| `utils/platform.py` | PlatformInfo 工具类（~80 行） |

---

## 新增配置项

添加到 `desktop_gui_agent/config.py`：

| 配置项 | 类型 | 默认值 | 说明 |
|------|------|------|------|
| `PROMPT_SYSTEM` | `str` | 原 `_SYSTEM_PROMPT` | 系统提示词 |
| `PROMPT_USER_TEMPLATE` | `str` | `"用户任务：{task}\n请输出下一步动作："` | 用户提示词模板 |
| `PROMPT_FEW_SHOT_EXAMPLES` | `list[str]` | 2 条预置示例 | few-shot 示例 |
| `PROMPT_COT_ENABLED` | `bool` | `True` | CoT 推理引导开关 |

---

## 新增异常/工具类

| 名称 | 类型 | 说明 |
|------|------|------|
| `ErrorCategory` | `Enum` | 错误类别：`RETRYABLE` / `SKIP` / `FATAL` |
| `classify_error()` | 函数 | 根据异常类型返回 `ErrorCategory` |
| `PlatformInfo` | 类 | 平台检测与资源路径管理 |

---

## 新增依赖

无。所有改动基于已有依赖。
