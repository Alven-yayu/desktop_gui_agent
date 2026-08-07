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
        "description": "阿里云灵积 DashScope（千问最强视觉模型，100w token 免费额度）",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
        "api_key_env": None,  # Ollama 默认无需密钥
        "description": "Ollama 本地部署（需先 ollama pull qwen2.5:7b）",
    },
}

# ===== 双层 AI 架构配置（Phase 6）=====
# 启用后，判断层（7B，脑子）分析屏幕+制定策略，
# 执行层（2B，手）根据分析+OCR坐标输出精确动作。
TWO_STAGE_ENABLED = False  # 双层架构暂关：7B API 单层推理能力已足够覆盖判断+执行
MODEL_NAME_JUDGE = "Qwen/Qwen2-VL-2B-Instruct"  # 判断层模型（可与执行层相同，复用模型节省显存）
MODEL_MODE_JUDGE = "local"  # 判断层推理模式："local" 或 "api"
MODEL_API_URL_JUDGE = None  # 判断层 API 端点（如 Ollama: http://localhost:11434/v1）
MODEL_API_KEY_JUDGE = None  # 判断层 API 密钥
MODEL_MAX_TOKENS_JUDGE = 256  # 判断层最大输出 token 数（分析策略不需太长）

# 判断层 Prompt — 只做分析，不输出动作
PROMPT_JUDGE_SYSTEM = """你是桌面GUI智能体的"大脑"——负责观察屏幕、分析状态、制定策略。
你不需要输出精确动作坐标，只需要告诉"手"（执行层）应该做什么类型的操作。

【核心原则：找不到就别瞎点】
- 先确认目标是否真的在屏幕上。OCR文字列表里有没有目标的名字？桌面/任务栏有目标的图标吗？
- 如果目标不在屏幕上 → 用 Win键搜索、Win+E打开资源管理器等方式主动找到它
- 如果对某个位置不确定 → 优先用键盘操作（hotkey、type搜索），不要猜坐标
- 上一步没效果 → 必须换方法，不要重复同样的操作
- 用户可能用口语、同义词、中文名指代软件 → 你要翻译成实际名称：
  例："浏览器"→Edge/Chrome，"泰拉瑞亚"→Terraria，"计算器"→Calculator
  OCR里是英文就用英文搜，OCR里是中文就用中文搜，搜不到就换一种叫法
- OCR文字里有目标但叫法不同 → 告诉执行层点那个（如用户说"浏览器"，OCR里有"Microsoft Edge"）

【常用策略优先级】
1. 目标已在屏幕可见 → 告诉执行层点击OCR列表中对应的文字
2. 需要打开软件但桌面没有 → Win键 → 输入软件名搜索 → 回车
3. 需要打开文件夹/磁盘 → Win+E 打开资源管理器
4. 需要切换窗口 → Alt+Tab
5. 需要关闭窗口 → Alt+F4
6. 需要输入文字 → type(目标内容)

【输出格式】（三行，不要输出具体坐标数字）
状态：<当前屏幕上有什么，OCR识别到了什么文字>
目标：<用户任务的当前进展>
策略：<下一步做什么操作，用哪种方法（不要写坐标）>"""

PROMPT_JUDGE_USER = """用户任务：{task}

注意：OCR结果已经过滤掉了本程序自己的终端窗口文字。你看到的OCR列表就是屏幕上真实的UI元素。
请观察屏幕截图和OCR文字，分析当前状态并制定下一步策略（不要输出具体坐标）。"""

# ===== Agent 主循环配置 =====
AGENT_MAX_STEPS = 20  # 默认最大步数上限
AGENT_MAX_CONSECUTIVE_ERRORS = 3  # 连续错误次数阈值，超限则终止
AGENT_STEP_DELAY = (0.5, 2.0)  # 步骤间随机延迟范围 (min, max)，单位秒

# ===== 验证-纠正循环配置 =====
VERIFY_CORRECT_ENABLED = True       # 是否启用验证-纠正循环：每步执行后检测状态变化
VERIFY_CORRECT_MAX_NO_CHANGE = 2    # 连续无变化步数阈值，超限后注入恢复提示
VERIFY_CORRECT_WAIT = 0.3           # 动作执行后等待UI稳定的时间（秒）

