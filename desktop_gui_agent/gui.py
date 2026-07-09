# -*- coding: utf-8 -*-
"""GUI 交互窗口。

提供图形化的任务输入和状态展示界面，
模型只加载一次，可连续执行多个任务。
"""
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from desktop_gui_agent.agent.task_manager import TaskManager
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

# 任务队列：GUI 线程 → 工作线程
_task_queue: queue.Queue = queue.Queue()
_shutdown: bool = False


def _worker(tm: TaskManager, app: "App"):
    """后台工作线程：加载模型，从队列取任务，执行。"""
    global _shutdown

    # 模型将在第一个任务执行时自动加载
    app.log("Agent 已就绪，输入第一个任务时自动加载模型（约15秒）")
    app.set_status("就绪，请输入任务")
    app.enable_input()

    # 循环执行任务
    while not _shutdown:
        try:
            task = _task_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if task is None:  # 退出信号
            break

        app.log(f"\n>>> 任务: {task}")
        app.set_status(f"正在执行: {task}")
        app.disable_input()

        # 创建新的取消事件，传进 run()，让 GUI 可以中途终止
        app.cancel_event.clear()
        try:
            result = tm.run(task, cancel_event=app.cancel_event)
            if result["success"]:
                app.log(f"✅ 完成，共 {result['steps']} 步")
                if result["result"]:
                    app.log(f"   结果: {result['result']}")
            else:
                app.log(f"❌ 未完成（{result['steps']} 步）")
                app.log(f"   原因: {result['error']}")
        except Exception as e:
            app.log(f"❌ 异常: {e}")

        app.set_status("就绪，请输入任务")
        app.enable_input()


class App:
    """GUI 应用主窗口。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.cancel_event: threading.Event = threading.Event()
        root.title("桌面 GUI 智能体")
        root.geometry("700x500")
        root.resizable(True, True)

        # 样式
        style = ttk.Style()
        style.theme_use("clam")

        self._build_ui()

    def _build_ui(self):
        """构建界面组件。"""
        # === 状态栏 ===
        status_frame = ttk.Frame(self.root, padding=(10, 10, 10, 5))
        status_frame.pack(fill=tk.X)

        ttk.Label(status_frame, text="状态：", font=("", 10, "bold")).pack(side=tk.LEFT)
        self.status_label = ttk.Label(status_frame, text="就绪，请输入任务", foreground="green")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # === 输入区 ===
        input_frame = ttk.Frame(self.root, padding=(10, 5, 10, 5))
        input_frame.pack(fill=tk.X)

        ttk.Label(input_frame, text="任务：").pack(side=tk.LEFT)
        self.task_entry = ttk.Entry(input_frame, font=("", 11))
        self.task_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.task_entry.config(state="disabled")
        self.task_entry.bind("<Return>", lambda e: self._on_run())

        self.run_btn = ttk.Button(input_frame, text="执行", command=self._on_run, state="disabled")
        self.run_btn.pack(side=tk.RIGHT)

        self.stop_btn = ttk.Button(input_frame, text="终止", command=self._on_stop)
        # 默认隐藏，执行任务时才显示

        # === 输出日志区 ===
        log_frame = ttk.Frame(self.root, padding=(10, 5, 10, 10))
        log_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(log_frame, text="执行日志：").pack(anchor=tk.W)
        self.log_area = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=("Consolas", 10),
            state="disabled", bg="#1e1e1e", fg="#d4d4d4",
        )
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

        # === 退出按钮 ===
        bottom_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom_frame.pack(fill=tk.X)
        ttk.Button(bottom_frame, text="退出", command=self._on_quit).pack(side=tk.RIGHT)

    # ===== 状态控制 =====

    def set_status(self, text: str):
        """更新状态标签（需在主线程调用）。"""
        self.root.after(0, lambda: self.status_label.config(text=text))

    def enable_input(self):
        """启用输入框和执行按钮，隐藏终止按钮。"""
        self.cancel_event.clear()
        self.root.after(0, lambda: (
            self.task_entry.config(state="normal"),
            self.stop_btn.pack_forget(),
            self.run_btn.pack(side=tk.RIGHT),
            self.run_btn.config(state="normal"),
            self.task_entry.focus_set(),
        ))

    def disable_input(self):
        """禁用输入框和执行按钮，显示终止按钮。"""
        self.root.after(0, lambda: (
            self.task_entry.config(state="disabled"),
            self.run_btn.pack_forget(),
            self.stop_btn.pack(side=tk.RIGHT),
        ))

    def log(self, text: str):
        """向日志区追加文本（线程安全）。"""
        self.root.after(0, lambda t=text: self._append_log(t))

    def _append_log(self, text: str):
        """在主线程追加日志。"""
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, text + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")

    # ===== 事件处理 =====

    def _on_run(self):
        """点击「执行」按钮或按回车。"""
        task = self.task_entry.get().strip()
        if not task:
            return
        self.task_entry.delete(0, tk.END)
        _task_queue.put(task)

    def _on_stop(self):
        """点击「终止」按钮，停止当前任务。"""
        self.log("⚠ 用户请求终止...")
        self.cancel_event.set()

    def _on_quit(self):
        """退出程序。"""
        global _shutdown
        _shutdown = True
        _task_queue.put(None)
        self.root.destroy()

    def _start_worker(self):
        """启动后台工作线程。"""
        self.set_status("正在加载模型...")
        self.log("正在初始化，加载 Qwen2-VL 模型...")

        tm = TaskManager()
        t = threading.Thread(target=_worker, args=(tm, self), daemon=True)
        t.start()


def launch():
    """启动 GUI 窗口。"""
    root = tk.Tk()
    app = App(root)

    # 启动后台工作线程（模型在第一个任务时加载）
    tm = TaskManager()
    t = threading.Thread(target=_worker, args=(tm, app), daemon=True)
    t.start()

    # 初始状态：输入已启用
    app.enable_input()

    root.mainloop()


if __name__ == "__main__":
    launch()
