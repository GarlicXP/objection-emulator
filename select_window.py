# -*- coding: utf-8 -*-
"""选择界面：窗口形态、小尺寸、点击选人。

- 背景左深蓝 / 右深红，标题「请选择您的律师」，播放 bgm.mp3（选完后淡出）。
- 未靠近时两侧均为灰色 14/24 循环（0.5x）；靠近左视频 → 彩色 15、
  靠近右视频 → 彩色 25（按视频区域判定，带滞回防快速滑动闪动）。
- 选中只产生选框：点击视频区域 → 从点击点扩散出一个框，0.5s 内扩到视频边缘
  并停留；鼠标没靠近的视频（包括已选中的那一侧）始终保持灰色。
- 改选另一侧时旧框消失、动画重播（可打断），旧律师播放 16/26 灰色。
- 「确认选择」按钮仅在已选中时可用；点击后窗口按矩形从边框向中心缩小消失。
- 选择界面视频全程静音（bgm 除外）。
"""
import logging
import os

from PySide6.QtCore import (QEasingCurve, QPoint, QRect, Qt, QTimer, Signal,
                            QUrl, QVariantAnimation)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from config import (BGM_FADE_IN_MS, BGM_FADE_OUT_MS, BGM_PATH, BOX_ANIM_MS,
                    COLOR_LEFT, COLOR_RIGHT, CONFIRM_TEXT, DEFAULT_H, DEFAULT_W,
                    HOVER_ENTER_TICKS, HOVER_LEAVE_TICKS, HOVER_RADIUS,
                    IDLE_SPEED, MIN_H, MIN_W, SELECT_LEFT, SELECT_RIGHT,
                    SHRINK_HOLD_MS, SHRINK_MS, TITLE, media)
from media_player import VideoSurface

log = logging.getLogger(__name__)


