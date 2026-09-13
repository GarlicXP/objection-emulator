# -*- coding: utf-8 -*-
"""基于 PyAV 的视频解码渲染控件。

支持：带透明通道的 WebM/MP4、灰度滤镜、播放倍速、循环 / 单次播放。
既可嵌入选择界面（子控件），也可作为桌面透明悬浮层（独立窗口）。
"""
import logging

import av
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtMultimedia import QAudioFormat, QAudioSink
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

_GRAY_WEIGHT = np.array([0.299, 0.587, 0.114], dtype=np.float32)


class VideoSurface(QWidget):
    """逐帧解码并绘制视频，输出 RGBA 帧。

    with_audio=True 时（桌面效果浮层）会同步播放音轨；选择界面保持静音。
    """

    finished = Signal()  # 单次播放结束时发出

    def __init__(self, path: str, gray: bool = False, speed: float = 1.0,
                 loop: bool = True, parent: QWidget = None, as_overlay: bool = False,
                 with_audio: bool = False):
        super().__init__(parent)
        if as_overlay:
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            # 纯视觉效果层：不拦截鼠标
            self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self._with_audio = bool(with_audio)
        self._audio_sink = None
        self._audio_io = None
        self._pcm = None
        self._finish_pending = False

        self._gray = bool(gray)
        self._speed = speed
        self._loop = loop
        self._path = None
        self._container = None
        self._stream = None
        self._alpha_stream = None
        self._frames = None
        self._alpha_frames = None
        self._last_alpha = None
        self._interval_ms = 40
        self._img = None          # 当前帧 QImage
        self._arr = None          # 当前帧 RGBA ndarray（灰度切换时重算用）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

        if path:
            self._open(path)
            self._timer.start(self._interval_ms)

    # ---------- 解码控制 ----------

    def _open(self, path: str):
        self.close_video(keep_image=True)
        self._path = path
        self._container = av.open(path)
        streams = self._container.streams.video
        self._stream = streams[0]
        # 双轨 WebM：第二轨为 alpha 平面（灰阶），解码后合并
        self._alpha_stream = streams[1] if len(streams) > 1 else None
        fps = float(self._stream.average_rate or 25.0)
        self._interval_ms = max(10, int(round(1000.0 / fps / max(self._speed, 0.05))))
        self._frames = iter(self._container.decode(self._stream))
        self._alpha_frames = (iter(self._container.decode(self._alpha_stream))
                              if self._alpha_stream is not None else None)
        if self._with_audio:
            self._pcm = self._collect_audio(self._path)
            self._start_audio()

    def _collect_audio(self, path: str):
        """把音轨重采样为 48k/立体声/Int16 平面格式，交错后一次性取出。

        注意：必须用独立容器解码音频——若与视频解码共用容器，音频循环会
        把全部包解复用走，导致视频迭代器立即 EOF、画面无法播放。
        """
        if not path:
            return None
        try:
            c2 = av.open(path)
            try:
                astreams = c2.streams.audio
                if not astreams:
                    return None
                resampler = av.AudioResampler(format="s16p", layout="stereo",
                                              rate=48000)
                chunks = []

                def _append(frame):
                    arr = frame.to_ndarray()  # 平面形式 (2, n)
                    n = arr.shape[1]
                    out = np.empty((2 * n,), dtype=np.int16)
                    out[0::2] = arr[0]
                    out[1::2] = arr[1]
                    chunks.append(out.tobytes())

                for frame in c2.decode(astreams[0]):
                    for f in resampler.resample(frame):
                        _append(f)
                for f in resampler.resample(None):
                    _append(f)
                return b"".join(chunks)
            finally:
                c2.close()
        except Exception as exc:
            log.warning("音频解码失败: %s", exc)
            return None

    def _start_audio(self):
        if not self._pcm or self._audio_sink is not None:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(48000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        try:
            sink = QAudioSink(fmt)
            # 默认缓冲只有约 1/4 秒，整段 PCM 一次写入会被丢弃大半；
            # 必须把缓冲调大到能容纳整段音频，音轨才会完整播完
            sink.setBufferSize(len(self._pcm))
            self._audio_sink = sink
            self._audio_io = sink.start()
            self._audio_io.write(self._pcm)
        except Exception as exc:
            log.warning("音频播放失败: %s", exc)
            self._audio_sink = None
            self._audio_io = None

    def _stop_audio(self):
        if self._audio_sink is not None:
            try:
                self._audio_sink.stop()
            except Exception:
                pass
        self._audio_sink = None
        self._audio_io = None

    def close_video(self, keep_image: bool = False):
        self._stop_audio()
        self._pcm = None
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
        self._stream = None
        self._alpha_stream = None
        self._frames = None
        self._alpha_frames = None
        self._last_alpha = None
        # 重载（14↔15 切换）时保留上一帧，避免出现空白闪烁
        if not keep_image:
            self._img = None
            self._arr = None

    def load(self, path: str, gray=None, speed=None, loop=None):
        """切换视频源（选择界面状态机用），并立即从头播放。"""
        if gray is not None:
            self._gray = bool(gray)
        if speed is not None:
            self._speed = speed
        if loop is not None:
            self._loop = loop
        self._open(path)
        self._timer.start(self._interval_ms)

    def play(self):
        if not self._timer.isActive():
            self._timer.start(self._interval_ms)

    def stop(self):
        self._timer.stop()

    def set_gray(self, gray: bool):
        if gray != self._gray:
            self._gray = bool(gray)
            self._rebuild_img()
            self.update()

    @property
    def video_size(self):
        if self._stream is not None:
            return self._stream.width, self._stream.height
        return 0, 0

    # ---------- 逐帧推进 ----------

    def _step(self):
        try:
            frame = next(self._frames)
        except StopIteration:
            if self._loop and self._path:
                # 循环：重新打开容器从头播
                self._open(self._path)
                try:
                    frame = next(self._frames)
                except StopIteration:
                    self._finish()
                    return
            else:
                self._finish()
                return
        except Exception:
            self._finish()
            return
        try:
            rgba = frame.to_ndarray(format="rgba")
            if self._alpha_frames is not None:
                aplane = self._last_alpha
                try:
                    aframe = next(self._alpha_frames)
                    aplane = np.asarray(aframe.to_ndarray(format="gray"))
                    if aplane.ndim == 3:
                        aplane = aplane[:, :, 0]
                    self._last_alpha = aplane
                except StopIteration:
                    pass
                if aplane is not None:
                    h = min(rgba.shape[0], aplane.shape[0])
                    w = min(rgba.shape[1], aplane.shape[1])
                    rgba[:h, :w, 3] = aplane[:h, :w]
            self._arr = rgba
        except Exception:
            return
        self._rebuild_img()
        self.update()

    def _finish(self):
        self._timer.stop()
        # 带音频的单次播放：保留最后一帧，等音轨播完再通知清理
        self.close_video(keep_image=True)
        if self._audio_sink is not None:
            self._finish_pending = True
            QTimer.singleShot(300, self._emit_finished)
            return
        self.finished.emit()

    def _emit_finished(self):
        try:
            self._stop_audio()
            self.finished.emit()
        except RuntimeError:
            pass  # 控件已被销毁

    def _rebuild_img(self):
        if self._arr is None:
            return
        if self._gray:
            rgb = self._arr[:, :, :3].astype(np.float32) @ _GRAY_WEIGHT
            y = rgb.astype(np.uint8)
            out = np.dstack([y, y, y, self._arr[:, :, 3]])
        else:
            out = self._arr
        h, w = out.shape[:2]
        self._img = QImage(out.data, w, h, out.strides[0],
                           QImage.Format.Format_RGBA8888).copy()

    # ---------- 绘制 ----------

    def paintEvent(self, event):
        if self._img is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        src_w, src_h = self._img.width(), self._img.height()
        if src_w <= 0 or src_h <= 0:
            return
        target = self.rect()
        scale = min(target.width() / src_w, target.height() / src_h)
        dw, dh = int(src_w * scale), int(src_h * scale)
        x = (target.width() - dw) // 2
        y = (target.height() - dh) // 2
        p.drawImage(QRect(x, y, dw, dh), self._img,
                    QRect(0, 0, src_w, src_h))

    def destroyEvent(self, event):
        self.close_video()
        super().destroyEvent(event)
