#!/usr/bin/env python3
"""
把 adaptive 主题的绘制几何复刻成 PNG，用于烧录前的视觉核对。
几何参数与 firmware/lib/adaptive/Clockface.cpp 保持一致：
  正常模式: x=7  y=10  w=10 h=20 t=2 gap=3 colon=4   日期 y=52
  大数字模式: x=1  y=16  w=13 h=32 t=3 gap=3 colon=4
"""
import struct
import zlib

SEG_A, SEG_B, SEG_C, SEG_D, SEG_E, SEG_F, SEG_G = 1, 2, 4, 8, 16, 32, 64
DIGIT_SEG = [0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F]

COLOR_TIME = (255, 255, 255)
COLOR_DATE = (0, 200, 200)
BG = (6, 8, 12)


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [[BG for _ in range(w)] for _ in range(h)]

    def rect(self, x, y, w, h, c):
        for yy in range(int(y), int(y + h)):
            for xx in range(int(x), int(x + w)):
                if 0 <= xx < self.w and 0 <= yy < self.h:
                    self.px[yy][xx] = c

    def png(self, scale=8):
        W, H = self.w * scale, self.h * scale
        rows = []
        for y in range(H):
            row = bytearray([0])
            sy = y // scale
            for x in range(W):
                r, g, b = self.px[sy][x // scale]
                row += bytes((r, g, b))
            rows.append(bytes(row))
        raw = b"".join(rows)

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9))
                + chunk(b"IEND", b""))


def draw_digit(cv, x, y, w, h, t, digit, color):
    mask = DIGIT_SEG[digit % 10]
    half = (h - t) // 2
    vert = (h - t) // 2 - t
    if mask & SEG_A:
        cv.rect(x + t, y, w - 2 * t, t, color)
    if mask & SEG_G:
        cv.rect(x + t, y + half, w - 2 * t, t, color)
    if mask & SEG_D:
        cv.rect(x + t, y + h - t, w - 2 * t, t, color)
    if mask & SEG_F:
        cv.rect(x, y + t, t, vert, color)
    if mask & SEG_B:
        cv.rect(x + w - t, y + t, t, vert, color)
    if mask & SEG_E:
        cv.rect(x, y + (h + t) // 2, t, vert, color)
    if mask & SEG_C:
        cv.rect(x + w - t, y + (h + t) // 2, t, vert, color)


def draw_time(cv, x, y, w, h, t, gap, colon_w, hh, mm, color):
    draw_digit(cv, x, y, w, h, t, hh // 10, color)
    draw_digit(cv, x + w + gap, y, w, h, t, hh % 10, color)
    cx = x + 2 * (w + gap)
    dot = 2
    cv.rect(cx + (colon_w - dot) // 2, y + h // 3, dot, dot, color)
    cv.rect(cx + (colon_w - dot) // 2, y + 2 * h // 3 - dot, dot, dot, color)
    draw_digit(cv, cx + colon_w + gap, y, w, h, t, mm // 10, color)
    draw_digit(cv, cx + colon_w + gap + w + gap, y, w, h, t, mm % 10, color)


# ---- 正常模式 ----
normal = Canvas(64, 64)
draw_time(normal, 4, 15, 10, 20, 2, 3, 4, 16, 20, COLOR_TIME)
# 日期用 5px 高的占位字形（picopixel 实高 5）
date_y = 44
date_w = 18  # "10-28" 在 picopixel 下实测 18px
normal.rect((64 - date_w) // 2, date_y, date_w, 1, COLOR_DATE)
normal.rect((64 - date_w) // 2, date_y + 4, date_w, 1, COLOR_DATE)

# ---- 大数字模式 ----
big = Canvas(64, 64)
draw_time(big, 2, 16, 12, 32, 3, 2, 4, 16, 20, COLOR_TIME)

open("dist/preview-normal.png", "wb").write(normal.png(8))
open("dist/preview-big.png", "wb").write(big.png(8))
print("已生成 dist/preview-normal.png 与 dist/preview-big.png (各 512x512)")

# 顺带核对几何是否越界
def bounds(cv):
    xs = [x for y in range(64) for x in range(64) if cv.px[y][x] != BG]
    ys = [y for y in range(64) for x in range(64) if cv.px[y][x] != BG]
    return (min(xs), max(xs), min(ys), max(ys)) if xs else None

print("正常模式内容范围 x:%d-%d y:%d-%d" % bounds(normal))
print("大数字模式内容范围 x:%d-%d y:%d-%d" % bounds(big))