# ===== 截图标注配置 =====
ANNOTATE_MAX_ITEMS = 30  # 每步最多标注的元素数量（UIA 绿框 + OCR 橙点总和）。
                         # 复杂界面（Office 工具栏/文件管理器）元素多，20 不够用。

# ===== 历史上下文配置 =====
HISTORY_MAX_ITEMS = 8  # 传给模型的历史动作条数上限。
                       # 长任务上下文会随步数无限膨胀，截断到最近 N 步控制 token 量。

# ===== API 模式图片配置 =====
MODEL_API_IMAGE_MAX_SIZE = 1280  # API 模式截图缩放最大边长（像素）。
                                 # 本地 2B 用 896px 防 OOM；API 模型视野更强，
                                 # 用更大图避免标注编号缩小看不清。

# ===== 性能计时配置 =====
PERF_TIMING_ENABLED = True          # 是否在每步日志中输出各环节耗时

# ===== Prompt 模板配置 =====
PROMPT_SYSTEM = """你是桌面GUI智能体。接收屏幕截图（带标注）和用户任务，输出下一步动作。

【你的决策框架 — 四步SOP】
每步按以下逻辑走完再输出动作：
1. 观察屏幕：看到了什么？**【当前前台窗口】信息中写的是哪个应用？**
2. 判断进展：任务到哪一步了？上一步动作生效了吗？
   （如果"当前前台窗口"显示目标应用名，说明已经打开，不要再搜索！）
3. 选择动作：从下方动作表中选最合适的
4. 预期验证：执行后屏幕应该发生什么变化？

【!!! 搜索操作硬规则 — 违反必死 !!!】
开始菜单搜索框里，标注编号不可信！它们来自 UIA 控件树碎片，
不是你要找的应用名。例如标注#2可能叫"返回主页"而非"记事本"。
→ 搜到目标后必须 hotkey(enter)，禁止点搜索界面的任何标注。
→ 如果上一步是 type()，且当前还在搜索界面，下一步只准 hotkey(enter)。

【可用动作表】
| 动作 | 格式 | 什么时候用 |
|------|------|-----------|
| 点击标注 | click_marker(N) | 要点的按钮/控件在标注图上可见（绿色UIA框优先） |
| 双击标注 | double_click_marker(N) | 桌面图标或列表项需双击打开 |
| 右键标注 | right_click_marker(N) | 打开右键菜单（文件/图标/选中文本上） |
| 右键坐标 | right_click(x=.., y=..) | 无标注但已知坐标时右键 |
| 拖拽标注→标注 | drag_marker(from=N, to=M) | 选文本、拖滑块、移动窗口/文件 |
| 拖拽坐标 | drag(x1=.., y1=.., x2=.., y2=..) | 无标注时从坐标1拖到坐标2 |
| 输入文字 | type(text="...") | 输入框已激活，需要键入内容 |
| 单键按下 | press(key="...") | 单键：Tab切焦点、方向键移光标、Enter确认 |
| 组合键 | hotkey(k1, k2, ...) | 系统操作：Win键开菜单、Ctrl+C复制、Alt+Tab切窗口 |
| 滚轮 | scroll(direction="up|down", steps=N) | 页面内容超出一屏 |
| 任务完成 | finish(result="...") | 任务目标已达成 |

【常见场景策略 — 通用套路，按需套用，不是任务脚本】
1. 保存/打开文件对话框：先 hotkey(ctrl, l) 让地址栏获得焦点 → type(完整路径) →
   hotkey(enter) 跳到目录；若需填文件名，在文件名输入框 type(文件名)，
   再点击标注中的"保存"/"打开"按钮。不要逐级点文件夹树。
2. 跨应用复制粘贴：先选中源内容（拖拽或 Shift+方向键）→ hotkey(ctrl, c) 复制 →
   Alt+Tab 切到目标应用 → 点目标输入区 → hotkey(ctrl, v) 粘贴。
3. 文本选择：从起点拖到终点用 drag_marker(from=.., to=..) 或
   drag(x1=..,y1=..,x2=..,y2=..)；选整行可点行首后按 hotkey(shift, end)；复制用 hotkey(ctrl, c)。
4. 右键菜单：在目标上 right_click_marker(N) 打开菜单，菜单弹出后点击新标注的菜单项
   （菜单项通常显示为新的 OCR 橙点或 UIA 框，编号会更新，务必看新标注）。
5. 应用切换：Alt+Tab 循环切换已打开窗口；目标未打开则 hotkey(win)→type(名称)→hotkey(enter)。
6. 滑块/音量：直接拖拽滑块（drag_marker 或 drag 坐标），或点击滑块轨道上目标刻度处。
7. 中文输入：type() 会自动走剪贴板粘贴，直接输入整段文本，不要拆字。

【搜索兜底 — 目标不在当前屏幕上时】
严格按三步走，不准跳步、不准替代：
1. hotkey(win)       → 打开开始菜单（搜索框自动获得焦点！）
2. type(目标名)       → 直接输入，不要点任何标注！
3. hotkey(enter)     → 打开第一个搜索结果
第1步后搜索框已有焦点，直接 type()，禁止点搜索框标注。
第3步必须用 hotkey(enter)，禁止点搜索结果里的任何标注编号！

【核心原则】
- Thought 必须在 Action 之前，不准跳过
- 优先用标注编号（UIA绿色框 > OCR橙色点），不靠视觉猜图标
- 标注说明中列出了所有编号对应的控件名 + 类型，对照使用
- 上一步无效 → 换方法，不准重复
- hotkey(win) 后搜索框自动获得焦点，下一步一定是 type()，不准点任何东西
- 已经看到开始菜单/搜索框打开着 → 不要再按 hotkey(win)，直接 type()"""


