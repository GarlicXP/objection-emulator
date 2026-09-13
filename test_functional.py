# -*- coding: utf-8 -*-
"""功能测试：驱动选择界面状态机、点击选人、选框动画、确认缩小、效果浮层。

在真实显示上运行（会短暂显示选择界面与效果浮层）。用法：
    .venv\\Scripts\\python.exe test_functional.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QAbstractAnimation, QPoint, QRect, QTimer
from PySide6.QtWidgets import QApplication

results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS" if cond else "FAIL"), name)


def main():
    app = QApplication(sys.argv)
    from select_window import SelectWindow

    win = SelectWindow()
    win.show()
    # 悬停定时器依赖真实鼠标位置，测试中停掉以保证确定性
    win._hover_timer.stop()
    check("选择界面为窗口形态(非全屏)",
          win.isVisible() and win.width() < 2000)
    check("窗口较小", win.width() <= 1100 and win.height() <= 900)
    check("初始左右均为灰色 idle", win._state["left"] == "idle"
          and win._state["right"] == "idle"
          and win._surface["left"]._gray and win._surface["right"]._gray)
    # 回归：启动时必须真正加载并播放 14/24（曾因 _state 初始即为 idle 被跳过）
    check("启动即加载并循环播放 14/24",
          win._surface["left"]._path.endswith("14.mp4")
          and win._surface["right"]._path.endswith("24.mp4")
          and win._surface["left"]._timer.isActive()
          and win._surface["right"]._timer.isActive())
    check("初始均未选中", win._selected is None)

    # ---- 悬停：按视频区域 + 滞回，未靠近时保持灰色 ----
    win._update_near("left", True)
    win._update_near("left", True)
    check("左靠近 2 拍 → hover(彩色 15)", win._state["left"] == "hover"
          and win._surface["left"]._gray is False)
    win._update_near("left", False)
    win._update_near("left", False)
    check("未离开满 3 拍 → 仍 hover", win._state["left"] == "hover")
    win._update_near("left", False)
    check("左离开满 3 拍 → 回灰色 idle(14)", win._state["left"] == "idle"
          and win._surface["left"]._gray is True)
    win._update_near("right", True)
    win._update_near("right", True)
    check("右靠近 → hover(彩色 25)", win._state["right"] == "hover"
          and win._surface["right"]._gray is False)
    win._update_near("right", False)
    win._update_near("right", False)
    win._update_near("right", False)
    check("右离开 → 回灰色 idle(24)", win._state["right"] == "idle"
          and win._surface["right"]._gray is True)

    # ---- 点击选人 + 选框动画；选中不强制彩色 ----
    left_rect = win._surface["left"].geometry()
    win._select("left", left_rect.center())
    check("点击左视频 → 选中 left", win._selected == "left")
    check("选中后确认按钮可用", win._btn.isEnabled())
    check("选框已出现", win._box.isVisible())
    check("选框动画进行中",
          win._box._anim is not None
          and win._box._anim.state() == QAbstractAnimation.State.Running)

    # 选中后：鼠标离开已选中的左律师 → 恢复灰色
    win._update_near("left", False)
    win._update_near("left", False)
    win._update_near("left", False)
    check("已选中的左律师鼠标离开 → 灰色",
          win._state["left"] == "idle" and win._surface["left"]._gray is True)

    # 靠近右律师：右侧彩色、已选中的左律师保持灰色
    win._update_near("right", True)
    win._update_near("right", True)
    check("靠近右律师 → 右彩色", win._state["right"] == "hover"
          and win._surface["right"]._gray is False)
    check("已选中的左律师未靠近 → 保持灰色",
          win._state["left"] == "idle" and win._surface["left"]._gray is True)
    win._update_near("right", False)
    win._update_near("right", False)
    win._update_near("right", False)

    # 换选：旧律师播 16 灰色
    right_rect = win._surface["right"].geometry()
    win._select("right", right_rect.center())
    check("换选 → 选中 right", win._selected == "right")
    check("旧律师进入 deselect(16)", win._state["left"] == "deselect")
    check("旧律师为灰色", win._surface["left"]._gray is True)
    win._surface["left"]._finish()
    check("16 播完 → 回 idle(14)", win._state["left"] == "idle")

    # ---- 确认与缩小消失 ----
    got = {}
    win.confirmed.connect(lambda s: got.update(side=s))
    win._hover_timer.stop()
    win._on_confirm_clicked()
    # 回归：点击确认后先定格画面（截图立即生成），缩小动画延迟 SHRINK_HOLD_MS 才开始
    check("确认后画面立即定格(截图就绪)",
          win._snapshot is not None and not win.isHidden())
    check("确认后缩小动画未立即开始", win._shrink_anim is None)

    def after_shrink():
        check("confirmed 信号发出(right)", got.get("side") == "right")

        # ---- 效果层（主线程触发，左键传 QPoint 与真实链路一致）----
        from overlay import EffectManager
        mgr = EffectManager("left")
        mgr.on_left_click(QPoint(300, 300))
        n1 = len(mgr._active)
        mgr.on_right_click((400, 400))
        n2 = len(mgr._active)
        mgr.on_window_appeared()
        n3 = len(mgr._active)
        check("左键 → 图片+视频浮层", n1 >= 2)
        check("右键 → 追加视频浮层", n2 >= n1 + 1)
        check("窗口事件 → 追加视频浮层", n3 >= n2 + 1)
        check("浮层均可见", all(w.isVisible() for w in mgr._active))
        # 回归：效果视频显示为原尺寸一半
        vids = [w for w in mgr._active if type(w).__name__ == "VideoSurface"]
        check("效果视频范围减半",
              all(0 < v.width() <= v.video_size[0] // 2 + 1
                  for v in vids))

        def after_wait():
            check("视频播完/图片渐隐 → 浮层自动清理", len(mgr._active) == 0)
            print("\n=== 结果 ===")
            fails = [n for n, c in results if not c]
            print("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}")
            app.quit()

        QTimer.singleShot(5000, after_wait)

    QTimer.singleShot(1500, after_shrink)
    QTimer.singleShot(20000, lambda: (print("超时退出"), app.quit()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
