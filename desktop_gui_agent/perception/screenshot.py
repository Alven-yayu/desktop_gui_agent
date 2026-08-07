# -*- coding: utf-8 -*-
"""屏幕截图模块 — Windows/macOS/Linux 跨平台支持。

Windows 平台提供终端窗口最小化功能，
在截图前隐藏控制台窗口，从源头避免 OCR 识别到 agent 自身的日志文字。

实现策略（按优先级）：
  1. 经典控制台 (cmd/PowerShell) → GetConsoleWindow() + ShowWindow(SW_MINIMIZE)
  2. 现代终端 (Windows Terminal/VS Code) → EnumWindows 按 PID 查找并最小化
  3. 回退方案：EnumWindows 获取窗口矩形 → capture() 中裁掉该区域
"""
import ctypes
import os
import sys
from ctypes import wintypes
from typing import List, Optional, Tuple

import mss
from PIL import Image

from desktop_gui_agent.config import ANNOTATE_MAX_ITEMS, SCREEN_ID, SCREENSHOT_REGION
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# 缓存当前进程窗口的屏幕矩形（用于裁剪回退方案）
_own_window_rects: List[Tuple[int, int, int, int]] = []


# ===== 终端窗口控制（Windows）=====

def minimize_console() -> bool:
    """最小化当前进程的控制台窗口（仅 Windows 生效）。

    策略：枚举当前进程及所有祖先进程的可见窗口，全部最小化。
    这样无论经典控制台(cmd)、Windows Terminal、VS Code Terminal 都能覆盖。

    Returns:
        True 表示成功最小化至少一个窗口，False 表示无可最小化的窗口。
    """
    if sys.platform != "win32":
        return False
    try:
        # 收集当前进程及其祖先进程的所有 PID
        pids = _get_ancestor_pids(os.getpid())
        # 枚举这些 PID 的可见窗口并最小化
        minimized = _minimize_windows_by_pids(pids)
        if minimized:
            logger.debug(f"已最小化 {minimized} 个终端窗口 (PIDs: {pids})")
            return True

        # 回退：经典 GetConsoleWindow（cmd.exe 等）
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd != 0:
            ctypes.windll.user32.ShowWindow(hwnd, 6)
            logger.debug("经典控制台窗口已最小化（回退）")
            return True

        return False
    except Exception:
        return False


def get_terminal_rects() -> List[Tuple[int, int, int, int]]:
    """获取当前进程终端窗口的屏幕矩形列表（用于截图裁剪回退）。

    仅在 minimize_console() 失败后调用，作为最后的兜底方案。
    结果会被缓存，每次 capture() 时用于裁剪。

    Returns:
        矩形列表，每个为 (left, top, right, bottom)。
    """
    global _own_window_rects
    if _own_window_rects:
        return _own_window_rects

    if sys.platform != "win32":
        return []

    try:
        _own_window_rects = _enum_own_window_rects()
        if _own_window_rects:
            logger.info(
                f"检测到 {len(_own_window_rects)} 个本进程窗口，"
                f"截图时将自动裁剪"
            )
    except Exception:
        _own_window_rects = []

    return _own_window_rects


def crop_terminal_from_screenshot(image: Image.Image) -> Image.Image:
    """如果已知终端窗口位置，将对应区域替换为纯色（避免 OCR 误读）。

    注意：此函数不会修改原始图像，返回新图像。

    Args:
        image: 原始截图。

    Returns:
        裁剪后的截图（或原始截图，如果没有已知的终端窗口区域）。
    """
    rects = get_terminal_rects()
    if not rects:
        return image

    # 用截图边缘颜色填充（比纯黑更自然），简单起见用灰色
    fill_color = (128, 128, 128)  # 中灰，干扰最小
    for (left, top, right, bottom) in rects:
        # 坐标裁剪到图像范围内
        w, h = image.size
        left = max(0, left)
        top = max(0, top)
        right = min(w, right)
        bottom = min(h, bottom)
        if right > left and bottom > top:
            # 用图像该区域周围颜色的均值填充
            region = image.crop((left, top, right, bottom))
            try:
                avg_color = tuple(
                    int(sum(c) / len(c))
                    for c in zip(*list(region.getdata()))
                )
            except (ValueError, ZeroDivisionError):
                avg_color = fill_color
            # 在图像上绘制填充矩形
            from PIL import ImageDraw
            draw = ImageDraw.Draw(image)
            draw.rectangle([left, top, right, bottom], fill=avg_color)

    return image


