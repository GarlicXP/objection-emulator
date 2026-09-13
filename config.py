# -*- coding: utf-8 -*-
"""全局配置：媒体文件路径与各场景视频映射。"""
import os
import sys


def _resource_dir() -> str:
    """资源目录：打包后为 exe 解包目录（_MEIPASS），开发时为项目目录。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _resource_dir()
MEDIA_DIR = os.path.join(BASE_DIR, "media")
LSXZ_PNG = os.path.join(MEDIA_DIR, "lsxz.png")
LSXZ_WEBP = os.path.join(MEDIA_DIR, "lsxz.webp")  # 软件/托盘图标（带透明）
APP_ICON = LSXZ_WEBP if os.path.exists(LSXZ_WEBP) else LSXZ_PNG

# 带透明通道的视频（已转为 webm），其余为 mp4
_TRANSPARENT = {"11", "12", "13", "21", "22", "23"}


def media(name: str) -> str:
    ext = "webm" if name in _TRANSPARENT else "mp4"
    return os.path.join(MEDIA_DIR, f"{name}.{ext}")


# ---------- 选择界面（窗口形态、小尺寸） ----------
TITLE = "请选择您的律师"
CONFIRM_TEXT = "确认选择"
COLOR_LEFT = "#0A1E6E"       # 左半区：深蓝色
COLOR_RIGHT = "#8B0000"      # 右半区：深红色

SELECT_LEFT = {"idle": "14", "hover": "15", "leave": "16"}
SELECT_RIGHT = {"idle": "24", "hover": "25", "leave": "26"}

DEFAULT_W, DEFAULT_H = 960, 680   # 窗口默认尺寸
MIN_W, MIN_H = 760, 560           # 窗口最小尺寸
HOVER_RADIUS = 20                 # 鼠标“靠近”判定：仅紧贴视频区域向外扩展的像素
HOVER_ENTER_TICKS = 2             # 进入悬停需连续靠近 2 拍（约 80ms）
HOVER_LEAVE_TICKS = 3             # 离开悬停需连续离开 3 拍（约 120ms，防闪动）
IDLE_SPEED = 0.5                  # 默认循环 0.5x 播放
SHRINK_MS = 800                   # 确认后界面缩小动画时长（毫秒）
SHRINK_HOLD_MS = 400              # 确认后先暂停画面，再出现关闭动画
BOX_ANIM_MS = 500                 # 选中框从点击点扩散到视频边缘的时长

# 选择界面背景音乐（播放中淡入，选完后淡出）；随项目打包，同目录自包含
BGM_PATH = os.path.join(MEDIA_DIR, "bgm.mp3")
BGM_FADE_IN_MS = 600
BGM_FADE_OUT_MS = 900

# ---------- 选中后的桌面效果 ----------
# 左律师：左键 13 / 右键 11 / 出现窗口 12；右律师同理对应 2x 系列
EFFECT = {
    "left":  {"left_click": "13", "right_click": "11", "window": "12"},
    "right": {"left_click": "23", "right_click": "21", "window": "22"},
}

IMAGE_DISPLAY_WIDTH = 520    # lsxz.png 显示基准宽度（保持原图比例）
IMAGE_FLY_DURATION_MS = 700  # lsxz.png 旋转缩小飞向点击点的动画时长
EFFECT_VIDEO_SCALE = 0.5     # 效果视频（11/12/13/21/22/23）显示为原尺寸的一半
OVERLAY_MARGIN = 12          # 浮层距屏幕边缘的最小间距

# ---------- 桌面监听 ----------
WINDOW_POLL_MS = 300         # 新窗口轮询间隔
