# -*- coding: utf-8 -*-
"""监听模块测试：桌面新窗口检测 + 全局鼠标钩子启停。"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from monitors import GlobalMouse, WindowMonitor

fired = []


def on_new():
    fired.append(True)


wm = WindowMonitor(on_new=on_new)
wm.start()
print("窗口监听已启动，初始已知窗口数:", len(wm._known))


def spawn_test_window():
    code = ("import tkinter as t;"
            "r=t.Tk(); r.title('zzz-test-window-12345');"
            "r.geometry('300x100+100+100');"
            "r.after(4000, r.destroy); r.mainloop()")
    subprocess.Popen([sys.executable, "-c", code],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) & 0)


QTimer.singleShot(1000, spawn_test_window)


def done():
    print("检测到新窗口:", bool(fired))
    gm = GlobalMouse()
    gm.start()
    print("全局鼠标钩子启动 OK")
    gm.stop()
    print("全局鼠标钩子停止 OK")
    ok = bool(fired)
    print("=== 结果:", "通过" if ok else "失败", "===")
    app.quit()


QTimer.singleShot(6000, done)
QTimer.singleShot(15000, lambda: (print("超时退出"), app.quit()))
sys.exit(app.exec())
