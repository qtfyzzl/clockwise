#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竖排「蛇形流动字」Canvas 主题（严格遵循 canvas/THEME-SPEC.md）

文本：长春光华学院 电信张明达

设计：
  - 内容**自上而下竖排**（每字一行，逐字向下堆叠），整体滚动方向也是自上而下。
  - 叠一层**轻微、有节奏的左右摆动**（正弦，振幅 2px，每个循环 2 个周期）。
  - 速度舒缓：30 帧 × 160ms ≈ 4.8s 走完一轮（约 40px/s）。
  - 全部用「预渲染帧动画」：sprite 固定 x=22/y=0，不参与位移，
    避开固件 renderImage(uint8_t) 负坐标整块消失、以及位移擦除的坑。

严格对齐 THEME-SPEC：
  - 每帧 PNG 一律 **8-bit、颜色类型 2 (RGB)**（绝不用 1/2-bit 索引色——
    这是上一版设备无限重启的根因）。宽 20 ≤64，高 64 ≤64，解码后 ~300B ≤1024。
  - JSON ≤16KB；每个元素都有 type；坐标 0..63。
  - 精灵总像素 30×20×64 = 38400 < 40000。

产出：
  canvas/snake-text-v2.json
  canvas/snake-text-v2-preview.gif
  canvas/snake-text-v2-frame.png
