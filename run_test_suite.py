# -*- coding: utf-8 -*-
"""批量测试集运行器 — 依次执行 11 个测试任务并生成报告。

用法:
  python run_test_suite.py --api dashscope          # 云端 qwen-vl-plus（推荐）
  python run_test_suite.py --api dashscope --only 1,3,6
  python run_test_suite.py --api dashscope --auto   # 任务间不等待确认

⚠️ 注意事项:
  - 会真实控制鼠标键盘、打开/关闭应用，请确保桌面处于可操作状态。
  - 默认每个任务结束后暂停，方便手动恢复桌面状态；--auto 跳过暂停。
  - Ctrl+Alt+Q 随时安全退出。
  - 报告写入 logs/test_suite_<时间戳>.json，单任务明细在 task_*.json。
"""
import argparse
import json
import time
from datetime import datetime

from desktop_gui_agent.agent.task_manager import TaskManager
from desktop_gui_agent.utils.global_hotkey import GlobalHotkey
from desktop_gui_agent.utils.logger import get_logger
from desktop_gui_agent.utils.platform import PlatformInfo

logger = get_logger(__name__)

# 任务间固定延时（秒）。连续执行不中断，给桌面状态一点稳定时间。
_BETWEEN_TASK_DELAY = 3
# 每个任务都扩写为 agent 可执行的明确指令（目标应用/输入内容/预期结果/约束）。
TEST_TASKS = [
    # ===== 简单任务（6）=====
    "打开计算器，输入 1+1 并回车得出结果，报告屏幕上显示的结果",
    "打开记事本（用 Win 搜索），在编辑区输入 Hello World",
    "打开音量面板，把音量调整到 50%",
    "用 Win 搜索打开 Chrome 浏览器，确认窗口已打开",
    "打开 Edge 浏览器，在地址栏输入 python 并回车搜索，报告搜索结果页面已显示",
    "关闭当前窗口（任务开始时最前面的那个），完成后报告，不要关闭其他窗口",
    # ===== 中等任务（5）=====
    "新建 Excel 表格，输入 3 行数据（表头：姓名,年龄；张三,25；李四,30），保存到桌面",
    "打开浏览器访问必应图片搜索，搜索'风景'，右键下载第一张图片保存到桌面",
    "打开桌面上的'测试文档.txt'，读取内容并报告文档写了什么",
    "打开微信，向联系人'文件传输助手'发送消息'你好'",
    "右键桌面回收站图标，选择'清空回收站'，确认后清空",
]


def _parse_args(argv=None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="run_test_suite",
        description="桌面GUI智能体 — 批量测试集（11 个任务）",
    )
    parser.add_argument(
        "--api", type=str, default="dashscope",
        choices=["local", "dashscope", "ollama"],
        help="推理后端（默认 dashscope=云端 qwen-vl-plus，效果最好）",
    )
    parser.add_argument("--max-steps", type=int, default=30,
                        help="每个任务最大步数（默认 30）")
    parser.add_argument("--only", type=str, default=None,
                        help="只跑指定编号，逗号分隔，如 1,3,6")
    parser.add_argument("--auto", action="store_true",
                        help="任务间不暂停等待确认，自动继续")
    return parser.parse_args(argv)


def _wait_between_tasks(task_num: int, total: int, auto: bool) -> None:
    """任务间固定延时，不弹输入对话框打断进程。

    之前用 input() 等待回车，若上一步的 type() 文本（如 "Hello World"）
    误输入到该对话框会提前回车打断流程。现改为固定短延时，保持连续运行。
    """
    print(f"\n--- [{task_num}] 执行完毕，剩余 {total} 个，{_BETWEEN_TASK_DELAY}s 后继续 ---")
    time.sleep(_BETWEEN_TASK_DELAY)


def run_suite(args: argparse.Namespace) -> None:
    """依次执行测试任务并汇总结果。

    Args:
        args: 解析后的命令行参数。
    """
    only = {int(x.strip()) for x in args.only.split(",")} if args.only else None
    tasks = [
        (num, task)
        for num, task in enumerate(TEST_TASKS, 1)
        if only is None or num in only
    ]
    total = len(tasks)
    if not tasks:
        print("没有匹配的任务编号，退出。")
        return

    print(f"测试集开始：共 {total} 个任务（API={args.api}）")
    print("提示：Ctrl+Alt+Q 可随时安全退出\n")

    hotkey = GlobalHotkey()
    hotkey.start()
    # 与 main.py 一致：api_preset 仅在非 local 时传入，模型全程只加载一次
    api_preset = args.api if args.api != "local" else None
    tm = TaskManager(max_steps=args.max_steps, api_preset=api_preset)

    results = []
    try:
        for idx, (num, task) in enumerate(tasks, 1):
            if hotkey.exit_event.is_set():
                print("\n⚠ Ctrl+Alt+Q 触发退出，跳过剩余任务")
                break

            print(f"\n{'=' * 60}\n[{num}] {task}\n{'=' * 60}")
            start = time.time()
            try:
                result = tm.run(task, cancel_event=hotkey.exit_event)
            except Exception as e:  # 单个任务崩溃不影响整套跑完
                logger.exception(f"[{num}] 任务执行异常")
                result = {"success": False, "result": "",
                          "steps": 0, "error": f"执行异常: {e}"}
            duration = time.time() - start

            results.append({
                "num": num,
                "task": task,
                "success": bool(result.get("success")),
                "steps": result.get("steps", 0),
                "result": result.get("result", ""),
                "error": result.get("error"),
                "duration_s": round(duration, 1),
            })

            tag = "✅" if result.get("success") else "❌"
            reason = result.get("result") or result.get("error") or ""
            print(f"{tag} [{num}] {'完成' if result.get('success') else '未完成'} "
                  f"({result.get('steps', 0)}步 {duration:.0f}s)")
            if reason:
                print(f"    {reason}")

            if idx < total and not hotkey.exit_event.is_set():
                _wait_between_tasks(num, total - idx, args.auto)
    finally:
        hotkey.stop()

    _save_report(results)
    _print_summary(results)


def _save_report(results: list) -> None:
    """把结果汇总保存到 logs/test_suite_<时间戳>.json。"""
    log_dir = PlatformInfo.get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"test_suite_{timestamp}.json"
    record = {
        "total": len(results),
        "passed": sum(1 for r in results if r["success"]),
        "timestamp": timestamp,
        "results": results,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        print(f"\n测试报告已保存: {path}")
    except Exception as e:
        logger.error(f"保存测试报告失败: {e}")


def _print_summary(results: list) -> None:
    """打印测试结果汇总表。"""
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    rate = passed / total * 100 if total else 0
    simple = [r for r in results if r["num"] <= 6]
    medium = [r for r in results if r["num"] > 6]
    s_pass = sum(1 for r in simple if r["success"])
    m_pass = sum(1 for r in medium if r["success"])

    print("\n" + "=" * 60)
    print("测试集汇总")
    print("=" * 60)
    print(f"总通过率: {passed}/{total} = {rate:.0f}%")
    if simple:
        print(f"简单任务: {s_pass}/{len(simple)}")
    if medium:
        print(f"中等任务: {m_pass}/{len(medium)}")
    print("-" * 60)
    for r in results:
        tag = "✅" if r["success"] else "❌"
        print(f"  {tag} [{r['num']}] {r['task'][:40]}")
        if r.get("error"):
            print(f"       原因: {r['error'][:60]}")
    print("=" * 60)


if __name__ == "__main__":
    run_suite(_parse_args())