class SelectionBox(QWidget):
    """选择框：从点击点扩散到视频边缘，随后停留在该视频区域。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()
        self._start = QPoint(0, 0)
        self._target = QRect()
        self._rect = QRect()
        self._anim = None

    def start_anim(self, start_point: QPoint, target: QRect):
        """从 start_point 起，在 BOX_ANIM_MS 内扩散到 target 并停留。"""
        self._anim_stop()
        self._start = QPoint(start_point)
        self._target = QRect(target)
        self._rect = QRect(self._start.x(), self._start.y(), 0, 0)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(BOX_ANIM_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_tick)
        anim.finished.connect(self._on_done)
        self._anim = anim
        anim.start()

    def set_target(self, target: QRect):
        """窗口尺寸变化时让静态框跟随目标区域（无动画）。"""
        self._anim_stop()
        self._target = QRect(target)
        self._rect = QRect(self._target)
        self.update()

    def clear(self):
        self._anim_stop()
        self.hide()

    def _anim_stop(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None

    def _on_tick(self, t: float):
        s, e = self._start, self._target
        self._rect = QRect(
            round(s.x() + (e.x() - s.x()) * t),
            round(s.y() + (e.y() - s.y()) * t),
            round(e.width() * t),
            round(e.height() * t),
        )
        self.update()

    def _on_done(self):
        self._rect = QRect(self._target)
        self.update()

    def paintEvent(self, event):
        if self._rect.isEmpty():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRect(self._rect).adjusted(2, 2, -2, -2)
        if r.width() <= 0 or r.height() <= 0:
            return
        p.setPen(QPen(QColor(255, 255, 255, 70), 9))
        p.drawRoundedRect(r, 16, 16)
        p.setPen(QPen(QColor(255, 255, 255, 255), 3))
        p.drawRoundedRect(r, 12, 12)


class SelectWindow(QWidget):
    """窗口形态的选择界面。"""

    confirmed = Signal(str)  # 参数为 "left" / "right"

    def __init__(self):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(TITLE)
        self.resize(DEFAULT_W, DEFAULT_H)
        self.setMinimumSize(MIN_W, MIN_H)
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2)

        self._selected = None
        # 初始为 "none"，确保 __init__ 里的 _load_state("idle") 真正执行加载
        self._state = {"left": "none", "right": "none"}
        self._near = {"left": False, "right": False}
        self._near_ticks = {"left": 0, "right": 0}  # 滞回计数（防快速滑动闪动）
        self._shrinking = False
        self._snapshot = None
        self._snap_rect = None
        self._shrink_anim = None
        self._bgm = None
        self._bgm_out = None

        # 左右视频区（选择界面一律静音）
        self._surface = {}
        for side in ("left", "right"):
            s = VideoSurface("", gray=True, speed=IDLE_SPEED, loop=True,
                             parent=self, with_audio=False)
            s.finished.connect(lambda side=side: self._on_finished(side))
            self._surface[side] = s

        self._title = QLabel(TITLE, self)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(
            "font-size: 26px; font-weight: bold; color: white;"
            "background: transparent;")

        self._hint = QLabel("提示：鼠标靠近视频可预览，点击视频选择律师，Esc 退出", self)
        self._hint.setStyleSheet(
            "font-size: 12px; color: rgba(255,255,255,150);"
            "background: transparent;")

        self._btn = QPushButton(CONFIRM_TEXT, self)
        self._btn.setEnabled(False)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; color: white;"
            " background: #1F6FEB; border: none; border-radius: 10px; }"
            "QPushButton:disabled { background: #444; }"
            "QPushButton:hover:enabled { background: #2E84FF; }")
        self._btn.clicked.connect(self._on_confirm_clicked)

        self._box = SelectionBox(self)

        self._hover_timer = QTimer(self)
        self._hover_timer.timeout.connect(self._update_hover)
        self._hover_timer.start(40)

        self._layout_ui()
        self._load_state("left", "idle")
        self._load_state("right", "idle")
        self._start_bgm()

    # ---------- 背景音乐 ----------

    def _start_bgm(self):
        """选择期间播放 bgm.mp3（淡入）。"""
        try:
            if not os.path.exists(BGM_PATH):
                log.warning("BGM 不存在: %s", BGM_PATH)
                return
            player = QMediaPlayer(self)
            out = QAudioOutput(self)
            player.setAudioOutput(out)
            player.setSource(QUrl.fromLocalFile(BGM_PATH))
            out.setVolume(0.0)
            self._bgm = player
            self._bgm_out = out
            player.play()
            anim = QVariantAnimation(self)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(BGM_FADE_IN_MS)
            anim.valueChanged.connect(
                lambda v: self._bgm_out.setVolume(float(v)))
            anim.start()
            log.info("BGM 开始播放")
        except Exception as exc:  # noqa: BLE001
            log.warning("BGM 启动失败: %s", exc)
            self._bgm = None
            self._bgm_out = None

    def _fade_out_bgm(self):
        """选完后 BGM 淡出并停止。"""
        if self._bgm is None:
            return
        player, out = self._bgm, self._bgm_out
        anim = QVariantAnimation(self)
        anim.setStartValue(float(out.volume()))
        anim.setEndValue(0.0)
        anim.setDuration(BGM_FADE_OUT_MS)
        anim.valueChanged.connect(lambda v: out.setVolume(float(v)))
        anim.finished.connect(player.stop)
        anim.start()
        log.info("BGM 淡出")

    # ---------- 布局 ----------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_ui()

    def _layout_ui(self):
        w, h = self.width(), self.height()
        self._title.setGeometry(0, 14, w, 40)
        btn_w, btn_h = 200, 44
        self._btn.setGeometry((w - btn_w) // 2, h - btn_h - 18, btn_w, btn_h)
        self._hint.setGeometry(16, h - 28, w - 32, 20)
        top, bottom = 66, h - 78
        vh = max(120, bottom - top)
        half = w // 2
        m = 24
        self._surface["left"].setGeometry(m, top, half - m - 8, vh)
        self._surface["right"].setGeometry(
            half + 8, top, w - half - m - 8, vh)
        self._box.setGeometry(0, 0, w, h)
        if self._selected is not None:
            self._box.set_target(self._surface[self._selected].geometry())

    # ---------- 悬停状态机（按视频区域 + 滞回防闪） ----------

    def _update_hover(self):
        if self._shrinking:
            return
        pos = self.mapFromGlobal(QCursor.pos())
        r = HOVER_RADIUS
        left = self._surface["left"].geometry().adjusted(-r, -r, r, r)
        right = self._surface["right"].geometry().adjusted(-r, -r, r, r)
        nl, nr = left.contains(pos), right.contains(pos)
        if nl and nr:
            # 两区重叠时取中心更近的一侧
            dl = (pos - left.center()).manhattanLength()
            dr = (pos - right.center()).manhattanLength()
            if dl <= dr:
                nr = False
            else:
                nl = False
        self._update_near("left", nl)
        self._update_near("right", nr)

    def _update_near(self, side: str, near: bool):
        """带滞回的靠近状态：连续多拍确认后才切换，避免鼠标快速划过时闪动。"""
        if self._shrinking:
            return
        if near == self._near[side]:
            self._near_ticks[side] = 0
            return
        self._near_ticks[side] += 1
        need = HOVER_ENTER_TICKS if near else HOVER_LEAVE_TICKS
        if self._near_ticks[side] >= need:
            self._near_ticks[side] = 0
            self._near[side] = near
            self._apply_near(side, near)

    def _apply_near(self, side: str, near: bool):
        """根据鼠标靠近情况切换视频（选中的律师未靠近时同样恢复灰色）。"""
        if near:
            if self._state[side] in ("idle", "deselect"):
                self._load_state(side, "hover")
        else:
            if self._state[side] == "hover":
                self._load_state(side, "idle")

    def _on_finished(self, side: str):
        """单次视频播完（仅 deselect 会单次播放）。"""
        if self._state[side] == "deselect":
            if self._near[side]:
                self._load_state(side, "hover")
            else:
                self._load_state(side, "idle")

    def _load_state(self, side: str, state: str):
        if self._state[side] == state:
            return
        self._state[side] = state
        cfg = SELECT_LEFT if side == "left" else SELECT_RIGHT
        s = self._surface[side]
        if state == "idle":
            s.load(media(cfg["idle"]), gray=True, speed=IDLE_SPEED,
                   loop=True)
        elif state == "hover":
            s.load(media(cfg["hover"]), gray=False, speed=1.0, loop=True)
        elif state == "deselect":
            s.load(media(cfg["leave"]), gray=True, speed=1.0, loop=False)
        log.info("选择界面状态 %s -> %s", side, state)

    # ---------- 点击选人 ----------

    def mousePressEvent(self, event):
        if self._shrinking:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            for side in ("left", "right"):
                area = self._surface[side].geometry().adjusted(-8, -8, 8, 8)
                if area.contains(pos):
                    self._select(side, pos)
                    return
        super().mousePressEvent(event)

    def _select(self, side: str, click_pos: QPoint):
        if side == self._selected:
            return
        if self._selected is not None:
            # 换选：旧律师播放 16/26 灰色，并重置其“靠近”状态
            self._near[self._selected] = False
            self._near_ticks[self._selected] = 0
            self._load_state(self._selected, "deselect")
        self._selected = side
        self._btn.setEnabled(True)
        self._box.start_anim(click_pos, self._surface[side].geometry())
        # 选中只决定选框；视频颜色仍跟随鼠标靠近（此处鼠标必然在该侧）
        self._near[side] = True
        self._near_ticks[side] = 0
        self._apply_near(side, True)
        log.info("选中律师: %s", side)

    # ---------- 确认与缩小消失 ----------

    def _on_confirm_clicked(self):
        if self._shrinking or self._selected is None:
            return
        self._begin_shrink(self._selected)

    def _begin_shrink(self, side: str):
        self._shrinking = True
        self._hover_timer.stop()
        self._box.clear()
        self._btn.setEnabled(False)
        self._title.hide()
        self._hint.hide()
        self._fade_out_bgm()
        for s in self._surface.values():
            s.stop()
        # 先抓取并暂停画面（定格），稍后再出现关闭动画
        self._snapshot = self.grab()
        self._snap_rect = QRect(0, 0, self.width(), self.height())
        self.update()
        QTimer.singleShot(SHRINK_HOLD_MS, self._start_shrink_anim)

    def _start_shrink_anim(self):
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(SHRINK_MS)
        anim.valueChanged.connect(self._on_shrink_tick)
        anim.finished.connect(self._on_shrink_done)
        self._shrink_anim = anim
        anim.start()

    def _on_shrink_tick(self, t: float):
        w = max(1, round(self._snap_rect.width() * t))
        h = max(1, round(self._snap_rect.height() * t))
        x = (self._snap_rect.width() - w) // 2
        y = (self._snap_rect.height() - h) // 2
        self._snap_rect = QRect(x, y, w, h)
        self.update()

    def _on_shrink_done(self):
        side = self._selected
        self.hide()
        self.confirmed.emit(side)

    def paintEvent(self, event):
        p = QPainter(self)
        if self._snapshot is not None:
            p.drawPixmap(self._snap_rect, self._snapshot, self.rect())
            return
        half = self.width() // 2
        p.fillRect(QRect(0, 0, half, self.height()), QColor(COLOR_LEFT))
        p.fillRect(QRect(half, 0, self.width() - half, self.height()),
                   QColor(COLOR_RIGHT))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and not self._shrinking:
            if self._bgm is not None:
                self._bgm.stop()
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return
        super().keyPressEvent(event)