"""

import base64
import io
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cw_core as cw  # noqa: E402

TEXT = "长春光华学院 电信张明达"
FONT_PATH = "C:/Windows/Fonts/simhei.ttf"

CW = 16                  # 单字宽
CH = 17                  # 单字占高（含 3px 行距）
PERIOD = len(TEXT) * CH + 12   # 竖排一屏循环高度 = 204 + 12 = 216

W = 22                   # 帧宽：16 字宽 + 2×2 摆动 + 2 余量
H = 64                   # 帧高 = 整屏
SWAY_AMP = 2             # 左右摆幅（轻微）
SWAY_CYCLES = 2          # 每个滚动循环摆 2 次（有节奏）
N_FRAMES = 28            # 28 帧 → 总像素 39424 < 40000
FRAME_DELAY = 178        # ms/帧；28×178≈4984ms，贴合 loopDelay=5000，循环无停顿
LOOP_DELAY = 5000        # 每 5s 回到第 0 帧（1000 的倍数，重置门才成立）

HEAD_COLOR = (255, 226, 40)
BODY_COLOR = (0, 255, 90)
BG = (0, 0, 0)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(_ROOT, "canvas", "snake-text-v2.json")
OUT_GIF = os.path.join(_ROOT, "canvas", "snake-text-v2-preview.gif")
OUT_FRAME = os.path.join(_ROOT, "canvas", "snake-text-v2-frame.png")


def glyph_mask(ch):
    """返回 CW×CH 的 0/1 蒙版；字模原生 13px 渲染后二值化。"""
    grid = [[0] * CW for _ in range(CH)]
    if ch.strip() == "":
        return grid
    font = ImageFont.truetype(FONT_PATH, 14)
    big = CH * 3
    canvas = Image.new("L", (big, big), 0)
    ImageDraw.Draw(canvas).text((CH, CH), ch, fill=255, font=font)
    bbox = canvas.getbbox()
    if not bbox:
        return grid
    g = canvas.crop(bbox)
    gw, gh = g.size
    if gw > CW or gh > CH - 1:
        s = min(CW / float(gw), (CH - 1) / float(gh))
        g = g.resize((max(1, int(round(gw * s))), max(1, int(round(gh * s)))),
                     Image.LANCZOS)
        gw, gh = g.size
    ox, oy = (CW - gw) // 2, (CH - 1 - gh) // 2
    px = g.load()
    for y in range(gh):
        for x in range(gw):
            if px[x, y] >= 96:
                grid[oy + y][ox + x] = 1
    return grid


def build_column():
    """竖排长条：宽度 W+2*amp，高度 2*PERIOD，字色 黄头/绿身。"""
    col_w = W + 2 * SWAY_AMP
    column = Image.new("RGB", (col_w, PERIOD * 2), BG)
    tx = (col_w - CW) // 2
    for rep in range(2):
        for i, ch in enumerate(TEXT):
            color = HEAD_COLOR if i == 0 else BODY_COLOR
            g = glyph_mask(ch)
            tile = Image.new("RGB", (CW, CH), color)
            mask = Image.new("L", (CW, CH), 0)
            mp = mask.load()
            for y in range(CH):
                for x in range(CW):
                    if g[y][x]:
                        mp[x, y] = 255
            column.paste(tile, (tx, rep * PERIOD + i * CH), mask)
    return column, col_w


def build_theme():
    column, col_w = build_column()
    base_x = (W - CW) // 2
    text_x = (col_w - CW) // 2
    frames = []
    for k in range(N_FRAMES):
        # 左右摆动：整块内容在帧内平移
        dx = int(round(SWAY_AMP * math.sin(2 * math.pi * SWAY_CYCLES * k / float(N_FRAMES))))
        crop_x = text_x - (base_x + dx)
        # 自上而下滚动：随 k 增大窗口上移 → 内容视觉向下移动
        y0 = int(round((PERIOD - k * PERIOD / float(N_FRAMES)) % PERIOD))
        frame = Image.new("RGB", (W, H), BG)
        win = column.crop((crop_x, y0, crop_x + W, y0 + H))
        frame.paste(win, (0, 0))
        buf = io.BytesIO()
        frame.save(buf, "PNG")          # PIL RGB → 8-bit, color type 2
        frames.append({"image": base64.b64encode(buf.getvalue()).decode("ascii")})

    theme = {
        "name": "竖排流动字-长春光华学院",
        "version": 1,
        "author": "@you",
        "bgColor": 0,
        "delay": FRAME_DELAY,
        "setup": [],
        "sprites": [frames],
        "loop": [{
            "type": "sprite",
            "sprite": 0,
            "x": (64 - W) // 2,
            "y": 0,
            "frameDelay": FRAME_DELAY,
            "loopDelay": LOOP_DELAY,
        }],
    }
    return theme


def make_preview(theme):
    frames = []
    t = 0
    while t < LOOP_DELAY:
        img = cw.render_theme_animated(theme, t)
        frames.append(img.resize((cw.PANEL * 5, cw.PANEL * 5), Image.NEAREST))
        t += FRAME_DELAY
    frames[0].save(OUT_GIF, save_all=True, append_images=frames[1:],
                   duration=FRAME_DELAY, loop=0, optimize=False)

    picks = [0, LOOP_DELAY // 4, LOOP_DELAY // 2, 3 * LOOP_DELAY // 4]
    thumbs = [cw.render_theme_animated(theme, p).resize(
        (cw.PANEL * 3, cw.PANEL * 3), Image.NEAREST) for p in picks]
    sheet = Image.new("RGB", (len(thumbs) * cw.PANEL * 3 + (len(thumbs) - 1) * 8,
                              cw.PANEL * 3), (22, 22, 26))
    x = 0
    for th in thumbs:
        sheet.paste(th, (x, 0))
        x += th.width + 8
    sheet.save(OUT_FRAME)


def main():
    theme = build_theme()
    size = cw.theme_bytes(theme)
    frames = theme["sprites"][0]
    total_px = len(frames) * W * H
    sizes = [len(base64.b64decode(f["image"])) for f in frames]

    print("帧数=%d  尺寸=%dx%d  总像素=%d" % (len(frames), W, H, total_px))
    print("单帧 PNG: max=%dB  min=%dB (上限 1024)" % (max(sizes), min(sizes)))
    print("JSON=%dB (上限 16384)" % size)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        f.write(cw.theme_to_json(theme))
    print("写出", OUT_JSON)
    make_preview(theme)
    print("写出", OUT_GIF)
    print("写出", OUT_FRAME)


if __name__ == "__main__":
    main()
