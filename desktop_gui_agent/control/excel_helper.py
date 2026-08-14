# -*- coding: utf-8 -*-
"""Excel 专门自动化 — 通过 COM 直接操作，绕开 VLM 的复杂 UI 理解。

高价值场景的专门优化：Excel 有开始页/功能区/单元格网格，VLM 在
这些复杂界面上不可靠（多行输入导航失败）。用 COM 直接创建工作簿并
填入数据，完全可靠，不依赖模型导航单元格。

用法：
    create_with_data("姓名,年龄\\n张三,25\\n李四,30")
    会创建 Excel 工作簿并在 A1:B3 填入上述数据。
"""
import os

import win32com.client

from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)


def create_with_data(data: str, save_path: str = "") -> bool:
    """用 COM 创建 Excel 工作簿并填入数据。

    Args:
        data: 表格数据。行用换行分隔，单元格用逗号分隔。
              例如 "姓名,年龄\\n张三,25" → A1="姓名", B1="年龄", A2="张三", B2="25"。
        save_path: 可选保存路径（含 .xlsx），空则不保存。

    Returns:
        True 表示创建成功，False 表示失败。
    """
    if not data or not data.strip():
        logger.warning("excel_create 数据为空")
        return False

    try:
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = True  # 让用户看到工作簿
        workbook = excel.Workbooks.Add()
        sheet = workbook.Worksheets(1)

        # 解析数据：行 = 换行分隔，单元格 = 逗号分隔
        rows = [r for r in data.strip().split("\n") if r.strip()]
        for row_idx, row in enumerate(rows, start=1):
            cells = [c.strip() for c in row.split(",")]
            for col_idx, val in enumerate(cells, start=1):
                if val:
                    sheet.Cells(row_idx, col_idx).Value = val

        if save_path:
            # 归一化路径分隔符（模型常输出正斜杠），避免 Excel SaveAs 误读
            save_path = os.path.normpath(save_path)
            workbook.SaveAs(save_path)
            logger.info(f"Excel 已保存: {save_path}")

        logger.info(f"Excel 工作簿创建成功，填入 {len(rows)} 行")
        return True

    except Exception as e:
        logger.error(f"Excel COM 操作失败: {e}")
        return False
