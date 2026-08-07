# -*- coding: utf-8 -*-
"""桌面GUI智能体 — 入口模块

解析命令行参数，创建 TaskManager，执行用户任务。
支持命令行直接传任务或交互式输入。

全局快捷键：Ctrl+Alt+Q 安全退出（优先于 agent 操作）。
"""
import argparse
import sys
import time
from typing import List, Optional

from desktop_gui_agent.agent.task_manager import TaskManager
from desktop_gui_agent.utils.global_hotkey import GlobalHotkey
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
    parser.add_argument(
        "--api",
        type=str,
        default=None,
        choices=["local", "dashscope", "ollama"],
        help="推理后端：local=本地2B模型（默认），dashscope=通义千问云端，ollama=本地Ollama",
    )
    return parser.parse_args(argv)


def main() -> int:
    """CLI 主入口。

    1. 解析命令行参数
    2. 获取任务（命令行或交互输入）
    3. 创建 TaskManager（模型只加载一次）
    4. 连续执行任务直到用户输入 exit

    Returns:
        0 表示成功，1 表示失败。
    """
    args = _parse_args()

    # 获取任务描述
    task = args.task

    # 启动全局退出快捷键 Ctrl+Alt+Q
    hotkey = GlobalHotkey()
    hotkey.start()

    # 创建 TaskManager（模型在第一个任务时加载一次，后续复用）
    logger.info("正在初始化 Agent...")
    api_preset = args.api if args.api and args.api != "local" else None
    tm = TaskManager(
        max_steps=args.max_steps,
        max_consecutive_errors=args.max_errors,
        api_preset=api_preset,
    )
    logger.info("Agent 初始化完成，输入第一个任务时自动加载模型（约15秒）")
    logger.info("按 Ctrl+Alt+Q 可随时安全退出")

    try:
        # 交互循环：支持连续执行多个任务
        if task:
            # 命令行直接传了任务 → 执行一次
            exit_code, _ = _run_one_task(tm, task, cancel_event=hotkey.exit_event)
            return exit_code
        else:
            # 交互模式 → 连续输入任务
            return _interactive_loop(tm, hotkey)
    finally:
        hotkey.stop()


def _run_one_task(tm: TaskManager, task: str,
                  cancel_event: object = None) -> tuple[int, bool]:
    """执行单个任务并输出结果。

    Args:
        tm: TaskManager 实例。
        task: 任务描述。
        cancel_event: 外部取消事件（如全局热键触发）。

    Returns:
        (exit_code, success): exit_code 为 0/1，success 表示任务是否成功。
    """
    logger.info(f"开始任务: {task}")
    result = tm.run(task, cancel_event=cancel_event)
    _print_result(result)
    return (0 if result["success"] else 1, result["success"])


def _interactive_loop(tm: TaskManager, hotkey: GlobalHotkey) -> int:
    """交互模式：模型保持加载，连续执行多个任务。

    安全检查：
    - 非 TTY 环境直接拒绝（防止 piped input 导致死循环）
    - 连续失败时指数退避（最大 30s）
    - 每次循环最小间隔 0.1s
    - Ctrl+Alt+Q 全局热键安全退出
    """
    if not sys.stdin.isatty():
        print("错误：交互模式需要终端（TTY）环境，不支持管道输入。", file=sys.stderr)
        print("请直接在终端中运行 python main.py，或通过命令行传任务：python main.py \"你的任务\"",
              file=sys.stderr)
        return 1

    print("\n桌面GUI智能体已就绪！输入任务开始，输入 exit 退出。")
    print("按 Ctrl+Alt+Q 可随时安全退出。\n")

    consecutive_failures = 0
    exit_code = 0

    while True:
        # 检查全局热键退出
        if hotkey.exit_event.is_set():
            print("\n⚠ Ctrl+Alt+Q 触发退出")
            return exit_code

        try:
            task = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出")
            return exit_code

        if not task:
            continue
        if task.lower() in ("exit", "quit", "q"):
            print("已退出")
            return exit_code

        _, success = _run_one_task(tm, task, cancel_event=hotkey.exit_event)
        print()

        if success:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            exit_code = 1  # 至少有一个任务失败，最终退出码为 1

        # 连续失败时指数退避，防止死循环耗尽系统资源
        if consecutive_failures > 0:
            delay = min(2 ** consecutive_failures, 30)
            logger.warning(
                f"已连续失败 {consecutive_failures} 次，{delay}s 后再继续..."
            )
            time.sleep(delay)
        else:
            time.sleep(0.1)  # 基础间隔，防止极端空转


def _print_result(result: dict) -> None:
    """打印任务执行结果。"""
    if result["success"]:
        print(f"✅ 完成，共 {result['steps']} 步")
        if result["result"]:
            print(f"   结果: {result['result']}")
    else:
        print(f"❌ 未完成（{result['steps']} 步），原因: {result['error']}")


if __name__ == "__main__":
    sys.exit(main())
