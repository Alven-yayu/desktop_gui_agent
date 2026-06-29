# -*- coding: utf-8 -*-
"""桌面GUI智能体 — 入口模块

解析命令行参数，创建 TaskManager，执行用户任务。
支持命令行直接传任务或交互式输入。
"""
import argparse
import sys
from typing import List, Optional

from desktop_gui_agent.agent.task_manager import TaskManager
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表，None 则使用 sys.argv。

    Returns:
        解析后的 Namespace 对象。
    """
    parser = argparse.ArgumentParser(
        prog="gui_agent",
        description="桌面GUI智能体 — 用自然语言控制桌面，自动完成操作任务",
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="任务描述（如 '打开记事本输入Hello World'），不传则进入交互模式",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="最大操作步数（默认 20）",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=3,
        help="连续错误次数上限（默认 3）",
    )
    return parser.parse_args(argv)


def main() -> int:
    """CLI 主入口。

    1. 解析命令行参数
    2. 获取任务（命令行或交互输入）
    3. 创建 TaskManager 并执行
    4. 输出结果

    Returns:
        0 表示任务成功，1 表示失败。
    """
    args = _parse_args()

    # 获取任务描述
    task = args.task
    if not task:
        print("请输入任务描述（如 '打开记事本输入Hello'）：", flush=True)
        try:
            task = input().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return 1
        if not task:
            print("错误：任务不能为空")
            return 1

    logger.info(f"启动 Agent，任务: {task}，max_steps={args.max_steps}")

    tm = TaskManager(
        max_steps=args.max_steps,
        max_consecutive_errors=args.max_errors,
    )

    result = tm.run(task)

    # 输出结果
    print()
    if result["success"]:
        print(f"✅ 任务完成！共执行 {result['steps']} 步")
        if result["result"]:
            print(f"结果: {result['result']}")
        return 0
    else:
        print(f"❌ 任务未完成")
        print(f"原因: {result['error']}")
        print(f"已执行 {result['steps']} 步")
        return 1


if __name__ == "__main__":
    sys.exit(main())
