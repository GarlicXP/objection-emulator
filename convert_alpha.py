# -*- coding: utf-8 -*-
"""把带透明通道的视频转换为双轨 VP9 WebM（主画面轨 + alpha 平面轨）。

背景说明：
  标准 WebM 的 alpha 存储方式是“单轨 + BlockAdditions 附加 alpha 码流”，但 FFmpeg
  的封装器写不出 alpha 数据、解码器也不会合并还原（只把 AlphaMode 导出为元数据）。
  因此对 FFmpeg/PyAV 技术栈而言，任何标准 alpha WebM 都无法解出透明通道。

  本工具采用可行替代方案：把主画面（RGB）与 alpha 平面（灰阶）分别编码为两条 VP9
  视频轨，装入同一个 WebM 文件（体积约 90KB/段）。播放端（media_player.py）解码两
  条轨后在运行时合并为 RGBA，透明效果与原 MOV 一致。

用法：
    python convert_alpha.py 源视频 输出.webm [crf主 crfAlpha]
"""
import os
import subprocess
import sys

import av
import numpy as np

MAIN_CRF = 30
ALPHA_CRF = 35


def _run(args: list):
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 失败: %s" % proc.stderr[-1500:])


def convert(src: str, dst: str, main_crf: int = MAIN_CRF,
            alpha_crf: int = ALPHA_CRF) -> None:
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="alpha_webm_")
    main_path = os.path.join(tmpdir, "main.webm")
    alpha_path = os.path.join(tmpdir, "alpha.webm")
    try:
        # 主画面：去掉 alpha 的 RGB → VP9
        _run([
            "ffmpeg", "-y", "-v", "error", "-i", src,
            "-vf", "format=rgba,format=rgb24",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p",
            "-crf", str(main_crf), "-b:v", "0",
            "-deadline", "good", "-cpu-used", "4", "-an",
            main_path,
        ])
        # alpha 平面：灰阶 → VP9（强制 full range，保证 alpha 数值不变）
        _run([
            "ffmpeg", "-y", "-v", "error", "-i", src,
            "-vf", "alphaextract,format=gray",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p",
            "-color_range", "pc",
            "-crf", str(alpha_crf), "-b:v", "0",
            "-deadline", "good", "-cpu-used", "4", "-an",
            alpha_path,
        ])
        # 合并为双轨 WebM，并保留音轨（转码为 Opus，webm 标准音频）
        probe = av.open(src)
        has_audio = len(probe.streams.audio) > 0
        probe.close()
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-i", main_path, "-i", alpha_path, "-i", src,
            "-map", "0:v:0", "-map", "1:v:0",
        ]
        if has_audio:
            cmd += ["-map", "2:a:0", "-c:a", "libopus", "-b:a", "96k"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "copy", dst]
        _run(cmd)
    finally:
        for p in (main_path, alpha_path):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def verify(path: str) -> dict:
    """解码双轨文件，合并 alpha 后返回帧信息。"""
    container = av.open(path)
    streams = container.streams.video
    info = {"tracks": len(streams), "size": os.path.getsize(path),
            "pix_fmts": [s.codec_context.pix_fmt for s in streams],
            "audio": len(container.streams.audio)}
    main_s, alpha_s = streams[0], (streams[1] if len(streams) > 1 else None)
    frame = next(iter(container.decode(main_s)))
    rgba = frame.to_ndarray(format="rgba")
    if alpha_s is not None:
        aframe = next(iter(container.decode(alpha_s)))
        aplane = np.asarray(aframe.to_ndarray(format="gray"))
        rgba[:, :, 3] = aplane
    alpha = rgba[:, :, 3]
    info["alpha_min"] = int(alpha.min())
    info["alpha_max"] = int(alpha.max())
    info["transparent_px"] = int((alpha < 255).sum())
    container.close()
    return info


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main_crf = int(sys.argv[3]) if len(sys.argv) > 3 else MAIN_CRF
    alpha_crf = int(sys.argv[4]) if len(sys.argv) > 4 else ALPHA_CRF
    convert(sys.argv[1], sys.argv[2], main_crf, alpha_crf)
    print("生成:", sys.argv[2])
    print("验证:", verify(sys.argv[2]))
