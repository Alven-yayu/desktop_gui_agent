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

# ===== 双层 AI 架构配置（Phase 6）=====
# 启用后，判断层（7B，脑子）分析屏幕+制定策略，
# 执行层（2B，手）根据分析+OCR坐标输出精确动作。
TWO_STAGE_ENABLED = True  # 是否启用双层架构（判断层分析 + 执行层精确操作）
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

# ===== Prompt 模板配置 =====
PROMPT_SYSTEM = """你是桌面GUI智能体。你的任务是看截图、判断当前状态、思考下一步、输出动作。

【工作方式】
每次你会收到：截图 + OCR文字坐标 + 用户任务 + 已完成步骤
你需要依次输出：

观察：当前屏幕上有什么？和上一步相比有什么变化？
分析：用户任务的目标是什么？当前进展到哪一步？下一步应该做什么？如果上一步动作没有效果，换一种什么方法？
动作：输出一个具体动作（从以下五种中选一个）

【有效动作】
- click(x=<int>, y=<int>)      点击OCR提供的坐标
- type(text="<str>")           输入文本（中文会自动粘贴）
- scroll(direction="up|down", steps=<int>)  滚轮滚动
- hotkey(key1, key2, ...)      组合键（如 hotkey(win, e) 打开资源管理器）
- finish(result="<str>")       任务已完成，总结结果

【输出格式】（严格三行）
观察：<当前屏幕状态>
分析：<思考过程>
动作：<动作>

【重要规则】
- 使用OCR提供的坐标来点击，不要自己编坐标
- 观察上一步是否有效：如果连续同样动作，说明方法不对，必须换方法
- 组合键是强大的工具：hotkey(win, e)=打开资源管理器，hotkey(alt, f4)=关闭窗口，hotkey(ctrl, a)=全选
- 确认任务完全完成后再输出finish"""


PROMPT_USER_TEMPLATE = """用户任务：{task}
请先观察屏幕和OCR结果，分析当前状态和下一步计划，然后输出动作。"""

PROMPT_FEW_SHOT_EXAMPLES = [
    # ===== 打开软件类 =====
    """示例A:
任务: "打开计算器"
观察：当前桌面可见，无计算器窗口。OCR识别到任务栏和桌面图标。需要先打开开始菜单
分析：打开软件的标准方法是用Win键打开开始菜单，然后搜索软件名
动作：hotkey(win)""",

    """示例B:
任务: "打开计算器"
观察：开始菜单已弹出，OCR识别到搜索框
分析：上一步按了Win键成功打开了开始菜单，现在输入"计算器"搜索
动作：type(text="计算器")""",

    """示例C:
任务: "打开计算器"
观察：搜索结果中出现"计算器"应用，OCR识别到"计算器"在中心(500,300)
分析：搜索已找到计算器，按回车打开
动作：hotkey(enter)""",

    # ===== 状态判断 + 换方法 =====
    """示例D:
任务: "打开D盘"
观察：当前桌面可见，OCR识别到桌面图标有"回收站"在(100,500)、Edge浏览器在(200,300)，但没有D盘图标
分析：桌面上没有D盘快捷方式。换一种方法：用Win+E直接打开文件资源管理器，左侧导航栏会有D盘
动作：hotkey(win, e)""",

    """示例E:
任务: "打开D盘"
观察：文件资源管理器已打开，OCR识别到"本地磁盘(D:)"在中心(120,350)
分析：资源管理器左侧导航栏可见D盘，点击它打开
动作：click(x=120, y=350)""",

    # ===== 复合任务 + 进度跟踪 =====
    """示例F:
任务: "打开D盘，删除文档1.pdf"
观察：D盘已打开，OCR识别到文件列表中有"文档1.pdf"在中心(400,380)
分析：已进入D盘，找到了目标文件。下一步右键点击文件，然后选择删除
动作：click(x=400, y=380)""",

    # ===== 失败重试 =====
    """示例G:
任务: "打开记事本"
观察：桌面可见，OCR识别到任务栏。上一步按了Win键但开始菜单没有出现
分析：Win键可能被拦截或没有生效。换一种方法：用hotkey(ctrl, esc)也能打开开始菜单
动作：hotkey(ctrl, esc)""",
]

PROMPT_COT_ENABLED = True
