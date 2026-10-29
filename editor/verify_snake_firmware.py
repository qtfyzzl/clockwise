#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固件级运动仿真：逐行复刻 Clockface.cpp 的 handleSpriteAnimation /
handleSpriteMovement（含擦除矩形、单帧推进、uint8 绘制语义），
用来在 PC 上验证「流动字」在真机上不会出现缺字 / 擦伤。

输出：
  canvas/snake-sim.png   仿真关键帧拼图
  stdout                 与理想画的差异像素数（越接近 0 越好）
"""

import base64
import io
import json
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cw_core as cw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEME = os.path.join(ROOT, "canvas", "snake-text.json")
OUT = os.path.join(ROOT, "canvas", "snake-sim.png")

PANEL = 64


def int8(v):
    v = int(v) & 0xFF
    return v - 256 if v >= 128 else v


class Sprite(object):
    def __init__(self, x, y, images):
        self.x = int8(x)
        self.y = int8(y)
        self.images = images          # list[Image RGB]
        self.w, self.h = images[0].size
        self.total = len(images)
        self.frame = 0
        self.count = 0
        self.last_frames = 0
        self.last_reset = 0
        self.last_reset_move = 0
        self.moving = False
        self.move_start = 1
        self.move_dur = 0
        self.mi_x = 0
        self.mi_y = 0
        self.mt_x = -1
        self.mt_y = -1
        self.ret = False
        self.reversing = False

    def inc(self):
        self.frame += 1
        if self.frame >= self.total:
            self.frame = 0


def lerp_i8(a, b, t):
    # C++: int8_t(start + (int8_t)(t * (end - start)))
    d = int8(b - a)
    return int8(a + int8(int(t * d)))


class Sim(object):
    def __init__(self, theme):
        self.theme = theme
        self.bg = tuple(cw.rgb565_to_rgb(theme.get("bgColor", 0)))
        self.sprites = []
        for entry in theme.get("loop", []):
            ref = int(entry.get("sprite", 0))
            imgs = []
            for fr in theme["sprites"][ref]:
                raw = base64.b64decode(fr["image"])
                imgs.append(Image.open(io.BytesIO(raw)).convert("RGB"))
            s = Sprite(entry.get("x", 0), entry.get("y", 0), imgs)
            s.cfg = entry
            self.sprites.append(s)

    def draw(self, s):
        # renderImage(x uint8, y uint8)；负坐标按 uint8 回绕 → 出屏不绘
        x = s.x & 0xFF
        y = s.y & 0xFF
        for yy in range(s.h):
            py = y + yy
            if py < 0 or py >= PANEL:
                continue
            for xx in range(s.w):
                # src 像素 (带黑底) 会覆盖屏幕
                px = x + xx
                if 0 <= px < PANEL:
                    self.pix[px, py] = s.images[s.frame].getpixel((xx, yy))

    def fill(self, x, y, w, h):
        for yy in range(y, y + h):
            if 0 <= yy < PANEL:
                for xx in range(x, x + w):
                    if 0 <= xx < PANEL:
                        self.pix[xx, yy] = self.bg

    def move(self, s, ms, second):
        c = s.cfg
        mst = int(c.get("moveStartTime", 0) or 0) or 1
        mdur = int(c.get("moveDuration", 0) or 0)
        mtx = int(c.get("moveTargetX", -1) or 0) if c.get("moveTargetX", -1) not in (None, -1) else -1
        mty = int(c.get("moveTargetY", -1) or 0) if c.get("moveTargetY", -1) not in (None, -1) else -1
        ret = bool(c.get("shouldReturnToOrigin", False))

        if s.moving:
            prog = (ms - s.move_start) / float(s.move_dur) if s.move_dur else 0
            ox, oy = s.x, s.y
            nx = lerp_i8(s.mi_x, s.mt_x, prog)
            ny = lerp_i8(s.mi_y, s.mt_y, prog)
            gx = min(ox, nx)
            gy = min(oy, ny)
            gw = s.w + max(ox, nx) - gx
            gh = s.h + max(oy, ny) - gy
            self.fill(gx, gy, gw, gh)
            if prog <= 1:
                s.x, s.y = nx, ny
            elif s.ret:
                s.x, s.y = s.mt_x, s.mt_y
                if not s.reversing:
                    # reverseMoving(mi_x, mi_y)
                    s.move_start = ms
                    s.mi_x, s.mi_y = s.x, s.y
                    s.mt_x, s.mt_y = c.get("_origin_x"), c.get("_origin_y")
                    s.ret = False
                    s.reversing = True
                    s.moving = True
            else:
                s.moving = False

        if (mdur > 0 and (mtx > -1 or mty > -1)) and (ms - s.last_reset_move >= mst):
            if (second * 1000) % mst == 0:
                s.last_reset_move = ms
                # startMoving(mtx, mty, mdur, ret)
                s.move_start = ms
                s.move_dur = mdur
                s.mi_x, s.mi_y = s.x, s.y
                c["_origin_x"], c["_origin_y"] = s.x, s.y
                s.mt_x, s.mt_y = mtx, mty
                s.ret = ret
                s.moving = True
                s.reversing = False

    def step(self, ms, second):
        for s in self.sprites:
            c = s.cfg
            fd = int(c.get("frameDelay", 0) or 0) or int(self.theme.get("delay", 300))
            ld = int(c.get("loopDelay", 0) or 0) or int(self.theme.get("delay", 300))
            if (ms - s.last_frames >= fd) and (s.count < s.total):
                s.inc()
                self.move(s, ms, second)
                self.draw(s)
                s.count += 1
                s.last_frames = ms
            if (ms - s.last_reset >= ld) and ((second * 1000) % ld == 0):
                s.count = 0
                s.last_reset = ms

    def frame_at(self, ms):
        self.img = Image.new("RGB", (PANEL, PANEL), self.bg)
        self.pix = self.img.load()
        self.__init_state = None
        # reset state
        for s in self.sprites:
            c = s.cfg
            s.x = int8(c.get("x", 0)); s.y = int8(c.get("y", 0))
            s.frame = 0; s.count = 0; s.last_frames = 0; s.last_reset = 0
            s.last_reset_move = 0; s.moving = False; s.reversing = False
            c.pop("_origin_x", None); c.pop("_origin_y", None)
        t = 0
        step = 5
        while t <= ms:
            self.step(t, int(t // 1000))
            t += step
        return self.img.copy()

    def _snapshot(self):
        im = Image.new("RGB", (PANEL, PANEL), self.bg)
        im.putdata([self.pix[x, y] for y in range(PANEL) for x in range(PANEL)])
        return im


def diff_pixels(a, b):
    ca, cb = a.load(), b.load()
    d = 0
    for y in range(PANEL):
        for x in range(PANEL):
            if ca[x, y] != cb[x, y]:
                d += 1
    return d


def main():
    theme = json.load(open(THEME, encoding="utf-8"))
    sim = Sim(theme)

    # 关键时刻：静止 / 去程中 / 到位 / 回程中
    picks = [0, 2450, 2900, 3350]
    print("固件仿真 vs 理想画 差异像素：")
    imgs = []
    for ms in picks:
        real = sim.frame_at(ms)
        ideal = cw.render_theme_animated(theme, ms)
        d = diff_pixels(real, ideal)
        print("  t=%5dms  差异=%3d px  %s" % (ms, d, "OK" if d < 40 else "偏大"))
        imgs.append((ms, real))

    gap = 8
    sheet = Image.new("RGB", (len(imgs) * PANEL * 3 + (len(imgs) - 1) * gap, PANEL * 3), (20, 20, 24))
    x = 0
    for ms, im in imgs:
        sheet.paste(im.resize((PANEL * 3, PANEL * 3), Image.NEAREST), (x, 0))
        x += PANEL * 3 + gap
    sheet.save(OUT)
    print("写出", OUT)


if __name__ == "__main__":
    main()
