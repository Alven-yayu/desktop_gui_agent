# -*- coding: utf-8 -*-
# ===== SSL 证书修复 + PaddlePaddle 修复（Windows，必须放最前面）=====
import os
import ssl

import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()


def _patched_create_default_context(*args, **kwargs):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(certifi.where())
    return context


ssl.create_default_context = _patched_create_default_context

# ===== 提前加载 torch（Windows DLL 加载顺序要求）=====
try:
    import torch  # noqa: F401  # 必须在其他 C 扩展之前加载
except ImportError:
    pass

# ===== HuggingFace 缓存路径 + 镜像（国内加速）=====
if "HF_HOME" not in os.environ:
    os.environ["HF_HOME"] = "D:/models/huggingface"
if "HF_ENDPOINT" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# ===== 截图配置 =====
SCREEN_ID = 0  # 默认屏幕ID，0表示主屏幕
SCREENSHOT_REGION = None  # 截图区域 (x, y, width, height)，None 表示全屏

# ===== UI 定位配置 =====
UI_BOX_COLOR = "#00FF00"  # 检测框颜色（绿色）
UI_LINE_WIDTH = 2  # 检测框线宽（像素）

# ===== OCR 配置 =====
OCR_LANG = "ch"  # PaddleOCR 语言，ch=中英文混合
OCR_CONFIDENCE_THRESHOLD = 0.5  # 低于此置信度的识别结果丢弃

# ===== 鼠标控制配置 =====
MOUSE_MOVE_DURATION = 0.3  # 移动动画时长（秒），分段插值模拟平滑移动
MOUSE_CLICK_DELAY = (0.05, 0.2)  # 点击后随机延迟范围 (min, max)，单位秒
MOUSE_DRAG_DURATION = 0.5  # 默认拖拽时长（秒）

# ===== 键盘控制配置 =====
KEYBOARD_TYPE_DELAY = (0.03, 0.1)  # 字符间随机延迟范围 (min, max)，单位秒
KEYBOARD_HOTKEY_DELAY = (0.05, 0.15)  # 组合键按下/释放间隔随机延迟范围，单位秒
KEYBOARD_SCROLL_STEP = 120  # 每次滚动的像素量

# ===== Agent 模型配置 =====
MODEL_NAME = "Qwen/Qwen2-VL-2B-Instruct"  # 本地模型名称或 HuggingFace 路径
MODEL_MODE = "local"  # 推理模式："local"（本地 Transformers）或 "api"（远程 API）
MODEL_API_URL = None  # API 端点 URL（仅 api 模式使用）
MODEL_API_KEY = None  # API 密钥（仅 api 模式使用）
MODEL_MAX_TOKENS = 512  # 单次推理最大输出 token 数
MODEL_GPU_MEMORY_RATIO = 0.75  # GPU 显存使用比例（0~1），防止 OOM。8GB → 6GB
MODEL_GPU_MEMORY_GB = None  # 显存上限（GB），设为具体值则覆盖比例计算。None=自动按比例

# ===== API 预设端点 =====
# 通过 --api <name> 一键切换，无需手动填 URL 和 model name。
# 密钥统一从环境变量读取（优先）或在此文件填写。
API_PRESETS = {
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
        "api_key_env": "DASHSCOPE_API_KEY",
        "description": "阿里云灵积 DashScope（千问视觉模型 qwen-vl-max，读标注更准）",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
        "api_key_env": None,  # Ollama 默认无需密钥
        "description": "Ollama 本地部署（需先 ollama pull qwen2.5:7b）",
    },
}

# ===== Agent 主循环配置 =====
AGENT_MAX_STEPS = 20  # 默认最大步数上限
AGENT_MAX_CONSECUTIVE_ERRORS = 3  # 连续错误次数阈值，超限则终止
AGENT_STEP_DELAY = (0.5, 2.0)  # 步骤间随机延迟范围 (min, max)，单位秒

# ===== 验证-纠正循环配置 =====
VERIFY_CORRECT_ENABLED = True       # 是否启用验证-纠正循环：每步执行后检测状态变化
VERIFY_CORRECT_MAX_NO_CHANGE = 2    # 连续无变化步数阈值，超限后注入恢复提示
VERIFY_CORRECT_WAIT = 0.3           # 动作执行后等待UI稳定的时间（秒）
VERIFY_PIXEL_THRESHOLD = 0.01       # 像素对比阈值：动作前后截图差异比例超过此值
                                    # 视为"有变化"。用于检测 UIA 结构未变但显示
                                    # 内容变了的情况（如计算器 0→1→1+）。

# ===== 截图标注配置 =====
ANNOTATE_MAX_ITEMS = 30  # 每步最多标注的元素数量（UIA 绿框 + OCR 橙点总和）。
                         # 复杂界面（Office 工具栏/文件管理器）元素多，20 不够用。
ANNOTATE_NO_CROP_KEYWORDS = [
    "音量", "回收站", "任务栏", "桌面", "壁纸", "时钟", "系统托盘",
]  # 任务含这些词时不做窗口裁剪。裁剪会把任务栏/系统托盘裁掉，
   # 而这些系统级任务的目标恰恰在任务栏上（如音量图标、回收站）。

# ===== 历史上下文配置 =====
HISTORY_MAX_ITEMS = 8  # 传给模型的历史动作条数上限。
                       # 长任务上下文会随步数无限膨胀，截断到最近 N 步控制 token 量。

# ===== API 模式图片配置 =====
MODEL_API_IMAGE_MAX_SIZE = 1280  # API 模式截图缩放最大边长（像素）。
                                 # 本地 2B 用 896px 防 OOM；API 模型视野更强，
                                 # 用更大图避免标注编号缩小看不清。

