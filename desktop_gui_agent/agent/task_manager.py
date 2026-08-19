# -*- coding: utf-8 -*-
"""任务管理器 — PDF 4.3.3

驱动 Agent 主循环：截图→OCR→模型→解析→执行，循环至任务完成或触发上限。
"""
import json
import os
import random
import re
import threading
import time
from datetime import datetime
from typing import Optional

from PIL import Image

from desktop_gui_agent.agent.action_parser import parse
from desktop_gui_agent.agent.model_client import ModelClient
from desktop_gui_agent.config import (
    AGENT_MAX_STEPS, AGENT_MAX_CONSECUTIVE_ERRORS, AGENT_STEP_DELAY,
    VERIFY_CORRECT_ENABLED, VERIFY_CORRECT_MAX_NO_CHANGE, VERIFY_CORRECT_WAIT,
    VERIFY_PIXEL_THRESHOLD,
    PERF_TIMING_ENABLED, ANNOTATE_MAX_ITEMS, ANNOTATE_NO_CROP_KEYWORDS,
    HISTORY_MAX_ITEMS,
)
from desktop_gui_agent.control.keyboard_controller import KeyboardController
from desktop_gui_agent.control.mouse_controller import MouseController
from desktop_gui_agent.perception.ocr_recognizer import recognize
from desktop_gui_agent.perception.screenshot import _is_terminal_window, capture
from desktop_gui_agent.perception.uia_parser import UiaParser
from desktop_gui_agent.utils.exceptions import ErrorCategory, OCRError, ScreenshotError, classify_error
from desktop_gui_agent.utils.logger import get_logger
from desktop_gui_agent.utils.platform import PlatformInfo

logger = get_logger(__name__)

# "关闭当前窗口"类任务的识别关键词。这些任务的目标是"任务开始时的前台窗口"，
# 必须以时间锚点界定目标，否则模型会把"当前"当活变量，关一个冒一个。
_CLOSE_WINDOW_KEYWORDS = (
    "关闭当前窗口", "关闭当前应用", "关闭当前", "关闭窗口",
    "关掉当前窗口", "关掉当前",
)