# ===== 内部：进程树 + 窗口枚举 =====

def _get_ancestor_pids(pid: int) -> List[int]:
    """向上追溯进程树，返回从当前进程到根进程的所有 PID。

    例如：python.exe → powershell.exe → WindowsTerminal.exe → ...

    Args:
        pid: 起始进程 PID。

    Returns:
        祖先进程 PID 列表（包含自身）。
    """
    pids = [pid]
    current = pid
    visited = {pid}
    # 最多追溯 10 层，防止死循环
    for _ in range(10):
        parent = _get_parent_pid(current)
        if parent in (0, None) or parent in visited:
            break
        visited.add(parent)
        pids.append(parent)
        current = parent
    return pids


def _get_parent_pid(pid: int):
    """获取指定 PID 的父进程 PID（仅 Windows）。

    使用 CreateToolhelp32Snapshot + Process32First/Next。
    """
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    snapshot = ctypes.windll.kernel32.CreateToolhelp32Snapshot(
        TH32CS_SNAPPROCESS, 0
    )
    if snapshot == INVALID_HANDLE_VALUE:
        return None

    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if ctypes.windll.kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                if entry.th32ProcessID == pid:
                    return entry.th32ParentProcessID
                if not ctypes.windll.kernel32.Process32Next(
                    snapshot, ctypes.byref(entry)
                ):
                    break
    finally:
        ctypes.windll.kernel32.CloseHandle(snapshot)
    return None


# 已知终端窗口类：Windows Terminal、经典控制台。
# 按类名匹配能覆盖"进程祖先链之外"的终端（如从 Claude Code 会话运行时，
# 其终端窗口属于 WindowsTerminal.exe，可能不在 agent 的祖先 PID 链里）。
_TERMINAL_WINDOW_CLASSES = (
    "CASCADIA_HOSTING_WINDOW_CLASS",  # Windows Terminal
    "ConsoleWindowClass",            # cmd / PowerShell 经典控制台
    "WTWindow",                      # Windows Terminal 旧类名
)


def _is_terminal_window(hwnd) -> bool:
    """判断窗口是否属于已知终端类（Windows Terminal / 经典控制台）。"""
    try:
        class_name = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, class_name, 256)
        return class_name.value in _TERMINAL_WINDOW_CLASSES
    except Exception:
        return False


def _minimize_windows_by_pids(pids: List[int]) -> int:
    """枚举所有顶层可见窗口，最小化属于指定 PID 列表的窗口，
    以及所有终端类窗口（不依赖 PID 祖先链，覆盖 Claude Code 终端）。

    Args:
        pids: 进程 PID 列表。

    Returns:
        成功最小化的窗口数量。
    """
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    pids_set = set(pids)
    count = [0]  # 用列表绕开 nonlocal 限制

    def _callback(hwnd, _lparam):
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        process_id = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd, ctypes.byref(process_id)
        )
        is_own_or_ancestor = process_id.value in pids_set
        is_terminal = _is_terminal_window(hwnd)
        if is_own_or_ancestor or is_terminal:
            # 跳过太小的窗口（托盘图标等）
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 150 and h > 150:
                ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                count[0] += 1
        return True

    callback = WNDENUMPROC(_callback)
    ctypes.windll.user32.EnumWindows(callback, 0)
    return count[0]


def _enum_own_window_rects() -> List[Tuple[int, int, int, int]]:
    """枚举属于当前进程的所有可见顶层窗口，返回其屏幕矩形。"""
    pid = os.getpid()
    rects = []

    # 定义回调函数类型
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd, _lparam):
        # 获取窗口所属进程 ID
        process_id = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd, ctypes.byref(process_id)
        )
        if process_id.value != pid:
            return True  # 不是我家的窗口，跳过

        # 只处理可见的顶层窗口
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True

        # 跳过没有标题的（通常是工具窗口或隐藏窗口）
        title_len = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if title_len == 0:
            return True

        # 获取窗口矩形
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w > 100 and h > 100:  # 过滤太小的窗口（如托盘图标）
            rects.append((rect.left, rect.top, rect.right, rect.bottom))

        return True

    callback = WNDENUMPROC(_callback)
    ctypes.windll.user32.EnumWindows(callback, 0)
    return rects