# ===== API 模式采样配置 =====
MODEL_API_TEMPERATURE = 0.3  # API 推理温度。越低输出越确定、越少幻觉，
                             # 适合需要精确动作的 agent 场景（0.2~0.5 为宜）。
                             # 默认 API 无 temperature 时会用 0.7~1.0，随机性过高。

# ===== 性能计时配置 =====
PERF_TIMING_ENABLED = True          # 是否在每步日志中输出各环节耗时

# ===== Prompt 模板配置 =====
PROMPT_SYSTEM = """你是桌面GUI智能体。接收带标注的屏幕截图和用户任务，每次输出下一个动作。

【决策框架 — 固定四步SOP，每步都按此顺序思考】
1. 观察：屏幕上有什么？【当前前台窗口】是哪个应用？标注编号对应什么？
2. 判断：任务进行到哪一步？上一步动作生效了吗？目标是否已在屏幕上？
3. 动作：根据下方【动作选型】选最合适的一个动作
4. 验证：执行后屏幕应出现什么变化？符合预期再继续或收尾

【动作选型 — 按场景选动作】
| 场景 | 动作 |
|------|------|
| 按钮/图标在标注图上可见 | click_marker(N) 或 double_click_marker(N)（桌面图标需双击） |
| 需要右键菜单 | right_click_marker(N) |
| 输入框已聚焦，需输入内容 | type(text="...")（中文自动剪贴板粘贴） |
| 拖拽选文本/移滑块/移动窗口 | drag_marker(from=N, to=M) |
| 标准控件设值（滑块/下拉/复选框） | set_control(marker=N, value=X) |
| 打开应用/文件 | 搜索SOP：hotkey(win) → type(名称) → hotkey(enter) |
| 系统快捷键（复制/保存/切窗/关闭） | hotkey(k1, k2, ...)（Ctrl+C/Alt+Tab/Alt+F4等） |
| 单键导航 | press(key="tab"/"enter"/"delete"/方向键) |
| 页面内容超出屏幕 | scroll(direction="up|down", steps=N) |
| 任务目标已达成 | finish(result="...") |

【通用操作原则 — 决策逻辑，不是任务脚本】
- 标注优先：目标在标注图上就用编号点，禁止凭位置猜编号含义（编号只有1~30，超出必是幻觉）
- 键盘优先：打开/输入/保存/关闭优先用键盘（搜索SOP/type/hotkey），比鼠标点击可靠
- 计算器：**数字用鼠标点击按钮（标注编号），运算符（+ - × ÷ =）用键盘 type() 输入**。
  混合方式可避免两个坑：① 点错运算符（+点成-）；② 运算符后键盘输入的数字被计算器吞掉。
  **输入完整算式后必须按 Enter（计算器上=等于键）得出结果**，看到结果数字后再 finish。
- 找不到目标：用搜索SOP（hotkey(win)→type→hotkey(enter)），禁止瞎点
- type 后需要确认的场合（搜索/地址栏/文件名）必须 hotkey(enter)；禁止重复输入同一内容
- 文件对话框：hotkey(ctrl, s) 打开保存，hotkey(ctrl, l) 地址栏输入完整路径导航，避免点侧边栏
- 快捷键：任务提到 Ctrl+X/复制/保存/关闭窗口 → 直接转 hotkey，不找按钮点
  （hotkey(ctrl, s) 保存 / hotkey(alt, f4) 关闭窗口 / hotkey(ctrl, v) 粘贴）
- Excel/表格：用 excel_create(data="...") 一次性创建（行\n分隔、列逗号分隔），不手动开Excel点单元格
- 上一步无效 → 换方法，禁止重复同一动作
- 验证驱动：每步后观察屏幕判断是否生效；finish 前必须确认最终结果显示在屏幕上，禁止谎报

【关键约束】
- 终端/命令提示符/本程序运行窗口是受保护窗口，禁止关闭/最小化/退出
- "关闭当前窗口"类任务：目标就是任务开始时的前台窗口，关闭后立即 finish，禁止关其他窗口

【输出格式 — 必须思考在前，动作在后】
Thought: <按四步SOP写判断依据：观察到了什么、任务进展到哪、为什么选这个动作>
动作：<只输出一个动作>"""


PROMPT_USER_TEMPLATE = """用户任务：{task}

【输出要求 — 思考链强制】
先写 Thought（按四步SOP：观察→判断→动作→验证，说明依据），再写动作。
每次只输出一个动作。

Thought: <观察到了什么、任务进展、为什么选这个动作>
动作：<动作>"""

PROMPT_FEW_SHOT_EXAMPLES = [
    # 单步样例：每种动作类型一个，教"什么场景用什么动作"，不是完整任务流程
    """【点击标注 — 按钮可见时用编号点】
Thought: 保存对话框已打开，标注#4是"保存"按钮。任务要确认保存，点它。
动作：click_marker(4)""",

    """【键盘输入 — 输入框已聚焦】
Thought: 计算器已打开并聚焦。直接输入算式比逐个点按钮可靠，回车执行。
动作：type(text="1+1")""",

    """【滚动 — 内容超出屏幕】
Thought: 页面内容超出一屏，底部内容不可见，需要向下滚动查看。
动作：scroll(direction="down", steps=3)""",

    """【搜索兜底 — 目标不在屏幕上】
Thought: 桌面上没有计算器图标，任务要打开计算器，用搜索SOP：先按Win打开开始菜单。
动作：hotkey(win)""",

    """【任务完成 — 结果已显示】
Thought: 屏幕显示计算结果为2，任务目标已达成。
动作：finish(result="2")""",
]

PROMPT_COT_ENABLED = True