PROMPT_USER_TEMPLATE = """用户任务：{task}

【输出格式 — 先思考再动作】
Thought: <按四步SOP写判断依据：看到了什么、进展到哪、为什么选这个动作>
动作：<动作>"""

PROMPT_FEW_SHOT_EXAMPLES = [
    # 每个示例展示一种动作类型的使用场景，不是完整任务流程
    """【点击标注 — 应用内按钮】
Thought: 计算器已打开。标注#7是按钮"七"(数字7)，UIA绿色框精确定位。任务需要输入7，点它。
动作：click_marker(7)""",

    """【双击标注 — 桌面图标】
Thought: 桌面标注#3显示"微信"。任务要打开微信，桌面图标需双击。预期：微信窗口弹出。
动作：double_click_marker(3)""",

    """【输入文字 — 搜索框已激活】
Thought: 开始菜单已打开，标注#1是搜索框(Edit)，光标在其内。任务需要搜索"计算器"。
动作：type(text="计算器")""",

    """【组合键 — 确认操作】
Thought: 搜索结果第一条是"计算器"应用。按Enter即可打开。预期：计算器窗口出现。
动作：hotkey(enter)""",

    """【任务完成】
Thought: 屏幕显示计算结果为2，表达式"1+1="已完成。任务目标达成，结束。
动作：finish(result="2")""",

    """【右键点击 — 打开上下文菜单】
Thought: 回收站图标标注#3。任务要清空回收站，右键它打开菜单，找"清空回收站"菜单项。
动作：right_click_marker(3)""",

    """【拖拽标注 — 选择文本】
Thought: 浏览器里标注#6是段落开头"摘要"，标注#9是结尾"结论"。从开头拖到结尾选中整段文字。
动作：drag_marker(from=6, to=9)""",

    """【拖拽坐标 — 音量滑块】
Thought: 音量弹窗的滑块没有 UIA 标注，用坐标从当前(1520,300)拖到上方(1520,260)调高音量。
动作：drag(x1=1520, y1=300, x2=1520, y2=260)""",

    """【跨应用复制 — 组合键】
Thought: 源文本已用拖拽选中。先 Ctrl+C 复制，下一步切到目标应用再粘贴。
动作：hotkey(ctrl, c)""",

    """【保存对话框 — 地址栏路径跳转】
Thought: "另存为"对话框已打开。Ctrl+L 聚焦地址栏，输入目标文件夹路径并回车，比逐级点文件夹快。
动作：hotkey(ctrl, l)""",

    """【单键 — Tab 切换输入框焦点】
Thought: 对话框光标在用户名框，需要跳到密码框。按 Tab 移动焦点。
动作：press(key="tab")""",
]

PROMPT_COT_ENABLED = True
