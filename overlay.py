# -*- coding: utf-8 -*-
"""选中律师后的桌面效果层。

- 左键点击：lsxz.png 在所选侧随机位置出现，旋转缩小飞向鼠标点击点，到达时
  恰好消失（可叠加）；同时在所选侧随机位置播放 13 / 23 透明视频（带声音）。
- 右键点击：在所选侧随机位置播放 11 / 21。
- 桌面出现新窗口：在所选侧随机位置播放 12 / 22。
所有浮层均为无边框置顶、穿透鼠标的透明窗口，且效果视频带声音。
"""
import logging
import random

from PySide6.QtCore import QEasingCurve, QPoint, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from config import (EFFECT, EFFECT_VIDEO_SCALE, IMAGE_DISPLAY_WIDTH,
                    IMAGE_FLY_DURATION_MS, LSXZ_PNG, OVERLAY_MARGIN, media)
from media_player import VideoSurface

log = logging.getLogger(__name__)


class ExitHint(QWidget):
    """进入桌面效果模式后，在屏幕角落短暂提示退出快捷键（自动淡出）。"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        label = QLabel("桌面效果已开启：按 Ctrl+Shift+Q 退出", self)
        label.setStyleSheet(
            "color: white; background: rgba(20,20,20,205);"
            "border-radius: 12px; padding: 10px 18px; font-size: 14px;")
        label.adjustSize()
        self.resize(label.size())
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.right() - self.width() - 24,
                  geo.bottom() - self.height() - 24)
        self.show()
        QTimer.singleShot(8000, self._fade_out)
        log.info("已显示退出提示")

    def _fade_out(self):
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(500)
        anim.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
        anim.finished.connect(self.close)
        anim.start()


class ImageFly(QWidget):
    """旋转缩小飞向目标点的图片浮层，到达目标时尺寸归零消失。"""

    def __init__(self, pixmap: QPixmap, start: QPoint, end: QPoint,
                 duration_ms: int = IMAGE_FLY_DURATION_MS, on_done=None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._pm = pixmap
        self._base_w = pixmap.width()
        self._base_h = pixmap.height()
        self._start = start
        self._end = end
        self._angle = 0.0
        self._scale = 1.0
        self._on_done = on_done

        self.setGeometry(start.x(), start.y(), self._base_w, self._base_h)
        self.show()

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(duration_ms)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.valueChanged.connect(self._on_tick)
        self._anim.finished.connect(self._on_done_anim)
        self._anim.start()

    def _on_tick(self, value: float):
        t = float(value)
        x = self._start.x() + (self._end.x() - self._start.x()) * t
        y = self._start.y() + (self._end.y() - self._start.y()) * t
        self._angle = t * 360.0
        self._scale = 1.0 - t
        self.move(int(x - self._base_w / 2), int(y - self._base_h / 2))
        self.update()

    def _on_done_anim(self):
        self._pm = None
        self.hide()
        if self._on_done is not None:
            self._on_done(self)

    def paintEvent(self, event):
        if self._pm is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self._angle)
        p.scale(self._scale, self._scale)
        p.drawPixmap(int(-self._base_w / 2), int(-self._base_h / 2), self._pm)


class EffectManager:
    """根据所选律师生成各类桌面效果浮层。"""

    def __init__(self, side: str):
        self.side = side  # 'left' / 'right'
        self._screen = QGuiApplication.primaryScreen().geometry()
        self._active = []  # 持有引用，防止浮层被回收

    # ---------- 位置 ----------

    def _rand_pos(self, w: int, h: int):
        """在所选律师对应的半屏内生成随机左上角坐标。"""
        W, H = self._screen.width(), self._screen.height()
        m = OVERLAY_MARGIN
        if self.side == "left":
            x0, x1 = m, W // 2 - w - m
        else:
            x0, x1 = W // 2 + m, W - w - m
        x0, x1 = max(m, x0), min(W - w - m, x1)
        if x1 < x0:
            x1 = x0
        y0, y1 = m, max(m, H - h - m)
        if y1 < y0:
            y1 = y0
        return QPoint(random.randint(x0, x1), random.randint(y0, y1))

    # ---------- 视频浮层（带声音） ----------

    def spawn_video(self, code: str):
        """在所选侧随机位置单次播放一个透明视频（带音轨，显示为原尺寸一半）。"""
        try:
            surface = VideoSurface(media(code), gray=False, speed=1.0,
                                   loop=False, as_overlay=True, with_audio=True)
            vw, vh = surface.video_size
            if vw <= 0 or vh <= 0:
                surface.close_video()
                surface.deleteLater()
                return
            w = max(1, round(vw * EFFECT_VIDEO_SCALE))
            h = max(1, round(vh * EFFECT_VIDEO_SCALE))
            p = self._rand_pos(w, h)
            surface.setGeometry(p.x(), p.y(), w, h)
            surface.show()
            surface.play()
            self._active.append(surface)
            log.info("播放视频浮层: %s", code)

            def _cleanup():
                if surface in self._active:
                    self._active.remove(surface)
                surface.close_video()
                surface.close()
                surface.deleteLater()

            surface.finished.connect(_cleanup)
        except Exception as exc:  # noqa: BLE001
            log.exception("spawn_video(%s) 失败: %s", code, exc)

    # ---------- 图片飞行动画 ----------

    def spawn_image_fly(self, target: QPoint):
        """lsxz.png 从所选侧随机位置旋转缩小飞向 target，到达即消失。"""
        try:
            img = QImage(LSXZ_PNG)
            if img.isNull():
                log.warning("无法加载 %s", LSXZ_PNG)
                return
            base_w = IMAGE_DISPLAY_WIDTH
            base_h = max(1, int(img.height() * base_w / img.width()))
            # 必须先把图缩放到目标尺寸再显示（否则只会按原生小尺寸显示）
            img = img.scaled(base_w, base_h,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            start = self._rand_pos(base_w, base_h)
            fly = ImageFly(QPixmap.fromImage(img), start, target)
            self._active.append(fly)

            def _cleanup(_f):
                if fly in self._active:
                    self._active.remove(fly)
                fly.deleteLater()

            fly._on_done = _cleanup
            log.info("图片飞行动画: %s -> %s", start, target)
        except Exception as exc:  # noqa: BLE001
            log.exception("spawn_image_fly 失败: %s", exc)

    # ---------- 全局触发入口 ----------

    def close_all(self):
        """关闭并清理全部浮层（重选/退出时调用）。"""
        for w in list(self._active):
            try:
                if hasattr(w, "close_video"):
                    w.close_video()
                w.close()
                w.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        self._active.clear()
        log.info("已清理全部浮层")

    @staticmethod
    def _point_of(pos):
        """兼容 QPoint（信号）与 (x, y) 元组（测试直接调用）。"""
        if hasattr(pos, "x"):
            return QPoint(int(pos.x()), int(pos.y()))
        return QPoint(int(pos[0]), int(pos[1]))

    def on_left_click(self, pos):
        """左键：图片飞行 + 13/23 视频。"""
        self.spawn_image_fly(self._point_of(pos))
        self.spawn_video(EFFECT[self.side]["left_click"])

    def on_right_click(self, pos):
        """右键：11/21 视频。"""
        self.spawn_video(EFFECT[self.side]["right_click"])

    def on_window_appeared(self):
        """桌面出现新窗口：12/22 视频。"""
        self.spawn_video(EFFECT[self.side]["window"])
