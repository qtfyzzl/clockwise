#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「贪吃蛇式流动字」Canvas 主题：长春光华学院 电信张明达

==================== 为什么用「预渲染滚动帧」而不是位移 ====================
逐行读过固件（Clockface.cpp / PNGRender.h / CustomSprite.h）后确认的硬约束：

1) 固件字体是拉丁点阵，没有汉字 → 汉字只能预渲染成 PNG 精灵。
2) renderImage(base64, uint8_t x, uint8_t y)：坐标是 **uint8_t**！
   而 sprite 坐标是 int8_t。一旦 getX() < 0，传进 renderImage 会回绕成 200+，
   整块精灵直接不可见（不是从左边裁掉，是整块消失）→ 水平位移根本无法"滑出左边界"。
3) 位移启用条件 moveTargetX > -1 || moveTargetY > -1，负目标会被当成"未设置"。
4) 单帧精灵每 loopDelay 才允许推进一次 → 位移必然很卡。

所以真正的平滑流动只能靠「帧动画」：
   把「长春光华学院 电信张明达」无限平铺成一条长条，按固定像素步长切出 N 个
   64×22 的窗口帧，做成一个多帧精灵，原地播放 → 连续、单向、无缝循环的流动字。
   x/y 固定 (0,21)，永不位移，彻底绕开 2)3)4) 的坑。每个字再叠一个正弦纵向
   偏移（振幅 2px、波长 52px），整条字带就像蛇身一样起伏游动。

配色：蛇头「长」亮黄，其余青绿 → 像一条发光的蛇从左往右"游"过屏幕。

用法:
  python make_snake_text.py
产出:
  canvas/snake-text.json         主题文件（可直接上传设备）
  canvas/snake-text-preview.gif  动画预览
  canvas/snake-text-frame.png    两帧静态对照
