# -*- coding: utf-8 -*-
from typing import Optional, Tuple

import mss
from PIL import Image

from desktop_gui_agent.config import SCREEN_ID, SCREENSHOT_REGION

def capture(screen_id: int = SCREEN_ID, region: Optional[Tuple[int, int, int, int]] = SCREENSHOT_REGION) -> Image.Image:
    """
    捕获屏幕截图。

    :param screen_id: 屏幕ID，默认为0表示主屏幕
    :param region: 截图区域，格式为 (x, y, width, height)，如果为 None 则截取全屏
    :return: 截图的PIL Image对象
    """
    with mss.mss() as sct:
        monitor = sct.monitors[screen_id]
        if region is not None:
            x, y, width, height = region
            monitor = {
                "top": monitor["top"] + y,
                "left": monitor["left"] + x,
                "width": width,
                "height": height
            }
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img