def _minimize_own_windows() -> bool:
    """枚举本进程可见窗口并全部最小化（现代终端回退方案）。"""
    pid = os.getpid()
    minimized_any = False

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _callback(hwnd, _lparam):
        nonlocal minimized_any
        process_id = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd, ctypes.byref(process_id)
        )
        if process_id.value != pid:
            return True
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        title_len = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if title_len == 0:
            return True

        # SW_MINIMIZE = 6
        ctypes.windll.user32.ShowWindow(hwnd, 6)
        minimized_any = True
        logger.debug(f"已最小化本进程窗口 (hwnd={hwnd})")
        return True

    callback = WNDENUMPROC(_callback)
    ctypes.windll.user32.EnumWindows(callback, 0)
    return minimized_any


def capture(
    screen_id: int = SCREEN_ID,
    region: Optional[Tuple[int, int, int, int]] = SCREENSHOT_REGION,
    crop_own_windows: bool = True,
) -> Image.Image:
    """捕获屏幕截图。

    Args:
        screen_id: 屏幕ID，默认为0表示主屏幕。
        region: 截图区域 (x, y, width, height)，None 表示全屏。
        crop_own_windows: 如果之前 minimize_console() 失败，
                          是否自动裁剪本进程终端窗口区域。

    Returns:
        截图的 PIL Image 对象。
    """
    with mss.mss() as sct:
        monitor = sct.monitors[screen_id]
        if region is not None:
            x, y, width, height = region
            monitor = {
                "top": monitor["top"] + y,
                "left": monitor["left"] + x,
                "width": width,
                "height": height,
            }
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    # 如果终端最小化失败，走裁剪回退方案
    if crop_own_windows:
        img = crop_terminal_from_screenshot(img)

    return img


def _init_terminal_avoidance() -> bool:
    """初始化终端窗口避让：先尝试最小化，失败则准备裁剪回退。

    应在 Agent 启动时调用一次（每次任务循环开始时也可以调用）。

    Returns:
        True 表示终端已最小化（无需裁剪），False 表示将使用裁剪回退。
    """
    if minimize_console():
        logger.info("终端窗口已最小化，截图不包含终端内容")
        return True
    # 最小化失败 → 预加载窗口矩形缓存，capture() 时自动裁剪
    rects = get_terminal_rects()
    if rects:
        logger.info(
            f"终端最小化不可用（如现代终端），"
            f"已启用截图裁剪回退 ({len(rects)} 个窗口)"
        )
    return False


# ===== 截图标注：在图像上标记 UIA 控件 + OCR 文字位置 =====

# UIA 控件标注视觉常量
UIA_RECT_COLOR = (0, 200, 83)       # 绿色，Material Green A700
UIA_RECT_WIDTH = 3                   # 矩形框线宽（像素）
UIA_RECT_FILL = (0, 200, 83, 38)     # 半透明绿色填充（RGBA）

# OCR 标注视觉常量
OCR_DOT_COLOR = (255, 80, 20)        # 橙色
OCR_OUTLINE_COLOR = (255, 255, 255)  # 白色外圈
OCR_DOT_RADIUS = 16

# 去重：OCR bbox 与 UIA bbox 的 IoU 超过此阈值则跳过
_UIA_OCR_IOU_THRESHOLD = 0.2