"""

import base64
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cw_core as cw  # noqa: E402

TEXT = "长春光华学院 电信张明达"
FONT_PATH = "C:/Windows/Fonts/simhei.ttf"

CELL_W = 12              # 12px 汉字：64 屏上可读性与体积的平衡点
CELL_H = 14
GAP = 12                 # 文字与下一轮之间的空隙
PERIOD = len(TEXT) * CELL_W + GAP   # 一个完整循环宽度 = 144 + 12 = 156

# 蛇形起伏：每个字按自身横坐标做一个正弦纵向偏移，整条丝带像蛇身一样波浪前进。
# 振幅 3px（能看出起伏又不伤可读性）；波长取整个循环宽度 → 一条平缓的大 S，
# 相邻字高度差 ~1.5px，不会出现锯齿台阶。
WAVE_AMP = 3
WAVE_LAMBDA = 156        # = PERIOD，一个完整波
FRAME_H = CELL_H + 2 * WAVE_AMP + 2   # 22（上下各 1px 余量）
BASE_Y = (64 - FRAME_H) // 2          # 21

HEAD_COLOR = (255, 226, 40)     # 蛇头：亮黄
BODY_COLOR = (0, 255, 90)       # 蛇身：荧光绿

# 帧动画节拍
STEP_TARGET = 4          # 每帧横向推进像素（12px 字下 39 帧，体积/顺滑平衡）
FRAME_DELAY = 50         # ms/帧 → 39 帧 ≈ 1950ms，配合 loopDelay 2s
LOOP_DELAY = 2000        # 每 2s 回到第 0 帧（偶数秒对齐）
JSON_BUDGET = 15000      # 留余量，固件 doc=16384

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(_ROOT, "canvas", "snake-text.json")
OUT_GIF = os.path.join(_ROOT, "canvas", "snake-text-preview.gif")
OUT_FRAME = os.path.join(_ROOT, "canvas", "snake-text-frame.png")


def glyph_mask(ch):
    grid = [[0] * CELL_W for _ in range(CELL_H)]
    if ch.strip() == "":
        return grid
    font = ImageFont.truetype(FONT_PATH, CELL_W)
    big = CELL_W * 3
    canvas = Image.new("L", (big, big), 0)
    ImageDraw.Draw(canvas).text((CELL_W, CELL_W), ch, fill=255, font=font)
    bbox = canvas.getbbox()
    if not bbox:
        return grid
    glyph = canvas.crop(bbox)
    gw, gh = glyph.size
    if gw > CELL_W or gh > CELL_H:
        s = min(CELL_W / float(gw), CELL_H / float(gh))
        glyph = glyph.resize((max(1, int(round(gw * s))), max(1, int(round(gh * s)))),
                             Image.LANCZOS)
        gw, gh = glyph.size
    ox, oy = (CELL_W - gw) // 2, (CELL_H - gh) // 2
    px = glyph.load()
    for y in range(gh):
        for x in range(gw):
            if px[x, y] >= 96:
                grid[oy + y][ox + x] = 1
    return grid


def build_strip():
    """返回 2*PERIOD 宽、FRAME_H 高的颜色 id 画布（1=绿, 2=黄）。

    每个字按自身横坐标叠一个正弦纵向偏移 → 整条字带呈蛇形起伏。
    由于波长整除 PERIOD，平铺第二遍时波相位与第一遍一致，循环无缝。
    """
    width = PERIOD * 2
    rows = [[0] * width for _ in range(FRAME_H)]
    for rep in range(2):
        base = rep * PERIOD
        for i, ch in enumerate(TEXT):
            cid = 2 if i == 0 else 1
            g = glyph_mask(ch)
            cx = i * CELL_W
            wave = int(round(WAVE_AMP * math.sin(2 * math.pi * cx / WAVE_LAMBDA)))
            top = 1 + WAVE_AMP + wave          # 上下各留 1px
            for y in range(CELL_H):
                for x in range(CELL_W):
                    if g[y][x]:
                        rows[top + y][base + cx + x] = cid
    return rows


def frame_png(rows, cols, width, height):
    """从画布切出 width 列 × height 行，生成索引色 PNG（按本帧实际用色裁剪调色板）。"""
    used = [0]
    for y in range(height):
        for x in range(cols, cols + width):
            v = rows[y][x]
            if v and v not in used:
                used.append(v)
    cmap = {0: (0, 0, 0), 1: BODY_COLOR, 2: HEAD_COLOR}
    palette = [cmap[u] for u in used]
    remap = {u: i for i, u in enumerate(used)}

    indices = []
    for y in range(height):
        for x in range(width):
            v = rows[y][cols + x]
            indices.append(remap.get(v, 0))
    return cw.encode_indexed_png(indices, palette, width, height)


def build_theme(step):
    rows = build_strip()
    n = (PERIOD + step - 1) // step
    frames = []
    for k in range(n):
        png = frame_png(rows, k * step, 64, FRAME_H)
        frames.append({"image": base64.b64encode(png).decode("ascii")})
    theme = {
        "name": "蛇形流动字-长春光华学院",
        "version": 1,
        "author": "@you",
        "bgColor": 0,
        "delay": FRAME_DELAY,
        "setup": [],
        "sprites": [frames],
        "loop": [{
            "type": "sprite",
            "sprite": 0,
            "x": 0,
            "y": BASE_Y,
            "frameDelay": FRAME_DELAY,
            "loopDelay": LOOP_DELAY,
        }],
    }
    return theme, n, step


def make_preview(theme):
    frames = []
    step_ms = FRAME_DELAY
    t = 0
    while t < LOOP_DELAY:
        img = cw.render_theme_animated(theme, t)
        frames.append(img.resize((cw.PANEL * 5, cw.PANEL * 5), Image.NEAREST))
        t += step_ms
    frames[0].save(OUT_GIF, save_all=True, append_images=frames[1:],
                   duration=step_ms, loop=0, optimize=False)

    a = cw.render_theme_animated(theme, 0)
    b = cw.render_theme_animated(theme, LOOP_DELAY // 2)
    sheet = Image.new("RGB", (cw.PANEL * 3 * 2 + 8, cw.PANEL * 3), (20, 20, 24))
    sheet.paste(a.resize((cw.PANEL * 3, cw.PANEL * 3), Image.NEAREST), (0, 0))
    sheet.paste(b.resize((cw.PANEL * 3, cw.PANEL * 3), Image.NEAREST),
                (cw.PANEL * 3 + 8, 0))
    sheet.save(OUT_FRAME)


def main():
    chosen = None
    for step in (STEP_TARGET, 4, 5, 6, 8, 10):
        theme, n, st = build_theme(step)
        size = cw.theme_bytes(theme)
        print("step=%dpx 帧数=%2d  JSON=%d B %s"
              % (st, n, size, "OK" if size <= JSON_BUDGET else "超预算"))
        if size <= JSON_BUDGET:
            chosen = (theme, n, st, size)
            break
    if chosen is None:
        raise SystemExit("无法在预算内生成，请增大 STEP_TARGET")

    theme, n, st, size = chosen
    print("\n采用 step=%dpx, %d 帧, JSON=%d B" % (st, n, size))

    issues = cw.validate(theme)
    errs = [m for lv, m in issues if lv == "error"]
    warns = [m for lv, m in issues if lv != "error"]
    print("校验: error=%d 其它=%d" % (len(errs), len(warns)))
    for m in errs:
        print("  [error]", m)
    for m in warns:
        print("  [warn]", m)
    if errs:
        raise SystemExit("存在 error")

    mx = 0
    for fr in theme["sprites"][0]:
        mx = max(mx, len(base64.b64decode(fr["image"])))
    print("单帧 PNG 最大 %d B（上限 1024）" % mx)
    if mx > 1024:
        raise SystemExit("单帧超 1024B")

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        f.write(cw.theme_to_json(theme))
    print("写出", OUT_JSON)
    make_preview(theme)
    print("写出", OUT_GIF)
    print("写出", OUT_FRAME)


if __name__ == "__main__":
    main()
