# -*- coding: utf-8 -*-
"""把律师选择器编译为 Windows 单文件 exe（配合 build_exe.bat 使用）。

所有必需素材（media 目录：视频 / 图片 / lsxz.webp 图标 / bgm.mp3）都在本项目
文件夹内，无需任何外部文件；把整个文件夹拷到任意位置即可编译。

步骤：
1. 准备打包素材：复制 media 目录到暂存区。
2. 用 PySide6 把 lsxz.webp 转成 .ico（PNG-in-ICO，无需 Pillow）。
3. 调用 PyInstaller（onefile + windowed，收集 av 依赖）。
产物：dist\\律师选择器.exe
"""
import os
import shutil
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, "_build_stage")
STAGE_MEDIA = os.path.join(STAGE, "media")
ICO_PATH = os.path.join(STAGE, "app.ico")
EXE_NAME = "律师选择器"


def stage_media():
    """复制 media 目录（含全部视频、lsxz.webp 图标、bgm.mp3）到打包暂存区。"""
    if os.path.exists(STAGE):
        shutil.rmtree(STAGE)
    shutil.copytree(os.path.join(HERE, "media"), STAGE_MEDIA)
    names = sorted(os.listdir(STAGE_MEDIA))
    print(f"media 暂存: {STAGE_MEDIA}（{len(names)} 个文件）")


def make_ico():
    """用 PySide6 读取 lsxz.webp，写成 PNG-in-ICO 格式的 app.ico。"""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage

    src = os.path.join(STAGE_MEDIA, "lsxz.webp")
    if not os.path.exists(src):
        src = os.path.join(STAGE_MEDIA, "lsxz.png")
    img = QImage(src)
    if img.isNull():
        print("警告: 图标生成失败（图片不可读），将使用默认图标")
        return False
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    png = bytes(buf.data())
    w, h = img.width(), img.height()
    b_w = 0 if w >= 256 else w
    b_h = 0 if h >= 256 else h
    ico = struct.pack("<HHH", 0, 1, 1)
    ico += struct.pack("<BBBBHHII", b_w, b_h, 0, 0, 1, 32, len(png), 22)
    ico += png
    with open(ICO_PATH, "wb") as f:
        f.write(ico)
    print(f"图标已生成: {ICO_PATH} ({w}x{h})")
    return True


# 排除用不到的 Qt 大模块（QtMultimedia 及基础模块保留），显著缩小 exe
_EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
    "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtTest",
    "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtXml", "PySide6.QtXmlPatterns",
]


def build():
    # 注意：不要 --collect-all PySide6（会把全部 Qt 模块与插件都打进去，exe 超过
    # 280MB）；PyInstaller 内置的 PySide6 钩子会按实际 import 的模块收集
    # 依赖和对应插件（含 QtMultimedia 音视频后端）。
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", EXE_NAME,
        "--add-data", f"{STAGE_MEDIA};media",
        "--collect-all", "av",
    ]
    for mod in _EXCLUDES:
        cmd += ["--exclude-module", mod]
    if os.path.exists(ICO_PATH):
        cmd += ["--icon", ICO_PATH]
    cmd.append(os.path.join(HERE, "main.py"))
    print("运行:", " ".join(cmd))
    subprocess.run(cmd, cwd=HERE, check=True)
    exe = os.path.join(HERE, "dist", f"{EXE_NAME}.exe")
    print("\n构建完成:", exe, f"（约 {os.path.getsize(exe) // 1024 // 1024} MB）")
    print("提示: 全部素材已内置，exe 可独立运行；media 目录可继续自由替换素材后重编译。")


if __name__ == "__main__":
    stage_media()
    make_ico()
    build()
