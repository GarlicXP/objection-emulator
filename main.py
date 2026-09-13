# -*- coding: utf-8 -*-
"""律师选择器 - 主程序。

用法：
    python main.py                正常启动（选择界面 → 桌面效果）
    python main.py --selftest     离屏自测：验证全部媒体可解码、界面可构建
    python main.py --smoke N      真实窗口冒烟测试：显示选择界面 N 秒后自动退出
"""
import logging
import os
import sys

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import QApplication

from config import APP_ICON

# 日志/数据目录：开发时为项目目录；打包后为 exe 所在目录（便于查看 app.log）
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class EffectBridge(QObject):
    """跨线程信号桥：鼠标钩子在后台线程回调，信号经队列转发到 Qt 主线程。

    Qt 禁止在非主线程创建/操作窗口部件——此前“图片卡住、视频不播、右键时灵
    时不灵”的根因就在于此；所有效果创建都必须回到主线程。
    """

    left_clicked = Signal(QPoint)
    right_clicked = Signal(QPoint)
    exit_requested = Signal()


def _setup_logging():
    logging.basicConfig(
        filename=os.path.join(BASE_DIR, "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )
    logging.getLogger().info("=== 程序启动 ===")


def run_selftest(app: QApplication) -> int:
    """离屏自测：解码每个媒体文件首帧，构建选择界面，验证关键对象。"""
    import config
    from media_player import VideoSurface
    from overlay import EffectManager

    logging.getLogger().info("开始离屏自测")
    failures = []

    # 1) 全部媒体可解码
    names = ["11", "12", "13", "14", "15", "16",
             "21", "22", "23", "24", "25", "26"]
    for name in names:
        try:
            path = config.media(name)
            assert os.path.exists(path), f"文件缺失 {path}"
            surf = VideoSurface(path, parent=None)
            surf._step()  # 取一帧
            ok = surf._arr is not None and surf.video_size != (0, 0)
            if name in ("11", "12", "13", "21", "22", "23"):
                # 双轨 WebM 必须带真实 alpha，且带音轨（效果视频要有声音）
                alpha = surf._arr[:, :, 3]
                ok = ok and int(alpha.min()) < 128
                ok = ok and len(surf._container.streams.audio) > 0
            surf.close_video()
            surf.deleteLater()
            if not ok:
                failures.append(f"{name}: 解码后无帧或 alpha 缺失")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {exc}")
    logging.getLogger().info("媒体解码检查完成: %d 失败", len(failures))

    # 2) 选择界面可构建
    try:
        from select_window import SelectWindow
        win = SelectWindow()
        win._hover_timer.stop()
        win.close()
        logging.getLogger().info("选择界面构建 OK")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"SelectWindow: {exc}")

    # 3) 效果管理器可构建
    try:
        mgr = EffectManager("left")
        assert mgr._screen is not None
        logging.getLogger().info("EffectManager 构建 OK")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"EffectManager: {exc}")

    # 4) 系统监听器可构建并启停（打包后验证 pynput 等依赖完整）
    try:
        from monitors import GlobalKeys, GlobalMouse, WindowMonitor
        gm = GlobalMouse()
        gm.start()
        gm.stop()
        gk = GlobalKeys()
        gk.start()
        gk.stop()
        wm = WindowMonitor()
        wm.start()
        wm.stop()
        logging.getLogger().info("监听器启停 OK")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"listeners: {exc}")

    print("自测失败项:", failures if failures else "无")
    return 1 if failures else 0


def run_smoke(app: QApplication, seconds: int) -> None:
    from select_window import SelectWindow
    win = SelectWindow()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(seconds * 1000, app.quit)
    logging.getLogger().info("冒烟测试：显示 %d 秒", seconds)


def main():
    _setup_logging()
    argv = sys.argv[:]
    selftest = "--selftest" in argv
    smoke = None
    for i, a in enumerate(argv):
        if a == "--smoke" and i + 1 < len(argv):
            smoke = max(1, int(argv[i + 1]))

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if selftest:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication(argv)

    if selftest:
        sys.exit(run_selftest(app))

    if smoke:
        run_smoke(app, smoke)
        sys.exit(app.exec())

    from monitors import GlobalKeys, GlobalMouse, WindowMonitor
    from overlay import EffectManager, ExitHint
    from select_window import SelectWindow

    # 全局运行状态：当前选择窗口、效果监听器、托盘
    state = {"window": None, "mgr": None, "bridge": None,
             "mouse": None, "monitor": None, "keys": None, "tray": None}

    def stop_effects():
        """停止全部效果监听并清理浮层（重选/退出前调用）。"""
        for key in ("mouse", "monitor", "keys"):
            obj = state.get(key)
            if obj is not None:
                try:
                    obj.stop()
                except Exception:  # noqa: BLE001
                    pass
        mgr = state.get("mgr")
        if mgr is not None:
            mgr.close_all()
        state.update(mgr=None, bridge=None, mouse=None, monitor=None, keys=None)

    def on_confirmed(side: str):
        logging.getLogger().info("选择完成: %s", side)
        stop_effects()  # 重选时旧监听一律先停，避免重复触发
        ExitHint()  # 提示退出快捷键（8 秒后自动淡出）
        mgr = EffectManager(side)
        bridge = EffectBridge()
        bridge.left_clicked.connect(mgr.on_left_click)
        bridge.right_clicked.connect(mgr.on_right_click)
        bridge.exit_requested.connect(QApplication.instance().quit)
        mouse_hook = GlobalMouse(
            on_left=lambda p: bridge.left_clicked.emit(
                QPoint(int(p[0]), int(p[1]))),
            on_right=lambda p: bridge.right_clicked.emit(
                QPoint(int(p[0]), int(p[1]))))
        mouse_hook.start()
        window_monitor = WindowMonitor(on_new=mgr.on_window_appeared)
        window_monitor.start()
        keys = GlobalKeys(on_exit=bridge.exit_requested.emit)
        keys.start()
        state.update(mgr=mgr, bridge=bridge, mouse=mouse_hook,
                     monitor=window_monitor, keys=keys)
        _ensure_tray()

    def on_re_select():
        """托盘菜单：重新选择律师。"""
        logging.getLogger().info("重新选择律师")
        stop_effects()
        open_selection()

    def on_quit():
        """托盘菜单：退出程序。"""
        logging.getLogger().info("通过托盘退出")
        stop_effects()
        tray = state.get("tray")
        if tray is not None:
            tray.hide()
        app.quit()

    def _ensure_tray():
        """选完后在系统托盘常驻（只创建一次）。"""
        if state.get("tray") is not None:
            return
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        tray = QSystemTrayIcon(QIcon(APP_ICON), app)
        tray.setToolTip("律师选择器")
        menu = QMenu()
        act_re = menu.addAction("重新选择律师")
        act_re.triggered.connect(on_re_select)
        act_exit = menu.addAction("退出")
        act_exit.triggered.connect(on_quit)
        tray.setContextMenu(menu)
        tray.show()
        state["tray"] = tray
        logging.getLogger().info("托盘图标已添加（图标: %s）", APP_ICON)

    def open_selection():
        old = state.get("window")
        if old is not None:
            old.deleteLater()
        win = SelectWindow()
        win.confirmed.connect(on_confirmed)
        win.show()
        state["window"] = win

    open_selection()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