def annotate_screenshot(
    image: Image.Image,
    ocr_results: list,
    max_items: int = ANNOTATE_MAX_ITEMS,
    task: str = "",
    uia_controls: list = None,
    is_desktop: bool = False,
) -> tuple:
    """在截图上标注可交互元素，返回标注图和编号→坐标映射表。

    融合两种感知源：
    - UIA 控件 → 绿色矩形框 + 白色编号，精确覆盖按钮等 Windows 控件
    - OCR 文字 → 橙色圆点 + 白色编号，覆盖非标准 UI（桌面、任务栏等）
    统一编号：UIA 优先（1,2,3…），OCR 去重后接在后面（N+1, N+2…）

    Args:
        image: 原始截图。
        ocr_results: OCR 结果列表，每项含 {"text", "bbox": (l,t,r,b), "confidence"}。
        max_items: 最多标注 N 个元素（UIA + OCR 总和）。
        task: 任务文本，用于 OCR 关键词排序。
        uia_controls: UIA 控件列表，每项含 {"name", "control_type", "bbox": (l,t,r,b)}。
                      None 或空列表表示无 UIA 数据（纯 OCR 模式）。
        is_desktop: 当前是否处于桌面（无应用窗口前台）。
                    True 时 OCR 点击点向上偏移一个文字高度以落在图标上
                    （桌面图标在文字上方，双击图标才能打开应用，点文字会进重命名模式）；
                    False（应用窗口内）时点击点取文字中心，用于菜单项/列表项等。

    Returns:
        (annotated_image, marker_map)
        annotated_image: 标注后的 PIL Image。
        marker_map: OrderedDict {
            编号: {
                "source": "uia" | "ocr",
                "text": str,
                "control_type": str | None,
                "bbox": (l, t, r, b),
                "click_point": (cx, cy),
            }
        }
    """
    from collections import OrderedDict

    from PIL import ImageDraw, ImageFont

    from desktop_gui_agent.agent.model_client import ModelClient

    uia_controls = uia_controls or []

    # ---- 先创建半透明叠加层画矩形框 ----
    # PIL 直接画线会完全遮挡框内内容。
    # 用 RGBA 叠加层画半透明填充 + 实线边框，然后粘贴回原图。
    annotated = image.copy()
    overlay = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    main_draw = ImageDraw.Draw(annotated)

    # 加载字体
    try:
        font = ImageFont.truetype("segoeui.ttf", 13)  # Segoe UI 在 Windows 上更适合小字号标注
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("C:\\Windows\\Fonts\\segoeui.ttf", 13)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("arial.ttf", 14)
            except (OSError, IOError):
                try:
                    font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 14)
                except (OSError, IOError):
                    font = ImageFont.load_default()

    marker_map = OrderedDict()
    marker_num = 1

    # ===== 第一轮：UIA 控件 → 绿色矩形框 =====
    for ctrl in uia_controls:
        if marker_num > max_items:
            break

        left, top, right, bottom = ctrl["bbox"]
        w, h = right - left, bottom - top

        # 跳过过小或过大的控件
        if w < 8 or h < 8:
            continue
        if w > image.width * 0.9 or h > image.height * 0.9:
            continue

        # 半透明绿色填充（叠加层）
        overlay_draw.rectangle(
            [left, top, right, bottom],
            fill=UIA_RECT_FILL,
        )
        # 实线边框（画在主图层，清晰可见）
        main_draw.rectangle(
            [left, top, right, bottom],
            outline=UIA_RECT_COLOR,
            width=UIA_RECT_WIDTH,
        )

        # 编号标签：贴在矩形框左上角外侧，白色文字 + 绿色底色小标签
        num_str = str(marker_num)
        label_w = 22
        label_h = 20
        label_x = left
        label_y = max(0, top - label_h)  # 贴在框上方

        # 绿色标签底色
        overlay_draw.rectangle(
            [label_x, label_y, label_x + label_w, label_y + label_h],
            fill=(0, 200, 83, 210),
        )
        # 标签上编号
        tw = len(num_str) * 7
        main_draw.text(
            (label_x + (label_w - tw) // 2, label_y + 2),
            num_str, fill=(255, 255, 255), font=font,
        )

        ctrl_name = ctrl.get("name", "")
        ctrl_type = ctrl.get("control_type", "")

        marker_map[marker_num] = {
            "source": "uia",
            "text": ctrl_name if ctrl_name else ctrl_type,
            "control_type": ctrl_type,
            "bbox": (left, top, right, bottom),
            "click_point": ctrl.get("click_point", ((left + right) // 2, (top + bottom) // 2)),
        }
        marker_num += 1

    # ===== 第二轮：OCR 文字 → 橙色圆点（去重后） =====
    uia_bboxes = [c["bbox"] for c in uia_controls]

    # 关键词排序
    task_keywords = ModelClient._extract_keywords(task)
    sorted_results = sorted(
        ocr_results,
        key=lambda item: (
            not any(
                kw in item["text"] or item["text"] in kw
                for kw in task_keywords
            ),
        ),
    )

    # 过滤噪声
    filtered = [
        item for item in sorted_results
        if not ModelClient._is_ocr_noise(item["text"], task)
    ]

    for item in filtered:
        if marker_num > max_items:
            break

        text = item["text"]
        x1, y1, x2, y2 = item["bbox"]

        # ---- 去重：OCR bbox 与任一 UIA bbox 重叠 > 阈值则跳过 ----
        if _is_duplicate_with_uia((x1, y1, x2, y2), uia_bboxes):
            continue

        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if is_desktop:
            # 桌面图标：图标在文字上方，点击需落在图标上（双击打开应用）。
            # 若点文字本身会进入重命名模式，因此点击点向上偏移一个文字高度。
            text_h = y2 - y1
            mx, my = cx, max(0, y1 - text_h)
        else:
            # 应用窗口内：文字本身就是要点击的目标（菜单项/列表项/对话框按钮），
            # 点击点取文字中心，避免偏移导致点空。
            mx, my = cx, cy

        # 白色外圈
        r = OCR_DOT_RADIUS
        main_draw.ellipse(
            [mx - r - 2, my - r - 2, mx + r + 2, my + r + 2],
            fill=None, outline=OCR_OUTLINE_COLOR, width=2,
        )
        # 橙色圆点
        main_draw.ellipse(
            [mx - r, my - r, mx + r, my + r],
            fill=OCR_DOT_COLOR, outline=OCR_DOT_COLOR,
        )
        # 编号
        num_str = str(marker_num)
        tw_est = len(num_str) * 8
        main_draw.text(
            (mx - tw_est // 2, my - 6),
            num_str, fill=(255, 255, 255), font=font,
        )

        marker_map[marker_num] = {
            "source": "ocr",
            "text": text,
            "control_type": None,
            "bbox": (x1, y1, x2, y2),
            "click_point": (mx, my),
        }
        marker_num += 1

    # 把半透明叠加层合并到主图
    annotated = Image.alpha_composite(annotated.convert("RGBA"), overlay).convert("RGB")

    logger.info(
        f"截图标注完成：{len(marker_map)} 个标记 "
        f"(UIA: {sum(1 for m in marker_map.values() if m['source'] == 'uia')}, "
        f"OCR: {sum(1 for m in marker_map.values() if m['source'] == 'ocr')})"
    )
    return annotated, marker_map


def _is_duplicate_with_uia(ocr_bbox: tuple, uia_bboxes: list) -> bool:
    """判断 OCR 边界框是否与任一 UIA 边界框重叠，避免重复标注。

    使用 IoU（交并比）衡量重叠程度。

    Args:
        ocr_bbox: OCR 边界框 (x1, y1, x2, y2)。
        uia_bboxes: UIA 边界框列表。

    Returns:
        True 表示应跳过此 OCR 元素（已被 UIA 框覆盖）。
    """
    if not uia_bboxes:
        return False

    ox1, oy1, ox2, oy2 = ocr_bbox
    o_area = max(0, ox2 - ox1) * max(0, oy2 - oy1)
    if o_area <= 0:
        return False

    for ux1, uy1, ux2, uy2 in uia_bboxes:
        # 计算交集
        ix1 = max(ox1, ux1)
        iy1 = max(oy1, uy1)
        ix2 = min(ox2, ux2)
        iy2 = min(oy2, uy2)
        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)
        inter = iw * ih
        if inter <= 0:
            continue

        u_area = max(0, ux2 - ux1) * max(0, uy2 - uy1)
        union = o_area + u_area - inter
        if union <= 0:
            continue

        iou = inter / union
        if iou > _UIA_OCR_IOU_THRESHOLD:
            return True

    return False