class TaskManager:
    """Agent 主循环控制器。

    接收用户任务描述，驱动"感知→决策→执行"循环，
    直到任务完成、达到步数上限或触发错误阈值。

    Attributes:
        max_steps: 最大步数上限。
        max_consecutive_errors: 连续错误次数阈值。
        mouse: 鼠标控制器实例。
        keyboard: 键盘控制器实例。
        model_client: 模型客户端实例。
    """

    def __init__(
        self,
        mouse: Optional[object] = None,
        keyboard: Optional[object] = None,
        model_client: Optional[object] = None,
        max_steps: int = AGENT_MAX_STEPS,
        max_consecutive_errors: int = AGENT_MAX_CONSECUTIVE_ERRORS,
        api_preset: Optional[str] = None,
    ):
        """初始化任务管理器。

        Args:
            mouse: 鼠标控制器，None 则使用默认 MouseController。
            keyboard: 键盘控制器，None 则使用默认 KeyboardController。
            model_client: 模型客户端，None 则使用默认 ModelClient。
            max_steps: 最大步数上限。
            max_consecutive_errors: 连续错误次数阈值。
            api_preset: API 预设名称（"dashscope" / "ollama"），None 则用本地模型。
        """
        self.max_steps = max_steps
        self.max_consecutive_errors = max_consecutive_errors
        self.api_preset = api_preset
        self.mouse = mouse
        self.keyboard = keyboard
        self.model_client = model_client
        self._marker_map: dict = {}  # 标注编号 → 坐标映射
        self._bad_marker_hint = ""  # 上一步模型输出无效标注编号时的纠正提示
        self._last_type_text: str = ""  # 上一步 type 的文本（防重复输入守卫）
        self._last_type_enter: bool = False  # 上一步 type 是否带 enter
        self._initial_window: dict = {}  # 任务开始时的前台窗口锚点（关闭窗口守卫用）
        logger.info(
            f"TaskManager 初始化，max_steps={max_steps}，"
            f"max_consecutive_errors={max_consecutive_errors}"
        )

    @staticmethod
    def _validate_coordinates(x: int, y: int, screen_width: int, screen_height: int) -> bool:
        """校验坐标是否在屏幕范围内。

        Args:
            x: X 坐标（像素）。
            y: Y 坐标（像素）。
            screen_width: 屏幕宽度（像素）。
            screen_height: 屏幕高度（像素）。

        Returns:
            True 表示坐标有效，False 表示越界。
        """
        if x < 0 or y < 0:
            return False
        if x >= screen_width or y >= screen_height:
            return False
        return True

    def _resolve_marker(self, marker: int) -> Optional[tuple]:
        """根据标注编号从 marker_map 解析屏幕坐标 (x, y)。

        Args:
            marker: 模型输出的标注编号。

        Returns:
            (x, y) 坐标元组；编号不存在时返回 None 并记录警告。
        """
        info = self._marker_map.get(marker, {})
        # 优先 click_point（新格式），回退 icon（旧格式兼容）
        x, y = info.get("click_point") or info.get("icon", (None, None))
        if x is None:
            keys = list(self._marker_map.keys())
            max_num = max(keys) if keys else 0
            logger.warning(f"标注 #{marker} 不存在，可用: {keys}")
            # 记录无效编号，下一步注入针对性纠正提示（打破模型幻觉循环）
            self._bad_marker_hint = (
                f"【!!! 纠正 — 标注编号无效 !!!】\n"
                f"你上一步输出的标注编号 #{marker} 不存在！标注编号只有 1~{max_num}。\n"
                f"不要输出无效编号。若任务是打开应用，请用搜索：hotkey(win)→type→hotkey(enter)。\n\n"
            )
            return None
        return int(x), int(y)

    def _marker_log(self, action_name: str, marker: int, x: int, y: int) -> None:
        """输出 marker 动作的定位日志，方便对照截图排查。

        Args:
            action_name: 动作名称（如 click_marker）。
            marker: 标注编号。
            x, y: 解析出的屏幕坐标。
        """
        info = self._marker_map.get(marker, {})
        source = info.get("source", "?")
        logger.info(
            f"[UIA] {action_name}(#{marker}) → ({x}, {y}) "
            f"\"{info.get('text', '')}\" ({source})"
        )

    # ===== 点击目标核对守卫 =====
    # 背景：模型会在屏幕上"看到"不存在的目标（幻觉），或把标注编号看错位，
    # 然后自信地输出 click_marker(N)。若执行层直接翻译编号点击，就会静默点错
    # （如任务要"打开计算器"，模型却点了 #8=哔哩哔哩）。此守卫在点击前用
    # 标注的真实文字做硬校验，把"模型说什么就点什么"变成"与事实不符就拦截"。

    # 泛称应用类别 → 真实应用名（小写子串匹配）。
    # 任务说"打开浏览器"时，桌面上的 Chrome/Edge 图标、前台 Edge 窗口都应视为
    # "浏览器已打开"，否则守卫会误判目标一直未打开而过度拦截。
    _GENERIC_CATEGORY_APPS: dict = {
        "浏览器": ["chrome", "edge", "firefox", "iexplore", "浏览器", "microsoft edge"],
        "资源管理器": ["explorer", "文件资源管理器", "此电脑"],
        "文件管理器": ["explorer", "文件资源管理器"],
    }

    @staticmethod
    def _relates_to_open_target(text: str, target: str) -> bool:
        """判断一段文字（窗口标题/标注文字）是否与"打开目标"相关。

        精确包含或共享子串（_texts_relate）之外，还处理泛称类别：
        target="浏览器" 时，文字含 "Chrome"/"Edge"/"浏览器" 都算相关，
        从而允许对真实浏览器图标/窗口的点击。

        Args:
            text: 要判断的文字（窗口标题或标注文字）。
            target: 打开目标应用名（_extract_open_target 的返回值）。

        Returns:
            True 表示文字与目标相关。
        """
        if not text or not target:
            return False
        if TaskManager._texts_relate(text, target):
            return True
        low = text.lower()
        for cat, members in TaskManager._GENERIC_CATEGORY_APPS.items():
            if target == cat:
                for m in members:
                    if m in low:
                        return True
        return False

    @staticmethod
    def _texts_relate(a: str, b: str) -> bool:
        """判断两段文字是否相关：子串包含，或共享任意 2 字子串。

        用于中英文混合场景：精确相等、包含（"计算器"⊂"计算器应用"）、
        以及共享二字词（"音量"与"音量控制"）都算相关。

        Args:
            a: 第一段文字。
            b: 第二段文字。

        Returns:
            True 表示两段文字相关。
        """
        a = (a or "").strip().lower()
        b = (b or "").strip().lower()
        if not a or not b:
            return False
        if a in b or b in a:
            return True
        # 中文词通常是 2 字起，共享任意 2 字子串视为同一主题
        for i in range(len(a) - 1):
            if a[i:i + 2] in b:
                return True
        for i in range(len(b) - 1):
            if b[i:i + 2] in a:
                return True
        return False

    @staticmethod
    def _is_name_like(text: str) -> bool:
        """判断标注文字是否为"名称型"（需要做任务关键词核对）。

        数字/单字符/纯符号按钮（计算器"1""7""C"、滚动箭头"+"）不是目标名称，
        跳过校验，避免误伤正常的数值/按钮点击。

        Args:
            text: 标注文字。

        Returns:
            True 表示是名称型文字，False 表示跳过关键词校验。
        """
        t = (text or "").strip()
        if len(t) < 2:
            return False
        # 纯数字/符号（按钮值）：如 "1"、"7"、"C"、"+"、"OK"
        if re.fullmatch(r"[\d\s+\-*/%.=()\[\]{}<>]+", t):
            return False
        # 含至少 2 个中文字符 → 应用名/按钮名（如"哔哩哔哩"、"保存"）
        if len(re.findall(r"[一-鿿]", t)) >= 2:
            return True
        # 英文单词（≥3 字母）→ 按钮名（如 "Save"、"Cancel"）
        if re.fullmatch(r"[a-zA-Z\s]{3,}", t):
            return True
        return False

    # ===== 打开应用 → 点击放行策略（防点击落点不可靠）=====
    # 用户策略（2026-08-08 实测反馈修正）：
    # - 桌面上的应用图标可以点击——只要编号对应的文字是对的（由 _marker_click_guard 核对）。
    # - 桌面上没有想打开的应用时，不乱点，用搜索打开。
    # - 搜索界面里的结果条目点选不可靠（会打开错应用），禁止点，改在已打开的搜索框直接输入。
    # - 目标应用已在前台，或在浏览器/应用内操作时，不拦。
    # 因此只在"前台是搜索界面"或"前台是无关应用窗口"时拦截；桌面和已打开的应用窗口放行。

    @staticmethod
    def _foreground_title() -> str:
        """获取当前前台窗口标题（仅 Windows；失败返回空串）。

        终端是 agent 自身的运行环境，不该被当作"当前应用"。若前台是终端窗口，
        返回空串（等价于桌面/无应用），避免守卫把终端标题（常含任务文本，
        如"搜索"）误判成搜索界面等。
        """
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return ""
            if _is_terminal_window(hwnd):
                return ""
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        except Exception:
            return ""

    @staticmethod
    def _foreground_class() -> str:
        """获取当前前台窗口的类名（仅 Windows；失败返回空串）。

        用于区分"桌面 shell"与普通应用窗口：桌面 shell 的类名是
        Progman / WorkerW，标题可能是 "Program Manager" 也可能是空串
        （Win11 的 WorkerW 标题为空），只认标题会误判。
        """
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return ""
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
            return buf.value
        except Exception:
            return ""

    @staticmethod
    def _is_desktop_shell(title: str, fg_class: str) -> bool:
        """判断前台窗口是否为桌面 shell。

        Win11 桌面 shell 有两种形态：Progman（标题 "Program Manager"）和
        WorkerW（标题为空串）。只认空标题会把 Progman 误判成应用窗口（open-guard
        拦截桌面图标点击、is_desktop 不生效导致偏移/双击失效）。统一用
        标题 + 窗口类判定，open-guard 与标注层共用同一套逻辑。

        Args:
            title: 前台窗口标题。
            fg_class: 前台窗口类名。

        Returns:
            True 表示前台是桌面 shell（应允许桌面图标点击/按桌面语义标注）。
        """
        title = (title or "").strip()
        return (
            not title
            or fg_class in ("Progman", "WorkerW")
            or title in ("Program Manager", "桌面")
        )

    @staticmethod
    def _calculator_display_hint() -> str:
        """读取计算器显示区内容（表达式 + 结果），注入模型上下文。

        背景：计算器界面有两行——表达式区（上行）和结果区（下行），模型从截图
        OCR 看不全（尤其运算符如 + 难识别），导致误判当前算式状态（如以为
        "1+1" 还缺一个 1 而重复输入）。UIA 能精确读到显示区文字
        （"表达式为 X"、"显示为 Y"），直接注入让模型知道真实状态。

        Returns:
            形如 "【计算器状态】表达式为 1+1，显示为 2\n" 的提示；非计算器
            窗口或读取失败返回空串。
        """
        try:
            from desktop_gui_agent.perception.uia_parser import UiaParser
            controls = UiaParser.get_foreground_controls()
        except Exception:
            return ""
        expr, result = "", ""
        for c in controls:
            name = str(c.get("name", "") or "")
            if name.startswith("表达式为"):
                expr = name
            elif name.startswith("显示为"):
                result = name
        if not expr and not result:
            return ""
        parts = [p for p in (expr, result) if p]
        return "【计算器状态】" + "，".join(parts) + "\n"

    @staticmethod
    def _excel_active_cell_hint() -> str:
        """读取 Excel 当前激活单元格地址（如 A1/B1），注入模型上下文。

        背景：模型逐格填数据时，用方向键移格后无法从截图判断"激活单元格
        已从 A1 移到 B1"（OCR 内容不变），会反复按方向键死循环。Excel 的
        激活单元格地址不通过 UIA 暴露（名称框 ValuePattern/LegacyIAccessible
        均为空），只能通过 COM 对象模型读取。这是"感知层读状态"，不是
        "操作层代劳"——填数据仍由模型用 type + 方向键完成。

        Returns:
            形如 "【Excel 状态】当前激活单元格：B1" 的提示（末尾带换行）；
            非 Excel 窗口或读取失败返回空串。
        """
        try:
            import win32com.client
            excel = win32com.client.GetActiveObject("Excel.Application")
            addr = str(excel.ActiveCell.Address).replace("$", "")
        except Exception:
            return ""
        return f"【Excel 状态】当前激活单元格：{addr}\n"

    @staticmethod
    def _extract_open_target(task: str) -> str:
        """从"打开X"类任务中提取目标应用名；非此类任务或目标模糊时返回空串。

        规则：
        - 匹配"打开/启动/开启/运行"后紧跟的名称。
        - 复合任务在第一个动作词（输入/搜索/查找等）处截断，
          如"打开记事本输入Hello"→"记事本"、"打开浏览器搜索Python"→"浏览器"。
        - 名称过长（>8 字）、过短（<2 字）、或含功能词（的/里/文件/文档等，
          如"打开桌面上的测试文档"）视为模糊目标，不返回（不触发守卫）。

        背景：守卫(_open_task_search_guard)依赖此函数拦截"搜索界面点击"。
        若复合任务提取失败返回空串，守卫会误判为"非打开X任务"而放行，
        模型就会在搜索/开始菜单界面用 OCR 坐标乱点（曾点中 Excel 磁贴）。

        Args:
            task: 用户任务文本。

        Returns:
            目标应用名，无法判定时返回空串。
        """
        if not task:
            return ""
        # "新建/创建 Excel/表格/工作簿"类任务：目标应用是 Excel，需先打开 Excel。
        # 任务词是"新建"而非"打开"，通用正则匹配不到，但打开 Excel 是前置步骤，
        # 必须同样触发搜索引导（否则模型点开始菜单图标点不开、死循环）。
        if re.search(r"(?:新建|创建|建)\s*(?:一个\s*)?(?:Excel|表格|工作簿|电子表格)", task, re.IGNORECASE):
            return "Excel"
        # 先按空格/标点切出"打开"后第一个词段（"打开计算器，输入 1+1"→"计算器"）。
        m = re.search(r"(?:打开|启动|开启|运行)\s*([^\s，。,!?！？]+)", task)
        if not m:
            return ""
        target = m.group(1)
        # 复合任务：词段内若含动作词，在其处截断（"记事本输入Hello"→"记事本"、
        # "计算器计算"→"计算器"）。非贪婪匹配，应用名本身含动作词前缀也安全
        # （"计算器"含"计算"但"计算器"不是"计算"后紧跟，不会误截）。
        m_act = re.match(
            r"(.+?)(?:搜索|输入|查找|点击|选择|设置|查看|计算|运行|启动|进入|新建|双击|创建)",
            target,
        )
        if m_act:
            target = m_act.group(1)
        if len(target) > 8 or len(target) < 2:
            return ""
        if any(w in target for w in ("的", "里", "中", "内", "文件", "文档", "目录")):
            return ""
        return target

    def _open_task_search_guard(self) -> bool:
        """"打开X"任务：只在"搜索界面点选"和"无关应用窗口"两种场景拦截点击。

        返回 True 表示放行点击；False 表示已拦截（注入纠正提示）。

        场景判定：
        - 目标应用已在前台（含泛称匹配，如"浏览器"↔Edge/Chrome）→ 放行。
        - 前台是搜索界面 → 拦截，改为在已打开的搜索框直接输入应用名。
        - 前台是桌面 → 放行（桌面应用图标可以点，正确性由 _marker_click_guard 核对）。
        - 前台是其他无关应用窗口 → 拦截，用搜索打开。
        - 系统级任务（音量/亮度/回收站等）目标不是应用窗口，一律放行。
        """
        task = str(getattr(self, "_current_task", "") or "")
        target = self._extract_open_target(task)
        if not target:
            return True  # 非"打开X"任务
        # 系统级任务：音量/回收站等目标不是应用窗口，不强制搜索
        if any(k in task for k in (
            "音量", "亮度", "回收站", "任务栏", "系统托盘", "快速设置", "通知"
        )):
            return True
        title = (self._foreground_title() or "").strip()
        if self._relates_to_open_target(title, target):
            return True  # 目标应用已在前台（含泛称匹配），点击放行
        if "搜索" in title or title in ("开始", "Start"):
            # 搜索界面：点选结果不可靠 → 拦截，改在已打开的搜索框直接输入应用名。
            # 不再建议按 win（搜索已打开，再按会空转）。
            # 若上一步已输入过目标文本（搜索框已有内容），引导直接回车打开，
            # 避免重复输入造成"记事本记事本"叠加、回车打开错误应用。
            if self._last_type_text == target:
                self._bad_marker_hint = (
                    f"【!!! 纠正 — 已输入“{target}”，直接回车打开 !!!】\n"
                    f"当前是搜索界面，你已输入“{target}”（搜索框已有内容）。\n"
                    f"请直接 hotkey(enter) 回车打开，不要重复输入，不要点搜索结果。\n\n"
                )
                logger.warning(
                    f"[OpenGuard] 搜索已输入 {target}，引导回车（前台={title!r}）"
                )
            else:
                self._bad_marker_hint = (
                    f"【!!! 纠正 — 搜索框已打开，直接输入应用名 !!!】\n"
                    f"当前是搜索界面，点选搜索结果不可靠。搜索框已聚焦，请直接 "
                    f"type(\"{target}\") 并回车打开，不要再按 win。\n\n"
                )
            logger.warning(
                f"[OpenGuard] 拦截搜索界面点击，改为直接输入 {target}（前台={title!r}）"
            )
            return False
        # 桌面：应用图标可以点，是否正确由 _marker_click_guard 核对。
        # 判定用 _is_desktop_shell（窗口类 + 标题双保险）：只认标题会把空标题
        # / Progman 桌面误判成"无关窗口"而拦截桌面图标点击（打开桌面应用会失败）。
        if self._is_desktop_shell(title, self._foreground_class()):
            return True
        # 其他无关应用窗口 → 拦截，用搜索打开
        self._bad_marker_hint = (
            f"【!!! 纠正 — 当前窗口不是目标应用，用搜索打开 !!!】\n"
            f"任务要打开“{target}”，但当前前台窗口是“{title}”，不是目标应用。\n"
            f"请用搜索：hotkey(win) → type(\"{target}\") → hotkey(enter)。\n\n"
        )
        logger.warning(
            f"[OpenGuard] 拦截无关窗口点击，改用搜索打开 {target}（前台={title!r}）"
        )
        return False

    @staticmethod
    def _is_calc_task(task: str) -> bool:
        """判断任务是否是"计算X"类任务（需操作计算器）。

        匹配含"计算/算/加减乘除"等计算意图词的任务。
        返回 True 时，对计算器的按键点击应改为一次性 type 输入。

        Args:
            task: 用户任务文本。

        Returns:
            True 表示是计算类任务。
        """
        if not task:
            return False
        return any(k in task for k in ("计算", "算一下", "算出", "1+", "1-", "等于"))

    @staticmethod
    def _is_calculator_button(info: dict) -> bool:
        """判断标注是否属于计算器按键（数字/运算符/等于等）。

        通过控件类型和名称判断：计算器按键是 Button，名称多为
        中文数字（一/二/三）、运算符（加/减/乘以/除以）或符号（等于）。

        Args:
            info: 标注信息字典。

        Returns:
            True 表示是计算器按键。
        """
        if not info:
            return False
        if info.get("source") != "uia":
            return False
        name = str(info.get("text", "") or "")
        # 计算器按键名：中文数字/运算符/等于/清除等
        _CALC_KEYS = (
            "一", "二", "三", "四", "五", "六", "七", "八", "九", "零",
            "加", "减", "乘以", "除以", "等于", "百分比", "平方", "平方根",
            "倒数", "清除", "清除条目", "Backspace", "正负", "十进制分隔符",
        )
        return any(name == k or name.startswith(k) for k in _CALC_KEYS)

    def _calculator_click_guard(self, marker: int) -> bool:
        """计算器按键点击守卫：任务要"计算X"时，禁止逐个点按键，改用 type 一次性输入。

        背景：计算器按键密集，模型逐键点击时看不到完整算式状态（尤其运算符
        OCR 难识别），容易误判重复输入（如"1+1"以为缺1又点一下变"11+1"）。
        一次性 type("1+1", enter=True) 最可靠，不依赖逐键点击和每步感知。

        Returns:
            True 表示放行点击（非计算器场景）；False 表示已拦截（提示用 type）。
        """
        task = str(getattr(self, "_current_task", "") or "")
        if not self._is_calc_task(task):
            return True
        if "计算器" not in (self._foreground_title() or ""):
            return True
        info = self._marker_map.get(marker, {})
        if not self._is_calculator_button(info):
            return True
        # 拦截计算器按键点击，提示用 type 一次性输入算式
        self._bad_marker_hint = (
            "【!!! 纠正 — 计算器不要逐个点按钮，用 type 一次性输入算式 !!!】\n"
            "计算器按键逐个点击不可靠（看不到完整算式，易误判重复输入）。\n"
            f"请直接 type(text=\"完整算式\", enter=True) 一次性输入并回车计算，"
            "例如 type(text=\"1+1\", enter=True)。\n"
            "不要点击任何数字/运算符按钮。\n\n"
        )
        logger.warning(
            f"[CalcGuard] 拦截计算器按键点击 #{marker} "
            f"\"{info.get('text', '')}\"，改用 type 输入"
        )
        return False

    def _marker_click_guard(self, marker: int, claimed_text: str = "") -> tuple:
        """点击前核对标注真实文字，防止模型点错目标。

        双重校验：
        - Tier 1（自证）：模型在动作里带了 text=...，则必须与标注真实文字相关，
          否则说明模型根本没看标注/在看幻影目标，拒绝。
        - Tier 2（任务关键词兜底）：模型没带 text 时，若任务有明确目标关键词、
          且标注是名称型文字且与任务无关，则拒绝，并要求模型明确确认或重看截图。

        Args:
            marker: 模型要点击的标注编号。
            claimed_text: 模型声称该标注是什么（可选，来自 click_marker(N, text=...)）。

        Returns:
            (ok, feedback)：ok=False 表示应拦截（feedback 为注入下一步的纠正提示）；
            ok=True 表示放行。
        """
        info = self._marker_map.get(marker, {})
        actual = str(info.get("text", "") or "").strip()
        task = str(getattr(self, "_current_task", "") or "")

        if claimed_text:
            claimed = claimed_text.strip()
            if actual and not self._texts_relate(claimed, actual):
                return False, (
                    f"【!!! 纠正 — 点击目标与标注不符 !!!】\n"
                    f"你声称标注 #{marker} 是“{claimed}”，但它的真实文字是“{actual}”。\n"
                    f"不要凭想象点标注。请重新看截图，用正确编号点击。\n\n"
                )
        elif actual and task and self._is_name_like(actual):
            # 与"打开目标"（含泛称类别，如"浏览器"↔Chrome/Edge）或任务关键词
            # 任一相关即放行；都无关才拒绝。
            target = self._extract_open_target(task)
            related = (
                self._relates_to_open_target(actual, target) if target else False
            )
            if not related:
                keywords = ModelClient._extract_keywords(task)
                related = any(
                    self._texts_relate(actual, kw) for kw in keywords
                )
            if not related:
                return False, (
                    f"【!!! 纠正 — 点击目标与任务无关 !!!】\n"
                    f"标注 #{marker} 的文字是“{actual}”，与任务“{task}”无关。\n"
                    f"请重新观察截图找正确目标；若确认要点击它，请输出 "
                    f"click_marker({marker}, text=\"{actual}\") 明确确认。\n\n"
                )
        return True, ""

    def _dispatch(self, action: dict) -> bool:
        """根据动作类型分发到对应的控制器方法。

        Args:
            action: 结构化动作字典，含 action_type 和 params。

        Returns:
            True 表示执行成功，False 表示失败。
        """
        action_type = action.get("action_type", "unknown")
        params = action.get("params", {})

        if action_type in ("click_marker", "double_click_marker", "right_click_marker"):
            # 计算器按键守卫：任务要"计算X"且前台是计算器时，禁止逐个点按键，
            # 强制模型改用 type("算式", enter=True) 一次性输入。
            if not self._calculator_click_guard(params["marker"]):
                return False
            # 打开应用守卫：任务要"打开X"且目标未在前台 → 拦截点击，强制键盘搜索。
            # 防"点计算器结果却打开Word"这类点击落点不可靠问题。
            if not self._open_task_search_guard():
                return False
            # 点击内容守卫：核对标注真实文字与任务/模型声称是否相符，防幻觉误点。
            # 拦截时不点击，把纠正提示注入下一步 prompt，让模型直面真实标注。
            ok, feedback = self._marker_click_guard(
                params["marker"], params.get("text", "")
            )
            if not ok:
                self._bad_marker_hint = feedback
                logger.warning(
                    f"[Guard] 拦截点击 #{params['marker']}: "
                    f"{feedback.splitlines()[1].strip()}"
                )
                return False
            pos = self._resolve_marker(params["marker"])
            if pos is None:
                return False
            x, y = pos
            if action_type == "click_marker":
                self._marker_log("click_marker", params["marker"], x, y)
                # 桌面上点图标自动双击：桌面图标单击只选中不打开，模型常因
                # "点了没反应"误判失败而退回搜索。桌面语义统一为双击打开，
                # 无需模型记住"桌面图标要双击"（通用能力，覆盖所有桌面图标）。
                if getattr(self, "_is_desktop", False):
                    return self.mouse.double_click(x, y)
                return self.mouse.click(x, y)
            elif action_type == "double_click_marker":
                self._marker_log("double_click_marker", params["marker"], x, y)
                return self.mouse.double_click(x, y)
            else:
                self._marker_log("right_click_marker", params["marker"], x, y)
                return self.mouse.right_click(x, y)
        elif action_type == "right_click":
            return self.mouse.right_click(params["x"], params["y"])
        elif action_type == "drag_marker":
            p1 = self._resolve_marker(params["from"])
            p2 = self._resolve_marker(params["to"])
            if p1 is None or p2 is None:
                return False
            x1, y1 = p1
            x2, y2 = p2
            logger.info(
                f"[UIA] drag_marker(#{params['from']}→#{params['to']}) "
                f"({x1},{y1})→({x2},{y2})"
            )
            return self.mouse.drag_from_to(x1, y1, x2, y2)
        elif action_type == "drag":
            return self.mouse.drag_from_to(
                params["x1"], params["y1"], params["x2"], params["y2"]
            )
        elif action_type == "press":
            return self.keyboard.press(params["key"])
        elif action_type in ("set_slider", "set_control"):
            # 通过 UIA 直接设标准控件值（滑块/输入框/复选/下拉/单选），
            # 不依赖鼠标精确点击。set_slider 是 set_control 的兼容别名。
            info = self._marker_map.get(params["marker"], {})
            bbox = info.get("bbox")
            if not bbox:
                logger.warning(f"标注 #{params['marker']} 无 bbox，无法设控件值")
                return False
            logger.info(
                f"[UIA] {action_type}(#{params['marker']}) → "
                f"value={params['value']} \"{info.get('text', '')}\""
            )
            return UiaParser.set_control_value(bbox, params["value"])
        elif action_type == "click":
            return self.mouse.click(params["x"], params["y"])
        elif action_type == "double_click":
            return self.mouse.double_click(params["x"], params["y"])
        elif action_type == "type":
            text = params["text"]
            enter = bool(params.get("enter"))
            # 防重复输入守卫：只要文本与上一步相同就拦截（无论是否带 enter）。
            # 背景：模型常"上一步已输入成功，没看结果又补一遍"，导致文本重复叠加
            # （如搜索框"记事本"→"记事本记事本"，回车打开错误应用）。
            # 只看文本不看 enter：因为重复输入相同文本本身几乎总是错误——若上一步
            # 输入已生效，重复是叠加；若未生效，应观察屏幕换方法而非原样重输。
            if self._last_type_text == text:
                self._bad_marker_hint = (
                    f"【!!! 纠正 — 你已经输入过“{text}”，不要重复输入 !!!】\n"
                    f"上一步已输入“{text}”，请等待结果并观察屏幕变化，不要再输入同一内容。\n"
                    f"若上一步输入未生效（如搜索框无内容），先点击输入框聚焦再输入。\n\n"
                )
                logger.warning(f"[RepeatGuard] 拦截重复输入: {text!r} enter={enter}")
                return False
            self._last_type_text = text
            self._last_type_enter = enter
            ok = self.keyboard.type(text)
            # type(..., enter=True)：输入后立即回车确认（搜索/地址栏/算式等）。
            # 一次动作完成，避免模型在两步之间做多余的中间判断。
            if ok and enter:
                # 计算器场景：输入算式前先清空显示区（按 C），避免上一步残留
                # 输入叠加（如已有"2+1"再输入"1+1"变"2+11+1"）。
                if self._is_calc_task(str(getattr(self, "_current_task", "") or "")) and \
                        "计算器" in (self._foreground_title() or ""):
                    self.keyboard.press("c")
                    time.sleep(0.2)
                    logger.info("[CalcGuard] type 前已清空计算器显示区")
                self.keyboard.press("enter")
            return ok
        elif action_type == "scroll":
            return self.keyboard.scroll(params["direction"], params["steps"])
        elif action_type == "hotkey":
            return self.keyboard.hotkey(*params["keys"])
        elif action_type == "finish":
            return True
        else:
            logger.warning(f"未知动作类型: {action_type}")
            return False

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
                # 每一步都重新执行终端最小化：运行中途用户可能把终端（或其它
                # 本进程窗口）点回前台，导致 OCR 读到终端内容、前台判定成"非桌面"
                # 而让桌面图标点击路径失效。每步重试让感知始终干净。
                from desktop_gui_agent.perception.screenshot import _init_terminal_avoidance
                _init_terminal_avoidance()
                return capture()
            except ScreenshotError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(
                        f"截图失败（第 {attempt + 1} 次），{0.5}s 后重试..."
                    )
                    time.sleep(0.5)
        raise last_error  # type: ignore[misc]

    @staticmethod
    def _capture_state() -> dict:
        """捕获当前 UI 状态快照，用于动作前后对比。

        收集前台窗口标题和 UIA 控件树特征，不依赖截图
        （UIA 比像素对比更快、更语义化）。

        Returns:
            状态特征字典，包含 window/uia_count/uia_types/uia_names。
            非 Windows 或获取失败时返回空特征。
        """
        state = {
            "fg_window_title": "",
            "uia_count": 0,
            "uia_type_counts": {},
            "uia_names": (),
        }

        # 前台窗口标题
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            state["fg_window_title"] = buf.value
        except Exception:
            pass

        # UIA 控件特征
        try:
            from desktop_gui_agent.perception.uia_parser import UiaParser
            controls = UiaParser.get_foreground_controls()
        except Exception:
            controls = []

        if controls:
            state["uia_count"] = len(controls)
            # 各类型数量
            type_counts = {}
            for c in controls:
                ct = c.get("control_type", "?")
                type_counts[ct] = type_counts.get(ct, 0) + 1
            state["uia_type_counts"] = type_counts
            # 前 15 个控件名称（排序后的元组，可哈希）
            names = tuple(
                sorted(c.get("name", "") for c in controls)[:15]
            )
            state["uia_names"] = names

        return state

    @staticmethod
    def _build_history_actions(history: list) -> list:
        """提取最近 N 步动作原文，防止长任务上下文随步数无限膨胀。

        Args:
            history: 步骤历史记录列表，每项含 "action_raw" 字段。

        Returns:
            最近 HISTORY_MAX_ITEMS 条动作原文列表。
        """
        actions = [h["action_raw"] for h in history if "action_raw" in h]
        return actions[-HISTORY_MAX_ITEMS:]

    # ===== 任务开始锚点 / 关闭窗口守卫 / 受保护窗口 =====
    # "关闭当前窗口"类任务必须以任务开始时的前台窗口为锚点界定目标，
    # 否则模型把"当前"当活变量，关一个冒一个，永远不会 finish。

    @staticmethod
    def _is_close_window_task(task: str) -> bool:
        """判断任务是否是"关闭当前窗口"类任务。

        Args:
            task: 用户任务描述文本。

        Returns:
            True 表示目标是"任务开始时的前台窗口"（关闭它即完成）。
        """
        return any(kw in task for kw in _CLOSE_WINDOW_KEYWORDS)

    @staticmethod
    def _capture_initial_window() -> dict:
        """捕获任务开始时的前台窗口，作为任务锚点。

        在终端最小化之后调用，锚点应落在真实用户窗口（而非本程序终端）。
        若前台仍是终端/命令提示符窗口（本程序运行环境），不设锚点——
        这类窗口不能作为"关闭当前窗口"的目标，返回空字典让守卫安全降级，
        避免与"运行任务先最小化终端"功能冲突。

        Returns:
            {"title": str, "hwnd": int}；不可用（桌面/终端/失败）时返回 {}。
        """
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return {}
            # 前台是终端 → 不是可关闭的用户窗口，且本程序运行窗口本就受保护。
            # 与"最小化终端"功能配合：最小化已把终端移开，这里做兜底，双保险。
            if _is_terminal_window(hwnd):
                return {}
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
            return {
                "title": buf.value,
                "hwnd": hwnd,
            }
        except Exception:
            return {}

    @staticmethod
    def _window_alive(hwnd) -> bool:
        """判断窗口句柄是否仍存在且可见。

        无法判断（非 Windows / 句柄无效）时保守返回 True，
        避免在不确定时误报"目标已关闭"。

        Args:
            hwnd: 窗口句柄。

        Returns:
            True 表示窗口还在（或无法判断），False 表示窗口已销毁/隐藏。
        """
        try:
            import ctypes
            return bool(ctypes.windll.user32.IsWindow(hwnd)) and bool(
                ctypes.windll.user32.IsWindowVisible(hwnd)
            )
        except Exception:
            return True

    def _build_window_context_extra(
        self, task: str, initial: dict, fg_title: str, fg_hwnd
    ) -> str:
        """构建注入模型上下文的任务开始锚点/完成守卫/安全警告。

        三类文本：
        1. 通用锚点（每步都注入）：【任务开始时的前台窗口】——让"当前窗口"
           类任务的目标有唯一时间锚点。
        2. 关闭任务完成守卫（代码级判据）：任务开始时的前台窗口已消失 →
           目标已关闭，强制提示模型立即 finish，禁止再关其他窗口。
        3. 受保护窗口安全警告：当前前台是终端/命令提示符窗口（含本程序终端）
           → 禁止对它做关闭/最小化/退出操作，防止重演"把 Claude Code 关了"。

        Args:
            task: 用户任务描述文本。
            initial: _capture_initial_window() 的返回。
            fg_title: 当前前台窗口标题。
            fg_hwnd: 当前前台窗口句柄。

        Returns:
            拼接好的提示文本，无内容时返回空字符串。
        """
        lines = []

        # 1. 通用锚点：记录任务下达时刻的窗口
        if initial.get("title"):
            lines.append(f"【任务开始时的前台窗口】{initial['title']}")
        elif initial:
            lines.append("【任务开始时的前台窗口】（桌面，无应用窗口）")

        # 2. 关闭任务完成守卫：初始窗口已消失 → 目标已完成，强制收尾
        if self._is_close_window_task(task) and initial.get("hwnd"):
            if not self._window_alive(initial["hwnd"]):
                lines.append(
                    "【!!! 目标窗口已关闭 — 任务完成 !!!】\n"
                    f"任务开始时的前台窗口「{initial.get('title', '')}」已关闭"
                    "（该窗口已不存在）。\n"
                    '"关闭当前窗口"任务已完成，请立即输出 '
                    'finish(result="已关闭窗口")。\n'
                    "禁止继续关闭其他任何窗口！"
                )

        # 3. 受保护窗口安全警告：当前前台是终端，绝不能关
        if fg_hwnd and _is_terminal_window(fg_hwnd):
            lines.append(
                "【!!! 安全警告 — 当前前台是终端/命令提示符窗口 !!!】\n"
                "这是本程序运行的终端窗口（受保护窗口），"
                "禁止对它执行关闭/最小化/退出操作！\n"
                "如果目标任务窗口已经关闭，请直接 finish。"
            )

        return ("\n".join(lines) + "\n") if lines else ""

    @staticmethod
    def _build_repeat_hint(history: list, fg_window_title: str) -> str:
        """检测模型最近反复执行同一动作，注入打断循环的纠正提示。

        泛化修复根因：任务 1/2（重复 type 死循环）和任务 3（点击/拖拽交替
        循环）的共同问题是模型反复执行同一动作且不自知，而现有的死循环检测
        只能"硬杀"（任务失败），不能帮模型跳出循环。此提示在重复出现时
        注入真实屏幕状态，告诉模型"已生效则收尾、未生效则换方法"。

        Args:
            history: 已执行步骤历史列表（含 action_type/action_params/success）。
            fg_window_title: 当前前台窗口标题，用于接地提示。

        Returns:
            提示文本；最近无重复动作时返回空字符串。
        """
        if len(history) < 2:
            return ""
        from collections import Counter
        recent = history[-4:]
        _CLICK_ACTIONS = (
            "click_marker", "double_click_marker", "click", "double_click",
        )
        # 连续点击过多且无 finish → 优先提示改用键盘输入（键盘优先原则兜底）。
        # 覆盖"计算器点按钮点出垃圾数字/表格逐个点单元格"这类场景：
        # 支持键盘输入的应用直接 type() 一次到位，比逐个点按钮可靠。
        # 放在重复检测之前：点击过多的场景给"换键盘"更可执行，避免模型继续瞎点。
        click_count = sum(
            1 for h in recent if h.get("action_type") in _CLICK_ACTIONS
        )
        if click_count >= 3:
            return (
                "【!!! 提示 — 点按钮太多次，改用键盘输入 !!!】\n"
                "你最近几步一直在点按钮。如果任务需要输入内容（计算器算式、"
                "表格数据、文字），请改用 type() 一次性输入全部内容再 hotkey(enter)，"
                "不要逐个点屏幕按钮！\n\n"
            )
        counts = Counter(
            (h.get("action_type"), str(h.get("action_params", {})))
            for h in recent
        )
        for (act, params), cnt in counts.most_common():
            if cnt < 2 or act == "finish":
                continue
            failed = any(
                h.get("action_type") == act
                and str(h.get("action_params", {})) == params
                and not h.get("success")
                for h in recent
            )
            state_desc = "执行失败" if failed else "已执行"
            return (
                "【!!! 纠正 — 你正在重复同一个动作 !!!】\n"
                f"最近几步你反复执行 {act} {params}（该动作最近{state_desc}）。\n"
                "如果动作已经生效，请立即进行下一步或 finish；"
                "如果没生效或失败，请换一种方法，禁止继续原样重复！\n"
                f"当前前台窗口是「{fg_window_title}」，请观察屏幕重新判断。\n\n"
            )
        return ""

    @staticmethod
    def _get_foreground_window_rect() -> Optional[tuple]:
        """获取前台窗口的屏幕矩形 (left, top, right, bottom)。

        用于把标注截图放大到前台窗口区域：完整桌面截图中应用窗口很小，
        标注编号缩放后模型读不清。裁剪后窗口填满图片，编号清晰。

        Returns:
            (left, top, right, bottom) 屏幕绝对坐标；
            无法获取或窗口不适合裁剪（桌面/全屏/过小）时返回 None。
        """
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w < 200 or h < 200:
                return None  # 窗口太小，裁剪无意义
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            if w >= sw * 0.95 and h >= sh * 0.95:
                return None  # 全屏窗口 ≈ 桌面，不裁剪（保留任务栏等上下文）
            return (rect.left, rect.top, rect.right, rect.bottom)
        except Exception:
            return None

    @staticmethod
    def _crop_image(image: Image.Image, rect: tuple, margin: int = 40) -> Image.Image:
        """把图片裁剪到指定矩形区域，外扩 margin 像素。

        Args:
            image: 原始图片。
            rect: (left, top, right, bottom) 裁剪矩形。
            margin: 外扩像素，避免裁掉窗口边缘控件。

        Returns:
            裁剪后的图片；裁剪后过小时返回原图。
        """
        left, top, right, bottom = rect
        w, h = image.size
        left = max(0, left - margin)
        top = max(0, top - margin)
        right = min(w, right + margin)
        bottom = min(h, bottom + margin)
        if right - left < 50 or bottom - top < 50:
            return image  # 裁剪后太小，放弃裁剪
        return image.crop((left, top, right, bottom))

    @staticmethod
    def _bbox_in_rect(bbox: tuple, rect: tuple, margin: int = 40) -> bool:
        """判断标注边界框中心是否落在窗口矩形内（含外扩 margin）。

        Args:
            bbox: 标注边界框 (x1, y1, x2, y2)。
            rect: 窗口矩形 (left, top, right, bottom)。
            margin: 外扩像素。

        Returns:
            True 表示标注在窗口内，应展示给模型。
        """
        if not bbox:
            return False
        x1, y1, x2, y2 = bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        left, top, right, bottom = rect
        return (left - margin) <= cx <= (right + margin) and \
               (top - margin) <= cy <= (bottom + margin)

    @staticmethod
    def _ordered_uia_controls(foreground: list, taskbar: list, no_crop: bool) -> list:
        """决定 UIA 控件标注顺序：系统级任务优先标注任务栏/系统托盘。

        标注有 max_items 上限（ANNOTATE_MAX_ITEMS），桌面图标多时任务栏控件
        会被挤出标注（如音量图标排桌面图标之后，40 上限一到就没了），模型因此
        看不到托盘目标而幻觉乱点桌面图标。系统级任务（音量/回收站/任务栏/托盘等，
        即 no_crop）目标区在任务栏/托盘，让它们排前面；普通任务保持前台窗口控件在前。

        Args:
            foreground: 前台窗口的 UIA 控件列表。
            taskbar: 任务栏/系统托盘的 UIA 控件列表。
            no_crop: 是否为系统级任务（不做窗口裁剪）。

        Returns:
            按标注优先级排序后的控件列表。
        """
        if no_crop:
            return taskbar + foreground
        return foreground + taskbar

    @staticmethod
    def _expand_rect(rect: tuple, margin: int, image_size: tuple) -> Optional[tuple]:
        """把窗口矩形外扩 margin 像素，并裁剪到图片边界内。

        Args:
            rect: (left, top, right, bottom)。
            margin: 外扩像素，避免裁掉窗口边缘控件。
            image_size: (width, height)，用于边界裁剪。

        Returns:
            外扩并夹紧后的矩形；窗口与图片无有效重叠时返回 None
            （例如 mock 小图 + 真实大窗口，裁剪无意义）。
        """
        left, top, right, bottom = rect
        w, h = image_size
        new_left = max(0, left - margin)
        new_top = max(0, top - margin)
        new_right = min(w, right + margin)
        new_bottom = min(h, bottom + margin)
        if new_right <= new_left or new_bottom <= new_top:
            return None
        return (new_left, new_top, new_right, new_bottom)

    @staticmethod
    def _translate_ctrl(ctrl: dict, offset_x: int, offset_y: int) -> dict:
        """把 UIA 控件的 bbox/click_point 平移到裁剪图坐标系。

        裁剪窗口后，控件坐标从屏幕坐标变为裁剪图局部坐标，
        标注时才能画到正确位置。

        Args:
            ctrl: UIA 控件字典（含 bbox、click_point）。
            offset_x, offset_y: 裁剪矩形左上角的屏幕坐标。

        Returns:
            平移后的控件字典副本。
        """
        new = dict(ctrl)
        bbox = ctrl.get("bbox")
        if bbox:
            x1, y1, x2, y2 = bbox
            new["bbox"] = (x1 - offset_x, y1 - offset_y, x2 - offset_x, y2 - offset_y)
        cp = ctrl.get("click_point")
        if cp:
            new["click_point"] = (cp[0] - offset_x, cp[1] - offset_y)
        return new

    @staticmethod
    def _translate_ocr(item: dict, offset_x: int, offset_y: int) -> dict:
        """把 OCR 结果项平移到裁剪图坐标系（用于裁剪后重新标注）。"""
        new = dict(item)
        bbox = item.get("bbox")
        if bbox:
            x1, y1, x2, y2 = bbox
            new["bbox"] = (x1 - offset_x, y1 - offset_y, x2 - offset_x, y2 - offset_y)
        return new

    @staticmethod
    def _screen_pixel_diff(img_before, img_after, sample: int = 64) -> float:
        """计算两张截图缩小后的像素差异比例 (0~1)。

        缩小到 sample×sample 再比较，速度快且对微小噪声不敏感。
        用于检测 UIA 结构未变但显示内容变了的情况（如计算器 0→1）。

        Args:
            img_before: 动作前截图（PIL Image）。
            img_after: 动作后截图。
            sample: 缩放边长，越小越快但灵敏度越低。

        Returns:
            差异像素占比 (0~1)，1 表示完全不同。
        """
        try:
            from PIL import ImageChops

            a = img_before.convert("RGB").resize((sample, sample))
            b = img_after.convert("RGB").resize((sample, sample))
            # 转灰度再统计：histogram 按通道独立统计，彩色 diff 的 hist[0]
            # 只覆盖 R 通道零值，会导致"相同图"也算出非零差异。
            diff = ImageChops.difference(a, b).convert("L")
            hist = diff.histogram()
            total = sum(hist)
            if total == 0:
                return 0.0
            changed = total - hist[0]  # 去掉完全相同的像素（灰度值为0）
            return changed / total
        except Exception:
            return 0.0

    @staticmethod
    def _has_state_changed(before: dict, after: dict) -> bool:
        """对比前后状态快照，判断是否有实质性变化。

        判断标准（满足任一即认为已变化）：
        1. 前台窗口标题不同
        2. UIA 控件总数变化 > 20%
        3. 控件类型种类发生变化
        4. 控件名称集合变化 > 30%

        Args:
            before: 动作前的状态快照。
            after: 动作后的状态快照。

        Returns:
            True 表示检测到变化（动作生效），False 表示无变化（动作无效）。
        """
        # 1. 前台窗口变了（最直观的信号）
        if before["fg_window_title"] != after["fg_window_title"]:
            return True

        b_count = before.get("uia_count", 0)
        a_count = after.get("uia_count", 0)

        # 如果都没有 UIA 数据，无法判断，保守认为有变化（避免误报）
        if b_count == 0 and a_count == 0:
            return True

        # 2. 控件总数变化 > 20%
        if b_count > 0:
            change_ratio = abs(a_count - b_count) / b_count
            if change_ratio > 0.2:
                return True
        elif a_count > 0:
            # 从无到有（或反之）——明显变化
            return True

        # 3. 控件类型种类变化
        b_types = set(before.get("uia_type_counts", {}).keys())
        a_types = set(after.get("uia_type_counts", {}).keys())
        if b_types != a_types:
            return True

        # 4. 控件名称集合变化 > 30%
        b_names = set(before.get("uia_names", ()))
        a_names = set(after.get("uia_names", ()))
        if b_names or a_names:
            all_names = b_names | a_names
            if all_names:
                common = b_names & a_names
                similarity = len(common) / len(all_names) if all_names else 1.0
                if similarity < 0.7:  # 变化 > 30%
                    return True

        return False

    def run(self, task: str, cancel_event: Optional[threading.Event] = None) -> dict:
        """执行 Agent 主循环。

        每步依次：截图 → OCR → 模型推理 → 动作解析 → 坐标校验 → 执行。
        循环直到：finish 动作 / 达到 max_steps / 连续错误超限 / 用户中断。

        Args:
            task: 用户自然语言任务描述。
            cancel_event: 外部传入的取消事件，set() 后循环立即终止。

        Returns:
            {"success": bool, "result": str, "steps": int, "error": str}
        """
        # 初始化默认依赖（允许通过 __init__ 注入 mock）
        if self.mouse is None:
            self.mouse = MouseController()
        if self.keyboard is None:
            self.keyboard = KeyboardController()
        if self.model_client is None:
            self.model_client = ModelClient(api_preset=self.api_preset)

        step = 0
        consecutive_errors = 0
        consecutive_no_change = 0  # 验证-纠正：连续无状态变化步数
        history = []
        result_text = ""
        # 当前任务文本：点击守卫核对标注与任务是否相关时使用。
        # 测试直接调 _dispatch 时不设置此值（为空），守卫自动跳过关键词校验。
        self._current_task = task
        # 每次任务重置防重复输入守卫状态
        self._last_type_text = ""
        self._last_type_enter = False

        # 终端窗口避让：先尝试最小化，失败则自动裁剪
        # （每次 run() 调用时执行一次，防止 OCR 自干扰）
        from desktop_gui_agent.perception.screenshot import _init_terminal_avoidance
        _init_terminal_avoidance()
        # OCR 引擎预热：首步 OCR 冷启动（PaddleOCR GPU 加载）约 20~70s。
        # 若等首次截图才启动，第一个动作会慢到像卡死。提前预热并把进度
        # 打出来，用户能确认程序在运行。
        from desktop_gui_agent.perception.ocr_recognizer import warm_up
        logger.info("OCR 引擎预热中（首次约需 20~70s 加载模型，请稍候）…")
        warm_up()

        # 任务开始锚点：记录终端最小化之后的前台窗口。
        # 短暂等待最小化生效、前台窗口切换稳定后再捕获——与"运行任务先最小化
        # 终端"功能配合，避免锚点捕获到正在最小化的终端（_capture_initial_window
        # 内部还会兜底过滤终端，双保险）。
        time.sleep(VERIFY_CORRECT_WAIT)
        self._initial_window = self._capture_initial_window()

        logger.info(f"开始执行任务: {task}")

        try:
            while step < self.max_steps:
                # 检查连续错误是否已达上限
                if consecutive_errors >= self.max_consecutive_errors:
                    logger.error(f"连续错误次数达到上限 {self.max_consecutive_errors}")
                    return {
                        "success": False,
                        "result": result_text,
                        "steps": step,
                        "error": "连续错误次数超限",
                    }

                step += 1

                # 检查用户是否请求终止
                if cancel_event and cancel_event.is_set():
                    logger.info("用户请求终止任务")
                    return {
                        "success": False,
                        "result": result_text,
                        "steps": step - 1,
                        "error": "用户终止",
                    }

                step_start = time.time()
                timings = {}

                # 1. 截图（带重试）
                try:
                    image = self._capture_with_retry(max_retries=2)
                    timings["screenshot"] = time.time() - step_start
                except ScreenshotError as e:
                    logger.error(f"截图失败（已重试）: {e}")
                    consecutive_errors += 1
                    continue

                # 保存截图
                screenshot_path = self._save_screenshot(image, step)

                # 2. OCR 识别
                ocr_start = time.time()
                try:
                    ocr_results = recognize(image)
                except OCRError as e:
                    logger.warning(f"OCR 失败（不计入错误计数）: {e}")
                    ocr_results = []
                timings["ocr"] = time.time() - ocr_start

                # 2.5 UIA 感知：获取前台窗口的原生 UI 控件树
                # （Windows 标准应用可精确定位按钮/文本框，不用猜坐标）
                uia_controls = []
                try:
                    uia_controls = UiaParser.get_foreground_controls()
                except Exception as e:
                    logger.debug(f"UIA 感知跳过: {e}")
                # 任务栏/系统托盘控件：前台窗口 UIA 覆盖不到音量图标等小目标。
                # 单独保存，标注顺序由 _ordered_uia_controls 决定（系统级任务
                # 优先标注任务栏，避免被标注上限挤掉）。
                taskbar_controls = []
                try:
                    taskbar_controls = UiaParser.get_taskbar_controls()
                except Exception as e:
                    logger.debug(f"UIA 任务栏感知跳过: {e}")

                # 3. 截图标注 + 模型推理
                # 融合标注：UIA 控件(绿色矩形框) + OCR 文字(橙色圆点)，
                # 统一编号，模型只需选编号，代码查表翻译为精确坐标
                from desktop_gui_agent.perception.screenshot import annotate_screenshot

                # 先取前台窗口标题（标注需要判断是否在桌面，也让模型知道当前应用）
                fg_window_title = ""
                fg_hwnd = None
                try:
                    import ctypes
                    fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetWindowTextW(fg_hwnd, buf, 256)
                    fg_window_title = buf.value
                except Exception:
                    pass

                # 终端是 agent 自身的运行环境，即使被最小化，GetForegroundWindow
                # 仍可能返回它（Claude Code 等终端会持续激活自己渲染输出）。此时
                # 前台判定失真，模型会把"终端"当成当前应用、又因它是受保护窗口而
                # 无从下手。把前台标题清空，让模型按桌面语义理解（终端已最小化、
                # 不出现在截图里）。fg_hwnd 保留：下游安全警告仍能触发（终端始终
                # 受保护，防止"关闭当前窗口"任务误关终端）。
                if fg_hwnd and _is_terminal_window(fg_hwnd):
                    fg_window_title = ""

                # 桌面判断：前台是桌面 shell 即认为在桌面——无标题的 WorkerW，
                # 或标题为 "Program Manager" 的 Progman（Win11 桌面 shell 有两种
                # 形态，只认空标题会把 Progman 误判成应用窗口，导致桌面图标偏移
                # 与自动双击不生效、点在文字上打不开）。
                # 桌面上 OCR 点击点需上偏以落在图标上；应用内取文字中心。
                fg_class = ""
                try:
                    import ctypes
                    cls_buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetClassNameW(fg_hwnd, cls_buf, 256)
                    fg_class = cls_buf.value
                except Exception:
                    pass
                is_desktop = self._is_desktop_shell(fg_window_title, fg_class)
                # 保存供 dispatch 使用：桌面上点图标要自动双击打开
                # （桌面图标单击只选中不打开，模型若用 click_marker 会"点了没反应"，
                # 进而误判失败退回搜索——这是通用能力，不是给特定应用的特例）。
                self._is_desktop = is_desktop

                # 获取前台窗口矩形：把标注聚焦到窗口区域。
                # 完整桌面标注时，小窗口按钮的编号是稀疏大号（如28、29），
                # 且可能超出 max_items 上限而没被标注。先裁剪窗口再标注，
                # 按钮就能获得 1、2、3… 密集清晰编号，模型读得准。
                # 但系统级任务（音量/回收站等）目标在任务栏/托盘，裁剪会裁掉，
                # 此时跳过裁剪保留完整上下文。
                no_crop = any(kw in task for kw in ANNOTATE_NO_CROP_KEYWORDS)
                # 系统级任务（音量/回收站/任务栏/托盘等）：目标区在任务栏/托盘，
                # 优先标注任务栏控件，避免被标注上限前的桌面图标挤掉（音量图标
                # 上次就被挤出标注，模型看不到托盘目标而幻觉乱点桌面图标）。
                uia_controls = self._ordered_uia_controls(
                    uia_controls, taskbar_controls, no_crop=no_crop
                )
                fg_rect = None
                if not is_desktop and not no_crop:
                    fg_rect = self._get_foreground_window_rect()
                    if fg_rect:
                        fg_rect = self._expand_rect(
                            fg_rect, margin=40, image_size=image.size
                        )

                if fg_rect:
                    # 裁剪原始截图到窗口，并平移 UIA/OCR 坐标到裁剪图坐标系
                    crop_img = image.crop(fg_rect)
                    offset_x, offset_y = fg_rect[0], fg_rect[1]
                    # 只保留窗口内的控件（任务栏在窗口外，裁剪后应排除）
                    uia_in_window = [
                        c for c in uia_controls
                        if self._bbox_in_rect(c.get("bbox"), fg_rect)
                    ]
                    uia_local = [
                        self._translate_ctrl(c, offset_x, offset_y)
                        for c in uia_in_window
                    ]
                    ocr_local = [
                        self._translate_ocr(o, offset_x, offset_y)
                        for o in ocr_results
                    ]
                    annotated_image, marker_map = annotate_screenshot(
                        crop_img, ocr_local, max_items=ANNOTATE_MAX_ITEMS,
                        task=task, uia_controls=uia_local, is_desktop=False,
                    )
                    # 点击坐标转回屏幕坐标（_dispatch 直接用屏幕坐标点击）
                    for info in marker_map.values():
                        cx, cy = info["click_point"]
                        info["click_point"] = (cx + offset_x, cy + offset_y)
                else:
                    annotated_image, marker_map = annotate_screenshot(
                        image, ocr_results, max_items=ANNOTATE_MAX_ITEMS, task=task,
                        uia_controls=uia_controls, is_desktop=is_desktop,
                    )
                self._marker_map = marker_map  # 保存供 _dispatch 翻译编号
                # 保存标注后的截图（模型实际看到的画面），排查"乱点/幻觉"时
                # 可对照编号与真实标注。原图保存在 step_{N}.png，标注图 step_{N}_annotated.png。
                try:
                    self._save_screenshot(annotated_image, step, suffix="_annotated")
                except Exception as e:
                    logger.debug(f"保存标注截图失败: {e}")
                # 构建标注文字说明（区分 UIA 矩形框和 OCR 圆点）
                def _build_marker_line(num: int, info: dict) -> str:
                    source = info.get("source", "?")
                    text = info.get("text", "")
                    cp = info.get("click_point", (0, 0))
                    if source == "uia":
                        ctrl_type = info.get("control_type", "")
                        return f"  #{num}[{ctrl_type}]: \"{text}\" ({cp[0]},{cp[1]})"
                    else:
                        return f"  #{num}[文字]: \"{text}\" ({cp[0]},{cp[1]})"

                marker_text_lines = [
                    _build_marker_line(num, info)
                    for num, info in marker_map.items()
                ]

                # 验证-纠正：连续无变化时，在下一次模型查询前注入恢复提示
                recovery_hint = ""
                if VERIFY_CORRECT_ENABLED and consecutive_no_change >= VERIFY_CORRECT_MAX_NO_CHANGE:
                    recovery_hint = (
                        "【!!! 纠正提示 — 上一步无效 !!!】\n"
                        "前面步骤没有让屏幕发生任何变化，上一次操作没有生效。\n"
                        "请换一种方法达成目标，严格禁止重复刚才做过的操作！\n\n"
                    )
                    logger.warning(
                        f"[Verify] 注入恢复提示（连续{consecutive_no_change}次无变化）"
                    )

                # 当前鼠标位置：模型规划拖拽/右键时需要知道鼠标在哪。
                # 防御性处理：mock 场景下 get_position 可能返回非元组。
                cursor_line = ""
                try:
                    pos = self.mouse.get_position()
                    if isinstance(pos, (tuple, list)) and len(pos) == 2:
                        cursor_line = (
                            f"【当前鼠标位置】({int(pos[0])}, {int(pos[1])})\n"
                        )
                except Exception:
                    pass

                # 基础上下文始终保留（即使 0 个标注，模型也需要知道光标/前台窗口）
                # 本机路径：文件对话框保存/打开时需要真实路径（模型无法猜用户名）
                try:
                    desktop_p = os.path.expanduser("~/Desktop").replace("\\", "/")
                    home_p = os.path.expanduser("~").replace("\\", "/")
                    path_line = f"【本机路径】桌面: {desktop_p} | 用户目录: {home_p}\n"
                except Exception:
                    path_line = ""

                # 计算器显示区：UIA 精确读"表达式为 X / 显示为 Y"，注入让模型
                # 知道真实算式状态，避免从截图猜两行显示而误判重复输入。
                calc_hint = ""
                if "计算器" in fg_window_title or "计算器" in task:
                    calc_hint = self._calculator_display_hint()

                # Excel 激活单元格：COM 读当前地址（A1/B1），注入让模型知道
                # 光标在哪，避免逐格填时反复按方向键死循环。
                excel_cell_hint = ""
                if "Excel" in fg_window_title or "工作簿" in fg_window_title:
                    excel_cell_hint = self._excel_active_cell_hint()

                # 上一步模型输出了无效标注编号 → 注入针对性纠正提示
                bad_marker_hint = self._bad_marker_hint
                self._bad_marker_hint = ""  # 用后重置，避免重复

                # 重复动作纠正：模型反复执行同一动作时注入打断提示，
                # 给它跳出循环的机会（泛化修复，见 _build_repeat_hint）
                repeat_hint = self._build_repeat_hint(history, fg_window_title)

                # 任务开始锚点 / 关闭任务完成守卫 / 受保护窗口警告
                anchor_extra = self._build_window_context_extra(
                    task, self._initial_window, fg_window_title, fg_hwnd
                )

                marker_extra = (
                    bad_marker_hint +
                    recovery_hint +
                    repeat_hint +
                    anchor_extra +
                    cursor_line +
                    path_line +
                    calc_hint +
                    excel_cell_hint +
                    f"【当前前台窗口】{fg_window_title}\n"
                )
                # 标注说明仅在有标注时追加（含 0 个标注的空桌面）
                if marker_text_lines:
                    marker_extra += (
                        "【屏幕标注说明】\n"
                        "  绿色矩形框 = Windows 应用按钮/控件（来自 UIA）\n"
                        "  橙色圆点 = 非标准 UI 文字（来自 OCR）\n"
                        "  请观察标注在图中的实际位置，用编号指定目标：\n"
                        + "\n".join(marker_text_lines)
                    )

                model_start = time.time()
                history_actions = self._build_history_actions(history)
                try:
                    model_output = self.model_client.query(
                        annotated_image, task, context=history_actions,
                        ocr_results=ocr_results, extra_text=marker_extra,
                    )
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
                timings["model"] = time.time() - model_start

                if not model_output:
                    logger.warning("模型返回空输出")
                    consecutive_errors += 1
                    continue

                # 4. 动作解析
                action = parse(model_output)
                if action["action_type"] == "unknown":
                    logger.warning(f"无法解析模型输出: {model_output[:100]}")
                    consecutive_errors += 1
                    continue

                # 死循环检测：连续3次输出相同动作 → 强制终止
                if len(history) >= 2:
                    last_two = [
                        (h.get("action_type"), h.get("action_params", {}))
                        for h in history[-2:]
                    ]
                    current = (action["action_type"], action.get("params", {}))
                    if last_two[0] == last_two[1] == current:
                        logger.warning("检测到连续3次相同动作，模型可能陷入死循环，强制终止")
                        return {
                            "success": False,
                            "result": result_text,
                            "steps": step,
                            "error": "模型陷入死循环（连续3次相同动作）",
                        }

                # 5. 坐标校验（click / right_click / drag 坐标形式）
                # 越界坐标会导致鼠标点到屏幕外，视为一次错误
                screen_w, screen_h = image.size
                invalid = False
                if action["action_type"] in ("click", "right_click"):
                    x, y = action["params"]["x"], action["params"]["y"]
                    if not self._validate_coordinates(x, y, screen_w, screen_h):
                        logger.warning(f"坐标越界: ({x}, {y})，屏幕={screen_w}x{screen_h}")
                        invalid = True
                elif action["action_type"] == "drag":
                    p = action["params"]
                    pts = [(p["x1"], p["y1"]), (p["x2"], p["y2"])]
                    for px, py in pts:
                        if not self._validate_coordinates(px, py, screen_w, screen_h):
                            logger.warning(
                                f"drag 坐标越界: ({px}, {py})，屏幕={screen_w}x{screen_h}"
                            )
                            invalid = True
                            break
                if invalid:
                    consecutive_errors += 1
                    continue

                # 6. 执行动作（含验证-纠正循环）
                # 动作前：捕获 UI 状态快照
                pre_state = self._capture_state() if VERIFY_CORRECT_ENABLED else None

                exec_start = time.time()
                success = self._dispatch(action)
                timings["execution"] = time.time() - exec_start

                # 动作后：等待 UI 稳定，捕获新状态并对比
                if pre_state is not None:
                    time.sleep(VERIFY_CORRECT_WAIT)
                    post_state = self._capture_state()
                    changed = self._has_state_changed(pre_state, post_state)
                    if not changed:
                        # UIA/标题没变化，但显示内容可能变了（计算器 0→1、文档内容等）。
                        # 用像素对比兜底：动作前后的截图差异超过阈值即视为有变化。
                        try:
                            post_img = capture()
                            ratio = self._screen_pixel_diff(image, post_img)
                            if ratio > VERIFY_PIXEL_THRESHOLD:
                                logger.info(
                                    f"[Verify] 步骤{step} 像素差异 {ratio:.1%}，"
                                    f"判定为有变化"
                                )
                                changed = True
                        except Exception as e:
                            logger.debug(f"[Verify] 像素对比失败: {e}")
                    if not changed:
                        consecutive_no_change += 1
                        logger.warning(
                            f"[Verify] 步骤{step} 无状态变化 "
                            f"(连续{consecutive_no_change}次)"
                        )
                        # 动作未产生任何屏幕变化（type 打空/点击未生效）时，重置
                        # 重复输入守卫。否则模型想重试"上次没生效的输入"会被
                        # RepeatGuard 误判为重复而拦截，陷入"不能点也不能输"死循环。
                        if not success:
                            self._last_type_text = ""
                            self._last_type_enter = False
                            logger.info(
                                f"[Verify] 步骤{step} 动作未生效，重置重复输入守卫"
                            )
                    else:
                        if consecutive_no_change > 0:
                            logger.info(
                                f"[Verify] 步骤{step} 状态已恢复变化"
                            )
                        consecutive_no_change = 0

                # 7. 性能计时日志（在记录历史之前，确保 finish 步骤也输出）
                if PERF_TIMING_ENABLED:
                    step_total = time.time() - step_start
                    logger.info(
                        f"[Perf] 步骤{step} 总耗时{step_total:.2f}s | "
                        f"截图={timings.get('screenshot',0):.3f}s "
                        f"OCR={timings.get('ocr',0):.3f}s "
                        f"模型={timings.get('model',0):.3f}s "
                        f"执行={timings.get('execution',0):.3f}s"
                    )

                # 8. 记录本步历史
                history.append({
                    "step": step,
                    "screenshot": screenshot_path,
                    "ocr_results": ocr_results,
                    "model_output": model_output,
                    "action_type": action["action_type"],
                    "action_params": action.get("params", {}),
                    "action_raw": model_output,
                    "success": success,
                    "timings": timings,
                })

                if not success:
                    logger.warning(f"动作执行失败: {action['action_type']}")
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0  # 成功后重置连续错误计数

                # 9. 判断终止条件
                if action["action_type"] == "finish":
                    result_text = action["params"].get("result", "任务完成")
                    logger.info(f"任务完成: {result_text}")
                    return {
                        "success": True,
                        "result": result_text,
                        "steps": step,
                        "error": None,
                    }

                # 10. 步骤间延迟
                min_delay, max_delay = AGENT_STEP_DELAY
                time.sleep(random.uniform(min_delay, max_delay))

            # 达到 max_steps
            logger.warning(f"达到最大步数上限 {self.max_steps}")
            return {
                "success": False,
                "result": result_text,
                "steps": step,
                "error": "达到最大步数上限",
            }

        except KeyboardInterrupt:
            logger.info("用户中断（Ctrl+C），保存已执行步骤")
            return {
                "success": False,
                "result": result_text,
                "steps": step,
                "error": "用户中断",
            }
        finally:
            # 保存完整历史记录
            self._save_history(history, task)

    def _save_screenshot(self, image: Image.Image, step: int, suffix: str = "") -> str:
        """保存截图到 logs/screenshots/ 目录。

        Args:
            image: 截图 PIL Image。
            step: 当前步骤编号。
            suffix: 文件名后缀（如 "_annotated" 表示标注后的图），空则原图。

        Returns:
            截图保存路径。
        """
        log_dir = PlatformInfo.get_log_dir() / "screenshots"
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"step_{step}{suffix}.png")
        image.save(path, "PNG")
        return path

    def _save_history(self, history: list, task: str) -> None:
        """将任务执行历史保存为 JSON 文件。

        Args:
            history: 步骤历史记录列表。
            task: 原始任务描述。
        """
        log_dir = PlatformInfo.get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%H%M%S")
        path = os.path.join(log_dir, f"task_{timestamp}.json")
        record = {"task": task, "history": history}
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"任务历史已保存: {path}")
        except Exception as e:
            logger.error(f"保存任务历史失败: {e}")
