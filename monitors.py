# -*- coding: utf-8 -*-
"""系统级监听：全局鼠标点击 + 桌面新窗口检测。"""
import ctypes
import logging
import os
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication
from pynput import keyboard, mouse

from config import WINDOW_POLL_MS

log = logging.getLogger(__name__)

_user32 = ctypes.windll.user32
_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _top_windows() -> set:
    """枚举当前可见、非本进程、有标题且有尺寸的顶层窗口句柄集合。"""
    out = set()
    pid = os.getpid()

    @_EnumWindowsProc
    def _cb(hwnd, lparam):  # noqa: ARG001
        if not _user32.IsWindowVisible(hwnd):
            return True
        wpid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        rect = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right - rect.left <= 0 or rect.bottom - rect.top <= 0:
            return True
        out.add(hwnd)
        return True

    _user32.EnumWindows(_cb, 0)
    return out


def to_qt_pos(x: int, y: int):
    """把 pynput 的物理像素坐标换算为 Qt 逻辑坐标（按主屏缩放比）。"""
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() or 1.0
    return int(x / dpr), int(y / dpr)


class GlobalMouse:
    """全局鼠标左/右键监听（pynput 低层钩子）。"""

    def __init__(self, on_left=None, on_right=None):
        self._on_left = on_left
        self._on_right = on_right
        self._listener = None

    def start(self):
        if self._listener is not None:
            return
        self._listener = mouse.Listener(on_click=self._on_click)
        self._listener.daemon = True
        self._listener.start()
        log.info("全局鼠标监听已启动")

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        try:
            qx, qy = to_qt_pos(x, y)
            if button == mouse.Button.left and self._on_left:
                self._on_left((qx, qy))
            elif button == mouse.Button.right and self._on_right:
                self._on_right((qx, qy))
        except Exception:  # noqa: BLE001
            log.exception("鼠标回调异常")


class GlobalKeys:
    """全局快捷键监听：Ctrl+Shift+Q 退出程序。"""

    def __init__(self, on_exit=None):
        self._on_exit = on_exit
        self._listener = None
        self._hotkey = keyboard.HotKey(
            keyboard.HotKey.parse("<ctrl>+<shift>+q"), self._trigger)

    def _trigger(self):
        log.info("收到退出快捷键")
        if self._on_exit:
            self._on_exit()

    def start(self):
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._hotkey.press, on_release=self._hotkey.release)
        self._listener.daemon = True
        self._listener.start()
        log.info("全局快捷键监听已启动")

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


class WindowMonitor(QObject):
    """轮询检测新出现的桌面窗口（排除自身进程的浮层）。"""

    def __init__(self, on_new=None):
        super().__init__()
        self._on_new = on_new
        self._known = set()
        self._timer = QTimer(self)
        self._timer.setInterval(WINDOW_POLL_MS)
        self._timer.timeout.connect(self._tick)

    def start(self):
        try:
            self._known = _top_windows()
        except Exception:  # noqa: BLE001
            log.exception("初始化窗口列表失败")
            self._known = set()
        self._timer.start()
        log.info("桌面窗口监听已启动")

    def stop(self):
        self._timer.stop()

    def _tick(self):
        try:
            current = _top_windows()
        except Exception:  # noqa: BLE001
            return
        new = current - self._known
        if new and self._on_new:
            log.info("检测到新窗口 %d 个", len(new))
            self._on_new()
        self._known = current
